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
from .ai.llm import LLMClient, LLMRuntimeConfig
from .ai.decision_runtime import ModelTurnError, create_runtime
from .ai.host import HostAgent
from .i18n import board_display, role_name, role_desc, board_role_name
from .casting import random_names, persona_options, CAST_IDS, PLAYER_ID
from .session import GameSession, GameRunner

config.ensure_dirs()
app = FastAPI(title="狼人杀 Web 版")

GAMES: dict[str, "GameSession"] = {}


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
    try:
        runner = GameSession(board_id, body.get("llm"), session_id=game_id,
                             locale=body.get("locale", "zh-CN"), names=body.get("names"),
                             personalities=body.get("personalities"),
                             conjecture=body.get("conjecture", False),
                             player_role=body.get("player_role"), onboarding=True)
        # Only explicit offline selection bypasses a real-model preflight.
        # Runtime commands come from trusted local configuration, never HTTP.
        offline = isinstance(body.get("llm"), dict) and body["llm"].get("enabled") is False
        if not offline:
            if runner.conjecture:
                raise ValueError("Model-player conjecture tables are not yet integrated; choose normal mode.")
            planner = create_runtime(backend="api" if body.get("llm") else None, options=body.get("llm"))
            await asyncio.to_thread(planner.preflight)
            runner.planner = planner
            runner.llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
            runner.host = HostAgent(runner.llm, locale=runner.engine.locale)
    except ModelTurnError:
        raise HTTPException(status_code=503, detail="LLM connection check failed. No game started and no offline fallback. / 模型预检失败，未开局、未降级。") from None
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    GAMES[game_id] = runner
    return {"ok": True, "game_id": game_id,
            "llm_status": runner._model_status()}


@app.get("/api/cast")
async def cast_options(locale: str = "zh-CN"):
    names = random_names(locale)
    return {"players": [{"id": key, "name": names[key], "is_player": key == PLAYER_ID}
                         for key in CAST_IDS], "personalities": persona_options(locale)}


@app.get("/api/stream")
async def stream(game_id: Optional[str] = None):
    runner = GAMES.get(game_id or "")
    if not runner:
        raise HTTPException(status_code=404, detail="No active game. Start a new game.")
    # Reserve before returning the response: two GETs must never start two
    # game loops or split one player's private events between consumers.
    if runner.stream_claimed or runner.finished:
        raise HTTPException(status_code=409, detail="Game stream already opened; resume is not supported.")
    runner.stream_claimed = True

    async def event_source():
        try:
            async for event in runner.run():
                yield event
        finally:
            GAMES.pop(game_id or "", None)

    return StreamingResponse(event_source(), media_type="text/event-stream")


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


app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.CONFIG.PORT, log_level="info")


if __name__ == "__main__":
    main()
