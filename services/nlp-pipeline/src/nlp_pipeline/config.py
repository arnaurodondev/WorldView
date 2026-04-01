"""Service configuration via environment variables."""

from __future__ import annotations

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
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db"
    database_url_read: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30

    # intelligence_db — read/write adapter, ALEMBIC_ENABLED MUST stay false
    intelligence_database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
    intelligence_database_url_read: str = ""
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
    topic_claim_extracted: str = "claim.extracted"

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"
    valkey_watchlist_key: str = "nlp:v1:watched_entities"

    # Ollama / ML endpoints
    ollama_base_url: str = "http://localhost:11434"
    embedding_model_id: str = "bge-large-en-v1.5"
    ner_model_id: str = "urchade/gliner_large-v2.1"
    extraction_model_id: str = "qwen2.5:7b-instruct"

    # GLiNER: when set, use the HTTP adapter (containerised GLiNER server).
    # Leave empty to fall back to GLiNERLocalAdapter (in-process model).
    gliner_base_url: str = ""

    # GLiNER thresholds (PRD §6.7 Block 4)
    gliner_threshold: float = 0.35  # for routing/novelty signal
    gliner_resolution_threshold: float = 0.45  # for entity resolution cascade
    gliner_batch_size: int = 32
    gliner_section_token_limit: int = 450  # truncate sections before NER

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

    # Storage (MinIO/S3 for Silver tier reading)
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = ""
    storage_secret_key: str = ""

    # Admin API
    admin_token: str = ""

    # Observability (STANDARDS.md §5 — mandatory)
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
