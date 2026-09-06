"""A bounded, isolated Hermes Python API call for background processing."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass


class AgentRunError(RuntimeError):
    def __init__(self, message: str, *, tail: list[str] | None = None):
        super().__init__(message)
        self.tail = tail or []


@dataclass
class AgentRunResult:
    payload: dict
    output_tail: list[str]
    agent_id: str = "hermes-background"


def strip_markdown_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
    return "\n".join(lines)


def extract_json_payload(text: str) -> dict:
    # Reject embedded JSON in prose, trailing garbage and arrays. Callers retain
    # their semantic validators and deterministic fallback for malformed output.
    value = json.loads(strip_markdown_fences(text))
    if not isinstance(value, dict) or value.get("ok") is False:
        raise ValueError("Expected a successful JSON object")
    return value


def run_agent_text(prompt: str, *, timeout_seconds: int = 180) -> str:
    if not 1 <= timeout_seconds <= 900:
        raise ValueError("Model timeout must be between 1 and 900 seconds")
    proc = subprocess.Popen(
        [sys.executable, "-m", "benka_integrations.model_child"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, start_new_session=True,
    )
    try:
        stdout, _ = proc.communicate(json.dumps({"prompt": prompt, "timeout": timeout_seconds}),
                                     timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise AgentRunError("Hermes model request exceeded its deadline") from None
    if proc.returncode:
        # Child logs can include source mail and credentials; never expose them.
        try:
            classes = json.loads(stdout).get("error_types", [])
            classes = [name for name in classes if isinstance(name, str) and name.isidentifier()]
        except (ValueError, AttributeError):
            classes = []
        raise AgentRunError("Hermes model request failed" + (": " + ", ".join(classes) if classes else ""))
    try:
        result = json.loads(stdout)
        text = result["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Empty response")
        return text
    except (ValueError, KeyError, TypeError):
        raise AgentRunError("Hermes returned an invalid response") from None


def run_agent_json(prompt: str, *, timeout_seconds: int | None = None) -> AgentRunResult:
    try:
        text = run_agent_text(prompt, timeout_seconds=timeout_seconds or 180)
        return AgentRunResult(extract_json_payload(text), [])
    except ValueError:
        raise AgentRunError("Hermes returned invalid JSON") from None
