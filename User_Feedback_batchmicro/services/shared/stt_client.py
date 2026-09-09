"""Cloud Speech-to-Text v2 client (asia-south1 telephony).

Chirp is not available in asia-south1 and other regions are blocked by
org policy. v1 latest_long dropped most of noisy WhatsApp field audio;
v2 telephony recovered 2–3× more words on the same clips.
"""
from __future__ import annotations

import logging

from core.config import settings
from services.shared.stt_config import resolve_v2_model, stt_location

logger = logging.getLogger(__name__)

try:
    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import cloud_speech

    _HAS_SPEECH = True
except ImportError:
    SpeechClient = None  # type: ignore[misc, assignment]
    cloud_speech = None  # type: ignore[misc, assignment]
    ClientOptions = None  # type: ignore[misc, assignment]
    _HAS_SPEECH = False

_speech_client = None


def get_speech_client():
    """Regional v2 client. Cached. Raises if the SDK is missing."""
    if not _HAS_SPEECH:
        raise RuntimeError("google-cloud-speech is not installed")

    global _speech_client
    if _speech_client is None:
        location = stt_location()
        _speech_client = SpeechClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-speech.googleapis.com"
            )
        )
    return _speech_client


def reset_speech_client() -> None:
    global _speech_client
    _speech_client = None


def recognizer_path() -> str:
    project = settings.GCP_PROJECT_ID or "pidilite-user-feedback-ai"
    return f"projects/{project}/locations/{stt_location()}/recognizers/_"


def build_recognition_config(language_code: str, model: str | None = None):
    """v2 config: auto-detect container, telephony model, no diarization.

    asia-south1 telephony rejects features.diarization_config
    (Recognizer does not support feature: speaker_diarization).
    """
    resolved = resolve_v2_model(model)
    primary = (language_code or "hi-IN").strip() or "hi-IN"
    # asia-south1 telephony rejects en-IN (and other pool alts). Keep primary only.
    return cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=[primary],
        model=resolved,
        features=cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=True,
            enable_word_confidence=True,
            enable_word_time_offsets=True,
        ),
    )


def submit_batch_recognize(
    gcs_uri: str,
    gcs_output_uri_prefix: str | None,
    language_code: str = "hi-IN",
    model: str | None = None,
) -> str:
    """Submit BatchRecognize LRO. Returns operation name."""
    client = get_speech_client()
    config = build_recognition_config(language_code, model)
    prefix = (gcs_output_uri_prefix or "").rstrip("/") + "/"
    request = cloud_speech.BatchRecognizeRequest(
        recognizer=recognizer_path(),
        config=config,
        files=[cloud_speech.BatchRecognizeFileMetadata(uri=gcs_uri)],
        recognition_output_config=cloud_speech.RecognitionOutputConfig(
            gcs_output_config=cloud_speech.GcsOutputConfig(uri=prefix),
        ),
    )
    logger.info(
        "STT v2 batch_recognize uri=%s model=%s languages=%s location=%s out=%s",
        gcs_uri,
        config.model,
        list(config.language_codes),
        stt_location(),
        prefix,
    )
    operation = client.batch_recognize(request=request)
    name = getattr(operation, "name", None) or getattr(
        getattr(operation, "operation", None), "name", None
    )
    if not name:
        raise RuntimeError("STT v2 BatchRecognize returned no operation name")
    return name


def get_operation(operation_name: str):
    client = get_speech_client()
    return client.transport.operations_client.get_operation(name=operation_name)


def _batch_recognize_response(op):
    response = getattr(op, "response", None)
    value = getattr(response, "value", None) if response is not None else None
    if not value:
        return None
    try:
        return cloud_speech.BatchRecognizeResponse.deserialize(value)
    except Exception:
        logger.warning("Could not deserialize BatchRecognizeResponse", exc_info=True)
        return None


def file_error_from_operation(op) -> str | None:
    """Per-file STT error (LRO can be done=True while GCS access failed)."""
    parsed = _batch_recognize_response(op)
    if parsed is None:
        return None
    for file_result in (parsed.results or {}).values():
        err = getattr(file_result, "error", None)
        code = getattr(err, "code", 0) if err is not None else 0
        if code:
            return (getattr(err, "message", None) or "").strip() or f"STT file error code {code}"
    return None


def output_uri_from_operation(op) -> str | None:
    """GCS transcript URI from a completed BatchRecognize LRO, if present."""
    if file_error_from_operation(op):
        return None
    parsed = _batch_recognize_response(op)
    if parsed is None:
        return None
    for file_result in (parsed.results or {}).values():
        cs = getattr(file_result, "cloud_storage_result", None)
        uri = (getattr(cs, "uri", None) if cs is not None else None) or getattr(
            file_result, "uri", None
        )
        if uri:
            return uri
    return None
