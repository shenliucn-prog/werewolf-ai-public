"""Trusted observation assembly; controllers receive detached data, not worlds.

The legacy agent is still a trusted adapter. Role visibility comes from the
existing InformationSet policy; this is an extraction, not a sandbox or a
claim that local executable agents cannot read files on their host.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass

from .participants import Participant


MODEL_INSTRUCTIONS = (
    "Choose your own strategy, not a prescribed template. Public flips are facts; claims are not. "
    "Compare dated check claims against flips. Track your own votes and explain changes of stance. "
    "Distinguish support from accusation. Answer questions addressed to you. "
    "Never invent historical votes, checks, deaths or utterances. Wolves may deliberately lie "
    "about their role/checks but must account for contradictions in their earlier public story. "
    "Keep private information private unless strategically choosing to disclose it in public speech. "
    "Use natural, specific arguments; personality influences priorities, not grammatical corruption. "
    "Return only requested fields. Do not include private reasoning in public speech by default."
    " Night N precedes day N and its election/speeches: later speech cannot be the reason "
    "for an earlier night's action. Separate the original choice from retrospective assessment. "
    "A first-night choice before anyone spoke may simply be exploratory; do not invent prior speech. "
    "Read statements_of_flipped_seers before accusing their claimed check targets; distinguish "
    "a publicly revealed seer role from that player's still-attributed check statements. "
    "Add new evidence or a changed conclusion instead of repeating earlier arguments. "
    "Answer a player's specific question (including why you withdrew), not a generic demand for logic."
)


@dataclass(frozen=True)
class Observation:
    participant: Participant
    public_event_cutoff: int
    payload: dict

    def __post_init__(self):
        # Nested input is detached too; provider mutation cannot alter memory.
        object.__setattr__(self, "payload", deepcopy(self.payload))

    def to_request(self):
        return deepcopy(self.payload)


class ObservationGateway:
    @staticmethod
    def for_model(agent, task, details):
        from .onboarding import introduction
        from .ai import model_context

        if (agent.participant.participant_id != agent.seat.player_id
                or agent.participant.seat != agent.seat.pos):
            raise ValueError("Observation participant does not match the acting seat")
        context = model_context.bound_information(asdict(agent.information_set()))
        context["rules"] = introduction(agent.engine, False)
        request = {
            "task": task, "language": agent.engine.locale, "actor": agent.seat.pos,
            "information": context, "persona": agent.persona,
            "personality_parameters": asdict(agent.style),
            "cognitive_parameters": agent.brain.cognition.to_dict(),
            "public_context": model_context.build_public_context(agent),
            "own_previous_decisions": agent.model_decisions[-model_context.DECISION_MEMORY:],
            "details": details, "instructions": MODEL_INSTRUCTIONS,
        }
        # Legacy rows without an event number do not get fabricated IDs.
        cutoff = max((row["event"]["event_no"]
                      for row in agent.public_record.entries
                      if type(row["event"].get("event_no")) is int), default=0)
        return Observation(agent.participant, cutoff,
                           model_context.fit_request_budget(deepcopy(request)))

    @staticmethod
    def public_events(record, last_event_no=0):
        """Shared public channel only; never accepts the full session ledger."""
        return deepcopy([row["event"] for row in record.entries
                         if (row["event"].get("event_no") or 0) > last_event_no])
