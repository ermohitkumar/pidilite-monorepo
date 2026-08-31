"""
Comprehensive tests for Dashboard + Auth endpoints.

Covers:
  - GET /api/v1/dashboard/summary
  - GET /api/v1/dashboard/batches
  - GET /api/v1/dashboard/batches/{batch_id}
  - GET /api/v1/dashboard/jobs
  - GET /api/v1/dashboard/jobs/{job_id}/insights
  - POST /api/v1/auth/login
  - POST /api/v1/auth/logout

Paths: happy, sad, edge cases, pagination, search, filtering.
"""
import json
import pytest

from core.enums import JobStatus, BatchStatus


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH — LOGIN
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthLogin:

    def test_login_success(self, client, create_test_user):
        from core.config import settings
        _orig = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            create_test_user(username="admin", email="admin@test.com",
                             password="secret123", role="admin")
            resp = client.post("/api/v1/auth/login", json={
                "email": "admin@test.com", "password": "secret123"
            })
            body = resp.json()
            assert resp.status_code == 200
            assert body["success"] is True
            assert body["data"]["user"]["username"] == "admin"
            assert body["data"]["user"]["role"] == "admin"
        finally:
            settings.ENVIRONMENT = _orig

    def test_login_wrong_password(self, client, create_test_user):
        from core.config import settings
        _orig = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            create_test_user(username="admin",
                             email="admin@test.com", password="secret123")
            resp = client.post("/api/v1/auth/login", json={
                "email": "admin@test.com", "password": "wrongpass"
            })
            body = resp.json()
            assert body["success"] is False
            assert type(
                body["error"]) is list and body["error"][0]["type"] == "authentication_error"
        finally:
            settings.ENVIRONMENT = _orig

    def test_login_nonexistent_user(self, client):
        from core.config import settings
        _orig = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            resp = client.post("/api/v1/auth/login", json={
                "email": "ghost@test.com", "password": "passwd"
            })
            body = resp.json()
            assert body["success"] is False
            assert type(
                body["error"]) is list and body["error"][0]["type"] == "authentication_error"
        finally:
            settings.ENVIRONMENT = _orig

    def test_login_inactive_user(self, client, create_test_user):
        from core.config import settings
        _orig = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            create_test_user(username="disabled", email="disabled@test.com",
                             password="passwd", is_active=False)
            resp = client.post("/api/v1/auth/login", json={
                "email": "disabled@test.com", "password": "passwd"
            })
            body = resp.json()
            assert body["success"] is False
            assert body["error"] == "AccountDisabled"
        finally:
            settings.ENVIRONMENT = _orig

    def test_login_blocked_in_production(self, client, create_test_user):
        """In production, form login must be blocked — only SSO is allowed."""
        create_test_user(username="admin", email="admin@test.com",
                         password="secret123", role="admin")
        resp = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "ValidLength12"
        })
        body = resp.json()
        assert resp.status_code == 403
        assert body["success"] is False
        assert body["error"] == "Forbidden"

    def test_login_empty_payload(self, client):
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422  # Pydantic validation error



# ═══════════════════════════════════════════════════════════════════════════════
# AUTH — LOGOUT
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthLogout:

    def test_logout_success(self, client):
        resp = client.post("/api/v1/auth/logout")
        body = resp.json()
        assert resp.status_code == 200
        assert body["success"] is True

    def test_logout_without_login(self, client):
        """Logout should succeed even if no session exists."""
        resp = client.post("/api/v1/auth/logout")
        assert resp.json()["success"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD SUMMARY — KPI Cards
# ═══════════════════════════════════════════════════════════════════════════════

class TestDashboardSummary:

    def test_summary_empty_db(self, client):
        resp = client.get("/api/v1/dashboard/summary")
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["total_batches"] == 0
        assert data["active_batches"]["count"] == 0
        assert data["active_batches"]["active_jobs"] == 0
        assert data["files_processed_24h"]["count"] == 0
        assert data["files_processed_24h"]["success_rate"] == 0.0
        assert data["failed_files"]["count"] == 0

    def test_summary_with_mixed_data(
        self, client, create_test_batch, create_test_job
    ):
        b1 = create_test_batch(batch_number=1, status=BatchStatus.PROCESSING)
        b2 = create_test_batch(batch_number=2, status=BatchStatus.COMPLETED)

        # Active jobs
        create_test_job(status=JobStatus.PENDING, batch_id=b1.id,
                        gcs_input_uri="gs://b/1.wav", file_name="1.wav")
        create_test_job(status=JobStatus.PROCESSING, batch_id=b1.id,
                        gcs_input_uri="gs://b/2.wav", file_name="2.wav")
        # Completed job (recent)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b2.id,
                        gcs_input_uri="gs://b/3.wav", file_name="3.wav")
        # Failed job
        create_test_job(status=JobStatus.FAILED, batch_id=b2.id,
                        gcs_input_uri="gs://b/4.wav", file_name="4.wav")

        resp = client.get("/api/v1/dashboard/summary")
        data = resp.json()["data"]
        assert data["total_batches"] == 2
        assert data["active_batches"]["count"] == 1  # only PROCESSING
        # PENDING + PROCESSING
        assert data["active_batches"]["active_jobs"] == 2
        assert data["failed_files"]["count"] == 1

    def test_summary_success_rate_calculation(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1, status=BatchStatus.COMPLETED)
        # 3 completed + 1 failed = 75% success rate
        for i in range(3):
            create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                            gcs_input_uri=f"gs://b/c{i}.wav", file_name=f"c{i}.wav")
        create_test_job(status=JobStatus.FAILED, batch_id=b.id,
                        gcs_input_uri="gs://b/f.wav", file_name="f.wav")

        resp = client.get("/api/v1/dashboard/summary")
        data = resp.json()["data"]
        assert data["files_processed_24h"]["count"] == 3
        assert data["files_processed_24h"]["success_rate"] == 75.0


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — LIST BATCHES
# ═══════════════════════════════════════════════════════════════════════════════

class TestListBatches:

    def test_list_batches_empty(self, client):
        resp = client.get("/api/v1/dashboard/batches")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["metadata"]["total_items"] == 0

    def test_list_batches_returns_items(self, client, create_test_batch):
        create_test_batch(batch_number=1, status=BatchStatus.PROCESSING)
        create_test_batch(batch_number=2, status=BatchStatus.COMPLETED)

        resp = client.get("/api/v1/dashboard/batches")
        data = resp.json()["data"]
        assert len(data["items"]) == 2
        assert data["metadata"]["total_items"] == 2

    def test_list_batches_status_values(self, client, create_test_batch):
        create_test_batch(batch_number=1, status=BatchStatus.PROCESSING)
        resp = client.get("/api/v1/dashboard/batches")
        item = resp.json()["data"]["items"][0]
        assert item["status"] == "PROCESSING"

    def test_list_batches_job_counts(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/a.wav", file_name="a.wav")
        create_test_job(status=JobStatus.FAILED, batch_id=b.id,
                        gcs_input_uri="gs://b/b.wav", file_name="b.wav")
        create_test_job(status=JobStatus.PENDING, batch_id=b.id,
                        gcs_input_uri="gs://b/c.wav", file_name="c.wav")

        resp = client.get("/api/v1/dashboard/batches")
        item = resp.json()["data"]["items"][0]
        assert item["total_jobs"] == 3
        assert item["completed_jobs"] == 1
        assert item["failed_jobs"] == 1

    # ── Pagination ────────────────────────────────────────────────────────

    def test_list_batches_pagination(self, client, create_test_batch):
        for i in range(1, 8):
            create_test_batch(batch_number=i, status=BatchStatus.PENDING)

        # Page 1, size 3
        resp = client.get("/api/v1/dashboard/batches?page=1&size=3")
        meta = resp.json()["data"]["metadata"]
        assert len(resp.json()["data"]["items"]) == 3
        assert meta["total_items"] == 7
        assert meta["total_pages"] == 3
        assert meta["has_next"] is True
        assert meta["has_previous"] is False

        # Page 3, size 3 — should have 1 item
        resp = client.get("/api/v1/dashboard/batches?page=3&size=3")
        assert len(resp.json()["data"]["items"]) == 1
        assert resp.json()["data"]["metadata"]["has_next"] is False
        assert resp.json()["data"]["metadata"]["has_previous"] is True

    def test_list_batches_beyond_last_page(self, client, create_test_batch):
        create_test_batch(batch_number=1)
        resp = client.get("/api/v1/dashboard/batches?page=99&size=6")
        assert resp.json()["data"]["items"] == []

    # ── Search ────────────────────────────────────────────────────────────

    def test_list_batches_search_by_number(self, client, create_test_batch):
        create_test_batch(batch_number=999, status=BatchStatus.PENDING)
        create_test_batch(batch_number=22, status=BatchStatus.PENDING)

        resp = client.get("/api/v1/dashboard/batches?search=999")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["batch_number"] == 999

    def test_list_batches_search_no_results(self, client, create_test_batch):
        create_test_batch(batch_number=1)
        resp = client.get("/api/v1/dashboard/batches?search=zzz")
        assert resp.json()["data"]["items"] == []

    # ── Status Filter ─────────────────────────────────────────────────────

    def test_list_batches_filter_by_status(self, client, create_test_batch):
        create_test_batch(batch_number=1, status=BatchStatus.PROCESSING)
        create_test_batch(batch_number=2, status=BatchStatus.COMPLETED)
        create_test_batch(batch_number=3, status=BatchStatus.PENDING)

        resp = client.get("/api/v1/dashboard/batches?status=COMPLETED")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "COMPLETED"

    def test_list_batches_filter_no_match(self, client, create_test_batch):
        create_test_batch(batch_number=1, status=BatchStatus.PENDING)
        resp = client.get("/api/v1/dashboard/batches?status=FAILED")
        assert resp.json()["data"]["items"] == []

    # ── Combined Search + Filter ──────────────────────────────────────────

    def test_list_batches_search_and_filter(self, client, create_test_batch):
        create_test_batch(batch_number=5, status=BatchStatus.PROCESSING)
        create_test_batch(batch_number=5, status=BatchStatus.COMPLETED)

        resp = client.get(
            "/api/v1/dashboard/batches?search=5&status=PROCESSING")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "PROCESSING"


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — SINGLE BATCH VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class TestSingleBatchView:

    def test_get_batch_not_found(self, client):
        resp = client.get("/api/v1/dashboard/batches/nonexistent-id")
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "NotFound"

    def test_get_batch_success(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1, status=BatchStatus.PROCESSING)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/a.wav", file_name="a.wav")
        create_test_job(status=JobStatus.PENDING, batch_id=b.id,
                        gcs_input_uri="gs://b/b.wav", file_name="b.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}")
        body = resp.json()
        assert body["success"] is True
        info = body["data"]["batch_info"]
        assert info["batch_number"] == 1
        assert info["status"] == "PROCESSING"
        assert info["total_jobs"] == 2
        assert info["completed_jobs"] == 1
        assert info["failed_jobs"] == 0
        assert len(body["data"]["jobs"]["items"]) == 2

    def test_get_batch_empty_jobs(self, client, create_test_batch):
        b = create_test_batch(batch_number=1, status=BatchStatus.PENDING)
        resp = client.get(f"/api/v1/dashboard/batches/{b.id}")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["batch_info"]["total_jobs"] == 0
        assert body["data"]["jobs"]["items"] == []

    def test_get_batch_job_fields(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        job = create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                              gcs_input_uri="gs://b/x.wav", file_name="report.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}")
        item = resp.json()["data"]["jobs"]["items"][0]
        assert item["job_id"] == job.id
        assert item["file_name"] == "report.wav"
        assert item["status"] == "COMPLETED"
        assert "created_at" in item
        assert item["has_insights"] is False

    # ── Search within batch ───────────────────────────────────────────────

    def test_get_batch_search_by_filename(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(batch_id=b.id, file_name="earnings_q3.wav",
                        gcs_input_uri="gs://b/e.wav")
        create_test_job(batch_id=b.id, file_name="interview.wav",
                        gcs_input_uri="gs://b/i.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}?search=earnings")
        items = resp.json()["data"]["jobs"]["items"]
        assert len(items) == 1
        assert items[0]["file_name"] == "earnings_q3.wav"

    # ── Status filter within batch ────────────────────────────────────────

    def test_get_batch_filter_by_status(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/c.wav", file_name="c.wav")
        create_test_job(status=JobStatus.FAILED, batch_id=b.id,
                        gcs_input_uri="gs://b/f.wav", file_name="f.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}?status=FAILED")
        items = resp.json()["data"]["jobs"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "FAILED"
        # batch_info should still show unfiltered stats
        info = resp.json()["data"]["batch_info"]
        assert info["total_jobs"] == 2

    # ── Pagination within batch ───────────────────────────────────────────

    def test_get_batch_pagination(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        for i in range(5):
            create_test_job(batch_id=b.id, gcs_input_uri=f"gs://b/{i}.wav",
                            file_name=f"file_{i}.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}?page=1&size=2")
        data = resp.json()["data"]
        assert len(data["jobs"]["items"]) == 2
        assert data["jobs"]["metadata"]["total_items"] == 5
        assert data["jobs"]["metadata"]["has_next"] is True

    # ── Footer stats in metadata ──────────────────────────────────────────

    def test_get_batch_metadata_includes_stats(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/a.wav", file_name="a.wav")
        create_test_job(status=JobStatus.FAILED, batch_id=b.id,
                        gcs_input_uri="gs://b/b.wav", file_name="b.wav")

        resp = client.get(f"/api/v1/dashboard/batches/{b.id}")
        meta = resp.json()["data"]["jobs"]["metadata"]
        assert meta["completed_jobs"] == 1
        assert meta["failed_jobs"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — GLOBAL JOBS LIST (All Files)
# ═══════════════════════════════════════════════════════════════════════════════

class TestListJobs:

    def test_list_jobs_empty(self, client):
        resp = client.get("/api/v1/dashboard/jobs")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []

    def test_list_jobs_returns_items(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/a.wav", file_name="a.wav")

        resp = client.get("/api/v1/dashboard/jobs")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["file_name"] == "a.wav"
        assert items[0]["batch_id"] == b.id
        assert items[0]["batch_number"] == 1

    def test_list_jobs_without_batch(self, client, create_test_job):
        """Jobs not assigned to a batch should still appear."""
        create_test_job(status=JobStatus.PENDING,
                        gcs_input_uri="gs://b/orphan.wav", file_name="orphan.wav")

        resp = client.get("/api/v1/dashboard/jobs")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["batch_id"] is None
        assert items[0]["batch_number"] is None

    # ── Search ────────────────────────────────────────────────────────────

    def test_list_jobs_search_by_filename(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(batch_id=b.id, file_name="q3_earnings.wav",
                        gcs_input_uri="gs://b/q.wav")
        create_test_job(batch_id=b.id, file_name="interview.wav",
                        gcs_input_uri="gs://b/i.wav")

        resp = client.get("/api/v1/dashboard/jobs?search=earnings")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["file_name"] == "q3_earnings.wav"

    def test_list_jobs_search_by_batch_number(
        self, client, create_test_batch, create_test_job
    ):
        b1 = create_test_batch(batch_number=9999)
        b2 = create_test_batch(batch_number=8888)
        create_test_job(batch_id=b1.id, gcs_input_uri="gs://b/a.wav",
                        file_name="a.wav")
        create_test_job(batch_id=b2.id, gcs_input_uri="gs://b/b.wav",
                        file_name="b.wav")

        resp = client.get("/api/v1/dashboard/jobs?search=9999")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["batch_number"] == 9999

    # ── Status Filter ─────────────────────────────────────────────────────

    def test_list_jobs_filter_by_status(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                        gcs_input_uri="gs://b/c.wav", file_name="c.wav")
        create_test_job(status=JobStatus.FAILED, batch_id=b.id,
                        gcs_input_uri="gs://b/f.wav", file_name="f.wav")

        resp = client.get("/api/v1/dashboard/jobs?status=FAILED")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "FAILED"

    # ── Pagination ────────────────────────────────────────────────────────

    def test_list_jobs_pagination(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        for i in range(8):
            create_test_job(batch_id=b.id, gcs_input_uri=f"gs://b/{i}.wav",
                            file_name=f"file_{i}.wav")

        resp = client.get("/api/v1/dashboard/jobs?page=1&size=3")
        data = resp.json()["data"]
        assert len(data["items"]) == 3
        assert data["metadata"]["total_items"] == 8
        assert data["metadata"]["total_pages"] == 3
        assert data["metadata"]["has_next"] is True

    def test_list_jobs_sort_by_file_name(
        self, client, create_test_batch, create_test_job
    ):
        b = create_test_batch(batch_number=1)
        create_test_job(batch_id=b.id, gcs_input_uri="gs://b/c.wav",
                        file_name="zeta.wav")
        create_test_job(batch_id=b.id, gcs_input_uri="gs://b/a.wav",
                        file_name="alpha.wav")

        resp = client.get("/api/v1/dashboard/jobs?sort_by=file_name&sort_dir=asc")
        names = [item["file_name"] for item in resp.json()["data"]["items"]]
        assert names[:2] == ["alpha.wav", "zeta.wav"]

    def test_list_jobs_has_insights_flag(
        self, client, create_test_batch, create_test_job, create_test_job_summary
    ):
        b = create_test_batch(batch_number=1)
        job = create_test_job(status=JobStatus.COMPLETED, batch_id=b.id,
                              gcs_input_uri="gs://b/a.wav", file_name="a.wav")
        create_test_job_summary(job_id=job.id)

        resp = client.get("/api/v1/dashboard/jobs")
        items = resp.json()["data"]["items"]
        assert items[0]["has_insights"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — JOB INSIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobInsights:

    def test_insights_job_not_found(self, client):
        resp = client.get("/api/v1/dashboard/jobs/nonexistent-id/insights")
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "NotFound"

    def test_insights_not_ready(self, client, create_test_job):
        """Job exists but has no processed file or insights yet."""
        job = create_test_job(status=JobStatus.PROCESSING,
                              gcs_input_uri="gs://b/x.wav", file_name="x.wav")
        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "PROCESSING"
        assert body["data"]["feedbacks"] == []
        assert body["data"]["raw_transcript_text"] is None

    def test_insights_has_processed_but_no_insight(
        self, client, create_test_job, create_test_processed_file
    ):
        job = create_test_job(status=JobStatus.COMPLETED,
                              gcs_input_uri="gs://b/x.wav", file_name="x.wav")
        create_test_processed_file(
            job_id=job.id,
            raw_transcript_text="Speaker 1: hello",
            translated_text="Speaker 1: hello",
            empty_reason="No actionable insights extracted from transcript.",
        )
        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["raw_transcript_text"] == "Speaker 1: hello"
        assert data["translated_text"] == "Speaker 1: hello"
        assert data["feedbacks"] == []
        assert "No actionable insights" in (data["empty_reason"] or "")

    def test_insights_failed_job_returns_error(
        self, client, create_test_job, db_session
    ):
        job = create_test_job(status=JobStatus.FAILED,
                              gcs_input_uri="gs://b/bad.wav", file_name="bad.wav")
        job.error_message = "STT bad encoding"
        db_session.commit()
        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "FAILED"
        assert body["data"]["error_message"] == "STT bad encoding"

    def test_insights_success(
        self, client, create_test_job, create_test_processed_file,
        create_test_job_summary, create_test_feedback
    ):
        job = create_test_job(status=JobStatus.COMPLETED,
                              gcs_input_uri="gs://b/x.wav", file_name="report.wav")
        create_test_processed_file(
            job_id=job.id,
            normalized_text="Fevicol SH sales were strong.",
            raw_transcript_text="कैसे हो",
            translated_text="How are you",
        )
        create_test_job_summary(
            job_id=job.id, overall_sentiment_label="positive", summary_product="Strong Q3 sales")
        create_test_feedback(
            job_id=job.id, remarks="Positive comment on Fevicol SH", sentiment_label="positive")

        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["job_id"] == job.id
        assert data["file_name"] == "report.wav"
        assert data["raw_transcript_text"] == "कैसे हो"
        assert data["translated_text"] == "How are you"
        assert len(data["feedbacks"]) == 1
        assert data["feedbacks"][0]["remarks"] == "Positive comment on Fevicol SH"

    def test_insights_with_multiple_feedbacks(
        self, client, create_test_job, create_test_processed_file,
        create_test_job_summary, create_test_feedback
    ):
        """Verify that a job can return multiple feedback items associated with its summary."""
        job = create_test_job(status=JobStatus.COMPLETED,
                              gcs_input_uri="gs://b/y.wav", file_name="multi_feedback.wav")
        create_test_processed_file(
            job_id=job.id, normalized_text="Some discussion about two products.")
        create_test_job_summary(
            job_id=job.id, overall_sentiment_label="mixed", summary_product="Mentioned two products")

        create_test_feedback(
            job_id=job.id, remarks="First remark", sentiment_label="positive")
        create_test_feedback(
            job_id=job.id, remarks="Second remark", sentiment_label="negative")

        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        assert resp.json()["success"] is True

        data = resp.json()["data"]
        assert data["job_id"] == job.id
        assert len(data["feedbacks"]) == 2

        summaries = {v["remarks"] for v in data["feedbacks"]}
        assert summaries == {"First remark", "Second remark"}

    def test_insights_uses_raw_json_when_feedbacks_empty(
        self, client, create_test_job, monkeypatch
    ):
        from services.api.routers import dashboard as dash

        job = create_test_job(
            status=JobStatus.COMPLETED,
            gcs_input_uri="gs://b/x.wav",
            file_name="x.wav",
        )
        monkeypatch.setattr(dash, "_insight_feedbacks", lambda db, j: [])
        monkeypatch.setattr(
            dash,
            "_feedbacks_from_raw_json",
            lambda db, job_id: [{
                "product_name": "Fevicol SH",
                "category_name": "Quality",
                "tag_name": None,
                "group_type": "PDT GROUP",
                "verbatim_quote": "It is strong",
                "remarks": "User praised bond strength",
                "sentiment_label": None,
                "sentiment_score": None,
            }],
        )
        resp = client.get(f"/api/v1/dashboard/jobs/{job.id}/insights")
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["feedbacks"][0]["remarks"] == "User praised bond strength"

    def test_insights_accepts_postgres_generated_at(self):
        from schemas.schemas import FileInsightsData, FileInsightsResponse

        payload = FileInsightsData(
            job_id="4e590ccc-bfef-48ac-9df4-aeb417357ab8",
            file_name="Painter.mp3",
            status="COMPLETED",
            generated_at="2026-08-18 09:00:00+00",
        )
        assert payload.generated_at is not None
        wrapped = FileInsightsResponse(
            success=True,
            message="ok",
            data=payload,
            timestamp="2026-08-18T09:00:00+00:00",
            request_id="req_test",
        )
        assert wrapped.data.file_name == "Painter.mp3"


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE ENVELOPE — verify all endpoints return the standard shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestResponseEnvelope:

    @pytest.mark.parametrize("url", [
        "/api/v1/dashboard/summary",
        "/api/v1/dashboard/batches",
        "/api/v1/dashboard/jobs",
    ])
    def test_envelope_has_required_fields(self, client, url):
        resp = client.get(url)
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "timestamp" in body
        assert "request_id" in body
        assert body["request_id"].startswith("req_")
