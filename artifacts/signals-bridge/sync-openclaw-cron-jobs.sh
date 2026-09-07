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
SIGNALS_ENV_FILE="${SIGNALS_ENV_FILE:-/opt/signals-bridge/signals.env}"
SIGNALS_CONFIG_FILE="${SIGNALS_CONFIG_FILE:-/opt/signals-bridge/config.json}"
SIGNALS_BRIDGE_URL="${SIGNALS_BRIDGE_URL:-http://signals-bridge:8093/trigger}"
LAST30DAYS_CRON_TIMEOUT_SECONDS="${LAST30DAYS_CRON_TIMEOUT_SECONDS:-240}"

SIGNALS_BRIDGE_TOKEN="${SIGNALS_BRIDGE_TOKEN:-}"
if [[ -z "$SIGNALS_BRIDGE_TOKEN" && -r "$SIGNALS_ENV_FILE" ]]; then
  SIGNALS_BRIDGE_TOKEN="$(awk -F= '/^SIGNALS_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$SIGNALS_ENV_FILE" | tail -n1)"
fi
if [[ -z "$SIGNALS_BRIDGE_TOKEN" && -f "$SIGNALS_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  SIGNALS_BRIDGE_TOKEN="$(sudo awk -F= '/^SIGNALS_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$SIGNALS_ENV_FILE" | tail -n1)"
fi
if [[ -z "$SIGNALS_BRIDGE_TOKEN" ]]; then
  echo "SIGNALS_BRIDGE_TOKEN is missing. Set it in $SIGNALS_ENV_FILE or the environment." >&2
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
  SIGNALS_BRIDGE_URL="$SIGNALS_BRIDGE_URL" \
  SIGNALS_BRIDGE_TOKEN="$SIGNALS_BRIDGE_TOKEN" \
  SIGNALS_CONFIG_FILE="$SIGNALS_CONFIG_FILE" \
  LAST30DAYS_CRON_TIMEOUT_SECONDS="$LAST30DAYS_CRON_TIMEOUT_SECONDS" \
  python3 - <<'PYCODE_SIGNALS_CRON'
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

managed_prefix = "Last30Days Trend"
store_path = Path(os.environ["CRON_STORE_PATH"]).expanduser()
config_path = Path(os.environ["SIGNALS_CONFIG_FILE"]).expanduser()
agent_id = os.environ["OPENCLAW_CRON_AGENT"]
default_tz_name = os.environ["OPENCLAW_CRON_TZ"]
bridge_url = os.environ["SIGNALS_BRIDGE_URL"]
bridge_token = os.environ["SIGNALS_BRIDGE_TOKEN"]
timeout_seconds = int(os.environ["LAST30DAYS_CRON_TIMEOUT_SECONDS"])

if not store_path.exists():
    raise SystemExit(f"Cron store not found: {store_path}")
if not config_path.exists():
    raise SystemExit(f"Signals config not found: {config_path}")

config = json.loads(config_path.read_text())
last30days = dict(config.get("last30days") or {})
enabled = bool(last30days.get("enabled", False))
schedule_expr = str(last30days.get("schedule_expr") or "0 7 * * *").strip()
preset_id = str(last30days.get("preset_id") or "world-radar-v1").strip()
tz_name = str(last30days.get("timezone") or default_tz_name).strip() or default_tz_name

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


def next_run_ms(expr: str) -> int:
    now = datetime.now(ZoneInfo(tz_name))
    minute_s, hour_s, *_ = expr.split()
    if minute_s.startswith("*/"):
        step = int(minute_s[2:])
        candidate = now.replace(second=0, microsecond=0)
        remainder = candidate.minute % step
        candidate += timedelta(minutes=(step - remainder) if remainder else step)
        return int(candidate.timestamp() * 1000)

    hour = int(hour_s)
    minute = int(minute_s)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def build_message() -> str:
    payload = {"job_type": "last30days_daily", "preset_id": preset_id}
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""/compact Trigger the signals bridge daily last30days preset and report only the enqueue result.

Rules:
- Work only on this task.
- Use exec for exactly one command.
- Do not modify files.
- Do not ask clarifying questions.
- Keep the reply to 2-4 factual lines.

Command:
python3 - <<'PY'
import json
import urllib.request

url = {bridge_url!r}
token = {bridge_token!r}
payload = {payload_json}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={{
        "Authorization": f"Bearer {{token}}",
        "Content-Type": "application/json",
    }},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print(resp.read().decode("utf-8"))
PY

Report:
- preset id
- bridge HTTP result
- whether the job was enqueued"""


filtered_jobs = [job for job in jobs if not str(job.get("name", "")).startswith(managed_prefix)]
now_ms = int(time.time() * 1000)
new_jobs = []

if enabled:
    name = "Last30Days Trend · 07:00 Compact daily"
    description = "Compact daily last30days trend run"
    existing = existing_by_name.get(name, {})
    state = dict(existing.get("state", {})) if isinstance(existing, dict) else {}
    state["nextRunAtMs"] = next_run_ms(schedule_expr)
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
                "expr": schedule_expr,
                "tz": tz_name,
                "staggerMs": 0,
            },
            "sessionTarget": "isolated",
            "wakeMode": "now",
            "payload": {
                "kind": "agentTurn",
                "message": build_message(),
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
if new_jobs:
    for job in new_jobs:
        print(f"{job['name']} | {job['schedule']['expr']} | next={job['state']['nextRunAtMs']}")
else:
    print("Removed managed Last30Days Trend jobs (feature disabled).")
PYCODE_SIGNALS_CRON

restart_gateway_if_present
echo "OpenClaw cron jobs synced for Signals Bridge last30days."
