import unittest
from werewolf_web.offline_dialogue import shortlist
from werewolf_web.social_actions import make


class ReplyMenuTest(unittest.TestCase):
    def test_reply_intents_not_collapsed_into_one_topic(self):
        choices = [{"id": kind, "topic": "direct_reply",
                    "speech": {"social_action": make(kind)}}
                   for kind in ("explain_stance", "reserve_judgment", "request_basis")]
        choices.append({"id": "wait"})
        self.assertEqual([c["id"] for c in shortlist(choices, answering=True)],
                         ["explain_stance", "reserve_judgment", "request_basis"])
        self.assertLessEqual(len(shortlist(choices, answering=True)) + 1, 4)
        self.assertEqual(shortlist(choices)[-1]["id"], "wait")
