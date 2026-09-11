"""Provider-independent NPC decisions and lawful per-seat model context."""
import random
from copy import deepcopy

from ..driver import driver_from_planner
from ..participants import Participant
from ..observations import ObservationGateway
from ..recovery import check_version, require_str
from .brain import Speech
from .strategic_agent import StrategicNPCAgent
from .decision_runtime import ModelTurnError
from .model_controller import ModelController, object_schema  # compatibility export


class ModelNPCAgent(StrategicNPCAgent):
    def __init__(self, *args, planner, public_record, recorder=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.planner = planner
        self.public_record = public_record
        self.recorder = recorder
        driver, adapter = driver_from_planner(planner)
        self.participant = Participant.from_seat("local", self.seat, driver, adapter)
        # Isolated per-seat, per-game decision memory; never emitted publicly.
        self.model_decisions = []

    def decide(self, task, properties, **details):
        observation = ObservationGateway.for_model(self, task, details)
        value = ModelController(self.planner, self.recorder).decide(observation, properties)
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
            "accuse": named, "defend": named,
            "question_to": {"type": "null"} if task == "brief answer to public question" else named,
        }, earlier_this_round=[{"name": n, "text": s.text} for n, s in today], **details)
        if value["accuse"] and value["accuse"] == value["defend"]:
            raise ModelTurnError("Conflicting speech metadata; no offline substitution.")
        return Speech(**value)

    def table_interject(self, speaker, speech):
        return self.speak([], task="brief public interruption", speaker=speaker, statement=speech.text)

    def table_reply(self, interrupter):
        return self.speak([], task="brief answer to public question", asker=interrupter,
                          reply_contract="Answer the asker's question using your lawful evidence, "
                          "or explicitly decline/admit uncertainty. Do not replace the answer "
                          "with a new question. Address public flips and distinguish claims from facts.")

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
        return self.decide("decide whether to withdraw from election" if withdraw else
                           "decide whether to join sheriff election",
                           {key: {"type": "boolean"}},
                           choice_meaning=({"true": "withdraw: stop competing for sheriff",
                                            "false": "stay: continue competing for sheriff"} if withdraw else
                                           {"true": "join: compete for sheriff",
                                            "false": "decline: do not compete for sheriff"}),
                           considerations="Choose strategically; neither answer is prescribed. "
                           "Consider your role, your public claims and earlier request for the badge. "
                           "Withdrawing is not voting for another candidate. If you change your "
                           "publicly stated intention, account for it in your next speech.")[key]

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
