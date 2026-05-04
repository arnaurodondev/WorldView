"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the nlp-pipeline service."""

    model_config = SettingsConfigDict(
        env_prefix="NLP_PIPELINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service identity (STANDARDS.md §5)
    service_name: str = "nlp-pipeline"

    # Server
    host: str = "0.0.0.0"
    port: int = 8006
    debug: bool = False

    # nlp_db — owned, Alembic enabled
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db")
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

    # intelligence_db — read/write adapter, ALEMBIC_ENABLED MUST stay false
    intelligence_database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
    )
    intelligence_database_url_read: SecretStr = SecretStr("")
    intelligence_db_pool_size: int = 10
    intelligence_db_max_overflow: int = 20
    intelligence_db_pool_size_read: int = 20
    intelligence_db_max_overflow_read: int = 30

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    kafka_consumer_group: str = "nlp-pipeline-group"
    kafka_watchlist_consumer_group: str = "nlp-watchlist-group"

    # Topics (consumed)
    topic_article_stored: str = "content.article.stored.v1"
    topic_watchlist_updated: str = "portfolio.watchlist.updated.v1"

    # Topics (produced)
    topic_article_enriched: str = "nlp.article.enriched.v1"
    topic_signal_detected: str = "nlp.signal.detected.v1"
    topic_temporal_event: str = "intelligence.temporal_event.v1"  # NLP_PIPELINE_TOPIC_TEMPORAL_EVENT
    kafka_topic_provisional_queued: str = "entity.provisional.queued.v1"  # NLP_PIPELINE_KAFKA_TOPIC_PROVISIONAL_QUEUED
    # PLAN-0057 D-1 (F-CRIT-08): the legacy ``topic_claim_extracted`` setting
    # was removed along with the orphan ``claim.extracted`` producer. Claims
    # now flow exclusively via ``nlp.article.enriched.v1.raw_claims``.

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"
    valkey_watchlist_key: str = "nlp:v1:watched_entities"

    # Ollama / ML endpoints
    ollama_base_url: str = "http://localhost:11434"
    embedding_model_id: str = "bge-large"
    ner_model_id: str = "urchade/gliner_large-v2.1"
    extraction_model_id: str = "qwen2.5:7b-instruct"

    # Embedding provider selection — controls BOTH ingestion (article consumer) and
    # query-time (POST /api/v1/embed endpoint).  Both paths MUST use the same model
    # so that chunk embeddings and query embeddings are in the same vector space.
    #
    # "ollama"    → local bge-large via OllamaEmbeddingAdapter (default; no key needed, slow on CPU)
    # "deepinfra" → BAAI/bge-large-en-v1.5 on DeepInfra GPU (~50-150ms, same 1024-dim output)
    # "jina"      → jina-embeddings-v3 on Jina AI REST API (~100-300ms, 1024-dim)
    #
    # WARNING: switching provider requires re-embedding all stored chunks (different semantic
    # spaces even for same-dim models from different providers). Run the EmbeddingRetryWorker
    # after switching, or use the admin /api/v1/admin/expire-embeddings endpoint to queue them.
    embedding_provider: str = "ollama"  # NLP_PIPELINE_EMBEDDING_PROVIDER
    # DeepInfra embedding API config (used when embedding_provider="deepinfra")
    embedding_api_key: str = ""  # NLP_PIPELINE_EMBEDDING_API_KEY (same DeepInfra key as extraction_api_key is fine)
    embedding_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # NLP_PIPELINE_EMBEDDING_API_BASE_URL
    embedding_api_model_id: str = "BAAI/bge-large-en-v1.5"  # NLP_PIPELINE_EMBEDDING_API_MODEL_ID
    # Jina AI config (used when embedding_provider="jina")
    jina_api_key: str = ""  # NLP_PIPELINE_JINA_API_KEY

    # PLAN-0057 QA A-005: tunable retry ceiling for the embedding-retry worker.
    # Was hard-coded to 5 in three places (worker module, repo defaults). Now
    # operator-tunable via NLP_PIPELINE_EMBEDDING_RETRY_MAX_ATTEMPTS so a high
    # error-rate from DeepInfra can be tolerated without a code change.
    embedding_retry_max_attempts: int = 5

    # Deep extraction via external API (DeepInfra / OpenAI-compatible)
    # When extraction_api_key is set, DeepSeekExtractionAdapter is used instead of OllamaExtractionAdapter.
    # Qwen3-235B-A22B-Instruct-2507: $0.071/$0.10 per 1M tokens; 250k context >> 24k max extraction window.
    extraction_api_key: str = ""  # NLP_PIPELINE_EXTRACTION_API_KEY
    extraction_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # NLP_PIPELINE_EXTRACTION_API_BASE_URL
    extraction_api_model_id: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # NLP_PIPELINE_EXTRACTION_API_MODEL_ID

    # GLiNER: when set, use the HTTP adapter (containerised GLiNER server).
    # Leave empty to fall back to GLiNERLocalAdapter (in-process model).
    gliner_base_url: str = ""

    # GLiNER thresholds (PRD §6.7 Block 4)
    gliner_threshold: float = 0.35  # for routing/novelty signal
    gliner_resolution_threshold: float = 0.45  # for entity resolution cascade
    gliner_batch_size: int = 32
    gliner_section_token_limit: int = 450  # truncate sections before NER
    gliner_nms_iou_threshold: float = 0.5  # Non-Maximum Suppression overlap threshold

    # Routing tier thresholds (PRD §6.7 Block 5)
    routing_tier_deep: float = 0.70  # score >= this → DEEP processing
    # Lowered from 0.45: watchlist signal fires post-resolution, effective max without it is ~0.44
    routing_tier_medium: float = 0.35  # score >= this → MEDIUM processing
    routing_tier_light: float = 0.20  # score >= this → LIGHT processing

    # Entity resolution thresholds (PRD §6.7 Block 9)
    entity_resolution_auto_resolve_threshold: float = 0.72  # auto-resolve above this
    entity_resolution_provisional_threshold: float = 0.45  # provisional above this

    # Novelty gate thresholds (PRD §6.7 Block 8)
    novelty_minhash_threshold: float = 0.80  # MinHash similarity → near-duplicate
    novelty_embedding_threshold: float = 0.90  # per-entity embedding similarity → near-duplicate

    # Backpressure (PRD §6.7 Block 7, T-C-3-05)
    max_ollama_queue_depth: int = 20
    resume_ollama_queue_depth: int = 10

    # Embedding (PRD §6.7 Block 7)
    embedding_batch_size: int = 64
    embedding_max_concurrent: int = 4
    embedding_instruction_prefix: str = "Represent this financial document passage for retrieval: "
    embedding_chunk_size_news: int = 280  # target tokens (NEWS 256-300)
    embedding_chunk_size_filings: int = 325  # FILINGS 300-350
    embedding_chunk_size_earnings: int = 300  # EARNINGS_CALL
    embedding_chunk_overlap_tokens: int = 64  # ~0-2 sentences

    # Deep extraction (PRD §6.7 Block 10)
    extraction_single_window_tokens: int = 24000
    extraction_window_size_tokens: int = 6000
    extraction_window_overlap_tokens: int = 500

    # Dispatcher
    dispatcher_poll_interval_secs: float = 1.0
    dispatcher_batch_size: int = 50

    # Storage (MinIO/S3 for Silver tier reading and chunk text persistence)
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    chunk_bucket: str = "worldview"
    silver_bucket: str = "worldview-silver"

    # Price-impact labelling worker (PRD-0026 §6.7 Flow A)
    # Per-window normalisation caps — configurable via S6_CAP_DAY_T*_PCT env vars
    price_impact_cap_day_t0_pct: float = 5.0  # S6_CAP_DAY_T0_PCT
    price_impact_cap_day_t1_pct: float = 5.0  # S6_CAP_DAY_T1_PCT
    price_impact_cap_day_t2_pct: float = 7.5  # S6_CAP_DAY_T2_PCT
    price_impact_cap_day_t5_pct: float = 10.0  # S6_CAP_DAY_T5_PCT
    price_impact_cycle_seconds: int = 14400
    price_impact_min_age_hours: int = 25
    market_data_internal_url: str = "http://market-data:8003"
    # Legacy setting — kept for backward compatibility, not used by the new worker
    impact_normalisation_cap_pct: float = 5.0

    # ArticleRelevanceScoringWorker (PRD-0026 §6.7 Flow B)
    relevance_scoring_cycle_seconds: int = 1800  # RELEVANCE_SCORING_CYCLE_SECONDS
    relevance_scoring_batch_size: int = 50  # RELEVANCE_SCORING_BATCH_SIZE
    relevance_scoring_ollama_url: str = "http://ollama:11434"  # RELEVANCE_SCORING_OLLAMA_URL
    relevance_scoring_model: str = "qwen3:0.6b"  # RELEVANCE_SCORING_MODEL
    relevance_scoring_timeout_seconds: int = 30  # RELEVANCE_SCORING_TIMEOUT_SECONDS
    # ArticleRelevanceScoringWorker — DeepInfra provider (optional override)
    # When set, worker uses OpenAI-compatible chat completions instead of Ollama.
    # Model options (availability depends on DeepInfra account tier):
    #   meta-llama/Meta-Llama-3.1-8B-Instruct  (confirmed available, ~100-200ms)
    #   Qwen/Qwen2.5-0.5B-Instruct             (smaller, faster — upgrade account to unlock)
    #   Qwen/Qwen2.5-1.5B-Instruct             (medium — upgrade account to unlock)
    relevance_scoring_api_key: str = ""  # NLP_PIPELINE_RELEVANCE_SCORING_API_KEY
    relevance_scoring_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # RELEVANCE_SCORING_API_BASE_URL
    # PLAN-0061 Wave D (2026-05-02): Llama-3.2-1B/3B not available on this account.
    # Confirmed available: Meta-Llama-3.1-8B-Instruct-Turbo (~100-200ms GPU,
    # ~$0.02/M tokens — still cheap enough for per-article relevance scoring).
    # RELEVANCE_SCORING_API_MODEL_ID
    relevance_scoring_api_model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    # Per-component weights for display_relevance_score = 0.5*market + 0.4*llm + 0.1*routing
    s6_display_weight_market: float = 0.50  # S6_DISPLAY_WEIGHT_MARKET
    s6_display_weight_llm: float = 0.40  # S6_DISPLAY_WEIGHT_LLM
    s6_display_weight_routing: float = 0.10  # S6_DISPLAY_WEIGHT_ROUTING

    # UnresolvedResolutionWorker (PLAN-0033 T-C-1-04)
    # All env vars: NLP_PIPELINE_UNRESOLVED_RESOLUTION_* prefix (auto via model_config)
    unresolved_resolution_enabled: bool = True
    unresolved_resolution_interval_s: int = 1800  # 30 minutes between poll cycles
    unresolved_resolution_batch_size: int = 500  # rows per poll cycle
    unresolved_resolution_lookback_days: int = 90  # max age of mentions to re-process
    unresolved_resolution_llm_timeout_s: float = 10.0  # Ollama per-call timeout
    unresolved_resolution_llm_retries: int = 2  # Ollama retries on JSON parse failure
    unresolved_resolution_stale_escalated_minutes: int = 30  # stale lock recovery threshold
    unresolved_resolution_ollama_base_url: str = "http://ollama:11434"
    unresolved_resolution_classification_model: str = "qwen3:0.6b"
    unresolved_resolution_max_llm_batch: int = 20  # max mentions per Ollama call
    # UnresolvedResolutionWorker — DeepInfra provider (optional override)
    # When set, worker uses OpenAI-compatible chat completions instead of Ollama.
    # Same model options as relevance_scoring (see above).
    unresolved_resolution_api_key: str = ""  # NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY
    unresolved_resolution_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # UNRESOLVED_RESOLUTION_API_BASE
    # PLAN-0061 Wave D (2026-05-02): Llama-3.2-1B/3B not available on this account.
    # Confirmed available: Meta-Llama-3.1-8B-Instruct-Turbo — sufficient for
    # the one-mention-at-a-time entity disambiguation prompt shape.
    # UNRESOLVED_RESOLUTION_API_MODEL_ID
    unresolved_resolution_api_model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

    # LLM usage logging (PLAN-0033)
    llm_usage_log_enabled: bool = True

    # Auth
    api_gateway_url: str = "http://api-gateway:8000"

    # PLAN-0057 Wave A-1 / BP-303 — service-account secret used by background
    # workers (e.g. PriceImpactLabellingWorker → MarketDataClient) to mint an
    # X-Internal-JWT via S9's ``POST /internal/v1/service-token``. Empty default
    # keeps local dev workflows on ``POST /v1/auth/dev-login``; production
    # MUST set this (sourced from the same sealed secret as
    # ``API_GATEWAY_SERVICE_ACCOUNT_TOKEN``).
    service_account_token: str = ""  # NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # JTI replay check boundary control.
    # S6 is an internal-only service: S8 (rag-chat) forwards the same JWT token
    # to S6 multiple times per user request (e.g. once to embed, once to search
    # chunks). The JTI replay check at S8 is the correct user-facing boundary.
    # Enabling it here causes the second S6 call within the same request to be
    # rejected as a replay, breaking RAG retrieval. Default: False.
    jti_replay_check_enabled: bool = False

    # Admin API
    admin_token: str = ""

    # Observability (STANDARDS.md §5 — mandatory)
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if any database_url still contains default superuser credentials (D-7)."""
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag."
            )
        for field_name, env_var in (
            ("database_url", "NLP_PIPELINE_DATABASE_URL"),
            ("intelligence_database_url", "NLP_PIPELINE_INTELLIGENCE_DATABASE_URL"),
        ):
            url_val: SecretStr = getattr(self, field_name)
            if "postgres:postgres" in url_val.get_secret_value():
                structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                    "default_db_credentials_detected",
                    field=field_name,
                    message=(
                        f"{env_var} still uses the default 'postgres:postgres' credentials. "
                        "Set this env var to a secure database URL before deploying to production."
                    ),
                )
        return self
