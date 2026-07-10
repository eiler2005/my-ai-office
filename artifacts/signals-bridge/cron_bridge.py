#!/usr/bin/env python3
"""Signals bridge: internal scheduler + Redis consumers + compact last30days daily feed."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import redis as redis_lib
from dotenv import load_dotenv

from agentmail_api import AgentMailApiClient, AgentMailApiError
from config_store import get_ruleset, index_sources, load_config
from email_adapter import collect_email_candidates, resolve_email_window
from event_store import append_events, append_new_events, trim_old_events
from last30days_persistence import persist_last30days_digest
from last30days_runner import build_digest, write_signal_digest
from omniroute_client import prepare_signal_batch
from poster import (
    SUPERGROUP_ID,
    TOPIC_ID,
    copy_message,
    post_html_message,
    post_plain_text_message,
    render_batch,
    render_last30days_digest,
)
import state_store
from telegram_adapter import build_client as build_telethon_client
from telegram_adapter import collect_telegram_candidates

load_dotenv("/app/signals.env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] signals-bridge: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("signals-bridge")

PORT = int(os.environ.get("SIGNALS_BRIDGE_PORT", "8093"))
TOKEN = os.environ.get("SIGNALS_BRIDGE_TOKEN", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()

STATE_DIR = Path("/app/state")
SIGNALS_STATUS_PATH = STATE_DIR / "signals-bridge-status.json"
LAST30DAYS_STATUS_PATH = STATE_DIR / "last30days-status.json"

STREAM_JOBS = "ingest:jobs:signals"
STREAM_LAST30DAYS_JOBS = "ingest:jobs:last30days"
STREAM_DLQ = "dlq:failed"
CONSUMER_GROUP = "signals-workers"
CONSUMER_NAME = "signals-bridge-worker"
LAST30DAYS_CONSUMER_GROUP = "last30days-workers"
LAST30DAYS_CONSUMER_NAME = "signals-last30days-worker"
BLOCK_MS = 5000
REDIS_SOCKET_TIMEOUT_SECONDS = max(
    int(os.environ.get("REDIS_SOCKET_TIMEOUT_SECONDS", "30")),
    int(BLOCK_MS / 1000) + 5,
)


def _make_redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


def _recover_interrupted_ruleset_locks(r: redis_lib.Redis, config: dict) -> int:
    released = 0
    for ruleset in config.get("rule_sets", []):
        ruleset_id = str(ruleset.get("id") or "").strip()
        if not ruleset_id:
            continue
        if r.delete(state_store.lock_key("ruleset", ruleset_id)):
            released += 1
    if released:
        logger.warning("Released %s interrupted signals ruleset lock(s) on startup", released)
    return released


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _tail_union(*tails: list[str]) -> list[str]:
    lines: list[str] = []
    for tail in tails:
        lines.extend(tail)
    return lines[-18:]


def _render_email_delivery_text(event) -> str:
    text = str(event.delivery_text or event.source_excerpt or event.summary).strip()
    if not text:
        return ""
    return f"Письмо от {event.author}\n\n{text}"


def _render_telegram_delivery_text(event, text: str | None = None) -> str:
    body = str(text or event.delivery_text or event.source_excerpt or event.summary).strip()
    if not body:
        return ""
    lines = [f"Оригинал из Telegram · {event.author}", "", body]
    if event.source_link:
        lines.extend(["", f"Ссылка: {event.source_link}"])
    return "\n".join(lines).strip()


async def _relay_email_event(event) -> bool:
    body = _render_email_delivery_text(event)
    if not body:
        return False
    return await post_plain_text_message(body)


async def _relay_telegram_text_event(event, *, text: str | None = None) -> bool:
    body = _render_telegram_delivery_text(event, text=text)
    if not body:
        return False
    return await post_plain_text_message(body)


async def _forward_telegram_event_via_telethon(client, event) -> bool:
    from telethon import functions

    chat_id = int(event.source_chat_id or 0)
    message_id = int(event.source_message_id or 0)
    if not chat_id or not message_id:
        return False
    try:
        await client(
            functions.messages.ForwardMessagesRequest(
                from_peer=chat_id,
                id=[message_id],
                to_peer=SUPERGROUP_ID,
                top_msg_id=TOPIC_ID if TOPIC_ID > 0 else None,
            )
        )
    except Exception as exc:
        logger.warning(
            "Telethon forward fallback failed for telegram source %s:%s: %s",
            chat_id,
            message_id,
            exc,
        )
        return False
    return True


async def _resend_telegram_message_via_telethon(client, message) -> bool:
    try:
        await client.send_message(
            SUPERGROUP_ID,
            message,
            reply_to=TOPIC_ID if TOPIC_ID > 0 else None,
        )
    except Exception as exc:
        logger.warning(
            "Telethon resend fallback failed for telegram message %s: %s",
            getattr(message, "id", "unknown"),
            exc,
        )
        return False
    return True


async def _relay_telegram_event_via_telethon(event) -> bool:
    chat_id = int(event.source_chat_id or 0)
    message_id = int(event.source_message_id or 0)
    if not chat_id or not message_id:
        return await _relay_telegram_text_event(event)

    client = build_telethon_client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("signals telethon session is not authorized")

    try:
        if await _forward_telegram_event_via_telethon(client, event):
            return True

        message = await client.get_messages(chat_id, ids=message_id)
        if message is None:
            return await _relay_telegram_text_event(event)

        if await _resend_telegram_message_via_telethon(client, message):
            return True

        delivery_text = str(getattr(message, "message", "") or event.delivery_text or "").strip()
        return await _relay_telegram_text_event(event, text=delivery_text)
    finally:
        await client.disconnect()


async def _relay_telegram_event(event) -> bool:
    chat_id = int(event.source_chat_id or 0)
    message_id = int(event.source_message_id or 0)
    if chat_id and message_id and await copy_message(from_chat_id=chat_id, message_id=message_id):
        return True
    return await _relay_telegram_event_via_telethon(event)


async def _deliver_source_contexts(events: list) -> tuple[int, int]:
    delivered = 0
    attempted = 0
    for event in events:
        try:
            if event.source_type == "telegram":
                attempted += 1
                if await _relay_telegram_event(event):
                    delivered += 1
            elif event.source_type == "email":
                attempted += 1
                if await _relay_email_event(event):
                    delivered += 1
        except Exception as exc:
            logger.exception("Failed to relay original source content for %s: %s", event.event_id, exc)
    return delivered, attempted


def _load_status_file(path: Path) -> dict:
    if not path.exists():
        return {"ok": True, "running": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "running": False, "error": "status_unreadable"}


def _load_signals_status() -> dict:
    return _load_status_file(SIGNALS_STATUS_PATH)


def _load_last30days_status() -> dict:
    return _load_status_file(LAST30DAYS_STATUS_PATH)


def _write_status(path: Path, r: redis_lib.Redis | None, payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if r is not None:
        state_store.set_status(r, payload)


def _parse_lookback_minutes(data: dict[str, str]) -> int | None:
    raw = str(data.get("lookback_minutes", "")).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("invalid_lookback_minutes") from exc
    if value <= 0:
        raise RuntimeError("invalid_lookback_minutes")
    return min(value, 7 * 24 * 60)


def _poll_interval_seconds(config: dict, ruleset: dict) -> int:
    return int(ruleset.get("poll_interval_seconds") or config.get("default_poll_interval_seconds", 300) or 300)


def _event_retention_days(config: dict) -> int:
    return int(config.get("event_retention_days", 14) or 14)


def _last30days_enabled(config: dict) -> bool:
    env_value = os.environ.get("LAST30DAYS_ENABLED", "1").strip().lower()
    if env_value in {"0", "false", "no", "off"}:
        return False
    return bool(config.get("last30days", {}).get("enabled", False))


def _last30days_lock_ttl_seconds() -> int:
    return int(os.environ.get("LAST30DAYS_TIMEOUT_SECONDS", "420") or 420) + 120


def _dlq(r, *, run_id: str, error: str, payload: dict) -> None:
    try:
        r.xadd(
            STREAM_DLQ,
            {
                "run_id": run_id,
                "error": error[:500],
                "payload": json.dumps(payload, ensure_ascii=False)[:5000],
                "failed_at": _utc_now_iso(),
            },
        )
    except redis_lib.exceptions.RedisError:
        logger.exception("Failed to write signals error to DLQ")


class Handler(BaseHTTPRequestHandler):
    server_version = "signals-bridge/1.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            signals_status = _load_signals_status()
            last30days_status = _load_last30days_status()
            self._send(
                HTTPStatus.OK,
                {
                    "ok": bool(signals_status.get("ok", True) and last30days_status.get("ok", True)),
                    "service": "signals-bridge",
                    "running": bool(signals_status.get("running") or last30days_status.get("running")),
                    "last_ruleset_id": signals_status.get("ruleset_id"),
                    "last_started_at": signals_status.get("started_at"),
                    "last_finished_at": signals_status.get("finished_at"),
                    "last_posted_events": signals_status.get("posted_events", 0),
                    "last30days": {
                        "running": bool(last30days_status.get("running")),
                        "preset_id": last30days_status.get("preset_id"),
                        "last_generated_at": last30days_status.get("finished_at"),
                        "last_posted_themes": last30days_status.get("posted_themes", 0),
                        "topic_name": last30days_status.get("topic_name"),
                    },
                },
            )
            return
        if self.path == "/status":
            payload = _load_signals_status()
            payload["last30days"] = _load_last30days_status()
            self._send(HTTPStatus.OK, payload)
            return
        self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/trigger":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not TOKEN:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "missing_bridge_token"})
            return
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self._send(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        job_type = str(payload.get("job_type", "")).strip() or "signals"
        if job_type == "last30days_daily":
            self._enqueue_last30days(payload)
            return
        self._enqueue_signals(payload)

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: HTTPStatus, payload: dict) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _enqueue_signals(self, payload: dict) -> None:
        ruleset_id = str(payload.get("ruleset_id", "")).strip()
        source_id = str(payload.get("source_id", "")).strip()
        try:
            lookback_minutes = _parse_lookback_minutes({k: str(v) for k, v in payload.items()})
            config = load_config()
            get_ruleset(config, ruleset_id)
            if source_id:
                sources = index_sources(config)
                if not any(key[1] == source_id for key in sources):
                    raise KeyError(source_id)
        except KeyError:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unknown_ruleset_or_source"})
            return
        except RuntimeError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_config", "detail": str(exc)})
            return

        run_id = str(uuid.uuid4())
        try:
            r = _make_redis()
            r.xadd(
                STREAM_JOBS,
                {
                    "run_id": run_id,
                    "ruleset_id": ruleset_id,
                    "source_id": source_id,
                    "lookback_minutes": str(lookback_minutes or ""),
                    "requested_at": _utc_now_iso(),
                    "requested_by": "manual",
                },
            )
        except redis_lib.exceptions.RedisError as exc:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "bus_unavailable", "detail": str(exc)})
            return

        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "job_type": "signals",
                "run_id": run_id,
                "ruleset_id": ruleset_id,
                "source_id": source_id or None,
                "lookback_minutes": lookback_minutes,
            },
        )

    def _enqueue_last30days(self, payload: dict) -> None:
        try:
            config = load_config()
            if not _last30days_enabled(config):
                raise RuntimeError("last30days_disabled")
            preset_id = str(payload.get("preset_id") or config.get("last30days", {}).get("preset_id") or "").strip()
            if not preset_id:
                raise RuntimeError("missing_preset_id")
        except RuntimeError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_config", "detail": str(exc)})
            return

        run_id = str(uuid.uuid4())
        try:
            r = _make_redis()
            r.xadd(
                STREAM_LAST30DAYS_JOBS,
                {
                    "run_id": run_id,
                    "job_type": "last30days_daily",
                    "preset_id": preset_id,
                    "requested_at": _utc_now_iso(),
                    "requested_by": "manual",
                },
            )
        except redis_lib.exceptions.RedisError as exc:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "bus_unavailable", "detail": str(exc)})
            return

        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "job_type": "last30days_daily",
                "run_id": run_id,
                "preset_id": preset_id,
            },
        )


def _scheduler_loop() -> None:
    r = _make_redis()
    while True:
        try:
            config = load_config()
            now = _utc_now()
            for ruleset in config.get("rule_sets", []):
                if not ruleset.get("enabled", True):
                    continue
                ruleset_id = str(ruleset["id"])
                next_due_key = state_store.ruleset_next_due_key(ruleset_id)
                next_due = state_store.get_dt(r, next_due_key)
                if next_due is None:
                    next_due = now
                if next_due <= now:
                    run_id = str(uuid.uuid4())
                    r.xadd(
                        STREAM_JOBS,
                        {
                            "run_id": run_id,
                            "ruleset_id": ruleset_id,
                            "source_id": "",
                            "lookback_minutes": "",
                            "requested_at": now.isoformat(),
                            "requested_by": "scheduler",
                        },
                    )
                    state_store.set_dt(
                        r,
                        next_due_key,
                        now + timedelta(seconds=_poll_interval_seconds(config, ruleset)),
                    )
                    logger.info("Scheduled signals job ruleset=%s run_id=%s", ruleset_id, run_id)
            tick = int(config.get("scheduler", {}).get("tick_seconds", 300) or 300)
            time.sleep(max(tick, 30))
        except Exception:
            logger.exception("signals scheduler loop failed")
            time.sleep(60)


def _cleanup_loop() -> None:
    r = _make_redis()
    while True:
        try:
            config = load_config()
            deleted = trim_old_events(r, retention_days=_event_retention_days(config))
            if deleted:
                logger.info("Trimmed %s old signals events", deleted)
            interval = int(config.get("scheduler", {}).get("cleanup_interval_seconds", 3600) or 3600)
            time.sleep(max(interval, 300))
        except Exception:
            logger.exception("signals cleanup loop failed")
            time.sleep(600)


def _signals_consumer_loop() -> None:
    while True:
        r = _make_redis()
        try:
            _signals_consumer_loop_inner(r)
        except redis_lib.exceptions.RedisError:
            logger.exception("signals consumer lost redis connection")
            time.sleep(3)


def _signals_consumer_loop_inner(r) -> None:
    try:
        r.xgroup_create(STREAM_JOBS, CONSUMER_GROUP, id="0", mkstream=True)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    while True:
        messages = r.xreadgroup(
            CONSUMER_GROUP,
            CONSUMER_NAME,
            {STREAM_JOBS: ">"},
            block=BLOCK_MS,
            count=1,
        )
        if not messages:
            continue
        _, entries = messages[0]
        msg_id, data = entries[0]
        run_id = data.get("run_id", msg_id)
        ruleset_id = data.get("ruleset_id", "")
        logger.info("Processing signals run_id=%s ruleset=%s", run_id, ruleset_id)
        try:
            result = _process_signals_job(r, data)
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)
            logger.info(
                "Signals run finished run_id=%s ruleset=%s posted=%s",
                run_id,
                ruleset_id,
                result.get("posted_events", 0),
            )
        except Exception as exc:
            logger.exception("signals job failed run_id=%s", run_id)
            _dlq(r, run_id=run_id, error=str(exc), payload=data)
            _write_status(
                SIGNALS_STATUS_PATH,
                r,
                {
                    "ok": False,
                    "running": False,
                    "ruleset_id": ruleset_id,
                    "run_id": run_id,
                    "started_at": None,
                    "finished_at": _utc_now_iso(),
                    "posted_events": 0,
                    "tail": [str(exc)],
                },
            )
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)


def _last30days_consumer_loop() -> None:
    while True:
        r = _make_redis()
        try:
            _last30days_consumer_loop_inner(r)
        except redis_lib.exceptions.RedisError:
            logger.exception("last30days consumer lost redis connection")
            time.sleep(3)


def _last30days_consumer_loop_inner(r) -> None:
    try:
        r.xgroup_create(STREAM_LAST30DAYS_JOBS, LAST30DAYS_CONSUMER_GROUP, id="0", mkstream=True)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    while True:
        messages = r.xreadgroup(
            LAST30DAYS_CONSUMER_GROUP,
            LAST30DAYS_CONSUMER_NAME,
            {STREAM_LAST30DAYS_JOBS: ">"},
            block=BLOCK_MS,
            count=1,
        )
        if not messages:
            continue
        _, entries = messages[0]
        msg_id, data = entries[0]
        run_id = data.get("run_id", msg_id)
        preset_id = data.get("preset_id", "")
        logger.info("Processing last30days run_id=%s preset=%s", run_id, preset_id)
        try:
            result = _process_last30days_job(r, data)
            r.xack(STREAM_LAST30DAYS_JOBS, LAST30DAYS_CONSUMER_GROUP, msg_id)
            logger.info(
                "Last30Days run finished run_id=%s preset=%s themes=%s",
                run_id,
                preset_id,
                result.get("posted_themes", 0),
            )
        except Exception as exc:
            logger.exception("last30days job failed run_id=%s", run_id)
            _dlq(r, run_id=run_id, error=str(exc), payload=data)
            _write_status(
                LAST30DAYS_STATUS_PATH,
                r,
                {
                    "ok": False,
                    "running": False,
                    "preset_id": preset_id,
                    "run_id": run_id,
                    "started_at": None,
                    "finished_at": _utc_now_iso(),
                    "posted_themes": 0,
                    "tail": [str(exc)],
                },
            )
            r.xack(STREAM_LAST30DAYS_JOBS, LAST30DAYS_CONSUMER_GROUP, msg_id)


def _process_signals_job(r, data: dict[str, str]) -> dict:
    config = load_config()
    ruleset = get_ruleset(config, str(data.get("ruleset_id", "")).strip())
    lookback_minutes = _parse_lookback_minutes(data)
    source_filter = str(data.get("source_id", "")).strip()
    run_id = str(data.get("run_id", "")).strip() or str(uuid.uuid4())
    topic_name = str(config.get("delivery", {}).get("topic_name", "signals"))
    now = _utc_now()

    holder = run_id
    job_lock = state_store.lock_key("ruleset", ruleset["id"])
    if not state_store.acquire_lock(r, job_lock, holder, ttl_seconds=600):
        raise RuntimeError(f"signals ruleset is already running: {ruleset['id']}")

    started_at = _utc_now_iso()
    _write_status(
        SIGNALS_STATUS_PATH,
        r,
        {
            "ok": True,
            "running": True,
            "ruleset_id": ruleset["id"],
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": None,
            "posted_events": 0,
            "tail": [],
            "omniroute_model": os.environ.get("OMNIROUTE_MODEL", "light"),
            "scheduler_tick_seconds": int(config.get("scheduler", {}).get("tick_seconds", 300) or 300),
        },
    )

    try:
        source_index = index_sources(config)
        candidates = []
        tails: list[list[str]] = []
        source_errors: list[str] = []
        for source_type, rules in _rules_by_source(ruleset).items():
            for source_id, source_rules in rules.items():
                if source_filter and source_id != source_filter:
                    continue
                source = source_index[(source_type, source_id)]
                if not source.get("enabled", True):
                    continue
                try:
                    if source_type == "email":
                        source_candidates, tail = _run_email_source(
                            r=r,
                            source=source,
                            ruleset=ruleset,
                            rules=source_rules,
                            lookback_minutes=lookback_minutes,
                            now=now,
                        )
                    elif source_type == "telegram":
                        source_candidates, tail = _run_telegram_source(
                            r=r,
                            source=source,
                            ruleset=ruleset,
                            rules=source_rules,
                            lookback_minutes=lookback_minutes,
                            now=now,
                        )
                    elif source_type == "web":
                        if source.get("enabled"):
                            raise RuntimeError(f"web source not implemented yet: {source_id}")
                        continue
                    else:
                        continue
                    candidates.extend(source_candidates)
                    tails.append(tail)
                except Exception as exc:
                    source_errors.append(f"{source_id}: {exc}")
                    tails.append([f"source_error {source_id}: {exc}"])
                    _dlq(
                        r,
                        run_id=run_id,
                        error=f"source {source_id} failed: {exc}",
                        payload={"ruleset_id": ruleset["id"], "source_id": source_id},
                    )

        prepared = prepare_signal_batch(
            ruleset_title=str(ruleset.get("title", ruleset["id"])),
            topic_name=topic_name,
            candidates=candidates,
        )
        _, fresh_events, duplicate_events = append_new_events(
            r,
            prepared.events,
            retention_days=_event_retention_days(config),
        )
        posted = False
        relayed_originals = 0
        relay_attempts = 0
        if fresh_events:
            body = render_batch(
                ruleset_title=str(ruleset.get("title", ruleset["id"])),
                events=fresh_events,
                model_meta=prepared.model_meta,
            )
            posted = asyncio.run(post_html_message(body))
            if posted:
                relayed_originals, relay_attempts = asyncio.run(_deliver_source_contexts(fresh_events))
        finished_at = _utc_now_iso()
        state_store.set_dt(r, state_store.ruleset_last_success_key(ruleset["id"]), now)
        status = {
            "ok": len(source_errors) == 0,
            "running": False,
            "ruleset_id": ruleset["id"],
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "posted_events": len(fresh_events) if posted else 0,
            "tail": _tail_union(
                *tails,
                [
                    f"dropped={len(prepared.dropped_external_refs)}",
                    f"deduped={len(duplicate_events)}",
                    f"relayed_originals={relayed_originals}/{relay_attempts}",
                ],
                source_errors,
            ),
            "omniroute_model": os.environ.get("OMNIROUTE_MODEL", "light"),
            "scheduler_tick_seconds": int(config.get("scheduler", {}).get("tick_seconds", 300) or 300),
        }
        _write_status(SIGNALS_STATUS_PATH, r, status)
        return status
    finally:
        state_store.release_lock(r, job_lock, holder)


def _process_last30days_job(r, data: dict[str, str]) -> dict:
    config = load_config()
    if not _last30days_enabled(config):
        raise RuntimeError("last30days_disabled")
    preset_id = str(data.get("preset_id") or config.get("last30days", {}).get("preset_id") or "").strip()
    run_id = str(data.get("run_id", "")).strip() or str(uuid.uuid4())

    holder = run_id
    job_lock = state_store.lock_key("last30days", preset_id)
    if not state_store.acquire_lock(r, job_lock, holder, ttl_seconds=_last30days_lock_ttl_seconds()):
        raise RuntimeError(f"last30days preset is already running: {preset_id}")

    started_at = _utc_now_iso()
    _write_status(
        LAST30DAYS_STATUS_PATH,
        r,
        {
            "ok": True,
            "running": True,
            "preset_id": preset_id,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": None,
            "posted_themes": 0,
            "tail": [],
        },
    )

    try:
        digest = build_digest(config, preset_id=preset_id)
        paths = persist_last30days_digest(digest, config=config)
        digest.persisted_paths = paths

        post_ok = True
        post_tail: list[str] = []
        if digest.topic_id > 0:
            body = render_last30days_digest(digest)
            post_ok = asyncio.run(post_html_message(body, topic_id=digest.topic_id))
            if not post_ok:
                post_tail.append("telegram_post_failed")
            else:
                try:
                    signal_digest_path = write_signal_digest(digest)
                    paths["obsidian_signal_digest_md"] = str(signal_digest_path)
                except Exception as exc:
                    post_tail.append(f"signal_digest_write_failed:{exc.__class__.__name__}")
        else:
            post_tail.append("telegram_topic_id_missing")

        finished_at = _utc_now_iso()
        state_store.set_dt(r, state_store.last30days_last_success_key(preset_id), _utc_now())
        status = {
            "ok": digest.status != "failed" and post_ok,
            "running": False,
            "preset_id": preset_id,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "posted_themes": len(digest.themes) if post_ok else 0,
            "total_themes": len(digest.themes),
            "successful_queries": digest.successful_queries,
            "total_queries": digest.total_queries,
            "topic_name": digest.topic_name,
            "topic_id": digest.topic_id,
            "source_counts": digest.source_counts,
            "errors_by_source": digest.errors_by_source,
            "query_errors": digest.query_errors,
            "persisted_paths": paths,
            "tail": _tail_union(digest.notes, post_tail),
        }
        _write_status(LAST30DAYS_STATUS_PATH, r, status)
        return status
    finally:
        state_store.release_lock(r, job_lock, holder)


def _rules_by_source(ruleset: dict) -> dict[str, dict[str, list[dict]]]:
    result: dict[str, dict[str, list[dict]]] = {}
    for rule in ruleset.get("rules", []):
        if not rule.get("enabled", True):
            continue
        result.setdefault(rule["source_type"], {}).setdefault(rule["source_id"], []).append(rule)
    return result


def _run_email_source(*, r, source: dict, ruleset: dict, rules: list[dict], lookback_minutes: int | None, now: datetime) -> tuple[list, list[str]]:
    try:
        api = AgentMailApiClient.from_env()
    except AgentMailApiError as exc:
        raise RuntimeError(str(exc)) from exc
    last_success = state_store.get_dt(r, state_store.source_last_success_key(source["id"]))
    since_dt, until_dt = resolve_email_window(source=source, last_success=last_success, lookback_minutes=lookback_minutes, now=now)
    candidates, tail = collect_email_candidates(
        api=api,
        source=source,
        ruleset_id=str(ruleset["id"]),
        ruleset_title=str(ruleset.get("title", ruleset["id"])),
        rules=rules,
        since_dt=since_dt,
        until_dt=until_dt,
    )
    state_store.set_dt(r, state_store.source_last_success_key(source["id"]), now)
    return candidates, tail


def _run_telegram_source(*, r, source: dict, ruleset: dict, rules: list[dict], lookback_minutes: int | None, now: datetime) -> tuple[list, list[str]]:
    cursor = state_store.get_int(r, state_store.source_cursor_key(source["id"]), 0)
    last_success = state_store.get_dt(r, state_store.source_last_success_key(source["id"]))

    async def _inner() -> tuple[list, list[str], int]:
        client = build_telethon_client()
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("signals telethon session is not authorized")
        try:
            return await collect_telegram_candidates(
                client=client,
                source=source,
                ruleset_id=str(ruleset["id"]),
                ruleset_title=str(ruleset.get("title", ruleset["id"])),
                rules=rules,
                cursor=cursor,
                last_success=last_success,
                lookback_minutes=lookback_minutes,
                now=now,
            )
        finally:
            await client.disconnect()

    candidates, tail, max_seen_id = asyncio.run(_inner())
    if max_seen_id > cursor:
        state_store.set_int(r, state_store.source_cursor_key(source["id"]), max_seen_id)
    state_store.set_dt(r, state_store.source_last_success_key(source["id"]), now)
    return candidates, tail


def main() -> None:
    if not REDIS_URL:
        raise SystemExit("REDIS_URL is required")
    if not TOKEN:
        raise SystemExit("SIGNALS_BRIDGE_TOKEN is required")
    config = load_config()
    _recover_interrupted_ruleset_locks(_make_redis(), config)
    logger.info(
        "Starting signals-bridge on :%s with 5m scheduler tick=%s and OmniRoute model=%s (last30days=%s)",
        PORT,
        config.get("scheduler", {}).get("tick_seconds", 300),
        os.environ.get("OMNIROUTE_MODEL", "light"),
        _last30days_enabled(config),
    )
    threading.Thread(target=_scheduler_loop, daemon=True, name="signals-scheduler").start()
    threading.Thread(target=_signals_consumer_loop, daemon=True, name="signals-consumer").start()
    threading.Thread(target=_last30days_consumer_loop, daemon=True, name="last30days-consumer").start()
    threading.Thread(target=_cleanup_loop, daemon=True, name="signals-cleanup").start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
