"""Thirty authored characters, twelve seats, durable independent role dealing."""
import unittest
from copy import deepcopy
from werewolf_web.characters import catalog
from werewolf_web.offline_cast import BY_ID, cast_settings, legacy_cast_settings
from werewolf_web.offline_game import OfflineSession
from werewolf_web.session import GameSession
from werewolf_web.ai.npc import load_seat_persona
from werewolf_web.ai.brain import Style


class LibraryTest(unittest.TestCase):
    def test_thirty_distinct_profiles_and_weights(self):
        self.assertEqual(len(BY_ID), 30)
        self.assertEqual(len({c.weights for c in BY_ID.values()}), 30)
        for language in ("zh-CN", "en"):
            rows = catalog(language)
            for field in ("id", "name", "title", "story", "phrase", "portrait"):
                self.assertEqual(len({r[field] for r in rows}), 30, field)
            for row in rows:
                self.assertTrue(row["voice"])
                self.assertEqual(len(row["weights"]), 6)
                self.assertTrue(all(0 <= value <= 1 for value in row["weights"].values()))

    def test_all_characters_playable_in_both_languages(self):
        for language in ("zh-CN", "en"):
            for key in BY_ID:
                s = GameSession("classic", {"enabled":False}, character=key, seed=5, locale=language, player_role="civilian")
                s.engine.setup()
                self.assertEqual(s.engine.player_seat().persona_id, key)
                self.assertEqual(s.engine.player_seat().role, "civilian")
                for seat in s.engine.seats.values():
                    persona = load_seat_persona(seat, s.engine)
                    self.assertTrue(persona["speech_style"])
                    self.assertEqual(Style.from_persona(persona), BY_ID[seat.persona_id].style())

    def test_seeded_sample_unique_and_varies_between_games(self):
        a = cast_settings("linque", "en", seed=4)
        self.assertEqual(a, cast_settings("linque", "en", seed=4))
        self.assertNotEqual(a, cast_settings("linque", "en", seed=5))
        self.assertEqual(len(set(a[0].values())), 12)
        self.assertEqual(a[0]["acheng"], "linque")
        for key in BY_ID:
            self.assertEqual(cast_settings(key, "en", seed=2)[0]["acheng"], key)

    def test_bad_mapping_restore_leaves_engine_unchanged(self):
        s = GameSession("classic", {"enabled":False}, character="yuejian", seed=4)
        s.engine.setup()
        before = s.engine.snapshot()
        for value in ("missing-person", ["bad"]):
            bad = deepcopy(before); bad["cast_personas"]["acheng"] = value
            with self.assertRaises(ValueError):
                s.engine.restore(bad)
            self.assertEqual(s.engine.snapshot(), before)


class LibraryRestoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_offline_restore_uses_saved_cast_not_new_draw(self):
        s = OfflineSession(character="linque", seed=8)
        await s._step_setup()
        restored = OfflineSession(character="linque", seed=999)
        restored.restore(s.snapshot())
        self.assertEqual(restored.character_map, s.character_map)
        self.assertEqual(restored.engine.public_state(), s.engine.public_state())
        for agent in restored.agents.values():
            self.assertEqual(agent.character.id, agent.seat.persona_id)
            self.assertEqual(agent.style, BY_ID[agent.seat.persona_id].style())

    async def test_original_twelve_person_cast_can_still_restore(self):
        s = OfflineSession(character="amo", seed=8)
        mapping = legacy_cast_settings("amo", "zh-CN")
        from werewolf_web.offline_cast import display_names
        s.character_map = mapping
        s.engine.cast_personas = mapping.copy()
        names = display_names("zh-CN")
        s.engine.cast_names = {key:names[value] for key,value in mapping.items()}
        await s._step_setup()
        restored = OfflineSession(character="amo", seed=999)
        restored.restore(s.snapshot())
        self.assertEqual(restored.character_map, mapping)
