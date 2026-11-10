"""Stage only tracked public engine sources/assets, never settings or saves."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
target = Path(__file__).parent / "app/build/staged-python"
names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode().split("\0")
files = [n for n in names if (
    n.startswith("werewolf_web/") and n.endswith(".py")
    or n == "werewolf_web/data/boards.json"
    or n.startswith("werewolf_web/data/personas/") and n.endswith(".md")
    or n == "LICENSE"
)]
manifest = {}
# This directory is generated exclusively by this script. Remove obsolete sources.
if target.exists():
    shutil.rmtree(target)
for name in files:
    origin = source / name
    destination = target / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origin, destination)
    manifest[name] = hashlib.sha256(origin.read_bytes()).hexdigest()
target.mkdir(parents=True, exist_ok=True)
(target / "SOURCE_MANIFEST.json").write_text(json.dumps({
    "upstream": "https://github.com/shenliucn-prog/werewolf-ai-public",
    "base": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source).decode().strip(),
    "files": manifest,
}, indent=2) + "\n")
print(f"Staged {len(files)} allowlisted public files; no private data or company source.")
