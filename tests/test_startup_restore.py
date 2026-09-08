"""game_id-keyed restore on startup + storage hardening (§7).

After a process restart ``GAMES`` is empty; a rejoin/stream for a known
``game_id`` rehydrates the session from its on-disk checkpoint — same role map,
no re-deal, and the same numbered event ledger (no missing/duplicate events).
"""
import asyncio
import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from werewolf_web import checkpoint as cp
from werewolf_web.run import GameSession, GAMES, app, restore_game


class LedgerPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_event_ledger_survives_round_trip(self):
        a = GameSession("classic", {"enabled": False}, session_id="ledger-rt",
                        seed=7, locale="zh-CN", player_role="seer")
        await a._step_setup()
        a.emit({"type": "narration", "text": "night falls"})
        a.emit({"type": "private", "text": "你查验了 3 号，是狼人。"})
        snapshot = a.snapshot()
        self.assertEqual(snapshot["event_no"], 3)
        self.assertEqual([e["event_no"] for e in snapshot["events"]], [1, 2, 3])

        b = GameSession("classic", {"enabled": False}, session_id="ledger-rt",
                        seed=99, locale="zh-CN", player_role="seer")
        b.restore(snapshot)
        self.assertEqual(b._event_no, 3)
        self.assertEqual(b._init_event["type"], "init")
        self.assertEqual([e["event_no"] for e in b._events], [1, 2, 3])
        self.assertEqual([e["text"] for e in b.recovery_view(0)["private_events"]],
                         ["你查验了 3 号，是狼人。"])
        self.assertEqual(b.recovery_view(0)["next_event_no"], 4)

    async def test_corrupt_ledger_is_rejected(self):
        a = GameSession("classic", {"enabled": False}, session_id="bad-ledger", seed=7)
        await a._step_setup()

        # Ledger length must match the counter, and numbering must be 1..N.
        length_mismatch = a.snapshot()
        length_mismatch["event_no"] = 5
        renumbered = a.snapshot()
        renumbered["events"][0]["event_no"] = 99
        for snapshot in (length_mismatch, renumbered):
            b = GameSession("classic", {"enabled": False}, session_id="bad-ledger")
            with self.assertRaises(ValueError):
                b.restore(snapshot)


class GameIdKeyTest(unittest.TestCase):
    def test_checkpoint_path_rejects_unsafe_ids(self):
        for bad in ("../etc/passwd", "a/b", "..", "a..b", "has space", "", "A" * 65):
            with self.assertRaises(ValueError):
                cp.checkpoint_path(bad)
        self.assertTrue(cp.checkpoint_path("abc123_-").endswith("abc123_-.json"))


class StartupRestoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_game_rehydrates_from_checkpoint(self):
        sid = "restore-on-startup-test"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                                locale="zh-CN", player_role="seer",
                                checkpoint_path=cp.checkpoint_path(sid))
                await a._step_setup()
                roles = {p: s.role for p, s in a.engine.seats.items()}
                a._checkpoint()
                self.assertNotIn(sid, GAMES)

                # Simulate a process restart: empty GAMES, restore from disk.
                runner = await restore_game(sid)
                self.assertIsNotNone(runner)
                self.assertIs(GAMES.get(sid), runner)
                self.assertEqual({p: s.role for p, s in runner.engine.seats.items()},
                                 roles)
                self.assertEqual(runner._step, "witch_rule")
                view = runner.recovery_view(0)
                self.assertEqual(view["init"]["type"], "init")
                self.assertEqual(view["private"]["role"], "seer")
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)

    async def test_restore_game_refuses_corrupt_save(self):
        sid = "corrupt-on-startup-test"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                                checkpoint_path=cp.checkpoint_path(sid))
                await a._step_setup()
                a._checkpoint()
                # Tamper with the payload without updating the checksum.
                path = cp.checkpoint_path(sid)
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                data["payload"]["engine"]["seats"] = []
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                self.assertIsNone(await restore_game(sid))
                self.assertNotIn(sid, GAMES)
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)

    async def test_restore_game_returns_none_for_unknown_or_mismatched_id(self):
        self.assertIsNone(await restore_game("no-such-game-123"))

        sid = "mismatched-session-id"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id="other-id",
                                seed=7, checkpoint_path=cp.checkpoint_path(sid))
                await a._step_setup()
                a._checkpoint()
                # The checkpoint's session_id differs from its file key: refuse.
                self.assertIsNone(await restore_game(sid))
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)


class RejoinEndpointRestoreTest(unittest.TestCase):
    def test_rejoin_restores_after_process_restart(self):
        sid = "rejoin-restore-endpoint"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                async def seed_game():
                    a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                                    locale="zh-CN", player_role="seer",
                                    checkpoint_path=cp.checkpoint_path(sid))
                    await a._step_setup()
                    a._checkpoint()
                asyncio.run(seed_game())
                self.assertNotIn(sid, GAMES)

                with TestClient(app) as client:
                    response = client.get("/api/rejoin",
                                          params={"game_id": sid, "last_event_no": 0})
                    self.assertEqual(response.status_code, 200)
                    view = response.json()["view"]
                    self.assertEqual(view["init"]["type"], "init")
                    self.assertEqual(view["private"]["role"], "seer")
                    self.assertIn(sid, GAMES)
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)


if __name__ == "__main__":
    unittest.main()
