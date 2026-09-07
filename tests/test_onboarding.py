import contextlib
import io
import unittest
from unittest.mock import patch

from werewolf_web.chat_game import parse_action
from werewolf_web.game.engine import BOARD_MAP, GameEngine
from werewolf_web.onboarding import introduction, seating_text
from werewolf_web.run import GameSession
from werewolf_web.setup import main


class OnboardingTest(unittest.IsolatedAsyncioTestCase):
    async def test_rules_question_and_invalid_action_cannot_start_night(self):
        for locale in ("en", "zh-CN"):
            session = GameSession("classic", {"enabled": False}, seed=45,
                                  locale=locale, player_role="guard", onboarding=True)
            with patch("werewolf_web.run.asyncio.sleep", return_value=None):
                async with contextlib.aclosing(session.events()) as events:
                    async for event in events:
                        if event["type"] == "request":
                            self.assertEqual(event["kind"], "ready")
                            break
                    self.assertEqual(session.engine.night_count, 0)
                    self.assertFalse(session.submit({"ready": "true"}))
                    self.assertFalse(session.submit({"target": 3}))
                    session.host.answer_rule_question("How does the Guard work?" if locale == "en" else "守卫能连守吗", session.engine)
                    self.assertEqual(session.pending["kind"], "ready")
                    self.assertEqual(session.engine.night_count, 0)
                    self.assertTrue(session.submit({"ready": True}))
                    async for event in events:
                        if event["type"] == "request":
                            self.assertEqual(event["kind"], "night")
                            self.assertEqual(session.engine.night_count, 1)
                            break

    def test_all_boards_have_localized_public_rules_and_seats(self):
        for locale in ("en", "zh-CN"):
            for board in BOARD_MAP:
                engine = GameEngine(board, seed=45, locale=locale)
                engine.setup()
                text = introduction(engine)
                self.assertIn("Raven" if locale == "en" else "夜鸦", text)
                self.assertIn("withdrawal" if locale == "en" else "退警", text)
                table = seating_text(engine.public_state())
                for seat in engine.seats.values():
                    self.assertIn(f"#{seat.pos} {seat.name}", table)
                self.assertNotIn("werewolf", table)
                if engine.witch_unlimited:
                    self.assertIn("unlimited" if locale == "en" else "不限", text)

    def test_setup_default_path_launches_model_chat(self):
        with patch("sys.argv", ["setup", "--lang", "en"]), patch("builtins.input", side_effect=[""] * 7), \
             patch("werewolf_web.setup.subprocess.call", return_value=0) as launch, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        command = launch.call_args.args[0]
        self.assertIn("werewolf_web.chat_game", command)
        self.assertNotIn("--offline", command)
        self.assertNotIn("--conjecture", command)

    def test_ready_requires_explicit_confirmation(self):
        self.assertEqual(parse_action("ready", {}, "开始"), {"ready": True})
        self.assertEqual(parse_action("ready", {}, "ready"), {"ready": True})
        self.assertIsNone(parse_action("ready", {}, ""))
        self.assertIsNone(parse_action("ready", {}, "what is this game?"))

    def test_missing_dependencies_explains_next_step_without_launch(self):
        output = io.StringIO()
        with patch("sys.argv", ["setup", "--check", "--lang", "en"]), \
             patch("werewolf_web.setup.importlib.util.find_spec", return_value=None), \
             patch("werewolf_web.setup.subprocess.call") as launch, contextlib.redirect_stdout(output):
            self.assertEqual(main(), 1)
            launch.assert_not_called()
        self.assertIn("pip install -r", output.getvalue())
        self.assertIn("-m werewolf_web.setup", output.getvalue())

    def test_browser_setup_launches_only_local_server(self):
        with patch("sys.argv", ["setup", "--lang", "en"]), patch("builtins.input", return_value="web"), \
             patch("werewolf_web.setup.subprocess.call", return_value=0) as launch, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        self.assertIn("127.0.0.1", launch.call_args.args[0])
        self.assertIn("werewolf_web.run:app", launch.call_args.args[0])
