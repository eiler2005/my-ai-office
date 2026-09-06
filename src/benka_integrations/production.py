"""Build one private Hermes production tree from a verified cold import.

This module deliberately accepts only an already-restored snapshot.  It neither
contacts the source VPS nor starts a process, so the cutover driver remains the
only place that can stop an old writer or enable a new one.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

import yaml

from .config import DOMAINS, digest
from .migration import private_directory
from .profiles import prepare as prepare_profiles


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return data


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key and key.replace("_", "").isalnum():
            values[key] = value
    return values


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        for key in sorted(values):
            value = str(values[key])
            if "\n" in value or "\r" in value:
                raise ValueError(f"Multiline environment value is not supported: {key}")
            stream.write(f"{key}={value}\n")
    os.chmod(path, 0o600)


def _find_topic_ids(value: Any) -> list[str]:
    """Extract numeric forum topic identifiers from a reviewed config object."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in {"thread_id", "topic_id", "messagethreadid", "message_thread_id"}:
                if isinstance(child, int) and child > 0:
                    found.add(str(child))
                elif isinstance(child, str) and child.isdecimal() and int(child) > 0:
                    found.add(child)
            found.update(_find_topic_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_topic_ids(child))
    return sorted(found, key=int)


def _source_bindings(config: dict[str, Any], bridge_envs: dict[str, dict[str, str]]) -> dict[str, Any]:
    telegram = ((config.get("channels") or {}).get("telegram") or {})
    users = {str(value) for key in ("allowFrom", "groupAllowFrom") for value in telegram.get(key, [])
             if str(value).isdigit() and int(value) > 0}
    if not users:
        raise ValueError("OpenClaw Telegram allowlist has no numeric trusted user")
    groups = telegram.get("groups") or {}
    if not isinstance(groups, dict):
        raise ValueError("OpenClaw Telegram group map is invalid")
    routes: list[dict[str, str]] = []
    chats: set[str] = set()
    for chat, specification in groups.items():
        chat_id = str(chat)
        if not (chat_id.startswith("-") and chat_id[1:].isdigit()):
            continue
        chats.add(chat_id)
        topic_ids = _find_topic_ids(specification)
        routes.extend({"chat_id": chat_id, "thread_id": topic} for topic in topic_ids)
        if not topic_ids:
            routes.append({"chat_id": chat_id})

    # Delivery-only workers can target forum topics that were not defined as
    # interactive routes.  Keep their exact targets in the root allowlist but
    # do not invent a domain route for them.
    for values in bridge_envs.values():
        for name, value in values.items():
            if name.endswith("_SUPERGROUP_ID") and str(value).startswith("-"):
                chats.add(str(value))
    personal_routes = routes[:]
    work_routes: list[dict[str, str]] = []
    for values in bridge_envs.values():
        chat = values.get("EMAIL_DIGEST_SUPERGROUP_ID")
        topic = values.get("EMAIL_DIGEST_TOPIC_ID")
        if chat and topic and str(chat).startswith("-") and str(topic).isdigit():
            work_routes.append({"chat_id": str(chat), "thread_id": str(topic)})
    # Most specific work routes must be present before a broad personal route.
    personal_routes = [route for route in personal_routes if route not in work_routes]
    return {
        "domains": {
            "personal": {"users": sorted(users), "admins": [], "routes": personal_routes},
            "work": {"users": sorted(users), "admins": [], "routes": work_routes},
            "family": {"users": sorted(users), "admins": [], "routes": []},
            "sandbox": {"users": sorted(users), "admins": [], "routes": []},
        },
        "chats": sorted(chats),
    }


def _owner_home_channel(bindings: dict[str, Any]) -> dict[str, str] | None:
    """Return the owner DM as Telegram's default notification destination.

    A Telegram private chat uses the owner's numeric user ID as its chat ID.
    Choose it only when the personal domain has exactly one trusted person: a
    group or family route must never become the default delivery destination.
    """
    users = {str(user) for user in bindings["domains"]["personal"]["users"]}
    if len(users) != 1:
        return None
    owner = users.pop()
    return {
        "platform": "telegram",
        "chat_id": owner,
        "name": "Benka owner DM",
        "user_id": owner,
    }


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"Expected regular source directory: {source}")
    # The legacy OpenClaw home may contain links into its former container or
    # host.  They cannot be restored safely in Hermes and are not source data,
    # so omit them instead of following a dangling target.
    def ignore_symlinks(directory: str, names: list[str]) -> list[str]:
        return [name for name in names if (Path(directory) / name).is_symlink()]

    shutil.copytree(source, destination, copy_function=shutil.copyfile, ignore=ignore_symlinks)


def _private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(content)
    os.chmod(path, 0o600)


def _worker_manifest(*, domain: str, pipeline: str, stream: str, group: str,
                     delivery_targets: list[str], receipt: str) -> dict[str, Any]:
    return {
        "schema": 1, "mode": "production", "domain": domain,
        "production_connections": True, "activation_receipt": receipt,
        "enabled_operations": ["worker", "poll", "send"],
        "worker": {"pipeline": pipeline, "stream": stream, "group": group},
        "redis_file": "/run/benka/redis-url", "media_root": "/state/uploads",
        "private_log_root": "/state/worker-logs", "delivery_targets": delivery_targets,
    }


def _signals_config(source: Path) -> dict[str, Any]:
    """Load Signals config together with its reviewed external rule fragments."""
    config = _read_json(source / "config/signals/config.json")
    rules_root = (source / "integrations/signals").resolve(strict=True)
    merged = list(config.get("rule_sets") or [])
    for raw_pattern in config.get("rule_files") or []:
        pattern = Path(str(raw_pattern))
        if pattern.is_absolute() or ".." in pattern.parts:
            raise ValueError("Signals rule file pattern escapes its reviewed root")
        for path in sorted(rules_root.glob(str(pattern))):
            if not path.is_file() or not path.is_relative_to(rules_root):
                continue
            payload = json.loads(path.read_text())
            if isinstance(payload, dict) and "rule_sets" in payload:
                merged.extend(payload.get("rule_sets") or [])
            elif isinstance(payload, list):
                merged.extend(payload)
            elif isinstance(payload, dict):
                merged.append(payload)
            else:
                raise ValueError(f"Invalid Signals rule fragment: {path.name}")
    config["rule_sets"] = merged
    return config


def _schedule_manifest(source: Path, receipt: str) -> dict[str, Any]:
    personal = _read_json(source / "config/agentmail/personal.json")
    work = _read_json(source / "config/agentmail/work.json")
    telegram = _read_json(source / "config/telethon/config.json")
    signals = _signals_config(source)

    def email(name: str, config: dict[str, Any], stream: str, group: str) -> dict[str, Any]:
        slots = []
        types = config.get("digest_types") or {}
        raw_slots = config.get("schedule_slots") or [f"{hour}:00" for hour in config.get("schedule_hours", [])]
        for raw in raw_slots:
            value = str(raw)
            kind = types.get(value, types.get(value.split(":", 1)[0], "interval"))
            if kind in {"morning", "interval", "editorial"}:
                slots.append({"time": value if ":" in value else value.zfill(2) + ":00", "digest_type": kind})
        return {"enabled": True, "stream": stream, "group": group,
                "inbox_ref": str(config.get("inbox_ref") or ""), "poll_schedule": "*/5 * * * *", "slots": slots}

    review = {
        "timezone": "Europe/Moscow", "server_verified": True,
        "email": {
            "personal": email("personal", personal, "ingest:jobs:email:personal", "personal-email-workers"),
            "work": email("work", work, "ingest:jobs:email:work", "work-email-workers"),
        },
        "telegram": {"enabled": True, "domain": "personal", "slots": [
            {"time": str(slot), "digest_type": (telegram.get("digest_types") or {}).get(str(slot).split(":", 1)[0], "interval")}
            for slot in telegram.get("schedule_slots", [])
            if (telegram.get("digest_types") or {}).get(str(slot).split(":", 1)[0], "interval") in {"morning", "interval", "editorial"}
        ]},
        "signals": [], "last30days": [],
        "maintenance": [
            {"enabled": True, "domain": "personal", "action": "wiki-daily", "schedule": "15 3 * * *"},
            {"enabled": True, "domain": "personal", "action": "wiki-weekly", "schedule": "30 3 * * 0"},
            {"enabled": True, "domain": "personal", "action": "rag-scan", "schedule": "0,30 * * * *"},
        ],
        # Cleanup has no independent worker: do not enqueue it when this
        # installation has no reviewed Signals ruleset to consume the job.
        "signals_cleanup": {"enabled": False, "schedule": "0 * * * *"},
    }
    for rule in signals.get("rule_sets") or []:
        identity = str(rule.get("id") or "")
        if identity:
            review["signals"].append({"enabled": bool(rule.get("enabled", True)), "domain": "personal",
                                      "ruleset_id": identity, "schedule": "*/5 * * * *"})
    review["signals_cleanup"]["enabled"] = bool(review["signals"])
    last30 = signals.get("last30days") or {}
    if last30.get("enabled") and last30.get("preset_id"):
        review["last30days"].append({"enabled": True, "domain": "personal",
                                      "preset_id": str(last30["preset_id"]),
                                      "schedule": str(last30.get("schedule_expr") or "0 7 * * *")})
    from .job_registry import build
    registry = build(review)
    return {"schema": 1, "mode": "standby", "domain": "personal", "data_class": "production",
            "production_connections": True, "activation_receipt": receipt,
            "enabled_operations": [], "jobs": registry["jobs"], "cron_connection_file": "/run/benka/cron.json",
            "redis_file": "/run/benka/redis-url"}


def refresh_schedules(source: Path, destination: Path) -> dict[str, int]:
    """Refresh only the active schedule manifest from a verified source snapshot.

    This leaves credentials, worker manifests, Redis and the imported Hermes
    profile untouched.  It is for an omitted ruleset discovered after cutover.
    """
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=True)
    private = destination / "private"
    manifest_root = private / "manifests"
    receipt_root = private / "activation"
    previous_receipt = _read_json(receipt_root / "schedules.json")
    snapshot_sha256 = previous_receipt.get("snapshot_sha256")
    if (previous_receipt.get("command") != "ACTIVATE_HERMES_BY_DENIS"
            or not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64):
        raise ValueError("Existing production schedule receipt is not valid")

    schedules = _schedule_manifest(source, "/state/hermes/benka/activation/schedules.json")
    schedules.update({
        "mode": "production",
        "enabled_operations": ["enqueue"],
        "cron_connection_file": "/state/hermes/benka/cron.json",
        "redis_file": "/state/hermes/benka/redis-url",
    })
    manifest_path = manifest_root / "schedules.json"
    _private_file(manifest_path, json.dumps(schedules, indent=2))
    _private_file(receipt_root / "schedules.json", json.dumps({
        "command": "ACTIVATE_HERMES_BY_DENIS",
        "manifest_sha256": digest(manifest_path),
        "snapshot_sha256": snapshot_sha256,
        "old_writers_stopped": True,
    }, indent=2))

    cron_runtime = destination / "runtime/gateway/hermes/benka"
    cron_receipt_root = cron_runtime / "activation"
    if not cron_runtime.is_dir() or not cron_receipt_root.is_dir():
        raise ValueError("Active Hermes cron runtime is missing")
    _private_file(cron_runtime / "schedules.json", manifest_path.read_text())
    _private_file(cron_receipt_root / "schedules.json", (receipt_root / "schedules.json").read_text())
    return {"schedule_count": len(schedules["jobs"]),
            "signals_jobs": sum(name.startswith("signals-") for name in schedules["jobs"]),
            "last30days_jobs": sum(name.startswith("last30days-") for name in schedules["jobs"])}


def prepare(source: Path, destination: Path, *, snapshot_sha256: str) -> dict[str, Any]:
    source = source.resolve(strict=True)
    if not len(snapshot_sha256) == 64 or any(char not in "0123456789abcdef" for char in snapshot_sha256):
        raise ValueError("Expected lowercase SHA-256 snapshot identifier")
    if destination.exists():
        raise FileExistsError("Production destination must be new")
    private_directory(destination)
    required = [
        "openclaw/home/openclaw.json", "secrets/env/openclaw.env", "secrets/env/agentmail-personal.env",
        "secrets/env/agentmail-work.env", "secrets/env/telethon.env", "secrets/env/signals.env",
        "secrets/env/omniroute.env", "secrets/env/wiki.env",
        "config/agentmail/personal.json", "config/agentmail/work.json", "config/telethon/config.json",
        "config/signals/config.json", "vault/personal", "redis/data", "omniroute/data", "lightrag/data",
    ]
    missing = [name for name in required if not (source / name).exists()]
    if missing:
        raise ValueError("Restored snapshot lacks required production material")

    envs = {
        "openclaw": _read_env(source / "secrets/env/openclaw.env"),
        "agentmail-personal": _read_env(source / "secrets/env/agentmail-personal.env"),
        "agentmail-work": _read_env(source / "secrets/env/agentmail-work.env"),
        "telethon": _read_env(source / "secrets/env/telethon.env"),
        "signals": _read_env(source / "secrets/env/signals.env"),
        "omniroute": _read_env(source / "secrets/env/omniroute.env"),
        "wiki": _read_env(source / "secrets/env/wiki.env"),
    }
    openclaw_config = _read_json(source / "openclaw/home/openclaw.json")
    bindings = _source_bindings(openclaw_config, envs)

    # Persistent state is copied from the verified restore.  The source restore
    # remains untouched, so an interrupted preparation can be removed safely.
    data = destination / "data"
    _copy_tree(source / "vault/personal", data / "vault/personal")
    for domain in ("work", "family", "sandbox"):
        private_directory(data / "vault" / domain)
    _copy_tree(source / "redis/data", data / "redis")
    _copy_tree(source / "omniroute/data", data / "omniroute")
    _copy_tree(source / "lightrag/data", data / "lightrag/data")
    _copy_tree(source / "integrations/agentmail/personal/state", data / "agentmail/personal/state")
    _copy_tree(source / "integrations/agentmail/work/state", data / "agentmail/work/state")
    _copy_tree(source / "integrations/telethon/state", data / "telethon/state")
    _copy_tree(source / "integrations/telethon/sessions", data / "telethon/sessions")
    _copy_tree(source / "integrations/signals/state", data / "signals/state")
    _copy_tree(source / "integrations/signals/sessions", data / "signals/sessions")
    _copy_tree(source / "integrations/wiki/state", data / "wiki/state")
    _copy_tree(source / "integrations/signals/rules", data / "signals/rules")
    _copy_tree(source / "lightrag/inputs", data / "lightrag/inputs")
    # Send-capable workers use a private bind-mounted /state.  The immutable
    # image cannot create these paths after that mount hides its image layer.
    for worker in ("email-personal", "email-work", "telegram", "signals", "last30days", "maintenance"):
        private_directory(data / "worker" / worker / "uploads")
        private_directory(data / "worker" / worker / "worker-logs")

    private = destination / "private"
    private_directory(private)
    for name, values in envs.items():
        values = dict(values)
        values["REDIS_URL"] = "redis://redis:6379/0"
        values["HERMES_MODEL_ENABLED"] = "1"
        values["WIKI_IMPORT_URL"] = "http://wiki:8095"
        values["WIKI_IMPORT_LIGHTRAG_URL"] = "http://lightrag:9621"
        values["LIGHTRAG_URL"] = "http://lightrag:9621"
        values["OMNIROUTE_URL"] = "http://omniroute:20129/v1/chat/completions"
        values.pop("OPENCLAW_EXEC_CONTAINER", None)
        _write_env(private / "bridges" / f"{name}.env", values)
    _private_file(private / "config" / "agentmail/personal.json", (source / "config/agentmail/personal.json").read_text())
    _private_file(private / "config" / "agentmail/work.json", (source / "config/agentmail/work.json").read_text())
    _private_file(private / "config" / "telethon/config.json", (source / "config/telethon/config.json").read_text())
    _private_file(private / "config" / "signals/config.json", (source / "config/signals/config.json").read_text())
    # The legacy deployment bind-mounted ``config.ini`` before the image
    # created it, leaving an empty directory at that path.  LightRAG accepts
    # its remaining configuration through the environment, so preserve a
    # regular file in the new layout only when one was actually present.
    legacy_lightrag_config = source / "lightrag/config.ini"
    _private_file(
        private / "config" / "lightrag/config.ini",
        legacy_lightrag_config.read_text() if legacy_lightrag_config.is_file() else "",
    )
    _private_file(private / "config" / "lightrag/.env", (source / "lightrag/.env").read_text())
    _private_file(private / "redis-url", "redis://redis:6379/0\n")
    _private_file(private / "cron.json", json.dumps({"redis_url": "redis://redis:6379/0"}))
    _private_file(private / "bindings.json", json.dumps(bindings, indent=2))
    model_routes = []
    for key_name, endpoint_name, default_url, default_model in (
        ("DASHSCOPE_API_KEY", "QWEN_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen3.7-flash"),
        ("DEEPSEEK_API_KEY", "DEEPSEEK_URL", "https://api.deepseek.com/chat/completions", "deepseek-v4-flash"),
    ):
        api_key = envs["openclaw"].get(key_name) or envs["telethon"].get(key_name) or envs["signals"].get(key_name)
        if api_key:
            endpoint = envs["telethon"].get(endpoint_name, default_url).removesuffix("/chat/completions")
            model_routes.append({"provider": "custom", "model": envs["telethon"].get(endpoint_name.removesuffix("_URL") + "_MODEL", default_model),
                                 "api_mode": "chat_completions", "base_url": endpoint, "api_key": api_key})
    if not model_routes:
        raise ValueError("No direct model reserve is available for Hermes workers")
    _private_file(private / "model-providers.json", json.dumps(model_routes, indent=2))

    # Copy source workspace/config into a private import staging area.  The
    # native importer runs separately and is allowed to create its own backup.
    import_root = destination / "import"
    _copy_tree(source / "openclaw/home", import_root / "openclaw")
    _copy_tree(source / "workspace/root", import_root / "workspace")

    receipt_root = private / "activation"
    private_directory(receipt_root)
    schedules = _schedule_manifest(source, "/run/benka/activation/schedules.json")
    manifest_root = private / "manifests"
    private_directory(manifest_root)
    _private_file(manifest_root / "schedules.json", json.dumps(schedules, indent=2))
    return {"snapshot_sha256": snapshot_sha256, "domains": sorted(DOMAINS),
            "interactive_routes": sum(len(domain["routes"]) for domain in bindings["domains"].values()),
            "schedule_count": len(schedules["jobs"])}


def finalize(destination: Path, *, snapshot_sha256: str) -> dict[str, Any]:
    """Apply profiles and create hash-bound receipts after native claw import."""
    destination = destination.resolve(strict=True)
    private, runtime = destination / "private", destination / "runtime/gateway/hermes"
    if not runtime.is_dir() or not (runtime / "config.yaml").is_file():
        raise ValueError("Run native Hermes claw import before production finalization")
    bindings = _read_json(private / "bindings.json")
    staging = destination / "profile-staging"
    prepare_profiles(bindings, staging, repo=Path("/opt/benka"), runtime_home="/state/hermes")
    profiles_root = runtime / "profiles"
    profiles_root.mkdir(parents=True, exist_ok=True)
    for domain in DOMAINS:
        existing = profiles_root / domain
        if existing.exists():
            shutil.rmtree(existing)
        shutil.move(str(staging / "profiles" / domain), str(profiles_root / domain))
    profile_manifests = private / "benka-manifests"
    if profile_manifests.exists():
        shutil.rmtree(profile_manifests)
    shutil.move(str(staging / "benka-manifests"), str(profile_manifests))
    for manifest in profile_manifests.glob("*.json"):
        os.chmod(manifest, 0o600)
    shutil.rmtree(staging)

    root = yaml.safe_load((runtime / "config.yaml").read_text()) or {}
    baseline = yaml.safe_load((Path("/opt/benka/deploy/hermes/hermes.example.yaml")).read_text())
    for key in ("timezone", "toolsets", "platform_toolsets", "agent", "database", "memory", "onboarding"):
        root[key] = copy.deepcopy(baseline[key])
    root["agent"].update({
        "reasoning_effort": "medium",
        "reasoning_overrides": {
            "gpt-5.6-luna": "minimal",
            "gpt-5.6-terra": "medium",
            "gpt-5.6-sol": "high",
        },
    })
    all_users = sorted({str(user) for domain in bindings["domains"].values() for user in domain["users"]})
    chats = bindings["chats"]
    routes = []
    for domain in ("work", "family", "sandbox", "personal"):
        for route in bindings["domains"][domain]["routes"]:
            routes.append({"name": f"benka-{domain}-{len(routes)}", "platform": "telegram", "profile": domain,
                           **{key: str(value) for key, value in route.items()}})
    routes.append({"name": "benka-personal-default", "platform": "telegram", "profile": "personal"})
    root["gateway"] = {"multiplex_profiles": True, "multiplex_profile_allowlist": sorted(DOMAINS),
                       "profile_routes": routes}
    root["telegram"] = {
        "enabled": True, "dm_policy": "allowlist", "allow_from": all_users,
        "group_policy": "allowlist", "group_allow_from": all_users,
        "allowed_chats": chats, "group_allowed_chats": chats,
        "observe_unmentioned_group_messages": False,
        "user_allowed_commands": ["help", "new", "status"],
        "group_user_allowed_commands": ["help", "new", "status"],
    }
    if home_channel := _owner_home_channel(bindings):
        root["telegram"]["home_channel"] = home_channel
    # This is an established assistant with an imported profile. Hermes's
    # first-touch profile-building prompt is useful for a fresh installation,
    # but not for Benka: it interrupts the first real Telegram request and
    # can offer account discovery that this deployment does not expose.
    root["onboarding"] = {"profile_build": "off"}
    root["plugins"] = {"enabled": ["benka"], "entries": {"benka": {"settings": {"manifest_path": "/run/benka/manifest.json"}}}}
    model_routes = json.loads((private / "model-providers.json").read_text())
    if not isinstance(model_routes, list) or not model_routes:
        raise ValueError("No reviewed Hermes model route is available")
    provider_configs: dict[str, dict[str, str]] = {}
    fallback_chain: list[dict[str, str]] = []
    for index, route in enumerate(model_routes):
        if not isinstance(route, dict):
            raise ValueError("Invalid reviewed Hermes model route")
        # The user-facing agent keeps the established ChatGPT Codex route as
        # its primary model.  Direct API providers are deliberately reserves:
        # Qwen is the first reserve and DeepSeek follows it when available.
        reserve_number = index + 1
        label = f"benka-fallback-{reserve_number}"
        api_key_env = f"BENKA_FALLBACK_{reserve_number}_API_KEY"
        if not all(isinstance(route.get(key), str) and route[key] for key in ("model", "base_url", "api_key")):
            raise ValueError("Reviewed Hermes model route is incomplete")
        provider_configs[label] = {
            "api": route["base_url"], "key_env": api_key_env,
            "transport": route.get("api_mode", "chat_completions"),
            "default_model": route["model"],
        }
        fallback_chain.append({"provider": f"custom:{label}", "model": route["model"]})
    root["providers"] = provider_configs
    root["model"] = {"provider": "openai-codex", "default": "gpt-5.6-terra"}
    root["fallback_providers"] = fallback_chain
    root["auxiliary"] = {
        "title_generation": {"provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "minimal"},
        "compression": {"provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "low"},
        "background_review": {"provider": "openai-codex", "model": "gpt-5.6-luna", "reasoning_effort": "low"},
    }
    root["delegation"] = {
        "provider": "openai-codex", "model": "gpt-5.6-sol",
        "max_concurrent_children": 1, "max_spawn_depth": 1,
        "orchestrator_enabled": False,
    }
    (runtime / "config.yaml").write_text(yaml.safe_dump(root, allow_unicode=True, sort_keys=False))
    os.chmod(runtime / "config.yaml", 0o600)

    root_env = _read_env(runtime / ".env") if (runtime / ".env").exists() else {}
    if not root_env.get("TELEGRAM_BOT_TOKEN"):
        token = (( _read_json(destination / "import/openclaw/openclaw.json").get("channels") or {}).get("telegram") or {}).get("botToken")
        if not isinstance(token, str) or not token:
            raise ValueError("Native import did not provide Telegram credentials")
        root_env["TELEGRAM_BOT_TOKEN"] = token
    # This legacy OpenClaw path is not mounted in the Hermes runtime and is
    # rejected by current Hermes as a deprecated terminal setting.
    root_env.pop("MESSAGING_CWD", None)
    for key in tuple(root_env):
        if key == "BENKA_PRIMARY_API_KEY" or key.startswith("BENKA_FALLBACK_"):
            root_env.pop(key)
    for index, route in enumerate(model_routes, start=1):
        key = f"BENKA_FALLBACK_{index}_API_KEY"
        root_env[key] = route["api_key"]
    _write_env(runtime / ".env", root_env) if not (runtime / ".env").exists() else (runtime / ".env").write_text("".join(f"{k}={v}\n" for k, v in sorted(root_env.items())))
    os.chmod(runtime / ".env", 0o600)
    soul_path = runtime / "SOUL.md"
    soul = soul_path.read_text() if soul_path.exists() else ""
    identity = (
        "Ты Бенька — цвергшнауцер, пёс-помощник Дениса и его деловой со-пилот. "
        "Пиши по существу, с живым сухим юмором, но без сюсюканья и без выдумок."
    )
    if "цвергшнауцер" not in soul.casefold():
        soul = f"{identity}\n\n{soul.lstrip()}"
        soul_path.write_text(soul)
        os.chmod(soul_path, 0o600)
    model_policy = (
        "\n\nМодельная политика: обычные ответы выполняй сам. Для сложной многошаговой "
        "задачи с исследованием, проектированием или проверкой используй ровно одного "
        "изолированного delegate_task, затем проверь и синтезируй его результат. Не делегируй "
        "простые вопросы, статусы и короткие правки.\n"
    )
    model_keys = {key: copy.deepcopy(root[key]) for key in ("model", "providers", "custom_providers", "fallback_providers") if key in root}
    for domain in DOMAINS:
        profile = profiles_root / domain
        profile_config = yaml.safe_load((profile / "config.yaml").read_text()) or {}
        profile_config.update(copy.deepcopy(model_keys))
        # The root gateway owns the one Bot API polling connection.  Routed
        # profiles must keep their platform disabled, otherwise Hermes starts
        # duplicate pollers with the same bot credential.
        profile_config["telegram"] = {"enabled": False}
        (profile / "config.yaml").write_text(yaml.safe_dump(profile_config, allow_unicode=True, sort_keys=False))
        if (profile / ".env").exists():
            (profile / ".env").unlink()
        profile_env = dict(root_env)
        profile_env.pop("TELEGRAM_BOT_TOKEN", None)
        _write_env(profile / ".env", profile_env)
        (profile / "SOUL.md").write_text(f"Ты Бенька. Активный контур: {domain}. Не используй данные других контуров.\n\n{soul}{model_policy}")
        os.chmod(profile / "SOUL.md", 0o600)
        if domain == "personal" and (runtime / "memories").is_dir():
            _copy_tree(runtime / "memories", profile / "memories")

    manifest_root = private / "manifests"
    wiki_values = _read_env(private / "bridges/wiki.env")
    wiki_token = wiki_values.get("WIKI_IMPORT_TOKEN")
    if not wiki_token:
        raise ValueError("Wiki authentication is required for Hermes maintenance")
    profile_secrets = private / "profile-secrets"
    private_directory(profile_secrets)
    profile_manifests = private / "benka-manifests"
    for domain in DOMAINS:
        manifest_path = profile_manifests / f"{domain}.json"
        manifest = _read_json(manifest_path)
        if manifest.get("domain") != domain:
            raise ValueError(f"Profile manifest domain mismatch: {domain}")
        manifest.update({
            "mode": "production",
            "data_class": "production",
            "production_connections": True,
            "activation_receipt": f"/run/benka/activation/profile-{domain}.json",
            "enabled_operations": ["wiki_read", "archive_read"],
        })
        if domain == "personal":
            secret_dir = profile_secrets / domain
            private_directory(secret_dir)
            _private_file(secret_dir / "redis-url", (private / "redis-url").read_text())
            _private_file(secret_dir / "wiki-token", wiki_token + "\n")
            _private_file(secret_dir / "rag-token", wiki_token + "\n")
            manifest.update({
                "enabled_operations": ["wiki", "wiki_read", "wiki_write", "archive_read", "enqueue"],
                "wiki_url": "http://wiki:8095",
                "rag_url": "http://lightrag:9621",
            })
        else:
            for key in ("redis_file", "wiki_token_file", "rag_token_file"):
                manifest.pop(key, None)
        _private_file(manifest_path, json.dumps(manifest, indent=2))
    maintenance_env = private / "bridges/maintenance.env"
    if maintenance_env.exists():
        maintenance_env.unlink()
    _write_env(maintenance_env, {"WIKI_IMPORT_TOKEN": wiki_token, "LIGHTRAG_API_KEY": wiki_token})
    rag_root = destination / "data/vault/personal"
    rag_index_roots = [name for name in ("wiki", "Telegram Digest", "Last30Days", "PlatformPulse", "Recordings")
                       if (rag_root / name).is_dir()]
    if not rag_index_roots:
        raise ValueError("No reviewed LightRAG source roots are available")
    delivery = []
    for name in ("agentmail-personal", "agentmail-work", "telethon", "signals"):
        values = _read_env(private / "bridges" / f"{name}.env")
        for prefix in ("EMAIL_DIGEST", "DIGEST", "SIGNALS"):
            chat, topic = values.get(prefix + "_SUPERGROUP_ID"), values.get(prefix + "_TOPIC_ID")
            if chat:
                delivery.append(f"telegram:{chat}" + (f":{topic}" if topic else ""))
    delivery = sorted(set(delivery))
    maintenance = _worker_manifest(domain="personal", pipeline="maintenance", stream="benka:maintenance:personal", group="benka-maintenance", delivery_targets=delivery, receipt="/run/benka/activation/maintenance.json")
    maintenance.update({
        "enabled_operations": ["worker", "wiki_write", "index"],
        "wiki_url": "http://wiki:8095", "rag_url": "http://lightrag:9621",
        "rag_source_root": "/vault", "rag_index_roots": rag_index_roots,
    })
    manifests = {
        "gateway": {"schema": 1, "mode": "production", "domain": "personal", "production_connections": True,
                    "activation_receipt": "/run/benka/activation/gateway.json", "enabled_operations": ["gateway"]},
        "dashboard": {"schema": 1, "mode": "production", "domain": "personal", "production_connections": True,
                      "activation_receipt": "/run/benka/activation/dashboard.json", "enabled_operations": ["dashboard"]},
        "wiki": {"schema": 1, "mode": "production", "domain": "personal", "production_connections": True,
                 "activation_receipt": "/run/benka/activation/wiki.json", "enabled_operations": ["wiki", "wiki_read", "wiki_write"]},
        "email-personal": _worker_manifest(domain="personal", pipeline="email", stream="ingest:jobs:email:personal", group="personal-email-workers", delivery_targets=delivery, receipt="/run/benka/activation/email-personal.json"),
        "email-work": _worker_manifest(domain="work", pipeline="email", stream="ingest:jobs:email:work", group="work-email-workers", delivery_targets=delivery, receipt="/run/benka/activation/email-work.json"),
        "telegram": _worker_manifest(domain="personal", pipeline="telegram", stream="ingest:jobs:telegram", group="digest-workers", delivery_targets=delivery, receipt="/run/benka/activation/telegram.json"),
        "signals": _worker_manifest(domain="personal", pipeline="signals", stream="ingest:jobs:signals", group="signals-workers", delivery_targets=delivery, receipt="/run/benka/activation/signals.json"),
        "last30days": _worker_manifest(domain="personal", pipeline="last30days", stream="ingest:jobs:last30days", group="last30days-workers", delivery_targets=delivery, receipt="/run/benka/activation/last30days.json"),
        "maintenance": maintenance,
    }
    schedules = _read_json(manifest_root / "schedules.json")
    schedules.update({"mode": "production", "activation_receipt": "/run/benka/activation/schedules.json",
                      "enabled_operations": ["enqueue"]})
    # Hermes cron runs scripts in its own scheduler context, where the
    # Compose-only /run mounts are not present.  Keep the schedule control
    # plane under HERMES_HOME so scripts have the same checked material.
    schedules["activation_receipt"] = "/state/hermes/benka/activation/schedules.json"
    schedules["cron_connection_file"] = "/state/hermes/benka/cron.json"
    schedules["redis_file"] = "/state/hermes/benka/redis-url"
    manifests["schedules"] = schedules
    receipts = private / "activation"
    for domain in DOMAINS:
        path = profile_manifests / f"{domain}.json"
        receipt = {"command": "ACTIVATE_HERMES_BY_DENIS", "manifest_sha256": digest(path),
                   "snapshot_sha256": snapshot_sha256, "old_writers_stopped": True}
        _private_file(receipts / f"profile-{domain}.json", json.dumps(receipt, indent=2))
    for name, manifest in manifests.items():
        path = manifest_root / f"{name}.json"
        _private_file(path, json.dumps(manifest, indent=2))
        receipt = {"command": "ACTIVATE_HERMES_BY_DENIS", "manifest_sha256": digest(path),
                   "snapshot_sha256": snapshot_sha256, "old_writers_stopped": True}
        _private_file(receipts / f"{name}.json", json.dumps(receipt, indent=2))
    cron_runtime = runtime / "benka"
    cron_runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    (cron_runtime / "schedules.json").write_text((manifest_root / "schedules.json").read_text())
    # Scheduler scripts executed by the Gateway use the private Compose
    # network, so they share the same Redis service address as the workers.
    cron_redis_url = "redis://redis:6379/0"
    (cron_runtime / "cron.json").write_text(json.dumps({"redis_url": cron_redis_url}))
    (cron_runtime / "redis-url").write_text(cron_redis_url + "\n")
    cron_receipts = cron_runtime / "activation"
    cron_receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    (cron_receipts / "schedules.json").write_text((receipts / "schedules.json").read_text())
    for path in (cron_runtime / "schedules.json", cron_runtime / "cron.json", cron_runtime / "redis-url",
                 cron_receipts / "schedules.json"):
        os.chmod(path, 0o600)
    return {"manifest_count": len(manifests) + len(DOMAINS), "delivery_target_count": len(delivery),
            "route_count": len(routes), "snapshot_sha256": snapshot_sha256}
