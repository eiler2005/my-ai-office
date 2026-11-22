#!/usr/bin/env python3
"""Exercise the pinned native plugin and cron API in an isolated Hermes home."""
import json
import os
from pathlib import Path
import shutil
import tempfile


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
    print("PASS: 7 native plugin tools; Telegram topic routing; paused idempotent cron; bounded AIAgent API")


if __name__ == "__main__":
    main()
