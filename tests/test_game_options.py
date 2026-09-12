import asyncio
from copy import deepcopy
import json
import tempfile
import unittest
from itertools import product
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException

from werewolf_web.casting import PERSONA_IDS, assign_personas, persona_options
from werewolf_web.game.engine import GameEngine, BOARD_MAP
from werewolf_web.game.conjecture import GameConjectures
from werewolf_web.run import GameSession, GAMES, start
from werewolf_web.chat_game import edit_conjecture, parse_action, _request_prompt
from werewolf_web.research.extreme_game import ExtremeGame, play_game
from werewolf_web.research.extreme_profiles import roster_profiles, validate_profile
from werewolf_web.research.shadow_debate import PLAYERS


def fake_complete(label, request):
    task = request["task"]
    if task in ("night_check", "night_kill"):
        return json.dumps({"target": request["candidates"][0], "reason": "test"})
    if task == "challenge":
        return json.dumps({"target": None, "row_player": None, "evidence": [], "text": "pass"})
    if task == "vote":
        return json.dumps({"target": next(p for p in request["active_players"] if p != request["actor"]), "reason": "test"})
    private, public = [], []
    for p, lock in request["lawful_constraints"].items():
        base = {"player": p, "roles": [], "candidate_roles": lock["possible_roles"], "status": "unknown",
                "faction": "", "faction_status": "unknown", "confidence": "low", "evidence": [],
                "rationale": "test", "alternatives": ""}
        public.append(deepcopy(base))
        if lock["role"]:
            base.update(roles=[lock["role"]], status="known")
        if lock["faction"]:
            base.update(faction=lock["faction"], faction_status="known")
        if lock["role"] or lock["faction"]:
            base["evidence"] = lock["evidence"]
        private.append(base)
    result = {"private": private, "public": public, "reason": "test"}
    if task == "revision":
        result["public_reason"] = "test"
    return json.dumps(result)


class OptionsTest(unittest.TestCase):
    def test_chat_table_editor_without_json(self):
        e = GameEngine(seed=1); e.setup()
        data = GameConjectures(e).human_request()
        self.assertTrue(edit_conjecture(data, "公开 3 狼人阵营 发言矛盾"))
        self.assertEqual(data["public"][2]["judgment"], "wolf")
        self.assertEqual(data["public"][2]["reason"], "发言矛盾")
        self.assertFalse(edit_conjecture(data, "public 99 wolf reason"))
        self.assertEqual(parse_action("conjecture", data, "done")["public"], data["public"])
        self.assertIn("提交", _request_prompt("conjecture", data))
        self.assertIn("投票", _request_prompt("vote", {"candidates": []}))

    def test_mixed_fixed_random_and_role_independence(self):
        for seed in range(5):
            fixed = assign_personas(seed, {"dashan": "aman", "amo": "aman"})
            self.assertEqual(fixed["dashan"], "aman")
            self.assertEqual(fixed["amo"], "aman")
            self.assertTrue(set(fixed.values()) <= {*PERSONA_IDS, "acheng"})
            a, b = GameEngine(seed=seed), GameEngine(seed=seed, personalities={"dashan": "aman"})
            a.setup(); b.setup()
            self.assertEqual([(s.player_id, s.role) for s in a.seats.values()],
                             [(s.player_id, s.role) for s in b.seats.values()])
        for invalid in ({"acheng": "aman"}, {"dashan": "../oops"}, [], {"fake": "random"}):
            with self.assertRaises(ValueError):
                assign_personas(1, invalid)
        self.assertEqual(len(persona_options("en")), 11)

    def test_human_table_privacy_and_validation(self):
        e = GameEngine(seed=1); e.setup()
        ledger = GameConjectures(e)
        data = ledger.human_request()
        response = {k: data[k] for k in ("private", "public")}
        response["private"][0]["reason"] = "PRIVATE_CANARY"
        ledger.validate_human(response)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(ledger.public_history()))
        response["public"].pop()
        with self.assertRaises(ValueError):
            ledger.validate_human(response)

    def test_extreme_game_complete_and_private_boundaries(self):
        for index in range(4):
            profiles = roster_profiles(index, PLAYERS)
            for value in profiles.values():
                validate_profile(value)
            game = ExtremeGame(profiles)
            seen = []
            def complete(label, request):
                self.assertNotIn("ground_truth", request)
                self.assertEqual(request["personality"], profiles[request["actor"]])
                self.assertIn(request["actor"], request["active_players"])
                for record in request["own_private"]["observations"]:
                    self.assertTrue(record["event_id"].startswith(f"P:{request['actor']}:"))
                seen.append(request)
                return fake_complete(label, request)
            play_game(game, complete)
            self.assertIn(game.winner, ("good", "wolf"))
            self.assertGreater(len(game.days), 0)
            self.assertEqual(game.profiles, profiles)
            self.assertNotIn('"private"', json.dumps(game.public_export()))
            self.assertTrue(any(r["task"] == "vote" for r in seen))


class PlayableTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_api_rejects_invalid_before_registering(self):
        before = set(GAMES)
        for body in ([], {"conjecture": "yes"}, {"personalities": {"dashan": "bad"}},
                     {"personalities": {"acheng": "aman"}}, {"board_id": []}):
            request = AsyncMock(); request.json.return_value = body
            with self.assertRaises(HTTPException) as error:
                await start(request)
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(set(GAMES), before)
        request = AsyncMock()
        request.json.return_value = {"conjecture": True, "personalities": {"dashan": "aman"}, "llm": {"enabled": False}}
        result = await start(request)
        session = GAMES.pop(result["game_id"])
        self.assertTrue(session.conjecture)
        self.assertEqual(session.engine.cast_personas["dashan"], "aman")

    async def test_conjecture_and_normal_complete_offline(self):
        original_sleep = asyncio.sleep
        async def fast_sleep(_):
            await original_sleep(0)
        for enabled, board, locale in product((False, True), BOARD_MAP, ("zh-CN", "en")):
            with tempfile.TemporaryDirectory() as memory, patch("werewolf_web.run.asyncio.sleep", fast_sleep), \
                 patch("werewolf_web.ai.host.HostAgent.evolve"):
                session = GameSession(board, {"enabled": False}, seed=3, conjecture=enabled,
                                      locale=locale, personalities={"dashan": "aman", "amo": "aman"})
                session.memory_dir = memory
                types = []
                async for event in session.events():
                    types.append(event["type"])
                    self.assertNotEqual(event["type"], "error", event)
                    if event["type"] == "conjecture":
                        self.assertNotIn('"private"', json.dumps(event))
                    if event["type"] != "request":
                        continue
                    kind, data = event["kind"], event["data"]
                    if kind == "conjecture":
                        response = {k: data[k] for k in ("private", "public")}
                    elif kind == "table_answer": response = {"skip": True}
                    elif kind in ("speech", "table_reply"):
                        response = {"text": "暂时没有新的信息。"}
                    elif kind == "election_up":
                        response = {"up": False}
                    elif kind == "night" and data.get("role_key") == "witch":
                        response = {"save": None, "poison": None}
                    else:
                        response = {"target": data["candidates"][0]["pos"] if data.get("candidates") else None}
                    self.assertTrue(session.submit(response), (kind, response))
                self.assertIn("gameover", types)
                self.assertEqual("conjecture" in types, enabled, (board, locale))


if __name__ == "__main__":
    unittest.main()
