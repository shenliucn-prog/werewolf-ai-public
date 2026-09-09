"""Unified game-driver resolution + save/restore driver lock.

Covers the resolution order (explicit > saved > env), the distinct
"unconfigured" state, keyless api servers, the agent adapter as a second layer,
the Web's "never supply an executable" boundary, and the offline<->counted
restore lock with legacy-save migration.
"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from werewolf_web import driver as driver_mod
from werewolf_web import settings as user_settings
from werewolf_web import checkpoint as cp
from werewolf_web.driver import (
    DriverResolutionError, infer_legacy_driver, resolve_driver, validate_restore,
)
from werewolf_web.run import GAMES, start, campaign_start, restore_game


def _env(**kwargs):
    base = {"PATH": "/usr/bin", "HOME": "/tmp"}
    base.update(kwargs)
    return base


class DriverResolutionTest(unittest.TestCase):
    def test_resolution_order_explicit_over_saved_over_env(self):
        # explicit driver + adapter beat saved + env.
        resolved = resolve_driver(
            explicit={"driver": "agent", "adapter": "codex", "model": "gpt-x"},
            saved={"backend": "api", "model": "saved"},
            env=_env(WEREWOLF_MODEL_BACKEND="api"))
        self.assertEqual(resolved["driver"], "agent")
        self.assertEqual(resolved["adapter"], "codex")
        self.assertEqual(resolved["backend"], "codex")
        self.assertEqual(resolved["model"], "gpt-x")

        # model: explicit > saved > env.
        self.assertEqual(resolve_driver(
            explicit={"model": "explicit"}, saved={"model": "saved"},
            env=_env(LLM_MODEL="env"))["model"], "explicit")
        self.assertEqual(resolve_driver(
            saved={"model": "saved"}, env=_env(LLM_MODEL="env"))["model"], "saved")
        self.assertEqual(resolve_driver(env=_env(LLM_MODEL="env"))["model"], "env")

    def test_unconfigured_is_distinct_from_offline(self):
        # Nothing anywhere: not offline, not a blind api default.
        resolved = resolve_driver(env=_env())
        self.assertFalse(resolved["configured"])
        self.assertIsNone(resolved["driver"])

        # Explicit offline is a configured, valid choice.
        resolved = resolve_driver(explicit={"enabled": False}, env=_env())
        self.assertTrue(resolved["configured"])
        self.assertEqual(resolved["driver"], "offline")

        # Saved `enabled: false` is NOT an explicit offline choice; with no model
        # it is unconfigured, never silently offline.
        resolved = resolve_driver(saved={"enabled": False}, env=_env())
        self.assertFalse(resolved["configured"])
        self.assertIsNone(resolved["driver"])

    def test_keyless_api_with_base_url_is_configured(self):
        resolved = resolve_driver(
            explicit={"enabled": True, "model": "m", "base_url": "http://localhost:1234/v1"},
            env=_env())
        self.assertTrue(resolved["configured"])
        self.assertEqual(resolved["driver"], "api")
        self.assertIsNone(resolved["adapter"])
        self.assertEqual(resolved["runtime_kwargs"]["backend"], "api")

    def test_agent_adapter_is_second_layer_not_driver(self):
        resolved = resolve_driver(
            explicit={"driver": "agent", "adapter": "command"},
            saved={"command": ["python", "wrapper.py"]}, env=_env())
        self.assertEqual(resolved["driver"], "agent")   # never "command"
        self.assertEqual(resolved["adapter"], "command")
        self.assertEqual(resolved["backend"], "command")
        self.assertEqual(resolved["runtime_kwargs"]["command"], '["python", "wrapper.py"]')

    def test_command_adapter_requires_trusted_command(self):
        resolved = resolve_driver(explicit={"driver": "agent", "adapter": "command"},
                                  env=_env())
        self.assertFalse(resolved["configured"])

        resolved = resolve_driver(explicit={"driver": "agent", "adapter": "command"},
                                  env=_env(WEREWOLF_AGENT_COMMAND='["python", "w.py"]'))
        self.assertTrue(resolved["configured"])
        self.assertEqual(resolved["runtime_kwargs"]["command"], '["python", "w.py"]')

    def test_connection_selection_uses_trusted_config(self):
        saved = {"agent_connections": {
            "local-codex": {"adapter": "codex", "model": "gpt-5.6-terra", "effort": "low"},
        }}
        resolved = resolve_driver(explicit={"driver": "agent", "connection": "local-codex"},
                                  saved=saved, env=_env())
        self.assertEqual(resolved["driver"], "agent")
        self.assertEqual(resolved["adapter"], "codex")
        self.assertEqual(resolved["model"], "gpt-5.6-terra")
        self.assertEqual(resolved["effort"], "low")

    def test_command_from_explicit_is_never_used(self):
        # Even if a caller smuggles a command into the explicit dict, it is
        # ignored (only the trusted ``command`` arg / saved / env provide it).
        resolved = resolve_driver(
            explicit={"driver": "agent", "adapter": "command", "command": ["evil"]},
            env=_env())
        self.assertFalse(resolved["configured"])

    def test_invalid_command_is_reported_not_crashed(self):
        resolved = resolve_driver(explicit={"driver": "agent", "adapter": "command"},
                                  saved={"command": "not json"}, env=_env())
        self.assertFalse(resolved["configured"])

    def test_saved_or_env_legacy_is_not_an_offline_selection(self):
        # Offline is only ever an explicit choice in this request; a saved or
        # environment ``legacy`` backend means "no usable model config", never a
        # silent offline switch.
        resolved = resolve_driver(saved={"backend": "legacy"}, env=_env())
        self.assertFalse(resolved["configured"])
        self.assertIsNot(resolved["driver"], "offline")

        resolved = resolve_driver(env=_env(WEREWOLF_MODEL_BACKEND="legacy"))
        self.assertFalse(resolved["configured"])
        self.assertIsNot(resolved["driver"], "offline")

    def test_saved_driver_and_adapter_are_honored(self):
        resolved = resolve_driver(saved={"driver": "agent", "adapter": "codex",
                                         "model": "gpt-x"}, env=_env())
        self.assertEqual(resolved["driver"], "agent")
        self.assertEqual(resolved["adapter"], "codex")
        self.assertEqual(resolved["backend"], "codex")
        self.assertEqual(resolved["runtime_kwargs"]["backend"], "codex")

    def test_explicit_effort_beats_saved_reasoning_effort(self):
        # The aliases must be merged by source first (explicit over saved), then
        # unified — an explicit ``effort`` wins over a saved ``reasoning_effort``.
        resolved = resolve_driver(explicit={"model": "m", "effort": "high"},
                                  saved={"reasoning_effort": "low"}, env=_env())
        self.assertTrue(resolved["configured"])
        self.assertEqual(resolved["effort"], "high")
        self.assertEqual(resolved["runtime_kwargs"]["effort"], "high")

    def test_explicit_backend_api_beats_saved_agent_driver(self):
        # An explicit ``backend="api"`` implies the api driver and must not be
        # shadowed by a saved ``driver="agent"`` / ``adapter="codex"``.
        resolved = resolve_driver(explicit={"backend": "api", "model": "m"},
                                  saved={"driver": "agent", "adapter": "codex"},
                                  env=_env())
        self.assertEqual(resolved["driver"], "api")
        self.assertIsNone(resolved["adapter"])
        self.assertEqual(resolved["runtime_kwargs"]["backend"], "api")

        # And the converse: an explicit agent backend beats a saved api driver.
        resolved = resolve_driver(explicit={"backend": "codex"},
                                  saved={"driver": "api", "model": "saved"},
                                  env=_env())
        self.assertEqual(resolved["driver"], "agent")
        self.assertEqual(resolved["adapter"], "codex")


class DriverSaveRestoreTest(unittest.TestCase):
    def test_infer_legacy_driver(self):
        self.assertEqual(infer_legacy_driver({"backend": "api"}, None), ("api", None))
        self.assertEqual(infer_legacy_driver({"backend": "codex"}, None), ("agent", "codex"))
        self.assertEqual(infer_legacy_driver({"backend": "command"}, None), ("agent", "command"))
        self.assertEqual(infer_legacy_driver(None, None), ("offline", None))
        self.assertEqual(infer_legacy_driver(None, False), ("offline", None))

    def test_contradictory_legacy_save_refused(self):
        # model/agent driver but marked not counted.
        with self.assertRaises(ValueError):
            infer_legacy_driver({"backend": "api"}, False)
        # counted campaign game without a planner.
        with self.assertRaises(ValueError):
            infer_legacy_driver(None, True)
        # unknown planner backend.
        with self.assertRaises(ValueError):
            infer_legacy_driver({"backend": "mystery"}, None)

    def test_validate_restore_offline_lock(self):
        with self.assertRaises(ValueError):
            validate_restore("offline", None, True, None)          # offline but counted
        with self.assertRaises(ValueError):
            validate_restore("offline", None, None, SimpleNamespace(backend="api"))

    def test_validate_restore_adapter_mismatch_refused(self):
        with self.assertRaises(ValueError):
            validate_restore("agent", "command", None, SimpleNamespace(backend="codex"))
        with self.assertRaises(ValueError):
            validate_restore("api", None, None, SimpleNamespace(backend="codex"))
        with self.assertRaises(ValueError):
            validate_restore("agent", "codex", None, None)         # agent but no planner


class _ApiPlanner:
    backend = "api"
    verified = True

    def __init__(self):
        self.model = "test-model"
        self.max_calls = 240
        self.timeout = 60.0
        self.calls = 0

    def reserve(self):
        self.calls += 1

    def preflight(self):
        self.verified = True

    def preflight_check(self):
        self.verified = True

    def snapshot(self):
        return {"schema_version": 1, "backend": "api", "model": self.model,
                "max_calls": self.max_calls, "timeout": self.timeout, "calls": self.calls}

    def restore(self, data):
        self.model = data["model"]
        self.max_calls = data["max_calls"]
        self.timeout = data["timeout"]
        self.calls = data["calls"]

    def public_status(self):
        return {"backend": "api"}


class _CodexPlanner(_ApiPlanner):
    backend = "codex"

    def snapshot(self):
        data = super().snapshot()
        data["backend"] = "codex"
        data["effort"] = "medium"
        return data

    def restore(self, data):
        super().restore(data)
        self.effort = data.get("effort", "medium")


class _CommandPlanner(_ApiPlanner):
    backend = "command"

    def reserve(self):
        self.calls += 1

    def preflight_check(self):
        self.verified = True

    def snapshot(self):
        data = super().snapshot()
        data["backend"] = "command"
        return data


class SessionDriverTest(unittest.IsolatedAsyncioTestCase):
    async def _dealt(self, session):
        from werewolf_web.run import GameSession
        await session._step_setup()

    def test_snapshot_carries_driver_and_adapter(self):
        from werewolf_web.run import GameSession
        offline = GameSession("classic", {"enabled": False}, session_id="d-off")
        self.assertEqual(offline.snapshot()["driver"], "offline")
        self.assertIsNone(offline.snapshot()["adapter"])

        api = GameSession("classic", {"enabled": False}, session_id="d-api",
                          planner=_ApiPlanner())
        self.assertEqual(api.snapshot()["driver"], "api")

        codex = GameSession("classic", {"enabled": False}, session_id="d-codex",
                            planner=_CodexPlanner())
        self.assertEqual(codex.snapshot()["driver"], "agent")
        self.assertEqual(codex.snapshot()["adapter"], "codex")

    def test_restore_refuses_offline_counted_upgrade(self):
        from werewolf_web.run import GameSession
        a = GameSession("classic", {"enabled": False}, session_id="lock-off")
        snapshot = a.snapshot()
        snapshot["campaign_counted"] = True          # attempt to upgrade
        b = GameSession("classic", {"enabled": False}, session_id="lock-off")
        with self.assertRaises(ValueError):
            b.restore(snapshot)
        # The offline label and un-counted marker stay intact.
        self.assertEqual(b.driver, "offline")
        self.assertIsNone(b.campaign_counted)

    def test_legacy_save_infers_driver_on_restore(self):
        from werewolf_web.run import GameSession
        a = GameSession("classic", {"enabled": False}, session_id="mig-codex",
                        planner=_CodexPlanner())
        snapshot = a.snapshot()
        del snapshot["driver"]          # simulate an old save with no driver field
        del snapshot["adapter"]
        b = GameSession("classic", {"enabled": False}, session_id="mig-codex",
                        planner=_CodexPlanner())
        b.restore(snapshot)
        self.assertEqual(b.driver, "agent")
        self.assertEqual(b.adapter, "codex")


class WebDriverTest(unittest.IsolatedAsyncioTestCase):
    def _req(self, body):
        return SimpleNamespace(json=AsyncMock(return_value=body))

    async def test_web_refuses_unconfigured_start(self):
        before = set(GAMES)
        req = self._req({"board_id": "classic"})
        with patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
             self.assertRaises(HTTPException) as error:
            await start(req)
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(set(GAMES), before)

    async def test_web_selects_preconfigured_agent_connection(self):
        saved = {"agent_connections": {
            "local-codex": {"adapter": "codex", "model": "gpt-5.6-terra"},
        }}
        planner = SimpleNamespace(verified=False, public_status=lambda: {"backend": "codex"})
        planner.preflight = Mock()
        req = self._req({"board_id": "classic", "driver": "agent", "connection": "local-codex"})
        with patch("werewolf_web.run.user_settings.load_settings", return_value=saved), \
             patch("werewolf_web.run.create_runtime", return_value=planner) as factory:
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        self.assertEqual(factory.call_args.kwargs["backend"], "codex")

    async def test_web_cannot_supply_command_through_llm(self):
        # A command embedded in the request's llm options is ignored entirely:
        # it never reaches create_runtime and never persists to settings.
        req = self._req({"board_id": "classic",
                         "llm": {"enabled": True, "model": "test", "command": ["evil"]}})
        planner = SimpleNamespace(verified=False, public_status=lambda: {"backend": "api"})
        planner.preflight = Mock()
        with patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
             patch("werewolf_web.run.user_settings.save_settings") as save, \
             patch("werewolf_web.run.create_runtime", return_value=planner) as factory:
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        self.assertEqual(factory.call_args.kwargs["backend"], "api")
        self.assertNotIn("command", factory.call_args.kwargs)
        # The web save path (non-trusted) strips the executable before persisting.
        self.assertNotIn("command", user_settings.sanitize(save.call_args.args[0]))

    async def test_web_model_game_snapshot_restore_roundtrip_api(self):
        from werewolf_web.run import GameSession
        planner = _ApiPlanner()
        req = self._req({"board_id": "classic",
                         "llm": {"enabled": True, "model": "test"}})
        with patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
             patch("werewolf_web.run.user_settings.save_settings"), \
             patch("werewolf_web.run.create_runtime", return_value=planner):
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        runner = GAMES[response["game_id"]]
        self.assertEqual(runner.driver, "api")
        self.assertIsNone(runner.adapter)
        snapshot = runner.snapshot()
        self.assertEqual(snapshot["driver"], "api")
        fresh = GameSession("classic", {"enabled": False},
                            session_id=response["game_id"], planner=_ApiPlanner())
        fresh.restore(snapshot)              # must not raise
        self.assertEqual(fresh.driver, "api")
        self.assertIsNone(fresh.adapter)
        self.assertEqual(fresh.planner.backend, "api")

    async def test_web_model_game_snapshot_restore_roundtrip_agent(self):
        from werewolf_web.run import GameSession
        saved = {"agent_connections": {
            "local-codex": {"adapter": "codex", "model": "gpt-5.6-terra"},
        }}
        planner = _CodexPlanner()
        req = self._req({"board_id": "classic", "driver": "agent",
                         "connection": "local-codex"})
        with patch("werewolf_web.run.user_settings.load_settings", return_value=saved), \
             patch("werewolf_web.run.user_settings.save_settings"), \
             patch("werewolf_web.run.create_runtime", return_value=planner):
            response = await start(req)
        self.addCleanup(GAMES.pop, response["game_id"], None)
        runner = GAMES[response["game_id"]]
        self.assertEqual(runner.driver, "agent")
        self.assertEqual(runner.adapter, "codex")
        snapshot = runner.snapshot()
        self.assertEqual(snapshot["driver"], "agent")
        self.assertEqual(snapshot["adapter"], "codex")
        fresh = GameSession("classic", {"enabled": False},
                            session_id=response["game_id"], planner=_CodexPlanner())
        fresh.restore(snapshot)              # must not raise
        self.assertEqual(fresh.driver, "agent")
        self.assertEqual(fresh.adapter, "codex")
        self.assertEqual(fresh.planner.backend, "codex")

    async def test_agent_connections_endpoint_strips_commands(self):
        from werewolf_web.run import agent_connections
        saved = {"agent_connections": {
            "local-codex": {"adapter": "codex", "model": "gpt-x",
                            "command": ["secret", "argv"]},
        }}
        with patch("werewolf_web.run.user_settings.load_settings", return_value=saved):
            result = await agent_connections()
        self.assertEqual(len(result["connections"]), 1)
        conn = result["connections"][0]
        self.assertEqual(conn["name"], "local-codex")
        self.assertEqual(conn["adapter"], "codex")
        self.assertEqual(conn["model"], "gpt-x")
        self.assertNotIn("command", conn)     # never expose an executable argv


class RestoreDriverTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_game_resolves_saved_agent_command(self):
        # A command-adapter save re-derives its runtime from trusted local
        # settings (the save never carries the argv), so an interrupt + restore
        # succeeds instead of returning None.
        from werewolf_web.run import GameSession
        sid = "agent-cmd-restore"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_CommandPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "agent", "command"
                a._checkpoint()
                self.assertNotIn(sid, GAMES)

                saved = {"driver": "agent", "adapter": "command",
                         "command": ["codex", "exec"]}
                created = {}

                def fake_create_runtime(**kwargs):
                    created.update(kwargs)
                    return _CommandPlanner()

                with patch("werewolf_web.run.user_settings.load_settings", return_value=saved), \
                     patch("werewolf_web.run.create_runtime", fake_create_runtime):
                    runner = await restore_game(sid)
                self.assertIsNotNone(runner)
                self.assertEqual(created["backend"], "command")
                self.assertEqual(created["command"], '["codex", "exec"]')
                self.assertEqual(runner.driver, "agent")
                self.assertEqual(runner.adapter, "command")
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)

    async def test_restore_game_refuses_command_without_trusted_config(self):
        from werewolf_web.run import GameSession
        sid = "agent-cmd-missing"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_CommandPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "agent", "command"
                a._checkpoint()

                with patch("werewolf_web.run.user_settings.load_settings", return_value=None):
                    runner = await restore_game(sid)
                self.assertIsNone(runner)   # no trusted command -> cannot resume
                self.assertNotIn(sid, GAMES)
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)

    def test_restore_runtime_kwargs_sources_and_priority(self):
        # command priority: explicit > saved > env.
        self.assertEqual(
            driver_mod.restore_runtime_kwargs(
                "agent", "command", {}, env=_env(WEREWOLF_AGENT_COMMAND='["env", "w.py"]')),
            {"backend": "command", "command": '["env", "w.py"]'})
        self.assertEqual(
            driver_mod.restore_runtime_kwargs(
                "agent", "command", {"command": ["saved", "w.py"]},
                env=_env(WEREWOLF_AGENT_COMMAND='["env", "w.py"]')),
            {"backend": "command", "command": '["saved", "w.py"]'})
        self.assertEqual(
            driver_mod.restore_runtime_kwargs(
                "agent", "command", {"command": ["saved", "w.py"]},
                command='["cli", "w.py"]', env=_env()),
            {"backend": "command", "command": '["cli", "w.py"]'})

        # api carries the saved endpoint so a local-server save restores against
        # its own endpoint, never the environment default.
        self.assertEqual(
            driver_mod.restore_runtime_kwargs(
                "api", None, {"base_url": "http://localhost:1234/v1"}, env=_env()),
            {"backend": "api", "options": {"base_url": "http://localhost:1234/v1"}})
        self.assertEqual(
            driver_mod.restore_runtime_kwargs("api", None, {}, env=_env()),
            {"backend": "api", "options": None})

    async def test_restore_game_uses_env_agent_command(self):
        from werewolf_web.run import GameSession
        sid = "agent-cmd-env-restore"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_CommandPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "agent", "command"
                a._checkpoint()

                created = {}

                def fake_create_runtime(**kwargs):
                    created.update(kwargs)
                    return _CommandPlanner()

                with patch.dict("os.environ", {"WEREWOLF_AGENT_COMMAND": '["env", "w.py"]'}), \
                     patch("werewolf_web.run.user_settings.load_settings", return_value=None), \
                     patch("werewolf_web.run.create_runtime", fake_create_runtime):
                    runner = await restore_game(sid)
                self.assertIsNotNone(runner)
                self.assertEqual(created["backend"], "command")
                self.assertEqual(created["command"], '["env", "w.py"]')
                self.assertEqual(runner.driver, "agent")
                self.assertEqual(runner.adapter, "command")
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)

    async def test_restore_game_uses_saved_api_endpoint(self):
        from werewolf_web.run import GameSession
        sid = "api-endpoint-restore"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_ApiPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "api", None
                a._checkpoint()

                saved = {"base_url": "http://localhost:1234/v1"}
                created = {}

                def fake_create_runtime(**kwargs):
                    created.update(kwargs)
                    return _ApiPlanner()

                with patch("werewolf_web.run.user_settings.load_settings", return_value=saved), \
                     patch("werewolf_web.run.create_runtime", fake_create_runtime):
                    runner = await restore_game(sid)
                self.assertIsNotNone(runner)
                self.assertEqual(created["backend"], "api")
                self.assertEqual(created["options"], {"base_url": "http://localhost:1234/v1"})
                self.assertEqual(runner.driver, "api")
            finally:
                cp.CHECKPOINTS_DIR = old
                GAMES.pop(sid, None)


class TerminalDriverEntryTest(unittest.IsolatedAsyncioTestCase):
    """Terminal ``play``/``campaign_play`` share the web's driver resolution."""

    async def test_play_uses_resolve_driver(self):
        import contextlib
        import io
        from werewolf_web import chat_game
        captured = {}
        planner = SimpleNamespace(verified=True, preflight=lambda: None,
                                  public_status=lambda: {})

        def fake_create_runtime(**kwargs):
            captured.update(kwargs)
            return planner

        async def fake_repl(session):
            captured["session"] = session
            return 0

        with contextlib.redirect_stdout(io.StringIO()):
            with patch("werewolf_web.ai.decision_runtime.create_runtime", fake_create_runtime), \
                 patch("werewolf_web.settings.load_settings", return_value=None), \
                 patch.object(chat_game, "_repl", new=fake_repl):
                result = await chat_game.play("classic", 7, False, "zh-CN",
                                              backend="codex")
        self.assertEqual(result, 0)
        self.assertEqual(captured["backend"], "codex")
        self.assertEqual(captured["session"].driver, "agent")
        self.assertEqual(captured["session"].adapter, "codex")

    async def test_play_explicit_backend_api_beats_saved_agent(self):
        import contextlib
        import io
        from werewolf_web import chat_game
        captured = {}
        planner = SimpleNamespace(verified=True, preflight=lambda: None,
                                  public_status=lambda: {})

        def fake_create_runtime(**kwargs):
            captured.update(kwargs)
            return planner

        async def fake_repl(session):
            captured["session"] = session
            return 0

        saved = {"driver": "agent", "adapter": "codex"}
        with contextlib.redirect_stdout(io.StringIO()):
            with patch("werewolf_web.ai.decision_runtime.create_runtime", fake_create_runtime), \
                 patch("werewolf_web.config.raw_env", return_value={"LLM_ENABLED": "true"}), \
                 patch("werewolf_web.settings.load_settings", return_value=saved), \
                 patch.object(chat_game, "_repl", new=fake_repl):
                result = await chat_game.play("classic", 7, False, "zh-CN",
                                              backend="api", model="m")
        self.assertEqual(result, 0)
        self.assertEqual(captured["backend"], "api")
        self.assertEqual(captured["session"].driver, "api")
        self.assertIsNone(captured["session"].adapter)

    async def test_play_resume_resolves_saved_agent_command(self):
        # The terminal resume path re-derives a command-adapter runtime from
        # trusted local settings (the save never carries the argv).
        import contextlib
        import io
        from werewolf_web import chat_game
        from werewolf_web.run import GameSession
        sid = "chat-cmd-resume"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_CommandPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "agent", "command"
                a._checkpoint()

                saved = {"driver": "agent", "adapter": "command",
                         "command": ["codex", "exec"]}
                created = {}

                def fake_create_runtime(**kwargs):
                    created.update(kwargs)
                    return _CommandPlanner()

                async def fake_repl(session):
                    created["session"] = session
                    return 0

                with contextlib.redirect_stdout(io.StringIO()):
                    with patch("werewolf_web.ai.decision_runtime.create_runtime", fake_create_runtime), \
                         patch("werewolf_web.settings.load_settings", return_value=saved), \
                         patch.object(chat_game, "_repl", new=fake_repl):
                        result = await chat_game.play(None, None, False, "zh-CN",
                                                      resume_game_id=sid)
                self.assertEqual(result, 0)
                self.assertEqual(created["backend"], "command")
                self.assertEqual(created["command"], '["codex", "exec"]')
                self.assertEqual(created["session"].driver, "agent")
                self.assertEqual(created["session"].adapter, "command")
            finally:
                cp.CHECKPOINTS_DIR = old

    async def test_play_resume_uses_explicit_agent_command(self):
        # --resume --agent-command rescues a command game even when no saved or
        # environment command is configured (the explicit CLI argv wins).
        import contextlib
        import io
        from werewolf_web import chat_game
        from werewolf_web.run import GameSession
        sid = "chat-cmd-resume-cli"
        with tempfile.TemporaryDirectory() as directory:
            old = cp.CHECKPOINTS_DIR
            cp.CHECKPOINTS_DIR = directory
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                planner=_CommandPlanner(),
                                checkpoint_path=cp.checkpoint_path(sid))
                a.driver, a.adapter = "agent", "command"
                a._checkpoint()

                created = {}

                def fake_create_runtime(**kwargs):
                    created.update(kwargs)
                    return _CommandPlanner()

                async def fake_repl(session):
                    created["session"] = session
                    return 0

                with contextlib.redirect_stdout(io.StringIO()):
                    with patch("werewolf_web.ai.decision_runtime.create_runtime", fake_create_runtime), \
                         patch("werewolf_web.settings.load_settings", return_value=None), \
                         patch.object(chat_game, "_repl", new=fake_repl):
                        result = await chat_game.play(None, None, False, "zh-CN",
                                                      resume_game_id=sid,
                                                      agent_command='["cli", "w.py"]')
                self.assertEqual(result, 0)
                self.assertEqual(created["backend"], "command")
                self.assertEqual(created["command"], '["cli", "w.py"]')
                self.assertEqual(created["session"].driver, "agent")
                self.assertEqual(created["session"].adapter, "command")
            finally:
                cp.CHECKPOINTS_DIR = old

    async def test_campaign_play_saves_resolved_config_with_trusted_true(self):
        import contextlib
        import io
        from werewolf_web import chat_game
        from werewolf_web import checkpoint as cp
        from werewolf_web import campaign_archive as ca
        planner = SimpleNamespace(verified=True, preflight=lambda: None,
                                  public_status=lambda: {}, model="m")
        saved_calls = []

        def fake_save_settings(config, trusted=False):
            saved_calls.append((dict(config), trusted))

        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with patch("werewolf_web.ai.decision_runtime.create_runtime",
                               return_value=planner), \
                         patch("werewolf_web.settings.load_settings", return_value=None), \
                         patch("werewolf_web.settings.save_settings", fake_save_settings), \
                         patch.object(chat_game, "_repl", return_value=0):
                        result = await chat_game.campaign_play(
                            "p1", False, "zh-CN", None, backend="command",
                            agent_command='["codex", "exec"]')
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca
        self.assertEqual(result, 0)
        self.assertEqual(len(saved_calls), 1)
        config, trusted = saved_calls[0]
        self.assertTrue(trusted)
        self.assertEqual(config["driver"], "agent")
        self.assertEqual(config["adapter"], "command")
        self.assertEqual(config["command"], '["codex", "exec"]')


class SettingsTrustedTest(unittest.TestCase):
    def test_trusted_cli_persists_command_but_web_path_drops_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            with patch.object(user_settings, "SETTINGS_PATH", path):
                user_settings.save_settings(
                    {"backend": "command", "command": ["python", "w.py"], "model": "m"},
                    trusted=True)
                self.assertEqual(user_settings.load_settings()["command"],
                                 ["python", "w.py"])

                # Web (non-trusted) save never writes an executable.
                user_settings.save_settings(
                    {"backend": "command", "command": ["evil"], "model": "m"})
                self.assertNotIn("command", user_settings.load_settings())


if __name__ == "__main__":
    unittest.main()
