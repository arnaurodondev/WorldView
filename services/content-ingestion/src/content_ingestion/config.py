"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Content Ingestion service (S4)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # External API keys
    EODHD_API_KEY: str = ""
    SEC_EDGAR_USER_AGENT: str = "worldview/1.0 contact@worldview.example"
    FINNHUB_API_KEY: str = ""
    NEWSAPI_KEY: str = ""

    # Database
    CONTENT_INGESTION_DB_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_OUTBOX_TOPIC: str = "content.article.raw.v1"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "worldview-bronze"

    # Security
    ADMIN_TOKEN: str = ""

    # Scheduler / outbox
    SCHEDULER_INTERVAL_SECONDS: int = 300
    OUTBOX_BATCH_SIZE: int = 100
    OUTBOX_POLL_INTERVAL_SECONDS: int = 5
    MAX_RETRIES: int = 3
    OUTBOX_METRICS_POLL_SECONDS: int = 30

    # Rate limiting
    NEWSAPI_DAILY_LIMIT: int = 100

    # Valkey
    VALKEY_URL: str = "redis://localhost:6379"

    # Backfill — historical ingestion via source API date range
    # Set BACKFILL_ENABLED=true to run a one-shot historical fetch on startup before
    # switching to steady-state polling.  BACKFILL_FROM_DATE / BACKFILL_TO_DATE are
    # ISO-8601 date strings (YYYY-MM-DD).  Leave BACKFILL_TO_DATE empty to default to
    # yesterday.  BACKFILL_SOURCES is a comma-separated subset of:
    #   eodhd, sec_edgar, finnhub, newsapi
    # Leave empty to backfill all configured sources.
    # BACKFILL_BATCH_DELAY_SECONDS adds a sleep between paginated requests during backfill
    # to avoid hammering external APIs.
    BACKFILL_ENABLED: bool = False
    BACKFILL_FROM_DATE: str = ""  # e.g. "2024-01-01"
    BACKFILL_TO_DATE: str = ""  # e.g. "2025-12-31"; defaults to yesterday
    BACKFILL_SOURCES: str = ""  # e.g. "eodhd,finnhub"; empty = all
    BACKFILL_BATCH_DELAY_SECONDS: float = 0.5

    @property
    def database_url(self) -> str:
        """Backward-compatible alias used by alembic/env.py."""
        return self.CONTENT_INGESTION_DB_URL
