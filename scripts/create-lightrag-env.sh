#!/usr/bin/env bash
# create-lightrag-env.sh
# Creates scripts/lightrag.env by prompting for OmniRoute and wiki-import keys.
# OmniRoute `light` uses Qwen first and DeepSeek only as the last reserve;
# wiki-import provides local OpenAI-compatible embeddings.
#
# Usage:
#   ./scripts/create-lightrag-env.sh
#
# If OMNIROUTE_API_KEY and/or WIKI_IMPORT_TOKEN are already set in the
# environment, they are used automatically without prompting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/lightrag.env"
TEMPLATE="${SCRIPT_DIR}/lightrag.env.template"

if [[ -f "${ENV_FILE}" ]]; then
  echo "lightrag.env already exists at ${ENV_FILE}"
  read -p "Overwrite? [y/N] " confirm
  [[ "${confirm}" == "y" || "${confirm}" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

# Get OmniRoute API key for LightRAG LLM extraction.
if [[ -n "${OMNIROUTE_API_KEY:-}" ]]; then
  OMNIROUTE_KEY="${OMNIROUTE_API_KEY}"
  echo "Using OMNIROUTE_API_KEY from environment."
else
  echo ""
  echo "Enter your OmniRoute API key."
  echo "This is used by the internal light route (Qwen first, DeepSeek reserve)."
  echo ""
  read -rsp "OmniRoute API key: " OMNIROUTE_KEY
  echo ""
fi

if [[ -z "${OMNIROUTE_KEY}" ]]; then
  echo "Error: OmniRoute API key cannot be empty."
  exit 1
fi

# Get wiki-import token for local embeddings.
if [[ -n "${WIKI_IMPORT_TOKEN:-}" ]]; then
  WIKI_IMPORT_KEY="${WIKI_IMPORT_TOKEN}"
  echo "Using WIKI_IMPORT_TOKEN from environment."
else
  echo ""
  echo "Enter your wiki-import bearer token."
  echo "This is the same token used by /opt/wiki-import/wiki-import.env."
  echo ""
  read -rsp "wiki-import token: " WIKI_IMPORT_KEY
  echo ""
fi

if [[ -z "${WIKI_IMPORT_KEY}" ]]; then
  echo "Error: wiki-import token cannot be empty."
  exit 1
fi

# Write env file from template.
python3 - "$TEMPLATE" "$ENV_FILE" "$OMNIROUTE_KEY" "$WIKI_IMPORT_KEY" <<'PY'
import sys
from pathlib import Path

template, env_file, omniroute_key, wiki_import_key = sys.argv[1:5]
text = Path(template).read_text()
text = text.replace("<your-omniroute-api-key>", omniroute_key)
text = text.replace("<your-wiki-import-token>", wiki_import_key)
Path(env_file).write_text(text)
PY
chmod 600 "${ENV_FILE}"

echo ""
echo "Created: ${ENV_FILE}"
echo ""
echo "Next step:"
echo "  OPENCLAW_HOST=deploy@<server-host> LIGHTRAG_ENV_FILE=${ENV_FILE} ./scripts/setup-lightrag.sh"
