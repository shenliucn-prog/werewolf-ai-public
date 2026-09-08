"""Provider-independent NPC decisions and lawful per-seat model context."""
from dataclasses import asdict
from .brain import Speech
from .strategic_agent import StrategicNPCAgent
from .decision_runtime import ModelTurnError


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


class ModelNPCAgent(StrategicNPCAgent):
    def __init__(self, *args, planner, public_record, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = planner
        self.public_record = public_record
        # Isolated per-seat, per-game decision memory; never emitted publicly.
        self.model_decisions = []

    def decide(self, task, properties, **details):
        from ..onboarding import introduction
        context = asdict(self.information_set())
        context["rules"] = introduction(self.engine, False)
        request = {
            "task": task, "language": self.engine.locale, "actor": self.seat.pos,
            "information": context, "persona": self.persona,
            "personality_parameters": asdict(self.style),
            "cognitive_parameters": self.brain.cognition.to_dict(),
            "public_history": self.public_record.entries,
            "own_previous_decisions": self.model_decisions,
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
        value = self.planner.complete(request, object_schema(properties))
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
