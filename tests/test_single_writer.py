"""§7 single-writer constraint: concurrent reconnects restore one live instance.

Before the per-game lock, two simultaneous ``restore_game`` calls for the same
game_id both saw ``GAMES`` empty, each loaded the checkpoint, each ran its own
model preflight (two budget calls) and each registered its own ``GameSession`` —
leaving two live instances and a leak.  The lock + double-check makes the second
caller reuse the first caller's instance.
"""
import asyncio
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import checkpoint as cp, run
from werewolf_web.run import GameSession

from tests.test_budget_commit import _ReservingPlanner


class SingleWriterRestoreTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_restore_yields_one_instance_and_one_preflight(self):
        sid = "single-writer-restore"
        preflights = []
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                # Seed a model-game checkpoint so restore takes the planner path
                # (the only one that awaits, and thus the one that interleaves).
                a = GameSession("classic", {"enabled": False}, session_id=sid, seed=7,
                                locale="zh-CN", player_role="civilian",
                                planner=_ReservingPlanner())
                a.checkpoint_path = cp.checkpoint_path(sid)
                await a._step_setup()
                a._checkpoint()

                def make_planner(*args, **kwargs):
                    planner = _ReservingPlanner(calls=0)
                    planner.verified = False

                    def preflight_check():
                        preflights.append(1)
                        planner.verified = True
                    planner.preflight_check = preflight_check
                    return planner

                with patch.object(run, "create_runtime", side_effect=make_planner):
                    first, second = await asyncio.gather(
                        run.restore_game(sid), run.restore_game(sid))

                self.assertIsNotNone(first)
                self.assertIs(first, second)              # one live instance
                self.assertEqual(len(preflights), 1)      # one preflight, not two
            finally:
                cp.CHECKPOINTS_DIR = old
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)


if __name__ == "__main__":
    unittest.main()
