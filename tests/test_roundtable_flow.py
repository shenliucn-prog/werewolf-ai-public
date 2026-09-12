"""Public dialogue recovery and authored voices; no external model calls."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from werewolf_web.session import GameSession
from werewolf_web.ai.brain import Speech
from werewolf_web import checkpoint
from werewolf_web.characters import catalog


class RoundtableFlowTest(unittest.IsolatedAsyncioTestCase):
    async def make(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        session = GameSession("classic", {"enabled": False}, seed=17, player_role="civilian",
                              session_id="roundtable", checkpoint_path=str(Path(temp.name) / "save.json"))
        session.memory_dir = temp.name
        await session._step_setup()
        session.onboarding = True
        return session

    async def request(self, session):
        while True:
            event = await asyncio.wait_for(session.event_q.get(), 3)
            if event["type"] == "request":
                return event

    async def test_grouped_questions_retain_both_quotes_and_answer_once(self):
        s = await self.make()
        player = s.engine.player_seat()
        for i, seat in enumerate(list(s.engine.seats.values())):
            if seat.is_player:
                continue
            speech = Speech(text=f"Question from seat {seat.pos}", question_to=player.name)
            s._broadcast_speech(seat, speech)
            s.emit({"type": "speech", "seat": seat.pos, "name": seat.name, "text": speech.text})
            if len(s.questions.pending) == 2:
                break
        task = asyncio.create_task(s._answer_table_questions())
        event = await self.request(s)
        self.assertEqual(len(event["data"]["questions"]), 2)
        for q in event["data"]["questions"]:
            self.assertEqual(s._events[q["event_no"] - 1]["text"], q["text"])
        s.submit({"answer": "I answer both."})
        await task
        self.assertEqual(s.questions.answered, 1)
        self.assertFalse(s.questions.pending)
        restored = GameSession("classic", {"enabled": False})
        restored.restore(checkpoint.load_checkpoint(s.checkpoint_path))
        restored.ask_player = AsyncMock(side_effect=AssertionError("no duplicate reply"))
        await restored._answer_table_questions()
        self.assertEqual(sum(e.get("text") == "I answer both." for e in restored._events), 1)

    async def test_election_closure_does_not_spend_daytime_floor(self):
        s = await self.make()
        s.questions.answered = 12
        s._step_state.update(question_window=[], question_closure=True)
        with patch.object(s, "_election", AsyncMock()):
            await s._step_election()
        self.assertEqual(s.questions.answered, 0)
        self.assertNotIn("question_window", s._step_state)
        self.assertNotIn("question_closure", s._step_state)

    async def kill_player(self, s, cause="exile"):
        s.engine.start_day()
        events = []
        s.engine._kill(s.engine.player_seat().pos, cause, events)
        for event in events:
            await s._emit_event(event)
        s._commit_batch()

    async def test_last_words_commit_and_restore_exactly_once(self):
        s = await self.make()
        await self.kill_player(s)
        task = asyncio.create_task(s._farewell_floor())
        event = await self.request(s)
        self.assertTrue(event["data"]["last_words"])
        s.submit({"answer": "My final words."})
        await task
        restored = GameSession("classic", {"enabled": False})
        restored.restore(checkpoint.load_checkpoint(s.checkpoint_path))
        restored.ask_player = AsyncMock(side_effect=AssertionError("must not ask again"))
        await restored._farewell_floor()
        self.assertEqual(sum(e.get("talk_kind") == "last_words" for e in restored._events), 1)

    async def test_badge_is_committed_before_last_words(self):
        s = await self.make()
        await self.kill_player(s)
        s.engine.sheriff = s.engine.player_seat().pos
        task = asyncio.create_task(s._farewell_floor())
        badge = await self.request(s)
        self.assertEqual(badge["data"]["role_key"], "badge")
        target = badge["data"]["candidates"][0]["pos"]
        self.assertFalse(s.submit({"target": 999}))
        self.assertTrue(s.submit({"target": target}))
        words = await self.request(s)
        self.assertTrue(words["data"]["last_words"])
        self.assertEqual(checkpoint.load_checkpoint(s.checkpoint_path)["engine"]["sheriff"], target)
        s.submit({"skip": True})
        await task

    async def test_second_night_has_no_last_words_and_old_saves_keep_policy(self):
        s = await self.make()
        await self.kill_player(s, "wolf_kill")
        s.engine.night_count = 2
        s.engine.phase = "dawn"
        s.ask_player = AsyncMock(side_effect=AssertionError("not eligible"))
        await s._farewell_floor()
        self.assertFalse(any(e.get("talk_kind") == "last_words" for e in s._events))
        old = s.snapshot()
        old.pop("dialogue_version")
        restored = GameSession("classic", {"enabled": False})
        restored.restore(old)
        self.assertEqual(restored.dialogue_version, 0)

    async def test_first_night_victim_receives_last_words(self):
        s = await self.make()
        await self.kill_player(s, "poison")
        s.engine.night_count = 1
        s.engine.phase = "dawn"
        s.ask_player = AsyncMock(return_value={"skip": True})
        await s._farewell_floor()
        self.assertTrue(s.ask_player.call_args.args[1]["last_words"])

    async def test_last_words_use_a_different_decision_slot_from_closing_reply(self):
        s = await self.make()
        s._current_step = "vote"
        s.engine.start_day()
        s.speech_events = [("NPC", Speech(text="Question"))]
        closing = asyncio.create_task(s._pre_vote_reply())
        await self.request(s)
        s.submit({"answer": "Closing statement"})
        await closing
        s.engine.player_seat().alive = False
        s.engine.player_seat().death_cause = "exile"
        farewell = asyncio.create_task(s._farewell_floor())
        await self.request(s)
        s.submit({"answer": "Farewell"})
        await farewell
        slots = [d["slot"] for d in s.decision_log if d["slot"].startswith("human:")]
        self.assertEqual(len(slots), len(set(slots)))

    async def test_new_markers_reject_invalid_save_without_mutation(self):
        from copy import deepcopy
        s = await self.make()
        before = s.snapshot()
        for state in ({"farewells": [1, 1]}, {"farewells": [True]}, {"question_sources": {"x": []}}):
            broken = deepcopy(before)
            broken["step_state"].update(state)
            with self.assertRaises(ValueError):
                s.restore(broken)
            self.assertEqual(s.snapshot(), before)

    async def test_badge_transfer_is_part_of_public_reconnect(self):
        s = await self.make()
        await self.kill_player(s)
        s.engine.sheriff = s.engine.player_seat().pos
        target = s.engine.alive_seats()[0].pos
        s.ask_player = AsyncMock(side_effect=[{"target": target}, {"skip": True}])
        await s._farewell_floor()
        restored = GameSession("classic", {"enabled": False})
        restored.restore(checkpoint.load_checkpoint(s.checkpoint_path))
        badges = [e for e in restored.recovery_view()["public_events"] if e["type"] == "badge"]
        self.assertEqual([e["target"] for e in badges], [target])

    def test_thirty_bilingual_unique_acting_directions(self):
        for locale in ("zh-CN", "en"):
            characters = catalog(locale)
            self.assertEqual(len(characters), 30)
            self.assertEqual(len({c["voice_sample"] for c in characters}), 30)
            self.assertTrue(all(c["under_pressure"] and c["motive_and_blind_spot"] for c in characters))


if __name__ == "__main__":
    unittest.main()
