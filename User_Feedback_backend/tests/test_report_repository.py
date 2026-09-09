import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from db.models import Product
from repositories.report_repository import (
    DETAIL_SEARCH,
    DIM_SEARCH,
    NO_PRODUCT_LABEL,
    build_filters,
    conversation,
    detail_page,
    fact_table,
    filter_options,
    product_counts,
    summary_counts,
)


def _reset_fact_view(db_session):
    db_session.execute(text("DROP VIEW IF EXISTS vw_pbi_feedback_fact"))
    db_session.execute(text("DROP VIEW IF EXISTS vw_pbi_feedback_fact_slim"))
    db_session.execute(text("DROP VIEW IF EXISTS vw_filter_options"))
    db_session.execute(text("DROP TABLE IF EXISTS _report_fact"))
    db_session.commit()


def _seed_fact_view(db_session):
    _reset_fact_view(db_session)
    db_session.execute(text("""
        CREATE TABLE _report_fact (
            feedback_id TEXT,
            job_id TEXT,
            feedback_created_at TEXT,
            feedback_group TEXT,
            feedback_category TEXT,
            feedback_tag TEXT,
            feedback_sub_tag TEXT,
            product_name TEXT,
            product_id INTEGER,
            product_short_code TEXT,
            feedback_summary_ai TEXT,
            feedback_excerpt TEXT,
            file_name TEXT,
            call_date TEXT,
            division TEXT,
            zone TEXT,
            cluster TEXT,
            state TEXT,
            data_source TEXT,
            fme_code TEXT,
            user_type TEXT,
            full_conversation TEXT,
            full_conversation_raw TEXT
        )
    """))
    db_session.execute(text(
        "CREATE VIEW vw_pbi_feedback_fact_slim AS SELECT * FROM _report_fact"
    ))
    db_session.execute(text(
        "CREATE VIEW vw_pbi_feedback_fact AS SELECT * FROM _report_fact"
    ))
    db_session.execute(text("""
        INSERT INTO _report_fact VALUES
        (
            'fb-aaaa-1111', 'job-1', '2026-08-01T10:00:00',
            'PDT GROUP', 'Product', 'Existing Product - Performance improvements',
            NULL, 'Marine', NULL, 'MAR', 'Grab is good in monsoon.', 'Grab jaldi ho jata hai.',
            'call.mp3', '2026-08-01', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'FME: Hello\nUser: Grab is good.', 'raw one'
        ),
        (
            'fb-bbbb-2222', 'job-2', '2026-08-02T11:00:00',
            'PDT GROUP', 'Product', 'Existing Product - Performance improvements',
            NULL, 'SH', NULL, 'SH', 'Open time is short.', 'Open time kam hai.',
            'sh.mp3', '2026-08-02', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Contractor', 'FME: How is SH?\nUser: Open time kam.', 'raw two'
        ),
        (
            'fb-cccc-3333', 'job-3', '2026-08-03T09:00:00',
            'USER GROUP', 'User Meets', 'User meet - long queues',
            NULL, NULL, NULL, NULL, 'Queue was long.', 'Line lambi thi.',
            'meet.mp3', '2026-08-03', 'Fevicol', 'West', 'Pune', 'Maharashtra',
            'M-Power', 'FME002', 'Dealer', 'FME: Meet kaisa tha?\nUser: Line lambi.', 'raw three'
        )
    """))
    db_session.commit()


@pytest.fixture
def fact_view(db_session):
    _seed_fact_view(db_session)
    yield db_session
    _reset_fact_view(db_session)


def test_build_filters_tag_matches_sub_tag():
    where_sql, params = build_filters(feedback_group="PDT GROUP", feedback_tag="Marine")
    assert "feedback_group = :feedback_group" in where_sql
    assert "LOWER(TRIM(feedback_tag)) = LOWER(TRIM(:feedback_tag))" in where_sql
    assert "feedback_sub_tag" in where_sql
    assert params["feedback_group"] == "PDT GROUP"
    assert params["feedback_tag"] == "Marine"


def test_build_filters_exact_tag_and_search():
    where_sql, params = build_filters(
        feedback_tag="Marine",
        search="plywood",
        search_sql=DIM_SEARCH,
        exact_tag=True,
    )
    assert "LOWER(TRIM(feedback_tag)) = LOWER(TRIM(:feedback_tag))" in where_sql
    assert "feedback_sub_tag" not in where_sql
    assert params["search"] == "%plywood%"
    assert "ILIKE :search" in where_sql


def test_fact_table_prefers_slim(fact_view):
    assert fact_table(fact_view) == "vw_pbi_feedback_fact_slim"


def test_summary_counts_by_group(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(feedback_group="PDT GROUP")
    result = summary_counts(fact_view, fact, where_sql, params)
    assert result["total"] == 2
    tags = {row["feedback_tag"]: row["feedback_count"] for row in result["tags"]}
    assert tags["Existing Product - Performance improvements"] == 2
    categories = {row["feedback_category"]: row["feedback_count"] for row in result["categories"]}
    assert categories["Product"] == 2


def test_product_counts_skips_empty_names(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(
        feedback_group="PDT GROUP",
        feedback_tag="Existing Product - Performance improvements",
    )
    items, total = product_counts(fact_view, fact, where_sql, params)
    assert total == 2
    assert [row["product_name"] for row in items] == ["Marine", "SH"]
    assert [row["feedback_count"] for row in items] == [1, 1]


def test_product_counts_includes_user_group_without_product(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(feedback_group="USER GROUP")
    items, total = product_counts(fact_view, fact, where_sql, params)
    assert total == 1
    assert items == [{"product_name": NO_PRODUCT_LABEL, "feedback_count": 1}]

    none_where, none_params = build_filters(
        feedback_group="USER GROUP",
        product_name=NO_PRODUCT_LABEL,
    )
    none_items, none_total = product_counts(fact_view, fact, none_where, none_params)
    assert none_total == 1
    assert none_items[0]["product_name"] == NO_PRODUCT_LABEL


def test_detail_page_paginates_unique_feedback(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(feedback_group="PDT GROUP")
    items, total = detail_page(
        fact_view, fact, where_sql, params,
        page=1, page_size=1, sort_by="call_datetime", sort_dir="desc",
    )
    assert total == 2
    assert len(items) == 1
    assert items[0]["feedback_id"] == "fb-bbbb-2222"
    assert "full_conversation" not in items[0]


def test_conversation_loads_transcript(fact_view):
    item = conversation(fact_view, "fb-aaaa-1111")
    assert item["full_conversation"] == "FME: Hello\nUser: Grab is good."
    assert item["feedback_excerpt"] == "Grab jaldi ho jata hai."


def test_conversation_filters_by_job_id(fact_view):
    item = conversation(fact_view, "fb-aaaa-1111", "job-1")
    assert item["job_id"] == "job-1"
    assert item["feedback_excerpt"] == "Grab jaldi ho jata hai."
    missing = conversation(fact_view, "fb-aaaa-1111", "job-missing-99")
    assert missing is None


def test_filter_options_from_fact(fact_view):
    fact_view.add(Product(product_name="Fevicol Marine", short_code="MAR"))
    fact_view.add(Product(product_name="Fevicol SH", short_code="SH"))
    fact_view.commit()
    fact = fact_table(fact_view)
    options = filter_options(fact_view, fact)
    assert "Fevicol Marine" in options["products"]
    assert "Fevicol SH" in options["products"]
    assert "Marine" not in options["products"]
    assert "SH" not in options["products"]
    assert "Century" not in options["products"]
    assert "divisions" in options
    assert "zones" in options
    assert "FME001" in options["fme_codes"]
    assert "Dealer" in options["user_types"]
    assert "rfmm_clusters" in options


def test_filter_options_prefers_master_view(fact_view):
    fact_view.execute(text("""
        CREATE VIEW vw_filter_options AS
        SELECT 'division' AS filter_type, 'N000105' AS code,
               'FV-RETAIL-NSM' AS name, 'FV-RETAIL-NSM' AS value
        UNION ALL
        SELECT 'product', 'SH', 'Fevicol SH', 'Fevicol SH'
        UNION ALL
        SELECT 'user_type', 'IMR', 'IMR', 'IMR'
    """))
    fact_view.commit()
    fact = fact_table(fact_view)
    options = filter_options(fact_view, fact)
    assert "FV-RETAIL-NSM" in options["divisions"]
    assert "Fevicol" not in options["divisions"]
    assert "Fevicol SH" in options["products"]
    assert "IMR" in options["user_types"]
    assert "Dealer" not in options["user_types"]


def test_filter_options_cascades_from_hierarchy(fact_view):
    fact_view.execute(text("""
        CREATE VIEW vw_filter_hierarchy AS
        SELECT 'FV-RETAIL-NSM' AS division, 'West' AS zone,
               'PUNE 1' AS rfmm_cluster, 'TY07220' AS fme_code
        UNION ALL
        SELECT 'FV-RETAIL-NSM', 'East', 'AMFC-Kolkata', 'FCSCAL1'
        UNION ALL
        SELECT 'Other Div', 'East', 'Other RFMM', 'OTHER1'
    """))
    fact_view.execute(text("""
        CREATE VIEW vw_filter_options AS
        SELECT 'product' AS filter_type, 'SH' AS code,
               'Fevicol SH' AS name, 'Fevicol SH' AS value
    """))
    fact_view.commit()
    fact = fact_table(fact_view)

    all_opts = filter_options(fact_view, fact)
    assert all_opts["divisions"] == ["FV-RETAIL-NSM", "Other Div"]
    assert "West" in all_opts["zones"]
    assert "East" in all_opts["zones"]
    assert "TY07220" in all_opts["fme_codes"]
    assert "Fevicol SH" in all_opts["products"]

    west = filter_options(fact_view, fact, division="FV-RETAIL-NSM", zone="West")
    assert west["divisions"] == ["FV-RETAIL-NSM", "Other Div"]
    assert west["zones"] == ["East", "West"]
    assert west["clusters"] == ["PUNE 1"]
    assert west["rfmm_clusters"] == ["PUNE 1"]
    assert west["fme_codes"] == ["TY07220"]
    assert "FCSCAL1" not in west["fme_codes"]

    fact_view.execute(text("""
        DROP VIEW IF EXISTS vw_filter_options
    """))
    fact_view.execute(text("""
        CREATE VIEW vw_filter_options AS
        SELECT 'rfmm_cluster' AS filter_type, 'X' AS code,
               'AMFC-Kolkata' AS name, 'AMFC-Kolkata' AS value
        UNION ALL
        SELECT 'fme_code', 'Y', 'FCSCAL1', 'FCSCAL1'
        UNION ALL
        SELECT 'product', 'SH', 'Fevicol SH', 'Fevicol SH'
    """))
    fact_view.commit()
    west_only = filter_options(fact_view, fact, zone="West")
    assert west_only["rfmm_clusters"] == ["PUNE 1"]
    assert west_only["fme_codes"] == ["TY07220"]
    assert "AMFC-Kolkata" not in west_only["rfmm_clusters"]
    assert "FCSCAL1" not in west_only["fme_codes"]


def test_build_filters_cluster_matches_rfmm():
    where_sql, params = build_filters(cluster="PUNE 1")
    assert "cluster = :cluster OR rfmm_cluster = :cluster" in where_sql
    assert params["cluster"] == "PUNE 1"


def test_build_filters_product_and_fme():
    where_sql, params = build_filters(product_name="Marine", fme_code="FME001", user_type="Dealer")
    assert "product_id IN" in where_sql
    assert "short_code" in where_sql
    # Shared/empty short_code equality across products must not appear.
    assert "COALESCE(product_short_code, '')) = LOWER(TRIM(p.short_code))" not in where_sql
    assert params["product_name"] == "Marine"
    assert params["fme_code"] == "FME001"
    assert params["user_type"] == "Dealer"


def test_detail_does_not_leak_across_shared_short_codes(fact_view):
    """Count is per product_name; detail must not pull siblings that share F-M."""
    multilock = Product(product_name="Fevicol Multilock", short_code="F-M")
    marine = Product(product_name="Fevicol MARINE", short_code="F-M")
    ezee = Product(product_name="Fevicol EZEESPRAY", short_code="F-E")
    fact_view.add_all([multilock, marine, ezee])
    fact_view.flush()

    fact_view.execute(text("""
        INSERT INTO _report_fact (
            feedback_id, job_id, feedback_created_at, feedback_group, feedback_category,
            feedback_tag, feedback_sub_tag, product_name, product_id, product_short_code,
            feedback_summary_ai, feedback_excerpt, file_name, call_date,
            division, zone, cluster, state, data_source, fme_code, user_type,
            full_conversation, full_conversation_raw
        ) VALUES
        (
            'fb-multi-1', 'job-m', '2026-08-10T10:00:00',
            'PDT GROUP', 'Product', 'Product In Pack quality / packaging / application complaints',
            NULL, 'Fevicol Multilock', :mid, 'F-M',
            'Multilock pack issue.', 'Multilock pack.',
            'sample_01.mp3', '2026-08-10', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'multi convo', 'multi raw'
        ),
        (
            'fb-marine-1', 'job-r', '2026-08-10T10:01:00',
            'PDT GROUP', 'Product', 'Product In Pack quality / packaging / application complaints',
            NULL, 'Fevicol MARINE', :rid, 'F-M',
            'Marine pack issue.', 'Marine pack.',
            'sample_01.mp3', '2026-08-10', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'marine convo', 'marine raw'
        ),
        (
            'fb-ezee-1', 'job-e', '2026-08-10T10:02:00',
            'PDT GROUP', 'Product', 'Product In Pack quality / packaging / application complaints',
            NULL, 'Fevicol EZEESPRAY', :eid, 'F-E',
            'Ezee pack issue.', 'Ezee pack.',
            'sample_01.mp3', '2026-08-10', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'ezee convo', 'ezee raw'
        )
    """), {"mid": multilock.id, "rid": marine.id, "eid": ezee.id})
    fact_view.commit()

    fact = fact_table(fact_view)
    tag = "Product In Pack quality / packaging / application complaints"

    products, total = product_counts(
        fact_view, fact, *build_filters(feedback_group="PDT GROUP", feedback_tag=tag),
    )
    by_name = {row["product_name"]: row["feedback_count"] for row in products}
    assert by_name.get("Fevicol Multilock") == 1
    assert by_name.get("Fevicol MARINE") == 1
    assert by_name.get("Fevicol EZEESPRAY") == 1
    assert total >= 3

    where_sql, params = build_filters(
        feedback_group="PDT GROUP",
        feedback_tag=tag,
        product_name="Fevicol Multilock",
    )
    items, detail_total = detail_page(
        fact_view, fact, where_sql, params,
        page=1, page_size=20, sort_by="call_datetime", sort_dir="desc",
    )
    assert detail_total == 1
    assert len(items) == 1
    assert items[0]["feedback_id"] == "fb-multi-1"
    assert items[0]["product_name"] == "Fevicol Multilock"

    where_ezee, params_ezee = build_filters(
        feedback_group="PDT GROUP",
        feedback_tag=tag,
        product_name="Fevicol EZEESPRAY",
    )
    ezee_items, ezee_total = detail_page(
        fact_view, fact, where_ezee, params_ezee,
        page=1, page_size=20, sort_by="call_datetime", sort_dir="desc",
    )
    assert ezee_total == 1
    assert ezee_items[0]["feedback_id"] == "fb-ezee-1"


def test_detail_ignores_empty_shared_short_code(fact_view):
    """Empty short_code must not match every feedback row."""
    named = Product(product_name="Fevicol EZEESPRAY", short_code="")
    other = Product(product_name="Fevicol PROBOND", short_code="")
    fact_view.add_all([named, other])
    fact_view.flush()
    fact_view.execute(text("""
        INSERT INTO _report_fact (
            feedback_id, job_id, feedback_created_at, feedback_group, feedback_category,
            feedback_tag, feedback_sub_tag, product_name, product_id, product_short_code,
            feedback_summary_ai, feedback_excerpt, file_name, call_date,
            division, zone, cluster, state, data_source, fme_code, user_type,
            full_conversation, full_conversation_raw
        ) VALUES
        (
            'fb-ezee-empty', 'job-e2', '2026-08-11T10:00:00',
            'PDT GROUP', 'Product', 'Packaging',
            NULL, 'Fevicol EZEESPRAY', :eid, '',
            'Ezee only.', 'Ezee.',
            'a.mp3', '2026-08-11', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'c1', 'r1'
        ),
        (
            'fb-probond-empty', 'job-p2', '2026-08-11T10:01:00',
            'PDT GROUP', 'Product', 'Packaging',
            NULL, 'Fevicol PROBOND', :pid, '',
            'Probond only.', 'Probond.',
            'b.mp3', '2026-08-11', 'Fevicol', 'West', 'Mumbai', 'Maharashtra',
            'M-Power', 'FME001', 'Dealer', 'c2', 'r2'
        )
    """), {"eid": named.id, "pid": other.id})
    fact_view.commit()

    fact = fact_table(fact_view)
    where_sql, params = build_filters(
        feedback_group="PDT GROUP",
        feedback_tag="Packaging",
        product_name="Fevicol EZEESPRAY",
    )
    items, total = detail_page(
        fact_view, fact, where_sql, params,
        page=1, page_size=20, sort_by="call_datetime", sort_dir="desc",
    )
    assert total == 1
    assert items[0]["feedback_id"] == "fb-ezee-empty"


def test_summary_filters_by_product(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(feedback_group="PDT GROUP", product_name="Marine")
    result = summary_counts(fact_view, fact, where_sql, params)
    assert result["total"] == 1


def test_summary_filters_by_short_code(fact_view):
    fact = fact_table(fact_view)
    where_sql, params = build_filters(feedback_group="PDT GROUP", product_name="MAR")
    result = summary_counts(fact_view, fact, where_sql, params)
    assert result["total"] == 1


def test_summary_api_with_view(client: TestClient, fact_view):
    resp = client.get("/api/v1/reports/summary", params={"feedback_group": "PDT GROUP"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["source"] == "vw_pbi_feedback_fact_slim"
    assert body["data"]["total"] == 2


def test_products_api_with_view(client: TestClient, fact_view):
    fact_view.add(Product(product_name="Fevicol Marine", short_code="MAR"))
    fact_view.add(Product(product_name="Fevicol SH", short_code="SH"))
    fact_view.commit()
    resp = client.get(
        "/api/v1/reports/products",
        params={
            "feedback_group": "PDT GROUP",
            "feedback_tag": "Existing Product - Performance improvements",
        },
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert {row["product_name"] for row in items} == {"Fevicol Marine", "Fevicol SH"}


def test_details_and_conversation_api(client: TestClient, fact_view):
    details = client.get(
        "/api/v1/reports/details",
        params={"feedback_group": "PDT GROUP", "page": 1, "page_size": 20},
    )
    assert details.status_code == 200
    payload = details.json()["data"]
    assert payload["metadata"]["total_items"] == 2
    assert all(not row.get("full_conversation") for row in payload["items"])
    feedback_id = payload["items"][0]["feedback_id"]

    convo = client.get("/api/v1/reports/conversation", params={"feedback_id": feedback_id})
    assert convo.status_code == 200
    assert "FME:" in (convo.json()["data"]["full_conversation"] or "")


def test_detail_search_constant_is_broader_than_dim():
    assert "feedback_summary_ai" in DETAIL_SEARCH
    assert "feedback_excerpt" not in DETAIL_SEARCH
    assert "file_name" in DIM_SEARCH
