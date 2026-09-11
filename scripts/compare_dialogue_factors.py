"""Separate dialogue effects using 24 fresh seeds; outputs aggregates only.

Each baseline is shared across five variants, so comparisons are correlated.
No coefficient tuning, model calls or local user data.
"""
import asyncio
from collections import Counter
import json
from scripts.compare_wolf_dialogue import run


async def main():
    factors = ("claims", "reports", "support", "reversal", "all")
    counts = {name: Counter() for name in ("control", *factors)}
    for seed in range(400, 424):
        baseline, roster, behavior = await run(seed, False)
        counts["control"]["wolf_wins"] += baseline == "wolf"
        counts["control"].update(behavior)
        for name in factors:
            selected = {"claims", "reports", "support", "reversal"} if name == "all" else {name}
            winner, other_roster, behavior = await run(seed, True, selected)
            assert roster == other_roster
            before, after = baseline == "wolf", winner == "wolf"
            counts[name]["wolf_wins"] += after
            counts[name]["improved" if after > before else "regressed" if after < before else "unchanged"] += 1
            counts[name].update(behavior)
    print(json.dumps({"games": 144, "seed_range": [400, 423], "results": counts,
                      "limitations": "One classic offline opponent family; shared baseline, "
                      "RNG divergence and game-length-dependent counts. Report factor bundles "
                      "polarity and target continuity, not good-check polarity alone. "
                      "No human/model benefit or balance claim."}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
