"""Unit tests for audio duration probing (WebM / WAV headers)."""
import struct

from services.shared.audio_duration import (
    probe_duration_seconds_from_bytes,
    _parse_wav_duration_seconds,
    _parse_webm_cluster_duration_seconds,
)


def _ebml_vint(value: int, width: int) -> bytes:
    """Encode an EBML vint with a fixed width (1..8)."""
    assert 1 <= width <= 8
    marker = 1 << (8 - width)
    max_val = marker - 1
    assert 0 <= value <= max_val or width > 1
    # Build width bytes with marker in the leading byte.
    raw = value.to_bytes(width, "big")
    lead = raw[0] | marker
    return bytes([lead]) + raw[1:]


def test_webm_duration_from_info_elements():
    # Minimal EBML-ish buffer containing TimecodeScale + Duration.
    # TimecodeScale ID 0x2AD7B1, size 4, value 1_000_000
    # Duration ID 0x4489, size 8, value 15000.0 ticks → 15.0s at scale 1e6
    scale = (1_000_000).to_bytes(4, "big")
    duration = struct.pack(">d", 15000.0)
    buf = (
        b"\x1a\x45\xdf\xa3"  # EBML header id (noise)
        + b"\x2a\xd7\xb1"
        + _ebml_vint(4, 1)
        + scale
        + b"\x44\x89"
        + _ebml_vint(8, 1)
        + duration
    )
    assert probe_duration_seconds_from_bytes(buf, "webm", allow_cluster_estimate=False) == 15


def test_wav_duration_from_header():
    # 16-bit mono PCM @ 16kHz, 32000 bytes of data → 1.0s
    byte_rate = 16000 * 2
    data_size = byte_rate  # 1 second
    fmt = struct.pack(
        "<HHIIHH",
        1,  # PCM
        1,  # channels
        16000,
        byte_rate,
        2,  # block align
        16,  # bits
    )
    buf = (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", data_size)
        + (b"\x00" * data_size)
    )
    assert _parse_wav_duration_seconds(buf) == 1
    assert probe_duration_seconds_from_bytes(buf, "wav") == 1


def _element(element_id: bytes, payload: bytes) -> bytes:
    return element_id + _ebml_vint(len(payload), 1) + payload


def _simple_block(relative_ms: int) -> bytes:
    payload = _ebml_vint(1, 1) + struct.pack(">h", relative_ms) + b"\x80"
    return _element(b"\xa3", payload)


def _cluster(timecode_ms: int, relative_ms: list[int]) -> bytes:
    body = _element(b"\xe7", timecode_ms.to_bytes(4, "big"))
    body += b"".join(_simple_block(value) for value in relative_ms)
    return b"\x1f\x43\xb6\x75" + _ebml_vint(len(body), 2) + body


def test_webm_cluster_duration_ignores_timestamp_hole():
    # Two frames at t=0, then a 5000s jump, then 1.2s of 60ms frames.
    scale = (1_000_000).to_bytes(4, "big")
    header = b"\x2a\xd7\xb1" + _ebml_vint(4, 1) + scale
    first = _cluster(0, [0, 60])
    second = _cluster(5_000_000, [index * 60 for index in range(21)])
    buf = header + first + second
    assert _parse_webm_cluster_duration_seconds(buf) == 1


def test_unknown_bytes_return_none():
    assert probe_duration_seconds_from_bytes(b"not-audio", "json") is None
