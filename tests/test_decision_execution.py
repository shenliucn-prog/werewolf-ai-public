"""Decision service gates using a port without any game engine or transport."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

from werewolf_web.decision_execution import execute
from werewolf_web.ai.decision_runtime import ModelTurnError


class DecisionExecutionTest(unittest.IsolatedAsyncioTestCase):
    def port(self):
        trace = []
        planner = SimpleNamespace(calls=0, backend="api", model="test", effort="medium")
        def reserve():
            planner.calls += 1
            trace.append("reserve")
        planner.reserve = reserve
        decision = {"decision_no": 1, "attempts": [], "committed": False}
        def begin(d, calls):
            d["attempts"].append({"before": calls})
        def end(d, calls, outcome):
            d["attempts"][-1].update(after=calls, outcome=outcome)
        port = SimpleNamespace(
            planner=planner, session_id="service-test", _current_step="vote",
            _slot_instance=lambda: "d1", _replay_decision=lambda slot: None,
            _open_decision=lambda slot: decision, _begin_attempt=begin,
            _end_attempt=end, _checkpoint=lambda: trace.append(
                ("save", planner.calls, decision["committed"])),
            perf_recorder=SimpleNamespace(decision=Mock()), emit=Mock(),
            ask_player=AsyncMock(return_value={"retry": True}))
        return port, trace, decision

    async def test_request_between_reserved_save_and_result_commit(self):
        port, trace, decision = self.port()
        def call():
            trace.append("request")
            return {"target": 3}
        self.assertEqual(await execute(port, "en", call), {"target": 3})
        self.assertEqual(trace, ["reserve", ("save", 1, False), "request", ("save", 1, True)])
        self.assertEqual(decision["result"], {"target": 3})

    async def test_save_failure_prevents_external_request(self):
        port, _, _ = self.port()
        port._checkpoint = Mock(side_effect=OSError("disk failure"))
        call = Mock()
        with self.assertRaises(OSError):
            await execute(port, "en", call)
        call.assert_not_called()
        self.assertEqual(port.planner.calls, 1)

    async def test_committed_replay_skips_request_and_reservation(self):
        port, trace, _ = self.port()
        port._replay_decision = lambda slot: {"result": False}
        call = Mock()
        self.assertIs(await execute(port, "en", call), False)
        self.assertEqual(port.planner.calls, 0)
        self.assertEqual(trace, [])
        call.assert_not_called()

    async def test_retry_is_new_attempt_and_rolls_back_failed_memory(self):
        port, trace, decision = self.port()
        class Actor:
            name = "actor"
            seat = SimpleNamespace(pos=2)
            def __init__(self):
                self.model_decisions = ["existing"]
                self.invocations = 0
            def vote(self):
                self.invocations += 1
                self.model_decisions.append(self.invocations)
                if self.invocations == 1:
                    raise ModelTurnError("bad response")
                return 3
        actor = Actor()
        self.assertEqual(await execute(port, "en", actor.vote), 3)
        self.assertEqual(actor.model_decisions, ["existing", 2])
        self.assertEqual(port.planner.calls, 2)
        self.assertEqual([a["outcome"] for a in decision["attempts"]], ["error", "accepted"])
        port.ask_player.assert_awaited_once_with("model_retry", {})

    async def test_offline_compatibility_does_not_create_model_attempt(self):
        port, trace, _ = self.port()
        port.planner = None
        self.assertEqual(await execute(port, "en", lambda x: x, 4), 4)
        self.assertEqual(trace, [])
