"""§5.3 budget-commit semantics: the reservation is durable *before* the call.

Shawn's repro: `_npc_call()` checkpointed first and only the actual call
(`complete()` → `_reserve()`) incremented `calls`, so a crash mid-request left
`calls=1` in memory but `calls=0` on disk — restore wiped one attempt's budget.
The fix moves the reservation in front of the pre-call checkpoint.  A restore
now validates + restores config and budget first, then *persists* the preflight
reservation, then runs the liveness check — so the preflight's own spend is on
disk before the network call, and a successful restore leaves ``verified=True``.
"""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from werewolf_web import checkpoint as cp
from werewolf_web.ai.decision_runtime import ModelTurnError
from werewolf_web.checkpoint import load_checkpoint
from werewolf_web.run import GameSession


class _ReservingPlanner:
    """Minimal runtime stand-in: reserve() increments before the call."""

    backend = "api"
    verified = True

    def __init__(self, calls=0):
        self.calls = calls
        self.max_calls = 240
        self.model = "test-model"
        self.timeout = 60.0

    def reserve(self):
        if self.calls >= self.max_calls:
            raise ModelTurnError("Model call budget exhausted; no offline substitution.")
        self.calls += 1

    def snapshot(self):
        return {"schema_version": 1, "backend": "api", "model": self.model,
                "max_calls": self.max_calls, "timeout": self.timeout, "calls": self.calls}

    def restore(self, data):
        self.calls = data["calls"]
        # Liveness is transient, matching the real runtimes: a restored runtime
        # must re-run preflight before the game can call the model again.
        self.verified = False

    def public_status(self):
        return {"mode": "model_decisions", "backend": "api",
                "calls": self.calls, "max_calls": self.max_calls}


class ReservationCommitTest(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_is_on_disk_before_the_call_runs(self):
        planner = _ReservingPlanner()
        session = GameSession("classic", {"enabled": False}, session_id="budget-commit",
                              planner=planner)
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            seen = {}

            def call(*args, **kwargs):
                # By the time the external request runs, reserve() + the pre-call
                # checkpoint have already happened, so the consumed attempt is on
                # disk even if the process dies right now.
                seen["disk_calls_at_call_time"] = load_checkpoint(
                    session.checkpoint_path)["planner"]["calls"]
                return {"target": 3}

            result = await session._npc_call(Mock(side_effect=call))
            self.assertEqual(result, {"target": 3})
            self.assertEqual(seen["disk_calls_at_call_time"], 1)
            self.assertEqual(planner.calls, 1)
            self.assertEqual(load_checkpoint(session.checkpoint_path)["planner"]["calls"], 1)
            entry = session.decision_log[0]
            self.assertEqual(entry["attempts"][-1]["calls_before"], 0)
            self.assertEqual(entry["attempts"][-1]["calls_after"], 1)

    async def test_a_failed_call_still_persists_its_reservation(self):
        planner = _ReservingPlanner()
        session = GameSession("classic", {"enabled": False}, session_id="budget-fail",
                              planner=planner)
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            task = asyncio.create_task(
                session._npc_call(Mock(side_effect=ModelTurnError("mid-request crash"))))
            try:
                while True:
                    event = await asyncio.wait_for(session.event_q.get(), 2)
                    if event["type"] == "request" and event["kind"] == "model_retry":
                        break
                # The reservation survived the failure on disk.
                self.assertEqual(load_checkpoint(session.checkpoint_path)["planner"]["calls"], 1)
                self.assertEqual(planner.calls, 1)
                self.assertEqual(session.decision_log[0]["attempts"][-1]["outcome"], "error")
            finally:
                task.cancel()


class RestoreGameBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_preserves_the_preflight_consumption(self):
        from werewolf_web import run
        sid = "restore-preflight-budget"

        class _PreflightingPlanner(_ReservingPlanner):
            def __init__(self):
                super().__init__(calls=0)
                self.verified = False

            def preflight_check(self):
                self.verified = True

        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                                locale="zh-CN", player_role="seer", planner=_ReservingPlanner())
                a.checkpoint_path = cp.checkpoint_path(sid)
                await a._step_setup()
                a.planner.calls = 5
                a._checkpoint()
                self.assertNotIn(sid, run.GAMES)

                with patch.object(run, "create_runtime", return_value=_PreflightingPlanner()):
                    runner = await run.restore_game(sid)
                self.assertIsNotNone(runner)
                # 5 restored from the snapshot + 1 reserved for the liveness check.
                self.assertEqual(runner.planner.calls, 6)
                # The reservation is durable *before* the liveness check runs, so
                # a crash between reserve() and preflight_check() still restores
                # calls=6 on disk — and a successful restore leaves the runtime
                # verified, not clobbered back to False.
                disk_calls = load_checkpoint(cp.checkpoint_path(sid))["planner"]["calls"]
                self.assertEqual(disk_calls, 6)
                self.assertTrue(runner.planner.verified)
            finally:
                cp.CHECKPOINTS_DIR = old
                run.GAMES.pop(sid, None)


if __name__ == "__main__":
    unittest.main()
