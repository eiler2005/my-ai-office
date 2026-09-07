#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# Deploy the LLM-Wiki scaffold into the Obsidian vault on the server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
SSH=(ssh -i "${SSH_KEY}")
TARGET_ROOT="${TARGET_ROOT:-/opt/obsidian-vault}"
SOURCE_DIR="${REPO_ROOT}/artifacts/llm-wiki"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Error: source scaffold not found: ${SOURCE_DIR}"
  exit 1
fi

echo "=== Deploying LLM-Wiki scaffold to ${OPENCLAW_HOST}:${TARGET_ROOT} ==="

"${SSH[@]}" "${OPENCLAW_HOST}" "
  sudo mkdir -p '${TARGET_ROOT}/wiki/templates' \
                '${TARGET_ROOT}/wiki/concepts' \
                '${TARGET_ROOT}/wiki/entities' \
                '${TARGET_ROOT}/wiki/decisions' \
                '${TARGET_ROOT}/wiki/sessions' \
                '${TARGET_ROOT}/wiki/research' \
                '${TARGET_ROOT}/raw/articles' \
                '${TARGET_ROOT}/raw/signals' \
                '${TARGET_ROOT}/raw/documents' \
                '${TARGET_ROOT}/legacy-vault'
"

COPYFILE_DISABLE=1 tar -C "${SOURCE_DIR}" -cf - . | "${SSH[@]}" "${OPENCLAW_HOST}" "sudo tar -C '${TARGET_ROOT}/wiki' -xf -"

"${SSH[@]}" "${OPENCLAW_HOST}" "find '${TARGET_ROOT}/wiki' -name '._*' -type f -delete"

"${SSH[@]}" "${OPENCLAW_HOST}" "sudo chown -R deploy:deploy '${TARGET_ROOT}/wiki' '${TARGET_ROOT}/raw'"

echo "LLM-Wiki scaffold deployed."
echo "Legacy vault content remains untouched and should stay outside LightRAG ingest."
