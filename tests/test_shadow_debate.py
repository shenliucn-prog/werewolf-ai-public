"""Synthetic protocol tests, not measured model behavior."""

import json
import unittest

from werewolf_web.research.shadow_debate import PLAYERS, ShadowDay, decode
from werewolf_web.research.codex_shadow_run import extract_completion, run_protocol


def tables(request):
    private, public = [], []
    for p in PLAYERS:
        row = {"player": p, "roles": [], "status": "unknown", "confidence": "low",
               "candidate_roles": ["seer", "villager", "werewolf"],
               "faction": "", "faction_status": "unknown",
               "evidence": [], "rationale": "暂不确定", "alternatives": ""}
        public.append(row.copy())
        known = request["lawful_constraints"][p]
        private.append({**row,
            "candidate_roles": known["possible_roles"],
            **({"roles": [known["role"]], "status": "known"} if known["role"] else {}),
            **({"faction": known["faction"], "faction_status": "known"} if known["faction"] else {}),
            "evidence": known["evidence"] if known["role"] or known["faction"] else []})
    result = {"private": private, "public": public, "reason": "PRIVATE_STRATEGY"}
    if request["task"] == "revision":
        result["public_reason"] = "继续保留判断"
    return result


def batch(day, task="initial"):
    return {p: json.dumps(tables(day.player_request(p, task))) for p in PLAYERS}


def challenge(day, actor, target):
    event = next(r for r in day.archive.history() if r.table and r.actor == target)
    return json.dumps({"target": target, "row_player": target, "evidence": [event.event_id],
                       "text": "请解释你的身份判断依据。"})


def finish_debate(day):
    for actor in ("A", "C"):
        day.challenge(actor, challenge(day, actor, "B"))
        day.respond("B", '{"text":"目前依据不足，保留判断。"}')
    day.close()


class ShadowDayTest(unittest.TestCase):
    def test_candidates_can_remain_multiple_with_no_current_assertion(self):
        day = ShadowDay()
        data = batch(day)
        draft = json.loads(data["A"])
        row = draft["private"][1]
        self.assertEqual(row["roles"], [])
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(set(row["candidate_roles"]), {"villager", "werewolf"})
        day.validate_submission("A", data["A"])
        self.assertFalse(day.notebooks["A"].history())
        row["roles"] = row["candidate_roles"]
        with self.assertRaises(ValueError):
            day.validate_submission("A", json.dumps(draft))

    def test_current_assertion_must_be_a_single_candidate(self):
        for assertion in (["seer"], ["villager", "werewolf"]):
            day = ShadowDay()
            draft = json.loads(batch(day)["A"])
            draft["private"][1].update(roles=assertion, status="inferred")
            with self.assertRaises(ValueError):
                day.validate_submission("A", json.dumps(draft))

    def test_format_gate_stops_before_remaining_seats(self):
        day = ShadowDay()
        calls = []
        def invalid(label, request):
            calls.append(label)
            data = tables(request)
            if request["actor"] == "B":
                data["private"][0]["roles"] = ["seer", "villager"]
            return json.dumps(data)
        with self.assertRaises(ValueError):
            run_protocol(day, invalid)
        self.assertEqual(calls, ["initial-A", "initial-B"])
        self.assertEqual(day.archive.sequence, 1)

    def test_provider_schema_and_cli_only_constrain_table_calls(self):
        from werewolf_web.research.shadow_schema import table_schema
        from werewolf_web.research.codex_shadow_run import cli_command
        schema = table_schema("initial")
        variants = schema["properties"]["private"]["items"]["anyOf"]
        self.assertEqual(variants[0]["properties"]["roles"]["maxItems"], 0)
        self.assertEqual(variants[1]["properties"]["roles"]["maxItems"], 1)
        self.assertIn("candidate_roles", variants[0]["required"])
        self.assertIsNone(table_schema("vote"))
        self.assertIn("--output-schema", cli_command("codex", "schema.json"))
        self.assertNotIn("--output-schema", cli_command("codex"))

    def test_actions_forbid_extra_private_tables_and_initial_reuse_is_exact(self):
        from werewolf_web.research.shadow_schema import output_schema
        from werewolf_web.research.codex_shadow_run import initial_reuse
        day = ShadowDay()
        source = {"calls": [{"label": f"initial-{p}",
            "request": json.loads(json.dumps(day.player_request(p, "initial"))),
            "response": raw} for p, raw in batch(day).items()]}
        self.assertEqual(len(initial_reuse(source, day)), 7)
        self.assertEqual(day.archive.sequence, 1)
        source["calls"][0]["request"]["actor"] = "B"
        with self.assertRaises(ValueError):
            initial_reuse(source, day)
        day.publish_tables(batch(day))
        request = day.player_request("A", "challenge")
        schema = output_schema(request)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"target", "row_player", "evidence", "text"})
        self.assertNotIn("两张表必须", request["instruction"])

    def test_lawful_closure_without_research_truth(self):
        day = ShadowDay()
        self.assertEqual(day.constraints["A"]["C"]["role"], "villager")
        self.assertNotIn("seer", day.constraints["A"]["D"]["possible_roles"])
        for actor in ("B", "F"):
            for target in "ACDEG":
                self.assertEqual(day.constraints[actor][target]["faction"], "good")
                self.assertEqual(day.constraints[actor][target]["role"], "")
        self.assertEqual(day.constraints["D"]["B"]["faction"], "")

    def test_redundant_faction_in_roles_rejected_but_separate_fields_accepted(self):
        day = ShadowDay()
        good = batch(day)
        bad = json.loads(good["C"])
        bad["private"][2]["roles"].append("good")
        with self.assertRaises(ValueError):
            day.publish_tables({**good, "C": json.dumps(bad)})
        day.publish_tables(good)

    def test_private_constraints_and_faction_certainty_enforced(self):
        for actor, player, change in (
            ("A", "D", {"roles": ["seer"], "status": "inferred"}),
            ("B", "A", {"faction": "", "faction_status": "unknown"}),
            ("D", "B", {"faction": "wolf", "faction_status": "known", "evidence": ["P:D:1"]}),
        ):
            day = ShadowDay()
            data = batch(day)
            bad = json.loads(data[actor])
            bad["private"][PLAYERS.index(player)].update(change)
            with self.assertRaises(ValueError):
                day.publish_tables({**data, actor: json.dumps(bad)})

    def test_initial_projection_only_owner_private(self):
        day = ShadowDay()
        for p in PLAYERS:
            request = json.dumps(day.player_request(p, "initial"))
            self.assertIn(f"P:{p}:", request)
            for other in set(PLAYERS) - {p}:
                self.assertNotIn(f"P:{other}:", request)
            self.assertNotIn("ground_truth", request)
            self.assertNotIn('"shadow"', request)

    def test_atomic_batch_and_same_cutoff(self):
        day = ShadowDay()
        values = batch(day)
        bad = json.loads(values["G"])
        bad["public"] = bad["public"][:-1]
        values["G"] = json.dumps(bad)
        with self.assertRaises(ValueError):
            day.publish_tables(values)
        self.assertEqual(day.archive.sequence, 1)
        self.assertTrue(all(not b.history() for b in day.notebooks.values()))
        day.publish_tables(batch(day))
        self.assertTrue(all(day.archive.table(p, 1).as_of == 1 for p in PLAYERS))
        public = json.dumps(day.public_export())
        self.assertNotIn("PRIVATE_STRATEGY", public)
        self.assertNotIn("P:", public)

    def test_private_refs_never_publish_and_batch_cannot_cite_itself(self):
        for ref in ("P:A:1", "E000002"):
            day = ShadowDay()
            values = batch(day)
            bad = json.loads(values["A"])
            bad["public"][0]["evidence"] = [ref]
            values["A"] = json.dumps(bad)
            with self.assertRaises(ValueError):
                day.publish_tables(values)
            self.assertEqual(day.archive.sequence, 1)

    def test_known_locked_and_no_invented_certainty(self):
        for player in ("A", "C", "D"):
            day = ShadowDay()
            values = batch(day)
            bad = json.loads(values["A"])
            row = bad["private"][PLAYERS.index(player)]
            row.update(roles=["werewolf"], status="known", evidence=["P:A:1"])
            values["A"] = json.dumps(bad)
            with self.assertRaises(ValueError):
                day.publish_tables(values)

    def test_host_bounds_target_evidence_and_pending_response(self):
        day = ShadowDay()
        day.publish_tables(batch(day))
        with self.assertRaises(ValueError):
            day.challenge("C", challenge(day, "C", "B"))
        with self.assertRaises(ValueError):
            day.close()
        bad = json.loads(challenge(day, "A", "B"))
        bad["evidence"] = ["E000001"]
        with self.assertRaises(ValueError):
            day.challenge("A", json.dumps(bad))
        day.challenge("A", challenge(day, "A", "B"))
        with self.assertRaises(ValueError):
            day.respond("F", '{"text":"不是我的回应机会"}')
        with self.assertRaises(ValueError):
            day.challenge("C", challenge(day, "C", "B"))
        day.respond("B", '{"text":"保留判断"}')
        day.challenge("C", challenge(day, "C", "B"))
        day.respond("B", '{"text":"仍保留判断"}')
        with self.assertRaises(ValueError):
            day.challenge("A", challenge(day, "A", "B"))

    def test_revision_vote_visibility_and_shadow_does_not_change_state(self):
        day = ShadowDay()
        day.publish_tables(batch(day))
        finish_debate(day)
        day.publish_tables(batch(day, "revision"))
        for p in PLAYERS:
            req = day.player_request(p, "vote")
            self.assertEqual(req["own_private"]["tables"][-1]["version"], 2)
            self.assertEqual(len([r for r in req["public"]["records"] if r["table"]]), 14)
        votes = {p: json.dumps({"target": "B" if p != "B" else "A", "reason": "SECRET_VOTE_REASON"})
                 for p in PLAYERS}
        with self.assertRaises(ValueError):
            day.publish_votes({**votes, "G": '{"target":"G","reason":"self"}'})
        self.assertFalse(day.votes)
        day.publish_votes(votes)
        self.assertNotIn("SECRET_VOTE_REASON", json.dumps(day.public_export()))
        before = {p: b.export_for_owner() for p, b in day.notebooks.items()}
        archive_before = day.public_export()
        for context in day.judgment_contexts():
            self.assertNotIn("P:", json.dumps([e.text for e in context.evidence]))
            self.assertFalse(any("投票结果" in e.text for e in context.evidence))
            evidence = context.evidence[-1]
            raw = json.dumps({"request_id": context.request_id, "observer": context.observer,
                "target": context.target, "verdict": "insufficient_evidence", "confidence": 0.5,
                "reason": "合成测试", "citations": [{"event_id": evidence.event_id, "quote": evidence.text}]})
            day.record_shadow(context, raw)
            with self.assertRaises(ValueError):
                day.record_shadow(context, raw)
        self.assertEqual(before, {p: b.export_for_owner() for p, b in day.notebooks.items()})
        self.assertEqual(archive_before, day.public_export())

    def test_pass_slots_and_end_to_end_injected_runner(self):
        day = ShadowDay()
        calls = []
        def complete(label, request):
            calls.append((label, request))
            task = request["task"]
            if task in ("initial", "revision"):
                return json.dumps(tables(request))
            if task == "challenge":
                return '{"target":null,"row_player":null,"evidence":[],"text":"没有具体质疑"}'
            return json.dumps({"target": "B" if request["actor"] != "B" else "A", "reason": "测试"})
        run_protocol(day, complete)
        self.assertEqual(day.stage, "complete")
        self.assertEqual(len(calls), 23)
        self.assertFalse(day.shadow)
        self.assertEqual(len(day.votes), 7)
        self.assertTrue(all(day.notebooks[p].export_for_owner()["decisions"][0]["table_version"] == 2
                            for p in PLAYERS))

    def test_json_strict_and_codex_event_fail_closed(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '```json\n{}\n```'):
            with self.assertRaises(ValueError):
                decode(raw)
        safe = [{"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
                {"type": "turn.completed", "usage": {"input_tokens": 1}}]
        self.assertEqual(extract_completion("\n".join(map(json.dumps, safe)))[0], "{}")
        for kind in ("command_execution", "mcp_tool_call", "web_search", "future_unknown_tool"):
            bad = safe + [{"type": "item.completed", "item": {"type": kind}}]
            with self.assertRaises(ValueError):
                extract_completion("\n".join(map(json.dumps, bad)))


if __name__ == "__main__":
    unittest.main()
