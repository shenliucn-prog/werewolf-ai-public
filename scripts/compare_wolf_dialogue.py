"""Paired, model-free v2 dialogue ablation on synthetic classic games.

Control retains shared inference/public-pressure v1, with black-only reports,
no proactive public moves and no reversal explanation. This is an ablation,
not a frozen released-version comparison. No user games or model calls.
"""
import asyncio
import argparse
import contextlib
import io
import json
from collections import Counter
from unittest.mock import patch

from werewolf_web.ai import wolf_dialogue
from werewolf_web.game.models import WOLF_ROLES
from werewolf_web.offline_game import OfflineSession, play


def old_check(brain, story, pool, previous):
    if not pool:
        return None
    weights = {r["target"]: r["pressure_score"] for r in story["targets"]}
    best = max(weights[s.pos] for s in pool)
    target = brain.rng.choice([s for s in pool if weights[s.pos] == best])
    return {"night": brain.engine.night_count, "target": target.pos,
            "name": target.name, "result": "wolf"}


async def run(seed, enabled, factors=None, *, board_id="classic", opponent="joint"):
    if opponent not in ("joint", "unary"):
        raise ValueError("Unknown opponent inference policy")
    session = OfflineSession(board_id, seed=seed)
    selected = set(factors) if factors is not None else ({"claims", "reports", "support", "reversal"} if enabled else set())
    if selected - {"claims", "reports", "support", "reversal"}:
        raise ValueError("Unknown dialogue factor")
    original_move = wolf_dialogue.public_move

    def move(brain, story):
        if "claims" not in selected and not story["own_claims"]:
            # Skip only the claim branch to test support independently.
            story = dict(story, own_claims=["ablation:withheld"])
        result = original_move(brain, story)
        if result and result.startswith("support:") and "support" not in selected:
            return None
        return result

    with contextlib.ExitStack() as stack:
        if opponent == "unary":
            from werewolf_web.ai import joint_belief
            original_adapter = joint_belief.for_brain
            original_solver = joint_belief.infer_factions

            def unary_good(brain):
                def solve(names, wolf_count, known, weights, relations=()):
                    return original_solver(names, wolf_count, known, weights,
                                           relations if brain.is_wolf else ())
                # Synchronous call: own faction selects the lawful policy;
                # never expose opponents' roles or brains to the acting agent.
                with patch.object(joint_belief, "infer_factions", solve):
                    return original_adapter(brain)

            stack.enter_context(patch.object(joint_belief, "for_brain", unary_good))
        if "reports" not in selected:
            stack.enter_context(patch.object(wolf_dialogue, "new_check", old_check))
        stack.enter_context(patch.object(wolf_dialogue, "public_move", move))
        if "reversal" not in selected:
            stack.enter_context(patch.object(wolf_dialogue, "reversal_prefix", return_value=""))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        code = await play(session, automatic=True)
    if code or not session.finished or session.faulted:
        raise RuntimeError(f"Incomplete synthetic game: {seed}/{enabled}")
    # Terminal evaluator only: hidden roles never enter the dialogue adapter.
    wolves = {s.name for s in session.engine.seats.values() if s.role in WOLF_ROLES}
    behavior = Counter()
    for ev in session._events:
        if ev.get("type") != "speech" or ev.get("name") not in wolves:
            continue
        behavior["wolf_speeches"] += 1
        behavior["support_speeches"] += bool(ev.get("defend"))
        behavior["civilian_claims"] += ev.get("claim") == "civilian"
        behavior["hunter_claims"] += ev.get("claim") == "hunter"
        behavior["explained_reversals"] += "我现在重新考虑" in ev.get("text", "")
    return session.engine.winner, [(s.pos, s.role) for s in session.engine.seats.values()], behavior


async def main(seed_start=200, seeds=24):
    counts = Counter()
    behavior = {"control": Counter(), "dialogue": Counter()}
    for seed in range(seed_start, seed_start + seeds):
        baseline, roster, old_behavior = await run(seed, False)
        treatment, other_roster, new_behavior = await run(seed, True)
        assert roster == other_roster
        before, after = baseline == "wolf", treatment == "wolf"
        counts["control_wolf_wins"] += before
        counts["dialogue_wolf_wins"] += after
        counts["improved" if after > before else "regressed" if after < before else "unchanged"] += 1
        behavior["control"].update(old_behavior)
        behavior["dialogue"].update(new_behavior)
    print(json.dumps({"games": seeds * 2, "seed_range": [seed_start, seed_start + seeds - 1], **counts,
                      "behavior": behavior,
                      "limitations": "Single classic offline opponent family. "
                      "Later RNG draws may diverge; raw speech counts depend on game length. "
                      "No human or real-model validation, no significance claim."}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-start", type=int, default=200)
    parser.add_argument("--seeds", type=int, default=24)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    asyncio.run(main(args.seed_start, args.seeds))
