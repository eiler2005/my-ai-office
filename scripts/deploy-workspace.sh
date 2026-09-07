#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# deploy-workspace.sh
# Deploys workspace template files to the OpenClaw server.
#
# Usage:
#   OPENCLAW_HOST=deploy@<server-host> ./scripts/deploy-workspace.sh
#
# The server host is defined in LOCAL_ACCESS.md (not committed to git).
# SSH key: ~/.ssh/id_rsa (adjust SSH_KEY below if different)
#
# What it does:
#   - Syncs all *.md files from ./workspace/ root to /opt/openclaw/workspace/
#   - Deploys memory/INDEX.md (catalog template) but skips daily memory logs
#   - Deploys executable helpers from ./workspace/bin/
#   - Creates memory/archive/ and raw/ directories on the server if missing
#   - Does NOT delete existing files on the server (safe incremental deploy)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="${SCRIPT_DIR}/../workspace"
REMOTE_DIR="/opt/openclaw/workspace"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
SSH="ssh -i ${SSH_KEY}"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

echo "=== Deploying workspace files to ${OPENCLAW_HOST}:${REMOTE_DIR} ==="

# 1. Deploy root workspace *.md files (MEMORY.md, INDEX.md, AGENTS.md, etc.)
echo ""
echo "[1/5] Syncing workspace root templates..."
rsync -avz \
  --include="*.md" \
  --exclude="memory/" \
  --exclude="raw/" \
  --exclude="*" \
  -e "${SSH}" \
  "${WORKSPACE_DIR}/" \
  "${OPENCLAW_HOST}:${REMOTE_DIR}/"

# 2. Deploy memory/INDEX.md (catalog template — not the daily logs)
echo ""
echo "[2/5] Deploying memory/INDEX.md catalog template..."
rsync -avz \
  -e "${SSH}" \
  "${WORKSPACE_DIR}/memory/INDEX.md" \
  "${OPENCLAW_HOST}:${REMOTE_DIR}/memory/INDEX.md"

# 3. Deploy executable helpers
echo ""
echo "[3/5] Deploying workspace bin helpers..."
rsync -avz \
  --include="*/" \
  --include="*" \
  -e "${SSH}" \
  "${WORKSPACE_DIR}/bin/" \
  "${OPENCLAW_HOST}:${REMOTE_DIR}/bin/"

${SSH} "${OPENCLAW_HOST}" "
  chmod +x ${REMOTE_DIR}/bin/*.py 2>/dev/null || true
"

# 4. Create memory/archive/ and raw/ directories on server (if missing)
echo ""
echo "[4/5] Ensuring memory/archive/ and raw/ directories exist on server..."
${SSH} "${OPENCLAW_HOST}" "
  mkdir -p ${REMOTE_DIR}/memory/archive
  mkdir -p ${REMOTE_DIR}/raw
  echo '  memory/archive/ — ok'
  echo '  raw/            — ok'
"

# 5. Fix ownership so OpenClaw container can write to the directories
echo ""
echo "[5/5] Fixing ownership on /opt/openclaw/workspace/ ..."
${SSH} "${OPENCLAW_HOST}" "
  sudo chown -R 1000:1000 ${REMOTE_DIR}/memory/archive ${REMOTE_DIR}/raw 2>/dev/null || \
  echo '  (chown skipped — already correct or requires manual fix)'
"

echo ""
echo "=== Done. Workspace deployed successfully. ==="
echo ""
echo "Next steps:"
echo "  1. In another terminal, open the UI tunnel: ./scripts/openclaw-ui-tunnel.sh"
echo "  2. Open http://127.0.0.1:18789/ and run: /new"
echo "  3. Test: ask the bot 'Кто ты и что ты знаешь обо мне?'"
echo "  4. Verify LightRAG: curl -sf http://127.0.0.1:8020/health (on server)"
