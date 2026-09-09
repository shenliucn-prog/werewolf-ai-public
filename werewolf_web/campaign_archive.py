"""Campaign archive: local, atomic, checksummed single-player progression store.

Separate from the game checkpoint.  The checkpoint holds one game's immutable
state; the archive holds cross-game progression — the unlocked level, per-level
results, the active game association, completion records, and a config snapshot
(no credentials).

Settlement is idempotent keyed by ``game_id`` and is read from the *validated,
identity-matched* checkpoint record, never from an arbitrary caller-supplied
winner.  ``reconcile`` performs the startup/restore crash catch-up (count the
attempt, then settle "ended but not recorded"; drop a stale ``preparing``
association whose game never initialized).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy

from . import config
from .campaign import LEVELS, PREPARING, IN_PROGRESS, player_side

CAMPAIGN_DIR = os.path.join(config.DATA_DIR, "campaign")
ARCHIVE_SCHEMA_VERSION = 1
_PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Terminal settlement results (§3.2): won / lost advance the win-loss counters,
# draw is a separate non-win record, abandoned is a non-win attempt.
RESULTS = ("won", "lost", "draw", "abandoned")
# result -> per-level stats counter key.
_STAT_KEY = {"won": "wins", "lost": "losses", "draw": "draws", "abandoned": "abandoned"}

# Non-sensitive config keys allowed into the snapshot (§5.2: no credentials).
_CONFIG_WHITELIST = {
    "backend", "model", "max_calls", "timeout", "base_url", "temperature",
    "reasoning_effort", "reasoning_param", "enabled", "effort", "board", "board_id",
    "personalities", "rules_version",
    "driver", "adapter",
}


def archive_path(profile_id: str) -> str:
    """Local archive file for one profile; the id charset mirrors checkpoints."""
    if not isinstance(profile_id, str) or not _PROFILE_RE.fullmatch(profile_id):
        raise ValueError("campaign: profile_id must match [A-Za-z0-9_-]{1,64}")
    return os.path.join(CAMPAIGN_DIR, f"{profile_id}.json")


def _canonical(data) -> bytes:
    # json turns int dict keys into strings; round-trip so the digest reflects
    # the on-disk representation (same fix as the checkpoint store).
    normalized = json.loads(json.dumps(data, sort_keys=True, ensure_ascii=False))
    return json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(data) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def save_archive(path: str, archive: dict) -> None:
    """Atomic, checksummed, permission-restricted archive write."""
    if not isinstance(archive, dict):
        raise ValueError("campaign: archive must be an object")
    envelope = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "checksum": _digest(archive),
        "payload": archive,
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_archive(path: str) -> dict:
    """Read and verify an archive; a corrupt archive raises rather than guessing."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"campaign: unreadable or malformed archive: {error}") from None
    if not isinstance(data, dict) or data.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise ValueError("campaign: unknown archive schema version")
    checksum = data.get("checksum")
    payload = data.get("payload")
    if not isinstance(checksum, str) or not isinstance(payload, dict):
        raise ValueError("campaign: archive checksum/payload invalid")
    if _digest(payload) != checksum:
        raise ValueError("campaign: archive checksum mismatch")
    return payload


def new_archive(profile_id: str = "default") -> dict:
    return {
        "profile_id": profile_id,
        "unlocked": 0,          # highest unlocked level index into LEVELS
        "attempts": {},         # role -> {"attempts","wins","losses","draws","abandoned"}
        "settled": [],          # game_ids already settled (dedup keys)
        "completions": [],      # ordered completion records
        "current_game": None,   # {"game_id","role","board","state"}
        "config": None,         # non-sensitive model/rules snapshot (deep-copied)
    }


def _level_stats(archive: dict, role: str) -> dict:
    return archive["attempts"].setdefault(
        role, {"attempts": 0, "wins": 0, "losses": 0, "draws": 0, "abandoned": 0})


def _level_index(role: str):
    for i, level in enumerate(LEVELS):
        if level["role"] == role:
            return i
    return None


def _config_snapshot(config):
    """Whitelist + deep-copy the config so no credential is ever stored and the
    snapshot is independent of the caller's live dict."""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("campaign: config snapshot must be an object")
    return deepcopy({key: value for key, value in config.items()
                     if key in _CONFIG_WHITELIST})


def register_attempt(archive: dict, game_id: str, role: str, board: str,
                     config: dict | None = None) -> dict:
    """Associate a new game with the archive in ``preparing`` state.

    Rejects (archive unchanged): a non-level / not-yet-unlocked role, a board
    that is not the level's fixed board, or an attempt already in flight.
    Does NOT count an attempt yet: only ``mark_in_progress`` counts, after the
    game's first checkpoint exists.
    """
    idx = _level_index(role)
    if idx is None:
        raise ValueError(f"campaign: {role!r} is not a campaign level role")
    if idx > archive.get("unlocked", 0):
        raise ValueError(f"campaign: {role!r} is not unlocked yet")
    expected_board = LEVELS[idx]["board"]
    if board != expected_board:
        raise ValueError(
            f"campaign: {role!r} must be played on {expected_board!r}, not {board!r}")
    if archive.get("current_game") is not None and archive.get("current_game").get("state") != PREPARING:
        raise ValueError("campaign: an attempt is already in progress")
    # A stale ``preparing`` association (a failed/aborted start) is replaced — it
    # was never counted, so nothing is lost.
    snapshot = _config_snapshot(config)     # validate + snapshot BEFORE mutating
    archive["current_game"] = {
        "game_id": game_id, "role": role, "board": board, "state": PREPARING,
    }
    archive["config"] = snapshot
    return archive


def mark_in_progress(archive: dict, game_id: str) -> dict:
    """Promote ``preparing`` -> ``in_progress`` and count one attempt, exactly once."""
    current = archive.get("current_game")
    if current and current.get("game_id") == game_id and current.get("state") == PREPARING:
        current["state"] = IN_PROGRESS
        _level_stats(archive, current["role"])["attempts"] += 1
    return archive


def drop_stale_preparing(archive: dict, game_id: str) -> dict:
    """Drop a ``preparing`` association whose game never created a checkpoint."""
    current = archive.get("current_game")
    if current and current.get("game_id") == game_id and current.get("state") == PREPARING:
        archive["current_game"] = None
    return archive


def result_for(winner: str | None, role: str) -> str:
    """Map the engine's faction winner onto a per-player settlement result.

    An undecided winner (``None``) is never a loss — it raises rather than
    mis-settling.
    """
    if winner == "draw":
        return "draw"
    if winner not in ("god", "wolf"):
        raise ValueError(f"campaign: cannot settle an undecided winner {winner!r}")
    side = player_side(role)          # "wolf" or "god"
    return "won" if winner == side else "lost"


def settle(archive: dict, game_id: str, result: str, winner: str | None = None,
           rounds: int = 0) -> dict:
    """Settle a finished game idempotently, keyed by ``game_id``.

    Rejects (archive unchanged) if ``game_id`` does not match the active
    association.  Only the first settle for a given ``game_id`` takes effect.
    Winning also unlocks the next level.
    """
    if result not in RESULTS:
        raise ValueError(f"campaign: unknown settle result {result!r}")
    if game_id in archive["settled"]:
        return archive
    current = archive.get("current_game")
    if current is None or current.get("game_id") != game_id:
        raise ValueError(
            f"campaign: cannot settle {game_id!r} — it is not the active attempt")
    role = current["role"]
    board = current["board"]
    state = current.get("state")
    # Reject a win/loss/draw on a not-started attempt, and contradictory results —
    # the settle entry itself must enforce the same counting constraints as
    # ``reconcile`` (a fresh ``preparing`` game has 0 counted attempts).
    if state != IN_PROGRESS:
        raise ValueError(f"campaign: cannot settle {result!r} on a {state!r} attempt")
    if result == "won":
        if winner != player_side(role):
            raise ValueError("campaign: 'won' contradicts the winner and role")
    elif result == "lost":
        if winner not in ("god", "wolf") or winner == player_side(role):
            raise ValueError("campaign: 'lost' contradicts the winner and role")
    elif result == "draw":
        if winner != "draw":
            raise ValueError("campaign: 'draw' requires winner='draw'")
    else:  # abandoned
        if winner not in (None, ""):
            raise ValueError("campaign: 'abandoned' must have no winner")
    _level_stats(archive, role)[_STAT_KEY[result]] += 1
    archive["completions"].append({
        "game_id": game_id, "role": role, "board": board,
        "result": result, "winner": winner, "rounds": rounds,
    })
    archive["settled"].append(game_id)
    archive["settled"].sort()
    if result == "won":
        idx = _level_index(role)
        if idx is not None:
            archive["unlocked"] = max(archive["unlocked"], min(idx + 1, len(LEVELS) - 1))
    archive["current_game"] = None
    return archive


# Sentinel returned by ``_validate_checkpoint`` for a valid-but-undealt save.
_UNINITIALIZED = object()


def _validate_checkpoint(checkpoint, game_id, current):
    """Validate the checkpoint's identity; return the terminal outcome
    ``(result, winner, rounds)`` when finished, ``None`` when in progress, or
    ``_UNINITIALIZED`` when the engine was never dealt.

    Runs before any archive mutation — an identity mismatch leaves the archive
    unchanged.
    """
    if not isinstance(checkpoint, dict):
        raise ValueError("campaign: checkpoint must be an object")
    if checkpoint.get("session_id") != game_id:
        raise ValueError("campaign: checkpoint session_id does not match the game")
    engine = checkpoint.get("engine")
    if not isinstance(engine, dict):
        raise ValueError("campaign: checkpoint has no engine")
    role = current["role"]
    board = current["board"]
    if engine.get("player_role") != role:
        raise ValueError("campaign: checkpoint player_role does not match the active role")
    if engine.get("board_id") != board:
        raise ValueError("campaign: checkpoint board does not match the active level")
    seats = engine.get("seats")
    if not isinstance(seats, list) or not seats:
        # A valid save whose engine was never dealt: still ``preparing`` — not an
        # error, but neither counted nor settled.
        return _UNINITIALIZED
    if not checkpoint.get("finished"):
        return None
    winner = engine.get("winner")
    result = result_for(winner, role)      # raises if undecided
    rounds = int(engine.get("day_count", 0)) + int(engine.get("night_count", 0))
    return result, winner, rounds


def reconcile(archive: dict, game_id: str, *, checkpoint=None) -> dict:
    """Crash catch-up for one game association (§5.1).

    - ``checkpoint is None``: the game never wrote a checkpoint -> drop a stale
      ``preparing`` entry (the attempt was never counted).
    - uninitialized (valid save, undealt engine): keep ``preparing`` — no count,
      no settle.
    - otherwise: count the attempt (preparing -> in_progress, idempotent) and, if
      the game ended, settle it.  Identity is validated *before* any mutation.
    """
    if game_id in archive.get("settled", []):
        return archive
    if checkpoint is None:
        return drop_stale_preparing(archive, game_id)
    current = archive.get("current_game")
    if current is None or current.get("game_id") != game_id:
        return archive                     # nothing associated with this game
    outcome = _validate_checkpoint(checkpoint, game_id, current)  # before any count
    if outcome is _UNINITIALIZED:
        return archive                     # still preparing; not counted, not settled
    mark_in_progress(archive, game_id)     # count the attempt exactly once
    if outcome is not None:
        result, winner, rounds = outcome
        return settle(archive, game_id, result=result, winner=winner, rounds=rounds)
    return archive
