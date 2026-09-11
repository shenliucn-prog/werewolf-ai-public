import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from werewolf_web.ai.joint_belief import infer_factions, for_brain
from werewolf_web.offline_game import OfflineSession
from werewolf_web.ai.model_context import fit_request_budget


class JointSolverTest(unittest.TestCase):
    def test_accusation_can_mean_true_accuser_or_deceptive_accuser(self):
        names = ['a', 'b', 'c', 'd']
        relation = [{'speaker': 'a', 'target': 'b', 'kind': 'accuse'}]
        baseline = infer_factions(names, 1, {'a': False}, {})
        truthful = infer_factions(names, 1, {'a': False}, {}, relation)
        self.assertGreater(truthful['wolf_weights']['b'], baseline['wolf_weights']['b'])
        baseline = infer_factions(names, 1, {'b': False}, {})
        deceptive = infer_factions(names, 1, {'b': False}, {}, relation)
        self.assertGreater(deceptive['wolf_weights']['a'], baseline['wolf_weights']['a'])
        self.assertGreater(deceptive['wolf_weights']['c'], 0)  # honest mistake remains possible

    def test_repetition_and_order_do_not_change_inference(self):
        relations = [{'speaker': 'a', 'target': 'b', 'kind': 'accuse'},
                     {'speaker': 'c', 'target': 'b', 'kind': 'defend'}]
        expected = infer_factions(['a', 'b', 'c', 'd'], 1, {}, {}, relations)
        self.assertEqual(expected, infer_factions(['a', 'b', 'c', 'd'], 1, {}, {}, list(reversed(relations)) * 100))

    def test_support_and_accusation_on_same_pair_cancel(self):
        names = ['a', 'b', 'c', 'd']
        relations = [{'speaker': 'a', 'target': 'b', 'kind': k} for k in ('accuse', 'defend')]
        expected = infer_factions(names, 1, {'a': False}, {})
        actual = infer_factions(names, 1, {'a': False}, {}, relations)
        self.assertEqual(expected['wolf_weights'], actual['wolf_weights'])

    def test_opinions_never_eliminate_known_worlds(self):
        relations = [{'speaker': 'a', 'target': 'b', 'kind': 'accuse'}]
        result = infer_factions(['a', 'b', 'c'], 1, {'a': False, 'b': False}, {}, relations)
        self.assertEqual(result['wolf_weights'], {'a': 0, 'b': 0, 'c': 1})

    def test_uniform_fixed_count_and_joint_exclusion(self):
        result = infer_factions(['a', 'b', 'c', 'd'], 2, {'a': False}, {})
        self.assertEqual(result['world_count'], 3)
        self.assertAlmostEqual(sum(result['wolf_weights'].values()), 2)
        self.assertEqual(result['wolf_weights']['a'], 0)
        self.assertAlmostEqual(result['wolf_weights']['b'], 2 / 3)

    def test_soft_claim_cannot_override_hard_fact(self):
        result = infer_factions(['a', 'b', 'c'], 1, {'a': False}, {'a': 1, 'b': .8, 'c': .2})
        self.assertEqual(result['wolf_weights']['a'], 0)
        self.assertGreater(result['wolf_weights']['b'], result['wolf_weights']['c'])
        self.assertAlmostEqual(sum(result['wolf_weights'].values()), 1)

    def test_contradictory_or_nonfinite_input_rejected(self):
        with self.assertRaises(ValueError):
            infer_factions(['a', 'b'], 1, {'a': True, 'b': True}, {})
        with self.assertRaises(ValueError):
            infer_factions(['a', 'b'], 1, {}, {'a': float('nan')})

    def test_optional_aid_is_dropped_before_sources(self):
        request = {'public_context': {'recent_public_statements': ['important']},
                   'joint_hypotheses': {'long': 'x' * 1000}}
        fitted = fit_request_budget(request, 100)
        self.assertNotIn('joint_hypotheses', fitted)
        self.assertEqual(fitted['public_context']['recent_public_statements'], ['important'])


class JointIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_sheriff_support_is_not_exile_suspicion(self):
        from werewolf_web.ai.strategy import StrategicVotePlanner, BeliefState
        session = OfflineSession(seed=4, player_role='civilian')
        await session._step_setup()
        brain = session.proxy.brain
        targets = [s for s in session.engine.seats.values() if s.name != brain.name][:2]
        beliefs = BeliefState({targets[0].name: {'wolf': .9, 'good': .1},
                              targets[1].name: {'wolf': .1, 'good': .9}})
        with patch.object(BeliefState, 'from_brain', return_value=beliefs), \
             patch.object(brain.rng, 'uniform', return_value=0), \
             patch.object(brain.cognition, 'choose_depth', return_value=(1, False)):
            planner = StrategicVotePlanner(brain)
            candidates = [s.pos for s in targets]
            self.assertEqual(planner.plan(candidates, sheriff=True).target, targets[1].pos)
            self.assertEqual(planner.plan(candidates).target, targets[0].pos)

    async def test_wolf_can_support_known_teammate_for_sheriff(self):
        from werewolf_web.ai.strategy import StrategicVotePlanner
        session = OfflineSession(seed=4, player_role='werewolf')
        await session._step_setup()
        brain = session.proxy.brain
        mate = next(s for s in session.engine.seats.values() if s.name in brain.mates())
        other = next(s for s in session.engine.seats.values() if s.name not in brain.mates() and s.name != brain.name)
        with patch.object(brain.rng, 'uniform', return_value=0), \
             patch.object(brain.cognition, 'choose_depth', return_value=(1, False)):
            self.assertEqual(StrategicVotePlanner(brain).plan([mate.pos, other.pos], sheriff=True).target, mate.pos)

    async def test_own_opinions_are_not_new_evidence_to_self(self):
        session = OfflineSession(seed=4, player_role='civilian')
        await session._step_setup()
        brain = session.proxy.brain
        target = next(s.name for s in session.engine.seats.values() if s.name != brain.name)
        before = for_brain(brain)
        brain.accuse_log.append((1, brain.name, target))
        self.assertEqual(for_brain(brain), before)
        brain.defend_log.append((2, brain.name, target))
        self.assertEqual(for_brain(brain), before)

    async def test_relation_memory_restore_and_flip_no_double_count(self):
        session = OfflineSession(seed=4, player_role='civilian')
        await session._step_setup()
        brain = session.proxy.brain
        others = [s for s in session.engine.seats.values() if s.name != brain.name]
        brain.accuse_log = [(1, others[0].name, others[1].name)] * 4
        before = for_brain(brain)
        self.assertEqual(before['relation_count'], 1)
        restored = OfflineSession()
        restored.restore(json.loads(json.dumps(session.snapshot())))
        self.assertEqual(for_brain(restored.proxy.brain), before)
        brain.observe_flip(others[1].name, others[1].role_cn, others[1].is_wolf)
        self.assertEqual(for_brain(brain)['relation_count'], 0)

    async def test_model_receives_aid_but_keeps_its_own_choice(self):
        from werewolf_web.ai.decision_runtime import RuntimeBase
        from werewolf_web.session import GameSession
        runtime = RuntimeBase('test-model')
        runtime.backend = 'api'
        runtime.verified = True
        runtime.complete = Mock(return_value={'target': None})
        session = GameSession('classic', seed=4, planner=runtime)
        await session._step_setup()
        agent = next(a for a in session.agents.values() if a.brain.role == 'civilian')
        candidates = [{'pos': s.pos, 'name': s.name} for s in session.engine.alive_seats()]
        self.assertIsNone(agent.vote(candidates))  # model may abstain despite ranking
        runtime.complete.assert_called_once()
        request = runtime.complete.call_args.args[0]
        self.assertFalse(request['joint_hypotheses']['calibrated'])
        self.assertEqual(request['joint_hypotheses'], for_brain(agent.brain))
        self.assertLessEqual(len(json.dumps(request, ensure_ascii=False)), 24000)

    async def test_public_dead_wolf_consumes_original_roster_count(self):
        session = OfflineSession(seed=4, player_role='civilian')
        await session._step_setup()
        brain = session.proxy.brain
        wolf = next(s for s in session.engine.seats.values() if s.is_wolf)
        wolf.alive = False
        brain.observe_flip(wolf.name, wolf.role_cn, True)
        result = for_brain(brain)
        self.assertEqual(result['wolf_weights'][wolf.name], 1)
        self.assertAlmostEqual(sum(w for n, w in result['wolf_weights'].items() if n != wolf.name), result['wolf_count'] - 1)

    async def test_civilian_hidden_assignment_invariance_and_restore(self):
        session = OfflineSession(seed=4, player_role='civilian')
        await session._step_setup()
        brain = session.proxy.brain
        before = for_brain(brain)
        snapshot = deepcopy(session.snapshot())
        others = [s for s in session.engine.seats.values() if s.name != brain.name]
        others[0].role, others[1].role = others[1].role, others[0].role
        others[0].is_wolf, others[1].is_wolf = others[1].is_wolf, others[0].is_wolf
        session.engine.seer_results.append({'name': others[0].name, 'result': 'wolf', 'night': 1, 'target': others[0].pos})
        self.assertEqual(for_brain(brain), before)
        restored = OfflineSession()
        restored.restore(json.loads(json.dumps(snapshot)))
        self.assertEqual(for_brain(restored.proxy.brain), before)
        self.assertEqual(restored.snapshot(), snapshot)

    async def test_private_check_and_hidden_wolf_exception(self):
        for board in ('classic', 'hidden_wolf_crow'):
            session = OfflineSession(board, seed=4, player_role='seer')
            await session._step_setup()
            brain = session.proxy.brain
            target = next(s for s in session.engine.seats.values() if s.name != brain.name)
            session.engine.seer_results.append({'name': target.name, 'result': 'good', 'night': 1, 'target': target.pos})
            weight = for_brain(brain)['wolf_weights'][target.name]
            if board == 'classic':
                self.assertEqual(weight, 0)
            else:
                self.assertGreater(weight, 0)
