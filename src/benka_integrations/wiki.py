from __future__ import annotations

import os
from pathlib import Path

import requests

from .config import confined, credential, require_active


def call(config, endpoint, payload):
    if endpoint not in {"trigger", "lint", "maintain", "status"}:
        raise ValueError("Unknown wiki endpoint")
    token = credential(config, "wiki_token", "WIKI_IMPORT_TOKEN")
    if not token:
        raise PermissionError("Wiki authentication is required")
    url = config["wiki_url"].rstrip("/") + "/" + endpoint
    headers = {"Authorization": "Bearer " + token}
    response = (requests.get(url, headers=headers, timeout=30) if endpoint == "status"
                else requests.post(url, headers=headers, json=payload, timeout=300))
    response.raise_for_status()
    result = response.json()
    if result.get("ok") is False:
        raise RuntimeError("Wiki operation failed")
    return result


def ingest(config, arguments):
    require_active(config, "wiki_write")
    if str(arguments.get("source", "")).lstrip().lower().startswith("обсуди:"):
        return {"ok": True, "saved": False, "reason": "discussion_only"}
    allowed = {"source_type", "source", "target_kind", "title", "import_goal", "capture_mode", "promote_fingerprint"}
    if set(arguments) - allowed:
        raise ValueError("Unknown wiki input fields")
    payload = dict(arguments)
    if payload.get("source_type") not in config.get("wiki_source_types", ["text"]):
        raise PermissionError("This source type is disabled for this domain")
    if payload.get("source_type") == "server_path":
        path = confined(config["capture_root"], payload["source"], must_exist=True)
        payload["source"] = str(path)
    if payload.get("capture_mode", "knowledgebase") not in {"knowledgebase", "ideas", "promotion"}:
        raise ValueError("Unknown capture mode")
    return call(config, "trigger", payload)


def read(config, path):
    require_active(config, "wiki_read")
    file = confined(config["vault_root"], path, must_exist=True)
    if file.suffix != ".md" or file.stat().st_size > 256 * 1024:
        raise ValueError("Only Markdown pages up to 256 KiB can be read")
    return {"source": path, "text": file.read_text()}


def rag_query(config, query):
    require_active(config, "wiki_read")
    token = credential(config, "rag_token", "LIGHTRAG_API_KEY")
    response = requests.post(config["rag_url"].rstrip("/") + "/query", json={"query": query, "mode": "hybrid"},
                             headers={"X-API-Key": token}, timeout=90)
    response.raise_for_status()
    return response.json()
