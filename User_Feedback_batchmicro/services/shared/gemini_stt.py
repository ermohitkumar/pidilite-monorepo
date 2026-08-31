"""Gemini Flash STT: Vertex generateContent on a gs:// audio URI.

Writes the same Eventarc path as Speech v2 (`stt-output/{job_id}/output.json`)
so /stt-complete and translate stay unchanged. Speaker labels are 1..N.
"""
from __future__ import annotations

import json
import logging
import re

from core.config import settings
from core.exceptions import STTGeminiTransientError, STTInvalidArgumentError
from services.shared.gcs_paths import build_stt_output_gcs_uri
from services.shared.stt_config import file_extension
from services.shared.speakers import is_collapsed_speaker_transcript
from services.shared.vertex_ai import (
    VertexRestAdapter,
    _SAFETY_OFF,
    _THINKING_OFF,
    split_collapsed_speaker_transcript,
)

logger = logging.getLogger(__name__)

try:
    from google.cloud import storage as gcs_storage
    _HAS_GCS = True
except ImportError:
    gcs_storage = None  # type: ignore[misc, assignment]
    _HAS_GCS = False

GEMINI_FLASH_OP_PREFIX = "gemini-flash:"
GEMINI_STT_MAX_ATTEMPTS = 3
GEMINI_STT_MAX_OUTPUT_TOKENS = 65536
GEMINI_STT_PROVIDER = "gemini_flash"

_MIME_BY_EXT = {
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "weba": "audio/webm",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
    "amr": "audio/amr",
}

_TRANSCRIBE_PROMPT = """Transcribe this field-visit audio in the spoken language(s).

RULES:
1. Do NOT translate. Keep code-switching (Hindi, Hinglish, Marathi, Gujarati, Tamil, Telugu, Kannada, Malayalam, Bengali, Punjabi, English) exactly as spoken.
2. Output ONLY labeled turns. Each line must start with "Speaker N:" where N is 1, 2, 3, ...
3. There may be TWO OR MORE speakers (FME, customer, dealer, extra site voice). Assign a stable Speaker ID to each distinct voice for the whole call. Never cap at 2. Never drop a voice.
4. Do not summarize, omit words, or add commentary.
5. Start a NEW line every time the speaker changes. Never put the whole call (or both people) on one "Speaker 1:" line. A two-person visit MUST use at least Speaker 1 and Speaker 2, with many short turns.
6. Use a single Speaker 1: line only when one voice is truly audible for the entire recording.
"""

_gcs_client = None


def gemini_flash_operation_name(job_id: str) -> str:
    return f"{GEMINI_FLASH_OP_PREFIX}{job_id}"


def is_gemini_flash_operation(name: str | None) -> bool:
    return bool(name) and str(name).startswith(GEMINI_FLASH_OP_PREFIX)


def is_last_flash_attempt(retry_count: int) -> bool:
    """Cloud Tasks X-CloudTasks-TaskRetryCount is 0 on the first try."""
    return int(retry_count or 0) >= GEMINI_STT_MAX_ATTEMPTS - 1


def mime_type_for_audio(gcs_uri: str, source_hint: str | None = None) -> str:
    ext = file_extension(gcs_uri, source_hint)
    return _MIME_BY_EXT.get(ext, "audio/mpeg")


def gemini_stt_output_uri(job_id: str) -> str:
    return build_stt_output_gcs_uri(job_id)


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def _vertex_generate_url(model_name: str) -> str:
    loc = settings.GCP_LOCATION or "asia-south1"
    project = settings.GCP_PROJECT_ID
    return (
        f"https://{loc}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{loc}/"
        f"publishers/google/models/{model_name}:generateContent"
    )


def transcribe_audio_gcs(
    gcs_uri: str,
    *,
    source_hint: str | None = None,
    model_name: str | None = None,
) -> dict:
    """Call Vertex generateContent with fileData.fileUri. Returns GCS JSON payload.

    Raises STTGeminiTransientError for retryable failures, STTInvalidArgumentError
    for non-retryable request/audio errors.
    """
    import requests

    name = model_name or settings.gemini_stt_model
    mime = mime_type_for_audio(gcs_uri, source_hint)
    timeout = int(settings.GEMINI_STT_TIMEOUT_SECONDS or 540)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"fileData": {"fileUri": gcs_uri, "mimeType": mime}},
                    {"text": _TRANSCRIBE_PROMPT},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": GEMINI_STT_MAX_OUTPUT_TOKENS,
            "thinkingConfig": _THINKING_OFF,
        },
        "safetySettings": _SAFETY_OFF,
    }

    try:
        creds = VertexRestAdapter._get_credentials()
        res = requests.post(
            _vertex_generate_url(name),
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise STTGeminiTransientError(f"Gemini STT timed out after {timeout}s") from exc
    except requests.RequestException as exc:
        raise STTGeminiTransientError(f"Gemini STT request failed: {exc}") from exc

    if res.status_code in (408, 429, 500, 502, 503, 504):
        raise STTGeminiTransientError(
            f"Gemini STT HTTP {res.status_code}: {(res.text or '')[:300]}"
        )
    if res.status_code >= 400:
        raise STTInvalidArgumentError(
            f"Gemini STT HTTP {res.status_code}: {(res.text or '')[:300]}"
        )

    try:
        res_json = res.json()
    except ValueError as exc:
        raise STTGeminiTransientError("Gemini STT returned non-JSON body") from exc

    if "error" in res_json:
        err = res_json["error"]
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else str(err)
        if code in (8, 13, 14, 429) or (isinstance(code, int) and code >= 500):
            raise STTGeminiTransientError(f"Gemini STT API error: {message}")
        raise STTInvalidArgumentError(f"Gemini STT API error: {message}")

    candidates = res_json.get("candidates") or []
    if not candidates:
        raise STTGeminiTransientError("Gemini STT returned no candidates")

    candidate = candidates[0]
    finish = (candidate.get("finishReason") or candidate.get("finish_reason") or "").upper()
    if finish in {"MAX_TOKENS", "TIMEOUT"}:
        raise STTGeminiTransientError(f"Gemini STT finishReason={finish}")

    try:
        text = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise STTGeminiTransientError(
            f"Gemini STT missing transcript text (finishReason={finish or 'unknown'})"
        ) from exc

    transcript = _strip_fences(text)
    if not transcript:
        raise STTGeminiTransientError("Gemini STT returned an empty transcript")
    if not re.search(r"Speaker\s+\d+\s*:", transcript, re.IGNORECASE):
        logger.warning("Gemini STT transcript has no Speaker N labels; keeping raw text")

    if is_collapsed_speaker_transcript(transcript):
        logger.warning("Gemini STT collapsed speakers into few lines; splitting turns")
        split_text, _ = split_collapsed_speaker_transcript(transcript, model_name=name)
        if split_text:
            transcript = split_text

    return {
        "provider": GEMINI_STT_PROVIDER,
        "model": name,
        "transcript": transcript,
        "detected_languages": [],
    }


def write_gemini_transcript_json(gcs_uri: str, payload: dict) -> None:
    """Write Flash STT JSON to the canonical Eventarc object."""
    if not _HAS_GCS:
        raise RuntimeError("google-cloud-storage is not installed")

    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    without_prefix = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = without_prefix.split("/", 1)
    blob = _gcs_client.bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
    )
    logger.info("Wrote Gemini STT JSON to %s (%d chars transcript)", gcs_uri, len(payload.get("transcript") or ""))
