"""Decision-log semantics: decision_no dedup key, attempt_no budget accounting.

These tests cover the §4.5 contract before checkpointing is layered on top:
one logical decision slot (decision_no) may span several physical invocations
(attempt_no), every attempt consumes budget, and a retry is a new attempt — not
a replay of the old one.
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from werewolf_web.ai.decision_runtime import ModelTurnError
from werewolf_web.run import GameSession


class DecisionLogTest(unittest.IsolatedAsyncioTestCase):
    def make_session(self, planner=None, **kwargs):
        return GameSession("classic", {"enabled": False}, planner=planner, **kwargs)

    async def drain_until_request(self, session, kind):
        while True:
            event = await asyncio.wait_for(session.event_q.get(), 2)
            if event["type"] == "request":
                return event

    def test_open_decision_is_monotonic_with_independent_attempts(self):
        session = self.make_session()
        first = session._open_decision("night:seer")
        self.assertEqual(first["decision_no"], 1)
        self.assertEqual(first["attempts"], [])
        self.assertFalse(first["committed"])
        session._begin_attempt(first, 5)
        session._end_attempt(first, 6, "accepted")
        second = session._open_decision("night:witch")
        self.assertEqual(second["decision_no"], 2)
        self.assertEqual(len(first["attempts"]), 1)
        self.assertEqual(first["attempts"][0],
                         {"attempt_no": 1, "calls_before": 5, "calls_after": 6, "outcome": "accepted"})
        self.assertEqual([e["decision_no"] for e in session.decision_log], [1, 2])

    async def test_model_success_consumes_one_call_and_records_result(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)

        def succeed():
            planner.calls += 1
            return {"target": 3}

        result = await session._npc_call(Mock(side_effect=succeed))
        self.assertEqual(result, {"target": 3})
        self.assertEqual(planner.calls, 1)
        self.assertEqual(len(session.decision_log), 1)
        entry = session.decision_log[0]
        self.assertEqual(entry["decision_no"], 1)
        self.assertEqual(entry["result"], {"target": 3})
        self.assertEqual(entry["attempts"],
                         [{"attempt_no": 1, "calls_before": 0, "calls_after": 1, "outcome": "accepted"}])

    async def test_retry_is_new_attempt_same_decision_and_consumes_budget(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)

        def flaky():
            planner.calls += 1
            if planner.calls == 1:
                raise ModelTurnError("first call failed")
            return {"target": 3}

        task = asyncio.create_task(session._npc_call(Mock(side_effect=flaky)))
        try:
            event = await self.drain_until_request(session, "model_retry")
            self.assertEqual(event["kind"], "model_retry")
            self.assertTrue(session.submit({"retry": True}))
            self.assertEqual(await asyncio.wait_for(task, 2), {"target": 3})
        finally:
            task.cancel()

        # The model decision is one slot; the human retry prompt is a second.
        self.assertEqual([e["decision_no"] for e in session.decision_log], [1, 2])
        model_entry = session.decision_log[0]
        self.assertEqual(model_entry["slot"], "None:d0:?:call")  # bare Mock call has no agent
        self.assertEqual([a["attempt_no"] for a in model_entry["attempts"]], [1, 2])
        self.assertEqual(model_entry["attempts"][0]["outcome"], "error")
        self.assertEqual(model_entry["attempts"][1]["outcome"], "accepted")
        self.assertEqual(model_entry["attempts"][0]["calls_after"], 1)
        self.assertEqual(model_entry["attempts"][1]["calls_after"], 2)
        self.assertEqual(model_entry["result"], {"target": 3})
        # The human retry is a separate decision and consumes no model budget.
        human_retry = session.decision_log[1]
        self.assertEqual(human_retry["slot"], "human:None:d0:model_retry")
        self.assertEqual(human_retry["attempts"][0]["calls_before"], 1)
        self.assertEqual(human_retry["attempts"][0]["calls_after"], 1)
        self.assertEqual(planner.calls, 2)

    async def test_budget_exhaustion_does_not_consume_a_call(self):
        planner = SimpleNamespace(verified=True, calls=0)

        def exhausted():
            raise ModelTurnError("budget exhausted")

        session = self.make_session(planner=planner)
        task = asyncio.create_task(session._npc_call(Mock(side_effect=exhausted)))
        try:
            await self.drain_until_request(session, "model_retry")
            session.submit({"retry": False})
            with self.assertRaises(ModelTurnError):
                await asyncio.wait_for(task, 2)
        finally:
            task.cancel()

        model_entry = session.decision_log[0]
        self.assertEqual(model_entry["attempts"][0]["calls_before"], 0)
        self.assertEqual(model_entry["attempts"][0]["calls_after"], 0)
        self.assertEqual(model_entry["attempts"][0]["outcome"], "error")
        self.assertIsNone(model_entry["result"])

    async def test_legacy_mode_opens_no_model_decision(self):
        session = self.make_session()  # planner is None
        call = Mock(return_value={"target": 1})
        result = await session._npc_call(call)
        self.assertEqual(result, {"target": 1})
        self.assertEqual(session.decision_log, [])

    async def test_human_decision_is_logged_without_budget(self):
        session = self.make_session()
        session._current_step = "speeches"
        task = asyncio.create_task(session.ask_player("speech", {"phase": "day 1"}))
        try:
            event = await self.drain_until_request(session, "speech")
            self.assertEqual(event["data"]["phase"], "day 1")
            self.assertTrue(session.submit({"text": "我先听大家发言。"}))
            resp = await asyncio.wait_for(task, 2)
            self.assertEqual(resp["text"], "我先听大家发言。")
        finally:
            task.cancel()

        self.assertEqual(len(session.decision_log), 1)
        entry = session.decision_log[0]
        self.assertEqual(entry["decision_no"], 1)
        self.assertEqual(entry["slot"], "human:speeches:d0:speech")
        self.assertEqual(entry["result"], {"text": "我先听大家发言。"})
        self.assertEqual(entry["attempts"],
                         [{"attempt_no": 1, "calls_before": 0, "calls_after": 0, "outcome": "accepted"}])

    async def test_model_and_human_decisions_share_one_monotonic_sequence(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "vote"

        def answer():
            planner.calls += 1
            return {"target": 4}

        npc = asyncio.create_task(session._npc_call(Mock(side_effect=answer)))
        await asyncio.wait_for(npc, 2)

        human = asyncio.create_task(session.ask_player("vote", {"candidates": [{"pos": 4}]}))
        try:
            await self.drain_until_request(session, "vote")
            self.assertTrue(session.submit({"target": 4}))
            await asyncio.wait_for(human, 2)
        finally:
            human.cancel()

        self.assertEqual([e["decision_no"] for e in session.decision_log], [1, 2])
        self.assertEqual(session.decision_log[0]["result"], {"target": 4})
        self.assertEqual(session.decision_log[1]["result"], {"target": 4})


if __name__ == "__main__":
    unittest.main()
