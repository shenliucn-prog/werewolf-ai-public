"""Transport-neutral task supervision, separate from game-step execution.

The session remains the sole owner of flags, pending input and task references.
These stateless operations never serialize state, adjudicate rules, or settle a
campaign. Checkpoint/event callbacks retain their existing transaction ordering.
"""
import asyncio

from .ai.decision_runtime import ModelTurnError


def ensure_task(session):
    if session._game_task_ref is None or session._game_task_ref.done():
        session._game_task_ref = asyncio.create_task(session._game_task())
    return session._game_task_ref


def abandon(session, sentinel):
    session._abandoned = True
    session.finished = True
    session.pending = None
    session._pending_event_no = None
    session.event_q.put_nowait(sentinel)
    if session._game_task_ref is not None and not session._game_task_ref.done():
        session._game_task_ref.cancel()
    session.perf_recorder.flush()


def fault(session, text):
    session.faulted = True
    session.emit({"type": "error", "text": text})


def terminal_state(session):
    if session._abandoned:
        return "abandoned"
    if session.faulted:
        return "faulted"
    if session.finished:
        return "ended"
    if session.pending is not None:
        return "paused"
    return "in_progress"


async def supervise(session, *, locale, sentinel, logger):
    # A same-process retry must clear the transient fault marker too.
    session.faulted = False
    try:
        await session._play()
        session.pending = None
        session._pending_event_no = None
    except ModelTurnError:
        session._fault(
            "Model decision failed, timed out or exceeded budget. The game is paused — fix the connection and rejoin to continue; no offline substitution."
            if locale == "en" else
            "模型决策失败、超时或调用额度耗尽。对局已暂停，请检查连接后重连继续；未切换离线玩家。")
    except Exception:
        logger.exception("Game session failed")
        session._fault(
            "The game paused due to an unexpected error; rejoin to continue or abandon this game."
            if locale == "en" else
            "对局因意外错误暂停；可重连继续，或放弃本局。")
    finally:
        # CancelledError deliberately propagates after cleanup. An explicit
        # abandon must not recreate a save the application is removing.
        session.event_q.put_nowait(sentinel)
        if not session._abandoned:
            session._checkpoint()
