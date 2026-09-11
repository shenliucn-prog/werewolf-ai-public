"""Validate an existing tag and build a verified, history-free release bundle.

No network, tags, release creation or publication. Output must be outside Git.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess

from scripts.check_delivery import check
from scripts.prepare_release import prepare, bundle


def validate_tag(root, tag):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?", tag):
        raise ValueError("Use an existing version tag, not a branch or expression")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    head = git("rev-parse", "HEAD")
    tagged = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if head != tagged or git("status", "--porcelain"):
        raise ValueError("Release checkout must be clean and match the tag exactly")
    check(root=Path(root), release=tag)
    return head


def build(root, output, tag):
    root, output = Path(root).resolve(), Path(output).resolve()
    validate_tag(root, tag)
    prepare(output, root)
    result = bundle(output)
    archive = Path(result["archive"])
    checksum = archive.with_name(archive.name + ".sha256")
    with checksum.open("x", encoding="utf-8") as file:
        file.write(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    version = tag[1:]
    section = text.split(f"## {version}\n", 1)[1].split("\n## ", 1)[0]
    with archive.with_name("RELEASE_NOTES.md").open("x", encoding="utf-8") as file:
        file.write(section.strip() + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output, args.tag)
