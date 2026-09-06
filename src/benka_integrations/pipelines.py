"""Run the existing business algorithms without their HTTP servers or schedulers."""
from __future__ import annotations

import asyncio
import importlib
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from .config import load_manifest, require_active

SERVICES = {"email": "agentmail-email", "telegram": "telethon-digest",
            "signals": "signals-bridge", "last30days": "signals-bridge"}


def execute(config, data):
    service = config["worker"]["pipeline"]
    operation = "poll" if service in SERVICES else "wiki_write" if data.get("action", "").startswith("wiki-") else "index"
    require_active(config, operation)
    logs = Path(config.get("private_log_root", "/state/worker-logs"))
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = logs / (hashlib.sha256(data.get("run_id", "missing").encode()).hexdigest() + ".log")
    with log_path.open("a") as log:
        os.chmod(log_path, 0o600)
        result = subprocess.run([sys.executable, "-m", "benka_integrations.pipelines", service],
                                input=json.dumps(data), text=True, stdout=log,
                                stderr=log, timeout=5400, check=False)
    if result.returncode:
        raise RuntimeError("Pipeline failed; inspect private runtime logs")
    return {"ok": True}


def main():
    service = sys.argv[1]
    config = load_manifest()
    require_active(config, "worker")
    if service != config["worker"]["pipeline"]:
        raise PermissionError("Pipeline is not assigned to this worker")
    root = Path(os.environ.get("BENKA_ARTIFACTS", "/opt/benka/artifacts"))
    data = json.load(sys.stdin)
    if not data.get("run_id"):
        raise ValueError("Missing stable run_id")
    os.environ["BENKA_RUN_ID"] = data["run_id"]
    from .queue import connection
    client = connection(config)
    if service == "maintenance":
        from .maintenance import run
        run(config, client, data)
        return
    if service == "rag":
        from .maintenance import mapped_rag_path, upload
        upload(config, client, mapped_rag_path(config, data["file_path"]))
        return
    sys.path.insert(0, str(root / SERVICES[service]))
    bridge = importlib.import_module("cron_bridge")
    if service == "signals" and data.get("job_type") == "cleanup":
        settings = bridge.load_config()
        bridge.trim_old_events(client, retention_days=bridge._event_retention_days(settings))
        return
    if service == "email":
        action = data.get("job_type", data.get("mode", "poll"))
        if action not in {"poll", "digest"}:
            raise ValueError("Unknown email operation")
        getattr(bridge, "_process_" + action)(client, data=data, config=bridge.load_config())
    elif service in {"signals", "last30days"}:
        result = getattr(bridge, "_process_" + service + "_job")(client, data)
        if result.get("ok") is False:
            raise RuntimeError("Pipeline returned a failure")
    elif service == "telegram":
        os.environ["DIGEST_TYPE_OVERRIDE"] = data.get("digest_type", "interval")
        for key in ("slot_hour", "slot_minute"):
            if key in data:
                os.environ["DIGEST_" + key.upper()] = data[key]
        worker = importlib.import_module("digest_worker")
        asyncio.run(worker.run_digest())


if __name__ == "__main__":
    main()
