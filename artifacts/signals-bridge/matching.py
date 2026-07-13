"""
Deterministic matching helpers used by the signals bridge.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from models import SignalCandidate, SignalEvent


TRADINGVIEW_USER_PATTERNS = [
    re.compile(r"\b(?:user|author|by)\s*[:\-]?\s*@?(?P<user>[A-Za-z0-9_.-]{3,64})\b", re.IGNORECASE),
    re.compile(r"\bidea by\s*@?(?P<user>[A-Za-z0-9_.-]{3,64})\b", re.IGNORECASE),
    re.compile(
        r"\b(?:мнение|идея|обзор|анализ|разбор)\s+от\s*@?(?P<user>[A-Za-z0-9_.-]{3,64})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<user>[A-Za-z0-9_.-]{3,64})\s+(?:на\s+которого\s+вы\s+подписаны,\s+)?"
        r"опубликовал(?:\(-а\))?\s+нов(?:ое|ую)\s+(?:мнение|идею|обзор|анализ|разбор)",
        re.IGNORECASE,
    ),
    re.compile(r"\b@(?P<user>[A-Za-z0-9_.-]{3,64})\b"),
]
HASHTAG_RE_TEMPLATE = r"(?<!\w){tag}\b"
YUAN_WORD_FORMS = (
    "юань",
    "юаня",
    "юаню",
    "юанем",
    "юане",
    "юани",
    "юаней",
    "юаням",
    "юанями",
    "юанях",
)
YUAN_SLANG_FORMS = ("юашка", "юашку", "юашки")
KEYWORD_ALIASES = {
    "си": ("сиха", "сиху"),
    "юань": (*YUAN_WORD_FORMS[1:], *YUAN_SLANG_FORMS),
    "cny": (*YUAN_WORD_FORMS, *YUAN_SLANG_FORMS),
    "yuan": (*YUAN_WORD_FORMS, *YUAN_SLANG_FORMS),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(text: str | None, limit: int = 500) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def build_telegram_message_link(*, chat_id: int | None, message_id: int | None, chat_username: str | None = None) -> str:
    if not message_id:
        return ""
    username = str(chat_username or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}/{int(message_id)}"
    if not chat_id:
        return ""
    raw = str(abs(int(chat_id)))
    internal = raw[3:] if raw.startswith("100") else raw
    return f"https://t.me/c/{internal}/{int(message_id)}"


def extract_tradingview_username(*parts: str) -> str | None:
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        return None
    for pattern in TRADINGVIEW_USER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("user")
    return None


def keyword_matches(text: str, keyword: str) -> bool:
    normalized_text = text.casefold()
    normalized_keyword = str(keyword or "").strip().casefold()
    if not normalized_keyword:
        return False
    candidates = (normalized_keyword, *KEYWORD_ALIASES.get(normalized_keyword, ()))
    return any(_contains_keyword(normalized_text, candidate) for candidate in candidates)


def _contains_keyword(normalized_text: str, normalized_keyword: str) -> bool:
    pattern = re.compile(rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)")
    return bool(pattern.search(normalized_text))


def match_keywords(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
    return any(keyword_matches(text, keyword) for keyword in keywords)


def match_email_rule(*, ruleset_id: str, ruleset_title: str, rule: dict, message: dict) -> SignalCandidate | None:
    from_email = str(message.get("from_email", "")).strip().lower()
    if from_email != str(rule.get("from_email", "")).strip().lower():
        return None
    username = extract_tradingview_username(
        str(message.get("subject", "")),
        str(message.get("preview", "")),
        str(message.get("text_excerpt", "")),
    )
    allowed = {str(value).lower() for value in rule.get("tradingview_usernames", [])}
    if not username:
        return None
    if username.lower() not in allowed:
        return None
    metadata = {
        "allowed_usernames": list(rule.get("tradingview_usernames", [])),
        "resolved_username": username,
        "message_id": str(message.get("message_id", "")).strip(),
        "delivery_text": truncate(str(message.get("delivery_text") or message.get("text_excerpt") or message.get("preview") or ""), 3500),
    }
    return SignalCandidate(
        ruleset_id=ruleset_id,
        ruleset_title=ruleset_title,
        rule_id=str(rule.get("id")),
        source_type="email",
        source_id=str(rule.get("source_id")),
        external_ref=str(message.get("message_id", "")).strip(),
        occurred_at=str(message.get("timestamp", "")),
        captured_at=utc_now_iso(),
        author=str(message.get("from_name") or message.get("from_email") or message.get("sender_domain") or "TradingView"),
        subject=str(message.get("subject", "")).strip() or "(no subject)",
        excerpt=truncate(str(message.get("text_excerpt") or message.get("preview") or ""), 700),
        tags=[str(tag) for tag in rule.get("tags", []) if str(tag).strip()],
        metadata=metadata,
    )


def match_telegram_rule(*, ruleset_id: str, ruleset_title: str, rule: dict, message: dict) -> SignalCandidate | None:
    text = str(message.get("text", "")).strip()
    has_video = bool(message.get("has_video", False))
    if not text and not has_video:
        return None
    kind = str(rule.get("kind", "")).strip()
    if kind == "hashtag":
        if not any(re.search(HASHTAG_RE_TEMPLATE.format(tag=re.escape(tag)), text, flags=re.IGNORECASE) for tag in rule.get("hashtags", [])):
            return None
    elif kind == "author_keywords":
        sender_id = int(message.get("sender_id") or 0)
        allowed_sender_ids = {int(v) for v in rule.get("sender_ids", [])}
        if sender_id not in allowed_sender_ids:
            return None
        if not match_keywords(text, rule.get("keywords", [])):
            return None
    elif kind == "content_keywords":
        if rule.get("require_video") and not has_video:
            return None
        if not match_keywords(text, rule.get("keywords", [])):
            return None
    else:
        return None
    return SignalCandidate(
        ruleset_id=ruleset_id,
        ruleset_title=ruleset_title,
        rule_id=str(rule.get("id")),
        source_type="telegram",
        source_id=str(rule.get("source_id")),
        external_ref=f"{message.get('chat_id')}:{message.get('message_id')}",
        occurred_at=str(message.get("timestamp", "")),
        captured_at=utc_now_iso(),
        author=str(message.get("author") or "Telegram"),
        subject=str(message.get("chat_name") or "Telegram"),
        excerpt=truncate(text, 700),
        tags=[str(tag) for tag in rule.get("tags", []) if str(tag).strip()],
        metadata={
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
            "sender_id": message.get("sender_id"),
            "has_video": has_video,
            "delivery_text": truncate(str(message.get("delivery_text") or text or ""), 3500),
            "message_link": build_telegram_message_link(
                chat_id=message.get("chat_id"),
                message_id=message.get("message_id"),
                chat_username=message.get("chat_username"),
            ),
        },
    )


def local_event_from_candidate(
    candidate: SignalCandidate,
    *,
    event_id: str,
    topic_name: str,
) -> SignalEvent | None:
    if candidate.source_type == "email" and candidate.metadata.get("needs_llm_username_resolution"):
        return None
    title_subject = candidate.subject if candidate.subject and candidate.subject != "(no subject)" else candidate.author
    summary = candidate.excerpt.strip().replace("\n", " ")
    if len(summary) > 220:
        summary = summary[:219].rstrip() + "…"
    return SignalEvent(
        event_id=event_id,
        ruleset_id=candidate.ruleset_id,
        rule_id=candidate.rule_id,
        source_type=candidate.source_type,
        source_id=candidate.source_id,
        external_ref=candidate.external_ref,
        occurred_at=candidate.occurred_at,
        captured_at=candidate.captured_at,
        author=candidate.author,
        title=title_subject[:120],
        summary=summary or candidate.subject or candidate.author,
        source_link=str(candidate.metadata.get("message_link") or ""),
        source_excerpt=candidate.excerpt[:700],
        delivery_text=truncate(str(candidate.metadata.get("delivery_text") or candidate.excerpt or ""), 3500),
        source_chat_id=int(candidate.metadata.get("chat_id") or 0) if candidate.source_type == "telegram" else 0,
        source_message_id=int(candidate.metadata.get("message_id") or 0) if candidate.source_type == "telegram" else 0,
        tags=list(dict.fromkeys(candidate.tags)),
        confidence=0.76,
        telegram_topic=topic_name,
    )
