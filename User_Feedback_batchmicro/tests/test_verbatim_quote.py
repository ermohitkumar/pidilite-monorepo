from services.shared.verbatim import snap_verbatim_quote_to_transcript


def test_snap_keeps_exact_transcript_words():
    transcript = (
        "Speaker 1: And also use some new product of ours.\n"
        "Speaker 2: Yes, we had applied it. We had applied that. "
        "So I had also ordered Hyperstar last month for this site. "
        "But it was taking time here, so the client said not to slow down the work, "
        "it's getting delayed. So apply whatever dries quickly.\n"
        "Speaker 1: Okay, if it's coming, try it."
    )
    paraphrased = (
        "I had also ordered Hyperstar last month for this site, but there was a delay "
        "here, so the client said not to slow down the work, it's getting delayed, "
        "so use whatever arrives quickly."
    )
    snapped = snap_verbatim_quote_to_transcript(paraphrased, transcript)
    assert snapped in transcript
    assert snapped == (
        "So I had also ordered Hyperstar last month for this site. "
        "But it was taking time here, so the client said not to slow down the work, "
        "it's getting delayed. So apply whatever dries quickly."
    )


def test_snap_returns_exact_substring_unchanged():
    transcript = "Speaker 2: We are applying Hyper.\nSpeaker 1: Okay."
    quote = "We are applying Hyper."
    assert snap_verbatim_quote_to_transcript(quote, transcript) == "We are applying Hyper."


def test_snap_falls_back_when_nothing_matches():
    quote = "This quote is not in the call at all."
    assert snap_verbatim_quote_to_transcript(quote, "Speaker 1: Hello there.") == quote
