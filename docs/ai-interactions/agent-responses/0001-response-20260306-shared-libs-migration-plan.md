# 0001 — Shared Libraries Migration: Detailed Plan & Atomic Tasks

## Metadata

- **Prompt ID**: 0001
- **Prompt file**: `docs/ai-interactions/agent-prompts/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md`
- **Execution date**: 2026-03-06
- **Agent role(s)**: Data Platform Engineer + Architecture Decision Lead
- **Scope**: `common`, `contracts`, `observability` (new), `storage`, `messaging`

---

## 1. Executive Summary

1. Five shared libraries form the foundation of every Worldview service; they must be migration-complete before any service migration begins.
2. `common` is **90% migrated** — time utilities and tests are present; `ids.py` and `types.py` are implemented but not yet wired into `__init__.py` or tested.
3. `contracts` is **~30% migrated** — `CanonicalOHLCVBar` and `versions.py` are implemented; `CanonicalQuote`, `CanonicalFundamentals`, three new models (`Article`, `Entity`, `Sentiment`), and `parsing.py` are missing.
4. `observability` is **~25% migrated** — `configure_logging` and `get_logger` are present; `metrics.py` (Prometheus) and `tracing.py` (OpenTelemetry) modules are entirely absent.
5. `storage` is **~20% migrated** — `KeyBuilder` scaffold and `StorageSettings` stub exist; `ObjectStorage` ABC, `S3ObjectStorage` adapter, exceptions, factory, and health check are absent.
6. `messaging` is **~15% migrated** — `AvroDictable` protocol, `load_schema`/`serialize_avro`/`deserialize_avro`, and topic constants exist; the entire Kafka consumer, producer, outbox dispatcher, Valkey client, and error hierarchy are absent.
7. Legacy codebase has ~4,884 lines of library source + ~1,460 lines of tests across 41 files — approximately 60% is directly reusable, the rest needs refactoring or fresh implementation.
8. All 8 Avro schemas are already defined in `infra/kafka/schemas/`; schema validation tasks focus on contract-test alignment, not schema creation.
9. The critical path is: `common` → `contracts` → `observability` → `storage` → `messaging`, with `observability` having no legacy predecessor and blocking metrics extraction from `messaging`.
10. 35 atomic tasks are defined below, grouped into 5 milestones.
11. Rollback strategy relies on Hatch editable installs and Git branch isolation — any lib can be reverted independently.
12. Three ADRs are required: observability stack selection, Valkey key taxonomy, and messaging error classification changes.

---

## 2. Gap Analysis: Legacy vs Target vs Delta

### 2.1 `common`

| Module | Legacy (`platform_repo`) | Target (`worldview`) | Status | Delta |
|--------|--------------------------|----------------------|--------|-------|
| `time.py` | 110 lines — 6 functions | 48 lines — 6 functions | ✅ Implemented | Functionally equivalent; legacy uses `from datetime import UTC`, target uses `timezone.utc` — both valid. Legacy test suite 267 lines vs target 60 lines: **test coverage gap**. |
| `ids.py` | 0 lines (empty placeholder) | 22 lines — 3 functions (`new_uuid`, `new_uuid_str`, `new_ulid`) | ✅ Implemented | Fresh implementation. **Missing**: not exported from `__init__.py`, no tests. |
| `types.py` | 0 lines (empty placeholder) | 14 lines — 7 type aliases | ✅ Implemented | Fresh implementation. **Missing**: not exported from `__init__.py`, no tests. |
| `__init__.py` | Re-exports time functions | Re-exports time functions only | ⚠️ Partial | **Missing**: `ids` and `types` re-exports in `__all__`. |
| `pyproject.toml` | Poetry, python ^3.11 | Hatch, python >=3.11,<3.13, ulid dep | ✅ Migrated | Packaging migrated to Hatch. |
| Tests | 267 lines, 7 test classes | 60 lines, 5 test classes | ⚠️ Partial | Missing: ensure_utc timezone conversion, round-trip edge cases, ids tests, types tests. |

### 2.2 `contracts`

| Module | Legacy | Target | Status | Delta |
|--------|--------|--------|--------|-------|
| `versions.py` | 4 constants (OHLCV=2, QUOTES=1, FUNDAMENTALS=1, MARKET_DATASET_FETCHED=2) | 6 constants (OHLCV=2, QUOTE=1, FUNDAMENTAL=1, ARTICLE=1, ENTITY=1, SENTIMENT=1) | ⚠️ Partial | Target adds 3 new version constants. **Missing**: `MARKET_DATASET_FETCHED_SCHEMA_VERSION` not carried over (needed for existing Avro schema). |
| `canonical/ohlcv.py` | 90 lines, `CanonicalOHLCVBar` (Decimal fields, ClassVar, `provider`, `timeframe`, `fetched_at`) | 55 lines, simplified (float fields, no `provider`/`timeframe`/`fetched_at`) | ⚠️ Diverged | Target uses `float` instead of `Decimal`, drops `provider`/`timeframe`/`fetched_at` fields. **Decision needed**: Are these fields required by consumers? Legacy consumers use them. |
| `canonical/quotes.py` | 76 lines, `CanonicalQuote` | ❌ Missing | ❌ | Needs copy & adapt from legacy. |
| `canonical/fundamentals.py` | 63 lines, `CanonicalFundamentals` | ❌ Missing | ❌ | Needs copy & adapt from legacy. |
| `canonical/article.py` | N/A (new) | ❌ Missing | ❌ | Fresh implementation per MASTER_PLAN. |
| `canonical/entity.py` | N/A (new) | ❌ Missing | ❌ | Fresh implementation per MASTER_PLAN. |
| `canonical/sentiment.py` | N/A (new) | ❌ Missing | ❌ | Fresh implementation per MASTER_PLAN. |
| `parsing.py` | 127 lines, JSONL/JSON/Parquet parser | ❌ Missing | ❌ | Needs copy from legacy, add Polars support. |
| `__init__.py` | Re-exports all models + versions | Re-exports versions only | ⚠️ Partial | **Missing**: model re-exports. |
| Tests | 472 lines (canonical + parsing) | 40 lines (ohlcv only) | ⚠️ Partial | Missing tests for quotes, fundamentals, article, entity, sentiment, parsing. |

### 2.3 `observability` (new — no legacy)

| Module | Legacy | Target | Status | Delta |
|--------|--------|--------|--------|-------|
| `logging.py` | N/A | 72 lines — `configure_logging`, `get_logger` | ✅ Implemented | Functional. |
| `metrics.py` | N/A | ❌ Missing | ❌ | `ServiceMetrics`, `create_metrics()`, `add_prometheus_middleware()` — need fresh build per docs spec. |
| `tracing.py` | N/A | ❌ Missing | ❌ | `configure_tracing()`, `get_tracer()`, `add_otel_middleware()` — need fresh build per docs spec. |
| `__init__.py` | N/A | Exports logging only | ⚠️ Partial | Missing metrics + tracing exports. |
| Tests | N/A | Empty `conftest.py` | ❌ Missing | No tests at all. |

### 2.4 `storage`

| Module | Legacy | Target | Status | Delta |
|--------|--------|--------|--------|-------|
| `interface.py` (`ObjectStorage` ABC) | 224 lines, 6 abstract + 2 concrete methods | ❌ Missing | ❌ | Core abstraction not yet created. |
| `s3_adapter.py` (`S3ObjectStorage`) | 392 lines, full boto3 impl | ❌ Missing | ❌ | Primary adapter not yet created. |
| `exceptions.py` | 163 lines, 6 exception classes | ❌ Missing | ❌ | `InvalidObjectKeyError` exists in `key_builder.py` locally but no hierarchy. |
| `factory.py` | 65 lines, `build_object_storage()` | ❌ Missing | ❌ | |
| `health.py` | 221 lines, 2 health check functions | ❌ Missing | ❌ | |
| `keys.py` → `key_builder.py` | 283 lines, `KeyBuilder`, `KeyComponents`, `validate_key`, `parse_key` | 52 lines, basic `KeyBuilder` + `validate` | ⚠️ Partial | Target is simplified scaffold. Missing: `KeyComponents`, `parse_key`, `build_prefix`, segment validation. |
| `settings.py` | 160 lines, full pydantic model with properties | 21 lines, minimal stub | ⚠️ Partial | Missing: `bucket`, `connect_timeout_seconds`, `read_timeout_seconds`, `max_attempts`, SSL properties. |
| `__init__.py` | Full re-exports | Docstring only | ⚠️ Minimal | No re-exports. |
| Tests | ~921 lines, 4 test files | Empty `conftest.py` | ❌ Missing | |

### 2.5 `messaging`

| Module | Legacy | Target | Status | Delta |
|--------|--------|--------|--------|-------|
| `kafka/consumer/base.py` | 576 lines, `BaseKafkaConsumer[TFailure]` | ❌ Missing | ❌ | Most complex module. 12 abstract methods. |
| `kafka/consumer/errors.py` | 95 lines, 2-branch error hierarchy (10 classes) | ❌ Missing | ❌ | |
| `kafka/producer.py` | 170 lines, `KafkaProducerConfig`, `OutboxKafkaValue`, serializer dispatcher | ❌ Missing | ❌ | |
| `kafka/serializer.py` | 155 lines, `AvroDictable` protocol, `AvroSerializerConfig`, builder | ⚠️ Partial | `AvroDictable` exists in `schemas.py` but with `to_dict`/`from_dict` not `event_type` property. Legacy version has `event_type` property. **Incompatible**. |
| `kafka/serialization_utils.py` | 65 lines, `load_schema`, `serializer_for_schema`, helpers | ⚠️ Partial | `load_schema`, `serialize_avro`, `deserialize_avro` in `schemas.py`. Missing: `serializer_for_schema`, `iso_datetime`, `decimal_to_str`. |
| `kafka/schema_registry.py` | 33 lines, `SchemaRegistryConfig`, `build_schema_registry_client` | ❌ Missing | ❌ | |
| `kafka/dispatcher/base.py` | 536 lines, `BaseOutboxDispatcher`, 3 protocols | ❌ Missing | ❌ | Second most complex module. |
| `valkey/client.py` | 349 lines, `ValkeyClient`, `ValkeyConfig` | ❌ Missing | ❌ | |
| `topics.py` | Constants for 3 legacy topics | 9 topic constants | ⚠️ Extended | Target already has topics for new services. |
| `schemas.py` | Avro loading + serialization | Protocol + schema utils | ⚠️ Partial | See serializer note above. |
| `__init__.py` | Full re-exports | Docstring only | ⚠️ Minimal | |
| Tests | 0 lines in legacy | Empty `conftest.py` | ❌ Missing | Legacy had no unit tests for messaging either. |

---

## 3. Dependency Graph (Text Form)

```
                    ┌─────────────┐
                    │   common    │  (no deps)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────┴──────┐    │    ┌───────┴────────┐
       │  contracts  │    │    │  observability  │  (no internal deps)
       │ (opt: common)│    │    └───────┬────────┘
       └──────┬──────┘    │            │
              │           │            │
              └─────┬─────┘            │
                    │                  │
              ┌─────┴─────┐           │
              │  storage   │  (no internal deps)
              └─────┬─────┘           │
                    │                 │
              ┌─────┴─────────────────┘
              │
        ┌─────┴──────┐
        │  messaging  │  (depends on: contracts, observability)
        └────────────┘
              │
    ┌─────────┼──────────┬──────────────┐
    │         │          │              │
  S1·Portfolio  S2·Market   S3·Market    ... S4–S9
              Ingestion     Data
```

**Critical Path**: `common` → `contracts` → `observability` → `storage` → `messaging`

**Parallelizable**:
- `observability` can be built in parallel with `contracts` (no mutual dependency)
- `storage` can be built in parallel with `observability` (no mutual dependency)
- Once `contracts` + `observability` are done, `messaging` can begin
- `storage` has no dependency on `contracts` or `observability` directly, but `messaging` depends on all three

---

## 4. Task Backlog — Atomic Tickets

### Milestone 1: `common` Library (Complete)

---

#### T-001: Wire `ids` and `types` into `common.__init__` exports

- **Objective**: Make `common.ids` and `common.types` accessible via the package's public API.
- **Why now**: `ids.py` and `types.py` are implemented but invisible to consumers — they can't `from common import new_uuid`.
- **Files touched**:
  - `libs/common/src/common/__init__.py` — add re-exports for ids (new_uuid, new_uuid_str, new_ulid) and types (all NewType aliases, JsonDict)
- **Prerequisites**: None
- **Steps**:
  1. Add `from common.ids import new_uuid, new_uuid_str, new_ulid` to `__init__.py`
  2. Add `from common.types import TenantId, UserId, InstrumentId, TransactionId, EventId, TopicName, JsonDict` to `__init__.py`
  3. Extend `__all__` with all new exports
  4. Run `ruff check libs/common/`
  5. Run `mypy libs/common/src/`
- **Tests**: Unit — import `from common import new_uuid, TenantId` and assert callable/type works. Container — N/A. QA — N/A.
- **Documentation updates**: Update `libs/common/IMPLEMENTATION.md` — check off items. Update `docs/libs/common.md` if any public API description is out of sync.
- **Definition of Done**: `from common import new_uuid, TenantId` works; `__all__` is complete; lint + typecheck pass.
- **Risks/Mitigations**: Low risk. Purely additive.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-002: Add comprehensive tests for `common.ids`

- **Objective**: Achieve full test coverage for ID generation utilities.
- **Why now**: `ids.py` has zero tests; it's a foundation for every entity in the system.
- **Files touched**:
  - `libs/common/tests/test_ids.py` (create)
- **Prerequisites**: T-001
- **Steps**:
  1. Create `test_ids.py`
  2. `TestNewUuid`: returns `uuid.UUID`, is v4, two calls return different values
  3. `TestNewUuidStr`: returns `str`, valid UUID format
  4. `TestNewUlid`: returns `str`, 26-char ULID, two sequential calls are time-ordered
  5. Run tests: `cd libs/common && python -m pytest tests/test_ids.py -v`
- **Tests**: Unit — 6+ test methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: All tests green; branch coverage ≥ 95% for `ids.py`.
- **Risks/Mitigations**: ULID ordering test may be flaky if called within same millisecond — add small sleep or assert ≥ (not >).
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-003: Add comprehensive tests for `common.types`

- **Objective**: Verify type aliases work correctly with mypy and at runtime.
- **Why now**: Types are used across every service; correctness must be verified before depending services.
- **Files touched**:
  - `libs/common/tests/test_types.py` (create)
- **Prerequisites**: T-001
- **Steps**:
  1. Create `test_types.py`
  2. Test each `NewType` wraps correctly: `TenantId(uuid4())` is a UUID, `EventId("abc")` is a str
  3. Test `JsonDict` annotation works as expected
  4. Run tests
- **Tests**: Unit — 7+ test methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: All tests green; mypy strict passes on test file.
- **Risks/Mitigations**: None — NewType is zero-cost at runtime.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-004: Expand `common.time` test suite to match legacy coverage

- **Objective**: Port the 267-line legacy test suite and strengthen edge-case coverage.
- **Why now**: Target has only 60 lines of tests vs 267 in legacy — coverage gap for a foundational module.
- **Files touched**:
  - `libs/common/tests/test_time.py` — expand existing
- **Prerequisites**: None
- **Steps**:
  1. Review legacy `platform_repo/libs/common/tests/test_time.py` for test cases not present in target
  2. Add: `TestEnsureUtc` — timezone conversion from non-UTC aware datetimes (using `zoneinfo`)
  3. Add: `TestToIso8601` — format edge cases (midnight, microseconds, max year)
  4. Add: `TestFromIso8601` — parse `+00:00` suffix, various ISO formats
  5. Add: `TestParseBarDate` — invalid formats, edge dates
  6. Add: `TestParseBarDatetime` — date-only as datetime, format mismatches
  7. Add: `TestRoundTrip` — `to_iso8601(from_iso8601(s)) == s` property test
  8. Run tests
- **Tests**: Unit — 15+ added test methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: Test file ≥ 200 lines; all edge cases from legacy ported; 100% branch coverage for `time.py`.
- **Risks/Mitigations**: `parse_bar_date` returns `datetime` in target vs `date` in legacy — verify consumer expectations.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-005: Mark `common` IMPLEMENTATION.md complete

- **Objective**: Update tracking document to reflect migration status.
- **Why now**: Gates Milestone 1 completion.
- **Files touched**:
  - `libs/common/IMPLEMENTATION.md`
- **Prerequisites**: T-001, T-002, T-003, T-004
- **Steps**:
  1. Check off all items in IMPLEMENTATION.md
  2. Change `Status: Scaffold` → `Status: Complete`
  3. Add migration verification date
- **Tests**: N/A.
- **Documentation updates**: `IMPLEMENTATION.md` itself.
- **Definition of Done**: All checkboxes checked; status updated.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

### Milestone 2: `contracts` Library (Complete)

---

#### T-006: Add `MARKET_DATASET_FETCHED_SCHEMA_VERSION` to versions.py

- **Objective**: Carry over the version constant needed by the existing `market.dataset.fetched` Avro schema.
- **Why now**: Without this constant, the market ingestion service migration (prompt 0003) will fail.
- **Files touched**:
  - `libs/contracts/src/contracts/versions.py`
  - `libs/contracts/src/contracts/__init__.py` (add re-export)
- **Prerequisites**: None
- **Steps**:
  1. Add `MARKET_DATASET_FETCHED_SCHEMA_VERSION: int = 2` to `versions.py`
  2. Add re-export in `__init__.py`
  3. Lint check
- **Tests**: Unit — import and assert value == 2. Container — N/A. QA — N/A.
- **Documentation updates**: None (docs already list this as v2 in REUSE_FROM_ORIGINAL_THESIS.md).
- **Definition of Done**: Constant importable; lint passes.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-007: Reconcile `CanonicalOHLCVBar` with legacy (field parity decision)

- **Objective**: Ensure the target OHLCV model has field parity with legacy where needed by consumers.
- **Why now**: Legacy has `provider`, `timeframe`, `fetched_at` fields that target omits; uses `Decimal` where target uses `float`. Consumers (Market Data service) depend on these fields.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/ohlcv.py`
  - `libs/contracts/tests/test_ohlcv.py`
- **Prerequisites**: None
- **Steps**:
  1. **Decision**: Add `provider: str = ""`, `timeframe: str = "1d"`, `fetched_at: datetime | None = None` as optional fields (forward-compatible, won't break existing usage)
  2. **Decision**: Keep `float` instead of `Decimal` — simpler, sufficient for OHLCV data. Document this delta from legacy.
  3. Update `from_dict` and `to_dict` to handle the new fields (with defaults for backward compat)
  4. Update tests for new fields
  5. Validate `to_dict()` output matches `market.dataset.fetched.avsc` claim-check schema expectations
- **Tests**: Unit — round-trip with/without optional fields; frozen check; schema_version check. Container — N/A. QA — N/A.
- **Documentation updates**: Add a note in `docs/libs/contracts.md` about float vs Decimal decision. Update OHLCV section.
- **Definition of Done**: `CanonicalOHLCVBar` has all fields needed by legacy consumers; tests pass; documented.
- **Risks/Mitigations**: Risk: precision loss from Decimal → float. Mitigation: OHLCV financial data precision is adequate at float64 (~15 sig digits).
- **Effort**: S | **Owner**: Data Platform Engineer

---

#### T-008: Implement `CanonicalQuote` model

- **Objective**: Port the `CanonicalQuote` frozen dataclass from legacy.
- **Why now**: Required by Market Data service's quotes consumer.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/quotes.py` (create)
  - `libs/contracts/src/contracts/canonical/__init__.py` (add export)
  - `libs/contracts/src/contracts/__init__.py` (add re-export)
  - `libs/contracts/tests/test_quotes.py` (create)
- **Prerequisites**: None
- **Steps**:
  1. Copy `CanonicalQuote` from legacy, adapt: use `float` instead of `Decimal`, use `QUOTE_SCHEMA_VERSION`
  2. Implement `from_dict`, `to_dict` methods
  3. Add to canonical `__init__.py` and root `__init__.py`
  4. Write tests: creation, roundtrip, frozen, schema_version, optional fields
- **Tests**: Unit — 5+ test methods. Contract — validate `to_dict()` output. Container — N/A. QA — N/A.
- **Documentation updates**: Verify `docs/libs/contracts.md` already lists CanonicalQuote — it does.
- **Definition of Done**: `from contracts.canonical import CanonicalQuote` works; tests pass.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-009: Implement `CanonicalFundamentals` model

- **Objective**: Port the `CanonicalFundamentals` frozen dataclass from legacy.
- **Why now**: Required by Market Data service's fundamentals consumer.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/fundamentals.py` (create)
  - `libs/contracts/src/contracts/canonical/__init__.py` (update)
  - `libs/contracts/src/contracts/__init__.py` (update)
  - `libs/contracts/tests/test_fundamentals.py` (create)
- **Prerequisites**: None
- **Steps**:
  1. Copy `CanonicalFundamentals` from legacy, adapt to Hatch conventions
  2. Implement `from_dict`, `to_dict`
  3. Export from package
  4. Write tests
- **Tests**: Unit — 4+ test methods. Container — N/A. QA — N/A.
- **Documentation updates**: Verify contracts doc lists fundamentals.
- **Definition of Done**: Importable, tested, lint-clean.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-010: Implement `CanonicalArticle` model (new)

- **Objective**: Create the canonical article model for the Content pipeline services (S4/S5).
- **Why now**: Content ingestion and content store services depend on a shared article contract.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/article.py` (create)
  - `libs/contracts/src/contracts/canonical/__init__.py` (update)
  - `libs/contracts/src/contracts/__init__.py` (update)
  - `libs/contracts/tests/test_article.py` (create)
- **Prerequisites**: T-006 (needs `ARTICLE_SCHEMA_VERSION`)
- **Steps**:
  1. Design fields based on `content.article.stored.v1.avsc`: `article_id`, `source_domain`, `title`, `url`, `language`, `word_count`, `is_duplicate`, `duplicate_of`, `published_at`, `body_text`, `schema_version`
  2. Implement frozen dataclass with `from_dict`, `to_dict`
  3. Export from package
  4. Write contract tests validating alignment with Avro schema
- **Tests**: Unit — 6+ test methods including Avro alignment. Container — N/A. QA — N/A.
- **Documentation updates**: `docs/libs/contracts.md` already lists CanonicalArticle v1.
- **Definition of Done**: Model matches Avro schema fields; tests pass; importable.
- **Risks/Mitigations**: Risk: Avro schema may evolve before Content service implementation. Mitigation: forward-compatible design (optional fields with defaults).
- **Effort**: S | **Owner**: Data Platform Engineer

---

#### T-011: Implement `CanonicalEntity` model (new)

- **Objective**: Create the canonical entity model for NLP pipeline / Knowledge Graph (S6/S7).
- **Why now**: Part of the contracts completeness requirement; blocks Intelligence service.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/entity.py` (create)
  - `libs/contracts/src/contracts/canonical/__init__.py` (update)
  - `libs/contracts/src/contracts/__init__.py` (update)
  - `libs/contracts/tests/test_entity.py` (create)
- **Prerequisites**: T-006
- **Steps**:
  1. Design fields: `entity_id`, `entity_type` (Person/Company/Location/Event), `name`, `canonical_name`, `source_article_id`, `confidence`, `metadata` (JsonDict), `schema_version`
  2. Implement frozen dataclass
  3. Export and test
- **Tests**: Unit — 5+ methods. Container — N/A. QA — N/A.
- **Documentation updates**: Verify docs/libs/contracts.md alignment.
- **Definition of Done**: Importable, tested.
- **Risks/Mitigations**: Entity type enum may change during S6/S7 design — keep as string for now with validation in application layer.
- **Effort**: S | **Owner**: Data Platform Engineer

---

#### T-012: Implement `CanonicalSentiment` model (new)

- **Objective**: Create the canonical sentiment analysis result model for S6.
- **Why now**: Completes the contracts library for the full Intelligence pipeline.
- **Files touched**:
  - `libs/contracts/src/contracts/canonical/sentiment.py` (create)
  - `libs/contracts/src/contracts/canonical/__init__.py` (update)
  - `libs/contracts/src/contracts/__init__.py` (update)
  - `libs/contracts/tests/test_sentiment.py` (create)
- **Prerequisites**: T-006
- **Steps**:
  1. Design fields: `article_id`, `label` (positive/negative/neutral), `score` (float 0.0–1.0), `model_name`, `model_version`, `schema_version`
  2. Implement frozen dataclass
  3. Export and test
- **Tests**: Unit — 4+ methods including score range validation. Container — N/A. QA — N/A.
- **Documentation updates**: Verify docs/libs/contracts.md.
- **Definition of Done**: Importable, tested.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-013: Implement `parsing.py` utilities

- **Objective**: Port the JSONL/JSON/Parquet parsing module from legacy.
- **Why now**: Used by Market Data consumers to deserialize claim-check payloads.
- **Files touched**:
  - `libs/contracts/src/contracts/parsing.py` (create)
  - `libs/contracts/src/contracts/__init__.py` (add export)
  - `libs/contracts/tests/test_parsing.py` (create)
- **Prerequisites**: T-007 (needs reconciled OHLCV model for integration tests)
- **Steps**:
  1. Copy `parse_canonical_data`, `_determine_format`, `_parse_jsonl`, `_parse_json`, `_parse_parquet` from legacy
  2. Replace `logging` with `structlog` (import from observability if available, else use structlog directly)
  3. Add optional Polars path for Parquet (future — stub with pyarrow for now)
  4. Write tests including edge cases from legacy test suite (204 lines)
- **Tests**: Unit — 10+ methods (empty, whitespace, invalid JSON, JSONL, nested JSON, Parquet). Container — N/A. QA — N/A.
- **Documentation updates**: Update `docs/libs/contracts.md` parsing section if API changed.
- **Definition of Done**: All parsing formats work; tests match or exceed legacy coverage.
- **Risks/Mitigations**: pyarrow dependency — add as optional dep in pyproject.toml.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-014: Mark `contracts` IMPLEMENTATION.md complete

- **Objective**: Update tracking document.
- **Why now**: Gates Milestone 2.
- **Files touched**:
  - `libs/contracts/IMPLEMENTATION.md`
- **Prerequisites**: T-006 through T-013
- **Steps**:
  1. Check off all items
  2. Update status
- **Tests**: N/A.
- **Documentation updates**: IMPLEMENTATION.md itself.
- **Definition of Done**: All checkboxes checked.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

### Milestone 3: `observability` Library (Complete)

---

#### T-015: Implement `observability.metrics` module

- **Objective**: Build Prometheus metrics integration per `docs/libs/observability.md` spec.
- **Why now**: `messaging` lib needs to emit Kafka consumer/producer/outbox metrics; extracting from inline code requires this module to exist first.
- **Files touched**:
  - `libs/observability/src/observability/metrics.py` (create)
  - `libs/observability/src/observability/__init__.py` (update exports)
- **Prerequisites**: None (independent of logging)
- **Steps**:
  1. Implement `ServiceMetrics` dataclass with fields per spec: `requests_total`, `request_duration_seconds`, `kafka_messages_consumed_total`, `kafka_messages_produced_total`, `outbox_dispatched_total`, `outbox_dispatch_errors_total`
  2. Implement `create_metrics(service_name)` factory
  3. Implement `add_prometheus_middleware(app, metrics)` — FastAPI middleware recording HTTP method/path/status
  4. Export from `__init__.py`
  5. Lint + typecheck
- **Tests**: Unit — metric label validation, counter increment, middleware request handling. Container — N/A. QA — verify `/metrics` endpoint responds with Prometheus format.
- **Documentation updates**: Verify `docs/libs/observability.md` alignment — it already specifies this API.
- **Definition of Done**: `create_metrics("test")` returns valid `ServiceMetrics`; middleware records requests; `/metrics` serves Prometheus format.
- **Risks/Mitigations**: `prometheus_client` multiprocess mode adds complexity — defer, document as known limitation.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-016: Implement `observability.tracing` module

- **Objective**: Build OpenTelemetry tracing integration per spec.
- **Why now**: Required for distributed trace correlation across Kafka consumers and REST APIs.
- **Files touched**:
  - `libs/observability/src/observability/tracing.py` (create)
  - `libs/observability/src/observability/__init__.py` (update exports)
- **Prerequisites**: None
- **Steps**:
  1. Implement `configure_tracing(service_name, otlp_endpoint=None)` — sets up TracerProvider + OTLP exporter (disabled when endpoint is None)
  2. Implement `get_tracer(name)` — returns OTel tracer
  3. Implement `add_otel_middleware(app)` — FastAPI middleware for span creation
  4. Wire trace_id/span_id injection into structlog context
  5. Export from `__init__.py`
- **Tests**: Unit — in-memory exporter confirms spans created; middleware creates server spans. Container — N/A. QA — N/A.
- **Documentation updates**: `docs/libs/observability.md` — already specified.
- **Definition of Done**: Traces export to in-memory exporter; structlog events include `trace_id` when tracing configured.
- **Risks/Mitigations**: OTel instrumentation versions must match — pin in pyproject.toml.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-017: Add comprehensive tests for `observability.logging`

- **Objective**: Test the existing logging module.
- **Why now**: Logging module exists but has zero tests.
- **Files touched**:
  - `libs/observability/tests/test_logging.py` (create)
- **Prerequisites**: None
- **Steps**:
  1. Test `configure_logging` sets correct level, format (JSON vs console)
  2. Test `get_logger` returns bound logger with service name
  3. Test JSON output format includes required fields (timestamp, level, service, event)
  4. Test log sanitization (if secret patterns appear, they're stripped — future, document as follow-up)
- **Tests**: Unit — 6+ test methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: Tests cover output format, level setting, service binding.
- **Risks/Mitigations**: Log capture requires redirecting structlog output — use `structlog.testing.capture_logs`.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-018: Add tests for `observability.metrics`

- **Objective**: Unit tests for the metrics module.
- **Why now**: New code, needs test coverage.
- **Files touched**:
  - `libs/observability/tests/test_metrics.py` (create)
- **Prerequisites**: T-015
- **Steps**:
  1. Test `create_metrics` returns valid `ServiceMetrics` with expected prometheus instruments
  2. Test counter increment and label cardinality
  3. Test middleware integration with mock FastAPI app (httpx + TestClient)
- **Tests**: Unit — 5+ methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: Tests pass; metrics registry validates.
- **Risks/Mitigations**: Prometheus registry is global — use `CollectorRegistry()` per test to avoid conflicts.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-019: Add tests for `observability.tracing`

- **Objective**: Unit tests for the tracing module.
- **Why now**: New code, needs coverage.
- **Files touched**:
  - `libs/observability/tests/test_tracing.py` (create)
- **Prerequisites**: T-016
- **Steps**:
  1. Test `configure_tracing` with and without endpoint
  2. Test span creation and export to `InMemorySpanExporter`
  3. Test trace_id propagation to structlog context
- **Tests**: Unit — 4+ methods. Container — N/A. QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: Tests confirm span export and structlog integration.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-020: Write ADR-0003 — Observability Stack Selection

- **Objective**: Document the architectural decision for the observability stack (structlog + prometheus-client + OTel).
- **Why now**: R4 requires ADR before major architectural addition; observability is a new cross-cutting library.
- **Files touched**:
  - `docs/architecture/decisions/0003-observability-stack.md` (create)
- **Prerequisites**: T-015, T-016 (informed by implementation experience)
- **Steps**:
  1. Use ADR template
  2. Context: need structured logging, metrics, tracing across 9 services
  3. Decision: structlog + prometheus-client + opentelemetry
  4. Alternatives: stdlib logging, datadog-agent, Jaeger-only, ELK
  5. Consequences: consistent telemetry, additional deps, learning curve
- **Tests**: N/A.
- **Documentation updates**: ADR itself. Reference from `docs/libs/observability.md`.
- **Definition of Done**: ADR reviewed and accepted.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Architecture Decision Lead

---

#### T-021: Mark `observability` IMPLEMENTATION.md complete

- **Objective**: Update tracking document.
- **Why now**: Gates Milestone 3.
- **Files touched**:
  - `libs/observability/IMPLEMENTATION.md`
- **Prerequisites**: T-015 through T-020
- **Steps**:
  1. Check off all items, update status
- **Tests**: N/A.
- **Documentation updates**: IMPLEMENTATION.md itself.
- **Definition of Done**: Status: Complete.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

### Milestone 4: `storage` Library (Complete)

---

#### T-022: Implement exception hierarchy for storage

- **Objective**: Create the full exception hierarchy matching legacy's 6-class structure.
- **Why now**: Required by `S3ObjectStorage`, health checks, and consuming services for error classification.
- **Files touched**:
  - `libs/storage/src/storage/exceptions.py` (create)
  - `libs/storage/src/storage/key_builder.py` (update `InvalidObjectKeyError` to import from exceptions.py)
- **Prerequisites**: None
- **Steps**:
  1. Create `exceptions.py` with: `StorageError(Exception)`, `ObjectNotFoundError(StorageError)`, `BucketNotFoundError(StorageError)`, `StoragePermissionError(StorageError)`, `StorageUnavailableError(StorageError)`, `InvalidObjectKeyError(StorageError)`
  2. Each exception includes descriptive docstring and `bucket`/`key` attributes where applicable
  3. Update `key_builder.py` to import `InvalidObjectKeyError` from `exceptions.py` instead of defining locally
  4. Lint + typecheck
- **Tests**: Unit — instantiation, inheritance chain (`isinstance(ObjectNotFoundError(...), StorageError)`). Container — N/A. QA — N/A.
- **Documentation updates**: `docs/libs/storage.md` already lists exceptions — verify alignment.
- **Definition of Done**: All 6 exceptions importable from `storage.exceptions`; inheritance correct.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-023: Implement `ObjectStorage` ABC (interface)

- **Objective**: Create the abstract base class that defines the storage port interface.
- **Why now**: Every service using storage depends on this interface via dependency injection.
- **Files touched**:
  - `libs/storage/src/storage/interface.py` (create)
- **Prerequisites**: T-022 (needs exceptions)
- **Steps**:
  1. Copy structure from legacy `interface.py` (224 lines)
  2. Define ABC with abstract methods: `bucket` (property), `put_bytes`, `get_bytes`, `delete`, `list_keys`, `exists`, `delete_prefix`
  3. Add concrete methods: `put_json`, `get_json` (call abstract `put_bytes`/`get_bytes` with JSON serialization)
  4. Use proper type hints (bytes, str, Iterable, Any)
  5. Lint + typecheck
- **Tests**: Unit — verify ABC cannot be instantiated directly; mock subclass works. Container — N/A. QA — N/A.
- **Documentation updates**: Verify `docs/libs/storage.md` ABC section.
- **Definition of Done**: ABC importable; mock implementation passable.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-024: Implement `S3ObjectStorage` adapter

- **Objective**: Port the boto3-based S3 adapter from legacy.
- **Why now**: The only concrete implementation of `ObjectStorage`; required for claim-check pattern.
- **Files touched**:
  - `libs/storage/src/storage/s3_adapter.py` (create)
- **Prerequisites**: T-022, T-023
- **Steps**:
  1. Copy from legacy `s3_adapter.py` (392 lines)
  2. Implement all 6 abstract methods + `bucket` property
  3. Map boto3 `ClientError` codes to domain exceptions (`_convert_error`)
  4. Map botocore connection errors to `StorageUnavailableError`
  5. Implement `_chunk` helper for batch `delete_prefix`
  6. Add `structlog` logging (replace `stdlib.logging`)
  7. Lint + typecheck
- **Tests**: Unit with mocked boto3 — put, get, delete, list, exists, delete_prefix, error mapping. Container — integration with MinIO testcontainer (follow-up). QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: All abstract methods implemented; error mapping verified; lint passes.
- **Risks/Mitigations**: Risk: boto3 version compatibility. Mitigation: pin `>=1.34` in pyproject.toml.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-025: Expand `StorageSettings` to full pydantic model

- **Objective**: Port the complete settings model from legacy (bucket, timeouts, etc.).
- **Why now**: `build_object_storage()` factory needs full settings to construct `S3ObjectStorage`.
- **Files touched**:
  - `libs/storage/src/storage/settings.py` (update)
- **Prerequisites**: None
- **Steps**:
  1. Add missing fields: `bucket` (required, no default), `connect_timeout_seconds` (10.0), `read_timeout_seconds` (30.0), `max_attempts` (5)
  2. Add properties: `effective_use_ssl`, `is_aws_s3`, `is_custom_endpoint`
  3. Update `model_config` to use `SettingsConfigDict(env_prefix="STORAGE_", env_file=".env")`
  4. Lint + typecheck
- **Tests**: Unit — env loading, defaults, SSL logic, endpoint detection. Container — N/A.
- **Documentation updates**: Verify `docs/libs/storage.md` configuration section.
- **Definition of Done**: All legacy fields present; env prefix works; properties compute correctly.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-026: Expand `KeyBuilder` to full feature parity

- **Objective**: Port `KeyComponents`, `parse_key`, `build_prefix`, `validate_key` from legacy.
- **Why now**: Services need `build_prefix` for listing operations and `parse_key` for debugging.
- **Files touched**:
  - `libs/storage/src/storage/key_builder.py` (update)
- **Prerequisites**: T-022 (needs `InvalidObjectKeyError` from exceptions)
- **Steps**:
  1. Add `KeyComponents` frozen dataclass with `service`, `domain`, `resource_id`, `artifact`, `version`, `extra`, and `to_key()` method
  2. Add `parse_key(key)` function that returns `KeyComponents`
  3. Add `KeyBuilder.build_prefix(service, domain, resource_id=None, artifact=None)` for listing
  4. Enhance `validate` with segment-level validation (`_validate_segment`), min/max segments, max key length
  5. Import `InvalidObjectKeyError` from `exceptions.py` (remove local definition)
  6. Port constants: `_VALID_SEGMENT_PATTERN`, `_RESERVED_SEGMENTS`, `_MIN_SEGMENTS`, `_MAX_SEGMENTS`, `_MAX_KEY_LENGTH`
- **Tests**: Unit — 25+ methods from legacy test suite (test_keys.py 253 lines). Container — N/A.
- **Documentation updates**: None.
- **Definition of Done**: Full feature parity with legacy; tests match or exceed legacy coverage.
- **Risks/Mitigations**: None.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-027: Implement `build_object_storage()` factory and health check

- **Objective**: Create the canonical factory function and health check utilities.
- **Why now**: Every service uses `build_object_storage()` to get a storage instance.
- **Files touched**:
  - `libs/storage/src/storage/factory.py` (create)
  - `libs/storage/src/storage/health.py` (create)
- **Prerequisites**: T-024, T-025
- **Steps**:
  1. Implement `build_object_storage(settings: StorageSettings | None = None) -> ObjectStorage` — reads settings from env if not provided, constructs `S3ObjectStorage`
  2. Implement `check_storage_health(storage)` — HEAD bucket, return health dict
  3. Implement `check_storage_health_with_list(storage)` — extended check
  4. Use `structlog` for logging
- **Tests**: Unit — factory returns `S3ObjectStorage`; health check returns dict. Container — integration with MinIO (follow-up).
- **Documentation updates**: Verify docs/libs/storage.md factory section.
- **Definition of Done**: `build_object_storage()` works end-to-end; health check returns structured result.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-028: Wire `storage.__init__` exports and add comprehensive tests

- **Objective**: Complete the storage package's public API and test coverage.
- **Why now**: Without proper `__init__.py`, services can't `from storage import ObjectStorage, build_object_storage`.
- **Files touched**:
  - `libs/storage/src/storage/__init__.py` (update)
  - `libs/storage/tests/test_exceptions.py` (create)
  - `libs/storage/tests/test_interface.py` (create)
  - `libs/storage/tests/test_s3_adapter.py` (create)
  - `libs/storage/tests/test_settings.py` (create)
  - `libs/storage/tests/test_keys.py` (create)
  - `libs/storage/tests/test_health.py` (create)
- **Prerequisites**: T-022 through T-027
- **Steps**:
  1. Update `__init__.py` with full re-exports matching legacy pattern
  2. Port tests from legacy (921 lines across 4 files), adapting to new module names
  3. Run full test suite
- **Tests**: Unit — 40+ test methods ported from legacy. Container — N/A (future MinIO testcontainer). QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: `from storage import ObjectStorage, S3ObjectStorage, StorageSettings, KeyBuilder, build_object_storage` all work; 40+ tests pass.
- **Risks/Mitigations**: None.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-029: Mark `storage` IMPLEMENTATION.md complete

- **Objective**: Update tracking document.
- **Why now**: Gates Milestone 4.
- **Files touched**:
  - `libs/storage/IMPLEMENTATION.md`
- **Prerequisites**: T-022 through T-028
- **Steps**: Check off items, update status.
- **Tests**: N/A.
- **Documentation updates**: IMPLEMENTATION.md.
- **Definition of Done**: Status: Complete.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

### Milestone 5: `messaging` Library (Complete)

---

#### T-030: Implement Kafka consumer error hierarchy

- **Objective**: Port the 2-branch error hierarchy from legacy (10 exception classes).
- **Why now**: `BaseKafkaConsumer` depends on this hierarchy for error classification and retry decisions.
- **Files touched**:
  - `libs/messaging/src/messaging/kafka/__init__.py` (create directory + init)
  - `libs/messaging/src/messaging/kafka/consumer/__init__.py` (create directory + init)
  - `libs/messaging/src/messaging/kafka/consumer/errors.py` (create)
- **Prerequisites**: None
- **Steps**:
  1. Create `kafka/` and `kafka/consumer/` directories with `__init__.py`
  2. Implement error hierarchy: `ConsumerError(Exception)` → `RetryableError` (StorageUnavailableError, DatabaseConnectionError, NetworkTimeoutError, ServiceUnavailableError, RateLimitedError) and `FatalError` (SchemaVersionError, MalformedDataError, MissingRequiredFieldError, BusinessRuleViolationError)
  3. Add re-exports to `kafka/consumer/__init__.py`
- **Tests**: Unit — inheritance checks, instantiation. Container — N/A.
- **Documentation updates**: None (internal module).
- **Definition of Done**: All 10 exceptions importable; hierarchy correct per `isinstance` checks.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

#### T-031: Implement `BaseKafkaConsumer` abstract base class

- **Objective**: Port the 576-line generic consumer base from legacy, refactoring metrics to use observability lib.
- **Why now**: Every Kafka consumer in every service inherits from this class. Most critical messaging module.
- **Files touched**:
  - `libs/messaging/src/messaging/kafka/consumer/base.py` (create)
  - `libs/messaging/src/messaging/kafka/consumer/__init__.py` (update exports)
- **Prerequisites**: T-030, T-015 (observability.metrics)
- **Steps**:
  1. Copy `BaseKafkaConsumer[TFailure]` from legacy (576 lines)
  2. Replace `import logging` → `from observability import get_logger`
  3. Extract inline Prometheus counters → use `ServiceMetrics` from observability
  4. Add `UnitOfWorkProtocol`, `FailureInfo`, `ConsumerConfig` dataclass
  5. Keep all 12 abstract methods intact
  6. Keep concrete methods: `_init_kafka`, `_shutdown_kafka`, `_deserialize`, `_compute_backoff`, `_handle_message`, `_handle_failure`, `_retry_loop`, `_process_retry_batch`, `_retry_failure`, `_handle_retry_failure`, `run`, `stop`
  7. Lint + typecheck (will need `confluent-kafka` stubs or ignores)
- **Tests**: Unit — test `_compute_backoff`, test error classification routing, test graceful shutdown signal handling (mock). Container — integration with embedded Kafka (future, via testcontainers). QA — verify existing legacy consumer tests inform coverage.
- **Documentation updates**: `docs/libs/messaging.md` — verify consumer section matches new API.
- **Definition of Done**: `BaseKafkaConsumer` importable; abstract methods defined; backoff/retry logic verified.
- **Risks/Mitigations**: Risk: `confluent_kafka` is C-extension-based, may have install issues. Mitigation: add installation note in README; CI uses prebuilt wheels.
- **Effort**: L | **Owner**: Data Platform Engineer

---

#### T-032: Implement Kafka producer, schema registry, and serializer modules

- **Objective**: Port `producer.py`, `schema_registry.py`, `serializer.py`, `serialization_utils.py` from legacy.
- **Why now**: Every service's outbox dispatcher and event producer depend on this stack.
- **Files touched**:
  - `libs/messaging/src/messaging/kafka/producer.py` (create)
  - `libs/messaging/src/messaging/kafka/schema_registry.py` (create)
  - `libs/messaging/src/messaging/kafka/serializer.py` (create)
  - `libs/messaging/src/messaging/kafka/serialization_utils.py` (create)
  - `libs/messaging/src/messaging/schemas.py` (update — reconcile `AvroDictable` with serializer module's version)
- **Prerequisites**: None (independent of consumer)
- **Steps**:
  1. Copy `producer.py` — `KafkaProducerConfig`, `OutboxKafkaValue`, `KafkaEventValueSerializer`, `OutboxEventValueSerializer`, `build_serializing_producer`
  2. Copy `schema_registry.py` — `SchemaRegistryConfig`, `build_schema_registry_client`
  3. Copy `serializer.py` — `AvroDictable` protocol (with `event_type` property), `AvroSerializerConfig`, `build_avro_serializer`, `topic_event_type_subject_name_strategy`
  4. Copy `serialization_utils.py` — `load_schema`, `serializer_for_schema`, `iso_datetime`, `decimal_to_str`
  5. **Reconcile**: `schemas.py` currently defines `AvroDictable` with `to_dict`/`from_dict`; `serializer.py` defines it with `event_type` property. Decision: keep `serializer.py` version (matches legacy consumer expectations), update `schemas.py` `AvroDictable` to add `event_type` property requirement, or rename to avoid conflict. Recommendation: merge into `serializer.py`, keep `schemas.py` for `load_schema`/`serialize_avro`/`deserialize_avro` without a conflicting protocol.
  6. Lint + typecheck
- **Tests**: Unit — `OutboxKafkaValue` creation, `KafkaProducerConfig` defaults, serializer routing by event_type, `iso_datetime` format, `decimal_to_str` edge cases. Container — N/A. QA — N/A.
- **Documentation updates**: `docs/libs/messaging.md` — verify producer/serializer sections.
- **Definition of Done**: All producer stack modules importable; config defaults match production values (acks=all, idempotence=true).
- **Risks/Mitigations**: Risk: `AvroDictable` protocol conflict. Mitigation: unified protocol in `serializer.py`, remove duplicate from `schemas.py`.
- **Effort**: M | **Owner**: Data Platform Engineer

---

#### T-033: Implement `BaseOutboxDispatcher` and outbox protocols

- **Objective**: Port the 536-line lease-based outbox dispatcher from legacy.
- **Why now**: Outbox pattern is the only safe way to publish Kafka events (R8). Every service needs this.
- **Files touched**:
  - `libs/messaging/src/messaging/kafka/dispatcher/__init__.py` (create directory + init)
  - `libs/messaging/src/messaging/kafka/dispatcher/base.py` (create)
- **Prerequisites**: T-032 (producer), T-015 (metrics)
- **Steps**:
  1. Copy `BaseOutboxDispatcher` from legacy (536 lines)
  2. Port protocols: `OutboxRecordProtocol`, `OutboxRepositoryProtocol`, `UnitOfWorkWithOutboxProtocol`
  3. Port `DispatcherConfig` dataclass (13 fields)
  4. Port `DeliveryResult` dataclass
  5. Replace `import logging` → `from observability import get_logger`
  6. Extract inline metrics → use `ServiceMetrics.outbox_dispatched_total` and `outbox_dispatch_errors_total`
  7. Keep lease logic, immediate + poll loops, batch dispatch, dead-letter handling
  8. Port `run_dispatcher()` async entry point
  9. Lint + typecheck
- **Tests**: Unit — `DispatcherConfig` defaults, `_generate_worker_id`, `_exponential_backoff`, protocol shape validation. Container — integration with Kafka + DB (future, via testcontainers). QA — verify outbox completeness by inspecting delivery callback patterns.
- **Documentation updates**: `docs/libs/messaging.md` — verify outbox section.
- **Definition of Done**: `BaseOutboxDispatcher` importable; protocols defined; lease/poll logic intact.
- **Risks/Mitigations**: Risk: lease acquisition race conditions. Mitigation: documented as at-least-once guarantee; consumer idempotency handles duplicates.
- **Effort**: L | **Owner**: Data Platform Engineer

---

#### T-034: Implement `ValkeyClient` async Redis wrapper

- **Objective**: Port the 349-line Valkey/Redis client from legacy.
- **Why now**: Market Data service (S3) and API Gateway (S9) use Valkey for caching; requires client abstraction.
- **Files touched**:
  - `libs/messaging/src/messaging/valkey/__init__.py` (create directory + init)
  - `libs/messaging/src/messaging/valkey/client.py` (create)
- **Prerequisites**: None (independent module)
- **Steps**:
  1. Copy `ValkeyConfig` dataclass from legacy — `host`, `port`, `db`, `password`, `username`, pool/timeout settings, `from_url` classmethod, `url` property
  2. Copy `ValkeyClient` from legacy — all operations: basic (get/set/delete/exists/expire/ttl), JSON (get_json/set_json), batch (mget/mset/delete_many), hash (hget/hset/hgetall/hdel), list (lpush/rpush/lpop/rpop/lrange/llen)
  3. Add `create_valkey_client(config)` and `create_valkey_client_from_url(url)` factories
  4. Replace `import logging` → `from observability import get_logger`
  5. Document key taxonomy in docstrings: `<scope>:<version>:<resource>:<id>[:<qualifier>]`
  6. Lint + typecheck
- **Tests**: Unit — config construction, URL generation, method signatures. Container — integration with Valkey testcontainer (follow-up). QA — N/A.
- **Documentation updates**: `docs/libs/messaging.md` — verify Valkey section.
- **Definition of Done**: `ValkeyClient` importable; all operations defined; config handles URL and component-based init.
- **Risks/Mitigations**: None.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-035: Write ADR-0004 — Valkey Key Taxonomy and TTL Conventions

- **Objective**: Formalize the caching key structure, TTL defaults, and invalidation strategy.
- **Why now**: Multiple services will use Valkey; without a standard, key collisions and TTL chaos ensue.
- **Files touched**:
  - `docs/architecture/decisions/0004-valkey-key-taxonomy.md` (create)
- **Prerequisites**: T-034
- **Steps**:
  1. Document key format: `<scope>:<version>:<resource>:<id>[:<qualifier>]`
  2. Define scopes: `md` (market data), `gw` (gateway), `content`, `nlp`
  3. Define TTL tiers: real-time (10s), quote (30s), OHLCV (5min), fundamentals (1hr), static (24hr)
  4. Define invalidation strategy: event-driven cache bust via Kafka consumer side-effects
  5. Document anti-patterns: no KEYS * in production, no unbounded key growth, mandatory TTL
- **Tests**: N/A.
- **Documentation updates**: ADR itself. Reference from `docs/libs/messaging.md`.
- **Definition of Done**: ADR accepted.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Architecture Decision Lead

---

#### T-036: Write ADR-0005 — Messaging Error Classification

- **Objective**: Document the Retryable vs Fatal error distinction and its implications.
- **Why now**: Error classification drives retry behavior, DLQ routing, and alerting. Must be explicit.
- **Files touched**:
  - `docs/architecture/decisions/0005-messaging-error-classification.md` (create)
- **Prerequisites**: T-030
- **Steps**:
  1. Document 2-branch hierarchy
  2. Define retry strategy per error type (exponential backoff w/ jitter, max attempts, DLQ threshold)
  3. Define alerting implications (Fatal → immediate alert, Retryable → alert after 3 consecutive failures)
  4. Document consumer idempotency requirements and `event_id` dedup table schema
- **Tests**: N/A.
- **Documentation updates**: ADR itself.
- **Definition of Done**: ADR accepted.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Architecture Decision Lead

---

#### T-037: Wire `messaging.__init__` exports and add comprehensive tests

- **Objective**: Complete the messaging package's public API and build test suite.
- **Why now**: Without proper exports, services can't import messaging primitives cleanly.
- **Files touched**:
  - `libs/messaging/src/messaging/__init__.py` (update with full re-exports)
  - `libs/messaging/tests/test_errors.py` (create)
  - `libs/messaging/tests/test_producer.py` (create)
  - `libs/messaging/tests/test_schemas.py` (create)
  - `libs/messaging/tests/test_serializer.py` (create)
  - `libs/messaging/tests/test_valkey.py` (create)
  - `libs/messaging/tests/test_topics.py` (create)
- **Prerequisites**: T-030 through T-034
- **Steps**:
  1. Update `__init__.py` — re-export: `BaseKafkaConsumer`, `ConsumerConfig`, `RetryableError`, `FatalError`, `ValkeyClient`, `ValkeyConfig`, `create_valkey_client`, `KafkaProducerConfig`, `OutboxKafkaValue`, `BaseOutboxDispatcher`, `AvroDictable`, `AvroSerializerConfig`, `load_schema`, `serialize_avro`, `deserialize_avro`
  2. Write tests for each module (error hierarchy, producer config, schema loading, serializer config, valkey config, topic constants)
  3. Run full test suite
- **Tests**: Unit — 30+ test methods across 6 test files. Container — N/A (future). QA — N/A.
- **Documentation updates**: None.
- **Definition of Done**: All public exports work; 30+ tests pass; lint clean.
- **Risks/Mitigations**: None.
- **Effort**: M | **Owner**: Backend Engineer

---

#### T-038: Mark `messaging` IMPLEMENTATION.md complete

- **Objective**: Update tracking document.
- **Why now**: Gates Milestone 5.
- **Files touched**:
  - `libs/messaging/IMPLEMENTATION.md`
- **Prerequisites**: T-030 through T-037
- **Steps**: Check off items, update status.
- **Tests**: N/A.
- **Documentation updates**: IMPLEMENTATION.md.
- **Definition of Done**: Status: Complete.
- **Risks/Mitigations**: None.
- **Effort**: S | **Owner**: Backend Engineer

---

### Cross-cutting Tasks

---

#### T-039: Validate all canonical models against Avro schemas

- **Objective**: Contract test ensuring `to_dict()` output from each canonical model matches the corresponding Avro schema field names and types.
- **Why now**: Schema drift between Python models and Avro `.avsc` files causes runtime serialization failures.
- **Files touched**:
  - `libs/contracts/tests/test_avro_alignment.py` (create)
- **Prerequisites**: T-007 through T-012, all Avro schemas in `infra/kafka/schemas/`
- **Steps**:
  1. Load each `.avsc` schema with `fastavro.parse_schema`
  2. For each canonical model, create a sample instance, call `to_dict()`, and validate against the schema
  3. Assert all required schema fields are present in `to_dict()` output
  4. Assert no extra fields beyond what the schema expects
- **Tests**: Contract — 6+ validation methods (one per model + schema pair). Container — N/A. QA — this IS the QA gate.
- **Documentation updates**: None.
- **Definition of Done**: All models validate against their schemas; test runs in CI.
- **Risks/Mitigations**: Risk: some canonical models don't have a direct 1:1 Avro schema (e.g., OHLCV is claim-check, not the event itself). Mitigation: test against the payload the model appears in, not necessarily as the top-level Avro message.
- **Effort**: M | **Owner**: Data Platform Engineer

---

#### T-040: Integration test scaffold — Docker Compose lib test profile

- **Objective**: Create a test profile in Docker Compose that starts only infra services (Kafka, MinIO, Valkey, Postgres) for lib-level integration tests.
- **Why now**: Unit tests with mocks are insufficient for storage and messaging libs; integration tests need real infrastructure.
- **Files touched**:
  - `infra/compose/docker-compose.yml` (update — add `lib-test` profile or document existing `infra` profile usage)
  - `scripts/test-libs.sh` (create)
- **Prerequisites**: None (independent)
- **Steps**:
  1. Document which Docker Compose profile to use for lib testing (likely `infra` profile already works)
  2. Create `scripts/test-libs.sh` that starts infra, waits for readiness, runs lib tests, and stops infra
  3. Add testcontainers dependency to dev deps if preferred over Docker Compose
- **Tests**: Meta — the script itself runs and produces test output. QA — CI integration.
- **Documentation updates**: `docs/developer-guide/` or README — document lib testing workflow.
- **Definition of Done**: `./scripts/test-libs.sh` runs all lib tests against real infra.
- **Risks/Mitigations**: Risk: CI environment may not have Docker. Mitigation: unit tests run without Docker; integration tests are opt-in.
- **Effort**: M | **Owner**: DevOps / Platform Engineer

---

## 5. Milestones and Release Gates

| Milestone | Tickets | Gate Criteria | Est. Duration |
|-----------|---------|---------------|---------------|
| **M1: common** | T-001 → T-005 | All exports wired; 15+ tests pass; IMPLEMENTATION.md complete | 1 day |
| **M2: contracts** | T-006 → T-014 | 7 models implemented; parsing works; 30+ tests pass; Avro alignment verified | 3 days |
| **M3: observability** | T-015 → T-021 | Logging + metrics + tracing functional; ADR-0003 accepted; 15+ tests | 3 days |
| **M4: storage** | T-022 → T-029 | Full feature parity with legacy; 40+ tests; factory works | 3 days |
| **M5: messaging** | T-030 → T-038 | Consumer + producer + outbox + Valkey functional; 30+ tests; 2 ADRs | 5 days |
| **Cross-cutting** | T-039, T-040 | Contract tests pass; integration scaffold ready | 2 days |

**Total estimated duration**: ~17 working days (3.5 weeks)

**Release gates**:
1. After M1: `common` can be used as a dependency by other libs.
2. After M2: `contracts` can be used by `messaging` and services.
3. After M3: `observability` replaces all `import logging` usage — services can fully adopt.
4. After M4: `storage` enables claim-check pattern for service migration.
5. After M5: **All shared libraries are migration-complete**. Service migrations (prompts 0002–0004) can begin.
6. After cross-cutting: Contract safety net and integration test infrastructure validated.

---

## 6. Rollout / Rollback / Backfill Strategy

### Rollout
- Each library is developed on a feature branch: `feat/lib-<name>-migration`
- Each milestone produces a PR that is merged independently
- Services adopt new lib versions via editable installs (`pip install -e ../../../libs/<name>`)
- No runtime deployment occurs during lib migration — libs are dev-time dependencies

### Rollback
- Git revert any lib migration PR without affecting other libs (they're independent packages)
- Services continue using legacy imports until the new lib PR is merged and they're updated
- Hatch editable installs mean reverting a lib is immediate (just `git checkout`)

### Backfill
- No data backfill needed for lib migration — these are code-only changes
- Avro schema compatibility is maintained (forward-compatible, additive only)
- Topic names don't change — existing Kafka data remains valid

---

## 7. Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| `confluent-kafka` C extension install failures | Medium | High (blocks messaging) | Pin version, provide wheel links, document build deps |
| `AvroDictable` protocol inconsistency between `schemas.py` and `serializer.py` | High | Medium | Resolve in T-032 — single canonical protocol |
| OHLCV `float` vs `Decimal` precision loss | Low | Medium | Document; float64 has 15 sig digits, sufficient for OHLCV |
| OTel dependency version conflicts | Medium | Low | Pin versions in pyproject.toml; test in CI |
| Prometheus multiprocess mode not supported initially | Medium | Low | Document limitation; single-process mode works for thesis demo |
| Legacy test gaps (messaging has 0 tests) | High | Medium | Write fresh tests; legacy's zero-test state is actually an improvement opportunity |
| Service migrations blocked by lib delays | Medium | High | Milestones are sequential; prioritize critical path libs |

---

## 8. Assumptions

1. Python 3.12 is the target runtime (per pyproject.toml `>=3.11,<3.13`).
2. Hatch is the build system; Poetry is fully abandoned.
3. All legacy code can be freely copied (same author, same thesis).
4. The 8 Avro schemas in `infra/kafka/schemas/` are considered stable.
5. No legacy Kafka data needs to be consumed by new services during migration (clean start).
6. The `observability` library can have heavier dependencies (structlog, prometheus-client, opentelemetry) since it's a new library not constrained by legacy.
7. Services will not be migrated until ALL 5 libs are complete (sequential dependency).

---

## 9. Open Questions Requiring Human Decision

| # | Question | Options | Impact | Blocking |
|---|----------|---------|--------|----------|
| Q1 | Should `CanonicalOHLCVBar` use `Decimal` (legacy) or `float` (current target)? | A) Keep float (simpler), B) Revert to Decimal (precision), C) Provide both via property | Field type affects all OHLCV consumers | T-007 |
| Q2 | Should `parse_bar_date` return `date` (legacy) or `datetime` at midnight UTC (current target)? | A) Keep datetime (consistent), B) Revert to date (semantic accuracy) | Affects Market Data materializer date handling | T-004 |
| Q3 | Should the `AvroDictable` protocol require `event_type` property (legacy serializer), `to_dict`/`from_dict` (current schemas.py), or both? | A) event_type only, B) to_dict + from_dict only, C) Unified with all three | Protocol shape affects every event class | T-032 |
| Q4 | Should `messaging` depend on `observability` (for structlog + metrics) or keep stdlib logging with optional observability integration? | A) Hard dependency (cleaner), B) Optional dependency (less coupling) | Import chains and deployment flexibility | T-031, T-033 |
| Q5 | Integration test strategy: testcontainers (per-test isolation) or shared Docker Compose (faster, less isolation)? | A) testcontainers, B) Docker Compose, C) Both (unit = mock, integration = compose) | CI runtime and test reliability | T-040 |
| Q6 | Should `ValkeyClient` remain inside `messaging` lib or move to its own `libs/cache/` package? | A) Stay in messaging (simpler), B) Separate lib (cleaner boundaries) | Package structure and dependency graph | T-034 |

---

## Summary

- **40 atomic tasks** (T-001 through T-040) organized into 5 milestones + cross-cutting
- **17 estimated working days** (3.5 weeks)
- **~4,884 lines** of legacy code to migrate, with ~60% reuse
- **3 ADRs** required (observability stack, Valkey taxonomy, error classification)
- **6 open questions** requiring human decision before implementation begins
- **Zero runtime risk** — library migration is code-only; no deployment, no data changes
