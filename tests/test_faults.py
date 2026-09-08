"""Fault-injection and dedup tests (§8.3).

The acceptance criteria for the recovery layer's fault behavior:
- a committed vote/potion is not re-applied after a restore (turn-boundary cursor);
- a crash between the pre-call and post-result checkpoints re-issues the decision
  as a *new* attempt that consumes budget, while a persisted/committed decision is
  reused and consumes no new attempt (decision replay);
- a restored game never emits another seat's private events to the wrong consumer.
"""
import asyncio
import unittest
from types import SimpleNamespace

from werewolf_web.run import GameSession


class _BoundAgent:
    """A tiny stand-in whose bound method carries a ``__self__`` with a name."""

    def __init__(self, name, fn=None):
        self.name = name
        self._fn = fn

    def speak(self, *args, **kwargs):
        if self._fn is None:
            raise AssertionError("the model call must not be re-issued")
        return self._fn()

    def election_choice(self, withdraw=False):
        if self._fn is None:
            raise AssertionError("the model call must not be re-issued")
        return self._fn()

    def vote(self, *args, **kwargs):
        if self._fn is None:
            raise AssertionError("the model call must not be re-issued")
        return self._fn()

    def night_action(self, *args, **kwargs):
        if self._fn is None:
            raise AssertionError("the model call must not be re-issued")
        return self._fn()


class DecisionReplayTest(unittest.IsolatedAsyncioTestCase):
    """§8.3(b): committed decisions are reused; uncommitted ones are re-issued."""

    def make_session(self, **kwargs):
        return GameSession("classic", {"enabled": False}, **kwargs)

    async def test_committed_decision_is_reused_without_budget(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "vote"
        session._resume_step = "vote"
        session._replay_committed = [{
            "decision_no": 1, "slot": "vote:d0:Alice:speak", "attempts": [],
            "result": {"target": 5}, "committed": True,
        }]
        session._replay_cursor = 0

        agent = _BoundAgent("Alice")  # speak() raises if invoked
        result = await session._npc_call(agent.speak)

        self.assertEqual(result, {"target": 5})
        self.assertEqual(planner.calls, 0)             # no budget consumed
        self.assertEqual(session.decision_log, [])     # no new decision opened

    async def test_replay_does_not_cross_day_instances(self):
        """§8.3(b): day-2 vote must reuse only the day-2 vote, never day-1's.

        The same step name recurs every day, so the slot must carry a durable
        day/phase instance.  Without it, a day-2 resume would replay a stale
        same-named day-1 decision (Shawn's repro)."""
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session.engine.day_count = 2          # day-2 vote
        session._current_step = "vote"
        session._resume_step = "vote"
        session._replay_committed = [
            {"decision_no": 1, "slot": "vote:d1:Alice:speak", "attempts": [],
             "result": {"target": 5}, "committed": True},
            {"decision_no": 2, "slot": "vote:d2:Alice:speak", "attempts": [],
             "result": {"target": 7}, "committed": True},
        ]
        session._replay_cursor = 0

        agent = _BoundAgent("Alice")  # speak() raises if re-issued
        result = await session._npc_call(agent.speak)

        self.assertEqual(result, {"target": 7})   # the day-2 decision, not day-1's
        self.assertEqual(planner.calls, 0)
        self.assertEqual(session.decision_log, [])

    async def test_uncommitted_slot_is_reissued_as_a_new_attempt(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "vote"
        session._resume_step = "vote"
        session._replay_committed = []                 # nothing committed yet
        session._replay_cursor = 0

        def answer():
            planner.calls += 1
            return {"target": 7}

        agent = _BoundAgent("Alice", answer)
        result = await session._npc_call(agent.speak)

        self.assertEqual(result, {"target": 7})
        self.assertEqual(planner.calls, 1)             # a fresh attempt consumed budget
        self.assertEqual(len(session.decision_log), 1)
        self.assertEqual(session.decision_log[0]["slot"], "vote:d0:Alice:speak")
        self.assertEqual([a["attempt_no"] for a in session.decision_log[0]["attempts"]], [1])

    async def test_replay_is_scoped_to_the_resumed_step(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "vote"
        session._resume_step = "night"                 # a *different* step
        session._replay_committed = [{
            "decision_no": 1, "slot": "vote:d0:Alice:speak", "attempts": [],
            "result": {"target": 5}, "committed": True,
        }]
        session._replay_cursor = 0

        def answer():
            planner.calls += 1
            return {"target": 9}

        agent = _BoundAgent("Alice", answer)
        result = await session._npc_call(agent.speak)

        # The committed entry belongs to another step, so it is not replayed.
        self.assertEqual(result, {"target": 9})
        self.assertEqual(planner.calls, 1)

    def test_slot_step_parses_npc_and_human_slots(self):
        self.assertEqual(GameSession._slot_step("vote:Alice"), "vote")
        self.assertEqual(GameSession._slot_step("vote:d1:Alice"), "vote")
        self.assertEqual(GameSession._slot_step("human:speeches:speech"), "speeches")
        self.assertEqual(GameSession._slot_step("human:vote:d1:ready"), "vote")
        self.assertIsNone(GameSession._slot_step(None))


class DecisionSlotCollisionTest(unittest.IsolatedAsyncioTestCase):
    """§4.5 P1: the concrete action must be part of the decision identity.

    Before the fix, one NPC's 上警/发言/退警/投票 on the same day shared a single
    ``{step}:{instance}:{name}`` slot, so an election-speech resume replayed the
    上警 ``True`` bool and crashed with ``AttributeError: 'bool' has no 'text'``.
    The slot now carries the action; repeated same-method calls (election_choice
    twice, stone ghost's two night actions) pass an explicit ``action`` label.
    """

    def make_session(self, **kwargs):
        return GameSession("classic", {"enabled": False}, **kwargs)

    async def test_election_actions_are_distinct_slots(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "election"
        agent = _BoundAgent("Alice")

        agent._fn = lambda: True
        await session._npc_call(agent.election_choice, action="election_up")
        agent._fn = lambda: SimpleNamespace(text="a speech")
        await session._npc_call(agent.speak)
        agent._fn = lambda: False
        await session._npc_call(agent.election_choice, withdraw=True, action="election_withdraw")
        agent._fn = lambda: 7
        await session._npc_call(agent.vote)

        slots = [d["slot"] for d in session.decision_log]
        self.assertEqual(slots, [
            "election:d0:Alice:election_up",
            "election:d0:Alice:speak",
            "election:d0:Alice:election_withdraw",
            "election:d0:Alice:vote",
        ])
        self.assertEqual(len(set(slots)), 4)          # no two actions collide

    async def test_election_speech_replay_does_not_fetch_the_up_result(self):
        """Shawn's repro: an election-speech resume must not replay the 上警 bool."""
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "election"
        session._resume_step = "election"
        session._replay_committed = [{
            "decision_no": 1, "slot": "election:d0:Alice:election_up",
            "attempts": [], "result": True, "committed": True,
        }]
        session._replay_cursor = 0

        agent = _BoundAgent("Alice", lambda: SimpleNamespace(text="My speech"))
        result = await session._npc_call(agent.speak)

        self.assertEqual(result.text, "My speech")    # a Speech, not the bool True
        self.assertFalse(result is True)
        # The speak opened its own decision; it did not consume the 上警 entry.
        self.assertEqual([d["slot"] for d in session.decision_log],
                         ["election:d0:Alice:speak"])

    async def test_stone_ghost_actions_are_distinct_slots(self):
        planner = SimpleNamespace(verified=True, calls=0)
        session = self.make_session(planner=planner)
        session._current_step = "night"
        agent = _BoundAgent("Ghost")

        agent._fn = lambda: {"target": 3}
        await session._npc_call(agent.night_action, "stone_ghost", [1, 2, 3],
                                action="stone_ghost")
        agent._fn = lambda: {"target": 5}
        await session._npc_call(agent.night_action, "wolves", [1, 2, 3],
                                action="stone_ghost_kill")

        slots = [d["slot"] for d in session.decision_log]
        self.assertEqual(slots, ["night:n0:Ghost:stone_ghost",
                                 "night:n0:Ghost:stone_ghost_kill"])
        self.assertNotEqual(slots[0], slots[1])


class _SimulatedCrash(Exception):
    """Raised mid-step to emulate a process death at a known execution point."""


class MidStepResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_play_redispatches_crashed_step_with_replay_queue(self):
        session = GameSession("classic", {"enabled": False}, session_id="fault-midstep")
        await session._step_setup()
        # Simulate a crash mid-"vote": dispatch cleared ``_step`` and one
        # decision was already committed.
        session._step = None
        session._current_step = "vote"
        entry = session._open_decision("vote:d0:Alice")
        entry["result"] = {"target": 2}
        entry["committed"] = True

        observed = {}

        async def probe_step():
            observed["resume_step"] = session._resume_step
            observed["replay_committed"] = [d["slot"] for d in session._replay_committed]
            session._step = None

        session._step_vote = probe_step
        await session._play()

        self.assertEqual(observed["resume_step"], "vote")
        self.assertEqual(observed["replay_committed"], ["vote:d0:Alice"])

    async def test_resolve_night_resume_skips_settlement_reapply(self):
        """§8.3(d): a crash mid-``resolve_night`` (after settlement, at the death-
        skill wait) must resume without re-popping ``actions`` or re-applying the
        settlement.  The pre-fix code popped ``actions`` first and would KeyError
        (or, if re-fed, re-validate against now-dead targets and ValueError)."""
        a = GameSession("classic", {"enabled": False}, session_id="fault-resolve-night",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()
        await a._step_witch_rule()
        await a._step_night()          # gather -> resolve_night, actions stored
        self.assertEqual(a._step, "resolve_night")
        night_count = a.engine.night_count

        async def crash():
            raise _SimulatedCrash()

        a._post_death_triggers = crash
        with self.assertRaises(_SimulatedCrash):
            await a._step_resolve_night()
        # Isolate the settlement guard: no death-trigger side effects on resume.
        async def noop():
            pass
        a._post_death_triggers = noop

        # The settlement was applied exactly once; its execution position is
        # durable in ``_step_state``.
        self.assertNotIn("actions", a._step_state)
        self.assertIn("night_events", a._step_state)
        history_len = len(a.engine.history)
        seer_results = len(a.engine.seer_results)

        # Re-entering the step must not raise and must not re-apply the night.
        await a._step_resolve_night()
        self.assertEqual(a.engine.night_count, night_count)
        self.assertEqual(len(a.engine.history), history_len)
        self.assertEqual(len(a.engine.seer_results), seer_results)
        self.assertEqual(a._step, "day_start")


class CommittedActionDedupTest(unittest.IsolatedAsyncioTestCase):
    """§8.3(a): after a committed turn, a restore resumes the *next* step."""

    async def test_restore_after_night_resolution_does_not_reapply_night(self):
        a = GameSession("classic", {"enabled": False}, session_id="fault-potion",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()           # deals; _step -> witch_rule
        await a._step_witch_rule()      # _step -> night
        await a._step_night()           # gather (no human night action) -> resolve_night
        night_count = a.engine.night_count
        await a._step_resolve_night()   # -> day_start
        await a._step_day_start()       # -> election (day 1)
        self.assertEqual(a._step, "election")
        snapshot = a.snapshot()

        b = GameSession("classic", {"enabled": False}, session_id="fault-potion",
                        seed=99, locale="zh-CN", player_role="civilian")
        b.restore(snapshot)
        self.assertEqual(b._step, "election")
        self.assertEqual(b.engine.night_count, night_count)

        task = asyncio.create_task(b._play())
        try:
            drained = []
            while True:
                event = await asyncio.wait_for(b.event_q.get(), 2)
                drained.append(event)
                if event["type"] == "request":
                    break
            # The resume dispatches the *election*, never re-runs night.
            self.assertEqual(event["kind"], "election_up")
            self.assertNotIn("init", [e["type"] for e in drained])
            self.assertNotIn("night_start", [e["type"] for e in drained])
            self.assertEqual(b.engine.night_count, night_count)
        finally:
            task.cancel()

    async def test_vote_settlement_is_not_reapplied_after_restore(self):
        """Shawn's repro: a crash after the vote settled re-ran the whole vote
        (a second ballot, 1 human vote request + N NPC votes).  The settled
        position must be committed with the batch, and a resume must skip it."""
        a = GameSession("classic", {"enabled": False}, session_id="fault-vote-settle",
                        seed=7, locale="zh-CN", player_role="civilian")
        await a._step_setup()
        a._current_step = "vote"
        calls = {"player": 0, "npc": 0}

        async def player(*args, **kwargs):
            calls["player"] += 1
            return {"target": None}
        a.ask_player = player

        async def npc(call, *args, **kwargs):
            calls["npc"] += 1
            return 1  # every NPC votes seat 1, so the exile is deterministic
        a._npc_call = npc

        await a._vote_phase()
        self.assertEqual(calls["player"], 1)
        self.assertGreater(calls["npc"], 0)
        self.assertTrue(a._step_state.get("vote_settled"))
        snapshot = a.snapshot()

        # Restore and re-enter the vote: it must skip, not re-vote anyone.
        b = GameSession("classic", {"enabled": False}, session_id="fault-vote-settle",
                        seed=99, locale="zh-CN", player_role="civilian")
        b.restore(snapshot)
        b.ask_player = lambda *a, **k: (_ for _ in ()).throw(AssertionError("human re-voted"))
        b._npc_call = lambda *a, **k: (_ for _ in ()).throw(AssertionError("NPC re-voted"))
        await b._vote_phase()
        self.assertTrue(b._step_state.get("vote_settled"))


class PrivacyBoundaryTest(unittest.IsolatedAsyncioTestCase):
    """§8.3(c): a restored game never leaks another seat's private lines."""

    async def test_restored_view_carries_only_the_players_own_private_lines(self):
        a = GameSession("classic", {"enabled": False}, session_id="fault-priv",
                        seed=7, locale="zh-CN", player_role="seer")
        await a._step_setup()
        a.emit({"type": "private", "text": "你查验了 3 号，是狼人。"})
        snapshot = a.snapshot()

        b = GameSession("classic", {"enabled": False}, session_id="fault-priv",
                        seed=99, locale="zh-CN", player_role="seer")
        b.restore(snapshot)
        view = b.recovery_view(0)

        # The player's own private line is re-presented...
        self.assertEqual([e["text"] for e in view["private_events"]],
                         ["你查验了 3 号，是狼人。"])
        # ...and never bleeds into the public transcript, which is the only
        # channel a reattaching client consumes for catch-up.
        self.assertNotIn("private", [e["type"] for e in view["public_events"]])
        # The player-scoped private payload exposes the player's own identity,
        # not the hidden wolf roster.
        # The player-scoped private payload exposes only the player's own
        # identity — a seer is not a wolf and has no wolfmates — so no other
        # seat's role roster leaks through.
        self.assertEqual(view["private"]["role"], "seer")
        self.assertFalse(view["private"]["is_wolf"])
        self.assertEqual(view["private"]["wolfmates"], [])


if __name__ == "__main__":
    unittest.main()
