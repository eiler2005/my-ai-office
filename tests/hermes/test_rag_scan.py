"""A RAG scan must not abort on a document LightRAG already holds.

Regression for 2026-09-07: `upload()` called `raise_for_status()` on every
response, so the first 409 Conflict -- LightRAG's way of saying "already have
this" -- aborted the whole scan. Every later file, including genuinely new ones,
went unindexed, and the job landed in `benka:reconcile` every 30 minutes.
"""
import fakeredis
import pytest

from benka_integrations import maintenance


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"raise_for_status must not be reached for {self.status_code}")


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "vault"
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "page.md").write_text("# page\n")
    (root / "wiki" / "second.md").write_text("# second\n")
    return {
        "schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
        "production_connections": False,
        "enabled_operations": ["index"],
        "rag_source_root": str(root), "rag_index_roots": ["wiki"],
        "rag_url": "http://lightrag.invalid", "rag_token_env": "TEST_RAG_TOKEN",
    }


def test_conflict_is_recorded_as_duplicate_not_a_failure(config, monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_RAG_TOKEN", "token")
    monkeypatch.setattr(maintenance.requests, "post", lambda *a, **k: Response(409))
    client = fakeredis.FakeStrictRedis(decode_responses=True)

    path = next((tmp_path / "vault" / "wiki").glob("page.md"))
    result = maintenance.upload(config, client, path)

    assert result["status"] == "duplicate"


def test_a_duplicate_does_not_stop_the_scan_reaching_later_files(config, monkeypatch):
    monkeypatch.setenv("TEST_RAG_TOKEN", "token")
    seen = []

    def post(url, files=None, headers=None, timeout=None):
        seen.append(files["file"][0])
        # the first file is already indexed, the second is new
        return Response(409) if len(seen) == 1 else Response(200, {"track_id": "t1"})

    monkeypatch.setattr(maintenance.requests, "post", post)
    client = fakeredis.FakeStrictRedis(decode_responses=True)

    result = maintenance.run(config, client, {"action": "rag-scan"})

    assert result["ok"] is True
    assert len(seen) == 2, "the scan must continue past the duplicate"
    assert sorted(r["status"] for r in result["files"]) == ["duplicate", "submitted"]


def test_a_duplicate_is_not_re_uploaded_on_the_next_pass(config, monkeypatch):
    monkeypatch.setenv("TEST_RAG_TOKEN", "token")
    calls = []
    monkeypatch.setattr(maintenance.requests, "post",
                        lambda *a, **k: (calls.append(1), Response(409))[1])
    client = fakeredis.FakeStrictRedis(decode_responses=True)

    maintenance.run(config, client, {"action": "rag-scan"})
    first = len(calls)
    maintenance.run(config, client, {"action": "rag-scan"})

    assert len(calls) == first, "the recorded digest should skip a known duplicate"
