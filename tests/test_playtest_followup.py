"""Synthetic public-only regressions; no local match transcript is published."""
import json
import unittest
from unittest.mock import Mock

from werewolf_web.ai.model_player import ModelNPCAgent
from werewolf_web.ai.model_context import statements_of_flipped_seers, fit_request_budget
from werewolf_web.observations import MODEL_INSTRUCTIONS


class PlaytestFollowupTest(unittest.TestCase):
    def rows(self):
        return [{"day": 1, "night": 1, "phase": "election", "event": {
            "type": "speech", "name": "seer-speaker", "seat": 9,
            "event_no": 2, "text": "I checked seat 1 on night 1: good."}}]

    def test_election_is_a_choice_not_an_imperative(self):
        agent = object.__new__(ModelNPCAgent)
        for withdraw in (False, True):
            for answer in (False, True):
                key = "withdraw" if withdraw else "up"
                agent.decide = Mock(return_value={key: answer})
                self.assertIs(agent.election_choice(withdraw), answer)
                args, kwargs = agent.decide.call_args
                self.assertTrue(args[0].startswith("decide whether"))
                self.assertEqual(set(kwargs["choice_meaning"]), {"true", "false"})
                self.assertIn("neither answer is prescribed", kwargs["considerations"])

    def test_old_seer_statement_survives_later_speech_window(self):
        rows = self.rows() + [{"day": 5, "event": {"type": "speech", "name": "other",
                "event_no": n, "text": "later"}} for n in range(3, 40)]
        items = statements_of_flipped_seers(rows, [("seer-speaker", "seer", False)])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["event_no"], 2)
        self.assertEqual(items[0]["text"], self.rows()[0]["event"]["text"])
        self.assertIn("attributed", items[0]["status"])
        self.assertEqual(items[0]["night"], 1)

    def test_unrevealed_claimant_is_not_certified(self):
        self.assertEqual(statements_of_flipped_seers(self.rows(), []), [])
        self.assertEqual(statements_of_flipped_seers(self.rows(), [("seer-speaker", "wolf", True)]), [])

    def test_private_result_is_not_read(self):
        rows = self.rows()
        rows[0]["event"]["type"] = "private"
        self.assertEqual(statements_of_flipped_seers(rows, [("seer-speaker", "seer", False)]), [])

    def test_evidence_is_bounded_and_budgeted(self):
        rows = self.rows() * 20
        rows[0]["event"]["text"] = "x" * 2000
        items = statements_of_flipped_seers(rows, [("seer-speaker", "seer", False)])
        self.assertEqual(len(items), 3)
        self.assertTrue(all(i["truncated"] and len(i["text"]) == 1200 for i in items))
        request = {"public_context": {"statements_of_flipped_seers": items}}
        fit_request_budget(request, 500)
        self.assertLessEqual(len(json.dumps(request)), 500)

    def test_temporal_contract_forbids_retrospective_first_night_reasons(self):
        self.assertIn("Night N precedes day N", MODEL_INSTRUCTIONS)
        self.assertIn("later speech cannot be the reason", MODEL_INSTRUCTIONS)
