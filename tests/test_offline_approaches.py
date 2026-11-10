import json
import unittest
from copy import deepcopy

from werewolf_web.ai.brain import Speech
from werewolf_web.offline_game import OfflineSession, action_choices
from werewolf_web.offline_dialogue import reply_choices
from werewolf_web.offline_social import feedback_choices
from werewolf_web.social_actions import make


class ApproachTest(unittest.IsolatedAsyncioTestCase):
    async def session(self, locale="en"):
        session = OfflineSession(seed=23, player_role="civilian", locale=locale)
        await session._step_setup()
        session.engine.day_count = 1
        session.engine.night_count = 1
        return session

    async def test_strategy_categories_have_distinct_engine_actions(self):
        session = await self.session()
        choices = action_choices(session, "speech", {})
        player = session.engine.player_seat()
        target = next(s for s in session.engine.alive_seats() if s.name != player.name)
        by_id = {c["id"]: c for c in choices}
        for prefix, category, field in (("suspect", "pressure", "accuse"),
                                        ("support", "protect", "defend"),
                                        ("ask", "probe", "question_to")):
            choice = by_id[f"{prefix}:{target.pos}"]
            self.assertEqual(choice["approach"], category)
            self.assertEqual(choice["speech"][field], target.name)
            self.assertTrue(choice["consequence"])
            self.assertNotIn("consequence", choice["payload"]["offline_speech"])
        self.assertEqual(by_id["claim:seer"]["approach"], "reveal")
        self.assertEqual(by_id["wait"]["approach"], "hold")

    async def test_pressure_and_protection_change_real_npc_read_differently(self):
        session = await self.session()
        observer = next(a for a in session.agents.values() if a.brain.role == "civilian")
        target = next(s for s in session.engine.alive_seats()
                      if s.name not in (observer.name, session.engine.player_seat().name))
        snapshot = json.loads(json.dumps(session.snapshot()))
        values = {}
        for prefix in ("suspect", "support", "wait"):
            clone = OfflineSession(seed=0)
            clone.restore(deepcopy(snapshot))
            key = prefix if prefix == "wait" else f"{prefix}:{target.pos}"
            option = next(c for c in action_choices(clone, "speech", {}) if c["id"] == key)
            clone._broadcast_speech(clone.engine.player_seat(), Speech(**option["speech"]))
            values[prefix] = clone.agents[observer.name].brain.suspicion(target.name)
        self.assertGreater(values["suspect"], values["wait"])
        self.assertLess(values["support"], values["wait"])

    async def test_plain_speech_keeps_internal_source_links(self):
        for locale in ("en", "zh-CN"):
            session = await self.session(locale)
            player = session.engine.player_seat()
            asker = next(iter(session.agents.values()))
            session.emit({"type": "speech", "name": asker.name, "seat": asker.seat.pos,
                          "text": "Why?", "question_to": player.name, "accuse": player.name})
            ref = session._events[-1]["event_no"]
            replies = reply_choices(session._events, player.name, asker.name, locale)
            feedback_event = {"type": "speech", "day": 1, "name": player.name,
                              "event_no": ref + 1, "social_action": make("reserve_judgment", asker.name, [ref], ref)}
            options = action_choices(session, "speech", {}) + replies + feedback_choices(
                [feedback_event], asker.name, asker.style, locale)
            for option in options:
                self.assertNotRegex(option["label"], r"(?i)records?\s*\d+|记录\s*\d+")
            self.assertTrue(replies)
            self.assertEqual(replies[0]["action"]["sources"], [ref])

    async def test_menu_survives_resume_and_does_not_read_secret_results(self):
        session = await self.session()
        before = action_choices(session, "speech", {})
        clone = OfflineSession(seed=0)
        clone.restore(json.loads(json.dumps(session.snapshot())))
        self.assertEqual(before, action_choices(clone, "speech", {}))
        session.engine.seer_results = [{"night": 1, "target": 4, "result": "wolf"}]
        self.assertEqual(before, action_choices(session, "speech", {}))
