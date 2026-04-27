"""Service configuration via environment variables."""

from __future__ import annotations

import os

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
    storage_access_key: SecretStr  # Required — set MARKET_INGESTION_STORAGE_ACCESS_KEY env var
    storage_secret_key: SecretStr  # Required — set MARKET_INGESTION_STORAGE_SECRET_KEY env var
    storage_bucket: str = "market-ingestion"
    bronze_bucket: str = "market-bronze"
    canonical_bucket: str = "market-canonical"

    # Provider base URLs (operational — overridable without image rebuild)
    eodhd_base_url: str = "https://eodhd.com/api"

    # Provider API keys — SecretStr prevents accidental serialisation via
    # repr(), model_dump(), or error tracebacks (F-002 QA finding).
    # N-003: Default "demo" is intentional for local dev and CI testing.
    # The demo key supports EODHD's original 3 endpoints at low concurrency.
    # Tests use the demo key explicitly; set MARKET_INGESTION_EODHD_API_KEY to
    # a real key in production. Startup validator below emits a WARNING if unset.
    eodhd_api_key: SecretStr = SecretStr("demo")
    finnhub_api_key: SecretStr = SecretStr("")
    polygon_api_key: SecretStr = SecretStr("")  # — empty = Polygon disabled
    polygon_base_url: str = "https://api.polygon.io"
    alpha_vantage_api_key: SecretStr = SecretStr("")
    alpaca_api_key: SecretStr = SecretStr("")  # — empty = Alpaca disabled
    alpaca_secret_key: SecretStr = SecretStr("")
    alpaca_base_url: str = "https://data.alpaca.markets"
    alpaca_feed: str = "iex"  # "iex" (free, ~15min delayed) | "sip" (paid, real-time)

    # Routing weights (PRD-0032, ADR-032-02): comma-separated provider:weight pairs.
    # These env vars define priority ordering for each dataset+timeframe slot.
    # No DB table — config-backed only. Force-reload via POST /internal/v1/routing/reload.
    routing_ohlcv_intraday: str = "alpaca:100,polygon:80"  # timeframes: 1m,5m,15m,30m,1h,4h
    routing_ohlcv_eod: str = "yahoo_finance:100,eodhd:80"  # timeframes: 1d,1w,1M
    routing_quotes: str = "eodhd:100"
    routing_fundamentals: str = "eodhd:100"
    # Finnhub provides these for free — set to "finnhub:100,eodhd:80" to prefer Finnhub.
    routing_news_sentiment: str = "eodhd:100"
    routing_earnings_calendar: str = "eodhd:100"
    routing_insider_transactions: str = "eodhd:100"

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

    # Auth (PRD-0025 Wave D) — S9 api-gateway base URL for JWKS fetch
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag.",
            )
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
        if self.eodhd_api_key.get_secret_value() == "demo":
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "demo_eodhd_api_key",
                message=(
                    "EODHD API key is 'demo' — limited to demo endpoints only. "
                    "Set MARKET_INGESTION_EODHD_API_KEY for production use."
                ),
            )
        return self
