# QA Report: PLAN-0072 (Second Pass — Post-Fix Verification)

**Date**: 2026-05-05 UTC
**Skill**: qa
**Scope**: PLAN-0072 bug fix commits (cfa342e8, 83dbcd1f, 56cf06b8)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL — 1 BLOCKING + 1 CRITICAL remain (resolved in follow-on fix commit)
**Report file**: docs/audits/2026-05-05-qa-plan-0072-pass2-report.md

---

## Executive Summary

Second-pass QA reviewed all three PLAN-0072 bug-fix commits applied after the first QA pass. Five specialist agents examined 21 source files. The test suite baseline is 887 KG unit + 714 NLP unit + 100 architecture tests — all passing. Ruff lint is clean; mypy has one pre-existing error in `fundamentals_refresh.py:108` (unrelated to PLAN-0072).

The most serious finding is **BLOCKING F-DATA-201**: `CREATE INDEX CONCURRENTLY` on a partitioned parent table is not supported on PostgreSQL 16 (the platform's DB version). This migration will fail completely when applied. The second most serious is **CRITICAL F-DS-202**: the BP-390 per-row-commit fix in `ProvisionalEnrichmentWorker` uses a single shared session across all rows in the write loop, leaving the session in an undefined state after any rollback — the fix is structurally incomplete.

Additional significant findings include: four security logging regressions where raw LLM/mention content is still emitted at WARNING/DEBUG level despite F-SEC-003/004/005 fixes; one NameError risk introduced by the F-SEC-004 fix itself; a `force_regen_batch_size` config field that is wired in settings and constructor but never passed at the instantiation site; five concrete repositories that don't inherit their port ABCs; stale Worker 13E documentation (10 min/20 rows vs actual 5 min/500 rows); and 21 test coverage gaps.

The system is not deployment-ready until at minimum the BLOCKING migration is corrected and the CRITICAL session isolation issue is resolved.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 16 | 21 | 0 | 0 | 9 | 9 | 3 |
| Security | 11 | 9 | 0 | 0 | 5 | 3 | 1 |
| Data Platform | 8 | 8 | 1 | 0 | 4 | 2 | 1 |
| Distributed Systems | 7 | 13 | 0 | 1 | 4 | 5 | 3 |
| Architecture | 12 | 13 | 0 | 0 | 3 | 7 | 3 |
| **Total (deduped)** | — | **47** | **1** | **1** | **22** | **18** | **5** |

### Cross-Agent Signals (HIGH Confidence — 2+ agents)

- **F-DATA-206 / F-ARCH-202**: `force_regen_batch_size` config field never passed to `SummaryWorker` in `scheduler.py` — flagged independently by Data Platform Engineer and Architecture Lead
- **F-DS-202 / F-DATA consequence**: BP-390 incomplete fix (shared session in write loop) — confirmed by DS and implicit in Data agent's F-DATA-204 analysis

### Decisions Made (inline for thesis system)

| Finding | Decision | Rationale |
|---------|----------|-----------|
| F-DATA-201 | Non-concurrent index (no CONCURRENTLY) | PG16 doesn't support CONCURRENTLY on partitioned parent; dev system has no live traffic, downtime acceptable |
| F-DS-201 | Remove FOR UPDATE SKIP LOCKED | max_instances=1 already prevents overlapping calls; locking adds false safety illusion |
| F-DS-208 | Set summary_stale=false on LLM failure, re-enable when new evidence arrives | No schema migration required; prevents indefinite retry storm |
| F-DATA-203 | Accept silent coercion to 'other' | Thesis/dev system always starts fresh; no legacy data to corrupt |

### Open Items (Requires Decision)
None — all decisions resolved inline above.

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | 100 | 100 | 0 | 0 | PASS |
| Lint (ruff) | KG+NLP+migrations | — | — | 0 | — | PASS |
| Type Check (mypy) | KG | 135 files | — | 1 (pre-existing) | — | WARN |
| Type Check (mypy) | NLP | 110 files | — | 0 | — | PASS |
| Library Unit | common,contracts,messaging,observability,ml-clients | PASS | — | — | — | PASS |
| Service Unit | knowledge-graph | 887 | 887 | 0 | 42 skip | PASS |
| Service Unit | nlp-pipeline | 714 | 714 | 0 | 46 skip | PASS |
| Service Unit | market-data | 631 | 631 | 0 | 139 skip | PASS |
| Integration | all | — | — | — | — | SKIP (no infra) |
| E2E | all | — | — | — | — | SKIP (no infra) |
| Frontend | N/A | — | — | — | — | N/A |

**Pre-existing mypy error** (unrelated to PLAN-0072): `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py:108` — `jwt.encode` arg-type error for private key union type.

---

## Issues — Full Investigation

## Issue F-DATA-201: CREATE INDEX CONCURRENTLY Fails on PG16 Partitioned Table (BLOCKING)

### Summary
Migration `0025_add_relations_relation_id_index.py` uses `CREATE INDEX CONCURRENTLY` on the `relations` parent table, which is not supported by PostgreSQL 16. The platform runs `timescale/timescaledb:2.17.2-pg16`. This migration will fail with a PostgreSQL error when applied, breaking the revision chain and blocking all subsequent migrations.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Data Platform Engineer

### Root Cause Analysis
- **What**: `op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relations_relation_id ON relations (relation_id)")` in `upgrade()` body, wrapped in `autocommit_block()`.
- **Why**: `CREATE INDEX CONCURRENTLY` was added with correct `autocommit_block()` per Alembic best practices for CONCURRENTLY DDL. However, PG16 does not support CONCURRENTLY on a partitioned parent table — that feature was introduced in PG17.
- **When**: Will fail on every attempt to run `alembic upgrade head` from revision 0024 → 0025 on the current PG16 cluster.
- **Where**: `services/intelligence-migrations/alembic/versions/0025_add_relations_relation_id_index.py:52`.
- **History**: New migration created as part of F-DATA-002 fix for N+1 query on relation_id. No existing bug pattern for this PG version-specific limitation.

### Evidence
```
ERROR: concurrent index creation on partitioned tables is not supported
```
Platform Postgres version: `timescale/timescaledb:2.17.2-pg16` (pg16).
PG17 release notes: "Allow index creation using CONCURRENTLY on a partitioned table."

### Impact
- **Immediate**: Migration 0025 fails; `alembic upgrade head` aborts; `idx_relations_relation_id` never created.
- **Blast radius**: All migrations after 0025 are blocked (PLAN-0074 migrations would be blocked).
- **Data risk**: None — index creation failure is non-destructive.
- **User impact**: Relation-id batch queries in `GetEntityGraphUseCase` fall back to partition-level sequential scans; degraded performance at scale but no correctness impact.

### Solution Options

#### Option A: Drop CONCURRENTLY (Recommended for PG16 dev/thesis system)
**Description**: Replace `CREATE INDEX CONCURRENTLY` with a plain `CREATE INDEX IF NOT EXISTS` inside a standard Alembic transaction (no `autocommit_block()`).
**Changes required**:
- [ ] `0025_add_relations_relation_id_index.py` — remove `autocommit_block()`, use plain `op.create_index("idx_relations_relation_id", "relations", ["relation_id"])`
- [ ] `downgrade()` — use `op.drop_index("idx_relations_relation_id")` (no `autocommit_block()` needed)
**Benefits**: Works on PG16; simpler code; atomic with surrounding transaction.
**Drawbacks**: Blocks `relations` table during index creation (acceptable for dev/thesis with no live traffic).
**Effort**: Low
**Risk**: Low

#### Option B: Per-partition CONCURRENTLY indexes
**Description**: Create 8 CONCURRENTLY indexes on individual partition tables (`relations_p0` through `relations_p7`) inside `autocommit_block()` blocks.
**Effort**: Medium (8× more code)
**Risk**: Medium (complex migration rollback)

### Recommended Option
**Option A** — CONCURRENTLY not needed for a dev/thesis system; PG16 compatibility requires the simpler approach.

### Verification Steps
- [ ] `alembic upgrade head` completes without error
- [ ] `SELECT indexname FROM pg_indexes WHERE tablename = 'relations' AND indexname = 'idx_relations_relation_id'` returns 1 row

---

## Issue F-DS-202: BP-390 Fix Incomplete — Single Shared Session in ProvisionalEnrichmentWorker Write Loop (CRITICAL)

### Summary
The BP-390 per-row-commit fix added `await session.commit()` calls inside the per-row write loop, but the loop still uses a single `async with self._sf() as session:` opened before the loop. After any `session.rollback()` in the except path, the session remains open. If `_apply_retry` raises inside the except handler, the exception propagates out of the entire `async with` block, abandoning all remaining rows. True BP-390 isolation requires one session per row.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Distributed Systems Reviewer

### Root Cause Analysis
- **What**: `provisional_enrichment.py` lines 325–378 — single `async with self._sf() as session:` wraps the entire row iteration loop.
- **Why**: BP-390 was described as "per-row commit" but the fix only added `session.commit()` calls inside the loop without extracting each row into its own session context.
- **When**: Any exception during `_apply_retry` (network error, asyncpg error) causes the exception to escape the `except` block, exit the shared session context (triggering implicit rollback), and abandon all remaining rows in `processing` state.
- **Where**: `infrastructure/workers/provisional_enrichment.py:325-378`.
- **History**: BP-390 (single-session batch rollback pattern).

### Evidence
```python
async with self._sf() as session:   # line 325 — single session opened for all rows
    for row_id, row in enrichment_results.items():
        try:
            await self._persist_enrichment(session, ...)
            await session.commit()       # line 359 — per-row commit (good)
        except Exception as exc:
            await session.rollback()     # line 376 — session stays open
            await self._apply_retry(session, ...)  # can raise → escapes except
            await session.commit()       # line 378 — may never execute
```

### Impact
- **Immediate**: A single `_apply_retry` failure abandons all subsequent rows in the batch, leaving them stuck in `processing` for 30 minutes until the recovery sweep.
- **Blast radius**: Any batch with a flaky DB connection loses all unprocessed rows.
- **Data risk**: No data loss — rows remain in `processing` and are reclaimed. No duplicate writes.
- **User impact**: Slower enrichment throughput; entities stuck in pending state for up to 30 extra minutes per failure.

### Solution
Refactor the write loop to open a fresh session per row:
```python
for row_id, row in enrichment_results.items():
    try:
        async with self._sf() as session:
            await self._persist_enrichment(session, ...)
            await session.commit()
        entity_ids_to_dirty.append(row_id)
    except Exception as exc:
        try:
            async with self._sf() as session:
                await self._apply_retry(session, row_id, retry_count[row_id])
                await session.commit()
        except Exception:
            _log.warning("provisional_enrichment_retry_failed", queue_id=str(row_id), exc_info=True)
```

### Verification Steps
- [ ] Unit test with 3 rows where row 2 fails: verify rows 1 and 3 are committed, row 2 is retried
- [ ] Unit test where `_apply_retry` raises on row 2: verify row 3 is still processed

---

## MAJOR Issues

### F-SEC-202: Raw mention text logged at WARNING in NLP worker (MAJOR)
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:743,854`
**Issue**: Both Ollama and DeepInfra JSON-parse-failure WARNING logs include `surface=mention.mention_text[:80]` — raw news-sourced PII. F-SEC-004 hashed `raw` but left `surface` unmasked.
**Fix**: Replace `surface=mention.mention_text[:80]` with `surface_hash=hashlib.sha256(mention.mention_text.encode()).hexdigest()[:16]` in both warning calls.

### F-SEC-203: Raw mention text logged at WARNING in KG provisional_enrichment (MAJOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py:600`
**Issue**: `_layer2_classify` error handler logs `mention_text=mention_text[:80]` at WARNING — raw news content.
**Fix**: Replace with `mention_text_hash=hashlib.sha256(mention_text.encode()).hexdigest()[:16]`. Add `import hashlib`.

### F-SEC-204: raw_response_preview still in SummaryWorker DEBUG log (MAJOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py:263`
**Issue**: `raw_response_preview=(raw_resp or "")[:200]` at DEBUG — financial news content exposed if LOG_LEVEL=DEBUG in any env.
**Fix**: Remove `raw_response_preview` entirely. Keep `raw_response_length` for size diagnostics.

### F-SEC-205: F-SEC-006 fix incomplete — surface text not JSON-escaped (MAJOR)
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:684`
**Issue**: `user_turn = 'SURFACE: "' + surface[:200] + '"\nCONTEXT: ...'` — raw concatenation breaks on headlines with double quotes.
**Fix**: `user_turn = "SURFACE: " + json.dumps(surface[:200]) + "\nCONTEXT: " + json.dumps(context_text)`.

### F-SEC-208: NameError risk in DeepInfra exception handler (MAJOR)
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:848`
**Issue**: `raw` is assigned after `KeyError`-prone line; exception handler references `raw` → `NameError` on KeyError.
**Fix**: Add `raw: str = ""` before the `try` block in `_phase2_llm_classify_external`.

### F-DATA-204: apply_retry_transition missing status guard (MAJOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py:383`
**Issue**: `WHERE queue_id = :queue_id` with no `AND status = 'processing'` — can reopen already-resolved rows.
**Fix**: Add `AND status = 'processing'` to the WHERE clause.

### F-DATA-205: mark_processed missing CAST (MAJOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py:365`
**Issue**: `WHERE raw_id = ANY(:raw_ids)` — missing `CAST(:raw_ids AS uuid[])`, inconsistent with F-DATA-004 fix.
**Fix**: Change to `WHERE raw_id = ANY(CAST(:raw_ids AS uuid[]))`.

### F-DATA-206 / F-ARCH-202: force_regen_batch_size not wired in scheduler (MAJOR — HIGH confidence)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py:259`
**Issue**: `SummaryWorker(session_factory, llm_client)` — third argument never passed. Config field `summary_worker_force_regen_batch_size` silently ignored.
**Fix**: `SummaryWorker(session_factory=session_factory, llm_client=llm_client, force_regen_batch_size=settings.summary_worker_force_regen_batch_size)`.

### F-DS-201: FOR UPDATE SKIP LOCKED released before Phase 2 processing (MAJOR — Decision: Remove it)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`
**Issue**: Phase 1 session exits without commit → implicit rollback → `FOR UPDATE SKIP LOCKED` locks released immediately.
**Fix (decided)**: Remove `FOR UPDATE SKIP LOCKED` from `fetch_stale_summary`. Document that `max_instances=1` APScheduler coalescing prevents concurrent calls within the same process.

### F-DS-203: _apply_retry can escape except block (MAJOR)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py:367`
**Issue**: Post-rollback `_apply_retry` call has no nested try/except — failure abandons all remaining rows.
**Fix**: Addressed by F-DS-202 per-row-session refactor (each row's except handler is independent).

### F-DS-208: SummaryWorker LLM failures retry indefinitely (MAJOR — Decision: fail-and-re-trigger)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py:199`
**Issue**: On LLM `None` return, `continue` without clearing `summary_stale=true` → indefinite retry every 60 min.
**Fix (decided)**: Call `rel_repo.mark_summary_updated(relation_id)` even on LLM failure (clearing the stale flag). The flag will be re-set to `true` when new evidence arrives via the hot path. Add a `summary_last_failed_at` log metric.

### F-ARCH-203: 5 concrete repos don't inherit port ABCs (MAJOR)
**Files**: `canonical_entity.py`, `relation.py`, `contradiction_repository.py`, `outbox_repository.py`, `relation_type_registry_repository.py`
**Issue**: None of these inherit from their corresponding port ABCs — mypy requires `# type: ignore[arg-type]` suppressions at all call sites.
**Fix**: Add the port ABC as parent class to each concrete class.

### F-ARCH-205/206: Worker 13E docs stale — 10min/20 vs actual 5min/500 (MAJOR)
**Files**: `.claude-context.md:98`, `docs/services/knowledge-graph.md`
**Fix**: Update both to `5 min | 500`.

### F-ARCH-207: ARCH-003 and force_regen undocumented in service docs (MAJOR)
**File**: `docs/services/knowledge-graph.md:94`
**Fix**: Add ARCH-003 session pattern note and `KNOWLEDGE_GRAPH_SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE` to ENV vars table.

---

## MINOR Issues (summary)

| Finding | File | Issue | Fix Approach |
|---------|------|-------|-------------|
| F-QA-201 | test_provisional_enrichment.py | `aclose()` has zero test coverage | Add TestAcloseLifecycle with 2 cases |
| F-QA-202 | test_provisional_enrichment.py | Empty `noise_api_key` path not tested | Add test with `noise_api_key=""` |
| F-QA-203 | test_provisional_enrichment.py | asyncio.gather exception path (fail-open) untested | Add test with RuntimeError from gather |
| F-QA-204 | test_provisional_enrichment.py | Noise counter metrics not asserted | Patch + assert `.inc()` per noise item |
| F-QA-205 | test_summary_worker.py | LLM returns None path not tested | Add test with `llm.extract=AsyncMock(return_value=None)` |
| F-QA-206 | test_graph_query.py | Graceful-degradation paths untested | Add tests with `side_effect=RuntimeError` |
| F-QA-207 | test_unresolved_resolution_worker.py | `run_once` phase1 auto-resolve path missing | Add end-to-end test |
| F-QA-208 | test_unresolved_resolution_worker.py | DeepInfra usage_logger not tested | Add test with usage_logger mock |
| F-QA-210 | test_summary_worker.py | Empty-string summary edge case not tested | Add test with `result={"summary": ""}` |
| F-QA-212 | test_summary_worker.py | Session discipline ordering not verified | Add call-ordering tracker for session_closed before llm_called |
| F-SEC-206 | config.py (KG + NLP) | API keys typed as `str` not `SecretStr` | Change to SecretStr with `.get_secret_value()` |
| F-SEC-207 | dependencies.py | No startup warning when admin_token empty | Add model_validator warning |
| F-DATA-203 | migration 0021 | Silent coercion to 'other' has no diagnostic | (Decision: Accept for dev system) |
| F-ARCH-201 | ports/relation_summary_repository.py | Write-side methods missing from port | Add get_current, insert_new, update_embedding as abstract |
| F-ARCH-204 | api/routes.py | Private `_get_cypher_neighborhood_uc` imported and called directly | Expose as Depends() injection |
| F-ARCH-208 | unresolved_resolution_worker.py | Classification prompt should be in libs/prompts | Extract to entity_classification.py |
| F-ARCH-209 | unresolved_resolution_worker.py | context_sentence discarded at enqueue step | Thread context_sentence into _enqueue_for_enrichment |
| F-ARCH-211 | .claude-context.md | Layer 2 noise classifier direct-HTTP path not documented | Add LLM Chain note |
| F-DS-204 | scheduler.py | aclose() exception not suppressed in stop() | Wrap with contextlib.suppress |
| F-DS-206 | graph_query.py | Warning logs missing exc_info=True | Add exc_info=True to both warns |
| F-DATA-207 | relation_summary.py | Empty-list entity_ids guard fragile | Add explicit None normalization |

---

## NITs

| Finding | File | Issue |
|---------|------|-------|
| F-QA-220 | test_unresolved_resolution_worker.py | Dead code `if False:` block in `_make_nlp_session_factory` |
| F-DATA-202 | migration 0025 | Comment incorrectly says "non-partitioned global index" |
| F-DATA-208 | migration 0025 | `autocommit_block()` unnecessary in downgrade() |
| F-DS-205 | provisional_enrichment.py | Two identical semaphore instances (Layer 2 + Phase 2) — use shared instance |
| F-ARCH-213 | summary.py | `self._sf` should be `self._session_factory` for grep-ability |

---

## Recommendations

1. **Fix F-DATA-201 IMMEDIATELY** — the migration will fail in production. Replace CONCURRENTLY with plain `CREATE INDEX IF NOT EXISTS`.
2. **Fix F-DS-202** — per-row session isolation in ProvisionalEnrichmentWorker write loop (one session per row, not shared).
3. **Apply all MAJOR security logging fixes** (F-SEC-202–205, F-SEC-208) — these are regressions introduced by the F-SEC-004 fix.
4. **Wire F-DATA-206 / F-ARCH-202** — one-line fix; the config feature is silently inoperative.
5. **Fix F-DATA-205** — missing CAST in `mark_processed`; will fail under asyncpg.
6. **Fix F-DATA-204** — `apply_retry_transition` can reopen resolved rows.
7. **Apply F-DS-208** — clear `summary_stale` on LLM failure to prevent retry storms.
8. **Fix F-DS-201** — remove FOR UPDATE SKIP LOCKED (now that the fix approach is decided).
9. **Fix all 5 repo port inheritance gaps** (F-ARCH-203) — eliminates all `# type: ignore[arg-type]`.
10. **Update docs** (F-ARCH-205/206/207, F-ARCH-211) — Worker 13E has wrong numbers.
