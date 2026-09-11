import json
import unittest
from unittest.mock import Mock

from werewolf_web.ai.brain import Speech
from werewolf_web.ai.decision_runtime import RuntimeBase
from werewolf_web.ai.model_context import build_public_context, statements_of_flipped_seers
from werewolf_web.session import GameSession


class ClaimEvidencePathTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_localized_snapshot_and_fake_claim_boundaries(self):
        entries = [{"day": 1, "event": {"type": "speech", "name": "speaker",
                    "claim": "seer", "text": "My claimed check", "event_no": 1}}]
        for label in ("seer", "Seer", "预言家"):
            flips = json.loads(json.dumps([("speaker", label, False)]))
            self.assertEqual(len(statements_of_flipped_seers(entries, flips)), 1)
        self.assertEqual(statements_of_flipped_seers(entries, []), [])
        for label in ("Werewolf", "狼人", "seer"):
            self.assertEqual(statements_of_flipped_seers(entries, [("speaker", label, True)]), [])

    async def test_changed_role_claims_keep_both_public_sources(self):
        from werewolf_web.ai.statement_memory import statement_summaries
        from types import SimpleNamespace
        brain = SimpleNamespace(claim_order=[("speaker", "civilian"), ("speaker", "seer")],
                                accuse_log=[], defend_log=[])
        entries = [{"day": day, "event": {"type": "speech", "name": "speaker",
                    "claim": role, "text": f"I claim {role}", "event_no": day}}
                   for day, role in ((1, "civilian"), (2, "seer"))]
        items = statement_summaries(entries, brain)[0]["items"]
        self.assertEqual([(i["claimed_role"], i["event_no"]) for i in items],
                         [("civilian", 1), ("seer", 2)])
        self.assertTrue(all(i["reference_status"] == "recorded_statement" for i in items))

    async def test_real_localized_flip_retains_old_seer_statement(self):
        for locale in ("zh-CN", "en"):
            with self.subTest(locale=locale):
                runtime = RuntimeBase("test-model")
                runtime.backend, runtime.verified = "api", True
                runtime.complete = Mock(return_value={"target": None})
                session = GameSession("classic", seed=4, player_role="civilian", locale=locale, planner=runtime)
                await session._step_setup()
                seer = next(s for s in session.engine.seats.values() if s.role == "seer")
                observer = next(a for a in session.agents.values() if a.brain.role == "civilian")
                speech = Speech(text="Synthetic attributed check report; not verified.", claim="seer")
                session._broadcast_speech(seer, speech)
                session.emit({"type": "speech", "seat": seer.pos, "name": seer.name,
                              "claim": "seer", "text": speech.text})
                for _ in range(20):
                    session.emit({"type": "speech", "seat": observer.seat.pos,
                                  "name": observer.name, "text": "Later public statement."})
                self.assertEqual(build_public_context(observer)["statements_of_flipped_seers"], [])
                events = []
                session.engine._kill(seer.pos, "wolf", events)
                for event in events:
                    await session._emit_event(event)
                items = build_public_context(observer)["statements_of_flipped_seers"]
                self.assertEqual([r["text"] for r in items], [speech.text])
                observer.vote([{"pos": s.pos, "name": s.name} for s in session.engine.alive_seats()])
                request = runtime.complete.call_args.args[0]
                self.assertEqual(request["public_context"]["statements_of_flipped_seers"], items)
                self.assertIn("attributed", items[0]["status"])
                runtime.complete.assert_called_once()
                self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), 24000)
