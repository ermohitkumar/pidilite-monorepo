from unittest.mock import MagicMock, patch

from services.shared.vertex_ai import (
    VertexRestAdapter,
    format_labeled_turns,
    label_timed_turns,
    relabel_speakers,
    translate_transcript,
)


def test_generate_content_uses_15k_output_cap():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [{"content": {"parts": [{"text": '{"insights": []}'}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "totalTokenCount": 14},
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        result, tokens = VertexRestAdapter.generate_content(
            "sys", "user", {"type": "object"}, "gemini-2.5-flash"
        )
    assert result == {"insights": []}
    assert tokens["total"] == 14
    payload = post.call_args.kwargs["json"]
    assert payload["generationConfig"]["maxOutputTokens"] == 15000
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_generate_text_sends_thinking_budget_zero():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [{"content": {"parts": [{"text": "Speaker 1: Hello\nSpeaker 2: Hi"}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8, "totalTokenCount": 18},
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        text, tokens = VertexRestAdapter.generate_text("hello", temperature=0.2)
    assert text.startswith("Speaker 1:")
    assert tokens["total"] == 18
    payload = post.call_args.kwargs["json"]
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert "maxOutputTokens" not in payload["generationConfig"]


def test_translate_and_relabel_both_disable_thinking():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "Speaker 1: How is Fevicol SH working on site?\n"
                                "Speaker 2: I applied two tins yesterday."
                            )
                        }
                    ]
                }
            }
        ],
        "usageMetadata": {},
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        out, _ = translate_transcript("Speaker 1: Fevicol SH kaisa hai?")
    assert "Fevicol" in out
    assert "FME:" in out or "User:" in out or "Speaker" in out
    assert post.call_count == 2  # translate + relabel
    for call in post.call_args_list:
        cfg = call.kwargs["json"]["generationConfig"]
        assert cfg["thinkingConfig"]["thinkingBudget"] == 0


def test_relabel_keeps_source_when_request_fails():
    src = "Speaker 1: How is Fevicol SH working?\nSpeaker 2: I applied it yesterday."
    with patch.object(VertexRestAdapter, "generate_text", side_effect=RuntimeError("boom")):
        out, tokens = relabel_speakers(src)
    assert out == src
    assert tokens["total"] == 0


def test_translate_prompt_includes_product_catalog():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [{"content": {"parts": [{"text": "FME: How is Fevicol EZEESPRAY?\nUser: Very good."}]}}],
        "usageMetadata": {},
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        translate_transcript(
            "Easy Spray kaisa hai?",
            product_catalog_tsv="EZEE|Fevicol EZEESPRAY|spray adhesive",
        )
    translate_prompt = post.call_args_list[0].kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "Fevicol EZEESPRAY" in translate_prompt
    assert "PRODUCT DATABASE" in translate_prompt
    assert "FME:" in translate_prompt
    assert "User:" in translate_prompt


def test_label_timed_turns_sends_timestamps_audio_and_thinking():
    segments = [
        {"start": 0.3, "end": 4.2, "text": "फेविकोल कैसा लगा"},
        {"start": 5.0, "end": 9.5, "text": "एक साइड में अच्छा है"},
        {"start": 10.1, "end": 14.0, "text": "पैकिंग कैसी है"},
    ]
    payload = {
        "lines": [
            {"index": 0, "role": "FME", "english": "How did you find Fevicol?"},
            {"index": 1, "role": "User", "english": "It is good on one side."},
            {"index": 2, "role": "FME", "english": "How is the packaging?"},
        ]
    }
    fake_json = {
        "candidates": [{"content": {"parts": [
            {"thought": True, "text": "The second voice answers."},
            {"text": __import__("json").dumps(payload)},
        ]}}],
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 30, "totalTokenCount": 80},
    }
    creds = MagicMock()
    creds.token = "tok"
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        text, tokens = label_timed_turns(
            segments,
            audio_gcs_uri="gs://pidilite-raw-audio/samples/test03/call.mp3",
        )
    body = post.call_args.kwargs["json"]
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 8192}
    sent = body["contents"][0]["parts"]
    assert sent[0]["fileData"]["fileUri"].endswith("call.mp3")
    assert "0|0.30|4.20|" in sent[1]["text"]
    assert "Do NOT merge the visit into two blocks" in sent[1]["text"]
    assert text.splitlines() == [
        "[00:00–00:04] FME: How did you find Fevicol?",
        "[00:05–00:10] User: It is good on one side.",
        "[00:10–00:14] FME: How is the packaging?",
    ]
    assert tokens["total"] == 80
    assert format_labeled_turns([]) == ""


def test_label_timed_turns_retries_when_reply_is_two_blocks():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 2.0, "end": 3.0, "text": "b"},
        {"start": 4.0, "end": 5.0, "text": "c"},
    ]
    short = {"lines": [{"index": 0, "role": "FME", "english": "all of it"}]}
    full = {
        "lines": [
            {"index": 0, "role": "FME", "english": "Question one."},
            {"index": 1, "role": "User", "english": "Answer."},
            {"index": 2, "role": "FME", "english": "Question two."},
        ]
    }
    with patch.object(
        VertexRestAdapter,
        "generate_parts",
        side_effect=[
            (__import__("json").dumps(short), {"input": 1, "output": 1, "total": 2}),
            (__import__("json").dumps(full), {"input": 1, "output": 1, "total": 2}),
        ],
    ) as gen:
        text, tokens = label_timed_turns(segments)
    assert gen.call_count == 2
    assert text.count("\n") == 2
    assert "User:" in text
    assert tokens["total"] == 4


def test_translate_splits_collapsed_english_turns():
    fme = ("How is Fevicol SH working on site? Do you use it for plywood? " * 4).strip()
    user = ("I applied two drums yesterday. Packets are leaking on my site. " * 4).strip()
    collapsed = f"FME: {fme} {user}"
    split = f"FME: {fme}\nUser: {user}"
    with patch.object(
        VertexRestAdapter,
        "generate_text",
        side_effect=[
            (collapsed, {"input": 1, "output": 1, "total": 2}),
            (split, {"input": 1, "output": 1, "total": 2}),
            (split, {"input": 1, "output": 1, "total": 2}),
        ],
    ) as gen:
        out, _ = translate_transcript(collapsed)
    assert gen.call_count == 3
    assert "User:" in out
    assert out.count("\n") >= 1
