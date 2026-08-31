"""
ORM models — Refactored for Dashboard AI requirements and Many-to-Many Tagging.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, Enum as SAEnum, func, Table
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from db.session import Base
from core.enums import JobStatus, BatchStatus

_FK_JOBS_ID = "jobs.id"


def _uuid() -> str:
    return str(uuid.uuid4())


# ── USERS ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    full_name = Column(String(200), nullable=True)
    role = Column(String(50), nullable=False, default="user")
    allowed_resources = Column(JSONB, nullable=False, default=list)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── BATCHES ───────────────────────────────────────────────────────────────────
class Batch(Base):
    __tablename__ = "batches"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    batch_number = Column(Integer, nullable=False, autoincrement=True)
    batch_size = Column(Integer, nullable=False, default=10)
    status = Column(SAEnum(BatchStatus), nullable=False, default=BatchStatus.PENDING, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    jobs = relationship("Job", back_populates="batch", lazy="dynamic")


# ── JOBS ──────────────────────────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    gcs_input_uri = Column(Text, nullable=False)
    gcs_stt_output_uri = Column(Text, nullable=True)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    stt_operation_name = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch = relationship("Batch", back_populates="jobs")
    file_details = relationship("FileDetails", back_populates="job", uselist=False)
    processed_file = relationship("ProcessedFile", back_populates="job", uselist=False, cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="job", lazy="dynamic", cascade="all, delete-orphan")
    failed_jobs = relationship("FailedJob", back_populates="job", cascade="all, delete-orphan")


# ── FILE_DETAILS ──────────────────────────────────────────────────────────────
class FileDetails(Base):
    __tablename__ = "file_details"

    job_id = Column(UUID(as_uuid=False), ForeignKey(
        _FK_JOBS_ID, ondelete="CASCADE"), primary_key=True)
    file_name = Column(String(500), nullable=False)
    
    # System timestamps
    file_uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # File properties
    mime_type = Column(String(100), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    file_extension = Column(String(20), nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)

    # ── NEW: Crucial Audio Metadata ──
    call_date = Column(DateTime(timezone=True), nullable=True, index=True) # Actual time of the conversation
    audio_duration_seconds = Column(Integer, nullable=True)
    language_code = Column(String(20), nullable=True, index=True) # e.g., 'hi-IN', 'en-IN'

    # ── Dashboard Filter Metadata ──
    state = Column(String(100), nullable=True, index=True) # NEW: Added for BI filtering
    division = Column(String(100), nullable=True, index=True)
    zone = Column(String(100), nullable=True, index=True)
    cluster = Column(String(100), nullable=True, index=True)
    rfmm_cluster = Column(String(100), nullable=True, index=True)
    town_city = Column(String(100), nullable=True, index=True)
    tsi_territory_code = Column(String(100), nullable=True, index=True)
    fme_code = Column(String(100), nullable=True, index=True)
    tty_code = Column(String(100), nullable=True, index=True)
    user_id_metadata = Column(String(100), nullable=True, index=True)
    user_type = Column(String(100), nullable=True, index=True)
    data_source = Column(String(100), nullable=True, default="Voice Conversations", index=True)

    job = relationship("Job", back_populates="file_details")


# ── PROCESSED_FILE ────────────────────────────────────────────────────────────
class ProcessedFile(Base):
    __tablename__ = "processed_file"

    job_id = Column(UUID(as_uuid=False), ForeignKey(_FK_JOBS_ID, ondelete="CASCADE"), primary_key=True)
    gcs_transcript_uri = Column(Text, nullable=True)
    raw_transcript_text = Column(Text, nullable=True)
    translated_text = Column(Text, nullable=True)
    
    # Audit log of exact LLM payload
    insights_raw_json = Column(JSONB, nullable=True)
    
    empty_reason = Column(Text, nullable=True) # Justification if insights generation fails or is skipped
    
    processed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="processed_file")


# ── LOOKUP TABLES ─────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(200), nullable=False)
    short_code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    
    is_active = Column(Boolean, default=True)


class FeedbackTag(Base):
    __tablename__ = "feedback_tags"

    tag_id = Column(Integer, primary_key=True)  # taxonomy integer ID (1-42)
    tag_name = Column(String(200), nullable=False)
    sub_tag_name = Column(String(200), nullable=True)
    
    description = Column(Text, nullable=True)
    group_type = Column(String(100), nullable=True)
    category = Column(String(100), nullable=True)
    
    is_active = Column(Boolean, default=True)

    feedbacks = relationship("Feedback", secondary="feedback_tag_link", back_populates="tags")


class FailedJob(Base):
    __tablename__ = "failed_jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey(_FK_JOBS_ID, ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=False)
    pipeline_stage = Column(String(50), nullable=False) # e.g., INGEST, BATCH, STT, TRANSLATE, INSIGHTS
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="failed_jobs")


# ── MANY-TO-MANY JUNCTION TABLE ───────────────────────────────────────────────
feedback_tag_link = Table(
    "feedback_tag_link",
    Base.metadata,
    Column("feedback_id", UUID(as_uuid=False), ForeignKey("feedbacks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("feedback_tags.tag_id", ondelete="CASCADE"), primary_key=True)
)


# ── FEEDBACKS (Granular Verbatims & AI Tagging) ───────────────────────────────
class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey(_FK_JOBS_ID, ondelete="CASCADE"), nullable=False, index=True)
    product_name = Column(String(200), nullable=True, index=True)  # LLM-extracted canonical name
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)  # resolved server-side
    
    group_type = Column(String(100), nullable=False)    
    category_type = Column(String(100), nullable=True)  
    
    verbatim_quote = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="feedbacks")
    product = relationship("Product")
    competitors = relationship("FeedbackCompetitor", back_populates="feedback", lazy="dynamic", cascade="all, delete-orphan")
    
    tags = relationship("FeedbackTag", secondary=feedback_tag_link, back_populates="feedbacks")


class FeedbackCompetitor(Base):
    __tablename__ = "feedback_competitors"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    feedback_id = Column(UUID(as_uuid=False), ForeignKey("feedbacks.id", ondelete="CASCADE"), nullable=False, index=True)
    competitor_name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    feedback = relationship("Feedback", back_populates="competitors")


# ── KEYWORD_DICTIONARY ────────────────────────────────────────────────────────
class KeywordDictionary(Base):
    __tablename__ = "keyword_dictionary"

    canonical_id = Column(String(100), primary_key=True)
    canonical_term = Column(String(300), nullable=False, unique=True)
    category = Column(String(100), nullable=True)
    language = Column(JSONB, nullable=True)
    aliases = Column(JSONB, nullable=False, default=list)
    priority = Column(Integer, default=0)
    effective_from = Column(DateTime(timezone=True), server_default=func.now())
    owner = Column(String(100), nullable=True)
    version = Column(Integer, default=1)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── APP_CONFIG ────────────────────────────────────────────────────────────────
class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(200), primary_key=True)
    value = Column(JSONB, nullable=False)
    description = Column(String(500), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())