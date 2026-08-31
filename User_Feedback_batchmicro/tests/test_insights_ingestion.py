"""
Tests for the post-processing (insights) ingestion pipeline.

Validates that the normalize router correctly:
  - Calls generate_insights with translated_text + product_catalog_tsv
  - Saves insights_raw_json on the ProcessedFile row
  - Creates Feedback rows with group_type, category_type, verbatim_quote, ai_summary
  - Links FeedbackTag records via the many-to-many junction table
  - Creates FeedbackCompetitor records when competitors are mentioned
  - Reuses existing taxonomy tags by tag_id (does not auto-create tags)
  - Marks the job as COMPLETED
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from core.enums import JobStatus
from db.models import (
    Job, ProcessedFile, Feedback, FeedbackTag,
    FeedbackCompetitor, Product,
)


# ── Sample LLM responses for different scenarios ────────────────────────────

INSIGHTS_WITH_TAGS_AND_COMPETITORS = [
    {
        "group_type": "Product",
        "category_type": "Adhesives",
        "tag_ids": [1, 2],
        "verbatim_quote": "The packets are leaking from the sides.",
        "summary": "Customer reports Fevicol SH packaging leakage and quality decline.",
        "product_name": "Fevicol SH",
        "competitors_mentioned": ["SupaStik"],
    },
    {
        "group_type": "Dealer",
        "category_type": "Credit",
        "tag_ids": [3],
        "verbatim_quote": "SupaStik is giving 45 days credit to dealers but we only get 30 days.",
        "summary": "Competitor offering longer credit terms causing dealer churn.",
        "product_name": None,
        "competitors_mentioned": ["SupaStik"],
    },
    {
        "group_type": "User",
        "category_type": "Training",
        "tag_ids": [4, 5],
        "verbatim_quote": "We need more FCC app training sessions for the contractors.",
        "summary": "Request for contractor training sessions on FCC app.",
        "product_name": None,
        "competitors_mentioned": [],
    },
]

INSIGHTS_EMPTY = []

INSIGHTS_WITH_PRODUCT_ID = [
    {
        "group_type": "Product",
        "category_type": "Tiling",
        "tags": ["Existing Product - Performance improvements"],
        "start_index": 0,
        "end_index": 55,
        "summary": "Positive feedback on Roff non-skid adhesive performance.",
        "product_id": "PRODUCT-UUID-PLACEHOLDER",  # will be replaced in test
        "competitors_mentioned": [],
    },
]


TAXONOMY_TAGS = [
    dict(tag_id=1, tag_name="Product In Pack quality / packaging / application complaints", group_type="PDT GROUP", category="Product", is_active=True),
    dict(tag_id=2, tag_name="Existing Product - Packaging improvements", group_type="PDT GROUP", category="Product", is_active=True),
    dict(tag_id=3, tag_name="Competition - Credit days", group_type="DEALER GROUP", category="Competition", is_active=True),
    dict(tag_id=4, tag_name="FCC App", group_type="USER GROUP", category="Training", is_active=True),
    dict(tag_id=5, tag_name="FCC Meet", group_type="USER GROUP", category="Training", is_active=True),
    dict(tag_id=6, tag_name="Competition product - Price / scheme", group_type="PDT GROUP", category="Competition", is_active=True),
]


def _seed_taxonomy(db_session):
    db_session.add(Product(product_name="Fevicol SH", short_code="FEV-SH", description="Adhesives"))
    for spec in TAXONOMY_TAGS:
        db_session.add(FeedbackTag(**spec))
    db_session.commit()

class TestInsightsIngestion:
    """Tests for POST /api/v1/files/post-processing DB ingestion."""

    def test_creates_feedback_with_tags_and_competitors(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """Full pipeline: 3 feedback items with tags and competitors."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_WITH_TAGS_AND_COMPETITORS, 500)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(
                job_id=job.id,
                translated_text="The packets are leaking from the sides. Earlier the quality was much better. SupaStik is giving 45 days credit to dealers but we only get 30 days. We need more FCC app training sessions for the contractors.",
            )

            resp = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["status"] == "COMPLETED"

        # ── Verify Feedback rows ──
        feedbacks = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(feedbacks) == 3

        product_fb = [f for f in feedbacks if f.group_type == "PDT GROUP"][0]
        assert product_fb.category_type == "Adhesives"
        assert "leaking" in product_fb.verbatim_quote
        assert "packaging" in product_fb.ai_summary.lower()

        dealer_fb = [f for f in feedbacks if f.group_type == "DEALER GROUP"][0]
        assert dealer_fb.category_type == "Credit"

        user_fb = [f for f in feedbacks if f.group_type == "USER GROUP"][0]
        assert user_fb.category_type == "Training"

    def test_many_to_many_tags_created(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """Existing taxonomy tags are linked via the junction table (not auto-created)."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_WITH_TAGS_AND_COMPETITORS, 500)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test transcript.")

            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        # ── Verify tags were auto-created ──
        all_tags = db_session.query(FeedbackTag).all()
        tag_names = {t.tag_name for t in all_tags}
        assert "Competition - Credit days" in tag_names
        assert "FCC App" in tag_names
        assert "FCC Meet" in tag_names
        assert "Product In Pack quality / packaging / application complaints" in tag_names

        # ── Verify many-to-many links ──
        user_fb = (
            db_session.query(Feedback)
            .filter(Feedback.job_id == job.id, Feedback.group_type == "USER GROUP")
            .first()
        )
        assert len(user_fb.tags) == 2
        user_tag_names = {t.tag_name for t in user_fb.tags}
        assert user_tag_names == {"FCC App", "FCC Meet"}

    def test_competitors_created(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """FeedbackCompetitor rows created for items with competitors_mentioned."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_WITH_TAGS_AND_COMPETITORS, 500)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test transcript.")

            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        # ── Product feedback should have 1 competitor ──
        product_fb = (
            db_session.query(Feedback)
            .filter(Feedback.job_id == job.id, Feedback.group_type == "PDT GROUP")
            .first()
        )
        competitors = list(product_fb.competitors)
        assert len(competitors) == 1
        assert competitors[0].competitor_name == "SupaStik"

        # ── User feedback should have 0 competitors ──
        user_fb = (
            db_session.query(Feedback)
            .filter(Feedback.job_id == job.id, Feedback.group_type == "USER GROUP")
            .first()
        )
        assert list(user_fb.competitors) == []

    def test_insights_raw_json_saved_on_processed_file(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """The raw LLM response is stored as an audit trail on ProcessedFile."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_WITH_TAGS_AND_COMPETITORS, 500)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test transcript.")

            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        pf = db_session.query(ProcessedFile).filter(ProcessedFile.job_id == job.id).first()
        assert pf.insights_raw_json is not None
        assert len(pf.insights_raw_json) == 3
        assert pf.insights_raw_json[0]["group_type"] == "Product"

    def test_empty_insights_marks_completed(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """An empty array from the LLM still results in COMPLETED status."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_EMPTY, 50)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="No feedback here.")

            resp = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp.status_code == 200
            body = resp.json()
            assert body["data"]["status"] == "COMPLETED"
            assert body["data"]["insights_generated"] is False

        feedbacks = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(feedbacks) == 0

        db_session.refresh(job)
        assert job.status == JobStatus.COMPLETED
        pf = db_session.query(ProcessedFile).filter(ProcessedFile.job_id == job.id).first()
        assert pf.empty_reason
        assert "No actionable insights" in pf.empty_reason

    def test_last_job_closes_parent_batch(
        self, client, db_session, create_test_batch, create_test_job, create_test_processed_file,
    ):
        """Completing the last job in a batch marks the batch COMPLETED."""
        from core.enums import BatchStatus

        batch = create_test_batch(status=BatchStatus.PROCESSING)
        create_test_job(
            status=JobStatus.COMPLETED,
            batch_id=batch.id,
            gcs_input_uri="gs://input-bucket/audio/done.wav",
            file_name="done.wav",
        )
        job = create_test_job(
            status=JobStatus.TRANSLATED,
            batch_id=batch.id,
            gcs_input_uri="gs://input-bucket/audio/last.wav",
            file_name="last.wav",
        )
        create_test_processed_file(job_id=job.id, translated_text="No feedback here.")

        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_EMPTY, 50)
            resp = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp.status_code == 200

        db_session.refresh(batch)
        assert batch.status == BatchStatus.COMPLETED

    def test_idempotent_skips_if_feedback_exists(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """Second call is idempotent — skips re-processing if feedbacks exist."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_WITH_TAGS_AND_COMPETITORS, 500)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test.")

            # First call — processes normally
            resp1 = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp1.json()["data"]["status"] == "COMPLETED"
            assert mock_insights.call_count == 1

            # Second call — should skip (feedback already exists)
            resp2 = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp2.json()["data"]["status"] == "COMPLETED"
            # generate_insights should NOT be called again
            assert mock_insights.call_count == 1

    def test_duplicate_tags_reused_not_duplicated(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """When two feedback items share the same tag, only one FeedbackTag row is created."""
        # Both Product and Dealer feedbacks mention SupaStik via "Competition - Credit days"
        # But Product also uses different tags. The shared tag should be a single DB row.
        insights_sharing_tag = [
            {
                "group_type": "Product",
                "category_type": "Pricing",
                "tag_ids": [6],
                "verbatim_quote": "Competitor has lower pricing.",
                "summary": "Competitor has lower pricing.",
                "product_name": "Fevicol SH",
                "competitors_mentioned": ["SupaStik"],
            },
            {
                "group_type": "Dealer",
                "category_type": "Pricing",
                "tag_ids": [6],
                "verbatim_quote": "Dealer churn due to competitor pricing.",
                "summary": "Dealer churn due to competitor pricing.",
                "product_name": "SupaStik",
                "competitors_mentioned": ["SupaStik"],
            },
        ]

        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (insights_sharing_tag, 300)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test.")

            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        # Only 1 tag row for "Competition product - Price / scheme"
        matching_tags = (
            db_session.query(FeedbackTag)
            .filter(FeedbackTag.tag_name == "Competition product - Price / scheme")
            .all()
        )
        assert len(matching_tags) == 1

        # But both feedbacks should reference it
        feedbacks = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        for fb in feedbacks:
            assert len(fb.tags) == 1
            assert fb.tags[0].tag_name == "Competition product - Price / scheme"

    def test_generate_insights_called_with_product_tsv(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        """Verify that generate_insights receives the product_catalog_tsv argument."""
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = (INSIGHTS_EMPTY, 50)

            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Test.")

            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

            # Verify the call args
            mock_insights.assert_called_once()
            call_kwargs = mock_insights.call_args
            tsv_arg = call_kwargs.kwargs.get("product_catalog_tsv") or call_kwargs[1].get("product_catalog_tsv")
            assert "Fevicol SH" in tsv_arg
            assert "Adhesives" in tsv_arg

    def test_skips_duplicate_insights_in_same_job(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        db_session.add(Product(product_name="Fevicol EZEESPRAY", short_code="EZEE"))
        db_session.commit()
        duplicate = {
            "group_type": "PDT GROUP",
            "category_type": "Product",
            "tag_ids": [],
            "summary": "The user finds Easy Spray to be a very good product.",
            "verbatim_quote": "That's even better, sir.",
            "product_name": "Fevicol EZEESPRAY",
            "competitors_mentioned": [],
        }
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = ([duplicate, dict(duplicate)], 100)
            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="That's even better, sir.")
            resp = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

        rows = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(rows) == 1

    def test_skips_competition_without_product_name(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        competition_tag = FeedbackTag(
            tag_id=21,
            tag_name="Competition product",
            category="Competition",
            group_type="PDT GROUP",
            is_active=True,
        )
        db_session.add(competition_tag)
        db_session.commit()
        insight = {
            "group_type": "PDT GROUP",
            "category_type": "Competition",
            "tag_ids": [21],
            "summary": "Competitor mentioned with no SKU.",
            "verbatim_quote": "Other brand is cheaper.",
            "product_name": None,
            "competitors_mentioned": [],
        }
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = ([insight], 50)
            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Other brand is cheaper.")
            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        rows = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert rows == []

    def test_keeps_competition_with_competitor_product_name(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        insight = {
            "group_type": "PDT GROUP",
            "category_type": "Competition",
            "tag_ids": [],
            "summary": "Competitor product is cheaper.",
            "verbatim_quote": "SupaStik is cheaper.",
            "product_name": None,
            "competitors_mentioned": ["SupaStik"],
        }
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = ([insight], 50)
            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="SupaStik is cheaper.")
            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        rows = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(rows) == 1
        assert rows[0].product_name is None
        assert rows[0].product_id is None
        assert list(rows[0].competitors)[0].competitor_name == "SupaStik"

    def test_keeps_competition_with_raw_competitor_product_name(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        insight = {
            "group_type": "PDT GROUP",
            "category_type": "Competition",
            "tag_ids": [],
            "summary": "Other brand dries faster.",
            "verbatim_quote": "SupaStik dries faster.",
            "product_name": "SupaStik",
            "competitors_mentioned": [],
        }
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = ([insight], 50)
            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="SupaStik dries faster.")
            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        rows = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(rows) == 1
        assert rows[0].product_name is None
        assert rows[0].product_id is None
        assert list(rows[0].competitors)[0].competitor_name == "SupaStik"

    def test_competition_century_is_competitor_not_product_name(
        self, client, db_session, create_test_job, create_test_processed_file,
    ):
        insight = {
            "group_type": "PDT GROUP",
            "category_type": "Competition",
            "tag_ids": [],
            "summary": "User compared with Century.",
            "verbatim_quote": "Century is cheaper.",
            "product_name": "Century",
            "competitors_mentioned": ["Century"],
        }
        _seed_taxonomy(db_session)
        with patch("services.shared.vertex_ai.generate_insights") as mock_insights:
            mock_insights.return_value = ([insight], 50)
            job = create_test_job(status=JobStatus.TRANSLATED)
            create_test_processed_file(job_id=job.id, translated_text="Century is cheaper.")
            client.post("/api/v1/files/post-processing", json={"job_id": job.id})

        rows = db_session.query(Feedback).filter(Feedback.job_id == job.id).all()
        assert len(rows) == 1
        assert rows[0].product_name is None
        assert {c.competitor_name for c in rows[0].competitors} == {"Century"}
