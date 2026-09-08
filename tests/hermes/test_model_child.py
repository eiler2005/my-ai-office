"""The isolated model subprocess: what config may configure, and what may escape.

`model_child` runs one agent per background task in a throwaway Hermes home. It
is the only place a worker-scoped API key is read, and the only process that sees
raw source content, so it has two jobs beyond calling a model.

It must not let a configuration file widen the agent. The provider file is
operational configuration, and only transport options are taken from it -- a file
that could also set `enabled_toolsets` or `skip_memory` would turn a config edit
into a capability grant.

And it must not let a provider's exception reach its parent. Those messages can
quote the prompt, which is untrusted source content, or echo an API key. Only
exception *class names* cross the pipe, which is why `run_agent_text` can
re-narrow them to identifiers.
"""
import io
import json
import os
import sys
import types

import pytest

from benka_integrations import model_child

FIXED_SAFETY_ARGUMENTS = {
    "enabled_toolsets": [], "disabled_toolsets": ["all"], "max_iterations": 3,
    "skip_context_files": True, "skip_memory": True, "skip_background_review": True,
    "load_soul_identity": False, "save_trajectories": False, "quiet_mode": True,
}
LEAKY_MESSAGE = "connect failed for synthetic-provider-key while summarising: Denis, your invoice"


@pytest.fixture(autouse=True)
def isolated_process(monkeypatch):
    """`main` chdirs into a directory it then deletes; restore the suite's cwd."""
    previous = os.getcwd()
    monkeypatch.setenv("HERMES_HOME", previous)
    yield
    os.chdir(previous)


@pytest.fixture
def providers(tmp_path, monkeypatch):
    def write(routes):
        path = tmp_path / "model-providers.json"
        path.write_text(json.dumps(routes))
        monkeypatch.setenv("BENKA_MODEL_PROVIDERS_FILE", str(path))
        return path

    return write


@pytest.fixture
def request_stdin(monkeypatch):
    def write(prompt="Summarise this.", timeout=60):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": prompt, "timeout": timeout})))

    return write


@pytest.fixture
def agent(monkeypatch):
    """Install a stub `run_agent` module and record how the agent was built."""
    calls, closed = [], []

    def install(*responses):
        class StubAgent:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                self._response = responses[len(calls) - 1]
                if isinstance(self._response, type) and issubclass(self._response, Exception):
                    raise self._response(LEAKY_MESSAGE)

            def run_conversation(self, prompt):
                if isinstance(self._response, Exception):
                    raise self._response
                return {"final_response": self._response}

            def close(self):
                closed.append(True)

        module = types.ModuleType("run_agent")
        module.AIAgent = StubAgent
        monkeypatch.setitem(sys.modules, "run_agent", module)
        return calls, closed

    return install


@pytest.mark.parametrize("routes, why", [
    ([], "no provider at all"),
    ({"provider": "custom"}, "an object instead of a list"),
    ("custom", "a bare string"),
    ([{"model": "a"}] * 5, "more routes than the bound allows"),
])
def test_an_unusable_provider_file_stops_the_run(providers, request_stdin, routes, why):
    providers(routes)
    request_stdin()
    with pytest.raises(ValueError, match="one to four"):
        model_child.main()


def test_four_providers_are_accepted(providers, request_stdin, agent, capsys):
    """Four is the documented bound, so it must not be off by one."""
    calls, _ = agent(*[RuntimeError(LEAKY_MESSAGE)] * 3, '{"ok": true}')
    providers([{"model": f"m{n}", "api_key": "k"} for n in range(4)])
    request_stdin()
    model_child.main()
    assert len(calls) == 4
    assert json.loads(capsys.readouterr().out) == {"text": '{"ok": true}'}


def test_configuration_cannot_widen_the_agent(providers, request_stdin, agent):
    """Only transport options are taken from the provider file."""
    calls, _ = agent('{"ok": true}')
    providers([{
        "model": "qwen3.7-flash", "provider": "custom", "base_url": "https://example.invalid/v1",
        "api_key": "k", "api_mode": "chat_completions",
        # A provider file must not be able to grant any of these.
        "enabled_toolsets": ["shell"], "disabled_toolsets": [], "skip_memory": False,
        "load_soul_identity": True, "save_trajectories": True, "max_iterations": 99,
    }])
    request_stdin()
    model_child.main()
    supplied, = calls
    assert set(supplied) - set(FIXED_SAFETY_ARGUMENTS) - {"ephemeral_system_prompt", "max_tokens",
                                                          "run_budget_seconds"} == {
        "model", "provider", "base_url", "api_key", "api_mode"}


def test_the_safety_arguments_are_always_fixed(providers, request_stdin, agent):
    calls, _ = agent('{"ok": true}')
    providers([{"model": "m", "api_key": "k", "enabled_toolsets": ["shell"], "skip_memory": False}])
    request_stdin()
    model_child.main()
    supplied, = calls
    for name, expected in FIXED_SAFETY_ARGUMENTS.items():
        assert supplied[name] == expected, f"{name} must not be configurable"


def test_the_run_budget_comes_from_the_request(providers, request_stdin, agent):
    calls, _ = agent('{"ok": true}')
    providers([{"model": "m", "api_key": "k"}])
    request_stdin(timeout=45)
    model_child.main()
    assert calls[0]["run_budget_seconds"] == 45


def test_source_content_is_declared_untrusted_to_the_model(providers, request_stdin, agent):
    calls, _ = agent('{"ok": true}')
    providers([{"model": "m", "api_key": "k"}])
    request_stdin()
    model_child.main()
    assert "untrusted" in calls[0]["ephemeral_system_prompt"]


def test_a_provider_failure_never_reaches_the_parent_as_text(providers, request_stdin, agent, capsys):
    """Only class names cross the pipe; messages may quote mail or a key."""
    agent(RuntimeError(LEAKY_MESSAGE))
    providers([{"model": "m", "api_key": "synthetic-provider-key"}])
    request_stdin()
    with pytest.raises(SystemExit) as raised:
        model_child.main()
    assert raised.value.code == 1
    out = capsys.readouterr().out
    assert json.loads(out) == {"error_types": ["RuntimeError"]}
    assert "synthetic-provider-key" not in out and "invoice" not in out


def test_a_constructor_failure_is_reported_the_same_way(providers, request_stdin, agent, capsys):
    """A bad base_url fails in `AIAgent(...)`, before any conversation."""
    agent(ConnectionError)
    providers([{"model": "m", "api_key": "k", "base_url": "https://example.invalid/v1"}])
    request_stdin()
    with pytest.raises(SystemExit):
        model_child.main()
    out = capsys.readouterr().out
    assert json.loads(out) == {"error_types": ["ConnectionError"]}
    assert LEAKY_MESSAGE not in out


def test_the_reserve_provider_is_tried_after_a_failure(providers, request_stdin, agent, capsys):
    calls, _ = agent(RuntimeError(LEAKY_MESSAGE), '{"ok": true}')
    providers([{"model": "primary", "api_key": "k"}, {"model": "reserve", "api_key": "k"}])
    request_stdin()
    model_child.main()
    assert [call["model"] for call in calls] == ["primary", "reserve"]
    assert json.loads(capsys.readouterr().out) == {"text": '{"ok": true}'}


def test_a_working_provider_stops_the_walk(providers, request_stdin, agent):
    calls, _ = agent('{"ok": true}', '{"ok": true}')
    providers([{"model": "primary", "api_key": "k"}, {"model": "reserve", "api_key": "k"}])
    request_stdin()
    model_child.main()
    assert len(calls) == 1, "the reserve must not be billed once the primary answered"


@pytest.mark.parametrize("response", ["Here you go: {\"ok\": true}", "", '{"ok": false}', "[1, 2]"])
def test_output_that_is_not_a_successful_json_object_counts_as_a_failure(providers, request_stdin,
                                                                        agent, capsys, response):
    """The contract is a JSON object, so prose or a refusal must fall through."""
    agent(response)
    providers([{"model": "m", "api_key": "k"}])
    request_stdin()
    with pytest.raises(SystemExit):
        model_child.main()
    assert "error_types" in json.loads(capsys.readouterr().out)


def test_the_agent_is_closed_even_when_it_fails(providers, request_stdin, agent):
    _, closed = agent(RuntimeError(LEAKY_MESSAGE), '{"ok": true}')
    providers([{"model": "primary", "api_key": "k"}, {"model": "reserve", "api_key": "k"}])
    request_stdin()
    model_child.main()
    assert len(closed) == 2, "every constructed agent must be closed, failures included"


def test_stdout_carries_one_json_object_and_nothing_else(providers, request_stdin, agent, capsys):
    """The agent's own chatter is redirected to stderr; stdout is the IPC channel."""
    agent('{"ok": true}')
    providers([{"model": "m", "api_key": "k"}])
    request_stdin()
    model_child.main()
    assert json.loads(capsys.readouterr().out) == {"text": '{"ok": true}'}
