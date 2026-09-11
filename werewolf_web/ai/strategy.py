"""Shared strategic primitives for every NPC runtime.

The first version keeps the existing suspicion model, but turns its inputs and
outputs into explicit information sets, beliefs, alternatives, and traces. This
creates the seam where deeper Bayesian and level-k reasoning can be added
without coupling strategy to either the CLI or web presentation layer.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional
from ..i18n import witch_rule_text


@dataclass
class InformationSet:
    actor: str
    day: int
    night: int
    phase: str
    alive: list[dict]
    claims: dict[str, str]
    public_flips: list[dict]
    public_votes: list[dict]
    private: dict
    public_rules: dict = field(default_factory=dict)

    @classmethod
    def from_brain(cls, brain: Any) -> "InformationSet":
        engine = brain.engine
        private = {"self_role": brain.role}
        mates = brain.mates()
        if mates:
            private["wolf_mates"] = [
                {"pos": seat.pos, "name": seat.name}
                for seat in engine.seats.values()
                if seat.name in mates
            ]
        if brain.role == "seer":
            private["seer_results"] = list(engine.seer_results)
        if brain.role == "stone_ghost":
            private["stone_ghost_results"] = list(engine.sg_results)
            private["can_kill"] = engine.stone_ghost_can_kill()
        if brain.role == "gravekeeper":
            private["grave_results"] = list(engine.grave_results)

        return cls(
            actor=brain.name,
            day=engine.day_count,
            night=engine.night_count,
            phase=engine.phase,
            alive=[{"pos": seat.pos, "name": seat.name}
                   for seat in engine.alive_seats()],
            claims=dict(brain.claims),
            public_flips=[
                {"name": name, "role": role, "is_wolf": is_wolf}
                for name, role, is_wolf in brain.flips
            ],
            public_votes=[
                {"day": day, "voter": voter, "target": target, "kind": kind}
                for day, voter, target, kind in brain.vote_log
            ],
            private=private,
            public_rules=({"board_id": engine.board_id, "witch": witch_rule_text(engine.locale, engine.board)}
                if engine.witch_unlimited else {}),
        )

    def to_prompt(self, locale: str = "zh-CN") -> str:
        if locale == "en":
            import json
            from dataclasses import asdict
            return "Your lawful observations and private information:\n" + json.dumps(asdict(self), ensure_ascii=False)
        alive = "、".join(f"{p['pos']}号{p['name']}" for p in self.alive)
        lines = [
            f"第{self.day}天 / 第{self.night}夜，阶段：{self.phase}",
            f"存活玩家：{alive}",
        ]
        if self.claims:
            lines.append("公开身份声明：" + "、".join(
                f"{name}→{role}" for name, role in self.claims.items()))
        if self.public_rules:
            lines.append(f"公开变体规则：{self.public_rules}")
        if self.public_flips:
            lines.append("已翻牌：" + "、".join(
                f"{item['name']}={item['role']}" for item in self.public_flips))
        if self.public_votes:
            lines.append("历史投票：" + "、".join(
                f"D{item['day']} {item['voter']}→{item['target']}"
                for item in self.public_votes[-12:]))
        lines.append(f"你的私有信息：{self.private}")
        return "\n".join(lines)


@dataclass
class BeliefState:
    faction_probabilities: dict[str, dict[str, float]]

    @classmethod
    def from_brain(cls, brain: Any, candidates: list[int]) -> "BeliefState":
        from .joint_belief import for_brain
        joint = for_brain(brain)["wolf_weights"]
        engine = brain.engine
        beliefs: dict[str, dict[str, float]] = {}
        mates = set(brain.mates())
        for pos in candidates:
            seat = engine.seat_at(pos)
            if seat.name == brain.name:
                wolf_probability = 1.0 if brain.is_wolf else 0.0
            elif brain.is_wolf and seat.name in mates:
                wolf_probability = 1.0
            elif brain.is_wolf and "stone_ghost" not in engine.board["roles"]:
                # On ordinary boards the complete wolf pack knows one another.
                wolf_probability = 0.0
            else:
                wolf_probability = joint[seat.name]
            beliefs[seat.name] = {
                "wolf": wolf_probability,
                "good": 1.0 - wolf_probability,
            }
        return cls(faction_probabilities=beliefs)


@dataclass
class DecisionAlternative:
    target: Optional[int]
    utility: float
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"target": self.target, "utility": self.utility,
                "components": deepcopy(self.components)}

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionAlternative":
        return cls(data["target"], data["utility"],
                   deepcopy(data.get("components") or {}))


@dataclass
class DecisionTrace:
    actor: str
    phase: str
    day: int
    night: int
    action: str
    target: Optional[int]
    reasoning_depth: int
    rationale: str
    beliefs: dict[str, dict[str, float]]
    alternatives: list[DecisionAlternative]
    confidence: float = 0.0
    overthought: bool = False
    state_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "actor": self.actor,
            "phase": self.phase,
            "day": self.day,
            "night": self.night,
            "action": self.action,
            "target": self.target,
            "reasoning_depth": self.reasoning_depth,
            "rationale": self.rationale,
            "beliefs": deepcopy(self.beliefs),
            "alternatives": [alt.to_dict() for alt in self.alternatives],
            "confidence": self.confidence,
            "overthought": self.overthought,
            "state_snapshot": deepcopy(self.state_snapshot),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionTrace":
        return cls(
            actor=data["actor"],
            phase=data["phase"],
            day=data["day"],
            night=data["night"],
            action=data["action"],
            target=data["target"],
            reasoning_depth=data["reasoning_depth"],
            rationale=data["rationale"],
            beliefs=deepcopy(data.get("beliefs") or {}),
            alternatives=[DecisionAlternative.from_dict(alt)
                          for alt in data.get("alternatives", [])],
            confidence=data.get("confidence", 0.0),
            overthought=data.get("overthought", False),
            state_snapshot=deepcopy(data.get("state_snapshot") or {}),
        )


@dataclass
class VotePlan:
    target: Optional[int]
    rationale: str
    trace: DecisionTrace


class StrategicVotePlanner:
    """A traceable first-step vote planner shared by CLI and web agents."""

    def __init__(self, brain: Any):
        self.brain = brain

    def plan(self, candidates: list[int], sheriff: bool = False) -> VotePlan:
        brain = self.brain
        engine = brain.engine
        pool = [pos for pos in candidates if sheriff or pos != brain.me.pos]
        if not pool:
            trace = DecisionTrace(
                actor=brain.name, phase=engine.phase, day=engine.day_count,
                night=engine.night_count, action="vote", target=None,
                reasoning_depth=1, rationale="没有合法投票目标。", beliefs={},
                alternatives=[], confidence=1.0,
                state_snapshot=brain.match_state.snapshot(),
            )
            return VotePlan(None, trace.rationale, trace)

        mates = set(brain.mates())
        if brain.is_wolf and not sheriff:
            pool = [pos for pos in pool if engine.seat_at(pos).name not in mates] or pool

        belief_state = BeliefState.from_brain(brain, pool)
        from .public_story import for_brain as public_story
        story = {r["target"]: r for r in public_story(brain)["targets"]} if brain.is_wolf and not sheriff else {}
        alternatives: list[DecisionAlternative] = []
        for pos in pool:
            seat = engine.seat_at(pos)
            public_plausibility = max(0.0, min(1.0, brain.suspicion(seat.name)))
            components = {"public_plausibility": public_plausibility}
            if sheriff:
                wolf_weight = belief_state.faction_probabilities[seat.name]["wolf"]
                if brain.is_wolf:
                    utility = 1.2 if seat.name in mates or seat.name == brain.name else .5 * (1 - public_plausibility)
                else:
                    utility = 1 - wolf_weight
                components['sheriff_support'] = utility
            elif brain.is_wolf:
                role_threat = 0.30 if brain.claims.get(seat.name) == "seer" else 0.0
                pressure_threat = 0.35 if any(
                    who == seat.name and target in mates
                    for _day, who, target in brain.accuse_log
                ) else 0.0
                sheriff_threat = 0.15 if engine.sheriff == pos else 0.0
                utility = public_plausibility + role_threat + pressure_threat + sheriff_threat
                story_pressure = story.get(pos, {}).get("pressure_score", 0.0)
                utility += .3 * story_pressure
                components.update({
                    "public_story_pressure": story_pressure,
                    "role_threat": role_threat,
                    "pressure_threat": pressure_threat,
                    "sheriff_threat": sheriff_threat,
                })
            else:
                utility = belief_state.faction_probabilities[seat.name]["wolf"]
                components["wolf_probability"] = utility

            noise = brain.match_state.decision_noise(
                brain.effective_ability("evidence_processing"))
            utility = min(1.5, utility + brain.rng.uniform(-noise, noise))
            alternatives.append(DecisionAlternative(pos, utility, components))

        alternatives.sort(key=lambda item: item.utility, reverse=True)
        confidence = (alternatives[0].utility - alternatives[1].utility
                      if len(alternatives) > 1 else 1.0)
        depth, overthought = brain.cognition.choose_depth(
            len(pool), confidence, brain.rng,
            depth_adjustment=brain.match_state.depth_adjustment(),
            recursive_reasoning=brain.effective_ability("recursive_reasoning"),
            calibration=brain.effective_ability("calibration"),
            overthinking_multiplier=brain.match_state.overthinking_multiplier(),
        )
        selected = alternatives[1] if overthought and len(alternatives) > 1 \
            else alternatives[0]
        target = selected.target
        target_seat = engine.seat_at(target)
        if sheriff:
            rationale = (f"警长票是授予警徽，不是放逐；当前选择{target}号{target_seat.name}，"
                         "依据阵营判断与警徽归属利益。")
        elif brain.is_wolf:
            rationale = (f"推演{depth}层后，{target}号{target_seat.name}既容易形成公开票型，"
                         "又对狼队构成最高综合威胁。")
        else:
            wolf_p = belief_state.faction_probabilities[target_seat.name]["wolf"]
            rationale = (f"推演{depth}层后，当前判断{target}号{target_seat.name}为狼的概率最高"
                         f"（{wolf_p:.2f}）。")
        if overthought:
            rationale += "我主动挑战了第一判断，但这也可能是想多了。"

        trace = DecisionTrace(
            actor=brain.name,
            phase=engine.phase,
            day=engine.day_count,
            night=engine.night_count,
            action="vote",
            target=target,
            reasoning_depth=depth,
            rationale=rationale,
            beliefs=belief_state.faction_probabilities,
            alternatives=alternatives,
            confidence=confidence,
            overthought=overthought,
            state_snapshot=brain.match_state.snapshot(),
        )
        return VotePlan(target, rationale, trace)
