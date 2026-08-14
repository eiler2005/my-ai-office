import sys
import json
import unittest
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import omniroute_client


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ModelFallbackTests(unittest.TestCase):
    def test_openclaw_runs_before_omniroute_and_deepseek(self) -> None:
        calls: list[str] = []
        original_urlopen = omniroute_client.urllib.request.urlopen
        original_openclaw = omniroute_client._run_openclaw_prompt
        original_deepseek = omniroute_client._run_deepseek_prompt
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_urlopen(*args, **kwargs):
            calls.append("omniroute")
            raise AssertionError("omniroute should not run before openclaw")

        def fake_openclaw(prompt):
            calls.append("openclaw")
            return {
                "ok": True,
                "items": [],
                "model_meta": {
                    "model_id": "gpt-5.5",
                    "tier": "light",
                    "provider_fallback": False,
                    "local_fallback": False,
                },
            }

        def fake_deepseek(prompt):
            calls.append("deepseek")
            return {"ok": True, "items": []}

        try:
            omniroute_client.urllib.request.urlopen = fake_urlopen
            omniroute_client._run_openclaw_prompt = fake_openclaw
            omniroute_client._run_deepseek_prompt = fake_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.DEEPSEEK_API_KEY = "test-key"

            payload = omniroute_client._run_omniroute_prompt("return json")
        finally:
            omniroute_client.urllib.request.urlopen = original_urlopen
            omniroute_client._run_openclaw_prompt = original_openclaw
            omniroute_client._run_deepseek_prompt = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw"])
        self.assertEqual(payload["model_meta"]["model_id"], "gpt-5.5")
        self.assertFalse(payload["model_meta"]["provider_fallback"])

    def test_omniroute_runs_after_openclaw_failure_before_deepseek(self) -> None:
        calls: list[str] = []
        original_urlopen = omniroute_client.urllib.request.urlopen
        original_openclaw = omniroute_client._run_openclaw_prompt
        original_deepseek = omniroute_client._run_deepseek_prompt
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_urlopen(*args, **kwargs):
            calls.append("omniroute")
            return FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "ok": True,
                                        "items": [],
                                        "model_meta": {
                                            "model_id": "light",
                                            "tier": "light",
                                            "local_fallback": False,
                                        },
                                    }
                                )
                            }
                        }
                    ],
                    "model": "light",
                }
            )

        def fake_openclaw(prompt):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        def fake_deepseek(prompt):
            calls.append("deepseek")
            return {
                "ok": True,
                "items": [],
            }

        try:
            omniroute_client.urllib.request.urlopen = fake_urlopen
            omniroute_client._run_openclaw_prompt = fake_openclaw
            omniroute_client._run_deepseek_prompt = fake_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.DEEPSEEK_API_KEY = "test-key"

            payload = omniroute_client._run_omniroute_prompt("return json")
        finally:
            omniroute_client.urllib.request.urlopen = original_urlopen
            omniroute_client._run_openclaw_prompt = original_openclaw
            omniroute_client._run_deepseek_prompt = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute"])
        self.assertEqual(payload["model_meta"]["model_id"], "light")
        self.assertTrue(payload["model_meta"]["provider_fallback"])

    def test_deepseek_runs_after_openclaw_and_omniroute_failure(self) -> None:
        calls: list[str] = []
        original_urlopen = omniroute_client.urllib.request.urlopen
        original_openclaw = omniroute_client._run_openclaw_prompt
        original_qwen = omniroute_client._run_qwen_prompt
        original_deepseek = omniroute_client._run_deepseek_prompt
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_qwen_key = omniroute_client.QWEN_API_KEY
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_urlopen(*args, **kwargs):
            calls.append("omniroute")
            raise urllib.error.URLError("omniroute unavailable")

        def fake_openclaw(prompt):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        def fake_deepseek(prompt):
            calls.append("deepseek")
            return {
                "ok": True,
                "items": [],
                "model_meta": {
                    "model_id": "deepseek-v4-flash",
                    "tier": "light",
                    "provider_fallback": True,
                    "local_fallback": False,
                },
            }

        def fake_qwen(prompt):
            calls.append("qwen")
            raise AssertionError("qwen should be disabled for this final-reserve test")

        try:
            omniroute_client.urllib.request.urlopen = fake_urlopen
            omniroute_client._run_openclaw_prompt = fake_openclaw
            omniroute_client._run_qwen_prompt = fake_qwen
            omniroute_client._run_deepseek_prompt = fake_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.QWEN_API_KEY = ""
            omniroute_client.DEEPSEEK_API_KEY = "test-key"

            payload = omniroute_client._run_omniroute_prompt("return json")
        finally:
            omniroute_client.urllib.request.urlopen = original_urlopen
            omniroute_client._run_openclaw_prompt = original_openclaw
            omniroute_client._run_qwen_prompt = original_qwen
            omniroute_client._run_deepseek_prompt = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.QWEN_API_KEY = original_qwen_key
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute", "deepseek"])
        self.assertEqual(payload["model_meta"]["model_id"], "deepseek-v4-flash")

    def test_qwen_runs_after_openclaw_and_omniroute_failure_before_deepseek(self) -> None:
        calls: list[str] = []
        original_urlopen = omniroute_client.urllib.request.urlopen
        original_openclaw = omniroute_client._run_openclaw_prompt
        original_qwen = omniroute_client._run_qwen_prompt
        original_deepseek = omniroute_client._run_deepseek_prompt
        original_enabled = omniroute_client.OPENCLAW_FALLBACK_ENABLED
        original_qwen_key = omniroute_client.QWEN_API_KEY
        original_deepseek_key = omniroute_client.DEEPSEEK_API_KEY

        def fake_urlopen(*args, **kwargs):
            calls.append("omniroute")
            raise urllib.error.URLError("omniroute unavailable")

        def fake_openclaw(prompt):
            calls.append("openclaw")
            raise RuntimeError("openclaw unavailable")

        def fake_qwen(prompt):
            calls.append("qwen")
            return {
                "ok": True,
                "items": [],
                "model_meta": {
                    "model_id": "qwen3.7-flash",
                    "tier": "light",
                    "provider_fallback": True,
                    "local_fallback": False,
                },
            }

        def fake_deepseek(prompt):
            calls.append("deepseek")
            raise AssertionError("deepseek must remain the last reserve")

        try:
            omniroute_client.urllib.request.urlopen = fake_urlopen
            omniroute_client._run_openclaw_prompt = fake_openclaw
            omniroute_client._run_qwen_prompt = fake_qwen
            omniroute_client._run_deepseek_prompt = fake_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = True
            omniroute_client.QWEN_API_KEY = "test-key"
            omniroute_client.DEEPSEEK_API_KEY = "reserve-key"

            payload = omniroute_client._run_omniroute_prompt("return json")
        finally:
            omniroute_client.urllib.request.urlopen = original_urlopen
            omniroute_client._run_openclaw_prompt = original_openclaw
            omniroute_client._run_qwen_prompt = original_qwen
            omniroute_client._run_deepseek_prompt = original_deepseek
            omniroute_client.OPENCLAW_FALLBACK_ENABLED = original_enabled
            omniroute_client.QWEN_API_KEY = original_qwen_key
            omniroute_client.DEEPSEEK_API_KEY = original_deepseek_key

        self.assertEqual(calls, ["openclaw", "omniroute", "qwen"])
        self.assertEqual(payload["model_meta"]["model_id"], "qwen3.7-flash")


if __name__ == "__main__":
    unittest.main()
