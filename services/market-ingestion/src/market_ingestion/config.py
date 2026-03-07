"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the market-ingestion service."""

    model_config = {"env_prefix": "MARKET_INGESTION_"}

    # Server
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ingestion_db"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"
