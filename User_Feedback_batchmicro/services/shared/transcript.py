"""Shared helpers for STT transcript extraction from GCS."""
import json
import logging
import re

from core.config import settings

logger = logging.getLogger(__name__)

try:
    from google.cloud import storage as gcs_storage
    _HAS_GCS = True
except ImportError:
    _HAS_GCS = False

_gcs_client = None  # Cached GCS client singleton

# Diarized last-result window must cover most of the plain transcript.
# Cloud STT speaker tags only land on a trailing slice of long audio.
_DIARIZATION_COVERAGE = 0.85


def extract_bucket_from_selflink(self_link: str | None, default_bucket: str | None = None) -> str:
    if self_link:
        match = re.search(r"/b/([^/]+)/o/", self_link)
        if match:
            return match.group(1)
    return default_bucket or settings.GCS_OUTPUT_BUCKET


def extract_job_id_from_path(gcs_path: str) -> str | None:
    """Extract job_id from stt-output/{job_id}/output.json"""
    parts = gcs_path.split("/")
    if len(parts) >= 2 and parts[0] == "stt-output":
        return parts[1]
    return None


def _speaker_tag(word: dict) -> int | None:
    if "speakerTag" in word:
        return int(word["speakerTag"])
    if "speaker_tag" in word:
        return int(word["speaker_tag"])
    return None


def _word_count(text: str) -> int:
    cleaned = re.sub(r"Speaker\s+\d+:", " ", text or "")
    return len(cleaned.split())


def _plain_transcript(results: list) -> str:
    """Concatenate per-chunk transcripts. Last result may repeat the full audio."""
    parts: list[str] = []
    for result in results:
        alternatives = result.get("alternatives") or []
        if not alternatives:
            continue
        text = (alternatives[0].get("transcript") or "").strip()
        if text:
            parts.append(text)
    if not parts:
        return ""
    if len(parts) >= 2:
        earlier = " ".join(parts[:-1])
        last = parts[-1]
        if last.startswith(earlier[:80]) or earlier in last:
            return last
    return " ".join(parts).strip()


def _diarized_transcript(words: list[dict]) -> str:
    unique_speakers = {
        tag
        for word_info in words
        if (tag := _speaker_tag(word_info)) is not None
    }
    # Cloud STT often collapses diarization to a single speakerTag (all "1").
    if len(unique_speakers) < 2:
        return ""

    lines: list[str] = []
    current_speaker: int | None = None
    current_words: list[str] = []
    for word_info in words:
        tag = _speaker_tag(word_info)
        token = (word_info.get("word") or "").strip()
        if not token:
            continue
        speaker = tag if tag is not None else 0
        if current_speaker is None:
            current_speaker = speaker
        if speaker != current_speaker:
            if current_words:
                lines.append(f"Speaker {current_speaker}: {' '.join(current_words)}")
            current_speaker = speaker
            current_words = [token]
        else:
            current_words.append(token)
    if current_words and current_speaker is not None:
        lines.append(f"Speaker {current_speaker}: {' '.join(current_words)}")
    return "\n".join(lines).strip()


def format_stt_results(raw_json: dict) -> str:
    """
    Build a plain-text transcript from Cloud STT JSON or Gemini Flash JSON.

    Gemini Flash writes {provider: gemini_flash, transcript: "Speaker 1: ..."}.
    Cloud STT uses results[]. When speaker diarization is enabled, Cloud STT
    attaches speakerTag on words (often only on a trailing window of the final
    result). Those become:

        Speaker 1: ...
        Speaker 2: ...

    If that window is shorter than the concatenated chunk transcripts, keep the
    full text so long videos are not reduced to the last few seconds.
    """
    if (raw_json.get("provider") or "") == "gemini_flash":
        return (raw_json.get("transcript") or "").strip()

    results = raw_json.get("results") or []
    plain = _plain_transcript(results)

    tagged_word_lists: list[list[dict]] = []
    for result in results:
        alternatives = result.get("alternatives") or []
        if not alternatives:
            continue
        words = alternatives[0].get("words") or []
        if words and any(_speaker_tag(w) is not None for w in words):
            tagged_word_lists.append(words)

    if tagged_word_lists:
        # Prefer the longest tagged list (final result is supposed to be full).
        words = max(tagged_word_lists, key=len)
        diarized = _diarized_transcript(words)
        if diarized:
            if not plain or _word_count(diarized) >= _word_count(plain) * _DIARIZATION_COVERAGE:
                return diarized
            logger.warning(
                "Discarding short STT diarization window (%d words) in favour of "
                "full transcript (%d words)",
                _word_count(diarized),
                _word_count(plain),
            )

    return plain


def extract_transcript_from_stt_json(gcs_uri: str) -> str:
    """Download STT output JSON from GCS and build a (optionally diarized) transcript."""
    if not _HAS_GCS:
        raise RuntimeError("google-cloud-storage is not installed")

    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    without_prefix = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = without_prefix.split("/", 1)
    blob = _gcs_client.bucket(bucket_name).blob(blob_path)
    raw_json = json.loads(blob.download_as_text())

    transcript = format_stt_results(raw_json)
    logger.info("Extracted transcript (%d chars) from %s", len(transcript), gcs_uri)
    return transcript


def gcs_blob_exists(gcs_uri: str) -> bool:
    """True when the GCS object exists (used by checker for Gemini Flash STT)."""
    if not _HAS_GCS:
        raise RuntimeError("google-cloud-storage is not installed")

    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    without_prefix = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = without_prefix.split("/", 1)
    return _gcs_client.bucket(bucket_name).blob(blob_path).exists()
