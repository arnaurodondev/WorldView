"""Service configuration via environment variables."""

from __future__ import annotations

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
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db"
    # Optional read replica URL. When set, read-only API queries are routed to this
    # DB instance (e.g. a streaming replica). When unset, reads use database_url.
    read_replica_url: str | None = None

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"

    # Observability (STANDARDS.md §8.3 — mandatory in every service)
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
