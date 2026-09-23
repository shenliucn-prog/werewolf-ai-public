from copy import deepcopy
import unittest
from werewolf_web.social_actions import make, validate_public
from werewolf_web.offline_game import OfflineSession, speech_choices
from werewolf_web.ai.brain import Speech


class PublicActionTest(unittest.TestCase):
    def test_private_future_and_wrong_speaker_sources_rejected(self):
        events = [{"type": "private", "event_no": 1},
                  {"type": "speech", "event_no": 2, "name": "A"}]
        for action in (make("cite", sources=[1]), make("cite", sources=[3]),
                       make("explain_stance", "B", [2], 2), make("support", "stranger")):
            with self.assertRaises(ValueError):
                validate_public(action, events, {"A", "B"})
        validate_public(make("explain_stance", "A", [2], 2), events, {"A", "B"})
        validate_public(None, [], set())  # legacy speech


class ActionIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_live_action_and_restore_leave_state_unchanged(self):
        session = OfflineSession(seed=4)
        await session._step_setup()
        before = session.snapshot()
        with self.assertRaises(ValueError):
            session._broadcast_speech(session.engine.player_seat(),
                Speech(text="Forged", social_action=make("cite", sources=[9999])))
        self.assertEqual(before, session.snapshot())
        bad = deepcopy(before)
        bad["events"].append({"type": "speech", "event_no": 999,
                              "social_action": make("cite", sources=[1000])})
        with self.assertRaises(ValueError):
            session.restore(bad)
        self.assertEqual(before, session.snapshot())

    async def test_citation_does_not_duplicate_accusation(self):
        session = OfflineSession(seed=4)
        await session._step_setup()
        seats = list(session.engine.seats.values())
        session.emit({"type": "speech", "name": seats[0].name, "text": "I suspect them.", "accuse": seats[1].name})
        options = [o for o in speech_choices(session, session.engine.player_seat()) if o["id"].startswith("cite:")]
        self.assertTrue(options)
        for option in options:
            self.assertIsNone(option["speech"]["accuse"])
            self.assertIsNone(option["speech"]["defend"])
