#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)

MODE="run"
if [[ "${1:-}" == "--install-cron" ]]; then
  MODE="install"
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  OPENCLAW_HOST=deploy@<server-host> scripts/recover-telegram-ingress-spool.sh
  OPENCLAW_HOST=deploy@<server-host> scripts/recover-telegram-ingress-spool.sh --install-cron

Requeues Telegram isolated-polling spool claims that were created before the
current openclaw-gateway container start. This handles graceful/recreate races
where the new container reuses the same PID and OpenClaw still treats old
.json.processing files as live.
EOF
  exit 0
fi

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" "MODE=$MODE bash -s" <<'REMOTE'
set -euo pipefail

install_guard() {
  sudo tee /usr/local/sbin/openclaw-telegram-spool-guard >/dev/null <<'GUARD'
#!/usr/bin/env bash
set -euo pipefail

container="${OPENCLAW_GATEWAY_CONTAINER:-openclaw-openclaw-gateway-1}"
spool_dir="${OPENCLAW_TELEGRAM_SPOOL_DIR:-/home/node/.openclaw/telegram/ingress-spool-default}"

if ! sudo docker inspect "$container" >/dev/null 2>&1; then
  exit 0
fi

started_at="$(sudo docker inspect -f '{{.State.StartedAt}}' "$container")"
started_ms="$(python3 - "$started_at" <<'PY'
import datetime
import sys

value = sys.argv[1].replace("Z", "+00:00")
dt = datetime.datetime.fromisoformat(value)
print(int(dt.timestamp() * 1000))
PY
)"

summary="$(
  sudo docker exec \
    -e GATEWAY_STARTED_MS="$started_ms" \
    -e SPOOL_DIR="$spool_dir" \
    "$container" \
    node <<'NODE'
const fs = require("node:fs");
const path = require("node:path");

const spoolDir = process.env.SPOOL_DIR;
const gatewayStartedMs = Number(process.env.GATEWAY_STARTED_MS || "0");
const summary = {
  checked: 0,
  requeued: 0,
  droppedDuplicates: 0,
  skippedCurrent: 0,
  errors: [],
};

if (!spoolDir || !Number.isFinite(gatewayStartedMs) || gatewayStartedMs <= 0) {
  console.log(JSON.stringify({ ...summary, errors: ["invalid-input"] }));
  process.exit(0);
}

let files = [];
try {
  files = fs.readdirSync(spoolDir).filter((file) => file.endsWith(".json.processing")).sort();
} catch (err) {
  if (err && err.code === "ENOENT") {
    console.log(JSON.stringify(summary));
    process.exit(0);
  }
  throw err;
}

for (const file of files) {
  summary.checked += 1;
  const processingPath = path.join(spoolDir, file);
  const pendingPath = processingPath.slice(0, -".processing".length);
  let claimedAt = 0;
  try {
    const payload = JSON.parse(fs.readFileSync(processingPath, "utf8"));
    claimedAt = Number(payload?.claim?.claimedAt || 0);
    if (!Number.isFinite(claimedAt) || claimedAt <= 0) {
      claimedAt = fs.statSync(processingPath).mtimeMs;
    }
    if (claimedAt >= gatewayStartedMs) {
      summary.skippedCurrent += 1;
      continue;
    }
    if (fs.existsSync(pendingPath)) {
      fs.unlinkSync(processingPath);
      summary.droppedDuplicates += 1;
    } else {
      fs.renameSync(processingPath, pendingPath);
      summary.requeued += 1;
    }
  } catch (err) {
    summary.errors.push(`${file}: ${err && err.message ? err.message : String(err)}`);
  }
}

console.log(JSON.stringify(summary));
NODE
)"

if echo "$summary" | grep -Eq '"(requeued|droppedDuplicates)":[1-9]'; then
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$summary"
fi
GUARD

  sudo chmod 0755 /usr/local/sbin/openclaw-telegram-spool-guard
  sudo tee /etc/cron.d/openclaw-telegram-spool-guard >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

* * * * * root /usr/local/sbin/openclaw-telegram-spool-guard >> /var/log/openclaw-telegram-spool-guard.log 2>&1
CRON
}

if [[ "${MODE:-run}" == "install" ]]; then
  install_guard
fi

/usr/local/sbin/openclaw-telegram-spool-guard
REMOTE
