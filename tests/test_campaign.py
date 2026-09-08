"""Main-line campaign level table: role↔board compatibility, coverage, win side."""
import unittest

from werewolf_web import campaign
from werewolf_web.game.engine import BOARD_MAP, ROLE_META
from werewolf_web.game.models import WOLF_ROLES


class CampaignLevelsTest(unittest.TestCase):
    def test_level_table_is_valid(self):
        self.assertEqual(campaign.validate_levels(), [])

    def test_levels_cover_every_playable_role_exactly_once(self):
        roles = [lvl["role"] for lvl in campaign.LEVELS]
        self.assertEqual(len(roles), len(set(roles)), "duplicate roles")
        self.assertEqual(set(roles), campaign.played_roles(), "coverage mismatch")

    def test_every_level_role_is_playable_on_its_board(self):
        for lvl in campaign.LEVELS:
            self.assertIn(lvl["role"], BOARD_MAP[lvl["board"]]["roles"], lvl)

    def test_win_side_matches_role_faction(self):
        for lvl in campaign.LEVELS:
            role = lvl["role"]
            meta_faction = ROLE_META[role]["faction"]
            expected = "wolf" if meta_faction == "wolf" else "god"
            self.assertEqual(campaign.player_side(role), expected, role)

    def test_wolf_roles_map_to_wolf_side(self):
        for role in WOLF_ROLES:
            self.assertEqual(campaign.player_side(role), "wolf", role)

    def test_civilian_maps_to_god_side(self):
        self.assertEqual(campaign.player_side("civilian"), "god")


if __name__ == "__main__":
    unittest.main()
