"""Render domain routing for a single Telegram polling owner, all platforms disabled."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil

import yaml

from .config import DOMAINS
from .migration import private_directory


def validate_bindings(bindings):
    if set(bindings.get("domains", {})) != DOMAINS:
        raise ValueError("Bindings must explicitly cover personal, work, family and sandbox")
    seen = set()
    for domain, spec in bindings["domains"].items():
        if not spec.get("users"):
            raise ValueError(f"Explicit trusted numeric user IDs required for {domain}")
        for user in spec["users"]:
            if not re.fullmatch(r"[1-9][0-9]*", str(user)):
                raise ValueError("Usernames and wildcard users are not trusted identity IDs")
        if set(map(str, spec.get("admins", []))) - set(map(str, spec["users"])):
            raise ValueError("Administrators must belong to the trusted user list")
        for route in spec.get("routes", []):
            if set(route) - {"chat_id", "thread_id"}:
                raise ValueError("Unknown routing fields")
            if not re.fullmatch(r"-?[1-9][0-9]*", str(route.get("chat_id", ""))):
                raise ValueError("Numeric chat ID required")
            if "thread_id" in route and not re.fullmatch(r"[1-9][0-9]*", str(route["thread_id"])):
                raise ValueError("Numeric topic ID required")
            identity = (str(route["chat_id"]), str(route.get("thread_id", "")))
            if identity in seen:
                raise ValueError("Ambiguous duplicate route")
            seen.add(identity)


def prepare(bindings, destination: Path, *, repo: Path, runtime_home="/state/hermes"):
    validate_bindings(bindings)
    if destination.exists():
        raise FileExistsError("Render profiles into a new private staging directory")
    private_directory(destination)
    base = yaml.safe_load((repo / "deploy/hermes/hermes.example.yaml").read_text())
    routes, users, chats = [], set(), set()
    for domain, spec in bindings["domains"].items():
        for route in spec.get("routes", []):
            routes.append({"name": f"benka-{domain}-{len(routes)}", "platform": "telegram",
                           "profile": domain, **{key: str(value) for key, value in route.items()}})
            chats.add(str(route["chat_id"]))
        users.update(str(user) for user in spec["users"])
        path = destination / "profiles" / domain
        private_directory(path)
        (path / ".env").write_text("# Separate profile credentials; no shared bot token here.\n")
        os.chmod(path / ".env", 0o600)
        config = copy.deepcopy(base)
        config["telegram"] = {"enabled": False, "dm_policy": "allowlist", "allow_from": [str(x) for x in spec["users"]],
                              "group_policy": "allowlist", "group_allow_from": [str(x) for x in spec["users"]],
                              "allow_admin_from": [str(x) for x in spec.get("admins", [])],
                              "group_allow_admin_from": [str(x) for x in spec.get("admins", [])],
                              "user_allowed_commands": ["help", "new", "status"],
                              "group_user_allowed_commands": ["help", "new", "status"]}
        config["plugins"]["entries"]["benka"]["settings"]["manifest_path"] = (
            f"{runtime_home}/profiles/{domain}/benka-manifest.json"
        )
        (path / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True))
        shutil.copytree(repo / "plugins/benka", path / "plugins/benka")
        for skill in ("benka-knowledge", "benka-scenarios"):
            shutil.copytree(repo / "skills" / skill, path / "skills" / skill)
        (path / "SOUL.md").write_text(f"Ты Бенька. Текущий контур: {domain}. Используй только его знания и инструменты.\n")
        manifest = {"schema": 1, "mode": "standby", "domain": domain, "data_class": "test",
                    "production_connections": False, "enabled_operations": [], "jobs": {}, "delivery_targets": [],
                    "vault_root": f"/vault/{domain}", "archive_database": f"{runtime_home}/profiles/{domain}/archive.sqlite",
                    "redis_file": f"/run/benka/profile-secrets/{domain}/redis-url",
                    "wiki_token_file": f"/run/benka/profile-secrets/{domain}/wiki-token",
                    "rag_token_file": f"/run/benka/profile-secrets/{domain}/rag-token"}
        (path / "benka-manifest.json").write_text(json.dumps(manifest, indent=2))
    default = copy.deepcopy(base)
    default["toolsets"] = []
    default["platform_toolsets"] = {"telegram": [], "cli": []}
    default["plugins"] = {"enabled": []}
    default["gateway"] = {"multiplex_profiles": True, "multiplex_profile_allowlist": sorted(DOMAINS), "profile_routes": routes}
    default["telegram"] = {"enabled": False, "dm_policy": "allowlist", "allow_from": sorted(users),
                           "group_policy": "allowlist", "group_allow_from": sorted(users),
                           "allowed_chats": sorted(chats), "observe_unmentioned_group_messages": False,
                           "allow_admin_from": [], "group_allow_admin_from": [],
                           "user_allowed_commands": ["help"], "group_user_allowed_commands": ["help"]}
    (destination / "config.yaml").write_text(yaml.safe_dump(default, allow_unicode=True))
    for path in destination.rglob("*"):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    return {"profiles": sorted(DOMAINS), "route_count": len(routes), "polling_enabled": False}
