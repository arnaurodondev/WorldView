# Response 0014 — Common Library Extension: UUIDv7 + Ingestion Types

**Date:** 2026-03-23
**Scope:** Extend `libs/common` with UUIDv7 support and ingestion-domain type aliases; enforce its usage across all services; update planned execution waves to use it consistently.
**Status:** Planning complete — ready for wave execution

---

## 1. Executive Summary

`libs/common` is the canonical source of cross-cutting utilities (time, ID generation, type aliases) shared across all services in this monorepo. Currently it provides `new_uuid()` (UUIDv4) for entity IDs and `new_ulid()` for Kafka event IDs. The PRD mandates UUIDv7 for all entity primary keys in the ingestion pipeline (S4, S5, S6, S7, S10).

This scope makes four changes:

1. **Add `new_uuid7()` and `new_uuid7_str()`** to `common.ids`, backed by the `uuid6` package, giving all services a single import point for RFC 9562 UUIDv7 generation.
2. **Add cross-service ingestion type aliases** (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`) to `common.types` — only types referenced by two or more services are promoted; service-local IDs remain in each service's domain layer.
3. **Wire new symbols into `common.__init__`**, expanding `__all__` from 17 to 21 exported symbols.
4. **Add `uuid6>=2024.1.12`** as a dependency in `libs/common/pyproject.toml`.

Alongside the library changes, six services that were missing an explicit `common` dependency in their `pyproject.toml` files are corrected, and all 20 existing execution wave planning documents (7 from prompt-0012, 13 from prompt-0013) are updated to enforce `common.ids.new_uuid7()` over direct `uuid6` usage.

---

## 2. Current State vs Target State Matrix

| Component | Current State | Target State | Gap |
|-----------|--------------|-------------|-----|
| `common.ids.new_uuid7` | Does not exist; `new_uuid()` returns UUIDv4 | `new_uuid7() -> uuid.UUID` (RFC 9562 UUIDv7 via `uuid6` package) | Add function + dep |
| `common.ids.new_uuid7_str` | Does not exist | `new_uuid7_str() -> str` | Add function |
| `common.types` ingestion aliases | `TenantId`, `UserId`, `InstrumentId`, `TransactionId`, `EventId`, `TopicName`, `JsonDict` only | Add `DocumentId`, `EntityId`, `UrlHash`, `MinIOKey` | 4 new NewType aliases |
| `common.__init__` | Exports 17 symbols | Exports 21 symbols (adds 4 new types + 2 new id functions; net +4 because new_uuid7/new_uuid7_str were already counted in ids but not __all__) | Update `__all__` |
| `common pyproject.toml` | `python-ulid==3.0.0` only | Add `uuid6>=2024.1.12` | 1 new dep |
| `services/market-data` | No `common` dep | `common` in dependencies | Add 1 line |
| `services/content-ingestion` | No `common` dep | `common` in dependencies | Add 1 line |
| `services/content-store` | No `common` dep | `common` in dependencies | Add 1 line |
| `services/nlp-pipeline` | No `common` dep | `common` in dependencies | Add 1 line |
| `services/knowledge-graph` | No `common` dep | `common` in dependencies | Add 1 line |
| `services/alert` | No `common` dep | `common` in dependencies | Add 1 line |
| 0012 wave files (7) | Reference `uuid6.uuid7()` directly | Reference `common.ids.new_uuid7()` | Constraint update |
| 0013 wave files (13) | Reference `uuid6.uuid7()` or raw uuid | Reference `common.ids.new_uuid7()` | Constraint update |
| `docs/libs/common.md` | Documents UUIDv4 + ULID only | Documents UUIDv7, new types, usage guide | Update |

---

## 3. New Type Aliases Rationale

Only types referenced by two or more services are promoted to `common.types`. Service-local types stay in each service's domain layer.

### Types added to `common.types`

| Alias | Underlying Type | Cross-service usage | Rationale |
|-------|----------------|-------------------|-----------|
| `DocumentId` | `NewType("DocumentId", UUID)` | S5 creates, S6 enriches, S7 produces evidence for | Canonical document traverses 3 services |
| `EntityId` | `NewType("EntityId", UUID)` | S6 resolves, S7 graphs, S10 fans out on | Intelligence entity traverses 3 services |
| `UrlHash` | `NewType("UrlHash", str)` | S4 computes, S5 checks for dedup | Dedup key crosses S4→S5 boundary |
| `MinIOKey` | `NewType("MinIOKey", str)` | S4 writes bronze, S5 reads bronze + writes silver, S6 reads silver | Storage key traverses 3 services |

### Types NOT added to `common.types` — define in each service's domain layer

| Type | Service | Reason not promoted |
|------|---------|---------------------|
| `RawArticleId` | S4 only | Not referenced downstream |
| `SourceId` | S4 only | Internal to fetch orchestration |
| `FetchLogId` | S4 only | Internal to fetch orchestration |
| `SignatureId` | S5 only | Dedup-internal, not exposed cross-service |
| `SectionId` | S6 only | NLP-internal chunking detail |
| `ChunkId` | S6 only | NLP-internal chunking detail |
| `RelationId` | S7 only | Graph-internal edge identifier |
| `EvidenceId` | S7 only | Graph-internal provenance identifier |
| `AlertId` | S10 only | Alerting-internal, not consumed by other services |

---

## 4. Atomic Task Backlog

### T-C-001 — Extend libs/common

**Files:**
- `libs/common/src/common/ids.py` — add `new_uuid7()`, `new_uuid7_str()`
- `libs/common/src/common/types.py` — add `DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`
- `libs/common/src/common/__init__.py` — update imports and `__all__`
- `libs/common/pyproject.toml` — add `uuid6>=2024.1.12`
- `libs/common/tests/test_ids.py` — add `TestNewUuid7` (6 tests)
- `libs/common/tests/test_types.py` — add tests for 4 new ingestion types
- `docs/libs/common.md` — document UUIDv7 functions, decision table, new types, updated pitfalls

**Effort:** 2h
**Dependency:** None — this is the wave foundation

### T-C-002 — Add `common` dependency to 6 service pyproject.toml files

**Files:**
- `services/market-data/pyproject.toml`
- `services/content-ingestion/pyproject.toml`
- `services/content-store/pyproject.toml`
- `services/nlp-pipeline/pyproject.toml`
- `services/knowledge-graph/pyproject.toml`
- `services/alert/pyproject.toml`

**Note:** This is already done via direct file edits — verification only required. If `"common"` is present in all 6 files, no edit is needed. If missing from any, add `"common",` as the first entry in the `dependencies` list, matching the pattern in `services/portfolio/pyproject.toml` and `services/market-ingestion/pyproject.toml`.

**Effort:** 0.5h
**Dependency:** T-C-001 must be understood (dependency exists logically) but T-C-002 edits are independent of T-C-001 file outputs

### T-C-003 — Update 0012-exec wave files (7 files)

**Files:**
- `docs/ai-interactions/agent-prompts/0012-exec-ingestion-pipeline-v1-s4-s5-wave-01.md` through `wave-07.md`

**Changes per file:**
- Add `docs/libs/common.md` to Mandatory pre-read
- Replace `uuid6.uuid7()` references in Constraints with `common.ids.new_uuid7()` enforcement bullets
- Verify `services/content-ingestion/pyproject.toml` and `services/content-store/pyproject.toml` appear in write_paths

**Effort:** 1h
**Dependency:** T-C-001 (conceptually; no file-output dependency)

### T-C-004 — Update 0013-exec wave files (13 files)

**Files:**
- `docs/ai-interactions/agent-prompts/0013-exec-ingestion-pipeline-v1-s6-s7-s10-wave-01.md` through `wave-13.md`

**Changes per file:**
- Add `docs/libs/common.md` to Mandatory pre-read (EntityId-focused variant)
- Replace `uuid6.uuid7()` references in Constraints with `common.ids.new_uuid7()` enforcement bullets
- For S7 waves: add `EntityId` graph-column enforcement bullet
- For S10 waves (wave-11, wave-12, wave-13): add `EntityId` fan-out enforcement bullet

**Effort:** 1.5h
**Dependency:** T-C-001 (conceptually; no file-output dependency)

---

## 5. Open Questions and Assumptions

| Question | Assumption | Risk |
|----------|-----------|------|
| Is `uuid6>=2024.1.12` available in the project's package registry? | Yes — public PyPI, no private registry needed | Low |
| Should portfolio and market-ingestion be migrated to UUIDv7? | No — breaking change to live DB rows; only new services use `new_uuid7()` | None (explicitly out of scope) |
| Does `market-data` actually need `common` now? | Adding preventively — no current uuid/datetime usage in stub, but all services should declare the dep explicitly | None |
| Is UUIDv7 Postgres-compatible? | Yes — stored as UUID column type, byte-order-compatible with standard UUID representation | None |
| Will Python 3.14 stdlib UUIDv7 require a migration? | Future migration will be a single-library change (`common.ids`) rather than multi-service; `uuid6` is the bridge | Low |

---

## 6. Coverage Ledger

| task_id | assigned_wave | status | dependency_note |
|---------|--------------|--------|----------------|
| T-C-001 | wave-01 | scheduled | foundation — must execute first in sequential group |
| T-C-002 | wave-01 | scheduled | parallel with T-C-003/004 after T-C-001 is done; already done by direct edit |
| T-C-003 | wave-01 | scheduled | parallel with T-C-002/004 after T-C-001 is done |
| T-C-004 | wave-01 | scheduled | parallel with T-C-002/003 after T-C-001 is done |

---

## 7. Summary

| Metric | Value |
|--------|-------|
| Total tasks | 4 |
| Total waves | 1 |
| W_min (theoretical minimum) | 1 |
| Actual waves | 1 |
| Unassigned tasks | 0 |
| New functions in common.ids | 2 (`new_uuid7`, `new_uuid7_str`) |
| New type aliases in common.types | 4 (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`) |
| New tests | ≥10 (6 in TestNewUuid7, ≥4 new type tests) |
| Service pyproject.toml files patched | 6 |
| Wave planning docs patched | 20 (7 + 13) |

All 4 tasks are assigned to wave-01. The wave is single-pass: T-C-001 executes first (sequential group 1), then T-C-002, T-C-003, and T-C-004 run concurrently (parallel group 2). No tasks remain unassigned.
