# Planning Response 0012 — Ingestion Pipeline v1: S4 Content Ingestion + S5 Content Store

**Date:** 2026-03-22
**Prompt:** `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
**Status:** Scheduled — 26 tasks across 7 waves

---

## 1. Executive Summary

This plan delivers two complete microservices:

**S4 Content Ingestion** fetches raw articles from four external sources (EODHD, SEC EDGAR, Finnhub, NewsAPI), stores raw bytes in MinIO bronze storage, writes fetch audit logs and outbox events in a single Postgres transaction, and dispatches those events to Kafka topic `content.article.raw.v1` via a dedicated outbox dispatcher. An APScheduler-based polling scheduler drives periodic ingestion with per-adapter Postgres advisory locks ensuring exactly-one-active-job semantics across replicas. An admin REST API exposes source CRUD and on-demand trigger endpoints. Prometheus metrics and a liveness/readiness endpoint complete the service.

**S5 Content Store** consumes `content.article.raw.v1`, runs a three-stage deduplication pipeline (exact raw SHA-256 → normalized URL+text hash → MinHash LSH near-duplicate detection via Valkey), writes canonical documents to MinIO silver storage plus Postgres in a single all-or-nothing transaction, and publishes `content.article.stored.v1` via its own outbox dispatcher. The dedup pipeline correctly classifies corroborating coverage (same event, different sources) versus true duplicates, enabling downstream intelligence services (S6) to receive only meaningful canonical documents.

Together, S4 and S5 form the raw-fetch → canonical-store → hand-off-to-S6 pipeline. S6 begins processing once it can consume `content.article.stored.v1` — this contract is established and validated in Wave 07.

---

## 2. Current-State vs Target-State Matrix

| Dimension | Current State | Target State after 0012 |
|-----------|--------------|------------------------|
| S4 service | Does not exist | Fully implemented: adapters, scheduler, outbox, admin API, metrics |
| S5 service | Does not exist | Fully implemented: consumer, dedup pipeline, canonical write, outbox, metrics |
| MinIO bronze | Empty | Receives `content-ingestion/{source_type}/{url_hash}/raw/v1.json` objects |
| MinIO silver | Empty | Receives `content-store/canonical/{doc_id}/body.json` objects |
| Kafka | No ingestion topics | `content.article.raw.v1` (S4 → S5), `content.article.stored.v1` (S5 → S6) live |
| Postgres | No S4/S5 schemas | `content_ingestion_db` + `content_store_db` schemas fully migrated |
| Valkey | Empty | MinHash LSH bands populated for near-dup detection |
| Observability | No S4/S5 metrics | Prometheus scrape endpoints live; liveness + readiness probes active |
| DLQ | None | Per-service DLQ tables + admin endpoints for list/retry/resolve |
| Integration tests | None | Full S4→S5 round-trip validated via docker-compose |

### Per-Service, Per-Layer Breakdown

#### S4 Content Ingestion (`services/content-ingestion/src/content_ingestion/`)

| Layer | Current | Target |
|-------|---------|--------|
| `domain/` | Empty | `Source`, `FetchResult`, `SourceType`, `RawArticle`, `TokenBucket` |
| `infrastructure/db/` | Empty | `content_ingestion_db` session, `FetchLogRepository`, `OutboxRepository`, `SourceRepository` |
| `infrastructure/adapters/` | Empty | MinIO bronze, EODHD, SEC EDGAR, Finnhub, NewsAPI adapters |
| `infrastructure/scheduler/` | Empty | APScheduler `AsyncIOScheduler` + pg advisory lock |
| `application/use_cases/` | Empty | `FetchAndWriteUseCase` |
| `api/` | Empty | Admin endpoints + health/ready + DLQ admin |
| `infrastructure/outbox/` | Empty | Outbox dispatcher (poll → Avro serialize → Kafka publish → mark done) |
| `infrastructure/metrics/` | Empty | Prometheus counters/histograms |

#### S5 Content Store (`services/content-store/src/content_store/`)

| Layer | Current | Target |
|-------|---------|--------|
| `domain/` | Empty | `Article`, `CanonicalDocument`, `DeduplicationDecision`, `DeduplicationStage`, `CorroborationPolicy` |
| `infrastructure/db/` | Empty | `content_store_db` session, `DocumentRepository`, `MinHashRepository`, `OutboxRepository` |
| `application/use_cases/` | Empty | Text cleaning, dedup stages A/B/C, MinHash, LSH lookup, canonical write |
| `infrastructure/consumer/` | Empty | Kafka consumer for `content.article.raw.v1` |
| `infrastructure/outbox/` | Empty | Outbox dispatcher for `content.article.stored.v1` |
| `api/` | Empty | Health/ready + DLQ admin endpoints |
| `infrastructure/metrics/` | Empty | Prometheus counters |

---

## 3. Dependency Graph

```
Wave 01 ─────────────────────────────────────────────────────────────┐
  T-S4-001 (domain entities)      ──┐                                │
  T-S4-002 (DB infra)              ──┼── all parallel, no deps       │
  T-S4-003 (outbox dispatcher)     ──┤                                │
  T-S4-004 (MinIO bronze adapter)  ──┘                                │
                                                                       │
Wave 02 (requires Wave 01) ────────────────────────────────────────── ┤
  T-S4-005 (EODHD adapter)     ──┐                                    │
  T-S4-006 (SEC EDGAR adapter)  ──┼── all parallel                   │
  T-S4-007 (Finnhub adapter)   ──┤                                    │
  T-S4-008 (NewsAPI adapter)   ──┘                                    │
                                                                       │
Wave 03 (requires Wave 02) ────────────────────────────────────────── ┤
  T-S4-009 (scheduler)  ──► T-S4-010 (use-case)  [sequential]       │
  T-S4-011 (admin API)  ──┐                                           │
  T-S4-012 (DLQ admin)  ──┼── parallel, require all infra            │
  T-S4-013 (health/metrics)─┘                                         │
                                                                       │
Wave 04 (requires Wave 03) ────────────────────────────────────────── ┤
  T-S4-014 (S4 integration tests)  [sequential, gates S5 build]      │
  T-S5-001 (S5 domain)   ──┐ parallel, no deps on S4 impl            │
  T-S5-002 (S5 DB infra) ──┘                                          │
                                                                       │
Wave 05 (requires Wave 04) ────────────────────────────────────────── ┤
  T-S5-003 (text cleaning)  ──┐                                       │
  T-S5-004 (dedup stage A)  ──┼── all parallel                       │
  T-S5-005 (dedup stage B)  ──┤                                       │
  T-S5-006 (MinHash)        ──┘                                       │
                                                                       │
Wave 06 (requires Wave 05) ────────────────────────────────────────── ┤
  T-S5-007 (Valkey LSH)  ──► T-S5-008 (canonical write) [sequential]│
  T-S5-009 (Kafka consumer) ──┐ parallel                              │
  T-S5-010 (outbox dispatcher)──┘                                     │
                                                                       │
Wave 07 (requires Wave 06) — FINAL ───────────────────────────────── ┘
  T-S5-011 (health/metrics/DLQ)  ──► T-S5-012 (integration tests)
```

**Parallel opportunities by wave:**
- Wave 01: 4 tasks in parallel (max parallelism = 4 agents)
- Wave 02: 4 tasks in parallel
- Wave 03: 2+3 split (T-S4-009→010 sequential; T-S4-011/012/013 parallel)
- Wave 04: T-S4-014 gates T-S5 build; T-S5-001 and T-S5-002 parallel
- Wave 05: 4 tasks in parallel
- Wave 06: T-S5-007→008 sequential; T-S5-009 and T-S5-010 parallel
- Wave 07: T-S5-011→012 sequential (observability before final tests)

---

## 4. Full Atomic Task Backlog

### T-S4-001 — Config + Domain Entities

**Objective:** Define all S4 domain entities and service configuration as the stable contract that all other S4 layers depend on.

**Paths to read:** `docs/services/content-ingestion.md`, `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/domain/__init__.py
services/content-ingestion/src/content_ingestion/domain/entities.py
services/content-ingestion/src/content_ingestion/domain/value_objects.py
services/content-ingestion/src/content_ingestion/config.py
```

**Prerequisites:** None

**Implementation steps:**
1. Create `config.py` using `pydantic-settings` `BaseSettings`; fields: `EODHD_API_KEY`, `SEC_EDGAR_USER_AGENT`, `FINNHUB_API_KEY`, `NEWSAPI_KEY`, `CONTENT_INGESTION_DB_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_OUTBOX_TOPIC` (default `content.article.raw.v1`), `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` (default `worldview-bronze`), `ADMIN_TOKEN`, `SCHEDULER_INTERVAL_SECONDS` (default 300).
2. Create `SourceType` enum: `EODHD`, `SEC_EDGAR`, `FINNHUB`, `NEWSAPI`.
3. Create `Source` dataclass: `id: UUID` (UUIDv7), `name: str`, `source_type: SourceType`, `enabled: bool`, `config: dict[str, Any]`, `created_at: datetime` (UTC TIMESTAMPTZ).
4. Create `FetchResult` dataclass: `source_id: UUID`, `url: str`, `url_hash: str` (sha256 hex), `raw_bytes: bytes`, `fetched_at: datetime`, `http_status: int`, `content_type: str`.
5. Create `RawArticle` dataclass (thin wrapper over FetchResult for domain clarity): `id: UUID` (UUIDv7), `source_type: SourceType`, `url: str`, `url_hash: str`, `raw_bytes: bytes`, `fetched_at: datetime`, `byte_size: int`.
6. Create `TokenBucket` dataclass (pure domain, no I/O): `capacity: int`, `tokens: float`, `refill_rate: float` (tokens/sec), `last_refill: datetime`. Add `consume(n: int) -> bool` method using token bucket algorithm; `wait_time() -> float` returns seconds until `n` tokens available.
7. Export all from `domain/__init__.py`.
8. Run `ruff check` and `mypy` — fix all errors before marking done.

**Tests required:**
- Unit tests for `TokenBucket.consume()` — verify deduction, refill, edge cases (n > capacity).
- Unit tests for `Source` and `FetchResult` construction with valid/invalid UUIDs.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** Update `docs/services/content-ingestion.md` domain entities section.

**DoD:** All domain entities importable, `ruff` clean, `mypy --strict` passes, unit tests green.

**Risks + mitigation:** UUIDv7 not in stdlib — use `uuid6` library; verify it is in `pyproject.toml` dependencies.

**Effort estimate:** 3h

---

### T-S4-002 — DB Infrastructure

**Objective:** Establish Postgres session factory and three repositories for S4 persistence.

**Paths to read:** `docs/services/content-ingestion.md` (schema section), `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/db/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/db/session.py
services/content-ingestion/src/content_ingestion/infrastructure/db/models.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/fetch_log.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/outbox.py
services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/source.py
services/content-ingestion/alembic/versions/0001_initial_s4_schema.py
```

**Prerequisites:** T-S4-001

**Implementation steps:**
1. Create async SQLAlchemy session factory in `session.py` using `AsyncEngine` + `async_sessionmaker`; expose `get_db_session()` async context manager.
2. Define SQLAlchemy ORM models in `models.py`:
   - `SourceModel`: `id UUID PK`, `name TEXT UNIQUE`, `source_type TEXT`, `enabled BOOL`, `config JSONB`, `created_at TIMESTAMPTZ`.
   - `FetchLogModel`: `id UUID PK`, `source_id UUID FK→sources`, `url TEXT`, `url_hash TEXT`, `http_status INT`, `byte_size INT`, `fetched_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ`. Add `UNIQUE(url_hash)` for idempotency.
   - `OutboxEventModel`: `id UUID PK`, `aggregate_type TEXT`, `aggregate_id UUID`, `event_type TEXT`, `payload JSONB`, `created_at TIMESTAMPTZ`, `dispatched_at TIMESTAMPTZ nullable`, `retry_count INT DEFAULT 0`, `status TEXT DEFAULT 'pending'`, `error TEXT nullable`.
   - `DLQEventModel`: `id UUID PK`, `original_event_id UUID`, `payload JSONB`, `error TEXT`, `created_at TIMESTAMPTZ`, `resolved_at TIMESTAMPTZ nullable`, `status TEXT DEFAULT 'open'`.
3. Implement `FetchLogRepository`: `async def create(fetch_log: FetchLog) -> None`; `async def exists_by_url_hash(url_hash: str) -> bool`.
4. Implement `OutboxRepository`: `async def append(event: OutboxEvent) -> None`; `async def fetch_pending(limit: int) -> list[OutboxEvent]`; `async def mark_dispatched(event_id: UUID) -> None`; `async def mark_failed(event_id: UUID, error: str) -> None`; `async def move_to_dlq(event_id: UUID) -> None`.
5. Implement `SourceRepository`: `async def get_all() -> list[Source]`; `async def get_by_id(source_id: UUID) -> Source | None`; `async def create(source: Source) -> None`; `async def update(source: Source) -> None`.
6. Write Alembic migration `0001_initial_s4_schema.py` covering all four tables.
7. `ruff check` + `mypy --strict` — fix all errors.

**Tests required:**
- Unit tests with `pytest-asyncio` + SQLite in-memory (or `aiosqlite`) mocking the async session for repository method correctness.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A (schema documented in service doc; update only if schema diverges).

**DoD:** Session factory + 3 repositories functional, migration file present, `ruff`/`mypy` clean, tests green.

**Risks + mitigation:** Async SQLAlchemy session leaks — ensure `async with` pattern and test teardown closes sessions.

**Effort estimate:** 4h

---

### T-S4-003 — Outbox Dispatcher

**Objective:** Background loop that polls `outbox_events`, serializes to Avro, publishes to Kafka, and marks events dispatched or failed; moves to DLQ after `max_retries`.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/outbox/dispatcher.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/avro_schema.py
services/content-ingestion/src/content_ingestion/infrastructure/outbox/__init__.py
```

**Prerequisites:** T-S4-001, T-S4-002

**Implementation steps:**
1. Define Avro schema in `avro_schema.py` for `content.article.raw.v1`: fields `article_id` (string/UUID), `source_type` (string), `url` (string), `url_hash` (string), `minio_key` (string), `fetched_at` (string/ISO-8601), `byte_size` (int). Use `fastavro` for serialization.
2. Implement `OutboxDispatcher` class in `dispatcher.py`:
   - Constructor: takes `db_session_factory`, `kafka_producer`, `settings`.
   - `async def run_once() -> None`: fetch up to `settings.OUTBOX_BATCH_SIZE` (default 100) pending events; for each: deserialize payload, Avro-serialize, produce to Kafka (await delivery confirmation), mark dispatched. On Kafka error: increment `retry_count`; if `retry_count >= settings.MAX_RETRIES` (default 3), call `move_to_dlq`; else `mark_failed`.
   - `async def run_loop() -> None`: loop `run_once()` with `asyncio.sleep(settings.OUTBOX_POLL_INTERVAL_SECONDS)` (default 5).
3. Use `aiokafka.AIOKafkaProducer` — do not import `confluent_kafka` (check pyproject.toml for which library is in use; default to `aiokafka`).
4. Wrap all DB access in try/except; log errors with `structlog` — never `print()`.
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock DB session + mock Kafka producer; assert `mark_dispatched` called on success; assert `move_to_dlq` called after `max_retries` exhausted.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A (outbox pattern documented in service doc).

**DoD:** Dispatcher runs, Avro schema correct, retry/DLQ logic tested, `ruff`/`mypy` clean.

**Risks + mitigation:** Avro schema mismatch with S5 consumer — pin schema version in both services; document in `docs/services/content-ingestion.md`.

**Effort estimate:** 4h

---

### T-S4-004 — MinIO Bronze Adapter

**Objective:** Infrastructure adapter that writes raw article bytes to MinIO under the canonical key pattern.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/storage/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py
```

**Prerequisites:** T-S4-001

**Implementation steps:**
1. Implement `MinioBronzeAdapter` in `minio_bronze.py` using `minio` Python SDK (async wrapper via `asyncio.to_thread` or use `aioboto3` — check pyproject.toml).
2. `async def put_object(article: RawArticle) -> str`: constructs key `content-ingestion/{source_type.value}/{url_hash}/raw/v1.json`; wraps raw bytes in a JSON envelope `{"url": ..., "source_type": ..., "fetched_at": ..., "raw_bytes_b64": base64(raw_bytes)}`; uploads to `settings.MINIO_BUCKET`; returns the full key.
3. `async def object_exists(url_hash: str, source_type: SourceType) -> bool`: HEAD request to check existence (used for idempotency check before write).
4. Handle `minio.S3Error` → raise domain `StorageError` (define in `domain/exceptions.py`).
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests with mocked MinIO client; assert key format, assert envelope JSON structure, assert `StorageError` raised on S3 error.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Adapter uploadable + queryable, key format matches spec, domain exception raised on failure, `ruff`/`mypy` clean.

**Risks + mitigation:** `base64` encoding of binary in JSON envelope adds ~33% size — document this; consider passing raw bytes with `application/octet-stream` content type as alternative if storage cost becomes concern.

**Effort estimate:** 2h

---

### T-S4-005 — EODHD Source Adapter

**Objective:** Fetch paginated news articles from EODHD API with sha256 URL deduplication, token-bucket rate limiting, and 3-retry logic routing failures to DLQ.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py
```

**Prerequisites:** T-S4-001 (domain), T-S4-004 (MinIO adapter interface)

**Implementation steps:**
1. Define `SourceAdapter` abstract base class in `infrastructure/adapters/base.py` (shared by all 4 adapters): `async def fetch(source: Source) -> list[FetchResult]`.
2. Implement `EodhdClient` in `client.py`: `async def get_news(api_token: str, symbol: str | None, from_date: date, to_date: date, offset: int, limit: int) -> list[dict]`; uses `aiohttp` GET to `https://eodhd.com/api/news`.
3. Implement `EodhdAdapter(SourceAdapter)` in `adapter.py`:
   - Reads `api_token`, `symbols` list, `from_date`/`to_date` from `source.config`.
   - Uses `TokenBucket` from domain for rate limiting (default 10 req/sec).
   - Paginates by incrementing `offset` until empty page or `max_pages` (default 100).
   - For each article URL: compute `sha256(url.encode()).hexdigest()` → `url_hash`; skip if already in DB (`FetchLogRepository.exists_by_url_hash`).
   - Retry loop: up to 3 attempts with exponential backoff (1s, 2s, 4s); on final failure append to DLQ via `OutboxRepository.move_to_dlq`.
   - Return `list[FetchResult]`.
4. Log fetched count, skipped count, failed count with `structlog`.
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock `EodhdClient`; assert pagination stops on empty page; assert dedup skips known url_hash; assert retry exhaustion triggers DLQ entry.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Adapter fetches paginated, deduplicates, retries, routes to DLQ. `ruff`/`mypy` clean.

**Risks + mitigation:** EODHD API rate limits vary by plan — read `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` subscription section; default to conservative 10 req/sec.

**Effort estimate:** 4h

---

### T-S4-006 — SEC EDGAR Adapter

**Objective:** Fetch SEC filings (HTML + XBRL) via EFTS search, respecting the 8 req/sec rate limit.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py
```

**Prerequisites:** T-S4-001, T-S4-004

**Implementation steps:**
1. Implement `SecEdgarClient` in `client.py`:
   - `async def search_filings(query: str, date_range: tuple[date, date], form_types: list[str], from_: int, size: int) -> dict`: POST to `https://efts.sec.gov/LATEST/search-index?q=...` (EFTS full-text search).
   - `async def get_filing_document(accession_number: str, filename: str) -> bytes`: GET from `https://www.sec.gov/Archives/edgar/...`.
   - Set `User-Agent` header to `settings.SEC_EDGAR_USER_AGENT` — required by SEC policy.
2. Implement `SecEdgarAdapter(SourceAdapter)` in `adapter.py`:
   - Rate limiter: `asyncio.Semaphore(8)` + `asyncio.sleep` to enforce 8 req/sec ceiling.
   - Paginate EFTS results; for each hit fetch primary document (HTML) and associated XBRL file if present.
   - URL deduplication via sha256 of `accession_number + filename`.
   - 3-retry loop with exponential backoff; DLQ on exhaustion.
3. Wrap raw HTML bytes in `FetchResult`; set `content_type` to `text/html` or `application/xml`.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock EFTS response; assert pagination; assert rate limiter semaphore acquired; assert DLQ on 3 failures.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Adapter fetches SEC filings, rate-limited, deduped, retried. `ruff`/`mypy` clean.

**Risks + mitigation:** SEC EDGAR blocks if User-Agent not set — enforce in `client.py` constructor, raise `ConfigurationError` if `SEC_EDGAR_USER_AGENT` is empty.

**Effort estimate:** 4h

---

### T-S4-007 — Finnhub Adapter

**Objective:** Fetch Finnhub company news and earnings call transcripts with a 55/min token bucket and minute-boundary backoff.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py
```

**Prerequisites:** T-S4-001, T-S4-004

**Implementation steps:**
1. Implement `FinnhubClient` in `client.py`:
   - `async def get_company_news(symbol: str, from_date: date, to_date: date) -> list[dict]`: GET `https://finnhub.io/api/v1/company-news`.
   - `async def get_transcripts(symbol: str) -> list[dict]`: GET `https://finnhub.io/api/v1/stock/transcripts/list`.
   - Both pass `token=settings.FINNHUB_API_KEY` query param.
2. Implement `FinnhubAdapter(SourceAdapter)` in `adapter.py`:
   - Token bucket: capacity=55, refill_rate=55/60 tokens/sec (i.e., 55 per minute).
   - On `TokenBucket.wait_time() > 0`: `asyncio.sleep` until next token available. On HTTP 429: compute seconds until start of next minute, sleep exactly that long (minute-boundary backoff).
   - Symbols list from `source.config['symbols']`.
   - URL dedup via sha256 of Finnhub `id` field (numeric article ID) for news; sha256 of transcript `id` for transcripts.
   - 3-retry + DLQ on exhaustion.
3. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock client; assert token bucket depletion triggers sleep; assert 429 triggers minute-boundary sleep; assert DLQ on 3 failures.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Adapter fetches news + transcripts, token-bucket rate-limited, 429 handled, `ruff`/`mypy` clean.

**Risks + mitigation:** Finnhub `id` field is numeric — ensure `str(id)` before sha256; document in adapter comments.

**Effort estimate:** 3h

---

### T-S4-008 — NewsAPI Adapter

**Objective:** Paginate NewsAPI `everything` endpoint with a daily Valkey quota counter that halts fetching when exhausted.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py
```

**Prerequisites:** T-S4-001, T-S4-004

**Implementation steps:**
1. Implement `NewsApiClient` in `client.py`:
   - `async def everything(query: str, from_date: date, to_date: date, page: int, page_size: int) -> dict`: GET `https://newsapi.org/v2/everything`.
   - Pass `apiKey=settings.NEWSAPI_KEY` in header (not query param — avoids logging).
2. Implement `NewsApiAdapter(SourceAdapter)` in `adapter.py`:
   - Valkey quota counter: key `newsapi:daily_requests:{YYYY-MM-DD}`; use `INCR` + `EXPIRE 86400`; if counter exceeds `settings.NEWSAPI_DAILY_LIMIT` (default 100), raise `QuotaExhaustedError` and halt (do not retry — quota is a hard daily limit).
   - Paginate until `totalResults` exhausted or `max_pages` (default 10) reached; `page_size=100`.
   - URL dedup via sha256 of article `url` field.
   - 3-retry (on non-429, non-quota errors) + DLQ on exhaustion.
3. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock Valkey + client; assert quota halt when counter ≥ limit; assert pagination; assert DLQ on 3 non-quota failures.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Adapter paginates NewsAPI, enforces daily quota via Valkey, halts cleanly on exhaustion, `ruff`/`mypy` clean.

**Risks + mitigation:** NewsAPI free tier limited to 100 requests/day — `NEWSAPI_DAILY_LIMIT` must be configurable; ensure quota check happens before each page request.

**Effort estimate:** 3h

---

### T-S4-009 — APScheduler Polling Scheduler

**Objective:** Schedule periodic ingestion jobs per enabled source, using Postgres advisory locks to prevent concurrent runs of the same adapter across replicas.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler.py
services/content-ingestion/src/content_ingestion/infrastructure/scheduler/advisory_lock.py
```

**Prerequisites:** T-S4-001–T-S4-008

**Implementation steps:**
1. Implement `advisory_lock.py`: async context manager `pg_advisory_lock(conn, lock_key: int)` using `SELECT pg_try_advisory_lock($1)` → if False, skip (don't wait); release with `pg_advisory_unlock($1)` on exit.
2. Implement `IngestionScheduler` in `scheduler.py`:
   - Use `apscheduler.schedulers.asyncio.AsyncIOScheduler`.
   - On startup: query `SourceRepository.get_all()` → filter `enabled=True` → for each source create an `IntervalTrigger(seconds=settings.SCHEDULER_INTERVAL_SECONDS)` job calling `_run_adapter(source)`.
   - `_run_adapter(source)`: acquire pg advisory lock keyed by `hash(source.name) % 2^31`; if acquired: instantiate correct adapter → call `FetchAndWriteUseCase.execute(source)` → release lock; if not acquired: log skip + return.
   - Handle adapter factory by mapping `SourceType` → adapter class.
3. Start scheduler in FastAPI lifespan event; stop on shutdown.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock `SourceRepository` + advisory lock; assert job created per enabled source; assert skipped when lock not acquired.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** Scheduler starts/stops cleanly, advisory lock prevents duplicate runs, `ruff`/`mypy` clean.

**Risks + mitigation:** APScheduler job store defaults to in-memory — ensure no `SQLAlchemyJobStore` is used (would require extra table); use `MemoryJobStore` + advisory lock for distributed coordination.

**Effort estimate:** 4h

---

### T-S4-010 — Fetch + Write Application Use-Case

**Objective:** Orchestrate adapter fetch → MinIO write → single DB transaction (fetch_log + outbox_events).

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/application/__init__.py
services/content-ingestion/src/content_ingestion/application/use_cases/__init__.py
services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py
```

**Prerequisites:** T-S4-009 (scheduler context), T-S4-001–T-S4-008

**Implementation steps:**
1. Implement `FetchAndWriteUseCase`:
   - Constructor: takes `adapter: SourceAdapter`, `minio: MinioBronzeAdapter`, `fetch_log_repo: FetchLogRepository`, `outbox_repo: OutboxRepository`, `session_factory`.
   - `async def execute(source: Source) -> FetchSummary`:
     a. Call `adapter.fetch(source)` → `list[FetchResult]`.
     b. For each `FetchResult`:
        - Skip if `fetch_log_repo.exists_by_url_hash(result.url_hash)` (idempotency).
        - Call `minio.put_object(article)` → `minio_key`.
        - Open single DB transaction: `INSERT fetch_log` + `INSERT outbox_event` (payload includes `minio_key`, `source_type`, `url`, `url_hash`, `fetched_at`, `byte_size`) → commit.
        - On any error: rollback transaction; log with structlog; continue to next article (don't abort entire batch).
     c. Return `FetchSummary(source_id, fetched=N, skipped=M, failed=K, duration_seconds=T)`.
2. The outbox event payload is a JSON dict matching the Avro schema fields in T-S4-003.
3. Never publish to Kafka directly inside this use-case — outbox dispatcher handles that.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock adapter returning 3 results; assert MinIO called 3 times; assert DB transaction called 3 times; assert 1 skip on duplicate url_hash; assert rollback on DB error without aborting remaining articles.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** Update `docs/services/content-ingestion.md` use-case flow section with `FetchAndWriteUseCase` description.

**DoD:** Use-case orchestrates full fetch→write flow atomically, idempotent, `ruff`/`mypy` clean, tests green.

**Risks + mitigation:** MinIO write before DB transaction — if DB commit fails, orphan MinIO object exists but won't be dispatched; on retry the idempotency check will skip the url_hash (already in fetch_log from DB commit failure? No — if DB commit fails, fetch_log not written → next run will re-fetch and re-write MinIO). The MinIO overwrite is idempotent (same key, same content) so this is acceptable.

**Effort estimate:** 3h

---

### T-S4-011 — Admin API

**Objective:** REST endpoints for source management and on-demand ingestion trigger.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/api/__init__.py
services/content-ingestion/src/content_ingestion/api/admin.py
services/content-ingestion/src/content_ingestion/api/dependencies.py
services/content-ingestion/src/content_ingestion/api/schemas.py
services/content-ingestion/src/content_ingestion/main.py
```

**Prerequisites:** T-S4-001–T-S4-010

**Implementation steps:**
1. Create `main.py` with FastAPI app, lifespan (start/stop scheduler + outbox dispatcher), include routers.
2. Create `dependencies.py`: `verify_admin_token(x_admin_token: str = Header(...))` dependency that raises `HTTPException(403)` if token != `settings.ADMIN_TOKEN`.
3. Create `schemas.py`: Pydantic models `SourceCreate`, `SourceUpdate`, `SourceResponse`, `IngestTriggerRequest`, `IngestStatusResponse`, `FetchSummaryResponse`.
4. Implement admin router in `admin.py`:
   - `GET /api/v1/sources` → list all sources.
   - `POST /api/v1/sources` → create source (validate `source_type` enum).
   - `PUT /api/v1/sources/{source_id}` → update source (enable/disable, config).
   - `POST /api/v1/ingest/trigger` → body `{source_id: UUID}`; immediately runs `FetchAndWriteUseCase` for that source; returns `FetchSummaryResponse`.
   - `GET /api/v1/ingest/status` → returns last fetch summary per source (from fetch_log aggregate query).
   - All endpoints require `Depends(verify_admin_token)`.
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests with FastAPI `TestClient`; assert 403 on missing/wrong token; assert 200 + correct response shape on valid requests; assert `source_type` validation rejects invalid values.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A (API spec documented in service doc).

**DoD:** All 5 endpoints functional, auth enforced, `ruff`/`mypy` clean, tests green.

**Risks + mitigation:** `POST /api/v1/ingest/trigger` is synchronous — may time out for large fetches. Document in API response that callers should use async job pattern for production; for now synchronous is acceptable for admin use.

**Effort estimate:** 4h

---

### T-S4-012 — DLQ Admin Endpoints

**Objective:** Admin endpoints to list, retry, and resolve DLQ entries.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/api/dlq.py
```

**Prerequisites:** T-S4-002 (DLQEventModel), T-S4-011 (admin pattern)

**Implementation steps:**
1. Implement `DLQRepository` in `infrastructure/db/repositories/dlq.py`: `async def list_open() -> list[DLQEvent]`; `async def get_by_id(id: UUID) -> DLQEvent | None`; `async def mark_resolved(id: UUID) -> None`; `async def requeue(id: UUID) -> None` (copies payload back to `outbox_events` with `retry_count=0`).
2. Implement DLQ router in `api/dlq.py`:
   - `GET /admin/dlq` → list all open DLQ entries (paginated, default `limit=50`).
   - `POST /admin/dlq/{event_id}/retry` → requeue event (calls `DLQRepository.requeue`).
   - `POST /admin/dlq/{event_id}/resolve` → mark resolved (calls `DLQRepository.mark_resolved`).
   - All require `Depends(verify_admin_token)`.
3. Register DLQ router in `main.py`.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert list returns open entries; assert retry requeus to outbox; assert resolve updates status.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** N/A.

**DoD:** DLQ endpoints operational, `ruff`/`mypy` clean, tests green.

**Risks + mitigation:** Requeue without rate limiting could re-flood the outbox — add optional `delay_seconds` parameter to `requeue` for graduated backoff.

**Effort estimate:** 2h

---

### T-S4-013 — Health/Ready + Prometheus Metrics

**Objective:** Liveness/readiness probes and Prometheus metrics for S4.

**Paths to create:**
```
services/content-ingestion/src/content_ingestion/api/health.py
services/content-ingestion/src/content_ingestion/infrastructure/metrics/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/metrics/prometheus.py
```

**Prerequisites:** T-S4-001–T-S4-012

**Implementation steps:**
1. Define Prometheus metrics in `prometheus.py` using `prometheus_client`:
   - `s4_fetches_total`: Counter, labels `source` (source name), `status` (`success`/`failure`/`skipped`).
   - `s4_fetch_duration_seconds`: Histogram, labels `source`.
   - `s4_outbox_pending_total`: Gauge (polled from DB count of pending outbox events).
2. Implement `health.py` router:
   - `GET /health` → always 200 `{"status": "ok"}` (liveness — just process alive).
   - `GET /ready` → check DB connection (simple `SELECT 1`), check Kafka producer connected, check MinIO bucket accessible; return 200 if all pass, 503 with failing component list otherwise.
   - `GET /metrics` → `prometheus_client.generate_latest()` with `text/plain; version=0.0.4` content type.
3. Instrument `FetchAndWriteUseCase.execute()` to increment `s4_fetches_total` and observe `s4_fetch_duration_seconds`.
4. Start background task in lifespan to poll outbox pending count every 30s for `s4_outbox_pending_total`.
5. Register health router in `main.py` — no auth required.
6. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock DB/Kafka/MinIO; assert `/health` always 200; assert `/ready` returns 503 with correct failing component when DB unreachable; assert metrics endpoint returns valid Prometheus text.
- Run: `cd services/content-ingestion && make test`

**Docs updates:** Update `docs/services/content-ingestion.md` observability section.

**DoD:** Probes + metrics functional, `ruff`/`mypy` clean, tests green.

**Effort estimate:** 3h

**Risks + mitigation:** `s4_outbox_pending_total` gauge polling frequency adds DB load — 30s interval is acceptable; make configurable via `OUTBOX_METRICS_POLL_SECONDS`.

---

### T-S4-014 — S4 Integration Tests

**Objective:** Validate full S4 pipeline (adapter → MinIO → Postgres → Kafka) end-to-end using real infrastructure via docker-compose.

**Paths to create:**
```
services/content-ingestion/tests/integration/__init__.py
services/content-ingestion/tests/integration/test_eodhd_adapter_pipeline.py
services/content-ingestion/tests/integration/test_outbox_dispatcher.py
services/content-ingestion/tests/integration/test_admin_api.py
services/content-ingestion/tests/integration/test_idempotency.py
services/content-ingestion/docker-compose.test.yml
```

**Prerequisites:** T-S4-001–T-S4-013 complete

**Implementation steps:**
1. Write `docker-compose.test.yml` with services: `postgres:16`, `kafka` (bitnami/kafka), `minio`, using test-only credentials.
2. `test_eodhd_adapter_pipeline.py` (`pytest.mark.integration`):
   - Mock EODHD HTTP endpoint with `respx` or `pytest-httpx`.
   - Call `FetchAndWriteUseCase.execute(source)`.
   - Assert MinIO object exists at expected key.
   - Assert `fetch_log` row written to Postgres.
   - Assert `outbox_events` row written with `status='pending'`.
3. `test_outbox_dispatcher.py`:
   - Seed one pending outbox_event.
   - Run `OutboxDispatcher.run_once()`.
   - Assert Kafka message received on `content.article.raw.v1`.
   - Assert outbox_event `status='dispatched'`.
4. `test_admin_api.py`:
   - POST `/api/v1/sources` → assert 201.
   - GET `/api/v1/sources` → assert source in list.
   - POST `/api/v1/ingest/trigger` with `source_id` → assert 200 + summary.
5. `test_idempotency.py`:
   - Call `FetchAndWriteUseCase.execute(source)` twice with same mock response.
   - Assert `fetch_log` has exactly 1 row (second run skipped duplicate url_hash).
   - Assert `outbox_events` has exactly 1 row.
6. Run: `cd services/content-ingestion && make test-integration`

**Docs updates:** Update `docs/services/content-ingestion.md` testing section.

**DoD:** All integration tests pass against real Postgres + MinIO + Kafka; idempotency confirmed; no Kafka direct-publish violations.

**Risks + mitigation:** Docker-compose test environment cold start time — add `healthcheck` + `depends_on` condition `service_healthy` for all services in compose file.

**Effort estimate:** 6h

---

### T-S5-001 — S5 Config + Domain Entities

**Objective:** Define all S5 domain entities as the stable contract for the content store service.

**Paths to create:**
```
services/content-store/src/content_store/domain/__init__.py
services/content-store/src/content_store/domain/entities.py
services/content-store/src/content_store/domain/value_objects.py
services/content-store/src/content_store/domain/exceptions.py
services/content-store/src/content_store/config.py
```

**Prerequisites:** None (parallel with T-S4-014)

**Implementation steps:**
1. Create `config.py` (`pydantic-settings`): `CONTENT_STORE_DB_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_INPUT_TOPIC` (default `content.article.raw.v1`), `KAFKA_OUTPUT_TOPIC` (default `content.article.stored.v1`), `KAFKA_CONSUMER_GROUP` (default `content-store-group`), `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_BRONZE` (default `worldview-bronze`), `MINIO_BUCKET_SILVER` (default `worldview-silver`), `VALKEY_URL`, `ADMIN_TOKEN`.
2. Create `DeduplicationStage` enum: `EXACT_RAW`, `EXACT_NORMALIZED`, `NEAR_DUPLICATE`.
3. Create `DeduplicationDecision` dataclass: `stage: DeduplicationStage`, `is_duplicate: bool`, `similarity_score: float | None`, `existing_doc_id: UUID | None`, `decision: str` (e.g., `"SAME_SOURCE_DUPLICATE"`, `"CORROBORATING"`, `"UNIQUE"`).
4. Create `CorroborationPolicy` dataclass: `jaccard_hard_threshold: float` (default 0.95, → SAME_SOURCE_DUPLICATE), `jaccard_soft_threshold: float` (default 0.80, → CORROBORATING), `source_type_aware: bool` (different source_types at 0.80–0.95 → CORROBORATING, not suppressed).
5. Create `Article` dataclass: `id: UUID`, `source_type: str`, `url: str`, `url_hash: str`, `minio_bronze_key: str`, `fetched_at: datetime`, `byte_size: int`. (Deserialized from Kafka Avro message.)
6. Create `CanonicalDocument` dataclass: `id: UUID` (UUIDv7), `source_article_id: UUID`, `url: str`, `url_hash: str`, `normalized_text_hash: str`, `raw_sha256: str`, `minio_silver_key: str`, `source_type: str`, `created_at: datetime`.
7. Define domain exceptions: `DeduplicationError`, `StorageError`, `ConsumerError`.
8. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests for `CorroborationPolicy` threshold logic; assert SAME_SOURCE_DUPLICATE at ≥0.95, CORROBORATING at 0.80–0.95 cross-source.
- Run: `cd services/content-store && make test`

**Docs updates:** Update `docs/services/content-store.md` domain section.

**DoD:** All entities importable, `ruff`/`mypy` clean, tests green.

**Effort estimate:** 3h

---

### T-S5-002 — S5 DB Infrastructure

**Objective:** Async SQLAlchemy session factory and three repositories for the content store database.

**Paths to create:**
```
services/content-store/src/content_store/infrastructure/db/__init__.py
services/content-store/src/content_store/infrastructure/db/session.py
services/content-store/src/content_store/infrastructure/db/models.py
services/content-store/src/content_store/infrastructure/db/repositories/document.py
services/content-store/src/content_store/infrastructure/db/repositories/minhash.py
services/content-store/src/content_store/infrastructure/db/repositories/outbox.py
services/content-store/alembic/versions/0001_initial_s5_schema.py
```

**Prerequisites:** T-S5-001

**Implementation steps:**
1. Create async session factory (same pattern as T-S4-002).
2. Define ORM models:
   - `DeduplicationHashModel`: `id UUID PK`, `hash_value TEXT`, `hash_type TEXT` (`raw_sha256` or `normalized_sha256`), `doc_id UUID FK→documents`, `created_at TIMESTAMPTZ`. `UNIQUE(hash_value, hash_type)`.
   - `DocumentModel`: `id UUID PK`, `source_article_id UUID`, `url TEXT`, `url_hash TEXT UNIQUE`, `normalized_text_hash TEXT UNIQUE`, `raw_sha256 TEXT`, `minio_silver_key TEXT`, `source_type TEXT`, `created_at TIMESTAMPTZ`.
   - `MinHashSignatureModel`: `id UUID PK`, `doc_id UUID FK→documents`, `signature INTEGER[]`, `num_perm INT`, `created_at TIMESTAMPTZ`. `UNIQUE(doc_id)`.
   - `MinHashEntityMentionModel`: `id UUID PK`, `doc_id UUID FK→documents`, `entity_id UUID` (logical FK only — NO Postgres FK constraint), `entity_type TEXT`, `created_at TIMESTAMPTZ`.
   - `OutboxEventModel`: same schema as S4 outbox (copy, not import).
3. Implement `DocumentRepository`: `async def create(doc: CanonicalDocument) -> None`; `async def exists_by_raw_sha256(hash: str) -> bool`; `async def exists_by_normalized_hash(hash: str) -> bool`; `async def get_by_id(id: UUID) -> CanonicalDocument | None`.
4. Implement `MinHashRepository`: `async def create_signature(doc_id: UUID, signature: list[int]) -> None`; `async def get_signature(doc_id: UUID) -> list[int] | None`.
5. Implement `OutboxRepository` (same interface as S4, different session).
6. Write Alembic migration `0001_initial_s5_schema.py`.
7. CRITICAL: `minhash_signatures.signature` MUST be `INTEGER[]` — never `BYTEA`.
8. CRITICAL: `minhash_entity_mentions.entity_id` has NO Postgres FK constraint (cross-DB logical FK only).
9. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests for all repository methods (mock async session).
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Session factory + 3 repos functional, migration correct, `ruff`/`mypy` clean.

**Risks + mitigation:** `INTEGER[]` Postgres type maps to `ARRAY(Integer())` in SQLAlchemy — test this mapping explicitly in unit tests.

**Effort estimate:** 4h

---

### T-S5-003 — Text Cleaning

**Objective:** Extract clean text from raw HTML/XBRL bytes using readability-lxml, sanitize with bleach, normalize encoding.

**Paths to create:**
```
services/content-store/src/content_store/application/__init__.py
services/content-store/src/content_store/application/text_cleaning/__init__.py
services/content-store/src/content_store/application/text_cleaning/cleaner.py
```

**Prerequisites:** T-S5-001, T-S5-002

**Implementation steps:**
1. Implement `TextCleaner` in `cleaner.py`:
   - `def extract(raw_bytes: bytes, content_type: str) -> str`:
     a. If `text/html` or `application/xhtml+xml`: use `readability.Document(raw_bytes.decode('utf-8', errors='replace'))` → `.summary()` to extract main content.
     b. If `application/xml` (XBRL): strip XML tags with `bleach.clean(text, tags=[], strip=True)`.
     c. Fallback: `raw_bytes.decode('utf-8', errors='replace')`.
   - `def sanitize(html: str) -> str`: `bleach.clean(html, tags=ALLOWED_TAGS, strip=True)` where `ALLOWED_TAGS = ['p', 'b', 'i', 'ul', 'li', 'h1', 'h2', 'h3']`.
   - `def normalize(text: str) -> str`: `unicodedata.normalize('NFC', text)`; strip null bytes (`\x00`); strip zero-width chars (`\u200b`, `\ufeff`, `\u00ad`); collapse whitespace.
   - `def clean(raw_bytes: bytes, content_type: str) -> str`: pipeline: `extract` → `sanitize` → `normalize`.
2. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert HTML cleaning extracts body text; assert null bytes removed; assert NFC normalization applied; assert zero-width chars stripped.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Cleaner handles HTML/XML/plaintext, NFC normalized, `ruff`/`mypy` clean, tests green.

**Effort estimate:** 2h

---

### T-S5-004 — Dedup Stage A — Exact Raw Hash

**Objective:** First deduplication stage: sha256 of raw_bytes, check against `dedup_hashes` table.

**Paths to create:**
```
services/content-store/src/content_store/application/deduplication/__init__.py
services/content-store/src/content_store/application/deduplication/stage_a_raw.py
```

**Prerequisites:** T-S5-001, T-S5-002

**Implementation steps:**
1. Implement `StageARawHashChecker` in `stage_a_raw.py`:
   - `async def check(article: Article, raw_bytes: bytes, doc_repo: DocumentRepository) -> DeduplicationDecision`:
     a. Compute `raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()`.
     b. Call `doc_repo.exists_by_raw_sha256(raw_sha256)`.
     c. If exists: return `DeduplicationDecision(stage=EXACT_RAW, is_duplicate=True, similarity_score=1.0, decision="EXACT_DUPLICATE")`.
     d. Else: return `DeduplicationDecision(stage=EXACT_RAW, is_duplicate=False, similarity_score=None, decision="UNIQUE")`.
2. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert EXACT_DUPLICATE on known hash; assert UNIQUE on unknown hash.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Stage A correctly detects exact duplicates, `ruff`/`mypy` clean.

**Effort estimate:** 1h

---

### T-S5-005 — Dedup Stage B — Normalized Hash

**Objective:** Second deduplication stage: URL normalization + lowercased text hash, check against `dedup_hashes`.

**Paths to create:**
```
services/content-store/src/content_store/application/deduplication/stage_b_normalized.py
```

**Prerequisites:** T-S5-001, T-S5-002, T-S5-003

**Implementation steps:**
1. Implement `StageBNormalizedHashChecker` in `stage_b_normalized.py`:
   - `def normalize_url(url: str) -> str`: parse with `urllib.parse.urlparse`; strip UTM params (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`); sort remaining query params; reconstruct; lowercase scheme + netloc; strip trailing slash.
   - `def compute_normalized_hash(cleaned_text: str, normalized_url: str) -> str`: `hashlib.sha256((normalized_url + "|" + cleaned_text.lower()).encode()).hexdigest()`.
   - `async def check(article: Article, cleaned_text: str, doc_repo: DocumentRepository) -> tuple[DeduplicationDecision, str]`: compute normalized hash; check `doc_repo.exists_by_normalized_hash(hash)`; return decision + hash.
   - If duplicate: return `DeduplicationDecision(stage=EXACT_NORMALIZED, is_duplicate=True, similarity_score=1.0, decision="NORMALIZED_DUPLICATE")`.
2. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert UTM params stripped; assert normalized URL lowercase; assert NORMALIZED_DUPLICATE on known hash; assert UNIQUE on unknown.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Stage B strips UTM, normalizes URL, detects normalized duplicates. `ruff`/`mypy` clean.

**Effort estimate:** 2h

---

### T-S5-006 — MinHash Computation

**Objective:** Compute MinHash signatures for near-duplicate detection using datasketch, with financial-text-aware shingling.

**Paths to create:**
```
services/content-store/src/content_store/application/deduplication/minhash_compute.py
```

**Prerequisites:** T-S5-001, T-S5-003

**Implementation steps:**
1. Implement `normalize_financial_text(text: str) -> str` in `minhash_compute.py`:
   - Replace ticker patterns (`$AAPL`, `AAPL.US`) with `TICKER_TOKEN`.
   - Replace currency amounts (`$1.2B`, `€500M`) with `AMOUNT_TOKEN`.
   - Replace percentages (`+12.5%`, `-3.2%`) with `PCT_TOKEN`.
   - Replace ISO dates (`2025-01-15`, `Jan 15, 2025`) with `DATE_TOKEN`.
   - Lowercase; strip punctuation (keep alphanumeric + space).
2. Implement `compute_minhash(text: str, num_perm: int = 128) -> list[int]`:
   - Normalize: `normalize_financial_text(text)`.
   - Generate shingles: word bigrams (sliding window over tokens) UNION char 3-grams over the normalized text.
   - Create `datasketch.MinHash(num_perm=num_perm)`; call `.update(shingle.encode('utf-8'))` for each shingle.
   - Return `list(minhash.hashvalues)` — this is `list[int]` of length `num_perm`.
3. CRITICAL: return type is `list[int]` — not bytes, not numpy array.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert `compute_minhash` returns `list[int]` of length 128; assert two identical texts produce identical signatures; assert two very different texts produce low Jaccard estimate; assert financial normalization replaces tokens.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** MinHash computed as `list[int]`, financial normalization applied, `ruff`/`mypy` clean.

**Risks + mitigation:** `datasketch.MinHash.hashvalues` is a numpy array — wrap with `list(int(v) for v in minhash.hashvalues)` to ensure pure Python `list[int]`.

**Effort estimate:** 3h

---

### T-S5-007 — Valkey LSH Two-Tier

**Objective:** Implement 4-band LSH lookup in Valkey for near-duplicate detection, computing Jaccard in-process, applying hard/soft thresholds.

**Paths to create:**
```
services/content-store/src/content_store/application/deduplication/lsh_valkey.py
services/content-store/src/content_store/infrastructure/valkey/__init__.py
services/content-store/src/content_store/infrastructure/valkey/client.py
```

**Prerequisites:** T-S5-006 (MinHash computation)

**Implementation steps:**
1. Implement `ValkeyClient` in `infrastructure/valkey/client.py` using `redis.asyncio` (Valkey is Redis-protocol compatible): `async def zrangebyscore(key: str, min: float, max: float) -> list[str]`; `async def zadd(key: str, mapping: dict[str, float]) -> None`; `async def expire(key: str, seconds: int) -> None`.
2. Implement `ValkeyLSH` in `application/deduplication/lsh_valkey.py`:
   - `NUM_BANDS = 4`, `ROWS_PER_BAND = 32` (128 / 4 = 32 rows/band).
   - `def _band_hash(signature: list[int], band_idx: int) -> int`: hash of the 32-value band slice using `hashlib.md5(str(signature[band_idx*32:(band_idx+1)*32]).encode()).hexdigest()` → `int(hex, 16) % 2^31`.
   - `async def query(article: Article, signature: list[int], source_type_window: str, policy: CorroborationPolicy) -> DeduplicationDecision`:
     a. For each band: key = `lsh:band{i}:{_band_hash(signature, i)}`; ZRANGEBYSCORE with score window for `source_type_window` (e.g., `"finnhub:7d"`).
     b. Collect candidate `doc_id`s from all band hits; deduplicate candidate list.
     c. For each candidate: fetch stored signature from `MinHashRepository`; compute Jaccard = (number of matching hashvalues) / num_perm.
     d. Apply `CorroborationPolicy`: if Jaccard ≥ `hard_threshold` AND same source_type → `SAME_SOURCE_DUPLICATE`; if Jaccard ≥ `soft_threshold` AND different source_type → `CORROBORATING` (NOT suppressed — still written); if Jaccard ≥ `hard_threshold` AND different source_type → also `CORROBORATING`.
     e. Return best match decision.
   - `async def index(doc_id: UUID, signature: list[int], source_type: str, score: float) -> None`: for each band, ZADD to band key with score=`score` (e.g., Unix timestamp for time-window lookup); EXPIRE key to 30 days.
3. CORROBORATING articles ARE written to canonical store — they represent genuine multi-source coverage.
4. SAME_SOURCE_DUPLICATE articles are NOT written.
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock Valkey client; assert band hash computation deterministic; assert SAME_SOURCE_DUPLICATE at Jaccard=0.96, same source_type; assert CORROBORATING at Jaccard=0.85, different source_type; assert UNIQUE on no band hits.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** LSH lookup functional, threshold logic correct, CORROBORATING vs DUPLICATE distinction correct, `ruff`/`mypy` clean.

**Risks + mitigation:** Jaccard estimation by hash equality in the full signature is exact (for MinHash this is the standard estimator); document that this is an approximation with standard MinHash error bounds.

**Effort estimate:** 5h

---

### T-S5-008 — Canonical Write Pipeline

**Objective:** Write canonical document to MinIO silver + INSERT documents + minhash_signatures + minhash_entity_mentions + outbox_events in a single all-or-nothing transaction.

**Paths to create:**
```
services/content-store/src/content_store/application/use_cases/__init__.py
services/content-store/src/content_store/application/use_cases/process_article.py
services/content-store/src/content_store/infrastructure/storage/__init__.py
services/content-store/src/content_store/infrastructure/storage/minio_silver.py
```

**Prerequisites:** T-S5-003–T-S5-007

**Implementation steps:**
1. Implement `MinioSilverAdapter` in `infrastructure/storage/minio_silver.py`: `async def put_canonical(doc: CanonicalDocument, cleaned_text: str) -> str` → key pattern `content-store/canonical/{doc_id}/body.json`; payload `{"doc_id": ..., "url": ..., "cleaned_text": ..., "source_type": ..., "created_at": ...}`; return key.
2. Implement `ProcessArticleUseCase` in `application/use_cases/process_article.py`:
   - `async def execute(article: Article) -> ProcessingSummary`:
     a. Fetch raw bytes from MinIO bronze using `article.minio_bronze_key`.
     b. `TextCleaner.clean(raw_bytes, content_type)` → `cleaned_text`.
     c. Stage A: `StageARawHashChecker.check(article, raw_bytes, doc_repo)` → if EXACT_DUPLICATE: return early (no write).
     d. Stage B: `StageBNormalizedHashChecker.check(article, cleaned_text, doc_repo)` → if NORMALIZED_DUPLICATE: return early.
     e. Compute MinHash: `compute_minhash(cleaned_text)` → `signature`.
     f. Stage C (LSH): `ValkeyLSH.query(article, signature, policy)` → if SAME_SOURCE_DUPLICATE: return early.
     g. Write to MinIO silver: `minio_silver.put_canonical(doc, cleaned_text)` → `minio_key`.
     h. Single DB transaction (all-or-nothing):
        - INSERT `documents`
        - INSERT `dedup_hashes` (raw_sha256 + normalized_sha256)
        - INSERT `minhash_signatures` (signature as `INTEGER[]`)
        - INSERT `outbox_events` (payload: `doc_id`, `url`, `source_type`, `minio_silver_key`, `created_at`)
        - Commit
     i. Index in Valkey LSH: `ValkeyLSH.index(doc.id, signature, article.source_type, Unix timestamp)`.
     j. Return `ProcessingSummary(article_id=article.id, decision=decision, doc_id=doc.id)`.
   - CORROBORATING articles proceed through steps g–j (they are written — not suppressed).
3. Never publish to Kafka directly — outbox dispatcher handles.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert exact duplicate exits at stage A with no DB write; assert normalized dup exits at stage B; assert SAME_SOURCE_DUPLICATE exits at stage C; assert CORROBORATING IS written; assert DB transaction rolls back on any step h failure.
- Run: `cd services/content-store && make test`

**Docs updates:** Update `docs/services/content-store.md` canonical write pipeline section.

**DoD:** Canonical write pipeline atomic, all dedup stages chained, CORROBORATING written, `ruff`/`mypy` clean.

**Risks + mitigation:** MinIO write before DB transaction — same risk as S4; same mitigation (MinIO overwrite is idempotent, identical key + content on retry).

**Effort estimate:** 5h

---

### T-S5-009 — Kafka Consumer

**Objective:** Consume `content.article.raw.v1` messages with at-least-once delivery, manually committing offsets only after DB commit.

**Paths to create:**
```
services/content-store/src/content_store/infrastructure/consumer/__init__.py
services/content-store/src/content_store/infrastructure/consumer/article_consumer.py
```

**Prerequisites:** T-S5-001, T-S5-002

**Implementation steps:**
1. Implement `ArticleConsumer` in `article_consumer.py` using `aiokafka.AIOKafkaConsumer`:
   - `group_id = settings.KAFKA_CONSUMER_GROUP` (default `content-store-group`).
   - `enable_auto_commit = False` — manual offset commit only.
   - `auto_offset_reset = 'earliest'`.
   - `async def run() -> None`: poll loop; for each message:
     a. Avro-deserialize using `fastavro` (same schema as S4 outbox produces).
     b. Construct `Article` from deserialized payload.
     c. Call `ProcessArticleUseCase.execute(article)`.
     d. Await `consumer.commit()` — only after use-case returns (whether success or handled error).
     e. On unhandled exception: log with `structlog`; DO NOT commit (message will be redelivered).
2. Start consumer in FastAPI lifespan as `asyncio.create_task`.
3. Graceful shutdown: cancel consumer task in lifespan shutdown; await consumer `stop()`.
4. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock `AIOKafkaConsumer`; assert offset committed after successful use-case; assert offset NOT committed on exception; assert article constructed from Avro payload.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Consumer runs at-least-once, manual commit, graceful shutdown, `ruff`/`mypy` clean.

**Effort estimate:** 3h

---

### T-S5-010 — S5 Outbox Dispatcher

**Objective:** Poll `content_store_db` outbox_events, publish `content.article.stored.v1` to Kafka.

**Paths to create:**
```
services/content-store/src/content_store/infrastructure/outbox/__init__.py
services/content-store/src/content_store/infrastructure/outbox/dispatcher.py
services/content-store/src/content_store/infrastructure/outbox/avro_schema.py
```

**Prerequisites:** T-S5-002 (S5 outbox repo)

**Implementation steps:**
1. Define `content.article.stored.v1` Avro schema in `avro_schema.py`: fields `doc_id` (string), `source_type` (string), `url` (string), `minio_silver_key` (string), `created_at` (string/ISO-8601).
2. Implement `S5OutboxDispatcher` — same structure as S4 `OutboxDispatcher` (T-S4-003) but uses `content_store_db` session and publishes to `settings.KAFKA_OUTPUT_TOPIC`.
3. Max retries: 3; DLQ: `dlq_events` table in `content_store_db`.
4. Start dispatcher loop in FastAPI lifespan.
5. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: mock DB + Kafka; assert `content.article.stored.v1` published; assert DLQ after 3 retries.
- Run: `cd services/content-store && make test`

**Docs updates:** N/A.

**DoD:** Dispatcher publishes `content.article.stored.v1`, retry/DLQ correct, `ruff`/`mypy` clean.

**Effort estimate:** 3h

---

### T-S5-011 — S5 Health/Ready + Prometheus + DLQ

**Objective:** Liveness/readiness probes, Prometheus metrics, and DLQ admin endpoints for S5.

**Paths to create:**
```
services/content-store/src/content_store/api/__init__.py
services/content-store/src/content_store/api/health.py
services/content-store/src/content_store/api/dlq.py
services/content-store/src/content_store/api/dependencies.py
services/content-store/src/content_store/infrastructure/metrics/__init__.py
services/content-store/src/content_store/infrastructure/metrics/prometheus.py
services/content-store/src/content_store/main.py
```

**Prerequisites:** T-S5-001–T-S5-010

**Implementation steps:**
1. Define Prometheus metrics in `prometheus.py`:
   - `s5_articles_received_total`: Counter (incremented on each Kafka message consumed).
   - `s5_duplicates_suppressed_total`: Counter, labels `tier` (`exact_raw`, `exact_normalized`, `near_dup_same_source`).
   - `s5_canonical_written_total`: Counter (incremented on successful canonical write).
   - `s5_outbox_pending_total`: Gauge (polled from DB).
2. `GET /health`: always 200.
3. `GET /ready`: check DB + Kafka consumer connected + Valkey reachable.
4. `GET /metrics`: Prometheus text format.
5. DLQ admin endpoints (same pattern as S4 T-S4-012): `GET /admin/dlq`, `POST /admin/dlq/{id}/retry`, `POST /admin/dlq/{id}/resolve`. Require `X-Admin-Token` header.
6. Create `main.py` with FastAPI app, lifespan (start consumer + outbox dispatcher + metrics poller), include routers.
7. Instrument `ProcessArticleUseCase` to increment relevant counters at each dedup stage.
8. `ruff check` + `mypy --strict`.

**Tests required:**
- Unit tests: assert `/health` 200; assert `/ready` 503 on Valkey unreachable; assert metrics endpoint valid; assert DLQ 403 on wrong token.
- Run: `cd services/content-store && make test`

**Docs updates:** Update `docs/services/content-store.md` observability section.

**DoD:** Probes + metrics + DLQ functional, `ruff`/`mypy` clean.

**Effort estimate:** 4h

---

### T-S5-012 — S5 Integration Tests

**Objective:** End-to-end validation of `content.article.raw.v1` → canonical write → `content.article.stored.v1`; near-dup at Jaccard ≥ 0.80; idempotency; S4→S5 pipeline continuity.

**Paths to create:**
```
services/content-store/tests/integration/__init__.py
services/content-store/tests/integration/test_article_processing_pipeline.py
services/content-store/tests/integration/test_deduplication.py
services/content-store/tests/integration/test_idempotency.py
services/content-store/tests/integration/test_s4_s5_continuity.py
services/content-store/docker-compose.test.yml
```

**Prerequisites:** T-S5-001–T-S5-011 complete

**Implementation steps:**
1. Write `docker-compose.test.yml`: postgres, kafka, minio, valkey (test credentials).
2. `test_article_processing_pipeline.py` (`pytest.mark.integration`):
   - Produce one `content.article.raw.v1` message to Kafka (seeded MinIO bronze object).
   - Start `ArticleConsumer` for one message cycle.
   - Assert `documents` row created in Postgres.
   - Assert `minhash_signatures` row created with `signature` as `INTEGER[]`.
   - Assert `outbox_events` row created.
   - Run `S5OutboxDispatcher.run_once()`.
   - Assert `content.article.stored.v1` message on Kafka.
3. `test_deduplication.py`:
   - Produce two articles with 90% overlapping text, different `source_type` → assert both written (CORROBORATING).
   - Produce two articles with 97% overlapping text, same `source_type` → assert second suppressed (SAME_SOURCE_DUPLICATE).
   - Produce two articles with identical `url` → assert second suppressed at Stage B.
4. `test_idempotency.py`:
   - Produce the same `content.article.raw.v1` message twice (same Kafka offset, replayed).
   - Assert exactly 1 `documents` row (no duplicate).
   - Assert exactly 1 `outbox_events` row.
5. `test_s4_s5_continuity.py`:
   - Use S4 `FetchAndWriteUseCase` to produce a real outbox event.
   - Run S4 `OutboxDispatcher.run_once()` → Kafka message produced.
   - Run S5 `ArticleConsumer` one cycle → assert canonical write.
   - Assert `content.article.stored.v1` produced by S5 outbox.
6. Run: `cd services/content-store && make test-integration`

**Docs updates:** Update `docs/services/content-store.md` testing section; update `docs/services/content-ingestion.md` with S4→S5 pipeline continuity note.

**DoD:** All integration tests pass; pipeline continuity confirmed; Jaccard near-dup threshold correct; idempotency confirmed; `ruff`/`mypy` clean; service docs reflect final state.

**Risks + mitigation:** Valkey LSH state between tests — flush Valkey before each test with `FLUSHDB`; use test-namespaced keys.

**Effort estimate:** 8h

---

## 5. Milestones

| Milestone | Description | Waves | Deliverable |
|-----------|-------------|-------|-------------|
| M1 | S4 domain + infrastructure (scheduler, adapters, outbox dispatcher) | W01 + W02 + W03 (partial: T-S4-009, T-S4-010) | S4 pipeline fetches + stores raw articles + dispatches to Kafka |
| M2 | S4 API + observability (admin endpoints, DLQ, Prometheus, readiness) | W03 (partial: T-S4-011, T-S4-012, T-S4-013) | S4 service feature-complete, observable, admin-controllable |
| M3 | S5 domain + dedup pipeline (3 dedup stages, MinHash, LSH Valkey) | W04 (T-S5-001, T-S5-002) + W05 + W06 (partial: T-S5-007) | Full dedup pipeline validated with unit tests |
| M4 | S5 canonical write + outbox (MinIO silver, DB transaction, consumer) | W06 (T-S5-008, T-S5-009, T-S5-010) | S5 service writes canonical docs and dispatches `content.article.stored.v1` |
| M5 | Full S4→S5 pipeline validated end-to-end | W07 | Integration tests green; `content.article.stored.v1` flowing; pipeline ready for S6 |

---

## 6. Open Questions and Assumptions

| # | Question / Assumption | Impact | Owner |
|---|----------------------|--------|-------|
| 1 | **Assumption:** `aiokafka` is the Kafka library (not `confluent_kafka`). | If wrong, all producer/consumer code must be rewritten. | Verify in `pyproject.toml` before Wave 01. |
| 2 | **Assumption:** `minio` Python SDK (sync, wrapped with `asyncio.to_thread`) or `aioboto3` for MinIO. | Affects MinIO adapter implementation. | Verify in `pyproject.toml` before Wave 01. |
| 3 | **Open:** NewsAPI free-tier daily limit (100 req/day). If production plan allows more, `NEWSAPI_DAILY_LIMIT` must be updated. | Quota enforcement. | Product decision. |
| 4 | **Assumption:** `fastavro` used for Avro serialization (not `confluent_kafka` Schema Registry). | Schema registry integration not implemented. | If Schema Registry required, add in a future wave. |
| 5 | **Open:** Entity extraction for `minhash_entity_mentions` — which service populates `entity_id`? | `entity_id` is logical FK; table seeded by S5 only if entity extraction is in scope here. | Clarify: if S6 populates entity mentions, `minhash_entity_mentions` table may be empty after S5. For now, S5 leaves it empty and documents that S6 back-fills. |
| 6 | **Assumption:** SEC EDGAR EFTS endpoint URL is `https://efts.sec.gov/LATEST/search-index`. | Verify against SEC docs; URL has changed historically. | Verify before Wave 02. |
| 7 | **Open:** `content_type` field in `FetchResult` — how to determine for EODHD JSON responses? | EODHD returns JSON (not HTML) — need to handle `application/json` in `TextCleaner`. | Add `application/json` handling in T-S5-003 (strip JSON keys, extract text values). |
| 8 | **Assumption:** UUIDv7 available via `uuid6` library in both service `pyproject.toml` files. | If absent, must add dependency before Wave 01. | Verify and add if missing. |

---

## 7. Coverage Ledger

| task_id | assigned_wave | status | dependency_note |
|---------|--------------|--------|----------------|
| T-S4-001 | Wave 01 | scheduled | No deps |
| T-S4-002 | Wave 01 | scheduled | No deps |
| T-S4-003 | Wave 01 | scheduled | No deps |
| T-S4-004 | Wave 01 | scheduled | No deps |
| T-S4-005 | Wave 02 | scheduled | Requires T-S4-001, T-S4-004 |
| T-S4-006 | Wave 02 | scheduled | Requires T-S4-001, T-S4-004 |
| T-S4-007 | Wave 02 | scheduled | Requires T-S4-001, T-S4-004 |
| T-S4-008 | Wave 02 | scheduled | Requires T-S4-001, T-S4-004 |
| T-S4-009 | Wave 03 | scheduled | Requires T-S4-001–T-S4-008 |
| T-S4-010 | Wave 03 | scheduled | Requires T-S4-009 |
| T-S4-011 | Wave 03 | scheduled | Requires T-S4-001–T-S4-010 |
| T-S4-012 | Wave 03 | scheduled | Requires T-S4-002, T-S4-011 |
| T-S4-013 | Wave 03 | scheduled | Requires T-S4-001–T-S4-012 |
| T-S4-014 | Wave 04 | scheduled | Requires Wave 03 complete |
| T-S5-001 | Wave 04 | scheduled | No S4 impl deps (parallel with T-S4-014) |
| T-S5-002 | Wave 04 | scheduled | Requires T-S5-001 |
| T-S5-003 | Wave 05 | scheduled | Requires T-S5-001, T-S5-002 |
| T-S5-004 | Wave 05 | scheduled | Requires T-S5-001, T-S5-002 |
| T-S5-005 | Wave 05 | scheduled | Requires T-S5-001, T-S5-002, T-S5-003 |
| T-S5-006 | Wave 05 | scheduled | Requires T-S5-001, T-S5-003 |
| T-S5-007 | Wave 06 | scheduled | Requires T-S5-006 |
| T-S5-008 | Wave 06 | scheduled | Requires T-S5-003–T-S5-007 |
| T-S5-009 | Wave 06 | scheduled | Requires T-S5-001, T-S5-002 |
| T-S5-010 | Wave 06 | scheduled | Requires T-S5-002 |
| T-S5-011 | Wave 07 | scheduled | Requires T-S5-001–T-S5-010 |
| T-S5-012 | Wave 07 | scheduled | Requires T-S5-011 |

---

## 8. Summary Artifact

| Field | Value |
|-------|-------|
| Total tasks | 26 |
| Total waves | 7 |
| W_min (ceil(26/8)) | 4 |
| Actual waves | 7 |
| Justification | S4/S5 service boundary (isolation); layer coherence (domain before infra before app before api); S4 integration tests gate S5 build; dedup stages sequentially compound |
| Coverage | 26/26 tasks assigned |
| Unassigned tasks | None |
| Exact-set match | Confirmed |

**Wave-by-wave task IDs:**

| Wave | Tasks | Execution |
|------|-------|-----------|
| Wave 01 | T-S4-001, T-S4-002, T-S4-003, T-S4-004 | All parallel |
| Wave 02 | T-S4-005, T-S4-006, T-S4-007, T-S4-008 | All parallel |
| Wave 03 | T-S4-009→T-S4-010 (sequential), T-S4-011, T-S4-012, T-S4-013 (parallel) | Mixed |
| Wave 04 | T-S4-014, T-S5-001, T-S5-002 | T-S4-014 then T-S5-001+T-S5-002 parallel |
| Wave 05 | T-S5-003, T-S5-004, T-S5-005, T-S5-006 | All parallel |
| Wave 06 | T-S5-007→T-S5-008 (sequential), T-S5-009, T-S5-010 (parallel) | Mixed |
| Wave 07 | T-S5-011→T-S5-012 (sequential) | Sequential — FINAL WAVE |
