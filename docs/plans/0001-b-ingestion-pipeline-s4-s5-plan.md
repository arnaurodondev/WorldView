---
id: PLAN-0001-B
prd: PRD-0001
title: "Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store — Implementation Plan"
status: draft
created: 2026-03-25
updated: 2026-03-25
plans: 2
waves: 8
tasks: 28
supersedes: "Original draft based on PRD-0014"
---

# PLAN-0001-B: S4 Content Ingestion + S5 Content Store

## Overview

**PRD Reference**: [PRD-0001](../specs/0001-intelligence-pipeline.md) — §6.1, §6.2.1–6.2.2, §6.3.2, §6.4.1–6.4.2, §6.7 Blocks 1–2
**Depends on**: PLAN-0001-A Wave 1 (Avro schemas must exist)
**Goal**: Implement the first two services of the unstructured intelligence pipeline — S4 polls external content sources and writes raw articles to MinIO bronze + outbox; S5 consumes, deduplicates (3-tier), writes canonical docs to MinIO silver + outbox — producing `content.article.stored.v1` events for S6.
**Total Scope**: 2 sub-plans, 8 waves, 28 tasks

---

## Plan Dependency Graph

```
Sub-Plan A: S4 Content Ingestion ──┐
                                   ├──→ PLAN-0013 Sub-Plan C (S6 NLP Pipeline)
Sub-Plan B: S5 Content Store ──────┘
```

**Execution Order**:
1. Sub-Plan A (S4) — Waves A-1 through A-4 (sequential)
2. Sub-Plan B (S5) — Waves B-1 through B-4 (sequential); B-1 can start after A-2 completes
3. A-4 and B-4 are integration waves that validate end-to-end S4→S5 continuity

**Session Boundaries**: Each sub-plan is designed to execute in 1–2 Claude Code sessions.

---

## Sub-Plan A: S4 Content Ingestion

### Context

S4 is a polling-based content ingestion service. It uses APScheduler to periodically fetch articles from 4 external APIs (EODHD News, SEC EDGAR, Finnhub, NewsAPI), writes raw payloads to MinIO bronze tier, persists metadata to `content_ingestion_db`, and emits `content.article.raw.v1` events via the outbox pattern. The service includes admin CRUD endpoints, DLQ management, and Prometheus observability.

### Pre-Read (agent must read before any wave)
- `RULES.md` — hard rules (outbox, UUIDv7, UTC, structlog)
- `AGENTS.md` — coding standards, hexagonal architecture
- `docs/MASTER_PLAN.md` — §4.4 (S4 definition), §5.2 (Kafka topics)
- `docs/specs/0001-intelligence-pipeline.md` — §6.2.1, §6.3.2 (content.article.raw.v1), §6.4.1, §6.7 Block 1
- `services/content-ingestion/.claude-context.md`
- `docs/services/content-ingestion.md`
- `libs/messaging/src/messaging/` — outbox dispatcher, Kafka producer
- `libs/storage/src/storage/` — S3/MinIO adapter
- `libs/contracts/src/contracts/` — canonical models
- `libs/common/src/common/` — ids, time, types
- `docs/ai-interactions/BUG_PATTERNS.md` — BP-001 through BP-011

---

### Wave A-1: S4 Foundation — Config, Domain, DB, MinIO

**Goal**: Establish the zero-dependency foundation layer: settings, domain entities, database infrastructure with repositories, MinIO bronze adapter, and Avro schema definition.
**Depends on**: none
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-1-01 | Config + Domain entities | impl | `services/content-ingestion/src/content_ingestion/config.py`, `domain/enums.py`, `domain/entities.py`, `domain/errors.py` | Settings with all env vars (DB, Kafka, MinIO, API keys, backfill); `SourceType` enum (5 values: eodhd, sec_edgar, finnhub, newsapi, manual); `Source`, `FetchResult`, `RawArticle` frozen dataclasses; `TokenBucket` with `consume()`/`wait_time()`; domain exceptions hierarchy; `published_at` + `is_backfill` fields on `FetchResult`/`RawArticle`; byte_size invariant on RawArticle |
| T-A-1-02 | Database infrastructure + repositories | impl | `infrastructure/db/session.py`, `infrastructure/db/models.py`, `infrastructure/db/repositories/source.py`, `infrastructure/db/repositories/fetch_log.py`, `infrastructure/db/repositories/adapter_state.py`, `infrastructure/db/repositories/outbox.py` | SQLAlchemy 2.x models: `sources`, `source_adapter_state` (per-source watermark + cursor + error tracking), `article_fetch_log` (with `published_at`, `is_backfill`, UNIQUE on url_hash), `outbox_events`, `dead_letter_queue`; 4 repositories (Source CRUD, AdapterState get/update, FetchLog create/exists_by_url_hash, Outbox append/fetch_pending/mark_dispatched/mark_failed/move_to_dlq); `FOR UPDATE SKIP LOCKED` on fetch_pending |
| T-A-1-03 | Alembic migrations | schema | `alembic/`, `alembic/versions/0001_initial_s4_schema.py` | Initial migration creates all 5 tables (sources, source_adapter_state, article_fetch_log, outbox_events, dead_letter_queue); `url_hash` UNIQUE index on `article_fetch_log`; `(status, created_at)` partial index on `outbox_events`; migration matches ORM models exactly (guard BP-008) |
| T-A-1-04 | MinIO bronze adapter | impl | `infrastructure/storage/minio_bronze.py` | Key pattern `content-ingestion/{source_type}/{url_hash}/raw/v1.json`; `put_object(article)` async via `asyncio.to_thread`; `object_exists()` check; JSON envelope with metadata; uses `libs/storage` S3ObjectStorage |
| T-A-1-05 | Outbox dispatcher + Avro schema | impl | `infrastructure/outbox/dispatcher.py`, `infrastructure/outbox/serializer.py` | Dispatcher polls outbox, serializes to Avro `content.article.raw.v1` schema (article_id, source_type, url, url_hash, minio_key, fetched_at, byte_size, published_at, is_backfill); publishes to Kafka; marks dispatched or moves to DLQ after MAX_RETRIES; uses `OutboxEventValueSerializer` not `KafkaEventValueSerializer` (guard BP-001) |
| T-A-1-06 | Unit tests for foundation layer | test | `tests/unit/domain/`, `tests/unit/infrastructure/` | ≥25 tests: TokenBucket logic, RawArticle byte_size, repo CRUD, exists_by_url_hash idempotency, Avro roundtrip, MinIO key format, envelope structure, dispatcher success/failure/DLQ paths |

#### Pre-Read
- `services/portfolio/src/portfolio/infrastructure/db/` — reference implementation for session/models/repos
- `services/portfolio/src/portfolio/infrastructure/outbox/` — reference outbox dispatcher
- `infra/kafka/schemas/content.article.raw.v1.avsc` — Avro schema

#### Validation Gate
- [ ] `ruff check services/content-ingestion/` passes
- [ ] `mypy services/content-ingestion/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-ingestion/tests/unit -v` — ≥25 tests pass
- [ ] Domain layer has zero infrastructure imports
- [ ] `alembic upgrade head` succeeds against test Postgres
- [ ] `docs/services/content-ingestion.md` updated with domain entities, MinIO key pattern, Avro schema fields

#### Regression Guardrails
- BP-001: Use `OutboxEventValueSerializer`, not `KafkaEventValueSerializer`
- BP-006: Load `DATABASE_URL` from settings, not alembic.ini
- BP-008: Verify migration matches final ORM model state

---

### Wave A-2: S4 Source Adapters — 4 External API Clients

**Goal**: Implement all 4 external API adapters (EODHD, SEC EDGAR, Finnhub, NewsAPI) with rate limiting, dedup-by-URL-hash, retry (3x backoff), DLQ routing, and backfill support.
**Depends on**: Wave A-1
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-2-01 | Base adapter + EODHD adapter | impl | `infrastructure/adapters/base.py`, `infrastructure/adapters/eodhd/client.py`, `infrastructure/adapters/eodhd/adapter.py` | Abstract `SourceAdapter` with `async fetch(source) -> list[FetchResult]`; EODHD: offset pagination, TokenBucket(10 req/s), sha256(url) dedup, 3x retry with 1s/2s/4s backoff, `published_at` from `article['date']`, `is_backfill` from settings |
| T-A-2-02 | SEC EDGAR adapter | impl | `infrastructure/adapters/sec_edgar/client.py`, `infrastructure/adapters/sec_edgar/adapter.py` | EFTS full-text search; User-Agent required (ConfigurationError if missing); asyncio.Semaphore(8) for rate limiting; sha256(accession_number+filename) dedup; `published_at` from `period_of_report` or `file_date`; HTML+XBRL doc fetch |
| T-A-2-03 | Finnhub adapter | impl | `infrastructure/adapters/finnhub/client.py`, `infrastructure/adapters/finnhub/adapter.py` | News + transcripts endpoints; TokenBucket(55 req/min); RateLimitError on 429 with `sleep_secs=60-now().second`; sha256(str(article_id)) dedup; `published_at` from Unix timestamp |
| T-A-2-04 | NewsAPI adapter | impl | `infrastructure/adapters/newsapi/client.py`, `infrastructure/adapters/newsapi/adapter.py` | API key in `X-Api-Key` header (not query param); Valkey daily quota `newsapi:daily_requests:{YYYY-MM-DD}` with 86400s TTL; QuotaExhaustedError breaks immediately (no retry); page pagination; `published_at` from ISO-8601 `publishedAt` |
| T-A-2-05 | Unit tests for all adapters | test | `tests/unit/infrastructure/adapters/` | ≥20 tests: per-adapter pagination, dedup skip, retry exhaustion → DLQ, rate limiter, published_at extraction, is_backfill flag, SEC User-Agent validation, NewsAPI quota halt, Finnhub 429 backoff |

#### Pre-Read
- `services/market-ingestion/src/market_ingestion/infrastructure/` — reference adapter pattern
- `libs/messaging/src/messaging/valkey/` — Valkey client for NewsAPI quota

#### Validation Gate
- [ ] `ruff check services/content-ingestion/` passes
- [ ] `mypy services/content-ingestion/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-ingestion/tests/unit -v` — all tests pass (≥45 total)
- [ ] No inter-adapter imports (each adapter is self-contained)
- [ ] `docs/services/content-ingestion.md` updated with adapter table (rate limits, dedup methods, DLQ triggers)

#### Regression Guardrails
- BP-002: Ensure env vars for API keys are loaded from settings, not hardcoded
- BP-011: Avro schema files accessible at runtime (if needed for serialization)

---

### Wave A-3: S4 Scheduler, Use-Case, Admin API, DLQ, Observability

**Goal**: Complete S4 service with APScheduler polling, fetch-and-write use-case (outbox pattern), admin API endpoints, DLQ management, health probes, Prometheus metrics, and `main.py` wiring.
**Depends on**: Wave A-2
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-3-01 | APScheduler polling scheduler | impl | `infrastructure/scheduler/advisory_lock.py`, `infrastructure/scheduler/scheduler.py` | `pg_advisory_lock()` async context manager (non-blocking `pg_try_advisory_lock`); `IngestionScheduler` adds one `IntervalTrigger` job per enabled source; lock acquired → run adapter, not acquired → skip; `ADAPTER_REGISTRY` maps SourceType → AdapterClass |
| T-A-3-02 | Fetch-and-write use-case | impl | `application/use_cases/fetch_and_write.py` | `execute(source) -> FetchSummary`: calls adapter.fetch(), for each result: check exists_by_url_hash (idempotent), put_object to MinIO, atomic transaction (INSERT fetch_log + INSERT outbox_event); NEVER calls Kafka directly; outbox payload matches Avro schema exactly; returns FetchSummary(fetched, skipped, failed, duration_seconds) |
| T-A-3-03 | Admin + Internal API endpoints | impl | `api/schemas.py`, `api/dependencies.py`, `api/admin.py`, `api/internal.py` | Admin (5 endpoints): GET/POST/PUT /sources, POST /sources/{id}/trigger, GET /status; all require `X-Admin-Token`. Internal (1 endpoint): POST /internal/v1/ingest/submit (accept raw content or URL from S9 webhook flow, `X-Internal-Token` auth); Pydantic request/response models per PRD §6.2.1 |
| T-A-3-04 | DLQ admin + Health/Ready + Prometheus | impl | `infrastructure/db/repositories/dlq.py`, `api/dlq.py`, `api/health.py`, `infrastructure/metrics/prometheus.py` | DLQ: list_open/get_by_id/mark_resolved/requeue; Health: GET /health (200 always), GET /ready (DB + Kafka + MinIO checks, 503 on failure), GET /metrics; Prometheus: `s4_fetches_total{source,status}`, `s4_fetch_duration_seconds`, `s4_outbox_pending_total`; use-case instrumented with metric calls |
| T-A-3-05 | main.py + lifespan wiring | impl | `main.py` | FastAPI app with asynccontextmanager lifespan starting scheduler + outbox dispatcher + metrics poller; include admin_router, dlq_router, health_router; exception handlers wired |
| T-A-3-06 | Unit tests for Wave A-3 | test | `tests/unit/application/`, `tests/unit/api/` | ≥25 tests: scheduler jobs only for enabled sources, lock skip, use-case round-trip + duplicate skip + MinIO/DB error isolation + summary counts, API auth + CRUD + trigger + status, DLQ list/retry/resolve, health checks, metrics increment |

#### Pre-Read
- `services/portfolio/src/portfolio/app.py` — reference main.py/lifespan pattern
- `services/portfolio/src/portfolio/api/` — reference API structure

#### Validation Gate
- [ ] `ruff check services/content-ingestion/` passes
- [ ] `mypy services/content-ingestion/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-ingestion/tests/unit -v` — all tests pass (≥70 total)
- [ ] Outbox pattern verified: no direct Kafka produce in use-case
- [ ] `docs/services/content-ingestion.md` updated with API endpoint table, scheduler advisory lock rationale, Prometheus metrics, Mermaid sequence diagram (fetch → MinIO → DB → outbox → Kafka)

#### Regression Guardrails
- BP-001: Outbox serializer choice (OutboxEventValueSerializer)
- BP-009: Let factory derive DispatcherConfig from settings
- BP-010: Health checks for readiness (not --wait)

---

### Wave A-4: S4 Integration Tests

**Goal**: Validate the complete S4 pipeline end-to-end against real infrastructure (Postgres, Kafka, MinIO). This wave is the exit gate before S5 can consume S4 output.
**Depends on**: Wave A-3
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-A-4-01 | Docker Compose test infrastructure | config | `tests/docker-compose.test.yml` | Postgres, Kafka (KRaft), MinIO, Schema Registry; health checks for each service; profiles for selective startup |
| T-A-4-02 | Integration test fixtures | test | `tests/integration/conftest.py` | session_factory (runs Alembic), minio_client (creates test buckets), kafka_consumer (subscribes to output topic); cleanup between tests |
| T-A-4-03 | Integration tests — pipeline + idempotency | test | `tests/integration/test_pipeline.py`, `tests/integration/test_idempotency.py` | Pipeline: mock EODHD HTTP → FetchAndWriteUseCase.execute() → assert MinIO object at pattern + fetch_log row + outbox_event pending → run dispatcher → assert Kafka message received + status=dispatched; Idempotency: same URL twice → exactly 1 fetch_log + 1 outbox_event |
| T-A-4-04 | Integration tests — admin API + outbox | test | `tests/integration/test_admin_api.py`, `tests/integration/test_outbox_dispatcher.py` | Admin: CRUD sources + trigger ingest + check status against real DB; Outbox: seed event → run_once() → Kafka message received + dispatched_at set |

#### Pre-Read
- `services/market-ingestion/tests/integration/` — reference integration test setup
- `services/market-data/tests/integration/` — reference fixtures

#### Validation Gate
- [ ] `python -m pytest services/content-ingestion/tests/integration -v -m integration` — all integration tests pass
- [ ] `python -m pytest services/content-ingestion/tests/unit -v` — no unit test regression
- [ ] `ruff check` + `mypy` clean
- [ ] S4 pipeline confirmed: raw article → MinIO bronze → outbox → Kafka `content.article.raw.v1`

#### Regression Guardrails
- BP-003: Async fixture teardown — use `asyncio_mode=auto`, scope carefully
- BP-004: Skip integration tests when infra unavailable via `@pytest.mark.integration`
- BP-005: Docker compose service health checks before test execution

---

## Sub-Plan B: S5 Content Store

### Context

S5 is a Kafka consumer service. It consumes `content.article.raw.v1` events from S4, cleans HTML/text content, runs 3-tier deduplication (exact SHA-256 → normalized hash → MinHash LSH via Valkey), writes canonical documents to MinIO silver tier, and emits `content.article.stored.v1` events via outbox. The service includes novelty score tracking, DLQ management, and Prometheus observability.

### Pre-Read (agent must read before any wave)
- `RULES.md` — hard rules
- `AGENTS.md` — coding standards
- `docs/MASTER_PLAN.md` — §4.5 (S5 definition)
- `docs/specs/0001-intelligence-pipeline.md` — §6.2.2, §6.3.2 (content.article.stored.v1), §6.4.2, §6.7 Block 2
- `services/content-store/.claude-context.md`
- `docs/services/content-store.md`
- `libs/messaging/src/messaging/` — BaseKafkaConsumer, outbox
- `libs/storage/src/storage/` — S3ObjectStorage
- `docs/ai-interactions/BUG_PATTERNS.md`

---

### Wave B-1: S5 Foundation — Config, Domain, DB

**Goal**: Establish S5 foundation: settings, domain entities (dedup decisions, canonical document, corroboration policy), database infrastructure with ORM models and repositories, Alembic migration.
**Depends on**: Wave A-2 (S4 Avro schema defined — needed for Article deserialization)
**Estimated effort**: 45–60 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-1-01 | Config + Domain entities | impl | `services/content-store/src/content_store/config.py`, `domain/enums.py`, `domain/entities.py`, `domain/errors.py` | Settings (DB, Kafka topics, MinIO, Valkey, MINHASH_NUM_PERM=128); per-source thresholds: NEWS hard=0.72/soft=0.55, FILINGS hard=0.85/soft=0.70, TRANSCRIPTS hard=0.75/soft=0.60, RESEARCH hard=0.70/soft=0.55 (from PRD §6.7 Block 2); `DedupOutcome` enum (UNIQUE, CORROBORATING, SEMANTIC_NEAR_DUPLICATE, SAME_SOURCE_DUPLICATE, DUPLICATE_EXACT, DUPLICATE_NORMALIZED); `DeduplicationDecision` frozen dataclass; `CorroborationPolicy.classify(jaccard, same_source)`; `Article` from Avro dict; `CanonicalDocument` with UUIDv7 |
| T-B-1-02 | Database models + repositories | impl | `infrastructure/db/session.py`, `infrastructure/db/models.py`, `infrastructure/db/repositories/document.py`, `infrastructure/db/repositories/dedup.py`, `infrastructure/db/repositories/minhash.py`, `infrastructure/db/repositories/outbox.py` | ORM models per PRD §6.4.2: `documents` (with `corroborates_doc_id`, `dedup_result`, `is_backfill`, content_hash UNIQUE), `dedup_hashes` (UNIQUE on hash_type+hash_value), `duplicate_clusters` (UNIQUE on primary+duplicate), `minhash_signatures` (signature `INTEGER[]` — CRITICAL: not BYTEA, doc_id UNIQUE), `minhash_entity_mentions` (entity_id UUID — NO FK constraint, PK on sig_id+mention_text_hash), `outbox_events`, `dead_letter_queue`; 4 repos: Document (create, query), DedupHash (check_exists, insert), MinHash (create_signature, get_signature), Outbox (append, fetch_pending, mark_dispatched) |
| T-B-1-03 | Alembic migration | schema | `alembic/`, `alembic/versions/0001_initial_s5_schema.py` | Creates all 7 tables (documents, dedup_hashes, duplicate_clusters, minhash_signatures, minhash_entity_mentions, outbox_events, dead_letter_queue); `signature` column is `INTEGER[]` (not BYTEA); `entity_id` has NO FK constraint; indexes per PRD §6.4.2; matches ORM exactly (guard BP-008) |
| T-B-1-04 | Unit tests for S5 foundation | test | `tests/unit/domain/`, `tests/unit/infrastructure/` | ≥15 tests: CorroborationPolicy threshold logic, DeduplicationDecision frozen, Article from Avro dict, repo CRUD, exists checks, signature stored as list[int], entity_mention no FK |

#### Pre-Read
- `services/content-ingestion/src/content_ingestion/infrastructure/db/` — reference from Wave A-1

#### Validation Gate
- [ ] `ruff check services/content-store/` passes
- [ ] `mypy services/content-store/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-store/tests/unit -v` — ≥15 tests pass
- [ ] `alembic upgrade head` succeeds; `signature` column confirmed as `INTEGER[]`
- [ ] `docs/services/content-store.md` updated with domain entities, schema (PROMINENT: INTEGER[], NO FK)

#### Regression Guardrails
- BP-007: Unique indexes with NULLs — use `NULLS NOT DISTINCT` where needed
- BP-008: Migration matches ORM models exactly

---

### Wave B-2: S5 Text Cleaning + 3-Tier Deduplication

**Goal**: Implement the complete dedup pipeline: text extraction/cleaning (4 content types), Stage A (raw SHA-256), Stage B (normalized hash), MinHash computation, and Valkey LSH lookup.
**Depends on**: Wave B-1
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-2-01 | Text cleaner | impl | `application/text_cleaning/cleaner.py` | `extract(raw_bytes, content_type)` handles HTML (readability-lxml), XML (bleach strip), JSON (recursive field extraction), plain text (UTF-8 decode); `sanitize(html)` keeps safe tags only; `normalize(text)` NFC + strip zero-width chars + collapse whitespace; `clean()` full pipeline |
| T-B-2-02 | Stage A raw hash + Stage B normalized hash | impl | `application/deduplication/stage_a_raw.py`, `application/deduplication/stage_b_normalized.py` | Stage A: sha256(raw_bytes), check exists_by_raw_sha256; Stage B: normalize_url (strip UTM, sort params, lowercase), sha256(normalized_url + "\|" + cleaned_text.lower()), check exists_by_normalized_hash |
| T-B-2-03 | MinHash computation | impl | `application/deduplication/minhash_compute.py` | `normalize_financial_text()` per PRD §6.7 Block 2: NFC normalization, lowercase, strip punctuation, collapse whitespace, remove FINANCIAL_STOPWORDS + tokens ≤ 1 char; `compute_shingles()`: word bigrams `w:{t1}_{t2}` + char trigrams `c:{t[i:i+3]}` (union); `compute_minhash(text, num_perm=128) -> list[int]` using datasketch; CRITICAL: returns `list[int]` not numpy array (type(result[0]) is int assertion mandatory) |
| T-B-2-04 | Valkey LSH two-tier lookup | impl | `infrastructure/valkey/lsh_client.py` | 4 bands × 32 rows; band hash via MD5; Valkey sorted sets with Unix timestamp score; `query()` returns DeduplicationDecision; `index()` adds to 4 bands with TTL per source type (NEWS=7d, FILINGS=180d, TRANSCRIPTS=60d, RESEARCH=30d, PRESS_RELEASE=14d — PRD §6.7 Block 2); Tier 2 exact Jaccard with per-source thresholds: NEWS hard=0.72/soft=0.55, FILINGS hard=0.85/soft=0.70, etc.; corroborating = different source + hard threshold match → BOTH retained |
| T-B-2-05 | Unit tests for cleaning + dedup | test | `tests/unit/application/` | ≥30 tests: text extraction (4 content types), normalization, URL normalization (UTM strip, sort, lowercase), Stage A/B exact/unique decisions, MinHash list[int] type assertion + length=128 + identical/different/similar texts, LSH band hash determinism + Jaccard thresholds + TTL per source |

#### Pre-Read
- `libs/messaging/src/messaging/valkey/` — ValkeyClient reference

#### Validation Gate
- [ ] `ruff check services/content-store/` passes
- [ ] `mypy services/content-store/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-store/tests/unit -v` — all tests pass (≥45 total)
- [ ] `compute_minhash()` return type verified as `list[int]` (not numpy)
- [ ] `docs/services/content-store.md` updated with dedup flowchart (Mermaid), text cleaning content types, MinHash/LSH parameters

#### Regression Guardrails
- BP-001: Ensure dedup decision metadata compatible with outbox serialization
- Custom: MinHash `list[int]` not numpy — type assertion in unit test mandatory

---

### Wave B-3: S5 Canonical Write Pipeline + Kafka Consumer + Outbox

**Goal**: Implement the complete S5 hot path: ProcessArticleUseCase orchestrating clean → dedup → MinIO silver write → atomic DB transaction → Valkey LSH index; Kafka consumer for `content.article.raw.v1`; outbox dispatcher for `content.article.stored.v1`.
**Depends on**: Wave B-2
**Estimated effort**: 60–75 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-3-01 | MinIO silver adapter | impl | `infrastructure/storage/minio_silver.py` | Key pattern `content-store/canonical/{doc_id}/body.json`; `put_canonical(doc, cleaned_text)` writes JSON payload (metadata + cleaned_text); uses `libs/storage` S3ObjectStorage |
| T-B-3-02 | ProcessArticleUseCase | impl | `application/use_cases/process_article.py` | `execute(article) -> ProcessingSummary`: fetch raw from MinIO bronze → clean → Stage A → Stage B → compute MinHash → LSH query → (if not suppressed) MinIO silver write + atomic 4-table DB transaction (documents + dedup_hashes + minhash_signatures + minhash_entity_mentions + outbox_event) → LSH index; NEVER publishes Kafka (outbox only); returns ProcessingSummary(article_id, decision, doc_id, suppressed) |
| T-B-3-03 | Kafka consumer | impl | `infrastructure/consumer/article_consumer.py` | `ArticleConsumer(BaseKafkaConsumer)`: consumes `content.article.raw.v1`, deserializes Avro, calls ProcessArticleUseCase, commits offset AFTER DB commit (at-least-once); handles rebalance, graceful shutdown; logs metrics |
| T-B-3-04 | Outbox dispatcher | impl | `infrastructure/outbox/dispatcher.py` | Polls `outbox_events`, serializes Avro `content.article.stored.v1` (doc_id, source_article_id, url, url_hash, source_type, minio_key, created_at, decision), publishes to Kafka; marks dispatched or DLQ after MAX_RETRIES; uses `OutboxEventValueSerializer` (guard BP-001) |
| T-B-3-05 | Unit tests for hot path | test | `tests/unit/application/use_cases/`, `tests/unit/infrastructure/` | ≥15 tests: ProcessArticleUseCase full round-trip, all 3 dedup stages (unique/corroborating/suppressed paths), MinIO silver key format, consumer deserialization, outbox Avro payload match |

#### Pre-Read
- `services/content-ingestion/src/content_ingestion/infrastructure/outbox/` — S4 dispatcher reference

#### Validation Gate
- [ ] `ruff check services/content-store/` passes
- [ ] `mypy services/content-store/src/ --config-file mypy.ini` passes
- [ ] `python -m pytest services/content-store/tests/unit -v` — all tests pass (≥60 total)
- [ ] Outbox pattern verified: no direct Kafka produce in use-case or consumer
- [ ] `docs/services/content-store.md` updated with canonical write pipeline, consumer topology

#### Regression Guardrails
- BP-001: OutboxEventValueSerializer for outbox dispatcher
- BP-009: DispatcherConfig derived from settings

---

### Wave B-4: S5 Observability + Integration Tests + S4→S5 Continuity

**Goal**: Complete S5 with health probes, Prometheus metrics, DLQ management, main.py wiring, and comprehensive integration tests validating the full S4→S5 pipeline end-to-end.
**Depends on**: Wave B-3 + Wave A-4 (S4 integration tests must pass)
**Estimated effort**: 60–90 minutes

#### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-B-4-01 | Health/Ready + Prometheus + DLQ + main.py | impl | `api/health.py`, `api/dlq.py`, `infrastructure/metrics/prometheus.py`, `main.py` | Health: GET /health (200), GET /ready (DB + Kafka consumer + Valkey, 503 on failure), GET /metrics; Prometheus: `s5_articles_received_total`, `s5_duplicates_suppressed_total{tier}`, `s5_canonical_written_total`, `s5_outbox_pending_total`; DLQ: list/retry/resolve with admin token; main.py: lifespan starts consumer + dispatcher + metrics poller |
| T-B-4-02 | Docker Compose test infrastructure | config | `tests/docker-compose.test.yml` | Postgres, Kafka, MinIO, Valkey (4 services); health checks; `FLUSHDB` Valkey between tests |
| T-B-4-03 | Integration test fixtures | test | `tests/integration/conftest.py` | session_factory with Alembic, minio_client, kafka_consumer, valkey_client fixtures; cleanup/isolation |
| T-B-4-04 | Integration tests — pipeline + dedup + idempotency | test | `tests/integration/test_pipeline.py`, `tests/integration/test_deduplication.py`, `tests/integration/test_idempotency.py` | Pipeline: seed MinIO bronze → produce `content.article.raw.v1` → consumer processes → assert documents row + minhash_signatures as list[int] + outbox pending → dispatcher → `content.article.stored.v1` on Kafka + MinIO silver object; Dedup: cross-source Jaccard ≥0.80 → CORROBORATING (both written), same-source ≥0.95 → suppressed, exact URL → suppressed; Idempotency: same message twice → single canonical doc |
| T-B-4-05 | Integration test — S4→S5 continuity | test | `tests/integration/test_s4_s5_continuity.py` | End-to-end: S4 fetch → `content.article.raw.v1` → S5 consumer → canonical doc → `content.article.stored.v1`; validates contract between S4 and S5 |
| T-B-4-06 | Unit tests for observability | test | `tests/unit/api/` | ≥10 tests: health always 200, ready checks (DB/Kafka/Valkey), metrics endpoint, DLQ auth/list/retry/resolve, metrics counters increment |

#### Pre-Read
- `services/content-ingestion/tests/integration/` — S4 integration test reference

#### Validation Gate
- [ ] `python -m pytest services/content-store/tests/integration -v -m integration` — all integration tests pass
- [ ] `python -m pytest services/content-store/tests/unit -v` — all unit tests pass (≥70 total)
- [ ] `ruff check` + `mypy` clean across both S4 and S5
- [ ] S4→S5 continuity test confirms full pipeline: raw article → MinIO bronze → outbox → Kafka → S5 consumer → canonical doc → MinIO silver → outbox → Kafka
- [ ] `docs/services/content-store.md` updated with observability, integration test coverage

#### Regression Guardrails
- BP-003: Async fixture teardown — asyncio_mode=auto, scope carefully
- BP-004: @pytest.mark.integration for conditional skip
- BP-010: Docker health checks before test execution
- Custom: Verify `minhash_signatures.signature` stored as `INTEGER[]` in actual DB

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Compatibility | Test |
|------|------|--------------|------|
| Avro | `content.article.raw.v1.avsc` | Forward-compatible | T-A-1-06 (Avro roundtrip), T-A-4-03 (integration) |
| Avro | `content.article.stored.v1.avsc` | Forward-compatible | T-B-3-05 (Avro roundtrip), T-B-4-04 (integration) |
| Avro | `market.instrument.created.avsc` | **Enhanced** (3 new nullable fields: name, description, isin) — BACKWARD compatible | PLAN-0001-A T-0001A-1-02 |
| REST | S4 Admin API (5 endpoints) + internal submit | New service | T-A-3-06 (unit), T-A-4-04 (integration) |

### Migrations
| Service | Migration | Description | Order |
|---------|-----------|-------------|-------|
| content-ingestion | `0001_initial_s4_schema.py` | 5 tables: sources, source_adapter_state, article_fetch_log, outbox_events, dead_letter_queue | Wave A-1 |
| content-store | `0001_initial_s5_schema.py` | 7 tables: documents, dedup_hashes, duplicate_clusters, minhash_signatures, minhash_entity_mentions, outbox_events, dead_letter_queue | Wave B-1 |

### Note on S3 Enhancement
S3 (Market Data) needs a minor change to populate `name`, `description`, `isin` from `company_profiles` when publishing `market.instrument.created` events. This is a localized change in S3's instrument materialization code. The Avro schema enhancement is handled by PLAN-0001-A Wave 1 (T-0001A-1-02).

### Configuration
| Service | Env Var | Default | Purpose |
|---------|---------|---------|---------|
| S4 | `DATABASE_URL` | — | content_ingestion_db connection |
| S4 | `EODHD_API_TOKEN` | — | EODHD API key |
| S4 | `SEC_EDGAR_USER_AGENT` | — | SEC EDGAR User-Agent (required) |
| S4 | `FINNHUB_API_TOKEN` | — | Finnhub API key |
| S4 | `NEWSAPI_API_KEY` | — | NewsAPI key |
| S4 | `NEWSAPI_DAILY_LIMIT` | `100` | Daily request quota |
| S4 | `ADMIN_TOKEN` | — | X-Admin-Token for admin endpoints |
| S4 | `BACKFILL_ENABLED` | `false` | Enable backfill mode |
| S4 | `BACKFILL_FROM_DATE` | — | Backfill start date |
| S4 | `BACKFILL_TO_DATE` | — | Backfill end date |
| S4 | `SCHEDULER_INTERVAL_SECONDS` | `300` | Polling interval |
| S5 | `DATABASE_URL` | — | content_store_db connection |
| S5 | `VALKEY_URL` | — | Valkey connection for LSH |
| S5 | `MINHASH_NUM_PERM` | `128` | MinHash permutations |
| S5 | `JACCARD_HARD_THRESHOLD` | `0.95` | Same-source dedup threshold |
| S5 | `JACCARD_SOFT_THRESHOLD` | `0.80` | Near-duplicate threshold |

### Documentation Updates
| Document | Update Required |
|----------|----------------|
| `docs/services/content-ingestion.md` | Domain entities, adapters, API, scheduler, metrics, pipeline diagram |
| `docs/services/content-store.md` | Domain entities, dedup pipeline, schema (INTEGER[], NO FK), metrics |
| `services/content-ingestion/.claude-context.md` | Endpoints, topics, entities, pitfalls |
| `services/content-store/.claude-context.md` | Endpoints, topics, entities, pitfalls |

---

## Risk Assessment

### Critical Path
Sub-Plan A Wave A-1 (S4 foundation) blocks everything. Sub-Plan B cannot start consuming until S4 produces valid `content.article.raw.v1` events.

### Highest Risk
| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| MinHash signature stored as BYTEA not INTEGER[] | Medium | High — breaks S5 consumers, S6 reads | Explicit type assertion in unit test (T-B-2-05); migration review (T-B-1-03) |
| Outbox dispatcher uses wrong serializer | Medium | High — events not consumable | Guard BP-001; unit test Avro roundtrip |
| SEC EDGAR rate limiting/User-Agent rejection | Low | Medium — adapter fails silently | ConfigurationError on missing User-Agent; integration test with mock HTTP |
| Alembic migration drift from ORM | Medium | High — runtime failures | Guard BP-008; migration-ORM comparison in integration tests |

### Rollback Strategy
Each wave leaves the codebase green. If a wave fails mid-way:
1. `git stash` or `git reset` to pre-wave state
2. Fix the issue in isolation
3. Re-execute the wave from scratch
4. Sub-plans are independent — S5 failure does not affect S4

---

## Tracking

### Plan Status
| Plan | Status | Waves Done | Waves Total |
|------|--------|-----------|-------------|
| A: S4 Content Ingestion | in-progress | 1 | 4 |
| B: S5 Content Store | pending | 0 | 4 |

### Wave Status
| Wave | Status | Tasks Done | Tasks Total | Blockers |
|------|--------|-----------|-------------|----------|
| A-1 | done | 6 | 6 | none |
| A-2 | pending | 0 | 5 | A-1 |
| A-3 | pending | 0 | 6 | A-2 |
| A-4 | pending | 0 | 4 | A-3 |
| B-1 | pending | 0 | 4 | A-2 |
| B-2 | pending | 0 | 5 | B-1 |
| B-3 | pending | 0 | 5 | B-2 |
| B-4 | pending | 0 | 6 | B-3, A-4 |
