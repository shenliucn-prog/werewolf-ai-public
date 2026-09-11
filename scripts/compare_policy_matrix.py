"""Synthetic multi-board paired checks, not a human/model strength benchmark."""
import asyncio
from collections import Counter
import json
from scripts.compare_wolf_dialogue import run


async def main():
    results = []
    for board in ("classic", "hidden_wolf_crow", "stone_ghost"):
        for opponent in ("unary", "joint"):
            counts = Counter()
            for seed in range(500, 508):
                before, roster, _ = await run(seed, False, board_id=board, opponent=opponent)
                after, other_roster, _ = await run(seed, True, board_id=board, opponent=opponent)
                assert roster == other_roster
                old_win, new_win = before == "wolf", after == "wolf"
                counts["control_wolf_wins"] += old_win
                counts["dialogue_wolf_wins"] += new_win
                counts["improved" if new_win > old_win else "regressed" if new_win < old_win else "unchanged"] += 1
            results.append({"board": board, "opponent": opponent, "pairs": 8, **counts})
    print(json.dumps({"games": 96, "seed_range": [500, 507], "results": results,
        "limitations": "Only two ablations of one offline opponent family. Unary retains "
        "fixed roster and private facts but drops good-side pairwise opinion factors. "
        "Not independently trained/stronger opponents. Paired seeds share roster, not subsequent RNG. "
        "No real models or human games; small samples do not establish balance."}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
