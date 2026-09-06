"""Offline-ready research variants. No provider calls or normal-game changes.

Keep v1 sources intact so the original four artifacts remain replayable.
The host checks structure and public references, never the truth of a claim.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import json

from .conjecture import PrivateNotebook
from .extreme_game import ExtremeGame
from .identity_constraints import possibilities
from .shadow_debate import PLAYERS, ROLES, decode, fields, prose
from .shadow_schema import obj, output_schema


@dataclass(frozen=True)
class LabRules:
    challenge_tickets: bool = False
    revision_receipts: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValueError("mechanic switches must be booleans")


ARMS = {"baseline": LabRules(), "tickets": LabRules(challenge_tickets=True),
        "receipts": LabRules(revision_receipts=True)}
CHANGE_FIELDS = ("roles", "candidate_roles", "status", "faction", "faction_status", "confidence")


def signature(row):
    return tuple(tuple(sorted(row[k])) if isinstance(row[k], (list, tuple)) else row[k]
                 for k in CHANGE_FIELDS)


class MechanicsLab(ExtremeGame):
    def __init__(self, profiles, rules=None, role_rotation=0):
        if type(role_rotation) is not int or not 0 <= role_rotation < len(PLAYERS):
            raise ValueError("role_rotation must be an integer from 0 to 6")
        self.rules = rules if rules is not None else LabRules()
        if type(self.rules) is not LabRules:
            raise ValueError("LabRules required")
        self.role_rotation = role_rotation
        super().__init__(deepcopy(profiles))
        # Rebuild lawful notebooks before any request. Rotation is researcher-only;
        # actors never receive the rotation or the full assignment.
        self.roles = {p: ROLES[PLAYERS[(i - role_rotation) % len(PLAYERS)]]
                      for i, p in enumerate(PLAYERS)}
        self.notebooks = {p: PrivateNotebook(p, self.archive) for p in PLAYERS}
        self.known = {}
        for actor in PLAYERS:
            record = self.notebooks[actor].observe(f"你的身份是 {self.roles[actor]}。")
            self.known[actor] = {actor: (self.roles[actor], record.event_id)}
            if self.roles[actor] == "werewolf":
                for buddy in PLAYERS:
                    if buddy != actor and self.roles[buddy] == "werewolf":
                        record = self.notebooks[actor].observe(f"你的狼人队友是 {buddy}。")
                        self.known[actor][buddy] = ("werewolf", record.event_id)
        self.constraints = {p: possibilities(PLAYERS, facts) for p, facts in self.known.items()}
        self.tickets = dict.fromkeys(PLAYERS, 1)
        self.protocol_record = self.archive.append_event("setup", "研究协议 v2：狼队禁止自刀及杀狼队友，因此夜间刀死者必为好人阵营，"
            "但不翻具体角色。质疑明确区分 target_record（被质疑记录）与 evidence（支持或被争议的来源）。"
            "同批表在相同 as_of 截止点封存，发布先后不是信息先后；不能声称对方封存前看到了同批新表。"
            "公开修订与解释只是声称，主持人不判断真假、不自动增加怀疑。玩法开关：" +
            json.dumps(asdict(self.rules), ensure_ascii=False) +
            ("。每人全局一张追问券，轮到主持人分配的窗口可使用或保留；回应不消耗券；仍每天最多两次质疑。"
             if self.rules.challenge_tickets else "。质疑沿用每天两个主持人窗口，无全局券数限制。") +
            ("。修表时每条身份/阵营/候选/置信度变动须公开标记新证据、纠错或策略调整及原因；不强制透露私有证据。"
             if self.rules.revision_receipts else ""))

    def _profile_request(self, actor, request):
        result = super()._profile_request(actor, request)
        result["lab_rules"] = asdict(self.rules)
        result["table_timing"] = [{"record": r.event_id, "actor": r.actor,
            "version": r.table.version, "phase": r.phase, "sealed_as_of": r.table.as_of}
            for r in self.archive.history() if r.table is not None]
        if self.rules.challenge_tickets:
            result["tickets_remaining"] = self.tickets.copy()
        result["instruction"] += ("\n遵守公开研究协议 v2。table_timing 给出封存截止点，"
            "同批新表不能被同批其他表预先看见。公开刀死事实加禁止自刀规则可确定死者好人阵营，"
            "但不能确定村民或预言家。主持人仅核查格式和公开来源，不认证论证或身份真假。")
        return result

    def player_request(self, actor, task):
        request = super().player_request(actor, task)
        if task == "challenge":
            request["response_schema"] = {"kind": "table/action/statement/pass",
                "target": "other living actor, or null for pass",
                "target_record": "public record being questioned, or null for pass",
                "row_player": "A..G for table; null otherwise",
                "evidence": "public sources supporting your question OR sources you dispute; may be empty",
                "text": "public question or reason to pass"}
            request["instruction"] += ("\n质疑表格用 kind=table，target_record 指向目标公开表，row_player 指明行。"
                "质疑公开投票用 kind=action，target_record 指向主持人公开投票记录，row_player=null。"
                "质疑发言用 kind=statement 指向目标发言，row_player=null。evidence 无须重复 target_record。"
                "放弃用 kind=pass，三个定位字段为null、evidence=[]。若启用追问券且已耗尽，只能pass。")
        if task == "revision" and self.rules.revision_receipts:
            request["response_schema"]["changes"] = [{"player": "changed public row",
                "kind": "new_evidence/correction/strategy", "evidence": "public IDs, may be empty",
                "text": "public explanation, not a truth certificate"}]
            request["instruction"] += ("\nchanges 必须恰好覆盖相对你上一版公开表在 roles/candidate_roles/status/"
                "faction/faction_status/confidence 上变化的行，每行一次；没变为[]。"
                "new_evidence 必须引用至少一个公开来源。纠错或策略调整可无公开来源，不得引用私有编号。"
                "原因的真实性由其他玩家判断。")
        return request

    def night(self, complete):
        super().night(complete)
        # This deduction uses the public death, not ground truth. Preserve any
        # stronger private exact-role fact rather than replacing it with a faction.
        victim = self.nights[-1]["victim"]
        death = next(r for r in reversed(self.archive.history())
                     if r.text.startswith(f"夜间结束，{victim} 死亡"))
        for actor in PLAYERS:
            if victim not in self.known[actor]:
                self.known[actor][victim] = ("good", death.event_id)
            self.constraints[actor] = possibilities(PLAYERS, self.known[actor])
            for constraint in self.constraints[actor].values():
                if self.protocol_record.event_id not in constraint["evidence"]:
                    constraint["evidence"].append(self.protocol_record.event_id)

    def _references(self, values):
        if type(values) is not list or any(type(ref) is not str for ref in values) or len(set(values)) != len(values):
            raise ValueError("unique public reference list required")
        for ref in values:
            try:
                self.archive.lookup(ref)
            except KeyError as error:
                raise ValueError("reference is not visible public history") from error

    def challenge(self, actor, raw):
        if self.stage != "debate" or len(self.exchanges) >= len(self.challengers):
            raise ValueError("challenge window closed")
        if self.exchanges and not self.exchanges[-1].get("response"):
            raise ValueError("response pending")
        if actor != self.challengers[len(self.exchanges)] or actor not in self.active:
            raise ValueError("not this actor's host slot")
        data = decode(raw)
        fields(data, {"kind", "target", "target_record", "row_player", "evidence", "text"})
        prose(data["text"])
        self._references(data["evidence"])
        if data["kind"] == "pass":
            if any(data[k] is not None for k in ("target", "target_record", "row_player")) or data["evidence"]:
                raise ValueError("pass requires null targets and empty evidence")
        else:
            if data["target"] not in self.active or data["target"] == actor:
                raise ValueError("invalid living challenge target")
            if self.rules.challenge_tickets and self.tickets[actor] <= 0:
                raise ValueError("no challenge tickets remaining")
            self._references([data["target_record"]])
            record = self.archive.lookup(data["target_record"])
            if data["kind"] == "table":
                if record.table is None or record.actor != data["target"] or data["row_player"] not in PLAYERS:
                    raise ValueError("target table and row required")
            elif data["kind"] == "statement":
                if record.kind != "statement" or record.actor != data["target"] or data["row_player"] is not None:
                    raise ValueError("target statement required")
            elif data["kind"] == "action":
                if record.kind != "event" or not record.text.startswith("公开投票：") or data["row_player"] is not None:
                    raise ValueError("public ballot event required")
                ballots = json.loads(record.text.removeprefix("公开投票：").split("；", 1)[0])
                if data["target"] not in ballots:
                    raise ValueError("target has no ballot in this record")
            else:
                raise ValueError("unknown challenge kind")
        record = self.archive.append_statement(actor, self.phase_label, json.dumps(data, ensure_ascii=False))
        exchange = {"actor": actor, **data, "challenge_id": record.event_id}
        if data["kind"] == "pass":
            exchange["response"] = "pass"
        elif self.rules.challenge_tickets:
            self.tickets[actor] -= 1
        self.exchanges.append(exchange)
        return data["target"]

    def validate_submission(self, actor, raw):
        data = decode(raw)
        receipts = None
        if self.stage == "revision" and self.rules.revision_receipts:
            if "changes" not in data:
                raise ValueError("revision receipts required")
            data = data.copy()
            receipts = data.pop("changes")
            if type(receipts) is not list:
                raise ValueError("changes must be a list")
        draft = super().validate_submission(actor, json.dumps(data, ensure_ascii=False))
        if receipts is not None:
            previous = self.archive.table(actor, draft[2].version - 1)
            before = {r.player: asdict(r) for r in previous.guesses}
            changed = {r.player for r in draft[2].guesses if signature(before[r.player]) != signature(asdict(r))}
            seen = set()
            for receipt in receipts:
                fields(receipt, {"player", "kind", "evidence", "text"})
                if receipt["player"] not in changed or receipt["player"] in seen:
                    raise ValueError("receipts must cover each changed public row once")
                seen.add(receipt["player"])
                if receipt["kind"] not in ("new_evidence", "correction", "strategy"):
                    raise ValueError("unknown change category")
                prose(receipt["text"])
                self._references(receipt["evidence"])
                if receipt["kind"] == "new_evidence" and not receipt["evidence"]:
                    raise ValueError("new evidence category requires public sources")
            if seen != changed:
                raise ValueError("missing changed-row receipts")
        return draft

    def publish_tables(self, responses):
        revised = self.stage == "revision"
        super().publish_tables(responses)
        if revised and self.rules.revision_receipts:
            for actor in self.active:
                self.archive.append_statement(actor, self.phase_label, "改口说明（玩家声称，非认证）：" +
                    json.dumps(decode(responses[actor])["changes"], ensure_ascii=False))

    def research_export(self):
        return {**super().research_export(), "protocol": "mechanics-lab-v2",
                "rules": asdict(self.rules), "role_rotation": self.role_rotation,
                "tickets": self.tickets.copy()}


def lab_output_schema(request):
    schema = output_schema(request)
    if request["task"] == "challenge":
        props = schema["properties"]
        props["kind"] = {"type": "string", "enum": ["table", "action", "statement", "pass"]}
        props["target_record"] = {"type": ["string", "null"]}
        return obj(props)
    if request["task"] == "revision" and request["lab_rules"]["revision_receipts"]:
        schema["properties"]["changes"] = {"type": "array", "items": obj({
            "player": {"type": "string", "enum": list(PLAYERS)},
            "kind": {"type": "string", "enum": ["new_evidence", "correction", "strategy"]},
            "evidence": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string"}})}
        schema["required"].append("changes")
    return schema


def screening_plan():
    """Unapproved 12-game screening proposal, NOT a runnable provider manifest."""
    return {"protocol": "mechanics-lab-v2", "status": "draft_requires_approval",
        "provider_calls_allowed": 0, "purpose": "qualitative mechanic discovery, not win-rate inference",
        "conditions": [{"id": f"{arm}-r{rotation}-p{profile}", "arm": arm,
            "rules": asdict(rules), "role_rotation": rotation, "profile_condition": profile}
            for rotation in (0, 3) for profile in (2, 3) for arm, rules in ARMS.items()],
        "expansion": "If promising, rotate all seven role assignments, vary initiative and replicate; do not claim balance from screening."}


if __name__ == "__main__":
    print(json.dumps(screening_plan(), ensure_ascii=False, indent=2))
