"""Atomic, checksummed, permission-restricted checkpoint storage (§5.2 / §7).

A checkpoint is a versioned JSON envelope written atomically (``save.tmp`` then
``rename``) under a ``0700`` directory with a ``0600`` file, guarded by a SHA-256
checksum.  It is *never emitted*; it exists only on disk under the session data
directory.  Corruption of the authoritative (latest) checkpoint is an explicit
error — the recovery layer refuses to "resume from an older checkpoint", because
that could re-apply actions already committed and emitted after it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import config
from .recovery import SCHEMA_VERSION, check_version

CHECKPOINTS_DIR = os.path.join(config.DATA_DIR, "checkpoints")

# ``game_id`` is generated via ``secrets.token_urlsafe`` and is also supplied by
# clients on the rejoin/stream query string.  Restricting it to this charset
# means it can never escape the checkpoint directory (no ``/``, no ``..``).
_GAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _canonical(data) -> bytes:
    """Deterministic serialization so the checksum is stable across runs.

    ``json`` turns integer dict keys into strings on the way out, and its
    ``sort_keys`` sorts int keys numerically but string keys lexicographically
    ("2" before "10" vs "10" before "2").  Round-trip through ``json.loads``
    first so the digest reflects *exactly* the on-disk representation, no matter
    whether the in-memory payload still has integer keys.  Otherwise a payload
    like ``{"votes": {2: 1, 10: 2}}`` saves, re-reads with string keys, and
    fails its own checksum.
    """
    normalized = json.loads(json.dumps(data, sort_keys=True, ensure_ascii=False))
    return json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(data) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def checkpoint_path(game_id: str) -> str:
    """Single-writer file for one game task, keyed by ``game_id``.

    ``game_id`` is validated against a strict charset so a client-supplied id
    can never traverse out of the checkpoint directory.
    """
    if not isinstance(game_id, str) or not _GAME_ID_RE.fullmatch(game_id):
        raise ValueError(
            "checkpoint: game_id must match [A-Za-z0-9_-]{1,64}")
    return os.path.join(CHECKPOINTS_DIR, f"{game_id}.json")


def save_checkpoint(path: str, payload: dict) -> None:
    """Persist ``payload`` atomically with a version and checksum.

    The directory is forced to ``0700`` and the file to ``0600`` before the
    atomic rename, so the high-value secret (roles, private results, NPC
    beliefs) is never world-readable.
    """
    if not isinstance(payload, dict):
        raise ValueError("checkpoint: payload must be an object")
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "checksum": _digest(payload),
        "payload": payload,
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


def load_checkpoint(path: str) -> dict:
    """Read and verify a checkpoint; a corrupt latest save raises, never falls
    back to an older one."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"checkpoint: unreadable or malformed save: {error}") from None
    check_version(data, "checkpoint")
    checksum = data.get("checksum")
    payload = data.get("payload")
    if not isinstance(checksum, str):
        raise ValueError("checkpoint: checksum missing or invalid")
    if not isinstance(payload, dict):
        raise ValueError("checkpoint: payload must be an object")
    if _digest(payload) != checksum:
        raise ValueError(
            "checkpoint: checksum mismatch — refusing to resume a corrupt save")
    return payload


def probe_checkpoint(game_id: str):
    """Distinguish the three save states a resume must treat differently.

    Returns ``("missing", None)`` (no file — genuinely never started),
    ``("corrupt", None)`` (file exists but fails to parse/verify, or its
    ``session_id`` does not match), ``("uninitialized", payload)`` (valid save
    whose engine was never dealt), or ``("ok", payload)``.
    """
    try:
        path = checkpoint_path(game_id)
    except ValueError:
        return "missing", None
    if not os.path.exists(path):
        return "missing", None
    try:
        payload = load_checkpoint(path)
    except ValueError:
        return "corrupt", None
    if payload.get("session_id") != game_id:
        return "corrupt", None
    engine = payload.get("engine")
    if isinstance(engine, dict) and not engine.get("seats"):
        return "uninitialized", payload
    return "ok", payload
