"""Unified game-driver resolution: how NPC decisions are produced.

The *driver* is distinct from the transport/UI:

- ``api``     — an OpenAI-compatible model API.  ``base_url`` / ``model`` /
                ``api_key``; a keyless local model server is a valid, fully
                configured API connection.
- ``agent``   — the user's own Agent via a locally pre-configured, verified
                connection.  The adapter (``command`` = a local JSON
                stdin/stdout wrapper, ``codex`` = the Codex CLI) is a SECOND
                layer and is never folded into ``driver``.
- ``offline`` — explicit rule-flow simulation, labelled "程序策略模拟" and never
                counted toward campaign progression.

Resolution order: explicit params > saved local settings > environment defaults.
"Unconfigured" is a distinct state (``configured=False``): it is never inferred
as ``offline`` and never blindly defaults to ``api`` — the caller is expected to
report it so the UI can guide configuration.
"""
from __future__ import annotations

import json
import os

from . import config as app_config

DRIVERS = ("api", "agent", "offline")
ADAPTERS = ("command", "codex")

_ENV_BACKEND = "WEREWOLF_MODEL_BACKEND"
_ENV_CODEX_MODEL = "WEREWOLF_CODEX_MODEL"
_ENV_AGENT_COMMAND = "WEREWOLF_AGENT_COMMAND"


class DriverResolutionError(ValueError):
    """A resolvable config turned out to be invalid (e.g. a malformed command)."""


def _first(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _unified_effort(*sources):
    """Resolve the ``effort`` / ``reasoning_effort`` alias per source, in source
    priority order, so an explicit ``effort`` always beats a saved
    ``reasoning_effort``.  Within a single source ``effort`` (the canonical
    field) wins over ``reasoning_effort``."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = _first(source.get("effort"), source.get("reasoning_effort"))
        if value is not None:
            return value
    return None


def _result(driver, adapter, backend, model, effort, max_calls, options,
            command, configured, reason=None):
    kwargs = None
    if configured and driver in ("api", "agent"):
        kwargs = {"backend": backend}
        if model is not None:
            kwargs["model"] = model
        if effort is not None:
            kwargs["effort"] = effort
        if max_calls is not None:
            kwargs["max_calls"] = max_calls
        if backend == "api":
            kwargs["options"] = options
        elif backend == "command" and command is not None:
            kwargs["command"] = command
    return {
        "driver": driver,
        "adapter": adapter,
        "backend": backend,
        "model": model,
        "effort": effort,
        "max_calls": max_calls,
        "options": options,
        "command": command,
        "configured": configured,
        "reason": reason,
        "runtime_kwargs": kwargs,
    }


def _unconfigured(reason=None):
    return _result(None, None, None, None, None, None, None, None, False, reason)


def _offline():
    return _result("offline", None, None, None, None, None, None, None, True)


def _explicit_offline(explicit, select):
    if select.get("driver") == "offline":
        return True
    if explicit.get("driver") == "offline":
        return True
    if explicit.get("offline") is True:
        return True
    if explicit.get("backend") == "legacy":
        return True
    # The Web's historical offline marker: ``llm.enabled`` is false.
    if explicit.get("enabled") is False:
        return True
    return False


def _as_bool(value, default=None):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return default


def _resolve_enabled(explicit, saved, env):
    if "enabled" in explicit:
        return bool(_as_bool(explicit["enabled"], True))
    if "enabled" in saved:
        return bool(_as_bool(saved["enabled"], True))
    raw = env.get("LLM_ENABLED")
    if raw is not None and raw != "":
        return bool(_as_bool(raw, True))
    return True


def _max_calls(*values):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _api_options(explicit, saved):
    """The api allow-list for ``LLMRuntimeConfig.from_request``.

    Built only from the explicit request and saved settings; environment defaults
    (base URL, key) are merged by ``from_request`` against ``config.CONFIG``.
    The ``api_key`` is in-memory only and is never persisted by the caller.
    """
    merged = {}
    merged.update(saved or {})
    merged.update(explicit or {})
    keys = ("base_url", "temperature", "reasoning_effort", "reasoning_param",
            "timeout", "max_calls", "model", "enabled", "api_key")
    options = {key: merged[key] for key in keys if merged.get(key) is not None}
    return options or None


def _command_json(value):
    """Normalize a trusted agent command to the JSON string ``create_runtime``
    expects, verifying it is a nonempty JSON array of nonempty strings."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            argv = json.loads(value)
        except (ValueError, TypeError):
            raise DriverResolutionError(
                "Agent command must be a JSON argument array.") from None
    else:
        argv = value
    if (not isinstance(argv, list) or not argv or
            any(not isinstance(x, str) or not x for x in argv)):
        raise DriverResolutionError(
            "Agent command must be a nonempty JSON array of strings.")
    if isinstance(value, str):
        return value
    return json.dumps(argv)


def _connection(saved, select, explicit):
    """A named, locally pre-configured agent connection (trusted config only)."""
    name = _first(select.get("connection"), explicit.get("connection"))
    if not name:
        return None
    connections = saved.get("agent_connections")
    if not isinstance(connections, dict):
        return None
    conn = connections.get(name)
    return conn if isinstance(conn, dict) else None


def _selection(source):
    """Normalize one source's ``driver``/``backend``/``adapter`` fields into a
    ``(driver, adapter)`` selection.

    A concrete ``backend`` implies the driver (``command``/``codex`` -> ``agent``
    with that adapter; ``api`` -> ``api``), so an explicit ``backend="api"`` is
    never shadowed by a saved ``driver="agent"``.  ``legacy`` is a "no usable
    config" marker, never a driver selection, so it maps to ``(None, None)`` and
    is handled by the caller.  ``offline`` is explicit-only (resolved before this
    runs) and is never returned here.
    """
    if not isinstance(source, dict):
        return None, None
    backend = source.get("backend")
    driver = source.get("driver")
    adapter = source.get("adapter")
    if backend in ADAPTERS:
        return "agent", backend
    if backend == "api":
        return "api", None
    if driver in ("api", "agent"):
        return driver, adapter if (driver == "agent" and adapter in ADAPTERS) else None
    return None, None


def resolve_driver(explicit=None, saved=None, env=None, select=None, command=None):
    """Resolve the gameplay driver and its concrete runtime configuration.

    ``explicit`` / ``select`` are what an entry point collected from the caller;
    the Web must never place a ``command`` (an executable argv) in either — it is
    only ever taken from the trusted ``command`` argument, saved settings, or the
    environment.  ``command`` is a JSON argument-array string (terminal only).

    Returns a dict with ``driver`` / ``adapter`` / ``backend`` / ``model`` /
    ``effort`` / ``max_calls`` / ``options`` / ``command`` / ``configured`` /
    ``reason`` and a ready-to-splat ``runtime_kwargs``.
    """
    env = dict(env) if env is not None else app_config.raw_env()
    explicit = dict(explicit) if isinstance(explicit, dict) else {}
    saved = dict(saved) if isinstance(saved, dict) else {}
    select = dict(select) if isinstance(select, dict) else {}

    # 1. Offline is only ever an explicit choice, never inferred.
    if _explicit_offline(explicit, select):
        return _offline()

    # 2. Resolve the driver (and, for agent, the second-layer adapter) by
    # normalizing each source's driver/backend/adapter first, then taking the
    # most explicit source (select > explicit > saved > env).  A source's
    # concrete ``backend`` implies the driver, so an explicit ``backend="api"``
    # is never shadowed by a saved ``driver="agent"``.
    conn = _connection(saved, select, explicit)
    driver = select.get("driver")
    adapter = select.get("adapter")
    if driver is None:
        driver, adapter = _selection(explicit)
    if driver is None:
        driver, adapter = _selection(saved)
    if driver is None:
        env_backend = env.get(_ENV_BACKEND)
        if env_backend in ADAPTERS:
            driver, adapter = "agent", env_backend
        elif env_backend == "api":
            driver, adapter = "api", None
        elif env_backend == "legacy":
            return _unconfigured(
                "saved/environment backend 'legacy' is not an offline selection")

    if driver == "api":
        backend, adapter = "api", None
    elif driver == "agent":
        adapter = adapter or (conn.get("adapter") if conn else None) \
            or saved.get("adapter")
        if adapter not in ADAPTERS:
            return _unconfigured("agent driver requires a command or codex adapter")
        backend = adapter
    elif driver == "offline":
        return _offline()
    elif driver is not None and driver not in DRIVERS:
        return _unconfigured(f"unknown driver {driver!r}")
    else:
        # No driver selection anywhere: infer the backend from any backend
        # marker.  ``legacy`` is a rule-test marker, not an offline selection —
        # saved/env legacy means "no usable model config".
        backend = _first(explicit.get("backend"), saved.get("backend"),
                         env.get(_ENV_BACKEND))
        if backend == "legacy":
            return _unconfigured(
                "saved/environment backend 'legacy' is not an offline selection")
        if backend in ADAPTERS:
            driver, adapter = "agent", backend
        else:
            driver, adapter, backend = "api", None, "api"

    # 3. Resolve the concrete config for the chosen driver.
    if driver == "api":
        model = _first(explicit.get("model"), saved.get("model"), env.get("LLM_MODEL"))
        enabled = _resolve_enabled(explicit, saved, env)
        configured = enabled is not False and bool(model)
        if not configured:
            return _unconfigured(
                "no model configured — choose a model or offline")
        return _result(
            "api", None, "api", model,
            _unified_effort(explicit, saved),
            _max_calls(explicit.get("max_calls"), saved.get("max_calls")),
            _api_options(explicit, saved), None, True)

    if driver == "agent":
        if conn:
            model = _first(explicit.get("model"), conn.get("model"),
                           saved.get("model"), env.get(_ENV_CODEX_MODEL))
            effort = _unified_effort(explicit, conn, saved)
            max_calls = _max_calls(explicit.get("max_calls"), conn.get("max_calls"),
                                   saved.get("max_calls"))
            command_value = _first(conn.get("command"), command,
                                   saved.get("command"), env.get(_ENV_AGENT_COMMAND))
        else:
            model = _first(explicit.get("model"), saved.get("model"),
                           env.get(_ENV_CODEX_MODEL))
            effort = _unified_effort(explicit, saved)
            max_calls = _max_calls(explicit.get("max_calls"), saved.get("max_calls"))
            command_value = _first(command, saved.get("command"),
                                   env.get(_ENV_AGENT_COMMAND))

        if adapter == "command":
            if command_value is None:
                return _unconfigured(
                    "agent command adapter requires a locally configured command")
            try:
                command_json = _command_json(command_value)
            except DriverResolutionError:
                return _unconfigured("agent command is not a valid argument array")
        else:
            command_json = None

        return _result("agent", adapter, backend, model, effort, max_calls,
                       None, command_json, True)

    # Unreachable: every branch above returns.
    return _unconfigured("no driver resolved")


# ---------------------------------------------------------------- save / restore

def driver_from_planner(planner):
    """Derive ``(driver, adapter)`` from a live runtime (or ``("offline", None)``
    when there is no planner — i.e. rule-flow simulation)."""
    if planner is None:
        return "offline", None
    backend = getattr(planner, "backend", None)
    if backend == "api":
        return "api", None
    if backend in ADAPTERS:
        return "agent", backend
    return "api", None


def infer_legacy_driver(planner_snap, campaign_counted):
    """Infer the driver from an old save that has no explicit ``driver`` field.

    ``planner_snap`` is the saved planner snapshot (``None`` for offline games);
    ``campaign_counted`` is the saved ``campaign_counted`` marker.  A
    contradictory combination raises ``ValueError`` rather than guessing.
    """
    if planner_snap is not None:
        backend = planner_snap.get("backend")
        if backend == "api":
            driver, adapter = "api", None
        elif backend in ADAPTERS:
            driver, adapter = "agent", backend
        else:
            raise ValueError(
                f"legacy save: unknown planner backend {backend!r}")
        if campaign_counted is False:
            raise ValueError(
                "legacy save: model/agent driver but marked not counted")
        return driver, adapter
    # No planner: an offline/rule-flow game.  It must never have been counted.
    if campaign_counted is True:
        raise ValueError(
            "legacy save: counted campaign game without a planner")
    return "offline", None


def validate_restore(driver, adapter, campaign_counted, planner):
    """Enforce the save's driver lock against the live runtime on restore.

    The runtime is always re-derived from trusted local config (never the save);
    this only checks the *driver* a restored save claims is still satisfiable,
    and refuses any offline -> counted (or counted -> offline) switch.  A live
    planner without a ``backend`` attribute is treated as a generic api planner
    (some fixtures omit it); an explicit non-matching backend is always refused.
    """
    has_planner = planner is not None
    backend = getattr(planner, "backend", None)

    if driver == "offline":
        if campaign_counted is True:
            raise ValueError(
                "offline save cannot be a counted campaign game")
        if has_planner:
            raise ValueError(
                "offline save but a live model/agent planner is attached")
        return

    if driver == "api":
        if not has_planner:
            raise ValueError("api save but no live planner")
        if backend not in (None, "api"):
            raise ValueError(
                "api save but the live runtime is not an api planner")
        return

    if driver == "agent":
        if adapter not in ADAPTERS:
            raise ValueError("agent save with no adapter")
        if not has_planner:
            raise ValueError("agent save but no live planner")
        if backend not in (None, adapter):
            raise ValueError(
                f"agent({adapter}) save but the live runtime is not that adapter")
        return

    raise ValueError(f"unknown driver {driver!r}")


def restore_runtime_kwargs(driver, adapter, saved=None, env=None, command=None):
    """Reconstruct ``create_runtime`` kwargs for a restore from trusted local
    config — never from the save.

    The save locks ``driver``/``adapter``; the trusted config supplies what the
    save deliberately omits, using the same sources and priority as a fresh
    resolution: an explicit CLI ``command`` > saved settings > environment.

    - ``api``: the endpoint is re-derived from saved settings (so a saved
      local-server URL restores against its own endpoint); the live credential
      (key) still comes from the environment.
    - ``agent``/``codex``: model/effort are re-bound from the snapshot.
    - ``agent``/``command``: the trusted argv comes from ``command`` (explicit)
      > ``saved["command"]`` > a single matching named command connection >
      ``WEREWOLF_AGENT_COMMAND``.

    Returns a kwargs dict to splat into ``create_runtime``, or ``None`` when the
    trusted config cannot satisfy the locked driver (the caller reports "cannot
    resume").
    """
    saved = dict(saved) if isinstance(saved, dict) else {}
    env = dict(env) if env is not None else app_config.raw_env()
    if driver == "api":
        base_url = saved.get("base_url")
        options = {"base_url": base_url} if base_url else None
        return {"backend": "api", "options": options}
    if driver == "agent":
        if adapter == "codex":
            return {"backend": "codex"}
        if adapter == "command":
            command_value = _first(command, saved.get("command"))
            if command_value is None:
                connections = saved.get("agent_connections")
                if isinstance(connections, dict):
                    matches = [conn.get("command") for conn in connections.values()
                               if isinstance(conn, dict)
                               and conn.get("adapter") == "command"
                               and conn.get("command")]
                    if len(matches) == 1:
                        command_value = matches[0]
            if command_value is None:
                command_value = env.get(_ENV_AGENT_COMMAND)
            if command_value is None:
                return None
            try:
                command_json = _command_json(command_value)
            except DriverResolutionError:
                return None
            return {"backend": "command", "command": command_json}
        return None
    return None
