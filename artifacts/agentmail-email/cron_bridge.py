#!/usr/bin/env python3
"""AgentMail inbox-email bridge + Redis Streams consumer."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import redis as redis_lib
from dotenv import load_dotenv

from agentmail_api import AgentMailApiClient, AgentMailApiError
from agent_runner import AgentRunError, run_agent_json
from event_store import append_events, trim_old_events
from models import ModelMeta, PollPrepResult
from poster import post_html_message, render_mailbox_digest
from prompts import build_prepare_poll_analysis_prompt
import state_store

load_dotenv("/app/email.env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] agentmail-email: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("agentmail-email")

PORT = int(os.environ.get("EMAIL_BRIDGE_PORT", "8092"))
TOKEN = os.environ.get("EMAIL_BRIDGE_TOKEN", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
STATE_DIR = Path(os.environ.get("EMAIL_STATE_DIR", "/app/state"))
STATUS_PATH = Path(os.environ.get("EMAIL_STATUS_PATH", str(STATE_DIR / "email-bridge-status.json")))

STREAM_JOBS = os.environ.get("EMAIL_STREAM_JOBS", "ingest:jobs:email").strip() or "ingest:jobs:email"
STREAM_DLQ = os.environ.get("EMAIL_STREAM_DLQ", "dlq:failed").strip() or "dlq:failed"
CONSUMER_GROUP = os.environ.get("EMAIL_CONSUMER_GROUP", "email-workers").strip() or "email-workers"
CONSUMER_NAME = os.environ.get("EMAIL_CONSUMER_NAME", "agentmail-email-worker").strip() or "agentmail-email-worker"
DLQ_SOURCE = os.environ.get("EMAIL_DLQ_SOURCE", "email").strip() or "email"
BLOCK_MS = 5000

VALID_JOB_TYPES = {"poll", "digest"}
VALID_DIGEST_TYPES = {"morning", "interval", "editorial"}
MAX_MESSAGE_PAGES = int(os.environ.get("AGENTMAIL_MAX_MESSAGE_PAGES", "5") or 5)
MAX_MESSAGE_PAGE_SIZE = int(os.environ.get("AGENTMAIL_MESSAGE_PAGE_SIZE", "100") or 100)
TEXT_EXCERPT_LIMIT = int(os.environ.get("AGENTMAIL_TEXT_EXCERPT_LIMIT", "2400") or 2400)
PREVIEW_LIMIT = int(os.environ.get("AGENTMAIL_PREVIEW_LIMIT", "420") or 420)
MAX_LLM_CANDIDATE_THREADS = int(os.environ.get("AGENTMAIL_MAX_LLM_CANDIDATE_THREADS", "10") or 10)
MAX_LLM_MESSAGES_PER_THREAD = int(os.environ.get("AGENTMAIL_MAX_LLM_MESSAGES_PER_THREAD", "3") or 3)
MAX_LLM_TEXT_EXCERPT_CHARS = int(os.environ.get("AGENTMAIL_MAX_LLM_TEXT_EXCERPT_CHARS", "700") or 700)
MAX_LLM_PROMPT_CHARS = int(os.environ.get("AGENTMAIL_MAX_LLM_PROMPT_CHARS", "60000") or 60000)
SENDER_RE = re.compile(r"^\s*(?:(?P<name>.*?)\s*)?<(?P<email>[^>]+)>\s*$")
REPLY_SUBJECT_RE = re.compile(r"^\s*(?:re|fw|fwd)\s*:", re.IGNORECASE)
FORWARDED_SENDER_LINE_RE = re.compile(r"(?im)^(?:from|от)\s*:\s*(?P<value>.+?)\s*$")
FORWARDED_HEADER_MARKERS = (
    "from:",
    "sent:",
    "to:",
    "subject:",
    "от:",
    "отправлено:",
    "кому:",
    "тема:",
)
ACTION_KEYWORDS = (
    "reply",
    "respond",
    "response needed",
    "deadline",
    "meeting",
    "calendar",
    "call",
    "approve",
    "approval",
    "action required",
    "asap",
    "urgent",
    "invoice",
    "payment due",
    "review requested",
)


def load_config() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    inbox_ref = os.environ.get("AGENTMAIL_INBOX_REF", "").strip()
    if inbox_ref:
        data["inbox_ref"] = inbox_ref
    scheduler = data.setdefault("scheduler", {})
    scheduler.setdefault("enabled", True)
    scheduler.setdefault("tick_seconds", int(data.get("poll_interval_minutes", 5) or 5) * 60)
    if "schedule_slots" not in data:
        hours = [int(value) for value in data.get("schedule_hours", [8, 13, 16, 20])]
        data["schedule_slots"] = [f"{hour:02d}:00" for hour in hours]
    return data


def _make_redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=(BLOCK_MS / 1000) + 10,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_status() -> dict:
    if not STATUS_PATH.exists():
        return {"ok": True, "running": False}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "running": False, "error": "status_unreadable"}


def _write_status(r: redis_lib.Redis | None, payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if r is not None:
        state_store.set_status(r, payload)


def _normalize_status_on_startup() -> None:
    status = _load_status()
    if not status.get("running"):
        return

    payload = dict(status)
    payload["running"] = False
    payload["finished_at"] = payload.get("finished_at") or _utc_now()
    tail = [str(line) for line in (payload.get("tail") or []) if str(line).strip()]
    tail.append("bridge restart cleared stale running status")
    payload["tail"] = tail[-12:]

    redis_client = None
    if REDIS_URL:
        try:
            redis_client = _make_redis()
            redis_client.ping()
        except redis_lib.exceptions.RedisError:
            redis_client = None
    _write_status(redis_client, payload)


def _clear_stale_locks_on_startup() -> None:
    if not REDIS_URL:
        return

    config = load_config()
    inbox_ref = str(config.get("inbox_ref", "")).strip()
    if not inbox_ref:
        return

    try:
        redis_client = _make_redis()
        redis_client.ping()
        removed = 0
        for job_type in ("poll", "digest"):
            removed += int(redis_client.delete(state_store.lock_key(inbox_ref, job_type)) or 0)
        if removed:
            logger.info("Cleared %s stale email lock(s) on startup", removed)
    except redis_lib.exceptions.RedisError as exc:
        logger.warning("Failed to clear stale email locks on startup: %s", exc)


def _tail_union(*tails: list[str]) -> list[str]:
    lines: list[str] = []
    for tail in tails:
        lines.extend(tail)
    return lines[-16:]


def _fallback_poll_result(
    *,
    run_id: str,
    inbox_ref: str,
    topic_name: str,
    scanned_count: int,
    thread_count: int,
    prefilter_actions: dict[str, list[str]],
    prefilter_low_signal_count: int,
    prefilter_stats: dict[str, int],
) -> PollPrepResult:
    result = _empty_poll_result(run_id=run_id, inbox_ref=inbox_ref, topic_name=topic_name)
    result.messages_scanned = scanned_count
    result.threads_considered = thread_count
    result.low_signal_count = prefilter_low_signal_count
    result.label_actions = prefilter_actions
    result.prefilter_scanned_threads = prefilter_stats.get("scanned_threads", 0)
    result.prefilter_skipped_handled = prefilter_stats.get("skipped_handled", 0)
    result.prefilter_skipped_low_signal = prefilter_stats.get("skipped_low_signal", 0)
    result.prefilter_candidate_threads = prefilter_stats.get("candidate_threads", 0)
    result.llm_skipped = True
    return result


def _compact_candidate_threads_for_llm(candidate_threads: list[dict]) -> tuple[list[dict], list[str]]:
    limited_threads = max(1, MAX_LLM_CANDIDATE_THREADS)
    limited_messages = max(1, MAX_LLM_MESSAGES_PER_THREAD)
    limited_excerpt = max(120, MAX_LLM_TEXT_EXCERPT_CHARS)
    compacted: list[dict] = []
    total_messages_before = 0
    total_messages_after = 0

    for thread in candidate_threads[:limited_threads]:
        current = dict(thread)
        messages = list(current.get("messages", []) or [])
        total_messages_before += len(messages)
        current["messages"] = [
            {
                **dict(message),
                "preview": _truncate(str(message.get("preview") or ""), min(PREVIEW_LIMIT, 240)),
                "text_excerpt": _truncate(str(message.get("text_excerpt") or ""), limited_excerpt),
            }
            for message in messages[:limited_messages]
        ]
        current["thread_preview"] = _truncate(str(current.get("thread_preview") or ""), 240)
        current["window_message_ids"] = [
            str(value)
            for value in (current.get("window_message_ids") or [])
            if str(value).strip()
        ][:limited_messages]
        total_messages_after += len(current["messages"])
        compacted.append(current)

    omitted_threads = max(0, len(candidate_threads) - len(compacted))
    omitted_messages = max(0, total_messages_before - total_messages_after)
    notes = [
        (
            "llm input compacted: "
            f"threads={len(compacted)}/{len(candidate_threads)}, "
            f"messages={total_messages_after}/{total_messages_before}, "
            f"excerpt_limit={limited_excerpt}"
        )
    ]
    if omitted_threads or omitted_messages:
        notes.append(f"llm input omitted: threads={omitted_threads}, messages={omitted_messages}")
    return compacted, notes


def _build_bounded_poll_prompt(
    *,
    inbox_ref: str,
    topic_name: str,
    since_dt: datetime,
    until_dt: datetime,
    labels: dict[str, str],
    low_signal_hints: list[str],
    candidate_threads: list[dict],
    mode: str,
) -> tuple[str, list[str]]:
    current_threads, notes = _compact_candidate_threads_for_llm(candidate_threads)
    while True:
        prompt = build_prepare_poll_analysis_prompt(
            inbox_ref=inbox_ref,
            topic_name=topic_name,
            since_iso=since_dt.isoformat(),
            until_iso=until_dt.isoformat(),
            labels=labels,
            low_signal_hints=low_signal_hints,
            thread_snapshots=current_threads,
            mode=mode,
        )
        if len(prompt) <= MAX_LLM_PROMPT_CHARS or len(current_threads) <= 1:
            break
        current_threads = current_threads[: max(1, len(current_threads) // 2)]
        notes.append(f"llm prompt trimmed to {len(current_threads)} thread(s) to fit {MAX_LLM_PROMPT_CHARS} chars")
    notes.append(f"llm prompt size: {len(prompt)} chars")
    return prompt, notes


def _event_retention_days(config: dict) -> int:
    return int(config.get("event_retention_days", 7) or 7)


def _as_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _scheduler_enabled(config: dict) -> bool:
    return _as_bool((config.get("scheduler") or {}).get("enabled"), True)


def _poll_llm_enabled(config: dict) -> bool:
    raw = config.get("poll_llm_enabled")
    if raw is None:
        raw = os.environ.get("AGENTMAIL_POLL_LLM_ENABLED")
    return _as_bool(raw, False)


def _scheduler_tick_seconds(config: dict) -> int:
    scheduler = config.get("scheduler") or {}
    raw = scheduler.get("tick_seconds", int(config.get("poll_interval_minutes", 5) or 5) * 60)
    try:
        tick = int(raw or 300)
    except (TypeError, ValueError):
        tick = 300
    return max(tick, 30)


def _schedule_slots(config: dict) -> list[tuple[int, int]]:
    raw_slots = list(config.get("schedule_slots", []) or [])
    if not raw_slots:
        raw_slots = [f"{int(value):02d}:00" for value in config.get("schedule_hours", [8, 13, 16, 20])]

    slots: list[tuple[int, int]] = []
    for raw in raw_slots:
        value = str(raw).strip()
        if not value:
            continue
        hour_s, minute_s = (value.split(":", 1) + ["00"])[:2]
        hour = max(0, min(23, int(hour_s)))
        minute = max(0, min(59, int(minute_s)))
        slots.append((hour, minute))

    slots = sorted(set(slots))
    if not slots:
        slots = [(8, 0), (13, 0), (16, 0), (20, 0)]
    return slots


def _parse_lookback_minutes(data: dict[str, str]) -> int | None:
    raw = str(data.get("lookback_minutes", "")).strip()
    if not raw:
        hint = str(data.get("window_hint", "")).strip()
        if hint.isdigit():
            raw = hint
        elif hint.lower().startswith("lookback:"):
            raw = hint.split(":", 1)[1].strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError("invalid_lookback_minutes")
    if value <= 0:
        raise RuntimeError("invalid_lookback_minutes")
    return min(value, 7 * 24 * 60)


def _labels(config: dict) -> dict[str, str]:
    current = config.get("labels", {}) or {}
    return {
        "polled": str(current.get("polled", "benka/polled")),
        "low_signal": str(current.get("low_signal", "benka/low-signal")),
        "digested": str(current.get("digested", "benka/digested")),
    }


def _api_client() -> AgentMailApiClient:
    return AgentMailApiClient.from_env()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _in_window(value: str | None, since_dt: datetime, until_dt: datetime) -> bool:
    dt = _parse_dt(value)
    if dt is None:
        return False
    return since_dt <= dt <= until_dt


def _truncate(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _parse_sender(raw: str | None) -> tuple[str, str, str]:
    value = (raw or "").strip()
    if not value:
        return "", "", ""
    match = SENDER_RE.match(value)
    if match:
        name = match.group("name") or ""
        email = match.group("email") or ""
    elif "@" in value and " " not in value:
        name, email = "", value
    else:
        name, email = value, ""
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    return name.strip().strip('"'), email.strip(), domain


def _forwarded_sender_lookup_enabled(config: dict) -> bool:
    return _as_bool(config.get("resolve_forwarded_sender"), False)


def _extract_forwarded_sender(message: dict) -> tuple[str, str, str]:
    text = "\n".join(
        str(message.get(key) or "").strip()
        for key in ("text_excerpt", "from_raw", "preview")
        if str(message.get(key) or "").strip()
    ).strip()
    if not text:
        return "", "", ""

    lowered = text.lower()
    marker_hits = sum(1 for marker in FORWARDED_HEADER_MARKERS if marker in lowered)
    if marker_hits < 2:
        return "", "", ""

    match = FORWARDED_SENDER_LINE_RE.search(text)
    if not match:
        return "", "", ""

    return _parse_sender(match.group("value"))


def _message_attachment_count(message: dict) -> int:
    attachments = message.get("attachments") or []
    return len(attachments) if isinstance(attachments, list) else 0


def _empty_poll_result(*, run_id: str, inbox_ref: str, topic_name: str) -> PollPrepResult:
    _ = (run_id, inbox_ref, topic_name)
    return PollPrepResult(
        messages_scanned=0,
        threads_considered=0,
        threads_selected=0,
        low_signal_count=0,
        batch_lead=[],
        publish_events=[],
        label_actions={},
        model_meta=ModelMeta(
            model_id="agentmail-direct",
            tier="primary",
            model_label="без LLM",
            complexity="template",
            memory_mode="mailbox-window",
        ),
    )


def _low_signal_hints(config: dict) -> list[str]:
    return [str(item).strip().lower() for item in config.get("low_signal_hints", []) if str(item).strip()]


def _looks_low_signal_message(message: dict, *, config: dict) -> bool:
    low_signal_label = _labels(config)["low_signal"]
    labels = {str(value).strip() for value in (message.get("labels") or []) if str(value).strip()}
    if low_signal_label in labels:
        return True

    haystack = " ".join(
        [
            str(message.get("subject") or ""),
            str(message.get("preview") or ""),
            str(message.get("text_excerpt") or ""),
            str(message.get("from_name") or ""),
            str(message.get("from_email") or ""),
            str(message.get("sender_domain") or ""),
        ]
    ).lower()
    return any(token in haystack for token in _low_signal_hints(config))


def _collect_thread_snapshots(
    *,
    inbox_ref: str,
    since_dt: datetime,
    until_dt: datetime,
) -> tuple[int, list[dict]]:
    api = _api_client()
    page_token: str | None = None
    scanned_messages: list[dict] = []
    pages = 0
    while pages < MAX_MESSAGE_PAGES:
        pages += 1
        page = api.list_messages(
            inbox_ref,
            limit=MAX_MESSAGE_PAGE_SIZE,
            page_token=page_token,
            after=since_dt,
            before=until_dt,
        )
        messages = list(page.get("messages", []) or [])
        scanned_messages.extend(messages)
        page_token = page.get("next_page_token")
        if not page_token or not messages:
            break

    thread_ids: list[str] = []
    seen_threads: set[str] = set()
    for message in scanned_messages:
        thread_id = str(message.get("thread_id", "")).strip()
        if thread_id and thread_id not in seen_threads:
            seen_threads.add(thread_id)
            thread_ids.append(thread_id)

    snapshots: list[dict] = []
    for thread_id in thread_ids:
        try:
            thread = api.get_thread(inbox_ref, thread_id)
        except AgentMailApiError as exc:
            logger.warning("Skipping AgentMail thread after API error thread_id=%s: %s", thread_id, exc)
            continue
        all_messages = list(thread.get("messages", []) or [])
        window_messages = [msg for msg in all_messages if _in_window(msg.get("timestamp"), since_dt, until_dt)]
        if not window_messages:
            continue
        ordered = sorted(window_messages, key=lambda item: item.get("timestamp", ""), reverse=True)
        latest = ordered[0]
        latest_name, latest_email, latest_domain = _parse_sender(latest.get("from"))
        snapshots.append(
            {
                "thread_id": thread_id,
                "subject": str(thread.get("subject") or latest.get("subject") or "(no subject)"),
                "thread_labels": [str(v) for v in (thread.get("labels") or []) if str(v).strip()],
                "thread_preview": _truncate(str(thread.get("preview") or latest.get("preview") or ""), PREVIEW_LIMIT),
                "timestamp": str(thread.get("timestamp") or latest.get("timestamp") or ""),
                "received_timestamp": str(thread.get("received_timestamp") or latest.get("timestamp") or ""),
                "senders": [str(v) for v in (thread.get("senders") or []) if str(v).strip()],
                "recipients": [str(v) for v in (thread.get("recipients") or []) if str(v).strip()],
                "window_message_ids": [str(msg.get("message_id", "")).strip() for msg in ordered if str(msg.get("message_id", "")).strip()],
                "window_count": len(ordered),
                "message_count": int(thread.get("message_count", len(all_messages)) or len(all_messages)),
                "latest_from_name": latest_name,
                "latest_from_email": latest_email,
                "latest_sender_domain": latest_domain,
                "messages": [
                    {
                        "message_id": str(msg.get("message_id", "")).strip(),
                        "timestamp": str(msg.get("timestamp") or ""),
                        "labels": [str(v) for v in (msg.get("labels") or []) if str(v).strip()],
                        "from_raw": str(msg.get("from") or ""),
                        "from_name": _parse_sender(msg.get("from"))[0],
                        "from_email": _parse_sender(msg.get("from"))[1],
                        "sender_domain": _parse_sender(msg.get("from"))[2],
                        "subject": str(msg.get("subject") or thread.get("subject") or "(no subject)"),
                        "preview": _truncate(str(msg.get("preview") or ""), PREVIEW_LIMIT),
                        "text_excerpt": _truncate(
                            str(msg.get("extracted_text") or msg.get("text") or msg.get("preview") or ""),
                            TEXT_EXCERPT_LIMIT,
                        ),
                        "has_attachments": _message_attachment_count(msg) > 0,
                        "attachment_count": _message_attachment_count(msg),
                    }
                    for msg in ordered
                ],
            }
        )
    return len(scanned_messages), snapshots


def _flatten_window_messages(*, thread_snapshots: list[dict], config: dict) -> list[dict]:
    messages: list[dict] = []
    resolve_forwarded_sender = _forwarded_sender_lookup_enabled(config)
    for thread in thread_snapshots:
        for message in thread.get("messages", []) or []:
            sender_name = str(message.get("from_name") or thread.get("latest_from_name") or "").strip()
            sender_email = str(message.get("from_email") or thread.get("latest_from_email") or "").strip()
            sender_domain = str(message.get("sender_domain") or thread.get("latest_sender_domain") or "").strip()
            if resolve_forwarded_sender:
                forwarded_name, forwarded_email, forwarded_domain = _extract_forwarded_sender(message)
                if forwarded_name or forwarded_email or forwarded_domain:
                    sender_name = forwarded_name
                    sender_email = forwarded_email
                    sender_domain = forwarded_domain
            sender_display = sender_name or sender_email or sender_domain or "Unknown sender"
            preview = str(message.get("text_excerpt") or message.get("preview") or thread.get("thread_preview") or "").strip()
            entry = {
                "message_id": str(message.get("message_id") or "").strip(),
                "thread_id": str(thread.get("thread_id") or "").strip(),
                "timestamp": str(message.get("timestamp") or thread.get("received_timestamp") or thread.get("timestamp") or ""),
                "subject": str(message.get("subject") or thread.get("subject") or "(no subject)"),
                "sender_display": sender_display,
                "from_name": sender_name,
                "from_email": sender_email,
                "sender_domain": sender_domain,
                "preview": preview,
                "labels": [str(value) for value in (message.get("labels") or []) if str(value).strip()],
                "has_attachments": bool(message.get("has_attachments", False)),
                "attachment_count": int(message.get("attachment_count", 0) or 0),
            }
            entry["is_low_signal"] = _looks_low_signal_message(entry, config=config)
            messages.append(entry)
    messages.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return messages


def _message_has_handled_label(message: dict, *, config: dict) -> bool:
    handled_labels = set(_labels(config).values())
    message_labels = {str(value).strip() for value in (message.get("labels") or []) if str(value).strip()}
    return bool(handled_labels & message_labels)


def _message_requires_llm_review(message: dict, *, config: dict) -> bool:
    if bool(message.get("has_attachments", False)):
        return True

    subject = str(message.get("subject") or "").strip()
    if subject and REPLY_SUBJECT_RE.match(subject):
        return True

    haystack = " ".join(
        [
            subject,
            str(message.get("preview") or ""),
            str(message.get("text_excerpt") or ""),
        ]
    ).lower()
    if any(token in haystack for token in ACTION_KEYWORDS):
        return True

    return not _looks_low_signal_message(message, config=config)


def _merge_label_actions(*actions: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for payload in actions:
        for label, values in (payload or {}).items():
            current = merged.setdefault(str(label), [])
            for value in values:
                message_id = str(value).strip()
                if message_id and message_id not in current:
                    current.append(message_id)
    return {label: ids for label, ids in merged.items() if ids}


def _prefilter_poll_thread_snapshots(thread_snapshots: list[dict], *, config: dict) -> tuple[list[dict], dict[str, list[str]], int, dict[str, int]]:
    labels = _labels(config)
    low_signal_label = labels["low_signal"]
    candidate_threads: list[dict] = []
    prefilter_label_actions: dict[str, list[str]] = {low_signal_label: []}
    low_signal_count = 0
    skipped_handled = 0
    skipped_low_signal = 0

    for thread in thread_snapshots:
        messages = list(thread.get("messages", []) or [])
        if not messages:
            continue

        if all(_message_has_handled_label(message, config=config) for message in messages):
            skipped_handled += 1
            continue

        needs_llm = False
        thread_low_signal_ids: list[str] = []
        thread_low_signal_messages = 0
        for message in messages:
            if _message_has_handled_label(message, config=config):
                continue
            if _message_requires_llm_review(message, config=config):
                needs_llm = True
                break
            if _looks_low_signal_message(message, config=config):
                thread_low_signal_messages += 1
                message_labels = {
                    str(value).strip()
                    for value in (message.get("labels") or [])
                    if str(value).strip()
                }
                message_id = str(message.get("message_id") or "").strip()
                if message_id and low_signal_label not in message_labels:
                    thread_low_signal_ids.append(message_id)
            else:
                needs_llm = True
                break

        if needs_llm:
            candidate_threads.append(thread)
            continue

        skipped_low_signal += 1
        low_signal_count += thread_low_signal_messages
        prefilter_label_actions[low_signal_label].extend(thread_low_signal_ids)

    return (
        candidate_threads,
        _merge_label_actions(prefilter_label_actions),
        low_signal_count,
        {
            "scanned_threads": len(thread_snapshots),
            "skipped_handled": skipped_handled,
            "skipped_low_signal": skipped_low_signal,
            "candidate_threads": len(candidate_threads),
        },
    )


def _prefilter_tail_line(stats: dict[str, int], *, llm_skipped: bool) -> str:
    return (
        "prefilter: "
        f"scanned_threads={stats.get('scanned_threads', 0)}, "
        f"skipped_handled={stats.get('skipped_handled', 0)}, "
        f"skipped_low_signal={stats.get('skipped_low_signal', 0)}, "
        f"candidate_threads={stats.get('candidate_threads', 0)}, "
        f"llm_skipped={'true' if llm_skipped else 'false'}"
    )


def _scheduled_digest_window(now: datetime, *, config: dict) -> tuple[datetime, datetime]:
    tz = ZoneInfo(str(config.get("timezone", "Europe/Moscow") or "Europe/Moscow"))
    slots = _schedule_slots(config)
    local_now = now.astimezone(tz)

    points: list[datetime] = []
    for day_offset in (-1, 0, 1):
        day = local_now.date() + timedelta(days=day_offset)
        for hour, minute in slots:
            points.append(datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz))
    points.sort()

    end_local = max(point for point in points if point <= local_now)
    end_index = points.index(end_local)
    start_local = points[end_index - 1]
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _collect_message_ids(events) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for event in events:
        for message_id in event.message_ids:
            if message_id and message_id not in seen:
                seen.add(message_id)
                result.append(message_id)
    return result


def _collect_mailbox_message_ids(messages: list[dict]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        message_id = str(message.get("message_id") or "").strip()
        if message_id and message_id not in seen:
            seen.add(message_id)
            result.append(message_id)
    return result


def _is_not_found_agentmail_error(exc: AgentMailApiError) -> bool:
    text = str(exc)
    return " failed: 404 " in text or "NotFoundError" in text


def _apply_label_actions(inbox_ref: str, label_actions: dict[str, list[str]]) -> list[str]:
    cleaned = {
        label: sorted({message_id for message_id in message_ids if str(message_id).strip()})
        for label, message_ids in label_actions.items()
        if sorted({message_id for message_id in message_ids if str(message_id).strip()})
    }
    if not cleaned:
        return ["label commit skipped (no-op)"]
    api = _api_client()
    applied: dict[str, int] = {}
    skipped_not_found: dict[str, int] = {}
    for label, message_ids in cleaned.items():
        count = 0
        skipped = 0
        for message_id in message_ids:
            try:
                api.update_message(inbox_ref, message_id, add_labels=[label])
                count += 1
            except AgentMailApiError as exc:
                if _is_not_found_agentmail_error(exc):
                    skipped += 1
                    logger.warning("Skipping missing AgentMail message during label commit: %s", message_id)
                    continue
                raise
        if count:
            applied[label] = count
        if skipped:
            skipped_not_found[label] = skipped
    parts = [f"{label}={count}" for label, count in applied.items()]
    if skipped_not_found:
        parts.extend(f"{label}:missing={count}" for label, count in skipped_not_found.items())
    if not parts:
        return ["label commit skipped (all message ids missing)"]
    return [f"label commit applied: {', '.join(parts)}"]


def _prepare_poll_result(
    *,
    config: dict,
    run_id: str,
    inbox_ref: str,
    since_dt: datetime,
    until_dt: datetime,
    mode: str,
) -> tuple[PollPrepResult, list[str]]:
    scanned_count, thread_snapshots = _collect_thread_snapshots(
        inbox_ref=inbox_ref,
        since_dt=since_dt,
        until_dt=until_dt,
    )
    prelude = [f"agentmail api window: messages={scanned_count}, threads={len(thread_snapshots)}, mode={mode}"]
    candidate_threads, prefilter_actions, prefilter_low_signal_count, prefilter_stats = _prefilter_poll_thread_snapshots(
        thread_snapshots,
        config=config,
    )
    poll_llm_enabled = _poll_llm_enabled(config)
    prefilter_line = _prefilter_tail_line(prefilter_stats, llm_skipped=(not candidate_threads or not poll_llm_enabled))
    if not candidate_threads or not poll_llm_enabled:
        empty = _fallback_poll_result(
            run_id=run_id,
            inbox_ref=inbox_ref,
            topic_name=str(config.get("topic_name", "inbox-email")),
            scanned_count=scanned_count,
            thread_count=len(thread_snapshots),
            prefilter_actions=prefilter_actions,
            prefilter_low_signal_count=prefilter_low_signal_count,
            prefilter_stats=prefilter_stats,
        )
        tail = [prefilter_line]
        if candidate_threads and not poll_llm_enabled:
            tail.append("poll llm skipped: disabled")
        return empty, _tail_union(prelude, tail)

    topic_name = str(config.get("topic_name", "inbox-email"))
    prompt, prompt_tail = _build_bounded_poll_prompt(
        inbox_ref=inbox_ref,
        topic_name=topic_name,
        since_dt=since_dt,
        until_dt=until_dt,
        labels=_labels(config),
        low_signal_hints=[str(v) for v in config.get("low_signal_hints", [])],
        candidate_threads=candidate_threads,
        mode=mode,
    )
    try:
        result = run_agent_json(prompt)
    except AgentRunError as exc:
        logger.warning("Poll LLM fallback for run_id=%s: %s", run_id, exc)
        fallback = _fallback_poll_result(
            run_id=run_id,
            inbox_ref=inbox_ref,
            topic_name=topic_name,
            scanned_count=scanned_count,
            thread_count=len(thread_snapshots),
            prefilter_actions=prefilter_actions,
            prefilter_low_signal_count=prefilter_low_signal_count,
            prefilter_stats=prefilter_stats,
        )
        return fallback, _tail_union(prelude, [prefilter_line], prompt_tail, exc.tail, [f"llm fallback: {exc}"])

    parsed = PollPrepResult.from_payload(
        result.payload,
        run_id=run_id,
        inbox_ref=inbox_ref,
        telegram_topic=topic_name,
    )
    parsed.messages_scanned = scanned_count
    parsed.threads_considered = len(thread_snapshots)
    parsed.low_signal_count += prefilter_low_signal_count
    parsed.label_actions = _merge_label_actions(parsed.label_actions, prefilter_actions)
    parsed.prefilter_scanned_threads = prefilter_stats.get("scanned_threads", 0)
    parsed.prefilter_skipped_handled = prefilter_stats.get("skipped_handled", 0)
    parsed.prefilter_skipped_low_signal = prefilter_stats.get("skipped_low_signal", 0)
    parsed.prefilter_candidate_threads = prefilter_stats.get("candidate_threads", 0)
    parsed.llm_skipped = False
    return parsed, _tail_union(prelude, [prefilter_line], prompt_tail, result.output_tail)


def _persist_catchup_if_needed(
    r: redis_lib.Redis,
    *,
    config: dict,
    run_id: str,
    inbox_ref: str,
    since_dt: datetime,
    until_dt: datetime,
) -> list[str]:
    poll_result, tail = _prepare_poll_result(
        config=config,
        run_id=f"{run_id}-catchup",
        inbox_ref=inbox_ref,
        since_dt=since_dt,
        until_dt=until_dt,
        mode="catchup",
    )

    if poll_result.publish_events:
        append_events(r, poll_result.publish_events, retention_days=_event_retention_days(config))

    tail_commit = _apply_label_actions(inbox_ref, poll_result.label_actions)
    state_store.set_dt(r, state_store.last_poll_key(inbox_ref), until_dt)
    state_store.set_dt(r, state_store.last_poll_success_key(inbox_ref), until_dt)
    trim_old_events(r, retention_days=_event_retention_days(config))
    return _tail_union(tail, tail_commit)


def _poll_summary_lines(
    poll_result: PollPrepResult,
    *,
    since_dt: datetime,
    until_dt: datetime,
    lookback_minutes: int | None,
    mode: str,
) -> list[str]:
    mode_label = "catchup" if mode != "poll" else "poll"
    window_label = (
        f"lookback={lookback_minutes}m"
        if lookback_minutes is not None
        else f"window={since_dt.isoformat()}..{until_dt.isoformat()}"
    )
    return [
        (
            f"{mode_label} summary: scanned={poll_result.messages_scanned}, "
            f"threads={poll_result.threads_considered}, "
            f"publishable={len(poll_result.publish_events)}, "
            f"low_signal={poll_result.low_signal_count}, "
            f"prefilter_scanned={poll_result.prefilter_scanned_threads}, "
            f"skipped_handled={poll_result.prefilter_skipped_handled}, "
            f"skipped_low_signal={poll_result.prefilter_skipped_low_signal}, "
            f"candidate_threads={poll_result.prefilter_candidate_threads}, "
            f"llm_skipped={'true' if poll_result.llm_skipped else 'false'}, "
            f"{window_label}"
        )
    ]


def _process_poll(r: redis_lib.Redis, *, data: dict[str, str], config: dict) -> list[str]:
    inbox_ref = data.get("inbox_ref") or str(config.get("inbox_ref", "")).strip()
    if not inbox_ref:
        raise RuntimeError("missing_inbox_ref")

    run_id = data.get("run_id", str(uuid.uuid4()))
    lock_name = state_store.lock_key(inbox_ref, "poll")
    if not state_store.acquire_lock(r, lock_name, run_id, ttl_seconds=900):
        raise RuntimeError("poll_lock_busy")

    try:
        now = datetime.now(timezone.utc)
        lookback_minutes = _parse_lookback_minutes(data)
        last_poll_at = state_store.get_dt(r, state_store.last_poll_key(inbox_ref))
        if lookback_minutes is not None:
            since_dt = now - timedelta(minutes=lookback_minutes)
        else:
            since_dt = last_poll_at or (
                now - timedelta(minutes=int(config.get("poll_bootstrap_lookback_minutes", 720) or 720))
            )
        poll_result, prep_tail = _prepare_poll_result(
            config=config,
            run_id=run_id,
            inbox_ref=inbox_ref,
            since_dt=since_dt,
            until_dt=now,
            mode="poll",
        )

        if poll_result.publish_events:
            append_events(r, poll_result.publish_events, retention_days=_event_retention_days(config))

        commit_tail = _apply_label_actions(inbox_ref, poll_result.label_actions)
        state_store.set_dt(r, state_store.last_poll_key(inbox_ref), now)
        state_store.set_dt(r, state_store.last_poll_success_key(inbox_ref), now)
        trim_old_events(r, retention_days=_event_retention_days(config))
        summary_tail = _poll_summary_lines(
            poll_result,
            since_dt=since_dt,
            until_dt=now,
            lookback_minutes=lookback_minutes,
            mode="poll",
        )
        return _tail_union(prep_tail, summary_tail, commit_tail)
    finally:
        state_store.release_lock(r, lock_name, run_id)


def _process_digest(r: redis_lib.Redis, *, data: dict[str, str], config: dict) -> list[str]:
    inbox_ref = data.get("inbox_ref") or str(config.get("inbox_ref", "")).strip()
    digest_type = data.get("digest_type", "interval")
    if not inbox_ref:
        raise RuntimeError("missing_inbox_ref")
    if digest_type not in VALID_DIGEST_TYPES:
        raise RuntimeError("invalid_digest_type")

    run_id = data.get("run_id", str(uuid.uuid4()))
    lock_name = state_store.lock_key(inbox_ref, "digest")
    if not state_store.acquire_lock(r, lock_name, run_id, ttl_seconds=1800):
        raise RuntimeError("digest_lock_busy")

    try:
        now = datetime.now(timezone.utc)
        lookback_minutes = _parse_lookback_minutes(data)
        if lookback_minutes is not None:
            window_start = now - timedelta(minutes=lookback_minutes)
            window_end = now
        else:
            window_start, window_end = _scheduled_digest_window(now, config=config)

        last_poll_success = state_store.get_dt(r, state_store.last_poll_success_key(inbox_ref))
        lag_grace = timedelta(minutes=int(config.get("poll_lag_grace_minutes", 15) or 15))
        catchup_tail: list[str] = []
        if lookback_minutes is None and (last_poll_success is None or (now - last_poll_success) > lag_grace):
            catchup_since = window_start if lookback_minutes is not None else (
                state_store.get_dt(r, state_store.last_poll_key(inbox_ref)) or window_start
            )
            try:
                catchup_tail = _persist_catchup_if_needed(
                    r,
                    config=config,
                    run_id=run_id,
                    inbox_ref=inbox_ref,
                    since_dt=catchup_since,
                    until_dt=window_end,
                )
            except AgentRunError as exc:
                logger.warning("Digest catch-up LLM skipped for run_id=%s: %s", run_id, exc)
                catchup_tail = _tail_union(exc.tail, [f"catchup skipped: {exc}"])

        scanned_count, thread_snapshots = _collect_thread_snapshots(
            inbox_ref=inbox_ref,
            since_dt=window_start,
            until_dt=window_end,
        )
        mailbox_messages = _flatten_window_messages(thread_snapshots=thread_snapshots, config=config)
        important_messages = [message for message in mailbox_messages if not bool(message.get("is_low_signal"))][:5]

        html = render_mailbox_digest(
            digest_type=digest_type,
            window_start=window_start,
            window_end=window_end,
            messages=mailbox_messages,
            important_messages=important_messages,
            topic_name=str(config.get("topic_name", "")).strip(),
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )
        posted = asyncio.run(post_html_message(html))
        if not posted:
            raise RuntimeError("telegram_post_failed")

        digested_label = _labels(config)["digested"]
        commit_tail = _apply_label_actions(inbox_ref, {digested_label: _collect_mailbox_message_ids(mailbox_messages)})
        state_store.set_dt(r, state_store.last_digest_key(inbox_ref), window_end)
        trim_old_events(r, retention_days=_event_retention_days(config))
        low_signal_count = sum(1 for message in mailbox_messages if bool(message.get("is_low_signal")))
        summary_tail = [
            (
                f"digest summary: messages={len(mailbox_messages)}, threads={len(thread_snapshots)}, "
                f"important={len(important_messages)}, low_signal={low_signal_count}, "
                f"scanned={scanned_count}, digest_type={digest_type}, "
                f"window={window_start.isoformat()}..{window_end.isoformat()}"
            )
        ]
        return _tail_union(catchup_tail, summary_tail, commit_tail)
    finally:
        state_store.release_lock(r, lock_name, run_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "agentmail-email-bridge/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            status = _load_status()
            self._send(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "agentmail-email-bridge",
                    "running": bool(status.get("running")),
                    "last_job_type": status.get("job_type"),
                    "last_digest_type": status.get("digest_type"),
                    "last_started_at": status.get("started_at"),
                    "last_finished_at": status.get("finished_at"),
                    "last_exit_code": status.get("exit_code"),
                },
            )
            return
        if self.path == "/status":
            self._send(HTTPStatus.OK, _load_status())
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
        if not REDIS_URL:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "integration_bus_not_configured"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        job_type = str(payload.get("job_type", "")).strip()
        if job_type not in VALID_JOB_TYPES:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_job_type"})
            return

        digest_type = str(payload.get("digest_type", "")).strip()
        if job_type == "digest" and digest_type not in VALID_DIGEST_TYPES:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_digest_type"})
            return

        run_id = str(uuid.uuid4())
        config = load_config()
        inbox_ref = str(payload.get("inbox_ref") or config.get("inbox_ref", "")).strip()
        if not inbox_ref:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_inbox_ref"})
            return

        try:
            r = _make_redis()
            r.xadd(
                STREAM_JOBS,
                {
                    "run_id": run_id,
                    "job_type": job_type,
                    "digest_type": digest_type,
                    "inbox_ref": inbox_ref,
                    "requested_at": _utc_now(),
                    "requested_by": "cron",
                    "window_hint": str(payload.get("window_hint", "")).strip(),
                    "lookback_minutes": str(payload.get("lookback_minutes", "")).strip(),
                },
            )
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to enqueue email job: %s", exc)
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "bus_unavailable", "detail": str(exc)})
            return

        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "run_id": run_id,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "inbox_ref": inbox_ref,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: HTTPStatus, payload: dict) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _scheduler_loop() -> None:
    logger.info("Email scheduler loop starting (REDIS_URL=%s)", REDIS_URL)
    while True:
        sleep_seconds: float = 60
        try:
            config = load_config()
            sleep_seconds = _scheduler_tick_seconds(config)
            if not _scheduler_enabled(config):
                time.sleep(sleep_seconds)
                continue

            inbox_ref = str(config.get("inbox_ref", "")).strip()
            if not inbox_ref:
                logger.warning("Email scheduler skipped: inbox_ref is not configured")
                time.sleep(sleep_seconds)
                continue

            status = _load_status()
            if status.get("running") and status.get("job_type") == "poll":
                time.sleep(min(sleep_seconds, 30))
                continue

            r = _make_redis()
            now = datetime.now(timezone.utc)
            next_due_key = state_store.next_poll_due_key(inbox_ref)
            next_due = state_store.get_dt(r, next_due_key)
            if next_due is None:
                next_due = now

            if next_due <= now:
                run_id = str(uuid.uuid4())
                r.xadd(
                    STREAM_JOBS,
                    {
                        "run_id": run_id,
                        "job_type": "poll",
                        "digest_type": "",
                        "inbox_ref": inbox_ref,
                        "requested_at": _utc_now(),
                        "requested_by": "scheduler",
                        "window_hint": "",
                        "lookback_minutes": "",
                    },
                )
                state_store.set_dt(r, next_due_key, now + timedelta(seconds=sleep_seconds))
                logger.info("Scheduled email poll run_id=%s", run_id)
            else:
                remaining = max((next_due - now).total_seconds(), 1)
                sleep_seconds = min(sleep_seconds, remaining)
            time.sleep(sleep_seconds)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("Email scheduler lost redis connection: %s", exc)
            time.sleep(max(sleep_seconds, 30))
        except Exception:
            logger.exception("Email scheduler loop failed")
            time.sleep(max(sleep_seconds, 60))


def _consumer_loop_inner(r: redis_lib.Redis) -> None:
    try:
        r.xgroup_create(STREAM_JOBS, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Consumer group '%s' created on '%s'", CONSUMER_GROUP, STREAM_JOBS)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("Email consumer loop ready — listening on '%s'", STREAM_JOBS)
    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_JOBS: "0"},
                count=1,
            )
            entries = messages[0][1] if messages else []
            if not entries:
                messages = r.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {STREAM_JOBS: ">"},
                    block=BLOCK_MS,
                    count=1,
                )
        except redis_lib.exceptions.TimeoutError:
            continue
        if not messages:
            continue

        _, entries = messages[0]
        if not entries:
            continue
        msg_id, data = entries[0]
        job_type = data.get("job_type", "poll")
        digest_type = data.get("digest_type", "")
        run_id = data.get("run_id", msg_id)
        started_at = _utc_now()

        _write_status(
            r,
            {
                "ok": True,
                "running": True,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": None,
                "exit_code": None,
                "tail": [],
            },
        )

        try:
            config = load_config()
            if job_type == "poll":
                tail = _process_poll(r, data=data, config=config)
            else:
                tail = _process_digest(r, data=data, config=config)
            exit_code = 0
        except AgentRunError as exc:
            logger.error("Agent run failed for run_id=%s: %s", run_id, exc)
            exit_code = 1
            tail = exc.tail or [str(exc)]
        except AgentMailApiError as exc:
            logger.error("AgentMail API failed for run_id=%s: %s", run_id, exc)
            exit_code = 1
            tail = [str(exc)]
        except Exception as exc:
            logger.error("Email pipeline failed for run_id=%s: %s", run_id, exc)
            exit_code = 1
            tail = [str(exc)]

        finished_at = _utc_now()
        _write_status(
            r,
            {
                "ok": exit_code == 0,
                "running": False,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": exit_code,
                "tail": tail[-12:],
            },
        )

        if exit_code != 0:
            try:
                r.xadd(
                    STREAM_DLQ,
                    {
                        "source": DLQ_SOURCE,
                        "job_type": job_type,
                        "digest_type": digest_type,
                        "msg_id": msg_id,
                        "run_id": run_id,
                        "error": tail[-1] if tail else "unknown_error",
                        "failed_at": finished_at,
                    },
                )
            except redis_lib.exceptions.RedisError as exc:
                logger.error("Failed to write email DLQ entry: %s", exc)

        try:
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to XACK email msg_id=%s: %s", msg_id, exc)


def consumer_loop() -> None:
    logger.info("Email consumer loop starting (REDIS_URL=%s)", REDIS_URL)
    while True:
        try:
            r = _make_redis()
            r.ping()
            _consumer_loop_inner(r)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("Redis connection lost: %s — reconnecting in 10s", exc)
            time.sleep(10)
        except Exception as exc:
            logger.error("Email consumer unexpected error: %s — restarting in 5s", exc)
            time.sleep(5)


def main() -> None:
    raise SystemExit("Legacy bridge entrypoint disabled. Use benka worker with a reviewed manifest.")


if __name__ == "__main__":
    main()
