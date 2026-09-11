import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from werewolf_web.ai.public_story import for_brain
from werewolf_web.ai.model_context import fit_request_budget
from werewolf_web.offline_game import OfflineSession


class PublicStoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = OfflineSession(seed=4, player_role="werewolf")
        await self.session._step_setup()
        self.brain = self.session.proxy.brain
        self.others = [s for s in self.session.engine.alive_seats() if s.name != self.brain.name]

    def row(self, target):
        return next(r for r in for_brain(self.brain)["targets"] if r["name"] == target)

    async def test_sheriff_ballots_are_not_exile_pressure(self):
        a, b = self.others[:2]
        before = for_brain(self.brain)
        self.brain.vote_log.append((1, a.name, b.name, "sheriff"))
        self.assertEqual(for_brain(self.brain), before)
        self.brain.vote_log.append((1, a.name, b.name, "exile"))
        self.assertGreater(self.row(b.name)["pressure_score"], 0)

    async def test_repetition_and_own_accusation_do_not_amplify_support(self):
        a, b = self.others[:2]
        self.brain.accuse_log = [(1, a.name, b.name)]
        before = for_brain(self.brain)
        self.brain.accuse_log *= 100
        self.assertEqual(for_brain(self.brain), before)
        score = self.row(b.name)["pressure_score"]
        self.brain.accuse_log.append((1, self.brain.name, b.name))
        self.assertEqual(self.row(b.name)["pressure_score"], score)

    async def test_defense_reversal_cost_and_latest_stance(self):
        a = self.others[0]
        self.brain.defend_log = [(1, self.brain.name, a.name)]
        self.assertEqual(self.row(a.name)["reversal_cost"], .5)
        self.brain.accuse_log = [(2, self.brain.name, a.name)]
        self.assertEqual(self.row(a.name)["reversal_cost"], 0)

    async def test_hidden_state_and_rng_invariance_and_restore(self):
        before = for_brain(self.brain)
        snapshot = deepcopy(self.session.snapshot())
        for_brain(self.brain)
        self.assertEqual(self.session.snapshot(), snapshot)
        restored = OfflineSession()
        restored.restore(json.loads(json.dumps(snapshot)))
        self.assertEqual(for_brain(restored.proxy.brain), before)
        a, b = self.others[:2]
        a.role, b.role = b.role, a.role
        self.session.engine.seer_results = [{"secret": "must not read"}]
        self.assertEqual(for_brain(self.brain), before)

    async def test_optional_story_dropped_before_sources(self):
        request = {"public_story": {"large": "x" * 1000},
                   "public_context": {"recent_public_statements": ["source"]}}
        result = fit_request_budget(request, 100)
        self.assertNotIn("public_story", result)
        self.assertEqual(result["public_context"]["recent_public_statements"], ["source"])

    async def test_offline_bluffer_does_not_silently_switch_claimed_role(self):
        self.session.engine.night_count = 1
        self.brain.wolf_strategy = "bluff"
        self.brain.claim_order = [(self.brain.name, "civilian")]
        self.assertNotEqual(self.session.proxy.speak().claim, "seer")

    async def test_wolf_vote_uses_public_audience_pressure(self):
        from werewolf_web.ai.strategy import StrategicVotePlanner
        targets = [s for s in self.others if s.name not in self.brain.mates()][:2]
        audience = next(s for s in self.others if s not in targets)
        self.brain.claims = {}
        self.brain.accuse_log = [(1, audience.name, targets[1].name)]
        with patch.object(self.brain, "suspicion", return_value=.5), \
             patch.object(self.brain.rng, "uniform", return_value=0), \
             patch.object(self.brain.cognition, "choose_depth", return_value=(1, False)):
            plan = StrategicVotePlanner(self.brain).plan([s.pos for s in targets])
        self.assertEqual(plan.target, targets[1].pos)

    async def test_fabricated_check_remains_identical_when_audience_changes(self):
        self.session.engine.night_count = 1
        self.brain.wolf_strategy = "bluff"
        self.session.proxy.speak()
        before = deepcopy(self.brain._bluff_checks)
        a, b = self.others[:2]
        self.brain.accuse_log = [(1, a.name, b.name)]
        self.session.proxy.speak()
        self.assertEqual(self.brain._bluff_checks, before)

    async def test_model_receives_story_but_may_abstain(self):
        from werewolf_web.ai.decision_runtime import RuntimeBase
        from werewolf_web.session import GameSession
        runtime = RuntimeBase("test-model")
        runtime.backend = "api"
        runtime.verified = True
        runtime.complete = Mock(return_value={"target": None})
        session = GameSession("classic", seed=4, planner=runtime)
        await session._step_setup()
        agent = next(a for a in session.agents.values() if a.brain.is_wolf)
        candidates = [{"pos": s.pos, "name": s.name} for s in session.engine.alive_seats()]
        self.assertIsNone(agent.vote(candidates))
        runtime.complete.assert_called_once()
        request = runtime.complete.call_args.args[0]
        self.assertEqual(request["public_story"], for_brain(agent.brain))
