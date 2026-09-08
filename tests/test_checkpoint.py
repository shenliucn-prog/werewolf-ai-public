"""Session checkpointing (§5.2 / §7): atomic store, corruption handling,
session-level snapshot/restore round-trip, and resume-from-cursor."""
import asyncio
import json
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from werewolf_web.checkpoint import load_checkpoint, save_checkpoint
from werewolf_web.run import GameSession


class _FakePlanner:
    """A minimal, symmetric DecisionRuntime stand-in for round-trip tests."""

    backend = "api"
    verified = True

    def __init__(self):
        self.calls = 0
        self.max_calls = 240
        self.timeout = 60.0
        self.model = "test-model"
        self.base_url = "http://local.example/v1"
        self.temperature = 0.7
        self.reasoning_effort = ""
        self.reasoning_param = ""
        self.enabled = True

    def snapshot(self):
        return {"schema_version": 1, "backend": "api", "model": self.model,
                "max_calls": self.max_calls, "timeout": self.timeout,
                "calls": self.calls, "base_url": self.base_url,
                "temperature": self.temperature,
                "reasoning_effort": self.reasoning_effort,
                "reasoning_param": self.reasoning_param, "enabled": self.enabled}

    def restore(self, data):
        self.calls = data["calls"]
        self.max_calls = data["max_calls"]
        self.model = data["model"]

    def public_status(self):
        return {"mode": "model_decisions", "backend": "api",
                "calls": self.calls, "max_calls": self.max_calls}


class CheckpointStoreTest(unittest.TestCase):
    def test_round_trip_and_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "game.json")
            payload = {"schema_version": 1, "hello": "世界", "n": 7}
            save_checkpoint(path, payload)
            self.assertFalse(os.path.exists(path + ".tmp"))
            self.assertEqual(load_checkpoint(path), payload)

    def test_int_keyed_payload_does_not_fail_its_own_checksum(self):
        """Shawn's repro: json turns int keys into strings, and sort order flips
        ("2" before "10" numerically, "10" before "2" lexicographically), so an
        int-keyed payload used to re-read and fail its own checksum."""
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "game.json")
            payload = {"votes": {2: 1, 10: 2}}
            save_checkpoint(path, payload)
            loaded = load_checkpoint(path)   # must not raise checksum mismatch
            self.assertEqual(loaded["votes"], {"2": 1, "10": 2})

    def test_file_and_directory_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sub", "game.json")
            save_checkpoint(path, {"schema_version": 1})
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
            dirmode = stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode)
            self.assertEqual(dirmode, 0o700)

    def test_corruption_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "game.json")
            save_checkpoint(path, {"schema_version": 1, "role": "seer"})
            # Tamper with the payload without updating the checksum.
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["payload"]["role"] = "witch"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            with self.assertRaises(ValueError):
                load_checkpoint(path)

    def test_truncation_and_unknown_version_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "game.json")
            save_checkpoint(path, {"schema_version": 1})
            # Truncate the authoritative save.
            with open(path, "r", encoding="utf-8") as handle:
                blob = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(blob[: len(blob) // 2])
            with self.assertRaises(ValueError):
                load_checkpoint(path)

            # Unknown schema version is refused, not silently misread.
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schema_version": 999, "checksum": "x", "payload": {}}, handle)
            with self.assertRaises(ValueError):
                load_checkpoint(path)


class SessionSnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_round_trip_preserves_identity(self):
        sid = "test-roundtrip-legacy"
        a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                        locale="zh-CN", player_role="seer")
        # Run the deal step directly (no human input in setup).
        await a._step_setup()
        snapshot = a.snapshot()

        b = GameSession("classic", {"enabled": False}, session_id=sid, seed=99,
                        locale="zh-CN", player_role="seer")
        b.restore(snapshot)

        self.assertEqual(b.snapshot(), snapshot)
        self.assertEqual(b.engine.public_state(), a.engine.public_state())
        self.assertEqual({p: s.role for p, s in b.engine.seats.items()},
                         {p: s.role for p, s in a.engine.seats.items()})
        self.assertEqual(b.engine.player_view()["role"], "seer")

    async def test_model_round_trip_preserves_identity(self):
        sid = "test-roundtrip-model"
        a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                        locale="zh-CN", player_role="seer", planner=_FakePlanner())
        await a._step_setup()
        snapshot = a.snapshot()
        self.assertIsNotNone(snapshot["planner"])

        b = GameSession("classic", {"enabled": False}, session_id=sid, seed=99,
                        locale="zh-CN", player_role="seer", planner=_FakePlanner())
        b.restore(snapshot)

        self.assertEqual(b.snapshot(), snapshot)
        self.assertEqual({p: s.role for p, s in b.engine.seats.items()},
                         {p: s.role for p, s in a.engine.seats.items()})
        # Agents are rebuilt as model-driven and hold the restored planner.
        self.assertTrue(b.agents)
        for name, agent in b.agents.items():
            self.assertIs(agent.planner, b.planner)

    async def test_resume_continues_from_restored_cursor(self):
        sid = "test-resume-cursor"
        a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                        locale="zh-CN", player_role="seer")
        await a._step_setup()  # deals; cursor -> witch_rule
        snapshot = a.snapshot()

        b = GameSession("classic", {"enabled": False}, session_id=sid, seed=99,
                        locale="zh-CN", player_role="seer")
        b.restore(snapshot)
        self.assertEqual(b._step, "witch_rule")

        task = asyncio.create_task(b._play())
        try:
            events = []
            while True:
                event = await asyncio.wait_for(b.event_q.get(), 2)
                events.append(event)
                if event["type"] == "request":
                    break
            # No re-deal: the first event is NOT the init broadcast.
            self.assertNotIn("init", [e["type"] for e in events])
            self.assertEqual(event["kind"], "night")
            self.assertEqual(event["data"]["role_key"], "seer")
        finally:
            task.cancel()

    async def test_checkpoint_writes_committed_decision_log(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = GameSession("classic", {"enabled": False}, session_id="cp-log",
                              planner=planner)
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            result = await session._npc_call(Mock(return_value={"target": 3}))
            self.assertEqual(result, {"target": 3})

            payload = load_checkpoint(session.checkpoint_path)
            log = payload["decision_log"]
            self.assertEqual(len(log), 1)
            self.assertTrue(log[0]["committed"])
            self.assertEqual(log[0]["result"], {"target": 3})
            self.assertEqual(log[0]["attempts"][-1]["outcome"], "accepted")


if __name__ == "__main__":
    unittest.main()
