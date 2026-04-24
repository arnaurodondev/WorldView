"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EODHDProviderSettings(BaseModel):
    """Operational parameters for the EODHD news provider."""

    base_url: str = "https://eodhd.com/api/news"
    page_size: int = 100
    # OPT-3: Cap pages fetched per fetch_all_pages() call to avoid runaway credit
    # consumption on busy news days. Each page costs 5 EODHD API credits; default 3
    # yields at most 3 x page_size articles per cycle, which covers all normal cases.
    max_pages_per_cycle: int = 3
    rate_limit_per_second: float = 10.0


class FinnhubProviderSettings(BaseModel):
    """Operational parameters for the Finnhub provider."""

    base_url: str = "https://finnhub.io/api/v1"
    rate_limit_per_minute: int = 55


class NewsAPIProviderSettings(BaseModel):
    """Operational parameters for the NewsAPI.org provider."""

    base_url: str = "https://newsapi.org/v2/everything"
    page_size: int = 100
    quota_ttl_seconds: int = 86400


class SECEdgarProviderSettings(BaseModel):
    """Operational parameters for the SEC EDGAR provider."""

    efts_url: str = "https://efts.sec.gov/LATEST/search-index"
    filing_base_url: str = "https://www.sec.gov/Archives/edgar/data"
    default_forms: str = "10-K,10-Q,8-K,DEF14A"
    max_concurrent: int = 8
    market_hours_interval_seconds: int = 60
    off_hours_interval_seconds: int = 1800


class PolymarketProviderSettings(BaseModel):
    """Operational parameters for the Polymarket Gamma API provider."""

    base_url: str = "https://gamma-api.polymarket.com/markets"
    page_size: int = Field(default=500, ge=1, le=1000)
    max_pages_per_cycle: int = Field(default=20, ge=1, le=100)


class HTTPClientSettings(BaseModel):
    """Shared httpx client tuning parameters."""

    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    max_retries: int = 3


class Settings(BaseSettings):
    """Configuration for the Content Ingestion service (S4).

    All fields are read from environment variables prefixed with
    ``CONTENT_INGESTION_`` (set by ``env_prefix``).

    Exception: source API keys use their own conventional unprefixed names
    (EODHD_API_KEY, FINNHUB_API_KEY, etc.) and are overridden via
    ``validation_alias`` to bypass the prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTENT_INGESTION_",
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # ── External API keys (no CONTENT_INGESTION_ prefix — shared variables) ──
    eodhd_api_key: str = ""
    sec_edgar_user_agent: str = "worldview/1.0 contact@worldview.example"
    finnhub_api_key: str = ""
    newsapi_key: str = ""

    # ── Database ──────────────────────────────────────────────────────────────
    db_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db")
    db_url_read: SecretStr = SecretStr("")  # Falls back to db_url if empty (R23)

    # ── Kafka ─────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_schema_registry_basic_auth: str = ""
    kafka_outbox_topic: str = "content.article.raw.v1"

    # ── MinIO (object storage) ────────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "worldview-bronze"
    minio_secure: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    admin_token: str = ""  # CONTENT_INGESTION_ADMIN_TOKEN — admin/DevOps only
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # ── Scheduler (process — R22) ────────────────────────────────────────────
    scheduler_interval_seconds: int = 300
    scheduler_tick_interval_seconds: float = 60.0
    scheduler_max_tasks_per_tick: int = 100

    # ── Worker (process — R22) ─────────────────────────────────────────────
    worker_batch_size: int = 5
    worker_lease_seconds: int = 300
    worker_idle_sleep_seconds: float = 5.0
    worker_concurrency: int = 2
    worker_task_timeout_seconds: float = 120.0
    # D-04: Polymarket tasks paginate the full market catalogue via the Gamma API
    # (up to 20 pages x 500 markets = 10 000 results + MinIO writes per result).
    # The default 120 s timeout is too short; use a dedicated timeout of 900 s.
    worker_polymarket_task_timeout_seconds: float = 900.0

    # ── Outbox / dispatcher ────────────────────────────────────────────────
    outbox_batch_size: int = 100
    outbox_poll_interval_seconds: float = 5.0
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 5
    outbox_metrics_poll_seconds: int = 30

    # ── Rate limiting ─────────────────────────────────────────────────────────
    newsapi_daily_limit: int = 100

    # ── Valkey ────────────────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379"

    # ── Backfill ─────────────────────────────────────────────────────────────
    backfill_enabled: bool = False
    backfill_from_date: str = ""
    backfill_to_date: str = ""
    backfill_sources: str = ""
    backfill_batch_delay_seconds: float = 0.5

    # ── Provider settings (operational params — overridable via ConfigMap) ───
    eodhd: EODHDProviderSettings = EODHDProviderSettings()
    finnhub: FinnhubProviderSettings = FinnhubProviderSettings()
    newsapi: NewsAPIProviderSettings = NewsAPIProviderSettings()
    sec_edgar: SECEdgarProviderSettings = SECEdgarProviderSettings()
    polymarket: PolymarketProviderSettings = PolymarketProviderSettings()
    http_client: HTTPClientSettings = HTTPClientSettings()

    # ── Observability (STANDARDS.md §5 — mandatory in every service) ─────────
    service_name: str = "content-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if db_url still contains default superuser credentials (D-7).

        Uses structlog so the warning is captured by the structured log pipeline
        in production log aggregators (F-SEC-001).
        """
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag."
            )
        if "postgres:postgres" in self.db_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "CONTENT_INGESTION_DB_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
