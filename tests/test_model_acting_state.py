import json
import tempfile
import unittest
from copy import deepcopy

from werewolf_web.session import GameSession
from werewolf_web.observations import ObservationGateway
from werewolf_web.ai.decision_runtime import RuntimeBase
from werewolf_web.ai.model_context import MAX_REQUEST_CHARS


class NoCallRuntime(RuntimeBase):
    backend = "api"

    def complete(self, *args):
        raise AssertionError("No real model in tests")


class ModelActingStateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        runtime = NoCallRuntime("test")
        runtime.verified = True
        self.session = GameSession("classic", planner=runtime, seed=7)
        self.session.memory_dir = self.directory.name
        await self.session._step_setup()
        self.agent = next(iter(self.session.agents.values()))

    def request(self):
        return ObservationGateway.for_model(self.agent, "public speech", {}).to_request()

    async def test_own_emotion_changes_only_own_context_not_facts(self):
        before = self.request()
        self.agent.brain.match_state.valence = -0.9
        self.agent.brain.match_state.arousal = 0.9
        after = self.request()
        self.assertNotEqual(before["own_acting_state"], after["own_acting_state"])
        before.pop("own_acting_state")
        after.pop("own_acting_state")
        self.assertEqual(before, after)

    async def test_other_state_and_private_event_ledger_cannot_leak(self):
        before = self.request()
        other = next(a for a in self.session.agents.values() if a is not self.agent)
        other.brain.match_state.stress = 1
        other.brain.match_state.events.append("OTHER_STATE_SECRET")
        self.agent.brain.match_state.events.append("OWN_LEDGER_SECRET")
        self.assertEqual(before, self.request())
        self.assertNotIn("own_acting_state", json.dumps(self.session.recovery_view()))

    async def test_detached_and_bounded_with_long_history(self):
        for i in range(40):
            self.session.public_record.observe({"type": "speech", "seat": self.agent.seat.pos,
                "text": "长发言" * 500, "event_no": i + 1}, 1)
        request = self.request()
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), MAX_REQUEST_CHARS)
        before = self.agent.brain.match_state.snapshot()
        request["own_acting_state"]["affect"]["stress"] = 99
        self.assertEqual(before, self.agent.brain.match_state.snapshot())

    async def test_restore_preserves_own_state_request(self):
        self.agent.brain.match_state.stress = 0.85
        before = self.request()
        snapshot = deepcopy(self.session.snapshot())
        self.session.restore(snapshot)
        self.agent = self.session.agents[self.agent.name]
        self.assertEqual(before, self.request())

    async def test_personality_remains_separate_from_state_and_rules(self):
        before = self.request()
        self.agent.style.aggression = 0.95
        self.agent.style.caution = 0.05
        after = self.request()
        self.assertNotEqual(before["personality_parameters"], after["personality_parameters"])
        self.assertEqual(before["information"], after["information"])
        self.assertEqual(before["own_acting_state"], after["own_acting_state"])
