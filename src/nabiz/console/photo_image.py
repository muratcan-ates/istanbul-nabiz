"""Inspect and remove embedded metadata from JPEG, PNG, and WebP photos without dependencies."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

PhotoKind = Literal["jpeg", "png", "webp"]

# These are product limits, not measurements of an uploaded image.
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_EDGE = 1600
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_KEEP = frozenset(b"IHDR PLTE IDAT IEND tRNS gAMA cHRM sRGB sBIT pHYs bKGD".split())
_PNG_CRITICAL = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})
_JPEG_DROP = frozenset({*range(0xE1, 0xEE), 0xEF, 0xFE})
_JPEG_STANDALONE = frozenset({0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)})
_WEBP_DROP = frozenset({b"EXIF", b"XMP ", b"ICCP"})


class PhotoRejected(ValueError):
    """An image that does not meet the upload contract, identified by a public error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CleanPhoto:
    kind: PhotoKind
    data: bytes
    width: int
    height: int


def photo_kind(data: bytes) -> PhotoKind | None:
    """Identify a supported raster format by its signature, never by a client MIME value."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(_PNG_SIGNATURE):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _jpeg_marker(data: bytes, pos: int) -> tuple[int, int, int]:
    if pos >= len(data) or data[pos] != 0xFF:
        raise ValueError("jpeg marker")
    start = pos
    while pos < len(data) and data[pos] == 0xFF:
        pos += 1
    if pos >= len(data):
        raise ValueError("jpeg marker end")
    return data[pos], start, pos + 1


def _jpeg_segment_end(data: bytes, marker: int, pos: int) -> int:
    if marker in _JPEG_STANDALONE:
        return pos
    if pos + 2 > len(data):
        raise ValueError("jpeg segment length")
    size = int.from_bytes(data[pos : pos + 2], "big")
    end = pos + size
    if size < 2 or end > len(data):
        raise ValueError("jpeg segment bounds")
    return end


def _jpeg_segments(data: bytes) -> Iterator[tuple[int, int, int]]:
    """Yield (marker, start, end) through SOS; malformed segment lengths raise ValueError."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("jpeg signature")
    pos = 2
    while pos < len(data):
        marker, start, after_marker = _jpeg_marker(data, pos)
        end = _jpeg_segment_end(data, marker, after_marker)
        yield marker, start, end
        if marker in {0xDA, 0xD9}:
            return
        pos = end


def _png_chunk(data: bytes, pos: int) -> tuple[bytes, int, int]:
    if pos + 12 > len(data):
        raise ValueError("png chunk header")
    start = pos
    size = int.from_bytes(data[pos : pos + 4], "big")
    kind = data[pos + 4 : pos + 8]
    end = pos + 12 + size
    valid_name = len(kind) == 4 and all(65 <= ch <= 90 or 97 <= ch <= 122 for ch in kind)
    if end > len(data) or not valid_name:
        raise ValueError("png chunk bounds")
    content = data[pos + 8 : pos + 8 + size]
    expected = int.from_bytes(data[pos + 8 + size : end], "big")
    if zlib.crc32(kind + content) & 0xFFFFFFFF != expected:
        raise ValueError("png crc")
    if kind == b"IHDR" and (start != len(_PNG_SIGNATURE) or size != 13):
        raise ValueError("png header")
    if kind == b"IEND" and (size != 0 or end != len(data)):
        raise ValueError("png end")
    return kind, start, end


def _png_chunks(data: bytes) -> Iterator[tuple[bytes, int, int]]:
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("png signature")
    pos = len(_PNG_SIGNATURE)
    while pos < len(data):
        chunk = _png_chunk(data, pos)
        yield chunk
        pos = chunk[2]
        if chunk[0] == b"IEND":
            return
    raise ValueError("png missing end")


def _webp_chunks(data: bytes):
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("webp signature")
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise ValueError("webp riff size")
    pos = 12
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("webp chunk header")
        start = pos
        kind = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        end = pos + 8 + size + (size & 1)
        if end > len(data):
            raise ValueError("webp chunk bounds")
        yield kind, start, end, data[pos + 8 : pos + 8 + size]
        pos = end


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    for marker, start, _ in _jpeg_segments(data):
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            marker_end = start
            while marker_end < len(data) and data[marker_end] == 0xFF:
                marker_end += 1
            length_at = marker_end + 1
            size = int.from_bytes(data[length_at : length_at + 2], "big")
            if size < 7 or length_at + size > len(data):
                raise ValueError("jpeg frame")
            height = int.from_bytes(data[length_at + 3 : length_at + 5], "big")
            width = int.from_bytes(data[length_at + 5 : length_at + 7], "big")
            return (width, height) if width and height else None
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    for kind, _, _, content in _webp_chunks(data):
        if kind == b"VP8X" and len(content) == 10:
            width = 1 + int.from_bytes(content[4:7], "little")
            height = 1 + int.from_bytes(content[7:10], "little")
            return width, height
        if kind == b"VP8L" and len(content) >= 5 and content[0] == 0x2F:
            width = 1 + content[1] + ((content[2] & 0x3F) << 8)
            height = 1 + ((content[2] >> 6) & 0x03) + (content[3] << 2) + ((content[4] & 0x0F) << 10)
            return width, height
        if kind == b"VP8 " and len(content) >= 10 and content[3:6] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(content[6:8], "little") & 0x3FFF,
                int.from_bytes(content[8:10], "little") & 0x3FFF,
            )
    return None


def photo_dimensions(data: bytes, kind: PhotoKind) -> tuple[int, int] | None:
    """Read dimensions from the image structure, returning None when its frame is absent."""
    if kind == "jpeg":
        return _jpeg_dimensions(data)
    if kind == "png":
        for name, start, _end in _png_chunks(data):
            if name == b"IHDR":
                width, height = struct.unpack(">II", data[start + 8 : start + 16])
                return (width, height) if width and height else None
        return None
    if kind == "webp":
        return _webp_dimensions(data)
    return None


def _strip_jpeg(data: bytes) -> bytes:
    output = bytearray(data[:2])
    found_scan = False
    for marker, start, end in _jpeg_segments(data):
        if marker == 0xDA:
            output.extend(data[start:])
            found_scan = True
            break
        if marker not in _JPEG_DROP:
            output.extend(data[start:end])
    if not found_scan or b"\xff\xd9" not in output:
        raise ValueError("jpeg scan missing")
    return bytes(output)


def _strip_png(data: bytes) -> bytes:
    chunks = list(_png_chunks(data))
    if not chunks or chunks[0][0] != b"IHDR" or not any(chunk[0] == b"IDAT" for chunk in chunks):
        raise ValueError("png image chunks")
    output = bytearray(_PNG_SIGNATURE)
    for name, start, end in chunks:
        if name not in _PNG_KEEP and name[0] & 0x20 == 0 and name not in _PNG_CRITICAL:
            raise ValueError("png unknown critical chunk")
        if name in _PNG_KEEP:
            output.extend(data[start:end])
    return bytes(output)


def _strip_webp(data: bytes) -> bytes:
    chunks = list(_webp_chunks(data))
    if not chunks or not any(name in {b"VP8 ", b"VP8L"} for name, _, _, _ in chunks):
        raise ValueError("webp image chunks")
    vp8x = next((content for name, _, _, content in chunks if name == b"VP8X"), None)
    animated = any(name in {b"ANIM", b"ANMF"} for name, _, _, _ in chunks)
    animated = animated or bool(vp8x and vp8x[0] & 0x02)
    if animated:
        raise ValueError("animated webp")
    output = bytearray(b"RIFF\x00\x00\x00\x00WEBP")
    for name, start, end, content in chunks:
        if name in _WEBP_DROP:
            continue
        segment = bytearray(data[start:end])
        if name == b"VP8X":
            if len(content) != 10:
                raise ValueError("webp extended header")
            segment[8] &= ~(0x08 | 0x04 | 0x20)
        output.extend(segment)
    output[4:8] = (len(output) - 8).to_bytes(4, "little")
    return bytes(output)


def strip_photo_metadata(data: bytes, kind: PhotoKind) -> bytes:
    """Drop metadata containers while preserving image bitstreams; reject malformed structures."""
    cleaners = {"jpeg": _strip_jpeg, "png": _strip_png, "webp": _strip_webp}
    try:
        return cleaners[kind](data)
    except KeyError as exc:
        raise ValueError("unsupported photo kind") from exc


def clean_photo(data: bytes) -> CleanPhoto:
    """Enforce size, signature, frame, and edge limits before returning metadata-free bytes."""
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoRejected("too_large")
    kind = photo_kind(data)
    if kind is None:
        raise PhotoRejected("bad_type")
    try:
        dimensions = photo_dimensions(data, kind)
        if dimensions is None:
            raise PhotoRejected("too_many_pixels")
        width, height = dimensions
        if max(width, height) > MAX_PHOTO_EDGE:
            raise PhotoRejected("too_many_pixels")
        cleaned = strip_photo_metadata(data, kind)
        if photo_kind(cleaned) != kind:
            raise ValueError("cleaned signature")
        after = photo_dimensions(cleaned, kind)
        if after != dimensions or max(after) > MAX_PHOTO_EDGE:
            raise PhotoRejected("too_many_pixels")
    except PhotoRejected:
        raise
    except (IndexError, OverflowError, struct.error, ValueError) as exc:
        raise PhotoRejected("malformed") from exc
    return CleanPhoto(kind, cleaned, width, height)


__all__ = [
    "MAX_PHOTO_BYTES", "MAX_PHOTO_EDGE", "CleanPhoto", "PhotoKind", "PhotoRejected", "clean_photo",
    "photo_dimensions", "photo_kind", "strip_photo_metadata",
]
