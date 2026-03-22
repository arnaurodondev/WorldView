from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALERT_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    s1_portfolio_base_url: str = "http://localhost:8001"
    internal_service_token: str = ""
    watchlist_cache_ttl_seconds: int = 300
    alert_dedup_window_seconds: int = 3600
    pending_alert_ttl_days: int = 7
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db"
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    valkey_url: str = "redis://localhost:6379/0"


settings = Settings()
