"""Fixed wiki and LightRAG maintenance jobs owned by Hermes cron."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import requests

from .config import confined, credential, digest, require_active
from . import wiki


def mapped_rag_path(config, raw):
    path = PurePosixPath(raw)
    if path.is_absolute():
        matches = sorted(config.get("legacy_path_map", {}).items(), key=lambda x: len(x[0]), reverse=True)
        for old, new in matches:
            try:
                relative = path.relative_to(old)
            except ValueError:
                continue
            return confined(config["rag_source_root"], str(PurePosixPath(new) / relative), must_exist=True)
        raise PermissionError("Legacy path has no reviewed domain mapping")
    return confined(config["rag_source_root"], raw, must_exist=True)


def upload(config, client, path):
    require_active(config, "index")
    root = Path(config["rag_source_root"]).resolve()
    path = confined(root, str(path.relative_to(root)), must_exist=True)
    if path.suffix != ".md" or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("RAG imports accept Markdown files up to 10 MiB")
    relative = path.relative_to(root).as_posix()
    key = "benka:rag-upload:" + hashlib.sha256((config["domain"] + ":" + relative).encode()).hexdigest()
    sha = digest(path)
    if client.get(key) == sha:
        return {"source": relative, "status": "unchanged"}
    token = credential(config, "rag_token", "LIGHTRAG_API_KEY")
    if not token:
        raise PermissionError("LightRAG authentication is required")
    with path.open("rb") as content:
        response = requests.post(config["rag_url"].rstrip("/") + "/documents/upload",
            files={"file": (path.name, content, "text/markdown")}, headers={"X-API-Key": token}, timeout=120)
    if response.status_code == 409:
        # LightRAG already holds this content. For a scan that is success, not a
        # fault: aborting here leaves every later file -- including genuinely new
        # ones -- unindexed. Record the digest so the next pass skips it locally.
        client.set(key, sha)
        return {"source": relative, "status": "duplicate"}
    response.raise_for_status()
    result = response.json()
    if result.get("status") in {"failure", "failed", "error"} or result.get("ok") is False:
        raise RuntimeError("LightRAG rejected the upload")
    if digest(path) != sha:
        raise RuntimeError("RAG source changed during upload; retry after reconciliation")
    client.set(key, sha)
    return {"source": relative, "status": "submitted", "track_id": result.get("track_id")}


def run(config, client, data):
    action = data.get("action")
    if action in {"wiki-daily", "wiki-weekly"}:
        require_active(config, "wiki_write")
        payload = ({"mode": "dry_run", "actions": ["report"]} if action == "wiki-daily" else
                   {"mode": "apply", "actions": ["report", "archive", "refresh_topics", "refresh_overview"]})
        return wiki.call(config, "maintain", payload)
    if action != "rag-scan":
        raise ValueError("Unknown maintenance action")
    require_active(config, "index")
    root = Path(config["rag_source_root"]).resolve()
    roots = config.get("rag_index_roots", [])
    if not roots:
        raise ValueError("Review explicit RAG roots before enabling index scans")
    results = []
    for relative in roots:
        directory = confined(root, relative, must_exist=True)
        for path in sorted(directory.rglob("*.md")):
            if "archive" in path.relative_to(directory).parts:
                continue
            results.append(upload(config, client, path))
    return {"ok": True, "files": results}
