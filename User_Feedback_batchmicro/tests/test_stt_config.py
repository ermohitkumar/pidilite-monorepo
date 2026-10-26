"""Unit tests for STT encoding / language helpers."""
from services.shared.stt_config import (
    alternative_language_codes,
    encoding_and_sample_rate,
    file_extension,
    resolve_v2_model,
)


def test_extension_from_uri():
    assert file_extension("gs://bucket/field/visit.webm") == "webm"
    assert file_extension("gs://bucket/a.MP3") == "mp3"
    assert file_extension("gs://bucket/noext", source_hint="wav") == "wav"


def test_webm_uses_opus_48k():
    assert encoding_and_sample_rate("webm") == ("WEBM_OPUS", 48000)


def test_ogg_uses_opus_48k():
    assert encoding_and_sample_rate("ogg") == ("OGG_OPUS", 48000)


def test_wav_omits_encoding_and_rate():
    assert encoding_and_sample_rate("wav") == (None, None)


def test_mp3_keeps_legacy_16k():
    assert encoding_and_sample_rate("mp3") == ("MP3", 16000)


def test_alternative_languages_exclude_primary():
    alts = alternative_language_codes("hi-IN")
    assert "hi-IN" not in alts
    assert "en-IN" in alts
    assert len(alts) <= 3


def test_legacy_models_map_to_chirp3():
    assert resolve_v2_model("latest_long") == "chirp_3"
    assert resolve_v2_model(None) == "chirp_3"
    assert resolve_v2_model("telephony") == "chirp_3"
    assert resolve_v2_model("chirp_2") == "chirp_3"


def test_webm_octet_stream_resolves_to_audio_webm():
    from services.shared.stt_config import (
        is_audio_media,
        resolve_media_extension,
        resolved_audio_mime,
    )

    assert resolved_audio_mime("webm", "application/octet-stream") == "audio/webm"
    assert resolved_audio_mime("webm", None) == "audio/webm"
    assert resolved_audio_mime("webm", "binary/octet-stream") == "audio/webm"
    assert is_audio_media("webm", "application/octet-stream") is True
    assert resolved_audio_mime("webm", "video/webm") == "video/webm"
    assert is_audio_media("json", "application/octet-stream") is False
    # Generic MIME alone must not pass as audio when the extension is unknown.
    assert resolved_audio_mime("", "application/octet-stream") == ""
    assert is_audio_media("", "application/octet-stream") is False
    assert resolve_media_extension(
        stored_ext="",
        file_name="visit.webm",
        gcs_uri="gs://bucket/path/visit.webm",
    ) == "webm"
    assert resolve_media_extension(
        stored_ext=None,
        file_name=None,
        gcs_uri="gs://bucket/sitelead/22:09:26/a.webm",
    ) == "webm"
