import unittest
from copy import deepcopy
from unittest.mock import patch

from werewolf_web.session import GameSession
from werewolf_web.night_review import capture, render
from werewolf_web.game.models import GameEvent


class NightReviewTest(unittest.IsolatedAsyncioTestCase):
    def make_session(self):
        return GameSession("classic", {"enabled": False}, seed=7)

    async def test_private_until_endgame_and_restores(self):
        session = self.make_session()
        await session._step_setup()
        session.night_audit = [capture(1, {"wolves": {"target": 10},
                                               "witch": {"save": None, "poison": 10}},
                                      [GameEvent(type="death", seat=10, text="dead",
                                                 data={"cause": "poison"})])]
        self.assertEqual(render(session), "")
        self.assertNotIn("night_audit", session.recovery_view())
        restored = self.make_session()
        restored.restore(session.snapshot())
        self.assertEqual(restored.night_audit, session.night_audit)
        restored.night_audit[0]["actions"]["wolves"]["target"] = 2
        self.assertEqual(session.night_audit[0]["actions"]["wolves"]["target"], 10)
        session.engine.winner = "god"
        with patch.object(session, "_write_review"):
            await session._step_endgame()
        text = render(session)
        self.assertIn("女巫毒杀", text)
        self.assertIn("毒药: #10", text)
        self.assertTrue(any("夜间行动与死因" in e.get("text", "")
                            for e in session.recovery_view()["public_events"]))

    async def test_old_snapshot_and_invalid_snapshot(self):
        session = self.make_session()
        await session._step_setup()
        snapshot = session.snapshot()
        snapshot.pop("night_audit")
        session.restore(snapshot)
        self.assertEqual(session.night_audit, [])
        before = session.snapshot()
        invalid = deepcopy(before)
        invalid["night_audit"] = [{"night": True, "actions": {}, "deaths": []}]
        with self.assertRaises(ValueError):
            session.restore(invalid)
        self.assertEqual(before, session.snapshot())
        session.finished = True
        session.engine.winner = "god"
        self.assertIn("无法还原", render(session))

    async def test_settlement_recorded_once_and_not_public(self):
        session = self.make_session()
        await session._step_setup()
        session.engine.start_night()
        session._step_state["actions"] = {"wolves": {"target": None}}
        with patch.object(session, "_post_death_triggers"):
            await session._step_resolve_night()
            await session._step_resolve_night()
        self.assertEqual(len(session.night_audit), 1)
        self.assertEqual(render(session), "")
        self.assertFalse(any("夜间行动与死因" in e.get("text", "")
                             for e in session.recovery_view()["public_events"]))
