"""
Telegram posting helpers for signals mini-batches.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from models import Last30DaysDigest, ModelMeta, SignalEvent

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPERGROUP_ID = int(os.environ["SIGNALS_SUPERGROUP_ID"])
TOPIC_ID = int(os.environ.get("SIGNALS_TOPIC_ID", "0") or 0)
TIMEZONE = ZoneInfo(os.environ.get("SIGNALS_TIMEZONE", "Europe/Moscow"))

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_MSG_LEN = 3900

_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre"}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)


def _sanitize_html(text: str) -> str:
    def _replace(match: re.Match) -> str:
        slash, tag = match.group(1), match.group(2).lower()
        if tag not in _ALLOWED_TAGS:
            return ""
        return f"<{slash}{tag}>"

    return _TAG_RE.sub(_replace, text)


def _fmt_dt(value: str) -> str:
    try:
        current = datetime.fromisoformat(value)
    except ValueError:
        return value
    return current.astimezone(TIMEZONE).strftime("%d.%m %H:%M")


def _model_line(meta: ModelMeta) -> str:
    parts = [meta.tier, meta.model_id]
    if meta.provider_fallback:
        parts.append("fallback")
    if meta.local_fallback:
        parts.append("local")
    return f"<i>{' · '.join(parts)}</i>"


def _compact_excerpt(text: str, limit: int = 420) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def render_batch(*, ruleset_title: str, events: list[SignalEvent], model_meta: ModelMeta) -> str:
    lines = [
        f"📡 <b>{escape(ruleset_title)}</b> | {len(events)} {_pluralize(len(events), 'сигнал', 'сигнала', 'сигналов')}",
    ]
    for event in sorted(events, key=lambda item: item.occurred_at):
        source_label = "email" if event.source_type == "email" else "telegram"
        tags = ", ".join(escape(tag) for tag in event.tags[:4])
        body_text = _compact_excerpt(event.source_excerpt or event.summary)
        lines.append("")
        lines.append(
            f"• <b>{escape(event.title)}</b> <i>[{escape(source_label)} · {_fmt_dt(event.occurred_at)}]</i>"
        )
        lines.append(f"{escape(body_text)}")
        if event.source_type == "telegram" and event.source_link:
            lines.append(f"<i>Ссылка:</i> {escape(event.source_link)}")
        meta_line = f"<i>{escape(event.author)}"
        if tags:
            meta_line += f" · {tags}"
        meta_line += f" · conf {event.confidence:.2f}</i>"
        lines.append(meta_line)
    lines.append("")
    lines.append(_model_line(model_meta))
    return _sanitize_html("\n".join(lines).strip())


def _pluralize(count: int, one: str, few: str, many: str) -> str:
    n = abs(count) % 100
    if 10 < n < 20:
        return many
    n %= 10
    if n == 1:
        return one
    if 1 < n < 5:
        return few
    return many


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if len(current) + len(block) > MAX_MSG_LEN and current:
            chunks.append(current.strip())
            current = block
        else:
            current += block
    if current.strip():
        chunks.append(current.strip())
    return chunks


_CATEGORY_EMOJI = {
    "Big Tech & AI": "🤖",
    "Markets / Regulation / Geopolitics": "📈",
    "Open Source / Builders": "🛠",
    "Science / Hardware": "🔬",
    "Startups / Deals": "💼",
    "Consumer Platforms": "📱",
    "Creator / Media": "🎬",
    "World / Culture": "🌐",
}

SUPPRESS_ERROR_SOURCES: set[str] = set()

_PLATFORM_LABELS = {
    "reddit": "Reddit",
    "hn": "Hacker News",
    "hackernews": "Hacker News",
    "x": "X",
    "bluesky": "Bluesky",
    "github": "GitHub",
    "youtube": "YouTube",
    "polymarket": "Polymarket",
    "web": "Web",
}

_PLATFORM_EMOJI = {
    "reddit": "👽",
    "hn": "🟠",
    "hackernews": "🟠",
    "x": "𝕏",
    "bluesky": "🦋",
    "github": "🐙",
    "youtube": "▶️",
    "polymarket": "📊",
    "web": "🌐",
}


def render_last30days_digest(digest: Last30DaysDigest) -> str:
    if digest.profile == "platform-pulse":
        return _render_platform_pulse_digest(digest)
    return _render_personal_feed_digest(digest)


def _render_personal_feed_digest(digest: Last30DaysDigest) -> str:
    try:
        dt = datetime.fromisoformat(digest.generated_at).astimezone(TIMEZONE)
        date_label = dt.strftime("%-d %b")
    except (ValueError, AttributeError):
        date_label = digest.generated_at[:10]

    lines = [
        f"🌍 <b>{escape(digest.display_name)} · {date_label}</b>  <code>{escape(_digest_tag(digest))}</code>  |  {digest.successful_queries}/{digest.total_queries}  |  {_source_coverage_line(digest.source_counts)}",
    ]

    for section in digest.category_sections:
        if not section.themes:
            continue
        emoji = _CATEGORY_EMOJI.get(section.category, "•")
        lines.append("")
        lines.append(f"{emoji} <b>{escape(section.category)}</b>")
        for index, theme in enumerate(section.themes[:4], start=1):
            source_badge = ""
            if theme.sources:
                source_badge = f" <i>[{' · '.join(escape(s) for s in theme.sources[:3])}]</i>"
            # Collapse newlines in title — multiline tweets break <b> tag splitting
            title_clean = " ".join(escape(theme.title).split())
            lines.append("")
            lines.append(f"{index}. <b>{title_clean}</b>{source_badge}")
            if theme.snippet:
                lines.append(escape(_compact_excerpt(theme.snippet, limit=200)))
            if theme.url:
                lines.append(theme.url)

    if digest.errors_by_source:
        visible_errors = {s: e for s, e in digest.errors_by_source.items() if s not in SUPPRESS_ERROR_SOURCES}
        if visible_errors:
            lines.append("")
            lines.append("<i>Частичные пробелы:</i>")
            for source, error in list(visible_errors.items())[:3]:
                lines.append(escape(f"{source}: {error[:120]}"))

    return _sanitize_html("\n".join(lines).strip())


def _render_platform_pulse_digest(digest: Last30DaysDigest) -> str:
    try:
        dt = datetime.fromisoformat(digest.generated_at).astimezone(TIMEZONE)
        date_label = dt.strftime("%-d %b")
    except (ValueError, AttributeError):
        date_label = digest.generated_at[:10]

    lines = [
        f"🧭 <b>{escape(digest.display_name)} · {date_label}</b>  <code>{escape(_digest_tag(digest))}</code>  |  {digest.successful_queries}/{digest.total_queries}",
        f"<i>Core: {escape(', '.join(_platform_display_name(source) for source in digest.core_sources) or 'none')}</i>",
    ]
    if digest.experimental_sources:
        lines.append(f"<i>Experimental: {escape(', '.join(_platform_display_name(source) for source in digest.experimental_sources))}</i>")

    for section in digest.platform_sections:
        emoji = _PLATFORM_EMOJI.get(section.platform, "•")
        platform_name = _platform_display_name(section.platform)
        lines.append("")
        lines.append(f"{emoji} <b>{escape(platform_name)}</b>  <i>({section.post_count} posts)</i>")
        if section.repeat_filtered_count and section.themes:
            lines.append(f"<i>{section.repeat_filtered_count} repeats hidden from the prior 7 days.</i>")
        if not section.themes:
            if section.repeat_filtered_count and section.raw_post_count:
                lines.append(f"<i>All {section.raw_post_count} posts repeated from the prior 7 days.</i>")
                continue
            lines.append("<i>No surfaced stories in this run.</i>")
            continue
        for index, theme in enumerate(section.themes, start=1):
            title_clean = " ".join(escape(theme.title).split())
            lines.append("")
            lines.append(f"{index}. <b>{title_clean}</b>")
            if theme.url:
                lines.append(theme.url)
            if theme.snippet:
                lines.append(escape(_compact_excerpt(theme.snippet, limit=220)))

    if digest.errors_by_source:
        visible_errors = {s: e for s, e in digest.errors_by_source.items() if s not in SUPPRESS_ERROR_SOURCES}
        if visible_errors:
            lines.append("")
            lines.append("<i>Partial gaps:</i>")
            for source, error in list(visible_errors.items())[:4]:
                lines.append(escape(f"{_platform_display_name(source)}: {error[:120]}"))

    return _sanitize_html("\n".join(lines).strip())


def _source_coverage_line(source_counts: dict[str, int]) -> str:
    if not source_counts:
        return "no source coverage"
    parts = [f"{source}:{count}" for source, count in list(source_counts.items())[:5]]
    return "sources " + ", ".join(parts)


def _digest_tag(digest: Last30DaysDigest) -> str:
    tag = (digest.profile or digest.canonical_preset_id or "").strip().lower()
    if tag.endswith("-v1"):
        tag = tag[:-3]
    return tag or "last30days"


def _platform_display_name(source: str) -> str:
    return _PLATFORM_LABELS.get(source, source)


def _resolve_target(chat_id: int | None, topic_id: int | None) -> tuple[int, int]:
    resolved_chat_id = int(chat_id if chat_id is not None else SUPERGROUP_ID)
    resolved_topic_id = int(topic_id if topic_id is not None else TOPIC_ID)
    return resolved_chat_id, resolved_topic_id


async def _telegram_json_request(method: str, payload: dict) -> bool:
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/{method}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error("Telegram API error on %s: %s", method, data)
                    return False
    except Exception as exc:
        logger.error("Failed Telegram API call %s: %s", method, exc)
        return False
    return True


async def _telegram_form_request(method: str, form_data) -> bool:
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/{method}",
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error("Telegram API error on %s: %s", method, data)
                    return False
    except Exception as exc:
        logger.error("Failed Telegram API form call %s: %s", method, exc)
        return False
    return True


async def post_html_message(text: str, *, chat_id: int | None = None, topic_id: int | None = None) -> bool:
    from benka_integrations.legacy_delivery import post_text
    chat, topic = _resolve_target(chat_id, topic_id)
    for chunk in _split_text(text):
        await post_text(chunk, chat_id=chat, topic_id=topic)
    return True


async def post_plain_text_message(text: str, *, chat_id: int | None = None, topic_id: int | None = None) -> bool:
    from benka_integrations.legacy_delivery import post_text
    chat, topic = _resolve_target(chat_id, topic_id)
    for chunk in _split_text(text):
        await post_text(chunk, chat_id=chat, topic_id=topic, html=False)
    return True


async def copy_message(
    *,
    from_chat_id: int,
    message_id: int,
    chat_id: int | None = None,
    topic_id: int | None = None,
) -> bool:
    # Native Hermes has no copyMessage verb. Fetch source content through
    # Telethon and publish it through the common receipt-aware sender.
    return False


async def post_binary_message(
    *,
    method: str,
    field_name: str,
    data: bytes,
    filename: str,
    caption: str = "",
    content_type: str = "application/octet-stream",
    chat_id: int | None = None,
    topic_id: int | None = None,
) -> bool:
    from benka_integrations.legacy_delivery import post_media
    resolved_chat_id, resolved_topic_id = _resolve_target(chat_id, topic_id)
    return await post_media(data, filename=filename, caption=caption,
                            chat_id=resolved_chat_id, topic_id=resolved_topic_id,
                            document=method != "sendPhoto")


async def post_photo_message(
    *,
    data: bytes,
    filename: str = "telegram-photo.jpg",
    caption: str = "",
    chat_id: int | None = None,
    topic_id: int | None = None,
) -> bool:
    return await post_binary_message(
        method="sendPhoto",
        field_name="photo",
        data=data,
        filename=filename,
        caption=caption,
        content_type="image/jpeg",
        chat_id=chat_id,
        topic_id=topic_id,
    )


async def post_document_message(
    *,
    data: bytes,
    filename: str = "telegram-document.bin",
    caption: str = "",
    content_type: str = "application/octet-stream",
    chat_id: int | None = None,
    topic_id: int | None = None,
) -> bool:
    return await post_binary_message(
        method="sendDocument",
        field_name="document",
        data=data,
        filename=filename,
        caption=caption,
        content_type=content_type,
        chat_id=chat_id,
        topic_id=topic_id,
    )
