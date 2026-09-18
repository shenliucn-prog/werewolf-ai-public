import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from werewolf_web.session import GameSession
from werewolf_web.observations import ObservationGateway
from werewolf_web.ai.decision_runtime import RuntimeBase
from werewolf_web.ai.model_context import public_facts, speaking_turns


class Runtime(RuntimeBase):
    backend = "api"
    def __init__(self):
        super().__init__("test")
        self.verified = True
        self.requests = []

    def complete(self, request, schema):
        self.requests.append(request)
        return {"target": None}


class PlaytestRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Runtime()
        self.s = GameSession("classic", planner=self.runtime, seed=91826,
                             player_role="civilian", onboarding=False)
        self.s.memory_dir = self.tmp.name
        await self.s._step_setup()

    async def test_chinese_targets_are_exact_and_clause_local(self):
        # Choose a setup where the human is not the tested seat.
        seats = {s.pos: s for s in self.s.engine.alive_seats()}
        # The full parser fixture reserves a seat outside all assertions.
        self.assertNotIn(self.s.engine.player_seat().pos, (4,7,11))
        for text, accuse, defend in [
            ("我暂站6号真预，11号先放；今天优先看7号。", 7, 11),
            ("3号狼与7号同票投4，今天仍反复压4号；我今天优先看7号。", 7, None),
            ("11号先放", None, 11), ("我不投7号", None, None),
            ("3号说‘我投7号’，我暂不判断。", None, None),
            ("我昨天投7号，今天投4号。", 4, None),
        ]:
            with self.subTest(text=text):
                sp = self.s._player_speech(text)
                self.assertEqual(sp.text, text)
                self.assertEqual(sp.accuse, seats[accuse].name if accuse else None)
                self.assertEqual(sp.defend, seats[defend].name if defend else None)

    async def test_pending_turns_come_only_from_public_order(self):
        record = self.s.public_record
        record.observe({"type":"narration", "speech_order":[6,7,8,1,2,3], "day":1}, 1)
        record.observe({"type":"speech", "seat":6, "phase":"day"}, 1, 1, "day")
        record.observe({"type":"speech", "seat":3, "table_talk":True}, 1, 1, "table_talk")
        result = speaking_turns(record.entries, 1)
        self.assertEqual(result["completed"], [6])
        self.assertEqual(result["awaiting"], [7,8,1,2,3])
        self.assertEqual(speaking_turns(record.entries, 2)["status"], "unknown")

    async def test_fact_fields_do_not_turn_votes_into_deaths_or_claims_into_roles(self):
        r = self.s.public_record
        r.observe({"type":"flip", "seat":9, "role":"witch"}, 1, 1, "vote")
        r.observe({"type":"death", "seat":4}, 4, 5, "night")
        r.observe({"type":"speech", "seat":1, "claim":"seer", "text":"4号被投走"}, 5)
        facts = public_facts(r.entries)
        self.assertEqual(facts[0]["side"], "god")
        self.assertEqual(facts[0]["role"], "witch")
        self.assertEqual(facts[1]["death_context"], "night_death")
        self.assertEqual(len(facts), 2)
        r.observe({"type":"death", "seat":5}, 5, 5, "vote")
        self.assertEqual(public_facts(r.entries)[-1]["death_context"], "unknown")

    async def test_public_order_is_emitted_once_and_survives_restore(self):
        agent = next(iter(self.s.agents.values()))
        self.s.engine.start_day()
        self.s.engine.speech_order = lambda: [agent.seat.pos]
        for _ in range(2):
            with patch.object(self.s, "_npc_call", AsyncMock(side_effect=RuntimeError("test stop"))):
                with self.assertRaisesRegex(RuntimeError, "test stop"):
                    await self.s._step_speeches()
            snapshot = self.s.snapshot()
            self.s.restore(snapshot)
        rows = [r for r in self.s.public_record.entries if "speech_order" in r["event"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"]["speech_order"], [agent.seat.pos])

    async def test_dying_seer_badge_has_own_latest_check_and_distinct_task(self):
        s, e = self.s, self.s.engine
        seer = next(a for a in s.agents.values() if a.seat.role == "seer")
        wolf = next(p for p in e.alive_seats() if p.is_wolf)
        for _ in range(3):
            e.start_night()
        events = e.resolve_night({"seer":{"target":wolf.pos}, "wolves":{"target":seer.seat.pos}})
        self.assertFalse(seer.seat.alive)
        for ev in events:
            await s._emit_event(ev)
        s._commit_batch()
        e.sheriff = seer.seat.pos
        import asyncio
        await asyncio.wait_for(s._farewell_floor(), 3)
        request = self.runtime.requests[-1]
        self.assertEqual(request["task"], "transfer or destroy sheriff badge")
        checks = request["information"]["private"]["seer_results"]
        self.assertEqual(checks[-1]["target"], wolf.pos)
        self.assertEqual(checks[-1]["result"], "wolf")
        other = next(a for a in s.agents.values() if a.seat.role == "civilian")
        self.assertNotIn("seer_results", ObservationGateway.for_model(other, "speech", {}).payload["information"]["private"])
        self.assertIsNone(e.sheriff)
        before = len(self.runtime.requests)
        s.restore(s.snapshot())
        await asyncio.wait_for(s._farewell_floor(), 3)
        self.assertEqual(len(self.runtime.requests), before)

    async def test_legacy_unknown_facts_and_budgeted_context(self):
        import json
        from werewolf_web.ai.model_context import MAX_REQUEST_CHARS
        r = self.s.public_record
        r.observe({"type":"flip", "seat":4, "text":"legacy"}, 1)
        r.observe({"type":"death", "seat":4}, 1)
        facts = public_facts(r.entries)
        self.assertEqual(facts[0]["side"], "unknown")
        self.assertEqual(facts[1]["death_context"], "unknown")
        for i in range(40):
            r.observe({"type":"speech", "seat":1, "text":"长发言"*500, "event_no":i+1}, 1)
        agent = next(iter(self.s.agents.values()))
        request = ObservationGateway.for_model(agent, "speech", {}).to_request()
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), MAX_REQUEST_CHARS)
