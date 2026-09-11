import asyncio
import contextlib
import io
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from werewolf_web.ai.brain import Speech, Style
from werewolf_web.check_claims import parse_reports, report_line
from werewolf_web.offline_dialogue import contextual_choices, shortlist, choose_reaction
from werewolf_web.offline_game import OfflineSession, action_choices, speech_choices, play
from werewolf_web.onboarding import introduction


def entries():
    return [{"night": 1, "event": {"type": "speech", "event_no": n, "seat": who,
             "text": report_line(1, target, result, "en")}}
            for n, who, target, result in ((1, 2, 5, "good"), (2, 7, 11, "good"), (3, 9, 1, "wolf"))]


class SituationalTest(unittest.TestCase):
    def test_three_claimants_create_relevant_options_not_role_certainty(self):
        seats = {i: f"P{i}" for i in range(1, 13)}
        options = contextual_choices(entries(), seats, 5, "en")
        self.assertTrue(any(c["topic"] == "receive_good" for c in options))
        self.assertTrue(any(c["topic"] == "counterclaim" for c in options))
        self.assertTrue(all(c["speech"]["accuse"] is None for c in options))
        self.assertTrue(all(not parse_reports(c["label"]) for c in options))
        self.assertIn(choose_reaction(options, [], Style())["topic"], ("receive_good",))

    def test_personality_changes_response_not_information(self):
        options = contextual_choices(entries(), {i: f"P{i}" for i in range(1, 13)}, 5, "en")
        warm = choose_reaction(options, [], Style(loyalty=.9, caution=.1))
        cautious = choose_reaction(options, [], Style(loyalty=.1, caution=.9))
        self.assertIn(":thanks:", warm["id"])
        self.assertIn(":probe:", cautious["id"])
        used = [{"text": c["label"]} for c in options]
        self.assertIsNone(choose_reaction(options, used, Style()))

    def test_shortlist_is_bounded_and_always_offers_neutral_listening(self):
        options = contextual_choices(entries(), {i: f"P{i}" for i in range(1, 13)}, 5, "en")
        options.append({"id": "wait", "label": "listen"})
        picks = shortlist(options)
        self.assertLessEqual(len(picks), 4)
        self.assertEqual(picks[-1]["id"], "wait")

    def test_legacy_and_natural_report_forms_not_quotations(self):
        for text in ("我是预言家，第2夜验5号，好人。", "I claim seer: night 2, seat 5 is good.",
                     report_line(2, 5, "good", "en")):
            self.assertEqual(parse_reports(text)[0]["target"], 5)
            self.assertFalse(parse_reports('“' + text + '”'))


class SituationalIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def make_session(self, locale="en"):
        s = OfflineSession(seed=23, player_role="civilian", locale=locale)
        await s._step_setup()
        s.engine.night_count = 1
        actor = s.engine.player_seat()
        others = [p for p in s.engine.alive_seats() if p.pos != actor.pos]
        for p, result in zip(others[:3], ("good", "wolf", "good")):
            s.emit({"type": "speech", "seat": p.pos, "name": p.name,
                    "claim": "seer", "text": report_line(1, actor.pos, result, locale)})
        return s

    async def test_menu_is_public_and_restore_recreates_same_suggestions(self):
        s = await self.make_session()
        before = action_choices(s, "speech", {})
        saved = json.loads(json.dumps(s.snapshot()))
        restored = OfflineSession(seed=99, player_role="civilian", locale="en")
        restored.restore(saved)
        self.assertEqual(action_choices(restored, "speech", {}), before)
        s.engine.seer_results = [{"night": 1, "target": 5, "result": "wolf"}]
        for p in s.engine.seats.values():
            p.role = "werewolf"
        self.assertEqual(action_choices(s, "speech", {}), before)

    async def test_natural_reports_roundtrip_and_listening_does_not_accuse(self):
        for locale in ("en", "zh-CN"):
            s = await self.make_session(locale)
            options = action_choices(s, "speech", {})
            for c in options:
                if c["id"].startswith("report:"):
                    self.assertEqual(len(parse_reports(c["label"])), 1)
                    self.assertNotIn("\n", c["label"])
            wait = next(c for c in options if c["id"] == "wait")
            agent = next(iter(s.agents.values()))
            before = deepcopy(agent.brain.accuse_log)
            agent.observe_speech(1, s.engine.player_seat().name, Speech(**wait["speech"]), 90)
            self.assertEqual(agent.brain.accuse_log, before)
            self.assertNotIn(s.engine.player_seat().name, agent.brain.silent)
            intro = introduction(s.engine, offline_choices=True)
            self.assertNotIn("自然语言", intro)
            self.assertNotIn("debate in natural language", intro)

    async def test_terminal_direct_choice_and_other_responses(self):
        for choose_other in (False, True):
            s = await self.make_session()
            options = action_choices(s, "speech", {})
            prompt = {"type": "request", "kind": "speech", "data": {}, "request_id": "prompt"}
            async def events():
                yield prompt
            submissions = []
            fake = SimpleNamespace(engine=s.engine, pending=True, spectator=False,
                _game_task_ref=None, ensure_game_task=lambda: None, events=events,
                _human_request=lambda: SimpleNamespace(request_id="prompt"),
                submit=lambda payload, **kw: submissions.append(payload) or True)
            answers = iter(["0", "2", "1"] if choose_other else ["1"])
            with patch("werewolf_web.offline_game.action_choices", return_value=options):
                with contextlib.redirect_stdout(io.StringIO()):
                    fake.faulted = False
                    await play(fake, read=lambda _: next(answers), write=lambda _: None)
            self.assertEqual(len(submissions), 1)
            self.assertIn(submissions[0], [c["payload"] for c in options])

    async def test_context_option_accepted_once_at_real_pending_prompt(self):
        s = await self.make_session()
        task = asyncio.create_task(s.ask_player("speech", {}))
        await asyncio.sleep(0)
        choice = next(c for c in action_choices(s, "speech", {}) if c.get("suggested") and c["id"] != "wait")
        request = s._human_request().request_id
        self.assertTrue(s.submit(choice["payload"], request_id=request))
        result = await task
        self.assertEqual(s._player_speech(result["text"]).text, choice["label"])
        self.assertFalse(s.submit(choice["payload"], request_id=request))
