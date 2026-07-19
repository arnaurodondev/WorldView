"""Service configuration via environment variables."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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

    # nlp_db — owned, Alembic enabled; no default: fails fast if env var missing (DEF-027)
    database_url: SecretStr  # NLP_PIPELINE_DATABASE_URL — required
    database_url_read: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_size_read: int = 20
    db_max_overflow_read: int = 30
    # Universal per-connection statement_timeout (milliseconds) applied to EVERY
    # SQL session on nlp_db AND intelligence_db.  Backstop introduced after FTS
    # ``ts_rank_cd`` / ``ts_headline`` queries (document_search.py) ran ~5 min
    # each against the full 52k-chunk corpus and starved the UI-facing OLTP
    # databases on the shared Postgres instance.  Set as an asyncpg
    # ``server_settings`` connection parameter so it applies immediately.
    #
    # 60_000 ms (60 s) default: broad full-text queries can legitimately take a
    # few seconds, but no interactive search should ever run a full minute; any
    # session that does is the runaway plan this backstop exists to kill.  Set
    # to 0 to disable (unbounded; not recommended).  Background batch workers
    # operate on bounded batches and complete well under 60 s.
    statement_timeout_ms: int = 60_000

    # ── HNSW ANN candidate-pool size (BUG-3 / feat/fix-s6-search-quality) ──────
    # pgvector applies the WHERE filters (source_type, tenant, entity, date) AFTER
    # the HNSW index returns its candidate set. With the pgvector default
    # ``hnsw.ef_search = 40`` the candidate pool is so small that any selective
    # post-filter (e.g. ``source_types=['sec_edgar']`` — ~2% of the corpus) shrinks
    # to near-zero rows. We raise ef_search per-query (``SET LOCAL``) so filtered
    # ANN keeps a usable candidate pool. 200 is a good recall/latency balance for a
    # ~66k-embedding corpus; raise for rarer buckets, lower if latency regresses.
    chunk_ann_ef_search: int = 200

    # ── Filter-first exact KNN (BUG-3 finish / feat/fix-bug3-ann-recall) ───────
    # Raising ef_search alone CANNOT surface a rare source under a HARD post-filter:
    # the HNSW ANN returns the top-ef_search nearest candidates for the *text*
    # query (dominated by the ~98%-news corpus), then the source_type/entity
    # post-filter drops a 2%-density bucket (e.g. sec_edgar = ~1.4k of ~66.8k) to
    # ~0. Fix: when a SELECTIVE filter (source_types / entity_ids / entity_types)
    # is present, filter FIRST (tenant + source_type + entity + date) and run an
    # EXACT ``ORDER BY embedding <=> query`` over just the filtered subset via a
    # MATERIALIZED CTE fence — no HNSW dependence, so the true nearest filtered
    # chunks are GUARANTEED. Exact-sorting a few thousand rows is sub-millisecond.
    # The UNFILTERED path (the 98% case) keeps the fast HNSW ANN unchanged.
    chunk_ann_exact_when_filtered: bool = True

    # Safety bound for the filter-first exact path: if the filtered candidate set
    # exceeds this many rows the filter is NOT selective (HNSW recall is already
    # fine and cheaper), so we fall back to the HNSW ANN path. Sized above the
    # current corpus (~66.8k) so all present filters take the exact path; lower it
    # only if a future, much larger corpus makes exact scans of big buckets slow.
    chunk_ann_exact_max_rows: int = 100_000

    # ── Partial-index accelerated ANN path (S6 chunk-search latency fix) ───────
    # The exact-when-filtered path above exact-sorts the ENTIRE filtered bucket.
    # That was sub-second when a bucket held a few thousand rows, but the R1
    # filings backfill grew ``sec_edgar`` to ~30.5k of ~110k ready embeddings, so
    # the exact sort now takes ~19 s — past rag-chat's 10 s client timeout, so
    # ``get_filings`` gets 0 items. Migration 0024 denormalizes ``source_type``
    # onto chunk_embeddings/section_embeddings and adds a PARTIAL HNSW index per
    # bucket listed here (``idx_chunk_emb_hnsw_<src>``). For a SINGLE source_type
    # in this set (and no entity filter) the repository emits a validated LITERAL
    # ``source_type='<src>'`` predicate so the partial index serves the ANN in
    # ~20 ms with 24-25/25 recall@25 vs exact. Comma-separated; MUST stay in
    # lock-step with the partial indexes created in migration 0024 (adding a value
    # here without the matching index just silently falls back to the exact path).
    chunk_ann_indexed_source_types: str = "sec_edgar"

    # ef_search used specifically on the partial-index accelerated path. Slightly
    # higher than the general chunk_ann_ef_search (200) to keep recall high when a
    # date post-filter co-occurs with the source filter (the date predicate is
    # applied AFTER the HNSW candidate fetch). The partial index only covers one
    # bucket (~30k rows), so even 400 is a few tens of ms.
    chunk_ann_accel_ef_search: int = 400

    # ── FTS planner override (HIGH-1 / feat/fix-s6-search-quality) ────────────
    # The document-search FTS query (document_search.py) has a broad ``tsv_english
    # @@ tsquery`` predicate. For common terms the planner MIS-COSTS a Seq Scan
    # cheaper than the GIN ``ix_chunks_tsv_english_gin`` bitmap scan, because it
    # underestimates the per-row cost of the ``@@`` / ``ts_rank_cd`` operator on
    # the large stored tsvector. Measured live: the Seq Scan took ~55s vs ~3s for
    # the GIN bitmap scan (18x). We disable seq scans transaction-locally
    # (``SET LOCAL enable_seqscan = off``) for the search query so the GIN index
    # is always used. Set False to fall back to the planner default.
    fts_force_index_scan: bool = True

    # intelligence_db — read/write adapter, ALEMBIC_ENABLED MUST stay false
    # no default: fails fast if env var missing (DEF-027)
    intelligence_database_url: SecretStr  # NLP_PIPELINE_INTELLIGENCE_DATABASE_URL — required
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
    # REQ-003 / TASK-W0-06: dedicated consumer group for the entity-refresh
    # consumer (entity.refresh.v1). This field and topic_entity_refresh below
    # were dropped in a config.py merge resolution (BP-590 silent merge data
    # loss), which crash-looped the entity-refresh consumer on a missing
    # Settings attribute; restored here.
    kafka_entity_refresh_consumer_group: str = "nlp-entity-refresh-group"
    # PLAN-0113 FIX-2: opt-in static group membership (KIP-345). Empty (default)
    # = dynamic membership, byte-identical to legacy behaviour. Set per-process
    # to a unique, restart-stable id (dev: numbered compose service e.g.
    # ``article-consumer-0``; prod: StatefulSet pod metadata.name) to skip
    # rebalances on restart. One knob per consumer scope so each fleet can be
    # made static independently.
    kafka_consumer_instance_id: str = ""
    kafka_watchlist_consumer_instance_id: str = ""
    kafka_entity_refresh_consumer_instance_id: str = ""
    kafka_document_deletion_consumer_instance_id: str = ""

    # Topics (consumed)
    topic_article_stored: str = "content.article.stored.v1"
    topic_watchlist_updated: str = "portfolio.watchlist.updated.v1"
    # REQ-003 / TASK-W0-06: manual entity-refresh trigger emitted by S7's
    # TriggerEntityRefreshUseCase; consumed by entity_refresh_consumer_main.
    topic_entity_refresh: str = "entity.refresh.v1"

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
    # PLAN-0063 W5-2 / FR-T1-2: SET key for the canonical tickers cache used
    # by the W5-3 rare-token analyzer to disambiguate tickers from noise
    # uppercase tokens. NLP_PIPELINE_VALKEY_CANONICAL_TICKERS_KEY.
    valkey_canonical_tickers_key: str = "nlp:v1:canonical_tickers"

    # PLAN-0084 C-1 / F-X02: background refresh interval for the canonical
    # tickers cache (seconds). The loop wakes every N seconds and calls
    # refresh() to re-read from intelligence_db. Staleness guarantee:
    # <= N seconds after a source-of-truth change. Range: 60-3600.
    # NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S
    canonical_tickers_refresh_interval_s: int = Field(default=600, ge=60, le=3600)

    # PLAN-0063 W5-3 §0-bis.7 / L9: lexical-leg RRF weight applied when the
    # query has rare identifier tokens. Default 1.5 from the spec; tuned
    # empirically per dataset via ``scripts/eval_retrieval.py --mode
    # hybrid_boost_sweep``. NLP_PIPELINE_HYBRID_LEXICAL_BOOST.
    hybrid_lexical_boost: float = 1.0

    # ── Hybrid chunk-search latency fix (R1 SEC-filings re-QA / 2026-07-06) ─────
    # The POST /api/v1/search/chunks hybrid path ran its two independent legs
    # (ANN vector + BM25/FTS) SEQUENTIALLY on one shared AsyncSession, so
    # end-to-end latency was ~ann + lex (measured 20-22 s warm, 32-40 s under a
    # host-load spike → rag-chat ReadTimeout → empty chat answers). With this
    # flag ON the use case runs the two legs CONCURRENTLY, each on its OWN
    # read-replica session leased from ``nlp_read_factory`` (a SQLAlchemy
    # AsyncSession is NOT safe for concurrent use from one session, so a fresh
    # session per leg is required). The embedding round-trip overlaps the
    # lexical leg, so total latency collapses to ~max(embed+ann, lex).
    # Set False to fall back to the (correct but slow) sequential path — the
    # fused result set is identical either way (RRF is order-only).
    # NLP_PIPELINE_CHUNK_SEARCH_PARALLEL_HYBRID
    chunk_search_parallel_hybrid: bool = True

    # Query-embedding cache TTL (seconds). Query text is embedded once via
    # DeepInfra and cached in Valkey keyed by (model, normalized-query) so
    # repeated/similar chat queries skip the embed round-trip. Short-ish TTL
    # keeps the cache fresh if the embedding model is swapped.
    # NLP_PIPELINE_CHUNK_EMBED_CACHE_TTL_S
    chunk_embed_cache_ttl_s: int = 3600

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
    embedding_api_key: SecretStr = SecretStr("")  # NLP_PIPELINE_EMBEDDING_API_KEY (DEF-019)
    embedding_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # NLP_PIPELINE_EMBEDDING_API_BASE_URL
    embedding_api_model_id: str = "BAAI/bge-large-en-v1.5"  # NLP_PIPELINE_EMBEDDING_API_MODEL_ID
    # Jina AI config (used when embedding_provider="jina")
    jina_api_key: SecretStr = SecretStr("")  # NLP_PIPELINE_JINA_API_KEY (DEF-019)

    # PLAN-0057 QA A-005: tunable retry ceiling for the embedding-retry worker.
    # Was hard-coded to 5 in three places (worker module, repo defaults). Now
    # operator-tunable via NLP_PIPELINE_EMBEDDING_RETRY_MAX_ATTEMPTS so a high
    # error-rate from DeepInfra can be tolerated without a code change.
    embedding_retry_max_attempts: int = 5

    # ── Startup stale-embedding expiry (PRE-1 / PLAN-0031 B-2) ───────────────
    # ``_expire_stale_embeddings`` runs on boot and sets ``expires_at = now()`` on
    # embeddings whose ``model_id`` is not one of the CURRENTLY configured model
    # labels (see ``current_embedding_model_ids``), so the EmbeddingRetryWorker
    # regenerates them after a genuine embedding-model change. In the common case
    # (model unchanged) it matches 0 rows and returns immediately. A GENUINE model
    # change can leave tens of thousands of stale rows, and each expiry forces an
    # HNSW graph re-insert (~0.5 s/row on the grown ~110k-vector corpus) → a single
    # unbounded UPDATE blew the 10-min statement_timeout on EVERY boot (PRE-1). The
    # expiry is therefore drained in bounded, individually-committed batches, off
    # the boot critical path, so it never blocks startup and never trips the
    # per-connection statement_timeout.
    #
    # Rows expired per UPDATE statement. Small enough that one batch (incl. its
    # HNSW churn) stays well under the per-batch timeout below.
    embedding_expiry_batch_size: int = 200  # NLP_PIPELINE_EMBEDDING_EXPIRY_BATCH_SIZE
    # Per-batch statement_timeout (ms), applied via SET LOCAL inside each batch
    # transaction so the one-time large expiry gets more headroom than the 60 s
    # OLTP default without loosening the global backstop. 0 = unbounded (not
    # recommended). 300 s comfortably covers a batch of HNSW re-inserts.
    embedding_expiry_statement_timeout_ms: int = 300_000  # NLP_PIPELINE_EMBEDDING_EXPIRY_STATEMENT_TIMEOUT_MS
    # Safety ceiling on batches per boot run so a pathological predicate can never
    # loop forever. 100_000 * batch_size rows is effectively unbounded for real
    # corpora while still terminating.
    embedding_expiry_max_batches_per_run: int = 100_000  # NLP_PIPELINE_EMBEDDING_EXPIRY_MAX_BATCHES_PER_RUN

    # Deep extraction via external API (DeepInfra / OpenAI-compatible)
    # When extraction_api_key is set, DeepSeekExtractionAdapter is used instead of OllamaExtractionAdapter.
    # Qwen3-235B-A22B-Instruct-2507: $0.071/$0.10 per 1M tokens; 250k context >> 24k max extraction window.
    extraction_api_key: SecretStr = SecretStr("")  # NLP_PIPELINE_EXTRACTION_API_KEY (DEF-019)
    extraction_api_base_url: str = "https://api.deepinfra.com/v1/openai"  # NLP_PIPELINE_EXTRACTION_API_BASE_URL
    extraction_api_model_id: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # NLP_PIPELINE_EXTRACTION_API_MODEL_ID
    # Task #36: SECONDARY model the DeepSeekExtractionAdapter falls back to when the
    # PRIMARY (Qwen3-235B above) is HTTP-429 rate-limited or persistently times out —
    # the post-outage-backlog saturation scenario that was dead-lettering articles.
    # Verified DeepInfra slug; OpenAI-compatible JSON-mode. Empty = fallback disabled.
    # NLP_PIPELINE_EXTRACTION_FALLBACK_MODEL_ID
    extraction_fallback_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"

    # ── Extraction reasoning_effort + max_tokens (PLAN-0111, 2026-06-16 A/B swap) ─
    # gpt-oss-120b / gpt-oss-20b are REASONING models: with no explicit
    # reasoning_effort they spend the whole budget on hidden reasoning and return
    # EMPTY content (docs/audits/2026-06-16-extraction-model-ab-results.md §4).  The
    # value MUST therefore be set explicitly and passed to the adapter.
    #   * Primary  (gpt-oss-120b) = "medium" — validated optimal: recall 3.62 /
    #     precision 4.93 / adherence 4.98 / ~0 fabrication / ~25s p50.
    #   * Fallback (gpt-oss-20b)  = "low"    — validated best fast fallback; does not
    #     need the primary's reasoning budget.  Empty => inherit the primary's effort.
    # NLP_PIPELINE_EXTRACTION_REASONING_EFFORT
    extraction_reasoning_effort: str = "medium"
    # NLP_PIPELINE_EXTRACTION_FALLBACK_REASONING_EFFORT
    extraction_fallback_reasoning_effort: str = "low"
    # max_tokens completion CAP — a ceiling, not a target.  gpt-oss-120b@medium emits
    # at most ~3k completion tokens on the golden set (p50 ~1.4k), so 8192 is pure
    # safety margin the model never fills; the 8192-vs-4096 check measured NO latency
    # difference (same audit).  Kept high so a verbose article never truncates JSON.
    # NLP_PIPELINE_EXTRACTION_MAX_TOKENS
    extraction_max_tokens: int = 8192

    # ── Deep-extraction timeout / retry budget (task #5, 2026-06-16) ──────────
    # The 235B deep tier is LATENCY-bound: the throughput audit measured p50=161s,
    # p95=179s for a full extract() call — yet logs showed "wall-clock timeout after
    # 90.0s".  The 90s came from the ml-clients module-level default
    # (ML_CLIENTS_EXTRACTION_TIMEOUT_S), which an ML_CLIENTS_* env never overrode in
    # the NLP container (its env is NLP_PIPELINE_*).  We now drive these knobs from
    # nlp-pipeline config and pass them EXPLICITLY to DeepSeekExtractionAdapter so the
    # effective per-attempt cap is config-controlled (no reliance on import-time env).
    #
    # BUDGET ARITHMETIC (must fit message_processing_timeout_s = 900s watchdog):
    #   * per-attempt cap = 300s  → a p95 (179s) call completes comfortably instead of
    #     being cut at 90s and wastefully retried.
    #   * max_attempts = 2  → with a 300s cap, 2 attempts is the most that fits the
    #     per-model budget without blowing the watchdog (was 3 at the old 90s cap).
    #   * total_budget_s = 320s  → one full 300s attempt + a short backoff + an early
    #     bail before a second 300s attempt that wouldn't fit.  In practice the p95
    #     completes on attempt 1, so the budget is rarely re-spent.
    #   * Worst case per window (primary 320 + fallback fresh 320) ≈ 640s, + GLiNER NER
    #     (~160s) + writes ≈ 820s < 900s watchdog.  See message_processing_timeout_s.
    # All env-overridable via the NLP_PIPELINE_* names below.
    # NLP_PIPELINE_EXTRACTION_TIMEOUT_S
    extraction_timeout_s: float = 300.0
    # NLP_PIPELINE_EXTRACTION_MAX_ATTEMPTS
    extraction_max_attempts: int = 2
    # NLP_PIPELINE_EXTRACTION_TOTAL_BUDGET_S
    extraction_total_budget_s: float = 320.0

    # GLiNER: when set, use the HTTP adapter (containerised GLiNER server).
    # Leave empty to fall back to GLiNERLocalAdapter (in-process model).
    gliner_base_url: str = ""

    # Per-request HTTP timeout (seconds) the article-consumer applies when calling
    # the containerised GLiNER server's /ner/batch endpoint.
    #
    # WHY 240s (was 60s): after the intra-consumer concurrency bump (16
    # handlers/replica x3) + server-side micro-batcher, the GLiNER forward pass is
    # CPU-bound and GIL/collector-serial — ONE batch runs at a time. Measured live
    # under concurrent load, a single 16-text /ner/batch call took ~79s end-to-end
    # (queue wait + forward pass) while the server sat pinned at ~1 core of a
    # 14-core host (the transformer inference does not parallelise across cores at
    # these batch sizes). An article with up to 32 sections is two such batches
    # (~160s), so the old 60s — and even an interim 120s — client timeout was being
    # exceeded → spurious "GLiNER server timeout" retries even though the server
    # returns 200s. Those retries re-enqueue work and make the saturation worse.
    #
    # This is genuine GLiNER capacity saturation, NOT a client bug. The durable fix
    # is the routing change that cuts full-pipeline volume (separate work) and/or
    # scaling GLiNER off the saturated host. Raising the timeout is the cheap, safe
    # mitigation: it lets a healthy-but-slow request finish instead of being failed
    # and retried. 240s keeps headroom under message_processing_timeout_s (450s) so
    # the outer Kafka handler still bounds a truly hung call. Env-configurable so
    # ops can tune without a rebuild.
    gliner_request_timeout_s: float = 240.0  # NLP_PIPELINE_GLINER_REQUEST_TIMEOUT_S

    # Minimum word count for an article to enter the NLP pipeline.
    # Articles below this threshold are skipped (too short for meaningful extraction).
    min_word_count: int = 50  # NLP_PIPELINE_MIN_WORD_COUNT

    # BP-719 Mode B: cap the number of words fed to Block-10 deep extraction so the
    # ML phase fits inside the 900s Kafka message watchdog on very large filings
    # (20-48k-word 10-Q/10-K). Deep extraction runs on the first N words only;
    # the rest of the document is STILL fully chunked + embedded + indexed by the
    # phase-1 searchable write, so retrieval coverage is unaffected — only the
    # KG-relation extraction is bounded (and remains backfillable). 0 disables the
    # cap (process every window; the pre-BP-719 behaviour). Override via env
    # NLP_PIPELINE_DEEP_EXTRACTION_MAX_WORDS.
    deep_extraction_max_words: int = 0  # NLP_PIPELINE_DEEP_EXTRACTION_MAX_WORDS

    # P0-A poison-pill safety bound (prod review 2026-07-15): cap the number of
    # deep-extraction WINDOWS a single article may consume in one handler call.
    # A pathological many-mention / very-long article can otherwise run dozens of
    # sequential 235B extraction windows (each up to ``extraction_timeout_s``)
    # inside ONE ``_handle_message`` call, monopolising a bounded handler slot for
    # tens of minutes and starving the consumer group. Beyond the cap the good
    # windows are PERSISTED and the remainder is skipped with ``degraded=true`` +
    # ``skipped_windows`` so the loss is visible and the doc stays backfillable
    # (workers/backfill_entity_mentions.py) — never a silent drop.
    #
    # This is a belt to the braces of the per-window liveness heartbeat: the
    # heartbeat keeps a slow-but-progressing article's ``/healthz`` alive, and this
    # cap bounds the worst case so no single article can hold a handler slot
    # indefinitely. Cap chosen (12) from the observed live window distribution; a
    # typical FULL_PIPELINE article is well under it, so the cap only bites on
    # outliers. 0 disables the cap (process every window). Env-overridable so ops
    # can tune without a rebuild. NLP_PIPELINE_EXTRACTION_MAX_WINDOWS_PER_DOC
    extraction_max_windows_per_doc: int = 12

    # GLiNER thresholds (PRD §6.7 Block 4)
    gliner_threshold: float = 0.35  # for routing/novelty signal
    gliner_resolution_threshold: float = 0.45  # for entity resolution cascade
    gliner_batch_size: int = 32
    gliner_section_token_limit: int = 450  # truncate sections before NER
    gliner_nms_iou_threshold: float = 0.5  # Non-Maximum Suppression overlap threshold
    # PLAN-0078 Wave B: minimum GLiNER confidence score for storing a mention in
    # chunks.entity_mentions JSONB (avoids index bloat from low-confidence noise).
    gliner_mention_floor: float = 0.6

    # PLAN-0093 C-2 (F-NPL-005): minimum GLiNER confidence to PERSIST a mention
    # to the entity_mentions table. Separate from gliner_mention_floor so the
    # JSONB cache and table can be tuned independently. Override via env
    # NLP_PIPELINE_MIN_PERSIST_FLOOR.
    min_persist_floor: float = 0.6

    # Routing tier thresholds (PRD §6.7 Block 5)
    routing_tier_deep: float = 0.70  # score >= this → DEEP processing
    # Lowered from 0.45: watchlist signal fires post-resolution, effective max without it is ~0.44
    routing_tier_medium: float = 0.35  # score >= this → MEDIUM processing
    routing_tier_light: float = 0.20  # score >= this → LIGHT processing

    # ── Deep-extraction VALUE gate (backlog-drain lever, 2026-07-17) ─────────────
    # Ref: docs/audits/2026-07-17-article-backlog-lever.md.
    #
    # PROBLEM the gate solves: the per-article cost is dominated by the DeepInfra
    # deep-extraction LLM chain (~2.9 calls/article: DeepSeek-V4-Flash extraction +
    # relation/claim entailment). The routing tier router does NOT gate that load —
    # BOTH the MEDIUM and DEEP tiers map to ProcessingPath.FULL_PIPELINE, so every
    # non-LIGHT article runs the full chain. Measured on prod (nlp_db.routing_decisions,
    # recent 3k rows under the live thresholds DEEP=0.45/MEDIUM=0.35/LIGHT=0.20):
    # ~69% of intake ran the full deep-extraction chain, only ~31% (LIGHT) skipped.
    # Deep-extraction throughput (~10-14/min) trailed intake (~15-18/min) → the
    # ~192k-article backlog never drained.
    #
    # THE GATE: skip the expensive chain (entity resolution + LLM extraction + guards)
    # for genuinely LOW-VALUE docs whose composite routing score is below
    # ``deep_extraction_score_floor`` — routing them to the SAME cheap path LIGHT
    # already uses (chunk embeddings ONLY → still fully searchable, no KG extraction).
    # It is conservative by construction (see apply_deep_extraction_value_gate):
    #   * never touches a doc already on a cheap path (LIGHT/SUPPRESS),
    #   * never touches an authoritative regulatory filing (always extracted),
    #   * never touches a doc scoring at/above the floor (high-value always extracted),
    #   * retrieval is preserved for every skipped doc (chunk embeddings still written;
    #     KG extraction remains backfillable from the persisted chunks/mentions).
    #
    # DEFAULT FLOOR 0.50 (env-tunable, NO rebuild): under the live prod score
    # distribution this gates the [0.35, 0.50) score band (~41% of recent intake, the
    # low-value tail just above the LIGHT cutoff) OUT of deep extraction. Combined with
    # the ~31% already-LIGHT, ~72% of intake then skips the LLM chain and only ~28%
    # runs it — a ~59% cut in deep-extraction volume + DeepInfra spend, flipping drain
    # rate comfortably above intake. Tune DOWN to 0.45 (gentler: gates only [0.35,0.45),
    # ~28% of intake) or UP to 0.55 to drain faster. Set the enabled flag False to
    # restore the pre-gate behaviour (every MEDIUM/DEEP doc runs the full chain).
    # NLP_PIPELINE_DEEP_EXTRACTION_VALUE_GATE_ENABLED
    deep_extraction_value_gate_enabled: bool = True
    # NLP_PIPELINE_DEEP_EXTRACTION_SCORE_FLOOR
    deep_extraction_score_floor: float = Field(default=0.50, ge=0.0, le=1.0)

    # ── Learned routing classifier (PLAN-0111 C-2 / C-6) ─────────────────────
    # Controls the EmbeddingGemma-based learned router that runs ALONGSIDE the
    # static weighted-sum router:
    #   "off"    — the learned router is not loaded or invoked at all.
    #   "shadow" — the learned router computes a proposed tier on every article
    #              (logged + persisted + counted) but NEVER changes the processing
    #              path; the static router still controls everything.
    #   "live"   — the (post-cascade) learned tier CONTROLS processing
    #              (PLAN-0111 C-8). The learned tier is written to
    #              ``final_routing_tier`` so the suppression gate + downstream
    #              embedding/extraction blocks read it. The STATIC tier is still
    #              computed + persisted (in ``routing_tier``) for ongoing
    #              comparison. SUPPRESS still HALTs and the regulatory-filing /
    #              authenticated-upload override still forces at least MEDIUM.
    # Default "off" so the feature is opt-in per environment via
    # NLP_PIPELINE_LEARNED_ROUTER_MODE; docker.env sets it to "live".
    learned_router_mode: Literal["off", "shadow", "live"] = "off"

    # ── Learned-router LLM CASCADE (PLAN-0111 C-7) ───────────────────────────
    # FrugalGPT / learning-to-defer cascade: when the calibrated P(yield) lands
    # in the AMBIGUOUS band [thr_extract-0.10, thr_extract+0.10] the cheap
    # embedding classifier is UNCERTAIN. Rather than commit to a coin-flip, we
    # escalate ONLY that uncertain slice (~14% of articles per the 24h shadow) to
    # the existing small generative relevance scorer (the Llama-3.1-8B
    # title-relevance model reused from ``ArticleRelevanceScoringWorker``) for a
    # tiebreak. Documents OUTSIDE the band skip the LLM entirely — that is the
    # whole point: cheap majority, LLM only on the genuinely-borderline minority.
    #
    # When False (default) the router behaves exactly as C-6/C-6b: the in-band
    # tier comes straight from ``map_p_yield_to_tier`` with no LLM call. Gate it
    # ON per environment via NLP_PIPELINE_LEARNED_ROUTER_CASCADE; docker.env
    # enables it. The cascade only adds latency/cost on the in-band slice.
    learned_router_cascade: bool = False

    # Decision cutoff for the cascade tiebreak (PLAN-0111 C-7). When an in-band
    # article is escalated to the Llama-8B relevance scorer, an LLM relevance
    # probability >= this value routes the article to MEDIUM (worth extracting);
    # below it routes to LIGHT. 0.5 is the natural midpoint of the [0,1]
    # relevance scale the scorer emits — documented + tunable without a rebuild.
    learned_router_cascade_relevance_cutoff: float = 0.5

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

    # ── Co-mention entailment check (ENHANCEMENT #6, prototype — default OFF) ──────
    # A cheap LLM entailment gate that drops relations whose evidence merely
    # CO-MENTIONS subject and object instead of asserting the relation with a
    # relation-bearing verb/phrase. Measured on a 443-relation strong-judge gold set
    # (docs/audits/2026-06-21-relation-entailment-check-prototype.md):
    #   Qwen3-235B: 0% false-positive on high-risk predicates, 88.6% defect recall,
    #   ~$0.07 per 1k checks. gpt-oss-20b was rejected (27.6% FP — kills good relations).
    # Default OFF so this is a safe, opt-in prototype: enabling it changes extraction
    # output, so it must be turned on deliberately (and watched) in any environment.
    # Enabling ALSO requires wiring an entailment_client in article_consumer_main (a
    # Qwen3-235B adapter) — until then the block stays a no-op even if this flag is True.
    relation_entailment_check_enabled: bool = False  # NLP_PIPELINE_RELATION_ENTAILMENT_CHECK_ENABLED
    # Only relations whose predicate is in this set are checked (high-risk co-mention
    # promoters per the audit). Comma-separated env override. Keep tight: every other
    # predicate skips the LLM call entirely (cost + latency control).
    relation_entailment_check_predicates: str = (
        "competes_with,regulates,produces,partner_of,supplier_of"  # NLP_PIPELINE_RELATION_ENTAILMENT_CHECK_PREDICATES
    )
    # Confidence floor below which the check's NOT_ASSERTED verdict is IGNORED (kept).
    # The prompt is tuned to only answer NOT_ASSERTED when confident; this is a second
    # guard so a low-confidence "drop" never destroys a relation.
    relation_entailment_check_min_drop_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    # Max risky relations checked per document (hard cap on added cost/latency per article).
    relation_entailment_check_max_per_doc: int = Field(default=20, ge=0, le=200)

    # ── Evidence-span grounding gate (2026-07-16 fabrication filter) ──────────────
    # Deterministic, free, model-agnostic post-extraction filter that drops any
    # claim/relation whose ``evidence_text`` is NOT verbatim-traceable to the source
    # passage (a normalised substring). The DEEP_EXTRACTION prompt already REQUIRES a
    # verbatim quote per item; this gate enforces that requirement instead of trusting
    # it. The 2026-07-16 model bake-off measured fabrication (ungrounded items) as the
    # top quality drag (2.13/art live 235B, 0.83/art DeepSeek-V4-Flash), and CLAIMS were
    # the largest previously-unguarded slice (relation_validation only touches relations).
    # A faithfully-quoted item is always a substring of its source, so the gate is
    # yield-neutral on faithful output — it removes only items the model could not ground.
    # Modes: "off" (no-op) | "present_only" (drop only when evidence_text is present but
    # ungrounded) | "require" (also drop items with a missing/blank quote). Claims schema-
    # require evidence_text so "require" is defensible for them; relations do not, so
    # "present_only" avoids penalising a legitimately quote-less relation.
    # NLP_PIPELINE_EVIDENCE_GROUNDING_CLAIMS_MODE
    evidence_grounding_claims_mode: str = "present_only"
    # NLP_PIPELINE_EVIDENCE_GROUNDING_RELATIONS_MODE
    evidence_grounding_relations_mode: str = "present_only"

    # ── Claim/relation entailment pass (2026-07-16 semantic-mislabel fabrication cure) ──
    # A cheap LLM entailment gate that drops CLAIMS of high-fabrication claim_types whose
    # evidence quote does NOT entail the assigned label (a refinancing tagged DEBT_CHANGE,
    # a segment mention tagged REVENUE_GROWTH, a plain release tagged GUIDANCE_RAISE, or an
    # inverted polarity). The 2026-07-16 fabrication investigation
    # (docs/audits/2026-07-16-extraction-fabrication.md) found fabrication is SEMANTIC
    # MISLABELLING of verbatim quotes — the models quote correctly but mis-type — and that
    # CLAIMS were the largest previously-UNGUARDED slice (validate_relations + the
    # relation entailment gate touch relations only). A substring check (evidence_grounding)
    # cannot catch a mislabel; only semantic entailment can. See application/blocks/
    # claim_entailment.py for the design and the audit's measured 0%-FP entailment template.
    # Default OFF so this is a safe, opt-in prototype: enabling it changes extraction output.
    # Enabling ALSO requires wiring a verifier client in article_consumer_main (built from
    # the extraction key); until then the block stays a no-op even if this flag is True.
    claim_entailment_check_enabled: bool = False  # NLP_PIPELINE_CLAIM_ENTAILMENT_CHECK_ENABLED
    # Only claims whose claim_type is in this set are checked (high-fabrication buckets per
    # the audit §1). Comma-separated env override. Keep tight: every other claim_type skips
    # the LLM call entirely (cost + latency control) so this stays ~1-2 calls/doc.
    claim_entailment_check_claim_types: str = (
        # NLP_PIPELINE_CLAIM_ENTAILMENT_CHECK_CLAIM_TYPES
        "DEBT_CHANGE,REVENUE_GROWTH,GUIDANCE_RAISE,GUIDANCE_CUT,HEADCOUNT_CHANGE,EPS_BEAT"
    )
    # Confidence floor below which a NOT_ENTAILED verdict is IGNORED (the claim is kept).
    # Second guard so a low-confidence "drop" never destroys a good claim.
    claim_entailment_check_min_drop_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    # Max gated claims checked per document (hard cap on added cost/latency per article).
    claim_entailment_check_max_per_doc: int = Field(default=20, ge=0, le=200)
    # Verifier model. Default = the cheap live-extraction-class model. The audit REJECTED
    # weaker verifiers (gpt-oss-20b: 27.6% FP kills good items); the verifier MUST be at
    # least DeepSeek-V4-Flash / Qwen3-235B class. NLP_PIPELINE_CLAIM_ENTAILMENT_CHECK_MODEL_ID
    claim_entailment_check_model_id: str = "deepseek-ai/DeepSeek-V4-Flash"

    # ── Concurrency (Task #14 — ~50 articles in flight platform-wide) ──────────
    # Deep extraction on DeepInfra is I/O-bound (12-22s network wait per article),
    # NOT CPU-bound.  The base Kafka consumer loop is strictly serial (one article
    # per replica), so each replica idles ~20s waiting on DeepInfra.  Two levers:
    #
    # 1. ``article_consumer_concurrency`` — the ArticleProcessingConsumer overrides
    #    the serial poll loop with a bounded-concurrency dispatcher: up to N message
    #    handlers run concurrently per replica, overlapping their DeepInfra waits.
    #    With 12 partitions / 3 replicas (4 partitions each) and N=16, the platform
    #    reaches ~48 concurrent articles (3 x 16).  Offsets commit only up to the
    #    highest *contiguous* completed offset per partition, preserving at-least-once
    #    and per-partition ordering (see ArticleProcessingConsumer.run docstring).
    # NLP_PIPELINE_ARTICLE_CONSUMER_CONCURRENCY
    article_consumer_concurrency: int = 16
    # 2. ``deepinfra_max_connections`` — sizes the httpx connection pool inside the
    #    DeepSeekExtractionAdapter so N concurrent extraction calls per replica do
    #    not queue at the client.  Default 64 = 16 concurrent + comfortable headroom
    #    for embedding calls sharing the host.  ``deepinfra_max_keepalive`` keeps
    #    warm TCP+TLS connections so DeepInfra's KV prefix cache stays hot.
    # NLP_PIPELINE_DEEPINFRA_MAX_CONNECTIONS
    deepinfra_max_connections: int = 64
    # NLP_PIPELINE_DEEPINFRA_MAX_KEEPALIVE
    deepinfra_max_keepalive: int = 32

    # Per-message processing budget (watchdog) for the article consumer.  A handler
    # that exceeds this is cancelled and the message is dead-lettered.  Deep-tier
    # extraction (Qwen3-235B-A22B) has a bursty latency tail; at a 300s budget paired
    # with a 90s extraction wall-clock cap, ~216 docs/hr dead-lettered.  Was 450s
    # (paired with the old 150s single-model extraction budget).
    #
    # TASK #5 RE-BUDGET (2026-06-16, raise the extraction per-attempt cap to 300s):
    #   The 235B is LATENCY-bound (p50=161s, p95=179s for a full extract()).  The old
    #   90s per-attempt cap guaranteed mass "wall-clock timeout after 90.0s" failures
    #   on calls that would have succeeded at ~180s.  We raise the per-attempt cap to
    #   300s and drop max_attempts to 2 (see extraction_timeout_s above) so a p95 call
    #   completes on attempt 1.  The per-MODEL budget is ~320s; with the Task #36
    #   fallback hop a window can in the WORST case spend primary(320) + fallback(320)
    #   ≈ 640s.  Almost all articles are single-window (<=24k tokens => one window, see
    #   SINGLE_WINDOW_TOKEN_LIMIT), so the dominant per-doc cost is one window plus the
    #   surrounding pipeline (GLiNER NER ~160s under load, embedding, resolution,
    #   writes).  We raise the watchdog to 900s so:
    #       1 window (primary 320 + fallback 320) + NER 160 + ~100 slack ≈ 900
    #   This keeps the resilience (retry + fallback hop) from itself tripping the
    #   watchdog and re-creating the dead-letter bleed it was meant to stop.  In the
    #   common (no-fallback) path a window is ~300s, leaving huge headroom.  Tunable
    #   via the env var below.
    # NLP_PIPELINE_MESSAGE_PROCESSING_TIMEOUT_S
    message_processing_timeout_s: int = 900

    # Dispatcher
    dispatcher_poll_interval_secs: float = 1.0
    dispatcher_batch_size: int = 50

    # Storage (MinIO/S3 for Silver tier reading and chunk text persistence)
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    chunk_bucket: str = "worldview"
    silver_bucket: str = "worldview-silver"

    # External service base URLs (PLAN-0064 W6 — document search needs S5 + S7 batch calls)
    # These are used by the API process only (dependency injection in dependencies.py).
    # Defaults point to the Docker Compose service names; override via env vars in production.
    content_store_internal_url: str = "http://content-store:8005"  # NLP_PIPELINE_CONTENT_STORE_INTERNAL_URL
    knowledge_graph_internal_url: str = "http://knowledge-graph:8007"  # NLP_PIPELINE_KNOWLEDGE_GRAPH_INTERNAL_URL

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
    relevance_scoring_api_key: SecretStr = SecretStr("")  # NLP_PIPELINE_RELEVANCE_SCORING_API_KEY (DEF-019)
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
    unresolved_resolution_api_key: SecretStr = SecretStr("")  # NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY (DEF-019)
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
    def _validate_startup(self) -> Settings:
        """Validate startup invariants.

        F-007: Production guard — reject skip_verification in production.
        DEF-027: database_url and intelligence_database_url have no defaults so Pydantic
        already fails fast at startup if the env vars are unset; no runtime check needed.
        """
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}:
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag."
            )
        return self
