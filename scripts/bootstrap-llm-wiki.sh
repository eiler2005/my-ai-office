#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
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

token="$(
  ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
    "sudo awk -F= '/^WIKI_IMPORT_TOKEN=/{print substr(\$0, length(\$1)+2)}' /opt/wiki-import/wiki-import.env | tail -n1"
)"

if [[ -z "$token" ]]; then
  echo "WIKI_IMPORT_TOKEN not found on server." >&2
  exit 1
fi

post_remote() {
  ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
    "curl -sf -X POST http://127.0.0.1:8095/trigger \
      -H 'Authorization: Bearer ${token}' \
      -H 'Content-Type: application/json' \
      --data-binary @-"
}

ingest_text_file() {
  local rel_path="$1"
  local title="$2"
  local goal="$3"
  python3 - "$REPO_ROOT/$rel_path" "$title" "$goal" <<'PY' | post_remote
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
title = sys.argv[2]
goal = sys.argv[3]
payload = {
    "source_type": "text",
    "source": path.read_text(encoding="utf-8"),
    "target_kind": "article",
    "title": title,
    "import_goal": goal,
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

ingest_url() {
  local url="$1"
  local title="$2"
  local goal="$3"
  python3 - "$url" "$title" "$goal" <<'PY' | post_remote
import json
import sys

payload = {
    "source_type": "url",
    "source": sys.argv[1],
    "target_kind": "auto",
    "title": sys.argv[2],
    "import_goal": sys.argv[3],
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

echo "Bootstrapping LLM-Wiki sources on ${OPENCLAW_HOST}"

ingest_text_file \
  "README.md" \
  "OpenClaw FirstSteps README" \
  "Bootstrap core entities around OpenClaw, LightRAG, OmniRoute, signals-bridge, and the current architecture."

ingest_text_file \
  "docs/07-architecture-and-security.md" \
  "OpenClaw Architecture and Security" \
  "Extract infrastructure entities, security boundaries, and the rationale for separate bridge services."

ingest_text_file \
  "docs/10-memory-architecture.md" \
  "OpenClaw Memory Architecture" \
  "Populate concepts for three-tier memory, cold start rules, and curated wiki memory flow."

ingest_text_file \
  "docs/11-lightrag-setup.md" \
  "LightRAG Setup and Operations" \
  "Capture why LightRAG was chosen, how ingest works, and which boundaries are intentionally excluded."

ingest_text_file \
  "docs/llm-wiki-design.md" \
  "LLM-Wiki Rollout Design" \
  "Bootstrap concepts and decisions around LLM-Wiki, curated import, Graphify-inspired confidence, and wiki ownership."

ingest_url \
  "https://telegra.ph/LLM-Wiki--personalnaya-baza-znanij-s-LLM-04-07" \
  "LLM-Wiki Personal Knowledge Base Article" \
  "Capture the external conceptual framing for LLM-Wiki and Memex-style associative knowledge."

ingest_url \
  "https://github.com/safishamsi/graphify" \
  "Graphify Repository" \
  "Capture graph confidence conventions, hub-node ideas, and relationship tagging patterns."

echo "Bootstrap ingestion requests submitted."
