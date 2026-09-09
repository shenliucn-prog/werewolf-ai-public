"""Phase-2 regression tests: unified day/night/phase/vote-kind semantics and
disputed-verbatim retention (no model, no key)."""
import unittest
import json
from unittest.mock import MagicMock

from werewolf_web.public_record import PublicRecord
from werewolf_web.ai import model_context
from werewolf_web.game.engine import GameEngine
from werewolf_web.run import GameSession
from werewolf_web.ai.brain import Speech


def _record():
    return PublicRecord("zh-CN")


class TimelineSemanticsTest(unittest.TestCase):
    def test_kill_stamps_night_and_phase(self):
        engine = GameEngine("classic", seed=7, locale="zh-CN")
        engine.setup()
        engine.start_night()  # night 1
        victim = next(s for s in engine.alive_seats() if not s.is_wolf)
        events = []
        engine._kill(victim.pos, "knife", events)
        death = next(ev for ev in events if ev.type == "death")
        flip = next(ev for ev in events if ev.type == "flip")
        # A night-1 death is stamped with the *night*, not the previous day (0).
        self.assertEqual(death.data["night"], 1)
        self.assertEqual(death.data["phase"], "night")
        self.assertEqual(flip.data["night"], 1)

    def test_public_facts_distinguish_vote_kind(self):
        record = _record()
        record.observe({"type": "ballots", "sheriff": True, "day": 1,
                        "ballots": [{"voter": 1, "target": 3, "weight": 1}],
                        "tally": {3: 1}, "text": "警长票型"}, 1, 1, "election")
        record.observe({"type": "ballots", "sheriff": False, "day": 1,
                        "ballots": [{"voter": 1, "target": 3, "weight": 1}],
                        "tally": {3: 1}, "text": "放逐票型"}, 1, 1, "vote")
        facts = model_context.public_facts(record.entries)
        kinds = [f["vote_kind"] for f in facts if f["kind"] == "ballots"]
        self.assertEqual(kinds, ["sheriff", "exile"])

    def test_death_fact_carries_night_not_old_day(self):
        record = _record()
        record.observe({"type": "death", "seat": 2, "text": "2号死亡",
                        "day": 1, "night": 2, "phase": "night"}, 1, 2, "night")
        facts = model_context.public_facts(record.entries)
        death = next(f for f in facts if f["kind"] == "death")
        self.assertEqual(death["night"], 2)
        self.assertEqual(death["phase"], "night")
        self.assertEqual(death["day"], 1)

    def test_recent_speech_carries_phase(self):
        record = _record()
        record.observe({"type": "speech", "seat": 3, "name": "p3",
                        "text": "我是预言家", "phase": "election", "event_no": 1},
                       1, 1, "election")
        rows = model_context.recent_public_statements(record.entries)
        self.assertEqual(rows[0]["phase"], "election")
        self.assertEqual(rows[0]["event_no"], 1)


class DisputedVerbatimTest(unittest.TestCase):
    def test_disputed_statement_kept_by_event_no_not_latest(self):
        brain = MagicMock()
        brain.disputed_event_nos = [1]   # the early disputed (accusation) speech
        record = _record()
        record.observe({"type": "speech", "seat": 5, "name": "accuser",
                        "text": "我怀疑3号是狼", "phase": "day", "event_no": 1}, 1, 1, "day")
        # A later long speech by the same speaker must NOT crowd out event_no=1.
        record.observe({"type": "speech", "seat": 5, "name": "accuser",
                        "text": "长" * 2000, "phase": "day", "event_no": 2}, 1, 1, "day")
        section = model_context.disputed_verbatim(record.entries, brain)
        self.assertEqual([i["event_no"] for i in section["items"]], [1])
        self.assertEqual(section["items"][0]["text"], "我怀疑3号是狼")
        self.assertFalse(section["truncated"])

    def test_disputed_verbatim_truncates_with_marker(self):
        brain = MagicMock()
        brain.disputed_event_nos = [1]
        record = _record()
        record.observe({"type": "speech", "seat": 5, "name": "accuser",
                        "text": "长" * 2000, "phase": "day", "event_no": 1}, 1, 1, "day")
        section = model_context.disputed_verbatim(record.entries, brain, max_chars=100)
        self.assertTrue(section["truncated"])
        self.assertEqual(len(section["items"]), 1)
        self.assertLessEqual(len(section["items"][0]["text"]), 101)
        self.assertTrue(section["items"][0]["text"].endswith("…"))

    def test_legacy_ballot_without_sheriff_is_unknown(self):
        record = _record()
        record.observe({"type": "ballots", "day": 1, "ballots": [], "tally": {},
                        "text": "旧记录"}, 1, 1, "vote")
        facts = model_context.public_facts(record.entries)
        ballot = next(f for f in facts if f["kind"] == "ballots")
        self.assertEqual(ballot["vote_kind"], "unknown")


class VoteMemoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_speeches_preserve_candidate_original_and_restore_atomically(self):
        session = GameSession("classic", {"enabled": False}, seed=7)
        await session._step_setup()
        a, b = list(session.agents.values())[:2]
        original = "我是预言家，昨晚验了5号。"
        await session._publish_table_speech(a.seat, Speech(text=original, claim="seer"), "clarification")
        original_no = session._event_no
        await session._publish_table_speech(b.seat, Speech(text="你的验人说法有矛盾", accuse=a.seat.name), "clarification")
        await session._publish_table_speech(a.seat, Speech(text="长" * 2000), "clarification")
        brain = b.brain
        before = brain.snapshot()
        brain.restore(json.loads(json.dumps(before)))
        self.assertEqual(brain.snapshot(), before)
        section = model_context.disputed_verbatim(session.public_record.entries, brain)
        item = next(i for i in section["items"] if i["event_no"] == original_no)
        self.assertEqual(item["text"], original)
        self.assertEqual(item["reference_status"], "candidate_original")
        self.assertEqual(item["exact_reference"], "unknown")
        self.assertNotIn(session._event_no, [i["event_no"] for i in section["items"]])
        for field, value in (("disputed_event_nos", [True]), ("disputed_targets", [[99999, a.seat.name]])):
            broken = json.loads(json.dumps(before))
            broken["name"] = "must not apply"
            broken[field] = value
            with self.assertRaises(ValueError):
                brain.restore(broken)
            self.assertEqual(brain.snapshot(), before)

    async def test_broadcast_votes_distinguishes_sheriff_from_exile(self):
        session = GameSession("classic", {"enabled": False}, seed=7)
        await session._step_setup()
        agent = next(iter(session.agents.values()))
        session._broadcast_votes({1: 3}, sheriff=True)
        session._broadcast_votes({1: 3}, sheriff=False)
        kinds = [v[3] for v in agent.brain.vote_log]
        self.assertEqual(kinds, ["sheriff", "exile"])


if __name__ == "__main__":
    unittest.main()
