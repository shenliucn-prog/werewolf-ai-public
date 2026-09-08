"""§7 GameSession.restore validate-then-apply (atomic restore).

The review flagged that ``restore()`` mutated live objects one-by-one — engine,
then llm, then planner, then public record / conjecture / agents — and only
validated late fields (the event ledger, agent entry shapes) at the end.  A
corrupt ledger, or a corrupt agent snapshot, therefore left a half-restored
session.  The fix validates the *entire* snapshot against throwaway copies of
the live components before any attribute on ``self`` is touched, so any defect —
however deep — raises with the session unchanged.
"""
import unittest

from werewolf_web.run import GameSession


class AtomicRestoreTest(unittest.IsolatedAsyncioTestCase):
    async def _seeded_snapshot(self) -> dict:
        a = GameSession("classic", {"enabled": False}, session_id="atomic-restore-src",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()
        return a.snapshot()

    def _dst(self) -> GameSession:
        return GameSession("classic", {"enabled": False}, session_id="atomic-restore-dst",
                           seed=99, locale="zh-CN", player_role="civilian")

    async def test_valid_snapshot_restores_fully(self):
        snap = await self._seeded_snapshot()
        b = self._dst()
        b.restore(snap)
        self.assertEqual(b._step, snap["step"])
        self.assertEqual(b.engine.night_count, snap["engine"]["night_count"])
        self.assertEqual([e["event_no"] for e in b._events],
                         [e["event_no"] for e in snap["events"]])
        self.assertEqual(set(b.agents), set(snap["agents"]))

    async def test_corrupt_event_ledger_leaves_session_unchanged(self):
        """A late-in-the-old-code failure must not touch engine/llm/agents."""
        snap = await self._seeded_snapshot()
        b = self._dst()
        before = b.snapshot()
        snap["events"] = snap["events"][:-1]   # now len(events) != event_no
        with self.assertRaises(ValueError):
            b.restore(snap)
        self.assertEqual(b.snapshot(), before)
        self.assertEqual(b._event_no, 0)
        self.assertEqual(b.agents, {})

    async def test_corrupt_agent_snapshot_leaves_session_unchanged(self):
        """A deep component failure (agents, rebuilt after engine/llm/planner in
        the old code) must also leave the session untouched."""
        snap = await self._seeded_snapshot()
        b = self._dst()
        before = b.snapshot()
        name = next(iter(snap["agents"]))
        snap["agents"][name]["role_cn"] = 123   # require_str -> ValueError
        with self.assertRaises(ValueError):
            b.restore(snap)
        self.assertEqual(b.snapshot(), before)
        self.assertEqual(b.agents, {})

    async def test_corrupt_engine_snapshot_leaves_session_unchanged(self):
        snap = await self._seeded_snapshot()
        b = self._dst()
        before = b.snapshot()
        snap["engine"]["phase"] = "bogus-phase"
        with self.assertRaises(ValueError):
            b.restore(snap)
        self.assertEqual(b.snapshot(), before)
        self.assertEqual(b.engine.phase, "prep")


if __name__ == "__main__":
    unittest.main()
