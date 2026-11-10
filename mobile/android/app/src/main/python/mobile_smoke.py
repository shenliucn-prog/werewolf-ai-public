"""Synthetic Android acceptance through the same native command boundary."""
import json
import os
import time
from mobile import Controller
from werewolf_web.offline_game import action_choices


def run(directory):
    controller = Controller(os.path.join(directory, "test-native"))
    started = time.monotonic()
    actions = 0
    resumed = False
    try:
        controller.request("start", {"locale": "zh-CN", "role": "civilian", "replace": True})
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            view = controller.read()
            if view["status"] == "error":
                raise AssertionError(view.get("error"))
            if view["status"] == "finished":
                assert view["finished"]
                numbers = [e["event_no"] for e in view["events"]]
                assert len(numbers) == len(set(numbers))
                return {"winner": view["table"]["winner"], "days": view["table"]["day"],
                        "actions": actions, "resumed_prompt": resumed, "events": len(numbers),
                        "duration_ms": round((time.monotonic() - started) * 1000)}
            if view["status"] != "waiting":
                time.sleep(.02)
                continue
            pending = view["pending"]
            if actions == 1 and not resumed:
                controller.request("pause", {})
                controller.request("resume", {})
                while controller.read()["status"] == "busy":
                    if time.monotonic() > deadline:
                        raise AssertionError("Resume timed out")
                    time.sleep(.02)
                assert controller.read()["pending"]["request_id"] == pending["request_id"]
                resumed = True
            for seat in view["table"]["seats"]:
                assert "role" not in seat and "is_wolf" not in seat
            game = controller.game
            choices = action_choices(game, pending["kind"], pending["data"])
            choice = game.auto_choice(pending["kind"], pending["data"], choices)
            result = controller.request("choose", {"request_id": pending["request_id"], "choice_id": choice["id"]})
            assert result["accepted"]
            actions += 1
        raise AssertionError("Native protocol full game timed out")
    finally:
        controller.request("pause", {})
        controller.loop.call_soon_threadsafe(controller.loop.stop)
        controller.thread.join(5)
        controller.loop.close()
