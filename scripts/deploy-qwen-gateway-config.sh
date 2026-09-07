#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PREDECESSOR-ERA SCRIPT -- DO NOT RUN AGAINST PRODUCTION.
# Targets the retired OpenClaw deployment. Production moved to Hermes Agent on
# 2026-09-06 and is operated through docs/hermes/operations.md. Kept for
# rollback and migration reference only. See scripts/README.md.
# ---------------------------------------------------------------------------

# Apply only the Qwen direct-provider and fallback-order migration to the
# existing live OpenClaw config. The remote script makes a dated backup before
# replacing the JSON and never emits environment values.

set -euo pipefail

OPENCLAW_HOST=${OPENCLAW_HOST-}
SSH_KEY=${SSH_KEY-$HOME/.ssh/id_rsa}

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: deploy@<server-host>" >&2
  exit 1
fi

ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20 "$OPENCLAW_HOST" 'sudo python3 -' <<'PY'
import datetime
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

config_path = Path("/opt/openclaw/config/openclaw.json")
env_path = Path("/opt/openclaw/.env")
compose_path = Path("/opt/openclaw/docker-compose.yml")
backup_dir = Path("/opt/openclaw/backups")

if not config_path.is_file():
    raise SystemExit("Missing /opt/openclaw/config/openclaw.json")
if not env_path.is_file():
    raise SystemExit("Missing /opt/openclaw/.env")
if not compose_path.is_file():
    raise SystemExit("Missing /opt/openclaw/docker-compose.yml")
if not any(
    line.startswith("DASHSCOPE_API_KEY=") and line.partition("=")[2].strip()
    for line in env_path.read_text().splitlines()
):
    raise SystemExit("DASHSCOPE_API_KEY is missing from /opt/openclaw/.env")

def atomic_replace(path: Path, content: str, *, prefix: str) -> None:
    original_stat = path.stat()
    fd, temp_name = tempfile.mkstemp(prefix=prefix, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temp_name, stat.S_IMODE(original_stat.st_mode))
        os.chown(temp_name, original_stat.st_uid, original_stat.st_gid)
        os.replace(temp_name, path)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


data = json.loads(config_path.read_text())
providers = data.setdefault("models", {}).setdefault("providers", {})
if "deepseek-direct" not in providers:
    raise SystemExit("Refusing migration: deepseek-direct reserve is absent")

providers["qwen-direct"] = {
    "baseUrl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "apiKey": {
        "source": "env",
        "provider": "default",
        "id": "DASHSCOPE_API_KEY",
    },
    "api": "openai-completions",
    "models": [
        {
            "id": "qwen3.7-flash",
            "name": "Qwen3.7 Flash Direct",
            "api": "openai-completions",
            "reasoning": False,
            "input": ["text"],
            "cost": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
            },
            "contextWindow": 1000000,
            "maxTokens": 65536,
        }
    ],
}

model_policy = data.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})
qwen = "qwen-direct/qwen3.7-flash"
deepseek = "deepseek-direct/deepseek-chat"
existing = model_policy.get("fallbacks", [])
if not isinstance(existing, list):
    existing = []
model_policy["fallbacks"] = [
    qwen,
    *[value for value in existing if value not in {qwen, deepseek}],
    deepseek,
]

# Qwen and the direct DeepSeek reserve are intentionally text-only in this
# deployment. Disable auto media understanding so a failed primary vision route
# cannot turn an attachment into a misleading Qwen "analyze image" attempt.
media = data.setdefault("tools", {}).setdefault("media", {})
for capability in ("image", "audio", "video"):
    media.setdefault(capability, {})["enabled"] = False

# Validate the Compose insertion point before replacing the JSON so a malformed
# Compose file cannot leave a partially applied migration.
compose_content = compose_path.read_text()
qwen_env_line = "      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}\n"
deepseek_env_line = "      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY}\n"
if qwen_env_line not in compose_content and compose_content.count(deepseek_env_line) != 2:
    raise SystemExit("Refusing migration: unexpected DeepSeek Compose wiring")

backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
backup_path = backup_dir / f"openclaw.json.pre-qwen.{stamp}"
shutil.copy2(config_path, backup_path)

config_content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
atomic_replace(config_path, config_content, prefix="openclaw.json.qwen.")

# The server .env alone does not make a secret available inside a Compose
# container. Add this exact non-secret interpolation beside the existing
# DeepSeek wiring for both gateway and CLI definitions when it is absent.
compose_backup_path = None
if qwen_env_line not in compose_content:
    compose_backup_path = backup_dir / f"docker-compose.yml.pre-qwen.{stamp}"
    shutil.copy2(compose_path, compose_backup_path)
    compose_content = compose_content.replace(deepseek_env_line, qwen_env_line + deepseek_env_line)
    atomic_replace(compose_path, compose_content, prefix="docker-compose.yml.qwen.")

print(
    json.dumps(
        {
            "ok": True,
            "backup": backup_path.name,
            "compose_backup": compose_backup_path.name if compose_backup_path else None,
            "primary": model_policy.get("primary"),
            "fallbacks": model_policy["fallbacks"],
            "media_auto_understanding": {
                capability: media[capability]["enabled"]
                for capability in ("image", "audio", "video")
            },
        }
    )
)
PY

ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20 "$OPENCLAW_HOST" '
  set -e
  cd /opt/openclaw
  sudo docker compose up -d --force-recreate openclaw-gateway
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:18789/healthz >/dev/null 2>&1; then
      echo gateway-healthy
      exit 0
    fi
    sleep 2
  done
  echo "OpenClaw Gateway did not become healthy in time." >&2
  exit 1
'
