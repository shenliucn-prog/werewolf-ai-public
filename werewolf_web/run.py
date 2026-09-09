"""狼人杀 Web 版 FastAPI/SSE 后端适配器。

游戏核心 ``GameSession`` 已抽出到 ``session.py``；本文件只负责 HTTP 路由、
SSE 事件流、玩家动作转交和静态资源挂载。游戏主循环在独立 task 中运行，通过
队列把事件推给 SSE；玩家输入经 /api/action 被主循环 await。只有显式指定
``llm.enabled=false`` 才跳过模型预检；否则开局前做真实预检，失败则返回 503，
不静默降级、不开局。
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from . import checkpoint
from . import campaign_flow
from . import driver as driver_mod
from . import settings as user_settings
from .campaign import LEVELS
from .ai.llm import LLMClient, LLMRuntimeConfig
from .ai.decision_runtime import ModelTurnError, create_runtime
from .ai.host import HostAgent
from .i18n import board_display, role_name, role_desc, board_role_name
from .casting import random_names, persona_options, CAST_IDS, PLAYER_ID
from .session import GameSession, GameRunner

config.ensure_dirs()
app = FastAPI(title="狼人杀 Web 版")

GAMES: dict[str, "GameSession"] = {}

# Per-game restore locks (§7 single-writer): two concurrent reconnects for the
# same game_id must not each load the checkpoint, each run a model preflight and
# each register their own live instance.  ``restore_game`` double-checks inside
# the lock, so the already-live fast path stays lock-free.
_RESTORE_LOCKS: dict[str, asyncio.Lock] = {}


def _driver_select(body: dict):
    """Non-executable driver/connection selectors the Web may supply.

    The browser may choose WHICH driver / adapter / pre-configured connection to
    use, but never a ``command``/adapter executable — those come from trusted
    local config only (``driver.resolve_driver`` never reads a command from the
    request).
    """
    select = {}
    for key in ("driver", "adapter", "connection"):
        value = body.get(key)
        if isinstance(value, str) and value:
            select[key] = value
    return select


async def restore_game(game_id: str):
    """game_id-keyed restore on startup (§7): rehydrate a game from its
    checkpoint when it is not already live in ``GAMES``.

    Offline games (no planner) restore self-contained.  A model game re-derives
    its runtime from trusted local configuration — never from the save — and is
    refused if the saved endpoint no longer matches the configured credential.
    A missing or corrupt save (or any invalid component) returns ``None`` rather
    than guessing.
    """
    if not game_id:
        return None
    runner = GAMES.get(game_id)
    if runner is not None:
        return runner
    lock = _RESTORE_LOCKS.setdefault(game_id, asyncio.Lock())
    async with lock:
        runner = GAMES.get(game_id)
        if runner is not None:
            return runner
        try:
            path = checkpoint.checkpoint_path(game_id)
            payload = checkpoint.load_checkpoint(path)
        except (ValueError, OSError):
            return None
        if payload.get("session_id") != game_id:
            # A checkpoint must never be restored under a different key.
            return None
        try:
            planner = None
            planner_snap = payload.get("planner")
            if planner_snap is not None:
                # Re-derive the runtime from trusted local config, matching the
                # save's driver/adapter lock — never from the save.  The save
                # omits the agent command argv, so a command-adapter game must
                # re-resolve it from local settings.
                driver = payload.get("driver")
                adapter = payload.get("adapter")
                if driver is None:
                    driver, adapter = driver_mod.infer_legacy_driver(
                        planner_snap, payload.get("campaign_counted"))
                kwargs = driver_mod.restore_runtime_kwargs(
                    driver, adapter, user_settings.load_settings())
                if kwargs is None:
                    return None
                planner = create_runtime(**kwargs)
            # Construct with a deferred preflight, restore first, then reserve and
            # persist the preflight budget unit *before* running the liveness
            # check.  Ordering matters (§7): validate + restore config and budget,
            # persist the preflight reservation, then execute the check — so a
            # crash between the reservation and the check still restores the
            # consumed call, and success leaves ``verified=True`` (not clobbered).
            runner = GameSession(payload.get("board_id", "classic"),
                                 {"enabled": False} if planner is None else None,
                                 session_id=game_id, planner=planner,
                                 checkpoint_path=path, _defer_preflight=True)
            runner.restore(payload)
            if runner.campaign_profile and not campaign_flow.resume(
                    runner.campaign_profile, game_id, runner):
                # abandoned (or reconciled-and-refused): never revive it.
                return None
            if planner is not None:
                planner.reserve()
                runner._checkpoint()
                await asyncio.to_thread(planner.preflight_check)
        except (ValueError, KeyError, TypeError, ModelTurnError):
            return None
        GAMES[game_id] = runner
        return runner


# ---------------- API ----------------
async def _json_object(req: Request) -> dict:
    """Reject malformed input consistently instead of returning a server error."""
    try:
        body = await req.json()
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="Expected a JSON object.") from error
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Expected a JSON object.")
    if "game_id" in body and not isinstance(body["game_id"], str):
        raise HTTPException(status_code=422, detail="game_id must be a string.")
    return body


@app.get("/api/boards")
async def boards(locale: str = "zh-CN"):
    with open(config.BOARDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for board in data["boards"]:
        board.update(board_display(locale, board))
        board["role_labels"] = {key: board_role_name(locale, board, key, data["roles"][key]["cn"])
                                for key in set(board["roles"])}
    for key, meta in data["roles"].items():
        meta["cn"] = role_name(locale, key, meta["cn"])
        meta["desc"] = role_desc(locale, key, meta)
    return data


@app.post("/api/start")
async def start(req: Request):
    body = await _json_object(req)
    board_id = body.get("board_id", "classic")
    game_id = secrets.token_urlsafe(18)
    resolved = driver_mod.resolve_driver(
        explicit=body.get("llm"),
        saved=user_settings.load_settings(),
        select=_driver_select(body),
    )
    if not resolved["configured"]:
        # Never silently start offline and never blindly default to api: report
        # the distinct "unconfigured" state so the UI can guide configuration.
        raise HTTPException(status_code=422, detail=(
            "No model or offline mode configured. Choose a model connection or "
            "offline rule simulation first. / 未配置模型或离线模式。请先配置模型连接，或选择离线规则模拟。"))
    llm = body.get("llm")
    offline = resolved["driver"] == "offline"
    try:
        runner = GameSession(board_id, {"enabled": False} if offline else llm,
                             session_id=game_id,
                             locale=body.get("locale", "zh-CN"), names=body.get("names"),
                             personalities=body.get("personalities"),
                             conjecture=body.get("conjecture", False),
                             player_role=body.get("player_role"), onboarding=True,
                             checkpoint_path=checkpoint.checkpoint_path(game_id))
        # Only explicit offline selection bypasses a real-model preflight.
        # Runtime commands come from trusted local configuration, never HTTP.
        if not offline:
            if runner.conjecture:
                raise ValueError("Model-player conjecture tables are not yet integrated; choose normal mode.")
            planner = create_runtime(**resolved["runtime_kwargs"])
            await asyncio.to_thread(planner.preflight)
            if llm:
                user_settings.save_settings(llm)
            runner.planner = planner
            # The constructor derived driver/adapter from the (then-None) planner
            # as "offline"; re-derive from the resolved driver now that the live
            # runtime is attached so the snapshot/restore lock stays consistent.
            runner.driver, runner.adapter = resolved["driver"], resolved["adapter"]
            runner.llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
            runner.host = HostAgent(runner.llm, locale=runner.engine.locale)
    except ModelTurnError:
        raise HTTPException(status_code=503, detail="LLM connection check failed. No game started and no offline fallback. / 模型预检失败，未开局、未降级。") from None
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    GAMES[game_id] = runner
    return {"ok": True, "game_id": game_id,
            "llm_status": runner._model_status()}


# ---------------- 闯关入口 ----------------


@app.post("/api/campaign/start")
async def campaign_start(req: Request):
    """Start a campaign attempt for a level role: register ``preparing``, deal a
    fixed-board game, then count/settle via the progress hook."""
    body = await _json_object(req)
    profile_id = body.get("profile_id", "default")
    role = body.get("role")
    level = next((l for l in LEVELS if l["role"] == role), None)
    if level is None:
        raise HTTPException(status_code=422, detail="Unknown campaign role.")
    board_id = level["board"]
    game_id = secrets.token_urlsafe(18)
    resolved = driver_mod.resolve_driver(
        explicit=body.get("llm"),
        saved=user_settings.load_settings(),
        select=_driver_select(body),
    )
    if not resolved["configured"]:
        raise HTTPException(status_code=422, detail=(
            "No model or offline mode configured. Choose a model connection or "
            "offline rule simulation first. / 未配置模型或离线模式。请先配置模型连接，或选择离线规则模拟。"))
    llm = body.get("llm")
    offline = resolved["driver"] == "offline"
    try:
        # Offline simulation is an explicit choice and never counts toward
        # campaign progress: no archive registration, no progress hook.
        if not offline:
            campaign_flow.begin_attempt(profile_id, game_id, role, board_id,
                config={"driver": resolved["driver"], "adapter": resolved["adapter"],
                        "backend": resolved["backend"], "model": resolved["model"]})
        runner = GameSession(board_id, {"enabled": False} if offline else llm,
                             session_id=game_id,
                             locale=body.get("locale", "zh-CN"),
                             player_role=role, onboarding=True,
                             checkpoint_path=checkpoint.checkpoint_path(game_id))
        runner.campaign_counted = not offline
        if not offline:
            planner = create_runtime(**resolved["runtime_kwargs"])
            await asyncio.to_thread(planner.preflight)
            if llm:
                user_settings.save_settings(llm)
            runner.planner = planner
            # Keep the durable driver/adapter lock consistent with the resolved
            # driver (the constructor saw planner=None and stored "offline").
            runner.driver, runner.adapter = resolved["driver"], resolved["adapter"]
            runner.llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
            runner.host = HostAgent(runner.llm, locale=runner.engine.locale)
            runner.campaign_profile = profile_id
            runner._checkpoint()                      # initial (uninitialized) save
            runner.progress_hook = campaign_flow.progress_hook(profile_id, game_id)
    except ModelTurnError:
        raise HTTPException(status_code=503, detail="LLM connection check failed.") from None
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    GAMES[game_id] = runner
    return {"ok": True, "game_id": game_id, "role": role, "board_id": board_id,
            "counted": not offline}


@app.get("/api/campaign/status")
async def campaign_status(profile_id: str = "default"):
    """The current campaign level (role/board/goal) and unlocked index."""
    profile = campaign_flow.load_profile(profile_id)
    idx = min(profile["unlocked"], len(LEVELS) - 1)
    level = LEVELS[idx]
    return {"ok": True, "profile_id": profile_id, "unlocked": profile["unlocked"],
            "role": level["role"], "board_id": level["board"],
            "goal_cn": level["goal_cn"], "goal_en": level["goal_en"]}


@app.get("/api/campaign/teaching")
async def campaign_teaching(profile_id: str = "default", game_id: str = ""):
    """The first-entry role teaching for the current campaign level.  Retryable:
    a cache hit returns instantly; a miss generates once (charging budget) and
    persists the reservation before the request.  Never re-registers the attempt."""
    if not game_id:
        raise HTTPException(status_code=422, detail="game_id is required.")
    runner = await restore_game(game_id)
    if not runner:
        raise HTTPException(status_code=404, detail="No such game.")
    role = runner.engine.player_role
    if role not in {level["role"] for level in LEVELS}:
        raise HTTPException(status_code=422, detail="Not a campaign level role.")
    model = getattr(runner.planner, "model", None) or "campaign"
    try:
        event = campaign_flow.generate_teaching(runner, role, model)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"ok": True, "game_id": game_id, "role": role, **event}


@app.post("/api/campaign/review")
async def campaign_review_retry(req: Request):
    """Regenerate a failed post-loss short review (charges budget; never re-settles)."""
    body = await _json_object(req)
    game_id = body.get("game_id", "")
    if not game_id:
        raise HTTPException(status_code=422, detail="game_id is required.")
    runner = await restore_game(game_id)
    if not runner:
        raise HTTPException(status_code=404, detail="No such game.")
    if not runner.campaign_profile:
        raise HTTPException(status_code=404, detail="Not a campaign game.")
    if not runner.finished:
        raise HTTPException(status_code=409, detail="Game is not finished.")
    try:
        event = campaign_flow.generate_campaign_review(runner)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if event is None:
        return {"ok": True, "game_id": game_id, "review": None}
    return {"ok": True, "game_id": game_id, **event}


@app.get("/api/campaign/resume")
async def campaign_resume(profile_id: str = "default", game_id: str = ""):
    """Resume a campaign attempt: reconcile the archive against the save, then
    reattach the progress hook so a finished game still settles."""
    status, _archive = campaign_flow.resume_game(profile_id, game_id)
    if status == "corrupt":
        raise HTTPException(status_code=409, detail="Save is corrupt; cannot resume.")
    if status == "missing":
        raise HTTPException(status_code=404, detail="No such game.")
    runner = await restore_game(game_id)
    if not runner:
        raise HTTPException(status_code=404, detail="No such game.")
    runner.progress_hook = campaign_flow.progress_hook(profile_id, game_id)
    return {"ok": True, "status": status, "view": runner.recovery_view(0)}


@app.get("/api/cast")
async def cast_options(locale: str = "zh-CN"):
    names = random_names(locale)
    return {"players": [{"id": key, "name": names[key], "is_player": key == PLAYER_ID}
                         for key in CAST_IDS], "personalities": persona_options(locale)}


@app.get("/api/stream")
async def stream(game_id: Optional[str] = None, after: int = 0):
    runner = await restore_game(game_id or "")
    if not runner:
        raise HTTPException(status_code=404, detail="No active game. Start a new game.")
    # One live viewer at a time: a concurrent GET must not split the single
    # human seat's events between two consumers.  Reattach (after a previous
    # stream closed) is allowed and resumes at ``after`` with no missing or
    # duplicate events.
    if runner.stream_active:
        raise HTTPException(status_code=409, detail="Game stream already opened.")
    runner.stream_active = True

    async def event_source():
        try:
            async for event in runner.run(after=max(0, after)):
                yield event
        finally:
            runner.stream_active = False

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/api/rejoin")
async def rejoin(game_id: str, last_event_no: int = 0):
    """Player-scoped recovery view (§6): init, own private results, numbered
    public events for catch-up, the pending action, and the live-stream
    hand-off point.  Restores from the checkpoint if the process restarted."""
    runner = await restore_game(game_id)
    if not runner:
        raise HTTPException(status_code=404, detail="No such game.")
    return {"ok": True, "view": runner.recovery_view(max(0, last_event_no))}


@app.post("/api/leave")
async def leave(req: Request):
    """Explicit abandon: stream close is no longer the only way to end a game.

    The on-disk checkpoint is removed too, so an abandoned game (and its secrets)
    cannot be resurrected by a later rejoin."""
    body = await _json_object(req)
    game_id = body.get("game_id", "")
    runner = GAMES.get(game_id)
    if not runner:
        return {"ok": False, "error": "no game"}
    # Settle an explicit abandon *before* deleting the game, so the attempt is
    # recorded (abandoned, or dropped if never started) and can be reconciled.
    if runner.campaign_profile:
        campaign_flow.abandon_game(runner.campaign_profile, game_id)
    runner.abandon()
    GAMES.pop(game_id, None)
    _RESTORE_LOCKS.pop(game_id, None)
    try:
        os.remove(checkpoint.checkpoint_path(game_id))
    except (ValueError, OSError):
        pass
    return {"ok": True}


@app.post("/api/action")
async def action(req: Request):
    body = await _json_object(req)
    runner = GAMES.get(body.get("game_id", ""))
    if not runner:
        return {"ok": False, "error": "no game"}
    body.pop("game_id", None)
    return {"ok": runner.submit(body)}


@app.post("/api/host_chat")
async def host_chat(req: Request):
    """Rules tutoring is deliberately separate from the turn/action queue."""
    body = await _json_object(req)
    runner = GAMES.get(body.get("game_id", ""))
    if not runner:
        return {"ok": False, "error": "no game"}
    question = body.get("question", "")
    if not isinstance(question, str) or not question.strip() or len(question) > 320:
        return {"ok": False, "error": "invalid question"}
    return {"ok": True,
            "reply": runner.answer_question(question)}


@app.get("/api/host_style")
async def host_style():
    if os.path.exists(config.HOST_STYLE_PATH):
        with open(config.HOST_STYLE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@app.get("/api/agent_connections")
async def agent_connections():
    """The names of locally pre-configured agent connections (non-secret
    metadata only).  The browser selects one of these names; it never receives
    (or supplies) a connection's executable ``command``."""
    saved = user_settings.load_settings() or {}
    connections = saved.get("agent_connections")
    if not isinstance(connections, dict):
        return {"connections": []}
    return {"connections": [
        {"name": name, "adapter": conn.get("adapter"), "model": conn.get("model")}
        for name, conn in connections.items()
        if isinstance(conn, dict)
    ]}


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.CONFIG.PORT, log_level="info")


if __name__ == "__main__":
    main()
