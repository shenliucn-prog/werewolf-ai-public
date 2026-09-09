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

from .statement_memory import statement_summaries

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

# Cap on the contested-speech section (§phase-2): disputed originals are kept
# word-for-word, referenced by event_no, within this character budget — never
# unbounded.  When the budget is exceeded, older items are dropped and a
# ``truncated`` marker is set.
DISPUTED_MAX_CHARS = 1600


def _speech_rows(entries):
    return [r for r in entries if r["event"].get("type") == "speech"]


def recent_public_statements(entries):
    """The most recent public speeches, word-for-word (bounded).

    Each row carries ``day``/``night``/``phase`` so a sheriff-candidacy speech is
    never read as a plain day speech, and ordering is by ``event_no``.
    """
    rows = _speech_rows(entries)[-VERBATIM_SPEECHES:]
    return [
        {"day": r["day"], "night": r.get("night"), "phase": r.get("phase"),
         "seat": r["event"].get("seat"), "name": r["event"].get("name"),
         "text": r["event"].get("text"), "event_no": r["event"].get("event_no")}
        for r in rows
    ]


def older_statement_summaries(brain, entries=()):
    """Attributed claims from the structured observation logs.

    These are claims, not facts: each entry records *who said what about whom*,
    so the model can never mistake a claim for a settled flip.  No verbatim text
    is carried — the archive holds that, keyed by event number.
    """
    return statement_summaries(entries, brain, CLAIM_WINDOW, ACCUSE_DEFEND_WINDOW)


def disputed_verbatim(entries, brain, max_chars=DISPUTED_MAX_CHARS):
    """Keep challenges and candidate originals, without inventing exact links.

    Accuse/defend identifies a person, not a particular utterance. Prior
    utterances are therefore explicitly candidates; later utterances cannot be
    the source. Prefer candidates within the shared bounded text budget.
    """
    disputed_nos = set(getattr(brain, "disputed_event_nos", None) or [])
    if not disputed_nos:
        return {"items": [], "truncated": False}
    items = []
    size = 0
    truncated = False
    rows = list(_speech_rows(entries))
    targets = getattr(brain, "disputed_targets", [])
    if not isinstance(targets, (list, tuple)):
        targets = []  # Older brains have only challenge event numbers.
    candidates = set()
    for challenge_no, target in targets:
        candidates.update(row["event"]["event_no"] for row in rows
                          if row["event"].get("name") == target
                          and isinstance(row["event"].get("event_no"), int)
                          and row["event"]["event_no"] < challenge_no)
    selected = [row for row in rows
                if row["event"].get("event_no") in candidates | disputed_nos]
    selected.sort(key=lambda row: (row["event"].get("event_no") not in candidates,
                                   -row["event"].get("event_no", 0)))
    for row in selected:
        event = row["event"]
        text = event.get("text") or ""
        remaining = max_chars - size
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            # Keep a truncated original (still referenced by event_no) so the
            # contested statement is not dropped entirely, and mark the cut.
            text = text[:max(0, remaining - 1)] + "…"
            truncated = True
        items.append({
            "day": row.get("day"), "night": row.get("night"),
            "phase": row.get("phase"), "seat": event.get("seat"),
            "name": event.get("name"), "text": text,
            "event_no": event.get("event_no"),
            "reference_status": "candidate_original" if event.get("event_no") in candidates else "challenge",
            "exact_reference": "unknown",
        })
        size += len(text)
        if truncated:
            break
    items.sort(key=lambda item: item["event_no"])
    return {"items": items, "truncated": truncated}


def public_facts(entries):
    """Settled public facts: flips, deaths/exiles, and recent ballots.

    Every entry carries ``day``/``night``/``phase`` so a night-2 death is never
    read as a day-1 event, and every ballot carries ``vote_kind`` so a sheriff
    ballot is never read as an exile vote.  Order is by ``event_no`` (the ledger),
    never by a monotonic 4-tuple guess.
    """
    facts = []
    for r in entries:
        ev = r["event"]
        kind = ev.get("type")
        temporal = {"day": r.get("day"), "night": r.get("night"),
                    "phase": r.get("phase")}
        if kind == "flip":
            facts.append({"kind": "flip", "seat": ev.get("seat"),
                          "text": ev.get("text"), "event_no": ev.get("event_no"),
                          **temporal})
        elif kind in ("death", "exile"):
            facts.append({"kind": kind, "seat": ev.get("seat"),
                          "text": ev.get("text"), "event_no": ev.get("event_no"),
                          **temporal})
    ballots = [r for r in entries if r["event"].get("type") == "ballots"]
    for r in ballots[-BALLOT_WINDOW:]:
        ev = r["event"]
        sheriff = ev.get("sheriff")
        # An absent ``sheriff`` field is a legacy record whose kind we cannot
        # reliably infer — mark it unknown rather than fabricating "exile".
        vote_kind = "sheriff" if sheriff is True else ("exile" if sheriff is False else "unknown")
        facts.append({"kind": "ballots", "vote_kind": vote_kind,
                      "day": r.get("day"), "night": r.get("night"),
                      "ballots": ev.get("ballots"), "tally": ev.get("tally"),
                      "event_no": ev.get("event_no")})
    return facts[-FACT_WINDOW:]


def build_public_context(agent):
    """The bounded public context for one model decision."""
    entries = agent.public_record.entries
    return {
        "recent_public_statements": recent_public_statements(entries),
        "older_statement_summaries": older_statement_summaries(agent.brain, entries),
        "disputed_verbatim": disputed_verbatim(entries, agent.brain),
        "public_facts": public_facts(entries),
        "statements_of_flipped_seers": statements_of_flipped_seers(entries, getattr(agent.brain, "flips", [])),
    }


def statements_of_flipped_seers(entries, flips):
    """Keep scarce public information-role evidence beyond the sliding window.

    Uses only observed public flips and public speech, never engine check results.
    Original excerpts stay attributed; a role reveal does not certify a claim.
    """
    names = {name for name, role, _wolf in flips if role == "seer"}
    rows = [row for row in _speech_rows(entries) if row["event"].get("name") in names]
    items = []
    for row in rows[-3:]:
        event = row["event"]
        original = event.get("text") or ""
        items.append({"name": event.get("name"), "seat": event.get("seat"),
                      "event_no": event.get("event_no"), "day": row.get("day"),
                      "night": row.get("night"), "phase": row.get("phase"),
                      "text": original[:1200], "truncated": len(original) > 1200,
                      "status": "attributed statement; speaker publicly flipped seer"})
    return items


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
    disputed = request.get("public_context", {}).get("disputed_verbatim")
    disputed_items = disputed.get("items") if isinstance(disputed, dict) else None
    seer_statements = request.get("public_context", {}).get("statements_of_flipped_seers")
    summaries = request.get("public_context", {}).get("older_statement_summaries", [])

    def over_budget() -> bool:
        return _serialized_size(request) > max_chars

    while statements and over_budget():
        statements.pop(0)
    while earlier and over_budget():
        earlier.pop(0)
    while decisions and over_budget():
        decisions.pop(0)
    # Source metadata is useful but still history, not an untrimmable fixed
    # instruction. Remove the oldest linked summary first (unknowns first).
    while over_budget():
        populated = [group for group in summaries if group.get("items")]
        if not populated:
            break
        group = min(populated, key=lambda g: g["items"][0].get("event_no") or -1)
        group["items"].pop(0)
    # Contested originals are the highest-value context; drop them last, and mark
    # the section truncated so the model knows text is missing.
    while disputed_items and over_budget():
        disputed_items.pop(0)
        disputed["truncated"] = True
    while seer_statements and over_budget():
        seer_statements.pop(0)
    if over_budget():
        # The fixed parts alone (rules/persona/instructions/information) already
        # exceed the budget — a misconfiguration, not a game-state problem.
        raise ValueError(
            f"model request exceeds the context budget even with no history "
            f"({_serialized_size(request)} chars > {max_chars})")
    return request
