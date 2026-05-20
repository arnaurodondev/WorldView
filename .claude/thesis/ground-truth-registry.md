# Worldview Ground Truth Registry

Generated: 2026-05-19
Status: LOCKED
Source: Phase 1 discovery (10 services + libs + infrastructure + draft audit)

This is the canonical source of truth for all thesis-writing subagents.
If a writing subagent encounters a conflict between the existing draft
and this registry, the registry wins. Discrepancies with prior memory
or skill defaults are noted in §"Known Discrepancies".

---

## System Facts (canonical)

| Fact | Value | Source |
|------|-------|--------|
| Backend services | 10 (S1–S10) + intelligence-migrations DDL owner | services/ |
| Shared Python libraries | 8 (common, contracts, messaging, storage, observability, ml-clients, prompts, tools) | libs/ |
| PostgreSQL databases | 11 (portfolio, ingestion, market_data, content_ingestion, content_store, nlp, intelligence (shared S6+S7), kg (AGE), rag, gateway, alert) | infra init script |
| Docker Compose containers — full production infra profile | **88** (10 services + ~40 workers/consumers/dispatchers/migrations + 13 observability + 1 frontend + databases) | compose.yml |
| Docker Compose containers — "core platform" (services + workers + dbs + infra, no observability stack) | **~54** (this is what the existing draft cites) | derivation |
| Kafka topics — declared via .avsc / init scripts | **22 regular + 1 compacted** (`entity.dirtied.v1`) | infra/kafka/schemas |
| Kafka topics — auto-created at runtime by services | +6 (`nlp.document.ready.v1`, `intelligence.temporal_event.v1`, `entity.canonical.created.v1` variants, `entity.narrative.generated.v1`, `entity.provisional.queued.v1`, `content.document.deleted.v1`) | service code |
| NLP pipeline blocks | **8** (Blocks 3–10 in code numbering; the *first* eight blocks shipped) | services/nlp-pipeline |
| GLiNER entity classes | **11** (canonical list — see §GLiNER) | services/nlp-pipeline/.../mention_class enum |
| API endpoints — S9 API Gateway | **141 routes across 12 domain modules** (post-PLAN-0089 split of 4,319-line proxy.py) | services/api-gateway/src/routes |
| Frontend user journeys | 5 (J1–J5) | docs/PRODUCT_CONTEXT.md |
| Data sources | 4 production (EODHD, SEC EDGAR, Finnhub, NewsAPI) + Polymarket (predictions) + tenant uploads (private) | S2/S4 adapters |
| Embedding model | BAAI/bge-large-en-v1.5 (1024-dim) via DeepInfra; Ollama bge-large fallback | libs/ml-clients |
| NER model | GLiNER `urchade/gliner_large-v2.1` via local GLiNER server (no external alternative) | services/nlp-pipeline |
| Deep extraction LLM | **Qwen/Qwen3-235B-A22B-Instruct-2507** via DeepInfra; Ollama `qwen2.5:7b-instruct` fallback | services/nlp-pipeline Block 10 |
| Relevance + unresolved-resolution LLM | meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo via DeepInfra; Ollama qwen3:0.6b fallback | services/nlp-pipeline workers |
| Intent classification LLM | meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo via DeepInfra; Ollama fallback | services/rag-chat |
| Chat completion LLM | **Qwen/Qwen3-235B-A22B-Instruct-2507** via DeepInfra (primary). Fallback chain: OpenRouter `deepseek/deepseek-r1-distill-qwen-32b` → Ollama `deepseek-r1:32b` (emergency) | services/rag-chat config |
| Entity description LLM | Google Gemini 3.1 Flash Lite (hardcoded in DefinitionRefreshWorker) | services/knowledge-graph |
| Graph database | Apache AGE (PostgreSQL extension) | infra/postgres |
| Vector index type | HNSW (pgvector); three partial indexes per view_type (definition/narrative/fundamentals_ohlcv); financial_instrument-only for fundamentals_ohlcv | intelligence-migrations |
| Embedding dimension | 1024 (hardcoded; mismatch is FatalError) | libs/ml-clients |
| Retrieval modalities | **4**: ANN (pgvector HNSW), BM25 (tsvector GIN), KG traversal (AGE Cypher), SQL (structured) | services/rag-chat |
| Fusion method | Reciprocal Rank Fusion, k = 60 | services/rag-chat |
| Query expansion | HyDE conditional on REASONING/RELATIONSHIP intents; 30-min Valkey cache | services/rag-chat |
| Frontend stack | Next.js 15 App Router + shadcn/ui only (dark theme, pnpm exact-pin) | apps/worldview-web |
| Auth provider | Zitadel Cloud (OIDC, PKCE) | services/api-gateway |
| Auth model | Two-level JWT: external RS256 (Zitadel) → internal RS256 (S9-signed, X-Internal-JWT header, JWKS at /internal/jwks) | services/api-gateway |
| Infrastructure cost claim | $0 infrastructure (single docker-compose) + <$50/mo external APIs | derived |
| Relation predicate vocabulary | ~30 canonical types in `relation_type_registry` seed (employment, ownership, supplier, customer, subsidiary, partnership, competitor, …) | intelligence-migrations |

---

## GLiNER entity classes (the eleven)

Canonical list from `MentionClass` enum in services/nlp-pipeline:

1. `organization`
2. `government_body`
3. `regulatory_body`
4. `financial_institution`
5. `person`
6. `financial_instrument`
7. `location`
8. `commodity`
9. `index`
10. `currency`
11. `macroeconomic_indicator`

> The existing thesis draft lists "Product, Event, Regulation, Technology, Other" — **these are wrong and must be replaced** in Ch. 4 §4.3 Block 2 with the correct list above.

---

## Per-Service Summary

### S1 Portfolio (port 8001, portfolio_db)
**Mission**: Tenant/user management, portfolio CRUD, FIFO holdings, watchlists, alert preferences, brokerage sync (SnapTrade), feedback.
**Key**: 4-step idempotent OIDC provisioning (sub-lookup → email-link → conflict → create); R23 read replica split (ReadOnlyUnitOfWork via ReadUoWDep); SnapTrade callback supports Portal v3+v4; Fernet-encrypted secrets; daily portfolio snapshot at 21:30 UTC with data_quality flag (ok / partial_prices); brokerage sync 4-hour cycle; sync errors are never retried by design.
**Thesis facts**: FIFO open-lot tracking with 365-day ST/LT classification; R23 split (write_factory vs read_factory); S1 NEVER maintains reverse entity→user index — S10 consumes `portfolio.watchlist.updated.v1` directly.

### S2 Market Ingestion (port 8002, ingestion_db)
**Mission**: Scheduled polling of 6 providers (EODHD, Yahoo, Finnhub, Polygon, Alpaca, Alpha Vantage stub) plus Polymarket; bronze/silver/canonical MinIO claim-check.
**Key**: 5 independent processes (API, Scheduler, Worker, Dispatcher, Reclaim) per Docker image; lease-based optimistic locking; exponential backoff 60s..3600s ±20% jitter; provider routing via config weights (5-min TTL); Yahoo→EODHD failover after 5 zero-bar streak (Valkey 24h TTL); EODHD demo key restricts to 3 endpoints; Officers/Holders.Institutions/Revenue_Segment fields **do not exist** on EODHD — use Insider Transactions endpoint instead.
**Thesis facts**: Watermark-driven incremental polling per (provider, dataset_type, variant, symbol, exchange, timeframe) 6-tuple; 4-tier symbol cadence (Tier 0 highest, Tier 4 lowest); claim-check produces `market.dataset.fetched`.

### S3 Market Data (port 8003, market_data_db = TimescaleDB)
**Mission**: Materialize OHLCV/quotes/fundamentals from claim-check events; 41 query endpoints; Polymarket prediction snapshots.
**Key**: TimescaleDB hypertables on `ohlcv_bars` (chunk on bar_date) and `prediction_market_snapshots` (chunk on snapshot_at); automatic compression policy on chunks >30 days; screener uses `COUNT(*) OVER()` for single-pass total; IntradayResamplingWorker derives 5m/15m/30m/1h/4h/1d from 1m bars (is_partial+is_derived flags); cache-aside Valkey quote cache (5s TTL); 10-metric `instrument_fundamentals_snapshot` derived projection (eps_ttm, beta, avg_volume_30d, OCF, CapEx, FCF, FCF margin, interest coverage, net_debt_to_EBITDA, credit_rating) with COALESCE-on-update so partial polls don't NULL-out fields.
**Thesis facts**: HNSW vs IVFFlat is **not S3's concern**; S3 uses TimescaleDB only. p95 chart-query target <200 ms via chunk exclusion + read replica.

### S4 Content Ingestion (port 8000 in container, content_ingestion_db)
**Mission**: Scheduled fetch of news/SEC/Polymarket/tenant docs → MinIO bronze → Kafka claim-check.
**Key**: 4 independent processes (API, Scheduler, Worker, Dispatcher); 5 adapters (EODHD news 15min, SEC EDGAR 30min, Finnhub 15min, NewsAPI 4h, Polymarket dedicated 900s timeout); per-adapter token-bucket rate limiting; Valkey daily counter for NewsAPI free tier (100/day); compensating GC deletes MinIO bronze keys on transaction failure; tenant document upload (≤50 MB, soft-delete emits `content.document.deleted.v1`); DocumentReadyConsumer marks upload `ready` after S6 emits `nlp.document.ready.v1`.
**Thesis facts**: 4 production data sources confirmed (EODHD, SEC EDGAR, Finnhub, NewsAPI) + Polymarket + tenant uploads.

### S5 Content Store (port 8005, content_store_db)
**Mission**: 3-stage dedup (exact SHA-256 → normalized URL+text SHA-256 → MinHash LSH); canonical ID assignment; silver bucket write.
**Key**: 4 bands × 32 rows per band = 128 MinHash permutations stored as `INTEGER[]` (not BYTEA); per-source Jaccard thresholds (hard/soft) and Valkey LSH TTLs (EODHD 7d, SEC 180d, Finnhub 60d, NewsAPI 7d, manual 30d); CorroborationPolicy outcomes: SAME_SOURCE_DUPLICATE (suppress) / CORROBORATING (retain both, `corroborates_doc_id` link) / SEMANTIC_NEAR_DUPLICATE (retain, cluster) / UNIQUE; LSH indexed in Valkey **post-commit** (CR-3 compliance); bronze bytes pre-fetched **before** DB session opens (R24); per-tenant partial unique indexes for global vs tenant-private scope.
**Suppression catch rate**: ~30–40 % of raw ingested articles (PRD §6.7 Block 2).
**Thesis facts**: S5 is purely Jaccard-threshold dedup — **not** ML-scored, **not** signal-weighted; the 8-signal routing score lives in S6 Block 5, not S5. The `display_relevance_score = 0.5×market + 0.4×llm + 0.1×routing` weighting is computed at query time, not in S5.

### S6 NLP Pipeline (port 8006, nlp_db + read-only intelligence_db)
**Mission**: 8-block enrichment + 4 background workers; emits enriched articles and signals.
**Eight blocks** (Block 3–10 in code numbering):
1. **Block 3 — Sectioning** (`NewsParagraphSectioner` / `SECEdgarSectioner` / `FinnhubTranscriptSectioner` / `SyntheticSectioner` fallback). Always emits ≥1 section.
2. **Block 4 — GLiNER NER** (`run_ner_block`). 11 classes. NMS IoU > 0.5 (strict). Thresholds: NER 0.35, resolution 0.45, mention floor 0.60. **Zero mentions NEVER suppresses a doc.**
3. **Block 5 — Routing score** (`compute_routing_score`). 8 signals with weights that sum to exactly 1.0: entity_density 0.25, source_reliability 0.20, novelty 0.15, recency 0.10 (exp(-0.02h)), watchlist 0.10 (Valkey SET overlap), price_impact 0.10 (from article_impact_windows), document_type 0.05, extraction_yield 0.05. Tiers: DEEP ≥0.70, MEDIUM ≥0.35, LIGHT ≥0.20, SUPPRESS <0.20. Authoritative SEC filings get LIGHT→MEDIUM upgrade.
4. **Block 6 — Suppression gate** (`apply_suppression_gate`). Maps tier to ProcessingPath: SUPPRESS→HALT, LIGHT→SECTION_EMBEDDINGS_ONLY, MEDIUM/DEEP→FULL_PIPELINE.
5. **Block 7 — Embedding** (`run_embeddings_block`). Sentence-aware chunking: 512-token max, 64-token overlap, source-specific targets (news 280, filings 325, earnings 300). Sections embedded all tiers; chunks only MEDIUM/DEEP. BAAI/bge-large-en-v1.5 via DeepInfra (primary) or Jina or Ollama. MinIO silver upload of chunk texts. `embedding_pending` retry queue.
6. **Block 8 — Novelty gate** (`run_novelty_gate`). Two stages, both best-effort. Stage 1: MinHash similarity ≥0.80 → DEEP→LIGHT. Stage 2: ALL resolved entities cosine similarity ≥0.90 (HNSW on narrative view) → DEEP→LIGHT.
7. **Block 9 — Entity resolution cascade** (`run_entity_resolution_block`). 4 stages: (1) Exact alias 1.00, (2) Ticker/ISIN 0.95, (3) Fuzzy trigram >0.75 weighted ×0.90, (4) ANN HNSW on definition view, distance <0.35, margin >0.10, weighted ×0.95. AUTO_RESOLVED ≥0.62; PROVISIONAL ≥0.45 (insert into `provisional_entity_queue`); UNRESOLVED <0.45 (preserved, never discarded per R19). Provisional churn guard: max 15 rows per (surface, class) per rolling hour.
8. **Block 10 — Deep LLM extraction** (`run_deep_extraction_block`). MEDIUM/DEEP only. **Qwen/Qwen3-235B-A22B-Instruct-2507** via DeepInfra; Ollama `qwen2.5:7b-instruct` fallback. Single window if ≤24,000 tokens, else 6,000-token sliding windows with 500-token overlap. Extracts events (14 enum types), claims, relations. Signal confidence ≥0.80 → `nlp.signal.detected.v1`. Claims+relations flow via `nlp.article.enriched.v1` payload (NOT separate topics — legacy `claim.extracted` was orphan, removed PLAN-0057 D-1).

**Cascade catch rates** (empirical, surface them in Ch. 4): Exact ~60%, Ticker/ISIN ~15%, Fuzzy ~10%, ANN ~5%, Unresolved ~10%.

**Workers (4)**: PriceImpactLabellingWorker (4h cycle, 25h min article age, daily OHLCV close), ArticleRelevanceScoringWorker (3-phase R24 pattern, title-only prompt, Llama-3.1-8B-Turbo), UnresolvedResolutionWorker (2-phase, FOR UPDATE SKIP LOCKED, Qwen LLM noise classification), EmbeddingRetryWorker.

**article_impact_windows** (replaces deprecated `article_price_impacts`): 4 windows day_t0/t1/t2/t5; UNIQUE on (article_id, entity_id, window_type); caps 5/5/7.5/10%.

### S7 Knowledge Graph (port 8007, intelligence_db — DDL owned by `intelligence-migrations`, S7 ALEMBIC_ENABLED=false)
**Mission**: Relation canonicalization (Block 11), graph materialization + evidence staging (Block 12), 15 async APScheduler workers (Block 13 — confidence, contradictions, summaries, descriptions, embeddings, partitions, narratives, path pre-computation), AGE shadow sync (Block 14).
**Confidence formula** (4-step bounded):
- C_final = clamp(support + corroboration − contradiction, 0, 1)
- support = Σ(w_i × source_weight_i) / Σ w_i where w_i = exp(−α × days_since(evidence_date))
- corroboration bonus = min(0.20, distinct_sources × 0.05)
- contradiction = sum of top-3 temporally-decayed contradiction strengths, capped at 0.60
**Per-predicate decay** (α values from `decay_class_config`):
- PERMANENT α=0, ∞ half-life (board membership, incorporation)
- DURABLE α=0.000950, ~730d half-life (ownership)
- SLOW α=0.003851, ~180d half-life (employment)
- MEDIUM α=0.011552, ~60d half-life (analyst ratings)
- FAST α=0.049510, ~14d half-life (sentiment)
- EPHEMERAL α=0.231049, ~3d half-life (intraday momentum)
**Three HNSW partial indexes** on `entity_embedding_state`: definition (all entities), narrative (financial_instrument only), fundamentals_ohlcv (financial_instrument only). dim=1024.
**AGE Cypher quirks** (thesis must surface): (a) Apache AGE on PostgreSQL extension; (b) BP-461 fix uses `nodes(p)` and `relationships(p)` scalar extraction with regex agtype-stripping (the previous `|` alternation syntax returned no rows); (c) `LOAD 'age'` + `SET search_path` required per session, write session required (R27 exception); (d) entity_id embedding via strict UUID regex before string interpolation; edge labels validated against 28-label whitelist (Cypher spec disallows parameterized labels); (e) O(degree³) traversal on hub entities → 5-second statement_timeout; pre-computed `path_insights` table for client queries.
**PLAN-0072 hardening** (commit ce649484): per-row session isolation (BP-390), security logging with salted argon2 entity_name hashes and SHA-256 doc_id masks, migration CONCURRENTLY→plain (BP-393), exponential backoff on provisional enrichment capped 1440 min, FOR UPDATE removed to prevent deadlocks.
**Per-tenant tracking**: `entity.dirtied.v1` is the ONLY compacted topic; **produced directly (not via outbox)** after `session.commit()` to enforce FIFO ordering for re-embedding consumers.
**Note**: `relations.confidence_components` JSONB column was designed (PLAN-0074 Wave B) but the migration was never shipped; `confidence_breakdown` API field currently returns `None` for sub-scores. Surface this honestly in Ch. 5 limitations if it comes up; otherwise omit.

### S8 RAG / Chat (port 8008, rag_db)
**Mission**: Tool-use conversational AI, hybrid retrieval, streaming SSE, citations, circuit breakers.
**Architecture (PLAN-0067 W11)**: Dual-LLM-turn tool-use loop replaces classical pipeline. First turn injects tool schema → LLM returns `tool_calls`. Second turn streams response after injecting tool results. UoW released during tool loop. **No feature flag — tool-use is the only path.**
**20-tool catalog (v3 manifest)** across 6 domains: market, intelligence, narrative, portfolio, news, alerts.
**Hybrid retrieval**: 4 modalities in parallel → RRF k=60 → `fusion_score = score × recency_score (exp(-0.005 × days)) × trust_weight`. ANN/BM25 via S6; KG via S7 Cypher (allowlist guarded); SQL via S3. Cohere Rerank v2 optional; falls back to fusion_score sort.
**HyDE**: REASONING + RELATIONSHIP intents only; 30-min Valkey cache.
**Provider chain**: DeepInfra Qwen3-235B (primary, 15s budget) → OpenRouter DeepSeek R1 Distill 32B (10s) → Ollama deepseek-r1:32b (emergency). 60s Valkey negative cache per provider.
**Embeddings**: Jina v3 1024-dim primary; S6 HTTP endpoint fallback.
**Streaming SSE events**: thinking, status, tool_call, tool_result, token, citations, contradictions, metadata, error, pending_action, action_executed, action_rejected.
**Per-source circuit breaker (PLAN-0084 A-2)**: rolling window 120s, threshold 3 failures, cool-down 120s, SETNX probe gate 5s.
**Intent enum** (8): FACTUAL_LOOKUP, GENERAL, COMPARISON, FINANCIAL_DATA, PORTFOLIO, REASONING, RELATIONSHIP, SIGNAL_INTEL.
**No Kafka** (S8 is stateless query orchestrator). Kafka-free; Valkey-backed caching.

### S9 API Gateway (port 8000, stateless)
**Mission**: BFF pattern. Single frontend entry point. PRD-0025 two-level JWT, rate limiting, response composition.
**Endpoint count**: **141 routes** across 12 domain files post-PLAN-0089 split (auth 8, portfolio 47, market 22, intelligence 12, content 10, chat 18, instruments 8, alerts 9, health 3, internal 2, admin_costs 1, risk_metrics 1).
**Two-level JWT (PRD-0025)**: Frontend bears Zitadel RS256 (validated via JWKS). S9 issues internal RS256 JWT in `X-Internal-JWT` header (signed with S9 private key). All 10 backends verify via `GET /internal/jwks` at startup. Backends NEVER see Zitadel tokens.
**Middleware order** (Starlette: last-added = outermost): RequestId → SecurityHeaders → Prometheus → OTel → CORS → RateLimit → OIDCAuth → InternalJWT.
**Dev-login**: `POST /v1/auth/dev-login` only when `OIDC_DISCOVERY_OPTIONAL=true` and OIDC unconfigured; hard-blocked when `app_env="production"` (SEC-003).
**PKCE state**: stored in Valkey 10-min TTL; **GETDEL atomic** (BP-146 fix; never GET+DEL).
**Rate limits**: 300 req/60s authenticated (raised from 100 for multi-panel workspace), 20 req/60s unauthenticated, fail-open on Valkey error.
**WS-URL endpoint**: `GET /v1/alerts/stream/ws-url` returns S10 WebSocket URL.
**Service-token mint** (PLAN-0057 Wave A-1): `POST /internal/v1/service-token` — shared secret + service-name allow-list (constant-time compare), returns 5-min RS256 JWT for background workers; not guarded by app_env (secret is the boundary).
**BFF composites degrade gracefully**: `/v1/instruments/{id}/page-bundle`, `/v1/portfolio/{id}/bundle`, `/v1/dashboard/snapshot` use asyncio.gather; per-leg failures return null; bundle returns 200; 20-25s timeout.

### S10 Alert Service (port 8010, alert_db)
**Mission**: Consume signals/graph/contradictions, fan out alerts via WebSocket, store pending alerts, send daily email digests.
**AlertSeverity enum** (PRD-0021, stored lowercase StrEnum): LOW/MEDIUM/HIGH/CRITICAL.
**SeverityThresholds**: critical ≥0.85, high ≥0.65, medium ≥0.40 (configurable via env). Signals use `market_impact_score`; graph/contradiction events forced to MEDIUM.
**Cross-process WebSocket fan-out**: IntelligenceConsumer publishes to Valkey channel `alert:{user_id}` (JSON text); API route subscribes and pushes to connected client; 30s heartbeat ping; offline catch-up via `GET /alerts/pending`.
**Outbox + dedup**: `sha256(entity_id+alert_type+window_bucket)` UNIQUE; default 300s window. Backfill suppression: signals/graph always; contradictions if backfill AND age >30 days.
**Email**: ALERT_EMAIL_PROVIDER ∈ {resend, sendgrid, smtp}; EmailScheduler hourly CronTrigger; uses S8BriefingClient (briefing content), S3 (portfolio data), S1 (email lookup); 23h dedup guard; `email_preferences` with weekly_digest_enabled / send_day_of_week / send_hour_utc.
**WebSocket auth**: inline JWT validation (audience=worldview-internal, scope=alerts:stream).
**FlashOverlay**: frontend renders 12-second auto-dismissing overlay for CRITICAL alerts.

---

## Shared Library Inventory (the eight)

| Library | Package | Architectural role |
|---------|---------|-------------------|
| `common` | `common` | UUIDv7 IDs, ULID event IDs, UTC time helpers, type aliases. R6/R7 enforcement. |
| `contracts` | `contracts` | Frozen Pydantic models + Avro envelopes; schema versions. Single source of truth for cross-service event shapes. |
| `messaging` | `messaging` | `BaseKafkaConsumer` (idempotency, retry classification, backoff, DLQ-cap 5000); `BaseOutboxDispatcher`; Confluent Avro serdes with 0x00 magic-byte detection; `ValkeyClient` (set_nx + ex=, BP-200). |
| `storage` | `storage` | Async-only `ObjectStorage` over MinIO/S3; `KeyBuilder` canonical key naming (bronze/silver). |
| `observability` | `observability` | structlog-only logging, Prometheus metrics with registry caching (BP-173), OpenTelemetry tracing, Sentry. |
| `ml-clients` | `ml_clients` | The ONLY ML path: `EmbeddingClient`, `NERClient`, `ExtractionClient`, `EntityDescriptionClient` protocols + DeepInfra/Ollama/Gemini adapters; cost tracking (LlmCallUsage). |
| `prompts` | `prompts` | Versioned `PromptTemplate` registry (extraction, intent, classification, retrieval, knowledge, description, briefing, chat, safety). |
| `tools` | `tools` | LLM tool-use registry: `ToolRegistry`, `ToolSpec`, `ToolUseBlock`, `ToolCallBatch`, `LLMToolResponse`; YAML capability manifest. |

Cross-cutting patterns enforced repo-wide:
- UUIDv7 for new entity IDs; ULID for Kafka event_id
- UTC-only timestamps via `common.utc_now()` / `ensure_utc()`
- structlog only (never stdlib logging)
- Outbox pattern for ALL DB+Kafka dual writes
- Idempotency check BEFORE `get_unit_of_work()` (BP-392)
- Backpressure tuning: session-timeout 60s > max-poll 600s > message-processing-timeout 45s
- Protocol-based adapters; no direct provider imports in services
- Frozen dataclasses for cross-service payloads

---

## Kafka Topic Catalog (authoritative)

**22 regular topics + 1 compacted = 23 declared in `.avsc` schemas.** Plus ~6 runtime-created. Use 23 as the canonical number for the thesis prose; treat "21 + 1" in prior memory as outdated.

| Topic | Partitions | Retention | Producer | Consumer(s) |
|-------|-----------|-----------|----------|-------------|
| market.dataset.fetched | 6 | 30d | S2 | S3 (4 groups: ohlcv, quotes, fundamentals, intraday-resampling), S7 (fundamentals, economic-events, macro-indicators, insider-transactions, earnings-calendar) |
| market.instrument.created | 3 | 7d | S3 (fundamentals consumer) | S1, S7 |
| market.instrument.discovered.v1 | 3 | 7d | S3 | S1, S7 |
| market.instrument.updated | 3 | 7d | S3 | S1, S3 |
| market.prediction.v1 | 8 | 30d | S4 (Polymarket adapter) | S3 |
| content.article.raw.v1 | 12 | 30d | S4 | S5 |
| content.article.stored.v1 | 12 | 30d | S5 | S6 |
| content.document.deleted.v1 | auto | 7d | S5 | S6 |
| nlp.article.enriched.v1 | 12 | 30d | S6 | S7, S10 |
| nlp.signal.detected.v1 | 24 | 14d | S6 | S10 |
| nlp.document.ready.v1 | auto | 7d | S6 | S4, S8 |
| intelligence.temporal_event.v1 | auto | 7d | S6 | S7 |
| entity.canonical.created.v1 | 12 | 7d | S7 | S7 (re-resolution) |
| entity.dirtied.v1 (compacted) | 24 | log-compact | S6, S7 | S7 (re-embedding) |
| entity.narrative.generated.v1 | auto | 7d | S7 | S7 |
| entity.provisional.queued.v1 | auto | 7d | S6 | S7 |
| graph.state.changed.v1 | 12 | 14d | S7 | audit |
| relation.type.proposed.v1 | 4 | 30d | S7 | audit |
| intelligence.contradiction.v1 | 12 | 30d | S7 | audit |
| portfolio.events.v1 | 3 | 7d | S1 | audit |
| portfolio.watchlist.updated.v1 | 12 | 7d | S1 | S6, S10 |
| alert.created.v1 | auto | 7d | S10 | audit |
| alert.delivered.v1 | 12 | 7d | S10 | audit |
| alert.email.sent.v1 | auto | 7d | S10 | audit |
| 5× *.dead-letter.v1 | 8–12 | 7d | per-service | manual |

---

## Known Discrepancies (resolved in this registry)

These supersede prior memory or skill defaults:

1. **Container count**: Production infra is **88 containers**, not 54. The "54-container" figure in the existing draft refers to the *core platform* slice (services + workers + dbs + Kafka/MinIO/Valkey/Ollama/GLiNER + frontend, excluding observability stack and one-shot inits). **Thesis recommendation**: keep the 54 figure but qualify it as "the core platform stack" and note that the full deployment with observability adds ~30 more containers. Or move to "≈50" with footnote.
2. **Kafka topic count**: **22 regular + 1 compacted = 23** declared in Avro. Plus 6 runtime-created. The prior memory's "21 + 1" is outdated. Use "22 + 1 compacted" or "23" in prose.
3. **S9 endpoint count**: **141 endpoints**, not 55+. The "55+" pre-dated PLAN-0089 split. Use 141 (or "over 140") in prose.
4. **Chat LLM primary**: **Qwen3-235B-A22B-Instruct** is the current primary; DeepSeek R1 Distill 32B is now Fallback 1 via OpenRouter. Prior memory inverted this.
5. **Deep extraction LLM**: **Qwen3-235B-A22B-Instruct-2507** in Block 10, not Llama 3.1 8B. Llama 8B is used only for relevance scoring, unresolved resolution, and intent classification.
6. **GLiNER classes**: the existing draft's list (Product, Event, Regulation, Technology, Other) is **wrong**. The correct 11 are listed in §"GLiNER entity classes" above.
7. **S2 = 6 providers, S4 = 5 providers**. S2 fetches *market data* (EODHD/Yahoo/Finnhub/Polygon/Alpaca/Alpha-Vantage-stub); S4 fetches *content* (EODHD news/SEC EDGAR/Finnhub news/NewsAPI/Polymarket). "4 production data sources" still holds at the *content* layer (EODHD, SEC, Finnhub, NewsAPI); add "+Polymarket (predictions) +tenant uploads (private)".
8. **`relations.confidence_components` JSONB**: designed (PLAN-0074 Wave B) but never migrated. `confidence_breakdown` API field returns None for sub-scores. Surface only if Ch. 5 discusses breakdown UX; otherwise omit.
9. **Confidence formula**: prior skill draft used `C = C_base × w_evidence × D_temporal`. **Actual implementation is additive**: `C_final = clamp(support + corroboration − contradiction, 0, 1)`. Replace the multiplicative form in Ch. 4 §4.4 with the additive form.
10. **Entity description model**: Gemini "3.1 Flash Lite" naming is the project shorthand; the model id is the latest Google Gemini Flash Lite endpoint. Use "Google Gemini Flash Lite" in prose; do not invent a version number.
11. **R23 read replica**: S1, S3, S6, S7 use ReadOnlyUnitOfWork via ReadUoWDep. Mention as an engineering practice in Ch. 3 §3.7.
12. **PRD-0086 tenant documents**: S4 + S5 + S6 now support private tenant uploads (multi-tenant scope). If Ch. 4 discusses this, mention it; otherwise scope to "public news + filings".

---

## TBD Items (from draft audit)

Pending resolution before submission. None of these block writing; they block final compilation.

| ID | Where | What's needed |
|----|-------|--------------|
| TBD-EVAL-1 | 05-evaluation.typ:18 | `articles processed` count — query `content_store_db.canonical_articles` |
| TBD-EVAL-2 | 05-evaluation.typ:18 | `canonical entities` count — query `intelligence_db.canonical_entities` |
| TBD-EVAL-3 | 05-evaluation.typ:18 | `canonical relations` count — query `intelligence_db.relations` |
| TBD-LAT | Appendix I tab:latency | p50/p95/p99 for 5 endpoints — run `scripts/stress_test/latency_benchmark.py` |
| TBD-TPUT | Appendix I tab:throughput | 8 throughput metrics — `scripts/stress_test/pipeline_metrics.py` |
| TBD-TESTS | Appendix I tab:tests | Unit/Integration/E2E per-service test counts — `pytest --co -q` aggregator |
| TBD-O6 | 06-conclusions.typ:31 | O6 status conditional on latency measurements |
| TBD-FIG-1..6 | Appendix I lines 143–207 | Six diagram PNG exports (topology, lifecycle, NLP pipeline, entity resolution, outbox, intelligence) |

---

## Appendix Manifest (current state)

| Appendix | Status | Required content |
|----------|--------|------------------|
| A — API documentation per service | **MISSING** (referenced in Ch. 3 §3.3 prose) | Tables of all endpoints per service (S1–S10). S9: 141 endpoints. |
| B — ER diagrams per database | **MISSING** | One Mermaid `erDiagram` per of 9 application databases (portfolio, ingestion, market_data, content_ingestion, content_store, nlp, intelligence, rag, alert). |
| C — Full Kafka topic catalog | **MISSING** | Table with 22+1 topics, partitions, retention, producer, consumer(s), key Avro fields. Source: §Kafka Topic Catalog above. |
| D — Service interaction diagrams | **MISSING** | 4 Mermaid sequence diagrams: Article ingestion (S4→S5→S6→S7→S10), Chat query (FE→S9→S8→retrievers→SSE), Market data (EODHD→S2→S3), Alert fan-out (S6/S7→S10→WS). |
| E — Routing score weights + signal formulas | **MISSING** | Table of the 8 weights + formula breakdown for each signal (entity_density, source_reliability, novelty, recency, watchlist, price_impact, document_type, extraction_yield). |
| F — Full infrastructure container list | **MISSING** (Ch. 3 §3.8 refers to it) | Container catalog from §Per-Service / §Container catalog (88 entries). |
| G — Frontend journey screenshots | **MISSING** | 5 placeholder PNGs (J1–J5) with captions. |
| H — Confidence decay formula derivation | **MISSING** | Derivation: half-life = ln(2)/α; per-class α table; worked example for ownership vs employment. |
| I — Supplementary tables & figures | **EXISTS** (current `appendices/I-supplementary-tables-figures.typ`) | Contains Table 2.1 (platforms), 2.2 (gap), 3.1 (services), 3.2 (topics — outdated to 21+1), 5.1 (latency TBD), 5.2 (throughput TBD), 5.3 (tests TBD), plus 6 figure placeholders. |

**Decision for Phase 4**: Reorganize. Keep Appendix I as the supplementary container, but also create A–H per the skill priority queue. Or merge A–H into renamed sub-sections of Appendix I. Defer this decision to Phase 4 dispatching.

---

## Draft Audit Summary

- Total mainmatter: **12,727 words ≈ 28.3 pages** (budget 30 pages — within hard limit).
- **Overrun chapters**: Ch.1 (+127 wds), Ch.2 (+361 wds), Ch.3 (+466 wds), Ch.6 (+153 wds).
- **Underfill**: Ch.5 (−380 wds; expand once TBDs filled).
- **Net**: +577 wds (~1.3 pages) over allotted-per-chapter targets but **under the 30-page hard cap**. Aggressive trim NOT required if Ch.5 grows back to 2.5 pp; instead, trim chapters 2 and 3 specifically where they list per-service detail (move to appendices).
- **Style**: No banned phrases detected. Prose is clean.
- **Outline ↔ draft**: Fully aligned (every planned section exists).
- **Factual errors to fix in rewrite**:
  - GLiNER class list (Ch. 4 §4.3 Block 2 — wrong classes)
  - Chat model naming inconsistency (DeepSeek R1 Distill 32B vs Qwen3 235B as primary)
  - Container count "54" needs qualification
  - Kafka topic count "21 + 1" → "22 + 1"
  - Extraction LLM "Llama 3.1 8B" in Block 10 → "Qwen3-235B"
  - S9 "55+" → "over 140"
  - Confidence formula: multiplicative → additive

---

## Style and Writing Constraints (for chapter subagents)

(Reproduced from `.claude/skills/thesis-write/SKILL.md` so chapter subagents have it inline.)

- ≤35-word sentences. Active voice default.
- One idea per paragraph; lead with the claim.
- Banned phrases: "it is worth noting", "due to the fact that", "in order to", "it should be mentioned", "Furthermore", "Moreover", "Notably", "Interestingly".
- Inline code formatting for service names (`S6`), topic names (`content.article.stored.v1`), library classes (`BaseKafkaConsumer`), file paths.
- Define acronyms on first use; never redefine.
- Numbers: spell out 1–9, digits for 10+; always include units (ms, MB, rows/s).
- No figures, no diagrams in main text — all live in appendices, referenced by `@fig-*` and `@appendix-*`.
- Tables in main text only if ≤4 rows and the table *is* the point.
- Every technical claim must trace to a fact in this registry (or be flagged as a TBD).
