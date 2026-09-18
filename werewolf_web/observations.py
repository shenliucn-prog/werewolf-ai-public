"""Trusted observation assembly; controllers receive detached data, not worlds.

The legacy agent is still a trusted adapter. Role visibility comes from the
existing InformationSet policy; this is an extraction, not a sandbox or a
claim that local executable agents cannot read files on their host.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass

from .participants import Participant
from .ai.acting_state import own_state, ACTING_INSTRUCTIONS


MODEL_INSTRUCTIONS = (
    "Optimize your own faction's victory, not agreement with the table or an attractive speech. "
    "Before choosing a speech or vote, compare your own recent public commitments and actions. "
    "A changed stance needs a concrete new observation or an acknowledged earlier mistake; "
    "do not invent either. A sheriff support vote is not an exile vote. "
    "If you are a wolf, privately weigh whether defending a teammate can actually change the "
    "outcome against exposing surviving pack members through linked votes. Sacrificing a teammate, "
    "defending them, counterclaiming or maintaining cover are choices, never mandatory scripts. "
    "Do not confuse your fabricated public suspicion with your private knowledge of your team. "
    "Do not disclose this private comparison in public speech. Do not assume future votes are known. "
    "Embody your character, not twelve copies of a debate analyst. Let the persona's motive "
    "choose what you care about and its blind spot shape your provisional judgment. Express "
    "warmth, doubt, humor, annoyance or loyalty when earned by the actual conversation. "
    "A short personal reaction or a concession is valid; not every speech needs a full role grid. "
    "Under pressure follow the acting direction, without threats or abuse. The voice_sample "
    "is an audition, NOT a historical utterance: do not copy it into every turn. Catchphrases "
    "are optional and rare. Personality never proves faction, permits invented observations "
    "or substitutes for answering a direct question. "
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
    " joint_hypotheses, when present, are optional heuristic aids, not calibrated facts or orders. "
    "Evaluate their assumptions against the source observations; choose your own action. "
    "Never describe a hypothesis weight as a verified role or leak privately known pack membership."
    " Your own earlier guess is a commitment to track, not new independent evidence for itself."
    " public_story is an optional summary of public pressure and your commitments, not other "
    "players' private beliefs or guaranteed future votes. New evidence may justify a changed stance."
    " Repeating one claim does not create independent evidence. A flip resolves the target's role, "
    "not the speaker's role; correct claims and fabricated good checks can both come from wolves. "
    "When assessing an exile ballot, distinguish that day's votes from earlier votes and sheriff support."
    " For an explicit public Seer check report, append a standalone final line exactly like "
    "'Seer report: night 1, seat 3, good.' or '预言家查验声明：第1夜，3号，好人。'. "
    "Use the night, seat and good/wolf (好人/狼人) result you choose to claim. "
    "These lines are your public claims, never quote another player in this declaration format. "
    "check_claim_audit flags only explicit declarations, not all prose; compatibility is not proof, "
    "and a contradiction is not automatic proof of the speaker's faction."
    " speaking_turns.awaiting means not yet given a main turn, NOT evasion or refusal. "
    "A queued question does not prove its recipient already had an opportunity to answer. "
    "Public facts outrank attributed statements and your hypotheses: an exile ballot targeting "
    "someone is not proof they were exiled; night_death must not be described as voted out. "
    "Revealed god-side roles (including witch and civilian) are good faction: exiling a witch "
    "is not a correct wolf elimination. Distinguish a wolf's private benefit from a plausible "
    "public good-player argument. Keep support (站/保) distinct from accusation (怀疑/出); "
    "your structured accuse/defend fields must match what you actually say. "
) + ACTING_INSTRUCTIONS


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
        from .ai.joint_belief import for_brain
        from .ai.public_story import for_brain as public_story

        if (agent.participant.participant_id != agent.seat.player_id
                or agent.participant.seat != agent.seat.pos):
            raise ValueError("Observation participant does not match the acting seat")
        context = model_context.bound_information(asdict(agent.information_set()))
        context["rules"] = introduction(agent.engine, False)
        own_statements = [row["event"] for row in agent.public_record.entries
                          if row["event"].get("type") == "speech"
                          and row["event"].get("seat") == agent.seat.pos][-2:]
        details = deepcopy(details)
        details["own_recent_public_commitments"] = [
            {"event_no": event.get("event_no"), "day": event.get("day"),
             "night": event.get("night"), "phase": event.get("phase"),
             "text": event.get("text", "")[:240],
             "excerpt": len(event.get("text", "")) > 240}
            for event in own_statements]
        request = {
            "task": task, "language": agent.engine.locale, "actor": agent.seat.pos,
            "information": context, "persona": agent.persona,
            "personality_parameters": asdict(agent.style),
            "cognitive_parameters": agent.brain.cognition.to_dict(),
            "own_acting_state": own_state(agent.brain),
            "public_context": model_context.build_public_context(agent),
            "own_previous_decisions": agent.model_decisions[-model_context.DECISION_MEMORY:],
            "details": details, "instructions": MODEL_INSTRUCTIONS,
            "joint_hypotheses": for_brain(agent.brain),
            "public_story": public_story(agent.brain),
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
