import io
import asyncio
import json
from pathlib import Path
import subprocess
import tarfile

import fakeredis
import pytest

from benka_integrations import archive, migration, wiki
from benka_integrations.config import confined, digest, require_active
from benka_integrations.delivery import UncertainDelivery, send
from benka_integrations.models import AgentRunError, extract_json_payload, run_agent_text
from benka_integrations.queue import consume_one, enqueue


@pytest.mark.parametrize("prefix", ["MEDIA:", "media:", "MeDiA:"])
def test_external_text_never_becomes_native_attachment(client, cfg, monkeypatch, tmp_path, prefix):
    from benka_integrations import legacy_delivery
    from gateway.platforms.base import BasePlatformAdapter
    captured = []
    monkeypatch.setattr(legacy_delivery, "load_manifest", lambda: cfg)
    monkeypatch.setattr(legacy_delivery, "connection", lambda config: client)
    monkeypatch.setattr(legacy_delivery, "send", lambda *args, **kwargs: captured.append(kwargs["text"]))
    monkeypatch.setenv("BENKA_RUN_ID", "fixture")
    path = tmp_path / "private-note.pdf"
    path.write_text("private content")
    asyncio.run(legacy_delivery.post_text(prefix + str(path), chat_id=123, topic_id=4, html=False))
    assert BasePlatformAdapter.extract_media(captured[0])[0] == []


@pytest.fixture
def cfg():
    return {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
            "production_connections": False, "enabled_operations": ["enqueue", "worker", "send", "wiki_read", "wiki_write"],
            "delivery_targets": ["telegram:123:4"],
            "jobs": {"poll": {"stream": "ingest:jobs:email", "payload": {"job_type": "poll"}}},
            "worker": {"stream": "ingest:jobs:email", "group": "email-workers"}}


@pytest.fixture
def client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.mark.parametrize("operation", ["enqueue", "worker", "send", "wiki_write"])
def test_standby_refuses_side_effects(cfg, operation):
    cfg["mode"] = "standby"
    with pytest.raises(PermissionError):
        require_active(cfg, operation)


def test_rehearsal_rejects_production_connections(cfg):
    cfg["production_connections"] = True
    with pytest.raises(PermissionError):
        require_active(cfg, "send")


def test_production_receipt_bound_to_manifest(tmp_path, cfg):
    manifest, receipt = tmp_path / "manifest.json", tmp_path / "activation.json"
    manifest.write_text("first revision")
    cfg.update(mode="production", activation_receipt=str(receipt), _manifest_path=str(manifest))
    receipt.write_text(json.dumps({"command": "ACTIVATE_HERMES_BY_DENIS", "manifest_sha256": digest(manifest),
                                  "snapshot_sha256": "test-snapshot", "old_writers_stopped": True}))
    require_active(cfg, "worker")
    manifest.write_text("changed revision")
    with pytest.raises(PermissionError):
        require_active(cfg, "worker")


def test_duplicate_slot_only_enqueues_once(client, cfg):
    first = enqueue(client, cfg, "poll", "2026-09-06T13:05+03:00")
    assert enqueue(client, cfg, "poll", "2026-09-06T13:05+03:00") == first
    assert client.xlen("ingest:jobs:email") == 1
    with pytest.raises(ValueError):
        enqueue(client, cfg, "poll", "another", {"inbox_ref": "different-mailbox"})


def test_worker_success_and_crash_recovery(client, cfg):
    enqueue(client, cfg, "poll", "one")
    calls = []
    assert consume_one(client, cfg, lambda data: calls.append(data))
    assert len(calls) == 1
    assert client.xpending("ingest:jobs:email", "email-workers")["pending"] == 0
    enqueue(client, cfg, "poll", "two")
    client.xreadgroup("email-workers", "dead-worker", {"ingest:jobs:email": ">"})
    assert consume_one(client, cfg, lambda data: calls.append(data), reclaim_ms=0)
    assert len(calls) == 1  # Never blindly re-run a previously started pipeline.
    assert client.xlen("benka:reconcile") == 1
    assert client.xpending("ingest:jobs:email", "email-workers")["pending"] == 0


def test_reported_pipeline_failure_is_not_success(client, cfg):
    enqueue(client, cfg, "poll", "one")
    consume_one(client, cfg, lambda data: {"ok": False})
    assert client.xlen("benka:reconcile") == 1


def test_confirmed_delivery_has_id_and_is_not_repeated(client, cfg):
    calls = []
    def runner(*a, **kw):
        calls.append((a, kw))
        return subprocess.CompletedProcess(a, 0, '{"success":true,"message_id":42}')
    first = send(client, cfg, delivery_id="job:1", target="telegram:123:4", text="hello", runner=runner)
    assert first["message_id"] == "42"
    assert send(client, cfg, delivery_id="job:1", target="telegram:123:4", text="hello", runner=runner) == first
    assert len(calls) == 1
    with pytest.raises(ValueError):
        send(client, cfg, delivery_id="job:1", target="telegram:123:4", text="changed", runner=runner)


@pytest.mark.parametrize("reply", ['broken', '{"success":true}', '{"success":true,"skipped":true,"message_id":3}'])
def test_uncertain_delivery_is_quarantined(client, cfg, reply):
    calls = []
    def runner(*a, **kw):
        calls.append(1)
        return subprocess.CompletedProcess(a, 0, reply)
    for _ in range(2):
        with pytest.raises(UncertainDelivery):
            send(client, cfg, delivery_id="one", target="telegram:123:4", text="hello", runner=runner)
    assert len(calls) == 1


def test_destination_not_supplied_by_untrusted_content(client, cfg):
    with pytest.raises(PermissionError):
        send(client, cfg, delivery_id="one", target="telegram:999:4", text="hi")


def test_domain_path_isolation_and_discussion(tmp_path, cfg):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private")
    (vault / "escape.md").symlink_to(outside)
    cfg["vault_root"] = str(vault)
    for path in ("../outside.md", "escape.md", str(outside)):
        with pytest.raises((ValueError, PermissionError)):
            wiki.read(cfg, path)
    assert wiki.ingest(cfg, {"source_type": "text", "source": "Обсуди: идея"})["saved"] is False


def fixture_snapshot(tmp_path):
    source = tmp_path / "source"
    (source / "vault").mkdir(parents=True)
    (source / "vault/note.md").write_text("test wiki")
    (source / "redis").mkdir()
    (source / "redis/dump.rdb").write_bytes(b"synthetic fixture, not a live Redis dump")
    receipt = tmp_path / "cold.json"
    receipt.write_text(json.dumps({"writers_stopped": True, "syncthing_paused": True,
                                   "components": sorted(migration.COMPONENTS), "data_class": "test"}))
    out = tmp_path / "export"
    migration.snapshot(source, out, cold_receipt=receipt)
    return out


def test_snapshot_restore_repeat_and_modified_import_rejected(tmp_path):
    out = fixture_snapshot(tmp_path)
    destination = tmp_path / "imports"
    dry = migration.restore(out / "snapshot.tar", out / "manifest.json", destination)
    assert dry["dry_run"] and not destination.exists()
    result = migration.restore(out / "snapshot.tar", out / "manifest.json", destination, dry_run=False)
    assert migration.restore(out / "snapshot.tar", out / "manifest.json", destination, dry_run=False)["already_imported"]
    (destination / result["snapshot_sha256"] / "vault/note.md").write_text("newer data")
    with pytest.raises(ValueError):
        migration.restore(out / "snapshot.tar", out / "manifest.json", destination, dry_run=False)


def test_corruption_does_not_create_import(tmp_path):
    out = fixture_snapshot(tmp_path)
    with (out / "snapshot.tar").open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(ValueError):
        migration.restore(out / "snapshot.tar", out / "manifest.json", tmp_path / "imports", dry_run=False)
    assert not (tmp_path / "imports").exists()


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "vault/../../escape"])
def test_unsafe_archive_names_rejected(tmp_path, name):
    archive_path = tmp_path / "bad.tar"
    with tarfile.open(archive_path, "w") as bundle:
        member = tarfile.TarInfo(name)
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    manifest = {"schema": 1, "kind": "cold", "archive_sha256": digest(archive_path), "files": {}, "skipped": []}
    with pytest.raises(ValueError):
        migration.verify(archive_path, manifest)


def test_interrupted_restore_leaves_no_partial_snapshot(tmp_path, monkeypatch):
    out = fixture_snapshot(tmp_path)
    def fail(*a, **kw):
        raise OSError("simulated interrupted write")
    monkeypatch.setattr(migration.shutil, "copyfileobj", fail)
    dest = tmp_path / "imports"
    with pytest.raises(OSError):
        migration.restore(out / "snapshot.tar", out / "manifest.json", dest, dry_run=False)
    assert list(dest.iterdir()) == []


def test_archive_index_is_idempotent_with_sources(tmp_path):
    source = tmp_path / "conversations"
    source.mkdir()
    (source / "session.jsonl").write_text(json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "Обсуждали миграцию Беньки"}]}}) + "\ninvalid\n")
    database = tmp_path / "private/archive.sqlite"
    result = archive.index(source, database)
    assert result["imported_messages"] == 1 and len(result["skipped"]) == 1
    assert archive.index(source, database)["imported_messages"] == 0
    matches = archive.search(database, "миграцию")
    assert matches[0]["source"] == "session.jsonl" and matches[0]["line"] == 1


@pytest.mark.parametrize("text", ['[]', '{"ok":false}', 'prose {"ok":true}', '{"ok":true} trailing'])
def test_model_rejects_malformed_contract(text):
    with pytest.raises(ValueError):
        extract_json_payload(text)


def test_model_accepts_fenced_object():
    assert extract_json_payload('```json\n{"events":[]}\n```') == {"events": []}
