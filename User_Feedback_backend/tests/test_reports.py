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


def test_audio_locator_rejects_non_admin(client: TestClient, db_session):
    from unittest.mock import patch

    from db.models import User

    user = db_session.query(User).filter(User.email == "testadmin@pidilite.com").one()
    user.role = "user"
    db_session.commit()
    with patch(
        "core.dependencies.jwt.decode",
        return_value={"role": "user", "user_id": str(user.user_id)},
    ):
        resp = client.get(
            "/api/v1/reports/audio-locator",
            params={"job_id": "11111111-1111-1111-1111-111111111111"},
        )
    assert resp.status_code == 403


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
    assert geo_tags[tag_name]["ai_summary"] is None
    assert unfiltered_tags[tag_name]["summary_status"] == "ok"


def test_report_summary_uses_cluster_zone_and_product_rollups(client: TestClient, db_session):
    import importlib.util
    from pathlib import Path

    helper_path = Path(__file__).with_name("test_report_repository.py")
    spec = importlib.util.spec_from_file_location("report_repo_test_helpers_rollups", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._seed_fact_view(db_session)
    tag_name = "Existing Product - Performance improvements"
    db_session.add(_period_row(
        id="11111111-aaaa-bbbb-cccc-dddddddddd01",
        grain="tag",
        grain_key="6",
        grain_label=tag_name,
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="All-India tag narrative.",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="11111111-aaaa-bbbb-cccc-dddddddddd02",
        grain="zone_t",
        grain_key="West::PDT::6",
        grain_label=tag_name,
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="West zone tag narrative.",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="11111111-aaaa-bbbb-cccc-dddddddddd03",
        grain="rfmm_t",
        grain_key="Mumbai::PDT::6",
        grain_label=tag_name,
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="Mumbai cluster tag narrative.",
        source_kind="insights",
    ))
    db_session.add(_period_row(
        id="11111111-aaaa-bbbb-cccc-dddddddddd04",
        grain="all_pt",
        grain_key="ALL::PDT::Marine::6",
        grain_label=f"Marine × {tag_name}",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="All-India Marine narrative.",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="11111111-aaaa-bbbb-cccc-dddddddddd05",
        grain="zone_pt",
        grain_key="West::PDT::Marine::6",
        grain_label=f"Marine × {tag_name}",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="West Marine narrative.",
        source_kind="child_summaries",
    ))
    db_session.commit()
    params = {"start_date": "2026-08-01", "end_date": "2026-08-31"}

    def narrative(**extra):
        resp = client.get("/api/v1/reports/summary", params={**params, **extra})
        assert resp.status_code == 200
        tags = {row["feedback_tag"]: row for row in resp.json()["data"]["tags"]}
        return tags[tag_name]["ai_summary"]

    assert narrative() == "All-India tag narrative."
    assert narrative(zone="West") == "West zone tag narrative."
    assert narrative(product_name="Marine") == "All-India Marine narrative."
    assert narrative(zone="West", product_name="Marine") == "West Marine narrative."
    from services.api.routers.reports import _attach_tag_ai_summaries

    clustered = _attach_tag_ai_summaries(
        db_session,
        [{"feedback_tag": tag_name}],
        "month",
        "2026-08",
        cluster="Mumbai",
    )
    assert clustered[0]["ai_summary"] == "Mumbai cluster tag narrative."
    east = client.get("/api/v1/reports/summary", params={**params, "zone": "East"})
    assert east.status_code == 200
    assert tag_name not in {row["feedback_tag"] for row in east.json()["data"]["tags"]}
    # Several zones: counts cover both, but no single stored zone narrative fits.
    multi = client.get("/api/v1/reports/summary", params={**params, "zone": ["West", "East"]})
    assert multi.status_code == 200
    multi_tags = {row["feedback_tag"]: row for row in multi.json()["data"]["tags"]}
    assert multi_tags[tag_name]["ai_summary"] is None

    def detail_total(**extra):
        resp = client.get("/api/v1/reports/details", params={**params, **extra})
        assert resp.status_code == 200
        return resp.json()["data"]["metadata"]["total_items"]

    west_total = detail_total(zone="West")
    assert west_total > 0
    assert detail_total(zone="East") == 0
    assert detail_total(zone=["West", "East"]) == west_total


def test_product_filter_uses_stored_product_tag_summary(client: TestClient, db_session):
    import importlib.util
    from pathlib import Path

    helper_path = Path(__file__).with_name("test_report_repository.py")
    spec = importlib.util.spec_from_file_location("report_repo_test_helpers_product_tag", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._seed_fact_view(db_session)
    tag_name = "Existing Product - Performance improvements"
    db_session.add(_period_row(
        id="22222222-aaaa-bbbb-cccc-dddddddddd01",
        grain="tag",
        grain_key="6",
        grain_label=tag_name,
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="All-India tag narrative.",
        source_kind="child_summaries",
    ))
    db_session.add(_period_row(
        id="22222222-aaaa-bbbb-cccc-dddddddddd02",
        grain="bde_pt",
        grain_key="BDDEL02::PDT::Marine::6",
        grain_label=f"Marine × {tag_name}",
        period_key="2026-08",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        summary_text="Marine bond did not hold.",
        source_kind="insights",
        highlights_json={"sentiment": "Negative"},
    ))
    db_session.commit()
    params = {"start_date": "2026-08-01", "end_date": "2026-08-31"}
    plain = client.get("/api/v1/reports/summary", params=params)
    product = client.get("/api/v1/reports/summary", params={**params, "product_name": "Marine"})
    other = client.get("/api/v1/reports/summary", params={**params, "product_name": "SH"})
    assert plain.status_code == 200
    assert product.status_code == 200
    assert other.status_code == 200

    def summary_for(resp):
        tags = {row["feedback_tag"]: row for row in resp.json()["data"]["tags"]}
        return tags[tag_name]

    assert summary_for(plain)["ai_summary"] == "All-India tag narrative."
    marine = summary_for(product)
    assert marine["ai_summary"] == "Marine bond did not hold."
    assert marine["sentiment"] == "Negative"
    assert summary_for(other)["ai_summary"] is None


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


def test_period_summaries_apply_division_and_product_filters(client: TestClient, db_session):
    db_session.add(_period_row(
        id="88888888-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="tag",
        grain_key="22::PDT",
        grain_label="Nationwide Tag",
        summary_text="All India tag narrative.",
        source_kind="insights",
    ))
    db_session.add(_period_row(
        id="99999999-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="div_t",
        grain_key="FV-RETAIL::PDT::22",
        grain_label="Division Tag",
        summary_text="FV-RETAIL tag narrative.",
        source_kind="insights",
    ))
    db_session.add(_period_row(
        id="aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee",
        grain="div_pt",
        grain_key="FV-RETAIL::PDT::Marine::22",
        grain_label="Marine × Division Tag",
        summary_text="FV-RETAIL Marine tag narrative.",
        source_kind="insights",
    ))
    db_session.commit()
    division = client.get(
        "/api/v1/reports/period-summaries",
        params={
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "division": "FV-RETAIL",
        },
    )
    assert division.status_code == 200
    division_labels = {row["grain_label"] for row in division.json()["data"]["tags"]}
    assert "Division Tag" in division_labels
    assert "Nationwide Tag" not in division_labels

    product = client.get(
        "/api/v1/reports/period-summaries",
        params={
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "division": "FV-RETAIL",
            "product_name": "Marine",
        },
    )
    assert product.status_code == 200
    product_labels = {row["grain_label"] for row in product.json()["data"]["tags"]}
    assert "Marine × Division Tag" in product_labels
    assert "Nationwide Tag" not in product_labels
    assert "Division Tag" not in product_labels


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


def test_compliance_counts_visited_and_recorded_sites(
    client: TestClient, create_test_job, create_test_processed_file, db_session
):
    from datetime import datetime, timezone

    from core.enums import JobStatus

    recorded = create_test_job(status=JobStatus.COMPLETED, file_name="recorded.wav")
    silent = create_test_job(status=JobStatus.PENDING, file_name="silent.wav")
    for job in (recorded, silent):
        details = job.file_details
        details.division = "FV-RETAIL"
        details.zone = "NCR"
        details.cluster = "DEL"
        details.rfmm_cluster = "RBDM-DELHI"
        details.fme_code = "BDDEL03"
        details.user_type = "BDE"
        details.call_date = datetime(2026, 7, 10, tzinfo=timezone.utc)
    db_session.commit()
    create_test_processed_file(job_id=recorded.id)

    resp = client.get(
        "/api/v1/reports/compliance",
        params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    row = items[0]
    assert row["division"] == "FV-RETAIL"
    assert row["fme_code"] == "BDDEL03"
    assert row["sites_visited"] == 2
    assert row["sites_recorded"] == 2
    assert row["conversation_rate"] == 100.0
    assert row["time_period"] == "2026-07"
