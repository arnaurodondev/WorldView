"""Service configuration via environment variables."""

from __future__ import annotations

import warnings

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the portfolio service."""

    model_config = SettingsConfigDict(
        env_prefix="PORTFOLIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    service_name: str = "portfolio"
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/portfolio_db"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    kafka_schema_registry_basic_auth: str = ""
    kafka_auto_register_schemas: bool = True

    # Kafka topics (produced)
    topic_portfolio_events: str = "portfolio.events.v1"

    # Kafka topics (consumed)
    topic_instrument_created: str = "market.instrument.created"
    topic_instrument_updated: str = "market.instrument.updated"
    consumer_group_instrument: str = "portfolio-instrument-sync"

    # Outbox dispatcher
    dispatcher_immediate_batch_size: int = 100
    dispatcher_poll_interval_seconds: float = 5.0
    dispatcher_lease_seconds: int = 30
    dispatcher_max_attempts: int = 10
    dispatcher_backoff_base_seconds: float = 1.0

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str  # Required — set PORTFOLIO_STORAGE_ACCESS_KEY env var
    storage_secret_key: str  # Required — set PORTFOLIO_STORAGE_SECRET_KEY env var

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"
    watchlist_cache_ttl_seconds: int = 300

    # Internal service-to-service auth (S10 → S1)
    internal_service_token: str = ""

    # Observability (STANDARDS.md §8.3 — mandatory in every service)
    log_level: str = "INFO"
    log_json: bool = True
    log_format: str = "json"
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_missing_internal_token(self) -> Settings:
        """Warn at startup if internal_service_token is unset (plan T-E3-3-02)."""
        if not self.internal_service_token:
            warnings.warn(
                "PORTFOLIO_INTERNAL_SERVICE_TOKEN is not set — all internal API endpoints "
                "will return 401. Set this env var before deploying to production.",
                stacklevel=2,
            )
        return self
