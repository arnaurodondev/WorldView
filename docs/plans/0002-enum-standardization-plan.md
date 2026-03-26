---
id: PLAN-0002
prd: N/A
title: "Enum Standardization: Shared OutboxStatus + ContentSourceType"
status: completed
created: 2026-03-26
updated: 2026-03-26
plans: 1
waves: 2
tasks: 8
supersedes: null
---

# PLAN-0002: Enum Standardization

## Overview

**Goal**: Eliminate duplicated enum definitions across services by extracting shared enums into the appropriate shared libraries, then migrating each service to import from the shared location.

**Motivation**: `OutboxStatus` is independently defined in 3 services (S1, S2, S5) with drift already occurring (S5 is missing `FAILED`). S4 uses bare string literals for the same values. `ContentSourceType` is identically defined in both S4 and S5. This duplication creates consistency risk as more services are added.

**Scope**: 2 shared enums, 2 shared libraries, 4 services modified, documentation updates.

**What is NOT in scope**: `Provider` and `DatasetType` enums in S2/S3 — these have different semantics, different values, and different casing. They are intentionally service-local.

---

## Audit Results

### OutboxStatus — 3 definitions + 1 implicit

| Service | Location | Values | Notes |
|---------|----------|--------|-------|
| S1 Portfolio | `domain/enums.py` | PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER | Canonical (5 values) |
| S2 Market Ingestion | `domain/enums.py` | PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER | Identical to S1 |
| S4 Content Ingestion | string literals in models/repos | "pending", "processing", "delivered", "dead_letter" | No enum class; missing FAILED |
| S5 Content Store | `domain/enums.py` | PENDING, PROCESSING, DELIVERED, DEAD_LETTER | Missing FAILED |

**Decision**: Canonical definition = 5 values (S1/S2 version). S4 and S5 must add FAILED.

### ContentSourceType — 2 identical definitions

| Service | Location | Values |
|---------|----------|--------|
| S4 Content Ingestion | `domain/entities.py` (inline) | EODHD, SEC_EDGAR, FINNHUB, NEWSAPI, MANUAL |
| S5 Content Store | `domain/enums.py` | EODHD, SEC_EDGAR, FINNHUB, NEWSAPI, MANUAL |

**Decision**: Extract to `libs/contracts` since this is a cross-service event discriminator (S4 produces `content.article.raw.v1` with `source_type`, S5 consumes it).

### Enums NOT shared (service-local, different semantics)

| Enum | Services | Why not shared |
|------|----------|---------------|
| `Provider` | S2, S3 | Different values (S2: yahoo_finance, S3: yahoo), different scopes |
| `DatasetType` | S2, S3 | Different casing (s2: lowercase, s3: UPPERCASE), different member counts |
| `Timeframe` | S3 only | Service-specific |
| `DedupOutcome` | S5 only | Service-specific |
| All other enums | Single service | No duplication |

---

## Plan Dependency Graph

```
Wave 1: Add shared enums to libs/messaging + libs/contracts
    │
    └──→ Wave 2: Migrate services S1, S2, S4, S5 to use shared enums
```

**Parallelizable with**: Any ongoing plan (no file conflicts with PLAN-0001-B or PLAN-0001-C).
**Should execute before**: PLAN-0001-C (S6/S7/S10) to prevent further duplication in new services.

---

## Wave 1: Add Shared Enums to Libraries

**Goal**: Define canonical `OutboxStatus` in `libs/messaging` and `ContentSourceType` in `libs/contracts`. Add tests. No service changes yet.
**Depends on**: none
**Estimated effort**: 20–30 minutes
**Architecture layer**: shared library

### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-1-01 | Add OutboxStatus to libs/messaging | impl | `libs/messaging/src/messaging/enums.py`, `libs/messaging/src/messaging/__init__.py` | `OutboxStatus(StrEnum)` with 5 values: PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER. Exported from `messaging.__init__`. Unit test verifying all 5 values and string comparison. |
| T-1-02 | Add ContentSourceType to libs/contracts | impl | `libs/contracts/src/contracts/enums.py`, `libs/contracts/src/contracts/__init__.py` | `ContentSourceType(StrEnum)` with 5 values: EODHD, SEC_EDGAR, FINNHUB, NEWSAPI, MANUAL. Exported from `contracts.__init__`. Unit test verifying all 5 values. |
| T-1-03 | Unit tests for shared enums | test | `libs/messaging/tests/test_enums.py`, `libs/contracts/tests/test_enums.py` | ≥6 tests: value correctness, string comparison, member count, StrEnum isinstance check for both enums. |
| T-1-04 | Add enum placement + outbox design rules to STANDARDS.md | docs | `docs/STANDARDS.md` | New section §2.4 "Shared Enums" documenting: which enums go in which lib, decision criteria for shared vs service-local, canonical locations. New section §3.X "Outbox Design Rules" with R-OUTBOX-1 through R-OUTBOX-5 (canonical column names, status values, DLQ population, payload format, ID type). |

#### Task Detail: T-1-01 — Add OutboxStatus to libs/messaging

**Type**: impl
**Target files**: `libs/messaging/src/messaging/enums.py` (new), `libs/messaging/src/messaging/__init__.py` (modify exports)

**What to build**: Create `enums.py` in libs/messaging with the canonical `OutboxStatus` StrEnum. This enum represents the transactional outbox event lifecycle and is used by every service that implements the outbox pattern. The canonical definition has 5 states matching the Portfolio/Market Ingestion implementation.

**Entity**:
- **Name**: `OutboxStatus`
- **Type**: `StrEnum`
- **Values**: `PENDING = "pending"`, `PROCESSING = "processing"`, `DELIVERED = "delivered"`, `FAILED = "failed"`, `DEAD_LETTER = "dead_letter"`
- **Invariants**: Values are lowercase strings matching DB column defaults and SQLAlchemy model defaults

**Acceptance criteria**:
- [ ] `OutboxStatus` importable from `messaging` top-level
- [ ] All 5 values present with correct string representations
- [ ] ruff + mypy clean on `libs/messaging/`

#### Task Detail: T-1-02 — Add ContentSourceType to libs/contracts

**Type**: impl
**Target files**: `libs/contracts/src/contracts/enums.py` (new), `libs/contracts/src/contracts/__init__.py` (modify exports)

**What to build**: Create `enums.py` in libs/contracts with `ContentSourceType` StrEnum. This enum is a cross-service discriminator: S4 writes it into `content.article.raw.v1` events, S5 reads it. Placing it in contracts ensures both services agree on valid values.

**Entity**:
- **Name**: `ContentSourceType`
- **Type**: `StrEnum`
- **Values**: `EODHD = "eodhd"`, `SEC_EDGAR = "sec_edgar"`, `FINNHUB = "finnhub"`, `NEWSAPI = "newsapi"`, `MANUAL = "manual"`
- **Invariants**: Values are lowercase, matching Avro schema string field values

**Acceptance criteria**:
- [ ] `ContentSourceType` importable from `contracts` top-level
- [ ] All 5 values present with correct string representations
- [ ] ruff + mypy clean on `libs/contracts/`

#### Pre-Read
- `libs/messaging/src/messaging/__init__.py` — current exports
- `libs/contracts/src/contracts/__init__.py` — current exports
- `services/portfolio/src/portfolio/domain/enums.py` — canonical OutboxStatus reference
- `services/content-ingestion/src/content_ingestion/domain/entities.py` — canonical SourceType reference

#### Validation Gate
- [ ] `ruff check libs/messaging/ libs/contracts/` passes
- [ ] `mypy libs/messaging/src/ libs/contracts/src/` passes (with respective configs)
- [ ] `python -m pytest libs/messaging/tests/test_enums.py -v` — ≥3 tests pass
- [ ] `python -m pytest libs/contracts/tests/test_enums.py -v` — ≥3 tests pass
- [ ] Existing lib tests still pass (no regression)

#### Regression Guardrails
- Ensure `__init__.py` `__all__` lists remain alphabetically sorted (RUF022)
- Do not modify existing exports — only add new ones

---

## Wave 2: Migrate Services to Shared Enums

**Goal**: Replace service-local `OutboxStatus` and `SourceType`/`ContentSourceType` definitions with imports from shared libraries. Fix S4/S5 to include all 5 OutboxStatus values. Update all tests.
**Depends on**: Wave 1
**Estimated effort**: 30–45 minutes
**Architecture layer**: domain + infrastructure (all 4 services)

### Tasks

| ID | Task | Type | Target Files | Acceptance Criteria |
|----|------|------|-------------|---------------------|
| T-2-01 | Migrate S1 (Portfolio) OutboxStatus | refactor | `services/portfolio/src/portfolio/domain/enums.py`, imports across service | Remove local `OutboxStatus` class. Add `from messaging import OutboxStatus` re-export or direct import. All existing tests pass unchanged (values are identical). |
| T-2-02 | Migrate S2 (Market Ingestion) OutboxStatus | refactor | `services/market-ingestion/src/market_ingestion/domain/enums.py`, imports across service | Remove local `OutboxStatus` class. Add `from messaging import OutboxStatus` re-export or direct import. All existing tests pass unchanged. |
| T-2-03 | Migrate S4 (Content Ingestion) SourceType + add OutboxStatus | refactor | `services/content-ingestion/src/content_ingestion/domain/entities.py`, imports across service | Remove local `SourceType` class from entities.py. Import `ContentSourceType` from `contracts` and alias as `SourceType` for backward compatibility. No existing test should break. |
| T-2-04 | Migrate S5 (Content Store) OutboxStatus + SourceType | refactor | `services/content-store/src/content_store/domain/enums.py`, imports across service | Remove local `OutboxStatus` and `SourceType` classes. Import from `messaging` and `contracts` respectively. Re-export from `domain/enums.py` for internal use. Add missing FAILED value (now comes from shared). All existing tests pass. |

#### Task Detail: T-2-01 — Migrate S1 (Portfolio) OutboxStatus

**Type**: refactor
**Target files**:
- `services/portfolio/src/portfolio/domain/enums.py` — remove OutboxStatus definition, add re-export
- Any files importing `from portfolio.domain.enums import OutboxStatus` — verify they still work

**What to build**: Replace the local `OutboxStatus` definition with a re-export from `messaging`. Since S1's values are identical to the shared definition, this is a safe drop-in replacement. Re-exporting from `domain/enums.py` preserves all existing import paths.

**Migration pattern**:
```python
# Before (in domain/enums.py):
class OutboxStatus(StrEnum):
    PENDING = "pending"
    ...

# After (in domain/enums.py):
from messaging import OutboxStatus as OutboxStatus  # noqa: PLC0414 — re-export
```

**Downstream test impact**:
- `services/portfolio/tests/` — all tests importing OutboxStatus from domain.enums must still work
- No Avro schema changes, no DB schema changes

**Acceptance criteria**:
- [ ] No local `OutboxStatus` class definition in S1
- [ ] `from portfolio.domain.enums import OutboxStatus` still works (re-export)
- [ ] All S1 tests pass
- [ ] ruff + mypy clean

#### Task Detail: T-2-02 — Migrate S2 (Market Ingestion) OutboxStatus

**Type**: refactor
**Target files**:
- `services/market-ingestion/src/market_ingestion/domain/enums.py` — remove OutboxStatus definition, add re-export

**What to build**: Same pattern as T-2-01. S2's OutboxStatus is identical to the shared definition.

**Downstream test impact**:
- `services/market-ingestion/tests/domain/test_enums.py` — tests asserting OutboxStatus values must pass

**Acceptance criteria**:
- [ ] No local `OutboxStatus` class definition in S2
- [ ] `from market_ingestion.domain.enums import OutboxStatus` still works
- [ ] All S2 tests pass (including test_enums.py lines 120-124 and 129)
- [ ] ruff + mypy clean

#### Task Detail: T-2-03 — Migrate S4 (Content Ingestion) SourceType

**Type**: refactor
**Target files**:
- `services/content-ingestion/src/content_ingestion/domain/entities.py` — remove SourceType class, import from contracts
- `services/content-ingestion/src/content_ingestion/domain/__init__.py` — update exports if needed

**What to build**: Replace the inline `SourceType` StrEnum in `entities.py` with an import from `contracts`. Use `from contracts import ContentSourceType as SourceType` to preserve backward compatibility (all existing code references `SourceType`, not `ContentSourceType`).

**Downstream test impact**:
- 14 files in S4 import/reference `SourceType` — all must continue working via the alias
- `services/content-ingestion/tests/unit/test_domain.py` — SourceType tests

**Acceptance criteria**:
- [ ] No local `SourceType` class definition in S4
- [ ] `from content_ingestion.domain.entities import SourceType` still works (re-export from entities.py)
- [ ] All 14 files referencing SourceType unchanged
- [ ] All S4 tests pass (126+ tests)
- [ ] ruff + mypy clean

#### Task Detail: T-2-04 — Migrate S5 (Content Store) OutboxStatus + SourceType

**Type**: refactor
**Target files**:
- `services/content-store/src/content_store/domain/enums.py` — remove OutboxStatus and SourceType, add re-exports

**What to build**: Replace both local enums with imports from shared libs. This also fixes the missing `FAILED` value in S5's OutboxStatus (the shared version has all 5 values). Re-export both from `domain/enums.py` for internal use.

**Downstream test impact**:
- `services/content-store/tests/unit/domain/test_enums.py` — TestOutboxStatus needs updating to verify 5 values (was 4)
- `services/content-store/tests/unit/domain/test_entities.py` — uses SourceType, must still work

**Acceptance criteria**:
- [ ] No local `OutboxStatus` or `SourceType` class definitions in S5
- [ ] S5 OutboxStatus now has 5 values (FAILED added via shared import)
- [ ] All S5 tests pass (update test_enums.py to expect 5 OutboxStatus values)
- [ ] ruff + mypy clean

#### Pre-Read
- Each service's `domain/enums.py` and `domain/__init__.py`
- Each service's test files that import the affected enums
- `libs/messaging/src/messaging/__init__.py` — verify OutboxStatus is exported
- `libs/contracts/src/contracts/__init__.py` — verify ContentSourceType is exported

#### Validation Gate
- [ ] `ruff check services/portfolio/ services/market-ingestion/ services/content-ingestion/ services/content-store/` passes
- [ ] `mypy` passes for all 4 services
- [ ] All unit tests pass for all 4 services (no regression)
- [ ] `python3 scripts/import_guards/check_import_guards.py --strict --baseline scripts/import_guards/baseline.json --services portfolio market-ingestion content-ingestion content-store` passes
- [ ] No local `OutboxStatus` class definitions remain in any service
- [ ] No local `SourceType`/`ContentSourceType` class definitions remain in S4 or S5

#### Regression Guardrails
- BP-001: Import paths must not break — re-exports preserve existing import contracts
- Verify `domain/enums.py` re-exports don't introduce circular imports (domain → messaging is infrastructure — but StrEnum is just a type, no infra dependency)

---

## Cross-Cutting Concerns

### Architecture Note: Domain Layer Purity

The STANDARDS.md §1 says domain layers must have "zero infrastructure imports." However, `StrEnum` re-exports from `libs/messaging` and `libs/contracts` are **type definitions, not infrastructure code**. These libraries provide:
- `OutboxStatus` — a plain StrEnum with string constants (no Kafka, no DB)
- `ContentSourceType` — a plain StrEnum with string constants (no serialization, no schemas)

This is analogous to how `libs/common` provides `new_uuid7()` and `utc_now()` — utility types used in domain layers. An ADR is NOT required since this is a refactoring with no new service or architectural change (R4/R16).

### Documentation Updates Required

| Document | Update | Wave |
|----------|--------|------|
| `docs/STANDARDS.md` | Add §2.4 "Shared Enums" + §3.X "Outbox Design Rules" (R-OUTBOX-1..5) | Wave 1 |
| `docs/libs/messaging.md` | Add OutboxStatus to exported types | Wave 1 |
| `docs/libs/contracts.md` | Add ContentSourceType to exported types | Wave 1 |
| `services/portfolio/.claude-context.md` | Note: OutboxStatus from messaging | Wave 2 |
| `services/market-ingestion/.claude-context.md` | Note: OutboxStatus from messaging | Wave 2 |
| `services/content-ingestion/.claude-context.md` | Note: SourceType from contracts | Wave 2 |
| `services/content-store/.claude-context.md` | Note: OutboxStatus from messaging, SourceType from contracts | Wave 2 |

### Configuration
No env var changes. No Docker changes. No Avro schema changes. No DB migrations.

---

## Appendix A: Outbox Implementation Audit

This audit was conducted during plan creation to understand the full scope of outbox-related standardization. The enum standardization (Waves 1-2) is the first step. Broader outbox model alignment is documented here for future work.

### Outbox Model Divergence Across Services

| Aspect | S1 Portfolio | S2 Market-Ingestion | S3 Market-Data | S4 Content-Ingestion | S5 Content-Store |
|--------|-------------|--------------------|----|----|----|
| **Status values** | 4: pending, processing, delivered, dead_letter | 5: pending, in_flight, published, retry, dead | 3: pending, delivered, dead_letter | 4: pending, processing, delivered, dead_letter | 4: same as S4 |
| **`topic` column** | Missing (inferred at runtime) | Yes | Yes | Yes | Yes |
| **Lease column** | `lease_expires` | `locked_until` | `lease_expires_at` | `leased_until` | `leased_until` |
| **Attempts column** | `attempt_count` | `attempt` | `attempts` | `attempts` | `attempts` |
| **ID type** | UUID | ULID (String) | UUID-as-string | UUID | UUID |
| **Payload type** | JSONB | LargeBinary | JSONB | JSONB | JSONB |
| **DLQ table** | No | No | No | Yes (populated) | Yes (orphaned!) |
| **Retry scheduling** | No | Yes (`next_attempt_at`) | No | No | No |
| **Uses OutboxStatus enum** | Yes | Yes | No (strings) | No (strings) | Yes (incomplete) |

### Protocol Column Name Mapping

`OutboxRecordProtocol` (from `libs/messaging`) requires: `id`, `event_type`, `topic`, `payload`, `attempts`, `leased_until`.

| Protocol Field | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|
| `id` | `id` (UUID) | `id` (ULID) | `id` (UUID-str) | `id` (UUID) | `id` (UUID) |
| `topic` | **MISSING** | `topic` | `topic` | `topic` | `topic` |
| `payload` | `payload` (JSONB) | `payload` (bytes) | `payload` (JSONB) | `payload` (JSONB) | `payload` (JSONB) |
| `attempts` | `attempt_count` | `attempt` | `attempts` | `attempts` | `attempts` |
| `leased_until` | `lease_expires` | `locked_until` | `lease_expires_at` | `leased_until` | `leased_until` |

### Known Issues

1. **S5 Content-Store DLQ orphaned**: `dead_letter_queue` table exists but `move_to_dead_letter()` only changes outbox status — never inserts a DLQ row. Either populate it or remove the table.
2. **S1 Portfolio missing `topic`**: Topic is inferred from `EVENT_TOPIC_MAP` at runtime. This makes the outbox table non-self-describing.
3. **S2 Market-Ingestion uses different status names**: `in_flight` (not `processing`), `published` (not `delivered`), `dead` (not `dead_letter`). Also uses LargeBinary payload.
4. **Column name drift**: 3 different names for the lease column, 3 for attempts.

### Outbox Design Rules (to add to STANDARDS.md)

The following rules should be added to STANDARDS.md §3 to prevent further divergence in new services:

**R-OUTBOX-1: Canonical column names** — New outbox tables MUST use the protocol-standard column names: `id` (UUID), `event_type`, `topic`, `payload` (JSONB), `status`, `attempts`, `leased_until`, `lease_owner`, `created_at`, `dispatched_at`.

**R-OUTBOX-2: Canonical status values** — Use `OutboxStatus` from `libs/messaging`: PENDING → PROCESSING → DELIVERED | FAILED → DEAD_LETTER. Services MAY add service-specific statuses but MUST support the canonical 5.

**R-OUTBOX-3: DLQ population** — If a service defines a `dead_letter_queue` table, `move_to_dead_letter()` MUST insert a row into it (not just change the outbox status). If no DLQ table exists, changing the outbox status to `dead_letter` is sufficient.

**R-OUTBOX-4: Payload format** — Outbox payload SHOULD be stored as JSONB for debuggability. Services that need binary Avro payloads for performance MUST document the reason.

**R-OUTBOX-5: ID type** — Outbox event IDs MUST use UUIDv7 (`common.ids.new_uuid7()`). ULIDs are acceptable for backward compatibility but UUIDv7 is preferred for new services.

These rules apply to **new services only**. Existing services will be aligned in a future refactoring plan (PLAN-TBD) if warranted. The enum standardization in Waves 1-2 is the minimum alignment needed now.

---

## Risk Assessment

- **Risk level**: Low — Waves 1-2 are pure refactoring with no behavior change
- **Critical path**: Wave 1 must complete before Wave 2
- **Highest risk**: Circular import if domain layer imports from messaging. Mitigated by: `OutboxStatus` is a plain StrEnum with no infrastructure dependencies
- **Rollback**: Revert commits — no schema or state changes to worry about
- **Testing gaps**: None — existing tests cover all enum usage; we only change import sources
- **Future work**: Full outbox model alignment (column names, DLQ population, S2 status reconciliation) is a separate plan, documented in Appendix A for reference
