"""Publication inventory must not emit embedded metadata values."""
import json
import struct
import unittest
import zlib

from scripts.audit_publication import PNG_SIGNATURE, png_metadata


def chunk(kind, payload=b""):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)


class PublicationInventoryTest(unittest.TestCase):
    def test_metadata_contents_are_not_returned(self):
        data = PNG_SIGNATURE + chunk(b"tEXt", b"Account\x00PRIVATE_CANARY") + chunk(b"IEND")
        result = png_metadata(data)
        self.assertEqual(result, [{"type": "tEXt", "bytes": 22}])
        self.assertNotIn("PRIVATE_CANARY", json.dumps(result))

    def test_non_metadata_chunks_are_not_reported(self):
        self.assertEqual(png_metadata(PNG_SIGNATURE + chunk(b"IDAT", b"pixels") + chunk(b"IEND")), [])

    def test_invalid_framing_and_checksum_are_rejected(self):
        valid = PNG_SIGNATURE + chunk(b"IEND")
        for data in (b"not a png", valid[:-1], valid + b"tail", valid[:-1] + bytes([valid[-1] ^ 1])):
            with self.assertRaises(ValueError):
                png_metadata(data)
