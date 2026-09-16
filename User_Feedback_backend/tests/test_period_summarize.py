from datetime import date

import pytest

from services.period_summarize.compact import estimate_tokens, pack_chunks, source_hash
from services.period_summarize.period_keys import (
    GRAINS,
    bounds_for,
    child_month_keys,
    infer_period,
    previous_period,
    resolve_grain,
)
from services.period_summarize.llm import LLMError, _prompt_for, summarize_lines


def test_month_quarter_year_bounds():
    assert bounds_for("month", "2026-09") == (date(2026, 9, 1), date(2026, 9, 30))
    assert bounds_for("quarter", "2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert bounds_for("year", "2026") == (date(2026, 1, 1), date(2026, 12, 31))
    assert child_month_keys("2026-Q3") == ["2026-07", "2026-08", "2026-09"]


def test_infer_and_previous_period():
    assert infer_period(date(2026, 9, 1), date(2026, 9, 30)) == ("month", "2026-09")
    assert infer_period(date(2026, 7, 1), date(2026, 9, 30)) == ("quarter", "2026-Q3")
    assert infer_period(date(2026, 1, 1), date(2026, 12, 31)) == ("year", "2026")
    assert previous_period("month", "2026-01") == ("month", "2025-12")
    assert previous_period("quarter", "2026-Q1") == ("quarter", "2025-Q4")


def test_resolve_grain_most_specific():
    assert resolve_grain(fme_code="BDDEL03", cluster="RBDM-DELHI", zone="NCR", division="FV") == ("bde", "BDDEL03")
    assert resolve_grain(cluster="RBDM-DELHI", zone="NCR", division="FV") == ("rfmm", "RBDM-DELHI")
    assert resolve_grain(zone="NCR", division="FV") == ("zone", "NCR")
    assert resolve_grain(division="FV") == ("division", "FV")
    assert resolve_grain() == (None, None)


def test_pack_chunks_never_exceeds_budget():
    lines = [f"insight-{index}-" + ("word " * 80) for index in range(80)]
    chunks, _truncated = pack_chunks(lines, budget=8000)
    assert chunks
    for chunk in chunks:
        assert estimate_tokens("\n".join(chunk)) <= 8000


def test_max_tokens_retries_with_half_chunk():
    calls: list[int] = []

    def generate(prompt: str, tighter: bool = False):
        calls.append(len(prompt))
        if len(calls) == 1:
            raise LLMError("max_tokens", "MAX_TOKENS")
        return {
            "summary": "short",
            "themes": ["quality"],
            "products": ["Marine"],
            "risks": [],
            "_tokens": {"input": 10, "output": 8},
        }

    result = summarize_lines(
        ["line-one quality Marine", "line-two price Marine"],
        generate=generate,
        sleep=lambda _seconds: None,
    )
    assert result["summary"] == "short"
    assert len(calls) >= 2


def test_429_backoff_then_success():
    calls = {"count": 0}

    def generate(prompt: str, tighter: bool = False):
        calls["count"] += 1
        if calls["count"] == 1:
            raise LLMError("transient", "429 Resource exhausted")
        return {
            "summary": "recovered",
            "themes": [],
            "products": [],
            "risks": [],
            "_tokens": {"input": 4, "output": 4},
        }

    sleeps: list[float] = []
    result = summarize_lines(
        ["one compact line about Marine"],
        generate=generate,
        sleep=sleeps.append,
    )
    assert result["summary"] == "recovered"
    assert calls["count"] == 2
    assert any(value >= 1 for value in sleeps)


def test_source_hash_stable():
    assert source_hash(["a", "b"]) == source_hash(["a", "b"])
    assert source_hash(["a", "b"]) != source_hash(["a", "c"])


def test_floor_chunk_max_tokens_raises():
    def generate(prompt: str, tighter: bool = False):
        raise LLMError("max_tokens", "MAX_TOKENS")

    with pytest.raises(LLMError):
        summarize_lines(
            ["single-line-floor"],
            generate=generate,
            sleep=lambda _seconds: None,
        )


def test_split_depth_cap_does_not_loop():
    calls = {"count": 0}

    def generate(prompt: str, tighter: bool = False):
        calls["count"] += 1
        assert calls["count"] < 40
        body = prompt.split("\n\n", 1)[-1]
        lines = [line for line in body.split("\n") if line.strip()]
        if len(lines) == 1 and not lines[0].startswith("short "):
            return {
                "summary": f"short {lines[0]}",
                "themes": [],
                "products": [],
                "risks": [],
                "_tokens": {"input": 4, "output": 4},
            }
        raise LLMError("max_tokens", "MAX_TOKENS")

    result = summarize_lines(
        ["line-a quality", "line-b price", "line-c stock", "line-d delay"],
        generate=generate,
        sleep=lambda _seconds: None,
    )
    assert result["summary"]
    assert calls["count"] < 40


def test_grains_include_tag():
    assert "tag" in GRAINS
    assert "bde_pt" in GRAINS
    assert "div_t" in GRAINS


def test_parse_insight_key_scoped_and_legacy():
    from services.period_summarize.period_keys import parse_insight_key, scoped_key

    assert parse_insight_key("tag", "22")["tag_id"] == "22"
    parsed = parse_insight_key("bde_pt", scoped_key("GOOD", "PDT", "Marine", "22"))
    assert parsed["geo_key"] == "GOOD"
    assert parsed["group_type"] == "PDT GROUP"
    assert parsed["product_name"] == "Marine"
    assert parsed["tag_id"] == "22"
    user_tag = parse_insight_key("bde_t", scoped_key("GOOD", "USER", "30"))
    assert user_tag["group_type"] == "USER GROUP"
    assert user_tag["product_name"] is None
    assert user_tag["tag_id"] == "30"


def test_is_visible_summary():
    from types import SimpleNamespace

    from services.period_summarize.store import is_visible_summary

    assert is_visible_summary(None) is False
    assert is_visible_summary(SimpleNamespace(status="ok", summary_text="")) is False
    assert is_visible_summary(SimpleNamespace(status="ok", summary_text="No insights for this node.")) is False
    assert is_visible_summary(SimpleNamespace(status="empty", summary_text="Marine leakage.")) is False
    assert is_visible_summary(SimpleNamespace(status="ok", summary_text="Marine leakage in NCR.")) is True


def test_tag_prompt_requires_justifying_the_tag():
    prompt = _prompt_for(
        ["2026-09-01|PDT|Marine|Packaging|Cap leaks"],
        False,
        grain="tag",
        grain_label="Packaging",
    )
    assert "Packaging" in prompt
    assert "justify this tag" in prompt.lower()
