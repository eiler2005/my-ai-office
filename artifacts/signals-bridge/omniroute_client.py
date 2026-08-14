"""
OpenClaw/OpenAI-first model client with OmniRoute, Qwen, DeepSeek, and local fallback.
"""
from __future__ import annotations

import contextlib
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from matching import local_event_from_candidate
from models import ModelMeta, PreparedSignalBatch, SignalCandidate, SignalEvent
from prompts import build_prepare_signal_batch_prompt


OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20129/v1/chat/completions").strip()
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "").strip()
OMNIROUTE_MODEL = os.environ.get("OMNIROUTE_MODEL", "light").strip() or "light"
OMNIROUTE_TIMEOUT_SECONDS = int(os.environ.get("OMNIROUTE_TIMEOUT_SECONDS", "45") or 45)
OMNIROUTE_MAX_TOKENS = int(os.environ.get("OMNIROUTE_MAX_TOKENS", "500") or 500)
OMNIROUTE_TEMPERATURE = float(os.environ.get("OMNIROUTE_TEMPERATURE", "0.1") or 0.1)

OPENCLAW_FALLBACK_ENABLED = os.environ.get("OPENCLAW_FALLBACK_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
OPENCLAW_EXEC_CONTAINER = os.environ.get("OPENCLAW_EXEC_CONTAINER", "openclaw-openclaw-gateway-1").strip()
OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main").strip() or "main"
OPENCLAW_FALLBACK_MODEL = os.environ.get("OPENCLAW_FALLBACK_MODEL", "openai/gpt-5.5").strip()
OPENCLAW_FALLBACK_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_FALLBACK_TIMEOUT_SECONDS", "180") or 180)
OPENCLAW_FALLBACK_SESSION_PREFIX = os.environ.get(
    "OPENCLAW_FALLBACK_SESSION_PREFIX",
    "agent:main:signals-openai-fallback",
).strip()

QWEN_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
QWEN_URL = os.environ.get(
    "QWEN_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
).strip()
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-flash").strip() or "qwen3.7-flash"
QWEN_TIMEOUT_SECONDS = int(os.environ.get("QWEN_TIMEOUT_SECONDS", "90") or 90)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
DEEPSEEK_TIMEOUT_SECONDS = int(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "90") or 90)


def prepare_signal_batch(
    *,
    ruleset_title: str,
    topic_name: str,
    candidates: list[SignalCandidate],
) -> PreparedSignalBatch:
    if not candidates:
        return PreparedSignalBatch(events=[], model_meta=ModelMeta(model_id="local", tier="light", local_fallback=True))
    try:
        payload = _run_omniroute_prompt(
            build_prepare_signal_batch_prompt(
                ruleset_title=ruleset_title,
                candidates=candidates,
                topic_name=topic_name,
            )
        )
        return _payload_to_batch(payload=payload, candidates=candidates, topic_name=topic_name)
    except Exception:
        return _local_fallback_batch(candidates=candidates, topic_name=topic_name)


def _run_omniroute_prompt(prompt: str) -> dict[str, Any]:
    payload = _chat_payload(prompt, model=OMNIROUTE_MODEL)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if OMNIROUTE_API_KEY:
        headers["Authorization"] = f"Bearer {OMNIROUTE_API_KEY}"
    req = urllib.request.Request(OMNIROUTE_URL, data=body, headers=headers, method="POST")
    route_errors: list[str] = []

    if OPENCLAW_FALLBACK_ENABLED:
        try:
            return _run_openclaw_prompt(prompt)
        except Exception as exc:
            route_errors.append(f"openclaw: {exc}")

    try:
        with urllib.request.urlopen(req, timeout=OMNIROUTE_TIMEOUT_SECONDS) as resp:
            raw = json.load(resp)
        return _completion_payload_to_signal_payload(
            raw,
            default_model=OMNIROUTE_MODEL,
            provider_fallback=bool(route_errors),
        )
    except Exception as exc:
        route_errors.append(f"omniroute: {exc}")

    if QWEN_API_KEY:
        try:
            return _run_qwen_prompt(prompt)
        except Exception as exc:
            route_errors.append(f"qwen: {exc}")

    if DEEPSEEK_API_KEY:
        try:
            return _run_deepseek_prompt(prompt)
        except Exception as exc:
            route_errors.append(f"deepseek: {exc}")

    raise RuntimeError("signals LLM route chain failed: " + " | ".join(route_errors))


def _chat_payload(prompt: str, *, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": OMNIROUTE_MAX_TOKENS,
        "temperature": OMNIROUTE_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }


def _completion_payload_to_signal_payload(
    raw: dict[str, Any],
    *,
    default_model: str,
    provider_fallback: bool,
) -> dict[str, Any]:
    choice = (((raw.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
    text = choice if isinstance(choice, str) else json.dumps(choice, ensure_ascii=False)
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict) or parsed.get("ok") is False:
        raise ValueError("model returned invalid payload")
    if "model_meta" not in parsed:
        parsed["model_meta"] = {
            "model_id": raw.get("model") or default_model,
            "tier": "light",
            "provider_fallback": provider_fallback,
            "local_fallback": False,
        }
    else:
        meta = parsed.get("model_meta") or {}
        meta["provider_fallback"] = bool(meta.get("provider_fallback") or provider_fallback)
        meta.setdefault("model_id", raw.get("model") or default_model)
        meta.setdefault("tier", "light")
        parsed["model_meta"] = meta
    return parsed


def _run_openclaw_prompt(prompt: str) -> dict[str, Any]:
    if not OPENCLAW_EXEC_CONTAINER:
        raise RuntimeError("OPENCLAW_EXEC_CONTAINER is empty")
    try:
        import docker
        from docker.errors import DockerException, NotFound
    except Exception as exc:
        raise RuntimeError("docker SDK unavailable") from exc

    fallback_prompt = (
        "You are running as the OpenClaw/OpenAI primary route for the Signals bridge. "
        "Return only the JSON object requested by the prompt. Do not add markdown fences.\n\n"
        + prompt
    )
    client = None
    try:
        client = docker.from_env()
        container = client.containers.get(OPENCLAW_EXEC_CONTAINER)
        result = container.exec_run(
            [
                "/usr/local/bin/openclaw",
                "agent",
                "--agent",
                OPENCLAW_AGENT_ID,
                "--model",
                OPENCLAW_FALLBACK_MODEL,
                "--session-key",
                f"{OPENCLAW_FALLBACK_SESSION_PREFIX}:{uuid.uuid4().hex}",
                "--timeout",
                str(OPENCLAW_FALLBACK_TIMEOUT_SECONDS),
                "--message",
                fallback_prompt,
                "--json",
            ],
            environment={"NO_COLOR": "1"},
            stdout=True,
            stderr=True,
            user="1000:1000",
        )
    except NotFound as exc:
        raise RuntimeError(f"OpenClaw container '{OPENCLAW_EXEC_CONTAINER}' not found") from exc
    except DockerException as exc:
        raise RuntimeError(f"OpenClaw docker exec failed: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            if client is not None:
                client.close()

    raw = (result.output or b"").decode("utf-8", errors="replace").strip()
    if int(result.exit_code) != 0:
        raise RuntimeError(f"openclaw agent failed exit={result.exit_code}: {raw[-500:]}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"openclaw agent returned non-json: {raw[-500:]}") from exc
    result_payload = data.get("result") or {}
    meta = result_payload.get("meta") or {}
    agent_meta = meta.get("agentMeta") or {}
    payloads = result_payload.get("payloads") or []
    text = ""
    if payloads and isinstance(payloads[0], dict):
        text = str(payloads[0].get("text") or "")
    text = text or str(meta.get("finalAssistantVisibleText") or meta.get("finalAssistantRawText") or "")
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict) or parsed.get("ok") is False:
        raise ValueError("openclaw returned invalid signals payload")
    parsed["model_meta"] = {
        "model_id": str(agent_meta.get("model") or OPENCLAW_FALLBACK_MODEL.split("/", 1)[-1]),
        "tier": "light",
        "provider_fallback": False,
        "local_fallback": False,
    }
    return parsed


def _run_deepseek_prompt(prompt: str) -> dict[str, Any]:
    payload = _chat_payload(prompt, model=DEEPSEEK_MODEL)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT_SECONDS) as resp:
        raw = json.load(resp)
    return _completion_payload_to_signal_payload(raw, default_model=DEEPSEEK_MODEL, provider_fallback=True)


def _run_qwen_prompt(prompt: str) -> dict[str, Any]:
    payload = _chat_payload(prompt, model=QWEN_MODEL)
    payload["enable_thinking"] = False
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        QWEN_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {QWEN_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=QWEN_TIMEOUT_SECONDS) as resp:
        raw = json.load(resp)
    return _completion_payload_to_signal_payload(raw, default_model=QWEN_MODEL, provider_fallback=True)


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(stripped[idx:])
                return payload
            except json.JSONDecodeError:
                continue
    raise ValueError("no json object found")


def _payload_to_batch(*, payload: dict[str, Any], candidates: list[SignalCandidate], topic_name: str) -> PreparedSignalBatch:
    by_ref = {candidate.external_ref: candidate for candidate in candidates}
    events: list[SignalEvent] = []
    dropped: list[str] = []
    for idx, item in enumerate(payload.get("items", []) or [], start=1):
        external_ref = str(item.get("external_ref", "")).strip()
        candidate = by_ref.get(external_ref)
        if candidate is None:
            continue
        if not item.get("keep", True):
            dropped.append(external_ref)
            continue
        title = str(item.get("title", "")).strip() or candidate.subject or candidate.author
        summary = str(item.get("summary", "")).strip() or candidate.excerpt
        tags = [str(tag) for tag in item.get("tags", []) if str(tag).strip()] or candidate.tags
        events.append(
            SignalEvent(
                event_id=f"{candidate.ruleset_id}:{idx:02d}:{external_ref}",
                ruleset_id=candidate.ruleset_id,
                rule_id=candidate.rule_id,
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                external_ref=candidate.external_ref,
                occurred_at=candidate.occurred_at,
                captured_at=candidate.captured_at,
                author=candidate.author,
                title=title[:120],
                summary=summary[:280],
                source_link=str(candidate.metadata.get("message_link") or ""),
                source_excerpt=candidate.excerpt[:700],
                delivery_text=str(candidate.metadata.get("delivery_text") or candidate.excerpt or "")[:3500],
                source_chat_id=int(candidate.metadata.get("chat_id") or 0) if candidate.source_type == "telegram" else 0,
                source_message_id=int(candidate.metadata.get("message_id") or 0) if candidate.source_type == "telegram" else 0,
                tags=list(dict.fromkeys(tags)),
                confidence=float(item.get("confidence", 0.7) or 0.7),
                telegram_topic=topic_name,
            )
        )
    if not events and candidates:
        return _local_fallback_batch(candidates=candidates, topic_name=topic_name)
    return PreparedSignalBatch(
        events=events,
        model_meta=ModelMeta.from_payload(payload.get("model_meta")),
        dropped_external_refs=dropped,
    )


def _local_fallback_batch(*, candidates: list[SignalCandidate], topic_name: str) -> PreparedSignalBatch:
    events: list[SignalEvent] = []
    dropped: list[str] = []
    for idx, candidate in enumerate(candidates, start=1):
        event = local_event_from_candidate(
            candidate,
            event_id=f"{candidate.ruleset_id}:{idx:02d}:{candidate.external_ref}",
            topic_name=topic_name,
        )
        if event is None:
            dropped.append(candidate.external_ref)
            continue
        events.append(event)
    return PreparedSignalBatch(
        events=events,
        model_meta=ModelMeta(model_id="local", tier="light", local_fallback=True),
        dropped_external_refs=dropped,
    )
