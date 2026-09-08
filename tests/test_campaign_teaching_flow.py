"""Campaign teaching + post-loss short review wiring (§7 / milestone 5).

Session-level acceptance tests over the thin flow layer: persist-before-request,
budget survival across restore, cache hits costing nothing, and a review failure
that never undoes the already-settled campaign score.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import campaign_archive as ca
from werewolf_web import campaign_flow as flow
from werewolf_web import campaign_teaching as ct
from werewolf_web import checkpoint as cp
from werewolf_web.ai.decision_runtime import ModelTurnError
from werewolf_web.run import GameSession


class _Planner:
    """Fake decision runtime: records ``complete`` calls, honours ``reserve``."""

    def __init__(self, text="teach", max_calls=10, fail=False):
        self.text = text
        self.calls = 0
        self.max_calls = max_calls
        self.completed = 0
        self.fail = fail
        self.verified = True

    def reserve(self):
        if self.calls >= self.max_calls:
            raise ModelTurnError("budget exhausted")
        self.calls += 1

    def complete(self, request, schema):
        if self.fail:
            raise ModelTurnError("model down")
        self.completed += 1
        return {"text": self.text}

    def public_status(self):
        return {"mode": "model_decisions", "backend": "test", "model": "m",
                "calls": self.calls, "max_calls": self.max_calls}

    def snapshot(self):
        return {"backend": "test", "model": "m", "max_calls": self.max_calls,
                "timeout": 30, "calls": self.calls}

    def restore(self, data):
        self.calls = int(data.get("calls", 0))
        self.max_calls = int(data.get("max_calls", self.max_calls))


class _FlowBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        directory = self._tmp.name
        self._old_ca, self._old_cp, self._old_teach = (
            ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR, ct.TEACHING_PATH)
        ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
        cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
        ct.TEACHING_PATH = os.path.join(directory, "teaching.json")
        self.addCleanup(self._restore)

    def _restore(self):
        ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR, ct.TEACHING_PATH = (
            self._old_ca, self._old_cp, self._old_teach)

    def _session(self, session_id, planner, role="civilian"):
        return GameSession("classic", None, session_id=session_id, seed=7,
                           locale="zh-CN", player_role=role, planner=planner,
                           checkpoint_path=cp.checkpoint_path(session_id))


class TeachingWiringTest(_FlowBase):
    def test_persist_failure_does_not_send_model_request(self):
        planner = _Planner()
        session = self._session("t1", planner)

        def fail():
            raise OSError("disk full")
        session._checkpoint = fail

        with self.assertRaises(OSError):
            flow.generate_teaching(session, "civilian", "m")
        self.assertEqual(planner.completed, 0)   # complete() never called
        self.assertEqual(planner.calls, 1)       # reservation already consumed

    def test_cache_hit_consumes_no_budget(self):
        planner = _Planner()
        session = self._session("t3", planner)
        first = flow.generate_teaching(session, "civilian", "m")
        self.assertEqual(planner.calls, 1)
        second = flow.generate_teaching(session, "civilian", "m")
        self.assertEqual(planner.calls, 1)       # cache hit: no new reservation
        self.assertEqual(first["text"], second["text"])

    def test_resume_after_interrupt_does_not_roll_back_budget(self):
        planner = _Planner()
        session = self._session("t2", planner)
        flow.generate_teaching(session, "civilian", "m")
        session._checkpoint()                    # full interrupt snapshot
        self.assertEqual(planner.calls, 1)

        on_disk = cp.load_checkpoint(cp.checkpoint_path("t2"))
        self.assertEqual(on_disk["planner"]["calls"], 1)   # reservation persisted

        planner2 = _Planner()
        restored = self._session("t2", planner2)
        restored.restore(on_disk)
        self.assertEqual(planner2.calls, 1)      # not rolled back to 0
        self.assertEqual(planner2.calls, planner.calls)

    def test_teaching_failure_emits_unavailable_not_fake_text(self):
        planner = _Planner(fail=True)
        session = self._session("t4", planner)
        event = flow.generate_teaching(session, "civilian", "m")
        self.assertTrue(event["unavailable"])
        self.assertIn("重试", event["text"])
        self.assertEqual(planner.completed, 0)   # no model text produced
        types = [e["type"] for e in session._events]
        self.assertIn("teaching", types)


class ReviewWiringTest(_FlowBase):
    def test_review_skipped_when_not_a_loss(self):
        planner = _Planner()
        session = self._session("r1", planner)
        session.engine.winner = "god"            # civilian wins
        self.assertIsNone(flow.generate_campaign_review(session))
        self.assertEqual(planner.completed, 0)

        session2 = self._session("r2", planner)
        session2.engine.winner = "draw"
        self.assertIsNone(flow.generate_campaign_review(session2))

    def test_short_review_generates_on_loss(self):
        planner = _Planner(text="你第2天的票与翻牌矛盾。")
        session = self._session("r3", planner)
        session.engine.winner = "wolf"           # civilian loses
        event = flow.generate_campaign_review(session)
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "campaign_review")
        self.assertEqual(event["text"], "你第2天的票与翻牌矛盾。")
        self.assertEqual(planner.completed, 1)

    def test_review_material_has_only_committed_human_decisions(self):
        planner = _Planner(text="复盘")
        session = self._session("r-mixed", planner)
        session.engine.winner = "wolf"           # civilian loses
        session.decision_log = [
            {"slot": "human:vote:d1:vote", "result": {"target": 1}, "committed": True},
            {"slot": "human:night:n1:night", "result": {"target": 2}, "committed": False},
            {"slot": "vote:d1:Alice:vote", "result": {"target": 3}, "committed": True},
        ]
        captured = {}

        def fake_short_review(planner, decisions, facts, role, locale, persist=None):
            captured["decisions"] = decisions
            return "复盘文本"

        with patch.object(flow.campaign_teaching, "short_review", fake_short_review):
            event = flow.generate_campaign_review(session)
        self.assertEqual(event["type"], "campaign_review")
        # Only the committed human entry reaches the review request material.
        self.assertEqual([d["slot"] for d in captured["decisions"]],
                         ["human:vote:d1:vote"])
        self.assertTrue(captured["decisions"][0]["committed"])

    def test_explicit_retry_after_failed_review(self):
        planner = _Planner(fail=True)
        session = self._session("r-retry", planner)
        session.engine.winner = "wolf"           # civilian loses
        first = flow.generate_review_once(session)
        self.assertTrue(first["unavailable"])
        self.assertEqual(session.campaign_review_state, "unavailable")
        self.assertEqual(planner.completed, 0)
        # A failed review is never auto-retried by the once-guard.
        self.assertIsNone(flow.generate_review_once(session))
        # An explicit retry regenerates (charging budget) and flips state to done.
        planner.fail = False
        planner.text = "你第2天的票错了。"
        second = flow.generate_campaign_review(session)
        self.assertFalse(second.get("unavailable"))
        self.assertEqual(second["text"], "你第2天的票错了。")
        self.assertEqual(session.campaign_review_state, "done")
        self.assertEqual(planner.completed, 1)
        self.assertEqual(planner.calls, 2)   # reserve charged on both attempts


class ReviewOnceGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_restore_does_not_regenerate_review(self):
        sid = "review-once"
        planner = _Planner(text="复盘")
        with tempfile.TemporaryDirectory() as directory:
            old_ca, old_cp = ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                s = GameSession("classic", None, session_id=sid, seed=7,
                                locale="zh-CN", player_role="civilian",
                                planner=planner, checkpoint_path=cp.checkpoint_path(sid))
                s.memory_dir = os.path.join(directory, "memory")
                s.campaign_profile = "p1"
                s.progress_hook = flow.progress_hook("p1", sid)
                await s._step_setup()
                s._checkpoint()                    # marks started (counts 1)
                s.engine.winner = "wolf"
                s.engine.end_reason = "测试终局"
                with patch.object(s.host, "review", return_value="复盘"):
                    await s._step_endgame()        # settles + generates review once
                self.assertEqual(s.campaign_review_state, "done")
                self.assertEqual(planner.completed, 1)
                snapshot = s.snapshot()
                self.assertEqual(snapshot["campaign_review_state"], "done")

                # Restore into a fresh session with a fresh planner/hook, then run
                # the entry path again: a persisted "done" review must not re-run.
                planner2 = _Planner(text="复盘")
                t = GameSession("classic", None, session_id=sid, seed=7,
                                locale="zh-CN", player_role="civilian",
                                planner=planner2, checkpoint_path=cp.checkpoint_path(sid))
                t.restore(snapshot)
                self.assertEqual(t.campaign_review_state, "done")
                flow.resume("p1", sid, t)          # re-attach hook (settle idempotent)
                self.assertIsNone(flow.generate_review_once(t))
                self.assertEqual(planner2.completed, 0)   # no double-spend
            finally:
                ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR = old_ca, old_cp


class TerminalReviewRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_review_command_retries_failed_review(self):
        import contextlib
        import io
        from types import SimpleNamespace
        from werewolf_web import chat_game
        session = SimpleNamespace(
            campaign_profile="p1", finished=True, faulted=False,
            engine=SimpleNamespace(locale="zh-CN", player_role="civilian", winner="wolf"),
            campaign_review_state="unavailable",
        )
        rendered = []
        with patch.object(flow, "review_applies", return_value=True), \
             patch.object(flow, "generate_review_once", return_value=None), \
             patch.object(flow, "generate_campaign_review",
                          return_value={"type": "campaign_review", "text": "新复盘", "winner": "wolf"}), \
             patch.object(chat_game, "_render", side_effect=lambda ev, loc: rendered.append(ev)), \
             patch("builtins.input", side_effect=["/review", "q"]):
            with contextlib.redirect_stdout(io.StringIO()):
                await chat_game._campaign_review_repl(session)
        self.assertEqual([ev["text"] for ev in rendered], ["新复盘"])


class ReviewHookTest(unittest.IsolatedAsyncioTestCase):
    async def test_review_failure_does_not_affect_settled_score(self):
        sid = "review-fail"
        planner = _Planner(fail=True)
        with tempfile.TemporaryDirectory() as directory:
            old_ca, old_cp = ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                s = GameSession("classic", None, session_id=sid, seed=7,
                                locale="zh-CN", player_role="civilian",
                                planner=planner,
                                checkpoint_path=cp.checkpoint_path(sid))
                s.memory_dir = os.path.join(directory, "memory")
                s.campaign_profile = "p1"
                s.progress_hook = flow.progress_hook("p1", sid)
                await s._step_setup()
                s._checkpoint()                  # marks started (counts 1)
                s.engine.winner = "wolf"         # civilian loses
                s.engine.end_reason = "测试终局"
                with patch.object(s.host, "review", return_value="复盘"):
                    await s._step_endgame()      # finished -> hook settles + review fails

                archive = flow.load_profile("p1")
                self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)
                self.assertEqual(archive["attempts"]["civilian"]["losses"], 1)
                self.assertEqual(archive["settled"], [sid])
                self.assertTrue(s.finished)
                # The failed review is an explicit unavailable marker, not a reset.
                reviews = [e for e in s._events if e.get("type") == "campaign_review"]
                self.assertEqual(len(reviews), 1)
                self.assertTrue(reviews[0].get("unavailable"))
                self.assertEqual(planner.calls, 1)   # the review reserved, then failed
            finally:
                ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR = old_ca, old_cp


class TeachingRetryWiringTest(_FlowBase):
    def test_teaching_retry_does_not_reregister_attempt(self):
        planner = _Planner()
        flow.begin_attempt("p1", "g1", "civilian", "classic")
        session = self._session("g1", planner)
        session.campaign_profile = "p1"
        session.progress_hook = flow.progress_hook("p1", "g1")
        before = flow.load_profile("p1")
        flow.generate_teaching(session, "civilian", "m")   # first-entry teaching (undealt engine)
        after = flow.load_profile("p1")
        self.assertEqual(after["current_game"], before["current_game"])
        self.assertEqual(after["attempts"], {})
        self.assertEqual(after["settled"], [])

    def test_teaching_retry_cache_hit_consumes_no_budget(self):
        planner = _Planner()
        session = self._session("g2", planner)
        session.campaign_profile = "p1"
        first = flow.generate_teaching(session, "civilian", "m")
        calls = planner.calls
        second = flow.generate_teaching(session, "civilian", "m")   # retry: cache hit
        self.assertEqual(planner.calls, calls)
        self.assertEqual(second["text"], first["text"])


class TeachingEndpointRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_teaching_endpoint_retry_does_not_reregister_or_double_spend(self):
        from werewolf_web import run
        sid = "teach-web"
        planner = _Planner()
        with tempfile.TemporaryDirectory() as directory:
            old_ca, old_cp, old_teach = ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR, ct.TEACHING_PATH
            ca.CAMPAIGN_DIR = os.path.join(directory, "campaign")
            cp.CHECKPOINTS_DIR = os.path.join(directory, "checkpoints")
            ct.TEACHING_PATH = os.path.join(directory, "teaching.json")
            try:
                flow.begin_attempt("p1", sid, "civilian", "classic")
                session = GameSession("classic", None, session_id=sid, seed=7,
                                      locale="zh-CN", player_role="civilian",
                                      planner=planner,
                                      checkpoint_path=cp.checkpoint_path(sid))
                session.campaign_profile = "p1"
                session.progress_hook = flow.progress_hook("p1", sid)
                run.GAMES[sid] = session
                before = flow.load_profile("p1")
                result = await run.campaign_teaching(game_id=sid)
                after = flow.load_profile("p1")
                self.assertTrue(result["ok"])
                self.assertFalse(result.get("unavailable"))
                # The teaching request never re-registers the attempt: the archive
                # association and counters are untouched.
                self.assertEqual(after["current_game"], before["current_game"])
                self.assertEqual(after["attempts"], {})
                self.assertEqual(after["settled"], [])
                # A second (cache-hit) retry consumes no further budget.
                calls = planner.calls
                await run.campaign_teaching(game_id=sid)
                self.assertEqual(planner.calls, calls)
            finally:
                ca.CAMPAIGN_DIR, cp.CHECKPOINTS_DIR, ct.TEACHING_PATH = old_ca, old_cp, old_teach
                run.GAMES.pop(sid, None)
                run._RESTORE_LOCKS.pop(sid, None)


class TerminalTeachingCommandTest(unittest.TestCase):
    def test_teaching_command_regenerates_and_renders_inline(self):
        from types import SimpleNamespace
        from werewolf_web import chat_game
        session = SimpleNamespace(
            campaign_profile="p1",
            engine=SimpleNamespace(locale="zh-CN", player_role="civilian"),
            planner=SimpleNamespace(model="m"),
        )
        rendered = []
        with patch.object(flow, "generate_teaching",
                          return_value={"type": "teaching", "role": "civilian", "text": "教学"}) as gen, \
             patch.object(chat_game, "_render", side_effect=lambda ev, loc: rendered.append(ev)):
            self.assertTrue(chat_game._teaching_command(session))
        # Rendered inline (publish=False) so the live REPL loop does not double-render.
        gen.assert_called_once_with(session, "civilian", "m", publish=False)
        self.assertEqual(rendered, [{"type": "teaching", "role": "civilian", "text": "教学"}])

    def test_teaching_command_is_a_noop_outside_a_campaign(self):
        from types import SimpleNamespace
        from werewolf_web import chat_game
        session = SimpleNamespace(
            campaign_profile=None,
            engine=SimpleNamespace(locale="zh-CN", player_role="civilian"),
            planner=SimpleNamespace(model="m"),
        )
        self.assertFalse(chat_game._teaching_command(session))


if __name__ == "__main__":
    unittest.main()
