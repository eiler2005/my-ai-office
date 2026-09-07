#!/usr/bin/env bash
# Blocks host-level installs of agent runtime dependencies.
#
# Runtime dependencies in this project are container-only by policy: the agent
# runs under /opt/benka-hermes with a read-only root and no Docker socket, and
# the VPS is shared with unrelated projects. Installing a runtime dependency on
# the host OS both breaks reproducibility and touches a machine this project
# does not own alone.
#
# Allowed: the same install inside a Dockerfile, a build, or docker compose exec.
set -euo pipefail

INPUT=$(cat)
COMMAND=$(
  printf '%s' "$INPUT" | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)

print(payload.get("tool_input", {}).get("command", ""))
' 2>/dev/null || true
)

LOWER_COMMAND=$(printf '%s' "$COMMAND" | tr '[:upper:]' '[:lower:]')

INSTALL_PATTERN='(apt(-get)?[[:space:]]+install|pip3?[[:space:]]+install|python3[[:space:]]+-m[[:space:]]+pip[[:space:]]+install|uv[[:space:]]+(pip[[:space:]]+install|sync)|brew[[:space:]]+install|npm[[:space:]]+install[[:space:]]+-g)'
AGENT_RUNTIME_PATTERN='(hermes|hermes-agent|benka|telethon|lightrag|openai-whisper|whisper|ffmpeg|ffprobe|torch)'
CONTAINER_CONTEXT_PATTERN='(docker[[:space:]]+compose[[:space:]]+(exec|run|build)|docker[[:space:]]+build|dockerfile|/opt/benka-hermes/|\.venv/)'

if printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$INSTALL_PATTERN" \
  && printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$AGENT_RUNTIME_PATTERN" \
  && ! printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$CONTAINER_CONTEXT_PATTERN"; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Agent runtime dependencies in this project are container-only by policy. Add them to deploy/hermes/Dockerfile and rebuild, or run inside the container via docker compose exec -- not on the shared VPS host OS. See CLAUDE.md 'Runtime boundary'."}}
EOF
fi
