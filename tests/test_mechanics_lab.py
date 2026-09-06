from collections import Counter
from copy import deepcopy
from itertools import product
import json
import unittest

from test_game_options import fake_complete
from werewolf_web.research.extreme_game import play_game
from werewolf_web.research.extreme_profiles import roster_profiles
from werewolf_web.research.mechanics_lab import (
    ARMS, LabRules, MechanicsLab, lab_output_schema, screening_plan)
from werewolf_web.research.shadow_debate import PLAYERS


def complete(label, request):
    data = json.loads(fake_complete(label, request))
    if request["task"] == "challenge":
        data.update(kind="pass", target_record=None)
    if request["task"] == "revision" and request["lab_rules"]["revision_receipts"]:
        # Public fixture remains unknown; lawful candidate sets can shrink
        # between days, but stay unchanged between initial and revision.
        data["changes"] = []
    # Check schema/engine top-level agreement without another runtime dependency.
    # All row semantics and references are validated by the engine below.
    schema = lab_output_schema(request)
    assert set(data) == set(schema["required"]) == set(schema["properties"])
    return json.dumps(data)


def ready(rules=None):
    game = MechanicsLab(roster_profiles(2, PLAYERS), rules)
    game.night(complete)
    game.publish_tables({p: complete("initial", game.player_request(p, "initial")) for p in game.active})
    return game


def challenge(game, actor, target=None):
    target = target or next(p for p in game.active if p != actor)
    record = next(r for r in reversed(game.archive.history()) if r.table and r.actor == target)
    return {"kind": "table", "target": target, "target_record": record.event_id,
            "row_player": "B", "evidence": ["E000001"], "text": "你的依据不足，请解释。"}


def end_debate(game):
    for actor in game.challengers[len(game.exchanges):]:
        game.challenge(actor, complete("challenge", game.player_request(actor, "challenge")))
    game.close()


class MechanicsLabTest(unittest.TestCase):
    def test_target_reference_separate_from_disputed_sources(self):
        game = ready()
        actor = game.challengers[0]
        data = challenge(game, actor)
        self.assertNotIn(data["target_record"], data["evidence"])
        self.assertEqual(game.challenge(actor, json.dumps(data)), data["target"])
        game.respond(data["target"], '{"text":"这是我的推断，不是公开查验事实。"}')
        end_debate(game)
        self.assertEqual(game.stage, "revision")

    def test_private_future_and_wrong_target_refs_rejected_atomically(self):
        game = ready(); actor = game.challengers[0]
        before = game.research_export()
        for ref in ("P:B:1", "E999999", None):
            data = challenge(game, actor); data["target_record"] = ref
            with self.assertRaises(ValueError): game.challenge(actor, json.dumps(data))
            self.assertEqual(game.research_export(), before)
        for ref in ("P:B:1", "E999999"):
            data = challenge(game, actor); data["evidence"] = [ref]
            with self.assertRaises(ValueError): game.challenge(actor, json.dumps(data))
        data = challenge(game, actor); data["target"] = actor
        with self.assertRaises(ValueError): game.challenge(actor, json.dumps(data))
        data = challenge(game, actor); data["target"] = "A"  # killed on N1
        with self.assertRaises(ValueError): game.challenge(actor, json.dumps(data))
        self.assertEqual(game.research_export(), before)

    def test_public_ballot_question_without_target_table(self):
        game = ready(); actor = game.challengers[0]
        record = game.archive.append_event("D0", '公开投票：{"B":"C","C":"B"}；出局：平票无人出局，不翻身份。')
        data = challenge(game, actor)
        data.update(kind="action", row_player=None, target_record=record.event_id)
        self.assertEqual(game.challenge(actor, json.dumps(data)), data["target"])

    def test_ticket_consumption_and_host_limit(self):
        game = ready(LabRules(challenge_tickets=True)); actor = game.challengers[0]
        target = game.challenge(actor, json.dumps(challenge(game, actor)))
        self.assertEqual(game.tickets[actor], 0)
        target_tickets = game.tickets[target]
        game.respond(target, '{"text":"我选择回应。"}')
        self.assertEqual(game.tickets[target], target_tickets)
        second = game.challengers[1]
        game.tickets[second] = 0
        with self.assertRaisesRegex(ValueError, "no challenge tickets"):
            game.challenge(second, json.dumps(challenge(game, second)))
        end_debate(game)
        with self.assertRaises(ValueError): game.challenge(actor, json.dumps(challenge(game, actor)))

    def test_public_closure_and_batch_cutoff(self):
        game = ready()
        for actor in game.active:
            self.assertEqual(game.constraints[actor]["A"]["faction"], "good")
        self.assertEqual(game.constraints["C"]["A"]["role"], "")
        request = game.player_request(game.challengers[0], "challenge")
        timing = request["table_timing"]
        self.assertEqual(len({r["sealed_as_of"] for r in timing}), 1)
        for row in timing:
            self.assertLess(row["sealed_as_of"], game.archive.lookup(row["record"]).sequence)
        self.assertNotIn("ground_truth", request)
        self.assertNotIn("role_rotation", request)
        public = json.dumps(request["public"])
        self.assertNotIn("P:", public)

    def test_revision_receipts_and_atomic_validation(self):
        game = ready(LabRules(revision_receipts=True)); end_debate(game)
        actor = game.active[0]
        data = json.loads(complete("revision", game.player_request(actor, "revision")))
        data["public"][0]["confidence"] = "high"
        with self.assertRaisesRegex(ValueError, "missing changed-row"):
            game.validate_submission(actor, json.dumps(data))
        receipt = {"player": "A", "kind": "correction", "evidence": [], "text": "修正之前的置信度。"}
        data["changes"] = [receipt]
        game.validate_submission(actor, json.dumps(data))
        for changes in (None, [receipt, receipt], [{**receipt, "evidence": ["P:B:1"]}],
                        [{**receipt, "kind": "new_evidence"}]):
            with self.assertRaises(ValueError):
                game.validate_submission(actor, json.dumps({**data, "changes": changes}))
        responses = {p: complete("revision", game.player_request(p, "revision")) for p in game.active}
        responses[actor] = json.dumps({**data, "changes": []})
        before = deepcopy(game.research_export())
        with self.assertRaises(ValueError): game.publish_tables(responses)
        self.assertEqual(before, game.research_export())
        responses[actor] = json.dumps(data)
        game.publish_tables(responses)
        self.assertEqual(game.stage, "vote")
        self.assertIn("修正之前的置信度", json.dumps(game.public_export(), ensure_ascii=False))

    def test_plan_unapproved_and_one_factor_at_a_time(self):
        plan = screening_plan()
        self.assertEqual(plan["provider_calls_allowed"], 0)
        self.assertEqual(len(plan["conditions"]), 12)
        self.assertEqual(len({c["id"] for c in plan["conditions"]}), 12)
        self.assertTrue(all(sum(c["rules"].values()) <= 1 for c in plan["conditions"]))

    def test_84_offline_full_games(self):
        # Mock decisions test protocol coverage, NOT gameplay quality.
        for arm, rotation, profile in product(ARMS, range(7), range(4)):
            with self.subTest(arm=arm, rotation=rotation, profile=profile):
                game = MechanicsLab(roster_profiles(profile, PLAYERS), ARMS[arm], rotation)
                self.assertEqual(Counter(game.roles.values()), {"werewolf": 2, "seer": 1, "villager": 4})
                play_game(game, complete)
                self.assertIn(game.winner, ("good", "wolf"))
                self.assertEqual(game.research_export()["protocol"], "mechanics-lab-v2")
