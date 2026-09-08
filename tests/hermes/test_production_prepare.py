"""Building the production tree from a restored snapshot, and refreshing its schedules.

`production.prepare` is the highest-stakes function in this repository: it is the
one that turns a verified cold restore into the private tree a production runtime
will own. It runs once, by hand, during a cutover, which is exactly the situation
in which a defect is most expensive and least likely to be noticed -- so its
refusals need to hold before anything is written, its output needs to be private
by construction, and it must leave the restore it read from untouched so an
interrupted attempt can simply be deleted.

Only `_delivery_targets` had tests. See `test_delivery_targets.py` for the
incident that produced those.

`finalize()` is deliberately absent: it hardcodes `/opt/benka` image paths, so it
cannot run outside the container and is covered by the VPS verification instead.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from benka_integrations.config import digest
from benka_integrations.production import _copy_tree, _delivery_targets, prepare, refresh_schedules

SHA = "a" * 64
CHAT = "-1003592370241"
OWNER = "111222333"

# Directories the preparation copies wholesale out of the restore.
COPIED = [
    "vault/personal", "redis/data", "omniroute/data", "lightrag/data", "lightrag/inputs",
    "integrations/agentmail/personal/state", "integrations/agentmail/work/state",
    "integrations/telethon/state", "integrations/telethon/sessions",
    "integrations/signals/state", "integrations/signals/sessions", "integrations/signals/rules",
    "integrations/wiki/state", "openclaw/home", "workspace/root",
]
ENVS = {
    "openclaw": "DASHSCOPE_API_KEY=synthetic-qwen-fixture\nOPENCLAW_EXEC_CONTAINER=openclaw-gateway\n",
    "agentmail-personal": f"EMAIL_DIGEST_SUPERGROUP_ID={CHAT}\nEMAIL_DIGEST_TOPIC_ID=119\n",
    "agentmail-work": f"EMAIL_DIGEST_SUPERGROUP_ID={CHAT}\nEMAIL_DIGEST_TOPIC_ID=125\n",
    "telethon": f"DIGEST_SUPERGROUP_ID={CHAT}\nDIGEST_TOPIC_ID=126\n",
    "signals": f"SIGNALS_SUPERGROUP_ID={CHAT}\nSIGNALS_TOPIC_ID=122\n",
    "omniroute": "OMNIROUTE_PORT=20129\n",
    "wiki": "WIKI_IMPORT_TOKEN=token\n",
}
CONFIGS = {
    "openclaw/home/openclaw.json": {
        "channels": {"telegram": {"allowFrom": [int(OWNER)], "groups": {CHAT: {"topic_id": 119}}}}},
    "config/agentmail/personal.json": {
        "inbox_ref": "personal@example.invalid", "schedule_slots": ["09:00"],
        "digest_types": {"09:00": "morning"}},
    "config/agentmail/work.json": {
        "inbox_ref": "work@example.invalid", "schedule_slots": ["18:00"],
        "digest_types": {"18:00": "editorial"}},
    "config/telethon/config.json": {"schedule_slots": ["10:00", "20:00"]},
    "config/signals/config.json": {
        "rule_sets": [{"id": "ai-news", "enabled": True}],
        "last30days": {"enabled": True, "preset_id": "personal-feed-v1",
                       "schedule_expr": "0 7 * * *", "telegram": {"topic_id": 414}}},
}


def fingerprint(root: Path) -> dict[str, str]:
    """Content hash of every file under a tree, for an untouched-source check."""
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture
def snapshot(tmp_path):
    """A synthetic restored cold snapshot with the minimum production material."""
    source = tmp_path / "restore"
    for relative in COPIED:
        (source / relative).mkdir(parents=True)
        (source / relative / "kept.bin").write_bytes(b"state")
    for name, body in ENVS.items():
        path = source / "secrets/env" / f"{name}.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    for relative, payload in CONFIGS.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    (source / "lightrag/.env").write_text("LIGHTRAG_LLM_MODEL=qwen3.7-flash\n")
    return source


@pytest.fixture
def destination(tmp_path):
    return tmp_path / "production"


@pytest.mark.parametrize("value, why", [
    ("a" * 63, "too short"),
    ("a" * 65, "too long"),
    ("A" * 64, "uppercase hex is a different string than the recorded one"),
    ("g" * 64, "not hex at all"),
    ("", "absent"),
])
def test_a_snapshot_identifier_that_is_not_a_sha256_is_refused(snapshot, destination, value, why):
    """The identifier binds this tree to a verified restore; a typo must not pass."""
    with pytest.raises(ValueError, match="SHA-256"):
        prepare(snapshot, destination, snapshot_sha256=value)
    assert not destination.exists(), f"nothing may be created when the id is {why}"


def test_an_existing_destination_is_refused(snapshot, destination):
    """Preparation never merges into a tree that already holds something."""
    destination.mkdir(parents=True)
    (destination / "previous-attempt").write_text("x")
    with pytest.raises(FileExistsError):
        prepare(snapshot, destination, snapshot_sha256=SHA)
    assert (destination / "previous-attempt").read_text() == "x"


@pytest.mark.parametrize("missing", [
    "openclaw/home/openclaw.json", "secrets/env/telethon.env", "config/signals/config.json",
    "vault/personal", "redis/data", "lightrag/data",
])
def test_an_incomplete_snapshot_copies_nothing(snapshot, destination, missing):
    """A half-restored snapshot must fail the manifest check, not be half-copied."""
    target = snapshot / missing
    if target.is_dir():
        os.rename(target, target.parent / "moved-away")
    else:
        target.unlink()
    with pytest.raises(ValueError, match="required production material"):
        prepare(snapshot, destination, snapshot_sha256=SHA)
    assert list(destination.rglob("*")) == [], "the destination must be left empty"


def test_the_restore_is_untouched_so_a_failed_attempt_can_be_deleted(snapshot, destination):
    before = fingerprint(snapshot)
    prepare(snapshot, destination, snapshot_sha256=SHA)
    assert fingerprint(snapshot) == before


def test_every_prepared_file_is_owner_only(snapshot, destination):
    """Walk the whole private tree; one spot check would miss a new writer."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    offenders = {str(path.relative_to(destination)): oct(path.stat().st_mode & 0o777)
                 for path in (destination / "private").rglob("*")
                 if path.is_file() and path.stat().st_mode & 0o177 != 0}
    assert offenders == {}, f"private material readable beyond its owner: {offenders}"


def test_the_private_root_denies_everyone_else(snapshot, destination):
    """The root is the boundary that matters, and `private_directory` verifies it.

    Intermediate directories created by `mkdir(parents=True, mode=...)` keep the
    default mode -- Python applies the mode to the final component only. That is
    harmless here precisely because nothing can traverse the 0700 root to reach
    them, so this asserts the root rather than every directory beneath it.
    """
    prepare(snapshot, destination, snapshot_sha256=SHA)
    for root in (destination, destination / "private"):
        assert root.stat().st_mode & 0o077 == 0, f"{root} is reachable by others"
        assert not root.is_symlink()


def test_the_legacy_exec_container_is_dropped_from_every_bridge(snapshot, destination):
    """That variable told the old bridge to run commands in the OpenClaw container."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    for path in (destination / "private/bridges").iterdir():
        assert "OPENCLAW_EXEC_CONTAINER" not in path.read_text(), path.name


@pytest.mark.parametrize("key, expected", [
    ("REDIS_URL", "redis://redis:6379/0"),
    ("WIKI_IMPORT_URL", "http://wiki:8095"),
    ("LIGHTRAG_URL", "http://lightrag:9621"),
    ("OMNIROUTE_URL", "http://omniroute:20129/v1/chat/completions"),
    ("HERMES_MODEL_ENABLED", "1"),
])
def test_every_bridge_is_repointed_at_the_compose_network(snapshot, destination, key, expected):
    """Host ports from the old deployment must not survive into the new network."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    for path in (destination / "private/bridges").iterdir():
        values = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
        assert values[key] == expected, f"{path.name} kept {key}={values[key]}"


def test_a_snapshot_with_no_model_key_is_refused(snapshot, destination):
    """A worker set that cannot reach a model would fail silently at the first job."""
    (snapshot / "secrets/env/openclaw.env").write_text("OPENCLAW_EXEC_CONTAINER=openclaw-gateway\n")
    with pytest.raises(ValueError, match="No direct model reserve"):
        prepare(snapshot, destination, snapshot_sha256=SHA)


def test_the_model_reserve_is_written_privately(snapshot, destination):
    prepare(snapshot, destination, snapshot_sha256=SHA)
    routes = destination / "private/model-providers.json"
    assert routes.stat().st_mode & 0o777 == 0o600
    assert [route["api_key"] for route in json.loads(routes.read_text())] == ["synthetic-qwen-fixture"]


def test_the_prepared_allowlist_covers_every_publishing_worker(snapshot, destination):
    """Ties this module to the Last30Days regression: the tree must ship a full allowlist."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    targets = _delivery_targets(destination / "private")
    for topic in ("119", "122", "125", "126", "414"):
        assert f"telegram:{CHAT}:{topic}" in targets, f"topic {topic} missing"


def test_the_report_describes_what_was_built(snapshot, destination):
    report = prepare(snapshot, destination, snapshot_sha256=SHA)
    assert report["snapshot_sha256"] == SHA
    assert report["domains"] == ["family", "personal", "sandbox", "work"]
    assert report["schedule_count"] == len(
        json.loads((destination / "private/manifests/schedules.json").read_text())["jobs"])


def test_the_schedule_manifest_starts_disabled(snapshot, destination):
    """A prepared tree owns nothing until an operator writes an activation receipt."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    manifest = json.loads((destination / "private/manifests/schedules.json").read_text())
    assert manifest["mode"] == "standby" and manifest["enabled_operations"] == []


def test_a_symlink_in_the_restore_is_omitted_not_followed(tmp_path):
    """The legacy OpenClaw home holds links into a container that no longer exists."""
    source, target = tmp_path / "source", tmp_path / "outside"
    source.mkdir()
    target.write_text("must not be copied")
    (source / "real.txt").write_text("data")
    (source / "link").symlink_to(target)
    (source / "dangling").symlink_to(tmp_path / "gone")
    _copy_tree(source, tmp_path / "copied")
    assert sorted(p.name for p in (tmp_path / "copied").iterdir()) == ["real.txt"]


def test_a_symlinked_source_directory_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="regular source directory"):
        _copy_tree(tmp_path / "link", tmp_path / "copied")


# --- refresh_schedules -------------------------------------------------------


@pytest.fixture
def active(snapshot, destination):
    """A prepared tree promoted to look like a running production installation."""
    prepare(snapshot, destination, snapshot_sha256=SHA)
    receipts = destination / "private/activation"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "schedules.json").write_text(json.dumps({
        "command": "ACTIVATE_HERMES_BY_DENIS", "manifest_sha256": "0" * 64,
        "snapshot_sha256": SHA, "old_writers_stopped": True}))
    (destination / "runtime/gateway/hermes/benka/activation").mkdir(parents=True)
    return destination


@pytest.mark.parametrize("receipt, why", [
    ({"command": "ACTIVATE", "snapshot_sha256": SHA}, "the wrong command word"),
    ({"command": "ACTIVATE_HERMES_BY_DENIS"}, "no snapshot identifier"),
    ({"command": "ACTIVATE_HERMES_BY_DENIS", "snapshot_sha256": "a" * 63}, "a truncated identifier"),
    ({"command": "ACTIVATE_HERMES_BY_DENIS", "snapshot_sha256": 1}, "a non-string identifier"),
])
def test_refreshing_requires_a_valid_existing_receipt(active, snapshot, receipt, why):
    """The refresh inherits the original activation; it cannot manufacture one."""
    (active / "private/activation/schedules.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="not valid"):
        refresh_schedules(snapshot, active)


def test_refreshing_requires_the_live_cron_runtime(active, snapshot):
    """Without the active runtime the refresh would write a manifest nothing reads."""
    os.rename(active / "runtime/gateway/hermes/benka", active / "runtime/gateway/hermes/moved")
    with pytest.raises(ValueError, match="cron runtime is missing"):
        refresh_schedules(snapshot, active)


def test_a_refresh_binds_the_receipt_to_the_manifest_it_wrote(active, snapshot):
    """`require_active` compares this hash, so a stale receipt must not survive."""
    refresh_schedules(snapshot, active)
    manifest = active / "private/manifests/schedules.json"
    receipt = json.loads((active / "private/activation/schedules.json").read_text())
    assert receipt["manifest_sha256"] == digest(manifest)
    assert receipt["snapshot_sha256"] == SHA, "the original snapshot binding is carried forward"


def test_a_refresh_reaches_the_running_runtime(active, snapshot):
    refresh_schedules(snapshot, active)
    runtime = active / "runtime/gateway/hermes/benka"
    assert (runtime / "schedules.json").read_text() == (
        active / "private/manifests/schedules.json").read_text()
    assert (runtime / "activation/schedules.json").read_text() == (
        active / "private/activation/schedules.json").read_text()
    assert (runtime / "schedules.json").stat().st_mode & 0o777 == 0o600


def test_a_refresh_reports_the_counts_it_wrote(active, snapshot):
    report = refresh_schedules(snapshot, active)
    jobs = json.loads((active / "private/manifests/schedules.json").read_text())["jobs"]
    assert report["schedule_count"] == len(jobs)
    assert report["signals_jobs"] == sum(name.startswith("signals-") and name != "signals-cleanup"
                                         for name in jobs)
    assert report["last30days_jobs"] == sum(name.startswith("last30days-") for name in jobs)
    assert report["last30days_jobs"] == 1, "the reviewed preset must produce a job"
    assert report["signals_jobs"] == 1, "one reviewed ruleset, and cleanup is not one"
    assert "signals-cleanup" in jobs, "the cleanup job is still scheduled, just not counted"


def test_a_refresh_switches_the_manifest_to_production(active, snapshot):
    """The prepared manifest is standby; the refreshed one is what production reads."""
    refresh_schedules(snapshot, active)
    manifest = json.loads((active / "private/manifests/schedules.json").read_text())
    assert manifest["mode"] == "production"
    assert manifest["enabled_operations"] == ["enqueue"], "a scheduler enqueues; it never delivers"


def test_a_newly_reviewed_ruleset_reaches_the_refreshed_manifest(active, snapshot):
    """This is the case the function exists for: a ruleset found after cutover.

    The reported count is what an operator reads to confirm the ruleset arrived,
    so it counts reviewed rulesets only -- `signals-cleanup` is housekeeping and
    is excluded, or two rulesets would report three.
    """
    config = json.loads((snapshot / "config/signals/config.json").read_text())
    config["rule_sets"].append({"id": "late-arrival", "enabled": True})
    (snapshot / "config/signals/config.json").write_text(json.dumps(config))
    report = refresh_schedules(snapshot, active)
    jobs = json.loads((active / "private/manifests/schedules.json").read_text())["jobs"]
    assert "signals-late-arrival" in jobs
    assert report["signals_jobs"] == 2
