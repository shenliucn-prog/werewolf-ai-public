import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from werewolf_web.ai.brain import Speech
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.chat_game import parse_action
from werewolf_web.game.engine import GameEngine
from werewolf_web.public_record import PublicRecord, ballot_event
from werewolf_web.run import GameSession


class PublicPlayTest(unittest.IsolatedAsyncioTestCase):
    def test_peaceful_day_weighting_and_no_exile(self):
        e = GameEngine("classic", seed=4)
        e.setup(); e.start_day(); e.sheriff = 1
        self.assertEqual(e.vote_tally({1: 0, 2: 0, 3: 2}), {0: 2.5, 2: 1.0})
        before = len(e.alive_seats())
        events = e.resolve_vote({1: 0, 2: 0, 3: 2}, 0)
        self.assertEqual(len(e.alive_seats()), before)
        self.assertIsNone(e.last_exiled)
        self.assertFalse(any(ev.type in ("death", "exile") for ev in events))
        e.sheriff = None
        self.assertEqual(e.vote_tally({1: 0, 2: 3}), {0: 1, 3: 1})
        e.crow_target = 3
        tally = e.vote_tally({1: 0, 2: 3})
        self.assertEqual(tally, {0: 1, 3: 2})
        self.assertIn("乌鸦额外票", ballot_event(e, {1: 0, 2: 3}, tally)["text"])

    def test_commands_and_public_history_do_not_leak_or_mutate(self):
        s = GameSession("classic", {"enabled": False}, seed=4)
        s.engine.setup(); s.engine.start_day()
        s.pending = {"kind": "night", "data": {"candidates": [{"pos": 2}]}}
        public = {"type": "speech", "seat": 1, "name": "Speaker", "text": "Exact words, not a summary."}
        s.emit(public); public["text"] = "Changed later"
        for kind in ("private", "init", "request", "conjecture"):
            s.emit({"type": kind, "text": "PRIVATE_CANARY"})
        s.emit(ballot_event(s.engine, {1: 0, 2: 1}, {0: 1, 1: 1}))
        before = dict(s.pending)
        history = s.answer_question("公开记录")
        self.assertIn("Exact words, not a summary.", history)
        self.assertNotIn("Changed later", history)
        self.assertNotIn("PRIVATE_CANARY", history)
        self.assertIn("平安日", s.answer_question("把上一轮的票型拿出来"))
        self.assertNotIn("Exact words", s.answer_question("上一轮票型"))
        self.assertEqual(s.pending, before)
        self.assertTrue(s.q.empty())
        self.assertEqual(parse_action("vote", {"candidates": [{"pos": 0}]}, "平安日"), {"target": 0})
        self.assertIsNone(parse_action("vote", {"sheriff": True, "candidates": [{"pos": 1}]}, "平安日"))
        self.assertEqual(parse_action("election_withdraw", {}, "退警"), {"withdraw": True})

    async def test_declining_interruption_emits_no_human_statement(self):
        s = GameSession("classic", {"enabled": False}, seed=5)
        s.engine.setup(); s.engine.start_day()
        human = s.engine.player_seat()
        other = next(seat for seat in s.engine.alive_seats() if not seat.is_player)
        agent = Mock(); agent.name = other.name; agent.seat = other
        agent.table_interruption_interest.return_value = 1
        agent.table_interject.return_value = Speech(text="Explain that claim.")
        s.agents = {other.name: agent}
        s.ask_player = AsyncMock(return_value={"text": ""})
        s.host.moderate_table_talk = Mock(return_value="")
        with patch("werewolf_web.run.asyncio.sleep", return_value=None):
            await s._maybe_table_talk(human, Speech(text="I suspect someone.", accuse=other.name))
        speeches = [r["event"] for r in s.public_record.entries if r["event"]["type"] == "speech"]
        self.assertEqual(len(speeches), 1)
        self.assertEqual(speeches[0]["seat"], other.pos)

    def test_cautious_npc_can_support_peace_without_invalid_seat_lookup(self):
        agent = StrategicNPCAgent.__new__(StrategicNPCAgent)
        agent.seat = SimpleNamespace(pos=1)
        agent.engine = SimpleNamespace(day_count=1)
        agent.brain = SimpleNamespace(style=SimpleNamespace(aggression=0.2), suspicion=lambda name: 0.4)
        agent.reasoning = []
        self.assertEqual(agent.vote([{"pos": 2, "name": "Other"}, {"pos": 0, "name": "Peaceful Day"}]), 0)

    async def test_withdrawal_and_complete_public_game_in_both_languages(self):
        sleep = asyncio.sleep
        async def fast(_): await sleep(0)
        for locale in ("zh-CN", "en"):
            with tempfile.TemporaryDirectory() as memory, patch("werewolf_web.run.asyncio.sleep", fast), \
                 patch("werewolf_web.ai.host.HostAgent.evolve"):
                s = GameSession("classic", {"enabled": False}, seed=7, player_role="guard", locale=locale, onboarding=True)
                s.memory_dir = memory
                withdrawn = False; complete = False; ballots = []; review = ""
                async for event in s.events():
                    self.assertNotEqual(event["type"], "error", event)
                    if event["type"] == "ballots": ballots.append(event)
                    if event["type"] == "review": review = event["text"]
                    if event["type"] == "gameover": complete = True
                    if event["type"] != "request": continue
                    kind, data = event["kind"], event["data"]
                    if kind == "ready": answer = {"ready": True}
                    elif kind == "election_up": answer = {"up": True}
                    elif kind == "election_withdraw":
                        self.assertFalse(s.submit({"withdraw": "yes"}))
                        answer = {"withdraw": True}; withdrawn = True
                    elif kind in ("speech", "table_reply"): answer = {"text": ""}
                    else:
                        if kind == "vote" and data.get("sheriff"):
                            self.assertTrue(withdrawn)
                            self.assertNotIn(s.engine.player_seat().pos, [c["pos"] for c in data["candidates"]])
                        answer = {"target": data["candidates"][0]["pos"] if data.get("candidates") else None}
                    self.assertTrue(s.submit(answer), (kind, answer))
                self.assertTrue(complete)
                self.assertTrue(withdrawn)
                self.assertTrue(any(b["sheriff"] for b in ballots))
                self.assertTrue(any(not b["sheriff"] for b in ballots))
                self.assertIn("Final roles" if locale == "en" else "最终身份", review)
                for ballot in ballots:
                    self.assertIn(ballot["text"], review)
