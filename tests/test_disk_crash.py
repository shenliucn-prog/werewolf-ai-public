"""§8.3 / Phase 4: real on-disk crash → recreate → continue.

The earlier fault tests round-trip ``snapshot()``/``restore()`` in one process.
These prove the same guarantees across an actual process-death boundary: the
authoritative checkpoint is read back from disk, a *fresh* ``GameSession`` (and,
for model games, a fresh runtime) is rehydrated via the production ``restore_game``
entry, and play continues from the exact crash position — no re-applied night,
no re-consumed attempt, no missing budget.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import checkpoint as cp
from werewolf_web import run
from werewolf_web.checkpoint import load_checkpoint
from werewolf_web.run import GameSession

from tests.test_budget_commit import _ReservingPlanner
from tests.test_faults import _SimulatedCrash


class DiskCrashRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_offline_crash_resumes_mid_resolve_night_from_disk(self):
        sid = "disk-crash-resolve"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                await a._step_setup()
                await a._step_witch_rule()
                await a._step_night()          # gather -> resolve_night
                self.assertEqual(a._step, "resolve_night")

                async def crash():
                    raise _SimulatedCrash()
                a._post_death_triggers = crash
                with self.assertRaises(_SimulatedCrash):
                    await a._step_resolve_night()

                # The settlement committed to disk before the crash: the marker
                # is durable, ``actions`` is gone.
                on_disk = load_checkpoint(cp.checkpoint_path(sid))
                self.assertIn("night_events", on_disk["step_state"])
                self.assertNotIn("actions", on_disk["step_state"])

                # Process restart: rehydrate a fresh session from the save.
                b = await run.restore_game(sid)
                self.assertIsNotNone(b)
                self.assertEqual(b._step, "resolve_night")
                self.assertIn("night_events", b._step_state)
                self.assertNotIn("actions", b._step_state)

                # Continue from the crash position: settlement is skipped, not
                # re-applied (no KeyError, no double resolve_night).
                night_count = b.engine.night_count
                history_len = len(b.engine.history)

                async def noop():
                    pass
                b._post_death_triggers = noop
                await b._step_resolve_night()
                self.assertEqual(b.engine.night_count, night_count)
                self.assertEqual(len(b.engine.history), history_len)
                self.assertEqual(b._step, "day_start")
            finally:
                cp.CHECKPOINTS_DIR = old
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)

    async def test_model_crash_preserves_reservation_across_restart(self):
        """A crash mid-request must survive a real runtime recreation: the
        reserved attempt is on disk, and rehydration + the liveness preflight
        stack on top without losing the reservation."""
        sid = "disk-crash-budget"

        class _PreflightingPlanner(_ReservingPlanner):
            def __init__(self):
                super().__init__(calls=0)
                self.verified = False

            def preflight_check(self):
                self.verified = True

        def boom():
            raise _SimulatedCrash()

        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                planner=_ReservingPlanner())
                a.checkpoint_path = cp.checkpoint_path(sid)
                await a._step_setup()
                a._current_step = "vote"

                with self.assertRaises(_SimulatedCrash):
                    await a._npc_call(boom)

                # Reservation is durable on disk before the call ran.
                self.assertEqual(
                    load_checkpoint(cp.checkpoint_path(sid))["planner"]["calls"], 1)

                # Process restart: recreate the runtime, rehydrate, continue.
                with patch.object(run, "create_runtime",
                                  return_value=_PreflightingPlanner()):
                    b = await run.restore_game(sid)
                self.assertIsNotNone(b)
                # 1 restored reservation + 1 liveness preflight = 2, not 0.
                self.assertEqual(b.planner.calls, 2)
                # A successful restore leaves the runtime verified, not clobbered.
                self.assertTrue(b.planner.verified)
                # The uncommitted decision is not treated as committed: it has
                # no committed entry to replay, so a resume re-issues it.
                self.assertFalse(any(d["committed"] for d in b.decision_log))
            finally:
                cp.CHECKPOINTS_DIR = old
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)


class RealProcessTerminationTest(unittest.IsolatedAsyncioTestCase):
    """A *real* process death — ``os._exit``, no finally, no graceful teardown —
    followed by rehydration in a fresh process via the production entry point."""

    async def test_resume_after_real_process_death(self):
        sid = "real-process-death"
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as directory:
            marker = os.path.join(directory, "marker.txt")
            script = (
                "import asyncio, os, sys\n"
                "from werewolf_web import checkpoint as cp\n"
                "from werewolf_web.run import GameSession\n"
                "async def main():\n"
                "    cp.CHECKPOINTS_DIR = sys.argv[1]\n"
                "    game_id = sys.argv[2]\n"
                "    marker = sys.argv[3]\n"
                "    s = GameSession('classic', {'enabled': False}, session_id=game_id,\n"
                "                    seed=7, locale='zh-CN', player_role='civilian',\n"
                "                    checkpoint_path=cp.checkpoint_path(game_id))\n"
                "    await s._step_setup()\n"
                "    await s._step_witch_rule()\n"
                "    await s._step_night()\n"
                "    await s._step_resolve_night()\n"
                "    with open(marker, 'w') as f:\n"
                "        f.write(str(s.engine.night_count) + ' ' + str(len(s.engine.history)))\n"
                "    os._exit(1)  # abrupt death: no finally, no further writes\n"
                "asyncio.run(main())\n"
            )
            env = {**os.environ,
                   "PYTHONPATH": repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")}
            proc = subprocess.run([sys.executable, "-c", script, directory, sid, marker],
                                  env=env, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0, proc.stderr)
            with open(marker) as f:
                night_count, history_len = map(int, f.read().split())

            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                b = await run.restore_game(sid)
                self.assertIsNotNone(b)
                # Rehydrated state matches the moment just before the process died.
                self.assertEqual(b.engine.night_count, night_count)
                self.assertEqual(len(b.engine.history), history_len)
                # Continue from the crash position: settlement is skipped, not
                # re-applied, and the death-trigger chain is not re-run.
                await b._step_resolve_night()
                self.assertEqual(b.engine.night_count, night_count)
                self.assertEqual(len(b.engine.history), history_len)
                self.assertEqual(b._step, "day_start")
            finally:
                cp.CHECKPOINTS_DIR = old
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)


class DeathTriggerChainTest(unittest.IsolatedAsyncioTestCase):
    """The death-trigger chain (hunter + wolf_king gun) is *not* stubbed out:
    it runs for real and is re-entrant — a restore re-runs it idempotently."""

    async def test_full_death_chain_is_recoverable(self):
        a = GameSession("wolf_king", {"enabled": False}, session_id="death-chain",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()
        hunter = next(s for s in a.engine.seats.values() if s.role == "hunter")
        wolf_king = next(s for s in a.engine.seats.values() if s.role == "wolf_king")
        self.assertFalse(hunter.is_player)   # the human is a civilian
        hunter.alive = False
        hunter.death_cause = "knife"
        wolf_king.alive = False
        wolf_king.death_cause = "exile"

        # The real chain fires (and drains any knock-on deaths).
        await a._post_death_triggers()
        self.assertIn(hunter.pos, a._triggered)
        self.assertIn(wolf_king.pos, a._triggered)
        dead_after = sorted(s.pos for s in a.engine.seats.values() if not s.alive)

        # Restore and re-run: no untriggered seat remains, so nothing double-fires.
        b = GameSession("wolf_king", {"enabled": False}, session_id="death-chain",
                        seed=99, locale="zh-CN", player_role="civilian")
        b.restore(a.snapshot())
        await b._post_death_triggers()
        self.assertEqual(sorted(s.pos for s in b.engine.seats.values() if not s.alive),
                         dead_after)
        self.assertIn(hunter.pos, b._triggered)
        self.assertIn(wolf_king.pos, b._triggered)


if __name__ == "__main__":
    unittest.main()
