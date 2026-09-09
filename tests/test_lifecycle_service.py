"""Task supervisor contracts without an engine, transport or model backend."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from werewolf_web import lifecycle
from werewolf_web.ai.decision_runtime import ModelTurnError


class LifecycleServiceTest(unittest.IsolatedAsyncioTestCase):
    def port(self, play):
        calls = []
        port = SimpleNamespace(
            _game_task_ref=None, _abandoned=False, finished=False, faulted=True,
            pending={"kind": "vote"}, _pending_event_no=12,
            event_q=asyncio.Queue(), perf_recorder=SimpleNamespace(flush=Mock()),
            _play=play, _checkpoint=lambda: calls.append("checkpoint"),
            emit=lambda event: calls.append(event["type"]))
        port._fault = lambda text: lifecycle.fault(port, text)
        sentinel = object()
        async def task():
            await lifecycle.supervise(port, locale="en", sentinel=sentinel, logger=Mock())
        port._game_task = task
        return port, calls, sentinel

    async def test_normal_return_clears_pending_without_adjudicating_winner(self):
        async def play():
            pass
        port, calls, sentinel = self.port(play)
        await port._game_task()
        self.assertFalse(port.faulted)
        self.assertFalse(port.finished)  # only the game executor can end a game
        self.assertIsNone(port.pending)
        self.assertIsNone(port._pending_event_no)
        self.assertIs(port.event_q.get_nowait(), sentinel)
        self.assertEqual(calls, ["checkpoint"])

    async def test_fault_preserves_input_and_checkpoints_after_error(self):
        async def play():
            raise ModelTurnError("failure")
        port, calls, _ = self.port(play)
        await port._game_task()
        self.assertEqual(lifecycle.terminal_state(port), "faulted")
        self.assertEqual(port.pending, {"kind": "vote"})
        self.assertEqual(port._pending_event_no, 12)
        self.assertEqual(calls, ["error", "checkpoint"])

    async def test_ensure_returns_same_running_task(self):
        ready, release = asyncio.Event(), asyncio.Event()
        async def play():
            ready.set()
            await release.wait()
        port, _, _ = self.port(play)
        task = lifecycle.ensure_task(port)
        await ready.wait()
        self.assertIs(lifecycle.ensure_task(port), task)
        release.set()
        await task

    async def test_cancellation_propagates_and_preserves_resume_input(self):
        ready = asyncio.Event()
        async def play():
            ready.set()
            await asyncio.Event().wait()
        port, calls, sentinel = self.port(play)
        task = lifecycle.ensure_task(port)
        await ready.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(port.finished)
        self.assertFalse(port.faulted)
        self.assertEqual(port._pending_event_no, 12)
        self.assertEqual(calls, ["checkpoint"])
        self.assertIs(port.event_q.get_nowait(), sentinel)

    async def test_abandon_cancels_without_recreating_checkpoint(self):
        ready = asyncio.Event()
        async def play():
            ready.set()
            await asyncio.Event().wait()
        port, calls, sentinel = self.port(play)
        task = lifecycle.ensure_task(port)
        await ready.wait()
        lifecycle.abandon(port, sentinel)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(lifecycle.terminal_state(port), "abandoned")
        self.assertIsNone(port.pending)
        self.assertIsNone(port._pending_event_no)
        self.assertEqual(calls, [])
        port.perf_recorder.flush.assert_called_once()

    def test_terminal_precedence_matches_existing_session_contract(self):
        port, _, _ = self.port(None)
        port.finished = True
        self.assertEqual(lifecycle.terminal_state(port), "faulted")
        port.faulted = False
        self.assertEqual(lifecycle.terminal_state(port), "ended")
        port.finished = False
        self.assertEqual(lifecycle.terminal_state(port), "paused")
        port.pending = None
        self.assertEqual(lifecycle.terminal_state(port), "in_progress")
