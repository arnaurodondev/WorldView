"""Canonical service configuration for rag-chat (S8).

All values are sourced from environment variables via pydantic-settings.
Environment prefix: ``RAG_CHAT_``

Example::

    RAG_CHAT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
    RAG_CHAT_S1_INTERNAL_TOKEN=dev-token
"""

from __future__ import annotations

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the rag-chat service (S8)."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_CHAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8008
    debug: bool = False

    # ── Database (R23 dual-URL) ───────────────────────────────────────────────
    database_url: SecretStr  # RAG_CHAT_DATABASE_URL — write primary
    database_url_read: SecretStr | None = None  # RAG_CHAT_DATABASE_URL_READ — read replica

    # ── Database pool sizing ──────────────────────────────────────────────────
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

    # ── Valkey ────────────────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379/0"

    # ── Ollama (local LLM container) ──────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_classification_model: str = "qwen2.5:3b"
    ollama_completion_model: str = "deepseek-r1:32b"  # emergency fallback only
    ollama_reranker_model: str = "bge-reranker-v2-m3"

    # ── LLM API providers (primary + fallback chain) ──────────────────────────
    deepinfra_api_key: str | None = None  # primary: deepseek-r1-distill-qwen-32b
    openrouter_api_key: str | None = None  # fallback: deepseek/deepseek-r1-distill-qwen-32b

    # ── Completion model config (PRD-0016 §6.2, T-B-2-01) ────────────────────
    completion_provider: str = "deepinfra"  # RAG_CHAT_COMPLETION_PROVIDER
    completion_model: str = "deepseek-r1-distill-qwen-32b"  # RAG_CHAT_COMPLETION_MODEL

    # ── Auth (PRD-0025): RS256 internal JWT via api-gateway JWKS ─────────────
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # ── Upstream services ─────────────────────────────────────────────────────
    s6_base_url: str = "http://nlp-pipeline:8006"
    s7_base_url: str = "http://knowledge-graph:8007"
    s3_base_url: str = "http://market-data:8003"
    s1_base_url: str = "http://portfolio:8001"
    s1_internal_token: str  # required — set via RAG_CHAT_S1_INTERNAL_TOKEN

    # ── Feature flags ─────────────────────────────────────────────────────────
    cypher_enabled: bool = False

    # ── Circuit breaker (PLAN-0031 T-D-1-02) ──────────────────────────────────
    cb_enabled: bool = True
    cb_failure_threshold: int = 3
    cb_failure_window_seconds: int = 120
    cb_cool_down_seconds: int = 3600

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_tenant: int = 10  # requests per minute per tenant
    upstream_timeout_seconds: float = 5.0

    # ── Observability (STANDARDS.md §8.3) ────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
    service_name: str = "rag-chat"

    @model_validator(mode="after")
    def _validate_startup(self) -> Settings:
        """Warn at startup about default credentials."""
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "RAG_CHAT_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self


__all__ = ["Settings"]
