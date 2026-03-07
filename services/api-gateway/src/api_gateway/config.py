"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the api-gateway service (stateless BFF)."""

    model_config = {"env_prefix": "API_GATEWAY_"}

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Valkey (caching + rate limiting)
    valkey_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    # Downstream service URLs
    portfolio_url: str = "http://localhost:8001"
    market_ingestion_url: str = "http://localhost:8002"
    market_data_url: str = "http://localhost:8003"
    content_ingestion_url: str = "http://localhost:8004"
    content_store_url: str = "http://localhost:8005"
    nlp_pipeline_url: str = "http://localhost:8006"
    knowledge_graph_url: str = "http://localhost:8007"
    rag_chat_url: str = "http://localhost:8008"

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
