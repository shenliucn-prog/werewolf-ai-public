"""Whitelisted snapshot/restore and the secrecy boundary (RECOVERY_DESIGN.md §8.2).

Three invariants are exercised across every stateful component:

1. round-trip ``snapshot -> restore`` yields a byte-identical ``public_state``
   and an identical RNG state (engine drives the deal; the brain RNG evolves
   independently and must be stored);
2. a snapshot never contains ``api_key``, ``argv``, liveness flags, or any
   transient run field;
3. restore refuses an unknown schema version.
"""
import json
import random
import sys
import tempfile
import unittest
from dataclasses import replace

from werewolf_web.ai.affect import MatchState
from werewolf_web.ai.brain import Speech
from werewolf_web.ai.codex_player import CodexPlayerRuntime
from werewolf_web.ai.decision_runtime import (
    APIPlayerRuntime,
    CommandPlayerRuntime,
)
from werewolf_web.ai.growth import CognitiveProfile
from werewolf_web.ai.llm import LLMClient, LLMRuntimeConfig
from werewolf_web.ai.model_player import ModelNPCAgent
from werewolf_web.ai.strategic_agent import StrategicNPCAgent
from werewolf_web.game.conjecture import GameConjectures
from werewolf_web.game.engine import GameEngine
from werewolf_web.public_record import PublicRecord
from werewolf_web.recovery import SCHEMA_VERSION, check_version

FORBIDDEN_KEYS = {
    "api_key", "argv", "verified", "_client", "llm", "q", "pending",
    "agents", "planner", "password", "token",
}


def walk_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_keys(item)


def assert_no_forbidden_keys(test, snapshot):
    present = sorted(set(walk_keys(snapshot)) & FORBIDDEN_KEYS)
    test.assertEqual(present, [], f"forbidden keys present: {present}")


class EngineSnapshotTest(unittest.TestCase):
    def make_advanced_engine(self):
        engine = GameEngine("classic", seed=42)
        engine.setup()
        victim = next(s for s in engine.seats.values() if not s.is_wolf)
        engine.start_night()
        engine.resolve_night({"wolves": {"target": victim.pos}})
        engine.start_day()
        speaker = engine.alive_seats()[0]
        engine.record_speech(speaker.pos, "我先听发言。")
        exiled = engine.alive_seats()[-1]
        voter = engine.alive_seats()[0]
        engine.resolve_vote({voter.pos: exiled.pos}, exiled.pos)
        return engine

    def test_round_trip_byte_identical_public_state_and_rng(self):
        engine = self.make_advanced_engine()
        snapshot = engine.snapshot()

        restored = GameEngine("classic", seed=1)
        restored.restore(snapshot)

        self.assertEqual(
            json.dumps(engine.public_state(), sort_keys=True, ensure_ascii=False),
            json.dumps(restored.public_state(), sort_keys=True, ensure_ascii=False),
        )
        self.assertEqual(engine.rng.getstate(), restored.rng.getstate())
        # Identity mapping must survive: same player_id -> role, seat order.
        self.assertEqual(
            {pos: seat.role for pos, seat in engine.seats.items()},
            {pos: seat.role for pos, seat in restored.seats.items()},
        )
        self.assertEqual(engine.history[-1].type, restored.history[-1].type)

    def test_snapshot_has_no_secrets_or_transient_fields(self):
        engine = self.make_advanced_engine()
        assert_no_forbidden_keys(self, engine.snapshot())

    def test_unknown_schema_version_is_rejected(self):
        engine = self.make_advanced_engine()
        snapshot = engine.snapshot()
        snapshot["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            engine.restore(snapshot)


class BrainSnapshotTest(unittest.TestCase):
    def make_agent(self, engine):
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
        return agent

    def test_brain_round_trip_preserves_private_state_and_rng(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        agent = self.make_agent(engine)
        # Exercise a few private-state mutations.
        speech = Speech(text="我怀疑你", claim="seer", accuse=agent.name)
        agent.brain.observe_speech(1, "someone", speech, "我怀疑你")
        agent.brain.gut_of("someone")
        agent.reasoning.append("[D1] trace")

        snapshot = agent.snapshot()
        restored = self.make_agent(engine)
        restored.restore(snapshot)

        self.assertEqual(agent.brain.rng.getstate(), restored.brain.rng.getstate())
        self.assertEqual(agent.brain.sus, restored.brain.sus)
        self.assertEqual(agent.brain.claims, restored.brain.claims)
        self.assertEqual(agent.brain.gut, restored.brain.gut)
        self.assertEqual(agent.brain.wolf_strategy, restored.brain.wolf_strategy)
        self.assertEqual(agent.reasoning, restored.reasoning)

    def test_brain_snapshot_has_no_transient_fields(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        agent = self.make_agent(engine)
        assert_no_forbidden_keys(self, agent.snapshot())

    def test_unknown_schema_version_is_rejected(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        agent = self.make_agent(engine)
        snapshot = agent.snapshot()
        snapshot["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            agent.restore(snapshot)


class ModelAgentSnapshotTest(unittest.TestCase):
    def test_model_decisions_round_trip(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        planner = CodexPlayerRuntime()
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = ModelNPCAgent(
                seat.name, engine, llm, memory_dir=memory_dir,
                planner=planner, public_record=PublicRecord(engine.locale))
            agent.model_decisions.append(
                {"day": 1, "night": 1, "task": "exile vote", "decision": {"target": 3}})
            snapshot = agent.snapshot()
            restored = ModelNPCAgent(
                seat.name, engine, llm, memory_dir=memory_dir,
                planner=planner, public_record=PublicRecord(engine.locale))
            restored.restore(snapshot)

        self.assertEqual(agent.model_decisions, restored.model_decisions)
        self.assertEqual(agent.brain.rng.getstate(), restored.brain.rng.getstate())


class RuntimeSnapshotTest(unittest.TestCase):
    def config(self, **kwargs):
        return replace(
            LLMRuntimeConfig(True, "http://local.example/v1", "", "test-model", 0.7, 2, 5),
            **kwargs)

    def test_api_runtime_round_trip_and_never_stores_key(self):
        runtime = APIPlayerRuntime(self.config(api_key="CANARY", model="m"))
        runtime.calls = 3
        snapshot = runtime.snapshot()

        self.assertNotIn("api_key", json.dumps(snapshot))
        self.assertNotIn("CANARY", json.dumps(snapshot))
        assert_no_forbidden_keys(self, snapshot)

        restored = APIPlayerRuntime(self.config(api_key="NEWKEY", model="x"))
        restored.restore(snapshot)
        self.assertEqual(restored.calls, 3)
        self.assertEqual(restored.model, "m")
        self.assertEqual(restored.config.api_key, "NEWKEY")  # credential preserved, not restored
        self.assertFalse(restored.verified)  # liveness never trusted from a save

    def test_command_runtime_never_stores_argv(self):
        runtime = CommandPlayerRuntime([sys.executable, "-c", "pass"], model="host-agent")
        snapshot = runtime.snapshot()
        self.assertNotIn("argv", json.dumps(snapshot))

        restored = CommandPlayerRuntime([sys.executable, "-c", "pass"], model="host-agent")
        restored.restore(snapshot)
        self.assertEqual(restored.argv, runtime.argv)

    def test_codex_runtime_round_trip_and_secrecy(self):
        runtime = CodexPlayerRuntime(model="gpt-5.6-terra", effort="low")
        runtime.calls = 5
        snapshot = runtime.snapshot()
        assert_no_forbidden_keys(self, snapshot)

        restored = CodexPlayerRuntime()
        restored.restore(snapshot)
        self.assertEqual(restored.calls, 5)
        self.assertEqual(restored.model, "gpt-5.6-terra")
        self.assertEqual(restored.effort, "low")
        self.assertFalse(restored.verified)

    def test_restore_rejects_backend_mismatch(self):
        api_snapshot = APIPlayerRuntime(self.config()).snapshot()
        with self.assertRaises(ValueError):
            CommandPlayerRuntime([sys.executable, "-c", "pass"]).restore(api_snapshot)

    def test_unknown_schema_version_is_rejected(self):
        snapshot = CodexPlayerRuntime().snapshot()
        snapshot["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            CodexPlayerRuntime().restore(snapshot)


class LLMClientSnapshotTest(unittest.TestCase):
    def test_never_stores_api_key_and_round_trips(self):
        client = LLMClient(LLMRuntimeConfig.from_request(
            {"enabled": True, "api_key": "TOPSECRET", "model": "m"}))
        client.calls = 4
        client.failures = 1
        snapshot = client.snapshot()
        self.assertNotIn("api_key", json.dumps(snapshot))
        self.assertNotIn("TOPSECRET", json.dumps(snapshot))
        assert_no_forbidden_keys(self, snapshot)

        restored = LLMClient(LLMRuntimeConfig.from_request(
            {"enabled": True, "api_key": "OTHERKEY", "model": "x"}))
        restored.restore(snapshot)
        self.assertEqual(restored.calls, 4)
        self.assertEqual(restored.failures, 1)
        self.assertEqual(restored.runtime.api_key, "OTHERKEY")

    def test_unknown_schema_version_is_rejected(self):
        client = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        snapshot = client.snapshot()
        snapshot["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            client.restore(snapshot)


class MatchStateAndCognitionSnapshotTest(unittest.TestCase):
    def test_match_state_round_trip(self):
        state = MatchState.start(random.Random(1))
        state.react("accused")
        restored = MatchState.restore(state.snapshot())
        self.assertEqual(state.snapshot(), restored.snapshot())

    def test_cognition_round_trip(self):
        class StyleStub:
            logic = 0.7
            aggression = 0.5
            bluff = 0.4
        profile = CognitiveProfile.from_persona({}, StyleStub())
        restored = CognitiveProfile.restore(profile.snapshot())
        self.assertEqual(profile.to_dict(), restored.to_dict())

    def test_unknown_schema_version_is_rejected(self):
        state = MatchState.start(random.Random(1))
        snapshot = state.snapshot()
        snapshot["schema_version"] = SCHEMA_VERSION + 1
        with self.assertRaises(ValueError):
            MatchState.restore(snapshot)


class ConjectureSnapshotTest(unittest.TestCase):
    def test_round_trip(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        ledger = GameConjectures(engine)
        ledger.private["x"] = []
        snapshot = ledger.snapshot()

        restored = GameConjectures(engine)
        restored.restore(snapshot)
        self.assertEqual(ledger.roster, restored.roster)
        self.assertEqual(ledger.options, restored.options)
        self.assertEqual(ledger.labels, restored.labels)


class SchemaVersionStrictnessTest(unittest.TestCase):
    def test_bool_and_non_integer_versions_are_rejected(self):
        for bad in (True, 1.0, "1", None):
            with self.assertRaises(ValueError):
                check_version({"schema_version": bad}, "snapshot")

    def test_engine_rejects_true_schema_version(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        snapshot = engine.snapshot()
        snapshot["schema_version"] = True
        with self.assertRaises(ValueError):
            engine.restore(snapshot)


class BudgetAndAtomicityTest(unittest.TestCase):
    def config(self, **kwargs):
        return replace(
            LLMRuntimeConfig(True, "http://local.example/v1", "", "test-model", 0.7, 2, 5),
            **kwargs)

    def test_api_negative_calls_rejected_without_partial_mutation(self):
        runtime = APIPlayerRuntime(self.config(api_key="K", model="orig"))
        runtime.calls = 2
        snapshot = runtime.snapshot()
        snapshot["calls"] = -100
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)
        self.assertEqual(runtime.calls, 2)
        self.assertEqual(runtime.config.model, "orig")
        self.assertEqual(runtime.config.api_key, "K")
        self.assertFalse(runtime.verified)

    def test_codex_negative_calls_rejected_without_partial_mutation(self):
        runtime = CodexPlayerRuntime(model="m", effort="low", max_calls=5)
        runtime.calls = 3
        snapshot = runtime.snapshot()
        snapshot["calls"] = -100
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)
        self.assertEqual(runtime.calls, 3)
        self.assertEqual(runtime.model, "m")

    def test_calls_exceeding_max_calls_rejected(self):
        runtime = CodexPlayerRuntime(model="m", effort="low", max_calls=5)
        snapshot = runtime.snapshot()
        snapshot["calls"] = 6
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)

    def test_api_restore_rejects_endpoint_mismatch_and_keeps_credential(self):
        runtime = APIPlayerRuntime(self.config(api_key="CANARY", model="orig"))
        snapshot = runtime.snapshot()
        snapshot["base_url"] = "https://evil.example/v1"
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)
        # Nothing was re-bound: credential, endpoint, and model are untouched.
        self.assertEqual(runtime.config.api_key, "CANARY")
        self.assertEqual(runtime.config.base_url, "http://local.example/v1")
        self.assertEqual(runtime.config.model, "orig")
        self.assertEqual(runtime.calls, 0)

    def test_llm_restore_rejects_endpoint_mismatch_and_keeps_key(self):
        client = LLMClient(LLMRuntimeConfig.from_request(
            {"enabled": True, "api_key": "TOPSECRET", "model": "m"}))
        original_url = client.runtime.base_url
        snapshot = client.snapshot()
        snapshot["config"]["base_url"] = "https://evil.example/v1"
        with self.assertRaises(ValueError):
            client.restore(snapshot)
        self.assertEqual(client.runtime.api_key, "TOPSECRET")
        self.assertEqual(client.runtime.base_url, original_url)
        self.assertEqual(client.runtime.model, "m")


class SnapshotIndependenceTest(unittest.TestCase):
    def _model_agent(self, engine, memory_dir):
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        planner = CodexPlayerRuntime()
        return ModelNPCAgent(
            seat.name, engine, llm, memory_dir=memory_dir,
            planner=planner, public_record=PublicRecord(engine.locale))

    def test_model_decisions_are_independent_both_directions(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = self._model_agent(engine, memory_dir)
            agent.model_decisions.append(
                {"day": 1, "night": 1, "task": "exile vote",
                 "decision": {"target": 3, "nested": {"x": [1, 2]}}})
            snapshot = agent.snapshot()

            # Mutating the live decision must not change the snapshot.
            agent.model_decisions[0]["decision"]["target"] = 8
            agent.model_decisions[0]["decision"]["nested"]["x"].append(99)
            self.assertEqual(snapshot["model_decisions"][0]["decision"]["target"], 3)
            self.assertEqual(
                snapshot["model_decisions"][0]["decision"]["nested"]["x"], [1, 2])

            # Restore must not share references with the snapshot.
            a1 = self._model_agent(engine, memory_dir)
            a2 = self._model_agent(engine, memory_dir)
            a1.restore(snapshot)
            a2.restore(snapshot)
            snapshot["model_decisions"][0]["decision"]["target"] = 999
            self.assertEqual(a1.model_decisions[0]["decision"]["target"], 3)
            a1.model_decisions[0]["decision"]["target"] = 555
            self.assertEqual(a2.model_decisions[0]["decision"]["target"], 3)

    def test_brain_snapshot_is_deeply_independent(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
            agent.brain._bluff_checks = {
                1: {"night": 1, "target": 2, "name": "x", "result": "wolf"}}
            snapshot = agent.snapshot()
            agent.brain._bluff_checks[1]["target"] = 99
            self.assertEqual(
                snapshot["brain"]["bluff_checks"]["1"]["target"], 2)


class JsonRoundTripTest(unittest.TestCase):
    def test_engine_snapshot_survives_json_round_trip(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        blob = json.dumps(engine.snapshot(), ensure_ascii=False)

        restored = GameEngine("classic", seed=1)
        restored.restore(json.loads(blob))

        self.assertEqual(
            json.dumps(engine.public_state(), sort_keys=True, ensure_ascii=False),
            json.dumps(restored.public_state(), sort_keys=True, ensure_ascii=False))
        self.assertEqual(engine.rng.getstate(), restored.rng.getstate())

    def test_brain_snapshot_survives_json_round_trip(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
            agent.brain.observe_speech(
                1, "someone", Speech(text="我怀疑你", claim="seer"), "我怀疑你")
            blob = json.dumps(agent.snapshot(), ensure_ascii=False)

            restored = StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
            restored.restore(json.loads(blob))

            self.assertEqual(agent.brain.rng.getstate(), restored.brain.rng.getstate())
            self.assertEqual(agent.brain.claims, restored.brain.claims)
            self.assertEqual(agent.reasoning, restored.reasoning)

    def test_runtime_and_match_state_survive_json_round_trip(self):
        cfg = LLMRuntimeConfig(True, "http://local.example/v1", "K", "m", 0.7, 2, 5)
        runtime = APIPlayerRuntime(cfg)
        runtime.calls = 3
        restored = APIPlayerRuntime(cfg)
        restored.restore(json.loads(json.dumps(runtime.snapshot())))
        self.assertEqual(restored.calls, 3)
        self.assertEqual(restored.model, "m")

        state = MatchState.start(random.Random(1))
        state.react("accused")
        restored_state = MatchState.restore(json.loads(json.dumps(state.snapshot())))
        self.assertEqual(state.snapshot(), restored_state.snapshot())


class FullRecoveryEquivalenceTest(unittest.TestCase):
    def test_engine_and_all_npcs_restore_equivalently_without_engine_side_effects(self):
        engine = GameEngine("classic", seed=11)
        engine.setup()
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        with tempfile.TemporaryDirectory() as memory_dir:
            agents = {
                seat.name: StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
                for seat in engine.seats.values() if not seat.is_player
            }
            first = next(iter(agents.values()))
            first.brain.observe_speech(
                1, "someone", Speech(text="我怀疑你", claim="seer"), "我怀疑你")
            first.brain.gut_of("someone")
            first.reasoning.append("[D1] trace")

            engine_blob = json.dumps(engine.snapshot(), ensure_ascii=False)
            agent_blobs = {
                name: json.dumps(agent.snapshot(), ensure_ascii=False)
                for name, agent in agents.items()
            }

            restored_engine = GameEngine("classic", seed=1)
            restored_engine.restore(json.loads(engine_blob))
            rng_before = restored_engine.rng.getstate()
            history_before = len(restored_engine.history)

            restored_agents = {
                name: StrategicNPCAgent.restore_agent(
                    json.loads(blob), restored_engine, llm, memory_dir=memory_dir)
                for name, blob in agent_blobs.items()
            }

            # Rebuilding NPCs must not consume engine RNG or append history.
            self.assertEqual(restored_engine.rng.getstate(), rng_before)
            self.assertEqual(len(restored_engine.history), history_before)

            # Public state and identity are byte-identical.
            self.assertEqual(
                json.dumps(engine.public_state(), sort_keys=True, ensure_ascii=False),
                json.dumps(restored_engine.public_state(), sort_keys=True, ensure_ascii=False))

            # Each restored brain matches its original, including private RNG.
            for name, agent in agents.items():
                restored = restored_agents[name]
                self.assertEqual(agent.brain.rng.getstate(), restored.brain.rng.getstate())
                self.assertEqual(agent.brain.sus, restored.brain.sus)
                self.assertEqual(agent.brain.claims, restored.brain.claims)
                self.assertEqual(agent.brain.gut, restored.brain.gut)
                self.assertEqual(agent.reasoning, restored.reasoning)
                self.assertEqual(agent.seat.role, restored.seat.role)
                self.assertEqual(agent.is_wolf, restored.is_wolf)


class StrictRestoreRejectionTest(unittest.TestCase):
    """Illegal snapshots are rejected AND leave the whole object unchanged.

    Every restore entry point must fail without half-applying: the reads,
    validation, and type conversions all happen before the first mutation.
    """

    def test_runtime_rejects_nan_timeout_without_partial_mutation(self):
        runtime = CodexPlayerRuntime(model="m", effort="low", max_calls=5)
        runtime.calls = 3
        snapshot = runtime.snapshot()
        snapshot["timeout"] = float("nan")
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)
        self.assertEqual(runtime.calls, 3)
        self.assertEqual(runtime.model, "m")
        self.assertEqual(runtime.effort, "low")
        self.assertEqual(runtime.timeout, 180)

    def test_api_runtime_rejects_nan_timeout_without_partial_mutation(self):
        cfg = LLMRuntimeConfig(True, "http://local.example/v1", "K", "m", 0.7, 2, 5)
        runtime = APIPlayerRuntime(cfg)
        snapshot = runtime.snapshot()
        snapshot["timeout"] = float("nan")
        with self.assertRaises(ValueError):
            runtime.restore(snapshot)
        self.assertEqual(runtime.timeout, 2)
        self.assertEqual(runtime.model, "m")

    def test_llm_rejects_nan_timeout_without_partial_mutation(self):
        client = LLMClient(LLMRuntimeConfig.from_request(
            {"enabled": True, "api_key": "TOPSECRET", "model": "m"}))
        snapshot = client.snapshot()
        snapshot["config"]["timeout_seconds"] = float("nan")
        with self.assertRaises(ValueError):
            client.restore(snapshot)
        self.assertEqual(client.runtime.model, "m")
        self.assertEqual(client.runtime.api_key, "TOPSECRET")

    def test_engine_rejects_unknown_role_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["seats"][0]["role"] = "not_a_role"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_engine_rejects_duplicate_seat_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["seats"][1]["pos"] = snapshot["seats"][0]["pos"]
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())
        self.assertEqual(len(engine.seats), 12)

    def test_engine_rejects_roster_mismatch_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        for seat in snapshot["seats"]:
            if seat["role"] == "civilian":
                seat["role"] = "seer"  # valid role, wrong multiset
                break
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_engine_rejects_unknown_phase_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["phase"] = "twilight"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_engine_rejects_unknown_winner_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["winner"] = "aliens"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_brain_rejects_bad_resolved_exiles_without_partial_mutation(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        seat = next(s for s in engine.seats.values() if not s.is_player)
        llm = LLMClient(LLMRuntimeConfig.from_request({"enabled": False}))
        with tempfile.TemporaryDirectory() as memory_dir:
            agent = StrategicNPCAgent(seat.name, engine, llm, memory_dir=memory_dir)
            before = agent.snapshot()
            snapshot = agent.snapshot()
            snapshot["brain"]["resolved_exiles"] = [[1, {}]]
            with self.assertRaises(ValueError):
                agent.restore(snapshot)
            self.assertEqual(before, agent.snapshot())

    def test_conjecture_rejects_missing_private_without_partial_mutation(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        ledger = GameConjectures(engine)
        before = ledger.snapshot()
        snapshot = ledger.snapshot()
        del snapshot["private"]
        with self.assertRaises(ValueError):
            ledger.restore(snapshot)
        self.assertEqual(before, ledger.snapshot())

    def test_conjecture_rejects_roster_mismatch(self):
        engine = GameEngine("classic", seed=7)
        engine.setup()
        ledger = GameConjectures(engine)
        snapshot = ledger.snapshot()
        snapshot["roster"] = snapshot["roster"][1:] + ["impostor"]
        with self.assertRaises(ValueError):
            ledger.restore(snapshot)


class PhaseAndIdentityValidationTest(unittest.TestCase):
    """Symmetric: every legal phase restores; contradictory identity is rejected."""

    def test_all_legal_session_phases_round_trip(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        # Dealt phases on a dealt engine (undealt prep is covered separately).
        for phase in ("onboarding", "night", "dawn", "day", "election", "vote"):
            engine.phase = phase
            snapshot = engine.snapshot()
            restored = GameEngine("classic", seed=1)
            restored.restore(snapshot)
            self.assertEqual(restored.phase, phase)

    def test_is_wolf_contradiction_rejected_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        wolf_count = sum(1 for s in before["seats"] if s["is_wolf"])
        snapshot = engine.snapshot()
        next(s for s in snapshot["seats"] if s["is_wolf"])["is_wolf"] = False
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())
        self.assertEqual(sum(1 for s in engine.seats.values() if s.is_wolf),
                         wolf_count)

    def test_faction_contradiction_rejected_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        seat = snapshot["seats"][0]
        seat["faction"] = "god" if seat["faction"] != "god" else "civilian"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_all_player_markers_cleared_rejected_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        for seat in snapshot["seats"]:
            seat["is_player"] = False
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_npc_marked_as_player_rejected_without_partial_mutation(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        next(s for s in snapshot["seats"] if not s["is_player"])["is_player"] = True
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_duplicate_human_identity_rejected(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        human = next(s for s in snapshot["seats"] if s["is_player"])
        npc = next(s for s in snapshot["seats"] if not s["is_player"])
        npc["player_id"] = human["player_id"]
        npc["is_player"] = True
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_undealt_prep_round_trips_from_real_engine(self):
        # A real, un-dealt engine (setup() never called) is in prep with an
        # empty roster and must round-trip — not just a renamed phase string.
        engine = GameEngine("classic", seed=7)
        self.assertEqual(engine.phase, "prep")
        self.assertEqual(engine.seats, {})
        restored = GameEngine("classic")
        restored.restore(engine.snapshot())
        self.assertEqual(restored.phase, "prep")
        self.assertEqual(restored.seats, {})
        self.assertEqual(
            json.dumps(engine.public_state(), sort_keys=True, ensure_ascii=False),
            json.dumps(restored.public_state(), sort_keys=True, ensure_ascii=False))

    def test_empty_roster_rejected_outside_prep(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["seats"] = []
        snapshot["phase"] = "night"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())

    def test_dealt_roster_rejected_in_prep(self):
        engine = EngineSnapshotTest().make_advanced_engine()
        before = engine.snapshot()
        snapshot = engine.snapshot()
        snapshot["phase"] = "prep"
        with self.assertRaises(ValueError):
            engine.restore(snapshot)
        self.assertEqual(before, engine.snapshot())


if __name__ == "__main__":
    unittest.main()
