"""R1 extraction gates: identity, request parity, isolation and restore.

All runtimes are deterministic doubles. No credentials or model calls.
"""
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from unittest.mock import Mock

from werewolf_web.ai import model_context
from werewolf_web.ai.decision_runtime import ModelTurnError, RuntimeBase
from werewolf_web.ai.model_controller import ModelController
from werewolf_web.observations import MODEL_INSTRUCTIONS, ObservationGateway
from werewolf_web.onboarding import introduction
from werewolf_web.participants import participant_roster
from werewolf_web.session import GameSession


class FakeRuntime(RuntimeBase):
    def __init__(self, backend="api"):
        super().__init__("test-model")
        self.backend = backend
        self.verified = True

    def complete(self, request, schema):
        return {key: None for key in schema["properties"]}


class ObservationBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def make_session(self, backend="api", role="civilian"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        session = GameSession("classic", planner=FakeRuntime(backend), seed=7,
                              session_id="observation-test", player_role="guard")
        session.memory_dir = directory.name
        await session._step_setup()
        agent = next(a for a in session.agents.values() if a.seat.role == role)
        return session, agent

    async def test_human_and_all_npcs_have_match_scoped_stable_identity(self):
        session, agent = await self.make_session()
        self.assertEqual(len(session.participants), 12)
        human = session.participants[session.engine.player_seat().player_id]
        self.assertEqual(human.controller, "human")
        self.assertEqual(agent.participant.match_id, session.session_id)
        self.assertEqual(agent.participant.controller, "api")
        before = dict(session.participants)
        agent.seat.name = "new display name"
        self.assertEqual(participant_roster(session.session_id, session.engine.seats.values(), "api"), before)

    async def test_existing_snapshot_reconstructs_identity_without_new_fields(self):
        for backend in ("api", "command", "codex"):
            with self.subTest(backend=backend):
                session, agent = await self.make_session(backend)
                snapshot = json.loads(json.dumps(session.snapshot()))
                self.assertNotIn("participants", snapshot)
                restored = GameSession("classic", planner=FakeRuntime(backend))
                restored.restore(snapshot)
                self.assertEqual(restored.participants, session.participants)
                self.assertEqual(restored.agents[agent.name].participant, agent.participant)
                self.assertEqual(restored.snapshot(), snapshot)

    async def test_undealt_snapshot_has_no_participants(self):
        session = GameSession("classic", {"enabled": False})
        session.restore(session.snapshot())
        self.assertEqual(session.participants, {})

    async def test_duplicate_identity_rejected_before_restore_mutation(self):
        session, _ = await self.make_session()
        before = session.snapshot()
        broken = deepcopy(before)
        seats = broken["engine"]["seats"]
        npcs = [seat for seat in seats if not seat["is_player"]]
        npcs[1]["player_id"] = npcs[0]["player_id"]
        with self.assertRaises(ValueError):
            session.restore(broken)
        self.assertEqual(session.snapshot(), before)

    async def test_request_is_equal_to_pre_extraction_builder(self):
        session, agent = await self.make_session()
        agent.model_decisions = [{"task": "old", "decision": {"target": None}}]
        details = {"candidates": [{"pos": 0, "name": "Peaceful Day"}]}
        # Characterization oracle of the pre-R1 request layout, not the new
        # gateway. Metadata (identity/cutoff) must not alter the model prompt.
        info = model_context.bound_information(asdict(agent.information_set()))
        info["rules"] = introduction(agent.engine, False)
        expected = model_context.fit_request_budget({
            "task": "exile vote", "language": agent.engine.locale, "actor": agent.seat.pos,
            "information": info, "persona": agent.persona,
            "personality_parameters": asdict(agent.style),
            "cognitive_parameters": agent.brain.cognition.to_dict(),
            "public_context": model_context.build_public_context(agent),
            "own_previous_decisions": agent.model_decisions[-model_context.DECISION_MEMORY:],
            "details": details, "instructions": MODEL_INSTRUCTIONS,
        })
        observation = ObservationGateway.for_model(agent, "exile vote", details)
        self.assertEqual(observation.to_request(), expected)

    async def test_other_secrets_do_not_change_civilian_input(self):
        session, agent = await self.make_session()
        before = ObservationGateway.for_model(agent, "public speech", {}).to_request()
        others = [s for s in session.engine.seats.values() if s.pos != agent.seat.pos]
        others[0].role, others[1].role = others[1].role, others[0].role
        session.engine.seer_results = [{"secret": "PRIVATE-CHECK"}]
        session.engine.sg_results = [{"secret": "PRIVATE-SG"}]
        session.engine.grave_results = [{"secret": "PRIVATE-GRAVE"}]
        next(a for a in session.agents.values() if a is not agent).model_decisions.append(
            {"secret": "OTHER-MEMORY"})
        session.public_record.observe({"type": "private", "text": "HUMAN-SECRET"}, 1)
        self.assertEqual(ObservationGateway.for_model(agent, "public speech", {}).to_request(), before)

    async def test_own_authorized_check_remains_visible(self):
        session, agent = await self.make_session(role="seer")
        session.engine.seer_results = [{"night": 1, "target": 3, "is_wolf": True}]
        observation = ObservationGateway.for_model(agent, "public speech", {})
        self.assertEqual(observation.payload["information"]["private"]["seer_results"], session.engine.seer_results)

    async def test_provider_mutation_cannot_modify_own_memory_or_live_details(self):
        _, agent = await self.make_session()
        agent.model_decisions = [{"decision": {"target": 1}}]
        details = {"candidates": [1, 2]}
        observation = ObservationGateway.for_model(agent, "vote", details)
        def mutate(request, schema):
            request["own_previous_decisions"][0]["decision"]["target"] = 99
            request["details"]["candidates"].clear()
            return {"target": None}
        runtime = Mock(complete=mutate)
        controller = ModelController(runtime)
        self.assertFalse(hasattr(controller, "engine"))
        before = observation.to_request()
        controller.decide(observation, {"target": {"type": ["integer", "null"], "enum": [None, 1, 2]}})
        self.assertEqual(observation.to_request(), before)
        self.assertEqual(agent.model_decisions[0]["decision"]["target"], 1)
        self.assertEqual(details["candidates"], [1, 2])

    async def test_wrong_identity_refuses_request(self):
        _, agent = await self.make_session()
        agent.participant = replace(agent.participant, participant_id="someone-else")
        with self.assertRaises(ValueError):
            ObservationGateway.for_model(agent, "vote", {})

    async def test_public_recovery_copy_is_isolated_and_cutoff_is_stable(self):
        session, agent = await self.make_session()
        session.emit({"type": "speech", "name": agent.name, "seat": agent.seat.pos, "text": "Public"})
        cutoff = session._event_no
        session.emit({"type": "private", "text": "SECRET"})
        observation = ObservationGateway.for_model(agent, "vote", {})
        self.assertEqual(observation.public_event_cutoff, cutoff)
        events = session.recovery_view()["public_events"]
        self.assertNotIn("SECRET", json.dumps(events))
        events[-1]["text"] = "changed"
        self.assertEqual(session.public_record.entries[-1]["event"]["text"], "Public")
        self.assertEqual(ObservationGateway.public_events(session.public_record, cutoff), [])

    async def test_all_model_adapters_keep_single_budget_owner(self):
        for backend in ("api", "command", "codex"):
            session, agent = await self.make_session(backend)
            await session._npc_call(agent.vote, [{"pos": 0, "name": "Peaceful Day"}])
            self.assertEqual(session.planner.calls, 1)
            self.assertEqual(agent.model_decisions[-1]["decision"], {"target": None})

    async def test_invalid_response_does_not_commit_private_memory(self):
        _, agent = await self.make_session()
        agent.planner.complete = Mock(return_value={"target": 999})
        with self.assertRaises(ModelTurnError):
            agent.vote([{"pos": 0, "name": "Peaceful Day"}])
        self.assertEqual(agent.model_decisions, [])
