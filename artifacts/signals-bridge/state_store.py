"""
Redis-backed state keys and locks for the signals bridge.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


def ruleset_next_due_key(ruleset_id: str) -> str:
    return f"state:signals:ruleset:{_slug(ruleset_id)}:next_due_at"


def ruleset_last_success_key(ruleset_id: str) -> str:
    return f"state:signals:ruleset:{_slug(ruleset_id)}:last_success_at"


def source_last_success_key(source_id: str) -> str:
    return f"state:signals:source:{_slug(source_id)}:last_success_at"


def source_cursor_key(source_id: str) -> str:
    return f"state:signals:source:{_slug(source_id)}:cursor"


def source_status_key(source_id: str) -> str:
    return f"state:signals:source:{_slug(source_id)}:status"


def last30days_last_success_key(preset_id: str) -> str:
    return f"state:signals:last30days:{_slug(preset_id)}:last_success_at"


def lock_key(scope: str, target: str) -> str:
    return f"lock:signals:{_slug(scope)}:{_slug(target)}"


def status_key() -> str:
    return "status:signals:latest"


def get_dt(r, key: str) -> datetime | None:
    value = r.get(key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def set_dt(r, key: str, value: datetime) -> None:
    r.set(key, value.astimezone(timezone.utc).isoformat())


def get_int(r, key: str, default: int = 0) -> int:
    value = r.get(key)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def set_int(r, key: str, value: int) -> None:
    r.set(key, str(int(value)))


def get_source_status(r, source_id: str) -> dict:
    raw = r.get(source_status_key(source_id))
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def set_source_status(r, source_id: str, payload: dict) -> None:
    r.set(source_status_key(source_id), json.dumps(payload, ensure_ascii=False, sort_keys=True))


def acquire_lock(r, key: str, holder: str, ttl_seconds: int) -> bool:
    return bool(r.set(key, holder, nx=True, ex=ttl_seconds))


def release_lock(r, key: str, holder: str) -> None:
    current = r.get(key)
    if current == holder:
        r.delete(key)


def set_status(r, payload: dict) -> None:
    r.set(status_key(), json.dumps(payload, ensure_ascii=False))
