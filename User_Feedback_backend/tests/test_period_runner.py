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


def test_runner_skips_empty_llm_output(db_session):
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
    assert any(item["status"] == "empty" and item.get("skipped") for item in results)
    assert get_current(db_session, "bde", "GOOD", "month", "2026-09") is None
    assert get_current(db_session, "rfmm", "RFMM-A", "month", "2026-09") is None


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
