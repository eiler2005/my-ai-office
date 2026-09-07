#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
MODE="${1:---dry-run}"
MESSAGE_LIMIT="${MESSAGE_LIMIT:-0}"
BATCH_SIZE="${BATCH_SIZE:-50}"
RESUME_IMPORTED="${RESUME_IMPORTED:-1}"
START_INDEX="${START_INDEX:-1}"
IMPORT_RETRY_COUNT="${IMPORT_RETRY_COUNT:-4}"
IMPORT_RETRY_DELAY="${IMPORT_RETRY_DELAY:-2}"
EXCLUDE_SOURCE_TITLES="${EXCLUDE_SOURCE_TITLES:-}"
ESCAPED_EXCLUDE_SOURCE_TITLES="$(printf '%q' "$EXCLUDE_SOURCE_TITLES")"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

case "$MODE" in
  --dry-run)
    APPLY=0
    ;;
  --apply)
    APPLY=1
    ;;
  *)
    echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0 [--dry-run|--apply]" >&2
    exit 1
    ;;
esac

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "BACKFILL_APPLY=${APPLY} BACKFILL_LIMIT=${MESSAGE_LIMIT} BACKFILL_BATCH_SIZE=${BATCH_SIZE} BACKFILL_RESUME_IMPORTED=${RESUME_IMPORTED} BACKFILL_START_INDEX=${START_INDEX} BACKFILL_IMPORT_RETRY_COUNT=${IMPORT_RETRY_COUNT} BACKFILL_IMPORT_RETRY_DELAY=${IMPORT_RETRY_DELAY} BACKFILL_EXCLUDE_SOURCE_TITLES=${ESCAPED_EXCLUDE_SOURCE_TITLES} bash -s" <<'REMOTE'
set -euo pipefail
cd /opt/telethon-digest

sudo docker compose run --rm -T \
  -e BACKFILL_APPLY="${BACKFILL_APPLY}" \
  -e BACKFILL_LIMIT="${BACKFILL_LIMIT}" \
  -e BACKFILL_BATCH_SIZE="${BACKFILL_BATCH_SIZE}" \
  -e BACKFILL_RESUME_IMPORTED="${BACKFILL_RESUME_IMPORTED}" \
  -e BACKFILL_START_INDEX="${BACKFILL_START_INDEX}" \
  -e BACKFILL_IMPORT_RETRY_COUNT="${BACKFILL_IMPORT_RETRY_COUNT}" \
  -e BACKFILL_IMPORT_RETRY_DELAY="${BACKFILL_IMPORT_RETRY_DELAY}" \
  -e BACKFILL_EXCLUDE_SOURCE_TITLES="${BACKFILL_EXCLUDE_SOURCE_TITLES}" \
  -v /opt/wiki-import:/host-wiki-import:ro \
  -v /opt/obsidian-vault:/host-vault \
  telethon-digest \
  sh -s <<'SH'
cp /app/sessions/telethon_digest.session /tmp/telethon_backfill.session 2>/dev/null || true
cp /app/sessions/telethon_digest.session-journal /tmp/telethon_backfill.session-journal 2>/dev/null || true
python - <<'PY'
import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import timezone
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Message, MessageEntityTextUrl, MessageEntityUrl


load_dotenv("/app/telethon.env", override=False)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_PATH = "/tmp/telethon_backfill.session"
BACKFILL_APPLY = os.environ.get("BACKFILL_APPLY", "0") == "1"
BACKFILL_LIMIT = int(os.environ.get("BACKFILL_LIMIT", "0") or 0)
BATCH_SIZE = max(1, int(os.environ.get("BACKFILL_BATCH_SIZE", "50") or 50))
RESUME_IMPORTED = os.environ.get("BACKFILL_RESUME_IMPORTED", "1") != "0"
START_INDEX = max(1, int(os.environ.get("BACKFILL_START_INDEX", "1") or 1))
IMPORT_RETRY_COUNT = max(1, int(os.environ.get("BACKFILL_IMPORT_RETRY_COUNT", "4") or 4))
IMPORT_RETRY_DELAY = max(1, int(os.environ.get("BACKFILL_IMPORT_RETRY_DELAY", "2") or 2))
EXCLUDED_SOURCE_TITLES = {
    item.strip()
    for item in os.environ.get("BACKFILL_EXCLUDE_SOURCE_TITLES", "").split(",")
    if item.strip()
}
TOKEN = ""
for line in Path("/host-wiki-import/wiki-import.env").read_text(encoding="utf-8").splitlines():
    if line.startswith("WIKI_IMPORT_TOKEN="):
        TOKEN = line.split("=", 1)[1].strip()
        break
if not TOKEN:
    raise SystemExit("WIKI_IMPORT_TOKEN is missing")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_USER_ID = int(BOT_TOKEN.split(":", 1)[0]) if ":" in BOT_TOKEN else 0
WIKI_IMPORT_URL = "http://wiki-import:8095/trigger"
TARGETS = [
    {"title": "Denis_AI", "chat_id": -1002184750950, "kind": "channel"},
    {"title": "Denis_ToolsForLife", "chat_id": -1002165329155, "kind": "channel"},
    {"title": "Denis_interesting", "chat_id": -1002244976114, "kind": "channel"},
    {"title": "Denis_Faang", "chat_id": -1002176413529, "kind": "channel"},
    {"title": "Saved Messages", "chat_id": "me", "kind": "saved_messages"},
]
if EXCLUDED_SOURCE_TITLES:
    TARGETS = [item for item in TARGETS if item["title"] not in EXCLUDED_SOURCE_TITLES]
HIGH_SIGNAL_TITLE_MARKERS = (
    "architecture",
    "memory",
    "metrics",
    "evaluation",
    "retrieval",
    "taxonomy",
    "framework",
)
HIGH_SIGNAL_TITLE_PAIRS = (
    ("llm", "rules"),
    ("llm", "memory"),
    ("llm", "metrics"),
    ("agent", "architecture"),
    ("agents", "architecture"),
)
HIGH_SIGNAL_BODY_MARKERS = (
    "arxiv.org",
    "taxonomy",
    "benchmark",
    "evaluation",
    "retrieval",
    "memory",
    "architecture",
    "grammar",
)
LOG_PATH = Path("/host-vault/wiki/LOG.md")
IMPORT_QUEUE_PATH = Path("/host-vault/wiki/IMPORT-QUEUE.md")
RESEARCH_ROOT = Path("/host-vault/wiki/research")
LEDGER_ROOT = Path("/host-vault/.ingest-ledgers")
LEDGER_PATH = LEDGER_ROOT / "telegram-post-imports.jsonl"


def _utc_iso(message: Message) -> str:
    return message.date.astimezone(timezone.utc).isoformat()


def extract_urls(message: Message) -> list[str]:
    text = message.raw_text or ""
    urls: list[str] = []
    for entity in message.entities or []:
        if isinstance(entity, MessageEntityTextUrl) and entity.url:
            urls.append(entity.url.strip())
        elif isinstance(entity, MessageEntityUrl):
            chunk = text[entity.offset : entity.offset + entity.length].strip()
            if chunk:
                urls.append(chunk)
    urls.extend(re.findall(r"https?://\S+", text))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        cleaned = normalize_url(url)
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped


def normalize_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip(").,]")
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    query_pairs = [
        item
        for item in (parsed.query or "").split("&")
        if item and not item.startswith("utm_")
    ]
    query = "&".join(sorted(query_pairs))
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    return normalized


def normalize_score_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def humanize_url_title(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for part in reversed(parts):
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", " ", part).strip(" -_")
        if cleaned and cleaned.lower() not in {"tpost", "library"}:
            return re.sub(r"[_-]+", " ", cleaned).strip().title()
    host = parsed.netloc.replace("www.", "").split(":")[0]
    return re.sub(r"[^A-Za-z0-9]+", " ", host).strip().title()


def first_title_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped and not stripped.startswith("- telegram_") and stripped != "Content":
            return stripped[:140]
    return ""


def build_title(message: Message, source_type: str, source: str, source_title: str) -> str:
    date_part = message.date.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if source_type == "url":
        return f"{source_title} {date_part} - {humanize_url_title(source)}"
    base = first_title_line(message.raw_text or source)
    slug_seed = re.sub(r"[^a-z0-9-]+", "", re.sub(r"[_\\s]+", "-", base.lower())) if base else ""
    if slug_seed and not slug_seed.isdigit():
        return f"{source_title} {date_part} #{message.id} - {base[:96]}"
    return f"{source_title} {date_part} #{message.id}"


def render_text_source(message: Message, source_meta: dict, urls: list[str], title: str) -> str:
    text = (message.raw_text or "").strip()
    source_chat_label = source_meta["title"]
    lines = [
        f"# {title}",
        "",
        "## Content",
        "",
        text or "_No text body. Imported for provenance._",
        "",
        "## Telegram Provenance",
        "",
        f"- source_chat_title: {source_chat_label}",
        f"- source_chat_id: {source_meta['chat_id']}",
        f"- source_kind: {source_meta['kind']}",
        f"- message_id: {message.id}",
        f"- post_date_utc: {_utc_iso(message)}",
        f"- forwarded: {'yes' if getattr(message, 'fwd_from', None) else 'no'}",
    ]
    if getattr(message, "grouped_id", None):
        lines.append(f"- grouped_id: {message.grouped_id}")
    if urls:
        lines.append(f"- related_urls: {', '.join(urls)}")
    return "\n".join(lines).strip() + "\n"


def render_url_fallback_source(item: dict, error_text: str) -> str:
    lines = [
        f"# {item['title']}",
        "",
        "## Source URL",
        "",
        str(item["source"]).strip(),
        "",
        "## Import Note",
        "",
        "Primary URL import failed, so this page preserves the source link and Telegram provenance as a wiki-first artifact.",
        "",
        f"- fallback_reason: {error_text}",
        "",
        "## Telegram Provenance",
        "",
        f"- source_chat_title: {item['source_title']}",
        f"- source_chat_id: {item['chat_id']}",
        f"- source_kind: {item['source_kind']}",
        f"- message_id: {item['message_id']}",
        f"- post_date_utc: {item['date']}",
        f"- original_url: {item['source']}",
    ]
    return "\n".join(lines).strip() + "\n"


def classify_candidate(message: Message, source_meta: dict) -> tuple[str, str] | None:
    text = (message.raw_text or "").strip()
    urls = extract_urls(message)
    if not text and not urls:
        return None
    if urls and (text == urls[0] or (len(text) <= 220 and "\n" not in text and text.count(" ") <= 6)):
        return ("url", urls[0])
    if text or urls:
        title = build_title(message, "text", text, source_meta["title"])
        return ("text", render_text_source(message, source_meta, urls, title))
    return None


def dedupe_key(message: Message, source_type: str, source: str) -> tuple[str, str]:
    urls = extract_urls(message)
    raw_text = normalize_score_text(message.raw_text or "")
    if source_type == "url" and urls:
        return ("url", urls[0])
    if raw_text:
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        return ("text", digest)
    normalized_text = normalize_score_text(source)
    if normalized_text:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        return ("rendered_text", digest)
    return ("telegram_message", f"{message.chat_id}:{message.id}")


def score_candidate_for_promotion(source_type: str, source: str, title: str) -> tuple[int, list[str]]:
    title_lookup = normalize_score_text(title)
    body_lookup = normalize_score_text(source)
    source_lookup = source.lower()
    score = 0
    reasons: list[str] = []
    if source_type == "url":
        score += 1
        reasons.append("url-source")
    if any(marker in title_lookup for marker in HIGH_SIGNAL_TITLE_MARKERS):
        score += 2
        reasons.append("strong-title-marker")
    if any(all(token in title_lookup for token in pair) for pair in HIGH_SIGNAL_TITLE_PAIRS):
        score += 2
        reasons.append("topic-pair")
    if any(marker in body_lookup for marker in HIGH_SIGNAL_BODY_MARKERS) or "arxiv.org" in source_lookup:
        score += 1
        reasons.append("body-signal")
    return score, reasons


def should_auto_promote(source_type: str, source: str, title: str) -> tuple[bool, list[str], int]:
    score, reasons = score_candidate_for_promotion(source_type, source, title)
    return score >= 3, reasons, score


def slugify(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    tokens = [token for token in lowered.strip("-").split("-") if token]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return "-".join(deduped)[:80]


def load_existing_research_slugs() -> set[str]:
    if not RESEARCH_ROOT.exists():
        return set()
    return {path.stem for path in RESEARCH_ROOT.glob("*.md")}


def load_existing_ledger_keys() -> set[str]:
    if not LEDGER_PATH.exists():
        return set()
    keys: set[str] = set()
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(payload.get("ledger_key", "")).strip()
        if key:
            keys.add(key)
    return keys


def ledger_key_for(item: dict) -> str:
    return "|".join(
        [
            str(item.get("source_title", "")).strip(),
            str(item.get("chat_id", "")).strip(),
            str(item.get("message_id", "")).strip(),
            str(item.get("source_type", "")).strip(),
        ]
    )


def append_ledger_entry(item: dict, final_result: dict, ledger_keys: set[str]) -> None:
    ledger_key = ledger_key_for(item)
    if not ledger_key or ledger_key in ledger_keys:
        return
    research_paths = [path for path in final_result.get("wiki_page_paths", []) if str(path).startswith("wiki/research/")]
    record = {
        "ledger_key": ledger_key,
        "logged_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_title": item.get("source_title"),
        "source_kind": item.get("source_kind"),
        "source_chat_id": item.get("chat_id"),
        "message_id": item.get("message_id"),
        "post_date_utc": item.get("date"),
        "source_type": item.get("source_type"),
        "title": item.get("title"),
        "research_path": research_paths[0] if research_paths else "",
        "wiki_page_paths": final_result.get("wiki_page_paths", []),
        "canonical_pages_updated": final_result.get("canonical_pages_updated", []),
        "rag_status": final_result.get("rag_status"),
        "status": final_result.get("status"),
        "capture_mode": "ideas",
        "auto_promote": bool(item.get("auto_promote")),
    }
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    ledger_keys.add(ledger_key)


def load_existing_titles() -> set[str]:
    titles: set[str] = set()
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            marker = " ingest | "
            if line.startswith("## [") and marker in line:
                titles.add(line.split(marker, 1)[1].strip())
    if IMPORT_QUEUE_PATH.exists():
        text = IMPORT_QUEUE_PATH.read_text(encoding="utf-8")
        start = text.find("```json\n")
        end = text.find("\n```", start + 1)
        if start != -1 and end != -1:
            try:
                items = json.loads(text[start + 8 : end])
            except json.JSONDecodeError:
                items = []
            for item in items:
                status = item.get("status")
                has_materialized_page = bool(item.get("research_path"))
                if status == "done" and item.get("title"):
                    titles.add(str(item["title"]).strip())
                elif status == "processing" and has_materialized_page and item.get("title"):
                    titles.add(str(item["title"]).strip())
    return titles


def call_wiki_import(payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        WIKI_IMPORT_URL,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def call_wiki_import_with_retry(payload: dict) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, IMPORT_RETRY_COUNT + 1):
        try:
            return call_wiki_import(payload)
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= IMPORT_RETRY_COUNT:
                break
            time.sleep(IMPORT_RETRY_DELAY * attempt)
    if last_exc is None:
        raise RuntimeError("wiki-import call failed without captured exception")
    raise last_exc


async def load_source_messages(client: TelegramClient, source_meta: dict) -> list[Message]:
    entity_ref = source_meta["chat_id"]
    limit = None if BACKFILL_LIMIT <= 0 else BACKFILL_LIMIT
    loaded = await client.get_messages(entity_ref, limit=limit)
    return [item for item in loaded if isinstance(item, Message)]


async def main() -> None:
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    try:
        all_messages: list[tuple[dict, Message]] = []
        source_counts: dict[str, int] = {}
        for source_meta in TARGETS:
            loaded = await load_source_messages(client, source_meta)
            source_counts[source_meta["title"]] = len(loaded)
            for message in reversed(loaded):
                if source_meta["kind"] != "saved_messages" and not getattr(message, "post", False):
                    continue
                if source_meta["kind"] == "saved_messages" and getattr(message, "from_id", None):
                    user_id = getattr(message.from_id, "user_id", 0)
                    if user_id and user_id == BOT_USER_ID:
                        continue
                all_messages.append((source_meta, message))
    finally:
        await client.disconnect()

    candidates = []
    skipped = []
    dedupe_seen: dict[tuple[str, str], dict] = {}
    dedupe_reasons = Counter()
    existing_titles = load_existing_titles() if RESUME_IMPORTED else set()
    existing_research_slugs = load_existing_research_slugs() if RESUME_IMPORTED else set()
    resume_skipped = 0
    for source_meta, message in all_messages:
        classified = classify_candidate(message, source_meta)
        if not classified:
            skipped.append(
                {
                    "source_title": source_meta["title"],
                    "message_id": message.id,
                    "reason": "not_importable",
                    "date": _utc_iso(message),
                }
            )
            continue
        source_type, source = classified
        title = build_title(message, source_type, source, source_meta["title"])
        dedupe_type, dedupe_value = dedupe_key(message, source_type, source)
        if (dedupe_type, dedupe_value) in dedupe_seen:
            existing = dedupe_seen[(dedupe_type, dedupe_value)]
            dedupe_reasons[dedupe_type] += 1
            skipped.append(
                {
                    "source_title": source_meta["title"],
                    "message_id": message.id,
                    "reason": f"duplicate_{dedupe_type}",
                    "date": _utc_iso(message),
                    "duplicate_of": {
                        "source_title": existing["source_title"],
                        "message_id": existing["message_id"],
                        "date": existing["date"],
                    },
                }
            )
            continue
        auto_promote, promote_reasons, promote_score = should_auto_promote(source_type, source, title)
        candidate = {
            "source_title": source_meta["title"],
            "source_kind": source_meta["kind"],
            "chat_id": source_meta["chat_id"],
            "message_id": message.id,
            "date": _utc_iso(message),
            "source_type": source_type,
            "source": source,
            "title": title,
            "auto_promote": auto_promote,
            "promote_reasons": promote_reasons,
            "promote_score": promote_score,
            "dedupe_type": dedupe_type,
            "import_goal": (
                "Historical Telegram backfill from "
                f"{source_meta['title']} message {message.id} dated {_utc_iso(message)}. "
                "Preserve a source-centric research page first, include the post date in the artifact, "
                "and update canonical pages only when confidence is high."
            ),
            "promotion_import_goal": (
                "Historical Telegram backfill from "
                f"{source_meta['title']} message {message.id} dated {_utc_iso(message)}. "
                "Reuse the existing research page and promote only durable, reusable concepts or "
                "canonical entities supported by the dated source."
            ),
        }
        dedupe_seen[(dedupe_type, dedupe_value)] = {
            "source_title": source_meta["title"],
            "message_id": message.id,
            "date": candidate["date"],
        }
        if title in existing_titles:
            resume_skipped += 1
            skipped.append(
                {
                    "source_title": source_meta["title"],
                    "message_id": message.id,
                    "reason": "already_materialized",
                    "date": _utc_iso(message),
                }
            )
            continue
        expected_research_slug = slugify(title)
        if expected_research_slug and expected_research_slug in existing_research_slugs:
            resume_skipped += 1
            skipped.append(
                {
                    "source_title": source_meta["title"],
                    "message_id": message.id,
                    "reason": "already_materialized_research_slug",
                    "date": _utc_iso(message),
                }
            )
            continue
        candidates.append(candidate)

    if START_INDEX > 1:
        candidates = candidates[START_INDEX - 1 :]

    report = {
        "apply": BACKFILL_APPLY,
        "message_limit_per_source": BACKFILL_LIMIT,
        "batch_size": BATCH_SIZE,
        "resume_imported": RESUME_IMPORTED,
        "start_index": START_INDEX,
        "import_retry_count": IMPORT_RETRY_COUNT,
        "excluded_source_titles": sorted(EXCLUDED_SOURCE_TITLES),
        "sources": source_counts,
        "scanned_total": len(all_messages),
        "candidates": len(candidates),
        "skipped": len(skipped),
        "resume_skipped": resume_skipped,
        "dedupe_summary": dict(dedupe_reasons),
        "candidate_preview": [
            {
                "source_title": item["source_title"],
                "message_id": item["message_id"],
                "date": item["date"],
                "source_type": item["source_type"],
                "title": item["title"],
                "auto_promote": item["auto_promote"],
                "promote_score": item["promote_score"],
            }
            for item in candidates[:25]
        ],
        "skip_preview": skipped[:25],
    }

    if not BACKFILL_APPLY:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    results = []
    ledger_keys = load_existing_ledger_keys()
    for batch_index in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_index : batch_index + BATCH_SIZE]
        for item in batch:
            payload = {
                "source_type": item["source_type"],
                "source": item["source"],
                "target_kind": "auto",
                "title": item["title"],
                "import_goal": item["import_goal"],
                "capture_mode": "ideas",
            }
            try:
                initial = call_wiki_import_with_retry(payload)
                promotion = None
                if bool(initial.get("ok")) and item["auto_promote"]:
                    promotion = call_wiki_import_with_retry(
                        {
                            "source_type": item["source_type"],
                            "source": item["source"],
                            "target_kind": "auto",
                            "title": item["title"],
                            "import_goal": item["promotion_import_goal"],
                            "capture_mode": "promotion",
                            "promote_fingerprint": initial.get("fingerprint", ""),
                        }
                    )
                final_result = promotion or initial
                results.append(
                    {
                        "source_title": item["source_title"],
                        "message_id": item["message_id"],
                        "date": item["date"],
                        "ok": bool(final_result.get("ok")),
                        "status": final_result.get("status"),
                        "rag_status": final_result.get("rag_status"),
                        "wiki_page_paths": final_result.get("wiki_page_paths", []),
                        "canonical_pages_updated": final_result.get("canonical_pages_updated", []),
                        "initial_capture_mode": "ideas",
                        "auto_promote": item["auto_promote"],
                        "promotion_status": promotion.get("status") if promotion else None,
                        "promotion_rag_status": promotion.get("rag_status") if promotion else None,
                    }
                )
                if bool(final_result.get("ok")):
                    append_ledger_entry(item, final_result, ledger_keys)
            except Exception as exc:
                error_text = f"{exc.__class__.__name__}: {exc}"
                if item["source_type"] == "url":
                    try:
                        fallback_result = call_wiki_import_with_retry(
                            {
                                "source_type": "text",
                                "source": render_url_fallback_source(item, error_text),
                                "target_kind": "auto",
                                "title": item["title"],
                                "import_goal": (
                                    f"{item['import_goal']} "
                                    "The original URL fetch failed, so preserve the URL and dated Telegram provenance as the research artifact."
                                ),
                                "capture_mode": "ideas",
                            }
                        )
                        results.append(
                            {
                                "source_title": item["source_title"],
                                "message_id": item["message_id"],
                                "date": item["date"],
                                "ok": bool(fallback_result.get("ok")),
                                "status": fallback_result.get("status"),
                                "rag_status": fallback_result.get("rag_status"),
                                "wiki_page_paths": fallback_result.get("wiki_page_paths", []),
                                "canonical_pages_updated": fallback_result.get("canonical_pages_updated", []),
                                "initial_capture_mode": "ideas",
                                "auto_promote": False,
                                "promotion_status": None,
                                "promotion_rag_status": None,
                                "fallback_from_url_error": error_text,
                            }
                        )
                        if bool(fallback_result.get("ok")):
                            append_ledger_entry(item, fallback_result, ledger_keys)
                        continue
                    except Exception as fallback_exc:
                        error_text = f"{error_text} | fallback_failed: {fallback_exc.__class__.__name__}: {fallback_exc}"
                results.append(
                    {
                        "source_title": item["source_title"],
                        "message_id": item["message_id"],
                        "date": item["date"],
                        "ok": False,
                        "status": "failed",
                        "error": error_text,
                    }
                )
        checkpoint = {
            "batch_start": batch_index + 1,
            "batch_end": batch_index + len(batch),
            "batch_size": len(batch),
            "success_count": sum(1 for item in results if item.get("ok")),
            "failure_count": sum(1 for item in results if not item.get("ok")),
        }
        print(json.dumps({"checkpoint": checkpoint}, ensure_ascii=False))

    summary = {
        **report,
        "results": results,
        "success_count": sum(1 for item in results if item.get("ok")),
        "partial_success_count": sum(1 for item in results if item.get("status") == "partial_success"),
        "failure_count": sum(1 for item in results if not item.get("ok")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


asyncio.run(main())
PY
SH
REMOTE
