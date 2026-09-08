"""Build an exclusive, history-free local candidate; never edit the source tree.

This only handles the reviewed portrait metadata layout. Unknown layouts fail
closed. It preserves compressed pixel data and the separate provenance envelope
byte-for-byte; this is NOT signature validation or a general metadata scrubber.
"""
import argparse
import hashlib
import gzip
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import zlib

try:
    from .audit_publication import PNG_SIGNATURE, png_metadata
except ImportError:
    from audit_publication import PNG_SIGNATURE, png_metadata

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FIELDS = {"ServiceUser", "Time", "ContentId"}
PORTRAITS = "werewolf_web/static/img/portraits/"
MANIFEST = "PUBLICATION_MANIFEST.json"


def redact_exif(data):
    if len(data) < 8 or data[:2] not in (b"MM", b"II"):
        raise ValueError("Unsupported EXIF format")
    order = ">" if data[:2] == b"MM" else "<"
    if struct.unpack_from(order + "H", data, 2)[0] != 42:
        raise ValueError("Unsupported TIFF format")
    first = struct.unpack_from(order + "I", data, 4)[0]
    if first < 8 or first + 2 > len(data):
        raise ValueError("Invalid EXIF directory")
    count = struct.unpack_from(order + "H", data, first)[0]
    directory_end = first + 2 + 12 * count + 4
    if directory_end > len(data):
        raise ValueError("Truncated EXIF directory")
    tags = {}
    for i in range(count):
        tag, kind, length, offset = struct.unpack_from(order + "HHII", data, first + 2 + 12 * i)
        if tag in tags:
            raise ValueError("Duplicate EXIF tag")
        tags[tag] = (kind, length, offset)
    if set(tags) != {270, 34665} or struct.unpack_from(order + "I", data, directory_end - 4)[0]:
        raise ValueError("Unreviewed EXIF layout; inspect before exporting")
    kind, length, offset = tags[270]
    if kind != 2 or length <= 4 or offset < directory_end or offset + length > len(data):
        raise ValueError("Unsupported description storage")
    # The second IFD and its signed UserComment must not overlap the edited span.
    exif_kind, exif_count, exif_offset = tags[34665]
    if exif_kind != 4 or exif_count != 1 or exif_offset < offset + length or exif_offset + 2 > len(data):
        raise ValueError("Unsupported provenance directory")
    if struct.unpack_from(order + "H", data, exif_offset)[0] != 1 or exif_offset + 18 > len(data):
        raise ValueError("Unreviewed provenance tags")
    comment_tag, comment_kind, comment_size, comment_offset = struct.unpack_from(order + "HHII", data, exif_offset + 2)
    if (comment_tag != 37510 or comment_kind != 7 or comment_size <= 4
            or comment_offset < exif_offset + 18 or comment_offset + comment_size != len(data)
            or struct.unpack_from(order + "I", data, exif_offset + 14)[0]):
        raise ValueError("Unsupported signed comment storage")
    description = json.loads(data[offset:offset + length].rstrip(b"\0").decode("utf-8"))
    if not isinstance(description, dict) or set(description) != {"AIGC"}:
        raise ValueError("Unreviewed description")
    fields = description["AIGC"]
    if (not isinstance(fields, dict) or "ServiceProvider" not in fields
            or not set(fields) <= PRIVATE_FIELDS | {"ServiceProvider"}
            or not all(isinstance(v, str) for v in fields.values())):
        raise ValueError("Unreviewed AIGC fields")
    removed = sorted(set(fields) & PRIVATE_FIELDS)
    preserved = data[:offset] + data[offset + length:]
    for field in removed:
        value = fields[field].encode("utf-8")
        if value and value in preserved:
            raise ValueError("Private value also occurs in preserved metadata; inspect manually")
    clean = json.dumps({"AIGC": {"ServiceProvider": fields["ServiceProvider"]}},
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(clean) >= length:
        raise ValueError("Insufficient existing metadata space")
    # Zero the entire old allocation, not just the visible JSON: no orphaned IDs.
    result = data[:offset] + clean + b"\0" * (length - len(clean)) + data[offset + length:]
    return result, removed


def redact_portrait(data):
    metadata = png_metadata(data)
    if [item["type"] for item in metadata] != ["eXIf"]:
        raise ValueError("Unreviewed PNG metadata chunks")
    result, offset, removed = bytearray(PNG_SIGNATURE), 8, []
    while offset < len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        end = offset + size + 12
        kind = data[offset + 4:offset + 8]
        if kind == b"eXIf":
            payload, removed = redact_exif(data[offset + 8:end - 4])
            result.extend(struct.pack(">I", len(payload)) + kind + payload)
            result.extend(struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))
        else:
            result.extend(data[offset:end])
        offset = end
    png_metadata(bytes(result))
    return bytes(result), removed


def allowed_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__", ".codex", ".agents"} for part in path.parts):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.suffix in {".key", ".pem", ".log", ".pyc"} or path.name == ".DS_Store":
        return False
    if name.startswith(("werewolf_web/data/reviews/", "werewolf_web/data/npc_memory/",
                        "werewolf_web/data/checkpoints/",
                        "docs/research-runs/", "docs/audit-assets/", "outputs/", "output/", "playtest/")):
        return False
    if path.name.startswith("host_style") and path.suffix == ".json":
        return False
    return name != MANIFEST


def source_inventory(root):
    """A Git checkout or a verified history-free candidate can be the source."""
    root = Path(root).resolve()
    if (root / ".git").exists():
        raw = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root)
        revision = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                                  capture_output=True, text=True)
        return sorted(set(raw.decode().split("\0")) - {""}), revision.stdout.strip() or None
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    names = []
    for entry in manifest["files"]:
        name = entry["path"]
        path = root / name
        if not allowed_path(name) or path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("Invalid manifest path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Candidate differs from its manifest")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("Duplicate manifest paths")
    return sorted(names), manifest.get("source_commit")


def prepare(output, root=ROOT):
    root, output = root.resolve(), Path(output).resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("Candidate must be separate from the source repository")
    if output.exists():
        raise FileExistsError("Candidate path already exists; choose a new path")
    names, source_commit = source_inventory(root)
    entries, payloads = [], []
    # Validate everything before creating output. Nothing writes to the source.
    for name in names:
        if not allowed_path(name):
            continue
        source = root / name
        if source.is_symlink() or root not in source.resolve().parents:
            raise ValueError("Symlink or escaping candidate path")
        if not source.exists():
            continue  # A deliberately deleted tracked file is not resurrected.
        original = source.read_bytes()
        data, removed = redact_portrait(original) if name.startswith(PORTRAITS) and name.endswith(".png") else (original, [])
        entries.append({"path": name, "source_sha256": hashlib.sha256(original).hexdigest(),
                        "sha256": hashlib.sha256(data).hexdigest(), "redacted_fields": removed})
        payloads.append((name, data))
    if sum(name.startswith(PORTRAITS) and name.endswith(".png") for name, _ in payloads) != 12:
        raise ValueError("Expected the reviewed twelve portraits")
    manifest = {"format": 1, "git_history_included": False,
                "source_commit": source_commit,
                "source_state": "working candidate including uncommitted release work; per-file hashes are authoritative",
                "portrait_policy": "Only independent EXIF description ServiceUser/Time/ContentId fields redacted; all non-EXIF chunks and separate signed UserComment preserved byte-for-byte. Signature validity not asserted. Provider trace IDs in that envelope remain.",
                "publication_status": "local candidate only; no remote publication or history rewrite",
                "files": entries}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"candidate": str(output), "files": len(entries),
            "portraits_redacted": sum(bool(e["redacted_fields"]) for e in entries),
            "git_history_included": False, "originals_changed": False}


def bundle(candidate):
    """Package only manifest-listed files, never test/runtime outputs or .git."""
    candidate = Path(candidate).resolve()
    names, _ = source_inventory(candidate)
    archive = candidate.with_name(candidate.name + ".tar.gz")
    with archive.open("xb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for name in sorted(names + [MANIFEST]):
                    data = (candidate / name).read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(data))
    return {"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the source repository")
    parser.add_argument("--archive", action="store_true", help="Also create an exclusive .tar.gz beside the candidate")
    args = parser.parse_args()
    if args.archive and args.output.resolve().with_name(args.output.name + ".tar.gz").exists():
        raise FileExistsError("Archive already exists; choose a new candidate name")
    result = prepare(args.output)
    if args.archive:
        result.update(bundle(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
