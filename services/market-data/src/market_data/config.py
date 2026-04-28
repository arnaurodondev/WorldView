"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the market-data service."""

    model_config = SettingsConfigDict(
        env_prefix="MARKET_DATA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db")
    # Optional read replica URL. When set, read-only API queries are routed to this
    # DB instance (e.g. a streaming replica). When unset, reads use database_url.
    read_replica_url: SecretStr | None = None

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: SecretStr  # Required — set MARKET_DATA_STORAGE_ACCESS_KEY env var
    storage_secret_key: SecretStr  # Required — set MARKET_DATA_STORAGE_SECRET_KEY env var

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"

    # Internal auth (PRD-0025): S9 api-gateway base URL for JWKS endpoint.
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # F-012: When False, disables JTI replay detection in InternalJWTMiddleware.
    # Market-data is called multiple times per request (quotes + fundamentals)
    # with the same JWT from rag-chat's gather_instrument_context(). Set to
    # False in dev so parallel calls to market-data share a single JWT without
    # triggering replay rejection. Keep True in production with proper JWT rotation.
    internal_jwt_jti_check_enabled: bool = False

    # Intraday resampling source timeframe (BP-254 — must be config-driven, not hardcoded).
    # Valid values: "1m", "5m", "15m", "1h". Changing this migrates the entire
    # ResampledOHLCVUseCase + IntradayResamplingConsumer pipeline to the new finest
    # granularity without any code change.
    intraday_source_tf: str = "1m"

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-data"
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
                    "MARKET_DATA_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
