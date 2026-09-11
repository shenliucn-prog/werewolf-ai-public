import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.release_candidate import validate_tag


class ReleaseTagTest(unittest.TestCase):
    def test_arbitrary_refs_rejected_before_git(self):
        for tag in ("master", "--help", "v1.0.0;echo", "v1.0.0\n", "v1.0.0-dev"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate_tag(Path("missing"), tag)

    def test_existing_tag_requires_exact_clean_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "base")
            git("tag", "v1.0.0")
            (root / "untracked").write_text("dirty")
            with self.assertRaisesRegex(ValueError, "clean"):
                validate_tag(root, "v1.0.0")
