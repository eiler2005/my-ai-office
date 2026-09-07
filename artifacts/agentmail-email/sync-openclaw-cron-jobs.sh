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
EMAIL_ENV_FILE="${EMAIL_ENV_FILE:-/opt/agentmail-email/email.env}"
EMAIL_CONFIG_FILE="${EMAIL_CONFIG_FILE:-/opt/agentmail-email/config.json}"
EMAIL_BRIDGE_URL="${EMAIL_BRIDGE_URL:-http://agentmail-email-bridge:8092/trigger}"
EMAIL_CRON_TIMEOUT_SECONDS="${EMAIL_CRON_TIMEOUT_SECONDS:-300}"
EMAIL_CRON_MANAGED_PREFIX="${EMAIL_CRON_MANAGED_PREFIX:-AgentMail Inbox}"
EMAIL_CRON_BRIDGE_LABEL="${EMAIL_CRON_BRIDGE_LABEL:-AgentMail inbox-email bridge}"
EMAIL_CRON_MORNING_TITLE="${EMAIL_CRON_MORNING_TITLE:-Morning brief}"
EMAIL_CRON_INTERVAL_TITLE="${EMAIL_CRON_INTERVAL_TITLE:-Regular digest}"
EMAIL_CRON_EDITORIAL_TITLE="${EMAIL_CRON_EDITORIAL_TITLE:-Evening editorial}"

EMAIL_BRIDGE_TOKEN="${EMAIL_BRIDGE_TOKEN:-}"
if [[ -z "$EMAIL_BRIDGE_TOKEN" && -r "$EMAIL_ENV_FILE" ]]; then
  EMAIL_BRIDGE_TOKEN="$(awk -F= '/^EMAIL_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$EMAIL_ENV_FILE" | tail -n1)"
fi
if [[ -z "$EMAIL_BRIDGE_TOKEN" && -f "$EMAIL_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  EMAIL_BRIDGE_TOKEN="$(sudo awk -F= '/^EMAIL_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$EMAIL_ENV_FILE" | tail -n1)"
fi
if [[ -z "$EMAIL_BRIDGE_TOKEN" ]]; then
  echo "EMAIL_BRIDGE_TOKEN is missing. Set it in $EMAIL_ENV_FILE or the environment." >&2
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
  EMAIL_CRON_TIMEOUT_SECONDS="$EMAIL_CRON_TIMEOUT_SECONDS" \
  EMAIL_CONFIG_FILE="$EMAIL_CONFIG_FILE" \
  EMAIL_BRIDGE_URL="$EMAIL_BRIDGE_URL" \
  EMAIL_BRIDGE_TOKEN="$EMAIL_BRIDGE_TOKEN" \
  EMAIL_CRON_MANAGED_PREFIX="$EMAIL_CRON_MANAGED_PREFIX" \
  EMAIL_CRON_BRIDGE_LABEL="$EMAIL_CRON_BRIDGE_LABEL" \
  EMAIL_CRON_MORNING_TITLE="$EMAIL_CRON_MORNING_TITLE" \
  EMAIL_CRON_INTERVAL_TITLE="$EMAIL_CRON_INTERVAL_TITLE" \
  EMAIL_CRON_EDITORIAL_TITLE="$EMAIL_CRON_EDITORIAL_TITLE" \
  python3 - <<'PYCODE_AGENTMAIL_SYNC'
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

managed_prefix = os.environ["EMAIL_CRON_MANAGED_PREFIX"]
store_path = Path(os.environ["CRON_STORE_PATH"]).expanduser()
config_path = Path(os.environ["EMAIL_CONFIG_FILE"]).expanduser()
agent_id = os.environ["OPENCLAW_CRON_AGENT"]
tz_name = os.environ["OPENCLAW_CRON_TZ"]
bridge_url = os.environ["EMAIL_BRIDGE_URL"]
bridge_token = os.environ["EMAIL_BRIDGE_TOKEN"]
timeout_seconds = int(os.environ["EMAIL_CRON_TIMEOUT_SECONDS"])
bridge_label = os.environ["EMAIL_CRON_BRIDGE_LABEL"]
title_map = {
    "morning": os.environ["EMAIL_CRON_MORNING_TITLE"],
    "interval": os.environ["EMAIL_CRON_INTERVAL_TITLE"],
    "editorial": os.environ["EMAIL_CRON_EDITORIAL_TITLE"],
}

if not store_path.exists():
    raise SystemExit(f"Cron store not found: {store_path}")

raw = json.loads(store_path.read_text())
jobs = raw.get("jobs", []) if isinstance(raw, dict) else raw

existing_by_name = {}
for job in jobs:
    name = str(job.get("name", ""))
    if name.startswith(managed_prefix):
        existing_by_name[name] = job
        if job.get("agentId"):
            agent_id = job["agentId"]

backup_path = store_path.with_name(store_path.name + ".bak-" + str(int(time.time())))
backup_path.write_text(store_path.read_text())

config = {}
if config_path.exists():
    config = json.loads(config_path.read_text())


def normalize_slot(raw: str) -> str:
    value = str(raw).strip()
    if not value:
        raise ValueError("empty schedule slot")
    hour_s, minute_s = (value.split(":", 1) + ["00"])[:2]
    hour = max(0, min(23, int(hour_s)))
    minute = max(0, min(59, int(minute_s)))
    return f"{hour:02d}:{minute:02d}"


raw_slots = list(config.get("schedule_slots", []) or [])
if not raw_slots:
    raw_slots = [f"{int(value):02d}:00" for value in config.get("schedule_hours", [8, 13, 16, 20])]
slot_keys = [normalize_slot(value) for value in raw_slots]

digest_types_raw = config.get("digest_types", {}) or {}
digest_types = {}
for key, value in digest_types_raw.items():
    key_s = str(key).strip()
    if ":" in key_s:
        digest_types[normalize_slot(key_s)] = str(value).strip() or "interval"
    elif key_s:
        digest_types[f"{int(key_s):02d}:00"] = str(value).strip() or "interval"


def next_run_ms(expr: str) -> int:
    now = datetime.now(ZoneInfo(tz_name))
    minute_s, hour_s, *_ = expr.split()
    hour = int(hour_s)
    minute = int(minute_s)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def build_message(job_type: str, digest_type: str | None) -> str:
    payload = {"job_type": job_type}
    if digest_type:
        payload["digest_type"] = digest_type
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""/compact Trigger the {bridge_label} and report only the enqueue result.

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
- job type
- digest type if present
- bridge HTTP result
- whether the job was enqueued"""


specs = []
for idx, slot_key in enumerate(slot_keys):
    hour_s, minute_s = slot_key.split(":", 1)
    digest_type = digest_types.get(slot_key)
    if digest_type not in title_map:
        if idx == 0:
            digest_type = "morning"
        elif idx == len(slot_keys) - 1:
            digest_type = "editorial"
        else:
            digest_type = "interval"
    title = title_map.get(digest_type, title_map["interval"])
    specs.append(
        (
            f"{managed_prefix} · {slot_key} {title}",
            f"{title} for {managed_prefix}",
            f"{int(minute_s)} {int(hour_s)} * * *",
            "digest",
            digest_type,
            None,
        )
    )

filtered_jobs = [job for job in jobs if not str(job.get("name", "")).startswith(managed_prefix)]
now_ms = int(time.time() * 1000)
new_jobs = []
for name, description, expr, job_type, digest_type, model in specs:
    existing = existing_by_name.get(name, {})
    state = dict(existing.get("state", {})) if isinstance(existing, dict) else {}
    state["nextRunAtMs"] = next_run_ms(expr)

    payload = {
        "kind": "agentTurn",
        "message": build_message(job_type, digest_type),
        "timeoutSeconds": timeout_seconds,
        "lightContext": True,
        "toolsAllow": ["exec", "read"],
    }
    if model:
        payload["model"] = model

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
                "expr": expr,
                "tz": tz_name,
                "staggerMs": 0,
            },
            "sessionTarget": "isolated",
            "wakeMode": "now",
            "payload": payload,
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
PYCODE_AGENTMAIL_SYNC

restart_gateway_if_present
echo "OpenClaw cron jobs synced for $EMAIL_CRON_MANAGED_PREFIX."
