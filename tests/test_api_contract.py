"""Transport boundaries; no provider calls or full games required."""
import asyncio
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from werewolf_web.run import app, GAMES, GameSession, stream
from werewolf_web.game.engine import GameEngine, BOARD_MAP


class ApiContractTest(unittest.TestCase):
    def test_every_selectable_role_has_localized_private_help(self):
        for board in BOARD_MAP:
            for role in set(BOARD_MAP[board]["roles"]):
                for locale in ("en", "zh-CN"):
                    engine = GameEngine(board, locale=locale, player_role=role)
                    engine.setup()
                    self.assertTrue(engine.player_view()["ability"].strip(), (board, role, locale))

    def test_bad_json_and_ids_are_client_errors(self):
        with TestClient(app) as client:
            for endpoint in ("start", "action", "host_chat"):
                for value in ([], None, "text", {"game_id": []}):
                    response = client.post(f"/api/{endpoint}", json=value)
                    self.assertEqual(response.status_code, 422)
                self.assertEqual(client.post(f"/api/{endpoint}", content="{").status_code, 422)
            self.assertEqual(client.get("/api/stream?game_id=missing").status_code, 404)

    def test_speech_limit_preserves_pending_action(self):
        session = GameSession("classic", {"enabled": False})
        session.pending = {"kind": "speech", "data": {}}
        self.assertFalse(session.submit({"text": "x" * 4001}))
        self.assertIsNotNone(session.pending)
        self.assertTrue(session.submit({"text": "A valid statement."}))
        self.assertFalse(session.submit({"text": "duplicate"}))


class StreamContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_stream_is_rejected_before_second_loop(self):
        session = GameSession("classic", {"enabled": False})
        GAMES["contract-test"] = session
        try:
            response = await stream("contract-test")
            with self.assertRaises(HTTPException) as error:
                await stream("contract-test")
            self.assertEqual(error.exception.status_code, 409)
            session._play = AsyncMock()
            self.assertEqual([event async for event in response.body_iterator], [])
            # The game task owns the lifetime: stream close does NOT drop the game.
            self.assertIn("contract-test", GAMES)
            session._play.assert_awaited_once()
        finally:
            session.abandon()
            GAMES.pop("contract-test", None)

    async def test_disconnect_keeps_game_pending_and_allows_reattach(self):
        session = GameSession("classic", {"enabled": False})

        async def waiting_game():
            await session.ask_player("speech", {})

        session._play = waiting_game
        first = session.events()
        event = await anext(first)
        self.assertEqual(event["type"], "request")
        self.assertEqual(event["kind"], "speech")
        self.assertEqual(event["event_no"], 1)
        await first.aclose()

        # Stream close no longer ends the game or drops the pending action.
        self.assertFalse(session.finished)
        self.assertIsNotNone(session.pending)
        self.assertEqual(session.pending["kind"], "speech")
        # The recovery view re-presents the exact pending action for reattach.
        view = session.recovery_view(1)
        self.assertEqual(view["pending"]["kind"], "speech")
        self.assertEqual(view["pending"]["event_no"], 1)
        self.assertEqual(view["next_event_no"], 2)
        session.abandon()
        self.assertTrue(session.finished)
