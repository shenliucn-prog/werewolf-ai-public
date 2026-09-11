"""Synthetic, model-free paired experiment; emits aggregate results only.

Run: python -m scripts.compare_joint_policies --seeds 24
Each seed has one all-v1 baseline and twelve runs with only one v2 seat.
The baseline is reused, so seat pairs are correlated: do not infer significance
from the number of seat pairs. No user saves or model credentials are loaded.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
import contextlib
import io
import json
from unittest.mock import patch

from werewolf_web.ai import joint_belief
from werewolf_web.offline_game import OfflineSession, play
from werewolf_web.game.models import WOLF_ROLES


async def play_variant(seed, upgraded_seat=None, audit=False):
    session = OfflineSession(seed=seed)
    original_adapter = joint_belief.for_brain
    original_solver = joint_belief.infer_factions

    def scoped(brain):
        def solve(names, wolf_count, known, weights, relations=()):
            return original_solver(names, wolf_count, known, weights,
                relations if brain.me.pos == upgraded_seat else ())
        # Synchronous inference only; no await inside this temporary override.
        with patch.object(joint_belief, 'infer_factions', solve):
            return original_adapter(brain)

    with patch.object(joint_belief, 'for_brain', scoped), contextlib.redirect_stdout(io.StringIO()):
        code = await play(session, automatic=True)
    if code or not session.finished or session.faulted:
        raise RuntimeError(f'Synthetic game did not complete: seed={seed}, seat={upgraded_seat}')
    # Evaluator-only role labels, obtained after termination. Never sent to NPCs.
    outcome = session.engine.winner, {s.pos: s.role for s in session.engine.seats.values()}
    if audit:
        # Public trajectory only, for offline synthetic diagnostic runs.
        return (*outcome, [{key: event.get(key) for key in
                           ('type', 'day', 'night', 'phase', 'seat', 'name', 'text')}
                          for event in session._events if event['type'] in ('speech', 'ballots')])
    return outcome


async def compare(seeds):
    by_role = defaultdict(Counter)
    by_side = defaultdict(Counter)
    baseline_results = Counter()
    paired = []
    for seed in range(seeds):
        baseline, roster = await play_variant(seed)
        baseline_results[baseline] += 1
        seed_delta = 0
        for seat, role in sorted(roster.items()):
            outcome, variant_roster = await play_variant(seed, seat)
            if variant_roster != roster:
                raise AssertionError('Initial role assignment changed between paired games')
            side = 'wolf' if role in WOLF_ROLES else 'god'
            before, after = int(baseline == side), int(outcome == side)
            seed_delta += after - before
            for row in (by_role[role], by_side[side]):
                row['pairs'] += 1
                row['baseline_wins'] += before
                row['upgraded_wins'] += after
                row['improved'] += after > before
                row['regressed'] += after < before
        paired.append(seed_delta)
    return {'seeds': seeds, 'games': seeds * 13, 'seat_pairs': seeds * 12,
            'baseline_results': dict(baseline_results),
            'by_side': dict(by_side), 'by_role': dict(by_role),
            'seed_delta': {'positive': sum(d > 0 for d in paired),
                           'zero': sum(d == 0 for d in paired),
                           'negative': sum(d < 0 for d in paired)},
            'limits': 'Classic board only; automatic human-seat proxy; correlated pairs; '
                      'changed actions may shift subsequent RNG use; no real models or human play. '
                      'This is a pilot, not proof of strength or balance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 1000:
        parser.error('--seeds must be between 1 and 1000')
    print(json.dumps(asyncio.run(compare(args.seeds)), ensure_ascii=False, indent=2))
