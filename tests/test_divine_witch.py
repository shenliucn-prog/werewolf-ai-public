import asyncio
from copy import deepcopy
import json
import random
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from werewolf_web.game.engine import BOARD_MAP, GameEngine
from werewolf_web.ai.brain import Brain
from werewolf_web.ai.host import RuleGuide
from werewolf_web.ai.strategy import InformationSet
from werewolf_web.chat_game import parse_action, _ordinary_request_prompt
from werewolf_web.run import GameSession, boards


def engine(board="divine_witch_dual", locale="zh-CN"):
    e = GameEngine(board, seed=21, player_role="witch", locale=locale)
    e.setup()
    return e


class DivineRulesTest(unittest.TestCase):
    def test_extreme_replay_independent_of_python_hash_seed(self):
        code = '''
import asyncio, hashlib, json
from unittest.mock import patch
from werewolf_web.research.divine_witch_screen import run_one
sleep = asyncio.sleep
async def fast(_): await sleep(0)
async def main():
    with patch("werewolf_web.run.asyncio.sleep", fast):
        results = [await run_one("divine_witch_dual", 0, c) for c in (0, 1)]
    print(hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest())
asyncio.run(main())
'''
        digests = [subprocess.check_output([sys.executable, "-c", code],
                   env={**os.environ, "PYTHONHASHSEED": seed}, text=True).strip() for seed in ("1", "99")]
        self.assertEqual(digests[0], digests[1])

    def test_repeat_rescue_and_poison_stock(self):
        e = engine(); victim = next(s for s in e.seats.values() if s.role == "civilian")
        wolves = [s for s in e.seats.values() if s.is_wolf]
        for wolf in wolves[:3]:
            e.start_night()
            e.resolve_night({"wolves": {"target": victim.pos}, "witch": {"save": victim.pos, "poison": wolf.pos}})
            self.assertTrue(victim.alive)
            self.assertFalse(wolf.alive)
            self.assertTrue(e.witch_antidote)
            self.assertTrue(e.witch_poison)
        self.assertIn(("witch", e.player_seat().pos), e.start_night())

    def test_single_variant_repeats_but_cannot_double(self):
        e = engine("divine_witch"); victim = next(s for s in e.seats.values() if s.role == "civilian")
        wolf = next(s for s in e.seats.values() if s.is_wolf)
        for _ in range(3):
            e.start_night()
            before = deepcopy({k: v for k, v in e.__dict__.items() if k != "rng"})
            rng_before = e.rng.getstate()
            with self.assertRaises(ValueError):
                e.resolve_night({"wolves": {"target": victim.pos}, "witch": {"save": victim.pos, "poison": wolf.pos}})
            self.assertEqual({k: v for k, v in e.__dict__.items() if k != "rng"}, before)
            self.assertEqual(e.rng.getstate(), rng_before)
            e.resolve_night({"wolves": {"target": victim.pos}, "witch": {"save": victim.pos}})
        self.assertTrue(victim.alive)

    def test_no_invincibility_resurrection_or_self_poison(self):
        for board in ("divine_witch", "divine_witch_dual"):
            e = engine(board); witch = e.player_seat()
            e.start_night(); e.resolve_night({"wolves": {"target": witch.pos}, "witch": {"save": witch.pos}})
            e.start_night()
            with self.assertRaises(ValueError): e.resolve_night({"wolves": {"target": witch.pos}, "witch": {"save": witch.pos}})
            with self.assertRaises(ValueError): e.resolve_night({"witch": {"poison": witch.pos}})
            e.resolve_night({"wolves": {"target": witch.pos}})
            self.assertFalse(witch.alive)
            self.assertNotIn(("witch", witch.pos), e.start_night())
            with self.assertRaises(ValueError): e.resolve_night({"witch": {"save": witch.pos}})

    def test_milk_and_poison_override_rescue(self):
        for extra in ("guard", "poison"):
            e = engine(); victim = next(s for s in e.seats.values() if s.role == "civilian")
            e.start_night()
            actions = {"wolves": {"target": victim.pos}, "witch": {"save": victim.pos}}
            if extra == "guard": actions["guard"] = {"target": victim.pos}
            else: actions["witch"]["poison"] = victim.pos
            e.resolve_night(actions)
            self.assertFalse(victim.alive)
            self.assertEqual(victim.death_cause, "knife" if extra == "guard" else "poison")

    def test_standard_unchanged_and_default_board(self):
        self.assertEqual(next(iter(BOARD_MAP)), "classic")
        e = engine("classic"); victim = next(s for s in e.seats.values() if s.is_wolf)
        e.start_night(); e.resolve_night({"witch": {"poison": victim.pos}})
        self.assertFalse(e.witch_poison)
        with self.assertRaises(ValueError):
            e.resolve_night({"witch": {"poison": next(s.pos for s in e.alive_seats() if s.is_wolf)}})

    def test_round_limit_not_before_complete_cycles(self):
        e = engine(); e.night_count = 20; e.day_count = 19
        self.assertFalse(e.check_round_limit())
        e.day_count = 20
        self.assertTrue(e.check_round_limit())
        self.assertEqual(e.winner, "draw")
        e = engine("classic"); e.night_count = e.day_count = 20
        self.assertFalse(e.check_round_limit())

    def test_claimed_divine_witch_is_a_public_wolf_priority(self):
        e = engine(); wolf = next(s for s in e.seats.values() if s.is_wolf)
        b = Brain(wolf, e, {}, random.Random(5)); b.style.logic = .95
        witch = e.player_seat(); other = next(s for s in e.seats.values() if s.role == "civilian")
        b.claims = {witch.name: "witch"}
        with patch.object(b, "suspicion", return_value=.35), patch.object(b, "gut_of", return_value=.5), \
             patch.object(b.rng, "random", return_value=0):
            decision = b._wolves([witch.pos, other.pos])
        self.assertEqual(decision.target, witch.pos)
        # Swap hidden identities: public claims and the decision remain unchanged.
        witch.role, other.role = other.role, witch.role
        with patch.object(b, "suspicion", return_value=.35), patch.object(b, "gut_of", return_value=.5), \
             patch.object(b.rng, "random", return_value=0):
            self.assertEqual(b._wolves([witch.pos, other.pos]).target, witch.pos)

    def test_npc_dual_decision_and_one_potion_tradeoff(self):
        for board in ("classic", "divine_witch", "divine_witch_dual"):
            e = engine(board); e.start_night()
            victim = next(s for s in e.seats.values() if s.role == "civilian")
            suspect = next(s for s in e.seats.values() if s.is_wolf)
            b = Brain(e.player_seat(), e, {}, random.Random(5)); b.style.aggression = .95
            with patch.object(b, "suspicion", side_effect=lambda name: .9 if name == suspect.name else .1):
                decision = b.night("witch", [s.pos for s in e.alive_seats() if s != b.me], knife=victim.pos)
            self.assertEqual(decision.save, None if board == "divine_witch" else victim.pos)
            self.assertEqual(decision.poison, None if board == "classic" else suspect.pos)

    def test_rules_host_context_and_chat(self):
        for locale in ("zh-CN", "en"):
            e = engine(locale=locale)
            answer = RuleGuide().answer("How does the Witch work?" if locale == "en" else "女巫如何用药？", e)
            self.assertIn("unlimited" if locale == "en" else "不限总次数", answer)
            self.assertNotIn(e.player_seat().name, answer)
            b = Brain(e.player_seat(), e, {}, random.Random(1))
            self.assertIn("witch", InformationSet.from_brain(b).public_rules)
        data = {"role_key": "witch", "antidote": True, "poison": True, "dual_potions": True,
                "save_candidates": [{"pos": 2, "name": "X"}], "candidates": [{"pos": 3, "name": "Y"}]}
        self.assertEqual(parse_action("night", data, "save 2 poison 3"), {"save": 2, "poison": 3})
        self.assertIn("AND/OR", _ordinary_request_prompt("night", data, "en"))
        self.assertIsNone(parse_action("night", {**data, "dual_potions": False}, "save 2 poison 3"))


class DivineSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_backend_dual_validation_and_description(self):
        for board in ("classic", "divine_witch", "divine_witch_dual"):
            session = GameSession(board, {"enabled": False}, player_role="witch", seed=21)
            session.engine.setup(); session.engine.start_night()
            victim = next(s for s in session.engine.seats.values() if s.role == "civilian")
            wolf = next(s for s in session.engine.seats.values() if s.is_wolf)
            with patch.object(session, "ask_player", new_callable=AsyncMock, return_value={}) as ask:
                await session._witch_action(victim.pos)
            data = ask.call_args.args[1]
            self.assertEqual(data["dual_potions"], board == "divine_witch_dual")
            session.pending = {"kind": "night", "data": data}
            self.assertEqual(session.submit({"save": victim.pos, "poison": wolf.pos}), board == "divine_witch_dual")
        response = await boards("en")
        board = next(b for b in response["boards"] if b["id"] == "divine_witch")
        self.assertEqual(board["role_labels"]["witch"], "Divine Witch")

    async def test_human_witch_complete_both_modes_languages_and_variants(self):
        sleep = asyncio.sleep
        async def fast(_): await sleep(0)
        for board in ("divine_witch", "divine_witch_dual"):
            for locale in ("zh-CN", "en"):
                for mode in (False, True):
                    with self.subTest(board=board, locale=locale, mode=mode), tempfile.TemporaryDirectory() as memory, \
                         patch("werewolf_web.run.asyncio.sleep", fast), patch("werewolf_web.ai.host.HostAgent.evolve"):
                        session = GameSession(board, {"enabled": False}, seed=7, player_role="witch", locale=locale, conjecture=mode)
                        session.memory_dir = memory; ended = False
                        async for event in session.events():
                            self.assertNotEqual(event["type"], "error", event)
                            if event["type"] == "gameover": ended = True
                            if event["type"] != "request": continue
                            kind, data = event["kind"], event["data"]
                            if kind == "conjecture": answer = {k: data[k] for k in ("private", "public")}
                            elif kind in ("speech", "table_reply"): answer = {"text": "暂不表态"}
                            elif kind == "election_up": answer = {"up": False}
                            elif kind == "night":
                                save = next(iter(data.get("save_candidates", [])), {}).get("pos")
                                poison = next((c["pos"] for c in data.get("candidates", []) if c["pos"] != save), None)
                                answer = {"save": save, "poison": poison if data["dual_potions"] or save is None else None}
                            else: answer = {"target": data["candidates"][0]["pos"] if data.get("candidates") else None}
                            self.assertTrue(session.submit(answer), (kind, answer))
                        self.assertTrue(ended)
