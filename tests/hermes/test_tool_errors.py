"""A Benka tool must say what is broken, not only which exception class fired.

Regression for the 2026-09-06 Knowledgebase incident: `wiki_ingest`, `wiki_lint`
and `benka_status` all returned a bare `FileNotFoundError` with no path, so the
missing mount could not be identified from the chat surface.

The balancing constraint is disclosure: these strings reach the model context and
can be echoed into Telegram, so credential *values* must never appear in them.
"""
import json

import pytest

from benka_integrations import plugin
from benka_integrations.config import DeploymentError, credential, load_manifest


class Ctx:
    """Minimal stand-in for the Hermes plugin registration context."""

    def __init__(self, manifest_path):
        self.manifest_path = manifest_path
        self.tools = {}

    def get_config(self, key):
        return self.manifest_path if key == "manifest_path" else None

    def register_tool(self, *, name, handler, **kwargs):
        self.tools[name] = handler

    def register_system_prompt_section(self, *args, **kwargs):
        pass


def manifest(tmp_path, **overrides):
    data = {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
            "production_connections": False,
            "enabled_operations": ["wiki_read", "wiki_write"],
            "wiki_url": "http://wiki.invalid", "wiki_source_types": ["text"]}
    data.update(overrides)
    path = tmp_path / "sandbox.json"
    path.write_text(json.dumps(data))
    return path


# --------------------------------------------------------------- the incident

@pytest.mark.parametrize("tool", ["wiki_ingest", "wiki_lint", "benka_status"])
def test_missing_manifest_names_the_path_and_a_remedy(tmp_path, tool):
    """The exact failure from the incident, across the three tools that showed it."""
    missing = tmp_path / "profiles" / "personal.json"
    ctx = Ctx(str(missing))
    plugin.register(ctx)

    report = json.loads(ctx.tools[tool]({"source_type": "text", "source": "x"}))

    assert report["ok"] is False
    assert report["error"] == "DeploymentError"
    assert str(missing) in report["detail"], "the operator cannot act without the path"
    assert "/run/benka/profiles/" in report["remedy"]


def test_ideas_capture_fails_identically_to_knowledgebase(tmp_path):
    """Ideas shares wiki_ingest, so it shared the fault and shares the fix."""
    ctx = Ctx(str(tmp_path / "absent.json"))
    plugin.register(ctx)
    reports = [
        json.loads(ctx.tools["wiki_ingest"](
            {"source_type": "text", "source": "note", "capture_mode": mode}))
        for mode in ("knowledgebase", "ideas")
    ]
    assert reports[0] == reports[1]
    assert reports[0]["error"] == "DeploymentError"


# ------------------------------------------------------------- other faults

def test_unreadable_manifest_reports_json_position(tmp_path):
    path = tmp_path / "sandbox.json"
    path.write_text("{ not json")
    with pytest.raises(DeploymentError) as caught:
        load_manifest(path)
    assert "not valid JSON" in str(caught.value)
    assert str(path) in str(caught.value)


def test_manifest_directory_is_reported_as_such(tmp_path):
    with pytest.raises(DeploymentError) as caught:
        load_manifest(tmp_path)
    assert "is a directory" in str(caught.value)


def test_missing_credential_file_names_the_setting_not_the_value(tmp_path):
    secret = tmp_path / "profile-secrets" / "wiki_token"
    with pytest.raises(DeploymentError) as caught:
        credential({"wiki_token_file": str(secret)}, "wiki_token", "WIKI_IMPORT_TOKEN")
    assert "wiki_token" in str(caught.value)
    assert str(secret) in str(caught.value)


def test_unset_credential_environment_names_the_variable(monkeypatch):
    monkeypatch.delenv("WIKI_IMPORT_TOKEN", raising=False)
    with pytest.raises(DeploymentError) as caught:
        credential({}, "wiki_token", "WIKI_IMPORT_TOKEN")
    assert "WIKI_IMPORT_TOKEN" in str(caught.value)


# ------------------------------------------------------------- disclosure

def test_credential_values_never_reach_the_report(tmp_path, monkeypatch):
    """A readable secret must not be echoed when a later step fails."""
    secret = tmp_path / "wiki_token"
    secret.write_text("super-secret-token-value")
    path = manifest(tmp_path, wiki_token_file=str(secret))
    ctx = Ctx(str(path))
    plugin.register(ctx)

    raw = ctx.tools["wiki_ingest"]({"source_type": "text", "source": "note"})

    assert "super-secret-token-value" not in raw
    assert json.loads(raw)["ok"] is False


def test_unknown_exceptions_stay_opaque():
    """Third-party messages are not reviewed for disclosure, so only the type is shown."""
    report = plugin._failure(OSError("connection to http://host/path?token=abc123 failed"))
    assert report == {"ok": False, "error": "OSError"}
    assert "abc123" not in json.dumps(report)


def test_authored_permission_messages_are_surfaced():
    report = plugin._failure(PermissionError("Operation is disabled: wiki_write"))
    assert report["detail"] == "Operation is disabled: wiki_write"


def test_missing_manifest_key_is_named():
    report = plugin._failure(KeyError("wiki_url"))
    assert report["error"] == "ConfigurationKeyMissing"
    assert "wiki_url" in report["detail"]
