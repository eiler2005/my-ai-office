#!/usr/bin/env python3
"""Apply the reviewed transport replacements once in the separate Hermes checkout.

This script never reads the live server or private state. Business algorithms and
their semantic validators stay in place. Re-running is a no-op after migration.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, replacements):
    text = path.read_text()
    tree = ast.parse(text)
    edits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in replacements:
            edits.append((node.lineno - 1, node.end_lineno, replacements.pop(node.name)))
    if replacements:
        raise ValueError(f"Missing expected functions in {path.name}: {sorted(replacements)}")
    lines = text.splitlines(keepends=True)
    for start, end, value in sorted(edits, reverse=True):
        lines[start:end] = [value.strip() + "\n"]
    path.write_text("".join(lines))


def main():
    artifacts = ROOT / "artifacts"
    marker = ROOT / "deploy/hermes/adapters-applied.txt"
    if marker.exists():
        print("Hermes adapters already applied")
        return
    (artifacts / "agentmail-email/agent_runner.py").write_text(
        '"""Hermes background model adapter; validators retain the existing result contract."""\n'
        'from benka_integrations.models import (AgentRunError, AgentRunResult, run_agent_json,\n'
        '                                       extract_json_payload, strip_markdown_fences)\n')
    replace(artifacts / "signals-bridge/omniroute_client.py", {"_run_openclaw_prompt": '''
def _run_openclaw_prompt(prompt: str) -> dict[str, Any]:
    # Compatibility name for the first route; runtime is exclusively Hermes.
    from benka_integrations.models import run_agent_json
    result = run_agent_json(prompt, timeout_seconds=180).payload
    result.setdefault("model_meta", {"model_id": "hermes-background", "tier": "light",
                                      "provider_fallback": False, "local_fallback": False})
    return result
'''})
    replace(artifacts / "telethon-digest/omniroute_client.py", {"_call_openclaw_fallback": '''
def _call_openclaw_fallback(payload: dict[str, Any], *, default_model: str) -> LLMCompletion:
    from benka_integrations.models import run_agent_text
    text = run_agent_text(_messages_to_agent_prompt(payload), timeout_seconds=180)
    return LLMCompletion(text=text, model_id="hermes-background", prompt_tokens=0, completion_tokens=0)
'''})
    for service in ("telethon-digest", "signals-bridge"):
        path = artifacts / service / "omniroute_client.py"
        text = path.read_text().replace('os.environ.get("OPENCLAW_FALLBACK_ENABLED", "1")', 'os.environ.get("HERMES_MODEL_ENABLED", "1")')
        text = text.replace("OpenClaw/OpenAI", "Hermes").replace('route_errors.append(f"openclaw:', 'route_errors.append(f"hermes:')
        path.write_text(text)
    replace(artifacts / "agentmail-email/poster.py", {"post_html_message": '''
async def post_html_message(text: str) -> bool:
    from benka_integrations.legacy_delivery import post_text
    for chunk in _apply_part_headers(_split_text(text)):
        await post_text(chunk, chat_id=SUPERGROUP_ID, topic_id=TOPIC_ID)
    return True
'''})
    replace(artifacts / "telethon-digest/poster.py", {"post_digest": '''
async def post_digest(document: DigestDocument) -> bool:
    from benka_integrations.legacy_delivery import post_text
    for chunk in _apply_part_headers(_split_text(render_digest_html(document))):
        await post_text(chunk, chat_id=SUPERGROUP_ID, topic_id=TOPIC_ID)
    return True
'''})
    # Hermes send has no copyMessage verb. Preserve original forwarding code for
    # reference, but fail closed until a receipt-aware native forwarding adapter
    # is accepted. Source links remain available in the text publication.
    replace(artifacts / "signals-bridge/poster.py", {
        "post_html_message": '''
async def post_html_message(text: str, *, chat_id: int | None = None, topic_id: int | None = None) -> bool:
    from benka_integrations.legacy_delivery import post_text
    chat, topic = _resolve_target(chat_id, topic_id)
    for chunk in _split_text(text):
        await post_text(chunk, chat_id=chat, topic_id=topic)
    return True
''', "post_plain_text_message": '''
async def post_plain_text_message(text: str, *, chat_id: int | None = None, topic_id: int | None = None) -> bool:
    from benka_integrations.legacy_delivery import post_text
    chat, topic = _resolve_target(chat_id, topic_id)
    for chunk in _split_text(text):
        await post_text(chunk, chat_id=chat, topic_id=topic, html=False)
    return True
'''})
    # Direct execution of an inherited bridge must not revive a second owner of
    # schedules or HTTP entry points. The native worker imports only job functions.
    for service in ("agentmail-email", "telethon-digest", "signals-bridge"):
        replace(artifacts / service / "cron_bridge.py", {"main": '''
def main() -> None:
    raise SystemExit("Legacy bridge entrypoint disabled. Use benka worker with a reviewed manifest.")
'''})
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("Hermes adapter migration v1 applied. See scripts/prepare-hermes-adapters.py.\n")
    print("Hermes model, delivery and worker adapters applied")


if __name__ == "__main__":
    main()
