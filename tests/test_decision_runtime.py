import asyncio
import json
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException
from werewolf_web.ai.decision_runtime import APIPlayerRuntime, CommandPlayerRuntime, ModelTurnError, create_runtime
from werewolf_web.ai.llm import LLMRuntimeConfig
from werewolf_web.ai.model_player import ModelNPCAgent
from werewolf_web.chat_game import parse_action
from werewolf_web.run import GAMES, GameSession, start


class DecisionRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def config(self, **kwargs):
        return replace(LLMRuntimeConfig(True, "http://local.example/v1", "", "test-model", 0.7, 2, 5), **kwargs)

    def test_api_contract_keyless_local_model_and_no_tools(self):
        requests = []
        def respond(request):
            requests.append(request)
            payload = json.loads(request.content)
            envelope = json.loads(payload["messages"][1]["content"])
            self.assertEqual(envelope["protocol"], "werewolf.decision.v1")
            self.assertNotIn("tools", payload)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ready":true}'}}]})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        runtime = APIPlayerRuntime(self.config())
        with patch("werewolf_web.ai.decision_runtime.httpx.Client", return_value=client):
            runtime.preflight()
        self.assertTrue(runtime.verified)
        self.assertEqual(str(requests[0].url), "http://local.example/v1/chat/completions")
        self.assertNotIn("authorization", requests[0].headers)

    def test_api_failures_never_become_successful_local_decisions(self):
        for status, payload in [(401, {}), (302, {}), (200, {"choices": []}),
            (200, {"choices": [{"message": {"content": "not JSON"}}]}),
            (200, {"choices": [{"message": {"content": '{"ready":true}', "tool_calls": [{}]}}]})]:
            client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))
            runtime = APIPlayerRuntime(self.config(api_key="TEST_SECRET"))
            with patch("werewolf_web.ai.decision_runtime.httpx.Client", return_value=client):
                with self.assertRaises(ModelTurnError) as caught:
                    runtime.preflight()
            self.assertFalse(runtime.verified)
            self.assertNotIn("TEST_SECRET", str(caught.exception))
            self.assertNotIn("TEST_SECRET", json.dumps(runtime.public_status()))

    def test_switching_endpoint_never_reuses_server_key(self):
        with patch.object(LLMRuntimeConfig, "from_config", return_value=self.config(api_key="TEST_SECRET")):
            runtime = create_runtime("api", {"base_url": "https://another.example/v1"})
        self.assertEqual(runtime.config.api_key, "")

    def test_reasoning_field_and_credentials_stay_out_of_model_context(self):
        def respond(request):
            body = json.loads(request.content)
            self.assertEqual(body["reasoning_effort"], "high")
            self.assertNotIn("TEST_SECRET", request.content.decode())
            self.assertEqual(request.headers["Authorization"], "Bearer TEST_SECRET")
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ready":true}'}}]})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        runtime = APIPlayerRuntime(self.config(api_key="TEST_SECRET", reasoning_effort="high", reasoning_param="reasoning_effort"))
        with patch("werewolf_web.ai.decision_runtime.httpx.Client", return_value=client):
            runtime.preflight()

    def test_generic_agent_wrapper_protocol_works_without_codex(self):
        # This is a protocol fixture, NOT a real LLM quality test.
        command = [sys.executable, "-c", "import json,sys; r=json.load(sys.stdin); assert r['protocol']=='werewolf.decision.v1'; print(json.dumps({'ready':True}))"]
        runtime = CommandPlayerRuntime(command, max_calls=1)
        runtime.preflight()
        self.assertTrue(runtime.verified)
        with self.assertRaises(ModelTurnError):
            runtime.preflight()

    def test_command_cannot_be_shell_string(self):
        with self.assertRaises(ValueError):
            CommandPlayerRuntime("untrusted shell string")

    async def test_browser_default_preflights_and_uses_shared_model_player(self):
        planner = SimpleNamespace(verified=False, public_status=lambda: {"backend": "api", "mode": "model_decisions"})
        def preflight(): planner.verified = True
        planner.preflight = preflight
        req = SimpleNamespace(json=AsyncMock(return_value={"board_id": "classic",
                                                          "llm": {"enabled": True, "model": "test"}}))
        with patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
             patch("werewolf_web.run.user_settings.save_settings"), \
             patch("werewolf_web.run.create_runtime", return_value=planner) as factory:
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        session = GAMES[response["game_id"]]
        self.assertIs(session.planner, planner)
        self.assertTrue(planner.verified)
        self.assertEqual(response["llm_status"]["backend"], "api")
        self.assertEqual(session.engine.night_count, 0)
        self.assertEqual(factory.call_args.kwargs["backend"], "api")

    async def test_browser_failed_preflight_creates_no_game(self):
        before = set(GAMES)
        req = SimpleNamespace(json=AsyncMock(return_value={"board_id": "classic",
                                                          "llm": {"enabled": True, "model": "test"}}))
        planner = SimpleNamespace(preflight=Mock(side_effect=ModelTurnError("PRIVATE_KEY_CANARY")))
        with patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
             patch("werewolf_web.run.user_settings.save_settings"), \
             patch("werewolf_web.run.create_runtime", return_value=planner), self.assertRaises(HTTPException) as error:
            await start(req)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("PRIVATE_KEY_CANARY", error.exception.detail)
        self.assertEqual(set(GAMES), before)

    async def test_browser_cannot_supply_executable_commands(self):
        req = SimpleNamespace(json=AsyncMock(return_value={"backend": "command", "command": ["evil"],
                                                          "llm": {"enabled": True, "model": "test"}}))
        planner = SimpleNamespace(preflight=Mock(), verified=True, public_status=lambda: {})
        with patch("werewolf_web.run.create_runtime", return_value=planner) as factory:
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        self.assertEqual(factory.call_args.kwargs["backend"], "api")
        self.assertNotIn("command", factory.call_args.kwargs)

    async def test_retry_preserves_session_and_never_reruns_completed_work(self):
        session = GameSession("classic", {"enabled": False}, planner=SimpleNamespace(verified=True))
        call = Mock(side_effect=[ModelTurnError("PRIVATE_CANARY"), {"target": 3}])
        task = asyncio.create_task(session._npc_call(call))
        try:
            while True:
                event = await asyncio.wait_for(session.event_q.get(), 2)
                self.assertNotIn("PRIVATE_CANARY", json.dumps(event))
                if event["type"] == "request": break
            self.assertEqual(event["kind"], "model_retry")
            self.assertFalse(session.submit({"target": 1}))
            self.assertTrue(session.submit({"retry": True}))
            self.assertEqual(await asyncio.wait_for(task, 2), {"target": 3})
            self.assertEqual(call.call_count, 2)
        finally:
            task.cancel()

    def test_retry_requires_explicit_choice(self):
        self.assertIsNone(parse_action("model_retry", {}, "continue"))
        self.assertEqual(parse_action("model_retry", {}, "重试"), {"retry": True})
        self.assertEqual(parse_action("model_retry", {}, "stop"), {"retry": False})

    def test_default_factory_is_provider_neutral(self):
        with patch.dict("os.environ", {"WEREWOLF_MODEL_BACKEND": "api"}):
            self.assertIsInstance(create_runtime(), APIPlayerRuntime)
        self.assertEqual(ModelNPCAgent.__module__, "werewolf_web.ai.model_player")

    async def test_stopping_failed_decision_never_calls_fallback(self):
        session = GameSession("classic", {"enabled": False}, planner=SimpleNamespace(verified=True))
        call = Mock(side_effect=ModelTurnError("failed"))
        task = asyncio.create_task(session._npc_call(call))
        try:
            while (await asyncio.wait_for(session.event_q.get(), 2))["type"] != "request":
                pass
            session.submit({"retry": False})
            with self.assertRaises(ModelTurnError):
                await asyncio.wait_for(task, 2)
            self.assertEqual(call.call_count, 1)
        finally:
            task.cancel()
