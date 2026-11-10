import json
import os
import tempfile
import time
import unittest

from mobile import Controller
from werewolf_web.offline_game import action_choices


class MobileBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.controller = Controller(self.tmp.name)

    def tearDown(self):
        self.controller.request("pause", {})
        self.controller.loop.call_soon_threadsafe(self.controller.loop.stop)
        self.controller.thread.join(5)
        self.controller.loop.close()
        self.tmp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            view = self.controller.read()
            if view["status"] in ("waiting", "error", "finished"):
                self.assertNotEqual(view["status"], "error", view.get("error"))
                return view
            time.sleep(.02)
        self.fail("Mobile engine did not reach a player boundary")

    def test_setup_public_boundary_and_catalog(self):
        catalog = self.controller.request("catalog", {"locale": "en"})
        self.assertEqual(len(catalog["characters"]), 30)
        self.controller.request("start", {"locale": "en", "role": "civilian"})
        view = self.wait()
        self.assertEqual(view["pending"]["kind"], "ready")
        self.assertEqual(len(view["table"]["seats"]), 12)
        for seat in view["table"]["seats"]:
            self.assertNotIn("role", seat)
            self.assertNotIn("is_wolf", seat)
        self.assertEqual(view["private"]["role"], "civilian")
        self.assertNotIn("payload", view["pending"]["choices"][0])
        self.assertNotIn("brain", json.dumps(view))

    def test_pause_resume_preserves_prompt_and_rejects_stale_duplicate(self):
        self.controller.request("start", {"role": "civilian"})
        first = self.wait()["pending"]
        self.controller.request("pause", {})
        self.controller.request("resume", {})
        same = self.wait()["pending"]
        self.assertEqual(first["request_id"], same["request_id"])
        self.assertFalse(self.controller.request("choose", {"choice_id": "ready", "request_id": "bad"})["accepted"])
        args = {"choice_id": "ready", "request_id": same["request_id"]}
        self.assertTrue(self.controller.request("choose", args)["accepted"])
        self.assertFalse(self.controller.request("choose", args)["accepted"])
        self.wait()

    def test_corrupt_save_is_not_overwritten_on_resume(self):
        with open(self.controller.path, "w") as handle:
            handle.write("not a save")
        with self.assertRaises(Exception):
            self.controller.request("resume", {})
        with open(self.controller.path) as handle:
            self.assertEqual(handle.read(), "not a save")

    def test_start_requires_replacement_authority(self):
        self.controller.request("start", {})
        self.wait()
        with self.assertRaises(ValueError):
            self.controller.request("start", {})

    def test_night_action_retains_engine_purpose_after_resume(self):
        self.controller.request("start", {"role": "seer", "locale": "en"})
        ready = self.wait()["pending"]
        self.controller.request("choose", {"choice_id": "ready", "request_id": ready["request_id"]})
        night = self.wait()["pending"]
        self.assertEqual(night["kind"], "night")
        self.assertEqual(night["data"]["role_key"], "seer")
        self.assertTrue(night["data"]["role"])
        self.assertTrue(night["data"]["desc"])
        self.controller.request("pause", {})
        self.controller.request("resume", {})
        self.assertEqual(night, self.wait()["pending"])

    def test_full_game_through_native_protocol_and_finished_resume(self):
        self.controller.request("start", {"role": "civilian", "locale": "en"})
        for step in range(150):
            view = self.wait()
            if view["status"] == "finished":
                break
            pending = view["pending"]
            # Synthetic player policy, accessed only by this test, not by the UI.
            game = self.controller.game
            options = action_choices(game, pending["kind"], pending["data"])
            choice = game.auto_choice(pending["kind"], pending["data"], options)
            self.assertTrue(self.controller.request("choose", {
                "choice_id": choice["id"], "request_id": pending["request_id"]})["accepted"])
        else:
            self.fail("Game exceeded bounded number of player decisions")
        self.assertTrue(view["finished"])
        numbers = [row["event_no"] for row in view["events"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.controller.request("pause", {})
        self.controller.request("resume", {})
        recovered = self.wait()
        self.assertTrue(recovered["finished"])
        self.assertEqual(view["table"], recovered["table"])


if __name__ == "__main__":
    unittest.main()
