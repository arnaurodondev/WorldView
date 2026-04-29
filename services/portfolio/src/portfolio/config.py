"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import AliasChoices, Field, SecretStr, model_validator
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

    # Database (R23 — read/write split)
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/portfolio_db")
    database_url_read: SecretStr = SecretStr("")  # Optional read-replica URL; falls back to database_url when empty
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

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

    # Internal JWT (RS256) — PRD-0025
    # S1 fetches the public key from S9's JWKS endpoint at startup.
    api_gateway_url: str = "http://api-gateway:8000"
    internal_jwt_issuer: str = Field(default="worldview-gateway")

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # SnapTrade brokerage sync (PRD-0022 §4.3, §12)
    # WHY PORTFOLIO_* listed first: docker-compose brokerage-sync sets bare SNAPTRADE_*
    # vars to "" (empty) via shell expansion when host env is unset. Putting the prefixed
    # alias first ensures the non-empty docker.env value wins over the empty bare var.
    snaptrade_client_id: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("PORTFOLIO_SNAPTRADE_CLIENT_ID", "SNAPTRADE_CLIENT_ID"),
    )
    snaptrade_consumer_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("PORTFOLIO_SNAPTRADE_CONSUMER_KEY", "SNAPTRADE_CONSUMER_KEY"),
    )
    snaptrade_redirect_uri: str = Field(
        default="http://localhost:3001/portfolio/brokerage/callback",
        validation_alias=AliasChoices("PORTFOLIO_SNAPTRADE_REDIRECT_URI", "SNAPTRADE_REDIRECT_URI"),
    )
    snaptrade_secret_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "PORTFOLIO_SNAPTRADE_SECRET_ENCRYPTION_KEY",
            "SNAPTRADE_SECRET_ENCRYPTION_KEY",
        ),
    )
    brokerage_sync_cycle_seconds: int = 14400  # 4 hours
    brokerage_sync_history_days: int = 730  # 2 years initial import
    # S3 (market-data) URL for instrument resolution fallback in BrokerageTransactionSyncWorker
    market_data_service_url: str = "http://market-data:8003"

    # Feedback subsystem (PLAN-0052 Wave D)
    # Screenshot URLs are stored as S3 keys / pre-signed URLs; the upload itself
    # is performed by the frontend via a pre-signed PUT (not yet implemented —
    # follow-up wave). The bucket and TTLs below are the source-of-truth for
    # the lifecycle policy that DevOps applies in worldview-gitops.
    feedback_s3_bucket: str = "worldview-feedback-screenshots"
    feedback_screenshot_ttl_days: int = 90
    feedback_console_logs_ttl_days: int = 7
    # F-Q1-04: anonymous (no-JWT) feedback submissions land under a
    # "platform support" tenant id. Admins read these via
    # ``GET /api/v1/feedback/submissions/anonymous`` (admin-only).
    # Defaults to the nil UUID — matches the gateway's issue_public_jwt()
    # tenant claim. Override via PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID
    # if you provision a dedicated tenant for anon traffic.
    feedback_anonymous_tenant_id: str = "00000000-0000-0000-0000-000000000000"

    # Observability (STANDARDS.md §8.3 — mandatory in every service)
    log_level: str = "INFO"
    log_json: bool = True
    log_format: str = "json"
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag."
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "PORTFOLIO_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self

    @model_validator(mode="after")
    def _warn_missing_snaptrade_credentials(self) -> Settings:
        """Warn at startup if SnapTrade credentials are unset (PRD-0022 F-23)."""
        if not self.snaptrade_client_id.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "missing_snaptrade_client_id",
                message=(
                    "SNAPTRADE_CLIENT_ID is not set — brokerage connection endpoints will fail. "
                    "Set this env var to enable SnapTrade brokerage sync."
                ),
            )
        if not self.snaptrade_secret_encryption_key:
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "missing_snaptrade_encryption_key",
                message=(
                    "SNAPTRADE_SECRET_ENCRYPTION_KEY is not set — snaptrade_user_secret will be "
                    "stored in plaintext (dev mode only). Generate a key with: "
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                ),
            )
        return self
