from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_delivery import check, validate_fragment


class DeliveryTest(unittest.TestCase):
    def record(self):
        return {"summary": {"en": "Feature", "zh": "功能"},
                "compatibility": {"en": "Unchanged", "zh": "不变"},
                "docs_impact": "readme", "reason": "Entry behavior changed",
                "docs": ["README.md", "README.zh-CN.md"]}

    def test_bilingual_readme_change(self):
        validate_fragment(self.record(), {"README.md", "README.zh-CN.md"})

    def test_missing_translation_rejected(self):
        data = self.record()
        del data["summary"]["zh"]
        with self.assertRaises(ValueError):
            validate_fragment(data, set(data["docs"]))

    def test_unchanged_declared_document_rejected(self):
        with self.assertRaises(ValueError):
            validate_fragment(self.record(), {"README.md"})

    def test_internal_change_requires_reason(self):
        data = self.record()
        data.update(docs_impact="none", docs=[])
        validate_fragment(data, {"code.py"})
        data["reason"] = ""
        with self.assertRaises(ValueError):
            validate_fragment(data, {"code.py"})

    def test_bad_records_rejected_without_mutation(self):
        for value in (None, [], {}, {"summary": "bad"}):
            before = deepcopy(value)
            with self.assertRaises(ValueError):
                validate_fragment(value, set())
            self.assertEqual(value, before)

    def setup_root(self, root, version="0.1.0-dev"):
        (root / "VERSION").write_text(version)
        for name in ("README.md", "README.zh-CN.md"):
            (root / name).write_text(f"<!-- version: {version} -->")
        (root / "CHANGELOG.md").write_text("## Unreleased\n")

    def test_release_rejects_dev_mismatch_or_missing_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            with self.assertRaises(ValueError):
                check(root, release="v0.1.0-dev")
            self.setup_root(root, "0.1.0")
            with self.assertRaises(ValueError):
                check(root, release="v0.2.0")
            with self.assertRaises(ValueError):
                check(root, release="v0.1.0")
            (root / "CHANGELOG.md").write_text("## Unreleased\n\n## 0.1.0\nReviewed bilingual release notes.\n")
            check(root, release="v0.1.0")

    def test_readme_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            (root / "README.md").write_text("stale")
            with self.assertRaises(ValueError):
                check(root)

    def test_old_fragment_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.setup_root(root)
            with patch("scripts.check_delivery.subprocess.check_output", side_effect=[
                b"code.py\n.changes/old.json\n", b"", b"", b""]):
                with self.assertRaisesRegex(ValueError, "NEW"):
                    check(root, base="base")
