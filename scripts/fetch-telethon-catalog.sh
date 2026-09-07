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
OUT="${OUT:-$ROOT_DIR/secrets/telethon-digest/config.local.json}"
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

mkdir -p "$(dirname "$OUT")"
ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  'sudo cat /opt/telethon-digest/config.json' > "$OUT"
chmod 600 "$OUT"

python3 - "$OUT" <<'PY'
import json
import sys

path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
folders = data.get("folders", [])
total = sum(len(f.get("channels", [])) for f in folders)
broadcast = sum(
    1
    for f in folders
    for ch in f.get("channels", [])
    if ch.get("broadcast") is True
)
print(f"Saved {path}")
print(f"folders={len(folders)} channels={total} broadcast_channels={broadcast}")
print("allowed_folder_names=" + ",".join(data.get("allowed_folder_names", [])))
PY
