"""Service configuration via environment variables."""

from __future__ import annotations

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

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-data"
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
                    "MARKET_DATA_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
