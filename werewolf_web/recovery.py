"""Whitelisted snapshot/restore primitives for reliable play and recovery.

Every snapshot is an explicit field allowlist — never ``asdict()`` of a whole
live object — so it cannot drag in credentials (``api_key``), commands
(``argv``), or transient run state (queues, locks, socket references, liveness
flags).  Each snapshot carries a ``schema_version``; ``restore`` refuses
unknown versions so a stale or corrupted save cannot be silently misread.

Restore is deliberately strict and validate-then-apply: every field is checked
for type/range/consistency *before* the target object is touched, so a corrupt
or malicious snapshot cannot leave a half-restored object.
"""
from __future__ import annotations

import math
import random
from typing import Any

SCHEMA_VERSION = 1


def check_version(data: Any, where: str) -> None:
    """Reject a non-dict, a non-integer version, or an unknown version.

    The ``type() is int`` check matters: ``True`` compares equal to ``1`` and
    ``1.0`` compares equal to ``1``, so ``!= SCHEMA_VERSION`` alone would accept
    both.  A schema version must be a genuine integer.
    """
    if not isinstance(data, dict):
        raise ValueError(f"{where}: snapshot must be a dict")
    version = data.get("schema_version")
    if type(version) is not int or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError(
            f"{where}: unsupported snapshot schema version {version!r} "
            f"(expected integer {SCHEMA_VERSION})")


# ---------------------------------------------------------------- validators
def require_str(data: dict, key: str, where: str, allow_empty: bool = True) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{where}: {key!r} must be a string, got {value!r}")
    if not allow_empty and not value:
        raise ValueError(f"{where}: {key!r} must not be empty")
    return value


def require_int(data: dict, key: str, where: str,
                minimum: int | None = None, maximum: int | None = None) -> int:
    value = data.get(key)
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(f"{where}: {key!r} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{where}: {key!r} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{where}: {key!r} must be <= {maximum}, got {value}")
    return value


def require_number(data: dict, key: str, where: str,
                   minimum: float | None = None,
                   maximum: float | None = None) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: {key!r} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where}: {key!r} must be a finite number, got {value!r}")
    if minimum is not None and number < minimum:
        raise ValueError(f"{where}: {key!r} must be >= {minimum}, got {number}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{where}: {key!r} must be <= {maximum}, got {number}")
    return number


def require_bool(data: dict, key: str, where: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:
        raise ValueError(f"{where}: {key!r} must be a boolean, got {value!r}")
    return value


def require_dict(data: dict, key: str, where: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{where}: {key!r} must be an object, got {value!r}")
    return value


def require_list(data: dict, key: str, where: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{where}: {key!r} must be an array, got {value!r}")
    return value


# ---------------------------------------------------------------- RNG codec
def encode_rng(rng: random.Random) -> dict:
    """``random.Random.getstate()`` returns a tuple; encode it JSON-safely."""
    version, internal, gauss = rng.getstate()
    return {"version": int(version), "internal": list(internal), "gauss": gauss}


def decode_rng(data: Any) -> random.Random:
    """Rebuild a ``random.Random`` whose state matches the encoded snapshot.

    Strictly validates the encoded state so a corrupt snapshot fails cleanly
    instead of surfacing a confusing ``setstate`` error later.
    """
    if not isinstance(data, dict):
        raise ValueError("rng state must be an object")
    version = data.get("version")
    internal = data.get("internal")
    gauss = data.get("gauss")
    if type(version) is not int or isinstance(version, bool):
        raise ValueError(f"rng version must be an integer, got {version!r}")
    if not isinstance(internal, list) or any(
            type(x) is not int or isinstance(x, bool) for x in internal):
        raise ValueError("rng internal state must be an array of integers")
    if isinstance(gauss, bool) or (gauss is not None and
                                  not isinstance(gauss, (int, float))):
        raise ValueError(f"rng gauss must be a number or null, got {gauss!r}")
    if gauss is not None and not math.isfinite(float(gauss)):
        raise ValueError(f"rng gauss must be finite, got {gauss!r}")
    rng = random.Random()
    try:
        rng.setstate((version, tuple(internal), float(gauss) if gauss is not None else None))
    except (ValueError, TypeError):
        raise ValueError("invalid rng state") from None
    return rng
