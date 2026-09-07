#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# Open an SSH tunnel for the OpenClaw graphical web UI.

set -euo pipefail

LOCAL_PORT="${LOCAL_PORT:-18789}"
REMOTE_HOST="${OPENCLAW_UI_HOST:-204.168.239.217}"
REMOTE_USER="${OPENCLAW_UI_USER:-deploy}"
REMOTE_PORT="${OPENCLAW_UI_REMOTE_PORT:-18789}"
BASTION_HOST="${OPENCLAW_UI_BASTION_HOST:-192.168.50.1}"
BASTION_USER="${OPENCLAW_UI_BASTION_USER:-admin}"

echo "Opening OpenClaw UI tunnel."
echo "Keep this terminal open, then browse: http://127.0.0.1:${LOCAL_PORT}/"
echo "If the local port is busy, run: LOCAL_PORT=18790 $0"

exec ssh -N \
  -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
  -o ExitOnForwardFailure=yes \
  -o "ProxyCommand=ssh ${BASTION_USER}@${BASTION_HOST} nc -w 120 %h %p" \
  "${REMOTE_USER}@${REMOTE_HOST}"
