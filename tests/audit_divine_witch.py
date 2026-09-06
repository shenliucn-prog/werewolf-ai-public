"""Recompute aggregates and replay recorded local games, without model calls."""
import asyncio
from collections import Counter, defaultdict
import json
import gzip
import argparse
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, os.environ.get("WEREWOLF_REPLAY_SOURCE", str(Path(__file__).resolve().parents[1])))
from werewolf_web.research.divine_witch_screen import BOARDS, run_one, source_hashes


def first_difference(a, b, path=""):
    if type(a) is not type(b): return (path, a, b)
    if isinstance(a, dict):
        if a.keys() != b.keys(): return (path + "/keys", sorted(a), sorted(b))
        for key in a:
            d = first_difference(a[key], b.get(key), path + "/" + key)
            if d: return d
    elif isinstance(a, list):
        if len(a) != len(b): return (path + "/length", len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, path + "/" + str(i))
            if d: return d
    elif a != b: return (path, a, b)


async def audit(path, compare_current=False):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file: artifact = json.load(file)
    same_source = artifact["source_sha256"] == source_hashes()
    assert same_source or compare_current, "source mismatch; restore the recorded source or use --compare-current for a compatibility check"
    assert artifact["provider_calls"] == 0
    games = artifact["games"]
    keys = [(g["board"], g["seed"], g["condition"]) for g in games]
    assert len(keys) == len(set(keys)) == len(artifact["seeds"]) * 4 * 3
    assert set(keys) == {(b, s, c) for b in BOARDS for s in artifact["seeds"] for c in range(4)}
    groups = defaultdict(list)
    for g in games: groups[(g["seed"], g["condition"])].append(g)
    for group in groups.values():
        assignments = [[(s["pos"], s["player_id"], s["role"]) for s in g["seats"]] for g in group]
        assert assignments[0] == assignments[1] == assignments[2]
        assert group[0]["profiles"] == group[1]["profiles"] == group[2]["profiles"]
    for b in BOARDS:
        selected = [g for g in games if g["board"] == b]
        expected = artifact["summary"][b]
        assert len(selected) == expected["attempts"]
        assert Counter(g["winner"] or g["status"] for g in selected) == expected["outcomes"]
        uses = Counter()
        for g in selected:
            wolf_positions = {s["pos"] for s in g["seats"] if s["is_wolf"]}
            for night in g["nights"]:
                a = night["actions"].get("witch", {})
                save, poison = a.get("save"), a.get("poison")
                uses["saves_attempted"] += save is not None
                uses["poisons_attempted"] += poison is not None
                uses["poison_wolf"] += poison is not None and poison in wolf_positions
                uses["poison_good"] += poison is not None and poison not in wolf_positions
                uses["dual_nights"] += save is not None and poison is not None
                uses["witch_action_nights"] += night["witch_alive_before"]
                uses["guard_save_collision"] += save is not None and save == night["actions"].get("guard", {}).get("target")
        for key, value in uses.items(): assert value == expected.get(key, 0), (b, key)
        assert max(len(g["nights"]) for g in selected) == expected["max_nights"]
    sleep = asyncio.sleep
    async def fast(_): await sleep(0)
    with patch("werewolf_web.run.asyncio.sleep", fast):
        for g in games:
            replay = await run_one(g["board"], g["seed"], g["condition"])
            difference = first_difference(g, json.loads(json.dumps(replay)))
            assert difference is None, (g["board"], g["seed"], g["condition"], difference)
    print(json.dumps({"audit": "passed", "replayed_games": len(games), "source_hashes": "match" if same_source else "different: compatibility replay only",
                      "matched_assignments": len(groups), "independent_aggregates": "match", "provider_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("--compare-current", action="store_true", help="Check unchanged game trajectories against newer source; does not certify source identity")
    args = parser.parse_args()
    asyncio.run(audit(args.artifact, args.compare_current))
