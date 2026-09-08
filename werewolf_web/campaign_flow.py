"""Campaign flow wiring: coordinate the archive with a game's checkpoint.

The archive is the source of truth for progression; the game checkpoint is the
source of truth for a single game's outcome.  Entry points call these to run the
full create -> save -> interrupt -> resume -> settle lifecycle.
"""
from __future__ import annotations

import os

from . import campaign_teaching
from . import checkpoint
from .ai.decision_runtime import ModelTurnError
from .campaign_archive import (
    archive_path, load_archive, save_archive, new_archive,
    register_attempt, mark_in_progress, reconcile,
    settle, drop_stale_preparing, result_for, IN_PROGRESS,
)


def load_profile(profile_id: str) -> dict:
    """Load the archive for a profile; a missing archive starts a fresh one, a
    corrupt archive raises (progress must not be silently reset)."""
    path = archive_path(profile_id)
    if not os.path.exists(path):
        return new_archive(profile_id)
    return load_archive(path)


def begin_attempt(profile_id: str, game_id: str, role: str, board: str,
                  config: dict | None = None) -> dict:
    """Register a ``preparing`` attempt and persist it.

    Any existing association is reconciled first: a save that is already
    initialized counts the old attempt and is then refused as in-progress; a
    save that never started is released; a corrupt save is refused.  A bare
    ``preparing`` is not assumed to mean "never started".
    """
    archive = load_profile(profile_id)
    current = archive.get("current_game")
    if current is not None:
        old_id = current["game_id"]
        status, payload = checkpoint.probe_checkpoint(old_id)
        if status in ("uninitialized", "ok"):
            reconcile(archive, old_id, checkpoint=payload)
        elif status == "missing":
            drop_stale_preparing(archive, old_id)
        elif status == "corrupt":
            raise ValueError("campaign: existing game save is corrupt; refusing to overwrite")
        current = archive.get("current_game")
        if current is not None and current.get("state") == IN_PROGRESS:
            save_archive(archive_path(profile_id), archive)   # persist the count
            raise ValueError("campaign: an attempt is already in progress")
    register_attempt(archive, game_id, role, board, config=config)
    save_archive(archive_path(profile_id), archive)
    return archive


def settled_result(profile_id: str, game_id: str):
    """Return the settle result ("won"/"lost"/"draw"/"abandoned") for a settled
    game_id, or ``None`` if it has not been settled."""
    archive = load_profile(profile_id)
    if game_id not in archive.get("settled", []):
        return None
    for record in archive.get("completions", []):
        if record.get("game_id") == game_id:
            return record.get("result")
    return None


def mark_started(profile_id: str, game_id: str) -> dict:
    """Count the attempt once (``preparing`` -> ``in_progress``) after the game's
    first initialized checkpoint exists, and persist."""
    archive = load_profile(profile_id)
    mark_in_progress(archive, game_id)
    save_archive(archive_path(profile_id), archive)
    return archive


def settle_game(profile_id: str, game_id: str, checkpoint_payload: dict) -> dict:
    """Reconcile the archive against a loaded checkpoint payload: count the
    attempt if still preparing, and settle the result if the game ended."""
    archive = load_profile(profile_id)
    reconcile(archive, game_id, checkpoint=checkpoint_payload)
    save_archive(archive_path(profile_id), archive)
    return archive


def abandon_game(profile_id: str, game_id: str) -> dict:
    """Settle an explicit abandon: count ``abandoned`` if the attempt started,
    else drop the never-counted ``preparing`` association.  Must run *before* the
    game checkpoint is deleted, so the abandon result is recoverable."""
    archive = load_profile(profile_id)
    current = archive.get("current_game")
    if current and current.get("game_id") == game_id:
        if current.get("state") == IN_PROGRESS:
            settle(archive, game_id, result="abandoned")
        else:
            drop_stale_preparing(archive, game_id)
    save_archive(archive_path(profile_id), archive)
    return archive


def progress_hook(profile_id: str, game_id: str):
    """A ``GameSession.progress_hook``: count the attempt once the game deals and
    settle it once it ends.  Idempotent via the archive's own guards.

    The post-loss short review is deliberately NOT generated here: it runs once
    at an explicit entry point (``generate_review_once``) guarded by the durable
    ``campaign_review_state``, so a restore never re-triggers (or re-charges) it.
    """
    state = {"marked": False, "settled": False}

    def hook(runner):
        if not state["marked"] and runner.engine.seats:
            state["marked"] = True
            mark_started(profile_id, game_id)
        if not state["settled"] and runner.finished:
            state["settled"] = True
            settle_game(profile_id, game_id, runner.snapshot())

    return hook


def generate_teaching(session, role: str, model: str, publish: bool = True) -> dict:
    """Generate (or cache-fetch) the first-entry teaching for a campaign level and
    publish it as a public event.  On model failure it emits an explicit
    ``unavailable`` marker — never a canned text masquerading as teaching.

    ``publish=False`` returns the event without emitting it, so a terminal retry
    can render the result inline instead of double-emitting it through the event
    queue (the live REPL loop would otherwise re-render it later)."""
    locale = session.engine.locale
    try:
        text = campaign_teaching.cached_role_teaching(
            session.planner, role, locale, model, persist=session._checkpoint)
    except ModelTurnError:
        event = {"type": "teaching", "role": role, "unavailable": True,
                 "text": ("Teaching is temporarily unavailable; please retry."
                          if locale == "en" else "教学暂不可用，请重试。")}
        if publish:
            session.emit(event)
        return event
    event = {"type": "teaching", "role": role, "text": text}
    if publish:
        session.emit(event)
    return event


def _human_decisions(decision_log) -> list[dict]:
    """The player's own *committed* decisions only (human slots), stripped of the
    internal per-attempt budget bookkeeping — never other seats' decisions, and
    never an uncommitted in-flight attempt."""
    out: list[dict] = []
    for entry in decision_log or []:
        slot = entry.get("slot")
        if (isinstance(slot, str) and slot.startswith("human:")
                and entry.get("committed")):
            out.append({"slot": slot, "result": entry.get("result"),
                        "committed": bool(entry.get("committed"))})
    return out


def _public_facts(session) -> list[dict]:
    """Public facts (flips/deaths/ballots/exiles) from the event ledger, never
    private results or another seat's hidden role."""
    facts: list[dict] = []
    for row in session.public_record.entries:
        ev = row.get("event", {})
        if ev.get("type") not in ("death", "flip", "ballots", "exile"):
            continue
        fact = {"day": row.get("day"), "type": ev.get("type")}
        for key in ("seat", "text"):
            if key in ev:
                fact[key] = ev[key]
        facts.append(fact)
    return facts


def generate_campaign_review(session, role: str | None = None) -> dict | None:
    """Post-loss short review, generated on demand.  This is the *explicit* path:
    an initial generation and every later retry both run here, charging budget and
    overwriting the durable ``campaign_review_state``.

    Uses only the player's committed decisions and public facts.  Returns ``None``
    when the game was not a loss (won/draw/offline); a model failure emits an
    ``unavailable`` marker, sets the state to ``"unavailable"``, and never touches
    the already-settled score.  Success sets the state to ``"done"``.
    """
    role = role or session.engine.player_role
    try:
        result = result_for(session.engine.winner, role)
    except ValueError:
        return None
    if result != "lost":
        return None
    decisions = _human_decisions(session.decision_log)
    facts = _public_facts(session)
    locale = session.engine.locale
    try:
        text = campaign_teaching.short_review(
            session.planner, decisions, facts, role, locale,
            persist=session._checkpoint)
    except ModelTurnError:
        event = {"type": "campaign_review", "role": role,
                 "winner": session.engine.winner, "unavailable": True,
                 "text": ("Short review is temporarily unavailable; retry later."
                          if locale == "en" else "短复盘暂不可用，可稍后重试。")}
        session.emit(event)
        session.campaign_review_state = "unavailable"
        session._checkpoint()
        return event
    event = {"type": "campaign_review", "role": role,
             "text": text, "winner": session.engine.winner}
    session.emit(event)
    session.campaign_review_state = "done"
    session._checkpoint()
    return event


def review_state(session) -> str | None:
    """The durable post-loss review state: ``None`` / ``"done"`` / ``"unavailable"``."""
    return session.campaign_review_state


def review_applies(session, role: str | None = None) -> bool:
    """True when this campaign game's result warrants a short review (a loss)."""
    role = role or session.engine.player_role
    try:
        return result_for(session.engine.winner, role) == "lost"
    except ValueError:
        return False


def generate_review_once(session, role: str | None = None) -> dict | None:
    """Generate the post-loss short review exactly once, guarded by the persisted
    ``campaign_review_state``.

    A persisted ``"done"`` or ``"unavailable"`` review is never regenerated here —
    only an explicit retry (``generate_campaign_review``) re-requests and
    overwrites it.  Returns the emitted event, or ``None`` when already generated
    or when the game is not a loss.
    """
    if session.campaign_review_state in ("done", "unavailable"):
        return None
    return generate_campaign_review(session, role=role)


def resume(profile_id: str, game_id: str, session) -> bool:
    """Shared resume logic for every entry point (Web rejoin/stream, terminal
    --resume): refuse a settled-as-abandoned game, reconcile the archive, and
    re-attach the progress hook.  Returns False to refuse, True to continue."""
    if settled_result(profile_id, game_id) == "abandoned":
        return False
    resume_game(profile_id, game_id)
    session.progress_hook = progress_hook(profile_id, game_id)
    return True


def resume_game(profile_id: str, game_id: str):
    """Probe the game's checkpoint and reconcile the archive.

    Returns ``(status, archive)`` where ``status`` is one of ``missing`` /
    ``corrupt`` / ``uninitialized`` / ``ok``.  Missing drops a stale preparing
    entry; uninitialized keeps it; ok counts and settles if ended; corrupt
    leaves the archive untouched so the caller can refuse the resume.
    """
    status, payload = checkpoint.probe_checkpoint(game_id)
    archive = load_profile(profile_id)
    if status == "missing":
        reconcile(archive, game_id, checkpoint=None)
    elif status in ("uninitialized", "ok"):
        reconcile(archive, game_id, checkpoint=payload)
    # corrupt: leave the archive alone
    save_archive(archive_path(profile_id), archive)
    return status, archive
