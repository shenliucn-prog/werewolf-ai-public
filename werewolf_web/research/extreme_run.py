"""Explicit Codex-backed extreme-profile paired experiment; no retries/repairs.

Each invocation writes new files only. Prior failed artifacts remain immutable.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .codex_shadow_run import cli_command, extract_completion
from .extreme_game import ExtremeGame, play_game
from .extreme_profiles import roster_profiles
from .shadow_debate import PLAYERS
from .shadow_schema import output_schema


def run_one(index, output, binary):
    game = ExtremeGame(roster_profiles(index, PLAYERS))
    artifact = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                "model": "gpt-5.6-terra", "reasoning_effort": "medium", "condition": index,
                "calls": [], "max_calls": 110, "retry_policy": "none",
                "limitations": ["prompt-conditioned personality, not measured cognitive capacity",
                                "one sample per combination; not a win-rate or causal estimate",
                                "all profile values frozen; learning disabled",
                                "fixed identities, paired complementary profiles; no human participants"],
                "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in Path(__file__).parent.glob("*.py")}}

    def checkpoint():
        artifact["experiment"] = game.research_export()
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    checkpoint()
    with tempfile.TemporaryDirectory(prefix="werewolf-extreme-") as isolated:
        def complete(label, request):
            if len(artifact["calls"]) >= artifact["max_calls"]:
                raise ValueError("call limit exceeded")
            call = {"label": label, "request": request, "status": "running"}
            artifact["calls"].append(call)
            checkpoint()
            schema = Path(isolated) / "output-schema.json"
            schema.write_text(json.dumps(output_schema(request)), encoding="utf-8")
            started = time.monotonic()
            try:
                result = subprocess.run(cli_command(binary, schema), cwd=isolated,
                    input="Use only supplied data; no tools. Return the task JSON.\n" + json.dumps(request, ensure_ascii=False),
                    text=True, capture_output=True, timeout=180, check=False)
                if result.returncode:
                    raise ValueError(f"Codex exit {result.returncode}")
                raw, usage, warnings = extract_completion(result.stdout)
                call.update(response=raw, usage=usage, warnings=warnings, tool_events=0, status="returned")
                return raw
            except BaseException as error:
                call.update(status="failed", error=f"{type(error).__name__}: {error}")
                raise
            finally:
                call["elapsed_seconds"] = round(time.monotonic() - started, 3)
                checkpoint()
                print(json.dumps({"condition": index, "call": label, "status": call["status"],
                                  "calls": len(artifact["calls"])}), flush=True)
        try:
            play_game(game, complete)
            artifact["status"] = "complete"
        except Exception as error:
            artifact.update(status="failed", error=f"{type(error).__name__}: {error}")
        finally:
            artifact["finished_at"] = datetime.now(timezone.utc).isoformat()
            artifact["usage"] = dict(sum((Counter(c.get("usage", {})) for c in artifact["calls"]), Counter()))
            checkpoint()
    print(json.dumps({"condition": index, "status": artifact["status"], "winner": game.winner,
                      "error": artifact.get("error")}), flush=True)
    return artifact["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-codex", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--conditions", type=int, nargs="+", default=[0, 1, 2, 3])
    args = parser.parse_args()
    if not args.run_codex:
        parser.error("Explicit --run-codex required")
    if len(set(args.conditions)) != len(args.conditions) or not set(args.conditions) <= {0, 1, 2, 3}:
        parser.error("Choose distinct conditions 0–3")
    binary = shutil.which("codex")
    if not binary:
        parser.error("Codex login/CLI required; no installation attempted")
    outputs = [args.output_dir / f"condition-{i}.json" for i in args.conditions]
    if any(p.exists() for p in outputs):
        parser.error("Refusing to overwrite research artifacts")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, output in zip(args.conditions, outputs):
        if run_one(index, output, binary) != "complete":
            raise SystemExit("Stopped on first failure; remaining conditions not run")


if __name__ == "__main__":
    main()
