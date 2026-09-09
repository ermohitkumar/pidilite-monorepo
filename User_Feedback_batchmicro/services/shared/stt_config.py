"""Cloud STT helpers.

Production uses Speech-to-Text v2 `telephony` in asia-south1 (org policy
blocks global/us; Chirp is not in this region). v1 encoding/rate maps are
kept for scripts that still call the v1 API.
"""

from __future__ import annotations

from core.config import settings

# v2 model that works in asia-south1 for hi-IN. latest_long is v1-only here.
STT_V2_MODEL = "telephony"
_V1_MODEL_ALIASES = {
    "latest_long",
    "latest_short",
    "default",
    "video",
    "command_and_search",
    "phone_call",
    "long",
    "short",
}

# Primary + up to 3 alternatives. Hinglish field visits mix hi/en; Pidilite
# coverage is heavy in Maharashtra and Gujarat.
_LANGUAGE_POOL = ("hi-IN", "en-IN", "mr-IN", "gu-IN")

# (AudioEncoding enum name or None to omit, sample_rate_hertz or None to omit)
# WAV/FLAC: header carries encoding + rate — do not override.
# WebM/OGG from browsers and phones is almost always Opus @ 48 kHz.
_ENCODING_BY_EXT: dict[str, tuple[str | None, int | None]] = {
    "webm": ("WEBM_OPUS", 48000),
    "weba": ("WEBM_OPUS", 48000),
    "ogg": ("OGG_OPUS", 48000),
    "opus": ("OGG_OPUS", 48000),
    "mp3": ("MP3", 16000),
    "wav": (None, None),
    "flac": (None, None),
}

# Sitelead / GCS often omit Content-Type, so objects land as octet-stream.
_GENERIC_MIMES = frozenset({
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/binary",
})
_MIME_BY_EXT: dict[str, str] = {
    "webm": "audio/webm",
    "weba": "audio/webm",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "amr": "audio/amr",
}


def file_extension(gcs_uri: str, source_hint: str | None = None) -> str:
    if source_hint:
        return source_hint.lower().lstrip(".")
    path = gcs_uri.split("?")[0]
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def encoding_and_sample_rate(ext: str) -> tuple[str | None, int | None]:
    """Return (AudioEncoding name, sample_rate_hertz). None = omit the field."""
    if not ext:
        return "MP3", 16000
    return _ENCODING_BY_EXT.get(ext, ("MP3", 16000))


def resolved_audio_mime(ext: str | None, mime_type: str | None = None) -> str:
    """Prefer a real audio/video MIME; otherwise infer from the file extension.

    GCS uploads without Content-Type are stored as application/octet-stream.
    """
    mime = (mime_type or "").strip().lower()
    ext = (ext or "").lower().lstrip(".")
    if mime and mime not in _GENERIC_MIMES and (
        mime.startswith("audio/") or mime.startswith("video/")
    ):
        return mime
    if ext in _MIME_BY_EXT:
        return _MIME_BY_EXT[ext]
    return mime or "audio/mpeg"


def is_audio_media(ext: str | None, mime_type: str | None = None) -> bool:
    mime = resolved_audio_mime(ext, mime_type)
    return mime.startswith("audio/") or mime.startswith("video/")


def alternative_language_codes(primary: str) -> list[str]:
    primary = (primary or "").strip() or "hi-IN"
    return [code for code in _LANGUAGE_POOL if code != primary][:3]


def stt_location() -> str:
    return (settings.GCP_LOCATION or "asia-south1").strip() or "asia-south1"


def resolve_v2_model(model: str | None) -> str:
    """Map leftover v1 model names onto v2 telephony."""
    name = (model or "").strip()
    if not name or name in _V1_MODEL_ALIASES:
        return STT_V2_MODEL
    return name
