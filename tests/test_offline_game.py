"""End-to-end rule games use synthetic seeds, no model or user transcript."""
import asyncio
import contextlib
from copy import deepcopy
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from werewolf_web.offline_game import (
    OfflineSession, ChoiceAgent, speech_choices, action_choices, public_event, play,
)
from werewolf_web.offline_cast import CHARACTERS, BY_ID, cast_settings
from werewolf_web.session import GameSession
from werewolf_web.game.engine import BOARD_MAP
from werewolf_web.campaign import LEVELS
from werewolf_web import checkpoint


class OfflineGameTest(unittest.IsolatedAsyncioTestCase):
    async def session(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        session = OfflineSession(session_id="offline-test", **kwargs)
        session.memory_dir = tmp.name
        return session

    async def run_complete(self, **kwargs):
        session = await self.session(**kwargs)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(session.llm, "chat", side_effect=AssertionError("No model calls")):
            code = await play(session, automatic=True)
        self.assertEqual(code, 0)
        self.assertTrue(session.finished)
        self.assertFalse(session.faulted)
        self.assertIn(session.engine.winner, ("god", "wolf", "draw"))
        self.assertFalse(session.campaign_counted)
        self.assertIsNone(session.campaign_profile)
        self.assertTrue(any(e["type"] == "gameover" for e in session._events))
        self.assertTrue(all(isinstance(a, ChoiceAgent) for a in session.agents.values()))
        return session

    async def test_all_boards_reach_endgame_as_public_spectator(self):
        for board in BOARD_MAP:
            with self.subTest(board=board):
                await self.run_complete(board_id=board, spectator=True, seed=2)

    async def test_twelve_characters_can_be_replaced_without_duplicates(self):
        for character in CHARACTERS:
            session = await self.session(character=character.id, seed=7)
            await session._step_setup()
            self.assertEqual(len(set(session.character_map.values())), 12)
            self.assertEqual(session.character_map[session.engine.player_seat().player_id], character.id)
            self.assertEqual(len({s.name for s in session.engine.seats.values()}), 12)
            for agent in session.agents.values():
                self.assertEqual(agent.style, BY_ID[session.character_map[agent.seat.player_id]].style())

    async def test_real_player_role_paths_complete(self):
        # Every playable role, on its compatible board.
        for level in LEVELS:
            role = level["role"]
            with self.subTest(role=role):
                session = await self.run_complete(board_id=level["board"], seed=5, player_role=role)
                self.assertEqual(session.engine.player_seat().role, role)
                self.assertTrue(any(e["type"] == "request" for e in session._events))

    async def test_english_complete_game_and_options(self):
        session = await self.run_complete(seed=4, locale="en")
        for event in session._events:
            if event["type"] == "request":
                for option in action_choices(session, event["kind"], event["data"]):
                    self.assertFalse(any("\u4e00" <= c <= "\u9fff" for c in option["label"] + option["group"]))

    async def test_public_spectator_filter_removes_private_fields(self):
        session = await self.run_complete(seed=3, spectator=True, player_role="seer")
        self.assertTrue(any(e["type"] == "private" for e in session._events))
        init = next(e for e in session._events if e["type"] == "init")
        visible = public_event(init, True)
        self.assertEqual(set(visible), {"type", "text"})
        self.assertNotIn("player", visible)
        for event in session._events:
            if event["type"] in ("private", "request"):
                self.assertIsNone(public_event(event, True))

    async def test_menu_does_not_depend_on_secret_roles_or_checks(self):
        session = await self.session(seed=1)
        await session._step_setup()
        session.engine.night_count = 1
        player = session.engine.player_seat()
        before = speech_choices(session, player)
        player.role = "seer"
        session.engine.seer_results = [{"night": 1, "target": 5, "name": "secret", "result": "wolf"}]
        self.assertEqual(before, speech_choices(session, player))
        self.assertTrue(any(c["id"].startswith("report:") for c in before))
        self.assertNotIn("secret", json.dumps(before))

    async def test_response_changes_belief_only_once_per_day(self):
        session = await self.session(seed=1)
        await session._step_setup()
        actor = session.engine.player_seat()
        from werewolf_web.ai.brain import Speech
        menu = {c["id"]: c for c in speech_choices(session, actor)}
        agent = next(iter(session.agents.values()))
        agent.brain.ensured(actor.name)
        before = agent.brain.sus[actor.name]
        speech = Speech(**menu["refuse"]["speech"])
        agent.observe_speech(1, actor.name, speech, 100)
        after = agent.brain.sus[actor.name]
        self.assertGreater(after, before)
        agent.observe_speech(1, actor.name, speech, 101)
        self.assertEqual(after, agent.brain.sus[actor.name])

    async def test_menu_rejects_forged_payload_and_stale_id(self):
        session = await self.session(seed=2)
        await session._step_setup()
        task = asyncio.create_task(session.ask_player("speech", {}))
        await asyncio.sleep(0)
        option = action_choices(session, "speech", {})[0]
        request = session._human_request().request_id
        forged = deepcopy(option["payload"])
        forged["offline_speech"]["accuse"] = "forged"
        before = deepcopy(session.pending)
        self.assertFalse(session.submit(forged, request_id=request))
        self.assertFalse(session.submit(option["payload"], request_id="stale"))
        self.assertEqual(before, session.pending)
        self.assertTrue(session.submit(option["payload"], request_id=request))
        result = await task
        self.assertEqual(session._player_speech(result["text"]).text, result["text"])
        self.assertFalse(session.submit(option["payload"], request_id=request))

    async def test_quit_disk_resume_and_finish_with_same_mode(self):
        session = await self.session(seed=3, character="xicao", spectator=True)
        session.checkpoint_path = os.path.join(session.memory_dir, "save.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await play(session, read=lambda _: "q"), 0)
        saved = checkpoint.load_checkpoint(session.checkpoint_path)
        restored = await self.session(character="xicao", spectator=True)
        restored.restore(saved)
        self.assertEqual(restored.engine.public_state(), session.engine.public_state())
        self.assertEqual(restored.proxy.brain.rng.getstate(), session.proxy.brain.rng.getstate())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await play(restored, automatic=True), 0)
        self.assertTrue(restored.finished)
        self.assertEqual(sum(e["type"] == "init" for e in restored._events), 1)
        self.assertEqual(sum(e["type"] == "gameover" for e in restored._events), 1)

    async def test_wrong_entry_or_view_cannot_restore(self):
        session = await self.session(seed=2, spectator=True)
        await session._step_setup()
        saved = session.snapshot()
        for target in (GameSession("classic", {"enabled": False}), await self.session(spectator=False)):
            before = target.snapshot()
            with self.assertRaises(ValueError):
                target.restore(saved)
            self.assertEqual(target.snapshot(), before)

    async def test_mid_speech_resume_matches_uninterrupted_game(self):
        interrupted = await self.session(seed=8)
        interrupted.checkpoint_path = os.path.join(interrupted.memory_dir, "save.json")
        def read(_):
            kind, data = interrupted.pending["kind"], interrupted.pending["data"]
            if kind == "speech":
                return "q"
            options = action_choices(interrupted, kind, data)
            selected = interrupted.auto_choice(kind, data, options)
            return str(options.index(selected) + 1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await play(interrupted, read=read), 0)
        self.assertEqual(interrupted.pending["kind"], "speech")
        restored = await self.session()
        restored.restore(checkpoint.load_checkpoint(interrupted.checkpoint_path))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await play(restored, automatic=True), 0)
        reference = await self.run_complete(seed=8)
        self.assertEqual(restored.engine.public_state(), reference.engine.public_state())
        def transcript(s):
            return [(e["type"], e.get("text")) for e in s._events if e["type"] in ("speech", "ballots")]
        self.assertEqual(transcript(restored), transcript(reference))

    async def test_restore_cannot_enable_model_or_campaign(self):
        session = await self.session(seed=2)
        await session._step_setup()
        saved = session.snapshot()
        for field in ("model", "campaign"):
            bad = deepcopy(saved)
            if field == "model":
                bad["llm"]["config"]["enabled"] = True
            else:
                bad["campaign_profile"] = "default"
            before = session.snapshot()
            with self.assertRaises(ValueError):
                session.restore(bad)
            self.assertEqual(before, session.snapshot())

    async def test_seed_reproducibility(self):
        first = await self.run_complete(seed=10, spectator=True)
        second = await self.run_complete(seed=10, spectator=True)
        self.assertEqual(first.engine.public_state(), second.engine.public_state())
        def public_transcript(session):
            return [(e["type"], e.get("text")) for e in session._events if e["type"] in ("speech", "ballots", "gameover")]
        self.assertEqual(public_transcript(first), public_transcript(second))


if __name__ == "__main__":
    unittest.main()
