import random
import unittest

from werewolf_web.ai.brain import Brain
from werewolf_web.ai.strategy import InformationSet
from werewolf_web.game.engine import GameEngine


class StrategicBrainTest(unittest.TestCase):
    def setUp(self):
        self.engine = GameEngine("classic", seed=19)
        self.engine.setup()

    def brain_for(self, seat):
        return Brain(seat, self.engine, {}, random.Random(seat.pos))

    def test_good_player_information_set_does_not_reveal_hidden_roles(self):
        civilian = next(
            seat for seat in self.engine.seats.values()
            if seat.faction == "civilian"
        )

        information = InformationSet.from_brain(self.brain_for(civilian))

        self.assertEqual(information.private, {"self_role": civilian.role})
        self.assertTrue(all(set(item) == {"pos", "name"} for item in information.alive))

    def test_wolf_information_set_reveals_only_legal_team_knowledge(self):
        wolf = next(seat for seat in self.engine.seats.values() if seat.is_wolf)
        expected_mates = {
            seat.name for seat in self.engine.seats.values()
            if seat.is_wolf and seat.name != wolf.name
        }

        information = InformationSet.from_brain(self.brain_for(wolf))

        self.assertEqual(
            {item["name"] for item in information.private["wolf_mates"]},
            expected_mates,
        )
        self.assertNotIn("all_roles", information.private)

    def test_vote_produces_an_explainable_decision_trace(self):
        civilian = next(
            seat for seat in self.engine.seats.values()
            if seat.faction == "civilian"
        )
        brain = self.brain_for(civilian)
        candidates = [seat.pos for seat in self.engine.alive_seats()]

        target, rationale = brain.vote(candidates)

        self.assertIsNotNone(target)
        self.assertTrue(rationale)
        self.assertEqual(len(brain.decision_traces), 1)
        trace = brain.decision_traces[0]
        self.assertEqual(trace.target, target)
        self.assertEqual(trace.action, "vote")
        self.assertGreater(len(trace.alternatives), 0)
        self.assertIn(self.engine.seat_at(target).name, trace.beliefs)
        self.assertLessEqual(trace.reasoning_depth, brain.cognition.max_depth)

    def test_intelligence_depth_is_distinct_and_can_grow(self):
        seats = [
            seat for seat in self.engine.seats.values()
            if seat.faction == "civilian"
        ]
        high = Brain(
            seats[0], self.engine,
            {"traits": "天才 冷静 理性 分析 逻辑 缜密"}, random.Random(1),
        )
        low = Brain(
            seats[1], self.engine,
            {"traits": "新手 凭感觉 不太会"}, random.Random(2),
        )

        self.assertGreater(high.cognition.max_depth, low.cognition.max_depth)
        high.vote([seat.pos for seat in self.engine.alive_seats()])
        before = high.cognition.experience
        lesson = high.grow(won=False)
        self.assertEqual(high.cognition.experience, before + 1)
        self.assertTrue(lesson)

    def test_stone_ghost_and_wolf_pack_are_information_isolated(self):
        engine = GameEngine("stone_ghost", seed=23)
        engine.setup()
        stone_ghost = next(
            seat for seat in engine.seats.values() if seat.role == "stone_ghost"
        )
        pack_wolf = next(
            seat for seat in engine.seats.values() if seat.role == "werewolf"
        )
        stone_brain = Brain(stone_ghost, engine, {}, random.Random(1))
        wolf_brain = Brain(pack_wolf, engine, {}, random.Random(2))

        stone_info = InformationSet.from_brain(stone_brain)
        wolf_info = InformationSet.from_brain(wolf_brain)

        self.assertNotIn("wolf_mates", stone_info.private)
        self.assertNotIn(
            stone_ghost.name,
            {mate["name"] for mate in wolf_info.private["wolf_mates"]},
        )
        self.assertNotIn(stone_ghost, engine.wolves())
        self.assertGreaterEqual(wolf_brain.suspicion(stone_ghost.name), 0.0)
        self.assertGreaterEqual(stone_brain.suspicion(pack_wolf.name), 0.0)


if __name__ == "__main__":
    unittest.main()
