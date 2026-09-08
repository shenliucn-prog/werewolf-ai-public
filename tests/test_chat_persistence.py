"""§7 chat (terminal) entry wired to persistence and restore.

Before the wiring, ``chat_game.py`` built ``GameSession`` without a
``checkpoint_path`` and had no resume entry, so the terminal adapter never wrote
a save and could not rehydrate an interrupted game.  Now the chat session is
keyed by a stable ``chat-…`` id, checkpointed at the same turn boundaries as the
web adapter, and resumed via ``--resume GAME_ID``.
"""
import asyncio
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import checkpoint as cp
from werewolf_web import chat_game
from werewolf_web.run import GameSession


class ChatPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_play_wires_a_checkpoint_path(self):
        captured = {}

        async def fake_repl(session):
            captured["session"] = session
            return 0

        with patch.object(chat_game, "_repl", new=fake_repl):
            result = await chat_game.play("classic", 7, True, "zh-CN")
        self.assertEqual(result, 0)
        session = captured["session"]
        self.assertTrue(session.session_id.startswith("chat-"))
        # The terminal session now persists to the same keyed store as the web.
        self.assertEqual(session.checkpoint_path,
                         cp.checkpoint_path(session.session_id))

    async def test_play_resume_rehydrates_the_checkpointed_session(self):
        sid = "chat-resume-test"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                await a._step_setup()
                a._checkpoint()

                captured = {}

                async def fake_repl(session):
                    captured["session"] = session
                    return 0

                with patch.object(chat_game, "_repl", new=fake_repl):
                    result = await chat_game.play(None, None, True, "zh-CN",
                                                  resume_game_id=sid)
                self.assertEqual(result, 0)
                session = captured["session"]
                self.assertEqual(session.session_id, sid)
                self.assertEqual(session._step, a._step)
                self.assertEqual(session.engine.night_count, a.engine.night_count)
                self.assertEqual(session.checkpoint_path, cp.checkpoint_path(sid))
            finally:
                cp.CHECKPOINTS_DIR = old

    async def test_play_resume_rejects_an_unknown_game_id(self):
        result = await chat_game.play(None, None, True, "zh-CN",
                                      resume_game_id="chat-no-such-game")
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
