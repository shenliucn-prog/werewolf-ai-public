"""Provider-independent NPC decisions and lawful per-seat model context."""
import json
import random
from copy import deepcopy
from dataclasses import asdict

from .. import perf
from ..recovery import check_version, require_str
from .brain import Speech
from .strategic_agent import StrategicNPCAgent
from .decision_runtime import ModelTurnError


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


class ModelNPCAgent(StrategicNPCAgent):
    def __init__(self, *args, planner, public_record, recorder=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = planner
        self.public_record = public_record
        self.recorder = recorder
        # Isolated per-seat, per-game decision memory; never emitted publicly.
        self.model_decisions = []

    def decide(self, task, properties, **details):
        from ..onboarding import introduction
        from . import model_context
        context = model_context.bound_information(asdict(self.information_set()))
        context["rules"] = introduction(self.engine, False)
        request = {
            "task": task, "language": self.engine.locale, "actor": self.seat.pos,
            "information": context, "persona": self.persona,
            "personality_parameters": asdict(self.style),
            "cognitive_parameters": self.brain.cognition.to_dict(),
            # §9 context budget: the model never receives the whole transcript.
            # The full archive stays whole in ``public_record`` / the event
            # ledger; this is the bounded slice (recent verbatim + attributed
            # summaries of older speech + settled public facts).
            "public_context": model_context.build_public_context(self),
            "own_previous_decisions": self.model_decisions[-model_context.DECISION_MEMORY:],
            "details": details,
            "instructions": (
                "Choose your own strategy, not a prescribed template. Public flips are facts; claims are not. "
                "Compare dated check claims against flips. Track your own votes and explain changes of stance. "
                "Distinguish support from accusation. Answer questions addressed to you. "
                "Never invent historical votes, checks, deaths or utterances. Wolves may deliberately lie "
                "about their role/checks but must account for contradictions in their earlier public story. "
                "Keep private information private unless strategically choosing to disclose it in public speech. "
                "Use natural, specific arguments; personality influences priorities, not grammatical corruption. "
                "Return only requested fields. Do not include private reasoning in public speech by default."
            ),
        }
        # §9 request-size budget: the final serialized request is bounded, not
        # just the history counts.
        request = model_context.fit_request_budget(request)
        request_chars = len(json.dumps(request, ensure_ascii=False))
        t0 = perf.now()
        value = self.planner.complete(request, object_schema(properties))
        if self.recorder is not None:
            # Privacy-safe: the request body and any private decision stay out;
            # only its serialized size and the observed call duration are kept.
            self.recorder.model_call(
                seat=self.seat.pos, task=task,
                backend=getattr(self.planner, "backend", None),
                request_chars=request_chars, dur_ms=perf.elapsed_ms(t0))
        if not isinstance(value, dict) or set(value) != set(properties):
            raise ModelTurnError("Invalid decision fields; no offline substitution.")
        for key, spec in properties.items():
            item = value[key]
            if "enum" in spec and item not in spec["enum"]:
                raise ModelTurnError("Illegal model decision; no offline substitution.")
            kind = spec.get("type")
            valid = ((kind == "boolean" and type(item) is bool) or
                     (kind == "string" and isinstance(item, str) and 0 < len(item.strip()) <= spec.get("maxLength", 2000)) or
                     (isinstance(kind, list) and (item is None or
                        ("integer" in kind and type(item) is int) or
                        ("string" in kind and isinstance(item, str)))))
            if not valid:
                raise ModelTurnError("Malformed model decision; no offline substitution.")
        self.model_decisions.append({"day": self.engine.day_count, "night": self.engine.night_count,
                                     "task": task, "decision": value})
        return value

    def speak(self, today, player_last_speech="", task="public speech", **details):
        names = [s.name for s in self.engine.alive_seats() if s.name != self.name]
        named = {"type": ["string", "null"], "enum": [None, *names]}
        from ..game.engine import ROLE_META
        value = self.decide(task, {
            "text": {"type": "string", "maxLength": 1600},
            "claim": {"type": ["string", "null"], "enum": [None, *ROLE_META]},
            "accuse": named, "defend": named, "question_to": named,
        }, earlier_this_round=[{"name": n, "text": s.text} for n, s in today], **details)
        if value["accuse"] and value["accuse"] == value["defend"]:
            raise ModelTurnError("Conflicting speech metadata; no offline substitution.")
        return Speech(**value)

    def table_interject(self, speaker, speech):
        return self.speak([], task="brief public interruption", speaker=speaker, statement=speech.text)

    def table_reply(self, interrupter):
        return self.speak([], task="brief answer to public question", asker=interrupter)

    def save_memory(self):
        # Local heuristic growth is not evidence about model decision quality.
        # Keep model decision memory within this match until evaluated growth
        # and privacy-safe persistence have a separate implementation.
        return None

    def snapshot(self) -> dict:
        """Per-agent snapshot adds the per-seat model decision memory."""
        data = super().snapshot()
        # Deep copy: a decision may hold nested dicts/lists, and the snapshot
        # must stay independent of any later mutation of the live decisions.
        data["model_decisions"] = deepcopy(self.model_decisions)
        return data

    def restore(self, data: dict) -> None:
        where = "ModelNPCAgent.snapshot"
        check_version(data, where)
        decisions = data.get("model_decisions")
        if not isinstance(decisions, list) or any(
                not isinstance(entry, dict) for entry in decisions):
            raise ValueError(f"{where}: model_decisions must be an array of objects")
        super().restore(data)
        self.model_decisions = deepcopy(decisions)

    @classmethod
    def restore_agent(cls, snapshot: dict, engine, llm, planner, public_record,
                      memory_dir: str | None = None, recorder=None) -> "ModelNPCAgent":
        """Side-effect-free rebuild for the model-driven agent (see base class)."""
        check_version(snapshot, "ModelNPCAgent.snapshot")
        name = require_str(snapshot, "name", "ModelNPCAgent.snapshot",
                           allow_empty=False)
        agent = cls(name, engine, llm, planner=planner,
                    public_record=public_record, memory_dir=memory_dir,
                    recorder=recorder, private_rng=random.Random(0), emit_start=False)
        agent.restore(snapshot)
        return agent

    def election_choice(self, withdraw=False):
        key = "withdraw" if withdraw else "up"
        return self.decide("withdraw from election" if withdraw else "join sheriff election",
                           {key: {"type": "boolean"}})[key]

    def vote(self, candidates, sheriff=False):
        positions = [c["pos"] for c in candidates if sheriff or c["pos"] != self.seat.pos]
        return self.decide("sheriff vote" if sheriff else "exile vote", {
            "target": {"type": ["integer", "null"], "enum": [None, *positions]},
        }, candidates=candidates)["target"]

    def night_action(self, kind, candidates, **kwargs):
        positions = [c["pos"] if isinstance(c, dict) else c for c in candidates]
        if kind == "witch":
            knife = kwargs.get("knife")
            save = [knife] if kwargs.get("antidote") and knife is not None and (
                knife != self.seat.pos or self.engine.night_count == 1) else []
            poison = positions if kwargs.get("poison") else []
            value = self.decide("witch potions", {
                "save": {"type": ["integer", "null"], "enum": [None, *save]},
                "poison": {"type": ["integer", "null"], "enum": [None, *poison]},
            }, dual_potions=self.engine.witch_dual, **kwargs)
            if value["save"] is not None and value["poison"] is not None and not self.engine.witch_dual:
                raise ModelTurnError("Illegal dual potion; no offline substitution.")
            return value
        return self.decide(kind, {"target": {"type": ["integer", "null"], "enum": [None, *positions]}},
                           candidates=positions, **kwargs)
