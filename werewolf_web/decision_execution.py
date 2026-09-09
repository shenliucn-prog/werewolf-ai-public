"""Durable model-decision execution, independent of rules and transports.

Session callbacks own the decision ledger and checkpoint schema. This service
preserves reservation-before-request and accepted-result-before-application.
It introduces no separate counters, save state or fallback model policy.
"""
import asyncio

from . import perf
from .actions import bind_decision
from .ai.decision_runtime import ModelTurnError


async def execute(session, locale, call, *args, action=None, **kwargs):
    if session.planner is None:
        return call(*args, **kwargs)
    agent = getattr(call, "__self__", None)
    name = agent.name if agent is not None else "?"
    # The decision identity must name the *concrete action*, not just the
    # step + actor: within one election an agent 上警/发言/退警/投票, and the
    # stone ghost acts twice a night.  A method-name default is unambiguous
    # for speak/vote/table_*; callers that repeat one method per step pass an
    # explicit ``action`` (election_up/election_withdraw/stone_ghost/…).
    act = action if action is not None else getattr(call, "__name__", "call")
    if not isinstance(act, str):
        act = "call"
    slot = f"{session._current_step}:{session._slot_instance()}:{name}:{act}"
    replayed = session._replay_decision(slot)
    if replayed is not None:
        # Committed decision reused verbatim — no new call, no budget.
        return replayed["result"]
    decision = session._open_decision(slot)
    # Perf metadata (privacy-safe: seat position only, never name/role).
    seat_pos = agent.seat.pos if agent is not None and getattr(agent, "seat", None) is not None else None
    backend = getattr(session.planner, "backend", None)
    model = getattr(session.planner, "model", None)
    effort = getattr(session.planner, "effort", None)
    while True:
        memory = getattr(agent, "model_decisions", [])
        checkpoint = len(memory)
        calls_before = getattr(session.planner, "calls", 0)
        session._begin_attempt(decision, calls_before)
        # Reserve the budget *before* the pre-call checkpoint: the external
        # request may still fail or the process may crash, but the consumed
        # attempt must survive a restore.  ``complete()`` no longer reserves.
        reserve = getattr(session.planner, "reserve", None)
        if reserve is not None:
            reserve()
        # Pre-call reservation: state-before-call + attempt are durable
        # before the external request goes out.
        session._checkpoint()
        t0 = perf.now()
        try:
            with bind_decision(session.session_id, decision["decision_no"]):
                result = await asyncio.to_thread(call, *args, **kwargs)
        except ModelTurnError:
            del memory[checkpoint:]
            session._end_attempt(decision, getattr(session.planner, "calls", 0), "error")
            session._checkpoint()
            session.perf_recorder.decision(
                decision_no=decision["decision_no"], step=session._current_step,
            instance=session._slot_instance(), seat=seat_pos,
                kind=act, attempt_no=len(decision["attempts"]), backend=backend,
                model=model, effort=effort, calls_before=calls_before,
                calls_after=getattr(session.planner, "calls", 0), outcome="error",
                dur_ms=perf.elapsed_ms(t0))
            session.emit({"type": "narration", "text": (
                "Model response failed. Game paused without substituting a local player. Retry after checking the connection, or stop. Budget limits still apply."
                if locale == "en" else "模型响应失败，对局已暂停，未替换为离线玩家。检查连接后可重试，或结束本局；调用上限仍有效。")})
            response = await session.ask_player("model_retry", {})
            if not response["retry"]:
                raise ModelTurnError("Player stopped after model failure.") from None
            continue
        session._end_attempt(decision, getattr(session.planner, "calls", 0), "accepted")
        decision["result"] = result
        decision["committed"] = True
        session.perf_recorder.decision(
            decision_no=decision["decision_no"], step=session._current_step,
            instance=session._slot_instance(), seat=seat_pos,
            kind=act, attempt_no=len(decision["attempts"]), backend=backend,
            model=model, effort=effort, calls_before=calls_before,
            calls_after=getattr(session.planner, "calls", 0), outcome="accepted",
            dur_ms=perf.elapsed_ms(t0))
        # Post-result commit: the accepted result is durable before the
        # engine applies it in the calling step.
        session._checkpoint()
        return result
