"""Canonical service configuration for rag-chat (S8).

All values are sourced from environment variables via pydantic-settings.
Environment prefix: ``RAG_CHAT_``

Example::

    RAG_CHAT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
    RAG_CHAT_S1_INTERNAL_TOKEN=dev-token
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    deepinfra_api_key: SecretStr | None = None  # primary: configurable via completion_model (DEF-034)
    openrouter_api_key: SecretStr | None = None  # fallback: configurable via openrouter_completion_model (DEF-034)

    # ── Intent classification (DeepInfra GPU) ─────────────────────────────────
    # PLAN-0061 Wave D (2026-05-02): Llama-3.2-1B/3B are not available on this
    # DeepInfra account. Confirmed available: Meta-Llama-3.1-8B-Instruct-Turbo
    # (~100-200ms GPU, 8B param, ~$0.02/M tokens — sufficient for a 1-token
    # intent decision and the same model used for classification across S6/S8).
    deepinfra_classification_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

    # ── External reranker (Cohere — replaces bge-reranker-v2-m3 Ollama) ───────
    # WHY: bge-reranker-v2-m3 is not in the Ollama registry (ollama pull fails),
    # causing 100% reranker failure (permanent fusion_score sort fallback).
    # Cohere Rerank v2 provides ~300ms cross-encoder quality via REST API.
    cohere_api_key: SecretStr | None = None  # optional; fusion_score fallback when absent (DEF-034)

    # ── External embeddings (Jina AI — replaces S6/Ollama for query embedding) ─
    # When set, rag-chat embeds queries directly via Jina AI (1024-dim, ~100-300ms)
    # instead of proxying through S6 → Ollama bge-large (7-13s on CPU).
    # Jina embeddings-v3 is 1024-dim (same pgvector schema as bge-large).
    jina_api_key: SecretStr | None = None  # optional; S6/Ollama fallback when absent (DEF-034)

    # ── Completion model config (PRD-0016 §6.2, T-B-2-01) ────────────────────
    completion_provider: str = "deepinfra"  # RAG_CHAT_COMPLETION_PROVIDER
    completion_model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # RAG_CHAT_COMPLETION_MODEL
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

    # ── Circuit breaker (PLAN-0031 T-D-1-02, PLAN-0084 A-2) ──────────────────
    cb_enabled: bool = True
    cb_failure_threshold: int = 3
    cb_failure_window_seconds: int = 120
    # PLAN-0084 A-2: lowered from 3600 → 120s (F-X04 fix) and added probe-TTL
    # for SETNX stampede prevention (F-X01 fix).
    cb_cool_down_seconds: int = Field(default=120, ge=10, le=3600)  # RAG_CHAT_CB_COOL_DOWN_SECONDS
    cb_probe_ttl_seconds: int = Field(default=5, ge=1, le=30)  # RAG_CHAT_CB_PROBE_TTL_SECONDS

    # ── Citation accuracy cron (PLAN-0084 A-1) ────────────────────────────────
    # Set RAG_CHAT_CITATION_CRON_ENABLED=true to activate the weekly LLM-judge
    # cron that populates the rag_citation_accuracy Prometheus gauge.
    # Disabled by default to avoid unintended ~$0.50/run LLM cost on first deploy
    # (L5: flag-controlled rollout — same pattern as internal_jwt_skip_verification).
    citation_cron_enabled: bool = False  # RAG_CHAT_CITATION_CRON_ENABLED
    citation_judge_provider: Literal["deepinfra", "ollama"] = "deepinfra"  # RAG_CHAT_CITATION_JUDGE_PROVIDER
    citation_min_samples: int = Field(default=10, ge=1, le=500)  # RAG_CHAT_CITATION_MIN_SAMPLES
    citation_call_timeout_s: float = Field(default=15.0, gt=0.0, le=120.0)  # RAG_CHAT_CITATION_CALL_TIMEOUT_S
    citation_run_budget_s: float = Field(default=600.0, gt=0.0)  # RAG_CHAT_CITATION_RUN_BUDGET_S

    # ── Trust scoring weights (PLAN-0079 Wave C) ─────────────────────────────
    # The TrustScorer formula is additive:
    #   trust = w_source * source_authority + w_corroboration * corr_factor + w_extraction * extr_factor
    # Defaults chosen so a sec_10k item yields 0.4*1.0 + 0.1*0.5 + 0.1*0.5 = 0.50
    # (numerically stable, backward-compatible with existing fusion_score invariant).
    # Override via RAG_CHAT_TRUST_W_SOURCE / _CORROBORATION / _EXTRACTION env vars.
    trust_w_source: float = 0.4  # RAG_CHAT_TRUST_W_SOURCE
    trust_w_corroboration: float = 0.1  # RAG_CHAT_TRUST_W_CORROBORATION
    trust_w_extraction: float = 0.1  # RAG_CHAT_TRUST_W_EXTRACTION

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
        """Validate startup invariants: F-007 (skip_verification) + F-014 (whitespace coercion).

        DEF-028: Use case-insensitive APP_ENV comparison so "Production", "PRODUCTION",
        and "prod" all trigger the guard — prevents bypassing the check via env var casing.
        """
        # F-007: internal_jwt_skip_verification=True MUST NOT be used in production.
        # Prevents accidentally deploying with signature verification disabled.
        _app_env = os.environ.get("APP_ENV", "").strip().lower()
        if self.internal_jwt_skip_verification and _app_env in {"production", "prod"}:
            raise ValueError("internal_jwt_skip_verification MUST NOT be enabled in production")

        # F-014: Coerce whitespace-only database_url_read to None — functionally empty
        # DSN strings cause asyncpg connection errors at startup.
        if self.database_url_read is not None:
            raw = self.database_url_read.get_secret_value()
            if not raw or not raw.strip():
                object.__setattr__(self, "database_url_read", None)

        return self


__all__ = ["Settings"]
