"""Translate reviewed source schedules into paused-candidate job definitions."""
from croniter import croniter


def build(source):
    if source.get("timezone") != "Europe/Moscow":
        raise ValueError("Confirm Europe/Moscow schedules explicitly")
    jobs, workers = {}, {}

    def add(name, schedule, worker, payload):
        if name in jobs or len(schedule.split()) != 5 or not croniter.is_valid(schedule):
            raise ValueError("Invalid or duplicate schedule")
        jobs[name] = {"schedule": schedule, "stream": workers[worker]["stream"], "payload": payload}

    for name, spec in source.get("email", {}).items():
        if not spec.get("enabled", False):
            continue
        if name not in {"personal", "work"}:
            raise ValueError("Unknown email domain")
        worker = name + "-email"
        workers[worker] = {"pipeline": "email", "stream": spec["stream"], "group": spec["group"], "domain": name}
        common = {"inbox_ref": spec["inbox_ref"]}
        add(worker + "-poll", spec["poll_schedule"], worker, {**common, "job_type": "poll"})
        for slot in spec["slots"]:
            hour, minute = map(int, slot["time"].split(":"))
            kind = slot["digest_type"]
            if not 0 <= hour < 24 or not 0 <= minute < 60 or kind not in {"morning", "interval", "editorial"}:
                raise ValueError("Invalid email slot")
            add(f"{worker}-{hour:02d}{minute:02d}", f"{minute} {hour} * * *", worker,
                {**common, "job_type": "digest", "digest_type": kind})
    telegram = source.get("telegram", {})
    if telegram.get("enabled", False):
        workers["telegram"] = {"pipeline": "telegram", "stream": "ingest:jobs:telegram", "group": "digest-workers", "domain": telegram["domain"]}
        for slot in telegram["slots"]:
            hour, minute = map(int, slot["time"].split(":"))
            if not 0 <= hour < 24 or not 0 <= minute < 60 or slot["digest_type"] not in {"morning", "interval", "editorial"}:
                raise ValueError("Invalid digest slot")
            add(f"telegram-{hour:02d}{minute:02d}", f"{minute} {hour} * * *", "telegram",
                {"digest_type": slot["digest_type"], "slot_hour": hour, "slot_minute": minute})
    for kind, pipeline, identity in (("signals", "signals", "ruleset_id"), ("last30days", "last30days", "preset_id")):
        for spec in source.get(kind, []):
            if not spec.get("enabled", False):
                continue
            name = kind + "-" + spec[identity]
            workers.setdefault(kind, {"pipeline": pipeline, "stream": "ingest:jobs:" + kind,
                                      "group": kind + "-workers", "domain": spec["domain"]})
            if workers[kind]["domain"] != spec["domain"]:
                raise ValueError("Separate registries/Redis instances required for different domains")
            add(name, spec["schedule"], kind, {identity: spec[identity]})
    for spec in source.get("maintenance", []):
        if not spec.get("enabled", False):
            continue
        if spec["action"] not in {"wiki-daily", "wiki-weekly", "rag-scan"}:
            raise ValueError("Unknown maintenance action")
        name = "maintenance-" + spec["domain"]
        workers[name] = {"pipeline": "maintenance", "stream": "benka:maintenance:" + spec["domain"],
                         "group": "benka-maintenance", "domain": spec["domain"]}
        add(spec["domain"] + "-" + spec["action"], spec["schedule"], name, {"action": spec["action"]})
    cleanup = source.get("signals_cleanup", {})
    if cleanup.get("enabled", False):
        if "signals" not in workers:
            raise ValueError("Signals cleanup requires a reviewed signals worker")
        add("signals-cleanup", cleanup["schedule"], "signals", {"job_type": "cleanup"})
    return {"jobs": jobs, "workers": workers, "activation": "disabled", "source_verified": source.get("server_verified", False)}
