"""
Tests for all Pidilite API v1 endpoints.

Uses in-memory SQLite + GCP mocks (no real cloud calls).
"""
import json
import pytest
from unittest.mock import patch

from core.enums import JobStatus, BatchStatus
from db.models import Job, ProcessedFile, Feedback, Product


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — POST /api/v1/file
# ═══════════════════════════════════════════════════════════════════════════════

class TestIngest:
    PAYLOAD = {
        "name": "audio/meeting-20260430.wav",
        "contentType": "audio/wav",
        "size": "24567890",
        "crc32c": "AAAAAA==",
        "etag": "COu8mb3Dn+kCEAE=",
        "md5Hash": "xrX0h3SqCoeoKidv+GvlBw==",
        "timeCreated": "2026-04-30T11:18:45.123Z",
        "updated": "2026-04-30T11:18:45.123Z",
        "storageClass": "STANDARD",
        "generation": "9688325123456789",
        "metageneration": "1",
        "selfLink": "https://www.googleapis.com/storage/v1/b/input-bucket/o/audio/meeting-20260430.wav",
        "mediaLink": "https://www.googleapis.com/download/storage/v1/b/input-bucket/o/audio/meeting-20260430.wav?alt=media",
        "metadata": {},
    }

    def test_ingest_new_file(self, client):
        resp = client.post("/api/v1/file", json=self.PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["file_name"] == "meeting-20260430.wav"
        assert body["data"]["gcs_input_uri"] == "gs://input-bucket/audio/meeting-20260430.wav"
        assert body["data"]["status"] == "PENDING"
        assert body["data"]["job_id"]

    def test_ingest_duplicate(self, client):
        resp1 = client.post("/api/v1/file", json=self.PAYLOAD)
        assert resp1.status_code == 200
        job_id = resp1.json()["data"]["job_id"]

        resp2 = client.post("/api/v1/file", json=self.PAYLOAD)
        assert resp2.status_code == 200
        assert resp2.json()["data"]["job_id"] == job_id
        assert "already ingested" in resp2.json()["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — POST /api/v1/batch
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchStart:
    def test_batch_start_no_pending(self, client, mock_cloud_tasks):
        resp = client.post("/api/v1/batch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["jobs_enqueued"] == 0

    def test_batch_start_with_pending(
        self, client, create_test_job, mock_cloud_tasks
    ):
        for i in range(3):
            create_test_job(
                gcs_input_uri=f"gs://input-bucket/audio/test-{i}.wav",
                file_name=f"test-{i}.wav",
            )

        resp = client.post("/api/v1/batch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["jobs_enqueued"] == 3
        assert body["data"]["batch_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3 — POST /api/v1/files/transcription
# ═══════════════════════════════════════════════════════════════════════════════

class TestSTTSubmit:
    def test_stt_submit_success(
        self, client, create_test_job, mock_speech_client
    ):
        job = create_test_job(status=JobStatus.BATCHED)
        payload = {
            "job_id": job.id,
            "gcs_input_uri": job.gcs_input_uri,
            "gcs_output_uri_prefix": f"gs://output-bucket/stt-output/{job.id}/",
            "batch_id": "batch_001",
            "language_code": "en-IN",
            "model": "telephony",
        }
        resp = client.post("/api/v1/files/transcription", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "STT_SUBMITTED"
        assert body["data"]["stt_operation_name"] == (
            "projects/test/locations/asia-south1/operations/123456"
        )

    def test_stt_submit_uses_v2_telephony(
        self, client, create_test_job, mock_speech_client, db_session
    ):
        job = create_test_job(
            status=JobStatus.BATCHED,
            gcs_input_uri="gs://input-bucket/field/visit.webm",
            file_name="visit.webm",
        )
        job.file_details.file_extension = "webm"
        job.file_details.mime_type = "video/webm"
        db_session.commit()

        payload = {
            "job_id": job.id,
            "gcs_input_uri": job.gcs_input_uri,
            "gcs_output_uri_prefix": f"gs://output-bucket/stt-output/{job.id}/",
            "language_code": "hi-IN",
            "model": "latest_long",
        }
        resp = client.post("/api/v1/files/transcription", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_speech_client.assert_called_once()
        kwargs = mock_speech_client.call_args.kwargs
        assert kwargs["language_code"] == "hi-IN"
        assert kwargs["model"] == "latest_long"
        assert mock_speech_client.call_args.args[0] == job.gcs_input_uri

    def test_stt_submit_job_not_found(self, client, mock_speech_client):
        payload = {
            "job_id": "nonexistent-job-id",
            "gcs_input_uri": "gs://bucket/audio/fake.wav",
        }
        resp = client.post("/api/v1/files/transcription", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "not found" in body["message"].lower()
        assert body["data"]["status"] == "NOT_FOUND"

    def test_stt_submit_wrong_status(
        self, client, create_test_job, mock_speech_client
    ):
        job = create_test_job(status=JobStatus.COMPLETED)
        payload = {
            "job_id": job.id,
            "gcs_input_uri": job.gcs_input_uri,
        }
        resp = client.post("/api/v1/files/transcription", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "skipping" in body["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4a — POST /api/v1/files/stt-complete
# ═══════════════════════════════════════════════════════════════════════════════

class TestSttComplete:
    def test_stt_complete_enqueues_translate(
        self, client, db_session, create_test_job, mock_cloud_tasks
    ):
        job = create_test_job(status=JobStatus.STT_COMPLETED)
        job.gcs_stt_output_uri = f"gs://output-bucket/stt-output/{job.id}/output.json"
        db_session.commit()

        payload = {
            "name": f"stt-output/{job.id}/output.json",
            "bucket": "output-bucket",
            "contentType": "application/json",
            "selfLink": f"https://www.googleapis.com/storage/v1/b/output-bucket/o/stt-output/{job.id}/output.json",
        }
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "TRANSLATING"
        assert body["data"]["action"] == "enqueued_translate"
        mock_cloud_tasks.assert_called_once()

    def test_stt_complete_accepts_stt_submitted_race(
        self, client, db_session, create_test_job, mock_cloud_tasks
    ):
        """Eventarc often fires before checker marks STT_COMPLETED."""
        job = create_test_job(status=JobStatus.STT_SUBMITTED)
        db_session.commit()

        payload = {
            "name": f"stt-output/{job.id}/output.json",
            "bucket": "output-bucket",
            "contentType": "application/json",
        }
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["action"] == "enqueued_translate"
        assert body["data"]["previous_status"] == "STT_SUBMITTED"
        mock_cloud_tasks.assert_called_once()

    def test_stt_complete_skips_ineligible_status(
        self, client, create_test_job, mock_cloud_tasks
    ):
        job = create_test_job(status=JobStatus.PENDING)
        payload = {
            "name": f"stt-output/{job.id}/output.json",
            "bucket": "output-bucket",
        }
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["action"] == "skipped"
        assert "skip_reason" in body["data"]
        mock_cloud_tasks.assert_not_called()

    def test_stt_complete_does_not_rewind_translated(
        self, client, db_session, create_test_job, mock_cloud_tasks
    ):
        """Duplicate Eventarc must not reset TRANSLATED → TRANSLATING."""
        job = create_test_job(status=JobStatus.TRANSLATED)
        payload = {
            "name": f"stt-output/{job.id}/output.json",
            "bucket": "output-bucket",
        }
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["action"] == "skipped"
        assert body["data"]["status"] == "TRANSLATED"
        mock_cloud_tasks.assert_not_called()
        db_session.refresh(job)
        assert job.status == JobStatus.TRANSLATED

    def test_stt_complete_skips_error_when_already_translated(
        self, client, create_test_job, create_test_processed_file, mock_cloud_tasks
    ):
        job = create_test_job(status=JobStatus.ERROR)
        create_test_processed_file(job_id=job.id, translated_text="Already done.")
        payload = {
            "name": f"stt-output/{job.id}/output.json",
            "bucket": "output-bucket",
        }
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "skipped"
        mock_cloud_tasks.assert_not_called()

    def test_stt_complete_no_job_id(self, client):
        payload = {"name": "random/file.json", "contentType": "application/json"}
        resp = client.post("/api/v1/files/stt-complete", json=payload)
        assert resp.status_code == 200
        assert "could not extract" in resp.json()["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4b — POST /api/v1/files/translate
# ═══════════════════════════════════════════════════════════════════════════════

class TestTranslate:
    def test_translate_success(
        self, client, db_session, create_test_job,
        mock_gcs_client, mock_vertex_translate, mock_cloud_tasks,
    ):
        job = create_test_job(status=JobStatus.TRANSLATING)
        gcs_uri = f"gs://output-bucket/stt-output/{job.id}/output.json"
        payload = {"job_id": job.id, "gcs_transcript_uri": gcs_uri}
        resp = client.post("/api/v1/files/translate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "TRANSLATED"
        mock_cloud_tasks.assert_called_once()

        pf = db_session.query(ProcessedFile).filter(ProcessedFile.job_id == job.id).first()
        assert pf.translated_text == "This is a translated transcript."

    def test_translate_idempotent(
        self, client, create_test_job, create_test_processed_file, mock_cloud_tasks,
    ):
        job = create_test_job(status=JobStatus.TRANSLATING)
        create_test_processed_file(job_id=job.id, translated_text="Already translated.")
        gcs_uri = f"gs://output-bucket/stt-output/{job.id}/output.json"
        resp = client.post(
            "/api/v1/files/translate",
            json={"job_id": job.id, "gcs_transcript_uri": gcs_uri},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "TRANSLATED"
        mock_cloud_tasks.assert_called_once()

    def test_translate_idempotent_enqueue_failure(
        self, client, db_session, create_test_job, create_test_processed_file, mock_cloud_tasks,
    ):
        mock_cloud_tasks.return_value = None
        job = create_test_job(status=JobStatus.TRANSLATING)
        create_test_processed_file(job_id=job.id, translated_text="Already translated.")
        gcs_uri = f"gs://output-bucket/stt-output/{job.id}/output.json"
        resp = client.post(
            "/api/v1/files/translate",
            json={"job_id": job.id, "gcs_transcript_uri": gcs_uri},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["data"]["action"] == "enqueue_failed"
        db_session.refresh(job)
        assert job.status == JobStatus.ERROR


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4c — POST /api/v1/files/post-processing
# ═══════════════════════════════════════════════════════════════════════════════

class TestNormalizeInsights:
    def test_normalize_insights_success(
        self, client, db_session, create_test_job, create_test_processed_file,
        mock_vertex_insights,
    ):
        db_session.add(Product(product_name="Fevicol SH", short_code="FEV-SH", is_active=True))
        db_session.commit()
        job = create_test_job(status=JobStatus.TRANSLATED)
        create_test_processed_file(
            job_id=job.id,
            translated_text="Translated sales call about Fevicol SH.",
        )

        resp = client.post(
            "/api/v1/files/post-processing",
            json={"job_id": job.id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "COMPLETED"
        assert body["data"]["insights_generated"] is True

        feedback = db_session.query(Feedback).filter(Feedback.job_id == job.id).first()
        assert feedback is not None
        finished = db_session.query(Job).filter(Job.id == job.id).first()
        assert finished.status == JobStatus.COMPLETED

    def test_post_processing_no_translated_text(self, client, create_test_job):
        job = create_test_job(status=JobStatus.TRANSLATED)
        resp = client.post("/api/v1/files/post-processing", json={"job_id": job.id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "translated_text" in body["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 5 — POST /api/v1/checker/run
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckerRun:
    def test_checker_run_empty(self, client):
        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["jobs_checked"] == 0
        assert body["data"]["jobs_recovered"] == 0
        assert body["data"]["jobs_marked_failed"] == 0
        assert body["data"]["jobs_still_pending"] == 0

    def test_checker_recovers_errors_to_pending(
        self, client, create_test_job
    ):
        create_test_job(
            status=JobStatus.ERROR,
            retry_count=0,
            gcs_input_uri="gs://input-bucket/audio/recoverable.wav",
            file_name="recoverable.wav",
        )
        create_test_job(
            status=JobStatus.ERROR,
            retry_count=3,
            gcs_input_uri="gs://input-bucket/audio/exhausted.wav",
            file_name="exhausted.wav",
        )

        resp = client.post("/api/v1/checker/run", json={"max_jobs_to_check": 50})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["jobs_recovered"] == 1
        assert body["data"]["jobs_marked_failed"] == 1

    def test_checker_retries_post_stt_translation(
        self, client, db_session, create_test_job, mock_cloud_tasks
    ):
        job = create_test_job(status=JobStatus.ERROR, retry_count=0)
        job.gcs_stt_output_uri = f"gs://output-bucket/stt-output/{job.id}/output.json"
        db_session.commit()

        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["jobs_recovered"] >= 1
        mock_cloud_tasks.assert_called()

    def test_checker_reconciles_batches(
        self, client, db_session, create_test_batch, create_test_job
    ):
        batch = create_test_batch(status=BatchStatus.PROCESSING)

        for i in range(2):
            create_test_job(
                status=JobStatus.COMPLETED,
                batch_id=batch.id,
                gcs_input_uri=f"gs://input-bucket/audio/done-{i}.wav",
                file_name=f"done-{i}.wav",
            )

        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        assert resp.json()["data"]["batches_reconciled"] == 1
        db_session.refresh(batch)
        assert batch.status == BatchStatus.COMPLETED

    def test_checker_partial_success_when_error_remains(
        self, client, db_session, create_test_batch, create_test_job
    ):
        batch = create_test_batch(status=BatchStatus.PROCESSING)
        create_test_job(
            status=JobStatus.COMPLETED,
            batch_id=batch.id,
            gcs_input_uri="gs://input-bucket/audio/ok.wav",
            file_name="ok.wav",
        )
        create_test_job(
            status=JobStatus.ERROR,
            retry_count=3,
            batch_id=batch.id,
            gcs_input_uri="gs://input-bucket/audio/bad.wav",
            file_name="bad.wav",
        )

        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        db_session.refresh(batch)
        assert batch.status == BatchStatus.PARTIAL_SUCCESS

    def test_checker_fails_batch_when_every_job_errored(
        self, client, db_session, create_test_batch, create_test_job
    ):
        batch = create_test_batch(status=BatchStatus.PROCESSING)
        for i in range(2):
            create_test_job(
                status=JobStatus.ERROR,
                retry_count=3,
                batch_id=batch.id,
                gcs_input_uri=f"gs://input-bucket/audio/bad-{i}.wav",
                file_name=f"bad-{i}.wav",
            )

        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        db_session.refresh(batch)
        assert batch.status == BatchStatus.FAILED

    def test_checker_recovers_stuck_batched(
        self, client, create_test_job, mock_cloud_tasks
    ):
        create_test_job(status=JobStatus.BATCHED, stt_operation_name=None)
        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["stuck_batched_recovered"] == 1
        mock_cloud_tasks.assert_called()

    def test_checker_recovers_stuck_translated(
        self, client, create_test_job, create_test_processed_file, mock_cloud_tasks
    ):
        job = create_test_job(status=JobStatus.TRANSLATED)
        create_test_processed_file(job_id=job.id, translated_text="Ready for insights.")
        resp = client.post("/api/v1/checker/run", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["stuck_translated_recovered"] == 1
        mock_cloud_tasks.assert_called()

    def test_checker_age_gate_prevents_enqueue_loop(
        self, client, db_session, create_test_job, mock_cloud_tasks, monkeypatch
    ):
        """Fresh BATCHED job must not be re-enqueued every checker tick."""
        from datetime import datetime, timezone

        monkeypatch.setattr(
            "services.api.routers.checker.settings.STUCK_JOB_RECOVERY_MINUTES", 10
        )
        job = create_test_job(status=JobStatus.BATCHED, stt_operation_name=None)
        job.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        resp1 = client.post("/api/v1/checker/run", json={})
        assert resp1.json()["data"]["stuck_batched_recovered"] == 0
        mock_cloud_tasks.assert_not_called()

        # Second tick still no-ops while within the age window
        resp2 = client.post("/api/v1/checker/run", json={})
        assert resp2.json()["data"]["stuck_batched_recovered"] == 0
        mock_cloud_tasks.assert_not_called()


def test_as_utc_datetime_parses_iso_strings():
    from services.api.routers.checker import _as_utc_datetime

    ts = _as_utc_datetime("2026-08-18T15:01:42.930304Z")
    assert ts is not None
    assert ts.tzinfo is not None
    assert _as_utc_datetime(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# STT ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════════

class TestSTTErrorHandling:
    def _make_payload(self, job):
        return {
            "job_id": job.id,
            "gcs_input_uri": job.gcs_input_uri,
        }

    def test_stt_credentials_error(
        self, client, create_test_job, db_session, mock_stt_credentials_error
    ):
        job = create_test_job(status=JobStatus.BATCHED)
        resp = client.post("/api/v1/files/transcription", json=self._make_payload(job))
        body = resp.json()
        assert body["success"] is False
        assert body["data"]["status"] == "FAILED"
        db_session.refresh(job)
        assert job.status == JobStatus.FAILED

    def test_stt_quota_exhausted(
        self, client, create_test_job, db_session, mock_stt_quota_exhausted
    ):
        job = create_test_job(status=JobStatus.BATCHED)
        resp = client.post("/api/v1/files/transcription", json=self._make_payload(job))
        body = resp.json()
        assert body["success"] is False
        assert body["data"]["status"] == "ERROR"
        db_session.refresh(job)
        assert job.status == JobStatus.ERROR
        assert job.retry_count == 1
