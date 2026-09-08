"""Cognitive ability and bounded learning for independent player brains."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..recovery import SCHEMA_VERSION, check_version, require_number, require_int


def _clamp(value: float, low: float = 0.05, high: float = 0.95) -> float:
    return max(low, min(high, value))


@dataclass
class CognitiveProfile:
    """How well a player thinks, separate from how the player behaves."""

    evidence_processing: float = 0.5
    recursive_reasoning: float = 0.5
    social_reading: float = 0.5
    deception: float = 0.4
    calibration: float = 0.5
    decisiveness: float = 0.5
    learning_rate: float = 0.5
    preferred_depth: int = 2
    max_depth: int = 3
    experience: int = 0

    @classmethod
    def from_persona(cls, persona: dict, style: Any,
                     saved: dict | None = None) -> "CognitiveProfile":
        if saved:
            allowed = cls.__dataclass_fields__
            return cls(**{key: value for key, value in saved.items() if key in allowed})

        explicit = persona.get("cognition") or {}
        logic = style.logic
        profile = cls(
            evidence_processing=_clamp(explicit.get("evidence_processing", logic)),
            recursive_reasoning=_clamp(explicit.get("recursive_reasoning", logic * 0.9)),
            social_reading=_clamp(explicit.get(
                "social_reading", 0.35 + style.aggression * 0.25 + logic * 0.25)),
            deception=_clamp(explicit.get("deception", style.bluff)),
            calibration=_clamp(explicit.get("calibration", 0.35 + logic * 0.45)),
            decisiveness=_clamp(explicit.get(
                "decisiveness", 0.35 + style.aggression * 0.35)),
            learning_rate=_clamp(explicit.get("learning_rate", 0.35 + logic * 0.4)),
        )
        profile.max_depth = max(1, min(5, round(1 + profile.recursive_reasoning * 4)))
        profile.preferred_depth = max(1, min(
            profile.max_depth, round(1 + profile.calibration * 2.5)))
        return profile

    def choose_depth(self, candidate_count: int, confidence_gap: float,
                     rng: Any, depth_adjustment: int = 0,
                     recursive_reasoning: float | None = None,
                     calibration: float | None = None,
                     overthinking_multiplier: float = 1.0) -> tuple[int, bool]:
        """Choose a useful depth; greater ability also creates overthinking risk."""
        recursive = (self.recursive_reasoning if recursive_reasoning is None
                     else recursive_reasoning)
        calibrated = self.calibration if calibration is None else calibration
        depth = self.preferred_depth + depth_adjustment
        if candidate_count >= 7 and recursive > 0.65:
            depth += 1
        if confidence_gap < 0.10 and recursive > 0.55:
            depth += 1
        depth = max(1, min(self.max_depth, depth))

        excess = max(0, depth - self.preferred_depth)
        risk = (excess * recursive * (1.0 - calibrated) * 0.45
                * overthinking_multiplier)
        overthought = excess > 0 and rng.random() < risk
        return depth, overthought

    def learn(self, traces: list[Any], won: bool) -> str:
        """Make small, bounded changes from decisions rather than raw outcomes."""
        self.experience += 1
        if not traces:
            return "本局没有足够的决策轨迹，暂不调整认知参数。"

        rate = self.learning_rate
        overthought = sum(1 for trace in traces if trace.overthought)
        if won:
            self.calibration = _clamp(self.calibration + 0.012 * rate)
            self.evidence_processing = _clamp(
                self.evidence_processing + 0.006 * rate)
            lesson = "保留本局有效判断，并小幅提高置信度校准。"
        elif overthought:
            self.calibration = _clamp(self.calibration + 0.018 * rate)
            if self.preferred_depth > 1:
                self.preferred_depth -= 1
            lesson = "本局存在过度推演，下局优先收敛证据再增加层级。"
        else:
            self.evidence_processing = _clamp(
                self.evidence_processing + 0.012 * rate)
            self.recursive_reasoning = _clamp(
                self.recursive_reasoning + 0.006 * rate)
            self.max_depth = max(
                self.max_depth,
                min(5, round(1 + self.recursive_reasoning * 4)),
            )
            lesson = "本局失利但并非过度推演，提升证据吸收与对手建模。"
        return lesson

    def to_dict(self) -> dict:
        return asdict(self)

    def snapshot(self) -> dict:
        """Versioned recovery snapshot; ``to_dict`` stays a plain field map."""
        return {"schema_version": SCHEMA_VERSION, **self.to_dict()}

    @classmethod
    def restore(cls, data: dict) -> "CognitiveProfile":
        where = "CognitiveProfile.snapshot"
        check_version(data, where)
        kwargs = {}
        for key in ("evidence_processing", "recursive_reasoning", "social_reading",
                    "deception", "calibration", "decisiveness", "learning_rate"):
            kwargs[key] = require_number(data, key, where, 0.0, 1.0)
        kwargs["preferred_depth"] = require_int(data, "preferred_depth", where, 1, 5)
        kwargs["max_depth"] = require_int(data, "max_depth", where, 1, 5)
        kwargs["experience"] = require_int(data, "experience", where, minimum=0)
        return cls(**kwargs)
