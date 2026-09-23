import unittest
from scripts.offline_acceptance import run_case


class OfflineAcceptanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_and_ablated_games_finish_without_model(self):
        for enabled in (True, False):
            row = await run_case(2, "en", True, enabled)
            self.assertGreater(row["speeches"], 0)
            self.assertIn(row["winner"], {"god", "wolf", "draw"})
            if not enabled:
                self.assertEqual(row["social_feedback"], 0)
