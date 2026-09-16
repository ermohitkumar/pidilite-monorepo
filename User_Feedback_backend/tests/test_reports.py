from datetime import date

from fastapi.testclient import TestClient

from db.models import PeriodSummary


def test_feedback_fact_missing_view_returns_empty(client: TestClient):
    resp = client.get("/api/v1/reports/feedback-fact")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["items"] == []
    assert body["data"]["source"] == "unavailable"
    assert "filter_options" in body["data"]


def test_audio_locator_returns_private_gcs_uri(client: TestClient, create_test_job):
    job = create_test_job(
        gcs_input_uri="gs://pidilite-raw-audio/test01/call.mp3",
        file_name="call.mp3",
    )
    resp = client.get("/api/v1/reports/audio-locator", params={"job_id": job.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["job_id"] == job.id
    assert body["data"]["gcs_uri"] == "gs://pidilite-raw-audio/test01/call.mp3"
    assert body["data"]["content_type"] == "audio/mpeg"
    assert body["data"]["file_name"] == "call.mp3"


def test_audio_locator_rejects_unknown_job(client: TestClient):
    resp = client.get(
        "/api/v1/reports/audio-locator",
        params={"job_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert resp.status_code == 404


def test_audio_locator_rejects_bucket_outside_allowlist(client: TestClient, create_test_job):
    job = create_test_job(gcs_input_uri="gs://someone-else-bucket/secret.mp3")
    resp = client.get("/api/v1/reports/audio-locator", params={"job_id": job.id})
    assert resp.status_code == 403


def test_report_filter_options_without_fact_view(client: TestClient):
    resp = client.get("/api/v1/reports/filter-options")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "divisions" in body["data"]
    assert "products" in body["data"]
    assert "fme_codes" in body["data"]


def test_report_summary_missing_view_returns_empty(client: TestClient):
    resp = client.get("/api/v1/reports/summary", params={"feedback_group": "PDT GROUP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["source"] == "unavailable"
    assert body["data"]["tags"] == []
    assert body["data"]["total"] == 0


def test_report_products_missing_view_returns_empty(client: TestClient):
    resp = client.get("/api/v1/reports/products", params={"feedback_group": "PDT GROUP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["source"] == "unavailable"
    assert body["data"]["items"] == []


def test_report_details_missing_view_returns_empty(client: TestClient):
    resp = client.get("/api/v1/reports/details", params={"feedback_group": "PDT GROUP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["source"] == "unavailable"
    assert body["data"]["items"] == []
    assert body["data"]["metadata"]["total_items"] == 0


def test_report_conversation_missing_view_returns_404(client: TestClient):
    resp = client.get(
        "/api/v1/reports/conversation",
        params={"feedback_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert resp.status_code == 404


def _period_row(**overrides):
    payload = dict(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="division",
        grain_key="FV-RETAIL",
        grain_label="FV-RETAIL",
        parent_key=None,
        period_type="month",
        period_key="2026-09",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        summary_text="Division saw Marine quality mentions.",
        highlights_json={"themes": ["quality"], "products": ["Marine"], "source_hash": "abc"},
        source_kind="child_summaries",
        source_count=2,
        call_count=4,
        insight_count=6,
        status="ok",
        version=1,
        is_current=True,
        model_name="gemini-2.5-flash",
        prompt_tokens=10,
        output_tokens=8,
    )
    payload.update(overrides)
    return PeriodSummary(**payload)


def test_period_summary_get_current_and_previous(client: TestClient, db_session):
    db_session.add(_period_row())
    db_session.add(_period_row(
        id="bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="August was quieter.",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summary",
        params={
            "division": "FV-RETAIL",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "include_previous": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["period_key"] == "2026-09"
    assert data["grain"] == "division"
    assert data["current"]["summary_text"].startswith("Division saw")
    assert data["previous"]["period_key"] == "2026-08"


def test_period_summaries_lists_divisions(client: TestClient, db_session):
    db_session.add(_period_row())
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summaries",
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["grain"] == "division"
    assert data["items"][0]["grain_key"] == "FV-RETAIL"
    assert data["tags"] == []


def test_period_summaries_run_mocked(client: TestClient, monkeypatch):
    from services.api.routers import reports as reports_mod

    monkeypatch.setattr(
        reports_mod,
        "run_period_summaries",
        lambda *args, **kwargs: {"nodes": 2, "skipped": 1, "errors": 0, "closed_periods": [], "results": []},
    )
    resp = client.post(
        "/api/v1/reports/period-summaries/run",
        json={"period_type": "month", "period_key": "2026-09"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["nodes"] == 2


def test_period_summary_returns_tag_when_selected(client: TestClient, db_session):
    db_session.add(_period_row(
        id="cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product - Performance improvements",
        summary_text="Nationwide performance complaints on grab and open time.",
        source_kind="insights",
    ))
    db_session.add(_period_row(
        id="dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product - Performance improvements",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="August performance mentions were lighter.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summary",
        params={
            "feedback_tag": "Existing Product - Performance improvements",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "include_previous": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tag"]["grain"] == "tag"
    assert data["tag"]["summary_text"].startswith("Nationwide performance")
    assert data["previous_tag"]["period_key"] == "2026-08"


def test_report_summary_attaches_nationwide_tag_narrative(client: TestClient, db_session):
    import importlib.util
    from pathlib import Path

    helper_path = Path(__file__).with_name("test_report_repository.py")
    spec = importlib.util.spec_from_file_location("report_repo_test_helpers", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._seed_fact_view(db_session)
    db_session.add(_period_row(
        id="eeeeeeee-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product - Performance improvements",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="All-India performance narrative for August.",
        source_kind="insights",
    ))
    db_session.commit()
    params = {
        "feedback_group": "PDT GROUP",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
    }
    unfiltered = client.get("/api/v1/reports/summary", params=params)
    geo = client.get("/api/v1/reports/summary", params={**params, "division": "Fevicol"})
    assert unfiltered.status_code == 200
    assert geo.status_code == 200
    unfiltered_tags = {
        row["feedback_tag"]: row for row in unfiltered.json()["data"]["tags"]
    }
    geo_tags = {row["feedback_tag"]: row for row in geo.json()["data"]["tags"]}
    tag_name = "Existing Product - Performance improvements"
    assert unfiltered_tags[tag_name]["ai_summary"] == "All-India performance narrative for August."
    assert geo_tags[tag_name]["ai_summary"] == unfiltered_tags[tag_name]["ai_summary"]
    assert unfiltered_tags[tag_name]["summary_status"] == "ok"


def test_period_summaries_includes_nationwide_tags(client: TestClient, db_session):
    db_session.add(_period_row())
    db_session.add(_period_row(
        id="ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product – Performance improvements",
        summary_text="Nationwide performance narrative.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summaries",
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"][0]["grain"] == "division"
    assert data["tags"][0]["grain_key"] == "6"
    assert data["tags"][0]["summary_text"].startswith("Nationwide performance")


def test_period_summary_matches_tag_dash_variants(client: TestClient, db_session):
    db_session.add(_period_row(
        id="aaaaaaaa-cccc-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product – Performance improvements",
        summary_text="Matched despite en-dash in stored label.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summary",
        params={
            "feedback_tag": "Existing Product - Performance improvements",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "include_previous": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["tag"]["summary_text"].startswith("Matched despite")


def test_report_summary_matches_tag_dash_variants(client: TestClient, db_session):
    import importlib.util
    from pathlib import Path

    helper_path = Path(__file__).with_name("test_report_repository.py")
    spec = importlib.util.spec_from_file_location("report_repo_test_helpers", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._seed_fact_view(db_session)
    db_session.add(_period_row(
        id="bbbbbbbb-cccc-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product – Performance improvements",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="Attached despite en-dash in stored label.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/summary",
        params={
            "feedback_group": "PDT GROUP",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200
    tags = {row["feedback_tag"]: row for row in resp.json()["data"]["tags"]}
    assert tags["Existing Product - Performance improvements"]["ai_summary"] == (
        "Attached despite en-dash in stored label."
    )


def test_report_summary_falls_back_to_latest_tag_period(client: TestClient, db_session):
    import importlib.util
    from pathlib import Path

    helper_path = Path(__file__).with_name("test_report_repository.py")
    spec = importlib.util.spec_from_file_location("report_repo_test_helpers", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._seed_fact_view(db_session)
    db_session.add(_period_row(
        id="cccccccc-cccc-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="6",
        grain_label="Existing Product - Performance improvements",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="Latest stored month used when requested month is empty.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/summary",
        params={"feedback_group": "PDT GROUP"},
    )
    assert resp.status_code == 200
    tags = {row["feedback_tag"]: row for row in resp.json()["data"]["tags"]}
    assert tags["Existing Product - Performance improvements"]["ai_summary"] == (
        "Latest stored month used when requested month is empty."
    )


def test_period_summaries_hides_empty_and_lists_available_filters(client: TestClient, db_session):
    db_session.add(_period_row())
    db_session.add(_period_row(
        id="11111111-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="bde",
        grain_key="EMPTY",
        grain_label="EMPTY",
        summary_text="No insights for this BDE.",
        source_kind="insights",
        insight_count=0,
    ))
    db_session.add(_period_row(
        id="22222222-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="bde",
        grain_key="BDDEL03",
        grain_label="BDDEL03",
        parent_key="RBDM-DELHI",
        summary_text="BDE saw leakage complaints.",
        source_kind="insights",
        insight_count=3,
    ))
    db_session.add(_period_row(
        id="33333333-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="rfmm",
        grain_key="RBDM-DELHI",
        grain_label="RBDM-DELHI",
        summary_text="",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="44444444-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="zone",
        grain_key="NCR",
        grain_label="NCR",
        summary_text="Zone quality mentions stayed high.",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="55555555-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="product",
        grain_key="Marine",
        grain_label="Marine",
        summary_text="Marine quality mentions.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summaries",
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {item["grain_key"] for item in data["items"]} == {"FV-RETAIL"}
    assert data["available_filters"]["divisions"] == ["FV-RETAIL"]
    assert data["available_filters"]["zones"] == ["NCR"]
    assert "RBDM-DELHI" not in data["available_filters"]["rfmm_clusters"]
    assert data["available_filters"]["fme_codes"] == ["BDDEL03"]
    assert "EMPTY" not in data["available_filters"]["fme_codes"]
    assert data["available_filters"]["products"] == ["Marine"]
    assert data["products"][0]["grain_key"] == "Marine"


def test_period_summaries_filters_products_by_feedback_group(client: TestClient, db_session):
    db_session.add(_period_row(
        id="66666666-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="product",
        grain_key="Marine::PDT",
        grain_label="Marine",
        summary_text="PDT Marine quality mentions.",
        source_kind="insights",
    ))
    db_session.add(_period_row(
        id="77777777-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="product",
        grain_key="Marine::USER",
        grain_label="Marine",
        summary_text="Should not appear for PDT.",
        source_kind="insights",
        status="ok",
    ))
    db_session.commit()
    pdt = client.get(
        "/api/v1/reports/period-summaries",
        params={"start_date": "2026-09-01", "end_date": "2026-09-30", "feedback_group": "PDT GROUP"},
    )
    user = client.get(
        "/api/v1/reports/period-summaries",
        params={"start_date": "2026-09-01", "end_date": "2026-09-30", "feedback_group": "USER GROUP"},
    )
    assert pdt.status_code == 200
    assert user.status_code == 200
    pdt_keys = {item["grain_key"] for item in pdt.json()["data"]["products"]}
    user_keys = {item["grain_key"] for item in user.json()["data"]["products"]}
    assert pdt_keys == {"Marine::PDT"}
    assert user_keys == {"Marine::USER"}
    assert "Marine::PDT" not in user_keys


def test_period_summary_hides_no_insight_text(client: TestClient, db_session):
    db_session.add(_period_row(
        grain="bde",
        grain_key="EMPTY",
        grain_label="EMPTY",
        summary_text="No insights available.",
        source_kind="insights",
    ))
    db_session.commit()
    resp = client.get(
        "/api/v1/reports/period-summary",
        params={
            "fme_code": "EMPTY",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "include_previous": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["current"] is None
