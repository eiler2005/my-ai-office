#!/usr/bin/env python3
"""Exercise the pinned native plugin and cron API in an isolated Hermes home."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def probe_send(target):
    from argparse import Namespace
    from unittest.mock import patch

    from gateway.outbound import send as outbound
    from hermes_cli.send_cmd import cmd_send

    async def confirm(platform, config, chat_id, text, *args, **kwargs):
        assert platform.value == "telegram" and str(chat_id) == "-100123"
        assert kwargs["thread_id"] == "12" and text == "Synthetic worker digest"
        return {"success": True, "message_id": "123"}

    # Run the native CLI including egress checks, but terminate the send before network I/O.
    with patch.object(outbound, "_send_to_platform", confirm):
        cmd_send(Namespace(to=target, file="-", json=True))


def verify_worker_send(home):
    from unittest.mock import patch

    from fakeredis import FakeRedis
    from pm.environments import install_key
    from pm.paths import repo_root
    from benka_integrations.delivery import send

    gateway = home / "gateway-read-only"
    install = gateway / "installs" / install_key(repo_root())
    install.mkdir(parents=True)
    (gateway / "config.yaml").write_text("telegram:\n  enabled: true\n")
    (gateway / ".env").write_text("TELEGRAM_BOT_TOKEN=12345:synthetic-outbound-token\n")
    install.chmod(0o500)
    target = "telegram:-100123:12"
    text = "Synthetic worker digest"
    probe = [sys.executable, str(Path(__file__).resolve()), "--probe-send", target]
    manifest = {"mode": "rehearsal", "data_class": "test", "production_connections": False,
                "enabled_operations": ["send"], "delivery_targets": [target]}

    def run_command(command, **kwargs):
        assert command[1:] == ["send", "--to", target, "--file", "-", "--json"]
        return subprocess.run(probe, **kwargs)

    try:
        with patch.dict(os.environ, {"HERMES_HOME": str(gateway)}):
            if os.getuid() != 0:
                rejected = subprocess.run(probe, input=text, text=True, capture_output=True, timeout=15)
                assert rejected.returncode != 0, "Native send fixture must exercise the read-only lock failure"
            receipt = send(FakeRedis(), manifest, delivery_id="fixture-digest", target=target, text=text,
                           runner=run_command)
            assert receipt["message_id"] == "123"
    finally:
        install.chmod(0o700)


def probe_shared_web_auth():
    from agent.transports.codex import _alias_wire_tools
    from plugins.web.openai_native.provider import has_codex_credentials
    from model_tools import _select_tool_names
    from benka_integrations.production import enable_personal_web_search

    assert has_codex_credentials(), "Personal profile cannot discover the shared Codex login"
    client_tool = {"type": "function", "name": "web_search"}
    assert _alias_wire_tools([client_tool], {}, False, True)[0] == [{"type": "web_search"}]
    assert _alias_wire_tools([client_tool], {}, False, False)[0] == [client_tool]
    config = {"platform_toolsets": {"telegram": ["web"]}}
    enable_personal_web_search(config)
    assert _select_tool_names(config["platform_toolsets"]["telegram"], [], quiet_mode=True) == {"web_search"}


def verify_shared_web_auth(home):
    profile = home / "profiles" / "personal"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("web:\n  search_backend: openai-native\n  keyless_fallback: false\n")
    (home / "auth.json").write_text(json.dumps({"credential_pool": {"openai-codex": [{"access_token": "fixture"}]}}))
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe-shared-web-auth"],
                   env=dict(os.environ, HERMES_HOME=str(profile)), check=True, timeout=20)


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="benka-native-contract-") as temporary:
        home = Path(temporary).resolve()
        scope = str(home)
        os.environ["HERMES_HOME"] = scope
        os.environ["HERMES_DISABLE_UPDATE_CHECK"] = "1"
        os.environ.pop("HERMES_PROFILE", None)
        os.chdir(home)
        (home / "plugins").mkdir()
        shutil.copytree(root / "plugins/benka", home / "plugins/benka")
        config_text = (root / "deploy/hermes/hermes.example.yaml").read_text()
        config_text = config_text.replace("/run/benka/manifest.json", str(home / "manifest.json"))
        (home / "config.yaml").write_text(config_text)
        (home / "manifest.json").write_text((root / "deploy/hermes/manifest.standby.example.json").read_text())
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        manager = PluginManager(scope_key=scope)
        manager.discover_and_load()
        names = {"wiki_ingest", "wiki_read", "wiki_lint", "lightrag_query", "benka_archive_search", "benka_status", "benka_run"}
        for name in names:
            entry = registry.get_entry(name, scope=scope)
            assert entry is not None, f"Missing native plugin tool: {name}"
        status = json.loads(registry.get_entry("benka_status", scope=scope).handler({}))
        assert status["mode"] == "standby", status
        from hermes_cli.version_info import get_version_info
        version = get_version_info().display_version
        assert version.startswith("0.23.3") and status["hermes_version"] == version, status
        from hermes_cli.tools_config import _get_platform_tools
        import yaml
        resolved = _get_platform_tools(yaml.safe_load(config_text), "telegram", include_default_mcp_servers=False)
        assert resolved == {"benka"}, f"Unexpected enabled toolsets: {sorted(resolved)}"
        from gateway.profile_routing import match_profile_route, parse_profile_routes
        routes = parse_profile_routes([
            {"platform": "telegram", "profile": "personal", "chat_id": "-100"},
            {"platform": "telegram", "profile": "work", "chat_id": "-100", "thread_id": "12"},
        ])
        assert match_profile_route(routes, "telegram", chat_id="-100", thread_id="12").profile == "work"
        assert match_profile_route(routes, "telegram", chat_id="-100", thread_id="13").profile == "personal"
        assert match_profile_route(routes, "telegram", chat_id="-200", thread_id="12") is None
        from benka_integrations.schedules import sync
        manifest = {"mode": "standby", "_manifest_path": str(home / "manifest.json"),
                    "jobs": {"test-poll": {"schedule": "*/5 * * * *"}}}
        first = sync(manifest, home)
        second = sync(manifest, home)
        assert first["prepared"][0]["id"] == second["prepared"][0]["id"]
        from cron.jobs import list_jobs
        jobs = list_jobs(include_disabled=True)
        assert len(jobs) == 1 and jobs[0]["enabled"] is False and jobs[0]["no_agent"] is True
        from run_agent import AIAgent
        import inspect
        for name in ("skip_memory", "skip_context_files", "skip_background_review", "enabled_toolsets", "run_budget_seconds"):
            assert name in inspect.signature(AIAgent).parameters
        manager.unload()
        verify_worker_send(home)
        if get_version_info().distribution == "docker":
            verify_shared_web_auth(home)
    print("PASS: 7 native plugin tools; Telegram topic routing and read-only worker delivery; paused cron; bounded AIAgent")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe-send":
        probe_send(sys.argv[2])
    elif sys.argv[1:] == ["--probe-shared-web-auth"]:
        probe_shared_web_auth()
    else:
        main()
