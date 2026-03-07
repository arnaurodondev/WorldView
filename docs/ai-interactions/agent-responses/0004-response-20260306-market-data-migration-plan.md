# 0004 — Market Data Migration Detailed Plan & Atomic Tasks

| Metadata         | Value                                          |
| ---------------- | ---------------------------------------------- |
| **Prompt**       | `0004-market-data-migration-detailed-plan-and-atomic-tasks.md` |
| **Date**         | 2026-03-06                                     |
| **Agents**       | Data Platform Engineer + Architecture Decision Lead |
| **Scope**        | Market Data service full migration plan         |
| **Output**       | Plan only — no code produced                   |

---

## Table of Contents

1. [Legacy Capability Inventory](#1-legacy-capability-inventory)
2. [Target Capability Checklist](#2-target-capability-checklist)
3. [Gap & Risk Matrix](#3-gap--risk-matrix)
4. [Atomic Independent Ticket Backlog](#4-atomic-independent-ticket-backlog)
5. [Milestone-Based Execution Plan & Critical Path](#5-milestone-based-execution-plan--critical-path)
6. [Release Gate Checklist & Rollback Triggers](#6-release-gate-checklist--rollback-triggers)

---

## 1. Legacy Capability Inventory

### 1.1 Technology Stack

| Component        | Technology                                     |
| ---------------- | ---------------------------------------------- |
| Language         | Python 3.12                                    |
| Web framework    | FastAPI                                        |
| ORM              | SQLAlchemy 2.0 async (asyncpg driver)          |
| Database         | PostgreSQL (LIST-partitioned OHLCV, 26 tables) |
| Messaging        | confluent-kafka with Avro + Schema Registry    |
| Object store     | MinIO (S3 API) via boto3                       |
| Cache            | Valkey (Redis-compatible)                      |
| Migrations       | Alembic (async)                                |
| Observability    | structlog + Prometheus (partial)               |

### 1.2 Database Tables (26 total)

| Category              | Tables                                                                 |
| --------------------- | ---------------------------------------------------------------------- |
| Core entities          | `securities`, `instruments`                                            |
| Market data            | `ohlcv_bars` (9 LIST partitions by timeframe), `quotes`               |
| Fundamentals (Type A)  | `income_statements`, `balance_sheets`, `cash_flow_statements`          |
| Fundamentals (Type B)  | `valuation_ratios`, `technicals_snapshots`, `share_statistics`, `splits_dividends`, `analyst_consensus` |
| Fundamentals (Type C)  | `earnings_history`, `earnings_trends`, `earnings_annual_trends`        |
| Fundamentals (Type D)  | `dividend_history`, `dividend_summary`, `outstanding_shares`           |
| Fundamentals (Type E)  | `esg_scores`                                                                                         |
| Infrastructure         | `ingestion_events`, `failed_tasks`, `outbox_events`                    |

**OHLCV partitioning**: Native PostgreSQL `LIST` partitioning on `timeframe` column with 9 child tables (`ohlcv_bars_1m` through `ohlcv_bars_1M`). Composite PK `(instrument_id, timeframe, bar_date)`. Descending index on `(instrument_id, bar_date DESC)`.

### 1.3 Kafka Consumers (3)

| Consumer Group              | Topic                    | Purpose                                       |
| --------------------------- | ------------------------ | ---------------------------------------------- |
| `market-data-ohlcv`        | `market.dataset.fetched` | Claim-check → S3 download → parse OHLCV JSONL → bulk upsert with provider priority |
| `market-data-quotes`       | `market.dataset.fetched` | Claim-check → S3 download → parse quotes JSON → upsert latest quote + cache invalidation |
| `market-data-fundamentals` | `market.dataset.fetched` | Claim-check → S3 download → parse fundamentals JSON → 13-section decomposition → 20-table merge-upsert |

### 1.4 Kafka Producers (via Outbox)

| Event Type                   | Topic                           | Trigger                        |
| ---------------------------- | ------------------------------- | ------------------------------ |
| `instrument.created`         | `market.instrument.created`     | First-seen instrument during OHLCV/quotes ingestion |
| `instrument.updated`         | `market.instrument.updated`     | Instrument flag changes        |

### 1.5 API Endpoints (22 routes)

| Group          | Endpoints                                                                                      |
| -------------- | ---------------------------------------------------------------------------------------------- |
| Health (3)     | `GET /healthz`, `GET /readyz`, `GET /metrics`                                                  |
| Instruments (3)| `GET /api/v1/instruments` (search/filter), `GET /api/v1/instruments/{id}`, `GET /api/v1/instruments/symbol/{symbol}` |
| Quotes (3)     | `GET /api/v1/quotes/{instrument_id}`, `POST /api/v1/quotes/batch`, `GET /api/v1/quotes/latest` |
| OHLCV (4)      | `GET /api/v1/ohlcv/{instrument_id}` (with timeframe/start/end), `GET /api/v1/ohlcv/{id}/timeframes`, `GET /api/v1/ohlcv/{id}/range`, `GET /api/v1/ohlcv/bulk` |
| Fundamentals (9)| `GET /api/v1/fundamentals/{security_id}` (full), per-section: `income-statement`, `balance-sheet`, `cash-flow`, `valuation`, `analyst-consensus`, `dividends`, `earnings`, `securities` list/detail |

### 1.6 Architectural Patterns

| Pattern                      | Implementation                                                        |
| ---------------------------- | --------------------------------------------------------------------- |
| **Claim-check**              | Kafka carries S3 pointer (`bucket`, `object_key`, `content_type`, `dataset_type`); consumer downloads from MinIO, parses payload |
| **Transactional outbox**     | Domain events written to `outbox_events` in same DB transaction; `OutboxDispatcher` with hybrid immediate NOTIFY + 10s polling |
| **Lease-based dispatch**     | Outbox rows locked with `worker_id=hostname-pid`, 60s lease, stale release at 300s |
| **Provider priority**        | OHLCV: SQL `ON CONFLICT DO UPDATE WHERE EXCLUDED.provider_priority >= current.provider_priority`; Fundamentals: application-level check |
| **Idempotency**              | `ingestion_events` table with UNIQUE `event_id`; check-then-insert in UoW |
| **Failed task recovery**     | 5 max attempts, exponential backoff (30s base, 1h cap, ±20% jitter), background retry worker polls every 60s |
| **Caching**                  | Valkey cache-aside for quotes only; key pattern `quote:{instrument_id}`, TTL 5s |
| **Read/write splitting**     | Separate SQLAlchemy sessions for read vs write via Unit of Work |
| **Unit of Work**             | Wraps 25+ repositories, commits/rollbacks as single transaction, outbox notification on commit |

### 1.7 Shared Library Dependencies

| Library          | Used Components                                                         |
| ---------------- | ----------------------------------------------------------------------- |
| `libs/messaging` | `BaseKafkaConsumer` (~576 LOC), `BaseOutboxDispatcher` (~536 LOC), `ValkeyClient`, Avro ser/deser, topic constants |
| `libs/storage`   | `S3ObjectStorage`, `KeyBuilder`, `StorageSettings`, exception hierarchy |
| `libs/contracts` | `CanonicalOHLCVBar`, JSONL/JSON/Parquet parsing, schema versions        |
| `libs/common`    | `utc_now()`, `ensure_utc()`, ISO-8601 parsing, bar date parsing         |

### 1.8 Known Issues in Legacy

| Issue                            | Severity | Detail                                           |
| -------------------------------- | -------- | ------------------------------------------------ |
| Outbox serialization bug         | Medium   | Decimal/UUID not JSON-serializable in outbox payload |
| No historical backfill           | Low      | Only forward-fill; no mechanism to request historical data |
| Incomplete fundamentals API      | Medium   | Some endpoints not fully wired                   |
| Field mapping duplicate keys     | Low      | Dict literal with duplicate keys in fundamentals mapping |
| Migration↔Model column mismatch | High     | `failed_tasks` and `outbox_events` models don't match migration 002 |

---

## 2. Target Capability Checklist

### 2.1 Currently Implemented (worldview)

| Component                          | Status       | Notes                                           |
| ---------------------------------- | ------------ | ----------------------------------------------- |
| `libs/common/time.py`             | ✅ Complete   | `utc_now`, `ensure_utc`, ISO/bar-date parsing, fully tested |
| `libs/common/ids.py`              | ✅ Complete   | `new_uuid`, `new_uuid_str`, `new_ulid`          |
| `libs/common/types.py`            | ✅ Complete   | All NewType aliases                              |
| `libs/contracts/versions.py`      | ✅ Complete   | 6 schema version constants                      |
| `libs/contracts/canonical/ohlcv`  | ✅ Complete   | `CanonicalOHLCVBar` frozen dataclass + tests     |
| `libs/messaging/schemas.py`       | ✅ Complete   | `AvroDictable`, Avro ser/deser, schema loading   |
| `libs/messaging/topics.py`        | ✅ Complete   | 9 topic constants including market-data ones      |
| `libs/storage/key_builder.py`     | ✅ Complete   | `KeyBuilder.build()` + `validate()`              |
| `libs/storage/settings.py`        | ✅ Complete   | `StorageSettings` pydantic model                 |
| `libs/observability/logging.py`   | ✅ Complete   | structlog integration                            |
| `services/market-data/config.py`  | ✅ Complete   | `Settings` with 10 env vars                     |
| `services/market-data/app.py`     | ⚠️ Scaffold   | `healthz` + `readyz` only — no routers, no lifespan |
| `services/market-data/tests/`     | ✅ Complete   | Health endpoint tests + conftest                 |
| Alembic infrastructure            | ⚠️ Scaffold   | `env.py` exists but `target_metadata = None`, zero migrations |
| All documentation                 | ✅ Complete   | MASTER_PLAN, AGENTS, CLAUDE, RULES, per-service docs, ADRs |

### 2.2 Not Yet Implemented

| Component                                | Priority | Legacy Reference                        |
| ---------------------------------------- | -------- | --------------------------------------- |
| `contracts.canonical.quotes`             | P0       | Quote frozen dataclass                  |
| `contracts.canonical.fundamentals`       | P0       | Fundamentals frozen dataclass           |
| `contracts.parsing`                      | P0       | JSONL/JSON/Parquet parsing utilities    |
| `messaging.consumer`                     | P0       | `BaseKafkaConsumer` abstract class      |
| `messaging.producer`                     | P0       | `KafkaProducerConfig`, producer factory |
| `messaging.outbox`                       | P0       | `BaseOutboxDispatcher` abstract class   |
| `messaging.valkey`                       | P0       | `ValkeyClient` async wrapper            |
| `messaging.errors`                       | P0       | `RetryableError`, `FatalError`          |
| `storage.object_storage`                 | P0       | `ObjectStorage` ABC + `S3ObjectStorage` |
| `storage.exceptions`                     | P0       | `ObjectNotFoundError` etc.              |
| `storage.health`                         | P1       | `check_storage_health()`               |
| `observability.metrics`                  | P1       | Prometheus metrics                      |
| `observability.tracing`                  | P1       | OpenTelemetry tracing                   |
| Market-data domain layer                 | P0       | Entities, value objects, events, errors |
| Market-data application layer            | P0       | Use cases, ports (repository ABCs)      |
| Market-data infrastructure/db            | P0       | SQLAlchemy models, repositories, UoW    |
| Market-data infrastructure/messaging     | P0       | 3 Kafka consumers + outbox dispatcher   |
| Market-data API layer                    | P0       | 16 business endpoints (FastAPI routers) |
| Market-data Alembic migrations           | P0       | TimescaleDB hypertable + all tables     |
| Market-data Valkey caching               | P1       | Cache-aside for quotes                  |

---

## 3. Gap & Risk Matrix

### 3.1 Functional Gaps

| ID   | Gap Description                                           | Severity   | Impact if Unresolved                          |
| ---- | --------------------------------------------------------- | ---------- | --------------------------------------------- |
| G-01 | No Kafka consumer infrastructure (`BaseKafkaConsumer`)     | 🔴 Critical | Cannot consume any events; all 3 consumers blocked |
| G-02 | No object storage client (`S3ObjectStorage`)               | 🔴 Critical | Cannot download claim-check payloads          |
| G-03 | No claim-check parsing (`contracts.parsing`)               | 🔴 Critical | Cannot parse JSONL/JSON/Parquet datasets       |
| G-04 | No database models or migrations                           | 🔴 Critical | No schema; service cannot persist anything     |
| G-05 | No OHLCV materializer consumer                             | 🔴 Critical | Core market data pipeline blocked              |
| G-06 | No quotes consumer                                         | 🔴 Critical | No real-time quotes                            |
| G-07 | No fundamentals consumer                                   | 🔴 Critical | No fundamental data                            |
| G-08 | No API endpoints beyond health                             | 🔴 Critical | No data queryable by downstream services       |
| G-09 | No outbox dispatcher                                       | 🟠 High     | Instrument lifecycle events not emitted         |
| G-10 | No Valkey client (`messaging.valkey`)                      | 🟡 Medium   | No caching; higher DB load but functionally OK |
| G-11 | No `CanonicalQuote` contract                               | 🟠 High     | Quotes consumer has no target data model        |
| G-12 | No `CanonicalFundamentals` contract                        | 🟠 High     | Fundamentals consumer has no target data model  |
| G-13 | No Prometheus metrics library                              | 🟡 Medium   | No `/metrics` endpoint; observability gap       |
| G-14 | No OpenTelemetry tracing library                           | 🟡 Medium   | No distributed tracing                          |
| G-15 | No error hierarchy (`RetryableError`, `FatalError`)        | 🟠 High     | Consumer error classification not possible      |
| G-16 | Alembic `target_metadata` not wired                        | 🟠 High     | Auto-generate migrations won't work             |
| G-17 | `pyproject.toml` missing shared lib dependencies           | 🟠 High     | Can't import any shared lib                     |
| G-18 | No Unit of Work pattern                                    | 🟠 High     | No transactional consistency guarantee          |
| G-19 | No producer / serializing producer                         | 🟠 High     | Outbox dispatcher cannot produce to Kafka       |

### 3.2 Architectural Risks

| ID   | Risk                                                       | Severity   | Mitigation                                    |
| ---- | ---------------------------------------------------------- | ---------- | --------------------------------------------- |
| R-01 | TimescaleDB vs LIST partitioning decision                   | 🟠 High     | Legacy uses LIST partitioning; docs specify TimescaleDB hypertable. Must decide and implement one. **Recommendation: TimescaleDB** (per docs/MASTER_PLAN) |
| R-02 | Legacy outbox serialization bug may be copied               | 🟡 Medium   | Fix Decimal/UUID serialization during migration |
| R-03 | Legacy migration↔model column mismatch                      | 🟠 High     | Fresh schema in worldview — verify model matches migration |
| R-04 | Fundamentals field mapping duplicate keys                   | 🟡 Medium   | Audit and fix dict literals during migration    |
| R-05 | 20+ fundamentals tables create large migration surface      | 🟡 Medium   | Split into logical migration files              |
| R-06 | Consumer concurrency model change (legacy sync → async)     | 🟠 High     | Legacy `BaseKafkaConsumer` uses threading; worldview should be async-first. Requires careful redesign |
| R-07 | No integration test infrastructure exists                   | 🟠 High     | Must set up testcontainers before consumer testing |
| R-08 | Event schema backward compatibility                         | 🟡 Medium   | Verify Avro schemas are forward-compatible with Schema Registry |
| R-09 | No historical backfill mechanism                            | 🟡 Medium   | Accept as known limitation; add task for future |
| R-10 | Provider priority SQL differs between OHLCV and fundamentals| 🟡 Medium   | Document both patterns; unit test each          |

### 3.3 Testing Gaps

| ID   | Gap                                                        | Severity   | Required Action                               |
| ---- | ---------------------------------------------------------- | ---------- | --------------------------------------------- |
| T-01 | No testcontainers setup for integration tests              | 🟠 High     | Create conftest with Postgres + Kafka + MinIO + Valkey containers |
| T-02 | No contract tests for Avro schemas                         | 🟡 Medium   | Add schema compatibility tests                 |
| T-03 | No platform QA test infrastructure                         | 🟡 Medium   | Create end-to-end test harness                 |
| T-04 | `libs/common/ids.py` has no tests                          | 🟢 Low      | Add unit tests                                 |

---

## 4. Atomic Independent Ticket Backlog

### Dependency Graph (high-level)

```
Phase 0: Foundation (libs)
  ├─ MD-001 → MD-002 → MD-003 (contracts)
  ├─ MD-004 → MD-005 → MD-006 → MD-007 (messaging)
  ├─ MD-008 → MD-009 (storage)
  └─ MD-010 → MD-011 (observability)

Phase 1: Domain + Schema
  ├─ MD-012 (domain entities)
  ├─ MD-013 (domain events + errors)
  └─ MD-014 → MD-015 (DB models + migrations)

Phase 2: Data Access
  ├─ MD-016 (repositories)
  ├─ MD-017 (Unit of Work)
  └─ MD-018 (query layer)

Phase 3: Consumers
  ├─ MD-019 (OHLCV materializer)
  ├─ MD-020 (quotes consumer)
  └─ MD-021 (fundamentals consumer)

Phase 4: API
  ├─ MD-022 → MD-023 → MD-024 → MD-025 (endpoint groups)
  └─ MD-026 (caching)

Phase 5: Outbox + Events
  └─ MD-027 (outbox dispatcher)

Phase 6: Integration + QA
  ├─ MD-028 (integration test infra)
  ├─ MD-029 (container tests)
  └─ MD-030 (platform QA)

Phase 7: Hardening
  ├─ MD-031 (docs update)
  ├─ MD-032 (performance validation)
  └─ MD-033 (release prep)
```

---

### MD-001 — Implement `CanonicalQuote` Contract

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-001                                                                |
| **Title**           | Implement `CanonicalQuote` frozen dataclass in contracts lib          |
| **Objective**       | Create the canonical quote data model as a frozen dataclass mirroring `CanonicalOHLCVBar` patterns, for use by the quotes consumer and API layer |
| **Paths to inspect** | `worldview/libs/contracts/src/contracts/canonical/ohlcv.py` (reference pattern), `platform_repo/apps/backend-market-data/src/market_data/domain/` (legacy quote entity), `worldview/libs/contracts/src/contracts/versions.py` |
| **Paths to modify** | `worldview/libs/contracts/src/contracts/canonical/quotes.py` (create), `worldview/libs/contracts/src/contracts/canonical/__init__.py` (update exports), `worldview/libs/contracts/tests/test_quotes.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `quotes.py` with `CanonicalQuote` frozen dataclass. Fields: `symbol`, `exchange`, `bid`, `ask`, `last_price`, `volume`, `timestamp`, `source`, `schema_version` (auto from `QUOTE_SCHEMA_VERSION`). 2. Implement `from_dict()` class method and `to_dict()` method. 3. Update `canonical/__init__.py` to export `CanonicalQuote`. 4. Write unit tests mirroring `test_ohlcv.py` patterns. |
| **Tests — unit**    | `test_canonical_quote_schema_version`, `test_canonical_quote_roundtrip`, `test_canonical_quote_frozen`, `test_canonical_quote_from_dict_missing_fields` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/contracts.md` to list `CanonicalQuote`    |
| **DoD / Acceptance** | 1. `CanonicalQuote` passes all unit tests. 2. Frozen (immutable). 3. `from_dict`/`to_dict` roundtrip. 4. `schema_version` auto-populated. 5. Exported from package. 6. Docs updated. |
| **Effort**          | S (1–2 hours)                                                         |
| **Risk controls**   | Low risk. Follow existing `CanonicalOHLCVBar` pattern exactly.        |

---

### MD-002 — Implement `CanonicalFundamentals` Contract

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-002                                                                |
| **Title**           | Implement `CanonicalFundamentals` frozen dataclass in contracts lib   |
| **Objective**       | Create canonical fundamentals data model supporting the 13-section decomposition from legacy |
| **Paths to inspect** | `worldview/libs/contracts/src/contracts/canonical/ohlcv.py`, `platform_repo/apps/backend-market-data/src/market_data/domain/` (legacy fundamentals entities — 20+ table mappings), `platform_repo/apps/backend-market-data/src/market_data/infrastructure/messaging/` (fundamentals consumer section mapping) |
| **Paths to modify** | `worldview/libs/contracts/src/contracts/canonical/fundamentals.py` (create), `worldview/libs/contracts/src/contracts/canonical/__init__.py` (update), `worldview/libs/contracts/tests/test_fundamentals.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `fundamentals.py` with `CanonicalFundamentals` frozen dataclass. Contains typed section dataclasses: `IncomeStatement`, `BalanceSheet`, `CashFlow`, `ValuationRatios`, `TechnicalsSnapshot`, `ShareStatistics`, `SplitsDividends`, `AnalystConsensus`, `EarningsHistory`, `EarningsTrend`, `EarningsAnnualTrend`, `DividendHistory`, `DividendSummary`, `OutstandingShares`. 2. Top-level `CanonicalFundamentals` aggregates all sections as optional fields. 3. Implement `from_dict()` and `to_dict()` with nested handling. 4. Write comprehensive unit tests. |
| **Tests — unit**    | `test_fundamentals_schema_version`, `test_fundamentals_roundtrip`, `test_fundamentals_optional_sections`, `test_fundamentals_frozen`, `test_individual_section_roundtrips` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/contracts.md` to list `CanonicalFundamentals` and all section types |
| **DoD / Acceptance** | 1. All 14 section dataclasses implemented and tested. 2. Sections are optional (partial fundamentals supported). 3. Roundtrip serialization. 4. Docs updated. |
| **Effort**          | M (3–5 hours) — large surface area but mechanical                     |
| **Risk controls**   | Medium. Audit legacy field mapping for duplicate keys before implementing. Cross-reference migration 001 columns vs ORM model columns. |

---

### MD-003 — Implement `contracts.parsing` Module

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-003                                                                |
| **Title**           | Implement JSONL/JSON/Parquet parsing utilities in contracts lib       |
| **Objective**       | Create the parsing module that converts raw S3 payloads into canonical dataclass instances |
| **Paths to inspect** | `platform_repo/libs/contracts/` (legacy parsing), `worldview/libs/contracts/src/contracts/canonical/` (existing canonical types) |
| **Paths to modify** | `worldview/libs/contracts/src/contracts/parsing.py` (create), `worldview/libs/contracts/src/contracts/__init__.py` (update), `worldview/libs/contracts/tests/test_parsing.py` (create), `worldview/libs/contracts/pyproject.toml` (add `orjson` dep if needed) |
| **Dependencies**    | MD-001, MD-002 (needs `CanonicalQuote` and `CanonicalFundamentals`)   |
| **Implementation steps** | 1. Create `parsing.py` with functions: `parse_ohlcv_jsonl(raw: bytes) -> list[CanonicalOHLCVBar]`, `parse_quotes_json(raw: bytes) -> CanonicalQuote`, `parse_fundamentals_json(raw: bytes) -> CanonicalFundamentals`. 2. Handle encoding detection (UTF-8/UTF-8-BOM). 3. Validate required fields, raise `ParseError` on malformed data. 4. Write tests with fixture files for each format. |
| **Tests — unit**    | `test_parse_ohlcv_jsonl_valid`, `test_parse_ohlcv_jsonl_empty`, `test_parse_ohlcv_jsonl_malformed_line`, `test_parse_quotes_json_valid`, `test_parse_quotes_json_missing_fields`, `test_parse_fundamentals_json_valid`, `test_parse_fundamentals_json_partial_sections` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/contracts.md` with parsing API reference  |
| **DoD / Acceptance** | 1. All 3 parsers handle valid and malformed input. 2. `ParseError` raised with context. 3. Unit tests pass. 4. Docs updated. |
| **Effort**          | M (3–4 hours)                                                         |
| **Risk controls**   | Test with real sample data from legacy if available. Validate UTF-8 BOM handling separately. |

---

### MD-004 — Implement `messaging.errors` Module

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-004                                                                |
| **Title**           | Implement `RetryableError` and `FatalError` exception hierarchy       |
| **Objective**       | Create the error classification hierarchy used by consumers for retry/DLQ decisions |
| **Paths to inspect** | `platform_repo/libs/messaging/` (legacy error classes), `worldview/libs/messaging/src/messaging/` |
| **Paths to modify** | `worldview/libs/messaging/src/messaging/errors.py` (create), `worldview/libs/messaging/src/messaging/__init__.py` (update exports), `worldview/libs/messaging/tests/test_errors.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `errors.py` with base `MessagingError(Exception)`, `RetryableError(MessagingError)` (with optional `retry_after_seconds`), `FatalError(MessagingError)`. 2. Add `DeserializationError(FatalError)`, `SchemaValidationError(FatalError)`, `BrokerUnavailableError(RetryableError)`. 3. Update `__init__.py` exports. 4. Write unit tests. |
| **Tests — unit**    | `test_retryable_error_is_messaging_error`, `test_fatal_error_is_messaging_error`, `test_retryable_error_retry_after`, `test_error_hierarchy` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/messaging.md` with error hierarchy        |
| **DoD / Acceptance** | 1. Error classes match documented hierarchy. 2. `RetryableError` has `retry_after_seconds`. 3. All tests pass. 4. Docs updated. |
| **Effort**          | XS (< 1 hour)                                                         |
| **Risk controls**   | Low risk. Pure data classes.                                          |

---

### MD-005 — Implement `BaseKafkaConsumer` in messaging lib

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-005                                                                |
| **Title**           | Implement `BaseKafkaConsumer[TFailure]` abstract base class            |
| **Objective**       | Create the async Kafka consumer base class that all market-data consumers will extend, with built-in error handling, idempotency tracking, and graceful shutdown |
| **Paths to inspect** | `platform_repo/libs/messaging/` (legacy `BaseKafkaConsumer` ~576 LOC), `worldview/libs/messaging/src/messaging/schemas.py` (Avro deser), `worldview/libs/messaging/src/messaging/topics.py` |
| **Paths to modify** | `worldview/libs/messaging/src/messaging/consumer.py` (create), `worldview/libs/messaging/src/messaging/__init__.py` (update), `worldview/libs/messaging/tests/test_consumer.py` (create), `worldview/libs/messaging/pyproject.toml` (verify deps) |
| **Dependencies**    | MD-004 (`RetryableError` / `FatalError`)                               |
| **Implementation steps** | 1. Create `consumer.py` with `BaseKafkaConsumer[TFailure]` generic ABC. 2. Constructor: `bootstrap_servers`, `schema_registry_url`, `group_id`, `topics`, `max_poll_interval_ms`. 3. Abstract methods: `process_message(msg) -> None`, `on_fatal_error(msg, error) -> TFailure`. 4. Lifecycle: `start()`, `stop()`, `run()` loop with poll/commit. 5. Error handling: catch `RetryableError` → NACK/retry, catch `FatalError` → call `on_fatal_error`, catch all → wrap as `FatalError`. 6. Graceful shutdown via `asyncio.Event`. 7. Structlog logging for all state transitions. 8. **Key design change from legacy**: use `confluent_kafka.Consumer` with async wrapper (run blocking poll in thread executor), not threading-based consumer. |
| **Tests — unit**    | `test_consumer_graceful_shutdown`, `test_consumer_retryable_error_handling`, `test_consumer_fatal_error_handling`, `test_consumer_commit_after_process`, `test_consumer_deserialize_avro_message` |
| **Tests — container** | Will be covered in MD-029                                            |
| **Tests — platform** | Will be covered in MD-030                                            |
| **Documentation**   | Update `worldview/docs/libs/messaging.md` with `BaseKafkaConsumer` API, usage example, and error handling behavior |
| **DoD / Acceptance** | 1. Abstract class can be subclassed. 2. Poll-process-commit loop works. 3. `RetryableError` does not commit offset. 4. `FatalError` calls `on_fatal_error` and commits. 5. Graceful shutdown on SIGTERM. 6. Unit tests pass. 7. Docs updated. |
| **Effort**          | L (5–8 hours) — critical path, complex async logic                    |
| **Risk controls**   | High. This is the most critical shared component. 1. Design async wrapper carefully (run `poll()` in `asyncio.to_thread`). 2. Test shutdown race conditions. 3. Consider backpressure. Review legacy implementation line-by-line for edge cases. |

---

### MD-006 — Implement `KafkaProducerConfig` and Producer Factory

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-006                                                                |
| **Title**           | Implement Kafka producer configuration and serializing producer factory |
| **Objective**       | Create the producer-side Kafka infrastructure for outbox dispatcher   |
| **Paths to inspect** | `platform_repo/libs/messaging/` (legacy producer), `worldview/libs/messaging/src/messaging/schemas.py` |
| **Paths to modify** | `worldview/libs/messaging/src/messaging/producer.py` (create), `worldview/libs/messaging/src/messaging/__init__.py` (update), `worldview/libs/messaging/tests/test_producer.py` (create) |
| **Dependencies**    | None — independent of MD-005                                          |
| **Implementation steps** | 1. Create `producer.py` with `KafkaProducerConfig` (pydantic `BaseSettings`): `bootstrap_servers`, `schema_registry_url`, `acks`, `retries`, `linger_ms`. 2. Implement `build_serializing_producer(config) -> SerializingProducer`. 3. Add delivery callback helper. 4. Write unit tests (mock confluent_kafka). |
| **Tests — unit**    | `test_producer_config_defaults`, `test_build_serializing_producer`, `test_delivery_callback_success`, `test_delivery_callback_failure` |
| **Tests — container** | Will be covered in MD-029                                            |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/messaging.md` with producer API           |
| **DoD / Acceptance** | 1. Config model validates. 2. Factory creates `SerializingProducer`. 3. Delivery callback logs errors. 4. Tests pass. 5. Docs updated. |
| **Effort**          | S (2–3 hours)                                                         |
| **Risk controls**   | Low. Mirror legacy producer setup.                                    |

---

### MD-007 — Implement `BaseOutboxDispatcher` in messaging lib

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-007                                                                |
| **Title**           | Implement `BaseOutboxDispatcher` with lease-based dispatch             |
| **Objective**       | Create the outbox dispatcher base class with hybrid immediate+polling dispatch, lease acquisition, and retry logic |
| **Paths to inspect** | `platform_repo/libs/messaging/` (legacy `BaseOutboxDispatcher` ~536 LOC), `worldview/libs/messaging/src/messaging/producer.py` |
| **Paths to modify** | `worldview/libs/messaging/src/messaging/outbox.py` (create), `worldview/libs/messaging/src/messaging/__init__.py` (update), `worldview/libs/messaging/tests/test_outbox.py` (create) |
| **Dependencies**    | MD-006 (producer factory)                                              |
| **Implementation steps** | 1. Create `outbox.py` with `BaseOutboxDispatcher` ABC. 2. Constructor: SQLAlchemy `AsyncSession` factory, `SerializingProducer`, `poll_interval_seconds=10`, `lease_duration_seconds=60`, `stale_threshold_seconds=300`. 3. Methods: `start()`, `stop()`, `_poll_pending()`, `_claim_event(event_id)`, `_dispatch(event)`, `_release_stale()`, `_on_delivery(err, msg)`. 4. Hybrid dispatch: listen for PostgreSQL NOTIFY on commit, fall back to polling. 5. Lease: `worker_id=hostname-pid`, update `claimed_at` and `claimed_by`. 6. Retry: exponential backoff (5s base), max 5 attempts, then status=DEAD. 7. **Fix legacy bug**: serialize Decimal/UUID fields before JSON encoding. |
| **Tests — unit**    | `test_outbox_claim_event`, `test_outbox_release_stale`, `test_outbox_retry_backoff`, `test_outbox_max_attempts_dead`, `test_outbox_decimal_uuid_serialization` |
| **Tests — container** | Will be covered in MD-029 (requires real Postgres + Kafka)           |
| **Tests — platform** | Will be covered in MD-030                                            |
| **Documentation**   | Update `worldview/docs/libs/messaging.md` with outbox dispatcher API, architecture diagram, lease mechanism explanation |
| **DoD / Acceptance** | 1. Hybrid dispatch (NOTIFY + poll). 2. Lease-based locking prevents duplicate dispatch. 3. Retry with backoff. 4. Max attempts → DEAD. 5. Decimal/UUID serialization fixed. 6. Tests pass. 7. Docs updated. |
| **Effort**          | L (5–8 hours) — complex concurrency logic                             |
| **Risk controls**   | High. 1. Test race conditions in lease acquisition. 2. Verify NOTIFY listener works with asyncpg. 3. Fix legacy serialization bug. |

---

### MD-008 — Implement `ValkeyClient` in messaging lib

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-008                                                                |
| **Title**           | Implement async `ValkeyClient` wrapper                                 |
| **Objective**       | Create the async Redis/Valkey client with typed get/set/delete and health check |
| **Paths to inspect** | `platform_repo/libs/messaging/` (legacy `ValkeyClient`), `worldview/libs/messaging/` |
| **Paths to modify** | `worldview/libs/messaging/src/messaging/valkey.py` (create), `worldview/libs/messaging/src/messaging/__init__.py` (update), `worldview/libs/messaging/tests/test_valkey.py` (create), `worldview/libs/messaging/pyproject.toml` (verify `redis` dep) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `valkey.py` with `ValkeyClient` class. 2. Constructor: `url: str`, `decode_responses=True`. 3. Methods: `connect()`, `close()`, `get(key) -> str | None`, `set(key, value, ttl_seconds)`, `delete(key)`, `health_check() -> bool`. 4. Use `redis.asyncio.Redis` underneath. 5. Structured logging for connection events. |
| **Tests — unit**    | `test_valkey_get_set_roundtrip` (mock), `test_valkey_ttl_expiry` (mock), `test_valkey_health_check` (mock), `test_valkey_delete` (mock) |
| **Tests — container** | Will be covered in MD-029 (requires real Valkey)                     |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/messaging.md` with `ValkeyClient` API     |
| **DoD / Acceptance** | 1. Async get/set/delete works. 2. TTL support. 3. Health check pings server. 4. Structured logging. 5. Tests pass. 6. Docs updated. |
| **Effort**          | S (2–3 hours)                                                         |
| **Risk controls**   | Low. Thin wrapper over `redis.asyncio`.                               |

---

### MD-009 — Implement `ObjectStorage` ABC and `S3ObjectStorage`

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-009                                                                |
| **Title**           | Implement object storage abstraction and S3-compatible implementation  |
| **Objective**       | Create the `ObjectStorage` port (ABC) and `S3ObjectStorage` adapter for MinIO/S3 |
| **Paths to inspect** | `platform_repo/libs/storage/` (legacy `S3ObjectStorage`), `worldview/libs/storage/src/storage/key_builder.py`, `worldview/libs/storage/src/storage/settings.py` |
| **Paths to modify** | `worldview/libs/storage/src/storage/object_storage.py` (create), `worldview/libs/storage/src/storage/exceptions.py` (create), `worldview/libs/storage/src/storage/health.py` (create), `worldview/libs/storage/src/storage/__init__.py` (update), `worldview/libs/storage/tests/test_object_storage.py` (create), `worldview/libs/storage/tests/test_exceptions.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `exceptions.py`: `StorageError`, `ObjectNotFoundError`, `BucketNotFoundError`, `StoragePermissionError`, `StorageUnavailableError`. 2. Create `object_storage.py` with `ObjectStorage` ABC: `get(bucket, key) -> bytes`, `put(bucket, key, data, content_type)`, `delete(bucket, key)`, `exists(bucket, key) -> bool`, `get_json(bucket, key) -> dict`, `put_json(bucket, key, data)`. 3. Create `S3ObjectStorage(ObjectStorage)` using `boto3` with `aiobotocore` for async. 4. Create `health.py` with `check_storage_health(client) -> bool`. 5. Create `build_object_storage(settings) -> ObjectStorage` factory. 6. Update `__init__.py` exports. |
| **Tests — unit**    | `test_s3_get_object`, `test_s3_put_object`, `test_s3_object_not_found`, `test_s3_bucket_not_found`, `test_s3_get_json`, `test_s3_put_json`, `test_build_object_storage`, `test_check_storage_health` (all with mocked boto3) |
| **Tests — container** | Will be covered in MD-029 (requires real MinIO)                      |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/storage.md` with `ObjectStorage` API, exception hierarchy, factory usage |
| **DoD / Acceptance** | 1. ABC with 6 methods. 2. S3 implementation works with MinIO. 3. Exception hierarchy. 4. Health check. 5. Factory function. 6. Tests pass. 7. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Medium. Async boto3 via `aiobotocore` or run sync boto3 in thread. Verify MinIO compatibility. Consider `aiobotocore` vs `boto3` + `asyncio.to_thread`. |

---

### MD-010 — Implement `observability.metrics` Module

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-010                                                                |
| **Title**           | Implement Prometheus metrics utilities in observability lib            |
| **Objective**       | Create metrics factory, middleware, and `/metrics` endpoint integration |
| **Paths to inspect** | `worldview/libs/observability/src/observability/logging.py` (existing pattern), `worldview/libs/observability/pyproject.toml` (deps already listed) |
| **Paths to modify** | `worldview/libs/observability/src/observability/metrics.py` (create), `worldview/libs/observability/src/observability/__init__.py` (update exports), `worldview/libs/observability/tests/test_metrics.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `metrics.py` with `ServiceMetrics` class: `requests_total` (Counter), `request_duration_seconds` (Histogram), `active_connections` (Gauge), `errors_total` (Counter, labels: error_type). 2. `create_metrics(service_name) -> ServiceMetrics`. 3. `add_prometheus_middleware(app: FastAPI, metrics: ServiceMetrics)` — middleware recording request metrics. 4. `get_metrics_endpoint() -> Response` — returns Prometheus text format. |
| **Tests — unit**    | `test_create_metrics_counters`, `test_metrics_middleware_increments`, `test_metrics_endpoint_format` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/observability.md` with metrics API        |
| **DoD / Acceptance** | 1. Prometheus counters/histograms/gauges created. 2. Middleware tracks requests. 3. `/metrics` endpoint returns text format. 4. Tests pass. 5. Docs updated. |
| **Effort**          | S (2–3 hours)                                                         |
| **Risk controls**   | Low. Standard prometheus-client usage.                                |

---

### MD-011 — Implement `observability.tracing` Module

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-011                                                                |
| **Title**           | Implement OpenTelemetry tracing utilities in observability lib         |
| **Objective**       | Create tracing configuration and middleware for distributed tracing    |
| **Paths to inspect** | `worldview/libs/observability/src/observability/logging.py`, `worldview/libs/observability/pyproject.toml` |
| **Paths to modify** | `worldview/libs/observability/src/observability/tracing.py` (create), `worldview/libs/observability/src/observability/__init__.py` (update exports), `worldview/libs/observability/tests/test_tracing.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `tracing.py` with `configure_tracing(service_name, otlp_endpoint)` — sets up OTLP exporter + BatchSpanProcessor. 2. `get_tracer(name) -> Tracer`. 3. `add_otel_middleware(app: FastAPI)` — instruments FastAPI with OTel. 4. Provide `shutdown_tracing()` for cleanup. |
| **Tests — unit**    | `test_configure_tracing`, `test_get_tracer_returns_tracer`, `test_add_otel_middleware` (mock FastAPI) |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/libs/observability.md` with tracing API        |
| **DoD / Acceptance** | 1. Tracer configured with OTLP exporter. 2. FastAPI middleware adds spans. 3. Graceful shutdown. 4. Tests pass. 5. Docs updated. |
| **Effort**          | S (2–3 hours)                                                         |
| **Risk controls**   | Low. Standard OTel Python SDK usage. Deps already in `pyproject.toml`. |

---

### MD-012 — Implement Market-Data Domain Entities and Value Objects

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-012                                                                |
| **Title**           | Implement domain entities, value objects, and enums for market-data    |
| **Objective**       | Create the domain layer with `Security`, `Instrument`, `OHLCVBar`, `Quote`, and all fundamentals entities, plus value objects (`Timeframe`, `DatasetType`, `Provider`, etc.) |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/domain/` (legacy: entities, enums, value objects), `worldview/libs/common/src/common/types.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/domain/__init__.py` (create), `worldview/services/market-data/src/market_data/domain/entities.py` (create), `worldview/services/market-data/src/market_data/domain/value_objects.py` (create), `worldview/services/market-data/src/market_data/domain/enums.py` (create), `worldview/services/market-data/tests/unit/test_domain_entities.py` (create), `worldview/services/market-data/tests/unit/test_value_objects.py` (create) |
| **Dependencies**    | None — independent                                                     |
| **Implementation steps** | 1. Create `enums.py` with: `Timeframe` (1m,5m,15m,30m,1h,4h,1d,1w,1M), `DatasetType` (OHLCV, QUOTE, FUNDAMENTALS), `Provider` (with priority values), `PeriodType` (ANNUAL, QUARTERLY), `FundamentalsSection` (13 sections). 2. Create `value_objects.py` with frozen dataclasses: `ProviderPriority`, `InstrumentFlags` (`has_ohlcv`, `has_quotes`, `has_fundamentals`). 3. Create `entities.py` with: `Security` (UUID, figi, isin, name, sector, industry, country, currency), `Instrument` (UUID, FK security, symbol, exchange, flags), `OHLCVBar` (instrument_id, timeframe, bar_date, OHLCV, adjusted_close, provider_priority), `Quote` (instrument_id, bid, ask, last, volume, timestamp), plus all fundamentals entities. 4. All entities use UUIDv7 via `common.ids`. |
| **Tests — unit**    | `test_timeframe_enum_values`, `test_dataset_type_enum`, `test_provider_priority_ordering`, `test_security_entity`, `test_instrument_entity_flags`, `test_ohlcv_bar_entity`, `test_quote_entity` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` domain model section  |
| **DoD / Acceptance** | 1. All enums match legacy values. 2. All entities have proper typing. 3. UUIDv7 IDs. 4. UTC-only timestamps enforced. 5. Provider priorities match legacy map. 6. Tests pass. 7. Docs updated. |
| **Effort**          | M (4–6 hours) — large number of entities but mechanical               |
| **Risk controls**   | Medium. Cross-reference every entity field against legacy migration 001 columns. |

---

### MD-013 — Implement Domain Events and Error Hierarchy

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-013                                                                |
| **Title**           | Implement domain events and domain error hierarchy for market-data     |
| **Objective**       | Create `InstrumentCreated`, `InstrumentUpdated` domain events and `MarketDataError` hierarchy |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/domain/` (legacy events + errors), `worldview/libs/messaging/src/messaging/errors.py` (base errors) |
| **Paths to modify** | `worldview/services/market-data/src/market_data/domain/events.py` (create), `worldview/services/market-data/src/market_data/domain/errors.py` (create), `worldview/services/market-data/tests/unit/test_domain_events.py` (create), `worldview/services/market-data/tests/unit/test_domain_errors.py` (create) |
| **Dependencies**    | MD-004 (messaging errors for `RetryableError`, `FatalError`)           |
| **Implementation steps** | 1. Create `events.py` with event envelope pattern: `DomainEvent` (base: `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `causation_id`), `InstrumentCreated(DomainEvent)`, `InstrumentUpdated(DomainEvent)`. 2. Create `errors.py` with: `MarketDataError(Exception)`, `InstrumentNotFoundError(MarketDataError)`, `SecurityNotFoundError(MarketDataError)`, `DuplicateEventError(MarketDataError)`, `IngestionError(MarketDataError)`, `ParseError(MarketDataError, FatalError)`, `StaleDataError(MarketDataError)`. |
| **Tests — unit**    | `test_instrument_created_event_envelope`, `test_instrument_updated_event_envelope`, `test_error_hierarchy`, `test_domain_event_auto_fields` |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` events section; update `worldview/docs/contracts/` if event contracts documented there |
| **DoD / Acceptance** | 1. Events follow envelope pattern from CLAUDE.md. 2. Error hierarchy classifiable as Retryable/Fatal. 3. Tests pass. 4. Docs updated. |
| **Effort**          | S (2 hours)                                                           |
| **Risk controls**   | Low. Follow event envelope spec from CLAUDE.md exactly.               |

---

### MD-014 — Implement SQLAlchemy ORM Models

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-014                                                                |
| **Title**           | Implement SQLAlchemy 2.0 async ORM models for all 26 tables           |
| **Objective**       | Create the ORM models matching the full database schema including `securities`, `instruments`, `ohlcv_bars`, `quotes`, 20 fundamentals tables, and 3 infrastructure tables |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/db/models/` (legacy models), `platform_repo/apps/backend-market-data/alembic/versions/` (migration 001 exact SQL), `worldview/services/market-data/src/market_data/domain/entities.py` (domain entities from MD-012) |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/base.py` (create — `Base = declarative_base()`), `worldview/services/market-data/src/market_data/infrastructure/db/models/` (create all model files), `worldview/services/market-data/tests/unit/test_models.py` (create) |
| **Dependencies**    | MD-012 (domain entities for reference)                                 |
| **Implementation steps** | 1. Create `base.py` with `Base = declarative_base()` and common mixins (`TimestampMixin` with `created_at`, `updated_at`). 2. Create `models/securities.py` — `SecurityModel`: UUID PK, figi, isin, name, sector, industry, country, currency, timestamps. 3. Create `models/instruments.py` — `InstrumentModel`: UUID PK, FK→securities, symbol, exchange, UNIQUE(symbol,exchange), flags. 4. Create `models/ohlcv.py` — `OHLCVBarModel`: composite PK (instrument_id, timeframe, bar_date), NUMERIC precision for prices, provider_priority. **Note**: use standard table, NOT partitioned — TimescaleDB hypertable will be created in migration. 5. Create `models/quotes.py` — `QuoteModel`: instrument_id PK, bid, ask, last, volume, timestamp. 6. Create `models/fundamentals/` — all 20 fundamentals models organized by type (A through E). 7. Create `models/infrastructure.py` — `IngestionEventModel`, `FailedTaskModel`, `OutboxEventModel`. 8. **Critical**: Verify every column name/type matches between model and what migration will create. Fix the legacy model↔migration mismatches. |
| **Tests — unit**    | `test_security_model_columns`, `test_instrument_model_unique_constraint`, `test_ohlcv_model_composite_pk`, `test_quote_model_pk`, `test_fundamentals_model_fk_constraints`, `test_infrastructure_models` |
| **Tests — container** | Will be covered in MD-029                                            |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` database schema section |
| **DoD / Acceptance** | 1. All 26 table models defined. 2. All column types match domain entities. 3. All constraints (PK, FK, UNIQUE, indexes) defined. 4. No model↔migration mismatches (fix legacy bugs). 5. Tests pass. 6. Docs updated. |
| **Effort**          | L (6–10 hours) — many models but mostly mechanical                    |
| **Risk controls**   | High. The legacy had model↔migration mismatches in `failed_tasks` and `outbox_events`. Must cross-reference every column against migration SQL and fix discrepancies. Create a verification checklist per table. |

---

### MD-015 — Create Alembic Migrations with TimescaleDB Hypertable

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-015                                                                |
| **Title**           | Create initial Alembic migration with TimescaleDB hypertable for OHLCV |
| **Objective**       | Generate fresh Alembic migration(s) that create all tables, indexes, constraints, and convert `ohlcv_bars` to a TimescaleDB hypertable |
| **Paths to inspect** | `worldview/services/market-data/src/market_data/infrastructure/db/models/` (ORM models from MD-014), `worldview/services/market-data/alembic/env.py` (current scaffold), `platform_repo/apps/backend-market-data/alembic/versions/` (legacy migrations for reference) |
| **Paths to modify** | `worldview/services/market-data/alembic/env.py` (wire `target_metadata = Base.metadata`), `worldview/services/market-data/alembic/versions/001_initial_schema.py` (create), `worldview/services/market-data/alembic/versions/002_timescaledb_hypertable.py` (create) |
| **Dependencies**    | MD-014 (ORM models must exist first)                                   |
| **Implementation steps** | 1. Update `alembic/env.py`: import `Base` from `infrastructure.db.base`, set `target_metadata = Base.metadata`. 2. Create migration `001_initial_schema.py`: create all 26 tables with proper column types, indexes, constraints. Keep OHLCV as standard table initially. 3. Create migration `002_timescaledb_hypertable.py`: `op.execute("SELECT create_hypertable('ohlcv_bars', 'bar_date', migrate_data => true)")`. Add appropriate chunk interval. 4. **Design decision**: Use TimescaleDB hypertable instead of legacy LIST partitioning (per MASTER_PLAN.md). This provides automatic chunking, compression, continuous aggregates, and better query performance for time-series. 5. Add `CREATE EXTENSION IF NOT EXISTS timescaledb` in migration 002. 6. Create indexes: `(instrument_id, bar_date DESC)` on OHLCV, `(symbol, exchange)` UNIQUE on instruments, FIGI UNIQUE on securities. |
| **Tests — unit**    | N/A (migrations tested at container level)                             |
| **Tests — container** | `test_migration_001_creates_all_tables`, `test_migration_002_creates_hypertable`, `test_migration_rollback` (in MD-029) |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` migration section; add ADR for TimescaleDB hypertable decision vs LIST partitioning |
| **DoD / Acceptance** | 1. `alembic upgrade head` creates all 26 tables. 2. OHLCV is a TimescaleDB hypertable. 3. All indexes created. 4. `alembic downgrade base` rolls back cleanly. 5. `target_metadata` wired correctly. 6. Docs and ADR updated. |
| **Effort**          | M (4–6 hours)                                                         |
| **Risk controls**   | High. 1. Test full upgrade+downgrade cycle. 2. Verify TimescaleDB extension available in test container. 3. Verify hypertable chunk interval appropriate for expected data volume. |

---

### MD-016 — Implement Repository Layer (Ports + Adapters)

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-016                                                                |
| **Title**           | Implement repository ports (ABCs) and PostgreSQL adapters              |
| **Objective**       | Create clean architecture repository interfaces and their SQLAlchemy implementations for all data access |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/db/repositories/` (legacy repos — CRUD + bulk upserts), `worldview/services/market-data/src/market_data/domain/entities.py`, `worldview/services/market-data/src/market_data/infrastructure/db/models/` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/application/__init__.py` (create), `worldview/services/market-data/src/market_data/application/ports/__init__.py` (create), `worldview/services/market-data/src/market_data/application/ports/repositories.py` (create — ABCs), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/securities.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/instruments.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/ohlcv.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/quotes.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/fundamentals.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/infrastructure.py` (create), `worldview/services/market-data/tests/unit/test_repositories.py` (create) |
| **Dependencies**    | MD-012 (domain entities), MD-014 (ORM models)                          |
| **Implementation steps** | 1. Create `ports/repositories.py` with ABCs: `SecurityRepository`, `InstrumentRepository`, `OHLCVRepository`, `QuoteRepository`, `FundamentalsRepository`, `IngestionEventRepository`, `FailedTaskRepository`, `OutboxEventRepository`. Each with CRUD + domain-specific methods. 2. Implement PostgreSQL adapters: (a) `SecurityRepo` — `find_by_figi()`, `find_by_isin()`, `upsert()`. (b) `InstrumentRepo` — `find_by_symbol_exchange()`, `find_by_id()`, `search()`, `upsert()`, `update_flags()`. (c) `OHLCVRepo` — `bulk_upsert_with_priority(bars)` (SQL: `ON CONFLICT DO UPDATE WHERE EXCLUDED.provider_priority >= current`), `find_by_instrument_timeframe_range()`, `get_available_timeframes()`, `get_date_range()`. (d) `QuoteRepo` — `upsert(quote)`, `find_by_instrument()`, `find_by_instruments(ids)`. (e) `FundamentalsRepo` — one method per table type, `merge_upsert()` for sections with partial updates. (f) `IngestionEventRepo` — `exists(event_id) -> bool`, `create(event_id)`. (g) `FailedTaskRepo` — `create()`, `find_retryable()`, `increment_attempts()`, `mark_dead()`. (h) `OutboxEventRepo` — `create()`, `find_pending()`, `claim()`, `mark_dispatched()`, `release_stale()`. 3. All repos accept `AsyncSession` in constructor. |
| **Tests — unit**    | `test_ohlcv_bulk_upsert_sql_generation` (mock session), `test_instrument_search_filters`, `test_ingestion_event_exists_check` |
| **Tests — container** | Full repo tests against real Postgres in MD-029                      |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` data access section   |
| **DoD / Acceptance** | 1. All ABCs defined with proper typing. 2. All PG adapters implement ABCs. 3. Provider priority upsert SQL correct. 4. Merge-upsert for fundamentals. 5. Tests pass. 6. Docs updated. |
| **Effort**          | L (8–12 hours) — many repositories, complex SQL logic                 |
| **Risk controls**   | High. 1. Provider priority SQL must be verified against legacy. 2. Fundamentals merge-upsert logic must handle partial sections. 3. Test with real OHLCV data. |

---

### MD-017 — Implement Unit of Work Pattern

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-017                                                                |
| **Title**           | Implement async Unit of Work with read/write session splitting          |
| **Objective**       | Create UoW that wraps all repositories in a single transaction, supports outbox event collection, and provides read/write session separation |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/db/uow.py` (legacy UoW with 25+ repos), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/application/ports/uow.py` (create — ABC), `worldview/services/market-data/src/market_data/infrastructure/db/uow.py` (create — implementation), `worldview/services/market-data/src/market_data/infrastructure/db/session.py` (create — session factory), `worldview/services/market-data/tests/unit/test_uow.py` (create) |
| **Dependencies**    | MD-016 (repositories)                                                  |
| **Implementation steps** | 1. Create `session.py` with `create_async_engine()`, `create_session_factory()`, `create_read_session_factory()`. 2. Create `ports/uow.py` with `UnitOfWork` ABC: async context manager, `commit()`, `rollback()`, property accessors for all repositories, `collect_event(event)`, `collected_events -> list[DomainEvent]`. 3. Create `infrastructure/db/uow.py` with `SqlAlchemyUnitOfWork(UnitOfWork)`: lazily creates repos on access, commits/rollbacks session, after commit notifies outbox if events collected. 4. Read/write splitting: read queries use read-only session (could be replica), writes use primary session. |
| **Tests — unit**    | `test_uow_commit_commits_session`, `test_uow_rollback_on_exception`, `test_uow_collects_events`, `test_uow_notifies_outbox_on_commit` (mock session) |
| **Tests — container** | Will be covered in MD-029                                            |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` UoW pattern section   |
| **DoD / Acceptance** | 1. UoW commits/rollbacks as context manager. 2. All repos accessible. 3. Events collected and forwarded to outbox on commit. 4. Read/write separation. 5. Tests pass. 6. Docs updated. |
| **Effort**          | M (4–6 hours)                                                         |
| **Risk controls**   | Medium. 1. Verify async session lifecycle. 2. Ensure rollback on exception in `__aexit__`. 3. Test nested transaction behavior. |

---

### MD-018 — Implement TimescaleDB Query Utilities

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-018                                                                |
| **Title**           | Implement TimescaleDB-specific query utilities for OHLCV               |
| **Objective**       | Create optimized TimescaleDB queries leveraging hypertable features (time_bucket, continuous aggregates) |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/db/` (legacy queries — raw SQL for partitioned tables), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/ohlcv.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/db/queries/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/db/queries/ohlcv_queries.py` (create), `worldview/services/market-data/tests/unit/test_ohlcv_queries.py` (create) |
| **Dependencies**    | MD-014 (ORM models), MD-015 (TimescaleDB hypertable), MD-016 (repositories) |
| **Implementation steps** | 1. Create `ohlcv_queries.py` with optimized queries: `get_bars_by_range(instrument_id, timeframe, start, end)` using time-range constraints that leverage hypertable chunk pruning. 2. `get_latest_bar(instrument_id, timeframe)` with `ORDER BY bar_date DESC LIMIT 1`. 3. `get_bar_count(instrument_id, timeframe)` for metadata. 4. `get_available_date_range(instrument_id, timeframe) -> (min_date, max_date)`. 5. Create `time_bucket` aggregate queries for downsampling (e.g., 1m → 5m aggregation). 6. Ensure all queries use parameterized SQL to prevent injection. |
| **Tests — unit**    | `test_ohlcv_query_range_parameters`, `test_ohlcv_query_ordering`, `test_time_bucket_aggregation_sql` |
| **Tests — container** | Will be covered in MD-029 (requires real TimescaleDB)                |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` query layer section   |
| **DoD / Acceptance** | 1. Range queries optimize for hypertable. 2. `time_bucket` aggregation works. 3. No SQL injection risk. 4. Tests pass. 5. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Medium. 1. TimescaleDB `time_bucket` behavior differs from manual aggregation. 2. Test with representative data volumes. |

---

### MD-019 — Implement OHLCV Materializer Consumer

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-019                                                                |
| **Title**           | Implement OHLCV materializer Kafka consumer                            |
| **Objective**       | Create the consumer that processes `market.dataset.fetched` events for OHLCV datasets: downloads claim-check payload from S3, parses JSONL, performs bulk upsert with provider priority, and emits instrument lifecycle events |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` (legacy implementation), `worldview/libs/messaging/src/messaging/consumer.py` (BaseKafkaConsumer from MD-005), `worldview/libs/storage/src/storage/object_storage.py` (S3 client from MD-009), `worldview/libs/contracts/src/contracts/parsing.py` (parser from MD-003), `worldview/services/market-data/src/market_data/infrastructure/db/repositories/ohlcv.py` (repo from MD-016) |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/messaging/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/messaging/consumers/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` (create), `worldview/services/market-data/tests/unit/test_ohlcv_consumer.py` (create) |
| **Dependencies**    | MD-003 (parsing), MD-005 (BaseKafkaConsumer), MD-009 (ObjectStorage), MD-012 (domain entities), MD-013 (domain events), MD-016 (repositories), MD-017 (UoW) |
| **Implementation steps** | 1. Create `OHLCVConsumer(BaseKafkaConsumer)` with group_id `market-data-ohlcv`, topic `market.dataset.fetched`. 2. In `process_message()`: (a) Deserialize Avro message to get claim-check pointer (`bucket`, `object_key`, `content_type`, `dataset_type`). (b) Filter: skip if `dataset_type != "OHLCV"`. (c) Check idempotency: query `ingestion_events` for `event_id`; skip if exists. (d) Download payload from S3 using `ObjectStorage.get()`. (e) Parse JSONL using `contracts.parsing.parse_ohlcv_jsonl()`. (f) Resolve/create instrument: find by `(symbol, exchange)` or create new. If new, collect `InstrumentCreated` event. (g) Map `CanonicalOHLCVBar` → `OHLCVBar` domain entity. (h) Bulk upsert via `OHLCVRepository.bulk_upsert_with_priority()`. (i) Record `event_id` in `ingestion_events`. (j) Commit UoW (triggers outbox for any collected events). 3. In `on_fatal_error()`: create `FailedTask` record. 4. Structured logging throughout. |
| **Tests — unit**    | `test_ohlcv_consumer_processes_valid_message` (mock S3 + DB), `test_ohlcv_consumer_skips_non_ohlcv`, `test_ohlcv_consumer_skips_duplicate_event`, `test_ohlcv_consumer_creates_instrument_on_first_seen`, `test_ohlcv_consumer_provider_priority_respected`, `test_ohlcv_consumer_fatal_error_creates_failed_task`, `test_ohlcv_consumer_retryable_error_does_not_commit` |
| **Tests — container** | `test_ohlcv_consumer_full_flow` (real Kafka + Postgres + MinIO) in MD-029 |
| **Tests — platform** | Ingestion → OHLCV API → verify data in MD-030                        |
| **Documentation**   | Update `worldview/docs/services/market-data.md` consumer section      |
| **DoD / Acceptance** | 1. Consumes `market.dataset.fetched` filtered by `dataset_type=OHLCV`. 2. Claim-check download from S3. 3. JSONL parsing to canonical bars. 4. Bulk upsert with provider priority SQL. 5. Idempotency via `ingestion_events`. 6. Instrument auto-creation with event emission. 7. Failed tasks on fatal error. 8. All unit tests pass. 9. Docs updated. |
| **Effort**          | L (6–10 hours) — complex integration, many dependencies               |
| **Risk controls**   | High. 1. Test with large JSONL payloads (1000+ bars). 2. Test provider priority edge cases (equal priority, lower priority). 3. Test concurrent processing (two consumers processing same instrument). 4. Verify S3 download error is classified as RetryableError. |

---

### MD-020 — Implement Quotes Consumer

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-020                                                                |
| **Title**           | Implement quotes Kafka consumer with Valkey cache invalidation         |
| **Objective**       | Create the consumer that processes `market.dataset.fetched` events for quote datasets: downloads from S3, parses, upserts latest quote, and invalidates Valkey cache |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py` (legacy), `worldview/libs/messaging/src/messaging/consumer.py`, `worldview/libs/messaging/src/messaging/valkey.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py` (create), `worldview/services/market-data/tests/unit/test_quotes_consumer.py` (create) |
| **Dependencies**    | MD-001 (CanonicalQuote), MD-003 (parsing), MD-005 (BaseKafkaConsumer), MD-008 (ValkeyClient), MD-009 (ObjectStorage), MD-016 (repositories), MD-017 (UoW) |
| **Implementation steps** | 1. Create `QuotesConsumer(BaseKafkaConsumer)` with group_id `market-data-quotes`, topic `market.dataset.fetched`. 2. In `process_message()`: (a) Filter: skip if `dataset_type != "QUOTE"`. (b) Idempotency check. (c) Download from S3. (d) Parse using `parse_quotes_json()`. (e) Resolve instrument (create if new, emit `InstrumentCreated`). (f) Upsert quote via `QuoteRepository.upsert()`. (g) Invalidate Valkey cache: `valkey.delete(f"quote:{instrument_id}")`. (h) Record event_id. (i) Commit UoW. 3. Error handling: S3 download errors → `RetryableError`, parse errors → `FatalError`. |
| **Tests — unit**    | `test_quotes_consumer_processes_valid_message`, `test_quotes_consumer_skips_non_quote`, `test_quotes_consumer_invalidates_cache`, `test_quotes_consumer_creates_instrument_on_first_seen`, `test_quotes_consumer_fatal_error_on_parse_failure`, `test_quotes_consumer_retryable_error_on_s3_failure` |
| **Tests — container** | `test_quotes_consumer_full_flow` in MD-029                           |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` consumer section      |
| **DoD / Acceptance** | 1. Filters by `dataset_type=QUOTE`. 2. Upserts latest quote. 3. Invalidates Valkey cache. 4. Instrument auto-creation. 5. Idempotency. 6. Error classification. 7. Tests pass. 8. Docs updated. |
| **Effort**          | M (4–6 hours) — similar pattern to OHLCV but simpler data            |
| **Risk controls**   | Medium. 1. Verify cache invalidation happens AFTER DB commit (not before). 2. Test cache miss scenario (Valkey down → degrade gracefully). |

---

### MD-021 — Implement Fundamentals Consumer

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-021                                                                |
| **Title**           | Implement fundamentals Kafka consumer with 13-section decomposition    |
| **Objective**       | Create the consumer that processes `market.dataset.fetched` events for fundamentals datasets: downloads, parses, decomposes into 13 sections, writes to 20 tables using merge-upsert |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` (legacy — 13 section mapping, merge-upsert), `platform_repo/apps/backend-market-data/src/market_data/infrastructure/db/repositories/fundamentals/` (legacy repos) |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` (create), `worldview/services/market-data/tests/unit/test_fundamentals_consumer.py` (create) |
| **Dependencies**    | MD-002 (CanonicalFundamentals), MD-003 (parsing), MD-005 (BaseKafkaConsumer), MD-009 (ObjectStorage), MD-016 (repositories including fundamentals repos), MD-017 (UoW) |
| **Implementation steps** | 1. Create `FundamentalsConsumer(BaseKafkaConsumer)` with group_id `market-data-fundamentals`, topic `market.dataset.fetched`. 2. Define section-to-table mapping (13 EODHD sections → 20 DB tables). 3. In `process_message()`: (a) Filter: skip if `dataset_type != "FUNDAMENTALS"`. (b) Idempotency check. (c) Download from S3. (d) Parse using `parse_fundamentals_json()`. (e) Resolve security by FIGI/ISIN. (f) For each section present: map fields → entity, route to correct repository. (g) Special handling for `analyst_consensus` and `dividend_summary`: merge-upsert (multiple sections write partial data to same table). (h) Provider priority check for each section. (i) Record event_id. (j) Commit UoW. 3. **Fix legacy bug**: audit field mapping dict for duplicate keys. |
| **Tests — unit**    | `test_fundamentals_consumer_processes_full_payload`, `test_fundamentals_consumer_processes_partial_payload`, `test_fundamentals_consumer_merge_upsert_analyst_consensus`, `test_fundamentals_consumer_merge_upsert_dividend_summary`, `test_fundamentals_consumer_section_mapping_complete`, `test_fundamentals_consumer_skips_esg_section`, `test_fundamentals_consumer_provider_priority` |
| **Tests — container** | `test_fundamentals_consumer_full_flow` in MD-029                     |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` consumer section; document section-to-table mapping |
| **DoD / Acceptance** | 1. All 13 sections mapped to correct tables. 2. Merge-upsert for shared tables. 3. Provider priority check. 4. ESG deferred (skipped). 5. No duplicate key bugs. 6. Idempotency. 7. Tests pass. 8. Docs updated. |
| **Effort**          | XL (8–14 hours) — most complex consumer, 20 tables, merge logic       |
| **Risk controls**   | High. 1. Cross-reference every field mapping against legacy. 2. Test merge-upsert correctness (section A writes partial, section B writes rest). 3. Test with real EODHD sample data if available. 4. Audit for duplicate dict keys. |

---

### MD-022 — Implement Instruments API Endpoints

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-022                                                                |
| **Title**           | Implement instruments REST API endpoints                               |
| **Objective**       | Create FastAPI router with search/list, detail, and symbol-lookup endpoints for instruments |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/api/routers/instruments.py` (legacy), `worldview/services/market-data/src/market_data/app.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/api/__init__.py` (create), `worldview/services/market-data/src/market_data/api/routers/__init__.py` (create), `worldview/services/market-data/src/market_data/api/routers/instruments.py` (create), `worldview/services/market-data/src/market_data/api/schemas/__init__.py` (create), `worldview/services/market-data/src/market_data/api/schemas/instruments.py` (create), `worldview/services/market-data/src/market_data/api/dependencies.py` (create), `worldview/services/market-data/src/market_data/app.py` (add router), `worldview/services/market-data/tests/unit/test_instruments_api.py` (create) |
| **Dependencies**    | MD-012 (domain entities), MD-016 (repositories), MD-017 (UoW)         |
| **Implementation steps** | 1. Create `schemas/instruments.py` with Pydantic response models: `InstrumentResponse`, `InstrumentListResponse`, `InstrumentSearchParams`. 2. Create `dependencies.py` with FastAPI dependency for UoW injection. 3. Create `routers/instruments.py` with: `GET /api/v1/instruments` (query params: `search`, `exchange`, `has_ohlcv`, `has_quotes`, `has_fundamentals`, `limit`, `offset`), `GET /api/v1/instruments/{instrument_id}`, `GET /api/v1/instruments/symbol/{symbol}` (query param: `exchange`). 4. Register router in `app.py`. 5. Return proper HTTP status codes (404 for not found, 422 for validation errors). |
| **Tests — unit**    | `test_list_instruments`, `test_list_instruments_with_filters`, `test_get_instrument_by_id`, `test_get_instrument_not_found_404`, `test_get_instrument_by_symbol`, `test_search_instruments_pagination` |
| **Tests — container** | API tests with real DB in MD-029                                     |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` API section           |
| **DoD / Acceptance** | 1. All 3 instrument endpoints working. 2. Search/filter/pagination. 3. 404 on not found. 4. Response schemas match documented contracts. 5. Tests pass. 6. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Low. Standard FastAPI CRUD endpoints.                                 |

---

### MD-023 — Implement OHLCV API Endpoints

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-023                                                                |
| **Title**           | Implement OHLCV REST API endpoints                                     |
| **Objective**       | Create FastAPI router for OHLCV bar queries with timeframe filtering, date range, and bulk retrieval |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/api/routers/ohlcv.py` (legacy), `worldview/services/market-data/src/market_data/infrastructure/db/queries/ohlcv_queries.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/api/routers/ohlcv.py` (create), `worldview/services/market-data/src/market_data/api/schemas/ohlcv.py` (create), `worldview/services/market-data/src/market_data/app.py` (add router), `worldview/services/market-data/tests/unit/test_ohlcv_api.py` (create) |
| **Dependencies**    | MD-016 (repositories), MD-017 (UoW), MD-018 (TimescaleDB queries)      |
| **Implementation steps** | 1. Create `schemas/ohlcv.py` with Pydantic models: `OHLCVBarResponse`, `OHLCVListResponse`, `OHLCVRangeResponse`. 2. Create `routers/ohlcv.py` with: `GET /api/v1/ohlcv/{instrument_id}` (query params: `timeframe`, `start`, `end`, `limit`), `GET /api/v1/ohlcv/{instrument_id}/timeframes` (available timeframes), `GET /api/v1/ohlcv/{instrument_id}/range` (min/max date per timeframe), `GET /api/v1/ohlcv/bulk` (query param: `instrument_ids`, `timeframe`, `start`, `end`). 3. Validate timeframe enum. 4. Date range validation (start < end). 5. Register router. |
| **Tests — unit**    | `test_get_ohlcv_bars`, `test_get_ohlcv_bars_with_date_range`, `test_get_ohlcv_bars_invalid_timeframe`, `test_get_available_timeframes`, `test_get_date_range`, `test_bulk_ohlcv`, `test_ohlcv_start_after_end_422` |
| **Tests — container** | API tests with real TimescaleDB in MD-029                            |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` API section           |
| **DoD / Acceptance** | 1. All 4 OHLCV endpoints working. 2. Timeframe validation. 3. Date range pagination. 4. Bulk retrieval. 5. Tests pass. 6. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Medium. Verify TimescaleDB query performance with large result sets.  |

---

### MD-024 — Implement Quotes API Endpoints

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-024                                                                |
| **Title**           | Implement quotes REST API endpoints with Valkey caching                |
| **Objective**       | Create FastAPI router for latest-quote retrieval with cache-aside Valkey support |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/api/routers/quotes.py` (legacy), `worldview/libs/messaging/src/messaging/valkey.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/api/routers/quotes.py` (create), `worldview/services/market-data/src/market_data/api/schemas/quotes.py` (create), `worldview/services/market-data/src/market_data/app.py` (add router), `worldview/services/market-data/tests/unit/test_quotes_api.py` (create) |
| **Dependencies**    | MD-008 (ValkeyClient), MD-016 (repositories), MD-017 (UoW)            |
| **Implementation steps** | 1. Create `schemas/quotes.py` with: `QuoteResponse`, `BatchQuoteRequest`, `BatchQuoteResponse`. 2. Create `routers/quotes.py` with: `GET /api/v1/quotes/{instrument_id}` (cache-aside: check Valkey → if miss, query DB → cache with 5s TTL → return), `POST /api/v1/quotes/batch` (body: list of instrument_ids → return dict of quotes), `GET /api/v1/quotes/latest` (query param: `instrument_ids`). 3. Cache key pattern: `quote:{instrument_id}`. 4. Graceful degradation: if Valkey unavailable, query DB directly. 5. Register router. |
| **Tests — unit**    | `test_get_quote`, `test_get_quote_cache_hit`, `test_get_quote_cache_miss`, `test_get_quote_not_found_404`, `test_batch_quotes`, `test_get_quote_valkey_down_fallback`, `test_quote_cache_ttl` |
| **Tests — container** | API tests with real DB + Valkey in MD-029                            |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` API + caching sections |
| **DoD / Acceptance** | 1. All 3 quotes endpoints working. 2. Cache-aside with 5s TTL. 3. Graceful degradation when Valkey down. 4. Batch retrieval. 5. Tests pass. 6. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Medium. 1. Test cache serialization (quote object → JSON → cache → deserialize). 2. Test Valkey connection failure graceful fallback. |

---

### MD-025 — Implement Fundamentals API Endpoints

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-025                                                                |
| **Title**           | Implement fundamentals REST API endpoints (9 endpoints)                |
| **Objective**       | Create FastAPI router for fundamentals data retrieval across all section types |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/api/routers/fundamentals.py` (legacy), `platform_repo/apps/backend-market-data/src/market_data/api/routers/securities.py` (legacy) |
| **Paths to modify** | `worldview/services/market-data/src/market_data/api/routers/fundamentals.py` (create), `worldview/services/market-data/src/market_data/api/routers/securities.py` (create), `worldview/services/market-data/src/market_data/api/schemas/fundamentals.py` (create), `worldview/services/market-data/src/market_data/api/schemas/securities.py` (create), `worldview/services/market-data/src/market_data/app.py` (add routers), `worldview/services/market-data/tests/unit/test_fundamentals_api.py` (create), `worldview/services/market-data/tests/unit/test_securities_api.py` (create) |
| **Dependencies**    | MD-016 (repositories), MD-017 (UoW)                                    |
| **Implementation steps** | 1. Create `schemas/fundamentals.py` with response models for each section: `IncomeStatementResponse`, `BalanceSheetResponse`, `CashFlowResponse`, `ValuationResponse`, `AnalystConsensusResponse`, `DividendsResponse`, `EarningsResponse`, `FullFundamentalsResponse`. 2. Create `schemas/securities.py` with `SecurityResponse`, `SecurityListResponse`. 3. Create `routers/fundamentals.py` with: `GET /api/v1/fundamentals/{security_id}` (aggregated), per-section endpoints (`income-statement`, `balance-sheet`, `cash-flow`, `valuation`, `analyst-consensus`, `dividends`, `earnings`). Query param: `period_type` (annual/quarterly), `limit`. 4. Create `routers/securities.py` with: `GET /api/v1/securities`, `GET /api/v1/securities/{security_id}`. 5. Register routers. |
| **Tests — unit**    | `test_get_full_fundamentals`, `test_get_income_statement`, `test_get_balance_sheet`, `test_get_cash_flow`, `test_get_valuation`, `test_get_analyst_consensus`, `test_get_dividends`, `test_get_earnings`, `test_fundamentals_not_found_404`, `test_list_securities`, `test_get_security_by_id` |
| **Tests — container** | API tests with real DB in MD-029                                     |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` API section           |
| **DoD / Acceptance** | 1. All 9 fundamentals + 2 securities endpoints working. 2. Period type filtering. 3. Aggregated full fundamentals view. 4. 404 on not found. 5. Tests pass. 6. Docs updated. |
| **Effort**          | L (5–8 hours) — many endpoints but repetitive pattern                 |
| **Risk controls**   | Medium. Verify response schemas match legacy API contracts for backward compatibility. |

---

### MD-026 — Implement Caching Strategy and Invalidation

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-026                                                                |
| **Title**           | Implement Valkey caching strategy with invalidation for quotes API     |
| **Objective**       | Formalize the cache-aside pattern with proper invalidation, TTL management, and graceful degradation |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/` (legacy caching — quotes only, 5s TTL), `worldview/services/market-data/src/market_data/api/routers/quotes.py`, `worldview/services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/cache/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/cache/quote_cache.py` (create), `worldview/services/market-data/tests/unit/test_quote_cache.py` (create) |
| **Dependencies**    | MD-008 (ValkeyClient), MD-020 (quotes consumer invalidation), MD-024 (quotes API caching) |
| **Implementation steps** | 1. Create `quote_cache.py` with `QuoteCache` class wrapping `ValkeyClient`. 2. Methods: `get(instrument_id) -> QuoteResponse | None`, `set(instrument_id, quote, ttl=5)`, `invalidate(instrument_id)`, `invalidate_many(instrument_ids)`. 3. Cache key: `quote:v1:{instrument_id}` (versioned key for cache compatibility). 4. JSON serialization of `QuoteResponse`. 5. Graceful degradation: catch `redis.ConnectionError`, log warning, return `None` (fall through to DB). 6. Integrate into quotes API router and quotes consumer. |
| **Tests — unit**    | `test_quote_cache_get_hit`, `test_quote_cache_get_miss`, `test_quote_cache_set_with_ttl`, `test_quote_cache_invalidate`, `test_quote_cache_graceful_degradation` |
| **Tests — container** | Real Valkey cache test in MD-029                                     |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` caching section; document cache key patterns in `worldview/docs/architecture/` |
| **DoD / Acceptance** | 1. Cache-aside pattern works. 2. 5s TTL. 3. Consumer invalidates on update. 4. Graceful degradation. 5. Versioned cache keys. 6. Tests pass. 7. Docs updated. |
| **Effort**          | S (2–3 hours)                                                         |
| **Risk controls**   | Low. Simple cache wrapper. Ensure JSON serialization handles all field types. |

---

### MD-027 — Implement Market-Data Outbox Dispatcher

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-027                                                                |
| **Title**           | Implement outbox dispatcher for instrument lifecycle events             |
| **Objective**       | Create the service-specific outbox dispatcher that publishes `market.instrument.created` and `market.instrument.updated` events to Kafka via the transactional outbox pattern |
| **Paths to inspect** | `platform_repo/apps/backend-market-data/src/market_data/infrastructure/messaging/outbox/` (legacy dispatcher), `worldview/libs/messaging/src/messaging/outbox.py` (BaseOutboxDispatcher from MD-007), `worldview/services/market-data/src/market_data/domain/events.py` |
| **Paths to modify** | `worldview/services/market-data/src/market_data/infrastructure/messaging/outbox/__init__.py` (create), `worldview/services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher.py` (create), `worldview/services/market-data/tests/unit/test_outbox_dispatcher.py` (create) |
| **Dependencies**    | MD-007 (BaseOutboxDispatcher), MD-013 (domain events), MD-014 (ORM models — outbox_events table), MD-017 (UoW) |
| **Implementation steps** | 1. Create `MarketDataOutboxDispatcher(BaseOutboxDispatcher)`. 2. Configure topic routing: `InstrumentCreated` → `market.instrument.created`, `InstrumentUpdated` → `market.instrument.updated`. 3. Serialize events using Avro schema for `instrument.created.v1`. 4. Wire into `app.py` lifespan: start dispatcher on startup, stop on shutdown. 5. **Fix legacy bug**: ensure Decimal fields serialized as strings and UUID fields serialized as strings before Avro encoding. |
| **Tests — unit**    | `test_dispatcher_routes_instrument_created`, `test_dispatcher_routes_instrument_updated`, `test_dispatcher_serializes_avro`, `test_dispatcher_decimal_uuid_serialization` |
| **Tests — container** | Full outbox dispatch test with real Kafka + Postgres in MD-029       |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` outbox section        |
| **DoD / Acceptance** | 1. Dispatches `InstrumentCreated` to correct topic. 2. Dispatches `InstrumentUpdated` to correct topic. 3. Avro serialization correct. 4. Decimal/UUID bug fixed. 5. Starts/stops with app lifecycle. 6. Tests pass. 7. Docs updated. |
| **Effort**          | M (3–5 hours)                                                         |
| **Risk controls**   | Medium. 1. Verify Avro schema compatibility with Schema Registry. 2. Test with concurrent dispatchers (lease contention). |

---

### MD-028 — Set Up Integration Test Infrastructure (testcontainers)

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-028                                                                |
| **Title**           | Set up testcontainers infrastructure for service container tests       |
| **Objective**       | Create reusable test fixtures with real PostgreSQL+TimescaleDB, Kafka+Schema Registry, MinIO, and Valkey containers for integration testing |
| **Paths to inspect** | `worldview/services/market-data/tests/conftest.py` (existing test setup), `worldview/pyproject.toml` (test deps) |
| **Paths to modify** | `worldview/services/market-data/tests/conftest.py` (extend), `worldview/services/market-data/tests/integration/__init__.py` (create), `worldview/services/market-data/tests/integration/conftest.py` (create — container fixtures), `worldview/services/market-data/tests/integration/fixtures/` (create — sample data), `worldview/services/market-data/pyproject.toml` (add testcontainers dep) |
| **Dependencies**    | MD-015 (Alembic migrations — needed to set up schema in test DB)       |
| **Implementation steps** | 1. Add `testcontainers[postgres,kafka,minio]` to dev dependencies. 2. Create `integration/conftest.py` with session-scoped container fixtures: (a) `pg_container` — `timescale/timescaledb:latest-pg16` with `market_data_db` database. (b) `kafka_container` — `confluentinc/cp-kafka` with Schema Registry. (c) `minio_container` — `minio/minio` with test bucket. (d) `valkey_container` — `valkey/valkey:7`. 3. Create function-scoped fixtures: `db_session` (runs Alembic migrations, yields session, truncates tables after test), `uow` (wraps session in UoW), `object_storage` (S3 client pointed at test MinIO), `valkey_client` (pointed at test Valkey). 4. Create `fixtures/` directory with sample OHLCV JSONL, quotes JSON, and fundamentals JSON files. 5. Register `@pytest.mark.integration` marker. |
| **Tests — unit**    | N/A (this IS the test infrastructure)                                  |
| **Tests — container** | `test_pg_container_starts`, `test_migrations_run_successfully`, `test_kafka_container_starts`, `test_minio_container_starts`, `test_valkey_container_starts` |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/developer-guide/testing.md` (if exists) or `worldview/services/market-data/README.md` with integration test instructions |
| **DoD / Acceptance** | 1. All 4 containers start reliably. 2. Alembic migrations run in test DB. 3. Tables truncated between tests. 4. Session-scoped (fast). 5. Sample fixture data present. 6. CI-compatible (Docker-in-Docker). 7. Docs updated. |
| **Effort**          | L (5–8 hours) — complex container orchestration                       |
| **Risk controls**   | High. 1. TimescaleDB container image availability. 2. Container startup time (session scope mitigates). 3. CI Docker-in-Docker support. 4. Port conflicts. |

---

### MD-029 — Implement Service Container Tests

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-029                                                                |
| **Title**           | Implement comprehensive service container integration tests            |
| **Objective**       | Create integration tests exercising consumers, API, repositories, and outbox dispatcher against real infrastructure containers |
| **Paths to inspect** | `worldview/services/market-data/tests/integration/conftest.py` (test infra from MD-028), all consumer/API/repo implementations |
| **Paths to modify** | `worldview/services/market-data/tests/integration/test_ohlcv_consumer.py` (create), `worldview/services/market-data/tests/integration/test_quotes_consumer.py` (create), `worldview/services/market-data/tests/integration/test_fundamentals_consumer.py` (create), `worldview/services/market-data/tests/integration/test_ohlcv_api.py` (create), `worldview/services/market-data/tests/integration/test_quotes_api.py` (create), `worldview/services/market-data/tests/integration/test_fundamentals_api.py` (create), `worldview/services/market-data/tests/integration/test_ohlcv_repo.py` (create), `worldview/services/market-data/tests/integration/test_outbox.py` (create), `worldview/services/market-data/tests/integration/test_migrations.py` (create) |
| **Dependencies**    | MD-028 (test infrastructure), MD-019–MD-027 (all implementations)      |
| **Implementation steps** | 1. **Migration tests**: `test_upgrade_head`, `test_downgrade_base`, `test_hypertable_created`. 2. **Repository tests**: `test_ohlcv_bulk_upsert_with_priority` (insert → upsert with higher priority → verify update; upsert with lower priority → verify no update), `test_instrument_search`, `test_quote_upsert`, `test_fundamentals_merge_upsert`. 3. **Consumer tests**: produce test Avro message to Kafka → consumer processes → verify DB state. Test each consumer: OHLCV (verify bars in DB), quotes (verify quote + cache), fundamentals (verify 20 tables). 4. **API tests**: seed DB → call endpoint → verify response schema + data. 5. **Outbox tests**: create domain event → commit UoW → verify outbox row → dispatcher sends to Kafka → verify Kafka message. 6. **Idempotency tests**: process same event twice → verify only one DB write. 7. **Error tests**: inject S3 failure → verify RetryableError → verify no commit. |
| **Tests — unit**    | N/A                                                                  |
| **Tests — container** | All of the above (25+ integration test cases)                        |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update test documentation with integration test catalog               |
| **DoD / Acceptance** | 1. ≥25 integration tests pass. 2. Each consumer tested end-to-end. 3. Each API group tested. 4. Repo tests cover priority upsert. 5. Outbox dispatch verified. 6. Idempotency verified. 7. Error handling verified. 8. All tests pass in CI. |
| **Effort**          | XL (10–16 hours) — many tests, complex setup                          |
| **Risk controls**   | High. 1. Tests must be independent (no ordering dependency). 2. Tables truncated between tests. 3. Container startup time managed via session scope. 4. May need test timeouts for Kafka consumer polling. |

---

### MD-030 — Implement Platform QA Scenarios

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-030                                                                |
| **Title**           | Implement platform QA end-to-end test scenarios                        |
| **Objective**       | Create end-to-end tests validating the full pipeline: ingestion → market-data consumers → API → downstream consumer verification |
| **Paths to inspect** | `worldview/services/market-data/tests/integration/` (container tests from MD-029) |
| **Paths to modify** | `worldview/services/market-data/tests/e2e/__init__.py` (create), `worldview/services/market-data/tests/e2e/conftest.py` (create), `worldview/services/market-data/tests/e2e/test_ohlcv_pipeline.py` (create), `worldview/services/market-data/tests/e2e/test_quotes_pipeline.py` (create), `worldview/services/market-data/tests/e2e/test_fundamentals_pipeline.py` (create), `worldview/services/market-data/tests/e2e/test_instrument_lifecycle.py` (create) |
| **Dependencies**    | MD-029 (all container tests pass first)                                |
| **Implementation steps** | 1. **OHLCV pipeline test**: Upload JSONL to MinIO → produce `market.dataset.fetched` → wait for consumer → query OHLCV API → verify bars returned with correct data. 2. **Quotes pipeline test**: Upload JSON to MinIO → produce event → wait for consumer → query quotes API → verify quote + verify Valkey cached. 3. **Fundamentals pipeline test**: Upload JSON to MinIO → produce event → wait for consumer → query each fundamentals endpoint → verify data across all 20 tables. 4. **Instrument lifecycle test**: Trigger first OHLCV event for new symbol → verify `instrument.created` event on Kafka topic → trigger second event with flag change → verify `instrument.updated` event. 5. Mark all tests with `@pytest.mark.slow`. |
| **Tests — unit**    | N/A                                                                  |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | All 4 pipeline scenarios above                                        |
| **Documentation**   | Update `worldview/docs/services/market-data.md` QA scenarios section; create runbook for manual QA |
| **DoD / Acceptance** | 1. OHLCV pipeline runs end-to-end. 2. Quotes pipeline with cache verification. 3. Fundamentals pipeline across all sections. 4. Instrument lifecycle events verified on Kafka. 5. All pipeline tests pass. 6. Docs updated. |
| **Effort**          | L (6–10 hours) — complex orchestration, timing-sensitive               |
| **Risk controls**   | High. 1. Consumer polling timeouts (use asyncio.wait_for with generous timeout). 2. Kafka message ordering. 3. MinIO upload timing. |

---

### MD-031 — Wire Application Lifespan and Service Composition

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-031                                                                |
| **Title**           | Wire FastAPI lifespan with all infrastructure components               |
| **Objective**       | Connect all infrastructure (DB engine, session factories, consumers, outbox dispatcher, Valkey, object storage, metrics, tracing) in the FastAPI lifespan and dependency injection |
| **Paths to inspect** | `worldview/services/market-data/src/market_data/app.py` (current scaffold), all infrastructure modules |
| **Paths to modify** | `worldview/services/market-data/src/market_data/app.py` (rewrite lifespan), `worldview/services/market-data/src/market_data/config.py` (extend if needed), `worldview/services/market-data/src/market_data/api/dependencies.py` (update DI), `worldview/services/market-data/pyproject.toml` (add lib dependencies), `worldview/services/market-data/tests/test_health.py` (update if needed) |
| **Dependencies**    | MD-005–MD-027 (all infrastructure components)                          |
| **Implementation steps** | 1. Update `pyproject.toml` to add dependencies: `common`, `contracts`, `messaging`, `storage`, `observability` (relative path deps). 2. Rewrite `lifespan()`: startup — create async engine, session factories, ValkeyClient, S3ObjectStorage, configure logging/metrics/tracing, start 3 consumers as background tasks, start outbox dispatcher. Shutdown — stop consumers, stop dispatcher, close Valkey, dispose engine. 3. Update `readyz` endpoint to check DB, Kafka, MinIO, Valkey. 4. Add `/metrics` endpoint for Prometheus. 5. Add Prometheus + OTel middleware. 6. Wire UoW factory into FastAPI dependency injection. |
| **Tests — unit**    | `test_readyz_checks_dependencies` (mock deps), `test_lifespan_starts_consumers`, `test_lifespan_cleanup_on_shutdown` |
| **Tests — container** | Covered by MD-029 integration tests                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/services/market-data.md` deployment section    |
| **DoD / Acceptance** | 1. All consumers start on app startup. 2. Outbox dispatcher starts. 3. `readyz` checks all dependencies. 4. `/metrics` returns Prometheus data. 5. Clean shutdown (SIGTERM → graceful stop). 6. Tests pass. 7. Docs updated. |
| **Effort**          | M (4–6 hours)                                                         |
| **Risk controls**   | Medium. 1. Consumer startup ordering. 2. Graceful shutdown race conditions. 3. Dependency injection scope management. |

---

### MD-032 — Comprehensive Documentation Update

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-032                                                                |
| **Title**           | Update all documentation for market-data service                       |
| **Objective**       | Ensure all documentation reflects the final implementation: API reference, consumer behavior, DB schema, caching, configuration, deployment, and troubleshooting |
| **Paths to inspect** | `worldview/docs/services/market-data.md`, `worldview/docs/architecture/`, `worldview/docs/libs/`, `worldview/docs/contracts/`, `worldview/docs/runbooks/` |
| **Paths to modify** | `worldview/docs/services/market-data.md` (major update), `worldview/docs/libs/contracts.md` (update), `worldview/docs/libs/messaging.md` (update), `worldview/docs/libs/storage.md` (update), `worldview/docs/libs/observability.md` (update), `worldview/docs/architecture/decisions/XXXX-timescaledb-hypertable.md` (create ADR), `worldview/docs/runbooks/market-data-troubleshooting.md` (create) |
| **Dependencies**    | MD-031 (all implementation complete)                                   |
| **Implementation steps** | 1. Update `market-data.md` with: complete API reference with request/response examples, all consumer behaviors, complete DB schema documentation, caching strategy, configuration reference (all env vars), deployment guide. 2. Update lib docs with newly implemented modules. 3. Create ADR for TimescaleDB hypertable decision. 4. Create troubleshooting runbook: common errors, recovery procedures, how to inspect failed tasks, how to force-retry, how to check outbox status. 5. Verify all inline code comments reference correct docs. |
| **Tests — unit**    | N/A                                                                  |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | This IS the documentation task.                                        |
| **DoD / Acceptance** | 1. API reference complete and accurate. 2. All consumers documented. 3. DB schema documented with ER diagram description. 4. ADR created. 5. Runbook created. 6. All lib docs updated. 7. No stale documentation references. |
| **Effort**          | M (4–6 hours) — large doc update but no code                          |
| **Risk controls**   | Low. Documentation-only change.                                       |

---

### MD-033 — Performance Validation Plan

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-033                                                                |
| **Title**           | Execute performance validation and benchmarking                        |
| **Objective**       | Validate that the migrated service meets performance requirements: consumer throughput, API latency, query performance, and TimescaleDB optimization |
| **Paths to inspect** | All service implementation files, `worldview/docs/services/market-data.md` (performance requirements if documented) |
| **Paths to modify** | `worldview/services/market-data/tests/performance/__init__.py` (create), `worldview/services/market-data/tests/performance/test_ohlcv_throughput.py` (create), `worldview/services/market-data/tests/performance/test_api_latency.py` (create), `worldview/services/market-data/tests/performance/test_query_performance.py` (create) |
| **Dependencies**    | MD-029 (integration test infrastructure), MD-031 (full service wired)  |
| **Implementation steps** | 1. **Consumer throughput test**: produce 10,000 OHLCV bars → measure time to fully materialize → target: ≥1,000 bars/second. 2. **API latency test**: seed DB with 100K OHLCV bars → measure p50/p95/p99 for `/api/v1/ohlcv/{id}` with various date ranges → target: p95 < 100ms. 3. **Query performance test**: test TimescaleDB chunk pruning (verify query plan only scans relevant chunks). 4. **Cache performance test**: measure quotes API latency with cache hit vs miss → target: cache hit < 5ms. 5. **Bulk upsert benchmark**: measure bulk upsert performance for 5,000 bars → establish baseline. 6. **Fundamentals consumer benchmark**: measure processing time for full fundamentals payload (20 tables). |
| **Tests — unit**    | N/A                                                                  |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | All performance benchmarks above (marked `@pytest.mark.slow`)         |
| **Documentation**   | Create `worldview/docs/services/market-data-performance.md` with benchmark results and tuning recommendations |
| **DoD / Acceptance** | 1. Consumer throughput meets target. 2. API latency meets SLO. 3. TimescaleDB chunk pruning verified. 4. Benchmarks documented. 5. Any performance issues identified with mitigation plans. |
| **Effort**          | L (5–8 hours) — setup-intensive, requires representative data          |
| **Risk controls**   | Medium. 1. Benchmark results depend on hardware. 2. Use relative comparisons. 3. Document test environment specs. |

---

### MD-034 — Contract and Schema Versioning Verification

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-034                                                                |
| **Title**           | Verify Avro schema compatibility and contract versioning               |
| **Objective**       | Ensure all Avro schemas are forward-compatible with Schema Registry, all REST API contracts are versioned, and all event schemas maintain backward compatibility |
| **Paths to inspect** | `worldview/libs/contracts/`, `worldview/libs/messaging/`, Avro `.avsc` files, API response models |
| **Paths to modify** | `worldview/services/market-data/tests/contract/__init__.py` (create), `worldview/services/market-data/tests/contract/test_avro_compatibility.py` (create), `worldview/services/market-data/tests/contract/test_api_contracts.py` (create) |
| **Dependencies**    | MD-001–MD-003 (contracts), MD-022–MD-025 (API schemas)                 |
| **Implementation steps** | 1. **Avro compatibility tests**: register schemas with Schema Registry → check BACKWARD compatibility mode → verify new fields have defaults → verify no field removals. 2. **REST API contract tests**: snapshot API response schemas → compare against documented contracts → verify `/api/v1/` versioning. 3. **Event envelope tests**: verify all domain events include required envelope fields (`event_id`, `event_type`, `schema_version`, `occurred_at`). 4. **Schema version consistency**: verify `OHLCV_SCHEMA_VERSION`, `QUOTE_SCHEMA_VERSION`, `FUNDAMENTAL_SCHEMA_VERSION` match Avro schema versions. |
| **Tests — unit**    | `test_avro_schema_backward_compatible`, `test_api_response_schema_matches_doc`, `test_event_envelope_fields`, `test_schema_versions_consistent` |
| **Tests — container** | `test_schema_registry_compatibility` (requires real Schema Registry)  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Update `worldview/docs/contracts/` with compatibility policy           |
| **DoD / Acceptance** | 1. All Avro schemas backward-compatible. 2. API contracts versioned. 3. Event envelope complete. 4. Schema versions consistent. 5. Tests pass. |
| **Effort**          | M (3–4 hours)                                                         |
| **Risk controls**   | Medium. Schema Registry compatibility check might fail if legacy schemas evolved without forward compatibility. |

---

### MD-035 — Release Preparation and Rollback Planning

| Field               | Value                                                                 |
| ------------------- | --------------------------------------------------------------------- |
| **ID**              | MD-035                                                                |
| **Title**           | Prepare staged rollout plan and rollback procedures                    |
| **Objective**       | Create deployment checklist, staged rollout plan, canary verification steps, and rollback procedures |
| **Paths to inspect** | `worldview/infra/`, `worldview/docs/services/market-data.md`, `worldview/docs/runbooks/` |
| **Paths to modify** | `worldview/docs/runbooks/market-data-deployment.md` (create), `worldview/docs/runbooks/market-data-rollback.md` (create), `worldview/services/market-data/configs/prod.env.example` (update with all new env vars) |
| **Dependencies**    | MD-031–MD-034 (all implementation and validation complete)             |
| **Implementation steps** | 1. **Deployment checklist**: verify all tests pass, verify schema migrations tested, verify Avro schemas registered, verify monitoring dashboards exist. 2. **Staged rollout plan**: Phase 1 — deploy DB migrations only. Phase 2 — deploy service with consumers disabled (API only, verify schema). Phase 3 — enable OHLCV consumer (lowest risk). Phase 4 — enable quotes consumer. Phase 5 — enable fundamentals consumer. Phase 6 — enable outbox dispatcher. 3. **Canary verification**: for each phase, define what to check (logs, metrics, API responses). 4. **Rollback procedures**: per-phase rollback steps. DB rollback via `alembic downgrade`. Consumer rollback via consumer group reset. 5. **Update prod env template** with all new environment variables. |
| **Tests — unit**    | N/A                                                                  |
| **Tests — container** | N/A                                                                  |
| **Tests — platform** | N/A                                                                  |
| **Documentation**   | Create deployment and rollback runbooks                                |
| **DoD / Acceptance** | 1. Deployment checklist complete. 2. 6-phase staged rollout documented. 3. Per-phase canary verification steps. 4. Per-phase rollback procedures. 5. Prod env template updated. |
| **Effort**          | M (3–4 hours) — documentation and planning                            |
| **Risk controls**   | Low. Planning-only task. Review with team before execution.           |

---

## 5. Milestone-Based Execution Plan & Critical Path

### Milestone Overview

| Milestone | Name                          | Tickets              | Duration Est | Cumulative |
| --------- | ----------------------------- | -------------------- | ------------ | ---------- |
| **M0**    | Foundation Libraries          | MD-001 through MD-011 | 5–7 days     | Week 1     |
| **M1**    | Domain + Schema               | MD-012 through MD-015 | 4–6 days     | Week 2     |
| **M2**    | Data Access Layer             | MD-016 through MD-018 | 4–6 days     | Week 3     |
| **M3**    | Consumers                     | MD-019 through MD-021 | 6–10 days    | Week 4–5   |
| **M4**    | API Layer                     | MD-022 through MD-026 | 5–8 days     | Week 5–6   |
| **M5**    | Outbox + Wiring               | MD-027, MD-031       | 3–5 days     | Week 6–7   |
| **M6**    | Testing + Validation          | MD-028 through MD-030, MD-033, MD-034 | 8–12 days | Week 7–9 |
| **M7**    | Documentation + Release Prep  | MD-032, MD-035       | 3–4 days     | Week 9–10  |

### Critical Path

```
MD-004 → MD-005 → MD-019 → MD-029
         ↑                    ↑
MD-009 ──┘                    │
MD-003 ──────── MD-019 ──────┘
MD-012 → MD-014 → MD-015 → MD-016 → MD-017 → MD-019
                                                 ↓
                                              MD-029 → MD-030
```

**Critical path items** (delays here delay everything):

1. **MD-005 — BaseKafkaConsumer** — blocks all 3 consumers
2. **MD-009 — ObjectStorage** — blocks all 3 consumers (claim-check download)
3. **MD-014/MD-015 — ORM Models + Migrations** — blocks all data access
4. **MD-016 — Repositories** — blocks all consumers and API
5. **MD-017 — Unit of Work** — blocks all consumers and API
6. **MD-019 — OHLCV Consumer** — first consumer, validates entire pipeline

### Parallelization Opportunities

The following groups can be worked on simultaneously:

**Parallel Group 1** (M0 — Foundation):
- MD-001, MD-002 (canonical contracts) — independent
- MD-004 (messaging errors) — independent
- MD-006 (producer) — independent
- MD-008 (Valkey) — independent
- MD-009 (object storage) — independent
- MD-010, MD-011 (observability) — independent

**Parallel Group 2** (M1 — begins after MD-004):
- MD-005 (BaseKafkaConsumer) — depends on MD-004
- MD-012 (domain entities) — independent
- MD-013 (domain events/errors) — depends on MD-004

**Parallel Group 3** (M4 — API endpoints are independent of each other):
- MD-022, MD-023, MD-024, MD-025 — all independent once MD-016/MD-017 done

**Parallel Group 4** (M3 — consumers are independent of each other):
- MD-019, MD-020, MD-021 — all independent once dependencies met

---

## 6. Release Gate Checklist & Rollback Triggers

### 6.1 Release Gate Checklist

| Gate | Criterion                                                  | Verification Method          | Required |
| ---- | ---------------------------------------------------------- | ---------------------------- | -------- |
| G1   | All unit tests pass (≥60% coverage)                        | `pytest -m unit --cov`       | ✅ Yes    |
| G2   | All integration tests pass                                 | `pytest -m integration`      | ✅ Yes    |
| G3   | All contract tests pass                                    | `pytest -m contract`         | ✅ Yes    |
| G4   | Ruff lint clean                                            | `ruff check`                 | ✅ Yes    |
| G5   | MyPy strict passes                                         | `mypy src/`                  | ✅ Yes    |
| G6   | Alembic migrations upgrade+downgrade clean                 | `alembic upgrade head && alembic downgrade base` | ✅ Yes |
| G7   | Avro schemas backward-compatible                           | Schema Registry compat check | ✅ Yes    |
| G8   | API endpoint parity with inventory (22 routes)             | API contract snapshot test   | ✅ Yes    |
| G9   | Consumer throughput meets baseline (≥1000 bars/s)          | Performance test             | ⚠️ Warn   |
| G10  | API p95 latency < 100ms                                    | Performance test             | ⚠️ Warn   |
| G11  | No critical/high severity known bugs                       | Issue tracker review         | ✅ Yes    |
| G12  | Documentation up to date                                   | Doc review checklist         | ✅ Yes    |
| G13  | Deployment runbook approved                                | Team review                  | ✅ Yes    |
| G14  | Rollback procedure tested in staging                       | Manual test                  | ✅ Yes    |
| G15  | Monitoring dashboards configured                           | Visual verification          | ⚠️ Warn   |

### 6.2 Rollback Triggers

| Trigger                                                     | Action                        | Severity |
| ----------------------------------------------------------- | ----------------------------- | -------- |
| Consumer error rate > 5% for 5 minutes                      | Disable affected consumer     | Auto     |
| API error rate (5xx) > 1% for 5 minutes                     | Roll back service deployment  | Auto     |
| DB connection pool exhaustion                                | Roll back service deployment  | Auto     |
| Kafka consumer lag > 10,000 messages for 10 minutes          | Alert + investigate           | Manual   |
| Memory usage > 90% for 5 minutes                            | Alert + scale or rollback     | Manual   |
| Data integrity issue (missing/corrupt data)                  | Disable consumers + rollback  | Manual   |
| Schema Registry incompatibility                              | Roll back schema + service    | Manual   |
| Outbox dispatcher stuck (pending > 1000 for 30 minutes)      | Restart dispatcher            | Manual   |
| Alembic migration failure in production                      | `alembic downgrade` to previous | Manual |
| Downstream service reports data quality issues               | Disable consumers + investigate | Manual  |

### 6.3 Staged Rollout Plan

| Phase | What's Deployed                        | Duration   | Canary Check                              | Rollback |
| ----- | -------------------------------------- | ---------- | ----------------------------------------- | -------- |
| 1     | DB migrations only                     | 1 hour     | Tables exist, indexes present             | `alembic downgrade base` |
| 2     | Service (API only, consumers disabled) | 4 hours    | `/healthz` OK, `/readyz` OK, `/metrics` responsive | Undeploy service |
| 3     | Enable OHLCV consumer                  | 24 hours   | Consumer lag decreasing, OHLCV API returns data | Disable consumer (env flag) |
| 4     | Enable quotes consumer                 | 24 hours   | Quote API returns cached data, consumer healthy | Disable consumer |
| 5     | Enable fundamentals consumer           | 24 hours   | Fundamentals API returns sectioned data | Disable consumer |
| 6     | Enable outbox dispatcher               | 24 hours   | Instrument events appearing on Kafka topics | Disable dispatcher |
| 7     | Full production traffic                | Continuous | All metrics within SLO, no errors        | Full rollback |

---

## Appendix A — Decisions Made

| Decision                                          | Rationale                                                   |
| ------------------------------------------------- | ----------------------------------------------------------- |
| **TimescaleDB hypertable over LIST partitioning**  | MASTER_PLAN.md specifies TimescaleDB; provides automatic chunking, compression, `time_bucket`, continuous aggregates. Legacy LIST partitioning was manual and limited to 9 fixed timeframes. |
| **Async consumer (thread executor) over threading** | Worldview mandates async-first (CLAUDE.md). Legacy `BaseKafkaConsumer` used threading. New design wraps blocking `poll()` in `asyncio.to_thread()` for compatibility with async UoW/repositories. |
| **Fix outbox serialization bug during migration**  | Legacy had unresolved Decimal/UUID JSON serialization issue. Clean slate = clean fix. |
| **Fix model↔migration mismatches**                 | Legacy `failed_tasks` and `outbox_events` models didn't match migration 002 columns. Fresh schema eliminates this technical debt. |
| **Versioned cache keys (`quote:v1:...`)**          | Future-proofs cache schema changes without requiring full cache flush. |
| **Split Alembic migration into 2 files**           | Separation of concerns: schema creation (001) vs TimescaleDB extension (002). Allows running on non-TimescaleDB for testing if needed. |
| **35 atomic tasks instead of fewer large ones**    | Per RULES.md R1 — tests for every behavior change. Per AGENTS.md — small, focused changes. Each task is independently testable and deployable. |

## Appendix B — Ticket Dependency Matrix

| Ticket | Depends On                                    | Blocks                           |
| ------ | --------------------------------------------- | -------------------------------- |
| MD-001 | —                                             | MD-003, MD-020                   |
| MD-002 | —                                             | MD-003, MD-021                   |
| MD-003 | MD-001, MD-002                                | MD-019, MD-020, MD-021           |
| MD-004 | —                                             | MD-005, MD-013                   |
| MD-005 | MD-004                                        | MD-019, MD-020, MD-021           |
| MD-006 | —                                             | MD-007                           |
| MD-007 | MD-006                                        | MD-027                           |
| MD-008 | —                                             | MD-020, MD-026                   |
| MD-009 | —                                             | MD-019, MD-020, MD-021           |
| MD-010 | —                                             | MD-031                           |
| MD-011 | —                                             | MD-031                           |
| MD-012 | —                                             | MD-013, MD-014, MD-016           |
| MD-013 | MD-004, MD-012                                | MD-019, MD-020, MD-021, MD-027   |
| MD-014 | MD-012                                        | MD-015, MD-016                   |
| MD-015 | MD-014                                        | MD-016, MD-018, MD-028           |
| MD-016 | MD-012, MD-014                                | MD-017, MD-019–MD-025            |
| MD-017 | MD-016                                        | MD-019–MD-025, MD-027            |
| MD-018 | MD-014, MD-015, MD-016                        | MD-023                           |
| MD-019 | MD-003, MD-005, MD-009, MD-013, MD-016, MD-017 | MD-029, MD-030                 |
| MD-020 | MD-001, MD-003, MD-005, MD-008, MD-009, MD-016, MD-017 | MD-029, MD-030         |
| MD-021 | MD-002, MD-003, MD-005, MD-009, MD-016, MD-017 | MD-029, MD-030                 |
| MD-022 | MD-012, MD-016, MD-017                        | MD-031                           |
| MD-023 | MD-016, MD-017, MD-018                        | MD-031                           |
| MD-024 | MD-008, MD-016, MD-017                        | MD-031                           |
| MD-025 | MD-016, MD-017                                | MD-031                           |
| MD-026 | MD-008, MD-020, MD-024                        | MD-031                           |
| MD-027 | MD-007, MD-013, MD-014, MD-017                | MD-031                           |
| MD-028 | MD-015                                        | MD-029                           |
| MD-029 | MD-028, MD-019–MD-027                         | MD-030                           |
| MD-030 | MD-029                                        | MD-033                           |
| MD-031 | MD-005–MD-027                                 | MD-029                           |
| MD-032 | MD-031                                        | MD-035                           |
| MD-033 | MD-029, MD-031                                | MD-035                           |
| MD-034 | MD-001–MD-003, MD-022–MD-025                  | MD-035                           |
| MD-035 | MD-032, MD-033, MD-034                        | —                                |
