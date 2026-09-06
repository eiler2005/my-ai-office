"""Native AIAgent calls a local protocol fixture; no external provider is used."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from benka_integrations.models import AgentRunError, run_agent_json


@pytest.fixture
def protocol_fixture(tmp_path, monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if "/slow/" in self.path:
                time.sleep(3)
            status = 401 if "/bad/" in self.path else 200
            reply = ({"error": {"message": "synthetic auth failure", "type": "authentication_error"}} if status == 401 else
                     {"id": "fixture", "object": "chat.completion", "created": 1, "model": "fixture-model",
                      "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"events":[]}'}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}})
            self.send_response(status)
            streaming = status == 200 and body.get("stream") is True
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.end_headers()
            try:
                if streaming:
                    chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": 1, "model": "fixture-model",
                             "choices": [{"index": 0, "delta": {"role": "assistant", "content": '{"events":[]}'}, "finish_reason": None}]}
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                    chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
                else:
                    self.wfile.write(json.dumps(reply).encode())
            except BrokenPipeError:
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = tmp_path / "interactive"
    home.mkdir()
    (home / "MEMORY.md").write_text("PRIVATE_MEMORY_SENTINEL")
    monkeypatch.setenv("HERMES_HOME", str(home))
    providers = tmp_path / "providers.json"
    monkeypatch.setenv("BENKA_MODEL_PROVIDERS_FILE", str(providers))
    def configure(routes):
        providers.write_text(json.dumps([{"provider": "custom", "model": "fixture-model", "api_mode": "chat_completions",
                                          "base_url": f"http://127.0.0.1:{server.server_port}/{route}/v1",
                                          "api_key": "synthetic-local-fixture"} for route in routes]))
    yield configure, requests
    server.shutdown()
    server.server_close()


def test_native_model_has_no_tools_or_interactive_memory(protocol_fixture):
    configure, requests = protocol_fixture
    configure(["ok"])
    try:
        result = run_agent_json("Return an empty events list as JSON", timeout_seconds=30)
    except AgentRunError as exc:
        pytest.fail(f"{exc}; fixture requests: {[(path, body.get('stream')) for path, body in requests]}")
    assert result.payload == {"events": []}
    assert requests
    assert all(not body.get("tools") for _, body in requests)
    assert "PRIVATE_MEMORY_SENTINEL" not in json.dumps(requests)


def test_native_model_tries_reserve_after_auth_failure(protocol_fixture):
    configure, requests = protocol_fixture
    configure(["bad", "ok"])
    assert run_agent_json("Return JSON", timeout_seconds=30).payload == {"events": []}
    assert any("/bad/" in path for path, _ in requests)
    assert any("/ok/" in path for path, _ in requests)


def test_native_model_deadline_terminates_process(protocol_fixture):
    configure, requests = protocol_fixture
    configure(["slow"])
    started = time.monotonic()
    with pytest.raises(AgentRunError, match="deadline"):
        run_agent_json("Return JSON", timeout_seconds=1)
    assert time.monotonic() - started < 3
