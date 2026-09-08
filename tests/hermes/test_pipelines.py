"""What a queued job is allowed to do, and what its log is allowed to reveal.

`pipelines.execute` is the hinge between the queue and the business algorithms:
it decides which permission the job needs, then runs it in a child process whose
entire output goes to a private log. Two properties matter and neither was
tested. The permission is derived from the job, so a mis-derivation would let a
job run under a permission the operator never granted. And the log is the only
place the child's output lands, so its name and mode are what keep one domain's
runtime output out of reach.
"""
import hashlib
import json
import subprocess

import pytest

from benka_integrations import pipelines

CHILD_OUTPUT_MARKER = "synthetic-child-output-marker"


@pytest.fixture
def config(tmp_path):
    return {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
            "production_connections": False,
            "enabled_operations": ["poll", "index", "wiki_write"],
            "private_log_root": str(tmp_path / "worker-logs"),
            "worker": {"pipeline": "email", "stream": "ingest:jobs:email", "group": "email-workers"}}


@pytest.fixture
def ran(monkeypatch):
    """Record the child invocation instead of spawning one."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(pipelines.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize("pipeline, data, expected", [
    ("email", {}, "poll"),
    ("telegram", {}, "poll"),
    ("signals", {}, "poll"),
    ("last30days", {}, "poll"),
    ("rag", {"action": "wiki-write"}, "wiki_write"),
    ("maintenance", {"action": "wiki-index"}, "wiki_write"),
    ("rag", {}, "index"),
    ("maintenance", {"action": "weekly"}, "index"),
])
def test_the_required_permission_is_derived_from_the_job(config, ran, monkeypatch,
                                                         pipeline, data, expected):
    """A job must not be able to pick a weaker permission than its work needs."""
    asked = []
    monkeypatch.setattr(pipelines, "require_active", lambda cfg, operation: asked.append(operation))
    config["worker"]["pipeline"] = pipeline
    pipelines.execute(config, {"run_id": "r1", **data})
    assert asked == [expected]


def test_an_action_named_like_a_wiki_write_does_not_widen_a_service_pipeline(config, ran, monkeypatch):
    """A publishing pipeline stays on `poll` whatever the payload claims."""
    asked = []
    monkeypatch.setattr(pipelines, "require_active", lambda cfg, operation: asked.append(operation))
    pipelines.execute(config, {"run_id": "r1", "action": "wiki-write"})
    assert asked == ["poll"], "the pipeline name decides, not attacker-controlled payload"


def test_standby_runs_no_pipeline(config, ran):
    config["mode"] = "standby"
    with pytest.raises(PermissionError):
        pipelines.execute(config, {"run_id": "r1"})
    assert not ran, "the child must not be spawned once the gate has refused"


def test_a_disabled_operation_runs_no_pipeline(config, ran):
    config["enabled_operations"] = ["index"]
    with pytest.raises(PermissionError, match="Operation is disabled: poll"):
        pipelines.execute(config, {"run_id": "r1"})
    assert not ran


def test_the_log_directory_is_not_readable_by_others(config, ran, tmp_path):
    pipelines.execute(config, {"run_id": "r1"})
    mode = (tmp_path / "worker-logs").stat().st_mode & 0o777
    assert mode & 0o077 == 0, f"worker logs are private runtime output, got {mode:o}"


def test_the_log_file_is_owner_only(config, ran, tmp_path):
    pipelines.execute(config, {"run_id": "r1"})
    log, = (tmp_path / "worker-logs").iterdir()
    assert log.stat().st_mode & 0o777 == 0o600


def test_the_log_is_named_by_hash_so_a_listing_reveals_no_run_id(config, ran, tmp_path):
    """A directory listing is readable without opening a file; keep it opaque."""
    pipelines.execute(config, {"run_id": "mailbox-denis-personal-2026-09-07"})
    log, = (tmp_path / "worker-logs").iterdir()
    assert log.name == hashlib.sha256(b"mailbox-denis-personal-2026-09-07").hexdigest() + ".log"
    assert "denis" not in log.name and "mailbox" not in log.name


def test_a_missing_run_id_does_not_collide_with_a_real_one(config, ran, tmp_path):
    pipelines.execute(config, {})
    log, = (tmp_path / "worker-logs").iterdir()
    assert log.name == hashlib.sha256(b"missing").hexdigest() + ".log"


def test_the_job_reaches_the_child_on_stdin(config, ran):
    pipelines.execute(config, {"run_id": "r1", "job_type": "digest"})
    call, = ran
    assert call["argv"][-3:] == ["-m", "benka_integrations.pipelines", "email"]
    assert json.loads(call["input"]) == {"run_id": "r1", "job_type": "digest"}


def test_the_child_output_goes_to_the_log_not_a_pipe(config, ran, tmp_path):
    """Both streams must land in the private log, so neither can be captured upstream."""
    pipelines.execute(config, {"run_id": "r1"})
    call, = ran
    log, = (tmp_path / "worker-logs").iterdir()
    assert call["stdout"] is call["stderr"], "one handle, so interleaving is preserved"
    assert call["stdout"].name == str(log)


def test_a_pipeline_run_cannot_hang_forever(config, ran):
    pipelines.execute(config, {"run_id": "r1"})
    assert ran[0]["timeout"] == 5400


def test_a_failing_pipeline_raises_without_quoting_the_child(config, monkeypatch):
    """The child's output may hold mail bodies or credentials; it stays in the log."""
    def failing_run(argv, **kwargs):
        kwargs["stdout"].write(CHILD_OUTPUT_MARKER)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(pipelines.subprocess, "run", failing_run)
    with pytest.raises(RuntimeError) as raised:
        pipelines.execute(config, {"run_id": "r1"})
    assert CHILD_OUTPUT_MARKER not in str(raised.value)
    assert "inspect private runtime logs" in str(raised.value)


def test_a_successful_run_reports_success(config, ran):
    assert pipelines.execute(config, {"run_id": "r1"}) == {"ok": True}
