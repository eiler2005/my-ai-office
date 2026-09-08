"""The two ways a container starts, and what each one refuses to do.

`service.main` is the image ENTRYPOINT and `cli.main` backs the `benka` console
script -- including `benka status`, which is the compose healthcheck. Both sit in
front of every side effect the runtime can have, so their refusals are the outer
boundary of the activation interlock: a manifest that has not been activated must
not reach a gateway, a worker, or the wiki, and no elapsed time can change that.

Neither had a test. They were only ever exercised as black boxes on the VPS.
"""
import json
import os
from pathlib import Path

import pytest

from benka_integrations import cli, service

ACTIVE_OPERATIONS = ["gateway", "dashboard", "worker", "wiki"]
# The runner gives each suite a temporary cwd, so repository files need a root.
ROOT = Path(__file__).resolve().parents[2]


def write_manifest(tmp_path, monkeypatch, **overrides):
    manifest = {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
                "production_connections": False, "enabled_operations": list(ACTIVE_OPERATIONS)}
    manifest.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("BENKA_MANIFEST", str(path))
    return path


@pytest.fixture
def execs(monkeypatch):
    """Capture the exec instead of replacing the test process."""
    captured = []
    monkeypatch.setattr(os, "execvp", lambda file, args: captured.append((file, args)))
    return captured


def run_service(monkeypatch, action):
    monkeypatch.setattr("sys.argv", ["service", action])
    service.main()


def test_a_standby_container_refuses_a_non_standby_manifest(tmp_path, monkeypatch, execs):
    """The standby image must never be the thing that starts owning production."""
    write_manifest(tmp_path, monkeypatch, mode="rehearsal")
    with pytest.raises(PermissionError, match="standby manifest"):
        run_service(monkeypatch, "standby")
    assert not execs, "nothing may be executed once the mode check has failed"


def test_an_unknown_service_is_refused_before_anything_runs(tmp_path, monkeypatch, execs):
    write_manifest(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Unknown service"):
        run_service(monkeypatch, "bogus")
    assert not execs


@pytest.mark.parametrize("action", ACTIVE_OPERATIONS)
def test_an_inactive_manifest_starts_no_service(tmp_path, monkeypatch, execs, action):
    """Standby owns nothing, so every service action must be refused."""
    write_manifest(tmp_path, monkeypatch, mode="standby")
    monkeypatch.setenv("WIKI_IMPORT_TOKEN", "present-so-the-gate-under-test-is-activation")
    with pytest.raises(PermissionError):
        run_service(monkeypatch, action)
    assert not execs


@pytest.mark.parametrize("action", ACTIVE_OPERATIONS)
def test_a_disabled_operation_starts_no_service(tmp_path, monkeypatch, execs, action):
    """`enabled_operations` is per-service, not a single on switch."""
    write_manifest(tmp_path, monkeypatch,
                   enabled_operations=[op for op in ACTIVE_OPERATIONS if op != action])
    monkeypatch.setenv("WIKI_IMPORT_TOKEN", "present")
    with pytest.raises(PermissionError, match="Operation is disabled"):
        run_service(monkeypatch, action)
    assert not execs


def test_the_wiki_refuses_to_run_unauthenticated(tmp_path, monkeypatch, execs):
    write_manifest(tmp_path, monkeypatch)
    monkeypatch.delenv("WIKI_IMPORT_TOKEN", raising=False)
    with pytest.raises(PermissionError, match="without authentication"):
        run_service(monkeypatch, "wiki")
    assert not execs


def test_activation_is_checked_before_the_wiki_token(tmp_path, monkeypatch, execs):
    """Order matters: an unactivated instance must not report a missing token.

    A token-shaped error would invite an operator to supply a token, when the
    real refusal is that this instance does not own production at all.
    """
    write_manifest(tmp_path, monkeypatch, mode="standby")
    monkeypatch.delenv("WIKI_IMPORT_TOKEN", raising=False)
    with pytest.raises(PermissionError, match="standby") as raised:
        run_service(monkeypatch, "wiki")
    assert "authentication" not in str(raised.value)


def test_the_worker_is_execed_by_absolute_path(tmp_path, monkeypatch, execs):
    """Pins the reason for the hardcoded venv path in `service.commands`.

    Legacy bridge env files may define their own PATH. A bare `benka` lookup
    would let one of them shadow the Hermes integration worker with something
    else entirely, so the packaged console entry point is named outright.
    """
    write_manifest(tmp_path, monkeypatch)
    run_service(monkeypatch, "worker")
    (executable, argv), = execs
    assert executable == "/opt/benka/.venv/bin/benka"
    assert os.path.isabs(executable), "a relative name could be shadowed by a bridge env PATH"
    assert argv == [executable, "worker"]


@pytest.mark.parametrize("action, expected", [
    ("gateway", ["hermes", "gateway", "run"]),
    ("dashboard", ["hermes", "dashboard", "--no-open", "--skip-build", "--host", "0.0.0.0", "--port", "9119"]),
])
def test_an_activated_service_execs_its_command(tmp_path, monkeypatch, execs, action, expected):
    write_manifest(tmp_path, monkeypatch)
    run_service(monkeypatch, action)
    (executable, argv), = execs
    assert executable == expected[0]
    assert argv == expected


def test_the_dashboard_never_opens_a_browser_or_rebuilds(tmp_path, monkeypatch, execs):
    """A container has no browser, and a build at start would need a writable tree."""
    write_manifest(tmp_path, monkeypatch)
    run_service(monkeypatch, "dashboard")
    (_, argv), = execs
    assert "--no-open" in argv and "--skip-build" in argv


def test_benka_status_answers_the_healthcheck(monkeypatch, capsys):
    """`benka status` is the compose healthcheck; it must work from the manifest alone."""
    monkeypatch.setenv("BENKA_MANIFEST", str(ROOT / "deploy/hermes/manifest.standby.example.json"))
    monkeypatch.setattr("sys.argv", ["benka", "status"])
    cli.main()
    reported = json.loads(capsys.readouterr().out)
    assert reported == {"mode": "standby", "domain": "sandbox", "automatic_cutover": False}


def test_status_never_reports_an_automatic_cutover(tmp_path, monkeypatch, capsys):
    """No mode may report that a cutover could happen on its own."""
    for mode in ("standby", "rehearsal"):
        write_manifest(tmp_path, monkeypatch, mode=mode)
        monkeypatch.setattr("sys.argv", ["benka", "status"])
        cli.main()
        assert json.loads(capsys.readouterr().out)["automatic_cutover"] is False


def test_benka_without_a_subcommand_fails_loudly(monkeypatch):
    """A mistyped healthcheck must fail, not fall through to a default action."""
    monkeypatch.setattr("sys.argv", ["benka"])
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 2
