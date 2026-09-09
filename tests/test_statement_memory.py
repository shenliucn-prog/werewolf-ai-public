import copy
import json
import unittest
from types import SimpleNamespace

from werewolf_web.ai.model_context import build_public_context
from werewolf_web.ai.statement_memory import statement_summaries
from werewolf_web.ai.model_context import fit_request_budget


class StatementMemoryTest(unittest.TestCase):
    def setUp(self):
        self.brain = SimpleNamespace(claim_order=[("Alice", "seer")],
                                     accuse_log=[], defend_log=[],
                                     disputed_event_nos=[], disputed_targets=[])

    def row(self, number, phase="election", **fields):
        return {"day": 1, "night": 1, "phase": phase,
                "event": {"type": "speech", "name": "Alice", "seat": 1,
                          "text": "public statement", "event_no": number, **fields}}

    def test_claim_changes_keep_separate_original_sources(self):
        rows = [self.row(2, claim="seer"), self.row(7, "day", claim="civilian"),
                self.row(9, "day", claim="seer")]
        items = statement_summaries(rows, self.brain)[0]["items"]
        self.assertEqual([i["event_no"] for i in items], [2, 7, 9])
        self.assertEqual([i["phase"] for i in items], ["election", "day", "day"])
        self.assertEqual([i["claimed_role"] for i in items], ["seer", "civilian", "seer"])
        self.assertTrue(all(i["reference_status"] == "recorded_statement" for i in items))

    def test_relations_keep_phase_and_do_not_duplicate_legacy(self):
        self.brain.accuse_log = [(1, "Alice", "Bob")]
        self.brain.defend_log = [(1, "Alice", "Carol")]
        groups = statement_summaries([self.row(3, accuse="Bob", defend="Carol")], self.brain)
        for group in groups[1:]:
            self.assertEqual(len(group["items"]), 1)
            self.assertEqual(group["items"][0]["event_no"], 3)
            self.assertEqual(group["items"][0]["phase"], "election")

    def test_old_save_without_metadata_stays_explicitly_unknown(self):
        items = statement_summaries([self.row(2)], self.brain)[0]["items"]
        self.assertIsNone(items[0]["event_no"])
        self.assertIsNone(items[0]["phase"])
        self.assertEqual(items[0]["reference_status"], "unknown")

    def test_missing_event_number_never_becomes_exact_reference(self):
        item = statement_summaries([self.row(None, claim="seer")], self.brain)[0]["items"][0]
        self.assertIsNone(item["event_no"])
        self.assertEqual(item["reference_status"], "unknown")

    def test_projection_is_bounded_detached_and_json_restore_equivalent(self):
        rows = [self.row(n, claim="seer") for n in range(1, 41)]
        before = copy.deepcopy(rows)
        result = statement_summaries(rows, self.brain)
        self.assertEqual(len(result[0]["items"]), 16)
        self.assertEqual(result[0]["items"][0]["event_no"], 25)
        self.assertEqual(result, statement_summaries(json.loads(json.dumps(rows)), self.brain))
        result[0]["items"][0]["claimed_role"] = "changed"
        self.assertEqual(rows, before)

    def test_live_context_uses_ledger_not_only_brain_claim_order(self):
        agent = SimpleNamespace(brain=self.brain, public_record=SimpleNamespace(
            entries=[self.row(4, claim="seer"), self.row(8, "day", claim="witch")]))
        context = build_public_context(agent)
        items = context["older_statement_summaries"][0]["items"]
        self.assertEqual([i["claimed_role"] for i in items], ["seer", "witch"])
        self.assertEqual([i["event_no"] for i in items], [4, 8])

    def test_non_speech_private_payload_is_not_projected(self):
        row = self.row(5, claim="wolf")
        row["event"]["type"] = "private"
        self.brain.claim_order = []
        self.assertEqual(statement_summaries([row], self.brain), [])

    def test_source_metadata_remains_inside_whole_request_budget(self):
        request = {"public_context": {"older_statement_summaries": statement_summaries(
            [self.row(n, claim="seer") for n in range(1, 41)], self.brain)}}
        fit_request_budget(request, max_chars=500)
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), 500)


class StatementSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_published_table_claim_survives_session_restore_with_source(self):
        import tempfile
        from werewolf_web.session import GameSession
        from werewolf_web.ai.brain import Speech
        from tests.test_observation_boundary import FakeRuntime

        with tempfile.TemporaryDirectory() as directory:
            session = GameSession("classic", planner=FakeRuntime(), seed=7)
            session.memory_dir = directory
            await session._step_setup()
            source = session.engine.player_seat()
            await session._publish_table_speech(source, Speech(text="I claim seer", claim="seer"), "reply")
            agent = next(iter(session.agents.values()))
            before = build_public_context(agent)
            item = before["older_statement_summaries"][0]["items"][0]
            self.assertEqual(item["phase"], "table_talk")
            event = next(e for e in session._events if e["event_no"] == item["event_no"])
            self.assertEqual(event["text"], "I claim seer")
            restored = GameSession("classic", planner=FakeRuntime())
            restored.restore(json.loads(json.dumps(session.snapshot())))
            self.assertEqual(build_public_context(restored.agents[agent.name]), before)
