"""Run real offline rules on Android, with no server or model packages."""
import asyncio
import json
import os
import sys
import time

from werewolf_web.offline_web import WebOfflineSession
from werewolf_web.offline_game import action_choices
from werewolf_web.checkpoint import load_checkpoint


async def pace(seconds=0):
    await asyncio.sleep(0)


def session(directory, locale, restore=False):
    path = os.path.join(directory, "game-" + locale + ".json")
    game = WebOfflineSession(seed=7, locale=locale, session_id="mobile-" + locale,
                             checkpoint_path=path)
    game.memory_dir = os.path.join(directory, "memory")
    if restore:
        game.restore(load_checkpoint(path))
    game._pace = pace
    return game


async def play(game, stop_at_prompt=False):
    count = 0
    game.ensure_game_task()
    await asyncio.sleep(0)
    async for event in game.events():
        count += 1
        if event["type"] == "error":
            raise AssertionError(event)
        if event["type"] != "request" or not game.pending:
            continue
        if event["request_id"] != game._human_request().request_id:
            continue
        if stop_at_prompt and event["kind"] != "ready":
            return {"pending_kind": event["kind"], "request_id": event["request_id"]}
        options = action_choices(game, event["kind"], event["data"])
        chosen = game.auto_choice(event["kind"], event["data"], options)
        assert game.submit_choice(chosen["id"], event["request_id"])
    assert game.finished and not game.faulted
    assert game.planner is None and not game.llm.runtime.enabled
    assert game.campaign_counted is False
    assert not any(m in sys.modules for m in ("httpx", "openai", "fastapi", "uvicorn"))
    return {"winner": game.engine.winner, "days": game.engine.day_count,
            "delivered_events": count, "saved_events": len(game._events)}


async def verify(directory, mode):
    if mode == "prepare":
        game = session(directory, "en")
        # Pause at a saved prompt. asyncio.run cancels the waiting task cleanly;
        # an external force-stop then tests a fresh process, not a mid-write crash.
        return await play(game, stop_at_prompt=True)
    locales = ("en",) if mode == "resume" else ("en", "zh-CN")
    results = {}
    for locale in locales:
        start = time.monotonic()
        game = session(directory, locale, restore=mode == "resume")
        results[locale] = await play(game)
        restored = session(directory, locale, restore=True)
        assert json.loads(json.dumps(restored.snapshot())) == json.loads(json.dumps(game.snapshot()))
        results[locale]["duration_ms"] = round((time.monotonic() - start) * 1000)
        results[locale]["checkpoint_bytes"] = os.path.getsize(game.checkpoint_path)
    return results


def run(directory, mode):
    if mode == "mobile":
        from mobile_smoke import run as mobile_run
        return json.dumps({"mode": "mobile", "results": mobile_run(directory)}, ensure_ascii=False)
    if mode not in ("prepare", "resume", "complete"):
        raise ValueError("Unknown probe mode")
    return json.dumps({"mode": mode, "results": asyncio.run(verify(directory, mode))}, ensure_ascii=False)
