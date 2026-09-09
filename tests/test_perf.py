"""Local-only perf instrumentation regression tests (no model, no key).

These assert the *foundation*: records are opt-in, monotonic-timed, privacy-safe
(seat position only — never a name, role, request body, command argv or
credential), observable-only (no fabricated spawn/inference/first-byte splits),
and the perf directory is excluded from release.  Real model/agent timing must
be collected in a connected environment; these tests only prove the plumbing and
the local measurements (request size, checkpoint size) that need no key.
"""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from werewolf_web import perf
from werewolf_web import checkpoint as cp
from werewolf_web.run import GameSession


def _read_lines(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class _FakePlanner:
    backend = "api"
    verified = True

    def __init__(self):
        self.model = "test-model"
        self.effort = "medium"
        self.calls = 0

    def reserve(self):
        self.calls += 1

    def public_status(self):
        return {"mode": "model_decisions", "backend": "api", "reason": ""}


class _SchemaPlanner(_FakePlanner):
    def complete(self, request, schema):
        result = {}
        for key, spec in schema.get("properties", {}).items():
            kind = spec.get("type")
            if kind == "boolean":
                result[key] = True
            elif kind == "string":
                result[key] = "ok"
            elif isinstance(kind, list):
                result[key] = None
        return result


class _FakeAgent:
    def __init__(self, pos, name):
        self.seat = SimpleNamespace(pos=pos)
        self.name = name
        self.model_decisions = []

    def speak(self, *args, **kwargs):
        return SimpleNamespace(text="hello")


class RecorderUnitTest(unittest.TestCase):
    def test_disabled_recorder_is_noop(self):
        recorder = perf.Recorder(None)
        recorder.decision(seat=1, dur_ms=1.0)
        recorder.flush()
        self.assertFalse(recorder.enabled)

    def test_records_are_privacy_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "perf.jsonl")
            recorder = perf.Recorder(path)
            recorder.decision(decision_no=1, step="speeches", instance="d0", seat=3,
                              kind="speak", attempt_no=1, backend="api",
                              model="m", effort="high", calls_before=0,
                              calls_after=1, outcome="accepted", dur_ms=12.3)
            recorder.model_call(seat=3, task="public speech", backend="api",
                                request_chars=1234, dur_ms=10.0)
            recorder.flush()
            lines = _read_lines(path)
            self.assertEqual(len(lines), 2)
            for record in lines:
                blob = json.dumps(record, ensure_ascii=False)
                for forbidden in ("name", "role", "command", "argv", "api_key",
                                  "token", "password", "request"):
                    self.assertNotIn(f'"{forbidden}"', blob)
                self.assertIn("cat", record)
                self.assertIn("t", record)
            # Actor is a seat position only.
            self.assertEqual(lines[0]["seat"], 3)
            self.assertNotIn("role", lines[0])
            self.assertNotIn("name", lines[0])

    def test_observable_only_no_fabricated_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "p.jsonl")
            recorder = perf.Recorder(path)
            recorder.decision(seat=1, dur_ms=5.0)
            recorder.flush()
            record = _read_lines(path)[0]
            for fabricated in ("spawn_ms", "inference_ms", "first_byte_ms", "turn_ms"):
                self.assertNotIn(fabricated, record)

    def test_flush_failure_disables_sink_without_raising(self):
        # A write failure (here: the target path is a directory) must be
        # swallowed and disable the recorder, never raise into the game loop.
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "perf.jsonl")
            os.makedirs(target)          # a directory where a file was expected
            recorder = perf.Recorder(target)
            recorder.decision(seat=1, dur_ms=1.0)
            recorder.flush()             # must not raise
            self.assertFalse(recorder.enabled)


class PerfReleaseTest(unittest.TestCase):
    def test_perf_dir_excluded_from_release(self):
        from scripts.prepare_release import allowed_path
        self.assertFalse(allowed_path("werewolf_web/data/perf/game.jsonl"))
        self.assertTrue(allowed_path("werewolf_web/perf.py"))
        self.assertTrue(allowed_path("tests/test_perf.py"))


class PerfIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_timing_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            try:
                path = os.path.join(directory, "perf.jsonl")
                session = GameSession("classic", {"enabled": False},
                                      session_id="perf-ck",
                                      checkpoint_path=cp.checkpoint_path("perf-ck"),
                                      perf_path=path)
                await session._step_setup()
                session._checkpoint()
                session.perf_recorder.flush()
                records = _read_lines(path)
                checkpoints = [r for r in records if r["cat"] == "checkpoint"]
                self.assertTrue(checkpoints)
                self.assertIn("dur_ms", checkpoints[0])
                self.assertIn("bytes", checkpoints[0])
                self.assertGreater(checkpoints[0]["bytes"], 0)
            finally:
                cp.CHECKPOINTS_DIR = old

    async def test_decision_records_seat_position_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "perf.jsonl")
            session = GameSession("classic", {"enabled": False},
                                  session_id="perf-dec", planner=_FakePlanner(),
                                  perf_path=path)
            session._current_step = "speeches"
            await session._npc_call(_FakeAgent(5, "SomeName").speak)
            session.perf_recorder.flush()
            records = _read_lines(path)
            decisions = [r for r in records if r["cat"] == "decision"]
            self.assertTrue(decisions)
            decision = decisions[0]
            self.assertEqual(decision["seat"], 5)
            self.assertEqual(decision["kind"], "speak")
            self.assertEqual(decision["backend"], "api")
            self.assertEqual(decision["outcome"], "accepted")
            self.assertIn("dur_ms", decision)
            self.assertNotIn("name", decision)
            self.assertNotIn("role", decision)

    async def test_model_call_records_request_chars(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "perf.jsonl")
            session = GameSession("classic", {"enabled": False},
                                  session_id="perf-mc", planner=_SchemaPlanner(),
                                  perf_path=path)
            await session._step_setup()
            agent = next(iter(session.agents.values()))
            await asyncio.to_thread(agent.decide, "public speech",
                                    {"text": {"type": "string", "maxLength": 100}})
            session.perf_recorder.flush()
            records = _read_lines(path)
            calls = [r for r in records if r["cat"] == "model_call"]
            self.assertTrue(calls)
            self.assertIn("request_chars", calls[0])
            self.assertGreater(calls[0]["request_chars"], 0)
            self.assertIn("dur_ms", calls[0])
            self.assertIn("seat", calls[0])
            self.assertNotIn("role", calls[0])
            self.assertNotIn("name", calls[0])


if __name__ == "__main__":
    unittest.main()
