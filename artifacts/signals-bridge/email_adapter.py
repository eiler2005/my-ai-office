"""
AgentMail polling adapter for rules-driven signals extraction.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any

from agentmail_api import AgentMailApiClient
from matching import match_email_rule, truncate
from models import SignalCandidate


_TEXT_KEYS = (
    "text_excerpt",
    "extracted_text",
    "text",
    "body_text",
    "body_plain",
    "plain_text",
    "content_text",
    "plain",
    "text_content",
)
_HTML_KEYS = (
    "body_html",
    "html_body",
    "content_html",
    "html_content",
    "html",
)
_CONTAINER_KEYS = (
    "body",
    "content",
    "payload",
    "part",
    "parts",
    "mime",
    "mime_parts",
)
_IGNORE_NESTED_KEYS = {
    "subject",
    "preview",
    "from",
    "to",
    "cc",
    "bcc",
    "thread_id",
    "message_id",
    "timestamp",
    "id",
}
_TRADINGVIEW_BOILERPLATE_RE = re.compile(
    r"на\s+которого\s+вы\s+подписаны,\s+опубликовал(?:\(-а\))?\s+нов(?:ое|ую)\s+(?:мнение|идею|обзор|анализ|разбор)",
    re.IGNORECASE,
)


def collect_email_candidates(
    *,
    api: AgentMailApiClient,
    source: dict,
    ruleset_id: str,
    ruleset_title: str,
    rules: list[dict],
    since_dt: datetime,
    until_dt: datetime,
) -> tuple[list[SignalCandidate], list[str]]:
    page_token: str | None = None
    seen_threads: set[str] = set()
    messages: list[dict] = []
    pages = 0
    max_pages = int(source.get("max_message_pages", 5) or 5)
    page_size = int(source.get("message_page_size", 100) or 100)

    while pages < max_pages:
        pages += 1
        page = api.list_messages(
            source["inbox_ref"],
            limit=page_size,
            page_token=page_token,
            after=since_dt,
            before=until_dt,
        )
        batch = list(page.get("messages", []) or [])
        messages.extend(batch)
        page_token = page.get("next_page_token")
        if not page_token or not batch:
            break

    candidates: list[SignalCandidate] = []
    for message in messages:
        thread_id = str(message.get("thread_id", "")).strip()
        if not thread_id or thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        thread = api.get_thread(source["inbox_ref"], thread_id)
        for prepared in _window_messages(thread=thread, since_dt=since_dt, until_dt=until_dt):
            for rule in rules:
                candidate = match_email_rule(
                    ruleset_id=ruleset_id,
                    ruleset_title=ruleset_title,
                    rule=rule,
                    message=prepared,
                )
                if candidate is not None:
                    candidates.append(candidate)
    tail = [
        f"email source={source['id']} scanned_messages={len(messages)}",
        f"email source={source['id']} matched={len(candidates)}",
    ]
    return candidates, tail


def resolve_email_window(*, source: dict, last_success: datetime | None, lookback_minutes: int | None, now: datetime) -> tuple[datetime, datetime]:
    until_dt = now
    if lookback_minutes:
        return until_dt - timedelta(minutes=lookback_minutes), until_dt
    bootstrap = int(source.get("bootstrap_lookback_minutes", 720) or 720)
    grace = int(source.get("lag_grace_minutes", 15) or 15)
    if last_success is None:
        return until_dt - timedelta(minutes=bootstrap), until_dt
    stale_after = int(source.get("stale_after_minutes", 15) or 15)
    if last_success < until_dt - timedelta(minutes=max(stale_after, 15)):
        # Backfill requires an explicit lookback override; a stale automatic
        # poll must not turn a recovery restart into an old-message replay.
        return until_dt - timedelta(minutes=grace), until_dt
    return last_success - timedelta(minutes=grace), until_dt


def _window_messages(*, thread: dict, since_dt: datetime, until_dt: datetime) -> list[dict]:
    prepared: list[dict] = []
    for item in thread.get("messages", []) or []:
        timestamp = _parse_dt(item.get("timestamp"))
        if timestamp is None or timestamp < since_dt or timestamp > until_dt:
            continue
        full_text = _resolve_text_excerpt(item=item, thread=thread)
        raw_from = str(item.get("from") or "").strip()
        from_name, from_email, sender_domain = _parse_sender(raw_from)
        prepared.append(
            {
                "message_id": str(item.get("message_id", "")).strip(),
                "thread_id": str(item.get("thread_id", "")).strip(),
                "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
                "from_name": from_name,
                "from_email": from_email,
                "sender_domain": sender_domain,
                "subject": str(item.get("subject") or thread.get("subject") or "(no subject)"),
                "preview": truncate(str(item.get("preview") or thread.get("preview") or ""), 320),
                "text_excerpt": truncate(full_text, 1200),
                "delivery_text": truncate(full_text, 3500),
            }
        )
    return prepared


def _resolve_text_excerpt(*, item: dict, thread: dict) -> str:
    direct_text = _first_text_field(item) or _first_text_field(thread)
    if direct_text:
        return _postprocess_excerpt(direct_text, item=item, thread=thread)

    nested_text = _extract_nested_text(item) or _extract_nested_text(thread)
    if nested_text:
        return _postprocess_excerpt(nested_text, item=item, thread=thread)

    return str(item.get("preview") or thread.get("preview") or "").strip()


def _first_text_field(payload: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    for key in _HTML_KEYS:
        value = str(payload.get(key) or "").strip()
        if value:
            text = _html_to_text(value)
            if text:
                return text
    return ""


def _extract_nested_text(value: Any) -> str:
    return _extract_nested_text_inner(value, seen=set())


def _extract_nested_text_inner(value: Any, *, seen: set[int]) -> str:
    if value is None:
        return ""
    marker = id(value)
    if marker in seen:
        return ""
    seen.add(marker)

    if isinstance(value, dict):
        direct = _first_text_field(value)
        if direct:
            return direct
        for key in _CONTAINER_KEYS:
            nested = value.get(key)
            if nested is None:
                continue
            extracted = _extract_nested_text_inner(nested, seen=seen)
            if extracted:
                return extracted
        for key, nested in value.items():
            if str(key).lower() in _IGNORE_NESTED_KEYS:
                continue
            if isinstance(nested, (dict, list, tuple)):
                extracted = _extract_nested_text_inner(nested, seen=seen)
                if extracted:
                    return extracted
        return ""

    if isinstance(value, (list, tuple)):
        for item in value:
            extracted = _extract_nested_text_inner(item, seen=seen)
            if extracted:
                return extracted
    return ""


def _html_to_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(?:p|div|section|article|header|footer|li|ul|ol|tr|table|h[1-6]|blockquote)[^>]*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _postprocess_excerpt(text: str, *, item: dict, thread: dict) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if _looks_like_tradingview_message(item=item, thread=thread):
        value = _cleanup_tradingview_excerpt(value)
    return value.strip()


def _looks_like_tradingview_message(*, item: dict, thread: dict) -> bool:
    sender_parts = [
        str(item.get("from") or ""),
        str(thread.get("from") or ""),
        str(item.get("subject") or ""),
        str(thread.get("subject") or ""),
    ]
    haystack = "\n".join(part for part in sender_parts if part).lower()
    return "tradingview" in haystack or "мнение от" in haystack


def _cleanup_tradingview_excerpt(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines:
        if line.lower() == "tradingview":
            continue
        if line.lower() == "открыть мнение":
            continue
        if _TRADINGVIEW_BOILERPLATE_RE.search(line):
            continue
        filtered.append(line)

    if len(filtered) >= 3 and _looks_like_tradingview_username_line(filtered[0]) and _looks_like_symbol_line(filtered[1]):
        filtered = filtered[1:]

    if filtered and len(filtered) > 1:
        symbol = filtered[0]
        body = "\n".join(filtered[1:]).strip()
        if body and len(body) > len(symbol):
            return f"{symbol}\n{body}".strip()
    return "\n".join(filtered).strip() or text.strip()


def _looks_like_tradingview_username_line(value: str) -> bool:
    line = str(value or "").strip()
    if not line or len(line) < 3 or len(line) > 64:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", line))


def _looks_like_symbol_line(value: str) -> bool:
    line = str(value or "").strip()
    if not line or len(line) > 24:
        return False
    return bool(re.fullmatch(r"\$?[A-Z][A-Z0-9_.-]{1,23}", line))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_sender(raw: str | None) -> tuple[str, str, str]:
    value = (raw or "").strip()
    if not value:
        return "", "", ""
    if "<" in value and ">" in value:
        name, email = value.split("<", 1)
        email = email.split(">", 1)[0]
        name = name.strip().strip('"')
    elif "@" in value and " " not in value:
        name, email = "", value
    else:
        name, email = value, ""
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    return name.strip(), email.strip().lower(), domain
