#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# Upload workspace + LLM-Wiki markdown files to LightRAG one by one.

set -euo pipefail

API="${LIGHTRAG_API:-http://127.0.0.1:8020}"
LOG_FILE="${LIGHTRAG_INGEST_LOG:-/var/log/lightrag-ingest.log}"
UPLOADED=0
FAILED=0

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

log() {
  local message="$1"
  if touch "${LOG_FILE}" >/dev/null 2>&1; then
    echo "[$(timestamp)] ${message}" | tee -a "${LOG_FILE}"
  else
    echo "[$(timestamp)] ${message}"
  fi
}

upload_dir() {
  local dir="$1"

  if [[ ! -d "${dir}" ]]; then
    log "Skip missing directory: ${dir}"
    return
  fi

  while IFS= read -r -d '' file; do
    if curl -sf -X POST "${API}/documents/upload" -F "file=@${file}" >/dev/null 2>&1; then
      UPLOADED=$((UPLOADED + 1))
    else
      FAILED=$((FAILED + 1))
      log "Upload failed: ${file}"
    fi
  done < <(find "${dir}" -type f -name '*.md' -not -path '*/archive/*' -print0 | sort -z)
}

log "LightRAG ingest started"

if ! curl -sf "${API}/health" >/dev/null 2>&1; then
  log "ERROR: LightRAG not reachable at ${API}"
  exit 1
fi

upload_dir "/opt/openclaw/workspace"
upload_dir "/opt/obsidian-vault/wiki"
upload_dir "/opt/obsidian-vault/raw/signals"

curl -sf -X POST "${API}/documents/reprocess_failed" >/dev/null 2>&1 || true

log "Done: ${UPLOADED} uploaded, ${FAILED} failed"
