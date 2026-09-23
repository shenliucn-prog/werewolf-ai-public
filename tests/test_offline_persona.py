import unittest
from werewolf_web.offline_cast import BY_ID
from werewolf_web.offline_persona import PROFILE, reply_order, reaction_bias
from werewolf_web.offline_dialogue import choose_reaction
from werewolf_web.ai.brain import Style


class PersonaPolicyTest(unittest.TestCase):
    def test_all_thirty_have_explicit_priorities(self):
        self.assertEqual(set(PROFILE), set(BY_ID))
        self.assertEqual(len(PROFILE), 30)
        self.assertEqual(len({reply_order(key) for key in PROFILE}), 5)
        for key in PROFILE:
            self.assertEqual(set(reply_order(key)), {"request_basis", "explain_stance", "reserve_judgment"})

    def test_same_public_context_different_choices_not_different_evidence(self):
        options = [{"id": "report:thanks:2", "topic": "receive_good", "label": "Thanks"},
                   {"id": "report:probe:2", "topic": "receive_good", "label": "Explain"}]
        self.assertNotEqual(choose_reaction(options, [], Style(), character_id="acheng")["id"],
                            choose_reaction(options, [], Style(), character_id="xicao")["id"])
        for key in PROFILE:
            self.assertEqual(choose_reaction(options, [], Style(), character_id=key),
                             choose_reaction(options, [], Style(), character_id=key))
            self.assertLessEqual(reaction_bias(key, options[0]), .4)
