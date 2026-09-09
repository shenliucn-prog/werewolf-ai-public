"""§8.3 atomic commit: pending action ↔ request event, the endgame finale, and
speech persistence-before-publication.

P1 gaps the review flagged:
- ``emit()`` wrote the request event and its ``pending_event_no`` *after* the
  pre-prompt checkpoint, so a crash while the player was deciding restored a
  pending action with no event number (state and event ledger inconsistent).
- endgame's ``review``/``gameover`` and ``finished=True`` had no final commit,
  so a restart re-presented a finished game as still running.
- a speech (or election speech) entered the live queue *before* its state, cursor
  and event were checkpointed, so a crash could lose content the player already
  saw (Shawn's repro: queue held the 2nd speech while disk held only the 1st).
"""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from werewolf_web.checkpoint import load_checkpoint
from werewolf_web.run import GameSession


class _RecordingQueue(asyncio.Queue):
    """A live queue that invokes a callback before each ``put_nowait``."""

    def __init__(self, on_publish):
        super().__init__()
        self._on_publish = on_publish

    def put_nowait(self, item):
        self._on_publish(item)
        super().put_nowait(item)


class PendingActionAtomicTest(unittest.IsolatedAsyncioTestCase):
    async def test_pending_action_and_request_event_commit_together(self):
        session = GameSession("classic", {"enabled": False}, session_id="atomic-pending")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            session._current_step = "speeches"
            task = asyncio.create_task(
                session.ask_player("speech", {"phase": "day 1"}))
            try:
                while True:
                    event = await asyncio.wait_for(session.event_q.get(), 2)
                    if event["type"] == "request":
                        break
                on_disk = load_checkpoint(session.checkpoint_path)
                # The pending action, its event number and the request event are
                # one atomic commit — never a pending action without an event_no.
                self.assertEqual(on_disk["pending"],
                                 {"kind": "speech", "data": {"phase": "day 1"}})
                self.assertIsNotNone(on_disk["pending_event_no"])
                requests = [e for e in on_disk["events"] if e["type"] == "request"]
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["event_no"], on_disk["pending_event_no"])
                self.assertEqual(requests[0]["kind"], "speech")
            finally:
                task.cancel()


class EndgameFinalCommitTest(unittest.IsolatedAsyncioTestCase):
    async def test_endgame_commits_finished_and_terminal_events(self):
        session = GameSession("classic", {"enabled": False}, session_id="atomic-endgame",
                              seed=7, locale="zh-CN", player_role="civilian")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            await session._step_setup()
            session.engine.winner = "wolf"
            session.engine.end_reason = "测试终局"
            # review() would write a runtime review file; keep the test hermetic.
            with patch.object(session.host, "review", return_value="复盘文本"):
                await session._step_endgame()

            on_disk = load_checkpoint(session.checkpoint_path)
            self.assertTrue(on_disk["finished"])
            self.assertIsNone(on_disk["step"])
            types = [e["type"] for e in on_disk["events"]]
            self.assertIn("review", types)
            self.assertIn("gameover", types)


class SpeechPersistenceOrderTest(unittest.IsolatedAsyncioTestCase):
    """§8.3: a speech must be durable on disk *before* it reaches the queue."""

    async def test_speech_event_is_durable_before_it_is_published(self):
        session = GameSession("classic", {"enabled": False}, session_id="atomic-speech-order")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            session._current_step = "speeches"
            published = []

            def on_publish(event):
                if event.get("type") == "speech":
                    on_disk = load_checkpoint(session.checkpoint_path)
                    disk_nos = {e["event_no"] for e in on_disk["events"]
                                if e.get("type") == "speech"}
                    published.append(event["event_no"] in disk_nos)

            session._event_q = _RecordingQueue(on_publish)

            # The speech paths (main, election, table) all follow this sequence:
            # record -> checkpoint -> publish.
            session.emit({"type": "speech", "seat": 1, "name": "A", "text": "first"},
                         publish=False)
            session._checkpoint()
            session._flush_publish()
            session.emit({"type": "speech", "seat": 2, "name": "B", "text": "second"},
                         publish=False)
            session._checkpoint()
            session._flush_publish()

            # Every published speech was already on disk at the instant it became
            # visible — never the reverse (queue ahead of the ledger).
            self.assertEqual(published, [True, True])
            disk_speeches = [e for e in load_checkpoint(session.checkpoint_path)["events"]
                             if e.get("type") == "speech"]
            self.assertEqual([e["text"] for e in disk_speeches], ["first", "second"])

    async def test_election_speech_is_durable_before_it_is_published(self):
        """Shawn's repro, driven through the real 竞选发言 path.

        Two NPC candidates speak; the human seat is excluded from the candidacy
        list (no prompt), and ``ask_player`` is stubbed so the sheriff vote
        phase never blocks.  Each election speech must be on disk before it is
        handed to the live queue.
        """
        session = GameSession("classic", {"enabled": False},
                              session_id="atomic-election-speech",
                              seed=7, locale="zh-CN", player_role="civilian")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            await session._step_setup()
            npc_positions = [s.pos for s in session.engine.alive_seats()
                             if not s.is_player][:2]
            session._step_state["election_phase"] = 1
            session._step_state["election_up"] = npc_positions
            session._step_state["election_speeches"] = []
            session._step_state["election_cursor"] = 0

            async def stub_player(*args, **kwargs):
                return {"target": None, "text": "", "up": False, "withdraw": False}
            session.ask_player = stub_player

            async def noop_questions():
                return None
            session._answer_table_questions = noop_questions

            published = []

            def on_publish(event):
                if event.get("type") == "speech":
                    on_disk = load_checkpoint(session.checkpoint_path)
                    disk_nos = {e["event_no"] for e in on_disk["events"]
                                if e.get("type") == "speech"}
                    published.append(event["event_no"] in disk_nos)

            session._event_q = _RecordingQueue(on_publish)

            await session._election()

            self.assertEqual(published, [True, True])
            self.assertEqual(len(published), 2)


class DeathEventPersistenceOrderTest(unittest.IsolatedAsyncioTestCase):
    """§8.3: a settlement batch must be durable in full before any of it is visible."""

    async def test_settlement_batch_is_durable_before_first_publish(self):
        """The whole batch is on disk before the first publish.

        ``_emit_event`` only records; ``_commit_batch`` checkpoints once then
        flushes once — so a crash can never leave the queue holding event 2
        while disk holds only event 1 (Shawn's repro).
        """
        session = GameSession("classic", {"enabled": False}, session_id="atomic-death-order")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            published = []

            def on_publish(event):
                if event.get("type") == "death":
                    on_disk = load_checkpoint(session.checkpoint_path)
                    disk = {e["event_no"] for e in on_disk["events"]
                            if e.get("type") == "death"}
                    published.append((event["event_no"], disk))

            session._event_q = _RecordingQueue(on_publish)

            await session._emit_event(SimpleNamespace(type="death", seat=2, text="2号 死亡"))
            await session._emit_event(SimpleNamespace(type="death", seat=4, text="4号 死亡"))
            await session._emit_event(SimpleNamespace(type="death", seat=6, text="6号 死亡"))
            session._commit_batch()

            self.assertEqual(len(published), 3)
            # At the instant each event was published, all three were already
            # durable on disk — never a torn batch.
            disk_at_first = published[0][1]
            self.assertEqual(len(disk_at_first), 3)
            for _no, disk in published:
                self.assertEqual(disk, disk_at_first)
            disk_deaths = [e for e in load_checkpoint(session.checkpoint_path)["events"]
                           if e.get("type") == "death"]
            self.assertEqual([e["seat"] for e in disk_deaths], [2, 4, 6])


class NightSettlementAtomicTest(unittest.IsolatedAsyncioTestCase):
    """§8.3: a night settlement (wolf knife + witch poison) commits as one batch."""

    async def test_wolf_knife_and_witch_poison_settle_as_one_batch(self):
        """Shawn's exact repro: 2 deaths + 2 flips must not tear across a crash.

        Engine state has both 2号 and 4号 dead; the public ledger must have all
        four events, not just the first death.
        """
        session = GameSession("classic", {"enabled": False},
                              session_id="atomic-night-batch",
                              seed=7, locale="zh-CN", player_role="civilian")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            await session._step_setup()
            victim = next(s for s in session.engine.seats.values()
                          if s.role == "civilian" and not s.is_player)
            wolf = next(s for s in session.engine.seats.values()
                        if s.role == "werewolf" and not s.is_player)
            session.engine.start_night()
            session._step = "resolve_night"
            session._step_state["actions"] = {
                "wolves": {"target": victim.pos},
                "witch": {"save": None, "poison": wolf.pos},
            }

            published = []
            def on_publish(event):
                if event.get("type") in ("death", "flip"):
                    on_disk = load_checkpoint(session.checkpoint_path)
                    disk = {e["event_no"] for e in on_disk["events"]
                            if e.get("type") in ("death", "flip")}
                    published.append((event["type"], event.get("seat"), disk))

            session._event_q = _RecordingQueue(on_publish)

            await session._step_resolve_night()

            death_events = [e for e in session._events if e["type"] == "death"]
            flip_events = [e for e in session._events if e["type"] == "flip"]
            self.assertEqual(len(death_events), 2)
            self.assertEqual(len(flip_events), 2)
            # Both deaths are in the engine AND the public ledger.
            self.assertFalse(session.engine.seat_at(victim.pos).alive)
            self.assertFalse(session.engine.seat_at(wolf.pos).alive)
            # At the first death publish, all four settlement events were already
            # durable — a resume after a crash would recover the whole batch.
            self.assertEqual(len(published), 4)
            first_disk = published[0][2]
            self.assertEqual(len(first_disk), 4)


class TableQuestionCommitTest(unittest.IsolatedAsyncioTestCase):
    """§8.3: a table clarification question is removed only after its reply commits."""

    async def test_question_stays_pending_until_the_reply_commits(self):
        """Shawn's repro: the pre-call checkpoint saved the question as already
        deleted and the budget already spent, with the decision uncommitted — so
        a restore permanently dropped the question (zero retries)."""
        session = GameSession("classic", {"enabled": False}, session_id="atomic-question",
                              seed=7, locale="zh-CN", player_role="civilian")
        with tempfile.TemporaryDirectory() as directory:
            session.checkpoint_path = os.path.join(directory, "game.json")
            await session._step_setup()
            names = [n for n in session.agents]
            target_name, asker_name = names[0], names[1]
            session._pending_questions = [[target_name, asker_name]]
            session.planner = SimpleNamespace(verified=True, calls=0)  # force model path

            seen = {}

            async def fake_npc_call(call, *args, **kwargs):
                # At the pre-call checkpoint, the question is still pending, the
                # budget unspent, and the in-flight marker is durable on disk.
                on_disk = load_checkpoint(session.checkpoint_path)
                seen["disk_pending"] = on_disk["pending_questions"]
                seen["disk_answered"] = on_disk["questions_answered"]
                seen["disk_marker"] = on_disk["step_state"].get("answering_question")
                return SimpleNamespace(text="回答", claim=None, accuse=None, defend=None)
            session._npc_call = fake_npc_call

            async def fake_publish(seat, speech, kind):
                pass
            session._publish_table_speech = fake_publish

            await session._answer_table_questions()

            self.assertEqual(seen["disk_pending"], [[target_name, asker_name]])
            self.assertEqual(seen["disk_answered"], 0)
            self.assertEqual(seen["disk_marker"], [target_name, asker_name])
            # After commit: question removed, budget spent, marker cleared.
            self.assertNotIn([target_name, asker_name], session._pending_questions)
            self.assertEqual(session._questions_answered, 1)
            self.assertNotIn("answering_question", session._step_state)


if __name__ == "__main__":
    unittest.main()
