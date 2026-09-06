import tempfile
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from werewolf_web.casting import CAST_IDS, PERSONA_IDS, random_names, validate_names
from werewolf_web.game.engine import GameEngine
from werewolf_web.ai.npc import load_seat_persona
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.ai.llm import LLMClient, LLMRuntimeConfig
from werewolf_web.run import GameSession, GAMES, start, cast_options


class CastingTest(unittest.TestCase):
    def test_seed_reproducible_and_names_do_not_affect_roles_or_personas(self):
        first = GameEngine(seed=4, locale="en")
        second = GameEngine(seed=4, locale="en", names={"acheng": "Shawn", "dashan": "River"})
        for game in (first, second):
            game.setup()
        self.assertEqual([(s.player_id, s.role, s.persona_id) for s in first.seats.values()],
                         [(s.player_id, s.role, s.persona_id) for s in second.seats.values()])
        self.assertEqual(first.rng.getstate(), second.rng.getstate())
        self.assertEqual(second.player_seat().name, "Shawn")
        self.assertEqual(len({s.name.casefold() for s in second.seats.values()}), 12)
        self.assertEqual(first.cast_names, GameEngine(seed=4, locale="en").cast_names)

    def test_random_presets_use_each_npc_template_and_vary_across_seeds(self):
        maps = []
        for seed in range(5):
            game = GameEngine(seed=seed)
            game.setup()
            self.assertEqual({s.persona_id for s in game.seats.values() if not s.is_player}, set(PERSONA_IDS))
            maps.append(tuple(game.cast_personas.items()))
        self.assertGreater(len(set(maps)), 1)
        self.assertGreater(len({tuple(random_names("en", s).values()) for s in range(5)}), 1)

    def test_rename_keeps_personality_localization_and_stable_memory_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = []
            for name in ("River", "Renamed"):
                game = GameEngine(seed=5, locale="en", names={"dashan": name})
                game.setup()
                agent = StrategicNPCAgent(name, game,
                    LLMClient(LLMRuntimeConfig.from_request({"enabled": False})), memory_dir=tmp)
                agents.append(agent)
                self.assertEqual(agent.persona["name"], name)
                self.assertNotRegex(agent.persona["traits"], r"[\u4e00-\u9fff]")
            self.assertEqual(agents[0].style, agents[1].style)
            self.assertEqual(agents[0].persona["catchphrases"], agents[1].persona["catchphrases"])
            self.assertEqual(agents[0].seat.persona_id, agents[1].seat.persona_id)

    def test_profile_text_rebind_and_public_state_no_hidden_role(self):
        game = GameEngine(seed=7, names={k: "名字" + str(i) for i, k in enumerate(CAST_IDS)})
        game.setup()
        for seat in game.seats.values():
            persona = load_seat_persona(seat, game)
            self.assertEqual(persona["name"], seat.name)
            self.assertTrue(persona["traits"])
            self.assertNotIn("role", seat.to_public())
            self.assertNotIn("persona_id", seat.to_public())

    def test_names_reject_ambiguous_unsafe_or_duplicate_values(self):
        for names in (["foo"], {"fake": "Hello"}, {"acheng": ""}, {"acheng": "123"},
                      {"acheng": "Host"}, {"acheng": "../file"}, {"acheng": "<img>"},
                      {"acheng": "A\nB"}, {"acheng": "A" * 25},
                      {"acheng": "River", "dashan": "Ｒｉｖｅｒ"}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                validate_names(names)
        self.assertEqual(validate_names({"acheng": " Zoë O’Neil "})["acheng"], "Zoë O’Neil")
        self.assertEqual(validate_names({"acheng": "阿星"})["acheng"], "阿星")
        names = random_names("en", 1, {"acheng": "Miles"})
        self.assertEqual(len(set(names.values())), 12)


class CastingRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_cast_preview_localized_unique_and_no_personality_or_roles(self):
        for locale in ("zh-CN", "en"):
            preview = await cast_options(locale)
            self.assertEqual(len(preview["players"]), 12)
            self.assertEqual(sum(p["is_player"] for p in preview["players"]), 1)
            self.assertTrue(all(set(p) == {"id", "name", "is_player"} for p in preview["players"]))
            if locale == "en":
                self.assertTrue(all(p["name"].isascii() for p in preview["players"]))

    async def test_web_and_chat_core_accept_same_names_and_api_rejects_invalid(self):
        names = {"acheng": "Shawn", "dashan": "River"}
        request = AsyncMock()
        request.json.return_value = {"board_id": "classic", "locale": "en", "names": names,
                                     "llm": {"enabled": False}}
        result = await start(request)
        try:
            web = GAMES[result["game_id"]]
            chat = GameSession("classic", {"enabled": False}, locale="en", names=names)
            for session in (web, chat):
                session.engine.setup()
                self.assertEqual(session.engine.player_seat().name, "Shawn")
                self.assertIsNotNone(session.engine.seat_by_name("River"))
        finally:
            GAMES.pop(result["game_id"])
        before = set(GAMES)
        request.json.return_value["names"] = {"acheng": "<script>"}
        with self.assertRaises(HTTPException) as error:
            await start(request)
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(set(GAMES), before)


if __name__ == "__main__":
    unittest.main()
