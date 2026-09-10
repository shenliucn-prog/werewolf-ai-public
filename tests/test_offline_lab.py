"""Synthetic discussion fixtures, not real match transcripts."""
from copy import deepcopy
from itertools import product
import unittest

from werewolf_web.offline_lab import DiscussionLab, MOVES, PERSONAS, RECORDS, REPLIES, main


class OfflineLabTest(unittest.TestCase):
    def run_path(self, reply, move="move:challenge", vote="vote:skip", lang="zh-CN"):
        lab = DiscussionLab(lang)
        for action in (reply, move, vote):
            lab.submit(action)
        return lab

    def test_all_paths_finish_with_bounded_floor_and_public_sources(self):
        for reply, move, vote in product(REPLIES, MOVES, ("vote:2", "vote:3", "vote:4", "vote:5", "vote:skip")):
            lab = self.run_path(reply.id, move.id, vote)
            self.assertEqual(lab.stage, "done")
            self.assertEqual(lab.choices(), ())
            self.assertTrue(lab.answered)
            self.assertEqual(set(lab.votes), {1, 2, 3, 4, 5})
            self.assertEqual(sum(e["kind"] == "interruption" for e in lab.events), 1)
            self.assertEqual(sum(e["kind"] == "close" for e in lab.events), 1)
            self.assertEqual(sum(e["kind"] == "question" for e in lab.events), 1 + (move.kind == "question"))
            for event in lab.events:
                self.assertTrue(set(event["source_records"]) <= {r.number for r in RECORDS})
            for actor, target in lab.votes.items():
                self.assertNotEqual(actor, target)

    def test_evidence_and_refusal_change_subsequent_ballots(self):
        evidence = self.run_path("reply:evidence")
        refusal = self.run_path("reply:refuse")
        self.assertNotEqual(evidence.votes, refusal.votes)
        for p in PERSONAS:
            self.assertLess(evidence.scores[p.seat][1], refusal.scores[p.seat][1])
        self.assertEqual(refusal.votes[2], 1)
        self.assertNotEqual(evidence.votes[2], 1)

    def test_personalities_have_different_response_sensitivities(self):
        evidence = self.run_path("reply:evidence")
        admit = self.run_path("reply:admit")
        self.assertGreater(.55 - evidence.scores[3][1], .55 - evidence.scores[2][1])
        self.assertGreater(.55 - admit.scores[5][1], .55 - admit.scores[2][1])

    def test_accusation_and_support_are_not_cosmetic(self):
        accuse = self.run_path("reply:evidence", "move:accuse")
        support = self.run_path("reply:evidence", "move:support")
        self.assertNotEqual(accuse.votes, support.votes)
        for seat in (3, 4, 5):
            self.assertGreater(accuse.scores[seat][2], support.scores[seat][2])

    def test_question_alone_does_not_raise_suspicion(self):
        lab = DiscussionLab()
        lab.submit("reply:admit")
        before = deepcopy(lab.scores)
        lab.submit("move:challenge")
        self.assertEqual(lab.scores, before)

    def test_invalid_or_repeated_actions_reject_without_mutation(self):
        lab = DiscussionLab()
        for action in ("vote:2", "reply:fake-evidence", "move:accuse"):
            before = deepcopy(lab.__dict__)
            with self.assertRaises(ValueError):
                lab.submit(action)
            self.assertEqual(lab.__dict__, before)
        lab.submit("reply:evidence")
        before = deepcopy(lab.__dict__)
        with self.assertRaises(ValueError):
            lab.submit("reply:evidence")
        self.assertEqual(lab.__dict__, before)

    def test_ballots_do_not_observe_human_ballot(self):
        a = self.run_path("reply:admit", vote="vote:2")
        b = self.run_path("reply:admit", vote="vote:3")
        self.assertEqual({k: v for k, v in a.votes.items() if k != 1},
                         {k: v for k, v in b.votes.items() if k != 1})

    def test_reproducible_and_returned_events_detached(self):
        a = self.run_path("reply:evidence")
        b = self.run_path("reply:evidence")
        self.assertEqual(a.__dict__, b.__dict__)
        lab = DiscussionLab()
        events = lab.submit("reply:evidence")
        events[0]["source_records"].append(999)
        events[0]["text"] = "mutated"
        self.assertNotIn(999, lab.events[1]["source_records"])
        self.assertNotEqual(lab.events[1]["text"], "mutated")

    def test_terminal_both_locales_invalid_input_and_complete_path(self):
        for lang in ("zh-CN", "en"):
            values = iter(("not a choice", "0", "999", "1", "2", "5"))
            output = []
            self.assertEqual(main(["--lang", lang], read=lambda _: next(values), write=output.append), 0)
            self.assertTrue(any("不计成绩" in line or "no score" in line for line in output))
            self.assertTrue(any("样板结束" in line or "prototype complete" in line for line in output))
            if lang == "en":
                self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for line in output for ch in line))

    def test_terminal_quit_and_eof(self):
        self.assertEqual(main([], read=lambda _: "q", write=lambda _: None), 0)
        def eof(_):
            raise EOFError
        self.assertEqual(main([], read=eof, write=lambda _: None), 0)


if __name__ == "__main__":
    unittest.main()
