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
LOCAL_ENV="$ROOT_DIR/secrets/agentmail-email/email.env"
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
  sudo mkdir -p /opt/agentmail-email
'

rsync -avz --delete --exclude config.json --exclude email.env --exclude '__pycache__/' --exclude '*.pyc' \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/agentmail-email/" \
  "$OPENCLAW_HOST":/opt/agentmail-email/

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo find /opt/agentmail-email -type d -name __pycache__ -prune -exec rm -rf {} +
'

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/agentmail-email/email.env

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/agentmail-email

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

  if ! sudo grep -Eq "^OPENCLAW_EXEC_CONTAINER=.+" email.env; then
    printf "OPENCLAW_EXEC_CONTAINER=openclaw-openclaw-gateway-1\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^OPENCLAW_AGENT_ID=.+" email.env; then
    printf "OPENCLAW_AGENT_ID=main\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^OPENCLAW_AGENT_FALLBACK_ID=.+" email.env; then
    printf "OPENCLAW_AGENT_FALLBACK_ID=main\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^EMAIL_BRIDGE_TOKEN=.+" email.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "EMAIL_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^EMAIL_CONTAINER_NAME=.+" email.env; then
    printf "EMAIL_CONTAINER_NAME=agentmail-email-bridge\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^EMAIL_STATE_VOLUME=.+" email.env; then
    printf "EMAIL_STATE_VOLUME=agentmail-email-state\n" | sudo tee -a email.env >/dev/null
  fi

  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" email.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in email.env and /opt/openclaw/.env" >&2
    exit 1
  }

  if sudo test -f /opt/openclaw/.env; then
    sudo sed -i "/^AGENTMAIL_API_KEY=/d" /opt/openclaw/.env
  fi

  sudo python3 - <<'"'"'PY'"'"'
from pathlib import Path

path = Path("/opt/openclaw/docker-compose.yml")
text = path.read_text()

text = text.replace("      AGENTMAIL_API_KEY: ${AGENTMAIL_API_KEY}\n", "")

path.write_text(text)
PY

  sudo python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path

path = Path("/opt/openclaw/config/openclaw.json")
data = json.loads(path.read_text())
data.setdefault("tools", {})["profile"] = "coding"
if "mcp" in data and isinstance(data["mcp"], dict):
    servers = data["mcp"].get("servers")
    if isinstance(servers, dict):
        servers.pop("agentmail", None)
        if not servers:
            data.pop("mcp", None)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

  sudo chmod 600 email.env
  sudo chmod +x /opt/agentmail-email/entrypoint.sh
  sudo chmod +x /opt/agentmail-email/trigger-email-digest.sh
  sudo chmod +x /opt/agentmail-email/sync-openclaw-cron-jobs.sh
  sudo test -f config.json || sudo cp config.example.json config.json
  sudo python3 - <<'PY'
import json
from pathlib import Path

env_path = Path("/opt/agentmail-email/email.env")
config_path = Path("/opt/agentmail-email/config.json")

env = {}
for line in env_path.read_text().splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

data = json.loads(config_path.read_text())
if env.get("AGENTMAIL_INBOX_REF"):
    data["inbox_ref"] = env["AGENTMAIL_INBOX_REF"]
data.setdefault("topic_name", "inbox-email")
data.setdefault("scheduler", {})
data["scheduler"].setdefault("enabled", True)
data["scheduler"].setdefault("tick_seconds", int(data.get("poll_interval_minutes", 5) or 5) * 60)
data.setdefault("poll_llm_enabled", False)
data.setdefault("schedule_slots", ["08:00", "13:00", "16:00", "20:00"])
data.setdefault("poll_bootstrap_lookback_minutes", 720)
config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY
  sudo rm -rf /opt/agentmail-email/openclaw-config 2>/dev/null || true

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

  cd /opt/agentmail-email
  sudo docker compose --env-file email.env build
  sudo docker compose --env-file email.env down 2>/dev/null || true
  sudo docker compose --env-file email.env up -d agentmail-email-bridge
  sudo docker image prune -f >/dev/null 2>&1 || true
  sudo docker builder prune -f >/dev/null 2>&1 || true

  sudo tee /etc/cron.d/agentmail-email >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Host cron runs in UTC. These lines map to 08:00, 13:00, 16:00, 20:00 MSK.
0 5 * * * root /opt/agentmail-email/trigger-email-digest.sh morning >> /var/log/agentmail-email-cron.log 2>&1
0 10 * * * root /opt/agentmail-email/trigger-email-digest.sh interval >> /var/log/agentmail-email-cron.log 2>&1
0 13 * * * root /opt/agentmail-email/trigger-email-digest.sh interval >> /var/log/agentmail-email-cron.log 2>&1
0 17 * * * root /opt/agentmail-email/trigger-email-digest.sh editorial >> /var/log/agentmail-email-cron.log 2>&1
CRON
  sudo chmod 0644 /etc/cron.d/agentmail-email

  sudo python3 - <<'PY'
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
    print("OpenClaw cron store not found; host cron is authoritative for AgentMail email.", file=sys.stderr)
    raise SystemExit(0)

data = json.loads(store_path.read_text())
jobs = data.get("jobs", data if isinstance(data, list) else [])
poll_jobs = [job for job in jobs if job.get("name") == "AgentMail Inbox · Poll every 5m"]
if poll_jobs:
    raise SystemExit("AgentMail poll cron job should not exist.")

changed = False
for job in jobs:
    if isinstance(job, dict) and str(job.get("name", "")).startswith("AgentMail Inbox ·"):
        if job.get("enabled", True):
            job["enabled"] = False
            changed = True

if changed:
    shutil.copy2(store_path, store_path.with_name(f"{store_path.name}.bak-{int(time.time())}"))
    store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

  cd /opt/openclaw
  sudo docker compose up -d openclaw-gateway
  sudo grep -q "0 5 \* \* \* root /opt/agentmail-email/trigger-email-digest.sh morning" /etc/cron.d/agentmail-email
'

cat <<'EOF'
AgentMail inbox-email pipeline deployed.

Scheduled:
  - internal scheduler poll every 5 minutes (LLM disabled by default)
  - digests at 08:00 / 13:00 / 16:00 / 20:00 MSK via /etc/cron.d/agentmail-email

Useful commands:
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/agentmail-email && sudo docker compose logs --tail=100 agentmail-email-bridge'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'curl -s http://127.0.0.1:8092/health && echo && curl -s http://127.0.0.1:8092/status'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:email'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo cat /etc/cron.d/agentmail-email'
EOF
