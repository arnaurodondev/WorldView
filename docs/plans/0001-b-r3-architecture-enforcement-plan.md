---
id: PLAN-0001-B-R3
prd: PRD-0001
title: "S4+S5 Architecture Enforcement: ABCs, BaseKafkaConsumer, MinIO GC, DomainError, Standards"
status: completed
created: 2026-03-27
updated: 2026-03-27
waves_done: 5
plans: 1
waves: 5
tasks: 22
supersedes: null
depends_on: PLAN-0001-B-R2
---

# PLAN-0001-B-R3: Architecture Enforcement & Standardization

## Overview

**Triggered by**: QA review deferred decisions D-1, D-3, D-4, D-5 + user mandate to enforce standards
**Goal**: Enforce hexagonal architecture ABCs in S5, migrate S5 consumer to `BaseKafkaConsumer` (shared lib), add inline MinIO GC on DB rollback, standardize `DomainError` in S4, and add architecture enforcement tests + documentation updates.
**Total Scope**: 1 plan, 5 waves, 22 tasks
**Estimated total effort**: 4–5 hours

### Decisions (user-confirmed)

| Decision | Resolution |
|----------|-----------|
| S5 consumer approach | Extend `BaseKafkaConsumer[dict]` from `libs/messaging` — mandatory for all services |
| S5 failure record type | `dict` — simple, stores raw Avro payload for retry (like Market-Data) |
| Idempotency table | `processed_events(event_id UUID PK, processed_at TIMESTAMPTZ)` — lightweight |
| MinIO GC approach | Inline compensating delete in `except` block on DB commit failure |
| ABC enforcement | Architecture tests that scan imports + verify ports directory exists |
| DomainError enforcement | Add `DomainError` base to S4, add rule to RULES.md, add test |

---

## Dependency Graph

```
Wave 1 (S5 ports + S4 DomainError) ────┐
                                        ├──→ Wave 2 (S5 consumer → BaseKafkaConsumer + lifespan)
Wave 3 (MinIO GC on rollback, S4+S5) ──┘              │
                                                       ↓
                                        Wave 4 (Architecture enforcement tests)
                                                       │
                                                       ↓
                                        Wave 5 (Standards + docs + rules)
```

Waves 1 and 3 are **parallelizable** (different files). Wave 2 depends on Wave 1 (ports).

---

## Pre-Read (agent must read before any wave)

- `RULES.md` — hard rules
- `AGENTS.md` — coding standards
- `libs/messaging/src/messaging/kafka/consumer/base.py` — BaseKafkaConsumer (12 abstract methods)
- `libs/messaging/src/messaging/kafka/consumer/errors.py` — RetryableError vs FatalError
- `services/portfolio/src/portfolio/application/ports/` — reference ABC pattern
- `services/portfolio/src/portfolio/infrastructure/messaging/consumers/` — reference consumer
- `services/portfolio/src/portfolio/app.py` — reference lifespan consumer wiring
- `services/market-data/src/market_data/infrastructure/messaging/consumers/` — reference 3-consumer pattern
- `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py` — current S5 consumer
- `services/content-store/src/content_store/application/use_cases/process_article.py` — S5 use case
- `services/content-ingestion/src/content_ingestion/domain/exceptions.py` — S4 exceptions (no DomainError)
- `services/content-ingestion/src/content_ingestion/application/ports/` — S4 ports (Protocol pattern)

---

## Wave 1: S5 Application Ports + S4 DomainError ✅

**Goal**: Create ABC ports for S5 application layer and add `DomainError` base class to S4.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-27 · 223 S5 + 9 S4 tests pass · ruff + mypy clean

#### T-R3-1-01: Create S5 application port ABCs

**Type**: impl | **depends_on**: none | **blocks**: [T-R3-1-02, T-R3-2-01]
**Target files**: `services/content-store/src/content_store/application/ports/__init__.py`, `application/ports/repositories.py`, `application/ports/storage.py`, `application/ports/lsh.py`

**What to build**: 6 ABCs — `DocumentRepositoryPort`, `DedupHashRepositoryPort`, `MinHashRepositoryPort`, `OutboxPort`, `SilverStoragePort`, `LSHClientPort`. Method signatures must match existing repo/adapter public APIs. No infrastructure imports.

**Acceptance criteria**: All 6 ports defined; zero infra imports in ports module.

#### T-R3-1-02: Update S5 use case + dedup stages to use port types

**Type**: impl | **depends_on**: [T-R3-1-01] | **blocks**: [T-R3-2-01]
**Target files**: `application/use_cases/process_article.py`, `application/deduplication/stage_a_raw.py`, `application/deduplication/stage_b_normalized.py`

**What to build**: Replace all infra type hints with port ABCs. Remove runtime `from infrastructure.storage.minio_silver import put_canonical`. Remove `session: AsyncSession` param — consumer manages transaction. Inject `SilverStoragePort` via constructor.

**Acceptance criteria**: `grep -r "from content_store.infrastructure" application/` returns nothing. All existing tests pass.

#### T-R3-1-03: Create SilverStorageAdapter implementing SilverStoragePort

**Type**: impl | **depends_on**: [T-R3-1-01] | **blocks**: none
**Target files**: `infrastructure/storage/minio_silver.py`

**What to build**: Wrap existing `put_canonical` into `SilverStorageAdapter` class implementing `SilverStoragePort`.

#### T-R3-1-04: Add DomainError base class to S4

**Type**: impl | **depends_on**: none | **blocks**: [T-R3-4-02]
**Target files**: `services/content-ingestion/src/content_ingestion/domain/exceptions.py`

**What to build**: `class DomainError(Exception)`. All 4 exceptions inherit from it. Backward-compatible.

#### T-R3-1-05: Tests for ports + DomainError

**Type**: test | **depends_on**: [T-R3-1-02, T-R3-1-04] | **blocks**: none
**Target files**: `tests/unit/application/test_ports.py` (S5), `tests/unit/domain/test_domain_error.py` (S4)

**Tests**: (≥6) Import scan for infra in application/; repos satisfy ports; DomainError inheritance; DomainError catchability.

### Validation Gate
- [x] `ruff check` + `mypy` clean | ≥6 new tests | Zero infra imports in S5 `application/`

---

## Wave 2: S5 Consumer → BaseKafkaConsumer + Lifespan Wiring ✅

**Goal**: Rewrite S5 consumer to extend `BaseKafkaConsumer[dict]`, add `processed_events` idempotency table, wire consumer + dispatcher in lifespan.
**Depends on**: Wave 1
**Estimated effort**: 60–90 minutes
**Status**: **DONE** — 2026-03-27 · 236 S5 tests pass · ruff + mypy clean

#### T-R3-2-01: Rewrite ArticleConsumer → BaseKafkaConsumer[dict]

**Type**: impl | **depends_on**: [T-R3-1-02] | **blocks**: [T-R3-2-03, T-R3-2-05]
**Target files**: `infrastructure/consumer/article_consumer.py`, `infrastructure/db/repositories/processed_events.py`

**What to build**: Extend `BaseKafkaConsumer[dict]`. Implement 12 abstract methods:
- `process_message(key, value, headers)` → parse + use case + LSH index (after UoW commit)
- `is_duplicate(event_id)` / `mark_processed(event_id)` → `ProcessedEventsRepository`
- `store_failure` / `update_failure` → log (dict failures tracked in DLQ)
- `dead_letter(failure)` → `move_to_dead_letter` on outbox repo
- `get_pending_retries()` → `[]` (DLQ admin handles retries)
- `get_unit_of_work()` → `SqlAlchemyUnitOfWork`
- `deserialize_value(raw, schema_path)` → Avro via schema registry
- `get_schema_path(topic)` → `content.article.raw.v1.avsc`
- `extract_event_id(value)` → `value["event_id"]`

**ProcessedEventsRepository**: `is_duplicate(event_id) -> bool`, `mark_processed(event_id) -> None`.

**Acceptance criteria**: `issubclass(ArticleConsumer, BaseKafkaConsumer)` is True. `consumer.run()` provides poll loop. Idempotency via `processed_events`.

#### T-R3-2-02: Add processed_events migration

**Type**: schema | **depends_on**: none | **blocks**: [T-R3-2-01]
**Target files**: `alembic/versions/0003_add_processed_events.py`, `infrastructure/db/models.py`

**DDL**: `CREATE TABLE processed_events (event_id UUID PRIMARY KEY, processed_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Index on `processed_at`. ORM: `ProcessedEventModel`.

**Downstream test impact**: `test_models.py` table count assertion; DDL alignment tests.

#### T-R3-2-03: Wire consumer + dispatcher in S5 lifespan

**Type**: impl | **depends_on**: [T-R3-2-01] | **blocks**: none
**Target files**: `app.py`

**What to build**: `consumer_task = asyncio.create_task(consumer.run())`, `dispatcher_task = asyncio.create_task(dispatcher.run())`. Graceful shutdown: `stop()` + `wait_for(task, timeout=10)` + `engine.dispose()`. Follow Portfolio/Market-Data pattern.

#### T-R3-2-04: Update integration conftest for processed_events

**Type**: impl | **depends_on**: [T-R3-2-02] | **blocks**: none
**Target files**: `tests/integration/conftest.py`

**What to build**: Add `TRUNCATE processed_events CASCADE` to `_clean_tables`.

#### T-R3-2-05: Tests for BaseKafkaConsumer integration

**Type**: test | **depends_on**: [T-R3-2-01] | **blocks**: none
**Target files**: `tests/unit/infrastructure/test_article_consumer.py`

**Tests**: (≥6) `issubclass` check; `is_duplicate` false/true; `process_message` delegates to use case; `extract_event_id`; `dead_letter` routes to DLQ.

### Validation Gate
- [x] `ruff check` + `mypy` clean | ≥6 new tests | Consumer extends BaseKafkaConsumer

---

## Wave 3: MinIO Orphan GC on DB Rollback ✅

**Goal**: Add inline compensating MinIO delete when DB commit fails.
**Depends on**: none (parallel with Wave 1)
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-27 · 11 new GC tests pass · ruff + mypy clean

#### T-R3-3-01: Add compensating delete to S4 fetch_and_write

**Type**: impl | **depends_on**: none | **blocks**: [T-R3-3-03]
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`

**What to build**: Track `written_minio_keys: list[str]` per batch. On rollback, iterate and call `store.delete(bucket, key)` best-effort. Reset list after successful commit.

#### T-R3-3-02: Add compensating delete to S5 consumer

**Type**: impl | **depends_on**: none | **blocks**: [T-R3-3-03]
**Target files**: `infrastructure/consumer/article_consumer.py`

**What to build**: Add `minio_silver_key: str | None` to `ProcessingSummary`. On DB commit failure, delete orphaned silver object best-effort.

#### T-R3-3-03: Tests for MinIO GC

**Type**: test | **depends_on**: [T-R3-3-01, T-R3-3-02] | **blocks**: none
**Target files**: `tests/unit/application/test_minio_gc.py` (S4), `tests/unit/infrastructure/test_minio_gc.py` (S5)

**Tests**: (≥6) Rollback deletes keys; GC failure doesn't propagate; committed batch not deleted; suppressed article no GC.

#### T-R3-3-04: Add delete method to ObjectStorage if missing

**Type**: impl | **depends_on**: none | **blocks**: [T-R3-3-01, T-R3-3-02]
**Target files**: `libs/storage/src/storage/interface.py`, `libs/storage/src/storage/s3_adapter.py`

**What to build**: Verify `delete(bucket, key)` exists. If not, add to ABC + implement in S3ObjectStorage.

### Validation Gate
- [x] `ruff check` + `mypy` clean | ≥6 new tests | GC only on failure paths

---

## Wave 4: Architecture Enforcement Tests ✅

**Goal**: Automated tests enforcing architectural invariants across all services.
**Depends on**: Wave 1, Wave 2, Wave 3
**Estimated effort**: 30–45 minutes
**Status**: **DONE** — 2026-03-27 · 35 architecture tests pass (6 new) · ruff clean

#### T-R3-4-01: Port directory enforcement test

**Type**: test | **depends_on**: none | **blocks**: none
**Target files**: `tests/architecture/test_ports_enforcement.py`

**Tests**: (≥2) Every service with `application/` also has `application/ports/`; each ports dir has ≥1 ABC.

#### T-R3-4-02: DomainError inheritance enforcement test

**Type**: test | **depends_on**: none | **blocks**: none
**Target files**: `tests/architecture/test_domain_error_enforcement.py`

**Tests**: (≥2) Every domain errors module defines `DomainError`; all exceptions inherit from it.

#### T-R3-4-03: BaseKafkaConsumer enforcement test

**Type**: test | **depends_on**: none | **blocks**: none
**Target files**: `tests/architecture/test_consumer_enforcement.py`

**Tests**: (≥2) All consumer classes extend `BaseKafkaConsumer`; no direct `confluent_kafka.Consumer` usage outside `libs/messaging`.

### Validation Gate
- [x] ≥6 architecture tests | All pass for current codebase

---

## Wave 5: Standards, Rules, and Documentation ✅

**Goal**: Codify all patterns in RULES.md, STANDARDS.md, review checklist, and service context docs.
**Depends on**: Waves 1–4
**Estimated effort**: 20–30 minutes
**Status**: **DONE** — 2026-03-27 · R20 + R21 in RULES.md · 3 new STANDARDS.md sections · context + checklist updated

#### T-R3-5-01: Add R20 — Kafka consumers must extend BaseKafkaConsumer

**Type**: docs | **Target files**: `RULES.md`

#### T-R3-5-02: Add R21 — Domain exceptions must inherit DomainError

**Type**: docs | **Target files**: `RULES.md`

#### T-R3-5-03: Update STANDARDS.md with ABC ports, Kafka consumer, MinIO GC sections

**Type**: docs | **Target files**: `docs/STANDARDS.md`

**Sections to add**: "Application Layer Port Pattern (Mandatory)", "Kafka Consumer Standard", "MinIO Compensating Delete"

#### T-R3-5-04: Update .claude-context.md + REVIEW_CHECKLIST.md

**Type**: docs | **Target files**: S4 + S5 `.claude-context.md`, `.claude/review/checklists/REVIEW_CHECKLIST.md`

### Validation Gate
- [x] All docs updated | R20, R21 in RULES.md | 3 new sections in STANDARDS.md

---

## Risk Assessment

**Critical path**: Wave 1 → Wave 2 (consumer rewrite)
**Highest risk**: Wave 2 — 12 abstract methods, mission-critical message processing
**Rollback**: Each wave is independently committable. Ports (W1) are backward-compatible.

---

## Tracking

| Wave | Status | Tasks Done | Tasks Total |
|------|--------|-----------|-------------|
| W1 | done | 5 | 5 |
| W2 | done | 5 | 5 |
| W3 | done | 4 | 4 |
| W4 | done | 3 | 3 |
| W5 | done | 4 | 4 |
