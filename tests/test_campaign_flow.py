"""Campaign flow wiring + local settings: full lifecycle and save-state handling."""
import os
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import checkpoint as cp
from werewolf_web import campaign_archive as ca
from werewolf_web import campaign_flow as flow
from werewolf_web import settings


def _checkpoint(game_id, role, board, winner, finished, seats):
    return {"session_id": game_id, "finished": finished,
            "engine": {"player_role": role, "board_id": board, "winner": winner,
                       "day_count": 3, "night_count": 3, "seats": seats}}


def _dealt(game_id, role, board, winner, finished=True):
    return _checkpoint(game_id, role, board, winner, finished,
                       seats=[{"pos": 1} for _ in range(12)])


class CampaignFlowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        directory = self._tmp.name
        self._old_ca = ca.CAMPAIGN_DIR
        self._old_cp = cp.CHECKPOINTS_DIR
        ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
        cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
        self.addCleanup(self._restore)

    def _restore(self):
        ca.CAMPAIGN_DIR = self._old_ca
        cp.CHECKPOINTS_DIR = self._old_cp

    def test_full_create_save_interrupt_resume_settle(self):
        # create: register preparing, write an uninitialized checkpoint
        flow.begin_attempt("p1", "g1", "civilian", "classic", config={"model": "m"})
        cp.save_checkpoint(cp.checkpoint_path("g1"),
                           _checkpoint("g1", "civilian", "classic", None, False, seats=[]))

        # resume before the game deals: uninitialized, not counted
        status, archive = flow.resume_game("p1", "g1")
        self.assertEqual(status, "uninitialized")
        self.assertEqual(archive["attempts"], {})

        # the game deals -> count the attempt once
        flow.mark_started("p1", "g1")
        archive = flow.load_profile("p1")
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)

        # interrupt mid-game (finished=False), then resume: no re-count, no settle
        cp.save_checkpoint(cp.checkpoint_path("g1"),
                           _dealt("g1", "civilian", "classic", None, finished=False))
        status, archive = flow.resume_game("p1", "g1")
        self.assertEqual(status, "ok")
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)
        self.assertEqual(archive["settled"], [])

        # the game ends -> settle exactly once, unlock the next level
        cp.save_checkpoint(cp.checkpoint_path("g1"),
                           _dealt("g1", "civilian", "classic", "god", finished=True))
        flow.settle_game("p1", "g1", cp.load_checkpoint(cp.checkpoint_path("g1")))
        flow.settle_game("p1", "g1", cp.load_checkpoint(cp.checkpoint_path("g1")))  # idempotent
        archive = flow.load_profile("p1")
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)
        self.assertEqual(archive["settled"], ["g1"])
        self.assertEqual(archive["unlocked"], 1)

    def test_missing_save_drops_stale_preparing(self):
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        # no checkpoint written (crash before the game initialized)
        status, archive = flow.resume_game("p1", "g1")
        self.assertEqual(status, "missing")
        self.assertIsNone(archive["current_game"])
        self.assertEqual(archive["attempts"], {})

    def test_corrupt_save_is_distinct_and_leaves_archive_unchanged(self):
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        cp.save_checkpoint(cp.checkpoint_path("g1"),
                           _dealt("g1", "civilian", "classic", "god"))
        with open(cp.checkpoint_path("g1"), "w", encoding="utf-8") as handle:
            handle.write("not json")
        before = flow.load_profile("p1")
        status, archive = flow.resume_game("p1", "g1")
        self.assertEqual(status, "corrupt")
        self.assertEqual(archive, before)   # archive untouched; caller refuses

    def test_preflight_failure_then_retry_replaces_stale_preparing(self):
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        # preflight failed, no checkpoint written; retry with a fresh game id.
        flow.begin_attempt("p1", "g2", "civilian", "classic")
        archive = flow.load_profile("p1")
        self.assertEqual(archive["current_game"]["game_id"], "g2")
        self.assertEqual(archive["attempts"], {})   # never counted

    def test_begin_attempt_reconciles_an_initialized_old_game(self):
        # Crash between the init save and the count: the old game has an
        # initialized checkpoint but the archive is still `preparing`.  A new
        # registration must count it and refuse, not silently overwrite.
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        cp.save_checkpoint(cp.checkpoint_path("g1"),
                           _dealt("g1", "civilian", "classic", None, finished=False))
        with self.assertRaises(ValueError):
            flow.begin_attempt("p1", "g2", "civilian", "classic")
        archive = flow.load_profile("p1")
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)  # old counted
        self.assertEqual(archive["current_game"]["game_id"], "g1")

    def test_abandon_settles_a_started_attempt(self):
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        flow.mark_started("p1", "g1")
        flow.abandon_game("p1", "g1")
        archive = flow.load_profile("p1")
        self.assertEqual(archive["attempts"]["civilian"]["abandoned"], 1)
        self.assertIsNone(archive["current_game"])
        flow.begin_attempt("p1", "g2", "civilian", "classic")   # next attempt OK

    def test_abandon_drops_a_never_started_attempt(self):
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        flow.abandon_game("p1", "g1")
        archive = flow.load_profile("p1")
        self.assertIsNone(archive["current_game"])
        self.assertEqual(archive["attempts"], {})


class CampaignHookTest(unittest.IsolatedAsyncioTestCase):
    async def test_campaign_profile_round_trips_and_hook_reattaches(self):
        from werewolf_web import run
        from werewolf_web.run import GameSession
        sid = "campaign-hook"
        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                a.campaign_profile = "p1"
                await a._step_setup()
                a._checkpoint()
                run.GAMES.pop(sid, None)
                b = await run.restore_game(sid)
                self.assertIsNotNone(b)
                self.assertEqual(b.campaign_profile, "p1")
                self.assertIsNotNone(b.progress_hook)   # hook re-attached on rejoin
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)

    async def test_player_entry_to_settlement_via_progress_hook(self):
        from unittest.mock import patch
        from werewolf_web.run import GameSession
        sid = "campaign-settle"
        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                s = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                s.memory_dir = os.path.join(directory, "memory")
                s.campaign_profile = "p1"
                s.progress_hook = flow.progress_hook("p1", sid)
                await s._step_setup()
                s._checkpoint()                    # hook marks started (counts 1)
                s.engine.winner = "god"
                s.engine.end_reason = "win"
                with patch.object(s.host, "review", return_value="复盘"):
                    await s._step_endgame()        # finished -> hook settles
                archive = flow.load_profile("p1")
                self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)
                self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)
                self.assertEqual(archive["settled"], [sid])
                self.assertEqual(archive["unlocked"], 1)
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca

    async def test_abandon_then_restore_refuses_revival(self):
        from werewolf_web import run
        from werewolf_web.run import GameSession
        sid = "campaign-abandon"
        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                a.campaign_profile = "p1"
                await a._step_setup()
                a._checkpoint()
                flow.mark_started("p1", sid)
                # abandon settles the archive, but the checkpoint is NOT deleted
                flow.abandon_game("p1", sid)
                run.GAMES.pop(sid, None)
                b = await run.restore_game(sid)
                self.assertIsNone(b)   # an abandoned game must not revive
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)


class SettingsTest(unittest.TestCase):
    def test_save_and_load_drops_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(settings, "SETTINGS_PATH",
                              os.path.join(directory, "settings.json")):
                settings.save_settings({"model": "gpt-x", "api_key": "SECRET",
                                        "backend": "api", "max_calls": 100})
                loaded = settings.load_settings()
                self.assertNotIn("api_key", loaded)
                self.assertEqual(loaded["model"], "gpt-x")
                self.assertEqual(loaded["max_calls"], 100)

    def test_load_returns_none_when_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            with patch.object(settings, "SETTINGS_PATH", path):
                self.assertIsNone(settings.load_settings())
                settings.save_settings({"model": "m"})
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("garbage")
                self.assertIsNone(settings.load_settings())

    def test_runtime_kwargs_resolves_backend_and_options(self):
        # an api config saved without a backend field still resolves to api and
        # carries base_url / timeout / etc.
        kwargs = settings.runtime_kwargs({"model": "m", "base_url": "http://x", "timeout": 30})
        self.assertEqual(kwargs["backend"], "api")
        self.assertEqual(kwargs["options"]["base_url"], "http://x")
        self.assertEqual(kwargs["options"]["timeout"], 30)
        # a codex config carries model / effort / max_calls (and no options).
        kwargs = settings.runtime_kwargs({"backend": "codex", "model": "saved-model",
                                          "effort": "low", "max_calls": 17})
        self.assertEqual(kwargs["backend"], "codex")
        self.assertEqual(kwargs["model"], "saved-model")
        self.assertEqual(kwargs["effort"], "low")
        self.assertEqual(kwargs["max_calls"], 17)
        self.assertNotIn("options", kwargs)

    def test_runtime_kwargs_carries_api_key_in_memory_only(self):
        # The key reaches the runtime options (in-memory), but save_settings
        # (which sanitizes) never persists it.
        kwargs = settings.runtime_kwargs({"base_url": "http://x", "api_key": "FAKE_KEY"})
        self.assertEqual(kwargs["options"]["api_key"], "FAKE_KEY")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(settings, "SETTINGS_PATH", os.path.join(directory, "s.json")):
                settings.save_settings({"base_url": "http://x", "api_key": "FAKE_KEY"})
                self.assertNotIn("api_key", settings.load_settings())


class TerminalResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_campaign_passes_agent_command(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from werewolf_web import chat_game
        captured = {}
        planner = SimpleNamespace(verified=True, preflight=lambda: None,
                                  public_status=lambda: {})

        def fake_create_runtime(**kwargs):
            captured.update(kwargs)
            return planner

        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                with patch("werewolf_web.ai.decision_runtime.create_runtime", fake_create_runtime), \
                     patch("werewolf_web.settings.save_settings"), \
                     patch.object(chat_game, "_repl", return_value=0):
                    await chat_game.campaign_play("p1", False, "zh-CN", None,
                                                  backend="command",
                                                  agent_command=["codex", "exec"])
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca
        self.assertEqual(captured["backend"], "command")
        self.assertEqual(captured["command"], ["codex", "exec"])

    async def test_offline_campaign_is_not_counted(self):
        from unittest.mock import patch
        from werewolf_web import chat_game
        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                with patch.object(chat_game, "_repl", return_value=0):
                    await chat_game.campaign_play("p1", True, "zh-CN", None)  # offline
                archive = flow.load_profile("p1")
                self.assertIsNone(archive["current_game"])   # never registered
                self.assertEqual(archive["attempts"], {})     # never counted
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca

    async def test_terminal_resume_refuses_abandoned_campaign(self):
        import contextlib
        import io
        from werewolf_web import chat_game
        from werewolf_web.run import GameSession
        sid = "campaign-term-abandon"
        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                a = GameSession("classic", {"enabled": False}, session_id=sid,
                                seed=7, locale="zh-CN", player_role="civilian",
                                checkpoint_path=cp.checkpoint_path(sid))
                a.campaign_profile = "p1"
                await a._step_setup()
                a._checkpoint()
                flow.mark_started("p1", sid)
                flow.abandon_game("p1", sid)   # settled abandoned; save NOT deleted
                with contextlib.redirect_stdout(io.StringIO()):
                    result = await chat_game.play(None, None, True, "zh-CN",
                                                  resume_game_id=sid)
                self.assertEqual(result, 1)   # refused: abandoned must not revive
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca


class WebCampaignEntryTest(unittest.IsolatedAsyncioTestCase):
    async def test_web_campaign_start_offline_does_not_count(self):
        from werewolf_web import run

        class FakeReq:
            async def json(self):
                return {"profile_id": "p1", "role": "civilian", "locale": "zh-CN",
                        "llm": {"enabled": False}}

        with tempfile.TemporaryDirectory() as directory:
            old_cp, old_ca = cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            try:
                resp = await run.campaign_start(FakeReq())
                self.assertFalse(resp["counted"])
                archive = flow.load_profile("p1")
                self.assertIsNone(archive["current_game"])   # not registered
                self.assertEqual(archive["attempts"], {})     # not counted
                run.GAMES.pop(resp["game_id"], None)
            finally:
                cp.CHECKPOINTS_DIR, ca.CAMPAIGN_DIR = old_cp, old_ca


if __name__ == "__main__":
    unittest.main()
