import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from werewolf_web import restore_coordinator as coordinator


class RestoreCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    def port(self):
        trace = []
        session = SimpleNamespace(
            session_id="g1", campaign_profile="profile",
            restore=lambda payload: trace.append("restore"),
            planner=SimpleNamespace(reserve=lambda: trace.append("reserve"),
                                    preflight_check=lambda: trace.append("preflight")),
            _checkpoint=lambda: trace.append("save"))
        def reconcile(*args):
            self.assertEqual(args, ("profile", "g1", session))
            trace.append("campaign")
            return True
        return session, trace, reconcile

    async def test_ordering(self):
        session, trace, reconcile = self.port()
        self.assertTrue(await coordinator.restore_and_verify(session, {}, resume_campaign=reconcile))
        self.assertEqual(trace, ["restore", "campaign", "reserve", "save", "preflight"])

    async def test_validation_failure_never_reconciles_or_calls_model(self):
        session, trace, reconcile = self.port()
        session.restore = Mock(side_effect=ValueError("bad save"))
        with self.assertRaises(ValueError):
            await coordinator.restore_and_verify(session, {}, resume_campaign=reconcile)
        self.assertEqual(trace, [])

    async def test_refused_campaign_spends_nothing(self):
        session, trace, _ = self.port()
        self.assertFalse(await coordinator.restore_and_verify(
            session, {}, resume_campaign=lambda *args: False))
        self.assertEqual(trace, ["restore"])

    async def test_failed_budget_save_prevents_preflight(self):
        session, trace, reconcile = self.port()
        session._checkpoint = Mock(side_effect=OSError("disk"))
        with self.assertRaises(OSError):
            await coordinator.restore_and_verify(session, {}, resume_campaign=reconcile)
        self.assertEqual(trace, ["restore", "campaign", "reserve"])

    async def test_offline_restore_skips_model_but_not_campaign(self):
        session, trace, reconcile = self.port()
        session.planner = None
        self.assertTrue(await coordinator.restore_and_verify(session, {}, resume_campaign=reconcile))
        self.assertEqual(trace, ["restore", "campaign"])

    def test_runtime_configuration_never_takes_command_or_endpoint_from_save(self):
        payload = {"driver": "agent", "adapter": "command", "planner": {},
                   "command": ["untrusted"], "base_url": "https://untrusted.invalid"}
        saved = {"command": ["trusted"]}
        with patch.object(coordinator.driver_mod, "restore_runtime_kwargs",
                          return_value={"backend": "command"}) as helper:
            result = coordinator.runtime_kwargs(payload, saved, command=["cli"],
                                                model="m", effort="high", max_calls=50)
        helper.assert_called_once_with("agent", "command", saved, command=["cli"])
        self.assertEqual(result, {"backend": "command", "model": "m",
                                  "effort": "high", "max_calls": 50})
