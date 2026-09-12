"""Phase-3 regression tests: the human player answers (or skips) public
clarifications, with no duplicate post, no model budget spent on a skip, and no
silent overwrite of distinct questions to one target (no model, no key)."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import checkpoint as cp
from werewolf_web.run import GameSession
from werewolf_web.ai.brain import Speech


class HumanClarificationTest(unittest.IsolatedAsyncioTestCase):
    async def _drain_request(self, session):
        while True:
            event = await asyncio.wait_for(session.event_q.get(), 2)
            if event["type"] == "request":
                return event

    def test_human_question_is_queued(self):
        session = GameSession("classic", {"enabled": False})
        session.engine.setup()
        player = session.engine.player_seat()
        asker_seat = next(s for s in session.engine.seats.values() if not s.is_player)
        session._broadcast_speech(asker_seat, Speech(text="问你", question_to=player.name))
        self.assertIn([player.name, asker_seat.name], session._pending_questions)

    def test_multiple_questions_same_target_not_overwritten(self):
        session = GameSession("classic", {"enabled": False})
        session.engine.setup()
        player = session.engine.player_seat()
        askers = [s for s in session.engine.seats.values() if not s.is_player][:2]
        for seat in askers:
            session._broadcast_speech(seat, Speech(text="问你", question_to=player.name))
        pairs = [p for p in session._pending_questions if p[0] == player.name]
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p[1] for p in pairs}, {s.name for s in askers})

    async def test_human_answer_is_published_once(self):
        session = GameSession("classic", {"enabled": False}, session_id="hc-answer", seed=7)
        await session._step_setup()
        player = session.engine.player_seat()
        asker = next(iter(session.agents))
        session._pending_questions = [[player.name, asker]]
        task = asyncio.create_task(session._answer_table_questions())
        event = await self._drain_request(session)
        self.assertEqual(event["kind"], "table_answer")
        self.assertEqual(event["data"]["from"], asker)
        self.assertTrue(session.submit({"answer": "我来回答"}))
        await asyncio.wait_for(task, 2)
        self.assertEqual(session._pending_questions, [])
        self.assertEqual(session._questions_answered, 1)
        answers = [speech.text for _name, speech in session.speech_events]
        self.assertEqual(answers, ["我来回答"])

    async def test_human_skip_spends_opportunity_without_speech(self):
        session = GameSession("classic", {"enabled": False}, session_id="hc-skip", seed=7)
        await session._step_setup()
        player = session.engine.player_seat()
        asker = next(iter(session.agents))
        session._pending_questions = [[player.name, asker]]
        task = asyncio.create_task(session._answer_table_questions())
        event = await self._drain_request(session)
        self.assertEqual(event["kind"], "table_answer")
        self.assertTrue(session.submit({"skip": True}))
        await asyncio.wait_for(task, 2)
        self.assertEqual(session._pending_questions, [])
        self.assertEqual(session._questions_answered, 1)   # opportunity spent
        self.assertEqual(len(session.speech_events), 0)    # no speech published

    def test_duplicate_submit_is_a_noop(self):
        session = GameSession("classic", {"enabled": False})
        session.pending = {"kind": "table_answer", "data": {"from": "asker"}}
        self.assertTrue(session.submit({"answer": "第一次"}))
        self.assertFalse(session.submit({"answer": "第二次"}))
        self.assertFalse(session.submit({"skip": True}))


class HumanClarificationRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_pending_question_survives_interruption(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
            path = cp.checkpoint_path("hc-pending")
            session = GameSession("classic", {"enabled": False}, session_id="hc-pending", seed=7, checkpoint_path=path)
            await session._step_setup()
            pair = [session.engine.player_seat().name, next(iter(session.agents))]
            session._pending_questions = [pair]
            task = asyncio.create_task(session._answer_table_questions())
            await self._drain_request(session)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            restored = GameSession("classic", {"enabled": False}, session_id="hc-pending", checkpoint_path=path)
            restored.restore(cp.load_checkpoint(path))
            self.assertEqual(restored.recovery_view()["pending"]["kind"], "table_answer")
            self.assertEqual(restored._pending_questions, [pair])
            self.assertEqual(restored._questions_answered, 0)
            task = asyncio.create_task(restored._answer_table_questions())
            await self._drain_request(restored)
            self.assertTrue(restored.submit({"answer": "恢复后的回答"}))
            await asyncio.wait_for(task, 2)
            self.assertEqual(restored._questions_answered, 1)
            self.assertEqual([s.text for _, s in restored.speech_events], ["恢复后的回答"])

    async def test_committed_answer_replays_after_crash_before_publish(self):
        class Crash(BaseException):
            pass
        with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
            path = cp.checkpoint_path("hc-before-publish")
            session = GameSession("classic", {"enabled": False}, session_id="hc-before-publish", seed=7, checkpoint_path=path)
            await session._step_setup()
            session._pending_questions = [[session.engine.player_seat().name, next(iter(session.agents))]]
            flush = session._flush_publish
            def crash_before_answer_publish():
                if session._events[-1].get("text") == "已落盘的回答":
                    raise Crash()
                flush()
            with patch.object(session, "_flush_publish", crash_before_answer_publish):
                task = asyncio.create_task(session._answer_table_questions())
                await self._drain_request(session)
                session.submit({"answer": "已落盘的回答"})
                with self.assertRaises(Crash):
                    await task
            while not session.event_q.empty():
                self.assertNotEqual(session.event_q.get_nowait().get("text"), "已落盘的回答")
            restored = GameSession("classic", {"enabled": False}, session_id="hc-before-publish")
            restored.restore(cp.load_checkpoint(path))
            await restored._answer_table_questions()
            self.assertEqual(restored._pending_questions, [])
            self.assertEqual(restored._questions_answered, 1)
            events = restored.recovery_view()["public_events"]
            answers = [e for e in events if e.get("text") == "已落盘的回答"]
            self.assertEqual(len(answers), 1)
            after = restored.recovery_view(answers[0]["event_no"])["public_events"]
            self.assertEqual([event["type"] for event in after], ["discussion_closed"])

    async def _drain_request(self, session):
        while True:
            event = await asyncio.wait_for(session.event_q.get(), 2)
            if event["type"] == "request":
                return event

    async def test_answer_is_durable_and_not_reposted_after_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            try:
                session = GameSession("classic", {"enabled": False},
                                      session_id="hc-restore", seed=7,
                                      checkpoint_path=cp.checkpoint_path("hc-restore"))
                await session._step_setup()
                player = session.engine.player_seat()
                asker = next(iter(session.agents))
                session._pending_questions = [[player.name, asker]]
                task = asyncio.create_task(session._answer_table_questions())
                await self._drain_request(session)
                self.assertTrue(session.submit({"answer": "我来回答"}))
                await asyncio.wait_for(task, 2)

                # Real disk recovery: rehydrate a fresh session from the save.
                payload = cp.load_checkpoint(session.checkpoint_path)
                restored = GameSession("classic", {"enabled": False},
                                       session_id="hc-restore", seed=7)
                restored.restore(payload)

                # The answer is durable; the clarification window must not
                # re-ask or re-post it.
                self.assertEqual(restored._pending_questions, [])
                self.assertEqual(restored._questions_answered, 1)
                await restored._answer_table_questions()
                answers = [speech.text for _name, speech in restored.speech_events]
                self.assertEqual(answers, ["我来回答"])
            finally:
                cp.CHECKPOINTS_DIR = old


if __name__ == "__main__":
    unittest.main()
