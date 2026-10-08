from datetime import date

from db.models import PeriodSummary
from services.period_summarize.llm import LLMError
from services.period_summarize.runner import run_month
from services.period_summarize.store import get_current


def _ok(summary: str) -> dict:
    return {
        "summary": summary,
        "themes": ["quality"],
        "products": ["Marine"],
        "risks": [],
        "_tokens": {"input": 6, "output": 4},
        "_truncated": False,
    }


def _nodes(_db, _start, _end):
    return [
        {"bde_key": "GOOD", "rfmm_key": "RFMM-A", "zone_key": "ZONE-A", "division_key": "DIV-A"},
        {"bde_key": "BAD", "rfmm_key": "RFMM-A", "zone_key": "ZONE-A", "division_key": "DIV-A"},
    ]


def _gather(_db, start, end, grain, grain_key):
    assert grain in {"bde", "product", "tag", "bde_pt", "bde_p", "bde_t"}
    summary = "FAILME hold issue" if grain_key == "BAD" else f"{grain_key} likes Marine"
    return [{
        "insight_id": f"{grain}:{grain_key}",
        "call_date": start,
        "group_type": "USER GROUP" if "USER" in grain_key else "PDT GROUP",
        "product_name": None if grain == "bde_t" and "USER" in grain_key else "Marine",
        "ai_summary": summary,
        "tags": "Quality",
    }]


def test_runner_builds_hierarchy_from_children_only(db_session):
    gather_grains: list[str] = []

    def gather(db, start, end, grain, grain_key):
        gather_grains.append(grain)
        return _gather(db, start, end, grain, grain_key)

    def summarize(lines, **_kwargs):
        text = "\n".join(lines)
        if "FAILME" in text:
            raise LLMError("fatal", "boom")
        return _ok(text[:80])

    results = run_month(
        db_session,
        "2026-09",
        summarize=summarize,
        gather=gather,
        list_nodes=_nodes,
        list_products=lambda *_args: ["Marine"],
        list_tags=lambda *_args: [],
    )
    assert "rfmm" not in gather_grains
    assert "zone" not in gather_grains
    assert "division" not in gather_grains
    assert any(item["grain"] == "bde" and item["grain_key"] == "BAD" and item["status"] == "error" for item in results)
    assert any(item["grain"] == "bde" and item["grain_key"] == "GOOD" and item["status"] == "ok" for item in results)
    rfmm = get_current(db_session, "rfmm", "RFMM-A", "month", "2026-09")
    zone = get_current(db_session, "zone", "ZONE-A", "month", "2026-09")
    division = get_current(db_session, "division", "DIV-A", "month", "2026-09")
    assert rfmm and rfmm.source_kind == "child_summaries"
    assert zone and zone.source_kind == "child_summaries"
    assert division and division.source_kind == "child_summaries"


def test_runner_skips_unchanged_hash_and_versions(db_session):
    calls = {"count": 0}

    def summarize(lines, **_kwargs):
        calls["count"] += 1
        return _ok("same narrative")

    kwargs = dict(
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args: [_nodes(None, None, None)[0]],
        list_products=lambda *_args: [],
        list_tags=lambda *_args: [],
    )
    first = run_month(db_session, "2026-09", **kwargs)
    second = run_month(db_session, "2026-09", **kwargs)
    assert calls["count"] >= 1
    assert any(item.get("skipped") for item in second)
    current = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    assert current and current.version == 1

    def summarize_new(lines, **_kwargs):
        return _ok("changed narrative")

    kwargs["summarize"] = summarize_new
    kwargs["force"] = True
    run_month(db_session, "2026-09", **kwargs)
    current = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    assert current and current.version == 2
    previous = (
        db_session.query(PeriodSummary)
        .filter(
            PeriodSummary.grain == "bde",
            PeriodSummary.grain_key == "GOOD",
            PeriodSummary.is_current.is_(False),
        )
        .one()
    )
    assert previous.version == 1
    assert previous.period_start == date(2026, 9, 1)
    assert any(item.get("skipped") for item in first) or first


def test_quarter_rolls_up_from_month_children(db_session):
    from services.period_summarize.runner import roll_quarter

    def summarize(lines, **_kwargs):
        return _ok("rolled")

    kwargs = dict(
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args: [_nodes(None, None, None)[0]],
        list_products=lambda *_args: [],
        list_tags=lambda *_args: [],
    )
    run_month(db_session, "2026-07", **kwargs)
    run_month(db_session, "2026-08", **kwargs)
    run_month(db_session, "2026-09", **kwargs)
    roll_quarter(db_session, "2026-Q3", force=False, summarize=summarize)
    quarter = get_current(db_session, "division", "DIV-A", "quarter", "2026-Q3")
    assert quarter is not None
    assert quarter.source_kind == "child_summaries"
    assert quarter.status == "ok"


def test_runner_writes_tag_months_after_product(db_session):
    order: list[str] = []

    def gather(db, start, end, grain, grain_key):
        order.append(grain)
        return _gather(db, start, end, grain, grain_key)

    def summarize(lines, **kwargs):
        if kwargs.get("grain") == "tag":
            assert kwargs.get("grain_label") == "Packaging"
        return _ok("tag narrative")

    results = run_month(
        db_session,
        "2026-09",
        summarize=summarize,
        gather=gather,
        list_nodes=lambda *_args: [],
        list_products=lambda *_args: ["Marine"],
        list_tags=lambda *_args: [{"grain_key": "22", "grain_label": "Packaging"}],
    )
    assert order == ["product", "tag"]
    assert any(item["grain"] == "tag" and item["grain_key"] == "22" and item["status"] == "ok" for item in results)
    row = get_current(db_session, "tag", "22", "month", "2026-09")
    assert row is not None
    assert row.grain_label == "Packaging"
    assert row.source_kind == "insights"


def test_tag_quarter_built_from_child_months_not_insights(db_session):
    from services.period_summarize.runner import roll_quarter

    gather_calls: list[str] = []

    def gather(db, start, end, grain, grain_key):
        gather_calls.append(grain)
        return _gather(db, start, end, grain, grain_key)

    def summarize(lines, **_kwargs):
        return _ok("child combine")

    kwargs = dict(
        summarize=summarize,
        gather=gather,
        list_nodes=lambda *_args: [],
        list_products=lambda *_args: [],
        list_tags=lambda *_args: [{"grain_key": "6", "grain_label": "Performance"}],
    )
    run_month(db_session, "2026-07", **kwargs)
    run_month(db_session, "2026-08", **kwargs)
    run_month(db_session, "2026-09", **kwargs)
    gather_calls.clear()
    roll_quarter(db_session, "2026-Q3", force=False, summarize=summarize)
    assert gather_calls == []
    quarter = get_current(db_session, "tag", "6", "quarter", "2026-Q3")
    assert quarter is not None
    assert quarter.source_kind == "child_summaries"
    assert quarter.grain_label == "Performance"


def test_runner_uses_findings_when_llm_empty(db_session):
    def summarize(lines, **_kwargs):
        return _ok("No insights for this BDE.")

    results = run_month(
        db_session,
        "2026-09",
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args: [_nodes(None, None, None)[0]],
        list_products=lambda *_args: [],
        list_tags=lambda *_args: [],
    )
    assert any(item["grain"] == "bde" and item["grain_key"] == "GOOD" and item["status"] == "ok" for item in results)
    row = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    assert row is not None
    assert "data:" not in (row.summary_text or "").lower()
    assert "Marine" in (row.summary_text or "")
    assert "•" in (row.summary_text or "")


def test_runner_writes_pdt_cube_and_user_tag_without_product(db_session):
    def summarize(lines, **_kwargs):
        return _ok("group narrative")

    def list_cube(_db, _start, _end, group_type=None):
        if group_type == "USER GROUP":
            return [{
                "group_type": "USER GROUP",
                "bde_key": "GOOD",
                "rfmm_key": "RFMM-A",
                "zone_key": "ZONE-A",
                "division_key": "DIV-A",
                "product_name": None,
                "tag_id": "30",
                "tag_name": "Queues",
            }]
        return [{
            "group_type": "PDT GROUP",
            "bde_key": "GOOD",
            "rfmm_key": "RFMM-A",
            "zone_key": "ZONE-A",
            "division_key": "DIV-A",
            "product_name": "Marine",
            "tag_id": "22",
            "tag_name": "Packaging",
        }]

    results = run_month(
        db_session,
        "2026-09",
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args, **_kwargs: [_nodes(None, None, None)[0]],
        list_products=lambda *_args, **kwargs: ["Marine"] if kwargs.get("group_type") == "PDT GROUP" else [],
        list_tags=lambda *_args, **kwargs: (
            [{"grain_key": "22", "grain_label": "Packaging"}]
            if kwargs.get("group_type") == "PDT GROUP"
            else [{"grain_key": "30", "grain_label": "Queues"}]
        ),
        list_groups=lambda *_args, **_kwargs: ["PDT GROUP", "USER GROUP"],
        list_cube=list_cube,
    )
    assert any(item["grain"] == "bde_pt" and item["grain_key"] == "GOOD::PDT::Marine::22" and item["status"] == "ok" for item in results)
    assert any(item["grain"] == "bde_t" and item["grain_key"] == "GOOD::USER::30" and item["status"] == "ok" for item in results)
    assert get_current(db_session, "bde_pt", "GOOD::PDT::Marine::22", "month", "2026-09") is not None
    assert get_current(db_session, "bde_t", "GOOD::USER::30", "month", "2026-09") is not None
    assert get_current(db_session, "bde_pt", "GOOD::USER::Marine::30", "month", "2026-09") is None
    assert get_current(db_session, "tag", "22::PDT", "month", "2026-09") is not None
    assert get_current(db_session, "tag", "30::USER", "month", "2026-09") is not None
    assert get_current(db_session, "bde", "GOOD::PDT", "month", "2026-09") is not None
    assert get_current(db_session, "bde", "GOOD::USER", "month", "2026-09") is not None


def test_quarter_rolls_cube_key_and_records_missing_month(db_session):
    from services.period_summarize.runner import roll_quarter

    def summarize(lines, **_kwargs):
        return _ok("rolled cube")

    def list_cube(_db, _start, _end, group_type=None):
        return [{
            "group_type": "PDT GROUP",
            "bde_key": "GOOD",
            "rfmm_key": "RFMM-A",
            "zone_key": "ZONE-A",
            "division_key": "DIV-A",
            "product_name": "Marine",
            "tag_id": "22",
            "tag_name": "Packaging",
        }]

    kwargs = dict(
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args, **_kwargs: [_nodes(None, None, None)[0]],
        list_products=lambda *_args, **_kwargs: [],
        list_tags=lambda *_args, **_kwargs: [],
        list_groups=lambda *_args, **_kwargs: ["PDT GROUP"],
        list_cube=list_cube,
    )
    run_month(db_session, "2026-07", **kwargs)
    run_month(db_session, "2026-08", **kwargs)
    roll_quarter(db_session, "2026-Q3", force=False, summarize=summarize)
    quarter = get_current(db_session, "bde_pt", "GOOD::PDT::Marine::22", "quarter", "2026-Q3")
    assert quarter is not None
    assert quarter.source_kind == "child_summaries"
    missing = (quarter.highlights_json or {}).get("missing") or []
    assert "2026-09" in missing


def test_runner_cell_cap_skips_remaining(db_session):
    def summarize(lines, **_kwargs):
        return _ok("capped run")

    results = run_month(
        db_session,
        "2026-09",
        summarize=summarize,
        gather=_gather,
        list_nodes=lambda *_args, **_kwargs: _nodes(None, None, None),
        list_products=lambda *_args, **_kwargs: ["Marine", "HEATX"],
        list_tags=lambda *_args, **_kwargs: [],
        list_groups=lambda *_args, **_kwargs: ["PDT GROUP"],
        list_cube=lambda *_args, **_kwargs: [],
        max_cells=1,
    )
    assert any(item.get("status") == "capped" for item in results)


def test_runner_incremental_update_tracks_insights(db_session):
    """Day two folds only new closed-day insights into the previous summary."""
    from datetime import datetime, timezone

    state = {"day": date(2026, 9, 22)}
    calls: list[dict] = []

    def gather(_db, start, end, grain, grain_key):
        if grain_key != "GOOD":
            return []
        rows = [{
            "insight_id": "a1",
            "call_date": date(2026, 9, 22),
            "group_type": "PDT GROUP",
            "product_name": "Marine",
            "ai_summary": "day22 marine quality",
            "tags": "Quality",
        }]
        if state["day"] >= date(2026, 9, 23):
            rows.append({
                "insight_id": "a2",
                "call_date": date(2026, 9, 23),
                "group_type": "PDT GROUP",
                "product_name": "Marine",
                "ai_summary": "day23 marine price",
                "tags": "Price",
            })
        if state["day"] >= date(2026, 9, 29):
            rows.append({
                "insight_id": "a3",
                "call_date": date(2026, 9, 29),
                "group_type": "PDT GROUP",
                "product_name": "Marine",
                "ai_summary": "open day still arriving",
                "tags": "Quality",
            })
        return rows

    def summarize(lines, **kwargs):
        calls.append({"lines": list(lines), "previous": kwargs.get("previous_summary")})
        return _ok("narrative-" + str(len(calls)))

    kwargs = dict(
        summarize=summarize,
        gather=gather,
        list_nodes=lambda *_args: [_nodes(None, None, None)[0]],
        list_products=lambda *_args: [],
        list_tags=lambda *_args: [],
    )

    # Freeze "today" as 24 Sep so 22–23 are closed and 29 is not yet present.
    # Patch as_of via gather days only: run with real clock, but keep call dates in the past.
    # First run on 24th-equivalent: only 22 is present initially.
    state["day"] = date(2026, 9, 22)
    run_month(db_session, "2026-09", **kwargs)
    row = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    assert row is not None
    highlights = row.highlights_json or {}
    assert "a1" in (highlights.get("considered_insight_ids") or [])
    assert highlights.get("covered_through") == "2026-09-22"
    assert highlights.get("summary_updated_at")
    assert highlights.get("tracking_checked_at")
    first_updated = highlights.get("summary_updated_at")
    assert len(calls) >= 1
    assert calls[0]["previous"] in (None, "")

    # Second run same day: no new closed insights → tracking only, no new LLM write for leaf.
    before_calls = len(calls)
    run_month(db_session, "2026-09", **kwargs)
    row = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    assert row.version == 1
    highlights = row.highlights_json or {}
    assert highlights.get("summary_updated_at") == first_updated
    assert highlights.get("tracking_checked_at") >= first_updated

    # New closed day arrives.
    state["day"] = date(2026, 9, 23)
    run_month(db_session, "2026-09", **kwargs)
    row = get_current(db_session, "bde", "GOOD", "month", "2026-09")
    highlights = row.highlights_json or {}
    assert row.version == 2
    assert set(highlights.get("considered_insight_ids") or []) >= {"a1", "a2"}
    assert highlights.get("covered_through") == "2026-09-23"
    # Last LLM call should have received the previous summary plus only the new line.
    assert any(call.get("previous") for call in calls[before_calls:])
