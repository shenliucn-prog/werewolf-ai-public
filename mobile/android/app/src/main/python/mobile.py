"""Local-only native transport. Rules and durable acceptance belong to the engine.

All engine access stays on one asyncio thread. Kotlin receives a whitelist of
player-visible fields, never a checkpoint or an NPC's belief state.
"""
import asyncio
import copy
import json
import os
import secrets
import threading

from werewolf_web.offline_web import WebOfflineSession
from werewolf_web.offline_game import action_choices
from werewolf_web.offline_cast import CHARACTERS, display_names
from werewolf_web.game.engine import BOARD_MAP, ROLE_META
from werewolf_web.i18n import role_name
from werewolf_web.checkpoint import load_checkpoint


class Controller:
    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, mode=0o700, exist_ok=True)
        self.path = os.path.join(directory, "mobile-game.json")
        self.lock = threading.Lock()
        self.view = {"status": "home", "saved": os.path.isfile(self.path), "events": []}
        self.game = None
        self.consumer = None
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def read(self):
        with self.lock:
            return copy.deepcopy(self.view)

    def update(self, **fields):
        with self.lock:
            self.view.update(fields)

    def request(self, operation, args):
        return asyncio.run_coroutine_threadsafe(self.execute(operation, args), self.loop).result(90)

    async def execute(self, operation, args):
        if operation == "catalog":
            locale = args.get("locale", "zh-CN")
            if locale not in ("zh-CN", "en"):
                raise ValueError("Unsupported locale")
            names = display_names(locale)
            return {"characters": [{"id": c.id, "name": names[c.id],
                        "description": c.description[locale == "en"]} for c in CHARACTERS],
                    "roles": [{"id": r, "name": role_name(locale, r, ROLE_META[r]["cn"])}
                              for r in dict.fromkeys(BOARD_MAP["classic"]["roles"])]}
        if operation == "pause":
            await self.stop()
            self.update(status="paused", saved=os.path.isfile(self.path))
            return self.read()
        if operation == "choose":
            game = self.game
            if not game or not game.submit_choice(args.get("choice_id"), args.get("request_id")):
                return {"accepted": False}
            self.update(pending=None, status="busy")
            # Let ask_player durably commit acceptance before acknowledging.
            await asyncio.sleep(0)
            return {"accepted": True}
        if operation not in ("start", "resume"):
            raise ValueError("Unknown operation")
        await self.stop()
        if operation == "start":
            if os.path.isfile(self.path) and not args.get("replace"):
                raise ValueError("Replacement requires explicit confirmation")
            locale = args.get("locale", "zh-CN")
            role = args.get("role", "random")
            character = args.get("character", "random")
            if locale not in ("en", "zh-CN") or role not in ("random", *BOARD_MAP["classic"]["roles"]):
                raise ValueError("Unsupported setup")
            game = WebOfflineSession(locale=locale, player_role=role, character=character,
                session_id=secrets.token_hex(12), checkpoint_path=self.path)
            game.memory_dir = os.path.join(self.directory, "memory")
            game._checkpoint()
        else:
            data = load_checkpoint(self.path)  # corruption is an error, never a new game
            game = WebOfflineSession(checkpoint_path=self.path,
                character=data["offline_choices"]["character"],
                spectator=data["offline_choices"]["spectator"])
            game.memory_dir = os.path.join(self.directory, "memory")
            game.restore(data)
        self.game = game
        with self.lock:
            self.view = {"status": "busy", "saved": True, "events": [], "pending": None}
        self.refresh()
        self.consumer = asyncio.create_task(self.consume(game))
        return self.read()

    async def stop(self):
        if self.consumer and not self.consumer.done():
            self.consumer.cancel()
            try:
                await self.consumer
            except asyncio.CancelledError:
                pass
        if self.game:
            task = self.game._game_task_ref
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self.game._checkpoint()
        self.consumer = None

    def refresh(self):
        game = self.game
        if not game:
            return
        # Public seats are already filtered by the rules engine.
        fields = {"table": game.engine.public_state(), "finished": game.finished,
                  "locale": game.engine.locale, "game_id": game.session_id}
        if game.engine.seats:
            fields["private"] = game.engine.player_view()
        self.update(**fields)

    async def consume(self, game):
        try:
            async for event in game.events():
                self.refresh()
                if event["type"] == "request":
                    if game.pending and event.get("request_id") == game._human_request().request_id:
                        options = action_choices(game, game.pending["kind"], game.pending["data"])
                        self.update(status="waiting", pending={
                            "kind": game.pending["kind"], "data": game.pending["data"],
                            "request_id": event["request_id"],
                            "choices": [{k: c.get(k) for k in ("id", "group", "label", "suggested", "approach", "consequence")}
                                        for c in options]})
                    continue
                if event["type"] == "error":
                    self.update(status="error", error=event.get("text", "Game paused"))
                if event.get("text") and event["type"] not in ("cursor", "llm_status"):
                    row = {k: event.get(k) for k in ("event_no", "type", "text", "seat", "name", "phase", "day", "night")}
                    with self.lock:
                        if not any(e["event_no"] == row["event_no"] for e in self.view["events"]):
                            self.view["events"].append(row)
                # Yield to commands and let the UI poll between CPU-bound NPC turns.
                await asyncio.sleep(0.02)
            self.refresh()
            if game.finished:
                self.update(status="finished", pending=None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.update(status="error", error=type(error).__name__ + ": " + str(error))


_controller = None
_guard = threading.Lock()


def command(directory, operation, payload="{}"):
    global _controller
    with _guard:
        if _controller is None:
            _controller = Controller(directory)
        if _controller.directory != directory:
            raise ValueError("Runtime directory cannot change")
    if operation == "poll":
        result = _controller.read()
    else:
        result = _controller.request(operation, json.loads(payload))
    return json.dumps(result, ensure_ascii=False)
