from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ───────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URL: str | None = None
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "pidilite_db"
    DB_USER: str = "pidilite_user"
    DB_PASSWORD: str = ""

    # ── GCP ───────────────────────────────────────────────────────────────────
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "asia-south1"
    GCS_INPUT_BUCKET: str = "pidilite-audio-input"
    GCS_OUTPUT_BUCKET: str = "pidilite-stt-output"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # ── Cloud Tasks ────────────────────────────────────────────────────────────
    CLOUD_TASKS_QUEUE: str = "pidilite-stt-queue"
    CLOUD_TASKS_CALLBACK_URL: str = ""  # STT submit: /api/v1/files/transcription
    CLOUD_TASKS_TRANSLATE_URL: str = ""
    CLOUD_TASKS_POSTPROCESS_URL: str = ""
    # Internal pipeline identity — used as OIDC token on Cloud Tasks HTTP targets and
    # by Cloud Scheduler when calling /batch. Needs roles/run.invoker on the Cloud Run
    # service and roles/iam.serviceAccountUser for callers that create OIDC tokens.
    CLOUD_TASKS_INVOKER_SA: str = ""
    # Required when Cloud Run rejects unauthenticated requests (default in production).
    # Set false only for local dev against a public Cloud Run URL.
    CLOUD_TASKS_USE_OIDC: bool = True
    # Optional override for OIDC audience (defaults to scheme+host of task URL).
    CLOUD_RUN_SERVICE_AUDIENCE: str = ""

    # ── Batch ──────────────────────────────────────────────────────────────────
    BATCH_SIZE: int = 10
    MAX_RETRY_COUNT: int = 2
    # Checker re-enqueues only when a job has been in the same status at least this long.
    # Prevents tight Cloud Task enqueue loops across frequent scheduler ticks.
    # Set 0 to disable the age gate (tests / emergency).
    STUCK_JOB_RECOVERY_MINUTES: int = 10

    # ── Speech-to-Text (Chirp 3) ───────────────────────────────────────────────
    # Chirp 3 is only in the us and eu multi-regions, not asia-south1.
    STT_LOCATION: str = "us"
    STT_MODEL: str = "chirp_3"

    # ── Gemini (translate / insights — not transcription) ─────────────────────
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── Security & Tuning ──────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["*"]  # Override in production via env var
    MARKETING_KEYWORDS: list[str] = [
        'experience center', 'brand ambassador', 'we lead in', 
        'launched', 'learning by doing', 'greenpro', 'ranking',
        'celebrates', 'pull it', 'beauty of', 'launches the',
        'creating a', 'green building', 'your partner in',
        'revolutionizing', 'make their entrance', 'launch of',
        'a strong start', 'phenko nahin', 'fixes in five',
        'changing the way', 'acquires', 'champs', 'at pidilite',
        'a year of', 'venturing into', 'a new star', 'from business',
        'taking roff', 'goes outdoor', 'building a green',
        'with you through', 'we build world', 'green pro certified',
        'art workshops', 'revamped', 'extension to govt',
        'preferred adhesive', 'is born', 'manufacturing plant',
        'first campaign', 'enhancing the', 'champions club',
        'adding magic', 'for the love', 'empowering women',
        'workshops', 'colours that', 'bring indian', 'pv seal launches'
    ]

    @property
    def internal_invoker_service_account(self) -> str:
        """Same SA for Cloud Tasks callbacks and Cloud Scheduler → /batch."""
        return self.cloud_tasks_invoker_service_account

    @property
    def cloud_tasks_invoker_service_account(self) -> str:
        if self.CLOUD_TASKS_INVOKER_SA:
            return self.CLOUD_TASKS_INVOKER_SA
        if self.GCP_PROJECT_ID:
            return f"cloud-run-api@{self.GCP_PROJECT_ID}.iam.gserviceaccount.com"
        return ""

    @property
    def stt_model(self) -> str:
        return (self.STT_MODEL or "chirp_3").strip() or "chirp_3"

    @property
    def stt_location(self) -> str:
        return (self.STT_LOCATION or "us").strip() or "us"

    @property
    def DATABASE_URL(self) -> str:
        if self.SQLALCHEMY_DATABASE_URL:
            return self.SQLALCHEMY_DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()