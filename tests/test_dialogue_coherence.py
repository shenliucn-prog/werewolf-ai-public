import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from werewolf_web.ai.brain import Brain, Speech
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.game.engine import GameEngine
from werewolf_web.run import GameSession


class DialogueCoherenceTest(unittest.IsolatedAsyncioTestCase):
    def make_brain(self, role, locale="zh-CN"):
        engine = GameEngine("classic", seed=19, locale=locale)
        engine.setup(); engine.start_night(); engine.start_day()
        seat = next(s for s in engine.seats.values() if s.role == role)
        return Brain(seat, engine, {}, random.Random(9))

    def test_seer_reports_old_and_new_checks_with_exact_nights(self):
        for locale in ("zh-CN", "en"):
            brain = self.make_brain("seer", locale)
            e = brain.engine
            targets = [s for s in e.alive_seats() if s.name != brain.name][:2]
            e.night_count = e.day_count = 2
            e.seer_results = [{"night": i, "target": s.pos, "name": s.name, "result": result}
                             for i, s, result in ((1, targets[0], "wolf"), (2, targets[1], "good"))]
            speech = brain.speak(2, [])
            account = speech.protected_facts[0]
            self.assertIn("night 1" if locale == "en" else "第1夜", account)
            self.assertIn("night 2" if locale == "en" else "第2夜", account)
            self.assertIn(targets[0].name, account); self.assertIn(targets[1].name, account)
            self.assertNotIn("昨晚", brain._why_suspect(targets[0].name))
            self.assertFalse(StrategicNPCAgent._matches_intent("I am the Seer.", speech))

    def test_bluff_account_is_stable_and_ignores_other_seers_private_results(self):
        for locale in ("zh-CN", "en"):
            brain = self.make_brain("werewolf", locale)
            brain.claims[brain.name] = "seer"
            first = brain.check_account()
            brain.engine.seer_results = [{"night": 1, "target": 99, "name": "PRIVATE_CANARY", "result": "wolf"}]
            self.assertEqual(first, brain.check_account("a different target"))
            brain.engine.night_count = 2
            second = brain.check_account()
            self.assertIn(first.split(": ", 1)[-1] if locale == "en" else first.split("：", 1)[-1], second)
            self.assertNotIn("PRIVATE_CANARY", second)

    def test_question_does_not_reveal_unclaimed_seer(self):
        brain = self.make_brain("seer", "en")
        brain.engine.seer_results = [{"night": 1, "target": 99, "name": "PRIVATE_CANARY", "result": "wolf"}]
        reply = brain.answer_check_question()
        self.assertIsNone(reply.claim)
        self.assertNotIn("PRIVATE_CANARY", reply.text)

    def test_wolf_does_not_support_the_claimant_accusing_it(self):
        brain = self.make_brain("werewolf")
        e = brain.engine
        rival = next(s for s in e.alive_seats() if not s.is_wolf)
        brain.wolf_strategy = "quiet"
        brain.claims[rival.name] = "seer"
        brain.accuse_log.append((1, rival.name, brain.name))
        speech = brain._wolf_speak(1, [(0.9, rival.name)], [rival.name], [rival.name], [])
        self.assertEqual(speech.accuse, rival.name)
        self.assertIsNone(speech.defend)
        self.assertNotIn(f"我先听 {rival.name}", speech.text)

    def test_night_noise_does_not_recheck_when_unchecked_targets_exist(self):
        brain = self.make_brain("seer")
        targets = [s for s in brain.engine.alive_seats() if s.name != brain.name]
        checked = targets[0]
        brain.engine.seer_results = [{"night": 1, "target": checked.pos, "name": checked.name, "result": "good"}]
        with patch.object(brain.rng, "random", return_value=0):
            for _ in range(20):
                self.assertNotEqual(brain.night("seer", [s.pos for s in targets]).target, checked.pos)

    async def test_host_routes_check_question_to_public_reply_without_player_action(self):
        s = GameSession("classic", {"enabled": False}, seed=19, player_role="guard")
        e = s.engine; e.setup(); e.start_night(); e.start_day()
        target = next(seat for seat in e.alive_seats() if seat.role == "seer")
        brain = Brain(target, e, {}, random.Random(9)); brain.claims[target.name] = "seer"
        checked = e.player_seat()
        e.seer_results = [{"night": 1, "target": checked.pos, "name": checked.name, "result": "good"}]
        agent = SimpleNamespace(seat=target, brain=brain,
                                observe_speech=lambda day, who, sp: brain.observe_speech(day, who, sp, sp.text))
        s.agents = {target.name: agent}
        question = s._player_speech(f"{target.pos}号不说自己验了谁吗？")
        self.assertEqual(question.question_to, target.name)
        s._broadcast_speech(checked, question)
        with patch("werewolf_web.run.asyncio.sleep", return_value=None):
            await s._answer_table_questions()
        history = s.public_record.query("公开记录")
        self.assertIn("主持人", history)
        self.assertIn("第1夜", history)
        self.assertTrue(s.q.empty())
        self.assertEqual(s._questions_answered, 1)
