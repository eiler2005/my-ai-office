#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
LOCAL_ENV="$ROOT_DIR/secrets/signals-bridge/signals.env"
LOCAL_CONFIG="$ROOT_DIR/secrets/signals-bridge/config.json"
LOCAL_RULES_DIR="$ROOT_DIR/secrets/signals-bridge/rules"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)
RSYNC_SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=${SSH_CONNECT_TIMEOUT:-15} -o ConnectionAttempts=1"

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "Missing $LOCAL_ENV" >&2
  exit 1
fi

if [[ ! -f "$LOCAL_CONFIG" ]]; then
  echo "Missing $LOCAL_CONFIG" >&2
  exit 1
fi

if [[ ! -d "$LOCAL_RULES_DIR" ]]; then
  echo "Missing $LOCAL_RULES_DIR" >&2
  exit 1
fi

missing=()
for key in TELEGRAM_API_ID TELEGRAM_API_HASH TELEGRAM_PHONE SIGNALS_SUPERGROUP_ID SIGNALS_TOPIC_ID AGENTMAIL_API_KEY; do
  if ! grep -Eq "^${key}=.+" "$LOCAL_ENV"; then
    missing+=("$key")
  fi
done

if (( ${#missing[@]} )); then
  printf 'Missing required values in %s: %s\n' "$LOCAL_ENV" "${missing[*]}" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/signals-bridge /opt/signals-bridge/rules
'

rsync -avz --delete \
  --exclude config.json \
  --exclude signals.env \
  --exclude rules \
  --exclude backups/ \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'tests/' \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/signals-bridge/" \
  "$OPENCLAW_HOST":/opt/signals-bridge/

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/signals-bridge/signals.env

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_CONFIG" \
  "$OPENCLAW_HOST":/opt/signals-bridge/config.json

rsync -avz --delete -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_RULES_DIR/" \
  "$OPENCLAW_HOST":/opt/signals-bridge/rules/

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/signals-bridge

  if ! sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" signals.env; then
    token=""
    if sudo test -f /opt/openclaw/.env; then
      token="$(sudo awk -F= "/^(TELEGRAM_BOT_TOKEN|OPENCLAW_TELEGRAM_BOT_TOKEN)=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    fi
    if [ -z "$token" ] && sudo test -f /opt/openclaw/config/openclaw.json; then
      token="$(sudo python3 - <<'"'"'PY'"'"'
import json
try:
    data = json.load(open("/opt/openclaw/config/openclaw.json"))
    print(data.get("channels", {}).get("telegram", {}).get("botToken", ""))
except Exception:
    print("")
PY
)"
    fi
    if [ -n "$token" ]; then
      sudo sed -i "/^TELEGRAM_BOT_TOKEN=/d" signals.env
      printf "TELEGRAM_BOT_TOKEN=%s\n" "$token" | sudo tee -a signals.env >/dev/null
    fi
  fi

  if ! sudo grep -Eq "^OMNIROUTE_API_KEY=.+" signals.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^OMNIROUTE_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^OMNIROUTE_API_KEY=/d" signals.env
      printf "OMNIROUTE_API_KEY=%s\n" "$key" | sudo tee -a signals.env >/dev/null
    fi
  fi

  if ! sudo grep -Eq "^DASHSCOPE_API_KEY=.+" signals.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^DASHSCOPE_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^DASHSCOPE_API_KEY=/d" signals.env
      printf "DASHSCOPE_API_KEY=%s\n" "$key" | sudo tee -a signals.env >/dev/null
    fi
  fi

  if ! sudo grep -Eq "^DEEPSEEK_API_KEY=.+" signals.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^DEEPSEEK_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^DEEPSEEK_API_KEY=/d" signals.env
      printf "DEEPSEEK_API_KEY=%s\n" "$key" | sudo tee -a signals.env >/dev/null
    fi
  fi

  if ! sudo grep -Eq "^SIGNALS_BRIDGE_TOKEN=.+" signals.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "SIGNALS_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a signals.env >/dev/null
  fi

  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" signals.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in signals.env and /opt/openclaw/.env" >&2
    exit 1
  }

  sudo chmod 600 signals.env
  sudo chmod +x /opt/signals-bridge/entrypoint.sh

  sudo docker compose build
  sudo docker compose down 2>/dev/null || true
  sudo docker compose up -d signals-bridge

  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8093/health >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "signals-bridge did not become healthy in time." >&2
    exit 1
  fi

'

cat <<'EOF'
Signals bridge deployed.

Cadence:
  - internal scheduler every 5 minutes
  - enrichment route: OpenClaw/OpenAI -> OmniRoute light -> Qwen -> DeepSeek -> local

Useful commands:
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/signals-bridge && sudo docker compose logs --tail=100 signals-bridge'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'curl -s http://127.0.0.1:8093/health && echo && curl -s http://127.0.0.1:8093/status'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo cat /opt/openclaw/config/cron/jobs.json 2>/dev/null || sudo cat /home/deploy/.openclaw/cron/jobs.json'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:signals'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:signals'
EOF
