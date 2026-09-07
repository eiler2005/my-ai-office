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
MESSAGE_LIMIT="${MESSAGE_LIMIT:-1500}"
MODE="${1:---dry-run}"
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
  "BACKFILL_APPLY=${APPLY} BACKFILL_LIMIT=${MESSAGE_LIMIT} bash -s" <<'REMOTE'
set -euo pipefail
cd /opt/telethon-digest

sudo docker compose run --rm -T \
  -e BACKFILL_APPLY="${BACKFILL_APPLY}" \
  -e BACKFILL_LIMIT="${BACKFILL_LIMIT}" \
  -v /opt/openclaw/config:/host-openclaw-config:ro \
  -v /opt/wiki-import:/host-wiki-import:ro \
  telethon-digest \
  python - <<'PY'
import asyncio
import json
import os
import re
from datetime import timezone
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import urlparse

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Message, MessageEntityTextUrl, MessageEntityUrl


load_dotenv("/app/telethon.env", override=False)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_PATH = "/app/sessions/telethon_digest"
BACKFILL_APPLY = os.environ.get("BACKFILL_APPLY", "0") == "1"
BACKFILL_LIMIT = int(os.environ.get("BACKFILL_LIMIT", "1500") or 1500)
TOPIC_MAP = json.loads(Path("/host-openclaw-config/telegram-topic-map.json").read_text(encoding="utf-8"))
CHAT_ID = int(TOPIC_MAP["chat_id"])
TOPIC_ID = int(TOPIC_MAP["topics"]["knowledgebase"]["message_thread_id"])
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

QUESTION_PREFIXES = (
    "что",
    "как",
    "почему",
    "когда",
    "кто",
    "где",
    "расскажи",
    "найди",
    "объясни",
    "а ты",
    "в чем",
    "какая ошибка",
)
COMMAND_PREFIXES = (
    "сохрани",
    "загружу",
    "загрузи",
    "добавь",
    "переделаю",
    "вот 4 лучшие идеи",
    "все за сегодня",
)
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
        cleaned = url.rstrip(").,]")
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped


def is_topic_message(message: Message) -> bool:
    reply_to = getattr(message, "reply_to", None)
    return bool(reply_to and (getattr(reply_to, "reply_to_msg_id", None) == TOPIC_ID or getattr(reply_to, "reply_to_top_id", None) == TOPIC_ID))


def is_human_message(message: Message) -> bool:
    from_id = getattr(message, "from_id", None)
    user_id = getattr(from_id, "user_id", 0) if from_id else 0
    return bool(user_id and user_id != BOT_USER_ID)


def looks_like_search(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if len(lowered) <= 280 and ("?" in lowered or lowered.startswith(QUESTION_PREFIXES)):
        return True
    return False


def looks_like_command_without_content(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if len(lowered) <= 180 and lowered.startswith(COMMAND_PREFIXES):
        return True
    return False


def classify_candidate(message: Message) -> tuple[str, str] | None:
    text = (message.raw_text or "").strip()
    urls = extract_urls(message)
    if not text and not urls:
        return None
    if looks_like_command_without_content(text):
        return None
    if looks_like_search(text):
        return None
    if urls and (text == urls[0] or (len(text) <= 220 and "\n" not in text and text.count(" ") <= 6)):
        return ("url", urls[0])
    if getattr(message, "fwd_from", None) or len(text) >= 280 or text.count("\n") >= 2 or urls:
        title = build_title(message, "text", text)
        header = [
            f"# {title}",
            "",
            "## Content",
            "",
            text,
            "",
            "## Telegram Provenance",
            "",
            f"- telegram_chat_id: {CHAT_ID}",
            f"- topic_id: {TOPIC_ID}",
            f"- message_id: {message.id}",
            f"- captured_at: {message.date.astimezone(timezone.utc).isoformat()}",
            f"- forwarded: {'yes' if getattr(message, 'fwd_from', None) else 'no'}",
        ]
        if urls:
            header.append(f"- related_urls: {', '.join(urls)}")
        body = "\n".join(header).strip() + "\n"
        return ("text", body)
    return None


def first_title_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped and not stripped.startswith("- telegram_") and stripped != "Content":
            return stripped[:140]
    return ""


def humanize_url_title(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for part in reversed(parts):
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", " ", part).strip(" -_")
        if cleaned and cleaned.lower() not in {"tpost", "library"}:
            return re.sub(r"[_-]+", " ", cleaned).strip().title()
    host = parsed.netloc.replace("www.", "").split(":")[0]
    return re.sub(r"[^A-Za-z0-9]+", " ", host).strip().title()


def build_title(message: Message, source_type: str, source: str) -> str:
    if source_type == "url":
        return humanize_url_title(source)
    base = first_title_line(message.raw_text or source)
    date_part = message.date.astimezone(timezone.utc).strftime("%Y-%m-%d")
    slug_seed = re.sub(r"[^a-z0-9-]+", "", re.sub(r"[_\\s]+", "-", base.lower())) if base else ""
    if slug_seed and not slug_seed.isdigit():
        return f"Knowledgebase {date_part} #{message.id} - {base[:96]}"
    return f"Knowledgebase {date_part} #{message.id}"


def normalize_score_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def score_candidate_for_promotion(message: Message, source_type: str, source: str, title: str) -> tuple[int, list[str]]:
    title_lookup = normalize_score_text(title)
    body_lookup = normalize_score_text(message.raw_text or "")
    source_lookup = (source or "").lower()
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


def should_auto_promote(message: Message, source_type: str, source: str, title: str) -> tuple[bool, list[str], int]:
    score, reasons = score_candidate_for_promotion(message, source_type, source, title)
    return score >= 3, reasons, score


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


async def main() -> None:
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    messages = await client.get_messages(CHAT_ID, limit=BACKFILL_LIMIT)
    await client.disconnect()

    topic_messages = [msg for msg in messages if isinstance(msg, Message) and is_topic_message(msg)]
    candidates = []
    skipped = []
    for message in reversed(topic_messages):
        if not is_human_message(message):
            skipped.append({"id": message.id, "reason": "bot_or_system"})
            continue
        classified = classify_candidate(message)
        if not classified:
            skipped.append({"id": message.id, "reason": "not_explicit_save_candidate"})
            continue
        source_type, source = classified
        title = build_title(message, source_type, source)
        auto_promote, promote_reasons, promote_score = should_auto_promote(message, source_type, source, title)
        candidates.append(
            {
                "message_id": message.id,
                "date": message.date.astimezone(timezone.utc).isoformat(),
                "source_type": source_type,
                "source": source,
                "title": title,
                "auto_promote": auto_promote,
                "promote_reasons": promote_reasons,
                "promote_score": promote_score,
                "import_goal": (
                    "Historical Knowledgebase backfill from Telegram message "
                    f"{message.id} in topic {TOPIC_ID}. Preserve a source-centric research page and "
                    "update canonical pages only when confidence is high."
                ),
                "promotion_import_goal": (
                    "Historical Knowledgebase backfill from Telegram message "
                    f"{message.id} in topic {TOPIC_ID}. Reuse the existing research page and promote "
                    "only durable, reusable concepts or canonical entities supported by the source."
                ),
            }
        )

    report = {
        "apply": BACKFILL_APPLY,
        "chat_id": CHAT_ID,
        "topic_id": TOPIC_ID,
        "topic_messages_scanned": len(topic_messages),
        "candidates": len(candidates),
        "skipped": len(skipped),
        "candidate_preview": [
            {
                "message_id": item["message_id"],
                "date": item["date"],
                "source_type": item["source_type"],
                "title": item["title"],
                "source_preview": item["source"][:160],
                "auto_promote": item["auto_promote"],
                "promote_score": item["promote_score"],
                "promote_reasons": item["promote_reasons"],
            }
            for item in candidates[:25]
        ],
    }

    if not BACKFILL_APPLY:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    results = []
    for item in candidates:
        payload = {
            "source_type": item["source_type"],
            "source": item["source"],
            "target_kind": "auto",
            "title": item["title"],
            "import_goal": item["import_goal"],
            "capture_mode": "ideas",
        }
        try:
            initial = call_wiki_import(payload)
            promotion = None
            if bool(initial.get("ok")) and item["auto_promote"]:
                promotion = call_wiki_import(
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
                    "message_id": item["message_id"],
                    "ok": bool(final_result.get("ok")),
                    "status": final_result.get("status"),
                    "rag_status": final_result.get("rag_status"),
                    "wiki_page_paths": final_result.get("wiki_page_paths", []),
                    "canonical_pages_updated": final_result.get("canonical_pages_updated", []),
                    "initial_capture_mode": "ideas",
                    "auto_promote": item["auto_promote"],
                    "promotion_status": promotion.get("status") if promotion else None,
                    "promotion_rag_status": promotion.get("rag_status") if promotion else None,
                    "promote_score": item["promote_score"],
                    "promote_reasons": item["promote_reasons"],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "message_id": item["message_id"],
                    "ok": False,
                    "status": "failed",
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )

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
REMOTE
