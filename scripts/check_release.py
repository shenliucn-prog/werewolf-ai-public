"""Portable, read-only release hygiene checks. Never print matched credentials.

Uses the working release candidate (tracked + non-ignored new files). Add
--history to scan text blobs reachable from local Git refs too. Neither check
proves the absence of secrets, personally identifying material or legal issues.
"""
import argparse
import gzip
import json
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.parse import unquote

try:
    from .prepare_release import source_inventory, MANIFEST, allowed_path
except ImportError:
    from prepare_release import source_inventory, MANIFEST, allowed_path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider-token": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential-url": re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@"),
    "machine-home-path": re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "machine-temp-path": re.compile(rb"/(?:private/)?var/folders/[A-Za-z0-9/_.-]+"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def check(history=False):
    failures = []
    files, _ = source_inventory(ROOT)
    has_git = (ROOT / ".git").exists()
    if not has_git:
        files.append(MANIFEST)
    texts = 0

    def inspect(label, data):
        nonlocal texts
        if b"\0" in data[:8192]:
            return
        texts += 1
        for kind, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append(f"{label}: possible {kind} (value redacted)")

    for name in files:
        path = ROOT / name
        if not path.is_file():
            continue
        if not allowed_path(name) and not (not has_git and name == MANIFEST):
            failures.append(f"{name}: local-only artifact must not be published")
        if name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                for member in archive.getmembers():
                    if member.isfile():
                        inspect(f"{name}:{member.name}", archive.extractfile(member).read())
            continue
        data = gzip.decompress(path.read_bytes()) if name.endswith(".json.gz") else path.read_bytes()
        inspect(name, data)
        if path.suffix == ".md":
            # Destination existence only; anchors and remote URLs need separate review.
            for target in re.findall(r"\]\(([^\s)]+)\)", data.decode("utf-8")):
                target = unquote(target.strip("<>").split("#")[0])
                if target and not re.match(r"[a-zA-Z][\w+.-]*:", target):
                    if not (path.parent / target).exists():
                        failures.append(f"{name}: missing link destination {target}")
    boards = json.loads((ROOT / "werewolf_web/data/boards.json").read_text())
    ids = [b["id"] for b in boards["boards"]]
    if len(ids) != len(set(ids)):
        failures.append("boards: duplicate stable ID")
    for board in boards["boards"]:
        if len(board["roles"]) != 12 or not set(board["roles"]) <= set(boards["roles"]):
            failures.append(f"boards: invalid roster for {board['id']}")
    for name in ("LICENSE", "README.md", "README.zh-CN.md", "CONTRIBUTING.md", "SECURITY.md", "docs/ASSETS.md"):
        if not (ROOT / name).is_file():
            failures.append(f"Missing {name}")
    history_blobs = 0
    if history and has_git:
        for entry in git("rev-list", "--objects", "--all").decode().splitlines():
            oid, _, name = entry.partition(" ")
            if name and git("cat-file", "-t", oid).strip() == b"blob":
                if not allowed_path(name):
                    failures.append(f"history:{oid[:12]}:{name}: local-only artifact")
                inspect(f"history:{oid[:12]}:{name}", git("cat-file", "blob", oid))
                history_blobs += 1
    print(json.dumps({"status": "failed" if failures else "passed", "candidate_files": len(files),
                      "git_history_available": has_git,
                      "text_payloads_checked": texts, "history_blobs_checked": history_blobs,
                      "boards": len(ids), "failures": failures}, ensure_ascii=False, indent=2))
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    raise SystemExit(check(parser.parse_args().history))
