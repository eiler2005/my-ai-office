#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
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
  "LEDGER_REBUILD_APPLY=${APPLY} bash -s" <<'REMOTE'
set -euo pipefail

python3 - <<'PY'
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

APPLY = os.environ.get("LEDGER_REBUILD_APPLY", "0") == "1"
VAULT_ROOT = Path("/opt/obsidian-vault")
RESEARCH_ROOT = VAULT_ROOT / "wiki" / "research"
LEDGER_ROOT = VAULT_ROOT / ".ingest-ledgers"
LEDGER_PATH = LEDGER_ROOT / "telegram-post-imports.jsonl"


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def _extract_title(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _extract_section(lines: list[str], header: str) -> list[str]:
    inside = False
    chunk: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == header:
            inside = True
            continue
        if inside and stripped.startswith("## "):
            break
        if inside:
            chunk.append(line.rstrip("\n"))
    return chunk


def _extract_bullets(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _infer_source_type(lines: list[str], provenance: dict[str, str]) -> str:
    if provenance.get("original_url"):
        return "url"
    if provenance.get("related_urls"):
        return "text"
    source_url_section = _extract_section(lines, "## Source URL")
    if any(line.strip() for line in source_url_section):
        return "url"
    return "text"


def _infer_source_value(lines: list[str], provenance: dict[str, str], source_type: str) -> str:
    if source_type == "url":
        if provenance.get("original_url"):
            return provenance["original_url"]
        source_url_section = _extract_section(lines, "## Source URL")
        joined = " ".join(line.strip() for line in source_url_section if line.strip())
        return joined.strip()
    return "manual"


def _normalize_chat_id(value: str) -> str | int:
    stripped = str(value or "").strip()
    if stripped == "me":
        return "me"
    try:
        return int(stripped)
    except ValueError:
        return stripped


def _ledger_key(record: dict) -> str:
    return "|".join(
        [
            str(record.get("source_title", "")).strip(),
            str(record.get("source_chat_id", "")).strip(),
            str(record.get("message_id", "")).strip(),
            str(record.get("source_type", "")).strip(),
        ]
    )


def _load_existing_ledger() -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not LEDGER_PATH.exists():
        return records
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(payload.get("ledger_key", "")).strip()
        if key:
            records[key] = payload
    return records


def _build_record(path: Path) -> dict | None:
    lines = _read_lines(path)
    if "## Telegram Provenance" not in "\n".join(lines):
        return None
    provenance = _extract_bullets(_extract_section(lines, "## Telegram Provenance"))
    if not provenance.get("source_chat_title") or not provenance.get("message_id"):
        return None
    title = _extract_title(lines)
    source_type = _infer_source_type(lines, provenance)
    source_value = _infer_source_value(lines, provenance, source_type)
    capture_mode = "ideas"
    for line in lines[:40]:
        stripped = line.strip()
        if stripped.startswith("capture_mode:"):
            capture_mode = stripped.split(":", 1)[1].strip() or "ideas"
            break
    record = {
        "ledger_key": "",
        "logged_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_title": provenance.get("source_chat_title", ""),
        "source_kind": provenance.get("source_kind", "telegram"),
        "source_chat_id": _normalize_chat_id(provenance.get("source_chat_id", "")),
        "message_id": int(provenance["message_id"]),
        "post_date_utc": provenance.get("post_date_utc", ""),
        "source_type": source_type,
        "source": source_value,
        "title": title,
        "research_path": str(path.relative_to(VAULT_ROOT)),
        "wiki_page_paths": [str(path.relative_to(VAULT_ROOT))],
        "canonical_pages_updated": [],
        "rag_status": "unknown",
        "status": "rebuilt",
        "capture_mode": capture_mode or "ideas",
        "auto_promote": False,
        "rebuilt_from_research_page": True,
    }
    record["ledger_key"] = _ledger_key(record)
    return record


rebuilt: dict[str, dict] = {}
for path in sorted(RESEARCH_ROOT.glob("*.md")):
    record = _build_record(path)
    if record and record["ledger_key"]:
        rebuilt[record["ledger_key"]] = record

existing = _load_existing_ledger()
missing_keys = sorted(set(rebuilt) - set(existing))
merged = {**rebuilt, **existing}
ordered = sorted(
    merged.values(),
    key=lambda item: (
        str(item.get("post_date_utc", "")),
        str(item.get("source_title", "")),
        int(item.get("message_id", 0)) if str(item.get("message_id", "")).isdigit() else str(item.get("message_id", "")),
    ),
)

report = {
    "apply": APPLY,
    "research_pages_scanned": len(list(RESEARCH_ROOT.glob("*.md"))),
    "rebuildable_records": len(rebuilt),
    "existing_ledger_records": len(existing),
    "missing_ledger_records": len(missing_keys),
    "merged_ledger_records": len(merged),
    "missing_preview": [
        {
            "ledger_key": key,
            "source_title": rebuilt[key].get("source_title"),
            "message_id": rebuilt[key].get("message_id"),
            "title": rebuilt[key].get("title"),
            "research_path": rebuilt[key].get("research_path"),
        }
        for key in missing_keys[:25]
    ],
}

if not APPLY:
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0)

LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
if LEDGER_PATH.exists():
    backup_path = LEDGER_ROOT / f"{LEDGER_PATH.stem}.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{LEDGER_PATH.suffix}"
    backup_path.write_text(LEDGER_PATH.read_text(encoding="utf-8"), encoding="utf-8")

with LEDGER_PATH.open("w", encoding="utf-8") as handle:
    for record in ordered:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

print(json.dumps(report, ensure_ascii=False, indent=2))
PY
REMOTE
