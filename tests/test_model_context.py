"""§9 context budget: the model sees a bounded slice; the archive stays whole.

The model must never receive the unbounded transcript.  These tests pin the
budgeted-context contract: recent statements verbatim, older speech summarized
as *attributed claims* (never rewritten facts), settled facts kept, and the
archive left intact.
"""
import unittest
from copy import deepcopy
from types import SimpleNamespace

from werewolf_web.ai import model_context
from werewolf_web.public_record import PublicRecord


def _record(locale="zh-CN"):
    return PublicRecord(locale)


def _agent(record, brain):
    return SimpleNamespace(public_record=record, brain=brain)


class ModelContextTest(unittest.TestCase):
    def test_recent_speeches_are_verbatim_and_bounded(self):
        record = _record()
        total = model_context.VERBATIM_SPEECHES + 5
        for i in range(total):
            record.observe({"type": "speech", "seat": i % 12 + 1, "name": f"p{i}",
                            "text": f"verbatim-{i}"}, 1)
        statements = model_context.recent_public_statements(record.entries)
        self.assertEqual(len(statements), model_context.VERBATIM_SPEECHES)
        texts = [s["text"] for s in statements]
        self.assertEqual(texts[-1], f"verbatim-{total - 1}")
        # The oldest statements fall out of the verbatim window.
        self.assertNotIn("verbatim-0", texts)

    def test_older_summaries_are_attributed_claims_not_facts(self):
        brain = SimpleNamespace(
            claim_order=[("阿承", "seer"), ("阿岚", "witch")],
            accuse_log=[(1, "阿承", "阿岚")],
            defend_log=[(1, "大山", "阿承")],
        )
        summaries = model_context.older_statement_summaries(brain)
        kinds = {s["kind"] for s in summaries}
        self.assertEqual(kinds, {"role_claims", "accusations", "defences"})
        # Each summary is attributed to a speaker — a claim, not a bare fact.
        claims = next(s for s in summaries if s["kind"] == "role_claims")
        self.assertEqual(claims["items"][0], {"who": "阿承", "claimed_role": "seer"})
        accusations = next(s for s in summaries if s["kind"] == "accusations")
        self.assertEqual(accusations["items"][0]["accused"], "阿岚")

    def test_public_facts_include_flips_deaths_and_ballots(self):
        record = _record()
        record.observe({"type": "flip", "seat": 11, "text": "11号阿岚翻牌——平民。"}, 2)
        record.observe({"type": "death", "seat": 3, "text": "3号死亡。"}, 1)
        record.observe({"type": "ballots", "ballots": [{"voter": 1, "target": 3}],
                        "tally": {3: 5}}, 2)
        facts = model_context.public_facts(record.entries)
        self.assertEqual({f["kind"] for f in facts}, {"flip", "death", "ballots"})

    def test_public_facts_are_bounded(self):
        record = _record()
        for i in range(model_context.FACT_WINDOW + 10):
            record.observe({"type": "death", "seat": 1, "text": f"death-{i}"}, 1)
        facts = model_context.public_facts(record.entries)
        self.assertEqual(len(facts), model_context.FACT_WINDOW)

    def test_build_public_context_does_not_mutate_the_archive(self):
        record = _record()
        for i in range(3):
            record.observe({"type": "speech", "seat": 8, "name": "阿承", "text": f"D{i}"}, 1)
        before = deepcopy(record.entries)
        agent = _agent(record, SimpleNamespace(
            claim_order=[], accuse_log=[], defend_log=[]))
        model_context.build_public_context(agent)
        self.assertEqual(record.entries, before)

    def test_bound_information_truncates_only_its_own_copy(self):
        info = {"public_votes": [{"day": i, "voter": 1, "target": 2}
                                 for i in range(model_context.VOTE_WINDOW + 20)]}
        bounded = model_context.bound_information(info)
        self.assertEqual(len(bounded["public_votes"]), model_context.VOTE_WINDOW)
        # The caller's dict is left untouched (it is always a fresh copy).
        self.assertEqual(len(info["public_votes"]), model_context.VOTE_WINDOW + 20)

    def test_fit_request_budget_trims_oldest_verbatim_first(self):
        import json
        statements = [{"text": f"old-{i}-" + "x" * 300} for i in range(3)]
        request = {
            "fixed": "y" * 40,
            "public_context": {"recent_public_statements": statements},
            "own_previous_decisions": [],
        }
        # Budget that fits the fixed part plus exactly the newest statement.
        budget = len(json.dumps({
            "fixed": request["fixed"],
            "public_context": {"recent_public_statements": [statements[-1]]},
            "own_previous_decisions": [],
        }, ensure_ascii=False))
        result = model_context.fit_request_budget(request, max_chars=budget)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), budget)
        kept = result["public_context"]["recent_public_statements"]
        # The oldest statements were trimmed; the newest survives.
        self.assertEqual([s["text"] for s in kept], [statements[-1]["text"]])

    def test_fit_request_budget_raises_when_fixed_parts_alone_exceed(self):
        with self.assertRaises(ValueError):
            model_context.fit_request_budget({"fixed": "z" * 200}, max_chars=50)


if __name__ == "__main__":
    unittest.main()
