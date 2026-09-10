"""Public Web transport uses the same offline game and durable decisions."""
import asyncio
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from werewolf_web import run, checkpoint
from werewolf_web.offline_web import WebOfflineSession


class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return deepcopy(self.body)


class OfflineWebTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(checkpoint, "CHECKPOINTS_DIR", self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.games = patch.object(run, "GAMES", {})
        self.games.start()
        self.addCleanup(self.games.stop)

    async def test_start_requires_explicit_offline_and_rejects_injected_settings(self):
        for body in ({}, {"offline_confirmed": 1},
                     {"offline_confirmed": True, "command": ["unsafe"]},
                     {"offline_confirmed": True, "spectator": True, "player_role": "seer"}):
            with self.subTest(body=body), self.assertRaises(HTTPException):
                await run.offline_start(Request(body))
        self.assertEqual(run.GAMES, {})

    async def test_cast_has_twelve_localized_characters(self):
        for locale in ("en", "zh-CN"):
            result = await run.offline_cast(locale)
            self.assertEqual(len(result["characters"]), 12)
            self.assertEqual(len({c["id"] for c in result["characters"]}), 12)

    async def test_real_entry_restores_undealt_offline_without_model(self):
        started = await run.offline_start(Request({"offline_confirmed": True}))
        self.assertFalse(started["counted"])
        game_id = started["game_id"]
        run.GAMES.pop(game_id)
        with patch.object(run, "create_runtime", side_effect=AssertionError("No model")):
            restored = await run.restore_game(game_id)
        self.assertIsInstance(restored, WebOfflineSession)
        self.assertEqual(restored.driver, "offline")
        self.assertFalse(restored.engine.seats)

    async def test_action_uses_menu_id_and_rejects_forgery_and_duplicate(self):
        started = await run.offline_start(Request({"offline_confirmed": True}))
        session = run.GAMES[started["game_id"]]
        await session._step_setup()
        task = asyncio.create_task(session.ask_player("speech", {}))
        try:
            await asyncio.sleep(0)
            view = session.recovery_view()
            pending = view["pending"]
            option = pending["choices"][0]
            self.assertEqual(set(option), {"id", "group", "label"})
            body = {"game_id": session.session_id, "request_id": pending["request_id"],
                    "choice_id": option["id"]}
            self.assertFalse((await run.action(Request({**body, "offline_speech": {}})))["ok"])
            self.assertFalse((await run.action(Request({**body, "request_id": "stale"})))["ok"])
            self.assertTrue((await run.action(Request(body)))["ok"])
            self.assertFalse((await run.action(Request(body)))["ok"])
            await task
        finally:
            if not task.done():
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_spectator_finishes_with_only_ready_and_never_receives_secrets(self):
        session = WebOfflineSession(spectator=True, seed=3, player_role="seer")
        delivered = []
        async def consume():
            async for event in session.events():
                delivered.append(event)
                if event["type"] == "request":
                    self.assertEqual(event["kind"], "ready")
                    self.assertTrue(session.submit_choice(event["choices"][0]["id"], event["request_id"]))
        await asyncio.wait_for(consume(), 30)
        self.assertTrue(session.finished)
        self.assertFalse(session.faulted)
        self.assertFalse(any(e["type"] == "private" for e in delivered))
        init = next(e for e in delivered if e["type"] == "init")
        self.assertIsNone(init["player"])
        self.assertFalse(any(s["is_player"] for s in init["state"]["seats"]))
        original = next(e for e in session._events if e["type"] == "init")
        self.assertIsNotNone(original["player"])
        view = session.recovery_view()
        self.assertIsNone(view["private"])
        self.assertEqual(view["private_events"], [])
        self.assertIsNone(view["init"]["player"])
