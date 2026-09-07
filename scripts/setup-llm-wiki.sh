#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# Prepare a safe LLM-Wiki cutover and re-arm LightRAG without wiping the vault.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
SSH=(ssh -i "${SSH_KEY}")
SCP=(scp -i "${SSH_KEY}")
TARGET_ROOT="${TARGET_ROOT:-/opt/obsidian-vault}"
LIGHTRAG_ROOT="${LIGHTRAG_ROOT:-/opt/lightrag}"
WAIT_SECONDS="${WAIT_SECONDS:-120}"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_ROOT="${BACKUP_ROOT:-${LIGHTRAG_ROOT}/backups/llm-wiki-${TIMESTAMP}}"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

echo "=== Safe LLM-Wiki cutover on ${OPENCLAW_HOST} ==="

echo "[1/6] Stopping LightRAG..."
"${SSH[@]}" "${OPENCLAW_HOST}" "cd '${LIGHTRAG_ROOT}' && docker compose stop >/dev/null 2>&1 || true"

echo "[2/6] Backing up current LightRAG derived state..."
"${SSH[@]}" "${OPENCLAW_HOST}" "
  sudo mkdir -p '${BACKUP_ROOT}' &&
  sudo cp -a '${LIGHTRAG_ROOT}/data' '${BACKUP_ROOT}/data'
"

echo "[3/6] Clearing only LightRAG derived state and preparing wiki directories..."
"${SSH[@]}" "${OPENCLAW_HOST}" "
  sudo rm -rf '${LIGHTRAG_ROOT}/data/graph_storage'* \
              '${LIGHTRAG_ROOT}/data/vdb_storage'* \
              '${LIGHTRAG_ROOT}/data/kv_storage'* \
              '${LIGHTRAG_ROOT}/data/doc_status_storage'* \
              '${LIGHTRAG_ROOT}/data/rag_storage'* &&
  sudo mkdir -p '${TARGET_ROOT}/wiki/concepts' \
                '${TARGET_ROOT}/wiki/entities' \
                '${TARGET_ROOT}/wiki/decisions' \
                '${TARGET_ROOT}/wiki/sessions' \
                '${TARGET_ROOT}/wiki/research' \
                '${TARGET_ROOT}/raw/articles' \
                '${TARGET_ROOT}/raw/signals' \
                '${TARGET_ROOT}/raw/documents' \
                '${TARGET_ROOT}/legacy-vault' &&
  sudo chown -R deploy:deploy '${TARGET_ROOT}/wiki' '${TARGET_ROOT}/raw'
"

echo "[4/6] Deploying wiki scaffold and ingest script..."
OPENCLAW_HOST="${OPENCLAW_HOST}" SSH_KEY="${SSH_KEY}" TARGET_ROOT="${TARGET_ROOT}" "${SCRIPT_DIR}/deploy-llm-wiki.sh"
"${SCP[@]}" "${SCRIPT_DIR}/lightrag-ingest.sh" "${OPENCLAW_HOST}:/tmp/lightrag-ingest.sh"
"${SSH[@]}" "${OPENCLAW_HOST}" "
  sudo install -m 0755 /tmp/lightrag-ingest.sh '${LIGHTRAG_ROOT}/scripts/lightrag-ingest.sh' &&
  rm -f /tmp/lightrag-ingest.sh &&
  sudo chown deploy:deploy '${LIGHTRAG_ROOT}/scripts/lightrag-ingest.sh'
"

echo "[5/6] Restarting LightRAG..."
"${SSH[@]}" "${OPENCLAW_HOST}" "cd '${LIGHTRAG_ROOT}' && docker compose up -d"

echo "[6/6] Waiting for LightRAG health..."
"${SSH[@]}" "${OPENCLAW_HOST}" "
  timeout '${WAIT_SECONDS}' bash -lc '
    until curl -sf http://127.0.0.1:8020/health >/dev/null 2>&1; do
      sleep 5
    done
  '
"

echo ""
echo "Safe cutover complete."
echo "Next steps:"
echo "  1. Keep legacy vault content outside active ingest scope"
echo "  2. Deploy wiki-import and run curated imports"
echo "  3. Run ${LIGHTRAG_ROOT}/scripts/lightrag-ingest.sh"
