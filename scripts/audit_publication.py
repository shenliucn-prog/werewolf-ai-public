"""Read-only publication inventory. Report metadata structure, never its values.

This does not decide copyright, remove provenance, sanitize images, publish a
repository, or certify that arbitrary personal information is absent.
"""
import json
from pathlib import Path
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
METADATA_CHUNKS = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"caBX"}


def png_metadata(data):
    """Validate chunk framing/CRCs and inventory metadata without decoding it."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG")
    offset, metadata, ended = 8, [], False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        size = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack_from(">I", data, offset + 8 + size)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError("PNG checksum mismatch")
        if kind in METADATA_CHUNKS:
            metadata.append({"type": kind.decode("ascii"), "bytes": size})
        offset = end
        if kind == b"IEND":
            ended = True
            break
    if not ended or offset != len(data):
        raise ValueError("Missing PNG end or trailing data")
    return metadata


def inventory(root=ROOT):
    portraits, invalid = [], []
    for path in sorted((root / "werewolf_web/static/img/portraits").glob("*.png")):
        try:
            portraits.append({"file": path.relative_to(root).as_posix(),
                              "metadata": png_metadata(path.read_bytes())})
        except ValueError:
            invalid.append(path.relative_to(root).as_posix())
    has_git = (root / ".git").exists()
    raw = subprocess.check_output(
        ["git", "log", "--all", "--format=%ae%n%ce"], cwd=root).decode() if has_git else ""
    emails = set(raw.splitlines()) - {""}
    return {
        "status": "manual_review_required",
        "scope": "current portraits and local reachable Git author/committer metadata",
        "git_history_available": has_git,
        "portraits": portraits,
        "invalid_png_files": invalid,
        "portraits_with_metadata": sum(bool(p["metadata"]) for p in portraits),
        "distinct_author_committer_emails": len(emails),
        "non_noreply_email_addresses": sum("noreply" not in email.casefold() for email in emails),
        "limitations": [
            "Metadata values deliberately omitted; a chunk is not proof of a privacy violation.",
            "Signatures and provenance require review before metadata editing.",
            "No remote-only branches, real-person likeness, text ownership or arbitrary private facts checked.",
            "Cleaning current files does not clean historical Git objects.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(inventory(), ensure_ascii=False, indent=2))
