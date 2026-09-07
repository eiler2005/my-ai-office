#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# sync-obsidian.sh
# One-way rsync: Obsidian vault (Mac/iCloud) → server (/opt/obsidian-vault/)
# Read-only on server — server never writes back to vault.
#
# Usage (once):
#   OPENCLAW_HOST=deploy@<server-host> ./scripts/sync-obsidian.sh
#
# Usage (via launchd — see below for automatic sync):
#   OPENCLAW_HOST=deploy@<server-host> SSH_KEY=~/.ssh/id_rsa ./scripts/sync-obsidian.sh
#
# To set up automatic sync every 15 minutes on Mac:
#   1. Copy scripts/com.openclaw.obsidian-sync.plist.template to ~/Library/LaunchAgents/
#   2. Edit it to set OPENCLAW_HOST and SSH_KEY values
#   3. launchctl load ~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist

set -euo pipefail

SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

# Obsidian vault path on Mac (iCloud-synced)
VAULT_LOCAL="${VAULT_LOCAL:-${HOME}/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals}"

if [[ ! -d "${VAULT_LOCAL}" ]]; then
  echo "Error: Obsidian vault not found at: ${VAULT_LOCAL}"
  echo "Set VAULT_LOCAL env var to the correct path."
  exit 1
fi

VAULT_REMOTE="/opt/obsidian-vault/"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Syncing Obsidian vault to ${OPENCLAW_HOST}:${VAULT_REMOTE}"

rsync -avz --delete \
  --exclude=".obsidian/workspace*" \
  --exclude=".obsidian/cache" \
  --exclude=".trash/" \
  --exclude="*.tmp" \
  --include="*.md" \
  --include="*/" \
  --exclude="*" \
  -e "ssh -i ${SSH_KEY}" \
  "${VAULT_LOCAL}/" \
  "${OPENCLAW_HOST}:${VAULT_REMOTE}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync complete."

# Optionally trigger LightRAG re-index after sync
if [[ "${TRIGGER_REINDEX:-false}" == "true" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Triggering LightRAG re-index..."
  ssh -i "${SSH_KEY}" "${OPENCLAW_HOST}" '/opt/lightrag/scripts/lightrag-ingest.sh' || \
    echo "Warning: re-index trigger failed (LightRAG may be starting up)"
fi
