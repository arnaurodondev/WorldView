"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Alert service (S10).

    All fields are read from environment variables prefixed with ``ALERT_``.
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

    # ── API Gateway ────────────────────────────────────────────────────────
    api_gateway_url: str = "http://api-gateway:8000"

    # ── S1 Portfolio dependency ────────────────────────────────────────────
    s1_portfolio_base_url: str = "http://localhost:8001"

    # ── Domain ─────────────────────────────────────────────────────────────
    alert_dedup_window_seconds: int = 300
    watchlist_cache_ttl_seconds: int = 300
    pending_alert_ttl_days: int = 7

    # Severity classification thresholds (PRD-0021 §6.5)
    alert_severity_critical_threshold: float = 0.85
    alert_severity_high_threshold: float = 0.65
    alert_severity_medium_threshold: float = 0.40

    # ── Security ───────────────────────────────────────────────────────────
    admin_token: str = ""

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # BP-183: Disable JTI replay check for internal-only services.
    # Alert receives forwarded user JWTs from rag-chat (S8) on briefing calls.
    # Re-checking the JTI here causes 401 because rag-chat already consumed it.
    jti_replay_check_enabled: bool = False

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
    # PRD-0025: S8 requires X-Internal-JWT (RS256-signed service JWT).  Set this
    # env var to a pre-signed long-lived service JWT.  Without it every briefing
    # call to S8 will return 401 (InternalJWTMiddleware rejects the missing header).
    s8_internal_jwt: str = ""
    # PRD-0025: S1 portfolio now requires X-Internal-JWT (RS256) — same pattern as S8.
    # Set this to a pre-signed long-lived service JWT (valid ~1 year for dev).
    s1_internal_jwt: str = ""
    s3_market_data_base_url: str = "http://market-data:8003"

    # ── Observability (STANDARDS.md §5 — mandatory in every service) ──────
    service_name: str = "alert"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _validate_startup(self) -> Settings:
        """Validate startup invariants: F-007 (skip_verification) + credential warnings."""
        # F-007: internal_jwt_skip_verification=True MUST NOT be used in production.
        # Prevents accidentally deploying with signature verification disabled.
        if self.internal_jwt_skip_verification and os.environ.get("APP_ENV") == "production":
            raise ValueError("internal_jwt_skip_verification MUST NOT be enabled in production")

        if not self.s8_internal_jwt:
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "s8_internal_jwt_not_set",
                message=(
                    "ALERT_S8_INTERNAL_JWT is not set. "
                    "The EmailScheduler will fail to call S8 /internal/v1/briefings (401). "
                    "Set this env var to a pre-signed RS256 service JWT to enable email digest generation."
                ),
            )
        if not self.s1_internal_jwt:
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "s1_internal_jwt_not_set",
                message=(
                    "ALERT_S1_INTERNAL_JWT is not set. "
                    "The S1Client will send no auth header — S1 Portfolio will return 401. "
                    "Set this env var to a pre-signed RS256 service JWT to enable watchlist lookups."
                ),
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "ALERT_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
