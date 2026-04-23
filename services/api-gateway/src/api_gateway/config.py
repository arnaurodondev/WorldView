"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic import SecretStr  # — pydantic evaluates field types at runtime
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the api-gateway service (stateless BFF)."""

    model_config = SettingsConfigDict(
        env_prefix="API_GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Valkey (caching + rate limiting)
    valkey_url: str = "redis://localhost:6379/0"

    # OIDC (Zitadel Cloud) — all required; service refuses to start without them (R13)
    oidc_issuer_url: str  # e.g. https://<instance>.zitadel.cloud
    oidc_client_id: str
    oidc_client_secret: SecretStr
    oidc_audience: str  # usually same as client_id
    # Set to true in test/dev environments where Zitadel is not running.
    # OIDC discovery failure becomes a warning instead of a fatal error;
    # the gateway starts with internal-JWT-only auth (no external OIDC token validation).
    oidc_discovery_optional: bool = False

    # Internal JWT (RS256) — PEM-encoded RSA-2048 key pair
    internal_jwt_private_key: SecretStr  # never logged — SecretStr
    internal_jwt_public_key: str

    # Frontend
    frontend_url: str = "http://localhost:5173"
    cookie_secure: bool = True  # False only in local dev (override via API_GATEWAY_COOKIE_SECURE=false)

    # Downstream service URLs
    portfolio_url: str = "http://localhost:8001"
    market_ingestion_url: str = "http://localhost:8002"
    market_data_url: str = "http://localhost:8003"
    content_ingestion_url: str = "http://localhost:8004"
    content_store_url: str = "http://localhost:8005"
    nlp_pipeline_url: str = "http://localhost:8006"
    knowledge_graph_url: str = "http://localhost:8007"
    rag_chat_url: str = "http://localhost:8008"
    alert_url: str = "http://localhost:8010"

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # CORS
    # SEC-008: Port 3001 is the worldview-web frontend.  Port 3000 is unused and
    # could be attacker-controlled; it must not appear in the default allowlist.
    cors_origins: str = "http://localhost:5173,http://localhost:3001"

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "api-gateway"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
