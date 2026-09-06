import unittest

from werewolf_web.game.engine import GameEngine
from werewolf_web.i18n import SUPPORTED_LOCALES, cast
from werewolf_web.ai.host import HostAgent
from werewolf_web.ai.llm import LLMClient


class LocaleIdentityTest(unittest.TestCase):
    def test_english_cast_uses_local_names_but_stable_ids(self):
        engine = GameEngine("classic", seed=12, locale="en")
        engine.setup()
        self.assertIn("en", SUPPORTED_LOCALES)
        self.assertEqual(engine.player_seat().player_id, "acheng")
        self.assertIn(engine.player_seat().name, {p["name"] for p in cast("en")})
        self.assertEqual(len({seat.player_id for seat in engine.seats.values()}), 12)
        self.assertIn("Miles", {seat.name for seat in engine.seats.values()})

    def test_same_seed_preserves_identity_role_assignment_across_locales(self):
        zh = GameEngine("classic", seed=99, locale="zh-CN")
        en = GameEngine("classic", seed=99, locale="en")
        zh.setup()
        en.setup()
        self.assertEqual(
            [(seat.player_id, seat.role) for seat in zh.seats.values()],
            [(seat.player_id, seat.role) for seat in en.seats.values()],
        )

    def test_english_host_rules_and_moderation_are_english(self):
        engine = GameEngine("classic", seed=1, locale="en")
        engine.setup()
        host = HostAgent(LLMClient(), locale="en")
        self.assertIn("village wins", host.answer_rule_question("How do we win?", engine))
        self.assertIn("Host:", host.moderate_table_talk(
            topic_turns=3, extra_turns=3, speaker_extra_turns=1, repeated_pair=True))


if __name__ == "__main__":
    unittest.main()
