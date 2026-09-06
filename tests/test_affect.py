import random
import unittest
from types import SimpleNamespace

from werewolf_web.ai.affect import MatchState
from werewolf_web.ai.brain import Brain, Speech
from werewolf_web.ai.strategy import InformationSet
from werewolf_web.game.engine import GameEngine


class MatchAffectTest(unittest.TestCase):
    def setUp(self):
        self.engine = GameEngine("classic", seed=41)
        self.engine.setup()
        self.seat = next(s for s in self.engine.seats.values()
                         if s.faction == "civilian")

    def test_form_varies_between_matches_and_repeats_for_a_seed(self):
        first = MatchState.start(random.Random(7)).snapshot()
        repeat = MatchState.start(random.Random(7)).snapshot()
        other = MatchState.start(random.Random(8)).snapshot()
        self.assertEqual(first, repeat)
        self.assertNotEqual(first["form"], other["form"])

    def test_effective_abilities_keep_professional_floor(self):
        state = MatchState(form=-0.85, confidence=0.18, stress=0.82,
                           momentum=-0.75)
        for dimension in ("evidence_processing", "recursive_reasoning",
                          "social_reading", "deception", "calibration",
                          "decisiveness"):
            baseline = 0.60
            self.assertGreaterEqual(state.effective(baseline, dimension),
                                    baseline * 0.82)

    def test_reactions_are_small_and_bounded(self):
        state = MatchState.start(random.Random(3))
        before = state.snapshot()
        state.react("accused")
        self.assertLessEqual(abs(state.valence - before["valence"]), 0.05)
        self.assertLessEqual(abs(state.stress - before["stress"]), 0.06)
        for _ in range(50):
            state.react("wrong_read")
        self.assertGreaterEqual(state.confidence, 0.18)
        self.assertLessEqual(state.stress, 0.82)
        self.assertLessEqual(abs(state.momentum), 0.75)

    def test_form_changes_noise_and_reasoning_depth_without_changing_legality(self):
        hot = MatchState(form=0.75, confidence=0.72, stress=0.18, momentum=0.45)
        cold = MatchState(form=-0.75, confidence=0.24, stress=0.76, momentum=-0.45)
        self.assertLess(hot.decision_noise(0.6), cold.decision_noise(0.6))
        self.assertGreater(hot.depth_adjustment(), cold.depth_adjustment())

        brain = Brain(self.seat, self.engine, {}, random.Random(21))
        brain.match_state = cold
        # Force the bounded alternate-choice branch; it must still choose only
        # from the caller's legal candidate list.
        brain.rng.random = lambda: 0.0
        choices = [s.pos for s in self.engine.alive_seats() if s.pos != self.seat.pos]
        decision = brain.night("guard", choices)
        self.assertIn(decision.target, choices)
        self.assertIn("合法目标", decision.reason)

    def test_public_exile_reacts_once_to_own_vote_and_records_it(self):
        brain = Brain(self.seat, self.engine, {}, random.Random(11))
        before = brain.match_state.snapshot()
        brain.observe_speech(1, "other", Speech(accuse=brain.name), "我怀疑你")
        self.assertIn("accused", brain.match_state.events)
        brain.observe_vote(1, brain.name, "other")
        brain.observe_exile(1, "other", True)
        brain.observe_exile(1, "other", True)
        self.assertIn("correct_read", brain.match_state.events)
        self.assertEqual(brain.match_state.events.count("correct_read"), 1)
        self.assertNotEqual(before["stress"], brain.match_state.stress)
        reactions = [e for e in self.engine.history
                     if e.type == "npc_state" and e.text == "correct_read"]
        self.assertEqual(len(reactions), 1)
        self.assertIn("start", reactions[0].data)
        self.assertIn("state", reactions[0].data)

    def test_known_wolf_ally_flip_reacts_privately_once(self):
        wolf = next(s for s in self.engine.seats.values() if s.is_wolf)
        ally = next(s for s in self.engine.seats.values()
                    if s.is_wolf and s.name != wolf.name)
        brain = Brain(wolf, self.engine, {}, random.Random(19))
        brain.observe_flip(ally.name, ally.role_cn, True)
        brain.observe_flip(ally.name, ally.role_cn, True)
        self.assertEqual(brain.match_state.events.count("ally_lost"), 1)
        self.assertEqual(len([e for e in self.engine.history
                              if e.type == "npc_state" and e.text == "ally_lost"
                              and e.seat == wolf.pos]), 1)
        self.assertNotIn("npc_state", self.engine.public_state())

    def test_effective_cognition_drives_evidence_and_deception_choices(self):
        brain = Brain(self.seat, self.engine, {}, random.Random(23))
        other = next(s for s in self.engine.alive_seats() if s.pos != self.seat.pos)
        brain.gut[other.name] = 0.9
        brain.effective_ability = lambda dimension: 0.90
        high = brain._base_suspicion(other.name)
        brain.effective_ability = lambda dimension: 0.20
        low = brain._base_suspicion(other.name)
        self.assertLess(high, low)

        wolf = next(s for s in self.engine.seats.values() if s.is_wolf)
        wolf_brain = Brain(wolf, self.engine, {}, random.Random(29))
        wolf_brain.wolf_strategy = "bluff"
        candidates = [s.pos for s in self.engine.alive_seats()]
        wolf_brain.rng.random = lambda: 0.0
        wolf_brain.effective_ability = lambda dimension: 0.0
        self.assertNotEqual(wolf_brain._wolves(candidates).target, wolf.pos)
        wolf_brain.effective_ability = lambda dimension: 0.95
        self.assertEqual(wolf_brain._wolves(candidates).target, wolf.pos)

    def test_coach_performance_has_start_and_final_state_without_public_leak(self):
        from werewolf_web.run import GameRunner

        brain = Brain(self.seat, self.engine, {}, random.Random(31))
        runner = GameRunner("classic")
        runner.agents = {brain.name: SimpleNamespace(
            memory={"learnings": []}, role_cn=brain.me.role_cn, brain=brain,
            reasoning=[])}
        performance = runner._npc_performances()
        self.assertIn("状态", performance)
        self.assertIn("→", performance)
        self.assertNotIn("npc_state", self.engine.public_state())

    def test_traces_snapshot_state_for_votes_and_night_actions(self):
        brain = Brain(self.seat, self.engine, {}, random.Random(13))
        candidates = [s.pos for s in self.engine.alive_seats()]
        brain.vote(candidates)
        brain.night("guard", [p for p in candidates if p != self.seat.pos])
        self.assertEqual({trace.action for trace in brain.decision_traces},
                         {"vote", "guard"})
        for trace in brain.decision_traces:
            self.assertIn("mood", trace.state_snapshot)
            self.assertIn("condition", trace.state_snapshot)

    def test_state_is_not_part_of_the_legal_information_set(self):
        brain = Brain(self.seat, self.engine, {}, random.Random(17))
        info = InformationSet.from_brain(brain)
        self.assertNotIn("match_state", info.private)
        self.assertNotIn("mood", info.private)


if __name__ == "__main__":
    unittest.main()
