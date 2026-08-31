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


def test_v1_models_map_to_telephony():
    assert resolve_v2_model("latest_long") == "telephony"
    assert resolve_v2_model(None) == "telephony"
    assert resolve_v2_model("telephony") == "telephony"
    assert resolve_v2_model("chirp_2") == "chirp_2"
