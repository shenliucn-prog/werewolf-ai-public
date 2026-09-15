"""Whitelisted session snapshot codec and restore validation.

This trusted boundary has access to full logical state. Never use its output as
an observation or HTTP response. Persistence, live connection setup and task
supervision are separate; this module does not perform network requests.
"""
import os
from copy import deepcopy
from dataclasses import replace

from . import config
from . import driver as driver_mod
from .game import engine as eng_mod
from .ai.brain import Speech
from .ai.llm import LLMClient
from .ai.strategic_agent import StrategicNPCAgent
from .public_record import PublicRecord
from .participants import participant_roster
from .conversation import QuestionQueue, InterruptionIntent


def freeze(value):
    """Recursively convert non-JSON game objects for the snapshot."""
    if isinstance(value, Speech):
        return {"__speech__": True, "text": value.text, "claim": value.claim,
                "accuse": value.accuse, "defend": value.defend,
                "question_to": value.question_to,
                "protected_facts": list(value.protected_facts)}
    if isinstance(value, eng_mod.GameEvent):
        return {"__event__": True, **value.to_dict()}
    if isinstance(value, dict):
        return {key: freeze(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [freeze(val) for val in value]
    return value

def thaw(value):
    """Inverse of :meth:`_freeze`."""
    if isinstance(value, dict):
        if value.get("__speech__"):
            return Speech(text=value.get("text", ""), claim=value.get("claim"),
                          accuse=value.get("accuse"), defend=value.get("defend"),
                          question_to=value.get("question_to"),
                          protected_facts=tuple(value.get("protected_facts", [])))
        if value.get("__event__"):
            return eng_mod.GameEvent.from_dict(value)
        return {key: thaw(val) for key, val in value.items()}
    if isinstance(value, list):
        return [thaw(val) for val in value]
    return value

def snapshot(session) -> dict:
    """Full logical-state snapshot (whitelisted; never emitted or stored
    with credentials)."""
    from .recovery import SCHEMA_VERSION
    planner = session.planner
    return {
        "schema_version": SCHEMA_VERSION,
        "board_id": session.engine.board_id,
        "locale": session.engine.locale,
        "session_id": session.session_id,
        "driver": session.driver,
        "adapter": session.adapter,
        "campaign_profile": session.campaign_profile,
        "campaign_counted": session.campaign_counted,
        "campaign_review_state": session.campaign_review_state,
        "conjecture": session.conjecture,
        "onboarding": session.onboarding,
        "dialogue_version": session.dialogue_version,
        "engine": session.engine.snapshot(),
        "agents": {name: agent.snapshot() for name, agent in session.agents.items()},
        "planner": planner.snapshot() if planner is not None and hasattr(planner, "snapshot") else None,
        "llm": session.llm.snapshot(),
        "conjecture_ledger": (session.conjecture_ledger.snapshot()
                              if session.conjecture_ledger is not None else None),
        "public_record": deepcopy(session.public_record.entries),
        "pending": deepcopy(session.pending),
        "speech_events": [[name, session._freeze(sp)] for name, sp in session.speech_events],
        "player_last_speech": session.player_last_speech,
        "triggered": sorted(session._triggered),
        "table_extra_turns": session._table_extra_turns,
        "table_extra_by_name": dict(session._table_extra_by_name),
        "table_pairs": [sorted(pair) for pair in session._table_pairs],
        **session.questions.snapshot_fields(),
        "table_cooldown": session._table_cooldown,
        "last_llm_status": (list(session._last_llm_status)
                            if session._last_llm_status is not None else None),
        "step": session._step,
        "current_step": session._current_step,
        "step_state": session._freeze(session._step_state),
        "decision_no": session._decision_no,
        "decision_log": session._freeze(session.decision_log),
        "finished": session.finished,
        # Event ledger (§5.4 / §6): durable so a process restart re-presents
        # the same numbered transcript with no missing/duplicate events.
        "event_no": session._event_no,
        "events": deepcopy(session._events),
        "pending_event_no": session._pending_event_no,
    }

def _prepare_loop_state(data):
    """Validate and materialize loop values before touching live components."""
    def typed(key, kind, default):
        value = data.get(key, default)
        if type(value) is not kind:
            raise ValueError(f"GameSession.snapshot: invalid {key}")
        return value

    profile = data.get("campaign_profile")
    if profile is not None and not isinstance(profile, str):
        raise ValueError("GameSession.snapshot: campaign_profile must be a string or null")
    try:
        speeches = []
        for row in typed("speech_events", list, []):
            if not isinstance(row, (list, tuple)) or len(row) != 2 or not isinstance(row[0], str):
                raise ValueError("GameSession.snapshot: invalid speech_events")
            speech = thaw(row[1])
            if not isinstance(speech, Speech):
                raise ValueError("GameSession.snapshot: invalid speech_events speech")
            speeches.append((row[0], speech))
        triggered = typed("triggered", list, [])
        if any(type(pos) is not int or not 1 <= pos <= 12 for pos in triggered):
            raise ValueError("GameSession.snapshot: invalid triggered")
        counts = typed("table_extra_by_name", dict, {})
        if any(not isinstance(name, str) or type(count) is not int or count < 0
               for name, count in counts.items()):
            raise ValueError("GameSession.snapshot: invalid table_extra_by_name")
        pairs = typed("table_pairs", list, [])
        if any(not isinstance(pair, (list, tuple)) or
               any(not isinstance(name, str) for name in pair) for pair in pairs):
            raise ValueError("GameSession.snapshot: invalid table_pairs")
        state = {
            "campaign_profile": profile, "speech_events": speeches,
            "_triggered": set(triggered), "_table_extra_by_name": dict(counts),
            "_table_pairs": {frozenset(pair) for pair in pairs},
            "_step_state": thaw(typed("step_state", dict, {})),
            "decision_log": thaw(typed("decision_log", list, [])),
            "player_last_speech": typed("player_last_speech", str, ""),
        }
        for key, dest in (("table_extra_turns", "_table_extra_turns"),
                          ("decision_no", "_decision_no")):
            value = typed(key, int, 0)
            if value < 0:
                raise ValueError(f"GameSession.snapshot: invalid {key}")
            state[dest] = value
        for key, dest in (("conjecture", "conjecture"), ("onboarding", "onboarding"),
                          ("finished", "finished"), ("table_cooldown", "_table_cooldown")):
            state[dest] = typed(key, bool, False)
        version = typed("dialogue_version", int, 0)
        if version not in (0, 1):
            raise ValueError("Unsupported dialogue version")
        state["dialogue_version"] = version
        for key, dest in (("step", "_step"), ("current_step", "_current_step")):
            value = data.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"GameSession.snapshot: invalid {key}")
            state[dest] = value
        pending = data.get("pending")
        if pending is not None and not isinstance(pending, dict):
            raise ValueError("GameSession.snapshot: invalid pending")
        state["pending"] = deepcopy(pending)
        last = data.get("last_llm_status")
        state["_last_llm_status"] = tuple(last) if isinstance(last, list) else None
        return state
    except (TypeError, KeyError) as error:
        raise ValueError("GameSession.snapshot: invalid loop state") from error


def restore(session, snapshot: dict) -> None:
    """Restore full logical state in place (strict, validate-then-apply).

    The session shell (board/seed/session_id/planner) must already exist;
    this fills it from a whitelisted snapshot.  Transient run state — the
    asyncio queues, ``stream_claimed``, ``_events_started`` — is reset, not
    resurrected (see §4.2).

    The restore is atomic: the *whole* snapshot is validated against
    throwaway copies of the live components before any attribute on
    ``self`` is touched, so a corrupt snapshot — however deep the defect —
    raises with the session left unchanged, never half-restored.
    """
    from .recovery import check_version
    check_version(snapshot, "GameSession.snapshot")
    if snapshot.get("offline_choices") is not None and not getattr(session, "offline_choice_mode", False):
        raise ValueError("Resume this choice game with offline_game, not a different driver interface")
    snapshot = deepcopy(snapshot)
    questions = QuestionQueue.from_snapshot(snapshot)
    loop_state = _prepare_loop_state(snapshot)

    # ================= Phase 1: validate (no mutation of ``self``) ======
    board_id = snapshot.get("board_id")
    if not isinstance(board_id, str) or not board_id:
        raise ValueError("GameSession.snapshot: board_id must be a non-empty string")
    session_id = snapshot.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("GameSession.snapshot: session_id must be a non-empty string")
    review_state = snapshot.get("campaign_review_state")
    if review_state not in (None, "done", "unavailable"):
        raise ValueError(
            "GameSession.snapshot: campaign_review_state must be null, 'done' or 'unavailable'")

    planner_snap = snapshot.get("planner")
    if planner_snap is not None:
        if session.planner is None or not hasattr(session.planner, "restore"):
            raise ValueError("GameSession.snapshot: planner snapshot without a live planner")
    elif session.planner is not None:
        raise ValueError("GameSession.snapshot: legacy snapshot but a live planner is attached")

    # Driver lock: infer a legacy save's driver, then enforce it against the
    # live runtime *before* any mutation.  The runtime is always re-derived
    # from trusted local config; this refuses offline<->counted switches and
    # adapter mismatches instead of guessing.
    counted_raw = snapshot.get("campaign_counted")
    if counted_raw is not None and not isinstance(counted_raw, bool):
        raise ValueError("GameSession.snapshot: campaign_counted must be a boolean or null")
    driver = snapshot.get("driver")
    adapter = snapshot.get("adapter")
    if driver is None:
        driver, adapter = driver_mod.infer_legacy_driver(planner_snap, counted_raw)
    if driver not in driver_mod.DRIVERS:
        raise ValueError(f"GameSession.snapshot: unknown driver {driver!r}")
    if adapter is not None and adapter not in driver_mod.ADAPTERS:
        raise ValueError(f"GameSession.snapshot: unknown adapter {adapter!r}")
    driver_mod.validate_restore(driver, adapter, counted_raw, session.planner)

    entries = snapshot.get("public_record")
    if not isinstance(entries, list):
        raise ValueError("GameSession.snapshot: public_record must be an array")

    ledger_snap = snapshot.get("conjecture_ledger")

    agents = snapshot.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("GameSession.snapshot: agents must be an object")
    for name in agents:
        if not isinstance(name, str) or not name:
            raise ValueError("GameSession.snapshot: agent names must be non-empty strings")

    # Event ledger (§5.4 / §6): restored verbatim so reattach after a
    # process restart re-presents the exact numbered transcript.  The
    # contiguous numbering invariant (1..event_no) is checked, not assumed.
    event_no = snapshot.get("event_no", 0)
    if type(event_no) is not int or event_no < 0:
        raise ValueError("GameSession.snapshot: event_no must be a non-negative integer")
    events = snapshot.get("events", [])
    if not isinstance(events, list):
        raise ValueError("GameSession.snapshot: events must be an array")
    if len(events) != event_no:
        raise ValueError("GameSession.snapshot: event ledger length does not match event_no")
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError("GameSession.snapshot: events must be objects")
        if event.get("event_no") != index + 1:
            raise ValueError("GameSession.snapshot: event ledger numbering is not contiguous")
    pending_event_no = snapshot.get("pending_event_no")
    if pending_event_no is not None and (type(pending_event_no) is not int or pending_event_no < 0):
        raise ValueError("GameSession.snapshot: pending_event_no must be an integer or null")

    # Validate every component snapshot by restoring it into a throwaway
    # copy of the live object, so any component defect fires here too.
    probe_engine = deepcopy(session.engine)
    probe_engine.restore(snapshot["engine"])
    participants = participant_roster(session_id, probe_engine.seats.values(), driver, adapter)
    if "table_talk" in snapshot.get("step_state", {}):
        InterruptionIntent.validate(snapshot["step_state"]["table_talk"], session_id, participants, events)

    # The live key is bound to the configured endpoint; a probe client
    # mirrors that endpoint (disabled, so no network/client side effects)
    # and re-runs llm.restore's endpoint-trust + budget checks untouched.
    probe_llm = LLMClient(replace(session.llm.runtime, enabled=False, api_key=""))
    probe_llm.restore(snapshot["llm"])

    probe_planner = None
    if planner_snap is not None:
        probe_planner = deepcopy(session.planner)
        probe_planner.restore(planner_snap)

    probe_public = PublicRecord(probe_engine.locale)
    probe_public.entries = deepcopy(entries)

    probe_ledger = None
    if ledger_snap is not None:
        from .game.conjecture import GameConjectures
        probe_ledger = GameConjectures(probe_engine)
        probe_ledger.restore(ledger_snap)

    memory_dir = os.path.join(config.DATA_DIR, "npc_memory", session_id)
    probe_agents = {}
    for name, agent_snap in agents.items():
        if probe_planner is not None:
            from .ai.model_player import ModelNPCAgent
            probe_agents[name] = ModelNPCAgent.restore_agent(
                agent_snap, probe_engine, probe_llm, probe_planner,
                probe_public, memory_dir=memory_dir)
        else:
            probe_agents[name] = StrategicNPCAgent.restore_agent(
                agent_snap, probe_engine, probe_llm, memory_dir=memory_dir)
        # Validate this lookup here too, not after replacing live components.
        probe_agents[name].participant = participants[probe_agents[name].seat.player_id]

    # ================= Phase 2: apply validated state =================
    # Component restores repeat their probe-validated checks. Loop values below
    # are already materialized; do not add new validation/conversion here.
    session.engine.restore(snapshot["engine"])
    session.llm.restore(snapshot["llm"])
    if planner_snap is not None:
        session.planner.restore(planner_snap)

    session.public_record = PublicRecord(session.engine.locale)
    session.public_record.entries = deepcopy(entries)

    if ledger_snap is not None:
        from .game.conjecture import GameConjectures
        session.conjecture_ledger = GameConjectures(session.engine)
        session.conjecture_ledger.restore(ledger_snap)
    else:
        session.conjecture_ledger = None

    # Rebuild agents side-effect-free (no engine RNG, no match_start),
    # against the restored engine/llm/planner and the restored memory_dir.
    session.agents = {}
    for name, agent_snap in agents.items():
        if session.planner is not None:
            from .ai.model_player import ModelNPCAgent
            session.agents[name] = ModelNPCAgent.restore_agent(
                agent_snap, session.engine, session.llm, session.planner,
                session.public_record, memory_dir=memory_dir,
                recorder=session.perf_recorder)
        else:
            session.agents[name] = StrategicNPCAgent.restore_agent(
                agent_snap, session.engine, session.llm, memory_dir=memory_dir)

    # Session loop state (durable fields only).
    session.session_id = session_id
    session.campaign_counted = counted_raw
    session.campaign_review_state = review_state
    session.driver = driver
    session.adapter = adapter
    session.participants = participants
    for agent in session.agents.values():
        agent.participant = participants[agent.seat.player_id]
    session.memory_dir = memory_dir
    session.__dict__.update(loop_state)
    session.questions = questions
    session._event_no = event_no
    session._events = deepcopy(events)
    session._init_event = next((e for e in session._events if e.get("type") == "init"), None)
    session._pending_event_no = pending_event_no
    # Transient, deliberately not restored (see §4.2).
    session.stream_claimed = False
    session._events_started = False
    session._q = None
    session._event_q = None
    session.stream_active = False
    session._game_task_ref = None
    session.faulted = False
    session.progress_hook = None
    # The restored ledger is already durable and re-presented by the
    # ``events(after)`` catch-up path, not the live queue.  Align the
    # publish cursor to the ledger end so a subsequent ``_flush_publish``
    # hands only *newly* emitted events to the fresh queue — never re-publishes
    # the pre-restart transcript from a stale cursor.
    session._published_upto = len(session._events)
