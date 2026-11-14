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

    # Security integrations
    malware_scan: Literal["off", "clamav"] = Field("off", alias="MALWARE_SCAN")
    clamav_host: str = Field("localhost", alias="CLAMAV_HOST")
    clamav_port: int = Field(3310, alias="CLAMAV_PORT")
    # "redis" is required when running more than one API replica
    rate_limit_backend: Literal["memory", "redis"] = Field("memory", alias="RATE_LIMIT_BACKEND")

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
    # "hashing" is a deterministic lexical embedder for tests/offline dev only (never in production).
    embedding_provider: Literal["openai", "local", "hashing"] = Field(
        "openai", alias="EMBEDDING_PROVIDER"
    )
    embedding_model: str = Field("text-embedding-3-large", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(1024, alias="EMBEDDING_DIM")
    embedding_version: str = Field("1", alias="EMBEDDING_VERSION")
    embedding_batch_size: int = Field(64, alias="EMBEDDING_BATCH_SIZE")
    openai_api_key: SecretStr = Field(SecretStr(""), alias="OPENAI_API_KEY")
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    ai_timeout_s: float = Field(60.0, alias="AI_TIMEOUT_S")
    local_scan_limit: int = Field(20000, alias="LOCAL_VECTOR_SCAN_LIMIT")

    # LLM. "fake" is a deterministic extractive stand-in for tests/offline demos (blocked in production).
    llm_provider: Literal["anthropic", "fake"] = Field("anthropic", alias="LLM_PROVIDER")
    anthropic_api_key: SecretStr = Field(SecretStr(""), alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-opus-5-5", alias="ANTHROPIC_MODEL")
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        "medium", alias="LLM_EFFORT"
    )
    llm_max_tokens: int = Field(4096, alias="LLM_MAX_TOKENS")

    # RAG
    reranker: Literal["lexical", "cross_encoder", "none"] = Field("lexical", alias="RERANKER")
    reranker_model: str = Field("BAAI/bge-reranker-v2-m3", alias="RERANKER_MODEL")
    rag_top_k: int = Field(8, alias="RAG_TOP_K")
    rag_candidates: int = Field(30, alias="RAG_CANDIDATES")
    rag_context_tokens: int = Field(6000, alias="RAG_CONTEXT_TOKENS")
    rag_min_vector_score: float = Field(0.2, alias="RAG_MIN_VECTOR_SCORE")
    rag_multi_query: bool = Field(True, alias="RAG_MULTI_QUERY")
    rag_history_turns: int = Field(6, alias="RAG_HISTORY_TURNS")
    llm_concurrency: int = Field(8, alias="LLM_CONCURRENCY")

    # Document intelligence (insights run as a separate background job after ingestion completes)
    insights_enabled: bool = Field(True, alias="INSIGHTS_ENABLED")
    insights_max_direct_chars: int = Field(70_000, alias="INSIGHTS_MAX_DIRECT_CHARS")
    insights_window_chars: int = Field(50_000, alias="INSIGHTS_WINDOW_CHARS")

    # Extraction / OCR
    ocr_enabled: bool = Field(True, alias="OCR_ENABLED")
    tesseract_cmd: str = Field("tesseract", alias="TESSERACT_CMD")
    ocr_langs: str = Field("eng", alias="OCR_LANGS")
    ocr_max_pages: int = Field(200, alias="OCR_MAX_PAGES")
    max_pages_per_document: int = Field(2000, alias="MAX_PAGES_PER_DOCUMENT")

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
    def embeds_externally(self) -> bool:
        """True when document text is sent to a third-party service for embedding."""
        return self.embedding_provider == "openai"

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider == "fake" or bool(self.anthropic_api_key.get_secret_value())

    @property
    def ai_external(self) -> bool:
        """True when document text can be sent to any third-party AI service (embeddings or LLM)."""
        return self.embeds_externally or self.llm_external

    @property
    def llm_external(self) -> bool:
        return self.llm_provider == "anthropic"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
