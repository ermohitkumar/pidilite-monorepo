from fastapi.testclient import TestClient


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
