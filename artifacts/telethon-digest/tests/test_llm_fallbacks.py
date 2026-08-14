import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import omniroute_client
from models import LLMCompletion


class FailingSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def post(self, *args, **kwargs):
        self.calls.append("omniroute")
        raise RuntimeError("omniroute unavailable")


class FakeResponse:
    headers = {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        return None

    async def json(self):
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "model": "light",
        }


class FakePostContext:
    async def __aenter__(self):
        return FakeResponse()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class OmnirouteSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def post(self, *args, **kwargs):
        self.calls.append("omniroute")
        return FakePostContext()


class LlmFallbackTests(unittest.TestCase):
    def test_openclaw_runs_first(self) -> None:
        calls: list[str] = []
        original_openclaw = omniroute_client._call_openclaw_fallback
        original_deepseek = omniroute_client._call_deepseek_fallback
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_openclaw(payload, *, default_model):
            calls.append("openclaw")
            return LLMCompletion(text='{"ok": true}', model_id="gpt-5.5", provider_fallback=False)

        async def fake_deepseek(session, payload, *, default_model):
            calls.append("deepseek")
            return LLMCompletion(text='{"ok": true}', model_id="deepseek-v4-flash", provider_fallback=True)

        try:
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.DEEPSEEK_API_KEY = "test-key"
            omniroute_client._call_openclaw_fallback = fake_openclaw
            omniroute_client._call_deepseek_fallback = fake_deepseek

            completion = asyncio.run(
                omniroute_client.call_chat_completion(
                    FailingSession(calls),
                    url="http://omniroute:20129/v1",
                    api_key="test",
                    payload={"messages": [{"role": "user", "content": "return json"}]},
                    timeout_seconds=1,
                    default_model="light",
                )
            )
        finally:
            omniroute_client._call_openclaw_fallback = original_openclaw
            omniroute_client._call_deepseek_fallback = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw"])
        self.assertFalse(completion.provider_fallback)
        self.assertEqual(completion.model_id, "gpt-5.5")

    def test_omniroute_runs_after_openclaw_failure_before_deepseek(self) -> None:
        calls: list[str] = []
        original_openclaw = omniroute_client._call_openclaw_fallback
        original_deepseek = omniroute_client._call_deepseek_fallback
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_openclaw(payload, *, default_model):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        async def fake_deepseek(session, payload, *, default_model):
            calls.append("deepseek")
            return LLMCompletion(text='{"ok": true}', model_id="deepseek-v4-flash", provider_fallback=True)

        try:
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.DEEPSEEK_API_KEY = "test-key"
            omniroute_client._call_openclaw_fallback = fake_openclaw
            omniroute_client._call_deepseek_fallback = fake_deepseek

            completion = asyncio.run(
                omniroute_client.call_chat_completion(
                    OmnirouteSession(calls),
                    url="http://omniroute:20129/v1",
                    api_key="test",
                    payload={"messages": [{"role": "user", "content": "return json"}]},
                    timeout_seconds=1,
                    default_model="light",
                )
            )
        finally:
            omniroute_client._call_openclaw_fallback = original_openclaw
            omniroute_client._call_deepseek_fallback = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute"])
        self.assertTrue(completion.provider_fallback)
        self.assertEqual(completion.model_id, "light")

    def test_deepseek_runs_after_openclaw_and_omniroute_failure(self) -> None:
        calls: list[str] = []
        original_openclaw = omniroute_client._call_openclaw_fallback
        original_qwen = omniroute_client._call_qwen_fallback
        original_deepseek = omniroute_client._call_deepseek_fallback
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_qwen_key = omniroute_client.QWEN_API_KEY
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_openclaw(payload, *, default_model):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        async def fake_deepseek(session, payload, *, default_model):
            calls.append("deepseek")
            return LLMCompletion(text='{"ok": true}', model_id="deepseek-v4-flash", provider_fallback=True)

        async def fake_qwen(session, payload, *, default_model):
            calls.append("qwen")
            raise AssertionError("qwen should be disabled for this final-reserve test")

        try:
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.QWEN_API_KEY = ""
            omniroute_client.DEEPSEEK_API_KEY = "test-key"
            omniroute_client._call_openclaw_fallback = fake_openclaw
            omniroute_client._call_qwen_fallback = fake_qwen
            omniroute_client._call_deepseek_fallback = fake_deepseek

            completion = asyncio.run(
                omniroute_client.call_chat_completion(
                    FailingSession(calls),
                    url="http://omniroute:20129/v1",
                    api_key="test",
                    payload={"messages": [{"role": "user", "content": "return json"}]},
                    timeout_seconds=1,
                    default_model="light",
                )
            )
        finally:
            omniroute_client._call_openclaw_fallback = original_openclaw
            omniroute_client._call_qwen_fallback = original_qwen
            omniroute_client._call_deepseek_fallback = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.QWEN_API_KEY = original_qwen_key
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute", "deepseek"])
        self.assertTrue(completion.provider_fallback)
        self.assertEqual(completion.model_id, "deepseek-v4-flash")

    def test_qwen_runs_after_openclaw_and_omniroute_failure_before_deepseek(self) -> None:
        calls: list[str] = []
        original_openclaw = omniroute_client._call_openclaw_fallback
        original_qwen = omniroute_client._call_qwen_fallback
        original_deepseek = omniroute_client._call_deepseek_fallback
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_qwen_key = omniroute_client.QWEN_API_KEY
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_openclaw(payload, *, default_model):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        async def fake_qwen(session, payload, *, default_model):
            calls.append("qwen")
            return LLMCompletion(text='{"ok": true}', model_id="qwen3.7-flash", provider_fallback=True)

        async def fake_deepseek(session, payload, *, default_model):
            calls.append("deepseek")
            raise AssertionError("deepseek must remain the last reserve")

        try:
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.QWEN_API_KEY = "test-key"
            omniroute_client.DEEPSEEK_API_KEY = "reserve-key"
            omniroute_client._call_openclaw_fallback = fake_openclaw
            omniroute_client._call_qwen_fallback = fake_qwen
            omniroute_client._call_deepseek_fallback = fake_deepseek

            completion = asyncio.run(
                omniroute_client.call_chat_completion(
                    FailingSession(calls),
                    url="http://omniroute:20129/v1",
                    api_key="test",
                    payload={"messages": [{"role": "user", "content": "return json"}]},
                    timeout_seconds=1,
                    default_model="light",
                )
            )
        finally:
            omniroute_client._call_openclaw_fallback = original_openclaw
            omniroute_client._call_qwen_fallback = original_qwen
            omniroute_client._call_deepseek_fallback = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.QWEN_API_KEY = original_qwen_key
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute", "qwen"])
        self.assertTrue(completion.provider_fallback)
        self.assertEqual(completion.model_id, "qwen3.7-flash")


if __name__ == "__main__":
    unittest.main()
