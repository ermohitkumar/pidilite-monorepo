from services.shared.speakers import (
    content_preserved,
    format_turns,
    is_collapsed_speaker_transcript,
    remap_speaker_roles,
    score_role,
)


def test_remap_swaps_inverted_fme_and_customer():
    text = (
        "Speaker 1: We applied Fevicol SH. The packets are leaking from the sides.\n"
        "Speaker 2: I understand sir. We will raise this with the product team. "
        "What about Roff?"
    )
    out = remap_speaker_roles(text)
    lines = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in out.splitlines()}
    assert "leaking" in lines["User"]
    assert "product team" in lines["FME"]
    assert "We applied" in lines["User"]


def test_remap_keeps_correct_fme_as_speaker_1():
    text = (
        "Speaker 1: How is Fevicol SH working? Do you use it on site?\n"
        "Speaker 2: I applied it yesterday. Packets are leaking."
    )
    out = remap_speaker_roles(text)
    assert "FME: How is Fevicol SH working?" in out
    assert "User: I applied it yesterday." in out


def test_remap_merges_consecutive_same_speaker():
    text = (
        "Speaker 1: How is business?\n"
        "Speaker 1: What about Fevicol SH?\n"
        "Speaker 2: We use it. I applied two drums."
    )
    out = remap_speaker_roles(text)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("FME:")
    assert "How is business?" in lines[0]
    assert "What about Fevicol SH?" in lines[0]


def test_remap_customer_like_speaker_3_survives_as_user():
    text = (
        "Speaker 1: How is Fevicol SH working?\n"
        "Speaker 2: I applied it yesterday.\n"
        "Speaker 3: Packets are leaking on my site."
    )
    out = remap_speaker_roles(text)
    assert "Speaker 3:" not in out
    assert "leaking" in out
    assert "User:" in out


def test_remap_maps_extra_speaker_ids_to_1_or_2():
    text = (
        "Speaker 1: How is the scheme?\n"
        "Speaker 3: We will arrange an FCC meet.\n"
        "Speaker 2: I use Fevicol SH on my site."
    )
    out = remap_speaker_roles(text)
    assert "Speaker 3:" not in out
    assert "FCC meet" in out
    assert "FME:" in out
    assert "User:" in out


def test_remap_accepts_fme_user_labels():
    text = (
        "FME: How is Fevicol SH working?\n"
        "User: I applied it yesterday."
    )
    out = remap_speaker_roles(text)
    assert out.splitlines()[0].startswith("FME:")
    assert "I applied it yesterday." in out


def test_score_role_questions_count_as_fme():
    fme, customer = score_role("How is Fevicol SH? Do you use it?")
    assert fme > customer


def test_content_preserved_rejects_short_relabel():
    original = "Speaker 1: One two three four five six seven eight\nSpeaker 2: nine ten"
    short = "Speaker 1: One two"
    assert content_preserved(original, short) is False
    assert content_preserved(original, original) is True


def test_format_turns_unlabeled_passthrough():
    assert format_turns([(None, "hello there")]) == "hello there"


def test_collapsed_single_speaker_blob_detected():
    blob = "Speaker 1: " + ("Namaste. How is Fevicol SH working on site? I applied two drums. " * 8)
    assert is_collapsed_speaker_transcript(blob) is True


def test_two_speaker_dialogue_is_not_collapsed():
    text = "\n".join(
        [
            "Speaker 1: How is Fevicol SH working?",
            "Speaker 2: I applied it yesterday.",
            "Speaker 1: Any leak issue?",
            "Speaker 2: Packets are leaking on my site.",
        ]
    )
    assert is_collapsed_speaker_transcript(text) is False


def test_short_one_liner_is_not_collapsed():
    assert is_collapsed_speaker_transcript("Speaker 1: Hello.") is False
