"""Rules, private information, and shared browser/chat action regressions."""
import asyncio
import copy
import os
import random
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from werewolf_web.ai.brain import Brain, Decision
from werewolf_web.ai.strategy import InformationSet
from werewolf_web.chat_game import parse_action, _request_prompt
from werewolf_web.game.engine import GameEngine
from werewolf_web.run import GameSession


def game(board="classic", locale="en"):
    engine = GameEngine(board, seed=7, locale=locale)
    engine.setup()
    return engine


def role(engine, key):
    return next(s for s in engine.seats.values() if s.role == key)


def human(engine, key):
    for seat in engine.seats.values():
        seat.is_player = seat.role == key
    return engine.player_seat()


class SpecialRulesTest(unittest.TestCase):
    def test_charm_target_stays_private_and_expires_when_skipped(self):
        for locale in ("zh-CN", "en"):
            e = game("wolf_beauty_knight", locale)
            victim = role(e, "civilian")
            beauty = role(e, "wolf_beauty")
            events = e.resolve_night({"wolf_beauty": {"target": victim.pos}})
            self.assertEqual(events, [])
            self.assertEqual(e.charmed, victim.name)
            deaths = []
            e._kill(beauty.pos, "exile", deaths)
            self.assertFalse(victim.alive)
            e = game("wolf_beauty_knight", locale)
            e.resolve_night({"wolf_beauty": {"target": role(e, "civilian").pos}})
            e.resolve_night({})
            self.assertIsNone(e.charmed)

    def test_seer_only_gets_faction_even_for_hidden_wolf(self):
        for target_role in ("witch", "hidden_wolf", "werewolf"):
            e = game("hidden_wolf_crow")
            seer = human(e, "seer")
            target = role(e, target_role)
            e.resolve_night({"seer": {"target": target.pos}})
            expected = {"night": 0, "target": target.pos, "name": target.name,
                        "result": "wolf" if target_role == "werewolf" else "good"}
            self.assertEqual(e.player_view()["seer_results"], [expected])
            info = InformationSet.from_brain(Brain(seer, e, {}, random.Random(1)))
            self.assertEqual(info.private["seer_results"], [expected])
            human(e, "witch")
            self.assertEqual(e.player_view()["seer_results"], [])

    def test_knight_wolf_duel_ends_day_and_is_once_per_game(self):
        e = game("white_wolf_knight")
        e.start_day()
        knight, wolf = role(e, "knight"), role(e, "werewolf")
        events = e.resolve_day_skill(knight.pos, wolf.pos)
        self.assertTrue(knight.alive)
        self.assertFalse(wolf.alive)
        self.assertEqual(e.phase, "night")
        self.assertEqual(e.history[-len(events):], events)
        e.start_day()
        with self.assertRaises(ValueError):
            e.resolve_day_skill(knight.pos, role(e, "civilian").pos)

    def test_knight_good_duel_kills_knight_and_day_continues(self):
        e = game("white_wolf_knight")
        e.start_day()
        knight, target = role(e, "knight"), role(e, "civilian")
        e.resolve_day_skill(knight.pos, None)
        self.assertFalse(e.knight_used)
        e.resolve_day_skill(knight.pos, target.pos)
        self.assertFalse(knight.alive)
        self.assertTrue(target.alive)
        self.assertEqual(e.phase, "day")

    def test_white_wolf_king_takes_target_and_ends_day(self):
        e = game("white_wolf_knight")
        e.start_day()
        king, target = role(e, "white_wolf_king"), role(e, "civilian")
        e.resolve_day_skill(king.pos, target.pos)
        self.assertFalse(king.alive)
        self.assertFalse(target.alive)
        self.assertEqual(e.phase, "night")
        with self.assertRaises(ValueError):
            e.resolve_day_skill(king.pos, role(e, "seer").pos)

    def test_day_skills_reject_invalid_phase_actor_and_targets(self):
        e = game("white_wolf_knight")
        knight = role(e, "knight")
        target = role(e, "civilian")
        with self.assertRaises(ValueError):
            e.resolve_day_skill(knight.pos, target.pos)
        e.start_day()
        target.alive = False
        for invalid in (target.pos, knight.pos, True, 99, "2"):
            with self.assertRaises(ValueError):
                e.resolve_day_skill(knight.pos, invalid)
            self.assertFalse(e.knight_used)
        with self.assertRaises(ValueError):
            e.resolve_day_skill(role(e, "seer").pos, knight.pos)

    def test_crow_extra_vote_is_single_round_and_not_sheriff_weighted(self):
        e = game("hidden_wolf_crow")
        e.start_day()
        crow, target = role(e, "crow"), role(e, "werewolf")
        other = role(e, "seer")
        e.sheriff = crow.pos
        e.resolve_day_skill(crow.pos, target.pos)
        self.assertEqual(e.vote_tally({crow.pos: target.pos, target.pos: other.pos}),
                         {target.pos: 2.5, other.pos: 1.0})
        with self.assertRaises(ValueError):
            e.resolve_day_skill(crow.pos, other.pos)
        e.start_day()
        self.assertEqual(e.vote_tally({crow.pos: target.pos}), {target.pos: 1.5})
        e.resolve_day_skill(crow.pos, other.pos)
        other.alive = False
        self.assertEqual(e.vote_tally({}), {})

    def test_gravekeeper_result_is_faction_only_and_skips_empty_exile(self):
        e = game("stone_ghost")
        e.start_night()
        self.assertEqual(e.grave_results, [])
        e.start_day()
        target = role(e, "werewolf")
        e.resolve_vote({}, target.pos)
        e.start_night()
        self.assertEqual(e.grave_results, [{"night": 2, "target": target.pos,
                                          "name": target.name, "result": "wolf"}])
        for key in ("gravekeeper", "seer", "stone_ghost"):
            seat = human(e, key)
            info = InformationSet.from_brain(Brain(seat, e, {}, random.Random(1)))
            self.assertEqual("grave_results" in info.private, key == "gravekeeper")
            self.assertEqual(bool(e.player_view()["grave_results"]), key == "gravekeeper")
        e.start_day()
        e.resolve_vote({}, None)
        e.start_night()
        self.assertEqual(len(e.grave_results), 1)

    def test_stone_ghost_inherits_kill_only_after_pack_is_gone(self):
        e = game("stone_ghost")
        victim = role(e, "civilian")
        self.assertNotIn("stone_ghost_kill", dict(e.start_night()))
        with self.assertRaises(ValueError):
            e.resolve_night({"stone_ghost_kill": {"target": victim.pos}})
        for wolf in e.wolves():
            wolf.alive = False
        self.assertIn("stone_ghost_kill", dict(e.start_night()))
        self.assertIn("stone_ghost", dict(e.start_night()))
        self.assertEqual(e.wolves(), [])
        e.resolve_night({"stone_ghost_kill": {"target": victim.pos},
                         "stone_ghost": {"target": role(e, "seer").pos}})
        self.assertFalse(victim.alive)
        self.assertEqual(len(e.sg_results), 1)

    def test_illegal_night_batches_are_atomic(self):
        e = game()
        e.start_night()
        victim, witch, guard = role(e, "civilian"), role(e, "witch"), role(e, "guard")
        e.guard_last = victim.pos
        batches = [
            {"seer": {"target": victim.pos}, "guard": {"target": victim.pos}},
            {"wolves": {"target": victim.pos}, "witch": {"save": victim.pos, "poison": guard.pos}},
            {"witch": {"save": victim.pos}},
            {"witch": {"poison": witch.pos}},
            {"seer": {"target": True}},
            {"seer": {"target": 99}},
            {"stone_ghost_kill": {"target": victim.pos}},
        ]
        before = copy.deepcopy(e.__dict__)
        for batch in batches:
            with self.assertRaises(ValueError):
                e.resolve_night(batch)
            for field in ("seats", "history", "seer_results", "witch_antidote", "witch_poison", "phase"):
                self.assertEqual(getattr(e, field), before[field])

    def test_poison_overrides_knife_for_hunter_and_spent_potion_rejected(self):
        e = game()
        hunter = role(e, "hunter")
        e.resolve_night({"wolves": {"target": hunter.pos}, "witch": {"poison": hunter.pos}})
        self.assertEqual(hunter.death_cause, "poison")
        with self.assertRaises(ValueError):
            e.resolve_night({"witch": {"poison": role(e, "civilian").pos}})

    def test_npc_witch_cannot_self_save_after_first_night(self):
        e = game()
        e.night_count = 2
        witch = role(e, "witch")
        brain = Brain(witch, e, {}, random.Random(1))
        decision = brain.night("witch", [s.pos for s in e.alive_seats() if s != witch],
                               knife=witch.pos, antidote=True, poison=True)
        self.assertIsNone(decision.save)

    def test_knight_decision_does_not_peek_at_target_role(self):
        e = game("white_wolf_knight")
        brain = Brain(role(e, "knight"), e, {}, random.Random(1))
        targets = [role(e, "civilian"), role(e, "werewolf")]
        with patch.object(brain, "suspicion", return_value=0.8):
            before = brain.day_skill([s.pos for s in targets]).target
            targets[0].role, targets[1].role = targets[1].role, targets[0].role
            targets[0].is_wolf, targets[1].is_wolf = targets[1].is_wolf, targets[0].is_wolf
            self.assertEqual(before, brain.day_skill([s.pos for s in targets]).target)


class SpecialSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_full_games_with_each_human_day_role_in_both_languages(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("werewolf_web.run.asyncio.sleep", new=AsyncMock()), \
                patch("werewolf_web.ai.host.STYLE_PATH", os.path.join(tmp, "host.json")), \
                patch("werewolf_web.ai.host.REVIEW_DIR", tmp), \
                patch.object(Brain, "day_skill", return_value=Decision(target=None)):
            for locale in ("zh-CN", "en"):
                for board, key in (("white_wolf_knight", "knight"),
                                   ("white_wolf_knight", "white_wolf_king"),
                                   ("hidden_wolf_crow", "crow")):
                    session = GameSession(board, {"enabled": False}, seed=7, locale=locale)
                    session.memory_dir = os.path.join(tmp, locale, key)
                    setup = session.engine.setup
                    async_night = session._gather_night
                    def setup_human():
                        setup()
                        human(session.engine, key)
                    async def night(requests):
                        # Keep the human alive until their first ability window.
                        return {} if session.engine.night_count == 1 else await async_night(requests)
                    seen_skill = False
                    seen_first_day_vote = False
                    seen_nights = 0
                    events = []
                    with patch.object(session.engine, "setup", side_effect=setup_human), \
                            patch.object(session, "_gather_night", side_effect=night):
                        async for event in session.events():
                            events.append(event)
                            self.assertNotEqual(event["type"], "error", (key, locale))
                            self.assertLess(len(events), 1800)
                            if event.get("phase") == "night" and event["type"] == "narration":
                                seen_nights += 1
                            if event["type"] == "vote_result" and seen_nights == 1:
                                seen_first_day_vote = True
                            if event["type"] != "request":
                                continue
                            kind, data = event["kind"], event["data"]
                            if kind == "day_skill":
                                seen_skill = True
                                wolf = next(s for s in session.engine.wolves() if not s.is_player)
                                raw = f"choose {wolf.pos}"
                            elif kind in ("speech", "table_reply"):
                                raw = "I am listening." if locale == "en" else "我先听大家发言。"
                            elif kind == "election_up":
                                raw = "no"
                            elif data.get("role_key") == "witch":
                                raw = "pass"
                            else:
                                raw = str(data["candidates"][0]["pos"]) if data.get("candidates") else "pass"
                            action = parse_action(kind, data, raw)
                            self.assertIsNotNone(action, (kind, data))
                            self.assertTrue(session.submit(action))
                    self.assertTrue(seen_skill, (key, locale))
                    self.assertEqual(seen_first_day_vote, key == "crow")
                    # The endgame commit (gameover) lands first; the review is a
                    # separate, retryable step emitted after it.
                    self.assertEqual(events[-1]["type"], "review")
                    self.assertTrue(any(e["type"] == "gameover" for e in events))

    def session(self, board, locale="en"):
        session = GameSession(board, {"enabled": False}, seed=7, locale=locale)
        session.engine.setup()
        return session

    async def test_day_action_is_shared_by_chat_and_session(self):
        for locale in ("en", "zh-CN"):
            for board, key in (("white_wolf_knight", "knight"),
                               ("white_wolf_knight", "white_wolf_king"),
                               ("hidden_wolf_crow", "crow")):
                session = self.session(board, locale)
                e = session.engine
                seat = human(e, key)
                e.start_day()
                with patch.object(session, "_post_death_triggers", new=AsyncMock()), \
                        patch("werewolf_web.run.asyncio.sleep", new=AsyncMock()):
                    task = asyncio.create_task(session._day_skill(seat, crow=key == "crow"))
                    event = await session.event_q.get()
                    self.assertEqual(event["kind"], "day_skill")
                    self.assertIsNone(parse_action("day_skill", event["data"], "choose 99"))
                    self.assertEqual(parse_action("day_skill", event["data"], "pass"), {"target": None})
                    self.assertFalse(session.submit({"target": seat.pos}))
                    target = role(e, "werewolf").pos
                    response = parse_action("day_skill", event["data"], f"choose {target}")
                    self.assertTrue(session.submit(response))
                    self.assertFalse(session.submit(response))
                    await task
                    if locale == "en":
                        self.assertNotRegex(_request_prompt("day_skill", event["data"], locale), r"[\u4e00-\u9fff]")
                self.assertTrue(e.crow_target == target if key == "crow" else not e.seat_at(target).alive)

    async def test_gravekeeper_delivery_never_reaches_other_human_roles(self):
        session = self.session("stone_ghost")
        e = session.engine
        e.start_day()
        e.resolve_vote({}, role(e, "werewolf").pos)
        e.start_night()
        human(e, "seer")
        session._deliver_grave_result()
        self.assertTrue(session.event_q.empty())
        human(e, "gravekeeper")
        session._deliver_grave_result()
        result = session.event_q.get_nowait()
        self.assertEqual(result["type"], "private")
        self.assertIn("Gravekeeper", result["text"])

    async def test_stone_ghost_human_kill_reaches_witch_before_resolution(self):
        session = self.session("stone_ghost")
        e = session.engine
        human(e, "stone_ghost")
        for wolf in e.wolves():
            wolf.alive = False
        victim = role(e, "civilian")
        with patch.object(session, "ask_player", new=AsyncMock(return_value={"target": victim.pos})) as ask, \
                patch.object(session, "_witch_action", new=AsyncMock(return_value={})) as witch:
            actions = await session._gather_night([("witch", None), ("stone_ghost_kill", None)])
        witch.assert_awaited_once_with(victim.pos)
        self.assertEqual(ask.call_args.args[1]["role_key"], "stone_ghost_kill")
        e.resolve_night(actions)
        self.assertFalse(victim.alive)

    async def test_reverse_seat_order_death_chain_finishes_before_return(self):
        session = self.session("wolf_king")
        e = session.engine
        hunter, king = role(e, "hunter"), role(e, "wolf_king")
        victim = role(e, "civilian")
        # Process the living King first; the Hunter then kills that earlier seat.
        e.seats = dict(sorted(e.seats.items(), key=lambda item: item[1] != king))
        e._kill(hunter.pos, "knife", [])
        async def aim(shooter, _label):
            return king.pos if shooter == hunter else victim.pos
        with patch.object(session, "_gun_target", side_effect=aim), \
                patch("werewolf_web.run.asyncio.sleep", new=AsyncMock()):
            await session._post_death_triggers()
            self.assertFalse(king.alive)
            self.assertFalse(victim.alive)
            count = session.event_q.qsize()
            await session._post_death_triggers()
            self.assertEqual(count, session.event_q.qsize())


if __name__ == "__main__":
    unittest.main()
