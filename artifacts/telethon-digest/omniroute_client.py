"""
Shared OmniRoute helpers.

Supports both normal JSON chat completions and text/event-stream responses.
"""
import contextlib
import json
import os
import uuid
from typing import Any

import aiohttp

from models import LLMCompletion

OPENCLAW_FALLBACK_ENABLED = os.environ.get("HERMES_MODEL_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
OPENCLAW_EXEC_CONTAINER = os.environ.get("OPENCLAW_EXEC_CONTAINER", "openclaw-openclaw-gateway-1").strip()
OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main").strip() or "main"
OPENCLAW_FALLBACK_MODEL = os.environ.get("OPENCLAW_FALLBACK_MODEL", "openai/gpt-5.5").strip()
OPENCLAW_FALLBACK_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_FALLBACK_TIMEOUT_SECONDS", "240") or 240)
OPENCLAW_FALLBACK_SESSION_PREFIX = os.environ.get(
    "OPENCLAW_FALLBACK_SESSION_PREFIX",
    "agent:main:telethon-digest-openai-fallback",
).strip()

QWEN_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
QWEN_URL = os.environ.get(
    "QWEN_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
).strip()
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-flash").strip() or "qwen3.7-flash"
QWEN_TIMEOUT_SECONDS = int(os.environ.get("QWEN_TIMEOUT_SECONDS", "120") or 120)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
DEEPSEEK_TIMEOUT_SECONDS = int(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "120") or 120)


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines).strip()
    return stripped


def has_markdown_fences(text: str) -> bool:
    return "```" in text


def extract_json_payload(text: str) -> Any:
    stripped = strip_markdown_fences(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(stripped):
            if ch not in "[{":
                continue
            try:
                payload, _ = decoder.raw_decode(stripped[idx:])
                return payload
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON payload found in LLM response")


async def read_completion(
    resp: aiohttp.ClientResponse,
    default_model: str,
) -> LLMCompletion:
    """
    Read either OpenAI-compatible JSON or SSE responses from OmniRoute.
    """
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        data = await resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {}) or {}
        return LLMCompletion(
            text=content,
            model_id=data.get("model", default_model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    chunks: list[str] = []
    model_id = default_model
    prompt_tokens = 0
    completion_tokens = 0

    async for raw_line in resp.content:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line.startswith("data:"):
            continue

        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            break

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if "model" in data:
            model_id = data["model"]
        if "usage" in data:
            usage = data["usage"] or {}
            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
            completion_tokens = usage.get("completion_tokens", completion_tokens)

        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content") or message.get("content") or ""
        if content:
            chunks.append(content)

    return LLMCompletion(
        text="".join(chunks).strip(),
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def call_chat_completion(
    session: aiohttp.ClientSession,
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    default_model: str,
) -> LLMCompletion:
    route_errors: list[str] = []

    if OPENCLAW_FALLBACK_ENABLED:
        try:
            return _call_openclaw_fallback(payload, default_model=default_model)
        except Exception as exc:
            route_errors.append(f"hermes: {exc}")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with session.post(
            f"{url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as resp:
            resp.raise_for_status()
            completion = await read_completion(resp, default_model=default_model)
            completion.provider_fallback = bool(route_errors)
            return completion
    except Exception as exc:
        route_errors.append(f"omniroute: {exc}")

    if QWEN_API_KEY:
        try:
            return await _call_qwen_fallback(session, payload, default_model=default_model)
        except Exception as exc:
            route_errors.append(f"qwen: {exc}")

    if DEEPSEEK_API_KEY:
        try:
            return await _call_deepseek_fallback(session, payload, default_model=default_model)
        except Exception as exc:
            route_errors.append(f"deepseek: {exc}")

    raise RuntimeError("LLM route chain failed: " + " | ".join(route_errors))


def _messages_to_agent_prompt(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    lines = [
        "You are running as the Hermes primary route for Telegram Digest.",
        "Return only the requested JSON payload. Do not add markdown fences or commentary.",
    ]
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").upper()
        content = str(message.get("content") or "")
        if content:
            lines.append(f"\n[{role}]\n{content}")
    return "\n".join(lines).strip()


def _call_openclaw_fallback(payload: dict[str, Any], *, default_model: str) -> LLMCompletion:
    from benka_integrations.models import run_agent_text
    text = run_agent_text(_messages_to_agent_prompt(payload), timeout_seconds=180)
    return LLMCompletion(text=text, model_id="hermes-background", prompt_tokens=0, completion_tokens=0)


async def _call_deepseek_fallback(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    *,
    default_model: str,
) -> LLMCompletion:
    deepseek_payload = dict(payload)
    deepseek_payload["model"] = DEEPSEEK_MODEL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    async with session.post(
        DEEPSEEK_URL,
        json=deepseek_payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=DEEPSEEK_TIMEOUT_SECONDS),
    ) as resp:
        resp.raise_for_status()
        completion = await read_completion(resp, default_model=DEEPSEEK_MODEL or default_model)
    completion.provider_fallback = True
    return completion


async def _call_qwen_fallback(
    session: aiohttp.ClientSession,
    payload: dict[str, Any],
    *,
    default_model: str,
) -> LLMCompletion:
    qwen_payload = dict(payload)
    qwen_payload["model"] = QWEN_MODEL
    qwen_payload["enable_thinking"] = False
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }
    async with session.post(
        QWEN_URL,
        json=qwen_payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=QWEN_TIMEOUT_SECONDS),
    ) as resp:
        resp.raise_for_status()
        completion = await read_completion(resp, default_model=QWEN_MODEL or default_model)
    completion.provider_fallback = True
    return completion
