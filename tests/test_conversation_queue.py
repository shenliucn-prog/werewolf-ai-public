"""Question-queue extraction: old storage, bounded order, durable consumption."""
import asyncio
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from werewolf_web import checkpoint as cp
from werewolf_web.ai.brain import Speech
from werewolf_web.conversation import QuestionQueue
from werewolf_web.session import GameSession


class QuestionQueueTest(unittest.TestCase):
    def test_fifo_and_duplicate_pair_without_overwriting_other_asker(self):
        queue = QuestionQueue()
        self.assertTrue(queue.enqueue("target", "A"))
        self.assertFalse(queue.enqueue("target", "A"))
        self.assertTrue(queue.enqueue("target", "B"))
        self.assertEqual(queue.window({}), [["target", "A"], ["target", "B"]])

    def test_finish_is_idempotent_and_skip_spends_one_opportunity(self):
        queue = QuestionQueue([["target", "A"]])
        state = {}
        pair = queue.window(state)[0]
        self.assertTrue(queue.begin(pair, state))
        self.assertFalse(queue.begin(pair, state))
        self.assertTrue(queue.finish(pair, state))
        self.assertFalse(queue.finish(pair, state))
        self.assertEqual(queue.answered, 1)
        self.assertEqual(queue.pending, [])
        queue.close_window(state)

    def test_late_questions_do_not_extend_or_reopen_closed_window(self):
        queue = QuestionQueue([["target", "A"]])
        state = {}
        pair = queue.window(state)[0]
        queue.begin(pair, state)
        queue.finish(pair, state)
        queue.enqueue("other", "B")
        self.assertEqual(queue.window(state), [])
        queue.close_window(state)
        self.assertEqual(queue.window(state), [])
        self.assertEqual(queue.pending, [["other", "B"]])
        queue.reset(state)
        self.assertEqual(queue.pending, [])
        self.assertNotIn("question_window", state)

    def test_no_early_consumption_and_only_one_active_question(self):
        queue = QuestionQueue([["one", "A"], ["two", "B"]])
        state = {}
        with self.assertRaises(ValueError):
            queue.finish(["one", "A"], state)
        self.assertEqual(queue.answered, 0)
        queue.begin(["one", "A"], state)
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            queue.begin(["two", "B"], state)
        self.assertEqual(state, before)

    def test_excess_and_unavailable_questions_do_not_spend_quota(self):
        queue = QuestionQueue([["one", "A"], ["two", "B"], ["three", "C"]])
        state = {}
        for pair in queue.window(state)[:2]:
            queue.begin(pair, state)
            queue.finish(pair, state)
        with self.assertRaises(ValueError):
            queue.begin(["three", "C"], state)
        queue.finish(["three", "C"], state, consume=False)
        self.assertEqual(queue.answered, 2)
        self.assertEqual(queue.pending, [])

    def test_legacy_dict_migrates_and_snapshots_are_detached(self):
        original = {"pending_questions": {"target": "A"}, "questions_answered": 1}
        queue = QuestionQueue.from_snapshot(original)
        original["pending_questions"]["target"] = "changed"
        exported = queue.snapshot_fields()
        exported["pending_questions"][0][0] = "changed"
        self.assertEqual(queue.pending, [["target", "A"]])


class QuestionQueueSessionTest(unittest.IsolatedAsyncioTestCase):
    async def make_session(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        session = GameSession("classic", {"enabled": False}, session_id="queue-test", seed=7)
        session.memory_dir = directory.name
        await session._step_setup()
        return session

    async def test_invalid_queue_restore_is_rejected_without_any_mutation(self):
        session = await self.make_session()
        before = session.snapshot()
        cases = [
            {"pending_questions": "bad"},
            {"pending_questions": [["A"]]},
            {"pending_questions": [["A", "B"], ["A", "B"]]},
            {"questions_answered": -1}, {"questions_answered": True},
            {"questions_answered": 3},
            {"step_state": {"answering_question": ["A", "B"]}},
            {"step_state": {"question_window": [["A", "B"]]}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                broken = deepcopy(before)
                broken["session_id"] = "must-not-apply"
                broken.update(changes)
                with self.assertRaises(ValueError):
                    session.restore(broken)
                self.assertEqual(session.snapshot(), before)

    async def test_dead_target_removed_without_request_or_quota(self):
        session = await self.make_session()
        target = next(iter(session.agents.values()))
        target.seat.alive = False
        session.questions.enqueue(target.name, session.engine.player_seat().name)
        session._npc_call = Mock(side_effect=AssertionError("must not ask dead target"))
        await session._answer_table_questions()
        self.assertEqual(session.questions.pending, [])
        self.assertEqual(session.questions.answered, 0)

    async def test_reply_created_question_stays_deferred_after_disk_crash(self):
        class Crash(BaseException):
            pass
        session = await self.make_session()
        target, later = list(session.agents.values())[:2]
        asker = session.engine.player_seat().name
        session.questions.enqueue(target.name, asker)
        target.brain.answer_check_question = Mock(return_value=Speech(text="答复并追问", question_to=later.name))
        with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
            session.checkpoint_path = cp.checkpoint_path(session.session_id)
            flush = session._flush_publish
            def crash():
                if session._events[-1].get("text") == "答复并追问":
                    raise Crash()
                flush()
            with patch.object(session, "_flush_publish", crash), self.assertRaises(Crash):
                await session._answer_table_questions()
            restored = GameSession("classic", {"enabled": False})
            restored.restore(cp.load_checkpoint(session.checkpoint_path))
            self.assertEqual(restored._step_state["question_window"], [])
            restored._npc_call = Mock(side_effect=AssertionError("must not expand restored window"))
            for agent in restored.agents.values():
                agent.brain.answer_check_question = Mock(side_effect=AssertionError("must not expand restored window"))
            await restored._answer_table_questions()
            self.assertEqual(restored.questions.pending, [[later.name, target.name]])
            self.assertEqual(restored.questions.answered, 1)
            self.assertEqual(len([e for e in restored.recovery_view()["public_events"]
                                  if e.get("text") == "答复并追问"]), 1)
            # Checkpoint after another day-wrap action still preserves closure.
            again = GameSession("classic", {"enabled": False})
            again.restore(restored.snapshot())
            self.assertEqual(again.questions.window(again._step_state), [])

    async def test_three_queued_questions_keep_two_opportunity_limit(self):
        session = await self.make_session()
        targets = list(session.agents.values())[:3]
        for agent in targets:
            session.questions.enqueue(agent.name, session.engine.player_seat().name)
            agent.brain.answer_check_question = Mock(return_value=Speech(text="回答"))
        await session._answer_table_questions()
        self.assertEqual([a.brain.answer_check_question.call_count for a in targets], [1, 1, 0])
        self.assertEqual(session.questions.answered, 2)
        self.assertEqual(session.questions.pending, [])
