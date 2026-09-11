import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from werewolf_web.offline_game import OfflineSession
from werewolf_web.ai.public_story import for_brain
from werewolf_web.ai.wolf_dialogue import new_check, public_move, reversal_prefix


class WolfDialogueTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = OfflineSession(seed=4, player_role="werewolf")
        await self.session._step_setup()
        self.brain = self.session.proxy.brain
        self.brain.wolf_strategy = "undercover"
        self.brain.claim_order = [(self.brain.name, "civilian")]
        self.pool = [s for s in self.session.engine.alive_seats()
                     if s.name != self.brain.name and s.name not in self.brain.mates()]

    async def test_active_support_is_public_and_not_pack_identity(self):
        a, b = self.pool[:2]
        self.brain.style.loyalty = 1
        self.brain.defend_log = [(1, b.name, a.name)]
        speech = self.session.proxy.speak()
        self.assertEqual(speech.defend, a.name)
        self.assertNotIn("wolf", speech.text.lower())

    async def test_new_accusation_explains_reversal_in_both_languages(self):
        a, b = self.pool[:2]
        self.brain.defend_log = [(1, self.brain.name, a.name)]
        self.brain.accuse_log = [(2, b.name, a.name)]
        story = for_brain(self.brain)
        for locale in ("zh-CN", "en"):
            text = reversal_prefix(story, a.pos, locale)
            self.assertIn(b.name, text)
            self.assertIn("2", text)
            self.assertIn("不是已证实" if locale == "zh-CN" else "not a verified fact", text)
        self.brain.accuse_log = [(1, b.name, a.name)]
        self.assertIsNone(reversal_prefix(for_brain(self.brain), a.pos, "en"))

    async def test_actual_speech_explains_or_asks_instead_of_silent_reversal(self):
        a, b = self.pool[:2]
        self.brain.style.caution = 0
        self.brain.defend_log = [(1, self.brain.name, a.name)]
        with patch.object(self.brain, "suspicion", side_effect=lambda name: 1 if name == a.name else 0):
            speech = self.session.proxy.speak()
            self.assertEqual(speech.question_to, a.name)
            self.brain.accuse_log = [(2, b.name, a.name)]
            speech = self.session.proxy.speak()
            self.assertEqual(speech.accuse, a.name)
            self.assertIn(b.name, speech.text)
            self.assertIn("第2天", speech.text)

    async def test_fake_good_and_black_checks_follow_public_pressure(self):
        a, b = self.pool[:2]
        self.session.engine.night_count = 1
        report = new_check(self.brain, for_brain(self.brain), [a], {})
        self.assertEqual(report["result"], "good")
        self.brain.accuse_log = [(1, b.name, a.name)]
        report = new_check(self.brain, for_brain(self.brain), [a], {})
        self.assertEqual(report["result"], "wolf")

    async def test_rechecked_target_keeps_result_and_prefers_unchecked(self):
        a, b = self.pool[:2]
        old = {1: {"target": a.pos, "result": "good"}}
        self.brain.accuse_log = [(2, b.name, a.name)]
        story = for_brain(self.brain)
        self.assertEqual(new_check(self.brain, story, [a], old)["result"], "good")
        self.assertEqual(new_check(self.brain, story, [a, b], old)["target"], b.pos)
        old[2] = {"target": a.pos, "result": "wolf"}
        self.assertIsNone(new_check(self.brain, story, [a], old))

    async def test_nonseer_personality_claims_do_not_unlock_skills(self):
        self.brain.claim_order = []
        story = for_brain(self.brain)
        self.brain.style.aggression = 0
        self.assertEqual(public_move(self.brain, story), "claim:civilian")
        self.brain.style.aggression = 1
        self.assertEqual(public_move(self.brain, story), "claim:hunter")
        self.assertEqual(self.brain.role, "werewolf")
        self.brain.claim_order = [(self.brain.name, "civilian")]
        self.assertIsNone(public_move(self.brain, for_brain(self.brain)))

    async def test_restored_bluff_report_and_rng_reproduce_next_speech(self):
        self.brain.claim_order = []
        self.brain.wolf_strategy = "bluff"
        self.session.engine.night_count = 1
        self.session.proxy.speak()
        restored = OfflineSession()
        restored.restore(json.loads(json.dumps(self.session.snapshot())))
        for session in (self.session, restored):
            session.engine.night_count = 2
        self.assertEqual(self.session.proxy.speak(), restored.proxy.speak())
        self.assertEqual(self.brain._bluff_checks, restored.proxy.brain._bluff_checks)

    async def test_public_aid_is_pure_and_hidden_checks_cannot_change_it(self):
        a, b = self.pool[:2]
        self.brain.defend_log = [(1, self.brain.name, a.name)]
        self.brain.accuse_log = [(2, b.name, a.name)]
        snapshot = deepcopy(self.session.snapshot())
        before = for_brain(self.brain)
        self.assertEqual(self.session.snapshot(), snapshot)
        self.session.engine.seer_results = [{"target": a.pos, "result": "wolf", "night": 1}]
        self.assertEqual(for_brain(self.brain), before)

    async def test_no_fake_check_before_first_night(self):
        self.brain.wolf_strategy = "bluff"
        self.brain.claim_order = []
        self.session.engine.night_count = 0
        self.session.proxy.speak()
        self.assertFalse(getattr(self.brain, "_bluff_checks", {}))
