"""Role teaching + short review (§7): model-generated, cached, fail-closed,
budget-reserved, and fed by deterministic rules."""
import os
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web import campaign_teaching as ct
from werewolf_web.ai.decision_runtime import ModelTurnError


class _RecordingPlanner:
    def __init__(self, response, max_calls=10):
        self.response = response
        self.calls = 0
        self.max_calls = max_calls
        self.requests = []

    def reserve(self):
        if self.calls >= self.max_calls:
            raise ModelTurnError("budget exhausted")
        self.calls += 1

    def complete(self, request, schema):
        self.requests.append(request)
        return dict(self.response)


class RoleTeachingTest(unittest.TestCase):
    def test_generates_and_returns_text(self):
        planner = _RecordingPlanner({"text": " 你是平民，靠发言与票型找狼。  "})
        self.assertEqual(ct.role_teaching(planner, "civilian", "zh-CN"),
                         "你是平民，靠发言与票型找狼。")
        self.assertEqual(planner.calls, 1)   # one reserved call

    def test_request_carries_deterministic_rules(self):
        planner = _RecordingPlanner({"text": "x"})
        ct.role_teaching(planner, "witch", "zh-CN")
        rules = planner.requests[0]["rules"]
        self.assertIn("解药", rules["role_rules"])
        self.assertIn("毒", rules["role_rules"])
        self.assertEqual(rules["win_side"], "god")
        self.assertEqual(rules["goal"], "权衡技能与身份暴露")

    def test_guard_rules_include_consecutive_limit(self):
        planner = _RecordingPlanner({"text": "x"})
        ct.role_teaching(planner, "guard", "zh-CN")
        self.assertIn("连续", planner.requests[0]["rules"]["role_rules"])

    def test_rejects_a_non_level_role(self):
        with self.assertRaises(ValueError):
            ct.role_teaching(_RecordingPlanner({"text": "x"}), "not_a_role", "zh-CN")

    def test_fails_closed_on_empty_text(self):
        with self.assertRaises(ModelTurnError):
            ct.role_teaching(_RecordingPlanner({"text": "   "}), "civilian", "zh-CN")

    def test_zero_budget_does_not_call_model(self):
        planner = _RecordingPlanner({"text": "x"}, max_calls=0)
        with self.assertRaises(ModelTurnError):
            ct.role_teaching(planner, "civilian", "zh-CN")
        self.assertEqual(planner.requests, [])   # complete() never called
        self.assertEqual(planner.calls, 0)

    def test_short_review_reserves_and_returns_text(self):
        planner = _RecordingPlanner({"text": "你第2天的票与翻牌矛盾。"})
        self.assertEqual(ct.short_review(planner, [], [], "civilian", "zh-CN"),
                         "你第2天的票与翻牌矛盾。")
        self.assertEqual(planner.calls, 1)

    def test_material_has_win_conditions(self):
        material = ct.teaching_material("civilian", "zh-CN")
        self.assertIn("win_conditions", material)
        self.assertIn("好人", material["win_conditions"]["god"])
        self.assertIn("狼人", material["win_conditions"]["wolf"])

    def test_missing_reserve_is_not_silently_bypassed(self):
        from types import SimpleNamespace
        planner = SimpleNamespace(complete=lambda request, schema: {"text": "x"})
        with self.assertRaises(ModelTurnError):
            ct.role_teaching(planner, "civilian", "zh-CN")

    def test_persist_runs_after_reserve_before_request(self):
        planner = _RecordingPlanner({"text": "x"})
        seen = {}

        def persist():
            seen["calls"] = planner.calls
            seen["requests"] = len(planner.requests)

        ct.role_teaching(planner, "civilian", "zh-CN", persist=persist)
        self.assertEqual(seen["calls"], 1)       # reserved before persist
        self.assertEqual(seen["requests"], 0)    # not yet requested
        self.assertEqual(len(planner.requests), 1)

    def test_persist_failure_does_not_send_request(self):
        planner = _RecordingPlanner({"text": "x"})

        def fail():
            raise OSError("disk full")

        with self.assertRaises(OSError):
            ct.role_teaching(planner, "civilian", "zh-CN", persist=fail)
        self.assertEqual(planner.requests, [])   # complete never called
        self.assertEqual(planner.calls, 1)       # reservation already consumed


class TeachingCacheTest(unittest.TestCase):
    def test_cached_teaching_is_generated_once(self):
        planner = _RecordingPlanner({"text": "teach"})
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ct, "TEACHING_PATH", os.path.join(directory, "t.json")):
                first = ct.cached_role_teaching(planner, "civilian", "zh-CN", "model-x")
                second = ct.cached_role_teaching(planner, "civilian", "zh-CN", "model-x")
        self.assertEqual(first, "teach")
        self.assertEqual(second, "teach")
        self.assertEqual(planner.calls, 1)   # cache hit costs no call

    def test_cache_invalidates_when_material_changes(self):
        planner = _RecordingPlanner({"text": "teach"})
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ct, "TEACHING_PATH", os.path.join(directory, "t.json")):
                ct.cached_role_teaching(planner, "civilian", "zh-CN", "m")
                with patch.object(ct, "teaching_material", return_value={"role_rules": "NEW_RULE"}):
                    ct.cached_role_teaching(planner, "civilian", "zh-CN", "m")
        self.assertEqual(len(planner.requests), 2)   # regenerated after material change


if __name__ == "__main__":
    unittest.main()
