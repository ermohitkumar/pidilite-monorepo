from datetime import date

import pytest

from services.period_summarize.compact import (
    combine_child_rollups,
    estimate_tokens,
    pack_chunks,
    findings_from_rows,
    format_findings,
    infer_sentiment,
    rollup_from_rows,
    row_sentiment,
    source_hash,
    topic_sentences,
)
from services.period_summarize.period_keys import (
    GRAINS,
    bounds_for,
    child_month_keys,
    infer_period,
    previous_period,
    resolve_grain,
)
from services.period_summarize.llm import (
    GeminiGate,
    LLMError,
    _is_transient,
    _retry_wait,
    _prompt_for,
    summarize_lines,
)


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


def test_transient_codes_include_grpc_and_http_gateway_errors():
    assert _is_transient(429, "", "quota") is True
    assert _is_transient(8, "", "RESOURCE_EXHAUSTED", "RESOURCE_EXHAUSTED") is True
    assert _is_transient(502, "", "Bad Gateway") is True
    assert _is_transient(504, "", "Gateway Timeout") is True
    assert _is_transient(14, "", "UNAVAILABLE", "UNAVAILABLE") is True
    assert _is_transient(400, "", "invalid argument") is False


def test_retry_after_header_is_honored():
    calls = {"count": 0}

    def generate(prompt: str, tighter: bool = False):
        calls["count"] += 1
        if calls["count"] == 1:
            raise LLMError("transient", "429 Resource exhausted", retry_after=12)
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
    assert any(value >= 12 for value in sleeps)
    assert _retry_wait(0, 12) == 12


def test_gemini_gate_caps_in_flight_and_interval():
    clock = {"t": 100.0}

    def now() -> float:
        return clock["t"]

    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    gate = GeminiGate(max_in_flight=1, max_per_minute=30, min_interval=0.5, clock=now)
    gate.acquire(sleep)
    assert gate._in_flight == 1
    gate.release()
    gate.acquire(sleep)
    assert sleeps and sleeps[0] >= 0.5
    gate.release()


def test_five_transient_failures_stop_at_cap():
    calls = {"count": 0}

    def generate(prompt: str, tighter: bool = False):
        calls["count"] += 1
        raise LLMError("transient", "503 UNAVAILABLE")

    with pytest.raises(LLMError) as caught:
        summarize_lines(
            ["one compact line about Marine"],
            generate=generate,
            sleep=lambda _seconds: None,
        )
    assert caught.value.kind == "transient"
    assert calls["count"] == 5


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
    rolled = parse_insight_key("div_pt", scoped_key("FV-RETAIL", "PDT", "Marine", "22"))
    assert rolled["geo_key"] == "FV-RETAIL"
    assert rolled["product_name"] == "Marine"
    assert rolled["tag_id"] == "22"


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


def test_infer_sentiment_from_insight_text():
    assert infer_sentiment("The user found Fevicol Multilock to be a good and effective product.") == "Positive"
    assert infer_sentiment("The user is happy with Fevicol Marine.") == "Positive"
    assert infer_sentiment("The user has never had trouble with Fevicol HEATX.") == "Positive"
    assert infer_sentiment("Fevicol RELAM's grip was less than desired.") == "Negative"
    assert infer_sentiment("The user experienced bubbling and poor adhesion.") == "Negative"
    assert infer_sentiment("One 10 kg Fevicol PROBOND token is not scanning in the FCC app.") == "Negative"
    assert infer_sentiment("The user is asking about the old scheme that used to happen every year.") == "Neutral"
    assert infer_sentiment("User asks if Fevicol Multilock can be used for sticking mirrors.") == "Neutral"
    assert row_sentiment({"ai_summary": "User praises Fevicol X-Per."}) == "Positive"
    unlabeled = rollup_from_rows([
        {"job_id": "j1", "user_id": "u1", "ai_summary": "Tin leaked from the lid."},
        {"job_id": "j2", "user_id": "u2", "ai_summary": "The user is asking about the scheme."},
    ])
    assert unlabeled["sentiment"] == "Negative"
    assert unlabeled["sentiment_counts"]["Negative"] == 1


def test_rollup_from_rows_counts_site_visits_users_and_topics():
    rows = [
        {
            "job_id": "j1",
            "user_id": "u1",
            "call_date": "2026-09-01",
            "product_name": "Marine",
            "tags": "Packaging, Leakage",
            "sentiment": "Negative",
            "ai_summary": "Tin leaked from the lid.",
        },
        {
            "job_id": "j2",
            "user_id": "u2",
            "call_date": "2026-09-02",
            "product_name": "Marine",
            "tags": "Packaging",
            "sentiment": "Negative",
            "ai_summary": "Tin leaked from the lid.",
        },
        {
            "job_id": "j3",
            "user_id": "u3",
            "call_date": "2026-09-03",
            "product_name": "SH",
            "tags": "Quality",
            "sentiment": "Positive",
            "ai_summary": "Bond is strong.",
        },
    ]
    rollup = rollup_from_rows(rows)
    assert rollup["site_visit_count"] == 3
    assert rollup["user_count"] == 3
    assert rollup["user_issue_count"] == 2
    assert rollup["sentiment"] == "Negative"
    topics = {item["label"]: item["user_count"] for item in rollup["topics"]}
    assert topics["Tin leaked from the lid"] == 2
    assert topics["Bond is strong"] == 1
    assert topic_sentences(rollup["topics"]) == (
        "Tin leaked from the lid (2 users). Bond is strong (1 user)."
    )
    findings = findings_from_rows(rows)
    assert findings[0]["title"] == "Marine"
    assert findings[0]["user_count"] == 2
    assert findings[0]["points"][0]["user_count"] == 2
    assert findings[0]["points"][0]["theme"] == "leakage / packaging"
    assert findings[0]["sentiment"] == "Negative"
    assert findings[0]["points"][0]["sentiment"] == "Negative"
    text = format_findings(findings)
    assert "leakage / packaging" in text.lower()
    assert "(2) " in text
    assert "(1) " in text
    assert "Marine" not in text
    shared_text = format_findings([
        {
            "product": "Fevicol X-Per",
            "points": [{
                "theme": "Weak Ultimate Bond / Delamination",
                "user_count": 1,
                "detail": "did not stick to the board",
            }],
        },
        {
            "product": "Fevicol SH",
            "points": [{
                "theme": "Weak Ultimate Bond / Delamination",
                "user_count": 1,
                "detail": "still came off",
            }],
        },
    ])
    assert shared_text.count("\n") == 0
    assert shared_text.startswith("(2) ")
    assert "Fevicol X-Per:" in shared_text
    assert "Fevicol SH:" in shared_text
    ordered = format_findings([
        {"points": [{"theme": "Others", "user_count": 7, "detail": "the result is good"}]},
        {"points": [{"theme": "Bubble forming", "user_count": 1, "detail": "no bubbles"}]},
    ])
    assert ordered.split("\n")[-1].startswith("(7) Others")
    assert ordered.split("\n")[0].startswith("(1) Bubble forming")
    assert "Data:" not in text
    assert "users reported similar observations" not in text
    assert "…" not in text
    assert "•" not in text
    assert text.split("\n")[0].startswith("(2) ")
    mixed = findings_from_rows([
        {
            "job_id": "a",
            "user_id": "a",
            "product_name": "Nail Free",
            "ai_summary": "There was bubbling on the acrylic edge.",
        },
        {
            "job_id": "b",
            "user_id": "b",
            "product_name": "Nail Free",
            "ai_summary": "User saw bubbles after application.",
        },
        {
            "job_id": "c",
            "user_id": "c",
            "product_name": "Nail Free",
            "ai_summary": "Fevicol Nail Free sets in 4-8 minutes.",
        },
    ])
    themes = {item["theme"]: item["user_count"] for item in mixed[0]["points"]}
    assert themes["bubbling issues"] == 2
    assert themes["setting time"] == 1
    mixed_text = format_findings(mixed)
    assert "Bubbling issues" in mixed_text
    assert "(2) " in mixed_text
    assert "Setting time" in mixed_text
    assert "(1) " in mixed_text
    assert "acrylic" in mixed_text.lower()
    assert mixed_text.split("\n")[0].startswith("(2) ")
    assert "Nail Free" not in mixed_text.split("\n")[0]
    tagged = findings_from_rows([
        {
            "job_id": "d",
            "user_id": "d",
            "product_name": "Fevicol Multilock",
            "tags": "Existing Product - Performance improvements",
            "ai_summary": "Fevicol Multilock has good grip when applied acrylic on acrylic.",
        },
        {
            "job_id": "e",
            "user_id": "e",
            "product_name": "Fevicol Multilock",
            "tags": "Existing Product - Performance improvements",
            "ai_summary": "Fevicol Multilock has good grip.",
        },
        {
            "job_id": "f",
            "user_id": "f",
            "product_name": "Fevicol Multilock",
            "tags": "Existing Product - Performance improvements",
            "ai_summary": "Fevicol Multilock is better for preventing bending.",
        },
    ])
    tagged_text = format_findings(tagged)
    assert "performance improvements" not in tagged_text.lower()
    assert "Grip / adhesion" in tagged_text
    assert "(2) " in tagged_text
    assert "acrylic" in tagged_text.lower()
    assert "bending" in tagged_text.lower()
    praise = findings_from_rows([
        {
            "job_id": "p1",
            "user_id": "p1",
            "product_name": "Fevicol SH",
            "ai_summary": "The quality of Fevicol SH is good.",
        },
        {
            "job_id": "p2",
            "user_id": "p2",
            "product_name": "Fevicol SH",
            "ai_summary": "Fevicol SH is a good product.",
        },
        {
            "job_id": "p3",
            "user_id": "p3",
            "product_name": "Fevicol SH",
            "ai_summary": "Fevicol SH for its strength.",
        },
        {
            "job_id": "p4",
            "user_id": "p4",
            "product_name": "Fevicol SH",
            "ai_summary": "The bonding strength of Fevicol SH is strong.",
        },
        {
            "job_id": "p5",
            "user_id": "p5",
            "product_name": "Fevicol SH",
            "ai_summary": "User praised Fevicol SH for being good and strong.",
        },
        {
            "job_id": "p6",
            "user_id": "p6",
            "product_name": "Fevicol SH",
            "ai_summary": "Fevicol SH for its good setting time.",
        },
    ])
    praise_themes = {item["theme"]: item["user_count"] for item in praise[0]["points"]}
    # Generic praise/quality/strength collapse; setting time stays its own line.
    assert set(praise_themes) <= {"product quality", "grip / adhesion", "setting time"}
    assert praise_themes.get("setting time") == 1
    assert sum(praise_themes.values()) == 6
    assert len(praise[0]["points"]) <= 3
    praise_text = format_findings(praise)
    assert "•" not in praise_text
    assert praise_text.count("\n") + 1 <= 3


def test_combine_child_rollups_merges_topics_and_sentiment():
    children = [
        {
            "call_count": 2,
            "insight_count": 2,
            "highlights": {
                "site_visit_count": 2,
                "user_count": 2,
                "user_issue_count": 2,
                "sentiment": "Negative",
                "sentiment_counts": {"Negative": 2},
                "topics": [{"label": "Marine", "user_count": 2}],
            },
        },
        {
            "call_count": 1,
            "insight_count": 1,
            "highlights": {
                "site_visit_count": 1,
                "user_count": 1,
                "user_issue_count": 0,
                "sentiment": "Positive",
                "sentiment_counts": {"Positive": 1},
                "topics": [{"label": "Marine", "user_count": 1}, {"label": "SH", "user_count": 1}],
            },
        },
    ]
    merged = combine_child_rollups(children)
    assert merged["site_visit_count"] == 3
    assert merged["user_issue_count"] == 2
    assert merged["sentiment"] == "Negative"
    topics = {item["label"]: item["user_count"] for item in merged["topics"]}
    assert topics["Marine"] == 3
    assert topics["SH"] == 1
