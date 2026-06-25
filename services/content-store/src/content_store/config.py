"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Content Store service (S5).

    All fields are read from environment variables prefixed with
    ``CONTENT_STORE_`` (set by ``env_prefix``).
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTENT_STORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server ─────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8005
    debug: bool = False

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db")
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

    # ── Kafka ──────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    kafka_input_topic: str = "content.article.raw.v1"
    kafka_output_topic: str = "content.article.stored.v1"
    kafka_consumer_group: str = "content-store-consumer"

    # ── Kafka static membership (KIP-345 / PRD-0113 FR-9 / BP-703) ──────────────
    # Opt-in stable consumer identity. Empty string ("") = dynamic membership
    # (the Kafka default, a no-op). When set per-replica (e.g. "content-store-0"),
    # a restarting consumer rejoins with its stable identity instead of triggering
    # a full group rebalance — preventing the controller-overload storm of BP-703.
    # One field per consumer process so each can carry a distinct identity.
    kafka_article_consumer_instance_id: str = ""
    kafka_dedup_consumer_instance_id: str = ""

    # ── MinIO (object storage) ─────────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bronze_bucket: str = "worldview-bronze"
    minio_silver_bucket: str = "worldview-silver"
    minio_secure: bool = False

    # ── Valkey (LSH bands) ─────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379"

    # ── Security ───────────────────────────────────────────────────────────────
    admin_token: str = ""
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # ── Outbox dispatcher ──────────────────────────────────────────────────────
    outbox_batch_size: int = 100
    outbox_poll_interval_seconds: float = 5.0
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 5
    outbox_metrics_poll_seconds: int = 30

    # ── MinHash / LSH ──────────────────────────────────────────────────────────
    minhash_num_perm: int = 128
    lsh_num_bands: int = 4
    lsh_rows_per_band: int = 32

    # ── LSH time windows (days) per source type ────────────────────────────────
    lsh_window_news_days: int = 7
    lsh_window_filings_days: int = 180
    lsh_window_transcripts_days: int = 60
    lsh_window_research_days: int = 30
    lsh_window_press_release_days: int = 14

    # ── Observability ──────────────────────────────────────────────────────────
    service_name: str = "content-store"
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
                "Set APP_ENV != 'production' or remove the flag."
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "CONTENT_STORE_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
