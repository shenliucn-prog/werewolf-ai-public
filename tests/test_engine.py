import unittest

from werewolf_web.game.engine import GameEngine


class GameEngineRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = GameEngine("evil_knight", seed=7)
        self.engine.setup()

    def seat_with_role(self, role):
        return next(seat for seat in self.engine.seats.values() if seat.role == role)

    def test_first_started_night_is_night_one(self):
        self.engine.start_night()

        self.assertEqual(self.engine.night_count, 1)
        self.assertEqual(self.engine.history[-1].text, "第1夜")

    def test_evil_knight_reflects_seer_without_dying(self):
        seer = self.seat_with_role("seer")
        evil_knight = self.seat_with_role("evil_knight")

        events = self.engine.resolve_night({"seer": {"target": evil_knight.pos}})

        self.assertFalse(seer.alive)
        self.assertEqual(seer.death_cause, "reflect")
        self.assertTrue(evil_knight.alive)
        self.assertEqual(self.engine.seer_results, [])
        self.assertTrue(any("预言家死亡" in event.text for event in events))

    def test_evil_knight_reflects_witch_poison_without_dying(self):
        witch = self.seat_with_role("witch")
        evil_knight = self.seat_with_role("evil_knight")

        events = self.engine.resolve_night({"witch": {"poison": evil_knight.pos}})

        self.assertFalse(witch.alive)
        self.assertEqual(witch.death_cause, "reflect")
        self.assertTrue(evil_knight.alive)
        self.assertFalse(self.engine.witch_poison)
        self.assertTrue(any("女巫死亡" in event.text for event in events))

    def test_evil_knight_blocks_hunter_shot_once(self):
        hunter = self.seat_with_role("hunter")
        evil_knight = self.seat_with_role("evil_knight")

        events = []
        fired = self.engine.trigger_hunter(hunter.pos, evil_knight.pos, events)

        self.assertFalse(fired)
        self.assertTrue(evil_knight.alive)
        self.assertTrue(any("猎人无法开枪" in event.text for event in events))

    def test_public_actions_are_written_to_one_event_ledger(self):
        engine = GameEngine("classic", seed=11)
        engine.setup()
        victim = next(seat for seat in engine.seats.values() if not seat.is_wolf)

        engine.start_night()
        night_events = engine.resolve_night({"wolves": {"target": victim.pos}})
        self.assertEqual(engine.history[-len(night_events):], night_events)

        engine.start_day()
        speaker = engine.alive_seats()[0]
        speech = engine.record_speech(speaker.pos, "我先听发言。")
        self.assertIs(engine.history[-1], speech)

        exiled = engine.alive_seats()[-1]
        voter = engine.alive_seats()[0]
        vote_events = engine.resolve_vote({voter.pos: exiled.pos}, exiled.pos)
        self.assertEqual(engine.history[-len(vote_events):], vote_events)
        self.assertEqual(vote_events[0].type, "vote")
        self.assertTrue(any(event.type == "flip" for event in vote_events))


if __name__ == "__main__":
    unittest.main()
