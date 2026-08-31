"""
Shared test fixtures for Pidilite API tests.

- In-memory SQLite database (no Postgres needed)
- FastAPI TestClient with dependency overrides
- GCP mock fixtures (Speech, GCS, Vertex AI, Cloud Tasks)
- STT error simulation fixtures
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID, JSONB

from db.session import Base, get_db
from db.models import Job, FileDetails, Batch, User, ProcessedFile, Feedback, FeedbackCompetitor
from core.enums import JobStatus, BatchStatus
from core.exceptions import (
    STTCredentialsError,
    STTPermissionDeniedError,
    STTBadEncodingError,
    STTMultiChannelError,
    STTQuotaExhaustedError,
    STTAudioTooLongError,
    STTUnavailableError,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SQLITE COMPATIBILITY — map Postgres-only types to SQLite equivalents
# ═══════════════════════════════════════════════════════════════════════════════

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY SQLITE DATABASE (shared single connection via StaticPool)
# ═══════════════════════════════════════════════════════════════════════════════

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # all connections share the same in-memory DB
)

# SQLite doesn't enforce FK by default — enable it
@event.listens_for(test_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def db_session():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def default_speech_v2_stt(monkeypatch):
    """Keep STT on Speech v2 unless a test explicitly flips STT_PROVIDER."""
    monkeypatch.setattr("core.config.settings.STT_PROVIDER", "speech_v2")


@pytest.fixture(autouse=True)
def disable_stuck_age_gate(monkeypatch):
    """
    Default tests expect immediate checker recovery.
    Age-gate behaviour is covered explicitly in dedicated tests.
    """
    monkeypatch.setattr(
        "core.config.settings.STUCK_JOB_RECOVERY_MINUTES", 0
    )
    monkeypatch.setattr(
        "services.api.routers.checker.settings.STUCK_JOB_RECOVERY_MINUTES", 0
    )


@pytest.fixture(autouse=True)
def client(db_session):
    """FastAPI TestClient with DB dependency override.

    Patches the production engine so the lifespan handler
    uses our in-memory SQLite instead of Postgres.
    """
    from fastapi.testclient import TestClient
    import db.session as session_mod

    # Swap the production engine with our test engine
    _orig_engine = session_mod.engine
    session_mod.engine = test_engine

    from services.api.main import app

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    session_mod.engine = _orig_engine


# ═══════════════════════════════════════════════════════════════════════════════
# SEED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def create_test_job(db_session):
    """Factory fixture to create a Job + FileDetails in the test DB."""

    def _create(
        status: JobStatus = JobStatus.PENDING,
        gcs_input_uri: str = "gs://input-bucket/audio/test.wav",
        file_name: str = "test.wav",
        batch_id: str | None = None,
        stt_operation_name: str | None = None,
        gcs_stt_output_uri: str | None = None,
        retry_count: int = 0,
    ) -> Job:
        job = Job(
            gcs_input_uri=gcs_input_uri,
            status=status,
            batch_id=batch_id,
            stt_operation_name=stt_operation_name,
            gcs_stt_output_uri=gcs_stt_output_uri,
            retry_count=retry_count,
        )
        db_session.add(job)
        db_session.flush()

        fd = FileDetails(
            job_id=job.id,
            file_name=file_name,
            mime_type="audio/wav",
            file_extension="wav",
            file_size_bytes=1024,
        )
        db_session.add(fd)
        db_session.commit()
        db_session.refresh(job)
        return job

    return _create


@pytest.fixture
def create_test_batch(db_session):
    """Factory fixture to create a Batch in the test DB."""

    def _create(
        batch_number: int = 1,
        batch_size: int = 10,
        status: BatchStatus = BatchStatus.PROCESSING,
    ) -> Batch:
        batch = Batch(
            batch_number=batch_number,
            batch_size=batch_size,
            status=status,
        )
        db_session.add(batch)
        db_session.commit()
        db_session.refresh(batch)
        return batch

    return _create


@pytest.fixture
def create_test_processed_file(db_session):
    """Factory fixture to create a ProcessedFile linked to a Job."""

    def _create(
        job_id: str,
        raw_transcript_text: str = "This is a raw transcript.",
        translated_text: str | None = "This is a translated transcript.",
        insights_raw_json: list | None = None,
    ) -> ProcessedFile:
        pf = ProcessedFile(
            job_id=job_id,
            raw_transcript_text=raw_transcript_text,
            translated_text=translated_text,
            insights_raw_json=insights_raw_json,
            gcs_transcript_uri=f"gs://output-bucket/stt-output/{job_id}/output.json",
        )
        db_session.add(pf)
        db_session.commit()
        db_session.refresh(pf)
        return pf

    return _create





# ═══════════════════════════════════════════════════════════════════════════════
# GCP MOCK FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_STT_JSON = json.dumps({
    "results": [
        {
            "alternatives": [
                {"transcript": "Hello this is a test call about Fevicol SH product."}
            ]
        },
        {
            "alternatives": [
                {"transcript": "The customer asked about pricing and delivery."}
            ]
        },
    ]
})

SAMPLE_INSIGHTS_ARRAY = [
    {
        "group_type": "PDT GROUP",
        "category_type": "Adhesives",
        "tag_ids": [],
        "summary": "Positive feedback on Fevicol SH product performance.",
        "verbatim_quote": "Fevicol SH is very good for wood work.",
        "product_name": "Fevicol SH",
        "competitors_mentioned": [],
    }
]


@pytest.fixture
def mock_speech_client():
    """Mock Speech-to-Text v2 BatchRecognize."""
    import services.shared.stt_client as stt_client

    stt_client.reset_speech_client()
    with patch("services.api.routers.stt._HAS_SPEECH", True), \
         patch("services.api.routers.stt.submit_batch_recognize") as mock_submit:
        mock_submit.return_value = (
            "projects/test/locations/asia-south1/operations/123456"
        )
        yield mock_submit
        stt_client.reset_speech_client()


@pytest.fixture
def mock_gcs_client():
    """Mock google.cloud.storage.Client for transcript download."""
    with patch("services.shared.transcript._HAS_GCS", True), \
         patch("services.shared.transcript.gcs_storage") as mock_gcs:
        mock_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = SAMPLE_STT_JSON
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs.Client.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_vertex_translate():
    with patch("services.shared.vertex_ai.translate_transcript") as mock_fn:
        mock_fn.return_value = ("This is a translated transcript.", 50)
        yield mock_fn





@pytest.fixture
def mock_vertex_insights():
    with patch("services.shared.vertex_ai.generate_insights") as mock_fn:
        mock_fn.return_value = (SAMPLE_INSIGHTS_ARRAY, 150)
        yield mock_fn


@pytest.fixture
def mock_gemini(mock_vertex_insights):
    """Alias for backward-compatible tests."""
    yield mock_vertex_insights


@pytest.fixture
def mock_cloud_tasks():
    """Mock Cloud Tasks enqueue at each router import site."""
    mock = MagicMock(return_value="projects/test/locations/asia-south1/queues/test/tasks/1")
    with patch("services.api.routers.batch.enqueue_http_task", mock), \
         patch("services.api.routers.stt.enqueue_gemini_stt_task", mock), \
         patch("services.api.routers.stt_complete.enqueue_http_task", mock), \
         patch("services.api.routers.translate.enqueue_http_task", mock), \
         patch("services.api.routers.checker.enqueue_http_task", mock):
        yield mock


# ═══════════════════════════════════════════════════════════════════════════════
# STT ERROR SIMULATION FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

def _make_stt_error_fixture(error_cls):
    """Factory: creates a fixture that makes _submit_to_stt raise the given STT error."""
    @pytest.fixture
    def _fixture():
        with patch("services.api.routers.stt._submit_to_stt") as mock_submit:
            mock_submit.side_effect = error_cls(f"Simulated {error_cls.__name__}")
            yield mock_submit
    return _fixture


mock_stt_credentials_error = _make_stt_error_fixture(STTCredentialsError)
mock_stt_permission_denied = _make_stt_error_fixture(STTPermissionDeniedError)
mock_stt_bad_encoding = _make_stt_error_fixture(STTBadEncodingError)
mock_stt_multi_channel = _make_stt_error_fixture(STTMultiChannelError)
mock_stt_quota_exhausted = _make_stt_error_fixture(STTQuotaExhaustedError)
mock_stt_audio_too_long = _make_stt_error_fixture(STTAudioTooLongError)
mock_stt_unavailable = _make_stt_error_fixture(STTUnavailableError)