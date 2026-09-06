"""Web adapter around the shared strategic Brain.

CLI and web games use the same belief, strategy, and decision machinery. The
LLM is a language realizer: it may change wording, but not the chosen claim,
accusation, defence, vote, or night action.
"""
from __future__ import annotations

import json
import os
import random
import re

from .. import config
from . import prompts
from .brain import Brain, Speech
from .llm import LLMClient
from .npc import load_seat_persona
from .strategy import InformationSet

MEMORY_DIR = os.path.join(config.DATA_DIR, "npc_memory")
os.makedirs(MEMORY_DIR, exist_ok=True)


class StrategicNPCAgent:
    """Presentation and persistence adapter for the shared Brain."""

    def __init__(self, name: str, engine, llm: LLMClient,
                 memory_dir: str | None = None):
        self.name = name
        self.engine = engine
        self.llm = llm
        self.memory_dir = memory_dir or MEMORY_DIR
        os.makedirs(self.memory_dir, exist_ok=True)
        self.seat = engine.seat_by_name(name)
        self.persona = self._load_persona(name)
        self.role_cn = self.seat.role_cn
        self.is_wolf = self.seat.is_wolf
        self.memory = self._load_memory()
        private_rng = random.Random(engine.rng.randrange(1, 2 ** 31))
        self.brain = Brain(
            self.seat, engine, self.persona, private_rng,
            cognitive_state=self.memory.get("cognition"),
            match_carry=self.memory.get("match_carry"),
        )
        self.reasoning: list[str] = []

    @property
    def style(self):
        return self.brain.style

    @property
    def decision_traces(self):
        return self.brain.decision_traces

    def assign_wolf_strategy(self, rank: int, total: int):
        self.brain.assign_wolf_strategy(rank, total)

    def _load_persona(self, name: str) -> dict:
        return load_seat_persona(self.seat, self.engine)

    def _load_memory(self) -> dict:
        path = os.path.join(self.memory_dir, f"{self.seat.player_id}-{self.seat.persona_id or self.seat.player_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except (OSError, ValueError):
                pass
        return {"games": 0, "wins": 0, "learnings": []}

    def save_memory(self):
        self.memory["games"] = self.memory.get("games", 0) + 1
        won = ((self.is_wolf and self.engine.winner == "wolf") or
               (not self.is_wolf and self.engine.winner == "god"))
        if won:
            self.memory["wins"] = self.memory.get("wins", 0) + 1
        lesson = self.brain.grow(won)
        learnings = self.memory.setdefault("learnings", [])
        learnings.append(lesson)
        self.memory["learnings"] = learnings[-20:]
        self.memory["cognition"] = self.brain.cognition.to_dict()
        # Persist only the deliberately bounded inter-match carry.  The live
        # emotion/form event list stays in this match's coach ledger.
        self.memory["match_carry"] = self.brain.match_state.carry_forward(won)
        self.brain._state_event("match_complete")
        path = os.path.join(self.memory_dir, f"{self.seat.player_id}-{self.seat.persona_id or self.seat.player_id}.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(self.memory, file, ensure_ascii=False, indent=2)

    def information_set(self) -> InformationSet:
        return InformationSet.from_brain(self.brain)

    def observe_speech(self, day: int, who: str, speech: Speech):
        self.brain.observe_speech(day, who, speech, speech.text)

    def observe_vote(self, day: int, who: str, target_name: str | None):
        self.brain.observe_vote(day, who, target_name)

    def observe_flip(self, name: str, role_name: str, is_wolf: bool):
        self.brain.observe_flip(name, role_name, is_wolf)

    def observe_exile(self, day: int, name: str, is_wolf: bool):
        self.brain.observe_exile(day, name, is_wolf)

    def speak(self, today: list[tuple[str, Speech]],
              player_last_speech: str = "") -> Speech:
        strategic_speech = self.brain.speak(self.engine.day_count, today)
        if self.llm.online:
            context = self.information_set().to_prompt(self.engine.locale)
            if getattr(self, "conjecture_history", None):
                context += "\nPublic conjecture history (claims, not truth):\n" + json.dumps(
                    self.conjecture_history, ensure_ascii=False)
            context += ("\nEarlier statements this round:\n" if self.engine.locale == "en" else "\n本轮此前发言：\n") + "\n".join(
                f"{name}：{speech.text}" for name, speech in today)
            intent = (
                f"不可改变的战略意图：claim={strategic_speech.claim}, "
                f"accuse={strategic_speech.accuse}, defend={strategic_speech.defend}。"
                f"基础表达：{strategic_speech.text}"
            )
            if self.engine.locale == "en":
                intent = (f"Locked intent: claim={strategic_speech.claim}, "
                          f"accuse={strategic_speech.accuse}, defend={strategic_speech.defend}. "
                          f"Base statement: {strategic_speech.text}")
            # Failure, timeout, quota exhaustion, and malformed empty output
            # all retain the strategy engine's original legal expression.
            realized = self.llm.generate(
                prompts.system_npc(self.engine.locale),
                prompts.build_speech_prompt(
                    self.persona, self.role_cn, self.is_wolf,
                    context + "\n" + intent, player_last_speech,
                    locale=self.engine.locale,
                ),
                max_tokens=300,
            )
            if (realized and self._matches_intent(realized, strategic_speech)
                    and (self.engine.locale != "en" or not re.search(r"[\u4e00-\u9fff]", realized))):
                strategic_speech.text = realized
        self.reasoning.append(
            f"[D{self.engine.day_count}] {self.name}: {strategic_speech.text[:80]}")
        return strategic_speech

    def table_interruption_interest(self, speaker: str, speech: Speech) -> float:
        return self.brain.interruption_interest(speaker, speech)

    def table_interject(self, speaker: str, speech: Speech) -> Speech:
        reply = self.brain.table_interjection(speaker, speech)
        self.reasoning.append(
            f"[D{self.engine.day_count} interrupt] {self.name}: {reply.text[:80]}")
        return reply

    def table_reply(self, interrupter: str) -> Speech:
        reply = self.brain.table_reply(interrupter)
        self.reasoning.append(
            f"[D{self.engine.day_count} reply] {self.name}: {reply.text[:80]}")
        return reply

    @staticmethod
    def _matches_intent(text: str, speech: Speech) -> bool:
        """Reject obvious contradictions from a free-form language model.

        This is a conservative guard, not a second strategic planner: locked
        claims and named accusation/defence targets must not be negated.
        """
        compact = text.replace(" ", "")
        lower = text.lower().replace("’", "'")
        if speech.claim == "seer" and re.search(r"i(?: am|'m) not (?:the |a )?seer", lower):
            return False
        if speech.claim is None and re.search(r"i(?: am|'m) (?:the |a )?seer\b", lower):
            return False
        if speech.claim == "seer" and any(x in compact for x in ("我不是预言家", "假预言家")):
            return False
        if speech.claim is None and "我是预言家" in compact:
            return False
        return len(text.strip()) <= 900

    def vote(self, candidates: list[dict], sheriff: bool = False) -> int | None:
        target, reason = self.brain.vote(
            [candidate["pos"] for candidate in candidates], sheriff=sheriff)
        self.reasoning.append(f"[D{self.engine.day_count} vote] {reason}")
        return target

    def night_action(self, kind: str, candidates: list, **kwargs) -> dict:
        positions = [candidate["pos"] if isinstance(candidate, dict) else candidate
                     for candidate in candidates]
        decision = self.brain.night(kind, positions, **kwargs)
        self.reasoning.append(
            f"[N{self.engine.night_count} {kind}] {decision.reason}")
        if kind == "witch":
            return {"save": decision.save, "poison": decision.poison}
        return {"target": decision.target}
