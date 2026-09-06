import json
from pathlib import Path
from unittest.mock import Mock, patch

import fakeredis
import pytest

from benka_integrations import archive, job_registry, maintenance


def config(tmp_path):
    return {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
            "production_connections": False, "enabled_operations": ["index", "wiki_write"],
            "rag_source_root": str(tmp_path), "rag_index_roots": ["wiki"], "rag_url": "http://rag.invalid",
            "rag_token_env": "BENKA_TEST_RAG_TOKEN", "legacy_path_map": {"/app/obsidian": "."}}


def test_legacy_rag_mapping_rejects_escape_and_foreign_path(tmp_path):
    (tmp_path / "wiki").mkdir()
    path = tmp_path / "wiki/page.md"
    path.write_text("page")
    cfg = config(tmp_path)
    assert maintenance.mapped_rag_path(cfg, "/app/obsidian/wiki/page.md") == path
    for raw in ("/etc/passwd", "/app/obsidian/../../etc/passwd"):
        with pytest.raises((ValueError, PermissionError)):
            maintenance.mapped_rag_path(cfg, raw)


def test_rag_scan_only_approved_roots_and_content_changes(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "page.md").write_text("version one")
    (tmp_path / "private-email.md").write_text("must never be indexed")
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setenv("BENKA_TEST_RAG_TOKEN", "synthetic-local-fixture")
    reply = Mock()
    reply.json.return_value = {"status": "success", "track_id": "fixture"}
    with patch("benka_integrations.maintenance.requests.post", return_value=reply) as post:
        first = maintenance.run(cfg, client, {"action": "rag-scan"})
        assert first["files"] == [{"source": "wiki/page.md", "status": "submitted", "track_id": "fixture"}]
        assert maintenance.run(cfg, client, {"action": "rag-scan"})["files"][0]["status"] == "unchanged"
        assert post.call_count == 1
        (wiki / "page.md").write_text("version two")
        maintenance.run(cfg, client, {"action": "rag-scan"})
        assert post.call_count == 2


def test_weekly_maintenance_preserves_existing_actions(tmp_path):
    with patch("benka_integrations.maintenance.wiki.call", return_value={"ok": True}) as call:
        maintenance.run(config(tmp_path), None, {"action": "wiki-weekly"})
        assert call.call_args.args[2] == {"mode": "apply", "actions": ["report", "archive", "refresh_topics", "refresh_overview"]}


def test_diary_archive_and_persistent_skip_report(tmp_path):
    source = tmp_path / "archive"
    source.mkdir()
    (source / "day.md").write_text("# Diary\nустойчивое наблюдение\n")
    (source / "chat.jsonl").write_text("invalid json\n")
    db = tmp_path / "private/search.sqlite"
    first = archive.index(source, db)
    second = archive.index(source, db)
    assert first["skipped"] == second["skipped"]
    assert second["imported_messages"] == 0
    result = archive.search(db, "наблюдение")
    assert result[0]["source"] == "day.md" and result[0]["line"] == 2


def test_registry_does_not_activate_disabled_sources():
    source = {"timezone": "Europe/Moscow", "email": {"personal": {"enabled": False}},
              "last30days": [{"enabled": True, "domain": "personal", "preset_id": "world-radar-v1", "schedule": "0 7 * * *"}]}
    result = job_registry.build(source)
    assert list(result["jobs"]) == ["last30days-world-radar-v1"]
    assert result["activation"] == "disabled" and result["source_verified"] is False


def test_registry_preserves_work_slots_and_modes():
    result = job_registry.build({"timezone": "Europe/Moscow", "email": {"work": {
        "enabled": True, "stream": "ingest:jobs:work-email", "group": "work-email-workers",
        "inbox_ref": "work", "poll_schedule": "*/5 * * * *", "slots": [
            {"time": "08:30", "digest_type": "morning"}, {"time": "19:00", "digest_type": "editorial"}]}}})
    assert result["jobs"]["work-email-0830"]["schedule"] == "30 8 * * *"
    assert result["jobs"]["work-email-1900"]["payload"]["digest_type"] == "editorial"
