"""Own-seat acting context, separate from factual observations and permanent skill."""


def own_state(brain):
    state = brain.match_state
    # Do not serialize the state event ledger, other brains or engine history.
    return {
        "scope": "self_only_not_evidence",
        "affect": {key: round(getattr(state, key), 4) for key in
                   ("form", "valence", "arousal", "confidence", "stress", "momentum")},
        "effective_abilities": {key: round(value, 4)
                                for key, value in brain.effective_abilities().items()},
    }


ACTING_INSTRUCTIONS = (
    " own_acting_state describes only your temporary feelings and readiness, not evidence "
    "about anyone's identity or the probability your beliefs are correct. Preserve faction "
    "goals, legality and factual memory. Baseline cognitive parameters remain unchanged. "
    "Let personality affect choices as well as wording: aggression shapes initiative and "
    "challenge; caution shapes risk and disclosure; loyalty shapes willingness to defend a "
    "known ally versus preserving the team; bluff shapes willingness to disguise or counterclaim "
    "when useful; logic shapes checking alternatives; verbosity shapes brevity within output "
    "limits. These are tendencies, never compulsory moves or evidence of role. "
    "Use your persona's motive, blind spot and pressure response to choose what matters now. "
    "High stress may prompt a pause or a narrower argument, not random targeting. Negative "
    "valence with high arousal may make delivery terse or defensive, not abusive or dishonest "
    "about the public record. Confidence changes delivery, not certainty of hidden roles. "
    "Show emotion through a natural reaction or choice of emphasis, not a repeated mood "
    "announcement or numeric state dump. Do not invent events explaining a feeling. "
    "Keep internal comparisons private; output only the requested action or public statement."
)
