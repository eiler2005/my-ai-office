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
WIKI_IMPORT_ENV_FILE="${WIKI_IMPORT_ENV_FILE:-/opt/wiki-import/wiki-import.env}"
WIKI_IMPORT_URL="${WIKI_IMPORT_URL:-http://wiki-import:8095/maintain}"
WIKI_IMPORT_CRON_TIMEOUT_SECONDS="${WIKI_IMPORT_CRON_TIMEOUT_SECONDS:-240}"
WIKI_IMPORT_CRON_MANAGED_PREFIX="${WIKI_IMPORT_CRON_MANAGED_PREFIX:-Wiki Lifecycle}"

WIKI_IMPORT_TOKEN="${WIKI_IMPORT_TOKEN:-}"
if [[ -z "$WIKI_IMPORT_TOKEN" && -r "$WIKI_IMPORT_ENV_FILE" ]]; then
  WIKI_IMPORT_TOKEN="$(awk -F= '/^WIKI_IMPORT_TOKEN=/{print substr($0, length($1)+2)}' "$WIKI_IMPORT_ENV_FILE" | tail -n1)"
fi
if [[ -z "$WIKI_IMPORT_TOKEN" && -f "$WIKI_IMPORT_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  WIKI_IMPORT_TOKEN="$(sudo awk -F= '/^WIKI_IMPORT_TOKEN=/{print substr($0, length($1)+2)}' "$WIKI_IMPORT_ENV_FILE" | tail -n1)"
fi
if [[ -z "$WIKI_IMPORT_TOKEN" ]]; then
  echo "WIKI_IMPORT_TOKEN is missing. Set it in $WIKI_IMPORT_ENV_FILE or the environment." >&2
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
  WIKI_IMPORT_URL="$WIKI_IMPORT_URL" \
  WIKI_IMPORT_TOKEN="$WIKI_IMPORT_TOKEN" \
  WIKI_IMPORT_CRON_TIMEOUT_SECONDS="$WIKI_IMPORT_CRON_TIMEOUT_SECONDS" \
  WIKI_IMPORT_CRON_MANAGED_PREFIX="$WIKI_IMPORT_CRON_MANAGED_PREFIX" \
  python3 - <<'PYCODE_WIKI_IMPORT_CRON'
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

managed_prefix = os.environ["WIKI_IMPORT_CRON_MANAGED_PREFIX"]
store_path = Path(os.environ["CRON_STORE_PATH"]).expanduser()
agent_id = os.environ["OPENCLAW_CRON_AGENT"]
tz_name = os.environ["OPENCLAW_CRON_TZ"]
maintain_url = os.environ["WIKI_IMPORT_URL"]
token = os.environ["WIKI_IMPORT_TOKEN"]
timeout_seconds = int(os.environ["WIKI_IMPORT_CRON_TIMEOUT_SECONDS"])

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


def next_run_ms(expr: str) -> int:
    now = datetime.now(ZoneInfo(tz_name))
    minute_s, hour_s, *_ = expr.split()
    hour = int(hour_s)
    minute = int(minute_s)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def build_message(*, mode: str, actions: list[str], label: str) -> str:
    payload_json = json.dumps({"mode": mode, "actions": actions}, ensure_ascii=False)
    return f"""/compact Trigger the wiki-import lifecycle maintenance job and report only the HTTP result.

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

url = {maintain_url!r}
token = {token!r}
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
- job label
- mode
- bridge HTTP result
- whether lifecycle maintenance reported success

Label:
- {label}"""


specs = [
    (
        f"{managed_prefix} · Daily report",
        "Daily wiki lifecycle dry-run report",
        "45 5 * * *",
        "dry_run",
        ["report"],
        "daily dry-run",
    ),
    (
        f"{managed_prefix} · Weekly archive refresh",
        "Weekly wiki lifecycle archive/apply refresh",
        "15 6 * * 0",
        "apply",
        ["report", "archive", "refresh_topics", "refresh_overview"],
        "weekly apply",
    ),
]

filtered_jobs = [job for job in jobs if not str(job.get("name", "")).startswith(managed_prefix)]
now_ms = int(time.time() * 1000)
new_jobs = []
for name, description, expr, mode, actions, label in specs:
    existing = existing_by_name.get(name, {})
    state = dict(existing.get("state", {})) if isinstance(existing, dict) else {}
    state["nextRunAtMs"] = next_run_ms(expr)
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
            "payload": {
                "kind": "agentTurn",
                "message": build_message(mode=mode, actions=actions, label=label),
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
PYCODE_WIKI_IMPORT_CRON

restart_gateway_if_present
echo "OpenClaw cron jobs synced for wiki-import lifecycle maintenance."
