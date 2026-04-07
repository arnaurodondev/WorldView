"""Service configuration via environment variables."""

from __future__ import annotations

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the market-ingestion service."""

    model_config = SettingsConfigDict(
        env_prefix="MARKET_INGESTION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/ingestion_db")
    database_url_read: str = ""  # Optional read-replica; falls back to database_url if empty

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str  # Required — set MARKET_INGESTION_STORAGE_ACCESS_KEY env var
    storage_secret_key: str  # Required — set MARKET_INGESTION_STORAGE_SECRET_KEY env var
    storage_bucket: str = "market-ingestion"
    bronze_bucket: str = "market-bronze"
    canonical_bucket: str = "market-canonical"

    # Provider base URLs (operational — overridable without image rebuild)
    eodhd_base_url: str = "https://eodhd.com/api"

    # Provider API keys
    eodhd_api_key: str = "demo"
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    alpha_vantage_api_key: str = ""

    # Valkey / Redis
    valkey_url: str = "redis://localhost:6379/0"

    # Scheduler
    scheduler_tick_interval_seconds: float = 60.0
    scheduler_max_tasks_per_tick: int = 1000

    # Worker
    worker_batch_size: int = 10
    worker_lease_seconds: int = 300
    worker_concurrency: int = 4
    provider_http_timeout_seconds: float = 30.0

    # Dispatcher
    dispatcher_batch_size: int = 50
    dispatcher_poll_interval_seconds: float = 1.0
    # Lease >=30 s — typical Kafka publish <5 s; 6x safety margin prevents
    # concurrent dispatchers from re-claiming a stalled record.
    dispatcher_lease_seconds: int = 60
    dispatcher_max_attempts: int = 5

    # Internal service-to-service auth (QA-018)
    internal_service_token: str = ""

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_missing_internal_token(self) -> Settings:
        """Warn at startup if internal_service_token is unset (QA-018).

        Uses structlog so the warning is captured by the structured log pipeline
        in production log aggregators (F-SEC-001).
        """
        if not self.internal_service_token:
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "missing_internal_service_token",
                message=(
                    "MARKET_INGESTION_INTERNAL_SERVICE_TOKEN is not set — all mutating API "
                    "endpoints (POST /trigger, POST /backfill) will return 401. "
                    "Set this env var before deploying to production."
                ),
            )
        return self

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "MARKET_INGESTION_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self

    @model_validator(mode="after")
    def _warn_demo_eodhd_key(self) -> Settings:
        if self.eodhd_api_key == "demo":
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "demo_eodhd_api_key",
                message=(
                    "EODHD API key is 'demo' — limited to demo endpoints only. "
                    "Set MARKET_INGESTION_EODHD_API_KEY for production use."
                ),
            )
        return self
