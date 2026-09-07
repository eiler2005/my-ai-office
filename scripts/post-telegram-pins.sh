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
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
SSH_OPTS=(-i "${SSH_KEY}")

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

KNOWLEDGE_TEXT_FILE="${REPO_ROOT}/artifacts/openclaw/telegram-pins/knowledgebase.txt"
IDEAS_TEXT_FILE="${REPO_ROOT}/artifacts/openclaw/telegram-pins/ideas.txt"

if [[ ! -f "${KNOWLEDGE_TEXT_FILE}" || ! -f "${IDEAS_TEXT_FILE}" ]]; then
  echo "Error: pin text files are missing under artifacts/openclaw/telegram-pins/"
  exit 1
fi

echo "=== Posting Telegram topic pins to ${OPENCLAW_HOST} ==="

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

cp "${KNOWLEDGE_TEXT_FILE}" "${TMP_DIR}/knowledgebase.txt"
cp "${IDEAS_TEXT_FILE}" "${TMP_DIR}/ideas.txt"

scp "${SSH_OPTS[@]}" "${TMP_DIR}/knowledgebase.txt" "${TMP_DIR}/ideas.txt" "${OPENCLAW_HOST}:~/"

ssh "${SSH_OPTS[@]}" "${OPENCLAW_HOST}" 'python3 - <<'"'"'PY'"'"'
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path


def read_env_value(path: str, key: str) -> str:
    text = subprocess.check_output(["sudo", "cat", path], text=True)
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def post_and_pin(token: str, chat_id: str, topic_id: int, text: str) -> int:
    base = f"https://api.telegram.org/bot{token}"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "message_thread_id": str(topic_id),
            "text": text,
            "disable_notification": "true",
        }
    ).encode()
    req = urllib.request.Request(f"{base}/sendMessage", data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        raise SystemExit(f"sendMessage failed: {data}")
    message_id = int(data["result"]["message_id"])

    pin_payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "message_id": str(message_id),
            "disable_notification": "true",
        }
    ).encode()
    pin_req = urllib.request.Request(f"{base}/pinChatMessage", data=pin_payload, method="POST")
    with urllib.request.urlopen(pin_req, timeout=30) as resp:
        pin_data = json.loads(resp.read().decode())
    if not pin_data.get("ok"):
        raise SystemExit(f"pinChatMessage failed: {pin_data}")
    return message_id


token = read_env_value("/opt/openclaw/.env", "TELEGRAM_BOT_TOKEN")
if not token:
    openclaw = json.loads(Path("/opt/openclaw/config/openclaw.json").read_text())
    token = str(openclaw.get("channels", {}).get("telegram", {}).get("botToken", "")).strip()
if not token or token.startswith("<"):
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in /opt/openclaw/.env and openclaw.json")
topic_map = json.loads(Path("/opt/openclaw/config/telegram-topic-map.json").read_text())
chat_id = str(topic_map["chat_id"])
knowledge_topic = int(topic_map["topics"]["knowledgebase"]["message_thread_id"])
ideas_topic = int(topic_map["topics"]["ideas"]["message_thread_id"])

knowledge_text = Path.home().joinpath("knowledgebase.txt").read_text(encoding="utf-8").strip()
ideas_text = Path.home().joinpath("ideas.txt").read_text(encoding="utf-8").strip()

knowledge_message_id = post_and_pin(token, chat_id, knowledge_topic, knowledge_text)
ideas_message_id = post_and_pin(token, chat_id, ideas_topic, ideas_text)

print(json.dumps(
    {
        "ok": True,
        "chat_id": chat_id,
        "knowledge_topic_id": knowledge_topic,
        "knowledge_message_id": knowledge_message_id,
        "ideas_topic_id": ideas_topic,
        "ideas_message_id": ideas_message_id,
    },
    ensure_ascii=False,
))
PY'

echo "=== Done. Telegram topic pins posted and pinned. ==="
