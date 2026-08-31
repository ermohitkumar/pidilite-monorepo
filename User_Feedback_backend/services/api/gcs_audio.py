"""Helpers for private GCS audio playback. Callers must already be authenticated."""
from __future__ import annotations

import re
from typing import Optional

from core.config import settings

_GS_URI = re.compile(r"^gs://([a-z0-9][a-z0-9._-]{1,61}[a-z0-9])/(.+)$")

_MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".flac": "audio/flac",
}


def parse_gcs_uri(uri: str) -> Optional[tuple[str, str]]:
    match = _GS_URI.match((uri or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def is_allowed_audio_uri(uri: str) -> bool:
    parsed = parse_gcs_uri(uri)
    if not parsed:
        return False
    bucket, object_name = parsed
    if not object_name or object_name.endswith("/"):
        return False
    allowed = settings.gcs_audio_allowed_buckets
    return bucket in allowed


def content_type_for_name(file_name: Optional[str], mime_type: Optional[str] = None) -> str:
    if mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
        return mime_type
    name = (file_name or "").lower()
    for ext, mime in _MIME_BY_EXT.items():
        if name.endswith(ext):
            return mime
    return "application/octet-stream"
