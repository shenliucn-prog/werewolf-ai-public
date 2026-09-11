"""Model-free paired ablation of wolf public-pressure scoring, aggregate only.

Both arms keep claim-continuity safeguards and the same joint inference.
All offline wolves use the scorer in the treatment; no scoring in control.
Not a comparison against the released version or proof of human playability.
"""
import asyncio
import contextlib
import io
import json
from unittest.mock import patch
from werewolf_web.ai import public_story
from werewolf_web.offline_game import OfflineSession, play


async def run(seed, enabled):
    original = public_story.for_brain

    def controlled(brain):
        result = original(brain)
        if not enabled:
            for row in result["targets"]:
                row["pressure_score"] = 0.0
        return result

    session = OfflineSession(seed=seed)
    with patch.object(public_story, "for_brain", controlled), contextlib.redirect_stdout(io.StringIO()):
        code = await play(session, automatic=True)
    if code or not session.finished or session.faulted:
        raise RuntimeError(f"Incomplete synthetic game: {seed}/{enabled}")
    return session.engine.winner, [(s.pos, s.role) for s in session.engine.seats.values()]


async def main():
    counts = {"control_wolf_wins": 0, "scorer_wolf_wins": 0,
              "improved": 0, "regressed": 0, "unchanged": 0}
    for seed in range(100, 124):
        baseline, roster = await run(seed, False)
        treatment, other_roster = await run(seed, True)
        assert roster == other_roster
        before, after = baseline == "wolf", treatment == "wolf"
        counts["control_wolf_wins"] += before
        counts["scorer_wolf_wins"] += after
        counts["improved" if after > before else "regressed" if after < before else "unchanged"] += 1
    print(json.dumps({"games": 48, "seed_range": [100, 123], **counts,
        "limitations": "24 paired classic offline auto-play seeds only; later random draws may diverge. "
            "No real model or human tests; no significance or overall strength claim."}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
