---
id: PLAN-0001-B-R2
prd: PRD-0001
title: "S4+S5 QA Fixes: DDL Alignment, DLQ, SSRF, LSH Ordering, Contract Tests, Compounding"
status: completed
created: 2026-03-27
updated: 2026-03-28
plans: 1
waves: 4
tasks: 19
supersedes: null
---

# PLAN-0001-B-R2: S4+S5 QA & Review Fixes

## Overview

**Triggered by**: Multi-agent QA review of PLAN-0001-B (5 specialist agents)
**Goal**: Fix all BLOCKING, CRITICAL, and MAJOR findings from the QA pass, add tests that would have caught these issues, and update compounding documents to prevent recurrence.
**Total Scope**: 1 plan, 4 waves, 19 tasks

### Findings Being Fixed

| QA ID | Severity | Issue | Wave |
|-------|----------|-------|------|
| B-1 | BLOCKING | S5 `outbox_events` DDL mismatches ORM (BP-008) | W1 |
| B-2 | BLOCKING | S4 `dead_letter_queue` DDL missing `payload_json` | W1 |
| CR-1 | CRITICAL | S4 `doc_id=source_id` — all articles share same doc_id | W2 |
| CR-2 | CRITICAL | SSRF bypass via DNS hostnames resolving to private IPs | W2 |
| CR-3 | CRITICAL | S5 LSH `index()` called before DB commit → phantom entries | W2 |
| CR-4 | CRITICAL | No Avro contract tests for `content.article.stored.v1` | W3 |
| M-1 | MAJOR | S5 `move_to_dead_letter` doesn't copy to DLQ table | W1 |
| M-2 | MAJOR | S5 DLQ `requeue()` produces empty payload | W1 |
| M-3 | MAJOR | S5 session factory doesn't return engine → connection leak | W2 |
| M-5 | MAJOR | S5 `ArticleConsumer.process_message` untested | W3 |
| M-8 | MAJOR | DDL defaults use `gen_random_uuid()` (UUIDv4) | W1 |

### Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| D-1 | S5 application ports: **defer** | Refactor scope — doesn't affect correctness. Create PLAN-0001-B-R3 |
| D-2 | SSRF DNS resolution: **fix now** | Security critical — DNS rebinding is a known attack vector |
| D-3 | S5 Kafka consumer poll loop: **defer** | Deployment integration — consumer `process_message()` works; loop is wired when deploying |
| D-4 | MinIO orphan GC: **defer** | Accepted trade-off for MVP — MinIO storage is cheap |
| D-5 | S4 DomainError base class: **defer** | Consistency improvement, not a bug. Add to refactor wave |

---

## Pre-Read (agent must read before any wave)

- `RULES.md` — hard rules (R5, R8, R9, R10, R19)
- `docs/ai-interactions/BUG_PATTERNS.md` — BP-001, BP-008
- `services/content-ingestion/.claude-context.md`
- `services/content-store/.claude-context.md`
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py` — S4 ORM (reference)
- `services/content-store/src/content_store/infrastructure/db/models.py` — S5 ORM (must match DDL)
- `services/content-ingestion/tests/unit/test_avro_schema.py` — reference for S5 contract tests

---

## Wave 1: DDL Alignment + DLQ Fixes ✅

**Goal**: Fix all migration DDL to match ORM models exactly, fix DLQ copy logic, and add DDL-vs-ORM alignment tests that would have caught these issues.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-28 · 200 S5 + 220 S4 tests pass · ruff + mypy clean

### Tasks

#### T-R2-1-01: Rewrite S5 `outbox_events` DDL in migration 0001 to match ORM

**Type**: schema
**depends_on**: none
**blocks**: [T-R2-1-05]
**Target files**: `services/content-store/alembic/versions/0001_create_content_store_schema.py`

**What to build**:
Replace the S5 `outbox_events` CREATE TABLE in migration 0001 with DDL matching the ORM exactly. The current DDL defines `event_id`, `partition_key`, `payload_avro BYTEA`, `retry_count`, `failed_at` — none of which exist in the ORM. The ORM has `id`, `aggregate_type`, `aggregate_id`, `event_type`, `topic`, `payload JSONB`, `status`, `lease_owner`, `leased_until`, `attempts`, `max_attempts`, `created_at`, `dispatched_at`.

**DDL to write** (must match `OutboxEventModel` exactly):
```sql
CREATE TABLE outbox_events (
    id             UUID        PRIMARY KEY,
    aggregate_type TEXT        NOT NULL,
    aggregate_id   UUID        NOT NULL,
    event_type     TEXT        NOT NULL,
    topic          TEXT        NOT NULL DEFAULT 'content.article.stored.v1',
    payload        JSONB       NOT NULL DEFAULT '{}',
    status         TEXT        NOT NULL DEFAULT 'pending',
    lease_owner    TEXT,
    leased_until   TIMESTAMPTZ,
    attempts       SMALLINT    NOT NULL DEFAULT 0,
    max_attempts   SMALLINT    NOT NULL DEFAULT 5,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ
)
```
Index: `CREATE INDEX ix_outbox_claimable ON outbox_events (status, leased_until) WHERE status IN ('pending', 'processing')`

Also fix `documents` table: remove `DEFAULT gen_random_uuid()` from `doc_id` (use app-generated UUIDv7). Remove `gen_random_uuid()` defaults from all UUID PKs in both migrations (M-8 fix).

Also fix `dead_letter_queue` DDL: add `payload_json JSONB` column (for M-2 fix).

**Downstream test impact**:
- Integration tests using `Base.metadata.create_all()` bypass Alembic, so they won't catch this — hence the need for T-R2-1-05.

**Acceptance criteria**:
- [ ] Every column in S5 `outbox_events` DDL matches `OutboxEventModel` name, type, default, nullable
- [ ] No `gen_random_uuid()` defaults on any UUID PK across both S5 migrations
- [ ] S5 `dead_letter_queue` DDL has `payload_json JSONB` column
- [ ] `alembic upgrade head` succeeds against test Postgres (if available)

---

#### T-R2-1-02: Add `payload_json` to S4 `dead_letter_queue` DDL

**Type**: schema
**depends_on**: none
**blocks**: [T-R2-1-05]
**Target files**: `services/content-ingestion/alembic/versions/0001_initial_s4_schema.py`

**What to build**:
Add `payload_json JSONB` column to the S4 `dead_letter_queue` CREATE TABLE in migration 0001. The ORM model has `payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)` but the migration DDL is missing it. The `move_to_dead_letter` repo method writes `payload_json=record.payload`, which will fail at runtime.

**Acceptance criteria**:
- [ ] S4 `dead_letter_queue` DDL includes `payload_json JSONB` after `payload_avro`
- [ ] Column is nullable (no NOT NULL, no DEFAULT)

---

#### T-R2-1-03: Fix S5 `move_to_dead_letter` to copy record to DLQ table

**Type**: impl
**depends_on**: [T-R2-1-01]
**blocks**: [T-R2-1-06]
**Target files**: `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py`

**What to build**:
Replace the current `move_to_dead_letter` (which only updates status) with the S4 pattern: fetch the outbox record, create a `DeadLetterQueueModel` row with `dlq_id`, `original_event_id`, `topic`, `payload_avro=b""`, `payload_json=record.payload`, `error_detail`, then update the outbox status to `dead_letter`.

Also add `error_detail: str = ""` parameter matching S4's signature.

**Logic**:
1. SELECT the outbox record by ID
2. If found, INSERT a `DeadLetterQueueModel` with the original payload
3. UPDATE the outbox status to `dead_letter`

**Acceptance criteria**:
- [ ] `move_to_dead_letter(record_id, error_detail)` creates a DLQ row
- [ ] DLQ row has `payload_json` populated from the outbox payload
- [ ] DLQ admin API (`/admin/dlq`) will now show dead-lettered events

---

#### T-R2-1-04: Fix S5 DLQ `requeue()` to use `payload_json`

**Type**: impl
**depends_on**: [T-R2-1-01]
**blocks**: [T-R2-1-06]
**Target files**: `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py`, `services/content-store/src/content_store/infrastructure/db/models.py`

**What to build**:
1. Add `payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)` to `DeadLetterQueueModel`
2. Update `DLQRepository.requeue()` to use `entry.payload_json or {}` instead of hardcoded `payload={}`

**Acceptance criteria**:
- [ ] `DeadLetterQueueModel` has `payload_json` column
- [ ] `requeue()` creates outbox event with original payload data
- [ ] Requeued events produce non-empty Kafka messages

---

#### T-R2-1-05: Add DDL-vs-ORM alignment tests for both services

**Type**: test
**depends_on**: [T-R2-1-01, T-R2-1-02]
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py`, `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py`

**What to build**:
Create tests that parse the migration DDL and compare column names/types against the SQLAlchemy ORM metadata. This prevents BP-008 recurrence. For each table, verify:
1. Every ORM column has a matching DDL column
2. Column types are compatible (JSONB↔JSONB, TEXT↔Text, etc.)
3. No extra DDL columns not in the ORM
4. No `gen_random_uuid()` defaults on UUID PKs

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_outbox_events_ddl_matches_orm | All outbox columns match | unit |
| test_dead_letter_queue_ddl_matches_orm | All DLQ columns match | unit |
| test_documents_ddl_matches_orm | All documents columns match (S5) | unit |
| test_sources_ddl_matches_orm | All sources columns match (S4) | unit |
| test_no_uuid4_defaults | No `gen_random_uuid()` in migrations | unit |

Minimum test count: 5 per service (10 total)

**Acceptance criteria**:
- [ ] Tests catch the exact DDL mismatches found by QA (outbox_events, dead_letter_queue)
- [ ] Tests would fail if run against the OLD migration DDL
- [ ] Tests pass against the FIXED migration DDL

---

#### T-R2-1-06: Add DLQ copy + requeue tests for S5

**Type**: test
**depends_on**: [T-R2-1-03, T-R2-1-04]
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_dlq_repo.py`

**What to build**:
Unit tests for the fixed `move_to_dead_letter` and `requeue` methods. Use mocked session to verify:
1. `move_to_dead_letter` creates a DLQ row with correct fields
2. `move_to_dead_letter` updates outbox status
3. `requeue` creates outbox event with original payload (not empty)
4. `requeue` marks DLQ entry as resolved

Minimum test count: 6

**Acceptance criteria**:
- [ ] Tests verify DLQ row creation (not just status update)
- [ ] Tests verify requeue payload is non-empty
- [ ] Tests would fail against the OLD implementation

---

### Validation Gate
- [x] `ruff check` passes on changed files
- [x] `mypy` passes on both services
- [x] All existing unit tests still pass (200 S5 + 220 S4)
- [x] ≥16 new tests pass (10 DDL alignment + 6 DLQ)

### Regression Guardrails
- BP-008: Migration DDL must match ORM — now enforced by tests
- BP-001: Outbox serializer must be `OutboxEventValueSerializer`

---

## Wave 2: Critical Bug Fixes (CR-1, CR-2, CR-3, M-3) ✅

**Goal**: Fix `doc_id` generation, SSRF DNS bypass, LSH ordering, and session factory leak.
**Depends on**: none (can run parallel with Wave 1)
**Estimated effort**: 45–60 minutes
**Status**: **DONE** — 2026-03-28 · 200 S5 + 220 S4 tests pass · ruff + mypy clean

### Tasks

#### T-R2-2-01: Fix S4 `doc_id=source_id` → generate unique UUIDv7 per article

**Type**: impl
**depends_on**: none
**blocks**: [T-R2-2-05]
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`

**What to build**:
Change line 181 from `doc_id=result.source_id` to `doc_id=common.ids.new_uuid7()`. Each article must have a unique `doc_id` in the outbox payload. `source_id` identifies the polling source, not the individual document.

**Acceptance criteria**:
- [ ] `doc_id` in outbox payload is a unique UUIDv7 per article
- [ ] `source_id` is still used for `aggregate_id` (correct — it identifies the aggregate)
- [ ] Existing tests pass

---

#### T-R2-2-02: Fix SSRF — resolve DNS hostname and check all IPs

**Type**: impl
**depends_on**: none
**blocks**: [T-R2-2-05]
**Target files**: `services/content-ingestion/src/content_ingestion/api/schemas.py`

**What to build**:
Enhance `validate_url_scheme_and_host` to resolve DNS hostnames via `socket.getaddrinfo()` and check ALL resolved IP addresses against `_PRIVATE_NETWORKS`. Currently, non-IP hostnames silently pass the check, allowing DNS rebinding attacks (e.g., `169.254.169.254.nip.io`).

**Logic**:
1. Parse URL, validate scheme (existing)
2. If hostname is a literal IP → check against `_PRIVATE_NETWORKS` (existing)
3. **NEW**: If hostname is NOT a literal IP → resolve via `socket.getaddrinfo(hostname, None)`
4. **NEW**: Check ALL resolved addresses against `_PRIVATE_NETWORKS`
5. **NEW**: Block `0.0.0.0/8` and `::1` (IPv6 loopback)

**Acceptance criteria**:
- [ ] `http://169.254.169.254.nip.io/...` is rejected
- [ ] `http://metadata.internal/...` is rejected (if it resolves to private IP)
- [ ] `http://google.com/...` is allowed (public IP)
- [ ] Non-resolving hostnames raise an appropriate error

---

#### T-R2-2-03: Move S5 LSH `index()` to after DB commit

**Type**: impl
**depends_on**: none
**blocks**: [T-R2-2-05]
**Target files**: `services/content-store/src/content_store/application/use_cases/process_article.py`, `services/content-store/src/content_store/infrastructure/consumer/article_consumer.py`

**What to build**:
The LSH `index()` call currently executes inside `ProcessArticleUseCase.execute()` (line 250–254), which runs BEFORE the session is committed in the consumer. If the commit fails, Valkey has phantom entries.

Fix: Return the signature and doc_id from `execute()` in the `ProcessingSummary`. Have the consumer call `lsh.index()` AFTER `session.commit()` succeeds.

**Changes**:
1. Add `signature: list[int] | None = None` and `source_type: str | None = None` to `ProcessingSummary`
2. Remove the `self._lsh.index(...)` call from `execute()`
3. Return the signature data in the summary
4. In `ArticleConsumer.process_message`, call `lsh.index()` after `session.commit()` using the summary data

**Acceptance criteria**:
- [ ] `ProcessArticleUseCase.execute()` no longer calls `lsh.index()`
- [ ] LSH index is called only after successful DB commit
- [ ] LSH index failure is still best-effort (logged, not raised)

---

#### T-R2-2-04: Fix S5 session factory to return engine + dispose on shutdown

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/src/content_store/infrastructure/db/session.py`, `services/content-store/src/content_store/app.py`

**What to build**:
1. Update `create_session_factory()` to return `tuple[AsyncEngine, async_sessionmaker]` matching S4 pattern
2. Update `app.py` lifespan to store the engine and call `await engine.dispose()` on shutdown

**Acceptance criteria**:
- [ ] `create_session_factory` returns `(engine, session_factory)` tuple
- [ ] `app.py` lifespan calls `engine.dispose()` in shutdown
- [ ] Existing tests still pass

---

#### T-R2-2-05: Add tests for CR-1, CR-2, CR-3 fixes

**Type**: test
**depends_on**: [T-R2-2-01, T-R2-2-02, T-R2-2-03]
**blocks**: none
**Target files**: `services/content-ingestion/tests/unit/application/test_doc_id_uniqueness.py`, `services/content-ingestion/tests/unit/api/test_ssrf.py`, `services/content-store/tests/unit/application/use_cases/test_lsh_ordering.py`

**What to build**:

**doc_id uniqueness tests** (≥3):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_each_article_gets_unique_doc_id | Two articles from same source have different doc_ids | unit |
| test_doc_id_is_valid_uuid | doc_id is a valid UUIDv7 string | unit |
| test_source_id_not_used_as_doc_id | doc_id != source_id in payload | unit |

**SSRF DNS tests** (≥4):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_rejects_nip_io_private | `169.254.169.254.nip.io` rejected | unit |
| test_rejects_localhost_hostname | `localhost` rejected | unit |
| test_allows_public_hostname | `example.com` allowed | unit |
| test_rejects_unresolvable_hostname | Non-existent hostname raises error | unit |

**LSH ordering tests** (≥2):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_execute_does_not_call_lsh_index | ProcessArticleUseCase.execute does not call lsh.index | unit |
| test_consumer_calls_lsh_after_commit | Consumer calls lsh.index after session.commit | unit |

Minimum test count: 9

**Acceptance criteria**:
- [ ] All 9 tests pass
- [ ] doc_id test would have caught the `source_id` bug
- [ ] SSRF test would have caught DNS bypass
- [ ] LSH test verifies ordering guarantee

---

### Validation Gate
- [x] `ruff check` + `mypy` clean
- [x] All existing tests pass
- [x] ≥9 new tests pass

### Regression Guardrails
- BP-015: Advisory lock hashing — not affected by these changes
- Custom: SSRF validation must handle both IP literals and hostnames

---

## Wave 3: Contract Tests + Coverage Gaps ✅

**Goal**: Add Avro contract tests for S5, test the consumer process_message, and add a hook/rule ensuring future schema changes include tests.
**Depends on**: Wave 1, Wave 2
**Estimated effort**: 30–45 minutes
**Status**: **DONE** — 2026-03-27 · 208 S5 tests pass · ruff + mypy clean

### Tasks

#### T-R2-3-01: Add Avro contract tests for `content.article.stored.v1`

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/test_avro_schema.py`

**What to build**:
Mirror `services/content-ingestion/tests/unit/test_avro_schema.py` for the S5 output schema. Verify:
1. Schema file exists at `infra/kafka/schemas/content.article.stored.v1.avsc`
2. Schema is valid JSON with `type: record`
3. All required envelope fields present (event_id, event_type, schema_version, occurred_at)
4. All data fields present (doc_id, content_hash, normalized_hash, dedup_result, minio_silver_key, source_type, title, word_count, published_at, is_backfill, correlation_id)
5. `_build_stored_payload()` output fields match schema fields exactly

Minimum test count: 4

**Acceptance criteria**:
- [ ] Tests would catch any drift between `_build_stored_payload()` and the Avro schema
- [ ] Tests verify field-by-field alignment (not just count)

---

#### T-R2-3-02: Add unit tests for `ArticleConsumer.process_message`

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/infrastructure/test_consumer_process.py`

**What to build**:
Unit tests for the consumer's orchestration logic with mocked dependencies:
1. Successful message → session.commit called, no exception
2. Processing failure → session.rollback called, exception re-raised
3. LSH index called AFTER commit (not before) — validates CR-3 fix
4. Each message gets its own session (isolation)

Minimum test count: 4

**Acceptance criteria**:
- [ ] Tests verify commit/rollback lifecycle
- [ ] Tests verify LSH ordering guarantee (post-commit)

---

#### T-R2-3-03: Add `published_at` parsing edge case tests

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/content-store/tests/unit/application/use_cases/test_process_article.py` (extend existing)

**What to build**:
Add tests for the `published_at` parsing that silently suppresses errors:
1. `published_at="invalid-date"` → doc.published_at is None
2. `published_at="2026-03-27T10:00:00Z"` → parses correctly
3. `published_at=None` → doc.published_at is None

Minimum test count: 3

---

### Validation Gate
- [x] `ruff check` + `mypy` clean
- [x] All existing + new tests pass
- [x] ≥11 new tests in this wave (14 new tests)

---

## Wave 4: Compounding — Documentation + Rules + Patterns ✅

**Goal**: Update all compounding documents to prevent recurrence of these issues. This is the most important wave for long-term quality.
**Depends on**: Wave 1, Wave 2, Wave 3
**Estimated effort**: 20–30 minutes
**Status**: **DONE** — 2026-03-27 · docs only, no code changes

### Tasks

#### T-R2-4-01: Add BP-019 — Migration DDL vs ORM mismatch

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/ai-interactions/BUG_PATTERNS.md`

**What to build**:
New bug pattern entry documenting:
- Symptom: `UndefinedColumnError` or `ProgrammingError` at runtime
- Root cause: Migration DDL written separately from ORM, columns diverge
- Fix: Always generate DDL from ORM introspection, or add DDL-vs-ORM alignment tests
- Prevention: DDL alignment tests (as implemented in T-R2-1-05)

---

#### T-R2-4-02: Add BP-020 — DLQ move_to_dead_letter must copy payload

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/ai-interactions/BUG_PATTERNS.md`

**What to build**:
New pattern: when implementing `move_to_dead_letter`, always INSERT a DLQ row (don't just update status). The DLQ table exists for queryability and retry — updating status alone makes events unrecoverable.

---

#### T-R2-4-03: Update REVIEW_CHECKLIST with new checks

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `.claude/review/checklists/REVIEW_CHECKLIST.md`

**What to build**:
Add checks:
- [ ] Migration DDL matches ORM columns exactly (guard BP-008, BP-019)
- [ ] `move_to_dead_letter` inserts DLQ row (not just status update)
- [ ] Avro contract tests exist for every schema a service produces
- [ ] `doc_id` in outbox payloads is a per-document UUIDv7 (not source/aggregate ID)
- [ ] SSRF validation resolves DNS hostnames, not just IP literals
- [ ] LSH/cache writes happen AFTER DB commit, not before

---

#### T-R2-4-04: Update service `.claude-context.md` with pitfalls

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `services/content-ingestion/.claude-context.md`, `services/content-store/.claude-context.md`

**What to build**:
Add pitfalls discovered in QA:
- S4: `doc_id` must be per-article UUIDv7, not `source_id`
- S4: SSRF check must resolve DNS hostnames
- S5: `move_to_dead_letter` must INSERT DLQ row
- S5: LSH index must happen AFTER session.commit
- S5: `outbox_events` DDL must match ORM (add DDL alignment tests for any new service)
- Both: DDL must never use `gen_random_uuid()` defaults — all IDs are app-generated UUIDv7

---

### Validation Gate
- [x] All documentation files updated
- [x] No code changes in this wave (docs only)
- [x] Bug patterns have proper ID, symptom, root cause, prevention sections

---

## Cross-Cutting Concerns

### Contract Changes
| Type | Item | Impact |
|------|------|--------|
| DDL | S5 `outbox_events` rewritten | Existing S5 Alembic deployments need `alembic downgrade` + `upgrade` |
| DDL | S4 `dead_letter_queue` + `payload_json` | New column, nullable, no migration needed for existing rows |
| DDL | S5 `dead_letter_queue` + `payload_json` | New column on S5 DLQ model |
| Code | S4 outbox payload `doc_id` | Now unique per article (was source UUID) |
| Code | S5 LSH index ordering | No external contract change — internal timing |

### Testing Enforcement
To prevent CR-4 recurrence (missing Avro contract tests), Wave 4 updates the review checklist. Additionally, the `/implement` skill's schema guard hook should be extended to check for corresponding test files when `.avsc` files are modified.

---

## Risk Assessment

### Critical Path
Wave 1 (DDL fixes) is the most critical — without it, neither service can operate via Alembic migrations.

### Highest Risk
T-R2-2-02 (SSRF fix) — `socket.getaddrinfo()` can be slow or fail for non-resolving hostnames. Need to handle timeouts gracefully.

### Rollback Strategy
Each wave is independent and leaves the codebase green. DDL fixes (Wave 1) are backward-compatible additions.

---

## Tracking

### Wave Status
| Wave | Status | Tasks Done | Tasks Total |
|------|--------|-----------|-------------|
| W1 | done | 6 | 6 |
| W2 | done | 5 | 5 |
| W3 | done | 3 | 3 |
| W4 | done | 4 | 4 |
