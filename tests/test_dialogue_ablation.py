import unittest
from scripts.compare_wolf_dialogue import run


class DialogueAblationTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_factor_set_reproduces_control(self):
        self.assertEqual(await run(400, False), await run(400, True, set()))

    async def test_claims_only_does_not_enable_support_or_good_checks(self):
        _, _, behavior = await run(400, True, {"claims"})
        self.assertEqual(behavior["support_speeches"], 0)
        self.assertGreater(behavior["civilian_claims"] + behavior["hunter_claims"], 0)

    async def test_unknown_factor_rejected(self):
        with self.assertRaises(ValueError):
            await run(400, True, {"typo"})

    async def test_nonclassic_unary_policy_completes_with_same_roster(self):
        before, roster, _ = await run(500, False, board_id="hidden_wolf_crow", opponent="unary")
        after, next_roster, _ = await run(500, True, board_id="hidden_wolf_crow", opponent="unary")
        self.assertEqual(roster, next_roster)
        self.assertIn(before, ("god", "wolf", "draw"))
        self.assertIn(after, ("god", "wolf", "draw"))

    async def test_unknown_opponent_rejected(self):
        with self.assertRaises(ValueError):
            await run(500, True, opponent="typo")
