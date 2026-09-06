"""Replay a finished/failed research artifact without any model calls.

Usage: python tests/audit_extreme.py path/to/condition-N.json
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werewolf_web.research.extreme_game import ExtremeGame, play_game
from werewolf_web.research.extreme_profiles import roster_profiles
from werewolf_web.research.shadow_debate import PLAYERS


def audit(path):
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if artifact["status"] not in ("complete", "failed"):
        raise ValueError("not a finished artifact")
    source = Path(__file__).resolve().parents[1] / "werewolf_web" / "research"
    changed = [name for name, digest in artifact["source_sha256"].items()
               if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError(f"source files changed: {changed}")
    normalize = lambda x: json.loads(json.dumps(x))
    if artifact["experiment"]["profiles"] != roster_profiles(artifact["condition"], PLAYERS):
        raise AssertionError("profile assignment differs from registered condition")
    game = ExtremeGame(artifact["experiment"]["profiles"])
    calls = iter(artifact["calls"])
    replayed = 0
    def complete(label, request):
        nonlocal replayed
        call = next(calls)
        if call["label"] != label or call["request"] != normalize(request):
            raise AssertionError(f"request mismatch at {label}")
        replayed += 1
        if call["status"] == "failed":
            raise RuntimeError(call["error"])
        return call["response"]
    error = None
    try:
        play_game(game, complete)
    except (ValueError, KeyError, RuntimeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    if replayed != len(artifact["calls"]):
        raise AssertionError("not all recorded calls consumed")
    if artifact["status"] == "complete" and error:
        raise AssertionError(error)
    if artifact["status"] == "failed" and error != artifact.get("error"):
        raise AssertionError("failure differs on replay")
    if normalize(game.research_export()) != artifact["experiment"]:
        raise AssertionError("state mismatch")
    usage = dict(sum((Counter(c.get("usage", {})) for c in artifact["calls"]), Counter()))
    if usage != artifact["usage"]:
        raise AssertionError("usage mismatch")
    output = {"file": Path(path).name, "status": artifact["status"], "winner": game.winner,
              "replayed_calls": replayed, "completed_days": len(game.days), "usage": usage,
              "error": error, "audit": "exact requests, terminal state, usage and source hashes match"}
    print(json.dumps(output, ensure_ascii=False))
    return output


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        audit(filename)
