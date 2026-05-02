"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the knowledge-graph service (S7)."""

    model_config = SettingsConfigDict(
        env_prefix="KNOWLEDGE_GRAPH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "knowledge-graph"

    # Server
    host: str = "0.0.0.0"
    port: int = 8007
    debug: bool = False

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db")
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30
    alembic_enabled: bool = False

    # Kafka topics — consumed
    kafka_topic_enriched: str = "nlp.article.enriched.v1"
    # Hot-path provisional enrichment topic (PLAN-0061 Wave E)
    kafka_topic_provisional_queued: str = "entity.provisional.queued.v1"
    kafka_consumer_group_provisional_queued: str = "kg-provisional-queued-group"
    kafka_topic_entity_created: str = "entity.canonical.created.v1"
    kafka_topic_instrument_created: str = "market.instrument.created"
    kafka_topic_dataset_fetched: str = "market.dataset.fetched"
    kafka_topic_temporal_event: str = "intelligence.temporal_event.v1"

    # Kafka topics — produced
    kafka_topic_graph_state: str = "graph.state.changed.v1"
    kafka_topic_contradiction: str = "intelligence.contradiction.v1"
    kafka_topic_relation_proposed: str = "relation.type.proposed.v1"
    kafka_topic_entity_dirtied: str = "entity.dirtied.v1"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_consumer_group: str = "kg-service-group"
    kafka_dlq_topic: str = "kg.dead-letter.v1"

    # Storage (S3/MinIO)
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str  # Required — set KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY
    storage_secret_key: str  # Required — set KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"

    # ML model endpoints
    ollama_base_url: str = "http://ollama:11434"
    # entity_embedding_state.embedding is vector(1024) — must use bge-large:latest (1024-dim).
    # nomic-embed-text produces 768-dim and raises FatalError on every embed call.
    embedding_model_id: str = "bge-large:latest"

    # Embedding provider selection — controls entity embedding workers.
    # "ollama"    → local bge-large:latest via OllamaEmbeddingAdapter (default; ~7-13s CPU)
    # "deepinfra" → BAAI/bge-large-en-v1.5 on DeepInfra GPU (~50-150ms; needs api_key)
    # IMPORTANT: must use same provider/model as nlp-pipeline to stay in same vector space.
    # Recommended models on DeepInfra:
    #   BAAI/bge-large-en-v1.5  (1024-dim, same as bge-large:latest — drop-in compatible)
    embedding_provider: str = "ollama"  # KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER
    embedding_api_key: str = ""  # KNOWLEDGE_GRAPH_EMBEDDING_API_KEY
    embedding_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # KNOWLEDGE_GRAPH_EMBEDDING_API_BASE_URL
    embedding_api_model_id: str = "BAAI/bge-large-en-v1.5"  # KNOWLEDGE_GRAPH_EMBEDDING_API_MODEL_ID

    # DeepInfra extraction (PLAN-0061 T-C-2) — primary extraction slot in FallbackChainClient.
    # When deepinfra_api_key is set, a DeepSeekExtractionAdapter is instantiated and placed
    # at position 0 in the extraction chain (before Ollama and Gemini).
    # KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY — set via secret; empty = extraction chain skips DeepInfra
    deepinfra_api_key: str = ""
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID
    deepinfra_extraction_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_BASE_URL
    deepinfra_extraction_base_url: str = "https://api.deepinfra.com/v1/openai"
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_CONCURRENCY
    deepinfra_extraction_concurrency: int = 5

    # Observability (STANDARDS.md §5)
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    # Confidence formula parameters (PRD §10.1)
    relation_canonicalization_threshold: float = 0.35
    confidence_corroboration_cap: float = 0.20
    confidence_contradiction_cap: float = 0.60
    confidence_temporal_claim_alpha: float = 0.02310  # legacy compatibility; currently ignored
    confidence_corroboration_gain_per_source: float = 0.05
    confidence_corroboration_min_temporal_weight: float = 0.1
    confidence_contradiction_top_k: int = 3

    # Worker intervals (seconds)
    worker_confidence_interval_s: int = 900  # 15 min
    worker_contradiction_interval_s: int = 1800  # 30 min
    worker_summary_interval_s: int = 3600  # 60 min
    worker_definition_refresh_interval_s: int = 3600  # 60 min
    worker_narrative_refresh_interval_s: int = 3600  # 60 min
    worker_fundamentals_refresh_interval_s: int = 7200  # 2 h
    worker_embedding_refresh_interval_s: int = 10800  # 3 h
    worker_partition_interval_s: int = 86400  # 24 h (also runs at startup)
    # Dedicated provisional enrichment worker controls (PLAN-0061 T-A-1/A-3/A-4)
    # interval: 300s = 5 min catch-up sweep; hot path handled by entity.provisional.queued.v1 consumer (Wave E)
    # batch: 500 — V4-Flash at concurrency=5 drains 500 in ~3-8 min; old 50-row cap was set for Ollama
    worker_provisional_enrichment_interval_s: int = 300  # 5 min
    worker_provisional_enrichment_batch_size: int = 500  # rows per cycle
    worker_provisional_enrichment_concurrency: int = 5  # concurrent LLM calls
    worker_provisional_enrichment_max_retries: int = 5  # terminal 'failed' after N failures

    # Entity description generation (PRD-0017 §6.5 — DefinitionRefreshWorker)
    # "deepinfra" → DeepInfraDescriptionAdapter (Qwen3-235B-A22B primary, Qwen3-32B fallback)
    # "gemini"    → GeminiDescriptionAdapter (gemini-3.1-flash-lite)
    # "none"      → NullDescriptionAdapter (fallback template, no external calls)
    description_provider: str = "none"  # KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER
    gemini_api_key: SecretStr = SecretStr("")
    description_max_monthly_usd: float = 10.0
    description_gemini_concurrency: int = 4
    # DeepInfra description model IDs (used when description_provider="deepinfra")
    description_deepinfra_model_id: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    description_deepinfra_fallback_model_id: str = "Qwen/Qwen3-32B"
    description_deepinfra_concurrency: int = 4

    # Market data service (used by Worker 13D-3)
    market_data_base_url: str = "http://market-data:8003"

    # AGE Cypher shadow sync (Worker 13F — PRD-0018)
    # Feature flag: set to true after AGE backfill is verified.
    cypher_enabled: bool = False
    worker_age_sync_interval_s: int = 900  # 15 min

    # Outbox dispatcher
    dispatcher_poll_interval_s: float = 1.0
    dispatcher_batch_size: int = 50

    # Auth
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # JTI replay check boundary control.
    # S7 is an internal-only service: S8 (rag-chat) forwards the same JWT token
    # to S7 multiple times per user request (e.g. graph enrichment + entity search).
    # The JTI replay check at S8 is the correct user-facing boundary.
    # Default: False — replay check is disabled for this internal service.
    jti_replay_check_enabled: bool = False

    # Admin token for DLQ endpoints (empty = no auth configured)
    admin_token: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag.",
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "KNOWLEDGE_GRAPH_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
