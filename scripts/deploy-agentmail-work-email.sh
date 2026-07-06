#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
LOCAL_ENV="$ROOT_DIR/secrets/agentmail-work-email/email.env"
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
for key in AGENTMAIL_API_KEY AGENTMAIL_INBOX_REF EMAIL_DIGEST_SUPERGROUP_ID EMAIL_DIGEST_TOPIC_ID; do
  if ! grep -Eq "^${key}=.+" "$LOCAL_ENV"; then
    missing+=("$key")
  fi
done

if (( ${#missing[@]} )); then
  printf 'Missing required values in %s: %s\n' "$LOCAL_ENV" "${missing[*]}" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/agentmail-work-email
'

rsync -avz --delete --exclude config.json --exclude email.env --exclude '__pycache__/' --exclude '*.pyc' \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/agentmail-email/" \
  "$OPENCLAW_HOST":/opt/agentmail-work-email/

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo find /opt/agentmail-work-email -type d -name __pycache__ -prune -exec rm -rf {} +
'

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/agentmail-work-email/email.env

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/agentmail-work-email

  if ! sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" email.env; then
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
      sudo sed -i "/^TELEGRAM_BOT_TOKEN=/d" email.env
      printf "TELEGRAM_BOT_TOKEN=%s\n" "$token" | sudo tee -a email.env >/dev/null
    fi
  fi

  append_if_missing() {
    local key="$1"
    local value="$2"
    if ! sudo grep -Eq "^${key}=.+" email.env; then
      printf "%s=%s\n" "$key" "$value" | sudo tee -a email.env >/dev/null
    fi
  }

  append_if_missing OPENCLAW_EXEC_CONTAINER openclaw-openclaw-gateway-1
  append_if_missing OPENCLAW_AGENT_ID main
  append_if_missing OPENCLAW_AGENT_FALLBACK_ID main
  append_if_missing EMAIL_BRIDGE_PORT 8094
  append_if_missing EMAIL_CONTAINER_NAME agentmail-work-email-bridge
  append_if_missing EMAIL_STATE_VOLUME agentmail-work-email-state
  append_if_missing EMAIL_STREAM_JOBS ingest:jobs:email:work
  append_if_missing EMAIL_STREAM_EVENTS ingest:events:email:work
  append_if_missing EMAIL_STREAM_DLQ dlq:failed:email:work
  append_if_missing EMAIL_CONSUMER_GROUP email-workers-work
  append_if_missing EMAIL_CONSUMER_NAME agentmail-work-email-worker
  append_if_missing EMAIL_STATUS_KEY status:email:work:latest
  append_if_missing EMAIL_DLQ_SOURCE email-work
  append_if_missing EMAIL_DIGEST_DISPLAY_NAME "Work Email"
  append_if_missing EMAIL_DIGEST_MORNING_TITLE "Morning triage"
  append_if_missing EMAIL_DIGEST_INTERVAL_TITLE "Regular digest"
  append_if_missing EMAIL_DIGEST_EDITORIAL_TITLE "End-of-day wrap-up"
  append_if_missing EMAIL_CRON_MANAGED_PREFIX "AgentMail Work Email"
  append_if_missing EMAIL_CRON_BRIDGE_LABEL "AgentMail work-email bridge"

  if ! sudo grep -Eq "^EMAIL_BRIDGE_TOKEN=.+" email.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "EMAIL_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a email.env >/dev/null
  fi

  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" email.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in email.env and /opt/openclaw/.env" >&2
    exit 1
  }

  sudo chmod 600 email.env
  sudo chmod +x /opt/agentmail-work-email/entrypoint.sh
  sudo chmod +x /opt/agentmail-work-email/trigger-email-digest.sh
  sudo chmod +x /opt/agentmail-work-email/sync-openclaw-cron-jobs.sh
  sudo test -f config.json || sudo cp config.example.json config.json
  sudo python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path

env_path = Path("/opt/agentmail-work-email/email.env")
config_path = Path("/opt/agentmail-work-email/config.json")

env = {}
for line in env_path.read_text().splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

data = json.loads(config_path.read_text())
if env.get("AGENTMAIL_INBOX_REF"):
    data["inbox_ref"] = env["AGENTMAIL_INBOX_REF"]
data["topic_name"] = "work-email"
data["timezone"] = "Europe/Moscow"
data["poll_interval_minutes"] = 5
data["poll_llm_enabled"] = False
data.setdefault("scheduler", {})
data["scheduler"]["enabled"] = True
data["scheduler"]["tick_seconds"] = 300
data["poll_bootstrap_lookback_minutes"] = 720
data["poll_lag_grace_minutes"] = 15
data["digest_bootstrap_lookback_hours"] = 24
data["event_retention_days"] = 7
data["resolve_forwarded_sender"] = True
data["schedule_slots"] = [
    "08:30",
    "10:00",
    "11:30",
    "13:00",
    "14:30",
    "16:00",
    "17:30",
    "19:00",
]
data["digest_types"] = {
    "08:30": "morning",
    "10:00": "interval",
    "11:30": "interval",
    "13:00": "interval",
    "14:30": "interval",
    "16:00": "interval",
    "17:30": "interval",
    "19:00": "editorial",
}
data["labels"] = {
    "polled": "workmail/polled",
    "low_signal": "workmail/low-signal",
    "digested": "workmail/digested",
}
data["low_signal_hints"] = [
    "newsletter",
    "unsubscribe",
    "sale",
    "discount",
    "promo",
    "digest",
    "sponsored",
]
config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

  cd /opt/openclaw
  sudo docker compose up -d openclaw-gateway

  ready=0
  for _ in $(seq 1 30); do
    if sudo docker exec openclaw-openclaw-gateway-1 /usr/local/bin/openclaw --version >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "OpenClaw gateway did not become ready in time." >&2
    exit 1
  fi

  cd /opt/agentmail-work-email
  sudo docker compose --env-file email.env build
  sudo docker compose --env-file email.env down 2>/dev/null || true
  sudo docker compose --env-file email.env up -d agentmail-email-bridge
  sudo docker image prune -f >/dev/null 2>&1 || true
  sudo docker builder prune -f >/dev/null 2>&1 || true

  sudo tee /etc/cron.d/agentmail-work-email >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Host cron runs in UTC. These lines map to 08:30, 10:00, 11:30, 13:00, 14:30, 16:00, 17:30, 19:00 MSK.
30 5 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh morning >> /var/log/agentmail-work-email-cron.log 2>&1
0 7 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
30 8 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
0 10 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
30 11 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
0 13 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
30 14 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh interval >> /var/log/agentmail-work-email-cron.log 2>&1
0 16 * * * root bash /opt/agentmail-work-email/trigger-email-digest.sh editorial >> /var/log/agentmail-work-email-cron.log 2>&1
CRON
  sudo chmod 0644 /etc/cron.d/agentmail-work-email

  sudo python3 - <<'"'"'PY'"'"'
import json
import shutil
import sys
import time
from pathlib import Path

paths = [
    Path("/opt/openclaw/config/cron/jobs.json"),
    Path("/home/deploy/.openclaw/cron/jobs.json"),
]
store_path = next((path for path in paths if path.exists()), None)
if store_path is None:
    print("OpenClaw cron store not found; host cron is authoritative for AgentMail work email.", file=sys.stderr)
    raise SystemExit(0)

raw = json.loads(store_path.read_text())
jobs = raw.get("jobs", raw if isinstance(raw, list) else [])
changed = False
for job in jobs:
    if isinstance(job, dict) and str(job.get("name", "")).startswith("AgentMail Work Email ·"):
        if job.get("enabled", True):
            job["enabled"] = False
            changed = True

if changed:
    shutil.copy2(store_path, store_path.with_name(f"{store_path.name}.bak-{int(time.time())}"))
    store_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
PY

  cd /opt/openclaw
  sudo docker compose up -d openclaw-gateway
  sudo grep -q "30 5 \* \* \* root bash /opt/agentmail-work-email/trigger-email-digest.sh morning" /etc/cron.d/agentmail-work-email
'

cat <<'EOF'
AgentMail work-email pipeline deployed.

Scheduled:
  - internal scheduler poll every 5 minutes
  - digests at 08:30 / 10:00 / 11:30 / 13:00 / 14:30 / 16:00 / 17:30 / 19:00 MSK via /etc/cron.d/agentmail-work-email

Useful commands:
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/agentmail-work-email && sudo docker compose logs --tail=100 agentmail-email-bridge'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'curl -s http://127.0.0.1:8094/health && echo && curl -s http://127.0.0.1:8094/status'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email:work'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:email:work'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo cat /etc/cron.d/agentmail-work-email'
EOF
