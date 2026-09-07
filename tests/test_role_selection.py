import asyncio
from collections import Counter
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from werewolf_web.game.engine import BOARD_MAP, GameEngine
from werewolf_web.run import GAMES, GameSession, start
from werewolf_web.chat_game import main


class RoleSelectionTest(unittest.TestCase):
    def test_all_board_roles_and_random_compatibility(self):
        for board, data in BOARD_MAP.items():
            for seed in range(12):
                default = GameEngine(board, seed=seed); default.setup()
                random = GameEngine(board, seed=seed, player_role="random"); random.setup()
                self.assertEqual(default.seats, random.seats)
                for role in set(data["roles"]):
                    with self.subTest(board=board, seed=seed, role=role):
                        engine = GameEngine(board, seed=seed, player_role=role); engine.setup()
                        self.assertEqual(engine.player_seat().role, role)
                        self.assertEqual(engine.player_seat().pos, default.player_seat().pos)
                        self.assertEqual(Counter(s.role for s in engine.seats.values()), Counter(data["roles"]))
                        self.assertTrue(all("role" not in s for s in engine.public_state()["seats"]))
                        self.assertEqual(engine.player_view()["role"], role)

    def test_invalid_types_and_board_roles(self):
        for value in (True, 1, [], {}, "", "stone_ghost", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GameEngine("classic", player_role=value)

    def test_chat_role_argument(self):
        with patch("sys.argv", ["chat", "--board", "classic", "--role", "seer", "--offline"]), \
             patch("werewolf_web.chat_game.play", new_callable=AsyncMock) as play:
            main()
            self.assertEqual(play.call_args.args[7], "seer")
        with patch("sys.argv", ["chat", "--board", "classic", "--role", "bad"]), \
             patch("sys.stderr"), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)


class RoleSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_api(self):
        before = set(GAMES)
        for value in ([], True, "stone_ghost"):
            request = AsyncMock(); request.json.return_value = {"player_role": value}
            with self.assertRaises(HTTPException) as error:
                await start(request)
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(set(GAMES), before)
        request = AsyncMock()
        request.json.return_value = {"player_role": "seer", "llm": {"enabled": False}}
        result = await start(request)
        session = GAMES.pop(result["game_id"])
        session.engine.setup()
        self.assertEqual(session.engine.player_seat().role, "seer")
        self.assertNotIn("player_role", result)

    async def test_selected_roles_complete_in_both_modes(self):
        sleep = asyncio.sleep
        async def fast_sleep(_):
            await sleep(0)
        for role in set(BOARD_MAP["classic"]["roles"]):
            for mode in (False, True):
                with self.subTest(role=role, mode=mode), tempfile.TemporaryDirectory() as memory, \
                     patch("werewolf_web.run.asyncio.sleep", fast_sleep), \
                     patch("werewolf_web.ai.host.HostAgent.evolve"):
                    session = GameSession("classic", {"enabled": False}, seed=7,
                                          player_role=role, conjecture=mode)
                    session.memory_dir = memory
                    ended = False
                    async for event in session.events():
                        self.assertNotEqual(event["type"], "error", event)
                        if event["type"] == "gameover": ended = True
                        if event["type"] != "request": continue
                        kind, data = event["kind"], event["data"]
                        if kind == "conjecture": answer = {k: data[k] for k in ("private", "public")}
                        elif kind in ("speech", "table_reply"): answer = {"text": "暂无新信息。"}
                        elif kind == "election_up": answer = {"up": False}
                        elif kind == "night" and data.get("role_key") == "witch": answer = {"save": None, "poison": None}
                        else: answer = {"target": data["candidates"][0]["pos"] if data.get("candidates") else None}
                        self.assertTrue(session.submit(answer), (kind, answer))
                    self.assertTrue(ended)
                    self.assertEqual(session.engine.player_seat().role, role)
