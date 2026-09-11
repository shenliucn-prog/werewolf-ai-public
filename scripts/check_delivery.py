"""Read-only delivery gate. Presence/consistency checks are not semantic review."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:dev|rc\.[1-9]\d*))?"


def validate_fragment(data, changed):
    if not isinstance(data, dict):
        raise ValueError("Change record must be an object")
    for field in ("summary", "compatibility"):
        value = data.get(field)
        if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("en", "zh")):
            raise ValueError(f"{field} requires English and Chinese text")
    impact = data.get("docs_impact")
    if impact not in ("none", "docs", "readme"):
        raise ValueError("Declare docs_impact: none/docs/readme")
    if not isinstance(data.get("reason"), str) or not data["reason"].strip():
        raise ValueError("Explain the documentation-impact decision")
    docs = data.get("docs")
    if not isinstance(docs, list) or any(not isinstance(p, str) for p in docs):
        raise ValueError("docs must list changed documentation paths")
    if impact != "none" and not docs:
        raise ValueError("Documentation changes are required")
    for path in docs:
        if path not in changed or not path.endswith(".md"):
            raise ValueError(f"Declared document was not changed: {path}")
    if impact == "readme" and not {"README.md", "README.zh-CN.md"} <= set(docs):
        raise ValueError("README-impact changes require both languages")


def check(root=ROOT, base=None, release=None):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError("Invalid VERSION")
    for name in ("README.md", "README.zh-CN.md"):
        if f"<!-- version: {version} -->" not in (root / name).read_text():
            raise ValueError(f"{name}: version marker differs from VERSION")
    changelog = (root / "CHANGELOG.md").read_text()
    if "## Unreleased" not in changelog:
        raise ValueError("CHANGELOG requires an Unreleased section")
    if base:
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=root).decode().splitlines()
        # Diff against the merge base in CI; the working tree locally. Include
        # new untracked files so the gate also works before the first commit.
        changed = set(git("diff", "--name-only", base, "--"))
        changed.update(git("ls-files", "--others", "--exclude-standard"))
        added = set(git("diff", "--name-only", "--diff-filter=A", base, "--"))
        added.update(git("ls-files", "--others", "--exclude-standard"))
        fragments = sorted(p for p in added if p.startswith(".changes/") and p.endswith(".json"))
        if changed and not fragments:
            raise ValueError("Each change requires a NEW .changes/*.json record; do not reuse an older PR's record")
        for path in fragments:
            validate_fragment(json.loads((root / path).read_text()), changed)
        if bool("README.md" in changed) != bool("README.zh-CN.md" in changed):
            raise ValueError("Review and update both README languages together")
    if release:
        if release != f"v{version}" or version.endswith("-dev"):
            raise ValueError("Release tag must equal vVERSION and must not be a development version")
        if f"## {version}\n" not in changelog:
            raise ValueError("Add the version's reviewed bilingual CHANGELOG section before release")
    print(f"Delivery checks passed ({version}); semantic documentation review is still required.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Trusted merge-base commit or local HEAD")
    parser.add_argument("--release", help="Validate a proposed tag, e.g. v0.1.0-rc.1; does not publish")
    args = parser.parse_args()
    try:
        check(base=args.base, release=args.release)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Delivery check failed: {error}\n")
