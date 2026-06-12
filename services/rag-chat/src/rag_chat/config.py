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

import structlog
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


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
    deepinfra_classification_model: str = "Qwen/Qwen3.5-9B"

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
    completion_model: str = "deepseek-ai/DeepSeek-V4-Flash-Thinking"  # RAG_CHAT_COMPLETION_MODEL
    # OpenRouter fallback model — configurable independently from the DeepInfra primary.
    openrouter_completion_model: str = "deepseek/deepseek-r1-distill-qwen-32b"  # RAG_CHAT_OPENROUTER_COMPLETION_MODEL

    # FIX-LIVE-X (2026-05-25): Q6 second-turn `chat_with_tools` calls regularly
    # exceed the previous 30s hardcoded budget when the completion model is the
    # heavier Qwen3-235B-A22B and the message stack carries 5+ tool results
    # (e.g. screen_universe + N fundamentals).  The timeout fired *before* the
    # HTTP request was even dispatched (asyncio.wait_for), and TimeoutError's
    # empty str() produced a silent `provider_chat_with_tools_failed` log.
    # Default raised to 90s; lowered in tests via env var when needed.
    deepinfra_tool_call_timeout_seconds: float = 90.0  # RAG_CHAT_DEEPINFRA_TOOLCALL_TIMEOUT

    # PLAN-0104 W43 / BP-NEW: same-provider model fallback for second-turn
    # synthesis.  When DeepInfra returns HTTP 200 + empty SSE (zero content
    # frames) on a long multi-tool synthesis with the primary completion
    # model, the adapter retries once with this lighter chat model on the
    # SAME provider.  Required because most live deployments only have the
    # DeepInfra key wired (W40 cross-provider failover is a no-op).  Set
    # to "" via env var to disable.
    deepinfra_stream_chat_fallback_model: str = (
        "deepseek-ai/DeepSeek-V4-Flash"  # RAG_CHAT_DEEPINFRA_STREAM_FALLBACK_MODEL
    )

    # FIX-LIVE-EE (2026-05-25): Provider-chain exponential backoff for the
    # iteration-0 chat_with_tools turn. Q4 v1 + similar queries surfaced a
    # transient DeepInfra failure rate of 60-100% under chained-test load (5x
    # same-query within ~10s) — most likely 429s and transient 5xx. Without
    # retry, a single transient failure flips the 60s Valkey negative cache,
    # masking what would otherwise be a 2-second recovery window. We retry the
    # SAME provider up to N times with exponential backoff BEFORE marking it
    # bad and falling back to the next provider in the chain.
    #
    # Defaults: 2 retries → delays of 1s, 2s before fallback.
    # Setting ATTEMPTS to 0 disables the retry entirely (legacy behaviour).
    provider_retry_attempts: int = Field(default=2, ge=0, le=5)  # RAG_CHAT_PROVIDER_RETRY_ATTEMPTS
    provider_retry_backoff_base: float = Field(default=1.0, gt=0.0, le=10.0)  # RAG_CHAT_PROVIDER_RETRY_BACKOFF_BASE

    # ── PLAN-0107 — Agent loop soft-budget knobs (env-configurable) ──────────
    #
    # WHY env-configurable: pre-PLAN-0107 these were hardcoded inside the
    # ``AgentBudget`` dataclass (max_tool_latency_s=30.0, max_consecutive_errors=2).
    # Live chat-eval runs showed those defaults systematically starved deep,
    # multi-round financial-research queries: a single TSLA-vs-NVDA compare
    # easily burned 30s across rerank + 3-4 tool calls, and 2 consecutive
    # all-fail rounds was too eager to surrender when the LLM was making
    # legitimate fallback attempts (e.g. screener → search_documents → claims).
    # The new defaults (90s / 3 errors) align with the FIX-LIVE-X DeepInfra
    # tool-call timeout (90s) and give the ReAct loop one extra retry budget
    # before surrendering. Env vars let ops dial these per-environment without
    # a redeploy.
    #
    # ``chat_max_tool_latency_s``: CUMULATIVE wall-clock across all tool
    # rounds in a single turn. When the sum exceeds this we inject a
    # surrender message and stop the loop. RAG_CHAT_MAX_TOOL_LATENCY_S.
    chat_max_tool_latency_s: float = Field(
        default=90.0,
        validation_alias="RAG_CHAT_MAX_TOOL_LATENCY_S",
    )
    # ``chat_max_consecutive_errors``: number of back-to-back iterations where
    # EVERY tool returned None/empty before the orchestrator gives up. Set to
    # 3 (was 2) so the LLM has one extra retry budget before surrender.
    # RAG_CHAT_MAX_CONSECUTIVE_ERRORS.
    chat_max_consecutive_errors: int = Field(
        default=3,
        validation_alias="RAG_CHAT_MAX_CONSECUTIVE_ERRORS",
    )

    # ── Auth (PRD-0025): RS256 internal JWT via api-gateway JWKS ─────────────
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # PLAN-0094 W2 follow-up (BP-303 variant): shared secret for the brief
    # pre-generation worker to mint an X-Internal-JWT via S9's
    # ``POST /internal/v1/service-token``. Without this, the worker calls S1/S6/S7
    # with no JWT, gets 401, and produces empty briefs (silent fail).
    # Empty default keeps the worker functional for tests / cold dev (the
    # adapter falls back to ``POST /v1/auth/dev-login`` when this is blank).
    service_account_token: SecretStr = SecretStr("")  # RAG_CHAT_SERVICE_ACCOUNT_TOKEN

    # ── Upstream services ─────────────────────────────────────────────────────
    s6_base_url: str = "http://nlp-pipeline:8006"
    s7_base_url: str = "http://knowledge-graph:8007"
    s3_base_url: str = "http://market-data:8003"
    s1_base_url: str = "http://portfolio:8001"
    s5_base_url: str = "http://alert:8010"  # Alert service (S5) — used by BriefingContextGatherer
    # Deprecated (PRD-0025): S1 Portfolio now uses X-Internal-JWT (RS256) propagated
    # from the ContextVar set by InternalJWTMiddleware. This field is kept with a
    # default to avoid startup ValidationError on existing deployments, but is unused.
    # S-004: SecretStr prevents the token from appearing in logs, repr(), or __str__.
    s1_internal_token: SecretStr = SecretStr("")  # RAG_CHAT_S1_INTERNAL_TOKEN

    # ── Knowledge Graph internal URL (PLAN-0074 Wave F) ──────────────────────
    # Used by EntityContextClient to load entity intelligence context.
    # WHY separate from s7_base_url: EntityContextClient calls /internal/v1/...
    # endpoints that use the same S7 service; separating allows routing to a
    # different host (e.g. internal VPC DNS) without affecting the existing
    # s7_client calls used by the retrieval pipeline.
    kg_internal_base_url: str = "http://knowledge-graph:8007"  # RAG_CHAT_KG_INTERNAL_BASE_URL

    # ── Circuit breaker (PLAN-0031 T-D-1-02, PLAN-0084 A-2) ──────────────────
    cb_enabled: bool = True
    cb_failure_threshold: int = 3
    cb_failure_window_seconds: int = 120
    # PLAN-0084 A-2: lowered from 3600 → 120s (F-X04 fix) and added probe-TTL
    # for SETNX stampede prevention (F-X01 fix).
    cb_cool_down_seconds: int = Field(default=120, ge=10, le=3600)  # RAG_CHAT_CB_COOL_DOWN_SECONDS
    cb_probe_ttl_seconds: int = Field(default=5, ge=1, le=30)  # RAG_CHAT_CB_PROBE_TTL_SECONDS

    # ── Citation accuracy cron (PLAN-0084 A-1, PLAN-0107) ─────────────────────
    # Set RAG_CHAT_CITATION_CRON_ENABLED=true to activate the daily LLM-judge
    # cron that populates the rag_citation_accuracy_24h Prometheus gauge.
    # Disabled by default to avoid unintended ~$0.50/run LLM cost on first deploy
    # (L5: flag-controlled rollout — same pattern as internal_jwt_skip_verification).
    citation_cron_enabled: bool = False  # RAG_CHAT_CITATION_CRON_ENABLED
    citation_judge_provider: Literal["deepinfra", "ollama"] = "deepinfra"  # RAG_CHAT_CITATION_JUDGE_PROVIDER
    # A-006: configurable citation judge model so production can use a cheaper/faster
    # model than the main completion model.  Default matches the classification model
    # (8B Instruct — confirmed available on the DeepInfra account in MEMORY.md).
    citation_judge_model: str = "deepseek-ai/DeepSeek-V4-Flash"  # RAG_CHAT_CITATION_JUDGE_MODEL
    citation_min_samples: int = Field(default=10, ge=1, le=500)  # RAG_CHAT_CITATION_MIN_SAMPLES
    citation_call_timeout_s: float = Field(default=15.0, gt=0.0, le=120.0)  # RAG_CHAT_CITATION_CALL_TIMEOUT_S
    citation_run_budget_s: float = Field(default=600.0, gt=0.0)  # RAG_CHAT_CITATION_RUN_BUDGET_S

    # F-NEW-015 Option B — defence-in-depth timeout for the entity-grounding
    # rewrite path. Iter-13 produced a 90s end-to-end timeout because the
    # rewrite stream_chat ran unbounded (15-60s per invocation, combined with
    # the prior synthesis budget). Default 15s aligns with the ceiling
    # identified by the iter-13 investigation. When this fires the original
    # synthesised response is returned with an [unverified] banner so the
    # user still gets the substantive answer.  Override via
    # RAG_CHAT_ENTITY_GROUNDING_REWRITE_TIMEOUT_SECONDS.
    entity_grounding_rewrite_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)

    # ── Trust scoring weights (PLAN-0079 Wave C) ─────────────────────────────
    # The TrustScorer formula is additive:
    #   trust = w_source * source_authority + w_corroboration * corr_factor + w_extraction * extr_factor
    # Defaults chosen so a sec_10k item yields 0.4*1.0 + 0.1*0.5 + 0.1*0.5 = 0.50
    # (numerically stable, backward-compatible with existing fusion_score invariant).
    # Override via RAG_CHAT_TRUST_W_SOURCE / _CORROBORATION / _EXTRACTION env vars.
    trust_w_source: float = 0.4  # RAG_CHAT_TRUST_W_SOURCE
    trust_w_corroboration: float = 0.1  # RAG_CHAT_TRUST_W_CORROBORATION
    trust_w_extraction: float = 0.1  # RAG_CHAT_TRUST_W_EXTRACTION

    # ── Layer 2 injection classifier availability policy ─────────────────────
    # BUG-FIX (DeepInfra 402 outage): when the Layer 2 LLM injection classifier
    # CANNOT RUN (provider unavailable / transport error — HTTP 402/429/5xx,
    # connect or network error), this flag controls the closed-vs-open policy.
    #
    #   False (default) → fail CLOSED-but-HONEST: reject the request, but with an
    #     accurate ``CLASSIFIER_UNAVAILABLE`` error ("input safety check
    #     temporarily unavailable, please retry") — NEVER the misleading
    #     "Semantic injection detected".
    #   True            → fail OPEN: let the request through (Layer 1 regex/PII
    #     already ran). Use ONLY when continuity of service is judged to outweigh
    #     the marginal risk of a semantic-only injection slipping past Layer 2
    #     during a provider outage. We NEVER default to this.
    #
    # The classifier reads ``RAG_CHAT_CLASSIFIER_FAIL_OPEN`` from the environment
    # per-call (same hot-toggle pattern as RAG_COMPLETION_CACHE_DISABLED /
    # DEBUG_SKIP_CLASSIFIER) so ops can flip it during an incident without a
    # redeploy. This field documents the knob and keeps it discoverable via
    # Settings. NOTE: a GENUINE injection verdict is always rejected regardless
    # of this flag — it only governs the "could not run" path.
    classifier_fail_open: bool = False  # RAG_CHAT_CLASSIFIER_FAIL_OPEN

    # Bounded retry on a transient classifier transport failure BEFORE declaring
    # the classifier unavailable. 0 disables retries (legacy behaviour). Kept
    # small (1) so a real outage surfaces fast instead of multiplying latency.
    classifier_retry_attempts: int = Field(
        default=1, ge=0, le=3, validation_alias="RAG_CHAT_CLASSIFIER_RETRY_ATTEMPTS"
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_tenant: int = 10  # requests per minute per tenant
    upstream_timeout_seconds: float = 5.0

    # ── Brief pre-generation (PLAN-0094 W2) ───────────────────────────────────
    # APScheduler-driven worker pre-generates morning briefs for active users
    # (identified via Valkey sorted-set ``active_users`` populated by S9 auth
    # middleware in W1).  The handler falls back to a last-known-good key if
    # regeneration fails so users never see a 503 on a cold cache miss.
    brief_pregen_enabled: bool = True  # RAG_CHAT_BRIEF_PREGEN_ENABLED
    brief_pregen_interval_hours: int = Field(default=24, ge=1, le=168)
    brief_pregen_active_window_days: int = Field(default=7, ge=1, le=90)
    brief_pregen_batch_size: int = Field(default=50, ge=1, le=500)
    brief_pregen_concurrency: int = Field(default=4, ge=1, le=20)
    brief_fresh_ttl_hours: int = Field(default=30, ge=1, le=168)
    brief_last_good_ttl_days: int = Field(default=7, ge=1, le=30)

    # ── Agentic brief generator (PLAN-0099 Wave C — experimental) ────────────
    # When True, the morning-brief route uses the AgenticBriefGenerator (an
    # iterative LLM tool-use loop) instead of the single-turn standard
    # generator. Off by default; intended for A/B comparison only. The
    # agentic path falls back to the standard generator on any exception or
    # if the per-generation tool-call budget is exhausted.
    brief_agentic_enabled: bool = False  # RAG_CHAT_BRIEF_AGENTIC_ENABLED
    brief_agentic_max_tool_calls: int = Field(default=8, ge=1, le=32)  # RAG_CHAT_BRIEF_AGENTIC_MAX_TOOL_CALLS

    # ── Brief context truncation + low-context refusal (PLAN-0099 Wave B) ────
    # Per-section caps applied by ``BriefContextFormatter`` before the prompt
    # is rendered.  Defaults raised from 8/6/5 (the audit-flagged settings
    # that hid tail signals on high-volume news days — BP-600) to 12/10/8.
    # Adjusting upward beyond these defaults is safe up to the prompt's
    # ~2000-token budget; bump cautiously and watch
    # ``brief_context_availability_score`` for regressions.
    brief_news_limit: int = Field(default=12, ge=1, le=64)  # BRIEF_NEWS_LIMIT
    brief_events_limit: int = Field(default=10, ge=1, le=64)  # BRIEF_EVENTS_LIMIT
    brief_alerts_limit: int = Field(default=8, ge=1, le=32)  # BRIEF_ALERTS_LIMIT
    # Refusal-on-low-context threshold: when the gatherer's weighted score
    # (see brief_diagnostics.compute_context_availability_score) falls below
    # this value, the generator skips the LLM call and returns a
    # "Limited data available today" lead built from whatever sections did
    # populate.  Setting to 0.0 disables the refusal entirely.
    brief_min_context_score: float = Field(default=0.3, ge=0.0, le=1.0)  # BRIEF_MIN_CONTEXT_SCORE
    # Headline-similarity threshold for ``_dedupe_news`` — articles whose
    # titles share a prefix or share >= this fraction of token overlap are
    # collapsed; the highest-display_relevance_score copy wins.
    brief_news_dedupe_threshold: float = Field(default=0.85, ge=0.0, le=1.0)

    # ── Follow-up suggestions SSE event ──────────────────────────────────────
    # When True (default) the orchestrator emits a ``suggestions`` SSE event
    # after the final answer with 3 deterministically-templated follow-up
    # questions (zero extra LLM calls — see application/services/suggestions.py).
    # NOTE: the orchestrator reads RAG_CHAT_SUGGESTIONS_ENABLED from the
    # environment per-call (same hot-toggle pattern as
    # RAG_COMPLETION_CACHE_DISABLED); this field documents the knob and keeps
    # it discoverable via Settings.
    suggestions_enabled: bool = True  # RAG_CHAT_SUGGESTIONS_ENABLED

    # ── Entity resolver tuning (F-LIVE-NEW-001) ──────────────────────────────
    # Stop-words stripped from the query string BEFORE the S7 alias fuzzy
    # match so generic English fragments ("space", "sector", "industry") do not
    # spuriously collide with canonical entities (e.g. "AI semiconductor space"
    # → SpaceX). The list is intentionally configurable via env var so future
    # tuning does not require a code change. The default below covers the
    # observed false-positives plus common stop-words and ultra-generic
    # industry tokens that have no business resolving to a single entity.
    #
    # RAG_CHAT_RESOLVER_STOP_WORDS — comma-separated list, e.g.
    #   RAG_CHAT_RESOLVER_STOP_WORDS="space,sector,industry,..."
    resolver_stop_words: str = Field(
        # F-CR-010 (iter-10): removed "ai" from the default list. The original
        # motivation was the "AI semiconductor space → SpaceX" false-positive,
        # but the 0.75 absolute similarity floor + 0.15 delta gate added in the
        # same F-LIVE-NEW-001 commit already reject that hit (SpaceX surfaced
        # at sim 0.62, well below the floor). Keeping "ai" stripped silently
        # broke two-token Ai-prefixed canonicals (Ai Group, Ai Holdings) by
        # collapsing them to a single token that then failed alias-search.
        #
        # NOTE: "tech" and "energy" are kept for now but are similarly broad —
        # they currently break "Tech Mahindra" and "Energy Transfer" if those
        # canonicals ever land in the alias index. Track via F-CR-010 follow-up
        # if those resolutions are observed failing live.
        default=(
            "space,industry,sector,market,markets,system,platform,company,companies,"
            "stocks,stock,share,shares,ticker,tickers,the,a,an,or,and,in,of,for,with,"
            "tech,energy,sentiment,rising,falling,bullish,bearish"
        ),
        alias="RAG_CHAT_RESOLVER_STOP_WORDS",
    )
    # Tightened from 0.10 → 0.15: when top-1 and top-2 similarity are within
    # this delta the resolver treats the result as ambiguous (and applies
    # tiebreakers / bails). Tuned after observing "AI semiconductor space"
    # fuzzy-matched SpaceX with a 0.06 delta from the runner-up.
    resolver_similarity_delta_min: float = Field(default=0.15, ge=0.0, le=1.0)
    # Absolute minimum similarity for the top-1 candidate. Below this the
    # resolver refuses regardless of the delta (low-quality alias match).
    resolver_top_similarity_min: float = Field(default=0.75, ge=0.0, le=1.0)

    # ── Observability (STANDARDS.md §8.3) ────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
    service_name: str = "rag-chat"

    # ── Deploy-version cache flush (PLAN-0097 W4 T-W4-04) ────────────────────
    # Operator-bumped token (e.g. git SHA, build timestamp, schema version)
    # written to Valkey on startup. When the value changes between deploys the
    # rag-chat completion cache (``rag:v*:completion:*``) is flushed so a new
    # prompt/version is not served stale answers from the previous deploy.
    # Empty string = feature disabled; the startup hook is a no-op.
    cache_deploy_token: str = Field(default="", alias="RAG_CACHE_DEPLOY_TOKEN")

    @model_validator(mode="after")
    def _validate_startup(self) -> Settings:
        """Validate startup invariants: F-007/F-S005 (skip_verification) + F-014 (whitespace coercion).

        DEF-028: Use case-insensitive APP_ENV comparison so "Production", "PRODUCTION",
        and "prod" all trigger the guard — prevents bypassing the check via env var casing.
        F-S005: Inverted from denylist to allowlist — only explicitly permitted dev/test
        environments may skip JWT signature verification; any unrecognised APP_ENV value
        (including blank) that is NOT in the safe set will be rejected, preventing the
        original bypass where APP_ENV="" silently passed the denylist.
        """
        # F-S005: Allowlist of environments where skip_verification is permitted.
        # Only these well-known dev/test envs may bypass JWT signature checks.
        # "" is included so local dev with no APP_ENV set still works, but triggers
        # a LOUD WARNING below (operator must verify this is intentional).
        _safe_envs: frozenset[str] = frozenset({"development", "dev", "test", "ci", "local", ""})

        # F-007: internal_jwt_skip_verification=True MUST NOT be used outside safe environments.
        # Prevents accidentally deploying with signature verification disabled.
        _app_env = os.environ.get("APP_ENV", "").strip().lower()
        if self.internal_jwt_skip_verification and _app_env not in _safe_envs:
            raise ValueError(
                f"internal_jwt_skip_verification MUST NOT be enabled outside safe environments "
                f"(APP_ENV={_app_env!r} is not in {sorted(_safe_envs)})"
            )

        # F-S005: Emit a LOUD WARNING when APP_ENV is unset and skip_verification is on.
        # An unset APP_ENV could indicate a misconfigured production container — ensure
        # the operator notices by logging at CRITICAL level.
        if self.internal_jwt_skip_verification and _app_env == "":
            _log.critical(  # type: ignore[no-any-return]
                "SECURITY: internal_jwt_skip_verification=True with APP_ENV unset. "
                "Ensure this is intentional for local development only."
            )

        # F-014: Coerce whitespace-only database_url_read to None — functionally empty
        # DSN strings cause asyncpg connection errors at startup.
        if self.database_url_read is not None:
            raw = self.database_url_read.get_secret_value()
            if not raw or not raw.strip():
                object.__setattr__(self, "database_url_read", None)

        return self


__all__ = ["Settings"]
