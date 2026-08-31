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

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID, JSONB

from db.session import Base, get_db
from db.models import Job, FileDetails, Batch, User, ProcessedFile, JobSummary, Feedback
from core.enums import JobStatus, BatchStatus
from core.security import hash_password

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


TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def db_session():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    yield session
    try:
        session.rollback()
        session.execute(text("DROP VIEW IF EXISTS vw_pbi_feedback_fact"))
        session.execute(text("DROP VIEW IF EXISTS vw_pbi_feedback_fact_slim"))
        session.execute(text("DROP TABLE IF EXISTS _report_fact"))
        session.commit()
    except Exception:
        session.rollback()
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def client(db_session):
    """FastAPI TestClient with DB dependency override.

    Patches the production engine so the lifespan handler
    uses our in-memory SQLite instead of Postgres.

    Creates a real super_admin user in the test DB so the
    RoleChecker's real-time DB lookup succeeds.
    """
    from fastapi.testclient import TestClient
    import db.session as session_mod

    # Swap the production engine with our test engine
    _orig_engine = session_mod.engine
    session_mod.engine = test_engine

    from services.api.main import app
    from core.config import settings

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    # Seed a super_admin user that the RoleChecker will find in the DB
    _TEST_ADMIN_ID = "00000000-0000-0000-0000-000000000000"
    admin_user = User(
        user_id=_TEST_ADMIN_ID,
        email="testadmin@pidilite.com",
        username="testadmin",
        password_hash=hash_password("placeholder"),
        role="super_admin",
        is_active=True,
        allowed_resources=[],
    )
    db_session.add(admin_user)
    db_session.commit()

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with patch("core.dependencies.jwt.decode", return_value={"role": "super_admin", "user_id": _TEST_ADMIN_ID}):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.cookies.set("pidilite_session_cookie", "fake-token")
            c.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": "Bearer fake-token"
            })
            yield c
    app.dependency_overrides.clear()
    session_mod.engine = _orig_engine
    settings.ENVIRONMENT = _orig_env


# ═══════════════════════════════════════════════════════════════════════════════
# SEED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def create_test_user(db_session):
    """Factory fixture to create a User in the test DB."""

    def _create(
        username: str = "testuser",
        email: str = "testuser@example.com",
        password: str = "testpass123",
        full_name: str = "Test User",
        role: str = "viewer",
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create


@pytest.fixture
def create_test_batch(db_session):
    """Factory fixture to create a Batch in the test DB."""

    def _create(
        batch_number: int = 1,
        batch_size: int = 10,
        status: BatchStatus = BatchStatus.PENDING,
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
def create_test_job(db_session):
    """Factory fixture to create a Job + FileDetails in the test DB."""

    def _create(
        gcs_input_uri: str = "gs://test-bucket/test.wav",
        file_name: str = "test.wav",
        batch_id: str | None = None,
        status: JobStatus = JobStatus.PENDING,
    ) -> Job:
        job = Job(
            gcs_input_uri=gcs_input_uri,
            batch_id=batch_id,
            status=status,
        )
        db_session.add(job)
        db_session.flush()  # get the job.id before creating FileDetails

        file_details = FileDetails(
            job_id=job.id,
            file_name=file_name,
        )
        db_session.add(file_details)
        db_session.commit()
        db_session.refresh(job)
        return job

    return _create


@pytest.fixture
def create_test_processed_file(db_session):
    """Factory fixture to create a ProcessedFile in the test DB."""

    def _create(
        job_id: str,
        normalized_text: str = "Normalized test text.",
        raw_transcript_text: str = "Raw test text.",
        translated_text: str = "Translated test text.",
        empty_reason: str | None = None,
    ) -> ProcessedFile:
        pf = ProcessedFile(
            job_id=job_id,
            normalized_text=normalized_text,
            raw_transcript_text=raw_transcript_text,
            translated_text=translated_text,
            empty_reason=empty_reason,
        )
        db_session.add(pf)
        db_session.commit()
        db_session.refresh(pf)
        return pf

    return _create


@pytest.fixture
def create_test_job_summary(db_session):
    """Factory fixture to create a JobSummary in the test DB."""

    def _create(
        job_id: str,
        overall_sentiment_label: str = "neutral",
        summary_product: str = "Test summary",
    ) -> JobSummary:
        summary = JobSummary(
            job_id=job_id,
            overall_sentiment_label=overall_sentiment_label,
            summary_product=summary_product,
        )
        db_session.add(summary)
        db_session.commit()
        db_session.refresh(summary)
        return summary

    return _create


@pytest.fixture
def create_test_feedback(db_session):
    """Factory fixture to create a Feedback in the test DB."""

    def _create(
        job_id: str,
        verbatim_quote: str = "Test quote",
        remarks: str = "Test remark",
        sentiment_label: str = "neutral",
    ) -> Feedback:
        feedback = Feedback(
            job_id=job_id,
            verbatim_quote=verbatim_quote,
            remarks=remarks,
            sentiment_label=sentiment_label,
        )
        db_session.add(feedback)
        db_session.commit()
        db_session.refresh(feedback)
        return feedback

    return _create
