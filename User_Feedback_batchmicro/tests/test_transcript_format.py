"""Unit tests for STT transcript formatting / speaker diarization."""
from services.shared.transcript import (
    format_stt_results,
    timed_utterances,
    transcript_meets_min_words,
    word_count,
    MIN_TRANSCRIPT_WORDS,
    TOO_FEW_WORDS_MESSAGE,
)


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


def test_short_closing_chunk_does_not_replace_full_transcript():
    """A last result that repeats only the opening must not drop the call."""
    opening = "Namaste ji kaise hain aap. " * 4
    middle = "Fevicol SH ka price kya hai aur scheme kab milegi dealer ko."
    closing = opening[:100] + " Theek hai bye."
    raw = {
        "results": [
            {"alternatives": [{"transcript": opening + middle}]},
            {"alternatives": [{"transcript": closing}]},
        ]
    }
    text = format_stt_results(raw)
    assert "price kya hai" in text
    assert "Theek hai bye." in text


def test_full_final_result_still_replaces_chunked_prefix():
    opening = "Namaste ji kaise hain aap. Fevicol SH bahut accha hai."
    raw = {
        "results": [
            {"alternatives": [{"transcript": opening}]},
            {"alternatives": [{"transcript": opening + " Delivery late hai dealer ke yahan."}]},
        ]
    }
    text = format_stt_results(raw)
    assert text == opening + " Delivery late hai dealer ke yahan."
    assert text.count("Namaste") == 1


def test_plain_transcript_removes_overlapping_chunk_boundary_words():
    raw = {
        "results": [
            {"alternatives": [{"transcript": "We discussed the Fevicol SH application on site today"}]},
            {"alternatives": [{"transcript": "Fevicol SH application on site today and delivery tomorrow"}]},
        ]
    }
    text = format_stt_results(raw)
    assert text == "We discussed the Fevicol SH application on site today and delivery tomorrow"


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


def test_format_chirp3_speaker_label_is_one_based():
    raw = {
        "results": [
            {
                "alternatives": [
                    {
                        "transcript": "hello there",
                        "words": [
                            {
                                "word": "hello",
                                "startOffset": "0s",
                                "endOffset": "0.400s",
                                "speakerLabel": "0",
                            },
                            {
                                "word": "there",
                                "startOffset": "0.500s",
                                "endOffset": "0.900s",
                                "speakerLabel": "1",
                            },
                        ],
                    }
                ]
            }
        ]
    }
    assert format_stt_results(raw) == "Speaker 1: hello\nSpeaker 2: there"


def test_label_only_transcript_fails_min_words():
    assert word_count("Speaker 1:") == 0
    assert word_count("Speaker 1: \nSpeaker 2:") == 0
    assert not transcript_meets_min_words("Speaker 1:")
    assert MIN_TRANSCRIPT_WORDS == 100
    assert "100" in TOO_FEW_WORDS_MESSAGE


def test_short_spoken_transcript_fails_min_words():
    text = "Speaker 1: It's good, it's strong.\nSpeaker 2: Fevicol MARINE is also good."
    assert word_count(text) < 100
    assert not transcript_meets_min_words(text)


def test_long_spoken_transcript_passes_min_words():
    words = " ".join(f"word{i}" for i in range(100))
    text = f"Speaker 1: {words}"
    assert word_count(text) == 100
    assert transcript_meets_min_words(text)


def test_timed_utterances_split_on_pause_and_keep_times():
    raw = {
        "results": [
            {
                "alternatives": [
                    {
                        "transcript": "hello there how are you",
                        "words": [
                            {"word": "hello", "startOffset": "0.200s", "endOffset": "0.500s"},
                            {"word": "there", "startOffset": "0.600s", "endOffset": "0.900s"},
                            {"word": "how", "startOffset": "2.400s", "endOffset": "2.700s"},
                            {"word": "are", "startOffset": "2.800s", "endOffset": "3.000s"},
                            {"word": "you", "startOffset": "3.100s", "endOffset": "3.400s"},
                        ],
                    }
                ]
            }
        ]
    }
    lines = timed_utterances(raw)
    assert len(lines) == 2
    assert lines[0]["text"] == "hello there"
    assert lines[0]["start"] == 0.2
    assert lines[1]["text"] == "how are you"
    assert lines[1]["start"] == 2.4


def test_timed_utterances_ignore_text_without_offsets():
    raw = {"results": [{"alternatives": [{"transcript": "Hello there."}]}]}
    assert timed_utterances(raw) == []


def test_timed_utterances_drop_same_text_repeated_at_overlapping_times():
    words = [
        {"word": "The", "startOffset": "0s", "endOffset": "0.2s"},
        {"word": "L-free", "startOffset": "0.2s", "endOffset": "0.5s"},
        {"word": "one", "startOffset": "0.5s", "endOffset": "0.7s"},
        {"word": "is", "startOffset": "0.7s", "endOffset": "0.9s"},
    ]
    raw = {
        "results": [
            {"alternatives": [{"words": words}]},
            {"alternatives": [{"words": words}]},
        ]
    }
    utterances = timed_utterances(raw)
    assert len(utterances) == 1
    assert utterances[0]["text"] == "The L-free one is"

