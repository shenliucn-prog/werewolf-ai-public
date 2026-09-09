"""Durable interaction tests through the production speech-step dispatcher.

One-speaker phase fixtures isolate this interaction; they are not full matches.
All model responses are deterministic doubles, never external requests.
"""
import asyncio
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import Mock, patch

from werewolf_web import checkpoint as cp
from werewolf_web.ai.brain import Speech
from werewolf_web.conversation import FloorPolicy, InterruptionIntent
from werewolf_web.session import GameSession
from tests.test_observation_boundary import FakeRuntime


class Crash(BaseException):
    pass


class TalkRuntime(FakeRuntime):
    def complete(self, request, schema):
        text = {"public speech": "Main", "brief public interruption": "Interrupt",
                "brief answer to public question": "Reply"}[request["task"]]
        return {"text": text, "claim": "seer" if text == "Main" else None,
                "accuse": None, "defend": None, "question_to": None}


class FloorPolicyTest(unittest.TestCase):
    def test_choice_is_score_then_seat_not_arrival(self):
        candidates = [(0.8, 9, "a"), (0.8, 2, "b"), (0.4, 1, "c")]
        self.assertEqual(FloorPolicy.choose(candidates), (0.8, 2, "b"))
        self.assertEqual(FloorPolicy.choose(list(reversed(candidates))), (0.8, 2, "b"))
        self.assertIsNone(FloorPolicy.choose([]))

    def test_host_reason_priority_and_caps_unchanged(self):
        self.assertEqual(FloorPolicy.EXTRA_LIMIT, 3)
        self.assertEqual(FloorPolicy.SPEAKER_LIMIT, 2)
        for turns in range(1, 5):
            for extra in range(9):
                for speaker in range(4):
                    for repeated in (True, False):
                        expected = ("space" if extra >= 7 else "pair" if repeated or turns >= 3
                                    else "speaker" if speaker >= 2 else None)
                        self.assertEqual(FloorPolicy.close_reason(topic_turns=turns,
                            extra_turns=extra, speaker_extra_turns=speaker, repeated_pair=repeated), expected)


class InterruptionIntentTest(unittest.IsolatedAsyncioTestCase):
    async def make_session(self, human=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        session = GameSession("classic", planner=TalkRuntime(), seed=7, session_id="talk-test")
        session.memory_dir = directory.name
        await session._step_setup()
        session.engine.start_night()
        session.engine.start_day()
        source = session.engine.player_seat() if human else next(iter(session.agents.values())).seat
        self.configure(session, source.player_id)
        session._step = "speeches"
        return session, source.player_id

    def configure(self, session, source_id):
        source = next(s for s in session.engine.seats.values() if s.player_id == source_id)
        session.engine.speech_order = lambda: [source.pos]
        chosen = min((a for a in session.agents.values() if a.seat.player_id != source_id), key=lambda a: a.seat.pos)
        for agent in session.agents.values():
            agent.table_interruption_interest = Mock(return_value=1.0 if agent is chosen else 0.0)
        async def stop_after_phase():
            session.finished = True
            session._step = None
        session._step_day_wrap = stop_after_phase

    def outcome(self, session):
        return ([row["event"] for row in session.public_record.entries],
                session.planner.calls, session._table_extra_turns,
                session._table_extra_by_name, session._table_pairs,
                session._table_cooldown, session.engine.rng.getstate())

    async def test_crash_matrix_matches_uninterrupted_phase(self):
        baseline, source_id = await self.make_session()
        await baseline._play()
        expected = self.outcome(baseline)
        self.assertEqual(baseline.planner.calls, 3)
        self.assertEqual([e["text"] for e in expected[0] if e["type"] == "speech"], ["Main", "Interrupt", "Reply"])
        # Checkpoints at each boundary survive a simulated process loss (no
        # game-task finally); fresh session resumes via the actual _play loop.
        for boundary in ("main", "selected", "decision", "interrupt", "reply", "closed"):
            with self.subTest(boundary=boundary):
                session, source_id = await self.make_session()
                with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
                    session.checkpoint_path = cp.checkpoint_path(session.session_id)
                    checkpoint = session._checkpoint
                    def crash_at_boundary():
                        checkpoint()
                        intent = session._step_state.get("table_talk", {})
                        stage = intent.get("stage")
                        last = session._events[-1]
                        hit = ((boundary == "main" and stage == "select" and last.get("text") == "Main") or
                               (boundary == "selected" and stage == "interrupt" and session.planner.calls == 1) or
                               (boundary == "decision" and stage == "interrupt" and session.decision_log[-1]["committed"]
                                and "table-interrupt:" in session.decision_log[-1]["slot"]) or
                               (boundary == "interrupt" and stage == "reply_gate") or
                               (boundary == "reply" and stage == "close") or
                               (boundary == "closed" and not intent and last.get("type") == "narration"
                                and session._table_extra_turns == 2))
                        if hit:
                            raise Crash()
                    with patch.object(session, "_checkpoint", crash_at_boundary), self.assertRaises(Crash):
                        await session._play()
                    restored = GameSession("classic", planner=TalkRuntime())
                    restored.restore(cp.load_checkpoint(session.checkpoint_path))
                    self.configure(restored, source_id)
                    if boundary != "main":
                        for agent in restored.agents.values():
                            agent.table_interruption_interest = Mock(side_effect=AssertionError("must not select again"))
                    await restored._play()
                    self.assertEqual(self.outcome(restored), expected)
                    self.assertNotIn("table_talk", restored._step_state)

    async def test_human_response_keeps_request_id_and_no_repeated_interrupt(self):
        session, source_id = await self.make_session(human=True)
        with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
            session.checkpoint_path = cp.checkpoint_path(session.session_id)
            task = asyncio.create_task(session._play())
            try:
                while True:
                    event = await asyncio.wait_for(session.event_q.get(), 3)
                    if event.get("kind") == "speech":
                        session.submit({"text": "我是预言家"}, request_id=event["request_id"])
                    if event.get("kind") == "table_reply":
                        original_request = event
                        break
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            restored = GameSession("classic", planner=TalkRuntime())
            restored.restore(cp.load_checkpoint(session.checkpoint_path))
            self.configure(restored, source_id)
            self.assertEqual(restored.recovery_view()["pending"]["request_id"], original_request["request_id"])
            task = asyncio.create_task(restored._play())
            try:
                while True:
                    event = await asyncio.wait_for(restored.event_q.get(), 3)
                    if event.get("kind") == "table_reply":
                        self.assertEqual(event["request_id"], original_request["request_id"])
                        restored.submit({"text": "我的回应"}, request_id=event["request_id"])
                        break
                await asyncio.wait_for(task, 3)
            finally:
                if not task.done():
                    task.cancel()
            self.assertEqual(restored.planner.calls, 1)
            texts = [r["event"].get("text") for r in restored.public_record.entries]
            self.assertEqual(texts.count("Interrupt"), 1)
            self.assertEqual(texts.count("我的回应"), 1)
            self.assertEqual(restored._table_extra_turns, 2)

    async def test_corrupt_intent_restore_rejects_without_mutation(self):
        session, source_id = await self.make_session()
        source = next(s for s in session.engine.seats.values() if s.player_id == source_id)
        speech = Speech(text="Main", claim="seer")
        session.emit({"type": "speech", "seat": source.pos, "name": source.name, "text": "Main"})
        session._start_table_intent(source, speech, session._event_no)
        before = session.snapshot()
        for change in ({"version": True}, {"stage": "invented"}, {"source_id": "unknown"},
                       {"source_event_no": 1}, {"interruption_event_no": 999},
                       {"stage": "interrupt", "interrupter_id": session.engine.player_seat().player_id},
                       {"source_speech": asdict(Speech(text="different text"))}):
            with self.subTest(change=change):
                broken = deepcopy(before)
                broken["step_state"]["table_talk"].update(change)
                with self.assertRaises(ValueError):
                    session.restore(broken)
                self.assertEqual(session.snapshot(), before)

    async def test_cooldown_and_question_keep_model_silent(self):
        for cooldown, question in ((True, None), (False, "someone")):
            session, source_id = await self.make_session()
            source = next(s for s in session.engine.seats.values() if s.player_id == source_id)
            session._table_cooldown = cooldown
            await session._maybe_table_talk(source, Speech(text="Main", question_to=question))
            self.assertEqual(session.planner.calls, 0)
            self.assertFalse(session._table_cooldown)
            self.assertNotIn("table_talk", session._step_state)

    async def test_repeated_pair_is_closed_without_model_call(self):
        session, source_id = await self.make_session()
        source = next(s for s in session.engine.seats.values() if s.player_id == source_id)
        chosen = min((a for a in session.agents.values() if a.seat.player_id != source_id), key=lambda a: a.seat.pos)
        session._table_pairs.add(frozenset((source.name, chosen.name)))
        await session._maybe_table_talk(source, Speech(text="Main", claim="seer"))
        self.assertEqual(session.planner.calls, 0)
        self.assertIn("两个人", session.public_record.entries[-1]["event"]["text"])

    async def test_new_intent_cannot_replay_previous_same_actor_response(self):
        session, source_id = await self.make_session()
        source = next(s for s in session.engine.seats.values() if s.player_id == source_id)
        session._current_step = "speeches"
        speech = Speech(text="Main", claim="seer")
        for iteration in range(2):
            session.emit({"type": "speech", "seat": source.pos, "name": source.name, "text": speech.text})
            session._start_table_intent(source, speech, session._event_no)
            if iteration:
                # Isolate decision-slot identity from the existing discussion
                # cap/cooldown: old committed slots remain in the replay pass.
                session._table_extra_turns = 0
                session._table_extra_by_name = {}
                session._table_pairs = set()
                session._table_cooldown = False
                session._resume_step = "speeches"
                session._replay_committed = list(session.decision_log)
                session._replay_cursor = 0
            await session._continue_table_intent()
        self.assertEqual(session.planner.calls, 4)
        self.assertEqual(len({d["slot"] for d in session.decision_log}), 4)

    async def test_human_can_skip_short_reply_without_extra_call(self):
        session, source_id = await self.make_session(human=True)
        source = session.engine.player_seat()
        task = asyncio.create_task(session._maybe_table_talk(source, Speech(text="Main", claim="seer")))
        try:
            while True:
                event = await asyncio.wait_for(session.event_q.get(), 3)
                if event.get("kind") == "table_reply":
                    session.submit({"text": ""}, request_id=event["request_id"])
                    break
            await asyncio.wait_for(task, 3)
        finally:
            if not task.done():
                task.cancel()
        self.assertEqual(session.planner.calls, 1)
        self.assertEqual(session._table_extra_turns, 1)
        self.assertNotIn("table_talk", session._step_state)
        self.assertEqual(session.public_record.entries[-1]["event"]["text"], "主持人：继续按顺序发言。")
