"""Service configuration via environment variables."""

from __future__ import annotations

import structlog
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Alert service (S10).

    All fields are read from environment variables prefixed with ``ALERT_``.
    Exception: ``INTERNAL_SERVICE_TOKEN`` is shared across services (no prefix).
    """

    model_config = SettingsConfigDict(
        env_prefix="ALERT_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # ── Server ─────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8010

    # ── Database ───────────────────────────────────────────────────────────
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db")
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

    # ── Kafka ──────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_consumer_group: str = "alert-service-group"
    kafka_watchlist_consumer_group: str = "alert-service-watchlist-group"

    # Consumed topics
    kafka_topic_signal: str = "nlp.signal.detected.v1"
    kafka_topic_graph_state: str = "graph.state.changed.v1"
    kafka_topic_contradiction: str = "intelligence.contradiction.v1"
    kafka_topic_watchlist: str = "portfolio.watchlist.updated.v1"

    # Produced topics
    kafka_topic_alert_delivered: str = "alert.delivered.v1"
    kafka_dlq_topic: str = "alert.dead-letter.v1"

    # ── Valkey ─────────────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379/0"

    # ── S1 Portfolio dependency ────────────────────────────────────────────
    s1_portfolio_base_url: str = "http://localhost:8001"
    internal_service_token: str = Field(default="", validation_alias="INTERNAL_SERVICE_TOKEN")

    # ── Domain ─────────────────────────────────────────────────────────────
    alert_dedup_window_seconds: int = 300
    watchlist_cache_ttl_seconds: int = 300
    pending_alert_ttl_days: int = 7

    # ── Security ───────────────────────────────────────────────────────────
    admin_token: str = ""

    # ── Outbox dispatcher ──────────────────────────────────────────────────
    dispatcher_poll_interval_s: float = 1.0
    dispatcher_batch_size: int = 50

    # ── Email provider ─────────────────────────────────────────────────────
    email_provider: str = "resend"  # resend | sendgrid | smtp
    email_from_address: str = ""
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # ── Email scheduler ────────────────────────────────────────────────────
    s8_base_url: str = "http://rag-chat:8008"
    s8_internal_token: str = ""
    s1_internal_token: str = ""
    s3_market_data_base_url: str = "http://market-data:8003"

    # ── Observability (STANDARDS.md §5 — mandatory in every service) ──────
    service_name: str = "alert"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "ALERT_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
