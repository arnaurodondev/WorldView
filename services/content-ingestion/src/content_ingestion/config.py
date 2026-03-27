"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    )

    # ── External API keys (no CONTENT_INGESTION_ prefix — shared variables) ──
    eodhd_api_key: str = ""
    sec_edgar_user_agent: str = "worldview/1.0 contact@worldview.example"
    finnhub_api_key: str = ""
    newsapi_key: str = ""

    # ── Database ──────────────────────────────────────────────────────────────
    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db"

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
    # Inter-service token shared across all services (no CONTENT_INGESTION_ prefix)
    internal_service_token: str = Field(default="", validation_alias="INTERNAL_SERVICE_TOKEN")

    # ── Scheduler / outbox ────────────────────────────────────────────────────
    scheduler_interval_seconds: int = 300
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

    # ── Observability (STANDARDS.md §5 — mandatory in every service) ─────────
    service_name: str = "content-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
