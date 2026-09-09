"""Compatibility seams of the extracted trusted save codec."""
import json
import unittest
from unittest.mock import patch

from werewolf_web import session_codec
from werewolf_web.session import GameSession
from werewolf_web.ai.brain import Speech


class SessionCodecTest(unittest.TestCase):
    def test_malformed_loop_fields_reject_before_any_live_mutation(self):
        cases = [
            ("campaign_profile", []), ("triggered", [[]]),
            ("speech_events", [["bad"]]),
            ("speech_events", [["name", {"__speech__": True, "protected_facts": None}]]),
            ("table_extra_by_name", []), ("table_extra_by_name", {"name": -1}),
            ("table_pairs", [[[]]]), ("table_extra_turns", True),
            ("step_state", []),
            ("step_state", {"nested": {"__speech__": True, "protected_facts": None}}),
            ("decision_log", [{"result": {"__speech__": True, "protected_facts": None}}]),
            ("decision_no", -1), ("pending", []), ("finished", "false"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                source = GameSession("classic", {"enabled": False}, seed=7)
                target = GameSession("classic", {"enabled": False}, seed=99)
                payload = source.snapshot()
                payload[field] = value
                before = target.snapshot()
                engine, llm, agents = target.engine, target.llm, target.agents
                with self.assertRaises(ValueError):
                    target.restore(payload)
                self.assertEqual(target.snapshot(), before)
                self.assertIs(target.engine, engine)
                self.assertIs(target.llm, llm)
                self.assertIs(target.agents, agents)

    def test_nested_speech_roundtrip_through_json_and_legacy_entry_points(self):
        value = {"speech": Speech(text="public claim", claim="seer"), "nested": [(1, 2)]}
        encoded = session_codec.freeze(value)
        self.assertEqual(GameSession._freeze(value), encoded)
        decoded = session_codec.thaw(json.loads(json.dumps(encoded)))
        self.assertEqual(decoded["speech"], value["speech"])
        self.assertEqual(decoded["nested"], [[1, 2]])
        self.assertEqual(GameSession._thaw(encoded), decoded)

    def test_session_snapshot_and_restore_delegate_without_new_state(self):
        session = GameSession("classic", {"enabled": False}, seed=7)
        with patch.object(session_codec, "snapshot", return_value={"test": True}) as snapshot:
            self.assertEqual(session.snapshot(), {"test": True})
            snapshot.assert_called_once_with(session)
        payload = {"test": True}
        with patch.object(session_codec, "restore") as restore:
            session.restore(payload)
            restore.assert_called_once_with(session, payload)
        self.assertNotIn("codec", vars(session))

    def test_undealt_save_is_identical_across_direct_and_compatibility_paths(self):
        a = GameSession("classic", {"enabled": False}, seed=7)
        payload = json.loads(json.dumps(session_codec.snapshot(a)))
        b = GameSession("classic", {"enabled": False}, seed=99)
        session_codec.restore(b, payload)
        self.assertEqual(b.snapshot(), payload)

    def test_unknown_version_rejection_keeps_session_unchanged(self):
        session = GameSession("classic", {"enabled": False}, seed=7)
        before = session.snapshot()
        payload = dict(before, schema_version=999)
        with self.assertRaises(ValueError):
            session_codec.restore(session, payload)
        self.assertEqual(session.snapshot(), before)
