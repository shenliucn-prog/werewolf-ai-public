"""Attempt lifecycle + recoverable fault (CAMPAIGN_DESIGN §3.3 / milestone 2).

Only normal endgame and explicit abandon end the attempt.  A model/internal
fault pauses the game — ``faulted=True``, ``finished=False`` — preserving the
resume position and the pending action; it must never settle.  Repeated restore
must not re-finish or re-settle.
"""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from werewolf_web import campaign
from werewolf_web.ai.decision_runtime import ModelTurnError
from werewolf_web.checkpoint import load_checkpoint
from werewolf_web.run import GameSession


class AttemptTransitionTest(unittest.TestCase):
    def test_transition_table_is_valid(self):
        self.assertEqual(campaign.validate_transitions(), [])

    def test_terminal_states_have_no_outgoing_edges(self):
        for terminal in (campaign.ABANDONED, campaign.ENDED):
            self.assertEqual(campaign.ATTEMPT_TRANSITIONS[terminal], set())

    def test_faulted_is_not_terminal(self):
        # faulted -> in_progress (fix + resume) and -> abandoned are the only
        # legal exits; it must never be a direct settling edge.
        self.assertIn(campaign.IN_PROGRESS, campaign.ATTEMPT_TRANSITIONS[campaign.FAULTED])
        self.assertNotIn(campaign.FAULTED, campaign.ATTEMPT_TRANSITIONS[campaign.ENDED])


class SessionFaultTest(unittest.IsolatedAsyncioTestCase):
    def make_session(self, **kwargs):
        return GameSession("classic", {"enabled": False},
                           planner=SimpleNamespace(
                               verified=True, calls=0,
                               public_status=lambda: {"mode": "model_decisions",
                                                      "backend": "api"}),
                           **kwargs)

    async def test_model_fault_is_recoverable_not_finished(self):
        session = self.make_session()
        session.pending = {"kind": "model_retry", "data": {}}

        async def boom():
            raise ModelTurnError("model down")
        session._play = boom

        await session._game_task()

        self.assertTrue(session.faulted)
        self.assertFalse(session.finished)
        self.assertEqual(session.terminal_state, "faulted")
        # The pending action is preserved for the resume (not cleared as it was
        # when the finalizer unconditionally marked the game finished).
        self.assertEqual(session.pending, {"kind": "model_retry", "data": {}})

    async def test_internal_error_is_recoverable_not_finished(self):
        session = self.make_session()

        async def boom():
            raise RuntimeError("unexpected bug")
        session._play = boom

        await session._game_task()

        self.assertTrue(session.faulted)
        self.assertFalse(session.finished)
        self.assertEqual(session.terminal_state, "faulted")

    async def test_fault_preserves_resume_position(self):
        session = self.make_session(session_id="fault-position",
                                    seed=7, locale="zh-CN", player_role="civilian")
        await session._step_setup()
        session._step = "night"
        session._current_step = "night"

        async def boom():
            raise ModelTurnError("model down")
        session._play = boom

        await session._game_task()

        self.assertEqual(session._step, "night")          # resume position kept
        self.assertEqual(session._current_step, "night")
        self.assertFalse(session.finished)

    async def test_normal_endgame_clears_pending_and_is_ended(self):
        session = self.make_session()
        session.pending = {"kind": "vote", "data": {}}

        async def finish():
            session.finished = True
        session._play = finish

        await session._game_task()

        self.assertTrue(session.finished)
        self.assertFalse(session.faulted)
        self.assertIsNone(session.pending)
        self.assertEqual(session.terminal_state, "ended")

    def test_abandon_is_terminal(self):
        session = self.make_session()
        session.abandon()
        self.assertTrue(session.finished)
        self.assertTrue(session._abandoned)
        self.assertEqual(session.terminal_state, "abandoned")

    async def test_retry_in_same_process_clears_fault(self):
        """Shawn's repro: after a same-process retry ends the game, ``faulted``
        stayed True (it was only reset in ``restore()``), so ``terminal_state``
        was still "faulted" even though ``finished=True``.  Re-entering the game
        loop must perform the fault -> in_progress transition."""
        session = self.make_session()

        async def boom():
            raise ModelTurnError("down")
        async def finish():
            session.finished = True

        session._play = boom
        await session._game_task()
        self.assertEqual(session.terminal_state, "faulted")

        # Same session object, no restore(): the retry re-enters _game_task.
        session._play = finish
        await session._game_task()
        self.assertFalse(session.faulted)
        self.assertTrue(session.finished)
        self.assertEqual(session.terminal_state, "ended")

    async def test_review_failure_keeps_game_finished(self):
        """Shawn's repro: review ran before the endgame commit, so a review
        failure left finished=False with _current_step="endgame" and _step=None,
        and the resume executor refused to re-dispatch "endgame" — the game was
        stuck "in_progress".  The endgame result must commit first; the review is
        a separate, retryable step after it."""
        session = GameSession("classic", {"enabled": False},
                              session_id="endgame-review-fault",
                              seed=7, locale="zh-CN", player_role="civilian")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            await session._step_setup()
            session.engine.winner = "wolf"
            session.engine.end_reason = "测试终局"

            with patch.object(session.host, "review", side_effect=ModelTurnError("review down")):
                await session._step_endgame()

            self.assertTrue(session.finished)
            self.assertIsNone(session._step)
            self.assertEqual(session.terminal_state, "ended")

            on_disk = load_checkpoint(session.checkpoint_path)
            self.assertTrue(on_disk["finished"])
            types = [e["type"] for e in on_disk["events"]]
            self.assertIn("gameover", types)
            self.assertIn("review", types)          # fallback review emitted


class FaultTransienceTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_resets_the_transient_fault_flag(self):
        a = GameSession("classic", {"enabled": False}, session_id="fault-reset",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()
        a.faulted = True           # simulate a fault in the live session
        snapshot = a.snapshot()
        self.assertNotIn("faulted", snapshot)   # transient, never snapshotted

        b = GameSession("classic", {"enabled": False}, session_id="fault-reset",
                        seed=99, locale="zh-CN", player_role="civilian")
        b.restore(snapshot)
        self.assertFalse(b.faulted)             # a restored game starts running again


if __name__ == "__main__":
    unittest.main()
