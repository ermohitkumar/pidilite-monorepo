"""
ORM models — exactly matching the ER diagram and new Dashboard AI requirements.

Tables:
  users                – form-login accounts (Kept as requested)
  batches              – groups of jobs sent to STT together
  jobs                 – one row per audio file, central tracking entity
  file_details         – 1-to-1 with jobs, file metadata
  processed_file       – 1-to-1 with jobs, STT + normalisation output
  keyword_dictionary   – canonical term replacement rules (Kept as requested)
  app_config           – runtime configuration key-value store
  products             – lookup table for Pidilite products (Fevicol SH, X-Per, etc.)
  feedback_categories  – lookup table for feedback categories (Product, Systems, etc.)
  feedback_tags        – lookup table for tags linked to categories
  feedbacks            – Granular AI output: Verbatims, CoT Remarks, Tags, and Scores
  job_summaries        – 1-to-1 with jobs: 4-Pillar Summaries and Overall Sentiment
  feedback_competitors – Junction table for competitors mentioned in feedback
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, Enum as SAEnum, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from db.session import Base
from core.enums import JobStatus, BatchStatus

# Foreign-key target used by multiple child tables
_FK_JOBS_ID = "jobs.id"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── USERS ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    full_name = Column(String(200), nullable=True)

    # ── Updated Roles & Dynamic Permissions ──
    # super_admin, admin, user
    role = Column(String(50), nullable=False, default="user")
    # Stores [{"resource": "view_dashboard", "actions": ["read"]}, etc.]
    allowed_resources = Column(JSONB, nullable=False, default=list)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())


# ── BATCHES ───────────────────────────────────────────────────────────────────
class Batch(Base):
    __tablename__ = "batches"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    batch_number = Column(Integer, nullable=False, autoincrement=True)
    batch_size = Column(Integer, nullable=False, default=10)
    status = Column(SAEnum(BatchStatus), nullable=False,
                    default=BatchStatus.PENDING, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    jobs = relationship("Job", back_populates="batch", lazy="dynamic")


# ── JOBS ──────────────────────────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    gcs_input_uri = Column(Text, nullable=False)
    gcs_stt_output_uri = Column(Text, nullable=True)
    batch_id = Column(UUID(as_uuid=False), ForeignKey(
        "batches.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(SAEnum(JobStatus), nullable=False,
                    default=JobStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    stt_operation_name = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())

    batch = relationship("Batch", back_populates="jobs")
    file_details = relationship(
        "FileDetails",   back_populates="job", uselist=False)
    processed_file = relationship(
        "ProcessedFile", back_populates="job", uselist=False)
    feedbacks = relationship("Feedback", back_populates="job", lazy="dynamic")
    summary = relationship("JobSummary", back_populates="job", uselist=False)


# ── FILE_DETAILS ──────────────────────────────────────────────────────────────
class FileDetails(Base):
    __tablename__ = "file_details"

    job_id = Column(UUID(as_uuid=False), ForeignKey(
        _FK_JOBS_ID, ondelete="CASCADE"), primary_key=True)
    file_name = Column(String(500), nullable=False)
    file_uploaded_at = Column(DateTime(timezone=True),
                              server_default=func.now())
    mime_type = Column(String(100), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    file_extension = Column(String(20), nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)

    # ── Dashboard Filter Metadata ──
    division = Column(String(100), nullable=True, index=True)
    zone = Column(String(100), nullable=True, index=True)
    cluster = Column(String(100), nullable=True, index=True)
    rfmm_cluster = Column(String(100), nullable=True, index=True)
    town_city = Column(String(100), nullable=True, index=True)
    tsi_territory_code = Column(String(100), nullable=True, index=True)
    fme_code = Column(String(100), nullable=True, index=True)
    tty_code = Column(String(100), nullable=True, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    user_type = Column(String(100), nullable=True, index=True)
    data_source = Column(String(100), nullable=True,
                         default="Voice Conversations", index=True)

    job = relationship("Job", back_populates="file_details")


# ── PROCESSED_FILE ────────────────────────────────────────────────────────────
class ProcessedFile(Base):
    __tablename__ = "processed_file"

    job_id = Column(UUID(as_uuid=False), ForeignKey(
        _FK_JOBS_ID, ondelete="CASCADE"), primary_key=True)
    gcs_transcript_uri = Column(Text, nullable=True)
    raw_transcript_text = Column(Text, nullable=True)
    translated_text = Column(Text, nullable=True)
    normalized_text = Column(Text, nullable=True)
    empty_reason = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="processed_file")


# ── LOOKUP TABLES (PRODUCTS, CATEGORIES, TAGS) ────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    product_name = Column(String(200), nullable=False)
    short_code = Column(String(50), nullable=True)
    category = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)


class FeedbackCategory(Base):
    __tablename__ = "feedback_categories"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    category_name = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)

    tags = relationship("FeedbackTag", back_populates="category")


class FeedbackTag(Base):
    __tablename__ = "feedback_tags"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    category_id = Column(UUID(as_uuid=False), ForeignKey(
        "feedback_categories.id"), nullable=True)
    tag_name = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)

    category = relationship("FeedbackCategory", back_populates="tags")


# ── FEEDBACKS (Granular Verbatims & AI Tagging) ───────────────────────────────
class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey(
        _FK_JOBS_ID, ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=False), ForeignKey(
        "products.id"), nullable=True)
    category_id = Column(UUID(as_uuid=False), ForeignKey(
        "feedback_categories.id"), nullable=True)
    tag_id = Column(UUID(as_uuid=False), ForeignKey(
        "feedback_tags.id"), nullable=True)

    verbatim_quote = Column(Text, nullable=True)
    remarks = Column(Text, nullable=True)
    sentiment_label = Column(String(50), nullable=True)
    sentiment_score = Column(Float, nullable=True)

    contractor_profile = Column(String(200), nullable=True)
    speaker_name = Column(String(200), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="feedbacks")
    competitors = relationship(
        "FeedbackCompetitor", back_populates="feedback", lazy="dynamic")

    # ── Added explicitly to allow router traversal ──
    product = relationship("Product")
    category = relationship("FeedbackCategory")
    tag = relationship("FeedbackTag")


class FeedbackCompetitor(Base):
    __tablename__ = "feedback_competitors"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    feedback_id = Column(UUID(as_uuid=False), ForeignKey(
        "feedbacks.id", ondelete="CASCADE"), nullable=False, index=True)
    competitor_name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    feedback = relationship("Feedback", back_populates="competitors")


# ── JOB SUMMARIES (4-Pillar Text & Overall Scores) ────────────────────────────
class JobSummary(Base):
    __tablename__ = "job_summaries"

    job_id = Column(UUID(as_uuid=False), ForeignKey(
        _FK_JOBS_ID, ondelete="CASCADE"), primary_key=True)

    overall_sentiment_label = Column(String(50), nullable=True)
    overall_sentiment_score = Column(Float, nullable=True)

    summary_product = Column(Text, nullable=True)
    summary_price_schemes = Column(Text, nullable=True)
    summary_quality = Column(Text, nullable=True)
    summary_service = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="summary")


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
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())


# ── APP_CONFIG ────────────────────────────────────────────────────────────────
class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(200), primary_key=True)
    value = Column(JSONB, nullable=False)
    description = Column(String(500), nullable=True)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
