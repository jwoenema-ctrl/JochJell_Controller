"""Bounded raster uploads with generated filenames and strict file serving."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
import re
import struct
from typing import Any
from uuid import uuid4
import zlib


MAX_SCAN_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BODY_BYTES = ((MAX_SCAN_BYTES + 2) // 3) * 4 + 4096
_MIME_EXTENSIONS = {"image/png": (".png",), "image/jpeg": (".jpg", ".jpeg"), "image/webp": (".webp",)}
_GENERATED_FILE = re.compile(r"[0-9a-f]{32}\.(?:png|jpg|webp)\Z")


def _dimensions(data: bytes, mime: str) -> tuple[int, int]:
    """Inspect image headers, not the client-supplied extension or MIME alone."""

    if mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset, dimensions, has_data = 8, None, False
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            end = offset + 12 + length
            if end > len(data):
                break
            kind, body = data[offset + 4:offset + 8], data[offset + 8:end - 4]
            if zlib.crc32(kind + body) != int.from_bytes(data[end - 4:end], "big"):
                break
            if offset == 8:
                if kind != b"IHDR" or length != 13:
                    break
                dimensions = struct.unpack(">II", body[:8])
            has_data |= kind == b"IDAT" and bool(body)
            if kind == b"IEND" and length == 0 and end == len(data) and dimensions and has_data:
                return dimensions
            offset = end
    elif mime == "image/jpeg" and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        offset, dimensions = 2, None
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD8, 0xD9):
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker == 0xDA:
                if dimensions and offset + length < len(data) - 2:
                    return dimensions
                break
            if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                dimensions = (width, height)
            offset += length
    elif mime == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("invalid WebP length")
        kind, length = data[12:16], int.from_bytes(data[16:20], "little")
        if length + 20 > len(data):
            raise ValueError("invalid WebP image chunk")
        if kind == b"VP8X" and length == 10:
            # An extended canvas header alone is not a decodable image.
            offset, has_frame = 30, False
            while offset + 8 <= len(data):
                chunk_kind = data[offset:offset + 4]
                chunk_length = int.from_bytes(data[offset + 4:offset + 8], "little")
                end = offset + 8 + chunk_length + (chunk_length % 2)
                if end > len(data):
                    break
                has_frame |= chunk_kind in (b"VP8 ", b"VP8L", b"ANMF") and chunk_length >= 5
                offset = end
            if has_frame and offset == len(data):
                return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
        if kind == b"VP8 " and length >= 10 and data[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L" and length >= 5 and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("file contents must be a valid PNG, JPEG, or WebP image matching mime_type")


class ScanStore:
    """Store binary assets only; the layout repository owns their manifest."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()

    def upload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        filename, mime, encoded = payload.get("filename"), payload.get("mime_type"), payload.get("data")
        if not isinstance(filename, str) or not filename or len(filename) > 255 or any(char in filename for char in '/\\:') or any(ord(char) < 32 for char in filename):
            raise ValueError("filename must be a plain image filename without a path")
        if mime not in _MIME_EXTENSIONS or Path(filename).suffix.lower() not in _MIME_EXTENSIONS[mime]:
            raise ValueError("only PNG, JPEG, and WebP filenames matching mime_type are supported")
        label = payload.get("label") or Path(filename).stem
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
            raise ValueError("label must contain 1 to 120 characters")
        if not isinstance(encoded, str) or len(encoded) > ((MAX_SCAN_BYTES + 2) // 3) * 4:
            raise ValueError("scan must be base64 encoded and no larger than 10 MiB")
        try:
            binary = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("scan data must be valid base64") from None
        if not binary or len(binary) > MAX_SCAN_BYTES:
            raise ValueError("scan must contain 1 byte to 10 MiB")
        width, height = _dimensions(binary, mime)
        if not 0 < width <= 10000 or not 0 < height <= 10000 or width * height > 36_000_000:
            raise ValueError("image dimensions exceed 10000 per side or 36 megapixels")
        scan_id = uuid4().hex
        stored_name = scan_id + _MIME_EXTENSIONS[mime][0]
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / stored_name
        with path.open("xb") as stream:
            stream.write(binary)
        return {
            "id": scan_id,
            "label": label.strip(),
            "description": f"Uploaded photo scan · {width} × {height}",
            "image": f"/api/scans/files/{stored_name}",
            "anchor": {"x": 0.5, "y": 0.5},
        }, path

    def resolve(self, generated_name: str) -> Path | None:
        if not _GENERATED_FILE.fullmatch(generated_name):
            return None
        candidate = (self.directory / generated_name).resolve()
        if candidate.parent != self.directory or not candidate.is_file():
            return None
        return candidate
