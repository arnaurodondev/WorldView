---
id: PLAN-0001-C
prd: PRD-0001
title: "Ingestion Pipeline v1: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service — Implementation Plan"
status: in-progress
created: 2026-03-25
updated: 2026-03-27
plans: 3

waves: 11
tasks: 48
supersedes: "Original draft based on PRD-0014"
---

# PLAN-0001-C: S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service

## Overview

**PRD Reference**: [PRD-0001](../specs/0001-intelligence-pipeline.md) — §6.2.3–6.2.6, §6.3, §6.4.3–6.4.5, §6.5, §6.7 Blocks 3–14, §7–§13
**Depends on**: PLAN-0001-A (all 3 waves) + PLAN-0012 (S4+S5 complete) + PLAN-0003 Wave A-1 (observability standards)
**Goal**: Implement the intelligence enrichment arm of the pipeline — S6 consumes canonical articles from S5, enriches via NER/embeddings/entity-resolution/LLM-extraction, emits enriched events; S7 materializes a knowledge graph with confidence-scored relations and 8 background workers; S10 fans out watchlist-triggered alerts via WebSocket — completing the full S4→S5→S6→S7→S10 pipeline.
**Total Scope**: 3 sub-plans, 11 waves, 48 tasks

---

## Plan Dependency Graph

```
PLAN-0012 Sub-Plan A (S4) ──┐
                             ├──→ Sub-Plan C: S6 NLP Pipeline ──→ Sub-Plan D: S7 Knowledge Graph ──→ Sub-Plan E: S10 Alert
PLAN-0012 Sub-Plan B (S5) ──┘                                                                           │
                                                                                                         │
                                                                                         S1 Portfolio ←───┘
                                                                                    (internal endpoints required)
```

**Execution Order**:
1. Sub-Plan C (S6) — Waves C-1 through C-4 (sequential); depends on PLAN-0012 completion
2. Sub-Plan D (S7) — Waves D-1 through D-4 (sequential); depends on C-4 (S6 emitting events)
3. Sub-Plan E (S10) — Waves E-1 through E-3 (sequential); depends on D-4 (S7 emitting events) + S1 internal endpoints

**Session Boundaries**: Each sub-plan is designed to execute in 1–2 Claude Code sessions.

---

## Sub-Plan C: S6 NLP Pipeline

### Context

S6 is the NLP enrichment service. It consumes `content.article.stored.v1` from S5, processes articles through 8 sequential blocks (sectioning → GLiNER NER → routing → suppression → embeddings → novelty → entity resolution → LLM extraction), and emits `nlp.article.enriched.v1` and `nlp.signal.detected.v1` via outbox. S6 connects to both `nlp_db` (owned, Alembic enabled) and `intelligence_db` (read/write only, `ALEMBIC_ENABLED=false`). All ML calls go through `libs/ml-clients` protocols.

### Pre-Read (agent must read before any wave)
- `RULES.md` — hard rules
- `AGENTS.md` — coding standards, hexagonal architecture
- `docs/MASTER_PLAN.md` — §4.6 (S6 definition), §5.2 (Kafka topics)
- `docs/STANDARDS.md` — §5 (canonical observability pattern: logging → metrics → tracing init sequence, RequestIdMiddleware, health endpoints, `/metrics`, docker.env vars) — **PLAN-0003 reference**
- `docs/specs/0001-intelligence-pipeline.md` — §6.2.3, §6.3.2, §6.4.3, §6.5.3, §6.7 Blocks 3–10, §14.2 (light-tier entity enrichment)
- `services/nlp-pipeline/.claude-context.md`
- `docs/services/nlp-pipeline.md`
- `libs/ml-clients/src/ml_clients/` — NERClient, EmbeddingClient, ExtractionClient protocols
- `libs/messaging/src/messaging/` — BaseKafkaConsumer, outbox
- `libs/contracts/src/contracts/` — canonical models
- `services/content-store/src/content_store/` — S5 output format (for consumer contract)
- `services/content-ingestion/src/content_ingestion/app.py` — gold-standard observability wiring reference
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave C-1: S6 Foundation — Config, Domain, Database Infrastructure ✅

**Goal**: Establish S6 foundation: settings, domain models (10-class NER ontology, routing tiers, NLP document lifecycle), database infrastructure for both `nlp_db` (Alembic enabled) and `intelligence_db` (read/write adapter with `ALEMBIC_ENABLED=false` guard).
**Depends on**: PLAN-0012 completed (S5 emitting `content.article.stored.v1`)
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-03-27 · 9 domain/infra guard tests pass · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-1-01 | Config + Domain models | impl | `config.py`, `domain/enums.py`, `domain/models.py`, `domain/errors.py` | Settings (nlp_db, intelligence_db, Kafka topics incl. `portfolio.watchlist.updated.v1` for watchlist signal, Ollama endpoints, backpressure thresholds, embedding params); `MentionClass` enum (**11 values**: organization, government_body, regulatory_body, financial_institution, person, financial_instrument, location, commodity, index, currency, **macroeconomic_indicator**); `RoutingTier` enum (DEEP, MEDIUM, LIGHT, SUPPRESS); domain models: Section, Chunk, EntityMention (with resolution_stage), RoutingDecision, NLPDocument, SignalEvent, EmbeddingPendingEntry; error hierarchy |
| T-C-1-02 | nlp_db infrastructure (owned, Alembic enabled) | impl | `infrastructure/nlp_db/session.py`, `infrastructure/nlp_db/models.py`, repositories (section, chunk, entity_mention, mention_resolution, document_entity_stats, routing_decision, chunk_entity_mention, outbox, dlq) | SQLAlchemy 2.x models per PRD §6.4.3: sections (with speaker), chunks, entity_mentions (with resolved_entity_id + resolution_confidence + resolution_stage), **mention_resolutions** (audit trail per resolution stage), **document_entity_stats** (distinct_mention_count, high_conf_count, type_distribution JSONB), chunk_entity_mentions (join table), chunk_embeddings (vector(1024) with expires_at), section_embeddings, routing_decisions (with final_routing_tier), outbox_events, dead_letter_queue; 9 repositories with `FOR UPDATE SKIP LOCKED` on outbox; HNSW indexes with partial predicate `WHERE embedding_status = 'ready' AND (expires_at IS NULL OR expires_at > now())` |
| T-C-1-03 | intelligence_db adapter (read/write, NO Alembic) | impl | `infrastructure/intelligence_db/session.py`, repositories (entity_alias, entity_profile_embedding, canonical_entity, claims) | Session factory with `ALEMBIC_ENABLED=false` guard (RuntimeError on True); 4 repositories: EntityAliasRepo (exact match, ticker/ISIN match, fuzzy trigram), EntityProfileEmbeddingRepo (ANN HNSW search), CanonicalEntityRepo (get/create), ClaimsRepo (write via outbox pattern) |
| T-C-1-04 | Alembic migrations for nlp_db | schema | `alembic/`, `alembic/versions/0001_initial_nlp_schema.py` | Creates all tables; pgvector extension enabled; `vector(1024)` columns; HNSW indexes with `WHERE (expires_at IS NULL OR expires_at > now())` partial predicate; matches ORM exactly (guard BP-008) |
| T-C-1-05 | Unit tests for S6 foundation | test | `tests/unit/domain/`, `tests/unit/infrastructure/` | ≥20 tests: MentionClass has exactly **11** members (incl. macroeconomic_indicator), RoutingTier ordering, domain model construction, ALEMBIC_ENABLED=true raises RuntimeError, mention_resolutions audit trail, document_entity_stats, repo type annotations, session factory |

#### Pre-Read
- `services/portfolio/src/portfolio/infrastructure/db/` — reference implementation
- `services/knowledge-graph/src/knowledge_graph/` — intelligence_db adapter reference

#### Validation Gate
- [x] `ruff check services/nlp-pipeline/` passes
- [x] `mypy services/nlp-pipeline/src/ --config-file mypy.ini` passes
- [x] `python -m pytest services/nlp-pipeline/tests/unit -v` — ≥20 tests pass
- [x] Domain layer has zero infrastructure imports
- [x] `ALEMBIC_ENABLED=true` raises RuntimeError on intelligence_db session import
- [x] `docs/services/nlp-pipeline.md` updated with domain models, DB topology (nlp_db owned, intelligence_db adapter)

#### Regression Guardrails
- BP-006: Load DATABASE_URL from settings, not alembic.ini
- BP-008: Migration matches ORM models exactly
- Custom: intelligence_db ALEMBIC_ENABLED=false guard — test this explicitly

---

### Wave C-2: S6 Blocks 3–6 — Sectioning, NER, Routing, Suppression ✅

**Goal**: Implement the first processing layer: source-specific document sectioning, GLiNER NER (**11-class** ontology with per-class thresholds), 7-signal routing score (incl. watchlist signal via `portfolio.watchlist.updated.v1` consumer), and suppression/audit gate.
**Depends on**: Wave C-1
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-03-27 · 120 unit tests pass · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-2-01 | Block 3: Sectioning | impl | `application/blocks/sectioning.py` | 4 sectioners: NewsParagraphSectioner (paragraph-based), SECEdgarSectioner (section headers), FinnhubTranscriptSectioner (speaker-turn), SyntheticSectioner (fallback single section); factory dispatches by source_type; writes `sections` rows to nlp_db |
| T-C-2-02 | Block 4: GLiNER NER | impl | `application/blocks/ner.py` | Inject `NERClient` (GLiNERLocalAdapter) via dependency; batch NER per section; **11-class** ontology (incl. macroeconomic_indicator) with per-class thresholds (GLINER_THRESHOLD=0.35 for routing, GLINER_RESOLUTION_THRESHOLD=0.45 for cascade); NMS (IoU>0.5) for overlapping spans; OOM retry (once, with reduced batch); writes `entity_mentions` + `document_entity_stats` rows; **CRITICAL: zero NER mentions NEVER suppress the document** — returns empty list without exception |
| T-C-2-03 | Block 5: Routing score + watchlist consumer | impl | `application/blocks/routing.py`, `infrastructure/consumer/watchlist_consumer.py`, `infrastructure/valkey/watchlist_cache.py` | 7-signal weighted formula per PRD §6.7 Block 5; `source_reliability_signal` reads from `source_trust_weights` table in intelligence_db (PRD §6.4.4); **Watchlist signal sourcing**: S6 consumes `portfolio.watchlist.updated.v1` (consumer group: `nlp-watchlist-group`), maintains Valkey SET `nlp:v1:watched_entities` (SADD on item_added, SREM on item_deleted); Block 5 checks `SISMEMBER` for each resolved GLiNER mention; tier boundaries: ≥0.70 DEEP, ≥0.45 MEDIUM, ≥0.20 LIGHT, <0.20 SUPPRESS; module-level assertion weights sum to 1.0; watchlist signal best-effort (Valkey unavailable → 0.0) |
| T-C-2-04 | Block 6: Suppression + audit | impl | `application/blocks/suppression.py` | SUPPRESS → write `nlp_processing_log` with routing_tier + halt all downstream; LIGHT → flag SECTION_EMBEDDINGS_ONLY (no NER reprocessing, no extraction); MEDIUM/DEEP → continue full pipeline; always writes audit log |
| T-C-2-05 | Unit tests for Blocks 3–6 | test | `tests/unit/application/blocks/` | ≥25 tests: each sectioner (4), NER zero-mentions returns [] (CRITICAL invariant), NER NMS overlap, routing weights sum to 1.0, routing tier boundaries (edge cases at 0.20/0.45/0.70), suppression halt/continue/embeddings-only paths, audit log written for every tier |

#### Pre-Read
- `libs/ml-clients/src/ml_clients/` — NERClient protocol, NERInput/NEROutput dataclasses

#### Validation Gate
- [x] `ruff check services/nlp-pipeline/` passes
- [x] `mypy services/nlp-pipeline/src/ --config-file mypy.ini` passes
- [x] `python -m pytest services/nlp-pipeline/tests/unit -v` — all tests pass (≥45 total)
- [x] Zero NER mentions test explicitly passes (most critical S6 invariant)
- [x] Signal weights sum assertion verified at import time
- [x] `docs/services/nlp-pipeline.md` updated with processing blocks 3–6, routing formula, tier boundaries

#### Regression Guardrails
- Custom: Zero NER mentions MUST NOT suppress — explicit test required
- Custom: Routing weights must sum to exactly 1.0 — module-level assertion

---

### Wave C-3: S6 Blocks 7–10 — Embeddings, Novelty, Entity Resolution, Deep Extraction ✅

**Goal**: Implement the second processing layer: sentence-aware chunked embeddings, novelty gate (MinHash + per-entity embedding similarity), 4-stage entity resolution cascade, and LLM deep extraction (Qwen2.5-7B for DEEP-tier only).
**Depends on**: Wave C-2
**Estimated effort**: 75–90 minutes
**Status**: **DONE** — 2026-03-27 · 184 unit tests pass (64 new) · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-3-01 | Block 7: Embedding generation | impl | `application/blocks/embeddings.py` | Inject `EmbeddingClient` (OllamaEmbeddingAdapter); sentence-aware 512-token chunks with 64-token overlap (never split mid-sentence); section embeddings for ALL tiers; chunk embeddings for MEDIUM/DEEP only; failed embeddings → `embedding_pending_queue` row; writes `chunk_embeddings` (vector(1024)) and `section_embeddings` |
| T-C-3-02 | Block 8: Novelty gate | impl | `application/blocks/novelty.py` | 2-stage: Stage 1 — MinHash/Valkey LSH (threshold 0.80) from S5 novelty data; Stage 2 — per-entity embedding similarity against recent content; downgrade DEEP→LIGHT if all entities near-duplicate; log decision to `nlp_processing_log`; cross-DB read from S5 via service API or Valkey cache (not direct DB) |
| T-C-3-03 | Block 9: Entity resolution cascade | impl | `application/blocks/entity_resolution.py` | 4-step cascade per PRD §6.7 Block 9: (1) exact alias match on `entity_aliases.normalized_alias_text = lower(trim(:mention_text))` WHERE `alias_type='EXACT' AND is_active=true`, confidence 1.0; (2) ticker/ISIN match on `canonical_entities`, confidence 0.95; (3) fuzzy trigram `similarity(normalized_alias_text, ...) > 0.75` via pg_trgm, confidence = sim*0.90; (4) ANN HNSW on `entity_embedding_state WHERE view_type='definition'` (cosine < 0.35, clear margin > 0.10) — uses **definition** view for identity resolution, NOT narrative, confidence = (1-dist)*0.80; AUTO_RESOLVE ≥ 0.72 → write `entity_mentions.resolved_entity_id`; PROVISIONAL ≥ 0.45 → INSERT `provisional_entity_queue` (UNIQUE on normalized_surface+mention_class); UNRESOLVED mentions NEVER discarded; write `mention_resolutions` audit trail; update `minhash_entity_mentions` with resolved entity_ids |
| T-C-3-04 | Block 10: Deep LLM extraction | impl | `application/blocks/deep_extraction.py` | Inject `ExtractionClient` (OllamaExtractionAdapter); **medium AND deep tier** (light returns []); Qwen2.5-7B-Instruct; ≤24,000 tokens single window, >24,000 → 6,000-token windows with 500-token overlap; structured output: events, claims, relations per PRD §6.7 Block 10; valid_to heuristic validation; `evidence_date = coalesce(published_at, extracted_at)` — **NEVER use now() when published_at available**; write `relation_evidence_raw` — for **relations with provisional (unresolved) entities**: set `entity_provisional=true` + `provisional_queue_id` (held until Block 13E resolves); claims written to intelligence_db via outbox; emit `nlp.signal.detected.v1` for high-confidence signals |
| T-C-3-05 | Backpressure controller | impl | `infrastructure/backpressure/controller.py` | `asyncio.Semaphore(MAX_OLLAMA_QUEUE_DEPTH=20)`; pause Kafka consumer partitions when semaphore full; resume when below `RESUME_OLLAMA_QUEUE_DEPTH`; `s6_ollama_queue_depth_current` gauge; NEVER uses `threading.sleep` (asyncio only) |
| T-C-3-06 | Unit tests for Blocks 7–10 + backpressure | test | `tests/unit/application/blocks/` | ≥30 tests: chunk splitting (512 tokens, 64 overlap, no mid-sentence), section embeddings for all tiers, pending queue on failure, novelty downgrade logic, entity resolution cascade (4 stages), auto-resolve/provisional/unresolved paths, deep extraction DEEP-only guard, claim extraction + JSON parse error, backpressure pause/resume thresholds, semaphore integration |

#### Pre-Read
- `libs/ml-clients/src/ml_clients/` — EmbeddingClient, ExtractionClient protocols
- `services/content-store/src/content_store/` — novelty scores / Valkey LSH (for Block 8)

#### Validation Gate
- [x] `ruff check services/nlp-pipeline/` passes
- [x] `mypy services/nlp-pipeline/src/ --config-file mypy.ini` passes
- [x] `python -m pytest services/nlp-pipeline/tests/unit -v` — 184 tests pass (≥75 ✅)
- [x] Entity resolution: unresolved mentions never discarded (explicit test)
- [x] Deep extraction: non-FULL_PIPELINE tier returns [] (explicit test for both LIGHT and HALT)
- [x] Claims written to nlp_db outbox, NOT directly to intelligence_db
- [x] `docs/services/nlp-pipeline.md` updated with blocks 7–10, entity resolution cascade, backpressure mechanism

#### Regression Guardrails
- Custom: Unresolved entity mentions MUST be preserved (never discarded)
- Custom: Claims go through nlp_db outbox, not direct intelligence_db writes
- Custom: Backpressure must use asyncio, never threading

---

### Wave C-4: S6 Consumer Orchestration, Outbox, API, Health, Integration Tests ✅

**Goal**: Complete S6 with Kafka consumer orchestrating all 8 blocks in sequence, outbox dispatcher (2 output topics + claims), REST API, health probes, Prometheus metrics, main.py wiring, and integration tests.
**Depends on**: Wave C-3
**Estimated effort**: 75–90 minutes
**Status**: **DONE** — 2026-03-27 · 217 tests pass (210 unit + 5 integration + 2 pre-existing) · ruff + mypy clean

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-C-4-01 | Kafka consumer orchestration | impl | `infrastructure/consumer/article_consumer.py` | Consumes `content.article.stored.v1`; orchestrates Blocks 3→4→5→6→7→8→9→10 in sequence; manual offset commit AFTER all DB writes; DLQ on unrecoverable errors; at-least-once semantics; backpressure integration (pause/resume via controller) |
| T-C-4-02 | Outbox dispatcher (3 output event types) | impl | `infrastructure/outbox/dispatcher.py` | Polls `nlp_db.outbox_events`; publishes `nlp.article.enriched.v1` (full enrichment result), `nlp.signal.detected.v1` (≥0.80 confidence resolved entities), and `claim.extracted` events (routed to intelligence_db claims); uses `OutboxEventValueSerializer` (guard BP-001) |
| T-C-4-03 | REST API endpoints | impl | `api/routes.py`, `api/schemas.py` | 6 endpoints: GET /signals (paginated), GET /entities (search), POST /vector-search (semantic), GET /entities/{id} (detail), GET /entities/{id}/articles, POST /reprocess/{article_id}; Pydantic request/response models |
| T-C-4-04 | Health/Ready + Prometheus + DLQ + main.py (PLAN-0003 pattern) | impl | `api/health.py`, `api/dlq.py`, `infrastructure/metrics/prometheus.py`, `main.py`, `config.py` | **Follow STANDARDS.md §5 canonical pattern (PLAN-0003)**: (1) `configure_logging()` FIRST in lifespan; (2) `create_metrics()` + `add_prometheus_middleware(app, metrics)` + `app.state.metrics = metrics`; (3) conditional `configure_tracing()` + `add_otel_middleware(app)` if `otlp_endpoint` set; (4) `RequestIdMiddleware` class in `create_app()`; (5) explicit `GET /metrics` endpoint via `prometheus_client.generate_latest()`; (6) `service_name: str = "nlp-pipeline"` in config.py; (7) docker.env must have `NLP_PIPELINE_LOG_LEVEL`, `NLP_PIPELINE_LOG_JSON`, `NLP_PIPELINE_OTLP_ENDPOINT`. **Custom metrics**: `s6_articles_processed_total{routing_tier}`, `s6_ner_mentions_total`, `s6_embeddings_created_total`, `s6_entity_resolved_total{method}`, `s6_claims_extracted_total`, `nlp_sectioning_fallback_total`, `s6_ollama_queue_depth_current` (Gauge, polled). Health: /healthz (200), /readyz (nlp_db + intelligence_db + Kafka + Ollama, 503 on failure); DLQ admin with X-Admin-Token; main.py lifespan starts consumer + dispatcher + backpressure controller |
| T-C-4-05 | Integration tests | test | `tests/integration/test_full_pipeline.py`, `tests/integration/test_zero_ner.py`, `tests/integration/test_backpressure.py`, `tests/integration/test_idempotency.py` | Full pipeline: stored article → consumer → all 8 blocks → enriched event on Kafka (with mock ML adapters); Zero NER: article with no entities → still processed (not suppressed); Backpressure: verify pause/resume at thresholds; Idempotency: same message twice → no duplicate DB rows |
| T-C-4-06 | Unit tests for consumer + outbox + API | test | `tests/unit/infrastructure/`, `tests/unit/api/` | ≥15 tests: consumer block orchestration order, outbox event routing (3 types), API endpoint responses, health checks, DLQ auth, metrics increment |

#### Pre-Read
- `services/content-ingestion/src/content_ingestion/main.py` — reference main.py pattern
- `services/portfolio/src/portfolio/api/` — reference API pattern

#### Validation Gate
- [x] `ruff check services/nlp-pipeline/` passes
- [x] `mypy services/nlp-pipeline/src/ --config-file mypy.ini` passes
- [x] `python -m pytest services/nlp-pipeline/tests -v` — all tests pass (217 total)
- [x] Integration test `test_full_pipeline` passes with mock ML adapters
- [x] S6 confirmed emitting `nlp.article.enriched.v1` to Kafka (outbox pattern)
- [x] `services/nlp-pipeline/.claude-context.md` updated (Wave C-4 API, consumer, dispatcher, pitfalls)

#### Regression Guardrails
- BP-001: OutboxEventValueSerializer for dispatcher
- BP-003: Async fixture teardown in integration tests
- BP-009: DispatcherConfig from settings
- Custom: Consumer commits offset ONLY after all DB writes succeed

---

## Sub-Plan D: S7 Knowledge Graph

### Context

S7 materializes a temporally-aware, evidence-backed knowledge graph from S6 enrichment events. It runs both a Kafka consumer (hot path: relation canonicalization, graph writes, contradiction detection) and 8 APScheduler async workers (derived semantics: confidence recomputation, summary generation, embedding refresh, partition management) in a single FastAPI process. S7 connects to `intelligence_db` for read/write but `ALEMBIC_ENABLED=false` — all DDL is owned by `intelligence-migrations`.

### Pre-Read (agent must read before any wave)
- `RULES.md` — hard rules
- `AGENTS.md` — coding standards
- `docs/MASTER_PLAN.md` — §4.7 (S7 definition)
- `docs/STANDARDS.md` — §5 (canonical observability pattern: logging → metrics → tracing init sequence, RequestIdMiddleware, health endpoints, `/metrics`, docker.env vars) — **PLAN-0003 reference**
- `docs/specs/0001-intelligence-pipeline.md` — §6.2.4, §6.3.2, §6.4.4, §6.5.4, §6.7 Blocks 11–14, §10.1 (confidence formula), §14.2 (light-tier entity enrichment)
- `services/knowledge-graph/.claude-context.md`
- `docs/services/knowledge-graph.md`
- `libs/ml-clients/src/ml_clients/` — EmbeddingClient, ExtractionClient
- `services/intelligence-migrations/` — DDL owner for intelligence_db
- `services/content-ingestion/src/content_ingestion/app.py` — gold-standard observability wiring reference
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave D-1: S7 Foundation — Config, Domain, intelligence_db Adapter

**Goal**: Establish S7 foundation: settings (confidence formula params, worker intervals), domain models (SemanticMode, DecayClass, Relation, RelationEvidence, ConfidenceComponents), and intelligence_db dual-session adapter with `ALEMBIC_ENABLED=false` guard.
**Depends on**: Wave C-4 (S6 integration test `test_full_pipeline` must pass)
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-1-01 | Config + Domain models | impl | `config.py`, `domain/enums.py`, `domain/models.py`, `domain/errors.py` | Settings: RELATION_CANONICALIZATION_THRESHOLD=0.35, worker intervals (15m/30m/60m/60m/2h/3h), confidence formula params (corroboration_cap=0.20, contradiction_cap=0.60, temporal_claim_alpha=0.02310); `SemanticMode` enum (RELATION_STATE, TEMPORAL_CLAIM); `DecayClass` enum (STANDARD, TEMPORAL); `RelationType` with 8 well-known types; domain models: Relation, RelationEvidence (with `is_backfill`), RelationSummary, Contradiction, ContradictionLink, ConfidenceComponents (with `validate()` asserting final ∈ [0,1], corroboration ≤ 0.20, contradiction ≤ 0.60) |
| T-D-1-02 | intelligence_db adapter (dual-session, NO Alembic) | impl | `infrastructure/intelligence_db/session.py`, 7 repositories (relation, relation_evidence, relation_summary, contradiction, canonical_entity, relation_type_registry, outbox) | `ALEMBIC_ENABLED=false` guard (RuntimeError on True); dual sessions (IntelligenceSession read/write + ReadOnlySession); RelationRepo: upsert keyed on (subject, object, type) with advisory lock; EvidenceRepo: insert (NEVER include partition_key — STORED generated); SummaryRepo: set is_current=false on old + insert new; ContradictionRepo: query by subject within 90-day window; OutboxRepo: append/fetch_pending; `partition_key` is STORED column — NEVER in INSERT |
| T-D-1-03 | Confidence formula implementation | impl | `domain/confidence.py` | 4-step bounded formula: (1) Support = sum(w_i * source_weight_i) / sum(temporal_weight) — normalize by sum(temporal_weight), NOT count; (2) Corroboration gain = distinct (source_type, source_name) with temporal_weight ≥ 0.1, capped 0.20; (3) Contradiction penalty = top-3 links, dynamic decay, capped 0.60; (4) Final = clamp(support + corroboration - contradiction, 0.0, 1.0); Decay: RELATION_STATE uses parent decay_alpha, TEMPORAL_CLAIM uses 0.02310 (30-day half-life) |
| T-D-1-04 | Unit tests for S7 foundation | test | `tests/unit/domain/`, `tests/unit/infrastructure/` | ≥25 tests: SemanticMode exactly 2 values, ConfidenceComponents.validate() boundary assertions, confidence formula (multi-source, bounded ≤1.0, corroboration cap, contradiction cap, temporal decay), ALEMBIC_ENABLED guard, partition_key NOT in INSERT, upsert idempotency, 90-day contradiction window |

#### Pre-Read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/` — S6 intelligence_db adapter reference
- `services/intelligence-migrations/` — DDL definitions for intelligence_db tables

#### Validation Gate
- [ ] `ruff check services/knowledge-graph/` passes
- [ ] `mypy services/knowledge-graph/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/knowledge-graph/tests/unit -v` — ≥25 tests pass
- [ ] ConfidenceComponents.validate() confirms all bounds
- [ ] ALEMBIC_ENABLED=true raises RuntimeError
- [ ] `docs/services/knowledge-graph.md` updated with domain models, confidence formula, DB topology

#### Regression Guardrails
- BP-008: intelligence_db tables match DDL from intelligence-migrations (not S7's responsibility to create)
- Custom: partition_key is STORED — never include in INSERT statements
- Custom: Confidence always bounded [0, 1] — explicit boundary tests

---

### Wave D-2: S7 Hot Path — Blocks 11–12 + APScheduler/Kafka Co-topology

**Goal**: Implement the S7 hot path: APScheduler + Kafka consumer co-topology in single FastAPI lifespan, relation canonicalization (3-step: exact → soft-map → propose), graph materialization with advisory locks, and hot-path contradiction detection.
**Depends on**: Wave D-1
**Estimated effort**: 75–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-2-01 | APScheduler + Kafka co-topology scaffold | impl | `infrastructure/scheduler/scheduler.py`, lifespan integration | `KnowledgeGraphScheduler` with `AsyncIOScheduler`; 8 job slots (stubs — implemented in Wave D-3); Kafka consumer in same event loop; graceful SIGTERM shutdown; lifespan starts both scheduler and consumer |
| T-D-2-02 | Block 11: Relation canonicalization | impl | `application/blocks/canonicalization.py` | 3-step per PRD §6.7 Block 11: (1) exact match against `relation_type_registry.canonical_type`; (2) soft-map via ANN against `relation_type_registry.embedding` column (VECTOR(1024), populated by intelligence-migrations at boot) — cosine distance ≤ 0.35; (3) no match → emit `relation.type.proposed.v1` event via outbox, return canonical_type=None WITHOUT raising; unknown types do NOT fail the message |
| T-D-2-03 | Block 12a: Graph materialization | impl | `application/blocks/graph_write.py` | Advisory lock (`pg_advisory_xact_lock()` on triple hash) within transaction; upsert relation keyed on (subject_entity_id, object_entity_id, relation_type); insert `relation_evidence_raw` — NO partition_key in INSERT (STORED, % 8 matching relations table); insert `events` + `event_entities` (join table with role: subject/object/participant) idempotent ON CONFLICT DO NOTHING; insert `claims`; produce `entity.dirtied.v1` DIRECTLY to Kafka (compacted topic — bypasses outbox); emit `graph.state.changed.v1` via outbox; **aggregation worker skips rows where `entity_provisional = true`** |
| T-D-2-04 | Block 12b: Contradiction detection (hot path) | impl | `application/blocks/contradiction.py` | Subject-based (NOT claimer-based); query claims on (subject_entity_id, claim_type, polarity) within 90-day window; match requires opposite polarity AND both non-neutral; write `relation_contradiction_links` (strength, detected_at — no temporal weights cached); emit `intelligence.contradiction.v1` via outbox |
| T-D-2-05 | Kafka consumers for enriched events + entity creation | impl | `infrastructure/consumer/enriched_consumer.py`, `infrastructure/consumer/entity_consumer.py` | **Enriched consumer**: consumes `nlp.article.enriched.v1`; canonicalize (Block 11) → materialize (Block 12a) → detect contradictions (Block 12b); manual offset commit after all DB writes; DLQ on unrecoverable. **Entity consumer** (NEW): consumes `entity.canonical.created.v1` from S6 Block 13E; creates entity profile embedding for the new entity; triggers aggregation of previously-held `relation_evidence_raw` rows (entity_provisional=true → now processable) |
| T-D-2-06 | Unit tests for hot path | test | `tests/unit/application/blocks/`, `tests/unit/infrastructure/` | ≥20 tests: canonicalization 3-step (exact/soft/propose), propose does not raise, graph upsert idempotency, advisory lock acquired, partition_key not in INSERT, contradiction detection (opposite polarity, same subject, 90-day window, non-neutral required), entity.dirtied.v1 direct produce (not outbox), consumer block orchestration |

#### Pre-Read
- `services/portfolio/src/portfolio/infrastructure/outbox/` — outbox dispatcher reference
- `infra/kafka/schemas/` — Avro schemas for output events

#### Validation Gate
- [ ] `ruff check services/knowledge-graph/` passes
- [ ] `mypy services/knowledge-graph/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/knowledge-graph/tests/unit -v` — all tests pass (≥45 total)
- [ ] entity.dirtied.v1 produced directly (not via outbox) — verified in test
- [ ] partition_key not in any INSERT — grep verification
- [ ] `docs/services/knowledge-graph.md` updated with hot path blocks, Kafka topology

#### Regression Guardrails
- BP-001: OutboxEventValueSerializer for outbox-dispatched events
- Custom: partition_key STORED — never in INSERT
- Custom: entity.dirtied.v1 bypasses outbox (compacted topic semantics)
- Custom: Contradiction requires opposite polarity AND non-neutral

---

### Wave D-3: S7 Workers 13A–H + Outbox Dispatcher

**Goal**: Implement all 8 APScheduler async workers (confidence recomputation, contradiction batch, summary generation, entity profile embedding, relation summary embedding, evidence embedding, monthly/yearly partition creation) and the outbox dispatcher for 3 output topics. Block 14 design memo (shadow migration — deferred).
**Depends on**: Wave D-2
**Estimated effort**: 90–120 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-3-01 | Worker 13A: Confidence recomputation | impl | `infrastructure/workers/confidence.py` | 15-min interval; process unprocessed `relation_evidence_raw` grouped by partition_key; apply 4-step formula from `domain/confidence.py`; mark processed; update `relations.confidence` + `summary_stale=true` |
| T-D-3-02 | Worker 13B: Contradiction batch detection | impl | `infrastructure/workers/contradiction_batch.py` | 30-min interval; full subject-based scan for unprocessed claims; same logic as Block 12b but batch-oriented; rate-limited scan using `idx_claims_contradiction_detection` index |
| T-D-3-03 | Worker 13C: Summary generation | impl | `infrastructure/workers/summary.py` | 60-min interval; process relations with `summary_stale=true`; inject `ExtractionClient` for LLM summary; evidence selection: `ORDER BY temporal_weight DESC, source_weight DESC, evidence_date DESC LIMIT 10`; set old summary `is_current=false`, insert new with `is_current=true`; compute `evidence_hash` for change detection; versioned prompt template |
| T-D-3-04 | Worker 13D-1: Definition embedding refresh | impl | `infrastructure/workers/definition_refresh.py` | Triggered by `market.instrument.created` (via 13D-4 consumer) and `market.dataset.fetched` (via 13D-5 consumer). Quarterly periodic fallback. Change detection: SHA-256(source_text) != source_hash → re-embed. LLM fallback chain: Ollama → Gemini Flash Lite. UPSERT `entity_embedding_state WHERE view_type='definition'` with `next_refresh_at = now() + 90 days`. |
| T-D-3-05 | Worker 13D-2: Narrative state embedding refresh | impl | `infrastructure/workers/narrative_refresh.py` | Hourly check, picks entities WHERE `view_type='narrative' AND next_refresh_at < now()`. Source text: canonical_name + entity_type + top-5 claims by date + top-5 mention contexts (incl. light-tier) + active contradictions. Truncate 512 tokens. No LLM (deterministic template → embed only). UPSERT with `next_refresh_at = now() + 7 days`. |
| T-D-3-06 | Worker 13D-3: Fundamentals+OHLCV state embedding refresh | impl | `infrastructure/workers/fundamentals_refresh.py` | 30-day schedule. Only ticker entities. Calls S3 REST API: `GET /api/v1/fundamentals/{id}` + `GET /api/v1/ohlcv/{id}?timeframe=monthly&limit=12` + `GET /api/v1/ohlcv/{id}?timeframe=weekly&limit=12`. Builds narrative via `build_fundamentals_narrative()` (deterministic, no LLM). S3 down → retry 1h/4h/24h backoff. |
| T-D-3-07 | Consumer 13D-4: Instrument entity creation | impl | `infrastructure/consumer/instrument_consumer.py` | Consumer group: `kg-instrument-group`. Consumes `market.instrument.created`. Creates canonical_entity + mechanical aliases (ticker, exchange:ticker, name, ISIN) + LLM-generated supplementary aliases (via ExtractionClient with fallback chain; validate: reject alias if collision with different entity). Embeds description as definition view. Inserts 3 `entity_embedding_state` rows. Logs to `llm_usage_log`. |
| T-D-3-08 | Consumer 13D-5: Fundamentals description change detector | impl | `infrastructure/consumer/fundamentals_consumer.py` | Consumer group: `kg-fundamentals-group`. Consumes `market.dataset.fetched` WHERE `dataset_type='fundamentals'`. Downloads from MinIO claim-check. Extracts `General.Description`. SHA-256 compare → re-embed definition if changed. |
| T-D-3-09 | LLM fallback chain client | impl | `infrastructure/llm/fallback_chain.py` | `FallbackChainClient` wrapping `EmbeddingClient`/`ExtractionClient`. Ollama (3 retries 30s/60s/120s) → Gemini Flash Lite (2 retries) → NULL + schedule retry. All calls logged to `llm_usage_log` with (model, provider, tokens, cost, latency). |
| T-D-3-10 | Worker 13E: Provisional entity enrichment | impl | `infrastructure/workers/provisional_enrichment.py` | 10-min interval. LLM generates profile via ExtractionClient (with fallback chain). INSERT canonical_entities + aliases. INSERT 3 entity_embedding_state rows (definition with embedding, narrative + fundamentals NULL). UPDATE mentions + evidence_raw. EMIT entity.canonical.created.v1 + entity.dirtied.v1. Log to llm_usage_log. |
| T-D-3-11 | Workers 13F–G: Relation embedding refresh + partition mgmt | impl | `infrastructure/workers/embedding_refresh.py`, `infrastructure/workers/partitions.py` | 13F: relation summaries missing embeddings (2h). 13G: monthly partition creation + 24-month pruning. |
| T-D-3-12 | `build_fundamentals_narrative()` utility | impl | `application/utils/fundamentals_narrative.py` | Deterministic template function per PRD §6.7 Block 13D-3: converts structured financial data (revenue, margins, P/E, price, 52-week range) into embeddable narrative with interpretive words ("growing", "expensive", "near highs"). Zero LLM cost. |
| T-D-3-06 | Workers 13G–H: Partition management | impl | `infrastructure/workers/partitions.py` | 13G (1st of month + startup): create current + next month partitions for relation_evidence, events, claims; `IF NOT EXISTS` idempotent. 13H (1st of year + startup): yearly partitions; idempotent |
| T-D-3-07 | Outbox dispatcher | impl | `infrastructure/outbox/dispatcher.py` | Polls `intelligence_db.outbox_events`; publishes 3 topics: `graph.state.changed.v1`, `intelligence.contradiction.v1`, `relation.type.proposed.v1`; entity.dirtied.v1 NOT via outbox (direct produce in Block 12a); warning log if found in outbox |
| T-D-3-08 | Block 14: Shadow migration design memo | docs | `docs/plans/block-14-shadow-migration-design.md` | 4-phase design: shadow column, dual write, backfill, cutover; env vars documented; implementation status: DEFERRED |
| T-D-3-13 | Unit tests for workers + consumers + outbox | test | `tests/unit/infrastructure/workers/`, `tests/unit/infrastructure/consumer/`, `tests/unit/infrastructure/outbox/` | ≥35 tests: confidence formula (bounded ≤1.0), summary evidence_hash skip, narrative template 512-token truncation, definition SHA-256 change detection (same hash → skip), fundamentals_narrative deterministic output, instrument consumer creates 3 embedding_state rows, LLM alias validation (collision → reject), fallback chain (Ollama fail → Gemini called → logged), llm_usage_log insert, fundamentals description change detection (changed → re-embed, unchanged → skip), S3 REST failure → retry backoff, partition idempotency, outbox routing (3 topics) |

#### Pre-Read
- `libs/ml-clients/src/ml_clients/` — EmbeddingClient, ExtractionClient protocols
- `libs/messaging/src/messaging/valkey/` — Valkey client for entity dedup lock

#### Validation Gate
- [ ] `ruff check services/knowledge-graph/` passes
- [ ] `mypy services/knowledge-graph/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/knowledge-graph/tests/unit -v` — all tests pass (≥70 total)
- [ ] All workers registered in KnowledgeGraphScheduler
- [ ] Instrument consumer creates canonical_entity + 3 entity_embedding_state rows
- [ ] LLM alias collision validation works (reject alias belonging to different entity)
- [ ] Fallback chain: Ollama failure → Gemini invoked → llm_usage_log row written
- [ ] `build_fundamentals_narrative()` is deterministic (same input → same output)
- [ ] Definition embedding: unchanged description → SHA-256 match → skip re-embed
- [ ] `docs/services/knowledge-graph.md` updated with multi-view embedding architecture, worker table, S3 REST dependency

#### Regression Guardrails
- Custom: Confidence formula bounded [0, 1] — tested with extreme inputs
- Custom: Definition embedding uses SHA-256 change detection — never re-embeds unchanged text
- Custom: LLM alias generation validated against existing entity_aliases — collision → reject
- Custom: All LLM calls logged to llm_usage_log (including Ollama $0 calls)
- Custom: Partition creation is idempotent (IF NOT EXISTS)
- Custom: `entity_embedding_state` has exactly 3 rows per entity (never more, never fewer)

---

### Wave D-4: S7 API, Health, Integration Tests

**Goal**: Complete S7 with REST API (graph query with `summary_authority()` computed at query time), health probes, Prometheus metrics, DLQ admin, main.py final wiring, and comprehensive integration tests including S6→S7 pipeline continuity.
**Depends on**: Wave D-3
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-D-4-01 | REST API endpoints | impl | `api/routes.py`, `api/schemas.py` | 3 endpoints: GET /entities/{entity_id}/graph (with `summary_authority()` computed at query time — NOT cached column), GET /relations (paginated, filtered), GET /graph/stats (aggregates); Pydantic response models |
| T-D-4-02 | Health/Ready + Prometheus + DLQ + main.py (PLAN-0003 pattern) | impl | `api/health.py`, `api/dlq.py`, `infrastructure/metrics/prometheus.py`, `main.py`, `config.py` | **Follow STANDARDS.md §5 canonical pattern (PLAN-0003)**: (1) `configure_logging()` FIRST in lifespan; (2) `create_metrics()` + `add_prometheus_middleware(app, metrics)` + `app.state.metrics = metrics`; (3) conditional `configure_tracing()` + `add_otel_middleware(app)` if `otlp_endpoint` set; (4) `RequestIdMiddleware` class in `create_app()`; (5) explicit `GET /metrics` endpoint; (6) `service_name: str = "knowledge-graph"` in config.py; (7) docker.env must have `KNOWLEDGE_GRAPH_LOG_LEVEL`, `KNOWLEDGE_GRAPH_LOG_JSON`, `KNOWLEDGE_GRAPH_OTLP_ENDPOINT`. **Custom metrics**: `s7_relations_upserted_total`, `s7_evidence_appended_total`, `s7_contradictions_detected_total`, `s7_confidence_recomputed_total`, `s7_summaries_generated_total`, `s7_embeddings_refreshed_total{worker}`; Health: /healthz (200), /readyz (intelligence_db + Kafka, 503 on failure); DLQ admin with X-Admin-Token; main.py lifespan starts scheduler (8 workers) + consumer + dispatcher |
| T-D-4-03 | Integration test fixtures | test | `tests/integration/conftest.py` | intelligence_db fixtures (confirm 8 relation partitions exist), Kafka fixtures, Valkey fixtures; prereq gate: intelligence-migrations must run before tests |
| T-D-4-04 | Integration tests — graph + confidence + pipeline | test | `tests/integration/test_graph_upsert.py`, `tests/integration/test_contradiction.py`, `tests/integration/test_confidence.py`, `tests/integration/test_valkey_dedup.py`, `tests/integration/test_alembic_guard.py`, `tests/integration/test_partitions.py`, `tests/integration/test_s6_s7_pipeline.py` | Graph upsert idempotency (ON CONFLICT DO UPDATE); contradiction round-trip (opposing claims → link → event); confidence bounded [0,1] + corroboration ≤0.20; Valkey entity refresh dedup (30-min); ALEMBIC_ENABLED=false RuntimeError; partitions exist; S6→S7 continuity: `nlp.article.enriched.v1` → `graph.state.changed.v1` |

#### Pre-Read
- `services/nlp-pipeline/tests/integration/` — S6 integration test reference

#### Validation Gate
- [ ] `python -m pytest services/knowledge-graph/tests/integration -v -m integration` — all integration tests pass
- [ ] `python -m pytest services/knowledge-graph/tests/unit -v` — no unit test regression (≥70)
- [ ] `ruff check` + `mypy` clean
- [ ] S6→S7 pipeline continuity confirmed
- [ ] `docs/services/knowledge-graph.md` fully updated; `services/knowledge-graph/.claude-context.md` updated

#### Regression Guardrails
- BP-003: Async fixture teardown
- BP-004: @pytest.mark.integration for conditional skip
- Custom: intelligence-migrations must run before S7 integration tests

---

## Sub-Plan E: S10 Alert Service

### Context

S10 is a new service (directory `services/alert/`) that fans out watchlist-triggered alerts. It consumes signals from S6 (`nlp.signal.detected.v1`) and S7 (`graph.state.changed.v1`, `intelligence.contradiction.v1`), resolves watchers via S1 internal API, deduplicates within a time window, writes alerts to `alert_db`, and pushes via WebSocket. S10 owns `alert_db` (Alembic IS enabled). S10 has a deployment gate on S1 providing internal watchlist lookup endpoints.

### Pre-Read (agent must read before any wave)
- `RULES.md` — hard rules
- `AGENTS.md` — coding standards
- `docs/MASTER_PLAN.md` — §4.10 (S10 definition)
- `docs/STANDARDS.md` — §5 (canonical observability pattern: logging → metrics → tracing init sequence, RequestIdMiddleware, health endpoints, `/metrics`, docker.env vars) — **PLAN-0003 reference**
- `docs/specs/0001-intelligence-pipeline.md` — §6.2.6 (S10 endpoints), §6.2.7 (S1 internal), §6.3.2 (alert.delivered.v1), §6.4.5, §7 (AD-9 dedup, AD-10 backfill)
- `services/alert/.claude-context.md`
- `services/portfolio/src/portfolio/api/` — S1 internal endpoints (required dependency)
- `services/content-ingestion/src/content_ingestion/app.py` — gold-standard observability wiring reference
- `libs/messaging/src/messaging/` — BaseKafkaConsumer
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave E-1: S10 Foundation — Service Setup, Domain, DB, S1 Client

**Goal**: Create the S10 service directory from scratch, establish domain models (AlertType, Alert, PendingAlert), database infrastructure with Alembic (S10 OWNS alert_db), S1 client with watchlist cache, and deployment gate documentation with contract tests.
**Depends on**: Wave D-4 (S7 integration test `test_s6_s7_pipeline` must pass) + S1 internal endpoints exist
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-E-1-01 | Service directory + config + domain | impl | `services/alert/` (new), `pyproject.toml`, `Makefile`, `src/alert/config.py`, `domain/enums.py`, `domain/entities.py`, `domain/errors.py` | Standard service structure; Settings (alert_db, Kafka topics/groups, Valkey, S1 URL, ALERT_DEDUP_WINDOW_SECONDS=300); `AlertType` enum (3 values: SIGNAL, GRAPH_CHANGE, CONTRADICTION); `Alert`, `PendingAlert`, `AlertDedup` domain models |
| T-E-1-02 | alert_db infrastructure + Alembic migration | impl | `infrastructure/db/session.py`, `infrastructure/db/models.py`, repositories (alert, pending_alert, dedup, outbox, dlq), `alembic/`, `alembic/versions/0001_initial_alert_schema.py` | ORM models: alerts, pending_alerts, alert_dedup (with dedup_key UNIQUE + window bucket), outbox_events, dlq_events; 5 repositories; Alembic migration creates all tables; S10 OWNS alert_db — Alembic IS enabled (unlike S6/S7) |
| T-E-1-03 | S1 client + watchlist cache | impl | `infrastructure/clients/s1_client.py`, `infrastructure/cache/watchlist_cache.py` | httpx-based `S1Client`: GET `/internal/v1/watchlists/by-entity/{entity_id}` → user_ids, POST `/internal/v1/watchlists/by-entities` → {entity_id: [user_ids]}, health_check; `WatchlistCache` with cache-aside pattern: Valkey `s10:v1:watchlist:by_entity:{entity_id}` TTL=300s; best-effort: S1 unavailable → return [] (never raises) |
| T-E-1-04 | Deployment gate docs + contract tests | test | `tests/contract/test_s1_contract.py`, docs update | 3 contract tests via pytest-httpserver: GET by-entity returns user_ids, POST by-entities returns map, S1 503 → graceful empty list; deployment gate documented: 4 required S1 endpoints specified |
| T-E-1-05 | Unit tests for S10 foundation | test | `tests/unit/domain/`, `tests/unit/infrastructure/` | ≥15 tests: AlertType values, domain model construction, repo CRUD, S1 client endpoints, watchlist cache hit/miss/invalidation, best-effort error handling |

#### Pre-Read
- `services/portfolio/src/portfolio/api/` — S1 endpoints (dependency)
- `services/content-ingestion/` — reference service structure

#### Validation Gate
- [ ] `ruff check services/alert/` passes
- [ ] `mypy services/alert/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/alert/tests -v` — ≥15 unit tests + 3 contract tests pass
- [ ] `alembic upgrade head` succeeds on alert_db
- [ ] S1 client graceful degradation: 503 → empty list (tested)
- [ ] `docs/services/alert-service.md` created with domain models, S1 dependency, deployment gate

#### Regression Guardrails
- BP-006: Load DATABASE_URL from settings
- BP-008: Migration matches ORM models
- Custom: S1 unavailable → graceful empty, never raises

---

### Wave E-2: S10 Consumers, Alert Fan-out, WebSocket, Outbox

**Goal**: Implement the 2-consumer-group topology (intelligence consumer for 3 signal topics + watchlist consumer for cache invalidation), alert fan-out use-case with dedup, WebSocket connection manager, and outbox dispatcher.
**Depends on**: Wave E-1
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-E-2-01 | WebSocket connection manager | impl | `infrastructure/websocket/manager.py` | `ConnectionManager`: Dict[user_id, WebSocket]; `/api/v1/alerts/stream?token=<jwt>`; send_to_user, broadcast; single-replica constraint documented; graceful disconnect |
| T-E-2-02 | Alert fan-out use-case | impl | `application/use_cases/alert_fanout.py` | `execute(event) -> FanoutResult`: resolve watchers via S1 client (batch lookup); dedup key = `sha256(f"{entity_id}:{alert_type}:{window_bucket}")` where window_bucket = `created_at // ALERT_DEDUP_WINDOW_SECONDS` — **NO source_event_id in key** (PRD AD-9: enables true dedup per entity+type+window); single transaction: INSERT alerts + INSERT pending_alerts + INSERT outbox_events; WebSocket push AFTER DB commit (not inside transaction); **Backfill suppression**: for `nlp.signal.detected.v1` and `graph.state.changed.v1`: `if event.is_backfill: return`; for `intelligence.contradiction.v1`: suppress if `is_backfill=true AND (detected_at - evidence_date) > 30 days` (PRD AD-10: recent-impact contradictions from backfill are still useful) |
| T-E-2-03 | Watchlist consumer | impl | `infrastructure/consumer/watchlist_consumer.py` | Group: `alert-service-watchlist-group`; consumes `portfolio.watchlist.updated.v1`; `item_added` → no-op (cache populated on next lookup); `item_deleted` → DEL Valkey key `s10:v1:watchlist:by_entity:{entity_id}` for each affected entity |
| T-E-2-04 | Intelligence consumer | impl | `infrastructure/consumer/intelligence_consumer.py` | Group: `alert-service-group`; consumes 3 topics: `nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1`; maps event_type to AlertType; routes to AlertFanoutUseCase; at-least-once with manual offset commit |
| T-E-2-05 | Outbox dispatcher | impl | `infrastructure/outbox/dispatcher.py` | Polls alert_db outbox; publishes `alert.delivered.v1`; marks dispatched or DLQ |
| T-E-2-06 | Unit tests for consumers + fan-out + WebSocket | test | `tests/unit/application/`, `tests/unit/infrastructure/` | ≥20 tests: fan-out dedup (same key within window → suppressed), fan-out backfill suppression, watchlist consumer invalidation, intelligence consumer routing (3 event types), WebSocket send/disconnect, outbox dispatch, dedup key computation |

#### Pre-Read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/consumer/` — consumer reference

#### Validation Gate
- [ ] `ruff check services/alert/` passes
- [ ] `mypy services/alert/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/alert/tests/unit -v` — all tests pass (≥35 total)
- [ ] Backfill suppression: is_backfill=true → no alert (explicit test)
- [ ] Dedup window: same (user, entity, type) within 300s → suppressed (explicit test)
- [ ] `docs/services/alert-service.md` updated with consumer topology, fan-out logic, dedup mechanism

#### Regression Guardrails
- BP-001: OutboxEventValueSerializer for outbox
- Custom: Backfill events MUST be suppressed (is_backfill check)
- Custom: WebSocket push is post-commit (never inside transaction)

---

### Wave E-3: S10 API, Health, Integration Tests + Full Pipeline Validation (FINAL WAVE)

**Goal**: Complete S10 with REST API (pending alerts, acknowledge), health probes (4 deps), Prometheus metrics, DLQ admin, main.py wiring, and integration tests including the final S7→S10 pipeline continuity test validating the complete S4→S5→S6→S7→S10 pipeline.
**Depends on**: Wave E-2
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-E-3-01 | REST API endpoints | impl | `api/routes.py`, `api/schemas.py` | GET /api/v1/alerts/pending (authenticated, paginated); DELETE /api/v1/alerts/{alert_id}/ack (scoped to user — 404 not 403 on wrong user); WebSocket /api/v1/alerts/stream (from Wave E-2) |
| T-E-3-02 | Health/Ready + Prometheus + DLQ + main.py (PLAN-0003 pattern) | impl | `api/health.py`, `api/dlq.py`, `infrastructure/metrics/prometheus.py`, `main.py`, `config.py` | **Follow STANDARDS.md §5 canonical pattern (PLAN-0003)**: (1) `configure_logging()` FIRST in lifespan; (2) `create_metrics()` + `add_prometheus_middleware(app, metrics)` + `app.state.metrics = metrics`; (3) conditional `configure_tracing()` + `add_otel_middleware(app)` if `otlp_endpoint` set; (4) `RequestIdMiddleware` class in `create_app()`; (5) explicit `GET /metrics` endpoint; (6) `service_name: str = "alert"` in config.py; (7) docker.env must have `ALERT_LOG_LEVEL`, `ALERT_LOG_JSON`, `ALERT_OTLP_ENDPOINT`. **Custom metrics**: `s10_alerts_fanned_out_total{type}`, `s10_alerts_deduplicated_total`, `s10_alerts_pending_total` (Gauge), `s10_websocket_pushes_total`; Health: /healthz (200), /readyz (alert_db + Kafka + Valkey + S1 /health — 4 deps, 503 on any failure); DLQ admin with X-Admin-Token; main.py lifespan starts 2 consumers + dispatcher + WebSocket manager |
| T-E-3-03 | Integration test fixtures | test | `tests/integration/conftest.py` | alert_db fixtures (Alembic), Kafka fixtures, Valkey fixtures, mock S1 (pytest-httpserver) |
| T-E-3-04 | Integration tests — alerts + dedup + pipeline | test | `tests/integration/test_watchlist_cache.py`, `tests/integration/test_fanout.py`, `tests/integration/test_dedup.py`, `tests/integration/test_websocket.py`, `tests/integration/test_s7_s10_pipeline.py` | Watchlist cache invalidation (item_deleted); fan-out end-to-end (mock S1 returns users → alert written); dedup within 300s window; WebSocket push to online user; **S7→S10 continuity**: `graph.state.changed.v1` → alert in alert_db (Milestone M7 — full pipeline validated) |
| T-E-3-05 | Unit tests for API + health | test | `tests/unit/api/` | ≥10 tests: pending alerts pagination, ack scoped to user (404 on wrong user), health checks (4 deps), DLQ auth, metrics counters |

#### Pre-Read
- `services/nlp-pipeline/tests/integration/` — integration test reference
- `services/knowledge-graph/tests/integration/` — integration test reference

#### Validation Gate
- [ ] `python -m pytest services/alert/tests/integration -v -m integration` — all integration tests pass
- [ ] `python -m pytest services/alert/tests -v` — all tests pass (≥45 total)
- [ ] `ruff check` + `mypy` clean across S6, S7, S10
- [ ] S7→S10 continuity test confirms: enriched event → graph write → graph.state.changed.v1 → alert fan-out → alert in alert_db
- [ ] Full pipeline milestone M7: S4→S5→S6→S7→S10 validated
- [ ] `docs/services/alert-service.md` fully updated; `services/alert/.claude-context.md` updated

#### Regression Guardrails
- BP-003: Async fixture teardown
- BP-004: @pytest.mark.integration for conditional skip
- Custom: S1 mock must return realistic responses (not empty)
- Custom: WebSocket test must verify actual push delivery

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Compatibility | Test |
|------|------|--------------|------|
| Avro | `nlp.article.enriched.v1.avsc` | Forward-compatible | T-C-4-05 (integration) |
| Avro | `nlp.signal.detected.v1.avsc` | Forward-compatible | T-C-4-05 (integration) |
| Avro | `graph.state.changed.v1.avsc` | Forward-compatible | T-D-4-04 (integration) |
| Avro | `intelligence.contradiction.v1.avsc` | Forward-compatible | T-D-4-04 (integration) |
| Avro | `relation.type.proposed.v1.avsc` | Forward-compatible | T-D-2-06 (unit) |
| Avro | `entity.dirtied.v1.avsc` | Compacted topic | T-D-2-06 (unit) |
| Avro | `alert.delivered.v1.avsc` | Forward-compatible | T-E-2-06 (unit) |
| REST | S6 API (6 endpoints) | New service | T-C-4-06 (unit) |
| REST | S7 API (3 endpoints) | New service | T-D-4-01 (unit) |
| REST | S10 API (2 REST + 1 WebSocket) | New service | T-E-3-05 (unit) |
| REST | S1 internal endpoints (2) | Required by S10 | T-E-1-04 (contract) |

### Migrations
| Service | Migration | Description | Order |
|---------|-----------|-------------|-------|
| nlp-pipeline | `0001_initial_nlp_schema.py` | nlp_db tables + pgvector + HNSW indexes | Wave C-1 |
| intelligence-migrations | (pre-existing) | intelligence_db DDL — must run before S6/S7 | Before C-1 |
| alert | `0001_initial_alert_schema.py` | alert_db: alerts, pending_alerts, alert_dedup, outbox, dlq | Wave E-1 |

### Observability (PLAN-0003 Dependency)

All three services (S6, S7, S10) **must** follow the canonical observability pattern defined in `STANDARDS.md §5` (written by PLAN-0003 Wave A-1). Specifically:

- **`pyproject.toml`**: Each service must declare `"observability"` as an explicit dependency
- **`config.py`**: Must include `service_name`, `log_level`, `log_json`, `otlp_endpoint` fields
- **`app.py` / `main.py`**: Must follow the canonical init sequence (logging → metrics → tracing) in lifespan, add `RequestIdMiddleware`, expose `GET /metrics`
- **`configs/docker.env`**: Must include `{PREFIX}_LOG_LEVEL`, `{PREFIX}_LOG_JSON`, `{PREFIX}_OTLP_ENDPOINT`
- **Custom metrics**: File at `infrastructure/metrics/prometheus.py` with `s{N}_` prefix naming convention
- **Reference implementation**: `services/content-ingestion/src/content_ingestion/app.py`

Tasks T-C-4-04, T-D-4-02, and T-E-3-02 specify the exact requirements per service.

### Configuration
| Service | Env Var | Default | Purpose |
|---------|---------|---------|---------|
| S6 | `NLP_PIPELINE_LOG_LEVEL` | `INFO` | Observability: log level (PLAN-0003) |
| S6 | `NLP_PIPELINE_LOG_JSON` | `true` | Observability: JSON logs (PLAN-0003) |
| S6 | `NLP_PIPELINE_OTLP_ENDPOINT` | `` | Observability: OTLP trace export (PLAN-0003) |
| S6 | `NLP_DATABASE_URL` | — | nlp_db connection |
| S6 | `INTELLIGENCE_DATABASE_URL` | — | intelligence_db connection (read/write) |
| S6 | `ALEMBIC_ENABLED` | `true` | Alembic for nlp_db only |
| S6 | `MAX_OLLAMA_QUEUE_DEPTH` | `20` | Backpressure pause threshold |
| S6 | `RESUME_OLLAMA_QUEUE_DEPTH` | `10` | Backpressure resume threshold |
| S6 | `EMBEDDING_CHUNK_SIZE` | `512` | Chunk token size |
| S6 | `EMBEDDING_CHUNK_OVERLAP` | `64` | Chunk overlap tokens |
| S6 | `AUTO_RESOLVE_THRESHOLD` | `0.85` | Entity resolution auto-resolve |
| S6 | `PROVISIONAL_THRESHOLD` | `0.60` | Entity resolution provisional |
| S7 | `KNOWLEDGE_GRAPH_LOG_LEVEL` | `INFO` | Observability: log level (PLAN-0003) |
| S7 | `KNOWLEDGE_GRAPH_LOG_JSON` | `true` | Observability: JSON logs (PLAN-0003) |
| S7 | `KNOWLEDGE_GRAPH_OTLP_ENDPOINT` | `` | Observability: OTLP trace export (PLAN-0003) |
| S7 | `INTELLIGENCE_DATABASE_URL` | — | intelligence_db connection |
| S7 | `ALEMBIC_ENABLED` | `false` | MUST be false — DDL owned by intelligence-migrations |
| S7 | `RELATION_CANONICALIZATION_THRESHOLD` | `0.35` | Soft-map cosine distance |
| S7 | `WORKER_13A_INTERVAL_MINUTES` | `15` | Confidence recomputation |
| S7 | `WORKER_13B_INTERVAL_MINUTES` | `30` | Contradiction batch |
| S7 | `WORKER_13C_INTERVAL_MINUTES` | `60` | Summary generation |
| S7 | `WORKER_13D_INTERVAL_MINUTES` | `60` | Entity profile embedding |
| S7 | `TEMPORAL_CLAIM_DECAY_ALPHA` | `0.02310` | 30-day half-life |
| S10 | `ALERT_LOG_LEVEL` | `INFO` | Observability: log level (PLAN-0003) |
| S10 | `ALERT_LOG_JSON` | `true` | Observability: JSON logs (PLAN-0003) |
| S10 | `ALERT_OTLP_ENDPOINT` | `` | Observability: OTLP trace export (PLAN-0003) |
| S10 | `ALERT_DATABASE_URL` | — | alert_db connection |
| S10 | `S1_BASE_URL` | — | Portfolio service URL |
| S10 | `S1_INTERNAL_TOKEN` | — | S1 internal auth token |
| S10 | `ALERT_DEDUP_WINDOW_SECONDS` | `300` | Dedup suppression window |

### Documentation Updates
| Document | Update Required |
|----------|----------------|
| `docs/services/nlp-pipeline.md` | Blocks 3–10, entity resolution, backpressure, API, metrics |
| `docs/services/knowledge-graph.md` | Hot path, workers, confidence formula, API, metrics |
| `docs/services/alert-service.md` | New document: fan-out, consumers, WebSocket, S1 dependency |
| `services/nlp-pipeline/.claude-context.md` | Endpoints, topics, entities, pitfalls |
| `services/knowledge-graph/.claude-context.md` | Endpoints, topics, entities, pitfalls |
| `services/alert/.claude-context.md` | Endpoints, topics, entities, pitfalls |
| `docs/plans/block-14-shadow-migration-design.md` | Shadow migration design memo (deferred) |

---

## Risk Assessment

### Critical Path
```
C-1 (S6 foundation) → C-2 (blocks 3-6) → C-3 (blocks 7-10) → C-4 (consumer/integration)
  → D-1 (S7 foundation) → D-2 (hot path) → D-3 (workers) → D-4 (integration)
    → E-1 (S10 foundation) → E-2 (consumers) → E-3 (full pipeline test)
```
The critical path is strictly sequential across services. S6 must fully emit before S7 can consume; S7 must emit before S10 can consume. S1 internal endpoints are a parallel external dependency for S10.

### Highest Risk
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| intelligence_db DDL mismatch | Medium | High — S6/S7 runtime failures | Compare ORM models against intelligence-migrations DDL; ALEMBIC_ENABLED=false guard |
| Confidence formula unbounded | Medium | High — invalid graph state | ConfidenceComponents.validate() assertions; boundary unit tests with extreme inputs |
| Ollama model unavailability | Medium | Medium — S6 pipeline stalls | Backpressure controller; embedding_pending_queue retry; readiness check for model loading |
| S1 internal endpoints missing | High | Blocking — S10 cannot deploy | Contract tests (T-E-1-04); deployment gate docs; stub for development |
| Partition key in INSERT | Medium | High — Postgres error | Grep verification; explicit test that INSERT omits partition_key |

### Rollback Strategy
- Each wave leaves codebase green; git stash/reset to pre-wave state
- Sub-plans are semi-independent: S6 failure does not affect existing S4/S5
- S7 depends on S6 output — if S6 is incomplete, S7 integration tests will be skipped
- S10 can be developed with mocked S7 events if S7 is delayed
- intelligence-migrations is a hard prereq — must run before any S6/S7 integration tests

---

## Tracking

### Plan Status
| Plan | Status | Waves Done | Waves Total |
|------|--------|-----------|-------------|
| C: S6 NLP Pipeline | pending | 0 | 4 |
| D: S7 Knowledge Graph | pending | 0 | 4 |
| E: S10 Alert Service | pending | 0 | 3 |

### Wave Status
| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| C-1 | pending | 0 | 5 | PLAN-0012 complete |
| C-2 | pending | 0 | 5 | C-1 |
| C-3 | pending | 0 | 6 | C-2 |
| C-4 | pending | 0 | 6 | C-3 |
| D-1 | pending | 0 | 4 | C-4 |
| D-2 | pending | 0 | 6 | D-1 |
| D-3 | pending | 0 | 13 | D-2 |
| D-4 | pending | 0 | 4 | D-3 |
| E-1 | pending | 0 | 5 | D-4, S1 internal endpoints |
| E-2 | pending | 0 | 6 | E-1 |
| E-3 | pending | 0 | 5 | E-2 |

### Milestones
| Milestone | Description | Gate Wave |
|-----------|-------------|-----------|
| M1 | S6 Blocks 3–6 complete (sectioning, NER, routing, suppression) | C-2 |
| M2 | S6 Blocks 7–10 complete (embeddings, novelty, entity resolution, extraction) | C-3 |
| M3 | S6 fully emitting `nlp.article.enriched.v1` | C-4 |
| M4 | S7 hot path complete (graph writes, contradiction detection) | D-2 |
| M5 | S7 workers complete (confidence, summaries, embeddings updating) | D-3 |
| M6 | S10 alert fan-out complete (watchlist-triggered alerts flowing) | E-2 |
| M7 | Full pipeline validated: S4→S5→S6→S7→S10 | E-3 |
