# Execution Prompt 0004 — market-data-migration wave 03

## Context (read first)

- **Planning prompt**: `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
- **Planning response (authoritative)**: `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md`

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture pattern
2. `CLAUDE.md` — Claude-specific workflow, diff discipline, logging rules
3. `docs/services/market-data.md` — target service specification
4. `docs/libs/contracts.md` — canonical model spec (CanonicalQuote, CanonicalFundamentals, parsing API)
5. `docs/libs/messaging.md` — BaseKafkaConsumer, BaseOutboxDispatcher, ValkeyClient, error hierarchy spec
6. `docs/libs/storage.md` — ObjectStorage interface and exception hierarchy
7. `docs/libs/observability.md` — ServiceMetrics and tracing API
8. `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
9. `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md` — §1 task backlog, Application Layer section (MD-019..MD-026, MD-031)
10. `docs/ai-interactions/BUG_PATTERNS.md` — read all consumer/outbox/env/async-test entries before starting

When handing off, explicitly list which `BP-xxx` entries were applied.

---

## Objective

Complete the **Application Layer** of the Market Data migration: Kafka consumers, REST API endpoints, QuoteCache, and full FastAPI app wiring (MD-019 through MD-026, and MD-031).

This wave builds directly on top of the foundation libs (wave 01: MD-001–MD-013) and the infrastructure/DB layer (wave 02: MD-014–MD-018, MD-027, MD-028). It delivers all consumer logic, all 22 API routes, the cache-aside caching layer, and the FastAPI lifespan that wires every infrastructure component together.

At the end of this wave:
- All three Kafka consumers are implemented, tested, and lint-clean.
- All 22 REST API routes are registered and tested.
- `QuoteCache` with versioned keys and graceful degradation is in place.
- FastAPI lifespan wires all infrastructure (DB, Valkey, S3, Kafka consumers, outbox dispatcher, Prometheus, OTel).
- No integration or E2E tests are written yet (wave 04).

---

## Task scope for this wave

**Total tasks: 9** (MD-019–MD-026, MD-031)

### Parallel group A — all can run simultaneously (all prerequisites satisfied from waves 01 and 02)

| Task ID | Short title | Target paths |
|---------|-------------|--------------|
| MD-019 | OHLCV Materializer Consumer | `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`, `tests/unit/test_ohlcv_consumer.py` |
| MD-020 | Quotes Consumer with Valkey cache invalidation | `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`, `tests/unit/test_quotes_consumer.py` |
| MD-021 | Fundamentals Consumer (13-section decomposition) | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`, `tests/unit/test_fundamentals_consumer.py` |
| MD-022 | Instruments API Endpoints | `services/market-data/src/market_data/api/routers/instruments.py`, `api/schemas/instruments.py`, `api/dependencies.py`, `tests/unit/test_instruments_api.py` |
| MD-023 | OHLCV API Endpoints | `services/market-data/src/market_data/api/routers/ohlcv.py`, `api/schemas/ohlcv.py`, `tests/unit/test_ohlcv_api.py` |
| MD-024 | Quotes API Endpoints with Valkey caching | `services/market-data/src/market_data/api/routers/quotes.py`, `api/schemas/quotes.py`, `tests/unit/test_quotes_api.py` |
| MD-025 | Fundamentals API Endpoints (9 endpoints + securities) | `services/market-data/src/market_data/api/routers/fundamentals.py`, `api/routers/securities.py`, `api/schemas/fundamentals.py`, `api/schemas/securities.py`, `tests/unit/test_fundamentals_api.py`, `tests/unit/test_securities_api.py` |

### Sequential group B — after MD-020 and MD-024 complete

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| MD-026 | MD-020, MD-024 done | QuoteCache (cache-aside pattern, TTL, invalidation, versioned keys) |

### Sequential group C — after all of group A and group B complete

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| MD-031 | MD-019–MD-026 all done | Wire FastAPI lifespan: all infrastructure, consumers, metrics, tracing, DI |

---

## Why this chunk

**Coherence**: This wave covers the entire application layer — consumers that materialize inbound events, the REST API surface exposed to clients, and the lifespan that wires them together. These are orthogonal to the DB/infrastructure work of wave 02 but all live in the same service boundary.

**Dependency fit**: All wave 03 tasks depend on wave 01 libs (BaseKafkaConsumer, ObjectStorage, ValkeyClient, error hierarchy, canonical models) and wave 02 DB artifacts (repositories, UoW, session factory, OHLCVRepository priority upsert). Waves 01 and 02 must be complete before this wave begins.

**Parallelism**: Seven tasks in parallel group A share no inter-dependencies. MD-026 waits only for MD-020 (QuotesConsumer provides the invalidation target) and MD-024 (Quotes API provides the cache-aside target). MD-031 consolidates everything in a single lifespan rewrite once all application components exist.

**Size**: 9 tasks — within the [1, 20] bound.

---

## Implementation instructions

### MD-019 — OHLCV Materializer Consumer

1. Read `services/market-data/src/market_data/infrastructure/db/repositories/` (from wave 02) and `libs/messaging/src/messaging/consumer.py` (from wave 01) before writing any code.
2. Create `OHLCVConsumer(BaseKafkaConsumer)` with `group_id="market-data-ohlcv"`, `topic="market.dataset.fetched"`.
3. Implement `process_message()` with the following ordered steps:
   a. Deserialize Avro message and extract `bucket`, `object_key`, `content_type`, `dataset_type`.
   b. Filter: `if dataset_type != "OHLCV": return` (skip without error).
   c. Idempotency: call `IngestionEventRepository.exists(event_id)` — return immediately if `True`.
   d. Download from S3 via `ObjectStorage.get(bucket, object_key)` — classify any S3/storage error as `RetryableError` so the offset is not committed.
   e. Parse: `parse_ohlcv_jsonl(raw)` → `list[CanonicalOHLCVBar]`.
   f. Resolve or create instrument: look up by `(symbol, exchange)`; if not found, create a new `Instrument` and collect an `InstrumentCreated` domain event.
   g. Map canonical bars → `OHLCVBar` domain entities.
   h. Bulk upsert: `OHLCVRepository.bulk_upsert_with_priority(bars)` — respects provider priority ordering.
   i. Record: `IngestionEventRepository.create(event_id)`.
   j. Commit UoW (triggers outbox dispatch for any collected `InstrumentCreated` events).
4. Implement `on_fatal_error()`: create a `FailedTask` record via `FailedTaskRepository`.
5. Write unit tests in `tests/unit/test_ohlcv_consumer.py`:
   - `test_ohlcv_consumer_processes_valid_message` — mock S3 and DB; verify bars upserted.
   - `test_ohlcv_consumer_skips_non_ohlcv` — `dataset_type="QUOTE"` → no DB interaction.
   - `test_ohlcv_consumer_skips_duplicate_event` — `exists()` returns `True` → early return, no upsert.
   - `test_ohlcv_consumer_creates_instrument_on_first_seen` — instrument lookup miss → instrument created, `InstrumentCreated` in outbox.
   - `test_ohlcv_consumer_provider_priority_respected` — higher-priority provider overwrites; lower-priority does not.
   - `test_ohlcv_consumer_fatal_error_creates_failed_task` — fatal parse error → `FailedTaskRepository.create()` called, offset committed.
   - `test_ohlcv_consumer_retryable_error_does_not_commit` — S3 failure → `RetryableError` raised, UoW not committed.
6. Update `docs/services/market-data.md` OHLCV consumer section with a Mermaid sequence diagram covering the full consume → filter → idempotency check → S3 download → parse → instrument resolve → bulk upsert → record → commit flow.
7. Run: `cd services/market-data && make test -- tests/unit/test_ohlcv_consumer.py && make lint`.

**DoD**: `OHLCVConsumer` subclasses `BaseKafkaConsumer`, all 7 unit tests pass, Mermaid diagram in `docs/services/market-data.md`, lint clean.

---

### MD-020 — Quotes Consumer with Valkey cache invalidation

1. Create `QuotesConsumer(BaseKafkaConsumer)` with `group_id="market-data-quotes"`, `topic="market.dataset.fetched"`.
2. Implement `process_message()`:
   a. Filter: skip if `dataset_type != "QUOTE"`.
   b. Idempotency check via `IngestionEventRepository.exists(event_id)`.
   c. Download from S3 via `ObjectStorage.get()` — S3 errors → `RetryableError`.
   d. Parse: `parse_quotes_json(raw)` → `CanonicalQuote`.
   e. Resolve instrument: look up by `(symbol, exchange)`; create if new, emit `InstrumentCreated`.
   f. Upsert: `QuoteRepository.upsert(quote)`.
   g. Invalidate Valkey cache **after** DB upsert (not before): `valkey.delete(f"quote:v1:{instrument_id}")`.
   h. Record `event_id`. Commit UoW.
3. Write unit tests in `tests/unit/test_quotes_consumer.py`:
   - `test_quotes_consumer_processes_valid_message`
   - `test_quotes_consumer_skips_non_quote`
   - `test_quotes_consumer_invalidates_cache` — verify `valkey.delete()` called with correct versioned key after DB upsert.
   - `test_quotes_consumer_creates_instrument_on_first_seen`
   - `test_quotes_consumer_fatal_error_on_parse_failure`
   - `test_quotes_consumer_retryable_error_on_s3_failure`
4. Update `docs/services/market-data.md` quotes consumer section.
5. Run: `cd services/market-data && make test -- tests/unit/test_quotes_consumer.py && make lint`.

**DoD**: `QuotesConsumer` subclasses `BaseKafkaConsumer`, cache invalidation uses versioned key `quote:v1:{instrument_id}`, all 6 unit tests pass, lint clean.

---

### MD-021 — Fundamentals Consumer (13-section decomposition)

1. Create `FundamentalsConsumer(BaseKafkaConsumer)` with `group_id="market-data-fundamentals"`, `topic="market.dataset.fetched"`.
2. Define the section-to-table mapping as a class-level dict: 13 EODHD section keys → 20 DB table-targeting repository methods.
3. Implement `process_message()`:
   a. Filter: skip if `dataset_type != "FUNDAMENTALS"`.
   b. Idempotency check. Download from S3. Parse: `parse_fundamentals_json(raw)` → `CanonicalFundamentals`.
   c. Resolve security by FIGI/ISIN via `SecurityRepository`.
   d. For each present section in the parsed payload: map fields to the appropriate domain entity and route to the correct repository method.
   e. Special handling: `analyst_consensus` and `dividend_summary` use merge-upsert (not replace).
   f. Provider priority check per section before writing.
   g. **Fix legacy bug**: audit the field mapping dict for duplicate keys — fix any found and document them explicitly in handoff evidence.
   h. Record `event_id`. Commit UoW.
4. Write unit tests in `tests/unit/test_fundamentals_consumer.py`:
   - `test_fundamentals_consumer_processes_full_payload` — all 13 sections present; verify rows written to all relevant repos.
   - `test_fundamentals_consumer_processes_partial_payload` — only 3 sections present; verify only those 3 are written.
   - `test_fundamentals_consumer_merge_upsert_analyst_consensus`
   - `test_fundamentals_consumer_merge_upsert_dividend_summary`
   - `test_fundamentals_consumer_section_mapping_complete` — assert all 13 sections covered in the mapping dict.
   - `test_fundamentals_consumer_skips_esg_section` — ESG key present but not in mapping → silently skipped.
   - `test_fundamentals_consumer_provider_priority` — lower-priority event does not overwrite existing data.
5. Update `docs/services/market-data.md` fundamentals consumer section with: the section-to-table mapping table (section → DB tables written), and a Mermaid flowchart diagram of the per-section routing logic.
6. Run: `cd services/market-data && make test -- tests/unit/test_fundamentals_consumer.py && make lint`.

**DoD**: `FundamentalsConsumer` with complete 13-section routing, merge-upsert for analyst consensus and dividend summary, legacy duplicate-key bug fixed and documented, all 7 unit tests pass, Mermaid diagram and section-to-table mapping table in docs, lint clean.

---

### MD-022 — Instruments API Endpoints

1. Create `services/market-data/src/market_data/api/schemas/instruments.py` with Pydantic models:
   - `InstrumentResponse` — all instrument fields including `InstrumentFlags`.
   - `InstrumentListResponse` — list + pagination metadata (`total`, `limit`, `offset`).
   - `InstrumentSearchParams` — query parameters model.
2. Create `services/market-data/src/market_data/api/dependencies.py` with `get_uow()` FastAPI dependency using `Depends`.
3. Create `services/market-data/src/market_data/api/routers/instruments.py` with:
   - `GET /api/v1/instruments` — query params: `search: str | None`, `exchange: str | None`, `has_ohlcv: bool | None`, `has_quotes: bool | None`, `has_fundamentals: bool | None`, `limit: int = 50`, `offset: int = 0`. Returns `InstrumentListResponse`.
   - `GET /api/v1/instruments/{instrument_id}` — returns `InstrumentResponse`; raises HTTP 404 if not found.
   - `GET /api/v1/instruments/symbol/{symbol}` — query param: `exchange: str | None`. Returns `InstrumentResponse`; 404 if not found.
4. Register the router in `app.py` under the `/api/v1` prefix.
5. Write unit tests in `tests/unit/test_instruments_api.py` (use `TestClient`, mock UoW):
   - `test_list_instruments`
   - `test_list_instruments_with_filters`
   - `test_get_instrument_by_id`
   - `test_get_instrument_not_found_404`
   - `test_get_instrument_by_symbol`
   - `test_search_instruments_pagination`
6. Update `docs/services/market-data.md` instruments API section with request/response examples for each endpoint.
7. Run: `cd services/market-data && make test -- tests/unit/test_instruments_api.py && make lint`.

**DoD**: 3 instrument endpoints registered, `dependencies.py` with `get_uow()`, all 6 unit tests pass, docs updated with examples, lint clean.

---

### MD-023 — OHLCV API Endpoints

1. Create `services/market-data/src/market_data/api/schemas/ohlcv.py` with:
   - `OHLCVBarResponse` — all OHLCV fields with Decimal serialization as strings.
   - `OHLCVListResponse` — list + metadata.
   - `OHLCVRangeResponse` — `min_date`, `max_date`, `count`.
2. Create `services/market-data/src/market_data/api/routers/ohlcv.py` with:
   - `GET /api/v1/ohlcv/{instrument_id}` — query params: `timeframe: Timeframe`, `start: date | None`, `end: date | None`, `limit: int = 500`. Returns `OHLCVListResponse`.
   - `GET /api/v1/ohlcv/{instrument_id}/timeframes` — returns list of available `Timeframe` values for the instrument.
   - `GET /api/v1/ohlcv/{instrument_id}/range` — returns `OHLCVRangeResponse`.
   - `GET /api/v1/ohlcv/bulk` — query params: `instrument_ids: list[UUID]`, `timeframe: Timeframe`, `start: date | None`, `end: date | None`. Returns dict keyed by instrument ID.
   Validation: invalid timeframe enum → 422; `start` after `end` → 422 with descriptive error message.
3. Register the router.
4. Write unit tests in `tests/unit/test_ohlcv_api.py`:
   - `test_get_ohlcv_bars`
   - `test_get_ohlcv_bars_with_date_range`
   - `test_get_ohlcv_bars_invalid_timeframe`
   - `test_get_available_timeframes`
   - `test_get_date_range`
   - `test_bulk_ohlcv`
   - `test_ohlcv_start_after_end_422`
5. Update `docs/services/market-data.md` OHLCV API section.
6. Run: `cd services/market-data && make test -- tests/unit/test_ohlcv_api.py && make lint`.

**DoD**: 4 OHLCV endpoints registered, start-after-end validation returns 422, all 7 unit tests pass, lint clean.

---

### MD-024 — Quotes API Endpoints with Valkey caching

1. Create `services/market-data/src/market_data/api/schemas/quotes.py` with:
   - `QuoteResponse` — all quote fields.
   - `BatchQuoteRequest` — body model for POST batch.
   - `BatchQuoteResponse` — dict of `instrument_id → QuoteResponse | null`.
2. Create `services/market-data/src/market_data/api/routers/quotes.py` with:
   - `GET /api/v1/quotes/{instrument_id}` — cache-aside pattern: check Valkey key `quote:v1:{instrument_id}` → if hit, return cached JSON; if miss, query DB → cache result with 5-second TTL → return. Graceful degradation: if Valkey is unavailable (`redis.ConnectionError`), log a warning and fall back to DB directly without raising.
   - `POST /api/v1/quotes/batch` — body: `BatchQuoteRequest`. For each ID: same cache-aside logic.
   - `GET /api/v1/quotes/latest` — query param: `instrument_ids: list[UUID]`. Returns all latest quotes in a single dict response.
   Cache key format: `quote:v1:{instrument_id}` (versioned to allow cache-busting on schema changes).
3. Register the router.
4. Write unit tests in `tests/unit/test_quotes_api.py`:
   - `test_get_quote`
   - `test_get_quote_cache_hit` — verify DB not called when cache hit.
   - `test_get_quote_cache_miss` — verify DB queried and result cached.
   - `test_get_quote_not_found_404`
   - `test_batch_quotes`
   - `test_get_quote_valkey_down_fallback` — Valkey raises `ConnectionError` → DB queried, 200 response returned.
   - `test_quote_cache_ttl` — verify TTL of 5 seconds passed to `valkey.set()`.
5. Update `docs/services/market-data.md` quotes API and caching sections.
6. Run: `cd services/market-data && make test -- tests/unit/test_quotes_api.py && make lint`.

**DoD**: 3 quote endpoints registered, cache-aside with TTL and graceful degradation, all 7 unit tests pass, lint clean.

---

### MD-025 — Fundamentals API Endpoints (9 endpoints + securities)

1. Create `services/market-data/src/market_data/api/schemas/fundamentals.py` with per-section response models:
   - `IncomeStatementResponse`, `BalanceSheetResponse`, `CashFlowResponse`, `ValuationResponse`, `AnalystConsensusResponse`, `DividendsResponse`, `EarningsResponse`, `FullFundamentalsResponse` (aggregates all available sections).
2. Create `services/market-data/src/market_data/api/schemas/securities.py` with:
   - `SecurityResponse`, `SecurityListResponse`.
3. Create `services/market-data/src/market_data/api/routers/fundamentals.py` with:
   - `GET /api/v1/fundamentals/{security_id}` — returns `FullFundamentalsResponse` (all available sections aggregated).
   - `GET /api/v1/fundamentals/{security_id}/income-statement` — query: `period_type: PeriodType`, `limit: int`.
   - `GET /api/v1/fundamentals/{security_id}/balance-sheet`
   - `GET /api/v1/fundamentals/{security_id}/cash-flow`
   - `GET /api/v1/fundamentals/{security_id}/valuation`
   - `GET /api/v1/fundamentals/{security_id}/analyst-consensus`
   - `GET /api/v1/fundamentals/{security_id}/dividends`
   - `GET /api/v1/fundamentals/{security_id}/earnings`
   All per-section endpoints return 404 if `security_id` not found.
4. Create `services/market-data/src/market_data/api/routers/securities.py` with:
   - `GET /api/v1/securities` — query params: `search`, `limit`, `offset`.
   - `GET /api/v1/securities/{security_id}` — 404 if not found.
5. Register all routers.
6. Write unit tests in `tests/unit/test_fundamentals_api.py` and `tests/unit/test_securities_api.py`:
   - `test_get_full_fundamentals`, `test_get_income_statement`, `test_get_balance_sheet`, `test_get_cash_flow`, `test_get_valuation`, `test_get_analyst_consensus`, `test_get_dividends`, `test_get_earnings`, `test_fundamentals_not_found_404`, `test_list_securities`, `test_get_security_by_id`.
7. Update `docs/services/market-data.md` fundamentals and securities API sections with request/response examples for all endpoints.
8. Run: `cd services/market-data && make test -- tests/unit/test_fundamentals_api.py tests/unit/test_securities_api.py && make lint`.

**DoD**: 9 fundamentals endpoints + 2 securities endpoints registered, all 11 unit tests pass, docs updated with examples, lint clean.

---

### MD-026 — QuoteCache (after MD-020 and MD-024)

1. Create `services/market-data/src/market_data/infrastructure/cache/quote_cache.py` with `QuoteCache` class wrapping `ValkeyClient`:
   - `get(instrument_id: UUID) -> QuoteResponse | None` — returns deserialized `QuoteResponse` or `None` on miss.
   - `set(instrument_id: UUID, quote: QuoteResponse, ttl: int = 5)` — serializes to JSON and sets with TTL.
   - `invalidate(instrument_id: UUID)` — deletes the key.
   - `invalidate_many(instrument_ids: list[UUID])` — deletes multiple keys in one batch.
   Cache key: `quote:v1:{instrument_id}` (versioned). Uses JSON serialization for the value.
   Graceful degradation on all methods: catch `redis.ConnectionError`, log a `structlog` warning with key context, and return `None` (for `get`) or silently pass (for `set`/`invalidate`). Never propagate `ConnectionError` to callers.
2. Integrate `QuoteCache` into:
   - `quotes.py` router (MD-024): replace any inline Valkey calls with `QuoteCache` methods.
   - `QuotesConsumer` (MD-020): replace inline `valkey.delete()` with `QuoteCache.invalidate()`.
3. Write unit tests in `tests/unit/test_quote_cache.py`:
   - `test_quote_cache_get_hit`
   - `test_quote_cache_get_miss`
   - `test_quote_cache_set_with_ttl` — verify correct TTL passed to underlying client.
   - `test_quote_cache_invalidate`
   - `test_quote_cache_graceful_degradation` — `ConnectionError` raised by client → method returns `None`, no exception propagated.
4. Update `docs/services/market-data.md` caching section with cache key patterns, TTL values, and invalidation flow.
5. Run: `cd services/market-data && make test -- tests/unit/test_quote_cache.py && make lint`.

**DoD**: `QuoteCache` with all 4 methods, versioned key `quote:v1:{instrument_id}`, graceful degradation on `ConnectionError`, all 5 unit tests pass, integrated into router and consumer, docs updated, lint clean.

---

### MD-031 — Wire FastAPI lifespan (after MD-019–MD-026 all done)

1. Update `services/market-data/pyproject.toml` to add relative path dependencies for: `common`, `contracts`, `messaging`, `storage`, `observability`.
2. Rewrite `services/market-data/src/market_data/app.py` lifespan function:
   - **Startup sequence**:
     1. Create async SQLAlchemy engine and session factory from `config.DATABASE_URL`.
     2. Create `ValkeyClient` and call `connect()`.
     3. Create `S3ObjectStorage` from storage config.
     4. Configure structlog (JSON formatter, log level from config).
     5. Call `create_metrics(service_name="market-data")` and `add_prometheus_middleware(app, metrics)`.
     6. Call `configure_tracing(service_name="market-data", otlp_endpoint=config.OTLP_ENDPOINT)` and `add_otel_middleware(app)`.
     7. Start `OHLCVConsumer`, `QuotesConsumer`, `FundamentalsConsumer` each as an `asyncio` background task.
     8. Start the outbox dispatcher as an `asyncio` background task.
   - **Shutdown sequence** (on context manager exit):
     1. Stop all three consumers (call `stop()` and await tasks).
     2. Stop outbox dispatcher.
     3. Close `ValkeyClient`.
     4. Dispose SQLAlchemy engine.
3. Update the `readyz` endpoint to check all four dependencies:
   - DB: execute `SELECT 1`.
   - Kafka: verify consumer reachability (ping broker or check consumer state).
   - MinIO/S3: `check_storage_health(object_storage, bucket=config.BUCKET)`.
   - Valkey: `valkey.health_check()`.
   Return HTTP 503 with a structured JSON body identifying which dependency failed if any check fails; return HTTP 200 `{"status": "ok"}` if all pass.
4. Add `/metrics` Prometheus endpoint (mounted via `add_prometheus_middleware`).
5. Wire `get_uow()` dependency into FastAPI DI container via `app.dependency_overrides` or `Depends` in all routers.
6. Write unit tests in `tests/unit/test_app.py`:
   - `test_readyz_checks_dependencies` — mock all 4 deps; verify 200 when all healthy, 503 when any fails.
   - `test_lifespan_starts_consumers` — verify all 3 consumers and dispatcher started as background tasks.
   - `test_lifespan_cleanup_on_shutdown` — verify all consumers stopped, Valkey closed, engine disposed.
7. Update `docs/services/market-data.md` deployment and configuration sections with:
   - Complete env var reference table (from `config.py`) with names, types, defaults, and descriptions.
   - Mermaid sequence diagram of the startup sequence (startup has ≥3 components and ≥4 steps).
8. Run: `cd services/market-data && make test && make lint`.

**DoD**: Lifespan wires all 8 startup steps and 4 shutdown steps, `readyz` checks all 4 dependencies and returns 503 on failure, `/metrics` endpoint mounted, all 3 unit tests pass, env var table and Mermaid startup sequence diagram in docs, lint clean.

---

## Constraints

- Do not implement any code outside the task IDs listed in this wave (MD-019 through MD-026 and MD-031).
- Do not run integration tests in this wave — testcontainers and full-stack tests are MD-029 in wave 04.
- Do not modify wave 01 lib files (`libs/`) or wave 02 DB/infrastructure files; only add consumer and API code on top of them.
- Cache key format must always use the versioned form `quote:v1:{instrument_id}` — never use unversioned keys.
- All timestamps must use `utc_now()` from `libs/common` or `datetime.now(tz=timezone.utc)`. Never use naive datetimes.

## Regression guardrails (compounding, mandatory)

- For consumer and dispatcher integrations, apply [BP-001] and [BP-009] to avoid outbox serialization/config regressions.
- For runtime wiring and local execution targets, apply [BP-002] and [BP-006] so env values flow correctly in Makefile and compose contexts.
- For any containerized background process started in this wave, apply [BP-010] and [BP-011] (healthchecks + runtime assets present in image).
- For async API/consumer tests with polling or rollback loops, apply [BP-003], [BP-012], and [BP-013] (fixture loop scope, scalar polling, strict deadlines).
- One logical change per edit. Do not combine unrelated changes in a single diff.
- `FundamentalsConsumer`: if the legacy field mapping dict contains duplicate keys, fix them and document all fixes in handoff evidence — do not leave them silently overwriting.
- All API endpoints must be registered under the `/api/v1/` prefix.

---

## Incremental quality gates (mandatory)

For each task ID, before moving to the next task, run and pass:

1. Targeted test command(s) for the task's changed behavior.
2. `ruff check` on changed paths only.
3. `mypy` on changed package/module only.

- No deferred fixes: do not carry ruff/mypy/test failures into later tasks.
- If the same failure repeats twice, capture root cause + remediation in handoff evidence.

## Required tests

### Unit tests

```bash
# Consumer tests
cd services/market-data && make test -- tests/unit/test_ohlcv_consumer.py && make lint
cd services/market-data && make test -- tests/unit/test_quotes_consumer.py && make lint
cd services/market-data && make test -- tests/unit/test_fundamentals_consumer.py && make lint

# API tests
cd services/market-data && make test -- tests/unit/test_instruments_api.py && make lint
cd services/market-data && make test -- tests/unit/test_ohlcv_api.py && make lint
cd services/market-data && make test -- tests/unit/test_quotes_api.py && make lint
cd services/market-data && make test -- tests/unit/test_fundamentals_api.py tests/unit/test_securities_api.py && make lint

# Cache and app tests
cd services/market-data && make test -- tests/unit/test_quote_cache.py && make lint
cd services/market-data && make test -- tests/unit/test_app.py && make lint

# Full unit suite
cd services/market-data && make test -- tests/unit/ -v && make lint
```

### Global lint

```bash
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass (`pytest` exit code 0).
- 22 API routes registered: 3 health/infra (`healthz`, `readyz`, `/metrics`) + 3 instruments + 4 OHLCV + 3 quotes + 9 fundamentals/securities.
- `ruff check` reports zero errors across all changed files.
- `mypy --strict` reports zero errors across all changed files.
- No regressions in previously passing tests.

---

## Documentation requirements

For every task in this wave, update documentation **in the same wave** for any change to behaviour, contracts, config, schema, or API surface.

| Change type | File to update |
|-------------|---------------|
| OHLCV consumer flow | `docs/services/market-data.md` — add Mermaid sequence diagram of consume → parse → upsert → commit |
| Quotes consumer flow | `docs/services/market-data.md` — update consumer section, note cache invalidation step |
| Fundamentals section-to-table mapping | `docs/services/market-data.md` — add mapping table + Mermaid flowchart of per-section routing |
| All 22 API endpoints | `docs/services/market-data.md` — API reference section with request params, response schemas, error codes, and copy-pasteable examples |
| Caching strategy | `docs/services/market-data.md` — caching section: key patterns (`quote:v1:{id}`), TTL values, invalidation trigger, graceful degradation behaviour |
| App lifespan and env vars | `docs/services/market-data.md` — deployment section: complete env var table + Mermaid startup sequence diagram |
| Common pitfalls | `docs/services/market-data.md` — `## Common Pitfalls` section with ≥3 concrete entries specific to this service (e.g., naive datetimes, unversioned cache keys, dual-writes) |

**Documentation quality standard** — before marking this wave done, verify all 8 criteria and include the quality checklist table in handoff evidence:

1. **Accuracy** — every documented endpoint path, field name, event type, config var, and cache key pattern must match the final implementation exactly.
2. **Diagrams for non-trivial flows** — OHLCV consumer flow (≥4 steps), fundamentals section routing (≥3 branches), and app startup sequence (≥3 components) each require a Mermaid diagram.
3. **Realistic code examples** — every new public class (`OHLCVConsumer`, `QuotesConsumer`, `FundamentalsConsumer`, `QuoteCache`) must have a working usage example in docs.
4. **Abstract methods documented** — `BaseKafkaConsumer` ABC table already completed in wave 01; verify it still matches the concrete implementations added in this wave.
5. **Common Pitfalls section** — `docs/services/market-data.md` must include `## Common Pitfalls` with ≥3 entries.
6. **Lib docs updated** — this wave does not modify any `libs/` file; state explicitly `N/A: no lib surface changed`.
7. **Service doc reflects final state** — `docs/services/market-data.md` must match all 22 routes, all consumer behaviours, caching strategy, and env vars after this wave.
8. **No orphan documentation** — do not document any endpoint, class, or behaviour that is not yet implemented.

**Mandatory instruction**: If any implementation changes a behaviour, contract, config, schema surface, or API surface described in documentation, update that documentation in this same wave. List every doc file changed in the handoff evidence.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description of the change.

### 2. Tests run and results

```
consumers (ohlcv, quotes, fundamentals):   X tests, X passed, 0 failed
API (instruments, ohlcv, quotes, fundamentals, securities):   X tests, X passed, 0 failed
cache (QuoteCache):   X tests, X passed, 0 failed
app wiring (lifespan, readyz):   X tests, X passed, 0 failed
services/market-data full unit suite:   X tests, X passed, 0 failed
./scripts/lint.sh:   exit code 0
```

### 3. Documentation changed (exact files + what was updated)

Example format:
- `docs/services/market-data.md` — added OHLCV consumer Mermaid sequence diagram; added quotes consumer section with cache invalidation note; added fundamentals section-to-table mapping table and Mermaid flowchart; added complete API reference for all 22 routes with examples; added caching section with key patterns and TTL; added deployment section with env var table and Mermaid startup sequence; added `## Common Pitfalls` with ≥3 entries.

### 4. Unresolved blockers

List anything that could not be implemented as specified and why. State `none` if there are no blockers.

### 5. Documentation quality checklist

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Accuracy — endpoints, fields, event types, config vars, cache keys match implementation | ✓ / ⚠️ / N/A | |
| 2 | Diagrams for non-trivial flows (OHLCV consumer, fundamentals routing, app startup) | ✓ / ⚠️ / N/A | List diagram titles |
| 3 | Realistic code examples — every new public class has working usage example | ✓ / ⚠️ / N/A | |
| 4 | Abstract methods documented — BaseKafkaConsumer ABC table still matches concrete impls | ✓ / ⚠️ / N/A | |
| 5 | Common Pitfalls section — `docs/services/market-data.md` has ≥3 entries | ✓ / ⚠️ / N/A | |
| 6 | Lib docs updated — N/A: no lib public surface changed in this wave | ✓ / ⚠️ / N/A | |
| 7 | Service doc reflects final state — all 22 routes, consumers, caching, env vars documented | ✓ / ⚠️ / N/A | |
| 8 | No orphan documentation — no docs for unimplemented code | ✓ / ⚠️ / N/A | |

### 6. Commit message proposal

```
feat(market-data/app): consumers, API endpoints, QuoteCache, and app wiring (MD-019..MD-026, MD-031)

Implement OHLCV materializer consumer, quotes consumer with Valkey invalidation, and
fundamentals consumer with 13-section decomposition and merge-upsert across 20 tables;
fix legacy duplicate-key field mapping bug. Implement all 22 API endpoints (instruments,
OHLCV, quotes with cache-aside, fundamentals, securities). Implement QuoteCache with
versioned keys and graceful degradation. Wire FastAPI lifespan with all infrastructure
components, 3 consumers, outbox dispatcher, Prometheus metrics, and OTel tracing.
All unit tests pass; ruff + mypy strict clean.
```

---

## Definition of done

- [ ] MD-019: `OHLCVConsumer` subclasses `BaseKafkaConsumer`, implements full 10-step `process_message()`, `on_fatal_error()` creates `FailedTask`, all 7 unit tests pass, Mermaid sequence diagram in `docs/services/market-data.md`.
- [ ] MD-020: `QuotesConsumer` subclasses `BaseKafkaConsumer`, cache invalidation uses versioned key `quote:v1:{instrument_id}` after DB upsert, all 6 unit tests pass, consumer section in docs updated.
- [ ] MD-021: `FundamentalsConsumer` with complete 13-section routing, merge-upsert for `analyst_consensus` and `dividend_summary`, legacy duplicate-key bug fixed and documented, all 7 unit tests pass, section-to-table mapping table and Mermaid flowchart in docs.
- [ ] MD-022: 3 instruments endpoints registered under `/api/v1/instruments`, `dependencies.py` with `get_uow()`, all 6 unit tests pass, docs updated with request/response examples.
- [ ] MD-023: 4 OHLCV endpoints registered, start-after-end validation → 422, all 7 unit tests pass, docs updated.
- [ ] MD-024: 3 quote endpoints registered, cache-aside with 5-second TTL, graceful Valkey degradation, all 7 unit tests pass, docs updated.
- [ ] MD-025: 9 fundamentals endpoints + 2 securities endpoints registered, all 11 unit tests pass, docs updated with examples.
- [ ] MD-026: `QuoteCache` with 4 methods, versioned key pattern, graceful `ConnectionError` handling, integrated into quotes router and quotes consumer, all 5 unit tests pass, docs updated.
- [ ] MD-031: Lifespan wires 8 startup steps and 4 shutdown steps, `readyz` checks DB/Kafka/MinIO/Valkey and returns 503 on failure, `/metrics` endpoint mounted, all 3 unit tests pass, env var table and Mermaid startup diagram in docs.
- [ ] All 22 API routes registered: 3 health/infra + 3 instruments + 4 OHLCV + 3 quotes + 9 fundamentals/securities.
- [ ] All three consumers implement `BaseKafkaConsumer` correctly (group IDs set, idempotency checked, RetryableError on S3 failure, FatalError triggers `FailedTask`).
- [ ] `QuoteCache` versioned key pattern `quote:v1:{instrument_id}` in place and used consistently by both consumer and router.
- [ ] Outbox dispatcher wired in lifespan and started as background task.
- [ ] `readyz` endpoint checks DB, Kafka, MinIO, and Valkey; returns 503 with structured error body on any failure.
- [ ] `docs/services/market-data.md` includes `## Common Pitfalls` with ≥3 entries.
- [ ] Documentation quality gate: all 8 criteria confirmed ✓ or N/A with justification — no criterion left blank.
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] Commit message proposal included in handoff evidence.
