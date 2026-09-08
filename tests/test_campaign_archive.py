"""Campaign archive (§5): atomic store, attempt registration, idempotent
settlement keyed by game_id, and crash catch-up from validated checkpoints."""
import os
import stat
import tempfile
import unittest
from copy import deepcopy

from werewolf_web import campaign_archive as ca
from werewolf_web.campaign import LEVELS


def _checkpoint(role, board, winner, finished=True, day=3, night=3, session_id="g1",
                seats=None):
    return {"session_id": session_id, "finished": finished,
            "engine": {"player_role": role, "board_id": board, "winner": winner,
                       "day_count": day, "night_count": night,
                       "seats": seats if seats is not None else [{"pos": 1} for _ in range(12)]}}


class ArchiveStoreTest(unittest.TestCase):
    def test_round_trip_and_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "arc.json")
            archive = ca.new_archive("p1")
            ca.save_archive(path, archive)
            self.assertFalse(os.path.exists(path + ".tmp"))
            self.assertEqual(ca.load_archive(path), archive)

    def test_int_keyed_payload_does_not_fail_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "arc.json")
            ca.save_archive(path, {"config": {"votes": {2: 1, 10: 2}}})
            self.assertEqual(ca.load_archive(path)["config"]["votes"],
                             {"2": 1, "10": 2})

    def test_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sub", "arc.json")
            ca.save_archive(path, ca.new_archive())
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)

    def test_corruption_is_an_explicit_error(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "arc.json")
            ca.save_archive(path, ca.new_archive())
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            data["payload"]["unlocked"] = 99
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            with self.assertRaises(ValueError):
                ca.load_archive(path)


class AttemptRegistrationTest(unittest.TestCase):
    def test_register_is_preparing_and_not_counted(self):
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", "civilian", "classic",
                            config={"npc_driver": "api", "model": "m"})
        self.assertEqual(archive["current_game"]["state"], "preparing")
        self.assertEqual(archive["attempts"], {})   # nothing counted yet

    def test_config_snapshot_whitelists_and_deepcopies(self):
        archive = ca.new_archive()
        config = {"model": "gpt-x", "api_key": "SECRET", "backend": "api", "max_calls": 100}
        ca.register_attempt(archive, "g1", "civilian", "classic", config=config)
        snap = archive["config"]
        self.assertNotIn("api_key", snap)           # credential never stored
        self.assertEqual(snap["model"], "gpt-x")
        config["model"] = "changed"                 # external mutation
        self.assertEqual(snap["model"], "gpt-x")    # snapshot is independent

    def test_mark_in_progress_counts_exactly_once(self):
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", "civilian", "classic")
        ca.mark_in_progress(archive, "g1")
        ca.mark_in_progress(archive, "g1")          # idempotent
        self.assertEqual(archive["current_game"]["state"], "in_progress")
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)

    def test_mark_in_progress_ignores_unknown_game(self):
        archive = ca.new_archive()
        ca.mark_in_progress(archive, "not-registered")
        self.assertEqual(archive["attempts"], {})

    def test_register_rejects_non_level_role(self):
        before = deepcopy(ca.new_archive())
        archive = ca.new_archive()
        with self.assertRaises(ValueError):
            ca.register_attempt(archive, "g1", "not_a_role", "classic")
        self.assertEqual(archive, before)

    def test_register_rejects_not_unlocked_role(self):
        before = deepcopy(ca.new_archive())
        archive = ca.new_archive()
        with self.assertRaises(ValueError):
            ca.register_attempt(archive, "g1", "seer", "classic")  # level 1, not unlocked
        self.assertEqual(archive, before)

    def test_register_rejects_wrong_board(self):
        before = deepcopy(ca.new_archive())
        archive = ca.new_archive()
        with self.assertRaises(ValueError):
            ca.register_attempt(archive, "g1", "civilian", "wolf_king")
        self.assertEqual(archive, before)

    def test_register_rejects_when_in_progress(self):
        # A live (counted) attempt must not be silently overwritten; a stale
        # `preparing` (never counted) is replaceable.
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", "civilian", "classic")
        ca.mark_in_progress(archive, "g1")
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.register_attempt(archive, "g2", "civilian", "classic")
        self.assertEqual(archive, before)

    def test_register_config_error_leaves_archive_unchanged(self):
        # A bad config must be rejected BEFORE the association is written.
        archive = ca.new_archive()
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.register_attempt(archive, "g1", "civilian", "classic", config=[])
        self.assertEqual(archive, before)


class SettlementTest(unittest.TestCase):
    def _active(self, role="civilian", board="classic"):
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", role, board)
        ca.mark_in_progress(archive, "g1")
        return archive

    def test_settle_is_idempotent_by_game_id(self):
        archive = self._active()
        ca.settle(archive, "g1", result="lost", winner="wolf", rounds=4)
        ca.settle(archive, "g1", result="lost", winner="wolf", rounds=4)  # no-op
        stats = archive["attempts"]["civilian"]
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["attempts"], 1)
        self.assertEqual(len(archive["completions"]), 1)
        self.assertEqual(archive["settled"], ["g1"])
        self.assertIsNone(archive["current_game"])

    def test_settle_rejects_wrong_game_id(self):
        archive = self._active()
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.settle(archive, "other-game", result="won", winner="god")
        self.assertEqual(archive, before)   # archive unchanged on rejection

    def test_settle_rejects_contradictory_winner(self):
        # A civilian (good side) cannot "win" when the wolves won.
        archive = self._active("civilian")
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.settle(archive, "g1", result="won", winner="wolf")
        self.assertEqual(archive, before)

    def test_settle_rejects_win_on_a_preparing_attempt(self):
        # A fresh attempt is still preparing (0 counted attempts): settling a
        # win must be rejected, not produce 0 attempts + 1 win.
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", "civilian", "classic")
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.settle(archive, "g1", result="won", winner="god")
        self.assertEqual(archive, before)

    def test_win_unlocks_the_next_level(self):
        archive = self._active("civilian")          # level 0
        ca.settle(archive, "g1", result="won", winner="god", rounds=2)
        self.assertEqual(archive["unlocked"], 1)
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)

    def test_win_on_last_level_does_not_overflow(self):
        role = LEVELS[-1]["role"]
        board = LEVELS[-1]["board"]
        archive = ca.new_archive()
        archive["unlocked"] = len(LEVELS) - 1   # unlock the whole track first
        ca.register_attempt(archive, "g1", role, board)
        ca.mark_in_progress(archive, "g1")
        ca.settle(archive, "g1", result="won", winner="god", rounds=1)   # bomber is good-side
        self.assertEqual(archive["unlocked"], len(LEVELS) - 1)

    def test_draw_and_abandoned_are_recorded_separately(self):
        archive = self._active()
        ca.settle(archive, "g1", result="draw", winner="draw", rounds=3)
        self.assertEqual(archive["attempts"]["civilian"]["draws"], 1)
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 0)
        self.assertEqual(archive["unlocked"], 0)

        archive2 = self._active()
        ca.settle(archive2, "g1", result="abandoned", rounds=1)
        self.assertEqual(archive2["attempts"]["civilian"]["abandoned"], 1)


class WinMappingTest(unittest.TestCase):
    def test_result_for_maps_faction_winner_to_player_result(self):
        self.assertEqual(ca.result_for("god", "civilian"), "won")
        self.assertEqual(ca.result_for("wolf", "werewolf"), "won")
        self.assertEqual(ca.result_for("wolf", "civilian"), "lost")
        self.assertEqual(ca.result_for("god", "werewolf"), "lost")
        self.assertEqual(ca.result_for("draw", "civilian"), "draw")

    def test_result_for_rejects_undecided_winner(self):
        with self.assertRaises(ValueError):
            ca.result_for(None, "civilian")


class ReconcileTest(unittest.TestCase):
    def _registered(self, role="civilian", board="classic", state="in_progress"):
        archive = ca.new_archive()
        ca.register_attempt(archive, "g1", role, board)
        if state == "in_progress":
            ca.mark_in_progress(archive, "g1")
        return archive

    def test_reconcile_settles_ended_but_not_recorded(self):
        archive = self._registered()
        ca.reconcile(archive, "g1", checkpoint=_checkpoint("civilian", "classic", "god"))
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)
        self.assertEqual(archive["settled"], ["g1"])

    def test_reconcile_is_idempotent(self):
        archive = self._registered()
        cp = _checkpoint("civilian", "classic", "god")
        ca.reconcile(archive, "g1", checkpoint=cp)
        ca.reconcile(archive, "g1", checkpoint=cp)
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)

    def test_reconcile_counts_attempt_before_terminal(self):
        # Crash between register and mark_in_progress, yet the game already ended:
        # reconcile must count the attempt AND settle the win — never 0 attempts
        # with 1 win.
        archive = self._registered(state="preparing")
        ca.reconcile(archive, "g1", checkpoint=_checkpoint("civilian", "classic", "god"))
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)
        self.assertEqual(archive["attempts"]["civilian"]["wins"], 1)

    def test_reconcile_unfinished_game_counts_attempt_only(self):
        archive = self._registered(state="preparing")
        ca.reconcile(archive, "g1",
                     checkpoint=_checkpoint("civilian", "classic", None, finished=False))
        self.assertEqual(archive["current_game"]["state"], "in_progress")
        self.assertEqual(archive["attempts"]["civilian"]["attempts"], 1)
        self.assertEqual(archive["settled"], [])

    def test_reconcile_drops_stale_preparing(self):
        archive = self._registered(state="preparing")
        ca.reconcile(archive, "g1", checkpoint=None)
        self.assertIsNone(archive["current_game"])
        self.assertEqual(archive["attempts"], {})

    def test_reconcile_rejects_identity_mismatch(self):
        archive = self._registered()
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.reconcile(archive, "g1", checkpoint=_checkpoint("seer", "classic", "god"))
        self.assertEqual(archive, before)   # archive unchanged on rejection

    def test_reconcile_rejects_undecided_winner(self):
        archive = self._registered()
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.reconcile(archive, "g1", checkpoint=_checkpoint("civilian", "classic", None))
        self.assertEqual(archive, before)   # archive unchanged on rejection

    def test_reconcile_rejects_wrong_session_id(self):
        # Another game's checkpoint (same role/board) must not settle this one.
        archive = self._registered()
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.reconcile(archive, "g1",
                         checkpoint=_checkpoint("civilian", "classic", "god", session_id="other-game"))
        self.assertEqual(archive, before)

    def test_reconcile_uninitialized_checkpoint_is_a_no_op(self):
        # A valid save whose engine was never dealt: still preparing — no count,
        # no settle, no error.
        archive = self._registered(state="preparing")
        before = deepcopy(archive)
        ca.reconcile(archive, "g1",
                     checkpoint=_checkpoint("civilian", "classic", None,
                                            finished=False, seats=[]))
        self.assertEqual(archive, before)

    def test_reconcile_rejects_malformed_checkpoint(self):
        # Missing player_role/board in the engine is a malformed save, not an
        # uninitialized one — it must be refused and leave the archive unchanged.
        archive = self._registered(state="preparing")
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.reconcile(archive, "g1",
                         checkpoint={"session_id": "g1", "finished": False,
                                     "engine": {"seats": []}})
        self.assertEqual(archive, before)

    def test_reconcile_unfinished_checkpoint_still_validates_identity(self):
        # Identity checks run even for unfinished checkpoints — no count on a
        # mismatched session_id.
        archive = self._registered(state="preparing")
        before = deepcopy(archive)
        with self.assertRaises(ValueError):
            ca.reconcile(archive, "g1",
                         checkpoint=_checkpoint("civilian", "classic", None,
                                                finished=False, session_id="other-game"))
        self.assertEqual(archive, before)


if __name__ == "__main__":
    unittest.main()
