import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from types import SimpleNamespace

from werewolf_web.check_claims import audit, parse_reports, report_line
from werewolf_web.offline_game import OfflineSession, speech_choices
from werewolf_web.ai.decision_runtime import RuntimeBase
from werewolf_web.session import GameSession


def row(number, night=1, target=3, result="good", actor=2):
    return {"night": night, "event": {"type": "speech", "event_no": number,
            "seat": actor, "name": "Speaker", "text": report_line(night, target, result, "en")}}


class CheckClaimTest(unittest.TestCase):
    def test_bilingual_explicit_trailing_block(self):
        for locale in ("en", "zh-CN"):
            line = report_line(1, 3, "good", locale)
            self.assertEqual(parse_reports("My claim.\n" + line)[0]["target"], 3)
            for text in ("I checked them last night", '“' + line + '”',
                         "```\n" + line + "\n```", line + "\nThis is a quotation."):
                self.assertEqual(parse_reports(text), [])

    def test_conflicts_have_both_sources_and_repeats_are_deduplicated(self):
        entries = [row(1), row(2), row(3, target=4), row(4, night=2, result="wolf")]
        result = audit(entries)
        self.assertEqual(len(result["reports"]), 3)
        conflicts = {f["kind"]: f for f in result["findings"]}
        self.assertEqual(conflicts["conflicting_same_night"]["previous_report"]["event_no"], 1)
        self.assertEqual(conflicts["changed_result"]["report"]["event_no"], 4)

    def test_future_and_invalid_target(self):
        future = row(1, night=3)
        future["night"] = 1
        self.assertEqual({f["kind"] for f in audit([future, row(2, target=13)])["findings"]},
                         {"future_night", "invalid_target"})

    def test_only_public_flips_and_hidden_wolf_exception(self):
        for role, expected in (("werewolf", "contradicted_by_flip"),
                               ("hidden_wolf", "compatible_with_flip"),
                               ("预言家", "compatible_with_flip")):
            flip = {"event": {"type": "flip", "seat": 3, "role": role, "event_no": 2}}
            self.assertEqual(audit([row(1), flip])["findings"][0]["kind"], expected)
            flip["event"]["type"] = "private"
            self.assertEqual(audit([row(1), flip])["findings"], [])

    def test_bounded_json_roundtrip_without_mutation(self):
        entries = [row(n, night=n) for n in range(1, 30)]
        original = deepcopy(entries)
        result = audit(entries)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["reports"]), 16)
        self.assertEqual(audit(json.loads(json.dumps(entries))), result)
        self.assertEqual(entries, original)


class CheckClaimIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_query_does_not_submit_action(self):
        from werewolf_web.chat_game import _repl
        async def events():
            yield {"type": "request", "kind": "speech", "data": {}, "event_no": 1}
        session = SimpleNamespace(engine=SimpleNamespace(locale="en"), events=events,
                                  _pending_event_no=1, answer_question=Mock(return_value="Audit"))
        with patch("builtins.input", side_effect=["/checks", EOFError]), patch("builtins.print"):
            with self.assertRaises(EOFError):
                await _repl(session)
        session.answer_question.assert_called_once_with("/checks")

    async def test_offline_reports_citations_and_public_challenge(self):
        session = OfflineSession(seed=4, player_role="civilian")
        await session._step_setup()
        session.engine.night_count = 1
        actor = session.engine.player_seat()
        other = next(s for s in session.engine.alive_seats() if s.pos != actor.pos)
        for result in ("good", "wolf"):
            session.emit({"type": "speech", "seat": other.pos, "name": other.name,
                          "text": report_line(1, actor.pos, result, session.engine.locale)})
        choices = speech_choices(session, actor)
        self.assertTrue(all(parse_reports(c["label"]) for c in choices if c["id"].startswith("report:")))
        self.assertTrue(all(not parse_reports(c["label"]) for c in choices if c["id"].startswith("cite:")))
        challenges = [c for c in choices if c["id"].startswith("audit:")]
        self.assertTrue(challenges)
        self.assertTrue(all(c["speech"]["accuse"] is None for c in challenges))
        self.assertEqual(session.proxy.speak().question_to, other.name)

    async def test_model_request_and_restored_public_query(self):
        runtime = RuntimeBase("test-model")
        runtime.backend, runtime.verified = "api", True
        runtime.complete = Mock(return_value={"target": None})
        session = GameSession("classic", seed=4, planner=runtime)
        await session._step_setup()
        session.engine.night_count = 1
        for result in ("good", "wolf"):
            session.emit({"type": "speech", "seat": 2, "name": "Speaker",
                          "text": report_line(1, 3, result, "en")})
        before = session.public_record.query("/checks")
        agent = next(iter(session.agents.values()))
        agent.vote([{"pos": s.pos, "name": s.name} for s in session.engine.alive_seats()])
        request = runtime.complete.call_args.args[0]
        self.assertTrue(request["public_context"]["check_claim_audit"]["findings"])
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), 24000)
        runtime.complete.assert_called_once()
        session.restore(json.loads(json.dumps(session.snapshot())))
        self.assertEqual(session.public_record.query("/checks"), before)
