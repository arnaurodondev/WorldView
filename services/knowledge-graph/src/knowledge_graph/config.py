"""Service configuration via environment variables."""

from __future__ import annotations

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
    embedding_model_id: str = "nomic-embed-text"

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

    # Entity description generation (PRD-0017 §6.5 — DefinitionRefreshWorker)
    description_provider: str = "none"  # "gemini" | "none"
    gemini_api_key: SecretStr = SecretStr("")
    description_max_monthly_usd: float = 10.0
    description_gemini_concurrency: int = 4

    # Market data service (used by Worker 13D-3)
    market_data_base_url: str = "http://market-data:8003"

    # EODHD API (Workers 13D-6, 13D-7, 13D-8)
    eodhd_api_key: SecretStr = SecretStr("")
    eodhd_base_url: str = "https://eodhd.com/api"
    # Comma-separated ISO-3166 alpha-2 country codes for economic event polling (Worker 13D-6)
    economic_event_countries: str = "US,DE,GB,JP,CN,EU"
    # Comma-separated ISO-3166 alpha-3 country codes for macro indicator enrichment (Worker 13D-7)
    # Note: Macro Indicator API uses alpha-3 (USA/GBR/DEU/JPN/CHN), not alpha-2
    macro_indicator_countries: str = "USA,GBR,DEU,JPN,CHN"

    # AGE Cypher shadow sync (Worker 13F — PRD-0018)
    # Feature flag: set to true after AGE backfill is verified.
    cypher_enabled: bool = False
    worker_age_sync_interval_s: int = 900  # 15 min

    # Outbox dispatcher
    dispatcher_poll_interval_s: float = 1.0
    dispatcher_batch_size: int = 50

    # Auth
    api_gateway_url: str = "http://api-gateway:8000"

    # Admin token for DLQ endpoints (empty = no auth configured)
    admin_token: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "KNOWLEDGE_GRAPH_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
