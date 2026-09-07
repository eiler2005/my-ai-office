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
LOCAL_ENV="$ROOT_DIR/secrets/telethon-digest/telethon.env"
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

missing=()
for key in TELEGRAM_API_ID TELEGRAM_API_HASH TELEGRAM_PHONE DIGEST_SUPERGROUP_ID DIGEST_TOPIC_ID; do
  if ! grep -Eq "^${key}=.+" "$LOCAL_ENV"; then
    missing+=("$key")
  fi
done

if (( ${#missing[@]} )); then
  printf 'Missing required values in %s: %s\n' "$LOCAL_ENV" "${missing[*]}" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/telethon-digest
  sudo mkdir -p "/opt/obsidian-vault/Telegram Digest/Derived" "/opt/obsidian-vault/Telegram Digest/Curated"
  sudo chown -R deploy:deploy "/opt/obsidian-vault/Telegram Digest"
'

rsync -avz --delete --exclude config.json --exclude telethon.env \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/telethon-digest/" \
  "$OPENCLAW_HOST":/opt/telethon-digest/

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/telethon-digest/telethon.env

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/telethon-digest
  if ! sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" telethon.env; then
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
      sudo sed -i "/^TELEGRAM_BOT_TOKEN=/d" telethon.env
      printf "TELEGRAM_BOT_TOKEN=%s\n" "$token" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  if ! sudo grep -Eq "^OMNIROUTE_API_KEY=.+" telethon.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^OMNIROUTE_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^OMNIROUTE_API_KEY=/d" telethon.env
      printf "OMNIROUTE_API_KEY=%s\n" "$key" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  if ! sudo grep -Eq "^DASHSCOPE_API_KEY=.+" telethon.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^DASHSCOPE_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^DASHSCOPE_API_KEY=/d" telethon.env
      printf "DASHSCOPE_API_KEY=%s\n" "$key" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  if ! sudo grep -Eq "^DEEPSEEK_API_KEY=.+" telethon.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^DEEPSEEK_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^DEEPSEEK_API_KEY=/d" telethon.env
      printf "DEEPSEEK_API_KEY=%s\n" "$key" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" telethon.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in telethon.env and /opt/openclaw/.env" >&2
    exit 1
  }
  if ! sudo grep -Eq "^DIGEST_CRON_BRIDGE_TOKEN=.+" telethon.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "DIGEST_CRON_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a telethon.env >/dev/null
  fi
  sudo chmod 600 telethon.env
  sudo chmod +x /opt/telethon-digest/cron-digest.sh
  sudo chmod +x /opt/telethon-digest/trigger-digest.sh
  sudo chmod +x /opt/telethon-digest/sync-openclaw-cron-jobs.sh
  sudo test -f config.json || sudo cp config.example.json config.json
  sudo python3 - <<'PY'
import json
from pathlib import Path

path = Path("/opt/telethon-digest/config.json")
data = json.loads(path.read_text())
data["schedule_hours"] = [8, 11, 14, 17, 21]
data["schedule_slots"] = ["08:00", "11:00", "14:00", "17:00", "21:00"]
data["digest_types"] = {
    "8": "morning",
    "11": "interval",
    "14": "interval",
    "17": "interval",
    "21": "editorial",
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY
  sudo docker compose build

  # Stop old APScheduler daemon; digest runs are triggered by host cron calling
  # the bridge directly. OpenClaw agent-turn cron cannot reliably run shell
  # tools in the lightweight cron context after 2026.5.x.
  sudo docker compose down 2>/dev/null || true
  sudo docker compose up -d telethon-digest-cron-bridge

  sudo tee /etc/cron.d/telethon-digest >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Host cron evaluates this file in UTC. The final arguments keep Moscow slot labels.

0 5 * * * root /bin/bash /opt/telethon-digest/trigger-digest.sh morning 8 0 >> /var/log/telethon-digest-cron.log 2>&1
0 8 * * * root /bin/bash /opt/telethon-digest/trigger-digest.sh interval 11 0 >> /var/log/telethon-digest-cron.log 2>&1
0 11 * * * root /bin/bash /opt/telethon-digest/trigger-digest.sh interval 14 0 >> /var/log/telethon-digest-cron.log 2>&1
0 14 * * * root /bin/bash /opt/telethon-digest/trigger-digest.sh interval 17 0 >> /var/log/telethon-digest-cron.log 2>&1
0 18 * * * root /bin/bash /opt/telethon-digest/trigger-digest.sh editorial 21 0 >> /var/log/telethon-digest-cron.log 2>&1
CRON
  sudo chmod 0644 /etc/cron.d/telethon-digest

  if sudo docker ps --format "{{.Names}}" | grep -qx "openclaw-openclaw-gateway-1"; then
    for id in $(sudo docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway sh -lc "openclaw cron list 2>/dev/null" | awk "/Telethon Digest/ {print \$1}"); do
      sudo docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway sh -lc "openclaw cron disable $id >/dev/null" || true
    done
  fi

  ready=0
  for _ in $(seq 1 75); do
    status="$(sudo docker ps --format "{{.Names}} {{.Status}}" | grep "^openclaw-openclaw-gateway-1 " || true)"
    if echo "$status" | grep -q "(healthy)"; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "OpenClaw gateway did not become healthy after cron sync." >&2
    exit 1
  fi

  sudo test -x /opt/telethon-digest/trigger-digest.sh
  sudo grep -q "0 5 \\* \\* \\* root /bin/bash /opt/telethon-digest/trigger-digest.sh morning 8 0" /etc/cron.d/telethon-digest
'

cat <<'EOF'
Telethon Digest deployed. Host cron now triggers the bridge directly.

Scheduled: 08:00, 11:00, 14:00, 17:00, 21:00 MSK via /etc/cron.d/telethon-digest

Useful commands:
  # Run digest immediately
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo /opt/telethon-digest/trigger-digest.sh interval 11 0'

  # Watch digest log
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo tail -f /var/log/telethon-digest-cron.log'

  # Inspect host cron
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo cat /etc/cron.d/telethon-digest'

  # Re-sync channels
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py'
EOF
