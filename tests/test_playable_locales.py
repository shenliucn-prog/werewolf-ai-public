"""Exercise real sessions, including initialization, actions and game completion."""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from werewolf_web.ai.brain import Speech
from werewolf_web.ai.llm import LLMClient, LLMRuntimeConfig
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.chat_game import _render, _request_prompt, parse_action
from werewolf_web.game.engine import BOARD_MAP, GameEngine
from werewolf_web.run import GameSession, boards


class PlayableLocalesTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_boards_complete_in_both_languages(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("werewolf_web.run.asyncio.sleep", new=AsyncMock()), \
                patch("werewolf_web.ai.host.STYLE_PATH", os.path.join(tmp, "host.json")), \
                patch("werewolf_web.ai.host.REVIEW_DIR", tmp):
            for locale in ("zh-CN", "en"):
                for board in BOARD_MAP:
                    for seed in (7, 42):
                        with self.subTest(locale=locale, board=board, seed=seed):
                            session = GameSession(board, {"enabled": False}, seed=seed, locale=locale)
                            session.memory_dir = os.path.join(tmp, f"{locale}-{board}-{seed}")
                            events = []
                            stream = session.events()
                            try:
                                async for event in stream:
                                    events.append(event)
                                    self.assertLess(len(events), 1800, "session did not converge")
                                    self.assertNotEqual(event["type"], "error", event)
                                    if event["type"] == "request":
                                        kind, data = event["kind"], event["data"]
                                        self.assertTrue(session.host.answer_rule_question(
                                            "How does the Witch work?" if locale == "en" else "女巫怎么用药？",
                                            session.engine))
                                        self.assertTrue(session.q.empty(), "rule chat consumed an action")
                                        if kind in ("speech", "table_reply"):
                                            raw = "I want to hear the table." if locale == "en" else "我先听大家发言。"
                                        elif kind == "election_up":
                                            raw = "yes"
                                        elif data.get("role_key") == "witch":
                                            saves = data.get("save_candidates", [])
                                            raw = f"save {saves[0]['pos']}" if saves else "pass"
                                        else:
                                            raw = str(data["candidates"][0]["pos"]) if data.get("candidates") else "pass"
                                        action = parse_action(kind, data, raw)
                                        self.assertIsNotNone(action, (kind, data, raw))
                                        self.assertTrue(session.submit(action))
                                        if locale == "en":
                                            self.assertNotRegex(_request_prompt(kind, data, locale), r"[\u4e00-\u9fff]")
                                    if locale == "en":
                                        rendered = io.StringIO()
                                        with contextlib.redirect_stdout(rendered):
                                            _render(event, locale)
                                        self.assertNotRegex(rendered.getvalue(), r"[\u4e00-\u9fff]", event)
                                        for key in ("text", "reason", "host_intro"):
                                            self.assertNotRegex(event.get(key, ""), r"[\u4e00-\u9fff]", event)
                            finally:
                                await stream.aclose()
                            self.assertEqual(events[0]["type"], "init")
                            self.assertEqual(events[-1]["type"], "gameover")
                            self.assertTrue(any(e["type"] == "review" for e in events))
                            self.assertIn(session.engine.winner, ("god", "wolf"))
                            self.assertTrue(session.finished)

    async def test_board_metadata_is_localized_without_changing_rules(self):
        zh, en = await boards("zh-CN"), await boards("en")
        self.assertEqual([b["roles"] for b in zh["boards"]], [b["roles"] for b in en["boards"]])
        self.assertNotRegex(json.dumps(en, ensure_ascii=False), r"[\u4e00-\u9fff]")

    async def test_initialization_failure_is_visible(self):
        session = GameSession("classic", {"enabled": False}, locale="en")
        with patch.object(session.engine, "setup", side_effect=RuntimeError("test failure")), \
                self.assertLogs("werewolf_web.run", level="ERROR"):
            events = [event async for event in session.events()]
        self.assertEqual(events[0]["type"], "error")
        self.assertTrue(session.finished)

    async def test_invalid_or_duplicate_input_does_not_advance_the_game(self):
        session = GameSession("classic", {"enabled": False}, locale="en")
        request = {"kind": "night", "data": {"role_key": "witch", "antidote": True,
                   "poison": True, "save_candidates": [{"pos": 1}], "candidates": [{"pos": 2}]}}
        session.pending = request
        for response in ({"save": 1, "poison": 2}, {"poison": 99}):
            self.assertFalse(session.submit(response))
            self.assertIs(session.pending, request)
            self.assertTrue(session.q.empty())
        self.assertTrue(session.submit({"save": 1}))
        self.assertFalse(session.submit({"save": 1}))
        self.assertEqual(session.q.qsize(), 1)

    async def test_stopping_event_consumer_cancels_the_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = GameSession("classic", {"enabled": False}, locale="en")
            session.memory_dir = tmp
            stream = session.events()
            self.assertEqual((await stream.__anext__())["type"], "init")
            await stream.aclose()
            self.assertTrue(session.finished)


class LocaleBehaviorTest(unittest.TestCase):
    def test_translation_preserves_distinct_personalities(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = []
            for locale in ("zh-CN", "en"):
                engine = GameEngine("classic", seed=9, locale=locale)
                engine.setup()
                llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
                agents = [StrategicNPCAgent(s.name, engine, llm, memory_dir=tmp)
                          for s in engine.seats.values() if not s.is_player]
                profiles.append({a.seat.player_id: (a.style, a.brain.cognition) for a in agents})
            self.assertEqual(profiles[0], profiles[1])
            self.assertGreater(len({p[0].argument for p in profiles[1].values()}), 2)

    def test_english_human_claim_and_targets_enter_public_reasoning(self):
        session = GameSession("classic", {"enabled": False}, seed=9, locale="en")
        session.engine.setup()
        target = next(s for s in session.engine.seats.values() if not s.is_player)
        speech = session._player_speech(f"I am the Seer. I suspect #{target.pos}.")
        self.assertEqual(speech.claim, "seer")
        self.assertEqual(speech.accuse, target.name)
        self.assertEqual(session._player_speech(f"I trust {target.name}.").defend, target.name)
        self.assertIsNone(session._player_speech("I am not the Seer.").claim)

    def test_english_witch_keeps_ability_and_rejects_invalid_commands(self):
        data = {"role_key": "witch", "role": "Witch", "candidates": [{"pos": 2}],
                "save_candidates": [{"pos": 1}], "antidote": True, "poison": True}
        self.assertEqual(parse_action("night", data, "save 1"), {"save": 1, "poison": None})
        self.assertEqual(parse_action("night", data, "pass"), {"save": None, "poison": None})
        for raw in ("save 2", "poison 7", "save 1 poison 2", "something unclear"):
            self.assertIsNone(parse_action("night", data, raw))

    def test_wrong_language_model_output_falls_back_to_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = GameEngine("classic", seed=3, locale="en")
            engine.setup()
            llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
            agent = StrategicNPCAgent(next(s.name for s in engine.seats.values() if not s.is_player),
                                      engine, llm, memory_dir=tmp)
            with patch.object(type(llm), "online", new_callable=unittest.mock.PropertyMock, return_value=True), \
                    patch.object(llm, "generate", return_value="我是预言家") as generate:
                speech = agent.speak([])
            self.assertNotRegex(speech.text, r"[\u4e00-\u9fff]")
            self.assertIn("English", generate.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
