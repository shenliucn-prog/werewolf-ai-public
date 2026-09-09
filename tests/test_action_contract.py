"""Action identity at actual HTTP/terminal and durable session boundaries."""
import asyncio
import contextlib
import io
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

from werewolf_web import checkpoint as cp, chat_game, run
from werewolf_web.actions import ActionRequest, ActionProposal, bind_decision, request_id
from werewolf_web.ai.decision_runtime import ModelTurnError
from werewolf_web.ai.model_controller import ModelController
from werewolf_web.observations import ObservationGateway
from werewolf_web.session import GameSession
from tests.test_observation_boundary import FakeRuntime


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return deepcopy(self.body)


class ActionContractTest(unittest.IsolatedAsyncioTestCase):
    async def make_session(self, planner=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        session = GameSession("classic", {"enabled": False}, seed=7,
                              session_id="action-test", planner=planner)
        session.memory_dir = directory.name
        await session._step_setup()
        return session

    async def prompt(self, session, kind="table_answer", data=None):
        task = asyncio.create_task(session.ask_player(kind, data or {"from": "Alice"}))
        async def cleanup():
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self.addAsyncCleanup(cleanup)
        while True:
            event = await asyncio.wait_for(session.event_q.get(), 2)
            if event["type"] == "request":
                return task, event

    async def post(self, session, **body):
        with patch.dict(run.GAMES, {session.session_id: session}):
            return await run.action(FakeRequest({"game_id": session.session_id, **body}))

    async def test_web_rejects_missing_and_stale_ids_for_same_kind(self):
        session = await self.make_session()
        task, first = await self.prompt(session)
        before = session.snapshot()
        self.assertFalse((await self.post(session, answer="missing ID"))["ok"])
        self.assertEqual(session.snapshot(), before)
        self.assertTrue((await self.post(session, request_id=first["request_id"], answer="first"))["ok"])
        self.assertEqual(await task, {"answer": "first"})
        next_task, second = await self.prompt(session)
        self.assertNotEqual(first["request_id"], second["request_id"])
        before = session.snapshot()
        self.assertFalse((await self.post(session, request_id=first["request_id"], answer="delayed duplicate"))["ok"])
        self.assertEqual(session.snapshot(), before)
        self.assertTrue((await self.post(session, request_id=second["request_id"], skip=True))["ok"])
        self.assertEqual(await next_task, {"skip": True})

    async def test_id_is_match_scoped(self):
        session = await self.make_session()
        _, event = await self.prompt(session)
        other = request_id("other-match", "human", event["event_no"])
        self.assertFalse((await self.post(session, request_id=other, skip=True))["ok"])
        self.assertIsNotNone(session.pending)

    async def test_disk_restore_reuses_pending_id_and_logical_decision(self):
        session = await self.make_session()
        with tempfile.TemporaryDirectory() as directory, patch.object(cp, "CHECKPOINTS_DIR", directory):
            session.checkpoint_path = cp.checkpoint_path(session.session_id)
            task, event = await self.prompt(session)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            saved = cp.load_checkpoint(session.checkpoint_path)
            restored = GameSession("classic", {"enabled": False}, checkpoint_path=session.checkpoint_path)
            restored.restore(saved)
            self.assertEqual(restored.recovery_view()["pending"]["request_id"], event["request_id"])
            number = restored._decision_no
            resumed_task, resumed_event = await self.prompt(restored)
            self.assertEqual(resumed_event["request_id"], event["request_id"])
            self.assertEqual(resumed_event["event_no"], event["event_no"])
            self.assertEqual(restored._decision_no, number)
            self.assertTrue((await self.post(restored, request_id=event["request_id"], skip=True))["ok"])
            await resumed_task
            self.assertEqual(len([d for d in restored.decision_log if d["committed"]]), 1)

    async def test_old_save_gains_same_id_in_recovery_and_catchup_without_rewrite(self):
        session = await self.make_session()
        task, event = await self.prompt(session)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        old = session.snapshot()
        old["events"][-1].pop("request_id")
        old["events"][-1].pop("participant_id")
        restored = GameSession("classic", {"enabled": False})
        restored.restore(old)
        before = restored.snapshot()
        replay = restored._delivery_event(restored._events[-1])
        self.assertEqual(replay["request_id"], restored.recovery_view()["pending"]["request_id"])
        self.assertEqual(replay["request_id"], event["request_id"])
        self.assertEqual(restored.snapshot(), before)

    async def test_terminal_resume_skips_historical_prompts_and_binds_answer(self):
        session = await self.make_session()
        task, event = await self.prompt(session, "table_answer", {"from": "First"})
        session.submit({"skip": True}, request_id=event["request_id"])
        await task
        waiting, current = await self.prompt(session, "table_answer", {"from": "Second"})
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        restored = GameSession("classic", {"enabled": False})
        restored.restore(session.snapshot())
        async def finish():
            await restored.ask_player("table_answer", {"from": "Second"})
        restored._play = finish
        original_submit = restored.submit
        with patch("builtins.input", return_value="恢复回答") as input_mock, \
                patch.object(restored, "submit", wraps=original_submit) as submit_mock, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await asyncio.wait_for(chat_game._repl(restored), 2), 0)
        self.assertEqual(input_mock.call_count, 1)
        self.assertEqual(submit_mock.call_args.kwargs["request_id"], current["request_id"])
        self.assertTrue(submit_mock.call_args.kwargs["require_request_id"])

    async def test_legal_validation_still_applies_to_bound_request(self):
        session = await self.make_session()
        task, event = await self.prompt(session, "vote", {"candidates": [{"pos": 3}]})
        before = session.snapshot()
        self.assertFalse((await self.post(session, request_id=event["request_id"], target=4))["ok"])
        self.assertEqual(session.snapshot(), before)
        self.assertTrue((await self.post(session, request_id=event["request_id"], target=3))["ok"])
        self.assertEqual(await task, {"target": 3})

    async def test_model_context_binding_crosses_thread_and_keeps_retry_identity(self):
        planner = FakeRuntime()
        planner.complete = Mock(side_effect=[ModelTurnError("retry"), {"target": None}])
        session = await self.make_session(planner)
        agent = next(iter(session.agents.values()))
        seen = []
        original = ModelController.propose
        def capture(controller, action, observation):
            seen.append(action)
            return original(controller, action, observation)
        with patch.object(ModelController, "propose", capture):
            task = asyncio.create_task(session._npc_call(agent.vote, [{"pos": 0}]))
            while True:
                event = await asyncio.wait_for(session.event_q.get(), 2)
                if event.get("kind") == "model_retry":
                    break
            self.assertTrue((await self.post(session, request_id=event["request_id"], retry=True))["ok"])
            await asyncio.wait_for(task, 2)
        self.assertEqual(len(seen), 2)
        self.assertIsNotNone(seen[0].request_id)
        self.assertEqual(seen[0].request_id, seen[1].request_id)
        self.assertEqual(seen[0].participant, agent.participant)
        self.assertEqual(planner.calls, 2)
        self.assertEqual(len(agent.model_decisions), 1)
        # No leaked ambient binding after returning to a direct adapter call.
        observation = ObservationGateway.for_model(agent, "vote", {})
        self.assertIsNone(ActionRequest.model(observation, {}).request_id)

    async def test_wrong_participant_proposal_and_cross_match_binding_fail(self):
        session = await self.make_session(FakeRuntime())
        agent = next(iter(session.agents.values()))
        observation = ObservationGateway.for_model(agent, "vote", {})
        action = ActionRequest.model(observation, {})
        with self.assertRaises(ValueError):
            action.accept(ActionProposal(action.request_id,
                replace(action.participant, participant_id="other"), {}))
        with bind_decision("other-match", 1), self.assertRaises(ValueError):
            ActionRequest.model(observation, {})

    async def test_failed_request_checkpoint_does_not_publish_prompt(self):
        session = await self.make_session()
        while not session.event_q.empty():
            session.event_q.get_nowait()
        with patch.object(session, "_checkpoint", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                await session.ask_player("table_answer", {"from": "Alice"})
        self.assertTrue(session.event_q.empty())
