"""Explicit, bounded Codex CLI experiment. Outputs are generated research data.

Never import this runner into a game server. Existing CLI login is required;
this module does not read credentials, install tools, or edit user config.
No retries or response repairs: malformed output aborts with an audit artifact.
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

from .shadow_debate import PLAYERS, ShadowDay
from .judgment import build_request
from .shadow_schema import output_schema


DISABLED = ("shell_tool", "unified_exec", "apps", "plugins", "hooks", "browser_use",
            "computer_use", "image_generation", "code_mode_host", "multi_agent",
            "memories", "skill_search", "view_image")


def cli_command(binary, schema_path=None):
    return [binary, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "-c", 'approval_policy="never"',
            "-c", 'web_search="disabled"', "-c", 'model_reasoning_effort="medium"',
            "--model", "gpt-5.6-terra", "--json",
            *[item for name in DISABLED for item in ("--disable", name)],
            *(["--output-schema", str(schema_path)] if schema_path else []), "-"]


def extract_completion(stdout):
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    # Fail closed on any unknown item capability, rather than only a tool denylist.
    if any(i.get("type") not in {"agent_message", "reasoning", "error"} for i in items):
        raise ValueError("unexpected tool/capability item")
    if any(e.get("type") in {"turn.failed", "error"} for e in events):
        raise ValueError("Codex turn failed")
    messages = [i["text"] for i in items if i.get("type") == "agent_message"]
    turns = [e for e in events if e.get("type") == "turn.completed"]
    if len(messages) != 1 or len(turns) != 1:
        raise ValueError("expected one completed model response")
    return messages[0], turns[0].get("usage", {}), [i for i in items if i.get("type") == "error"]


def run_protocol(day, complete):
    """complete(label, sanitized_request) -> raw JSON, injectable for offline tests."""
    drafts = {}
    # Representative format gate: seer knowledge, wolf faction knowledge, unknown villager view.
    for p in ("A", "B", "D", "C", "E", "F", "G"):
        drafts[p] = complete(f"initial-{p}", day.player_request(p, "initial"))
        day.validate_submission(p, drafts[p])
        if p == "D":
            print('{"pilot_gate":"passed","actors":["A","B","D"]}', flush=True)
    day.publish_tables(drafts)
    for actor in ("A", "C"):
        target = day.challenge(actor, complete(f"challenge-{actor}", day.player_request(actor, "challenge")))
        if target:
            day.respond(target, complete(f"response-{actor}-{target}", day.player_request(target, "response")))
    day.close()
    drafts = {}
    for p in PLAYERS:
        drafts[p] = complete(f"revision-{p}", day.player_request(p, "revision"))
        day.validate_submission(p, drafts[p])
    day.publish_tables(drafts)
    day.publish_votes({p: complete(f"vote-{p}", day.player_request(p, "vote")) for p in PLAYERS})
    for context in day.judgment_contexts():
        day.record_shadow(context, complete(context.request_id, build_request(context)))


def initial_reuse(source, day):
    """Reuse only seven byte-preserved valid initial answers with identical inputs."""
    normalize = lambda value: json.loads(json.dumps(value))
    reused = {}
    for call in source["calls"]:
        label = call.get("label", "")
        if not label.startswith("initial-"):
            continue
        actor = label.removeprefix("initial-")
        if actor not in PLAYERS or label in reused:
            raise ValueError("invalid or duplicate initial replay")
        if call["request"] != normalize(day.player_request(actor, "initial")):
            raise ValueError("initial replay request differs from current protocol")
        day.validate_submission(actor, call["response"])
        reused[label] = call["response"]
    if set(reused) != {f"initial-{p}" for p in PLAYERS}:
        raise ValueError("initial replay must contain seven valid submissions")
    return reused


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-codex", action="store_true", help="explicitly allow up to 27 account-backed calls")
    parser.add_argument("--output", type=Path, required=True, help="new all-private research JSON path")
    parser.add_argument("--resume-initial-from", type=Path,
                        help="reuse only validated initial drafts with exactly matching inputs; records lineage")
    args = parser.parse_args()
    if not args.run_codex:
        parser.error("no calls made: --run-codex is required")
    if args.output.exists():
        parser.error("refusing to overwrite an existing run")
    binary = shutil.which("codex")
    if not binary:
        parser.error("Codex CLI not found; no installation attempted")
    day = ShadowDay()
    reuse = initial_reuse(json.loads(args.resume_initial_from.read_text(encoding="utf-8")), day) \
            if args.resume_initial_from else {}
    source_dir = Path(__file__).parent
    artifact = {"started_at": datetime.now(timezone.utc).isoformat(), "model": "gpt-5.6-terra",
                "reasoning_effort": "medium", "locale": "zh-CN", "max_calls": 27,
                "cli_version": subprocess.check_output([binary, "--version"], text=True).strip(),
                "source_sha256": {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
                                  for name in ("conjecture.py", "shadow_debate.py", "codex_shadow_run.py",
                                               "identity_constraints.py", "shadow_schema.py", "judgment.py")},
                "format_gate": ["A", "B", "D"], "calls": [], "status": "running"}
    if args.resume_initial_from:
        artifact["reused_initial_source"] = {"file": args.resume_initial_from.name,
            "sha256": hashlib.sha256(args.resume_initial_from.read_bytes()).hexdigest()}

    def checkpoint():
        artifact["experiment"] = day.research_export()
        args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    checkpoint()
    with tempfile.TemporaryDirectory(prefix="werewolf-shadow-") as isolated_cwd:
        def complete(label, request):
            if len(artifact["calls"]) >= 27:
                raise ValueError("call budget exhausted")
            call = {"label": label, "request": request, "status": "running"}
            artifact["calls"].append(call)
            if label in reuse:
                call.update(status="reused", response=reuse[label], new_model_call=False)
                checkpoint()
                return reuse[label]
            checkpoint()
            started = time.monotonic()
            try:
                schema = output_schema(request)
                schema_path = None
                if schema:
                    schema_path = Path(isolated_cwd) / "table-schema.json"
                    schema_path.write_text(json.dumps(schema), encoding="utf-8")
                    call["output_schema"] = schema
                result = subprocess.run(cli_command(binary, schema_path), cwd=isolated_cwd,
                    input="Use only the supplied task data. Do not use any tools. Return only the required JSON.\n"
                          + json.dumps(request, ensure_ascii=False),
                    text=True, capture_output=True, timeout=180, check=False)
                call["elapsed_seconds"] = round(time.monotonic() - started, 3)
                call["exit_code"] = result.returncode
                # Keep final answer and normalized runtime outcomes, not environment logs.
                if result.returncode:
                    raise ValueError(f"Codex exit {result.returncode}")
                raw, usage, warnings = extract_completion(result.stdout)
                call.update(response=raw, usage=usage, warnings=warnings, tool_events=0, status="returned")
                checkpoint()
                print(json.dumps({"completed": label, "calls": len(artifact["calls"]),
                                  "elapsed_seconds": call["elapsed_seconds"]}), flush=True)
                return raw
            except BaseException as error:
                call.update(status="failed", error=f"{type(error).__name__}: {error}")
                checkpoint()
                raise

        try:
            run_protocol(day, complete)
            artifact["status"] = "complete"
        except BaseException as error:
            artifact.update(status="failed", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            artifact["finished_at"] = datetime.now(timezone.utc).isoformat()
            artifact["usage"] = dict(sum((Counter(c.get("usage", {})) for c in artifact["calls"]), Counter()))
            checkpoint()
    print(json.dumps({"status": artifact["status"], "calls": len(artifact["calls"]),
                      "ballots": {p: v["target"] for p, v in day.votes.items()},
                      "shadow": [{"target": r["target"], "verdict": r["verdict"]} for r in day.shadow]}))


if __name__ == "__main__":
    main()
