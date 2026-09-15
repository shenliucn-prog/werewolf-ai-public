"""Local user settings: the model/rules configuration snapshot, minus credentials.

A small, atomic, checksummed JSON store so a first-time connection check is not
repeated every session.  Only whitelisted fields are stored — never ``api_key``
or ``token``.  ``command`` (the agent-command argv) and ``agent_connections``
are trusted local config, persisted only by the trusted CLI (``trusted=True``),
never from an HTTP request.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy

from . import config

SETTINGS_PATH = os.path.join(config.DATA_DIR, "settings.json")
SETTINGS_SCHEMA_VERSION = 1

# Whitelisted config fields; anything else (credentials, …) is dropped.
ALLOWED_KEYS = {
    "backend", "model", "max_calls", "timeout", "base_url", "temperature",
    "reasoning_effort", "reasoning_param", "enabled", "effort",
    "driver", "adapter",
}

# Trusted local-only keys: an executable argv and named agent connections.  These
# are stored only by the trusted CLI; the Web can read them but never write them.
TRUSTED_KEYS = {"command", "agent_connections"}


def sanitize(config_dict, trusted=False):
    """Whitelist + deep-copy a config dict; credentials are never retained.

    ``trusted=True`` (the local CLI) additionally keeps the agent-command argv and
    named agent connections; the Web path keeps them out so an HTTP request can
    never plant an executable in local settings.
    """
    if config_dict is None:
        return None
    if not isinstance(config_dict, dict):
        raise ValueError("settings: config must be an object")
    keys = ALLOWED_KEYS | (TRUSTED_KEYS if trusted else set())
    return deepcopy({key: value for key, value in config_dict.items()
                     if key in keys})


def _canonical(data) -> bytes:
    normalized = json.loads(json.dumps(data, sort_keys=True, ensure_ascii=False))
    return json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(data) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def save_settings(config_dict, trusted=False) -> None:
    """Persist a sanitized config snapshot atomically (0700 dir / 0600 file)."""
    payload = sanitize(config_dict, trusted=trusted)
    # Saving API fields from the browser must not erase trusted local adapters.
    # Never accept those keys FROM the browser; retain only our existing store.
    if not trusted and isinstance(payload, dict):
        previous = load_settings() or {}
        for key in TRUSTED_KEYS:
            if key in previous:
                payload[key] = deepcopy(previous[key])
    envelope = {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "checksum": _digest(payload) if payload is not None else "",
        "payload": payload,
    }
    directory = os.path.dirname(os.path.abspath(SETTINGS_PATH))
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, SETTINGS_PATH)


def load_settings():
    """Return the saved sanitized config snapshot, or ``None`` when absent or
    corrupt (a corrupt settings file is non-critical and is ignored)."""
    if not os.path.exists(SETTINGS_PATH):
        return None
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("schema_version") != SETTINGS_SCHEMA_VERSION:
            return None
        payload = data.get("payload")
        if not isinstance(data.get("checksum"), str):
            return None
        if _digest(payload) != data["checksum"]:
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def runtime_kwargs(config_dict):
    """Map a sanitized config dict onto ``create_runtime`` kwargs (canonical).

    Resolves the backend (defaulting an api-like config to ``api``), carries the
    model / effort / max_calls for every backend, and passes the full options
    dict only for the api backend (which reads base_url / timeout / etc.).
    """
    if not config_dict:
        return {}
    cfg = config_dict
    backend = cfg.get("backend") or "api"
    kwargs = {
        "backend": backend,
        "model": cfg.get("model"),
        "effort": cfg.get("effort") or cfg.get("reasoning_effort"),
        "max_calls": cfg.get("max_calls"),
    }
    if backend == "api":
        options = {key: cfg[key] for key in
                   ("base_url", "temperature", "reasoning_effort", "reasoning_param",
                    "timeout", "max_calls", "model", "enabled", "api_key")
                   if cfg.get(key) is not None}
        kwargs["options"] = options or None
    return kwargs
