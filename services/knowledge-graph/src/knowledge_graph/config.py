"""Service configuration via environment variables."""

from __future__ import annotations

import os

from pydantic import Field, SecretStr, model_validator
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

    # Database — no default; service fails fast at startup if env var is missing (DEF-001)
    database_url: SecretStr  # KNOWLEDGE_GRAPH_DATABASE_URL — required
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30
    # Universal per-connection statement_timeout (milliseconds) applied to EVERY
    # regular (non-AGE) SQL session on intelligence_db.  Backstop introduced
    # after a single ``RelationEvidencePromoterWorker._FETCH_SQL`` run ran for
    # 16,188 s (4.5 h) and starved the UI-facing OLTP databases sharing the
    # Postgres instance.  Set as an asyncpg ``server_settings`` connection
    # parameter so it applies the moment a connection is established.
    #
    # 60_000 ms (60 s) chosen as the default: it is ~3x the slowest legitimate
    # AGE neighbourhood query (20 s) yet two orders of magnitude below the
    # pathological 4.5 h.  Background batch workers (promoter, confidence,
    # summary) operate on bounded batches (<=200 rows) and complete in well
    # under 60 s once 0049's indexes land; any session exceeding 60 s is, by
    # definition, the runaway plan this backstop exists to kill.
    #
    # PRECEDENCE: AGE Cypher use cases issue ``SET LOCAL statement_timeout`` per
    # transaction (5/20/30 s) which overrides this connection-level default for
    # the duration of that transaction only — their explicit bounds are NOT
    # widened by this value.  Set to 0 to disable (unbounded; not recommended).
    statement_timeout_ms: int = 60_000
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
    # Hot-path narrative embedding refresh topic (PLAN-0074 T-C-05)
    kafka_topic_narrative_generated: str = "entity.narrative.generated.v1"
    kafka_consumer_group_narrative_refresh: str = "kg-narrative-refresh-group"

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
    embedding_api_key: SecretStr = SecretStr("")  # KNOWLEDGE_GRAPH_EMBEDDING_API_KEY (DEF-005)
    embedding_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # KNOWLEDGE_GRAPH_EMBEDDING_API_BASE_URL
    embedding_api_model_id: str = "BAAI/bge-large-en-v1.5"  # KNOWLEDGE_GRAPH_EMBEDDING_API_MODEL_ID

    # DeepInfra extraction (PLAN-0061 T-C-2) — primary extraction slot in FallbackChainClient.
    # When deepinfra_api_key is set, a DeepSeekExtractionAdapter is instantiated and placed
    # at position 0 in the extraction chain (before Ollama and Gemini).
    # KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY — set via secret; empty = extraction chain skips DeepInfra
    deepinfra_api_key: SecretStr = SecretStr("")  # DEF-005: SecretStr prevents key leakage in tracebacks
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_MODEL_ID
    deepinfra_extraction_model_id: str = "deepseek-ai/DeepSeek-V4-Flash-Thinking"
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_BASE_URL
    deepinfra_extraction_base_url: str = "https://api.deepinfra.com/v1/openai"
    # KNOWLEDGE_GRAPH_DEEPINFRA_EXTRACTION_CONCURRENCY
    deepinfra_extraction_concurrency: int = 5

    # PLAN-0056 Wave C3: MarketPolarityClassifier (prediction-market exposure polarity).
    # Reuses the DeepInfra OpenAI-compat small-model stack (same shape as S6 relevance
    # scoring — a small, cheap chat model). When ``deepinfra_api_key`` is set the
    # PredictionEnrichedConsumer wires the classifier; empty key → exposures keep
    # NULL polarity (the classifier is never constructed).
    #
    # PLAN-0056 live-QA fix: the original default ``Qwen/Qwen2.5-0.5B-Instruct`` is
    # NOT served on this DeepInfra account — the endpoint returns HTTP 404
    # ("model_not_found"), which the classifier swallows into ("neutral", 0.0), so
    # EVERY exposure silently degraded to neutral/0.0 (the "against a company"
    # bullish/bearish signal was dead). We default to the SAME served model the S6
    # relevance-scoring worker uses in the live config
    # (``meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`` — verified HTTP 200 with the
    # current KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY). It is larger than 0.5B (a small
    # cost bump), but a working classifier beats a 404→neutral degrade. Override via
    # KNOWLEDGE_GRAPH_POLARITY_CLASSIFIER_MODEL_ID if the account tier changes.
    polarity_classifier_model_id: str = (
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"  # KNOWLEDGE_GRAPH_POLARITY_CLASSIFIER_MODEL_ID
    )
    polarity_classifier_base_url: str = (
        "https://api.deepinfra.com/v1/openai"  # KNOWLEDGE_GRAPH_POLARITY_CLASSIFIER_BASE_URL
    )
    polarity_classifier_timeout_seconds: int = 30  # KNOWLEDGE_GRAPH_POLARITY_CLASSIFIER_TIMEOUT_SECONDS

    # ── PLAN-0056 Wave D2 — PredictionSignalEmitter tunables ─────────────────
    # The emitter turns the three prediction triggers (new_market / material_move /
    # resolution) into per-entity ``market.prediction.signal.v1`` events (one per
    # entity exposure) with a gating ``market_impact_score`` in [0, 1]. All bases /
    # multipliers are env-driven so the alert severity mapping can be tuned without
    # a code change (no magic numbers buried in the score logic).
    #
    # new_market  : score = new_market_base * exposure.confidence (clamped 0..1).
    # material_move: score = clamp(|delta|, 0..1), boosted by adverse_factor when the
    #               move is adverse for the entity (bearish-outcome rising OR the
    #               entity's favourable outcome falling), capped at 1.0.
    # resolution  : score = resolution_base (fixed).
    prediction_signal_new_market_base: float = 0.5  # KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_NEW_MARKET_BASE
    prediction_signal_resolution_base: float = 0.6  # KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_RESOLUTION_BASE
    # KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_MATERIAL_MOVE_ADVERSE_FACTOR
    prediction_signal_material_move_adverse_factor: float = 1.25
    # Gate: when False the enriched consumer never emits new_market signals (the
    # first-sight-of-a-market trigger). material_move + resolution are unaffected.
    # KNOWLEDGE_GRAPH_PREDICTION_SIGNAL_EMIT_NEW_MARKET
    prediction_signal_emit_new_market: bool = True

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

    # PLAN-0109 W1 — Beta / subjective-logic confidence backbone (v2).
    # When True the worker uses ``compute_confidence_beta`` (prior from
    # base_confidence, graded source trust, extraction confidence, per-mode decay
    # floor, uncertainty) instead of the v1 bounded-additive formula above.
    # Rolled out behind a flag; v1 stays as the fallback.
    confidence_formula_v2: bool = False  # KNOWLEDGE_GRAPH_CONFIDENCE_FORMULA_V2
    confidence_prior_strength: float = 2.0  # kappa - prior pseudo-count weight
    confidence_signal_decay_floor: float = 0.1  # TEMPORAL_CLAIM floor as evidence decays
    confidence_default_source_trust: float = 0.5  # fallback when source_type ∉ source_trust_weights
    # PLAN-0109 W6 - Beta calibration P = sigmoid(a*ln(s) + b*ln(1-s) + c). Defaults
    # are the identity map (P = s); an operator sets fitted (a,b,c) from
    # scripts/fit_confidence_calibration.py after building a labelled set.
    confidence_calibration_a: float = 1.0
    confidence_calibration_b: float = -1.0
    confidence_calibration_c: float = 0.0

    # Worker intervals (seconds)
    # FIX-LIVE-GG (2026-05-25, INV-LIVE-GG cluster 2): lowered SummaryWorker,
    # EmbeddingRefresh and FundamentalsRefresh intervals to drain the
    # worker-starvation backlog that surfaced in iter-5 SLO failures
    # (``test_summary_coverage`` 7%, ``test_definition_embedding_coverage``
    # 10%, ``test_fundamentals_ohlcv_embedding_coverage`` 0/2405).  With 5
    # LLM-bound workers sharing one asyncio loop and ~60 s LLM calls per
    # batch, the old 3600/7200/10800 s cadences burned <2% of wall time on
    # work — far too sparse to keep up with ingestion.  Overridable via
    # ``KNOWLEDGE_GRAPH_WORKER_*_INTERVAL_S`` env vars (see docker.env).
    worker_confidence_interval_s: int = 900  # 15 min
    worker_contradiction_interval_s: int = 1800  # 30 min
    worker_summary_interval_s: int = 600  # FIX-LIVE-GG: was 3600 (60 min); now 10 min
    # Worker 13B: relation_evidence_raw → relation_evidence promotion (SA-2).
    # Runs every 5 minutes so freshly processed NLP batches are promotable
    # within one short window.
    worker_evidence_promote_interval_s: int = 300  # 5 min
    worker_definition_refresh_interval_s: int = 3600  # 60 min
    worker_narrative_refresh_interval_s: int = 3600  # 60 min
    worker_fundamentals_refresh_interval_s: int = 300  # FIX-LIVE-GG: was 7200 (2 h); now 5 min
    worker_embedding_refresh_interval_s: int = 300  # FIX-LIVE-GG: was 10800 (3 h); now 5 min
    worker_partition_interval_s: int = 86400  # 24 h (also runs at startup)
    # Dedicated provisional enrichment worker controls (PLAN-0061 T-A-1/A-3/A-4)
    # interval: 300s = 5 min catch-up sweep; hot path handled by entity.provisional.queued.v1 consumer (Wave E)
    # batch: 500 — V4-Flash at concurrency=5 drains 500 in ~3-8 min; old 50-row cap was set for Ollama
    worker_provisional_enrichment_interval_s: int = 300  # 5 min
    worker_provisional_enrichment_batch_size: int = 500  # rows per cycle
    worker_provisional_enrichment_concurrency: int = 5  # concurrent LLM calls
    worker_provisional_enrichment_max_retries: int = 5  # terminal 'failed' after N failures

    # Worker 13K — entity re-typing sweep (2026-07-16 KG deep-quality audit).
    # Periodically re-classifies canonical entities stuck at entity_type='unknown'
    # (audit: ~150 clearly-typable rows with no re-typing path). Read-replica
    # SELECT → extraction LLM → guarded UPDATE. Interval 1800s = 30 min; batch 100
    # bounds per-cycle LLM spend. Set retype_enabled=false to disable the sweep.
    retype_enabled: bool = True  # KNOWLEDGE_GRAPH_RETYPE_ENABLED
    worker_retype_interval_s: int = 1800  # 30 min
    worker_retype_batch_size: int = 100  # unknown rows per cycle

    # Embedding worker batch controls (PLAN perf-fix)
    # 0 = all due entities per cycle (drain the full queue in one cycle).
    # FIX-LIVE-GG (2026-05-25): default raised from 0->200 alongside the new
    # 300 s EmbeddingRefresh cadence so each cycle is sized to a single
    # DeepInfra embed batch (``_EMBED_CHUNK_SIZE=200`` in embedding_refresh.py)
    # — prevents one cycle from issuing many sequential embed calls and
    # blocking the asyncio loop for the other 4 workers.  Set to ``0`` only
    # when tuning a fresh deployment that needs a full backlog drain.
    worker_embedding_batch_limit: int = 200  # KNOWLEDGE_GRAPH_WORKER_EMBEDDING_BATCH_LIMIT

    # SummaryWorker force-regeneration (ARCH-008).
    # When > 0, force-regenerate this many stale summaries per cycle regardless of evidence
    # hash match.  0 (default) disables force-regen so only hash-changed relations are sent
    # to the LLM.  Useful during prompt-template upgrades to refresh cached summaries.
    summary_worker_force_regen_batch_size: int = Field(
        default=0,
        description=(
            "If > 0, force-regenerate this many stale summaries per cycle regardless of hash match. "
            "0 disables force-regen."
        ),
    )  # KNOWLEDGE_GRAPH_SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE
    # Parallel HTTP concurrency for FundamentalsRefreshWorker Phase 2.
    worker_fundamentals_concurrency: int = 5  # KNOWLEDGE_GRAPH_WORKER_FUNDAMENTALS_CONCURRENCY

    # Entity description generation (PRD-0017 §6.5 — DefinitionRefreshWorker)
    # "deepinfra" → DeepInfraDescriptionAdapter (Qwen3-235B-A22B primary, Qwen3-32B fallback)
    # "gemini"    → GeminiDescriptionAdapter (gemini-3.1-flash-lite)
    # "none"      → NullDescriptionAdapter (fallback template, no external calls)
    description_provider: str = "none"  # KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER
    gemini_api_key: SecretStr = SecretStr("")
    description_max_monthly_usd: float = 10.0
    description_gemini_concurrency: int = 4
    # DeepInfra description model IDs (used when description_provider="deepinfra")
    # NOTE (PRD-0073 / ADR-0073-006): Worker 13J (StructuredEnrichmentWorker) shares the
    # description model with DefinitionRefreshWorker.  The previous standalone fields
    # ``enrichment_llm_model_id`` / ``enrichment_llm_fallback_model_id`` were dead code
    # (defined in Settings but never read by any adapter).  Consolidated here to a single
    # source of truth so that env-var changes actually take effect.
    # Fallback aligned to Meta-Llama-3.1-8B-Instruct-Turbo per ADR-0073-006 (Qwen/Qwen3-32B
    # was the previous default but is not on the project's DeepInfra account allow-list).
    description_deepinfra_model_id: str = "deepseek-ai/DeepSeek-V4-Flash-Thinking"
    description_deepinfra_fallback_model_id: str = "Qwen/Qwen3.5-9B"
    description_deepinfra_concurrency: int = 4

    # Market data service (used by Worker 13D-3 and Worker 13J)
    market_data_base_url: str = "http://market-data:8003"
    # Internal JWT-authenticated URL for Worker 13J on-demand-profile calls.
    # Defaults to same host as market_data_base_url (no separate internal port).
    market_data_internal_url: str = "http://market-data:8003"

    # Worker 13D-3: Narrative generation LLM model (PRD-0074 Wave C)
    # Uses Meta-Llama-3.1-8B-Instruct (confirmed available on this DeepInfra account).
    # Falls back to template-v1 when llm_client is None or model call fails.
    narrative_llm_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"

    # Worker 13J — Structured Enrichment (PRD-0073)
    #
    # DEPRECATED FIELDS REMOVED (PLAN-0073 cleanup, F-A04 / F-S08):
    #   ``enrichment_llm_model_id`` and ``enrichment_llm_fallback_model_id`` were defined
    #   in Settings but never read by any adapter — setting the env vars had no effect.
    #   Worker 13J shares the description model with DefinitionRefreshWorker via
    #   ``description_deepinfra_model_id`` / ``description_deepinfra_fallback_model_id``
    #   (see ADR-0073-006).  Use those fields instead.
    kafka_consumer_group_structured_enrichment: str = "kg-structured-enrichment-group"

    # AGE Cypher shadow sync (Worker 13F — PRD-0018)
    # Feature flag: set to true after AGE backfill is verified.
    cypher_enabled: bool = False
    worker_age_sync_interval_s: int = 900  # 15 min

    # Outbox dispatcher
    dispatcher_poll_interval_s: float = 1.0
    dispatcher_batch_size: int = 50

    # Auth
    api_gateway_url: str = "http://api-gateway:8000"

    # F-015: Optional RS256 private key PEM for service-to-service JWT signing.
    # When set, FundamentalsRefreshWorker issues RS256-signed internal JWTs
    # (the same key pair used by S9 api-gateway). When empty (default), the
    # worker falls back to the HS256 dev token, which market-data accepts when
    # MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true (dev/test only).
    # Set KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY to the PEM contents of the
    # same RS256 key that S9 uses so backends can verify with the gateway JWKS.
    internal_jwt_private_key: SecretStr = SecretStr("")

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

    # ── PLAN-0113 FIX-2: static-membership consumer instance IDs ─────────────
    # Each Kafka consumer group that runs in a KG container may be configured
    # with a stable group.instance.id so that Kafka's static membership protocol
    # (KIP-345) avoids a full consumer-group rebalance on every rolling restart.
    # Default: "" (empty) — the consumer falls back to dynamic membership.
    # Override in docker-compose via KNOWLEDGE_GRAPH_KAFKA_*_CONSUMER_INSTANCE_ID.
    kafka_enriched_consumer_instance_id: str = ""
    kafka_entity_consumer_instance_id: str = ""
    kafka_fundamentals_consumer_instance_id: str = ""
    kafka_instrument_consumer_instance_id: str = ""
    kafka_instrument_discovered_consumer_instance_id: str = ""
    kafka_temporal_event_consumer_instance_id: str = ""
    kafka_earnings_calendar_dataset_consumer_instance_id: str = ""
    # PLAN-0056 Wave C2 — PredictionEnrichedConsumer (own group on nlp.article.enriched.v1).
    kafka_prediction_enriched_consumer_instance_id: str = ""
    # PLAN-0056 deploy-fix — start-at-latest for the prediction-enriched consumer.
    # This consumer is a FRESH group on the high-volume nlp.article.enriched.v1
    # topic, which holds ~20k historical messages written under the PRE-C2b/C3
    # schema (before the additive nullable external_id/source_title fields). The
    # no-registry ``fastavro.schemaless_reader`` decodes those old records with the
    # NEW reader schema → union misalignment → IndexError → dead-letter storm →
    # dead_letter_cap crash-loop. The consumer is FORWARD-ONLY (it only needs NEW
    # polymarket synthetic docs; there are ZERO polymarket docs in the historical
    # news backlog), so a fresh group starts at the LATEST offset and never reads
    # the pre-change backlog. Override via
    # KNOWLEDGE_GRAPH_KAFKA_PREDICTION_ENRICHED_CONSUMER_AUTO_OFFSET_RESET.
    kafka_prediction_enriched_consumer_auto_offset_reset: str = "latest"
    # PLAN-0056 Wave D2 — PredictionMoveConsumer (own group on market.prediction.move.v1).
    kafka_prediction_move_consumer_instance_id: str = ""
    kafka_economic_events_dataset_consumer_instance_id: str = ""
    kafka_insider_transactions_dataset_consumer_instance_id: str = ""
    kafka_macro_indicator_dataset_consumer_instance_id: str = ""
    kafka_narrative_refresh_consumer_instance_id: str = ""
    kafka_provisional_queued_consumer_instance_id: str = ""
    kafka_structured_enrichment_consumer_instance_id: str = ""

    # SummaryWorker Gemini fallback (SA-2 / PLAN-0088).
    # When the primary extraction chain (DeepInfra → Ollama) is exhausted,
    # SummaryWorker makes one additional attempt via Gemini 2.5 Flash Lite.
    # "gemini" activates the fallback; "none" disables it.
    summary_fallback_provider: str = "deepinfra"  # KNOWLEDGE_GRAPH_SUMMARY_FALLBACK_PROVIDER
    summary_fallback_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"  # KNOWLEDGE_GRAPH_SUMMARY_FALLBACK_MODEL_ID

    # Wave A-2 / DEF-022: embedding model tracking
    # Recorded alongside every relation_summaries.summary_embedding write so we
    # can detect mixed-model drift in the HNSW index and target re-embedding.
    # Default matches the canonical 1024-dim model used by both Ollama
    # (bge-large:latest) and DeepInfra (BAAI/bge-large-en-v1.5) — same vector
    # space, drop-in compatible.
    summary_embedding_model_id: str = "BAAI/bge-large-en-v1.5"

    # Wave A-4 / DEF-033: exponential backoff for ProvisionalEnrichmentWorker
    # On every failed attempt we set ``next_retry_at = utc_now() +
    # min(base * 2^retry_count, max)`` minutes so an LLM outage self-throttles
    # instead of hammering the upstream API on every 5-minute sweep.
    #   base=2:   retry_count=0 → 2 min, =1 → 4, =2 → 8, …, =10 → 2048 → cap.
    #   max=1440: 24 hours — beyond this it is cheaper to mark 'failed' than
    #             keep the row in the queue.
    provisional_enrichment_base_retry_minutes: int = 2
    provisional_enrichment_max_retry_minutes: int = 1440

    # PathExplanationBatchWorker controls (2026-05-23, Wave E2; tuned 2026-05-25 by FIX-LIVE-HH2;
    # cycle dropped 20->12 by PLAN-0095 W4 T-W4-01 on 2026-05-26).
    # batch_size: rows fetched per scheduler tick (ordered by composite_score DESC).
    # concurrency: max parallel LLM calls within a single tick.
    # cycle_minutes: how often the scheduler fires the worker.
    # Tuning (INV-LIVE-HH-2 Option 4): 200->300 batch, 5->7 concurrency, 30->20 min cycle =
    # 3.15x throughput (400 rows/hr -> 1266 rows/hr). 4710-row backlog drain time
    # drops from ~12h to ~3.7h.
    # PLAN-0095 W4 (2026-05-26): cycle 20->12 min adds another 1.67x ticks/hr
    # (3 ticks/hr -> 5 ticks/hr) to drain the iter-9 path-insight backlog. Combined
    # throughput projection: 300 * 7 / 12 = 175 rows/min effective.
    path_explanation_batch_size: int = 300  # KNOWLEDGE_GRAPH_PATH_EXPLANATION_BATCH_SIZE
    path_explanation_concurrency: int = 7  # KNOWLEDGE_GRAPH_PATH_EXPLANATION_CONCURRENCY
    path_explanation_cycle_minutes: int = 12  # KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES

    # Path Insight Worker (PLAN-0074 Wave E1)
    # Model ID for Wave E2 LLM explanations (stored but not used in E1).
    path_insight_explanation_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"
    # Stable worker instance ID — overridable via env var for testing and to ensure
    # disjoint SKIP LOCKED sets when running multiple containers.
    # Default: generated at process start (uuid4 as string, overridden at startup).
    path_insight_worker_instance_id: str = ""
    # APScheduler cron for PathInsightSeeder (default: 02:30 UTC daily).
    path_insight_seeder_cron: str = "30 2 * * *"

    # PLAN-0113 — relational recursive-CTE traversal engine (graph_edges matview).
    # When True, the connection-discovery hot path (pairwise FindPathsBetween use
    # case + PathInsightWorker anchor discovery) uses RelationalGraphPathAdapter
    # over the graph_edges matview instead of the AGE Cypher VLE engine.  Default
    # False (AGE remains the engine) until the relational adapter is validated on
    # the live stack.  Env: KNOWLEDGE_GRAPH_RELATIONAL_TRAVERSAL_ENABLED.
    relational_traversal_enabled: bool = False
    # Per-node fan-out cap for the relational path-array enumeration CTE: a hub
    # with thousands of neighbours must not explode the frontier.  Only used by
    # the relational adapter (the AGE engine has its own _MAX_LIMIT).  Env:
    # KNOWLEDGE_GRAPH_RELATIONAL_TRAVERSAL_DEGREE_CAP.
    relational_traversal_degree_cap: int = 200

    # PLAN-0112 W1 (T-1-04, §AD-5) — hard ceiling on path-discovery hop length.
    # AGE traversal cost grows steeply with hop count; the investigation measured
    # maxhops <= 3 safe (60-800 ms) but maxhops=4 hub-to-hub blew up to 13.8 s on
    # the unpruned graph.  Capped at 3 until the W2 membership-pruning spike
    # re-measures 4/5 on the pruned graph and raises this if p95 stays in budget.
    # Env override: KNOWLEDGE_GRAPH_PATH_MAX_HOPS.
    path_max_hops: int = 3

    # ── PLAN-0112 W3 (T-3-03) — WeirdnessScorer knobs ─────────────────────────
    # weirdness = reliability x (w_U*unexpectedness + w_S*semantic_distance + w_N*novelty)
    # Weights default to (0.45, 0.40, 0.15) per §6.5; tuned in the metric-validation
    # wave against human-judged samples.  Env: KNOWLEDGE_GRAPH_WEIRDNESS_W_*.
    weirdness_w_unexpectedness: float = 0.45
    weirdness_w_semantic: float = 0.40
    weirdness_w_novelty: float = 0.15
    # novelty = fraction of the path's edges with first_evidence_at within this
    # many days.  Small (7) because the graph is only ~3 weeks old (audit Thread 2).
    # Env: KNOWLEDGE_GRAPH_NOVELTY_WINDOW_DAYS.
    novelty_window_days: int = 7
    # Unexpectedness formula selector (AD-3): "config_model" (default,
    # configuration-model surprise -log(deg(u)*deg(v)/2m)) or "adamic_adar".
    # Env: KNOWLEDGE_GRAPH_WEIRDNESS_UNEXPECTEDNESS_MODE.
    weirdness_unexpectedness_mode: str = "config_model"

    @model_validator(mode="after")
    def _validate_startup(self) -> Settings:
        """Validate startup invariants.

        F-007: Production guard — reject skip_verification in production.
        DEF-001: database_url has no default so Pydantic already fails fast at startup
        if KNOWLEDGE_GRAPH_DATABASE_URL is unset; no runtime credential check needed.
        """
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}:
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag.",
            )
        return self
