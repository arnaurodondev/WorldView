"""Canonical service configuration for rag-chat (S8).

All values are sourced from environment variables via pydantic-settings.
Environment prefix: ``RAG_CHAT_``

Example::

    RAG_CHAT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
    RAG_CHAT_S1_INTERNAL_TOKEN=dev-token
"""

from __future__ import annotations

import os

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
    ollama_classification_model: str = "qwen3:0.6b"
    ollama_completion_model: str = "deepseek-r1:32b"  # emergency fallback only
    ollama_reranker_model: str = "bge-reranker-v2-m3"

    # ── LLM API providers (primary + fallback chain) ──────────────────────────
    deepinfra_api_key: str | None = None  # primary: configurable via completion_model
    openrouter_api_key: str | None = None  # fallback: configurable via openrouter_completion_model

    # ── Intent classification (DeepInfra GPU) ─────────────────────────────────
    # PLAN-0052 platform-QA round 5 (2026-05-01): switched default 8B → 1B.
    # Llama-3.2-1B-Instruct is ~6x smaller, completes in ~1.2s, and is more
    # than capable of the small classification task ("which intent template
    # does this query map to?"). Live probe confirmed availability on our
    # DeepInfra account (the 8B was the only model documented as confirmed
    # in project memory, but the lowercase `llama` path unlocks the 1B/3B
    # variants too). Saves ~80% on classification tokens vs the 8B.
    # WHY 1B over 3B: classification is a 1-token decision; the 1B's accuracy
    # is sufficient and the cost/latency floor matters more here. We keep 3B
    # available as a config override for installations that need higher
    # accuracy (e.g. ambiguous multi-intent queries).
    deepinfra_classification_model: str = "meta-llama/Llama-3.2-1B-Instruct"

    # ── External reranker (Cohere — replaces bge-reranker-v2-m3 Ollama) ───────
    # WHY: bge-reranker-v2-m3 is not in the Ollama registry (ollama pull fails),
    # causing 100% reranker failure (permanent fusion_score sort fallback).
    # Cohere Rerank v2 provides ~300ms cross-encoder quality via REST API.
    cohere_api_key: str | None = None  # optional; fusion_score fallback when absent

    # ── External embeddings (Jina AI — replaces S6/Ollama for query embedding) ─
    # When set, rag-chat embeds queries directly via Jina AI (1024-dim, ~100-300ms)
    # instead of proxying through S6 → Ollama bge-large (7-13s on CPU).
    # Jina embeddings-v3 is 1024-dim (same pgvector schema as bge-large).
    jina_api_key: str | None = None  # optional; S6/Ollama fallback when absent

    # ── Completion model config (PRD-0016 §6.2, T-B-2-01) ────────────────────
    completion_provider: str = "deepinfra"  # RAG_CHAT_COMPLETION_PROVIDER
    completion_model: str = "Qwen/Qwen3-32B"  # RAG_CHAT_COMPLETION_MODEL
    # OpenRouter fallback model — configurable independently from the DeepInfra primary.
    openrouter_completion_model: str = "deepseek/deepseek-r1-distill-qwen-32b"  # RAG_CHAT_OPENROUTER_COMPLETION_MODEL

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
    s5_base_url: str = "http://alert:8010"  # Alert service (S5) — used by BriefingContextGatherer
    # Deprecated (PRD-0025): S1 Portfolio now uses X-Internal-JWT (RS256) propagated
    # from the ContextVar set by InternalJWTMiddleware. This field is kept with a
    # default to avoid startup ValidationError on existing deployments, but is unused.
    s1_internal_token: str = ""

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
        """Validate startup invariants: F-007 (skip_verification) + F-014 (whitespace coercion) + credential warning."""
        # F-007: internal_jwt_skip_verification=True MUST NOT be used in production.
        # Prevents accidentally deploying with signature verification disabled.
        if self.internal_jwt_skip_verification and os.environ.get("APP_ENV") == "production":
            raise ValueError("internal_jwt_skip_verification MUST NOT be enabled in production")

        # F-014: Coerce whitespace-only database_url_read to None — functionally empty
        # DSN strings cause asyncpg connection errors at startup.
        if self.database_url_read is not None:
            raw = self.database_url_read.get_secret_value()
            if not raw or not raw.strip():
                object.__setattr__(self, "database_url_read", None)

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
