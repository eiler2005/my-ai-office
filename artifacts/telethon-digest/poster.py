"""
Render and post structured digests to Telegram.
"""
from __future__ import annotations

import logging
import os
import re
from html import escape

import aiohttp

from models import DigestDocument, DigestItem, DigestSection, ModelMeta, friendly_model

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPERGROUP_ID = int(os.environ["DIGEST_SUPERGROUP_ID"])
TOPIC_ID = int(os.environ["DIGEST_TOPIC_ID"])

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_MSG_LEN = 3900

_ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "a",
    "code",
    "pre",
}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)


def _sanitize_html(text: str) -> str:
    def _replace(match: re.Match) -> str:
        slash, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
        if tag not in _ALLOWED_TAGS:
            return ""
        if tag == "a" and not slash:
            return f"<a{attrs}>"
        return f"<{slash}{tag}>"

    return _TAG_RE.sub(_replace, text)


def _model_line(meta: ModelMeta) -> str:
    if meta.local_fallback:
        return "<i>local deterministic fallback · no LLM</i>"

    parts = [meta.tier, friendly_model(meta.model_id)]
    if meta.provider_fallback:
        parts.append("fallback")
    if meta.prompt_tokens > 0 and meta.completion_tokens > 0:
        total = meta.prompt_tokens + meta.completion_tokens
        parts.append(f"{round(meta.completion_tokens / total * 100)}% out")
    return f"<i>{' · '.join(parts)}</i>"


def _escape_list(items: list[str]) -> str:
    return ", ".join(escape(item) for item in items if item)


def _pluralize(count: int, one: str, few: str, many: str) -> str:
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if mod10 in {2, 3, 4} and mod100 not in {12, 13, 14}:
        return few
    return many


def _message_count(item: DigestItem) -> int:
    return 1 + len(item.extra_post_urls)


def _section_message_count(section: DigestSection) -> int:
    return sum(_message_count(item) for item in section.items)


def _section_channel_count(section: DigestSection) -> int:
    return len(section.items)


def _summary_text(value: str) -> str:
    text = re.sub(r"https?://\S+", " ", value or "")
    text = re.sub(r"www\.\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return escape(text)


def _render_lead_line(value: str) -> str:
    raw = re.sub(r"\s+", " ", value or "").strip()
    match = re.match(r"^([^:]{2,80}):\s*(.+)$", raw)
    if not match:
        return f"• {_summary_text(raw)}"
    channel, summary = match.group(1), match.group(2)
    return f"• <b>{escape(channel)}</b>: {_summary_text(summary)}"


def _lead_candidates(document: DigestDocument) -> list[DigestItem]:
    candidates = [*document.must_read, *document.new_glance]
    for section in document.sections:
        candidates.extend(section.items)
    return candidates


def _normalized_terms(value: str) -> set[str]:
    return {
        item.casefold()
        for item in re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", value or "")
        if item
    }


def _item_urls(item: DigestItem) -> set[str]:
    return {url for url in [item.post_url, *item.extra_post_urls] if url}


def _find_lead_item(document: DigestDocument, value: str, used_urls: set[str] | None = None) -> DigestItem | None:
    used_urls = used_urls or set()
    raw = re.sub(r"\s+", " ", value or "").strip()
    match = re.match(r"^([^:]{2,80}):\s*(.+)$", raw)
    candidates = [item for item in _lead_candidates(document) if not (_item_urls(item) & used_urls)]
    for item in candidates:
        if match and item.channel == match.group(1).strip() and item.summary == match.group(2).strip():
            return item

    lead_terms = _normalized_terms(raw)
    scored: list[tuple[float, DigestItem]] = []
    for item in candidates:
        item_text = f"{item.channel} {item.summary} {' '.join(item.also_mentioned)}"
        item_terms = _normalized_terms(item_text)
        overlap = len(lead_terms & item_terms)
        if not overlap:
            continue
        channel_bonus = 2 if item.channel.casefold() in raw.casefold() else 0
        scored.append((overlap + channel_bonus, item))
    if scored:
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored[0][0] >= 2:
            return scored[0][1]

    return candidates[0] if candidates else None


def _render_post_links(item: DigestItem) -> str:
    urls = [item.post_url, *item.extra_post_urls]
    arrows = [f'<a href="{escape(url, quote=True)}">→</a>' for url in urls if url]
    if not arrows:
        return ""
    if len(arrows) == 1:
        return f" {arrows[0]}"
    return f" ({', '.join(arrows)})"


def _render_item(item: DigestItem) -> str:
    prefix = "📌 " if item.pinned else ""
    message_count = _message_count(item)
    channel = (
        f"<b>{escape(item.channel)}</b> "
        f"<i>· {message_count} {_pluralize(message_count, 'сообщение', 'сообщения', 'сообщений')}</i>"
    )
    summary = _summary_text(item.summary)
    links = _render_post_links(item)
    return f"{prefix}{channel}\n{summary}{links}"


def _render_section_header(section: DigestSection) -> str:
    folder = escape(section.folder)
    channels = _section_channel_count(section)
    messages = _section_message_count(section)
    counts = (
        f" <i>· {channels} {_pluralize(channels, 'канал', 'канала', 'каналов')} "
        f"/ {messages} {_pluralize(messages, 'сообщение', 'сообщения', 'сообщений')}</i>"
    )
    if section.folder_link:
        return f'📁 <a href="{escape(section.folder_link, quote=True)}">{folder}</a>{counts}'
    return f"📁 <b>{folder}</b>{counts}"


def _render_item_list(items: list[DigestItem]) -> list[str]:
    return [_render_item(item) for item in items]


def _render_section(section: DigestSection) -> list[str]:
    lines = [_render_section_header(section)]
    for idx, item in enumerate(section.items):
        if idx:
            lines.append("")
        lines.append(_render_item(item))
    return lines


def _shown_post_count(document: DigestDocument) -> int:
    seen: set[str] = set()
    for item in document.new_glance:
        if item.post_url:
            seen.add(item.post_url)
        for extra_url in item.extra_post_urls:
            seen.add(extra_url)
    for item in document.must_read:
        if item.post_url:
            seen.add(item.post_url)
        for extra_url in item.extra_post_urls:
            seen.add(extra_url)
    for section in document.sections:
        for item in section.items:
            if item.post_url:
                seen.add(item.post_url)
            for extra_url in item.extra_post_urls:
                seen.add(extra_url)
    return len(seen)


def _story_count(document: DigestDocument) -> int:
    section_items = sum(len(section.items) for section in document.sections)
    if section_items:
        return section_items
    return len(document.must_read) + len(document.new_glance)


def _render_themes(document: DigestDocument) -> list[str]:
    title = "Пульс дня"
    if not document.themes:
        return []
    return ["", f"<b>{title}</b>", *[f"• {escape(item)}" for item in document.themes]]


def _render_footer(document: DigestDocument) -> list[str]:
    shown_posts = _shown_post_count(document)
    reserve = max(document.stats.posts_selected - shown_posts, 0)
    lines = [
        "",
        "<b>Итоги</b>",
        (
            f"• Просмотрено <b>{document.stats.new_posts_seen}</b> новых постов "
            f"из <b>{document.stats.channels_in_scope}</b> каналов в скоупе."
        ),
        (
            f"• В выпуск вошло <b>{_story_count(document)}</b> сюжетов и "
            f"<b>{shown_posts}</b> прямых ссылок на посты; в резерве осталось около "
            f"<b>{reserve}</b> сигналов."
        ),
    ]
    if document.quiet_folders:
        quiet_parts = []
        for folder in document.quiet_folders:
            messages = document.stats.folder_message_counts.get(folder, 0)
            channels = document.stats.folder_channel_counts.get(folder, 0)
            if messages > 0:
                quiet_parts.append(
                    f"<b>{escape(folder)}</b> "
                    f"({channels} {_pluralize(channels, 'канал', 'канала', 'каналов')} / "
                    f"{messages} {_pluralize(messages, 'сообщение', 'сообщения', 'сообщений')})"
                )
        if quiet_parts:
            lines.append(f"• Активные папки вне финального обзора: {', '.join(quiet_parts)}.")
    return lines


def render_digest_html(document: DigestDocument) -> str:
    active_channels = document.stats.active_channels_seen or document.stats.channels_in_scope
    lines = [
        (
            f"📊 <b>{escape(document.title)}</b> | {escape(document.period_label)} "
            f"({active_channels} {_pluralize(active_channels, 'канал', 'канала', 'каналов')}, "
            f"обработано {document.stats.new_posts_seen} "
            f"{_pluralize(document.stats.new_posts_seen, 'сообщение', 'сообщения', 'сообщений')}, "
            f"в выпуске {document.stats.posts_selected} "
            f"{_pluralize(document.stats.posts_selected, 'пост', 'поста', 'постов')})"
        ),
    ]

    if document.digest_type == "editorial" and document.executive_summary:
        lines.append("")
        lines.append("<b>Резюме дня</b>")
        lines.extend(f"• {escape(item)}" for item in document.executive_summary)

    if document.lead:
        lines.append("")
        lines.append("🧭 <b>Главное</b>")
        used_lead_urls: set[str] = set()
        for item in document.lead:
            lead_line = _render_lead_line(item)
            lead_item = _find_lead_item(document, item, used_urls=used_lead_urls)
            if lead_item:
                lead_line += _render_post_links(lead_item)
                used_lead_urls.update(_item_urls(lead_item))
            lines.append(lead_line)

    lines.extend(_render_themes(document))

    if document.new_glance:
        lines.append("")
        lines.append(
            f"✨ <b>Новое</b> <i>· обработано {document.stats.new_posts_seen} "
            f"{_pluralize(document.stats.new_posts_seen, 'сообщение', 'сообщения', 'сообщений')}</i>"
        )
        for idx, item in enumerate(document.new_glance):
            if idx:
                lines.append("")
            lines.append(_render_item(item))

    if document.must_read and document.digest_type in {"morning", "editorial"}:
        lines.append("")
        lines.append("<b>Must read</b>")
        lines.extend(_render_item_list(document.must_read))

    if document.sections:
        lines.append("")
        lines.append("🗂 <b>Папки</b>")
        for idx, section in enumerate(document.sections):
            if idx:
                lines.append("")
            lines.extend(_render_section(section))

    if document.low_signal:
        lines.append("")
        lines.append("<b>Low signal</b>")
        lines.extend(f"• {escape(item)}" for item in document.low_signal)

    if document.watchpoints:
        lines.append("")
        lines.append("<b>Watchpoints</b>")
        lines.extend(f"• {escape(item)}" for item in document.watchpoints)

    lines.extend(_render_footer(document))

    lines.append("")
    lines.append(_model_line(document.model_meta))
    return _sanitize_html("\n".join(lines).strip())


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if len(block) > MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(block), MAX_MSG_LEN):
                chunks.append(block[start : start + MAX_MSG_LEN].strip())
            continue
        if len(current) + len(block) > MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
            current = block
        else:
            current += block
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _apply_part_headers(chunks: list[str]) -> list[str]:
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"<b>Часть {idx}/{total}</b>\n\n{chunk}" for idx, chunk in enumerate(chunks, start=1)]


async def post_digest(document: DigestDocument) -> bool:
    from benka_integrations.legacy_delivery import post_text
    for chunk in _apply_part_headers(_split_text(render_digest_html(document))):
        await post_text(chunk, chat_id=SUPERGROUP_ID, topic_id=TOPIC_ID)
    return True
