"""Bounded per-decision model context (RECOVERY_DESIGN §9).

Two tiers.  The *full archive* — original text, retrievable by ``event_no`` —
stays whole in ``PublicRecord`` and the event ledger; nothing here deletes or
rewrites it.  This module builds the *model context*: the bounded slice actually
shown to the model for one decision.

The model is shown:

  - its own lawful private information and the rules (assembled elsewhere),
  - settled public facts (flips, deaths/exiles, recent ballots),
  - the most recent public statements verbatim,
  - older speech and votes as *attributed claims* ("#3 Alice claimed seer",
    "#5 Bob accused Alice on day 3") — never rewritten facts ("Alice is seer").

Every cap is deliberate: the point is boundedness, not any particular number,
and ``fit_request_budget`` enforces a cap on the *whole serialized request* so
the final prompt size has an acceptance bound.

Conjecture mode is not covered here: a model planner with ``conjecture=True`` is
currently rejected outright at ``GameSession`` construction, so there is no
model+conjecture path to budget yet — the "full traceable table versions"
requirement is a future wiring, not a forgetting strategy that is implemented.
"""
from __future__ import annotations

import json

VERBATIM_SPEECHES = 12   # most recent public speeches shown word-for-word
DECISION_MEMORY = 8      # most recent of the actor's own decisions shown
CLAIM_WINDOW = 16        # most recent role claims summarized
ACCUSE_DEFEND_WINDOW = 16  # most recent accusation/defence pairs summarized
BALLOT_WINDOW = 6        # most recent ballots shown as facts
VOTE_WINDOW = 16         # most recent public votes carried in the info set
FACT_WINDOW = 24         # total number of fact entries shown

# Budget on the *whole* serialized model request — rules + information + persona
# + instructions + context.  Characters are a deterministic token proxy; the
# point is an acceptance bound on the final request size, not just per-field
# counts.
MAX_REQUEST_CHARS = 24000


def _speech_rows(entries):
    return [r for r in entries if r["event"].get("type") == "speech"]


def recent_public_statements(entries):
    """The most recent public speeches, word-for-word (bounded)."""
    rows = _speech_rows(entries)[-VERBATIM_SPEECHES:]
    return [
        {"day": r["day"], "seat": r["event"].get("seat"), "name": r["event"].get("name"),
         "text": r["event"].get("text"), "event_no": r["event"].get("event_no")}
        for r in rows
    ]


def older_statement_summaries(brain):
    """Attributed claims from the structured observation logs.

    These are claims, not facts: each entry records *who said what about whom*,
    so the model can never mistake a claim for a settled flip.  No verbatim text
    is carried — the archive holds that, keyed by event number.
    """
    items = []
    claims = [{"who": who, "claimed_role": role}
              for who, role in brain.claim_order[-CLAIM_WINDOW:]]
    if claims:
        items.append({"kind": "role_claims", "items": claims})
    accusations = [{"day": day, "who": who, "accused": target}
                   for day, who, target in brain.accuse_log[-ACCUSE_DEFEND_WINDOW:]]
    if accusations:
        items.append({"kind": "accusations", "items": accusations})
    defences = [{"day": day, "who": who, "defended": target}
                for day, who, target in brain.defend_log[-ACCUSE_DEFEND_WINDOW:]]
    if defences:
        items.append({"kind": "defences", "items": defences})
    return items


def public_facts(entries):
    """Settled public facts: flips, deaths/exiles, and recent ballots."""
    facts = []
    for r in entries:
        ev = r["event"]
        kind = ev.get("type")
        if kind == "flip":
            facts.append({"kind": "flip", "day": r["day"], "seat": ev.get("seat"),
                          "text": ev.get("text"), "event_no": ev.get("event_no")})
        elif kind in ("death", "exile"):
            facts.append({"kind": kind, "day": r["day"], "seat": ev.get("seat"),
                          "text": ev.get("text"), "event_no": ev.get("event_no")})
    ballots = [r for r in entries if r["event"].get("type") == "ballots"]
    for r in ballots[-BALLOT_WINDOW:]:
        ev = r["event"]
        facts.append({"kind": "ballots", "day": r["day"],
                      "ballots": ev.get("ballots"), "tally": ev.get("tally"),
                      "event_no": ev.get("event_no")})
    return facts[-FACT_WINDOW:]


def build_public_context(agent):
    """The bounded public context for one model decision."""
    entries = agent.public_record.entries
    return {
        "recent_public_statements": recent_public_statements(entries),
        "older_statement_summaries": older_statement_summaries(agent.brain),
        "public_facts": public_facts(entries),
    }


def bound_information(info: dict) -> dict:
    """Bound the parts of the information set that grow with the game.

    ``information_set()`` currently exposes the full public vote log; the model
    only needs the recent tail.  Returns a shallow copy, so the caller's dict
    (and the live ``InformationSet`` behind it) is never mutated.
    """
    info = dict(info)
    votes = info.get("public_votes")
    if isinstance(votes, list) and len(votes) > VOTE_WINDOW:
        info["public_votes"] = votes[-VOTE_WINDOW:]
    return info


def _serialized_size(request: dict) -> int:
    return len(json.dumps(request, ensure_ascii=False))


def fit_request_budget(request: dict, max_chars: int = MAX_REQUEST_CHARS) -> dict:
    """Guarantee the *whole* serialized request stays within ``max_chars``.

    The per-field caps bound history *counts*; this bounds the *final request
    size*.  It trims the lowest-value context first — the oldest verbatim public
    statements, then the oldest in-round statements (``details.earlier_this_round``,
    which duplicates the public statements), then the oldest of the actor's own
    decisions — until the entire request (rules, information, persona,
    instructions and all) fits.  The archive is untouched: this only decides
    what the model is shown.

    The lists it trims are fresh copies owned by the request, so popping them
    cannot affect the live ``public_record`` or ``model_decisions``.
    """
    statements = request.get("public_context", {}).get("recent_public_statements")
    decisions = request.get("own_previous_decisions")
    details = request.get("details")
    earlier = details.get("earlier_this_round") if isinstance(details, dict) else None

    def over_budget() -> bool:
        return _serialized_size(request) > max_chars

    while statements and over_budget():
        statements.pop(0)
    while earlier and over_budget():
        earlier.pop(0)
    while decisions and over_budget():
        decisions.pop(0)
    if over_budget():
        # The fixed parts alone (rules/persona/instructions/information) already
        # exceed the budget — a misconfiguration, not a game-state problem.
        raise ValueError(
            f"model request exceeds the context budget even with no history "
            f"({_serialized_size(request)} chars > {max_chars})")
    return request
