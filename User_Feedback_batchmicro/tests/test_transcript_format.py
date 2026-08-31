"""Unit tests for STT transcript formatting / speaker diarization."""
from services.shared.transcript import format_stt_results


def test_format_without_speaker_tags_joins_transcripts():
    raw = {
        "results": [
            {"alternatives": [{"transcript": "Hello there."}]},
            {"alternatives": [{"transcript": "How are you?"}]},
        ]
    }
    assert format_stt_results(raw) == "Hello there. How are you?"


def test_format_with_speaker_tags_builds_speaker_lines():
    # Mimic Cloud STT: final result carries full word list with speakerTag.
    raw = {
        "results": [
            {
                "alternatives": [
                    {
                        "transcript": "hello how are you fine",
                        "words": [
                            {"word": "hello", "speakerTag": 1},
                            {"word": "how", "speakerTag": 1},
                            {"word": "are", "speakerTag": 1},
                            {"word": "you", "speakerTag": 1},
                            {"word": "fine", "speakerTag": 2},
                        ],
                    }
                ]
            }
        ]
    }
    text = format_stt_results(raw)
    assert "Speaker 1: hello how are you" in text
    assert "Speaker 2: fine" in text
    assert text.index("Speaker 1:") < text.index("Speaker 2:")


def test_format_uses_last_tagged_result_when_it_covers_full_audio():
    raw = {
        "results": [
            {
                "alternatives": [
                    {"transcript": "Namaste ji"},
                ]
            },
            {
                "alternatives": [
                    {
                        "transcript": "Namaste ji",
                        "words": [
                            {"word": "Namaste", "speakerTag": 1},
                            {"word": "ji", "speakerTag": 2},
                        ],
                    }
                ]
            },
        ]
    }
    text = format_stt_results(raw)
    assert text == "Speaker 1: Namaste\nSpeaker 2: ji"


def test_format_keeps_full_transcript_when_diarization_window_is_short():
    """Long audio: chunk transcripts are full; last result only tags a tail window."""
    raw = {
        "results": [
            {
                "alternatives": [
                    {"transcript": "We discussed Fevicol SH and the new scheme for dealers."}
                ]
            },
            {
                "alternatives": [
                    {"transcript": "Customer said the adhesive is good but delivery is late."}
                ]
            },
            {
                "alternatives": [
                    {
                        "transcript": "",
                        "words": [
                            {"word": "delivery", "speakerTag": 1},
                            {"word": "is", "speakerTag": 1},
                            {"word": "late", "speakerTag": 2},
                        ],
                    }
                ]
            },
        ]
    }
    text = format_stt_results(raw)
    assert "Fevicol SH" in text
    assert "adhesive is good" in text
    assert "delivery is late" in text
    assert "Speaker 1:" not in text


def test_format_empty_results():
    assert format_stt_results({}) == ""
    assert format_stt_results({"results": []}) == ""


def test_format_single_speaker_tag_falls_back_to_plain_transcript():
    # Cloud STT often tags every word as speaker 1 — do not emit a fake single blob.
    raw = {
        "results": [
            {"alternatives": [{"transcript": "Hello there."}]},
            {
                "alternatives": [
                    {
                        "transcript": "",
                        "words": [
                            {"word": "Hello", "speakerTag": 1},
                            {"word": "there.", "speakerTag": 1},
                        ],
                    }
                ]
            },
        ]
    }
    text = format_stt_results(raw)
    assert text == "Hello there."
    assert "Speaker 1:" not in text


def test_format_gemini_flash_json_keeps_speaker_n():
    raw = {
        "provider": "gemini_flash",
        "model": "gemini-2.5-flash",
        "transcript": (
            "Speaker 1: How is Fevicol SH?\n"
            "Speaker 2: I applied it yesterday.\n"
            "Speaker 3: Packets are leaking."
        ),
        "detected_languages": [],
    }
    text = format_stt_results(raw)
    assert "Speaker 1:" in text
    assert "Speaker 2:" in text
    assert "Speaker 3: Packets are leaking." in text
    assert "results" not in raw or format_stt_results({"provider": "gemini_flash"}) == ""

