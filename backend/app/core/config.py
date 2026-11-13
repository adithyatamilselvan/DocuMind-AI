from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = Field("development", alias="APP_ENV")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    secret_key: SecretStr = Field(..., alias="APP_SECRET_KEY", min_length=32)

    # MongoDB
    mongodb_uri: str = Field("mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field("documind_dev", alias="MONGODB_DB")
    # "atlas" uses $vectorSearch/$search; "local" uses bounded brute-force cosine + $text (dev only)
    vector_backend: Literal["atlas", "local"] = Field("local", alias="VECTOR_BACKEND")

    # Sessions / cookies / CORS
    session_cookie_name: str = "documind_session"
    csrf_cookie_name: str = "documind_csrf"
    session_ttl_hours: int = Field(24 * 14, alias="SESSION_TTL_HOURS")
    cookie_secure: bool = Field(False, alias="COOKIE_SECURE")
    cors_origins: list[str] = Field(default_factory=list, alias="CORS_ORIGINS")
    frontend_url: str = Field("http://localhost:3000", alias="FRONTEND_URL")

    # Disable only for automated end-to-end runs where every test registers from one IP.
    rate_limit_enabled: bool = Field(True, alias="RATE_LIMIT_ENABLED")

    # Set true only when running behind a trusted reverse proxy (Next.js rewrite / nginx)
    trust_forwarded_for: bool = Field(False, alias="TRUST_FORWARDED_FOR")
    email_backend: Literal["log", "smtp"] = Field("log", alias="EMAIL_BACKEND")
    smtp_host: str = Field("", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: SecretStr = Field(SecretStr(""), alias="SMTP_PASSWORD")
    email_from: str = Field("DocuMind <no-reply@example.com>", alias="EMAIL_FROM")

    # Uploads
    max_upload_mb: int = Field(50, alias="MAX_UPLOAD_MB")
    max_files_per_upload: int = Field(20, alias="MAX_FILES_PER_UPLOAD")

    # Object storage
    storage_backend: Literal["local", "s3"] = Field("local", alias="STORAGE_BACKEND")
    local_storage_dir: str = Field(".local-data/objects", alias="LOCAL_STORAGE_DIR")
    s3_endpoint_url: str = Field("", alias="S3_ENDPOINT_URL")
    s3_region: str = Field("us-east-1", alias="S3_REGION")
    s3_bucket: str = Field("documind", alias="S3_BUCKET")
    s3_access_key_id: str = Field("", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr = Field(SecretStr(""), alias="S3_SECRET_ACCESS_KEY")

    # AI providers (server-side only). Embeddings default to a hosted API; "local" = sentence-transformers.
    embedding_provider: Literal["openai", "local"] = Field("openai", alias="EMBEDDING_PROVIDER")

    # Background jobs. "celery" needs Redis + a worker; "inline" runs jobs inside the API
    # process (development without Redis only; jobs do not survive API restarts except via recovery).
    job_backend: Literal["celery", "inline"] = Field("inline", alias="JOB_BACKEND")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    job_max_attempts: int = Field(3, alias="JOB_MAX_ATTEMPTS")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
