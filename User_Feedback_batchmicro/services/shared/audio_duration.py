"""Probe audio duration from a GCS object without requiring ffprobe.

Supports WebM/Matroska (sitelead MediaRecorder clips) and WAV.

Chrome MediaRecorder WebM often omits the Info/Duration element. In that case
we estimate duration from Cluster Timecode values (max timecode × TimecodeScale).
"""
from __future__ import annotations

import logging
import struct
from typing import Optional

logger = logging.getLogger(__name__)

_HAS_GCS = True
try:
    from google.cloud import storage as gcs_storage
except ImportError:  # pragma: no cover
    _HAS_GCS = False
    gcs_storage = None  # type: ignore

_gcs_client = None

# First pass: enough for Info + early clusters on typical phone clips.
_PROBE_BYTES = 512 * 1024
# Cap full-object fallback so a bad URI cannot pull a huge file into memory.
_MAX_FULL_BYTES = 40 * 1024 * 1024


def _get_client():
    global _gcs_client
    if not _HAS_GCS:
        raise RuntimeError("google-cloud-storage is not installed")
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    return _gcs_client


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    without = (gcs_uri or "").replace("gs://", "", 1)
    bucket, _, path = without.partition("/")
    if not bucket or not path:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    return bucket, path


def _read_vint(
    data: bytes, offset: int, *, allow_unknown: bool = False
) -> tuple[Optional[int], int] | None:
    """Return (value_or_None_if_unknown, width) for an EBML vint."""
    if offset >= len(data):
        return None
    first = data[offset]
    if first == 0:
        return None
    width = 0
    mask = 0x80
    while width < 8 and (first & mask) == 0:
        mask >>= 1
        width += 1
    width += 1
    if offset + width > len(data):
        return None
    value = first & (mask - 1)
    for i in range(1, width):
        value = (value << 8) | data[offset + i]
    if value == (1 << (7 * width)) - 1:
        if allow_unknown:
            return None, width
        return None
    return value, width


def _find_timecode_scale(data: bytes) -> int:
    i = data.find(b"\x2a\xd7\xb1")
    if i < 0:
        return 1_000_000
    vint = _read_vint(data, i + 3)
    if not vint:
        return 1_000_000
    size, width = vint
    if size is None or size not in (1, 2, 3, 4, 8):
        return 1_000_000
    start = i + 3 + width
    if start + size > len(data):
        return 1_000_000
    return int.from_bytes(data[start : start + size], "big") or 1_000_000


def _parse_webm_info_duration_seconds(data: bytes) -> Optional[int]:
    """Parse Duration from Segment/Info when present (float ticks × scale)."""
    if len(data) < 16:
        return None
    timecode_scale = _find_timecode_scale(data)
    # Prefer scanning inside Info (0x1549A966) to avoid false 0x4489 hits in clusters.
    info_at = data.find(b"\x15\x49\xa9\x66")
    region = data[info_at : info_at + 512] if info_at >= 0 else data[:4096]
    duration_ticks: float | None = None
    i = 0
    while i + 2 < len(region):
        if region[i] == 0x44 and region[i + 1] == 0x89:
            vint = _read_vint(region, i + 2)
            if not vint:
                i += 1
                continue
            size, width = vint
            start = i + 2 + width
            if size == 4 and start + 4 <= len(region):
                duration_ticks = struct.unpack(">f", region[start : start + 4])[0]
                break
            if size == 8 and start + 8 <= len(region):
                duration_ticks = struct.unpack(">d", region[start : start + 8])[0]
                break
        i += 1
    if duration_ticks is None or duration_ticks <= 0:
        return None
    seconds = duration_ticks * (timecode_scale / 1_000_000_000.0)
    if seconds < 0.5 or seconds > 24 * 3600:
        return None
    return max(1, int(round(seconds)))


def _parse_webm_cluster_duration_seconds(data: bytes) -> Optional[int]:
    """Estimate duration from max Cluster Timecode (MediaRecorder WebM)."""
    if len(data) < 32:
        return None
    timecode_scale = _find_timecode_scale(data)
    cluster_id = b"\x1f\x43\xb6\x75"
    max_tc = 0
    clusters = 0
    pos = 0
    while True:
        i = data.find(cluster_id, pos)
        if i < 0:
            break
        vint = _read_vint(data, i + 4, allow_unknown=True)
        if not vint:
            pos = i + 1
            continue
        size, width = vint
        body_start = i + 4 + width
        window = data[body_start : body_start + 32]
        j = window.find(b"\xe7")
        if j >= 0:
            tv = _read_vint(window, j + 1)
            if tv:
                tsize, tw = tv
                tstart = j + 1 + tw
                if tsize is not None and 1 <= tsize <= 8 and tstart + tsize <= len(window):
                    tc = int.from_bytes(window[tstart : tstart + tsize], "big")
                    if tc >= max_tc:
                        max_tc = tc
                    clusters += 1
        if size is None:
            pos = body_start + 1
        else:
            pos = min(len(data), body_start + size)
    if clusters == 0:
        return None
    seconds = max_tc * (timecode_scale / 1_000_000_000.0)
    if seconds < 0.5 or seconds > 24 * 3600:
        return None
    return max(1, int(round(seconds)))


def _parse_webm_duration_seconds(data: bytes) -> Optional[int]:
    return _parse_webm_info_duration_seconds(data) or _parse_webm_cluster_duration_seconds(data)


def _parse_wav_duration_seconds(data: bytes) -> Optional[int]:
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    offset = 12
    byte_rate = None
    data_size = None
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        chunk_data = offset + 8
        if chunk_id == b"fmt " and chunk_data + 16 <= len(data):
            byte_rate = struct.unpack("<I", data[chunk_data + 8 : chunk_data + 12])[0]
        elif chunk_id == b"data":
            data_size = chunk_size
            break
        offset = chunk_data + chunk_size + (chunk_size & 1)
    if not data_size or not byte_rate:
        return None
    seconds = data_size / float(byte_rate)
    if seconds < 0.5 or seconds > 24 * 3600:
        return None
    return max(1, int(round(seconds)))


def _plausible_duration(seconds: Optional[int], size_bytes: int | None) -> Optional[int]:
    """Reject durations that imply an impossible bitrate for speech Opus/PCM."""
    if seconds is None or seconds <= 0:
        return None
    if not size_bytes or size_bytes <= 0:
        return seconds
    bits_per_sec = (size_bytes * 8) / float(seconds)
    # Speech WebM/Opus is typically ~16–128 kbps; allow a wide band.
    if bits_per_sec < 4_000 or bits_per_sec > 512_000:
        return None
    return seconds


def _size_bitrate_estimate_seconds(size_bytes: int, bitrate: int = 96_000) -> Optional[int]:
    """Estimate duration from object size.

    Chrome MediaRecorder WebM/Opus is typically closer to 64–128 kbps than 48 kbps;
    using 96 kbps avoids large over-estimates that make the UI show longer than
    the playable length.
    """
    if size_bytes < 1000:
        return None
    seconds = (size_bytes * 8) / float(bitrate)
    if seconds < 0.5 or seconds > 24 * 3600:
        return None
    return max(1, int(round(seconds)))


def probe_duration_seconds_from_bytes(
    data: bytes,
    ext_hint: str | None = None,
    *,
    allow_cluster_estimate: bool = True,
    size_bytes: int | None = None,
) -> Optional[int]:
    ext = (ext_hint or "").lower().lstrip(".")
    is_webm = ext in {"webm", "weba", "mkv"} or data[:4] == b"\x1a\x45\xdf\xa3"
    # Bitrate checks need the full object size; skip them on header-only probes.
    check_size = size_bytes if size_bytes is not None else (
        len(data) if allow_cluster_estimate else None
    )
    if is_webm:
        info = _plausible_duration(_parse_webm_info_duration_seconds(data), check_size)
        if info:
            return info
        if allow_cluster_estimate:
            cluster = _plausible_duration(_parse_webm_cluster_duration_seconds(data), check_size)
            if cluster:
                return cluster
            return _size_bitrate_estimate_seconds(check_size or len(data))
        return _parse_webm_info_duration_seconds(data)
    if ext == "wav" or data[:4] == b"RIFF":
        return _parse_wav_duration_seconds(data)
    return (
        _plausible_duration(_parse_webm_info_duration_seconds(data), check_size)
        or (
            _plausible_duration(_parse_webm_cluster_duration_seconds(data), check_size)
            if allow_cluster_estimate
            else None
        )
        or _parse_wav_duration_seconds(data)
        or (_size_bitrate_estimate_seconds(check_size or len(data)) if allow_cluster_estimate else None)
    )


def probe_gcs_audio_duration_seconds(
    gcs_uri: str,
    *,
    ext_hint: str | None = None,
    max_bytes: int = _PROBE_BYTES,
) -> Optional[int]:
    """Download audio bytes from GCS and parse duration. Never raises."""
    try:
        bucket_name, path = _parse_gcs_uri(gcs_uri)
        client = _get_client()
        blob = client.bucket(bucket_name).blob(path)
        try:
            data = blob.download_as_bytes(start=0, end=max(0, max_bytes - 1))
        except TypeError:
            data = blob.download_as_bytes()[:max_bytes]
        except Exception:
            raw = blob.download_as_bytes()
            data = raw[:max_bytes]
        # Prefix is only trusted for Info/Duration or WAV. Cluster estimates need
        # the last cluster, so require a full object read for MediaRecorder WebM.
        probed = probe_duration_seconds_from_bytes(
            data, ext_hint, allow_cluster_estimate=False
        )
        if probed:
            return probed
        try:
            blob.reload()
            size = int(blob.size or 0)
        except Exception:
            size = 0
        if size <= 0:
            return probe_duration_seconds_from_bytes(data, ext_hint)
        if size > _MAX_FULL_BYTES:
            logger.warning(
                "Audio duration probe skipped full download for %s size=%s",
                gcs_uri,
                size,
            )
            return probe_duration_seconds_from_bytes(data, ext_hint)
        if size <= len(data):
            return probe_duration_seconds_from_bytes(data, ext_hint)
        full = blob.download_as_bytes()
        return probe_duration_seconds_from_bytes(full, ext_hint)
    except Exception as exc:
        logger.warning("Audio duration probe failed for %s: %s", gcs_uri, exc)
        return None
