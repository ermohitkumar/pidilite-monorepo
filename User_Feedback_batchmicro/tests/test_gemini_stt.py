"""Gemini Flash STT: dispatcher, worker retries, v2 fallback, checker sentinel."""
from unittest.mock import MagicMock, patch

from core.config import settings
from core.enums import JobStatus
from core.exceptions import STTGeminiTransientError, STTInvalidArgumentError
from services.shared.gemini_stt import (
    GEMINI_STT_MAX_OUTPUT_TOKENS,
    gemini_flash_operation_name,
    is_gemini_flash_operation,
    is_last_flash_attempt,
    transcribe_audio_gcs,
)
from services.api.routers.checker import _poll_stt_lros
from services.shared.vertex_ai import VertexRestAdapter, translate_transcript


def test_flash_operation_helpers():
    assert gemini_flash_operation_name("abc") == "gemini-flash:abc"
    assert is_gemini_flash_operation("gemini-flash:abc") is True
    assert is_gemini_flash_operation("projects/x/locations/y/operations/z") is False
    assert is_last_flash_attempt(0) is False
    assert is_last_flash_attempt(1) is False
    assert is_last_flash_attempt(2) is True


def test_gemini_stt_callback_url_derived_from_transcription_url(monkeypatch):
    monkeypatch.setattr(settings, "CLOUD_TASKS_GEMINI_STT_URL", "")
    monkeypatch.setattr(
        settings,
        "CLOUD_TASKS_CALLBACK_URL",
        "https://svc.run.app/api/v1/files/transcription",
    )
    assert settings.gemini_stt_callback_url == "https://svc.run.app/api/v1/files/gemini-stt"


def test_transcribe_audio_gcs_sends_file_data_and_thinking_off():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [{
            "content": {"parts": [{"text": "Speaker 1: Hello\nSpeaker 2: Hi\nSpeaker 3: Leak"}]},
            "finishReason": "STOP",
        }],
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = fake_json
        result = transcribe_audio_gcs("gs://bucket/a.mp3")
    assert result["provider"] == "gemini_flash"
    assert "Speaker 3:" in result["transcript"]
    payload = post.call_args.kwargs["json"]
    assert payload["contents"][0]["parts"][0]["fileData"]["fileUri"] == "gs://bucket/a.mp3"
    assert payload["contents"][0]["parts"][0]["fileData"]["mimeType"] == "audio/mpeg"
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert payload["generationConfig"]["maxOutputTokens"] == GEMINI_STT_MAX_OUTPUT_TOKENS
    assert post.call_args.kwargs["timeout"] == settings.GEMINI_STT_TIMEOUT_SECONDS
    prompt = payload["contents"][0]["parts"][1]["text"]
    assert "Never put the whole call" in prompt
    assert "Speaker 1 and Speaker 2" in prompt


def test_transcribe_splits_collapsed_single_speaker():
    creds = MagicMock()
    creds.token = "tok"
    blob = "Speaker 1: " + ("Namaste. Fevicol SH kaisa hai? Maine do drum lagaya. " * 10)
    fake_json = {
        "candidates": [{"content": {"parts": [{"text": blob}]}, "finishReason": "STOP"}],
    }
    split = "Speaker 1: Namaste. Fevicol SH kaisa hai?\nSpeaker 2: Maine do drum lagaya."
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post, patch(
        "services.shared.gemini_stt.split_collapsed_speaker_transcript",
        return_value=(split, {"input": 1, "output": 1, "total": 2}),
    ) as split_fn:
        post.return_value.status_code = 200
        post.return_value.json.return_value = fake_json
        result = transcribe_audio_gcs("gs://bucket/a.mp3")
    split_fn.assert_called_once()
    assert result["transcript"] == split


def test_transcribe_empty_is_transient():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {"candidates": [{"content": {"parts": [{"text": "   "}]}, "finishReason": "STOP"}]}
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = fake_json
        try:
            transcribe_audio_gcs("gs://bucket/a.mp3")
            assert False, "expected STTGeminiTransientError"
        except STTGeminiTransientError:
            pass


def test_transcribe_http_503_is_transient():
    creds = MagicMock()
    creds.token = "tok"
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.status_code = 503
        post.return_value.text = "unavailable"
        try:
            transcribe_audio_gcs("gs://bucket/a.mp3")
            assert False, "expected STTGeminiTransientError"
        except STTGeminiTransientError:
            pass


def test_transcribe_http_400_is_permanent():
    creds = MagicMock()
    creds.token = "tok"
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.status_code = 400
        post.return_value.text = "bad audio"
        try:
            transcribe_audio_gcs("gs://bucket/a.mp3")
            assert False, "expected STTInvalidArgumentError"
        except STTInvalidArgumentError:
            pass


def test_translate_prompt_uses_two_roles_and_speaker_n():
    creds = MagicMock()
    creds.token = "tok"
    fake_json = {
        "candidates": [{"content": {"parts": [{"text": "FME: Hi\nUser: Hello"}]}}],
        "usageMetadata": {},
    }
    with patch.object(VertexRestAdapter, "_get_credentials", return_value=creds), patch(
        "requests.post"
    ) as post:
        post.return_value.json.return_value = fake_json
        translate_transcript(
            "Speaker 1: Hi\nSpeaker 2: Hello\nSpeaker 3: Leak on site"
        )
    translate_prompt = post.call_args_list[0].kwargs["json"]["contents"][0]["parts"][0]["text"]
    relabel_prompt = post.call_args_list[1].kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "two speaker ROLES" in translate_prompt
    assert "Speaker 3+" in translate_prompt
    assert "Exactly two ROLES" in relabel_prompt
    assert "Speaker 3+" in relabel_prompt


def test_transcription_enqueues_gemini_when_flash_on(
    client, create_test_job, mock_speech_client, mock_cloud_tasks, monkeypatch
):
    monkeypatch.setattr(settings, "STT_PROVIDER", "gemini_flash")
    job = create_test_job(status=JobStatus.BATCHED)
    payload = {
        "job_id": job.id,
        "gcs_input_uri": job.gcs_input_uri,
        "gcs_output_uri_prefix": f"gs://output-bucket/stt-output/{job.id}/",
        "language_code": "hi-IN",
        "model": "telephony",
    }
    resp = client.post("/api/v1/files/transcription", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "STT_SUBMITTED"
    assert body["data"]["stt_operation_name"] == gemini_flash_operation_name(job.id)
    mock_speech_client.assert_not_called()
    mock_cloud_tasks.assert_called_once()
    payload_sent = mock_cloud_tasks.call_args.args[0]
    assert payload_sent["job_id"] == job.id
    assert payload_sent["gcs_input_uri"] == job.gcs_input_uri


def test_gemini_worker_writes_gcs_and_completes(client, create_test_job, db_session):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    db_session.commit()
    result = {
        "provider": "gemini_flash",
        "model": "gemini-2.5-flash",
        "transcript": "Speaker 1: Hi\nSpeaker 2: Hello",
        "detected_languages": [],
    }
    with patch("services.api.routers.gemini_stt.transcribe_audio_gcs", return_value=result) as mock_tx, \
         patch("services.api.routers.gemini_stt.write_gemini_transcript_json") as mock_write:
        resp = client.post(
            "/api/v1/files/gemini-stt",
            json={"job_id": job.id, "gcs_input_uri": job.gcs_input_uri},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "STT_COMPLETED"
    mock_tx.assert_called_once()
    mock_write.assert_called_once()
    db_session.refresh(job)
    assert job.status == JobStatus.STT_COMPLETED
    assert job.gcs_stt_output_uri.endswith(f"stt-output/{job.id}/output.json")


def test_gemini_worker_returns_503_on_transient(client, create_test_job, db_session):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    db_session.commit()
    with patch(
        "services.api.routers.gemini_stt.transcribe_audio_gcs",
        side_effect=STTGeminiTransientError("flash down"),
    ), patch("services.api.routers.gemini_stt._submit_to_stt") as mock_v2:
        resp = client.post(
            "/api/v1/files/gemini-stt",
            json={"job_id": job.id, "gcs_input_uri": job.gcs_input_uri},
            headers={"X-CloudTasks-TaskRetryCount": "0"},
        )
    assert resp.status_code == 503
    mock_v2.assert_not_called()
    db_session.refresh(job)
    assert job.status == JobStatus.STT_SUBMITTED


def test_gemini_worker_falls_back_to_v2_on_third_attempt(
    client, create_test_job, db_session
):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    db_session.commit()
    v2_op = "projects/test/locations/asia-south1/operations/fallback"
    with patch(
        "services.api.routers.gemini_stt.transcribe_audio_gcs",
        side_effect=STTGeminiTransientError("flash down"),
    ), patch("services.api.routers.gemini_stt._submit_to_stt", return_value=v2_op) as mock_v2:
        resp = client.post(
            "/api/v1/files/gemini-stt",
            json={
                "job_id": job.id,
                "gcs_input_uri": job.gcs_input_uri,
                "gcs_output_uri_prefix": f"gs://output-bucket/stt-output/{job.id}/",
            },
            headers={"X-CloudTasks-TaskRetryCount": "2"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["fallback"] == "speech_v2"
    assert body["data"]["stt_operation_name"] == v2_op
    mock_v2.assert_called_once()
    db_session.refresh(job)
    assert job.status == JobStatus.STT_SUBMITTED
    assert job.stt_operation_name == v2_op


def test_gemini_worker_skips_existing_speech_lro(client, create_test_job, db_session):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = "projects/test/locations/asia-south1/operations/already"
    db_session.commit()
    with patch("services.api.routers.gemini_stt.transcribe_audio_gcs") as mock_tx:
        resp = client.post(
            "/api/v1/files/gemini-stt",
            json={"job_id": job.id, "gcs_input_uri": job.gcs_input_uri},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["fallback"] == "speech_v2"
    mock_tx.assert_not_called()


def test_checker_skips_speech_poll_when_flash_blob_exists(
    db_session, create_test_job
):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    db_session.commit()
    with patch("services.api.routers.checker.get_operation") as mock_get_op, \
         patch("services.api.routers.checker.gcs_blob_exists", return_value=True) as mock_exists:
        result = _poll_stt_lros(db_session, 10)
    mock_get_op.assert_not_called()
    mock_exists.assert_called_once()
    assert result["completed"] == 1
    db_session.refresh(job)
    assert job.status == JobStatus.STT_COMPLETED


def test_checker_flash_stuck_without_blob_submits_v2(db_session, create_test_job):
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    db_session.commit()
    v2_op = "projects/test/locations/asia-south1/operations/checker-fallback"
    with patch("services.api.routers.checker.get_operation") as mock_get_op, \
         patch("services.api.routers.checker.gcs_blob_exists", return_value=False), \
         patch("services.api.routers.checker.submit_batch_recognize", return_value=v2_op) as mock_submit:
        result = _poll_stt_lros(db_session, 10)
    mock_get_op.assert_not_called()
    mock_submit.assert_called_once()
    assert result["completed"] == 0
    db_session.refresh(job)
    assert job.status == JobStatus.STT_SUBMITTED
    assert job.stt_operation_name == v2_op


def test_checker_flash_not_stuck_waits(db_session, create_test_job, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr("services.api.routers.checker.settings.STUCK_JOB_RECOVERY_MINUTES", 10)
    job = create_test_job(status=JobStatus.STT_SUBMITTED)
    job.stt_operation_name = gemini_flash_operation_name(job.id)
    job.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    with patch("services.api.routers.checker.get_operation") as mock_get_op, \
         patch("services.api.routers.checker.gcs_blob_exists", return_value=False), \
         patch("services.api.routers.checker.submit_batch_recognize") as mock_submit:
        _poll_stt_lros(db_session, 10)
    mock_get_op.assert_not_called()
    mock_submit.assert_not_called()
    db_session.refresh(job)
    assert job.status == JobStatus.STT_SUBMITTED
    assert is_gemini_flash_operation(job.stt_operation_name)
