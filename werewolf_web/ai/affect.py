"""Bounded match form and in-game emotion for NPC decision variance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from ..recovery import SCHEMA_VERSION, check_version, require_number, require_list


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass
class MatchState:
    """Temporary performance state; it never overwrites long-term ability."""

    form: float = 0.0
    valence: float = 0.0
    arousal: float = 0.45
    confidence: float = 0.5
    stress: float = 0.25
    momentum: float = 0.0
    events: list[str] = field(default_factory=list)

    @classmethod
    def start(cls, rng: Any, saved: dict | None = None) -> "MatchState":
        saved = saved or {}
        carry = _clamp(float(saved.get("carry", 0.0)))
        # Ordinary form is common; extreme hot and cold streaks are rare.
        form = _clamp(carry * 0.42 + rng.gauss(0.0, 0.28), -0.85, 0.85)
        valence = _clamp(form * 0.55 + rng.gauss(0.0, 0.14))
        arousal = _clamp(0.44 + abs(form) * 0.16 + rng.gauss(0.0, 0.08), 0.18, 0.78)
        confidence = _clamp(0.52 + form * 0.20 + rng.gauss(0.0, 0.06), 0.30, 0.75)
        stress = _clamp(0.27 - form * 0.10 + rng.gauss(0.0, 0.05), 0.12, 0.52)
        return cls(form=form, valence=valence, arousal=arousal,
                   confidence=confidence, stress=stress)

    @property
    def condition(self) -> float:
        return _clamp(self.form * 0.72 + self.momentum * 0.28)

    @property
    def condition_label(self) -> str:
        value = self.condition
        if value >= 0.58:
            return "火热"
        if value >= 0.20:
            return "良好"
        if value <= -0.58:
            return "低迷"
        if value <= -0.20:
            return "欠佳"
        return "正常"

    @property
    def mood(self) -> str:
        if self.stress >= 0.68:
            return "紧张"
        if self.arousal >= 0.66 and self.valence >= 0.10:
            return "兴奋"
        if self.arousal >= 0.62 and self.valence <= -0.15:
            return "恼火"
        if self.confidence >= 0.66:
            return "自信"
        if self.valence <= -0.35:
            return "沮丧"
        return "平静"

    def effective(self, baseline: float, dimension: str) -> float:
        """Apply a small state delta while preserving a professional floor."""
        weights = {
            "evidence_processing": (0.070, 0.045, -0.075),
            "recursive_reasoning": (0.060, 0.035, -0.090),
            "social_reading": (0.045, 0.040, -0.045),
            "deception": (0.040, 0.070, -0.065),
            "calibration": (0.055, 0.030, -0.070),
            "decisiveness": (0.050, 0.085, -0.055),
        }
        form_w, confidence_w, stress_w = weights.get(
            dimension, (0.05, 0.04, -0.06))
        delta = (self.condition * form_w
                 + (self.confidence - 0.5) * confidence_w
                 + self.stress * stress_w)
        floor = max(0.05, baseline * 0.82)
        ceiling = min(0.98, baseline + 0.12)
        return max(floor, min(ceiling, baseline + delta))

    def decision_noise(self, evidence_ability: float) -> float:
        """Poor form adds uncertainty, never chaos."""
        penalty = max(0.0, -self.condition) * 0.035 + self.stress * 0.025
        protection = evidence_ability * 0.035
        return max(0.008, min(0.075, 0.045 + penalty - protection))

    def depth_adjustment(self) -> int:
        if self.condition >= 0.38 and self.stress < 0.48:
            return 1
        if self.condition <= -0.42 or self.stress >= 0.68:
            return -1
        return 0

    def overthinking_multiplier(self) -> float:
        return max(0.65, min(1.55,
                            0.85 + self.stress * 0.75 - self.confidence * 0.25))

    def react(self, event: str) -> None:
        """Update emotion in small steps from personally experienced events."""
        changes = {
            "accused": (-0.025, 0.045, -0.015, 0.055, -0.02),
            "defended": (0.020, 0.018, 0.025, -0.015, 0.02),
            "correct_read": (0.045, 0.025, 0.055, -0.025, 0.08),
            "wrong_read": (-0.045, 0.020, -0.045, 0.045, -0.07),
            "survived_vote": (0.025, 0.035, 0.025, -0.010, 0.04),
            "ally_lost": (-0.040, 0.035, -0.025, 0.045, -0.04),
        }
        if event not in changes:
            return
        valence, arousal, confidence, stress, momentum = changes[event]
        self.valence = _clamp(self.valence + valence)
        self.arousal = _clamp(self.arousal + arousal, 0.10, 0.90)
        self.confidence = _clamp(self.confidence + confidence, 0.18, 0.88)
        self.stress = _clamp(self.stress + stress, 0.08, 0.82)
        self.momentum = _clamp(self.momentum + momentum, -0.75, 0.75)
        self.events.append(event)
        self.events = self.events[-16:]

    def expression_prefix(self) -> str:
        return {
            "兴奋": "我现在思路比较快，",
            "自信": "我这一轮比较确定，",
            "紧张": "我先稳一下，",
            "恼火": "我直说了，",
            "沮丧": "我可能状态一般，但还是说一下，",
        }.get(self.mood, "")

    def carry_forward(self, won: bool) -> dict:
        result_bump = 0.10 if won else -0.08
        carry = _clamp(self.condition * 0.55 + result_bump, -0.65, 0.65)
        return {"carry": round(carry, 4)}

    def snapshot(self) -> dict:
        data = asdict(self)
        data.update({"condition": round(self.condition, 4),
                     "condition_label": self.condition_label,
                     "mood": self.mood,
                     "schema_version": SCHEMA_VERSION})
        return deepcopy(data)

    @classmethod
    def restore(cls, data: dict) -> "MatchState":
        """Rebuild from a whitelisted snapshot; computed fields are re-derived.

        Strictly validates the dataclass fields and returns an object that
        shares no nested references with ``data``.
        """
        where = "MatchState.snapshot"
        check_version(data, where)
        kwargs = {}
        for key in ("form", "valence", "arousal", "confidence", "stress", "momentum"):
            kwargs[key] = require_number(data, key, where, -2.0, 2.0)
        events = require_list(data, "events", where)
        if any(not isinstance(item, str) for item in events):
            raise ValueError(f"{where}: events must be an array of strings")
        kwargs["events"] = deepcopy(events)
        return cls(**kwargs)
