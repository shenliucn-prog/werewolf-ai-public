"""SSE reattach + player-scoped recovery view (§6).

The game task owns the session's lifetime: a closed stream no longer ends the
game.  Reattach resumes from the retained event ledger by event number (no
missing, no duplicate), and ``recovery_view`` re-presents only what the single
human seat is entitled to see.
"""
import asyncio
import unittest

from fastapi.testclient import TestClient

from werewolf_web.run import GameSession


class ReattachStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_reattach_joins_at_cursor_without_missing_or_duplicate(self):
        session = GameSession("classic", {"enabled": False})

        async def idle():
            await asyncio.Event().wait()

        session._play = idle
        for text in ("e1", "e2", "e3", "e4"):
            session.emit({"type": "narration", "text": text})

        # First consumer sees events 1 and 2, then disconnects.
        first = session.events(after=0)
        self.assertEqual((await anext(first))["event_no"], 1)
        self.assertEqual((await anext(first))["event_no"], 2)
        await first.aclose()

        # Reattach at the cursor: 3 and 4 are delivered exactly once; 1 and 2
        # are not repeated.
        got = []
        second = session.events(after=2)
        try:
            async for ev in second:
                got.append(ev["event_no"])
                if len(got) >= 2:
                    break
        finally:
            await second.aclose()
        self.assertEqual(got, [3, 4])
        session.abandon()

    async def test_events_are_numbered_monotonically(self):
        session = GameSession("classic", {"enabled": False})
        session.emit({"type": "narration", "text": "a"})
        session.emit({"type": "narration", "text": "b"})
        session.emit({"type": "death", "text": "c", "seat": 1})
        self.assertEqual([e["event_no"] for e in session._events], [1, 2, 3])
        self.assertEqual(session.recovery_view(0)["next_event_no"], 4)


class RecoveryViewTest(unittest.IsolatedAsyncioTestCase):
    async def test_view_is_player_scoped_and_numbers_public_events(self):
        session = GameSession("classic", {"enabled": False}, session_id="view-test",
                              seed=7, locale="zh-CN", player_role="seer")
        await session._step_setup()
        view = session.recovery_view(0)

        self.assertEqual(view["init"]["type"], "init")
        self.assertEqual(view["private"]["role"], "seer")
        self.assertIn("seer_results", view["private"])
        self.assertFalse(view["finished"])
        # Public catch-up carries only public event types, each numbered, and
        # never a seat's private result (those live in ``private`` only).
        for pe in view["public_events"]:
            self.assertIsInstance(pe["event_no"], int)
            self.assertIn(pe["type"],
                          ("speech", "narration", "ballots", "death", "flip", "exile"))

    async def test_pending_action_and_number_are_re_presented(self):
        session = GameSession("classic", {"enabled": False}, session_id="pending-test")

        async def waiting_game():
            await session.ask_player("vote", {"candidates": [{"pos": 3}]})

        session._play = waiting_game
        # The stream starts the game task; the emitted request is then consumed.
        stream = session.events(after=0)
        request = await anext(stream)
        self.assertEqual(request["type"], "request")
        self.assertEqual(request["event_no"], 1)
        await stream.aclose()

        view = session.recovery_view(0)
        self.assertEqual(view["pending"]["kind"], "vote")
        self.assertEqual(view["pending"]["event_no"], 1)
        self.assertEqual(view["next_event_no"], 2)
        session.abandon()

    async def test_private_results_are_re_presented_separately(self):
        session = GameSession("classic", {"enabled": False}, session_id="priv-test")
        session.emit({"type": "private", "text": "你查验了 3 号，是狼人。"})
        view = session.recovery_view(0)

        # The seat's own private result line is re-renderable after reattach...
        self.assertEqual([e["text"] for e in view["private_events"]],
                         ["你查验了 3 号，是狼人。"])
        # ...and is never duplicated into the public transcript.
        self.assertNotIn("private", [e["type"] for e in view["public_events"]])
        session.abandon()


class ReconnectEndpointTest(unittest.TestCase):
    def test_rejoin_and_leave_endpoints(self):
        from werewolf_web.run import GAMES, app
        with TestClient(app) as client:
            start = client.post("/api/start", json={"board_id": "classic",
                                                    "llm": {"enabled": False},
                                                    "locale": "zh-CN"})
            self.assertEqual(start.status_code, 200)
            game_id = start.json()["game_id"]
            self.assertIn(game_id, GAMES)

            # Rejoin before the game starts returns a minimal, player-scoped view.
            rejoin = client.get("/api/rejoin", params={"game_id": game_id,
                                                       "last_event_no": 0})
            self.assertEqual(rejoin.status_code, 200)
            self.assertTrue(rejoin.json()["ok"])
            view = rejoin.json()["view"]
            self.assertIsNone(view["init"])
            self.assertIsNone(view["private"])
            self.assertEqual(view["next_event_no"], 1)

            # Leave removes the game from the registry.
            leave = client.post("/api/leave", json={"game_id": game_id})
            self.assertEqual(leave.status_code, 200)
            self.assertEqual(leave.json(), {"ok": True})
            self.assertNotIn(game_id, GAMES)

            # Rejoin after leave is a 404.
            self.assertEqual(client.get("/api/rejoin",
                                        params={"game_id": game_id}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
