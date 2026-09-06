import unittest
from unittest.mock import patch
from types import SimpleNamespace

from werewolf_web.ai.llm import LLMClient, LLMRuntimeConfig
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.ai.brain import Speech


class _Completions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class LLMResilienceTest(unittest.TestCase):
    def runtime(self, **overrides):
        data = dict(enabled=True, base_url="https://example.invalid/v1", api_key="secret-key",
                    model="test-model", temperature=0.7, timeout_seconds=2, max_calls=3)
        data.update(overrides)
        return LLMRuntimeConfig(**data)

    def client_with(self, completions, **runtime):
        # Keep these unit tests provider-free; the fake below supplies only
        # the tiny client surface exercised by the resilience layer.
        runtime["enabled"] = False
        client = LLMClient(self.runtime(**runtime))
        client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        client.unavailable_reason = ""
        return client

    def test_public_status_never_exposes_api_key(self):
        client = self.client_with(_Completions())
        rendered = str(client.public_status())
        self.assertNotIn("secret-key", rendered)
        self.assertEqual(client.public_status()["mode"], "online")

    def test_budget_exhaustion_skips_provider_and_degrades(self):
        completions = _Completions()
        client = self.client_with(completions, max_calls=0)
        self.assertIsNone(client.generate("system", "prompt"))
        self.assertEqual(completions.requests, [])
        self.assertEqual(client.public_status()["mode"], "degraded")

    def test_consecutive_failures_open_circuit(self):
        client = self.client_with(_Completions(error=RuntimeError("network")))
        self.assertIsNone(client.generate("system", "prompt"))
        self.assertIsNone(client.generate("system", "prompt"))
        self.assertFalse(client.online)
        self.assertEqual(client.public_status()["reason"], "circuit_open")

    def test_reasoning_field_is_opt_in(self):
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="一句合法发言"))])
        completions = _Completions(response=response)
        client = self.client_with(completions, reasoning_effort="medium",
                                  reasoning_param="reasoning_effort")
        self.assertEqual(client.generate("system", "prompt"), "一句合法发言")
        self.assertEqual(completions.requests[0]["extra_body"],
                         {"reasoning_effort": "medium"})

    def test_free_form_model_cannot_reverse_locked_claim(self):
        speech = Speech(text="我验了 2 号是好人", claim="seer")
        self.assertFalse(StrategicNPCAgent._matches_intent("我不是预言家", speech))
        self.assertFalse(StrategicNPCAgent._matches_intent("x" * 901, speech))
        self.assertTrue(StrategicNPCAgent._matches_intent("我验了 2 号是好人", speech))

    def test_request_override_is_bounded_and_does_not_keep_unknown_fields(self):
        runtime = LLMRuntimeConfig.from_request({
            "api_key": "user-secret", "model": "different-model",
            "timeout_seconds": 999, "max_calls": -2, "unknown": "ignored",
        })
        self.assertEqual(runtime.api_key, "user-secret")
        self.assertEqual(runtime.model, "different-model")
        self.assertEqual(runtime.timeout_seconds, 30.0)
        self.assertEqual(runtime.max_calls, 0)

    def test_custom_endpoint_cannot_inherit_the_server_key(self):
        defaults = self.runtime(api_key="server-private-key")
        with patch.object(LLMRuntimeConfig, "from_config", return_value=defaults):
            redirected = LLMRuntimeConfig.from_request({"base_url": "https://other.example/v1"})
            own_key = LLMRuntimeConfig.from_request({"base_url": "https://other.example/v1", "api_key": "user-key"})
            unchanged = LLMRuntimeConfig.from_request(None)
        self.assertEqual(redirected.api_key, "")
        self.assertEqual(own_key.api_key, "user-key")
        self.assertEqual(unchanged.api_key, "server-private-key")

    def test_web_games_keep_model_credentials_and_memory_scopes_separate(self):
        from werewolf_web.run import GameRunner

        first = GameRunner("classic", {"enabled": False, "api_key": "first-secret"},
                           session_id="test-first")
        second = GameRunner("classic", {"enabled": False, "api_key": "second-secret"},
                            session_id="test-second")
        self.assertNotEqual(first.memory_dir, second.memory_dir)
        self.assertNotIn("first-secret", str(first.llm.public_status()))
        self.assertNotIn("second-secret", str(second.llm.public_status()))


if __name__ == "__main__":
    unittest.main()
