"""Prepare paused native Hermes cron jobs; no migration date activates them."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .config import load_manifest, require_active


def sync(config, home: Path, *, api=None, activate=False):
    if config["mode"] == "standby":
        if activate:
            raise PermissionError("A standby candidate cannot activate schedules")
    elif config["mode"] == "production" and activate:
        require_active(config, "enqueue")
    else:
        raise PermissionError("Prepare schedules in standby or sync an active production manifest")
    if api is None:
        from cron import jobs as api
        from hermes_cli.config import load_config_readonly
        if load_config_readonly().get("timezone") != "Europe/Moscow":
            raise ValueError("Hermes timezone must be Europe/Moscow before preparing schedules")
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    existing = api.list_jobs(include_disabled=True)
    by_name = {}
    for job in existing:
        if job.get("name", "").startswith("benka-"):
            if job["name"] in by_name:
                raise ValueError("Duplicate Benka cron name; reconcile before syncing")
            by_name[job["name"]] = job
    prepared = []
    desired = set()
    for name, spec in config.get("jobs", {}).items():
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("Invalid job name")
        if not spec.get("schedule"):
            continue
        key = "benka-" + name
        desired.add(key)
        script = scripts / (key + ".py")
        # Native cron intentionally strips arbitrary env vars. Load only the
        # private worker connection file inside this script, never provider keys.
        script.write_text("from benka_integrations.schedules import tick\n"
                          + "tick(" + repr(name) + ", " + repr(config["_manifest_path"]) + ")\n")
        values = {"schedule": spec["schedule"], "no_agent": True, "script": script.name,
                  "deliver": "local", "failure_deliver": "local", "prompt": ""}
        if key in by_name:
            job = api.update_job(by_name[key]["id"], values)
        else:
            job = api.create_job(name=key, **values)
        if activate:
            api.resume_job(job["id"])
        else:
            api.pause_job(job["id"], reason="Prepared candidate; separate owner activation required")
        prepared.append({"name": key, "id": job["id"], "enabled": bool(activate)})
    stale = []
    for name, job in by_name.items():
        if name not in desired:
            api.pause_job(job["id"], reason="Removed from reviewed Benka schedule manifest")
            stale.append(name)
    return {"prepared": prepared, "stale_paused": stale, "timezone": "Europe/Moscow"}


def tick(job: str, manifest: str):
    from .config import require_active
    from .queue import connection, enqueue
    config = load_manifest(manifest)
    require_active(config, "enqueue")
    credentials = json.loads(Path(config["cron_connection_file"]).read_text())
    os.environ[config.get("redis_env", "REDIS_URL")] = credentials["redis_url"]
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    # Fixed cron slots are identified by their local minute; the queue retains
    # the slot claim across worker restarts and duplicate scheduler invocations.
    slot = slot_for(config["jobs"][job]["schedule"], now)
    enqueue(connection(config), config, job, slot)
    # Empty stdout and local delivery prevent cron from posting a second copy.


def slot_for(schedule: str, now: datetime) -> str:
    from croniter import croniter
    if len(schedule.split()) != 5:
        raise ValueError("Benka schedules use explicit five-field cron expressions")
    local = now.astimezone(ZoneInfo("Europe/Moscow"))
    return croniter(schedule, local + timedelta(microseconds=1)).get_prev(datetime).isoformat()
