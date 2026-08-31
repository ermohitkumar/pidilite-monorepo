"""
Pydantic v2 schemas — request/response models for all API endpoints.

Endpoints:
  1. POST /api/v1/ingest
  2. POST /api/v1/batch/start
  3. POST /api/v1/stt/submit
  4. POST /api/v1/process/normalize-insights
  5. POST /api/v1/checker/run
  6. Dashboard & Auth endpoints
"""
from __future__ import annotations
from typing import Any, Optional, List, Dict, Union, Literal
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from datetime import datetime, timezone
import secrets
import string
from core.config import settings


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Accept datetime objects, Postgres/ISO strings, or None for response validation."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip().replace(" ", "T", 1)
        if normalized.endswith("+00"):
            normalized += ":00"
        return datetime.fromisoformat(normalized)
    raise TypeError(f"Expected datetime, str, or None, got {type(value)!r}")

# ═══════════════════════════════════════════════════════════════════════════════
# COMMON RESPONSE ENVELOPE
# ═══════════════════════════════════════════════════════════════════════════════


class APIResponse(BaseModel):
    """Standard V1 API response envelope used by all /api/v1/* endpoints."""
    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[Any] = None
    timestamp: str
    request_id: str


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD & AUTH SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str
    
    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        min_length = 6 if settings.ENVIRONMENT == "development" else 12
        if len(v) < min_length:
            raise ValueError(f"Password must be at least {min_length} characters")
        return v


class SSOLoginRequest(BaseModel):
    token: str = Field(
        description="The ID token received from Microsoft Entra ID")
    email: str = Field(
        description="User email strictly required for database verification")


class PaginationMeta(BaseModel):
    current_page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool

# ── 0. Summary Endpoint Schemas ──


class ActiveBatchesSummary(BaseModel):
    count: int
    active_jobs: int


class FilesProcessedSummary(BaseModel):
    count: int
    success_rate: float


class FailedFilesSummary(BaseModel):
    count: int


class DashboardSummaryData(BaseModel):
    total_batches: int
    completed_batches: int
    active_batches: ActiveBatchesSummary
    files_processed_24h: FilesProcessedSummary
    failed_files: FailedFilesSummary


class DashboardSummaryResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[DashboardSummaryData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ── 1. Batches Endpoint Schemas ──


class BatchItem(BaseModel):
    batch_id: str
    batch_number: int
    status: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    created_at: Optional[datetime]
    completed_at: Optional[datetime] = None

    @field_validator("created_at", "completed_at", mode="before")
    @classmethod
    def _parse_datetimes(cls, value: Any) -> Optional[datetime]:
        return _coerce_datetime(value)


class DashboardBatchesData(BaseModel):
    items: List[BatchItem]
    metadata: PaginationMeta


class DashboardBatchesResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[DashboardBatchesData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ── 2. Single Batch Endpoint Schemas ──


class JobItem(BaseModel):
    job_id: str
    file_name: str
    status: str
    created_at: Optional[datetime]
    has_insights: bool
    error_message: Optional[str] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: Any) -> Optional[datetime]:
        return _coerce_datetime(value)


class SingleBatchJobsMeta(PaginationMeta):
    completed_jobs: int
    failed_jobs: int


class SingleBatchJobsData(BaseModel):
    items: List[JobItem]
    metadata: SingleBatchJobsMeta


class DashboardSingleBatchData(BaseModel):
    batch_info: BatchItem
    jobs: SingleBatchJobsData


class DashboardSingleBatchResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[DashboardSingleBatchData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ── 3. Global Jobs Endpoint Schemas ──


class GlobalJobItem(JobItem):
    batch_id: Optional[str] = None
    batch_number: Optional[int] = None


class DashboardJobsData(BaseModel):
    items: List[GlobalJobItem]
    metadata: PaginationMeta


class DashboardJobsResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[DashboardJobsData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ── 4. File Insights Endpoint Schemas ──


class FileInsightFeedback(BaseModel):
    product_name: Optional[str] = None
    category_name: Optional[str] = None
    tag_name: Optional[str] = None
    group_type: Optional[str] = None
    verbatim_quote: Optional[str] = None
    remarks: Optional[str] = None
    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None

    @field_validator(
        "product_name", "category_name", "tag_name", "group_type",
        "verbatim_quote", "remarks", "sentiment_label",
        mode="before",
    )
    @classmethod
    def _stringify(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)


class FileInsightSummary(BaseModel):
    overall_sentiment_label: Optional[str] = None
    overall_sentiment_score: Optional[float] = None
    summary_product: Optional[str] = None
    summary_price_schemes: Optional[str] = None
    summary_quality: Optional[str] = None
    summary_service: Optional[str] = None


class FileInsightsData(BaseModel):
    job_id: str
    file_name: str
    status: Optional[str] = None
    error_message: Optional[str] = None
    empty_reason: Optional[str] = None
    raw_transcript_text: Optional[str] = None
    translated_text: Optional[str] = None
    normalized_text: Optional[str] = None
    summary: Optional[FileInsightSummary] = None
    feedbacks: List[FileInsightFeedback] = []
    generated_at: Optional[datetime] = None

    @field_validator("generated_at", mode="before")
    @classmethod
    def _parse_generated_at(cls, value: Any) -> Optional[datetime]:
        return _coerce_datetime(value)

    @field_validator(
        "file_name", "status", "error_message", "empty_reason",
        "raw_transcript_text", "translated_text", "normalized_text",
        mode="before",
    )
    @classmethod
    def _stringify_optional(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)


class FileInsightsResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[FileInsightsData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


# ── Allowed roles (3 roles) ──
_VALID_ROLES = Literal["user", "admin", "super_admin"]


class UserCreate(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: _VALID_ROLES = "user"
    allowed_resources: List[Union[str, Dict[str, Any]]
                            ] = Field(default_factory=list)

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        min_length = 8 if settings.ENVIRONMENT == "development" else 12
        if len(v) < min_length:
            raise ValueError(f"Password must be at least {min_length} characters")
        if not any(c.isupper() for c in v):
            raise ValueError(
                "Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

    from pydantic import model_validator

    @model_validator(mode="after")
    def password_required_in_dev(self) -> "UserCreate":
        """In development, password is mandatory. In production, it's forbidden (SSO only)."""
        if settings.ENVIRONMENT == "development":
            if not self.password:
                raise ValueError("Password is required in development environment")
        else:
            if self.password is not None:
                raise ValueError("Password must not be provided in production. Users authenticate via SSO.")
        return self


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(default=None, max_length=254)
    password: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[_VALID_ROLES] = None
    is_active: Optional[bool] = None
    allowed_resources: Optional[List[Union[str, Dict[str, Any]]]] = None

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not any(c.isupper() for c in v):
            raise ValueError(
                "Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserResponseData(BaseModel):
    user_id: str
    email: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    allowed_resources: List[Union[str, Dict[str, Any]]]
    created_at: Optional[datetime] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: Any) -> Optional[datetime]:
        return _coerce_datetime(value)


class UserResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[UserResponseData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None


class UserListResponseData(BaseModel):
    items: List[UserResponseData]
    total: int


class UserListResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[UserListResponseData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None


class PermissionsListResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[List[str]] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════════
# KEYWORD MANAGEMENT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


class KeywordCreate(BaseModel):
    canonical_id: str
    canonical_term: str
    category: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    priority: int = 0
    owner: Optional[str] = None


class KeywordUpdate(BaseModel):
    canonical_term: Optional[str] = None
    category: Optional[str] = None
    aliases: Optional[List[str]] = None
    priority: Optional[int] = None


class KeywordResponseData(BaseModel):
    canonical_id: str
    canonical_term: str
    category: Optional[str] = None
    aliases: List[str]
    priority: int
    owner: Optional[str] = None
    version: int
    updated_at: Optional[datetime] = None

    @field_validator("updated_at", mode="before")
    @classmethod
    def _parse_updated_at(cls, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        return _coerce_datetime(value)


class KeywordListResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[List[KeywordResponseData]] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None


class KeywordActionResponseData(BaseModel):
    canonical_id: str
    version: Optional[int] = None


class KeywordActionResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[KeywordActionResponseData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY CONFIGURATION SCHEMAS (AppConfig)
# ═══════════════════════════════════════════════════════════════════════════════


class RegistryItemCreate(BaseModel):
    value: str = Field(description="The new category or language to add")


class RegistryItemUpdate(BaseModel):
    new_value: str = Field(description="The updated category or language name")


class RegistryResponseData(BaseModel):
    key: str
    values: List[str]
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    @field_validator("updated_at", mode="before")
    @classmethod
    def _parse_updated_at(cls, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        return _coerce_datetime(value)


class RegistryResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[RegistryResponseData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK FACT REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

class FeedbackFactRow(BaseModel):
    feedback_id: Optional[str] = None
    job_id: Optional[str] = None
    feedback_created_at: Optional[str] = None
    feedback_group: Optional[str] = None
    feedback_category: Optional[str] = None
    feedback_tag: Optional[str] = None
    feedback_sub_tag: Optional[str] = None
    product_name: Optional[str] = None
    product_id: Optional[str] = None
    product_short_code: Optional[str] = None
    feedback_summary_ai: Optional[str] = None
    feedback_excerpt: Optional[str] = None
    full_conversation: Optional[str] = None
    full_conversation_truncated: bool = False
    competitors_mentioned: Optional[str] = None
    file_name: Optional[str] = None
    call_date: Optional[str] = None
    language_code: Optional[str] = None
    state: Optional[str] = None
    division: Optional[str] = None
    zone: Optional[str] = None
    cluster: Optional[str] = None
    rfmm_cluster: Optional[str] = None
    town_city: Optional[str] = None
    fme_code: Optional[str] = None
    user_type: Optional[str] = None
    data_source: Optional[str] = None
    job_status: Optional[str] = None
    audio_gcs_uri: Optional[str] = None


class FeedbackFactFilterOptions(BaseModel):
    divisions: List[str] = []
    zones: List[str] = []
    clusters: List[str] = []
    states: List[str] = []
    products: List[str] = []
    data_sources: List[str] = []
    fme_codes: List[str] = []
    user_types: List[str] = []


class AudioLocatorData(BaseModel):
    job_id: str
    file_name: str
    gcs_uri: str
    content_type: str


class FeedbackFactData(BaseModel):

    items: List[FeedbackFactRow] = []
    filter_options: FeedbackFactFilterOptions = FeedbackFactFilterOptions()
    metadata: Dict[str, Any] = {}
    source: str = "vw_pbi_feedback_fact"


class FeedbackFactResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[FeedbackFactData] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None
