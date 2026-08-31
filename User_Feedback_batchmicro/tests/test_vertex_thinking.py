from unittest.mock import MagicMock, patch

from services.shared.vertex_ai import VertexRestAdapter, relabel_speakers, translate_transcript


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
