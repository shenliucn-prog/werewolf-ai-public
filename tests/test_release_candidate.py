"""Metadata-only candidate export: keep originals, pixels and provenance bytes."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from scripts import check_release

from scripts.prepare_release import ROOT, allowed_path, prepare, redact_portrait, source_inventory, bundle


def chunks(data):
    result, offset = [], 8
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        end = offset + size + 12
        result.append((data[offset + 4:offset + 8], data[offset + 8:end - 4]))
        offset = end
    return result


def description_and_provenance(exif):
    order = ">" if exif[:2] == b"MM" else "<"
    first = struct.unpack_from(order + "I", exif, 4)[0]
    count = struct.unpack_from(order + "H", exif, first)[0]
    entries = [struct.unpack_from(order + "HHII", exif, first + 2 + 12 * i) for i in range(count)]
    _, _, length, offset = next(e for e in entries if e[0] == 270)
    return json.loads(exif[offset:offset + length].rstrip(b"\0")), exif[:offset] + exif[offset + length:]


class ReleaseCandidateTest(unittest.TestCase):
    def test_checker_rejects_tracked_and_historical_local_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".git").mkdir()
            (root / "werewolf_web/data").mkdir(parents=True)
            (root / "werewolf_web/data/boards.json").write_text('{"boards": [], "roles": {}}')
            for name in ("LICENSE", "README.md", "README.zh-CN.md", "CONTRIBUTING.md", "SECURITY.md", "docs/ASSETS.md"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            (root / "outputs").mkdir()
            (root / "outputs/game.json").write_text('{}')
            def fake_git(*args):
                if args[0] == "rev-list":
                    return b"abc outputs/old-game.json\n"
                return b"blob" if args[1] == "-t" else b"{}"
            with patch.object(check_release, "ROOT", root), patch.object(check_release, "source_inventory", return_value=(["outputs/game.json"], None)), patch.object(check_release, "git", side_effect=fake_git), patch("builtins.print") as output:
                self.assertTrue(check_release.check(history=True))
            report = json.loads(output.call_args.args[0])
            self.assertEqual(len(report["failures"]), 2)
            self.assertTrue(all("local-only artifact" in item for item in report["failures"]))

    def test_all_portraits_preserve_pixels_and_provenance_without_old_ids(self):
        paths = sorted((ROOT / "werewolf_web/static/img/portraits").glob("*.png"))
        self.assertEqual(len(paths), 30)
        for path in paths:
            original = path.read_bytes()
            result, removed = redact_portrait(original)
            before, after = chunks(original), chunks(result)
            if any(c[0] == b"caBX" for c in before):
                self.assertEqual(result, original)
                self.assertEqual(removed, [])
                continue
            self.assertEqual([c for c in before if c[0] != b"eXIf"], [c for c in after if c[0] != b"eXIf"])
            old_fields, old_envelope = description_and_provenance(next(c[1] for c in before if c[0] == b"eXIf"))
            fields, envelope = description_and_provenance(next(c[1] for c in after if c[0] == b"eXIf"))
            self.assertEqual(old_envelope, envelope)
            self.assertEqual(fields, {"AIGC": {"ServiceProvider": old_fields["AIGC"]["ServiceProvider"]}})
            for name in removed:
                self.assertNotIn(old_fields["AIGC"][name].encode(), result)
            self.assertEqual(path.read_bytes(), original)
            again, fields_removed = redact_portrait(result)
            self.assertEqual(again, result)
            self.assertEqual(fields_removed, [])

    def test_sensitive_paths_cannot_enter_candidate_even_if_tracked(self):
        for path in (".git/config", "werewolf_web/.env", "x/.env.local", "key.pem", "a.key",
                     "werewolf_web/data/reviews/a.md", "werewolf_web/data/npc_memory/a.json",
                     "werewolf_web/data/checkpoints/game.json", "werewolf_web/data/checkpoints/game.json.tmp",
                     "werewolf_web/data/host_style.en.json", "../escape", "/tmp/escape", "x/.venv/a.py",
                     "docs/research-runs/a.json", "docs/research-runs/source.tar.gz",
                     "docs/audit-assets/screen.png", "outputs/game.json", "output/log.json",
                     "playtest/notes.md", "PUBLICATION_MANIFEST.json"):
            self.assertFalse(allowed_path(path), path)
        for path in ("werewolf_web/.env.example", "LICENSE", ".github/workflows/ci.yml", "tests/test_debate.py"):
            self.assertTrue(allowed_path(path), path)

    def test_checkpoints_directory_is_gitignored(self):
        # The checkpoint store holds full identities + NPC private state; it must
        # be ignored by Git AND excluded from the release candidate even if a
        # file were force-added to the index.
        root = ROOT / ".gitignore"
        self.assertTrue(root.is_file())
        ignored = set(
            line.strip() for line in root.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        self.assertIn("werewolf_web/data/checkpoints/", ignored)
        probe = ROOT / "werewolf_web/data/checkpoints/game.json"
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.touch()
            import subprocess
            result = subprocess.run(
                ["git", "check-ignore", "-q", "werewolf_web/data/checkpoints/game.json"],
                cwd=ROOT)
            self.assertEqual(result.returncode, 0,
                             "werewolf_web/data/checkpoints/ must be git-ignored")
        finally:
            probe.unlink(missing_ok=True)
            try:
                probe.parent.rmdir()
            except OSError:
                pass

    def test_refuses_existing_and_source_paths(self):
        for path in (ROOT, ROOT / "new-candidate", ROOT.parent):
            with self.assertRaises(ValueError):
                prepare(path)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError):
                prepare(Path(folder))

    def test_export_manifest_matches_contents_and_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "candidate"
            result = prepare(target)
            expected = sum(bool(redact_portrait(p.read_bytes())[1])
                           for p in (ROOT / "werewolf_web/static/img/portraits").glob("*.png"))
            self.assertEqual(result["portraits_redacted"], expected)
            self.assertFalse((target / ".git").exists())
            manifest = json.loads((target / "PUBLICATION_MANIFEST.json").read_text())
            for entry in manifest["files"]:
                self.assertEqual(hashlib.sha256((target / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
                self.assertEqual(hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest(), entry["source_sha256"])
            self.assertFalse((target / "werewolf_web/data/npc_memory").exists())
            self.assertFalse((target / "werewolf_web/.env").exists())
            names, _ = source_inventory(target)
            self.assertEqual(len(names), len(manifest["files"]))
            # A history-free snapshot remains independently testable/exportable.
            second = Path(folder) / "second"
            self.assertEqual(prepare(second, root=target)["portraits_redacted"], 0)
            runtime = target / "werewolf_web/data/reviews/private.md"
            runtime.parent.mkdir(parents=True)
            runtime.write_text("NOT_FOR_PUBLICATION", encoding="utf-8")
            packed = bundle(target)
            with tarfile.open(packed["archive"]) as archive:
                self.assertNotIn("werewolf_web/data/reviews/private.md", archive.getnames())
                self.assertIn("PUBLICATION_MANIFEST.json", archive.getnames())
                for member in archive.getmembers():
                    self.assertEqual((member.uid, member.gid, member.uname, member.gname, member.mtime), (0, 0, "", "", 0))
            with self.assertRaises(FileExistsError):
                bundle(target)
            (target / "LICENSE").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                source_inventory(target)

    def test_unreviewed_metadata_fails_closed(self):
        with self.assertRaises(ValueError):
            redact_portrait(b"not an image")
