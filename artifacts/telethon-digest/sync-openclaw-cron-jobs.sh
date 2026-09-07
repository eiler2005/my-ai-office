#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

OPENCLAW_CRON_AGENT="${OPENCLAW_CRON_AGENT:-main}"
OPENCLAW_CRON_TZ="${OPENCLAW_CRON_TZ:-Europe/Moscow}"
OPENCLAW_CRON_STORE="${OPENCLAW_CRON_STORE:-}"
TELETHON_ENV_FILE="${TELETHON_ENV_FILE:-/opt/telethon-digest/telethon.env}"
DIGEST_CRON_BRIDGE_URL="${DIGEST_CRON_BRIDGE_URL:-http://telethon-digest-cron-bridge:8091/trigger}"
DIGEST_CRON_TIMEOUT_SECONDS="${DIGEST_CRON_TIMEOUT_SECONDS:-1800}"

DIGEST_CRON_BRIDGE_TOKEN="${DIGEST_CRON_BRIDGE_TOKEN:-}"
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" && -r "$TELETHON_ENV_FILE" ]]; then
  DIGEST_CRON_BRIDGE_TOKEN="$(awk -F= '/^DIGEST_CRON_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$TELETHON_ENV_FILE" | tail -n1)"
fi
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" && -f "$TELETHON_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  DIGEST_CRON_BRIDGE_TOKEN="$(sudo awk -F= '/^DIGEST_CRON_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$TELETHON_ENV_FILE" | tail -n1)"
fi
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" ]]; then
  echo "DIGEST_CRON_BRIDGE_TOKEN is missing. Set it in $TELETHON_ENV_FILE or the environment." >&2
  exit 1
fi

resolve_cron_store() {
  if [[ -n "$OPENCLAW_CRON_STORE" ]]; then
    echo "$OPENCLAW_CRON_STORE"
    return 0
  fi

  local candidate
  for candidate in \
    /opt/openclaw/config/cron/jobs.json \
    /home/deploy/.openclaw/cron/jobs.json
  do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
    if command -v sudo >/dev/null 2>&1 && sudo test -f "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  echo "OpenClaw cron store not found. Set OPENCLAW_CRON_STORE explicitly." >&2
  exit 1
}

restart_gateway_if_present() {
  local gateway_name="openclaw-openclaw-gateway-1"
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$gateway_name"; then
    docker restart "$gateway_name" >/dev/null
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo docker ps --format '{{.Names}}' | grep -qx "$gateway_name"; then
    sudo docker restart "$gateway_name" >/dev/null
  fi
}

CRON_STORE_PATH="$(resolve_cron_store)"

sudo env \
  CRON_STORE_PATH="$CRON_STORE_PATH" \
  OPENCLAW_CRON_AGENT="$OPENCLAW_CRON_AGENT" \
  OPENCLAW_CRON_TZ="$OPENCLAW_CRON_TZ" \
  DIGEST_CRON_TIMEOUT_SECONDS="$DIGEST_CRON_TIMEOUT_SECONDS" \
  DIGEST_CRON_BRIDGE_URL="$DIGEST_CRON_BRIDGE_URL" \
  DIGEST_CRON_BRIDGE_TOKEN="$DIGEST_CRON_BRIDGE_TOKEN" \
  python3 - <<'PYCODE_TELETHON_SYNC'
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

managed_prefix = "Telethon Digest"
store_path = Path(os.environ["CRON_STORE_PATH"]).expanduser()
agent_id = os.environ["OPENCLAW_CRON_AGENT"]
tz_name = os.environ["OPENCLAW_CRON_TZ"]
bridge_url = os.environ["DIGEST_CRON_BRIDGE_URL"]
bridge_token = os.environ["DIGEST_CRON_BRIDGE_TOKEN"]
timeout_seconds = int(os.environ["DIGEST_CRON_TIMEOUT_SECONDS"])

if not store_path.exists():
    raise SystemExit(f"Cron store not found: {store_path}")

raw = json.loads(store_path.read_text())
jobs = raw.get("jobs", raw if isinstance(raw, list) else [])

existing_by_name = {}
for job in jobs:
    name = str(job.get("name", ""))
    if name.startswith(managed_prefix):
        existing_by_name[name] = job
        if job.get("agentId"):
            agent_id = job["agentId"]

backup_path = store_path.with_name(store_path.name + ".bak-" + str(int(time.time())))
backup_path.write_text(store_path.read_text())


def next_run_ms(hour: int) -> int:
    now = datetime.now(ZoneInfo(tz_name))
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def build_message(digest_type: str, hour: int, minute: int = 0) -> str:
    return f"""/compact Trigger the Telegram digest bridge and report the outcome in 3-5 plain lines.

Rules:
- Work only on this task.
- Use exec for exactly one command.
- Do not modify files.
- Do not ask clarifying questions.
- Keep the reply short and factual.

Command:
python3 - <<'PY'
import json
import urllib.request

url = {bridge_url!r}
token = {bridge_token!r}
payload = {{
    "digest_type": {digest_type!r},
    "slot_hour": {hour},
    "slot_minute": {minute},
}}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={{
        "Authorization": f"Bearer {{token}}",
        "Content-Type": "application/json",
    }},
    method="POST",
)
with urllib.request.urlopen(req, timeout=3600) as resp:
    print(resp.read().decode("utf-8"))
PY

Report:
- digest type
- bridge HTTP result
- whether Telegram posting appears successful from the bridge response
- first actionable error if the run failed

If the bridge returns 409 digest_already_running, report that another digest is still in progress instead of calling it a hang."""


specs = [
    ("Telethon Digest · 08:00 Morning brief", "Morning brief for Telegram Digest", 8, "morning"),
    ("Telethon Digest · 11:00 Regular digest", "Regular interval digest", 11, "interval"),
    ("Telethon Digest · 14:00 Regular digest", "Regular interval digest", 14, "interval"),
    ("Telethon Digest · 17:00 Regular digest", "Regular interval digest", 17, "interval"),
    ("Telethon Digest · 21:00 Evening editorial", "Evening editorial digest", 21, "editorial"),
]

filtered_jobs = [job for job in jobs if not str(job.get("name", "")).startswith(managed_prefix)]
now_ms = int(time.time() * 1000)
new_jobs = []
for name, description, hour, digest_type in specs:
    existing = existing_by_name.get(name, {})
    state = dict(existing.get("state", {})) if isinstance(existing, dict) else {}
    state["nextRunAtMs"] = next_run_ms(hour)

    new_jobs.append(
        {
            "id": existing.get("id") or str(uuid.uuid4()),
            "agentId": existing.get("agentId") or agent_id,
            "name": name,
            "description": description,
            "enabled": True,
            "createdAtMs": existing.get("createdAtMs") or now_ms,
            "updatedAtMs": now_ms,
            "schedule": {
                "kind": "cron",
                "expr": f"0 {hour} * * *",
                "tz": tz_name,
                "staggerMs": 0,
            },
            "sessionTarget": "isolated",
            "wakeMode": "now",
            "payload": {
                "kind": "agentTurn",
                "message": build_message(digest_type, hour),
                "timeoutSeconds": timeout_seconds,
                "lightContext": True,
                "toolsAllow": ["exec", "read"],
            },
            "delivery": {
                "mode": "none",
                "channel": "last",
            },
            "state": state,
        }
    )

if isinstance(raw, dict):
    raw["jobs"] = filtered_jobs + new_jobs
    output = raw
else:
    output = filtered_jobs + new_jobs

store_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
print(f"Patched {store_path}")
for job in new_jobs:
    print(f"{job['name']} | {job['schedule']['expr']} | next={job['state']['nextRunAtMs']}")
PYCODE_TELETHON_SYNC

restart_gateway_if_present
echo "OpenClaw cron jobs synced for Telethon Digest."
