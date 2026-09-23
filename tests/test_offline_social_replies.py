import json
import unittest

from werewolf_web.offline_dialogue import reply_choices
from werewolf_web.offline_game import OfflineSession, action_choices


class ReplyChoicesTest(unittest.TestCase):
    def test_attributed_stance_is_not_a_new_accusation(self):
        events = [{"type": "speech", "event_no": 1, "name": "A", "accuse": "C"},
                  {"type": "speech", "event_no": 2, "name": "B", "question_to": "A"}]
        for locale in ("en", "zh-CN"):
            choices = reply_choices(events, "A", "B", locale)
            self.assertEqual(choices[0]["action"]["reply_to"], 2)
            self.assertEqual(choices[0]["action"]["kind"], "explain_stance")
            self.assertTrue(all(c["speech"]["accuse"] is None for c in choices))
            self.assertTrue(all(c["speech"]["defend"] is None for c in choices))
            self.assertTrue(all(c["speech"]["question_to"] is None for c in choices))
            self.assertEqual(choices, reply_choices(json.loads(json.dumps(events)), "A", "B", locale))

    def test_unrelated_question_and_quoted_text_do_not_create_stance(self):
        events = [{"type": "speech", "event_no": 1, "name": "A", "text": "B suspects C"},
                  {"type": "speech", "event_no": 2, "name": "B", "question_to": "D"}]
        self.assertEqual(reply_choices(events, "A", "B", "en"), [])
        events[-1]["question_to"] = "A"
        self.assertEqual([c["action"]["kind"] for c in reply_choices(events, "A", "B", "en")],
                         ["reserve_judgment"])

    def test_durable_question_sources_work_without_speech_target_field(self):
        events = [{"type": "speech", "event_no": 8, "name": "B", "text": "Why?"}]
        choices = reply_choices(events, "A", "B", "en", [{"from": "B", "event_no": 8}])
        self.assertEqual(choices[0]["action"]["reply_to"], 8)
        self.assertEqual(reply_choices(events, "A", "B", "en", [{"from": "C", "event_no": 8}]), [])


class ReplyIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_menu_and_agent_reply_survive_restore(self):
        session = OfflineSession(seed=23, player_role="civilian", locale="en")
        await session._step_setup()
        player = session.engine.player_seat()
        agent = next(iter(session.agents.values()))
        session.emit({"type": "speech", "name": agent.name, "seat": agent.seat.pos,
                      "question_to": player.name, "text": "Explain your position."})
        before = action_choices(session, "table_answer", {"from": agent.name})
        self.assertTrue(any(c["id"].startswith("reply:") and c["suggested"] for c in before))
        saved = json.loads(json.dumps(session.snapshot()))
        restored = OfflineSession(seed=99, player_role="civilian", locale="en")
        restored.restore(saved)
        self.assertEqual(before, action_choices(restored, "table_answer", {"from": agent.name}))
        session.emit({"type": "speech", "name": player.name, "seat": player.pos,
                      "question_to": agent.name, "text": "Why?"})
        response = agent.table_reply(player.name)
        self.assertIn(player.name, response.text)
        self.assertIn("record", response.text)
        self.assertIsNone(response.question_to)
