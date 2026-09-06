#!/usr/bin/env python3
"""Telethon Digest cron bridge + integration bus consumer.

HTTP server (GET /health, GET /status, POST /trigger) and a Redis Streams
consumer loop running as a background thread in the same process.

POST /trigger enqueues a job to `ingest:jobs:telegram` and returns 202
immediately — the digest pipeline runs asynchronously in the consumer loop.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import redis as redis_lib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] cron_bridge: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("cron_bridge")

PORT = int(os.environ.get("DIGEST_CRON_BRIDGE_PORT", "8091"))
TOKEN = os.environ.get("DIGEST_CRON_BRIDGE_TOKEN", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()

STATE_DIR = Path("/app/state")
STATUS_PATH = STATE_DIR / "cron-bridge-status.json"

LIGHTRAG_URL = os.environ.get("LIGHTRAG_URL", "http://lightrag:9621")

STREAM_JOBS = "ingest:jobs:telegram"
STREAM_RAG = "ingest:rag:queue"
STREAM_DLQ = "dlq:failed"
CONSUMER_GROUP = "digest-workers"
CONSUMER_NAME = "cron-bridge-worker"
RAG_CONSUMER_GROUP = "rag-workers"
RAG_CONSUMER_NAME = "rag-worker"
BLOCK_MS = 5000
REDIS_SOCKET_TIMEOUT_SECONDS = max(
    int(os.environ.get("REDIS_SOCKET_TIMEOUT_SECONDS", "30")),
    int(BLOCK_MS / 1000) + 5,
)

VALID_DIGEST_TYPES = {"morning", "interval", "editorial"}
DIGEST_LOCK_KEY = "lock:telegram-digest:run"
LOCK_TTL_SECONDS = int(os.environ.get("DIGEST_RUN_LOCK_TTL_SECONDS", "5400"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _write_status(payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _make_redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


def _parse_slot_value(payload: dict, key: str, *, minimum: int, maximum: int) -> int | None:
    raw = payload.get(key)
    if raw in (None, ""):
        return None
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"{key}_out_of_range")
    return value


def _acquire_run_lock(r: redis_lib.Redis, *, run_id: str) -> bool:
    return bool(r.set(DIGEST_LOCK_KEY, run_id, nx=True, ex=LOCK_TTL_SECONDS))


def _release_run_lock(r: redis_lib.Redis, *, run_id: str) -> None:
    try:
        current = r.get(DIGEST_LOCK_KEY)
        if current == run_id:
            r.delete(DIGEST_LOCK_KEY)
    except redis_lib.exceptions.RedisError as exc:
        logger.error("Failed to release digest lock for run_id=%s: %s", run_id, exc)


# ---------------------------------------------------------------------------
def _recover_interrupted_status() -> None:
    status = _load_status()
    if not status.get("running"):
        return

    run_id = str(status.get("run_id") or "")
    tail = list(status.get("tail") or [])
    tail.append("bridge restarted before digest_worker.py finished")
    status.update(
        {
            "ok": False,
            "running": False,
            "finished_at": _utc_now(),
            "exit_code": 130,
            "interrupted": True,
            "error": "bridge_restarted_while_pipeline_running",
            "tail": tail[-12:],
        }
    )
    _write_status(status)
    logger.warning("Marked interrupted digest run_id=%s after bridge restart", run_id)

    if not (REDIS_URL and run_id):
        return
    try:
        r = _make_redis()
        _release_run_lock(r, run_id=run_id)
    except redis_lib.exceptions.RedisError as exc:
        logger.error("Failed to release interrupted run lock run_id=%s: %s", run_id, exc)


# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "telethon-digest-cron-bridge/2.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            status = _load_status()
            self._send(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "telethon-digest-cron-bridge",
                    "running": bool(status.get("running")),
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
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "missing_bridge_token"},
            )
            return
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self._send(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if not REDIS_URL:
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "integration_bus_not_configured"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        digest_type = str(payload.get("digest_type", "")).strip()
        if digest_type not in VALID_DIGEST_TYPES:
            self._send(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_digest_type"},
            )
            return

        try:
            r = _make_redis()
            slot_hour = _parse_slot_value(payload, "slot_hour", minimum=0, maximum=23)
            slot_minute = _parse_slot_value(payload, "slot_minute", minimum=0, maximum=59)
            if slot_hour is None and slot_minute is not None:
                raise ValueError("slot_minute_without_hour")
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_slot"})
            return
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "bus_unavailable", "detail": str(exc)},
            )
            return

        run_id = str(uuid.uuid4())
        try:
            if not _acquire_run_lock(r, run_id=run_id):
                self._send(
                    HTTPStatus.CONFLICT,
                    {"ok": False, "error": "digest_already_running"},
                )
                return
            job_payload = {
                "run_id": run_id,
                "digest_type": digest_type,
                "requested_at": _utc_now(),
                "requested_by": "cron",
            }
            if slot_hour is not None:
                job_payload["slot_hour"] = slot_hour
                job_payload["slot_minute"] = slot_minute or 0
            r.xadd(STREAM_JOBS, job_payload)
        except redis_lib.exceptions.RedisError as exc:
            _release_run_lock(r, run_id=run_id)
            logger.error("Failed to enqueue job: %s", exc)
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "bus_unavailable", "detail": str(exc)},
            )
            return

        logger.info("Enqueued job run_id=%s digest_type=%s", run_id, digest_type)
        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "run_id": run_id,
                "digest_type": digest_type,
                "slot_hour": slot_hour,
                "slot_minute": slot_minute,
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


# ---------------------------------------------------------------------------
# Redis consumer loop (background thread)
# ---------------------------------------------------------------------------

def _run_pipeline(digest_type: str, run_id: str, *, slot_hour: int | None = None, slot_minute: int | None = None) -> tuple[int, list[str]]:
    """Run digest_worker.py subprocess; return (exit_code, tail_lines)."""
    env = os.environ.copy()
    env["DIGEST_TYPE_OVERRIDE"] = digest_type
    if slot_hour is None:
        env.pop("DIGEST_SLOT_HOUR", None)
        env.pop("DIGEST_SLOT_MINUTE", None)
    else:
        env["DIGEST_SLOT_HOUR"] = str(slot_hour)
        env["DIGEST_SLOT_MINUTE"] = str(slot_minute or 0)
    try:
        proc = subprocess.run(
            ["python", "digest_worker.py", "--now"],
            cwd="/app",
            env=env,
            capture_output=True,
            text=True,
            timeout=5400,
        )
        output = "\n".join(
            p for p in [proc.stdout.strip(), proc.stderr.strip()] if p
        ).strip()
        return proc.returncode, output.splitlines()[-12:] if output else []
    except subprocess.TimeoutExpired:
        logger.error("digest_worker.py timed out for run_id=%s", run_id)
        return 124, ["timeout"]


def _consumer_loop_inner(r: redis_lib.Redis) -> None:
    """Inner consumer loop; raises on Redis errors for outer reconnect logic."""
    try:
        r.xgroup_create(STREAM_JOBS, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Consumer group '%s' created on '%s'", CONSUMER_GROUP, STREAM_JOBS)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info(
        "Consumer loop ready — listening on '%s' (group '%s')",
        STREAM_JOBS,
        CONSUMER_GROUP,
    )

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
        digest_type = data.get("digest_type", "interval")
        run_id = data.get("run_id", msg_id)
        raw_slot_hour = data.get("slot_hour")
        raw_slot_minute = data.get("slot_minute")
        slot_hour = int(raw_slot_hour) if str(raw_slot_hour or "").strip() else None
        slot_minute = int(raw_slot_minute) if str(raw_slot_minute or "").strip() else None
        logger.info("Processing job run_id=%s digest_type=%s", run_id, digest_type)

        started_at = _utc_now()
        _write_status({
            "ok": True,
            "running": True,
            "digest_type": digest_type,
            "run_id": run_id,
            "slot_hour": slot_hour,
            "slot_minute": slot_minute,
            "started_at": started_at,
            "finished_at": None,
            "exit_code": None,
            "tail": [],
        })

        exit_code, tail = _run_pipeline(digest_type, run_id, slot_hour=slot_hour, slot_minute=slot_minute)
        finished_at = _utc_now()

        _write_status({
            "ok": exit_code == 0,
            "running": False,
            "digest_type": digest_type,
            "run_id": run_id,
            "slot_hour": slot_hour,
            "slot_minute": slot_minute,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "tail": tail,
        })

        if exit_code != 0:
            logger.error("Pipeline failed exit_code=%d run_id=%s → dlq", exit_code, run_id)
            try:
                r.xadd(STREAM_DLQ, {
                    "source": "telegram",
                    "msg_id": msg_id,
                    "run_id": run_id,
                    "error": f"exit_code={exit_code}",
                    "failed_at": finished_at,
                })
            except redis_lib.exceptions.RedisError as exc:
                logger.error("Failed to write dlq entry: %s", exc)
        else:
            logger.info("Pipeline completed OK run_id=%s", run_id)

        try:
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to XACK msg_id=%s: %s", msg_id, exc)
        finally:
            _release_run_lock(r, run_id=run_id)


# ---------------------------------------------------------------------------
# RAG consumer loop (background thread)
# ---------------------------------------------------------------------------

def _upload_file_to_lightrag_sync(file_path: str, file_name: str) -> None:
    """Upload a markdown file to LightRAG synchronously (runs in consumer thread)."""
    path_obj = Path(file_path)
    if not path_obj.exists():
        logger.warning("RAG worker: file not found: %s", file_path)
        return
    content = path_obj.read_bytes()
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{LIGHTRAG_URL}/documents/upload",
            files={"file": (file_name, content, "text/markdown")},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"LightRAG upload failed HTTP {resp.status_code}")
        logger.info("RAG worker: uploaded %s → LightRAG", file_name)
    with httpx.Client(timeout=30) as client:
        try:
            client.post(f"{LIGHTRAG_URL}/documents/reprocess_failed")
        except Exception as exc:
            logger.warning("RAG worker: reprocess_failed error: %s", exc)


def _rag_consumer_loop_inner(r: redis_lib.Redis) -> None:
    """Inner RAG consumer loop; raises on Redis errors for outer reconnect logic."""
    try:
        r.xgroup_create(STREAM_RAG, RAG_CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("RAG consumer group '%s' created on '%s'", RAG_CONSUMER_GROUP, STREAM_RAG)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("RAG consumer loop ready — listening on '%s'", STREAM_RAG)

    while True:
        messages = r.xreadgroup(
            RAG_CONSUMER_GROUP,
            RAG_CONSUMER_NAME,
            {STREAM_RAG: ">"},
            block=BLOCK_MS,
            count=1,
        )
        if not messages:
            continue

        _, entries = messages[0]
        msg_id, data = entries[0]
        file_path = data.get("file_path", "")
        file_name = data.get("file_name", Path(file_path).name if file_path else "unknown")
        logger.info("RAG worker: processing %s", file_name)

        try:
            _upload_file_to_lightrag_sync(file_path, file_name)
            r.xack(STREAM_RAG, RAG_CONSUMER_GROUP, msg_id)
        except Exception as exc:
            logger.error("RAG worker: failed %s: %s → dlq", file_name, exc)
            try:
                r.xadd(STREAM_DLQ, {
                    "source": "rag-worker",
                    "msg_id": msg_id,
                    "file_path": file_path,
                    "error": str(exc),
                    "failed_at": _utc_now(),
                })
            except Exception:
                pass
            r.xack(STREAM_RAG, RAG_CONSUMER_GROUP, msg_id)


def rag_consumer_loop() -> None:
    """Background thread: connect to Redis, run RAG consumer loop with reconnect."""
    logger.info("RAG consumer loop starting")
    while True:
        try:
            r = _make_redis()
            r.ping()
            _rag_consumer_loop_inner(r)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("RAG consumer Redis lost: %s — reconnecting in 10s", exc)
            time.sleep(10)
        except Exception as exc:
            logger.error("RAG consumer unexpected error: %s — restarting in 5s", exc)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Digest consumer loop (background thread)
# ---------------------------------------------------------------------------

def consumer_loop() -> None:
    """Background thread: connect to Redis, run consumer loop with reconnect."""
    logger.info("Consumer loop starting (REDIS_URL=%s)", REDIS_URL)
    while True:
        try:
            r = _make_redis()
            r.ping()
            _consumer_loop_inner(r)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("Redis connection lost: %s — reconnecting in 10s", exc)
            time.sleep(10)
        except Exception as exc:
            logger.error("Consumer loop unexpected error: %s — restarting in 5s", exc)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    raise SystemExit("Legacy bridge entrypoint disabled. Use benka worker with a reviewed manifest.")


if __name__ == "__main__":
    main()
