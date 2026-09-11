import json
import unittest
from copy import deepcopy

from werewolf_web.offline_game import OfflineSession
from werewolf_web.ai.joint_belief import for_brain


class EvidenceAccountingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = OfflineSession(seed=4, player_role="civilian")
        await self.session._step_setup()
        self.brain = self.session.proxy.brain
        self.others = [s for s in self.session.engine.alive_seats() if s.name != self.brain.name]

    def clone(self):
        restored = OfflineSession()
        restored.restore(json.loads(json.dumps(self.session.snapshot())))
        return restored.proxy.brain

    async def test_repeated_support_cannot_multiply_flip_credit(self):
        a, b = self.others[:2]
        one, repeated = self.clone(), self.clone()
        one.defend_log = [(1, a.name, b.name)]
        repeated.defend_log = [(day, a.name, b.name) for day in range(1, 9)]
        for brain in (one, repeated):
            brain.observe_flip(b.name, "平民", False)
        self.assertEqual(one.sus_of(a.name), repeated.sus_of(a.name))
        self.assertEqual(one.suspicion(a.name), repeated.suspicion(a.name))
        self.assertEqual(for_brain(one)["wolf_weights"], for_brain(repeated)["wolf_weights"])

    async def test_repeated_accusation_cannot_multiply_flip_penalty(self):
        a, b = self.others[:2]
        one, repeated = self.clone(), self.clone()
        one.accuse_log = [(1, a.name, b.name)]
        repeated.accuse_log = one.accuse_log * 8
        for brain in (one, repeated):
            brain.observe_flip(b.name, "平民", False)
        self.assertEqual(one.sus_of(a.name), repeated.sus_of(a.name))
        self.assertEqual(one.suspicion(a.name), repeated.suspicion(a.name))

    async def test_exile_scores_only_current_day_unique_voters(self):
        a, b, target = self.others[:3]
        self.brain.vote_log = [(1, a.name, target.name, "exile"),
                               (2, b.name, target.name, "exile"),
                               (2, b.name, target.name, "exile"),
                               (2, a.name, target.name, "sheriff")]
        before_a, before_b = self.brain.sus_of(a.name), self.brain.sus_of(b.name)
        self.brain.observe_exile(2, target.name, False)
        self.assertEqual(self.brain.sus_of(a.name), before_a)
        self.assertAlmostEqual(self.brain.sus_of(b.name), before_b + .12)
        before = deepcopy(self.brain.snapshot())
        self.brain.observe_exile(2, target.name, False)
        self.assertEqual(self.brain.snapshot(), before)

    async def test_restore_does_not_repeat_existing_flip_accounting(self):
        a, b = self.others[:2]
        self.brain.defend_log = [(1, a.name, b.name)] * 4
        self.brain.observe_flip(b.name, "平民", False)
        restored = self.clone()
        before = restored.snapshot()
        restored.observe_flip(b.name, "平民", False)
        self.assertEqual(restored.snapshot(), before)

    async def test_distinct_speakers_each_receive_one_update(self):
        a, b, target = self.others[:3]
        self.brain.defend_log = [(1, a.name, target.name)] * 8 + [(1, b.name, target.name)]
        before_a, before_b = self.brain.sus_of(a.name), self.brain.sus_of(b.name)
        self.brain.observe_flip(target.name, "平民", False)
        self.assertAlmostEqual(self.brain.sus_of(a.name), before_a - .20)
        self.assertAlmostEqual(self.brain.sus_of(b.name), before_b - .20)

    async def test_legacy_accumulated_weights_preserved_not_silently_rewritten(self):
        a = self.others[0]
        self.brain.sus[a.name] = -1.25
        self.assertEqual(self.clone().sus_of(a.name), -1.25)
