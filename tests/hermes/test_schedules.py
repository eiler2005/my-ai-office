from pathlib import Path
from types import SimpleNamespace

import pytest

from benka_integrations.schedules import sync


def test_delayed_invocation_keeps_the_original_slot():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from benka_integrations.schedules import slot_for
    tz = ZoneInfo("Europe/Moscow")
    assert slot_for("30 8 * * *", datetime(2026, 9, 6, 8, 30, tzinfo=tz)) == slot_for(
        "30 8 * * *", datetime(2026, 9, 6, 8, 32, 15, tzinfo=tz))


def test_prepare_pauses_jobs_and_does_not_touch_other_owners(tmp_path):
    calls = []
    existing = [{"id": "old", "name": "benka-obsolete"}, {"id": "foreign", "name": "other-job"}]
    api = SimpleNamespace(list_jobs=lambda **kw: existing,
                          create_job=lambda **kw: (calls.append(("create", kw)) or {"id": "new"}),
                          pause_job=lambda ident, **kw: calls.append(("pause", ident)))
    result = sync({"mode": "standby", "_manifest_path": "/run/benka/manifest.json", "jobs": {
        "poll": {"schedule": "*/5 * * * *"}}}, tmp_path, api=api)
    assert result["stale_paused"] == ["benka-obsolete"]
    assert ("pause", "new") in calls and ("pause", "old") in calls and ("pause", "foreign") not in calls
    assert calls[0][1]["no_agent"] is True
    assert calls[0][1]["deliver"] == calls[0][1]["failure_deliver"] == "local"
    compile((tmp_path / "scripts/benka-poll.py").read_text(), "cron-script", "exec")


def test_cron_prepare_cannot_run_on_active_candidate(tmp_path):
    with pytest.raises(PermissionError):
        sync({"mode": "production"}, tmp_path)


def test_rollback_three_way_does_not_overwrite_conflicts(tmp_path):
    from benka_integrations.migration import rollback_delta
    roots = [tmp_path / name for name in ("base", "hermes", "old")]
    for root in roots:
        root.mkdir()
        (root / "same.md").write_text("original")
        (root / "conflict.md").write_text("original")
        (root / "deleted.md").write_text("original")
    (roots[1] / "same.md").write_text("new")
    (roots[1] / "added.md").write_text("new")
    (roots[1] / "conflict.md").write_text("hermes version")
    (roots[2] / "conflict.md").write_text("old version")
    (roots[1] / "deleted.md").unlink()
    result = rollback_delta(*roots)
    assert result["copy_from_hermes"] == ["added.md", "same.md"]
    assert result["conflicts"] == ["conflict.md"]
    assert result["deletions_require_review"] == ["deleted.md"]
    assert (roots[2] / "same.md").read_text() == "original"
