"""Service configuration via environment variables."""

from __future__ import annotations

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
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ingestion_db"
    database_url_read: str = ""  # Optional read-replica; falls back to database_url if empty

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "market-ingestion"
    bronze_bucket: str = "market-bronze"
    canonical_bucket: str = "market-canonical"

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
    dispatcher_max_attempts: int = 5

    # Observability (STANDARDS.md §8.3 — mandatory in every service)
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
