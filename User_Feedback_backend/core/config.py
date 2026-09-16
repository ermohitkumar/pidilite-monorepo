import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union

_DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "https://pidilite-dashboard-634870075270.asia-south1.run.app",
]


class Settings(BaseSettings):
    # ── Environment ────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"   # "development" | "production"

    # ── Database ───────────────────────────────────────────────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "pidilite_db"
    DB_USER: str = "pidilite_user"
    DB_PASSWORD: str = ""

    # ── Session ────────────────────────────────────────────────────────────────
    SESSION_SECRET_KEY: str    # No default — app will refuse to start without it
    SESSION_MAX_AGE: int = 28800   # 8 hours

    # ── Vertex / Gemini (period summaries) ─────────────────────────────────────
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "asia-south1"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── SSO / Azure AD ─────────────────────────────────────────────────────────
    AZURE_CLIENT_ID: str = ""  # Add your Microsoft App/Client ID in .env
    AZURE_TENANT_ID: str = ""  # Add your Microsoft Tenant ID in .env

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Comma-separated or JSON array in env, e.g. CORS_ALLOWED_ORIGINS='["https://app.example.com"]'
    CORS_ALLOWED_ORIGINS: str = ""

    @staticmethod
    def _valid_origin(origin: str) -> bool:
        return origin.startswith("http://") or origin.startswith("https://")

    @classmethod
    def _parse_cors_origins(cls, raw: Union[str, List[str], None]) -> List[str]:
        if isinstance(raw, list):
            origins = [str(origin)
                       for origin in raw if cls._valid_origin(str(origin))]
            return origins or list(_DEFAULT_CORS_ORIGINS)
        if not isinstance(raw, str) or not raw.strip():
            return list(_DEFAULT_CORS_ORIGINS)
        value = raw.strip()
        try:
            if value.startswith("["):
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    origins = [
                        str(origin) for origin in parsed if cls._valid_origin(str(origin))]
                    if origins:
                        return origins
            else:
                origins = [
                    origin.strip()
                    for origin in value.split(",")
                    if origin.strip() and cls._valid_origin(origin.strip())
                ]
                if origins:
                    return origins
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return list(_DEFAULT_CORS_ORIGINS)

    @property
    def cors_allowed_origins(self) -> List[str]:
        return self._parse_cors_origins(self.CORS_ALLOWED_ORIGINS)

    @field_validator("SESSION_SECRET_KEY")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "SESSION_SECRET_KEY must be at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return v

    # Private GCS buckets allowed for authenticated audio playback (comma-separated).
    GCS_AUDIO_ALLOWED_BUCKETS: str = "pidilite-raw-audio,pidilite-audio-input"

    @property
    def gcs_audio_allowed_buckets(self) -> set[str]:
        return {
            bucket.strip()
            for bucket in self.GCS_AUDIO_ALLOWED_BUCKETS.split(",")
            if bucket.strip()
        }

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
