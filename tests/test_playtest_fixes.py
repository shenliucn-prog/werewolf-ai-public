"""Public facts and short, persona-aware model-turn regressions."""
import unittest
from unittest.mock import AsyncMock, patch
import test_codex_player
from werewolf_web.session import GameSession
from werewolf_web.ai.model_context import public_facts


class LocalPlaytestFixes(unittest.IsolatedAsyncioTestCase):
    async def test_host_peaceful_night_survives_public_record_snapshot(self):
        game = GameSession("classic", {"enabled": False}, seed=7)
        game.engine.setup()
        game.engine.start_night()
        with patch.object(game, "_pace", new=AsyncMock()):
            await game._step_day_start()
        facts = public_facts(game.public_record.entries)
        fact = next(f for f in facts if f["kind"] == "night_outcome")
        self.assertEqual((fact["night"], fact["deaths"], fact["source"]), (1, 0, "host"))
        restored = GameSession("classic", {"enabled": False})
        restored.restore(game.snapshot())
        self.assertEqual(public_facts(restored.public_record.entries), facts)

    def test_player_prose_does_not_become_host_fact(self):
        game = GameSession("classic", {"enabled": False})
        game._record_event({"type": "speech", "seat": 3, "name": "P", "text": "昨夜平安", "night_outcome": {"deaths": 0, "night": 1}})
        self.assertFalse(public_facts(game.public_record.entries))

    def test_explicit_check_is_attributed_not_verified_role(self):
        game = GameSession("classic", {"enabled": False})
        event = game._record_event({"type": "speech", "seat": 3, "name": "P", "text": "预言家查验声明：第1夜，4号，好人。"})
        self.assertEqual(event["check_reports"][0]["target"], 4)
        self.assertNotIn("role", event)

    def test_short_speech_limits_and_persona_are_in_actual_request(self):
        helper = test_codex_player.CodexPlayerTest()
        self.addCleanup(helper.doCleanups)
        for locale, limit in [("zh-CN", 240), ("en", 720)]:
            agent, planner, _ = helper.make_agent(locale=locale)
            planner.complete.return_value = dict(text="OK", claim=None, accuse=None, defend=None, question_to=None)
            agent.speak([])
            request, schema = planner.complete.call_args.args
            self.assertEqual(schema["properties"]["text"]["maxLength"], limit)
            self.assertEqual(request["persona"], agent.persona)
            self.assertIn("speech_contract", request["details"])
            agent.speak([], task="brief answer to public question")
            self.assertEqual(planner.complete.call_args.args[1]["properties"]["text"]["maxLength"], limit // 2)
