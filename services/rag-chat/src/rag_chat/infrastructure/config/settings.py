"""Service configuration — all values sourced from environment variables (pydantic-settings).

Environment prefix: ``RAG_CHAT_``

Example::

    RAG_CHAT_RAG_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
    RAG_CHAT_S1_INTERNAL_TOKEN=dev-token
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RagChatSettings(BaseSettings):
    """Runtime configuration for the rag-chat service (S8)."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_CHAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8008
    debug: bool = False

    # ── Database (R23 dual-URL) ───────────────────────────────────────────────
    rag_db_url: str  # RAG_CHAT_RAG_DB_URL — write primary
    rag_db_url_read: str | None = None  # RAG_CHAT_RAG_DB_URL_READ — read replica

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

    # ── Upstream services ─────────────────────────────────────────────────────
    s6_base_url: str = "http://nlp-pipeline:8006"
    s7_base_url: str = "http://knowledge-graph:8007"
    s3_base_url: str = "http://market-data:8003"
    s1_base_url: str = "http://portfolio:8001"
    s1_internal_token: str  # required — set via RAG_CHAT_S1_INTERNAL_TOKEN

    # ── Feature flags ─────────────────────────────────────────────────────────
    cypher_enabled: bool = False

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_tenant: int = 10  # requests per minute per tenant
    upstream_timeout_seconds: float = 5.0

    # ── Observability (STANDARDS.md §8.3) ────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
    service_name: str = "rag-chat"
