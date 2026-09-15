"""Product-flow regressions: bounded reply, authored cast and safe setup."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock, AsyncMock
from fastapi import HTTPException

from werewolf_web import run, settings, checkpoint, config
from werewolf_web.session import GameSession
from werewolf_web.ai.brain import Speech
from werewolf_web.characters import catalog
from werewolf_web.offline_game import OfflineSession, action_choices
from werewolf_web.connection_setup import register


class ReplyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(config, "DATA_DIR", self.tmp.name)
        self.patch.start()
        self.path = str(Path(self.tmp.name) / "game.json")

    async def asyncTearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    async def session(self):
        s = GameSession("classic", {"enabled":False}, session_id="reply-test", seed=7, checkpoint_path=self.path)
        await s._step_setup()
        s.engine.start_day()
        s._step = "vote"
        s._current_step = "vote"
        s.speech_events = [(next(iter(s.agents)), Speech(text="Please explain."))]
        s.questions.answered = s.questions.LIMIT
        return s

    async def request(self, s):
        while True:
            event = await asyncio.wait_for(s.event_q.get(), 2)
            if event["type"] == "request":
                return event

    async def test_shared_cap_cannot_remove_last_reply(self):
        s = await self.session()
        task = asyncio.create_task(s._pre_vote_reply())
        event = await self.request(s)
        self.assertTrue(event["data"]["final_reply"])
        self.assertFalse(task.done())
        self.assertTrue(s.submit({"answer":"我把理由说完整。"}))
        await task
        self.assertEqual(s.questions.answered, s.questions.LIMIT)
        self.assertEqual(s.speech_events[-1][1].text, "我把理由说完整。")
        restored = GameSession("classic", {"enabled":False}, session_id=s.session_id)
        restored.restore(checkpoint.load_checkpoint(self.path))
        before = len(restored._events)
        await restored._pre_vote_reply()
        self.assertEqual(len(restored._events), before)

    async def test_skip_is_durable_and_silent(self):
        s = await self.session()
        task = asyncio.create_task(s._pre_vote_reply())
        await self.request(s)
        s.submit({"skip":True})
        await task
        self.assertEqual(len(s.speech_events), 1)
        self.assertEqual(checkpoint.load_checkpoint(self.path)["step_state"]["pre_vote_reply_day"], 1)
        await s._pre_vote_reply()
        self.assertFalse(s.submit({"answer":"duplicate"}))

    async def test_pending_reply_restores_before_any_vote(self):
        s = await self.session()
        task = asyncio.create_task(s._pre_vote_reply())
        await self.request(s)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        restored = GameSession("classic", {"enabled":False}, session_id=s.session_id)
        restored.restore(checkpoint.load_checkpoint(self.path))
        self.assertTrue(restored.recovery_view()["pending"]["data"]["final_reply"])
        task = asyncio.create_task(restored._pre_vote_reply())
        await self.request(restored)
        restored.submit({"answer":"恢复后的解释。"})
        await task
        self.assertEqual(sum(x[1].text == "恢复后的解释。" for x in restored.speech_events), 1)

    async def test_dead_and_spectator_do_not_get_extra_turn(self):
        s = await self.session()
        s.engine.player_seat().alive = False
        await s._pre_vote_reply()
        self.assertIsNone(s.pending)
        s.engine.player_seat().alive = True
        s.spectator = True
        await s._pre_vote_reply()
        self.assertIsNone(s.pending)

    async def test_vote_step_waits_for_reply_before_ballots(self):
        s = await self.session()
        with patch.object(s, "_vote_phase", new_callable=AsyncMock) as vote, patch.object(s, "_post_death_triggers", new_callable=AsyncMock):
            task = asyncio.create_task(s._step_vote())
            event = await self.request(s)
            self.assertTrue(event["data"]["final_reply"])
            vote.assert_not_called()
            s.submit({"skip":True})
            await task
            vote.assert_awaited_once()


class CharacterTest(unittest.TestCase):
    def test_catalog_is_bilingual_complete_and_has_real_portraits(self):
        for locale in ("zh-CN", "en"):
            entries = catalog(locale)
            self.assertEqual(len({e["id"] for e in entries}), 30)
            for entry in entries:
                self.assertTrue(entry["title"] and entry["story"] and entry["phrase"])
                self.assertTrue((Path(config.STATIC_DIR) / entry["portrait"].lstrip("/")).is_file())

    def test_character_binding_and_role_independence_restore(self):
        s = GameSession("classic", {"enabled":False}, seed=7, character="amo", player_role="civilian")
        s.engine.setup()
        self.assertEqual(s.engine.player_seat().persona_id, "amo")
        self.assertEqual(s.engine.player_seat().role, "civilian")
        self.assertEqual(len({x["character_id"] for x in s.engine.public_state()["seats"]}), 12)
        restored = GameSession("classic", {"enabled":False})
        restored.engine.restore(s.engine.snapshot())
        self.assertEqual(s.engine.public_state(), restored.engine.public_state())
        other = GameSession("classic", {"enabled":False}, seed=7, character="amo", player_role="werewolf")
        other.engine.setup()
        self.assertEqual(other.engine.player_seat().persona_id, "amo")

    def test_seeded_random_character_and_invalid_restore(self):
        a = GameSession("classic", {"enabled":False}, seed=12, character="random")
        b = GameSession("classic", {"enabled":False}, seed=12, character="random")
        self.assertEqual(a.engine.cast_personas, b.engine.cast_personas)
        old = a.engine.snapshot()
        bad = deepcopy(old); bad["character_cast"] = "yes"
        with self.assertRaises(ValueError):
            a.engine.restore(bad)
        self.assertEqual(a.engine.snapshot(), old)

    def test_offline_final_reply_has_explicit_skip(self):
        s = OfflineSession(seed=2, character="random")
        s.engine.setup()
        options = action_choices(s, "table_answer", {"final_reply":True})
        self.assertEqual(options[0]["payload"], {"skip":True})
        self.assertEqual(len({x["character_id"] for x in s.engine.public_state()["seats"]}), 12)

    def test_conflicting_character_save_rejected_without_mutation(self):
        s = GameSession("classic", {"enabled":False}, seed=7, character="amo")
        s.engine.setup()
        before = s.engine.snapshot()
        bad = deepcopy(before)
        bad["seats"][0]["persona_id"] = "unknown"
        with self.assertRaises(ValueError):
            s.engine.restore(bad)
        self.assertEqual(before, s.engine.snapshot())


class SetupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(settings, "SETTINGS_PATH", str(Path(self.tmp.name)/"settings.json"))
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def req(self, body, token=True, origin="http://localhost"):
        class Req:
            headers = {"x-setup-token":run._SETUP_TOKEN if token else "bad", "origin":origin}
            base_url = "http://localhost/"
            async def json(self): return body
        return Req()

    async def test_fixed_adapter_registration_no_model_call(self):
        with patch("shutil.which", return_value="/local/codex"), patch.object(run, "create_runtime") as factory:
            response = await run.connection_register(self.req({"name":"Local", "model":"test-model", "effort":"medium", "max_calls":240}))
        self.assertFalse(response["verified"])
        factory.assert_not_called()
        self.assertEqual(settings.load_settings()["agent_connections"]["Local"]["adapter"], "codex")

    async def test_command_origin_and_token_rejected_without_mutation(self):
        register("Kept", "codex", "m")
        before = settings.load_settings()
        valid = {"name":"Local", "model":"m", "effort":"medium", "max_calls":240}
        for req in (self.req({**valid, "command":["evil"]}), self.req(valid, token=False), self.req(valid, origin="https://evil.example")):
            with self.assertRaises(HTTPException):
                await run.connection_register(req)
            self.assertEqual(settings.load_settings(), before)

    async def test_browser_api_save_retains_only_existing_trusted_connections(self):
        register("Kept", "codex", "m")
        settings.save_settings({"model":"api-model", "api_key":"fake-secret", "command":["evil"], "agent_connections":{"evil":{}}})
        saved = settings.load_settings()
        self.assertEqual(set(saved["agent_connections"]), {"Kept"})
        self.assertNotIn("api_key", saved)
        self.assertNotIn("command", saved)

    async def test_check_uses_one_preflight_no_game_or_settings(self):
        register("Local", "codex", "m")
        before = settings.load_settings()
        games = dict(run.GAMES)
        planner = Mock()
        with patch.object(run, "create_runtime", return_value=planner):
            result = await run.connection_check(self.req({"driver":"agent", "connection":"Local"}))
        planner.preflight.assert_called_once()
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(run.GAMES, games)
        self.assertEqual(settings.load_settings(), before)

    async def test_missing_config_stops_before_model(self):
        with patch.object(run.driver_mod, "resolve_driver", return_value={"configured":False}), patch.object(run, "create_runtime") as factory:
            with self.assertRaises(HTTPException) as caught:
                await run.connection_check(self.req({}))
        self.assertEqual(caught.exception.status_code, 422)
        factory.assert_not_called()
