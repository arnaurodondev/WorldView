# Execution Prompt 0004 — market-data-migration wave 01

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
4. `docs/libs/contracts.md` — canonical model spec
5. `docs/libs/messaging.md` — Kafka producer, consumer, outbox, error hierarchy spec
6. `docs/libs/storage.md` — ObjectStorage interface spec
7. `docs/libs/observability.md` — metrics and tracing spec
8. `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
9. `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md` — §1 task backlog, Foundation Libs and Domain Layer sections

---

## Objective

Complete **Foundation Libs** (MD-001 through MD-012) and the **Domain Layer** (MD-012, MD-013) of the Market Data migration.

This wave lays all shared-library capabilities (canonical models, parsing, error hierarchy, Kafka producer, consumer, outbox, Valkey client, object storage, metrics, tracing) that subsequent waves depend on, and simultaneously establishes the complete framework-free domain layer of the `market-data` service (enums, value objects, entities, domain events, error hierarchy).

At the end of this wave:
- All lib gaps relevant to market-data are closed and ready for use.
- The entire `market_data/domain/` package is populated, tested, and lint-clean.
- No application, infrastructure, or API code is written yet.

---

## Task scope for this wave

**Total tasks: 13**

### Parallel group A — no external dependencies (start simultaneously)

| Task ID | Short title | Target paths |
|---------|-------------|--------------|
| MD-001 | CanonicalQuote frozen dataclass | `libs/contracts/src/contracts/canonical/quotes.py`, `libs/contracts/tests/test_quotes.py`, `libs/contracts/src/contracts/canonical/__init__.py` |
| MD-002 | CanonicalFundamentals frozen dataclass | `libs/contracts/src/contracts/canonical/fundamentals.py`, `libs/contracts/tests/test_fundamentals.py` |
| MD-004 | messaging.errors module | `libs/messaging/src/messaging/errors.py`, `libs/messaging/tests/test_errors.py` |
| MD-006 | KafkaProducerConfig + producer factory | `libs/messaging/src/messaging/producer.py`, `libs/messaging/tests/test_producer.py` |
| MD-008 | ValkeyClient async wrapper | `libs/messaging/src/messaging/valkey.py`, `libs/messaging/tests/test_valkey.py` |
| MD-009 | ObjectStorage ABC + S3ObjectStorage + health + exceptions | `libs/storage/src/storage/object_storage.py`, `libs/storage/src/storage/exceptions.py`, `libs/storage/src/storage/health.py`, `libs/storage/tests/test_object_storage.py` |
| MD-010 | Prometheus ServiceMetrics + middleware | `libs/observability/src/observability/metrics.py`, `libs/observability/tests/test_metrics.py` |
| MD-011 | configure_tracing + OTel middleware | `libs/observability/src/observability/tracing.py`, `libs/observability/tests/test_tracing.py` |
| MD-012 | Domain entities, value objects, enums | `services/market-data/src/market_data/domain/entities.py`, `value_objects.py`, `enums.py`, `__init__.py`, `tests/unit/test_domain_entities.py`, `tests/unit/test_value_objects.py` |

### Sequential group B — after parallel group A completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| MD-003 | MD-001, MD-002 done | contracts.parsing module |
| MD-005 | MD-004 done | BaseKafkaConsumer abstract base class |
| MD-007 | MD-006 done | BaseOutboxDispatcher with lease-based dispatch |
| MD-013 | MD-004 done | Domain events + error hierarchy |

---

## Why this chunk

**Coherence**: Parallel group A covers all shared library foundations (no service dependencies) and the domain layer (no library dependencies). These are orthogonal subsystems that can be developed simultaneously — domain code is pure Python with zero lib imports.

**Dependency fit**: Every wave 02 task (DB, infrastructure) requires at least one lib from group A or an entity from MD-012. Completing all of groups A and B in wave 01 clears the critical path for wave 02.

**Size**: 13 tasks — within the [1, 20] bound.

**Parallelism**: 9 tasks can start concurrently; each group B task requires exactly one or two prior steps and unlocks immediately once those are done.

---

## Implementation instructions

### MD-001 — CanonicalQuote

1. Read `libs/contracts/src/contracts/canonical/ohlcv.py` for the frozen-dataclass pattern.
2. Create `libs/contracts/src/contracts/canonical/quotes.py` with `CanonicalQuote` frozen dataclass. Fields: `symbol: str`, `exchange: str`, `bid: Decimal`, `ask: Decimal`, `last_price: Decimal`, `volume: Decimal`, `timestamp: datetime`, `source: str`, `schema_version: int` (non-init, auto from `QUOTE_SCHEMA_VERSION` constant).
3. Implement `from_dict(d: dict) -> CanonicalQuote` and `to_dict() -> dict`.
4. Update `canonical/__init__.py` to re-export `CanonicalQuote` and `QUOTE_SCHEMA_VERSION`.
5. Write unit tests in `libs/contracts/tests/test_quotes.py`: `test_canonical_quote_schema_version`, `test_canonical_quote_roundtrip`, `test_canonical_quote_frozen`, `test_canonical_quote_from_dict_missing_fields`.
6. Update `docs/libs/contracts.md` — add `CanonicalQuote` to the public API surface table.
7. Run: `cd libs/contracts && make test && make lint`.

**DoD**: `CanonicalQuote` frozen dataclass with `from_dict()`/`to_dict()`, `schema_version` matches constant, all 4 tests pass, `docs/libs/contracts.md` updated.

---

### MD-002 — CanonicalFundamentals

1. Read `libs/contracts/src/contracts/canonical/ohlcv.py` for the frozen-dataclass pattern.
2. Create `libs/contracts/src/contracts/canonical/fundamentals.py` with `CanonicalFundamentals` and 14 typed section dataclasses: `IncomeStatement`, `BalanceSheet`, `CashFlow`, `ValuationRatios`, `TechnicalsSnapshot`, `ShareStatistics`, `SplitsDividends`, `AnalystConsensus`, `EarningsHistory`, `EarningsTrend`, `EarningsAnnualTrend`, `DividendHistory`, `DividendSummary`, `OutstandingShares`. Top-level `CanonicalFundamentals` aggregates all sections as optional fields.
3. Implement `from_dict()` and `to_dict()` with nested handling for each section.
4. Before implementing, audit the legacy field mapping for duplicate dict keys — fix any found and note them in handoff evidence.
5. Update `canonical/__init__.py` to re-export `CanonicalFundamentals` and all 14 section types.
6. Write unit tests in `libs/contracts/tests/test_fundamentals.py`: `test_fundamentals_schema_version`, `test_fundamentals_roundtrip`, `test_fundamentals_optional_sections`, `test_fundamentals_frozen`, `test_individual_section_roundtrips`.
7. Update `docs/libs/contracts.md`.
8. Run: `cd libs/contracts && make test && make lint`.

**DoD**: `CanonicalFundamentals` + 14 section types frozen, `from_dict()`/`to_dict()` handles nested sections, all 5 tests pass, duplicate key audit note in handoff, docs updated.

---

### MD-004 — messaging.errors module

1. Create `libs/messaging/src/messaging/errors.py` with the following hierarchy:
   - `MessagingError(Exception)` — base
   - `RetryableError(MessagingError)` — with optional `retry_after_seconds: float | None = None`
   - `FatalError(MessagingError)` — base for non-recoverable errors
   - Sub-classes of `FatalError`: `DeserializationError`, `SchemaValidationError`
   - Sub-class of `RetryableError`: `BrokerUnavailableError`
2. Update `libs/messaging/src/messaging/__init__.py` to re-export all error classes.
3. Write unit tests in `libs/messaging/tests/test_errors.py`: `test_retryable_error_is_messaging_error`, `test_fatal_error_is_messaging_error`, `test_retryable_error_retry_after`, `test_error_hierarchy`.
4. Update `docs/libs/messaging.md` with an error hierarchy section (include the full inheritance tree and `retry_after_seconds` behaviour).
5. Run: `cd libs/messaging && make test && make lint`.

**DoD**: 6 error classes with correct hierarchy, `retry_after_seconds` on `RetryableError`, all 4 tests pass, docs updated.

---

### MD-006 — KafkaProducerConfig + producer factory

1. Read `libs/messaging/src/messaging/schemas.py` for Avro serialization/deserialization patterns.
2. Create `libs/messaging/src/messaging/producer.py`:
   - `KafkaProducerConfig` (pydantic `BaseSettings`) with fields: `bootstrap_servers: str`, `schema_registry_url: str`, `acks: str = "all"`, `retries: int = 3`, `linger_ms: int = 5`.
   - `build_serializing_producer(config: KafkaProducerConfig) -> SerializingProducer` factory.
   - Delivery callback helper `_on_delivery(err, msg)` — logs success or error via structlog.
3. Update `libs/messaging/src/messaging/__init__.py` re-exports.
4. Write unit tests (mock confluent_kafka) in `libs/messaging/tests/test_producer.py`: `test_producer_config_defaults`, `test_build_serializing_producer`, `test_delivery_callback_success`, `test_delivery_callback_failure`.
5. Update `docs/libs/messaging.md` with a producer API section.
6. Run: `cd libs/messaging && make test && make lint`.

**DoD**: `KafkaProducerConfig` + `build_serializing_producer()` + delivery callback, all 4 tests pass (mocked), docs updated.

---

### MD-008 — ValkeyClient async wrapper

1. Create `libs/messaging/src/messaging/valkey.py` with `ValkeyClient` class:
   - Constructor: `url: str`, `decode_responses: bool = True`.
   - Methods: `connect()`, `close()`, `get(key: str) -> str | None`, `set(key: str, value: str, ttl_seconds: int)`, `delete(key: str)`, `health_check() -> bool`.
   - Uses `redis.asyncio.Redis` underneath.
2. Update `libs/messaging/src/messaging/__init__.py` re-exports. Verify `redis` dependency is present in `pyproject.toml`; add it if missing.
3. Write unit tests (mock redis.asyncio) in `libs/messaging/tests/test_valkey.py`: `test_valkey_get_set_roundtrip`, `test_valkey_ttl_expiry`, `test_valkey_health_check`, `test_valkey_delete`.
4. Update `docs/libs/messaging.md` with a ValkeyClient API section.
5. Run: `cd libs/messaging && make test && make lint`.

**DoD**: `ValkeyClient` with 6 async methods using `redis.asyncio`, all 4 tests pass, docs updated.

---

### MD-009 — ObjectStorage ABC + S3ObjectStorage + health + exceptions

1. Create `libs/storage/src/storage/exceptions.py` with: `StorageError` (base), `ObjectNotFoundError(StorageError)`, `BucketNotFoundError(StorageError)`, `StoragePermissionError(StorageError)`, `StorageUnavailableError(StorageError)`.
2. Create `libs/storage/src/storage/object_storage.py`:
   - `ObjectStorage` ABC with abstract methods: `get(bucket, key) -> bytes`, `put(bucket, key, data, content_type)`, `delete(bucket, key)`, `exists(bucket, key) -> bool`, `get_json(bucket, key) -> dict`, `put_json(bucket, key, data)`.
   - `S3ObjectStorage(ObjectStorage)` concrete implementation using aiobotocore (or boto3 + `asyncio.to_thread` if aiobotocore is not available). Map boto3/botocore client errors to typed `StorageError` subclasses.
3. Create `libs/storage/src/storage/health.py` with `check_storage_health(client: ObjectStorage, bucket: str) -> bool`.
4. Create `build_object_storage(settings: StorageSettings) -> ObjectStorage` factory. Update `libs/storage/src/storage/__init__.py`.
5. Write unit tests (mock boto3) in `libs/storage/tests/test_object_storage.py`: all 6 abstract methods, object-not-found path, health check pass/fail, factory construction.
6. Update `docs/libs/storage.md` with: ObjectStorage API, exception hierarchy, ABC abstract methods table (method → when called → what to do → what to return), usage example, `## Common Pitfalls` with ≥3 entries.
7. Run: `cd libs/storage && make test && make lint`.

**DoD**: `ObjectStorage` ABC + `S3ObjectStorage` + exceptions + health + factory, all method tests + not-found + health + factory pass, docs updated with ABC table and Common Pitfalls.

---

### MD-010 — Prometheus ServiceMetrics + middleware

1. Create `libs/observability/src/observability/metrics.py`:
   - `ServiceMetrics` class with: `requests_total` (Counter), `request_duration_seconds` (Histogram), `active_connections` (Gauge), `errors_total` (Counter, label: `error_type`).
   - `create_metrics(service_name: str) -> ServiceMetrics` factory — registers all metrics with prometheus_client.
   - `add_prometheus_middleware(app: FastAPI, metrics: ServiceMetrics)` — instruments all routes, mounts `/metrics` endpoint.
   - `get_metrics_endpoint() -> Response`.
2. Update `libs/observability/src/observability/__init__.py` re-exports.
3. Write unit tests in `libs/observability/tests/test_metrics.py`: `test_create_metrics_counters`, `test_metrics_middleware_increments`, `test_metrics_endpoint_format`.
4. Update `docs/libs/observability.md` with a metrics API section, usage example, and `## Common Pitfalls` with ≥3 entries if not already present.
5. Run: `cd libs/observability && make test && make lint`.

**DoD**: 4 metric types + factory + middleware + endpoint, all 3 tests pass, docs updated.

---

### MD-011 — configure_tracing + OTel middleware

1. Create `libs/observability/src/observability/tracing.py`:
   - `configure_tracing(service_name: str, otlp_endpoint: str | None = None)` — sets up OTLP gRPC exporter + `BatchSpanProcessor`; falls back to no-op if `otlp_endpoint` is `None`.
   - `get_tracer(name: str) -> Tracer`.
   - `add_otel_middleware(app: FastAPI)` — instruments FastAPI with `OpenTelemetryMiddleware`.
   - `shutdown_tracing()` — flushes and shuts down the span processor.
2. Update `libs/observability/src/observability/__init__.py` re-exports.
3. Write unit tests in `libs/observability/tests/test_tracing.py`: `test_configure_tracing`, `test_get_tracer_returns_tracer`, `test_add_otel_middleware`.
4. Update `docs/libs/observability.md` with a tracing API section and usage example.
5. Run: `cd libs/observability && make test && make lint`.

**DoD**: 4 tracing functions implemented, no-op mode when endpoint is None, all 3 tests pass, docs updated.

---

### MD-012 — Domain entities, value objects, enums

1. Create `services/market-data/src/market_data/domain/enums.py` with:
   - `Timeframe` (`StrEnum`): `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, `1M`.
   - `DatasetType` (`StrEnum`): `OHLCV`, `QUOTE`, `FUNDAMENTALS`.
   - `Provider` (`StrEnum`, with priority values).
   - `PeriodType` (`StrEnum`): `ANNUAL`, `QUARTERLY`.
   - `FundamentalsSection` (`StrEnum`, 13 sections matching the section dataclasses in MD-002).
2. Create `services/market-data/src/market_data/domain/value_objects.py` with frozen dataclasses:
   - `ProviderPriority` — wraps provider priority ordering.
   - `InstrumentFlags` — `has_ohlcv: bool`, `has_quotes: bool`, `has_fundamentals: bool`.
3. Create `services/market-data/src/market_data/domain/entities.py` with:
   - `Security` — UUID (UUIDv7 via `common.ids`), figi, isin, name, sector, industry, country, currency.
   - `Instrument` — UUID, FK security, symbol, exchange, `InstrumentFlags`.
   - `OHLCVBar` — instrument_id, timeframe, bar_date, OHLCV fields (Decimal precision), adjusted_close, provider_priority.
   - `Quote` — instrument_id, bid, ask, last, volume, timestamp.
   - Fundamentals entities aligned with the 14 section types from MD-002.
4. Create `services/market-data/src/market_data/domain/__init__.py` — package marker, re-export public symbols.
5. Write unit tests:
   - `tests/unit/test_domain_entities.py`: `test_timeframe_enum_values`, `test_dataset_type_enum`, `test_provider_priority_ordering`, `test_security_entity`, `test_instrument_entity_flags`, `test_ohlcv_bar_entity`, `test_quote_entity`.
   - `tests/unit/test_value_objects.py`: construction, immutability, field access.
6. Update `docs/services/market-data.md` domain model section with entity fields, enum values, and ER relationships.
7. Run: `cd services/market-data && make test -- tests/unit/test_domain_entities.py tests/unit/test_value_objects.py && make lint`.

**DoD**: 5 enums, 2 value objects, ≥4 entities, UUIDv7 IDs, all 7+ unit tests pass, domain model section in `docs/services/market-data.md` updated.

---

### MD-003 — contracts.parsing module (after MD-001, MD-002)

1. Create `libs/contracts/src/contracts/parsing.py` with:
   - `parse_ohlcv_jsonl(raw: bytes) -> list[CanonicalOHLCVBar]` — handles UTF-8 and UTF-8-BOM.
   - `parse_quotes_json(raw: bytes) -> CanonicalQuote`.
   - `parse_fundamentals_json(raw: bytes) -> CanonicalFundamentals`.
   - `ParseError(FatalError)` — raised on malformed or incomplete data; import `FatalError` from `libs/messaging/errors.py`.
2. Update `libs/contracts/src/contracts/__init__.py` re-exports.
3. Write unit tests with fixture data in `libs/contracts/tests/test_parsing.py`:
   - `test_parse_ohlcv_jsonl_valid`
   - `test_parse_ohlcv_jsonl_empty`
   - `test_parse_ohlcv_jsonl_malformed_line`
   - `test_parse_quotes_json_valid`
   - `test_parse_quotes_json_missing_fields`
   - `test_parse_fundamentals_json_valid`
   - `test_parse_fundamentals_json_partial_sections`
4. Update `docs/libs/contracts.md` with a parsing API reference section, including `ParseError` and encoding-handling behaviour.
5. Run: `cd libs/contracts && make test && make lint`.

**DoD**: 3 parse functions + `ParseError`, all 7 tests pass (including error-path tests), docs updated.

---

### MD-005 — BaseKafkaConsumer abstract base class (after MD-004)

1. Read the legacy `BaseKafkaConsumer` patterns referenced in the planning response §1.7.
2. Create `libs/messaging/src/messaging/consumer.py` with `BaseKafkaConsumer[TFailure]` generic ABC:
   - Constructor: `bootstrap_servers: str`, `schema_registry_url: str`, `group_id: str`, `topics: list[str]`, `max_poll_interval_ms: int`.
   - Abstract methods: `process_message(msg) -> None`, `on_fatal_error(msg, error) -> TFailure`.
   - Lifecycle: `start()`, `stop()`, `run()` loop.
   - **Key design**: run confluent_kafka blocking `poll()` inside `asyncio.to_thread` — do not use threading.
   - Error handling: `RetryableError` → NACK (do not commit offset); `FatalError` → call `on_fatal_error()` then commit offset; unknown exception → wrap as `FatalError` then follow fatal path.
   - Graceful shutdown via `asyncio.Event`.
3. Update `libs/messaging/src/messaging/__init__.py` re-exports.
4. Write unit tests in `libs/messaging/tests/test_consumer.py`:
   - `test_consumer_graceful_shutdown`
   - `test_consumer_retryable_error_handling`
   - `test_consumer_fatal_error_handling`
   - `test_consumer_commit_after_process`
   - `test_consumer_deserialize_avro_message`
5. Update `docs/libs/messaging.md` with:
   - BaseKafkaConsumer API section.
   - ABC abstract methods table (method → when called → what to do → what to return).
   - Concrete usage example (minimal subclass).
   - Error handling behaviour table (error type → consumer action).
6. Run: `cd libs/messaging && make test && make lint`.

**DoD**: Generic `BaseKafkaConsumer` with `asyncio.to_thread` poll, correct error routing, graceful shutdown, all 5 tests pass, ABC table + usage example in docs.

---

### MD-007 — BaseOutboxDispatcher with lease-based dispatch (after MD-006)

1. Read the legacy `BaseOutboxDispatcher` patterns referenced in the planning response.
2. Create `libs/messaging/src/messaging/outbox.py` with `BaseOutboxDispatcher` ABC:
   - Constructor: SQLAlchemy `AsyncSession` factory, `SerializingProducer`, `poll_interval_seconds: int = 10`, `lease_duration_seconds: int = 60`, `stale_threshold_seconds: int = 300`.
   - Concrete methods: `start()`, `stop()`, `_poll_pending()`, `_claim_event(event_id)`, `_dispatch(event)`, `_release_stale()`.
   - Hybrid dispatch: immediate NOTIFY on commit + polling fallback.
   - Lease: `worker_id = f"{socket.gethostname()}-{os.getpid()}"`.
   - **Fix legacy bug**: serialize `Decimal` and `UUID` fields to strings before JSON encoding.
   - Max 5 dispatch attempts; move to `DEAD` status after exhausting retries.
3. Update `libs/messaging/src/messaging/__init__.py` re-exports.
4. Write unit tests in `libs/messaging/tests/test_outbox.py`:
   - `test_outbox_claim_event`
   - `test_outbox_release_stale`
   - `test_outbox_retry_backoff`
   - `test_outbox_max_attempts_dead`
   - `test_outbox_decimal_uuid_serialization`
5. Update `docs/libs/messaging.md` with:
   - Outbox dispatcher API section.
   - Mermaid sequence diagram of the 3-phase dispatch (claim → produce → finalize) — required because this flow has ≥3 components and ≥4 steps.
   - Lease mechanism explanation.
   - ABC abstract methods table.
6. Run: `cd libs/messaging && make test && make lint`.

**DoD**: `BaseOutboxDispatcher` with hybrid dispatch, lease claiming, Decimal/UUID serialization fix, dead-letter after 5 attempts, all 5 tests pass, Mermaid diagram + ABC table in docs.

---

### MD-013 — Domain events + error hierarchy (after MD-004)

1. Create `services/market-data/src/market_data/domain/events.py` with:
   - `DomainEvent` frozen dataclass base: `event_id: str` (UUIDv7, auto-generated), `event_type: str`, `schema_version: int`, `occurred_at: str` (ISO-8601 UTC via `utc_now()`), `correlation_id: str | None = None`, `causation_id: str | None = None`.
   - `InstrumentCreated(DomainEvent)`: `event_type = "market.instrument.created"`, `schema_version = 1`. Include all instrument fields.
   - `InstrumentUpdated(DomainEvent)`: `event_type = "market.instrument.updated"`, `schema_version = 1`.
2. Create `services/market-data/src/market_data/domain/errors.py` with:
   - `MarketDataError(Exception)` — base.
   - `InstrumentNotFoundError(MarketDataError)`
   - `SecurityNotFoundError(MarketDataError)`
   - `DuplicateEventError(MarketDataError)`
   - `IngestionError(MarketDataError)`
   - `ParseError(MarketDataError, FatalError)` — multiple inheritance; import `FatalError` from `libs/messaging`.
   - `StaleDataError(MarketDataError)`
3. Write unit tests:
   - `tests/unit/test_domain_events.py`: `test_instrument_created_event_envelope`, `test_instrument_updated_event_envelope`, `test_domain_event_auto_fields`.
   - `tests/unit/test_domain_errors.py`: `test_error_hierarchy`.
4. Update `docs/services/market-data.md` events section and error hierarchy section.
5. Run: `cd services/market-data && make test -- tests/unit/test_domain_events.py tests/unit/test_domain_errors.py && make lint`.

**DoD**: 2 domain events + `DomainEvent` base with auto envelope fields, 6-class error hierarchy including multiple-inheritance `ParseError`, all 4 tests pass, docs updated.

---

## Constraints

- Do not implement any code outside the task IDs listed in this wave (MD-001 through MD-013).
- No application layer, no infrastructure layer, no API entrypoints, no Alembic migrations.
- Do not modify existing lib files beyond re-exports in `__init__.py` and corresponding doc updates.
- Do not write service-level DB models — that is wave 02 (MD-014).
- Keep lib tasks isolated from service domain tasks (separate directories, no cross-imports except `libs/messaging.errors` in `contracts.parsing` and `market_data.domain.errors`).
- One logical change per edit. Do not combine unrelated changes in a single diff.
- All timestamps must use `utc_now()` from `libs/common` or `datetime.now(tz=timezone.utc)`. Never use naive datetimes.

---

## Required tests

### Lib tests (run from each lib's directory)

```bash
cd libs/contracts && make test && make lint
cd libs/messaging && make test && make lint
cd libs/storage && make test && make lint
cd libs/observability && make test && make lint
```

### Service domain tests

```bash
cd services/market-data && make test -- tests/unit/ && make lint
```

### Global lint

```bash
./scripts/lint.sh
```

**Pass criteria:**
- All unit tests pass (`pytest` exit code 0).
- `ruff check` reports zero errors across all changed files.
- `mypy --strict` reports zero errors across all changed files.
- No regressions in previously passing tests.

---

## Documentation requirements

For every task in this wave, update docs **in the same wave** for any change to behaviour, contracts, config, schema, or API surface.

| Change type | File to update |
|-------------|---------------|
| New CanonicalQuote, CanonicalFundamentals | `docs/libs/contracts.md` — add to public API surface table |
| New parsing API | `docs/libs/contracts.md` — add parsing API reference section |
| New error hierarchy | `docs/libs/messaging.md` — add error hierarchy section |
| New consumer ABC | `docs/libs/messaging.md` — add consumer API section, ABC table, usage example |
| New producer API | `docs/libs/messaging.md` — add producer API section |
| New Valkey client | `docs/libs/messaging.md` — add ValkeyClient API section |
| New outbox dispatcher | `docs/libs/messaging.md` — add outbox API section, Mermaid diagram, ABC table |
| New ObjectStorage ABC + S3 impl | `docs/libs/storage.md` — add API, exception hierarchy, ABC table, Common Pitfalls |
| New metrics + tracing | `docs/libs/observability.md` — add metrics and tracing API sections |
| New domain entities, enums, value objects | `docs/services/market-data.md` — update domain model section |
| New domain events | `docs/services/market-data.md` — update events section |
| New domain error hierarchy | `docs/services/market-data.md` — update errors section |

**Mandatory instruction**: If any implementation changes a behaviour, contract, config, schema surface, or test surface described in documentation, you MUST update that documentation in this same wave. List every doc file changed in the handoff evidence.

**Documentation quality gate**: Before marking this wave done, verify all 8 criteria from the Documentation quality standard and include the quality checklist table in handoff evidence. All criteria must be ✓ or explicitly N/A with justification.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description of the change.

### 2. Tests run and results

```
libs/contracts:       X tests, X passed, 0 failed
libs/messaging:       X tests, X passed, 0 failed
libs/storage:         X tests, X passed, 0 failed
libs/observability:   X tests, X passed, 0 failed
services/market-data (domain): X tests, X passed, 0 failed
./scripts/lint.sh:    exit code 0
```

### 3. Documentation changed (exact files + what was updated)

Example format:
- `docs/libs/contracts.md` — added `CanonicalQuote` and `CanonicalFundamentals` to public API surface table; added parsing API reference section with `ParseError` behaviour.
- `docs/libs/messaging.md` — added error hierarchy, producer API, consumer API (with ABC table and usage example), ValkeyClient API, outbox dispatcher API (with Mermaid diagram and ABC table).

### 4. Unresolved blockers

List anything that could not be implemented as specified and why. State `none` if there are no blockers.

### 5. Documentation quality checklist

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Accuracy — endpoints, fields, event types, config vars match implementation | ✓ / ⚠️ / N/A | |
| 2 | Diagrams for non-trivial flows (≥3 components or ≥4 steps → Mermaid) | ✓ / ⚠️ / N/A | |
| 3 | Realistic code examples — every new public class/function has working usage example | ✓ / ⚠️ / N/A | |
| 4 | Abstract methods documented — ABC table (method → when called → what to do → what to return) | ✓ / ⚠️ / N/A | |
| 5 | Common Pitfalls section — `docs/services/market-data.md` and updated lib docs have ≥3 entries | ✓ / ⚠️ / N/A | |
| 6 | Lib docs updated — every touched `libs/` file has corresponding `docs/libs/<lib>.md` update | ✓ / ⚠️ / N/A | |
| 7 | Service doc reflects final state — `docs/services/market-data.md` matches implementation | ✓ / ⚠️ / N/A | |
| 8 | No orphan documentation — no docs for unimplemented code | ✓ / ⚠️ / N/A | |

### 6. Commit message proposal

```
feat(libs+market-data/domain): foundation libs + domain layer for market-data migration (MD-001..MD-013)

Add CanonicalQuote, CanonicalFundamentals, and contracts.parsing to contracts lib; implement
messaging.errors, BaseKafkaConsumer, KafkaProducerConfig, BaseOutboxDispatcher, ValkeyClient
to messaging lib; implement ObjectStorage ABC + S3ObjectStorage + health to storage lib;
implement ServiceMetrics + OTel tracing to observability lib; port complete market_data
domain layer with enums, entities, value objects, domain events and error hierarchy. All unit
tests pass; ruff + mypy strict clean.
```

---

## Definition of done

- [ ] MD-001: `CanonicalQuote` frozen dataclass with `from_dict()`/`to_dict()`, `schema_version` matches constant, 4 unit tests pass, `docs/libs/contracts.md` updated.
- [ ] MD-002: `CanonicalFundamentals` + 14 section types, nested `from_dict()`/`to_dict()`, duplicate key audit complete, 5 unit tests pass, `docs/libs/contracts.md` updated.
- [ ] MD-003: 3 parse functions + `ParseError`, UTF-8/BOM handling, 7 unit tests pass, `docs/libs/contracts.md` parsing section added.
- [ ] MD-004: 6-class error hierarchy with `retry_after_seconds` on `RetryableError`, 4 unit tests pass, `docs/libs/messaging.md` error hierarchy section added.
- [ ] MD-005: `BaseKafkaConsumer` generic ABC with `asyncio.to_thread` poll, correct error routing, graceful shutdown, 5 unit tests pass, ABC table + usage example in `docs/libs/messaging.md`.
- [ ] MD-006: `KafkaProducerConfig` + `build_serializing_producer()` + delivery callback, 4 unit tests pass (mocked), `docs/libs/messaging.md` producer section added.
- [ ] MD-007: `BaseOutboxDispatcher` with hybrid dispatch, lease claiming, Decimal/UUID fix, dead-letter at 5 attempts, 5 unit tests pass, Mermaid diagram + ABC table in `docs/libs/messaging.md`.
- [ ] MD-008: `ValkeyClient` with 6 async methods, `redis.asyncio` dependency verified, 4 unit tests pass, `docs/libs/messaging.md` ValkeyClient section added.
- [ ] MD-009: `ObjectStorage` ABC + `S3ObjectStorage` + 5 exceptions + health + factory, all method tests + not-found + health + factory pass, `docs/libs/storage.md` updated with ABC table and `## Common Pitfalls`.
- [ ] MD-010: 4 metric types + `create_metrics()` + middleware + endpoint, 3 unit tests pass, `docs/libs/observability.md` metrics section added.
- [ ] MD-011: 4 tracing functions, no-op fallback, 3 unit tests pass, `docs/libs/observability.md` tracing section added.
- [ ] MD-012: 5 enums, 2 value objects, ≥4 entities with UUIDv7 IDs, 7+ unit tests pass, domain model section in `docs/services/market-data.md` updated.
- [ ] MD-013: `DomainEvent` base + `InstrumentCreated` + `InstrumentUpdated`, 6-class error hierarchy with multiple-inheritance `ParseError`, 4 unit tests pass, events and errors sections in `docs/services/market-data.md` updated.
- [ ] All lib `__init__.py` exports updated for every task above.
- [ ] All lib docs updated (`docs/libs/contracts.md`, `docs/libs/messaging.md`, `docs/libs/storage.md`, `docs/libs/observability.md`).
- [ ] Domain model, events, and error sections in `docs/services/market-data.md` updated.
- [ ] `docs/libs/messaging.md` and `docs/libs/storage.md` include `## Common Pitfalls` with ≥3 entries each.
- [ ] `docs/services/market-data.md` includes `## Common Pitfalls` with ≥3 entries.
- [ ] Documentation quality gate: all 8 criteria confirmed ✓ or N/A with justification — no criterion left blank.
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] Commit message proposal included in handoff evidence.
