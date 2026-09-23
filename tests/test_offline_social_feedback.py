import json
import unittest

from werewolf_web.ai.brain import Speech, Style
from werewolf_web.social_actions import make
from werewolf_web.offline_social import relationships, feedback_choices
from werewolf_web.offline_game import OfflineSession


class SocialFeedbackTest(unittest.TestCase):
    def test_rapport_is_bounded_replayable_and_not_alignment(self):
        e = {"type": "speech", "name": "A", "day": 1, "event_no": 1,
             "social_action": make("support", "B")}
        once = relationships([e], "B", Style())
        self.assertEqual(once, relationships([e] * 20, "B", Style()))
        self.assertGreater(once["A"]["rapport"], 0)
        self.assertEqual(set(once["A"]), {"rapport", "openness"})

    def test_feedback_is_style_dependent_but_not_new_question(self):
        e = {"type": "speech", "name": "A", "day": 1, "event_no": 5,
             "social_action": make("explain_stance", "B", [2], 2)}
        friendly = feedback_choices([e], "B", Style(loyalty=.9), "en")
        wary = feedback_choices([e], "B", Style(caution=.9, aggression=.9), "en")
        self.assertNotEqual(friendly[0]["id"], wary[0]["id"])
        for option in friendly + wary:
            self.assertIsNone(option["speech"]["question_to"])
            self.assertIsNone(option["speech"]["accuse"])
        done = {"type": "speech", "name": "B", "day": 1, "social_action": friendly[0]["speech"]["social_action"]}
        self.assertEqual(feedback_choices([e, done], "B", Style(), "en"), [])
        self.assertEqual(feedback_choices([e, {"day": 2}], "B", Style(), "en"), [])


class SocialFeedbackIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_feedback_persisted_once_and_no_private_state_changed(self):
        session = OfflineSession(seed=23, locale="en")
        await session._step_setup()
        agent = next(iter(session.agents.values()))
        player = session.engine.player_seat()
        await session._publish_table_speech(player, Speech(text="I reserve judgment.",
            social_action=make("reserve_judgment", agent.name, [1], 1)), "clarification")
        await session._social_feedback()
        events = [e for e in session._events if e.get("talk_kind") == "social_feedback"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["social_action"]["target"], player.name)
        self.assertFalse(session.questions.pending)
        restored = OfflineSession(seed=0, locale="en")
        restored.restore(json.loads(json.dumps(session.snapshot())))
        before = len(restored._events)
        await restored._social_feedback()
        self.assertEqual(len(restored._events), before)
