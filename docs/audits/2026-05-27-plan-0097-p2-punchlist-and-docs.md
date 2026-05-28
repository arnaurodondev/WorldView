# PLAN-0097 — P2 Punch List & Doc Recommendations Consolidation

**Date:** 2026-05-27
**Source:** `2026-05-26-iter-9-final-qa-code-review.md` (6 P2 items) + `2026-05-26-iter-9-phase-d-adversarial-qa.md` (doc gaps)
**Scope:** 10 actionable items, 5 recommended commits, estimated 40–60 hrs total implementation
**Target:** PLAN-0097 wave allocation (suggested: 2–3 per wave)

---

## Overview

This document consolidates **6 code-level P2 risks** from the final adversarial code review (iter-9) and **4 documentation/rule recommendations** from the parallel phase-D QA pass. Each item includes: (a) one-line summary, (b) affected file:line, (c) exact change, (d) regression test, (e) commit scope, and (f) time estimate.

**Bundling recommendation:**
- **Commit 1 (market-data + test):** Items 2 + 5 (30 min)
- **Commit 2 (nlp-pipeline):** Item 1 (20 min)
- **Commit 3 (migration safety):** Item 3 (15 min)
- **Commit 4 (knowledge-graph):** Item 4 (25 min)
- **Commit 5 (rag-chat + cache):** Item 6 (45 min)
- **Commit 6 (docs):** Items 7–10 (35 min)

---

## P2 Code Items (1–6)

### 1. Sentinel × Tenant SQL Filter Visibility Inversion

| Field | Value |
|-------|-------|
| **Summary** | `news_query.py:139` `em.tenant_id IS NULL OR em.tenant_id = :tenant_id` silently inverts article visibility post-W4 sentinel fix: legacy (NULL) articles now visible *only* to PUBLIC_TENANT_ID (anonymous), invisible to real tenants. |
| **File:Line** | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:139` |
| **Change** | Update the SQL filter to include both the tenant_id and the PUBLIC_TENANT_ID sentinel:<br/><br/>`if tenant_id != PUBLIC_TENANT_ID:`<br/>`    stmt = stmt.where((em.tenant_id == tenant_id) \| (em.tenant_id == PUBLIC_TENANT_ID))`<br/>`else:`<br/>`    stmt = stmt.where((em.tenant_id.is_(None)) \| (em.tenant_id == PUBLIC_TENANT_ID))` |
| **Test** | Seed: (a) article with `tenant_id=NULL` (legacy), (b) article with `tenant_id=PUBLIC_TENANT_ID` (sentinel), (c) article with `tenant_id=real_tenant_id` (real). Query with both `real_tenant_id` and `PUBLIC_TENANT_ID` callers; assert (a) & (b) visible to both, (c) visible only to real_tenant_id. |
| **Commit Scope** | `nlp-pipeline` only. Standalone commit. File: `news_query.py`. |
| **Est. Time** | 20 min (includes test) |

---

### 2. Tautological Period-Type Tests → Integration Test

| Field | Value |
|-------|-------|
| **Summary** | `test_fundamentals_query_defaults.py` greps compiled SQL strings for `"QUARTERLY"` substring; proves filter is *present* in SQL, not that it *excludes* ANNUAL rows. String-inspection tests cannot detect if filter becomes tautological (`period_type IS NOT NULL OR period_type = :p`) in a refactor. |
| **File:Line** | `services/market-data/tests/unit/test_fundamentals_query_defaults.py:57–122` |
| **Change** | Add an integration test (or promote unit test to async fixture + DB seed pattern):<br/><br/>`async def test_period_type_quarterly_excludes_annual():`<br/>`    # Seed: QUARTERLY $50B revenue + ANNUAL $200B at same period_end`<br/>`    # Assert: returned revenue == $50B (quarterly shadows annual)`<br/>Keep existing string-inspection tests for regression coverage. |
| **Test** | (a) Seed both periodicities at same `period_end`, (b) Query income_statement without explicit `period_type`, verify default QUARTERLY is applied, (c) Assert returned revenue == quarterly value, NOT annual. (d) Reverse: seed ANNUAL-only, verify the returned value. |
| **Commit Scope** | `market-data/tests/unit/` + `market-data/tests/integration/` (new). Single commit. |
| **Est. Time** | 30 min (fixture setup + seed + assertions) |

---

### 3. Migration 019 Partial-Rerun Idempotency

| Field | Value |
|-------|-------|
| **Summary** | `019_composite_fundamentals_indexes.py` uses `op.create_index()` (fails if index exists); if migration fails halfway, re-running fails on first already-created index, leaving DB in inconsistent state. Must use `IF NOT EXISTS` for safe partial re-runs. |
| **File:Line** | `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py:106–114` |
| **Change** | Replace each `op.create_index(...)` with `op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON ...")`. Preserve the same index name + column order as the original calls. Example:<br/><br/>`# Before:`<br/>`op.create_index("ix_earnings_history_instrument_period", "earnings_history", ["instrument_id", "period_end_date"])`<br/><br/>`# After:`<br/>`op.execute("CREATE INDEX IF NOT EXISTS ix_earnings_history_instrument_period ON earnings_history(instrument_id, period_end_date ASC)")`<br/>(Repeat for all 18 indexes.) |
| **Test** | (a) Apply migration 019 normally (baseline), (b) Drop one index manually, (c) Reapply migration 019, verify no error and all indexes present. (Alternative: simulate Alembic partial failure by aborting the transaction and retry.) |
| **Commit Scope** | `market-data/alembic/` only. Standalone migration-only commit. |
| **Est. Time** | 15 min (textual edit + test) |

---

### 4. AGE Session Invalidation Before DML

| Field | Value |
|-------|-------|
| **Summary** | `age_sync_worker.py:516–525` calls `session.connection().invalidate()` to flush plpgsql catalog cache post-schema-changes. However, invalidating without explicit rollback first leaves transactional state ambiguous; subsequent implicit BEGIN may fail with `InvalidRequestError`. |
| **File:Line** | `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:516–525` |
| **Change** | Add explicit `await session.rollback()` immediately before `invalidate()`:<br/><br/>`async def _invalidate_session_connection(session: AsyncSession) -> None:`<br/>`    try:`<br/>`        await session.rollback()  # ← NEW: explicit state reset`<br/>`        await session.connection().invalidate()`<br/>`        log.warning("session invalidated post-AGE schema changes")`<br/>`    except Exception as e:`<br/>`        log.warning(f"invalidate failed: {e}")` |
| **Test** | Add a unit test that mocks `AsyncSession`, calls `_invalidate_session_connection`, and asserts both `rollback()` and `invalidate()` are called in sequence (use mock call order verification). Integration test: none (AGE requires containerized Postgres + AGE extension; unit mock sufficient). |
| **Commit Scope** | `knowledge-graph/src/` only. Standalone commit. |
| **Est. Time** | 25 min (code + unit test) |

---

### 5. Batch Endpoint Exception Reason Sanitization

| Field | Value |
|-------|-------|
| **Summary** | `fundamentals.py:205` batch endpoint returns `reason=str(exc)` for unexpected exceptions (e.g., SQL syntax errors leak table/column names, malformed JSON leaks structure). These strings surface in LLM output and user chat. Must redact to safe enum. |
| **File:Line** | `services/market-data/src/market_data/api/routers/fundamentals.py:177–213` (batch handler); specifically line 205 exception reason |
| **Change** | Update exception handling:<br/><br/>`except InstrumentNotFoundError as e:`<br/>`    reason = "instrument_not_found"`<br/>`except Exception as e:`<br/>`    # Log full exception server-side for debugging`<br/>`    log.exception(f"batch fundamentals error: {e}")`<br/>`    # Return safe reason code to client`<br/>`    reason = "internal_error"  # ← Sanitized`<br/>`return {`<br/>`    "status": "error",`<br/>`    "reason": reason,`<br/>`    # Optionally: "error_id": uuid4() for server-side lookup`<br/>`}` |
| **Test** | (a) Mock a non-`InstrumentNotFoundError` exception (e.g., `ValueError`), call batch endpoint, assert response `reason="internal_error"` (not `str(exc)`). (b) Verify `log.exception()` was called with the full traceback. |
| **Commit Scope** | `market-data/src/market_data/api/routers/fundamentals.py` (same commit as item 2, testing). |
| **Est. Time** | 20 min (with test from item 2; combined time: 30 min for both) |

---

### 6. Classifier-Before-Cache Poisoned-Cache Mitigation

| Field | Value |
|-------|-------|
| **Summary** | W4's reorder (check cache *before* validate_input) assumes all pre-existing cache entries passed classifier on first write. If classifier was ever bypassed (feature flag, dev override), poisoned entries are permanent. Must flush cache at deploy + document precondition. |
| **File:Line** | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:456–475` + `docs/BUG_PATTERNS.md` |
| **Change** | **(a) Deployment-time flush** — Add to deployment entrypoint (or as first-run task in scheduler):<br/><br/>`# rag-chat startup (before first request)`<br/>`try:`<br/>`    valkey_client.connection_pool.disconnect()`<br/>`    for cursor in valkey_client.scan_iter(match="rag:completion:*", count=100):`<br/>`        valkey_client.delete(cursor)`<br/>`    log.info("rag:completion:* cache flushed on deploy")`<br/>`except Exception as e:`<br/>`    log.warning(f"cache flush failed (non-blocking): {e}")`<br/><br/>**(b) BP-572 documentation update** — Add explicit precondition:<br/>"This reorder is safe **only if** every prior cache-write went through the classifier. If the classifier was ever bypassed (feature flag, dev override, skipped validation), poisoned entries from before this commit will surface. Mitigation: deploy-time `rag:completion:*` flush above." |
| **Test** | Unit test for flush logic (mock valkey, assert `SCAN` + `DEL`). Integration test: seed a poisoned cache entry, flush, verify it's gone. |
| **Commit Scope** | `rag-chat/src/` + `docs/BUG_PATTERNS.md`. Single commit. |
| **Est. Time** | 45 min (flush logic + tests + doc update) |

---

## Documentation Items (7–10)

### 7. R35 — Fundamentals Period-Type Contract

| Field | Value |
|-------|-------|
| **Summary** | New rule: all fundamentals queries must specify `period_type` explicitly OR accept safe repository-layer defaults (QUARTERLY for income_statement; no default for balance_sheet/cash_flow). Mixed-periodicity row leakage = silent fabrication risk. |
| **Location** | `RULES.md` after R34 (insert new section) |
| **Text** | **R35** — "All fundamentals queries MUST specify `period_type` explicitly OR rely on documented repository-layer defaults (QUARTERLY for income_statement, balance_sheet, cash_flow). Balance-sheet and cash-flow queries without explicit `period_type` will receive mixed QUARTERLY/ANNUAL rows. Callers: use cases must pass `period_type=PeriodType.QUARTERLY` or call a repository method that enforces it. Reviewers: grep for `find_by_section(...)` calls without `period_type=` kwarg." |
| **Commit Scope** | `RULES.md` update (same commit as item 8). |
| **Est. Time** | 10 min |

---

### 8. R36 — AGE DDL → Session Invalidation Pattern

| Field | Value |
|-------|-------|
| **Summary** | New rule: after AGE DDL (create_vlabel/elabel), call `await session.connection().invalidate()` before DML (MERGE/MATCH). plpgsql schema cache survives session.commit(); stale cache can cause "undefined relationship" errors. |
| **Location** | `RULES.md` after R35 |
| **Text** | **R36** — "After AGE DDL (CREATE VLABEL / CREATE ELABEL / ALTER VLABEL), call `await session.connection().invalidate()` before issuing DML (MERGE/MATCH). PostgreSQL plpgsql catalogs are cached per backend connection; `session.commit()` does not flush this cache. Without invalidate, subsequent DML will use stale schema and raise `ERROR: undefined virtual relationship`. Pattern: (1) execute DDL, (2) `await session.commit()`, (3) `await session.connection().invalidate()`, (4) execute DML. See `knowledge_graph/workers/age_sync_worker.py` for implementation." |
| **Commit Scope** | `RULES.md` only (combined with R35). Single commit. |
| **Est. Time** | 10 min |

---

### 9. `docs/services/market-data.md` — Period-Type Contract Subsection

| Field | Value |
|-------|-------|
| **Summary** | Add dedicated subsection documenting the period_type filter contract, default behavior, and landmine cases (balance-sheet/cash-flow queries). |
| **Location** | `docs/services/market-data.md`, new subsection "## Period-Type Contract" (after "## Entities & Data Model" or similar) |
| **Text** | Approximately 400–500 words covering:<br/>- Why: EODHD ingests both QUARTERLY and ANNUAL financials for the same instruments; mixing them = silent revenue/EPS fabrication<br/>- Default behavior: income_statement defaults to QUARTERLY; balance_sheet/cash_flow have no default (must be explicit)<br/>- Callers: use cases must pass `period_type=PeriodType.QUARTERLY` or other value<br/>- Defensive layers: repository `find_by_section()` enforces default; use cases override if needed<br/>- Pitfall: if balance-sheet/cash-flow are ever queried directly (e.g., analyst briefing tool), they will leak mixed rows unless filtered<br/>- Tests: regression test example seeding both periodicities, asserting only one is returned<br/>Cross-reference: R35, BP-123 |
| **Commit Scope** | `docs/services/market-data.md` only. Standalone docs commit. |
| **Est. Time** | 25 min |

---

### 10. `docs/MASTER_PLAN.md` — Cross-Refs to New Contracts

| Field | Value |
|-------|-------|
| **Summary** | Add one-line pointers in MASTER_PLAN.md to three new architectural contracts: (a) S3 period-type filter, (b) S3 batch endpoint safety, (c) S7 AGE bootstrap pattern. Helps future engineers discover these contracts without reading service docs. |
| **Location** | `docs/MASTER_PLAN.md` in the **Services** section (where each S1–S10 is summarized) or in a new **"Critical Data/Safety Contracts"** subsection |
| **Text** | Suggested additions:<br/><br/>**§ Market Data (S3) — Critical Contracts**<br/>- "Period-Type Filter": See `docs/services/market-data.md:Period-Type Contract`. All fundamentals queries default to QUARTERLY (income_statement) or require explicit `period_type` (balance_sheet, cash_flow) to avoid mixing periodicities.<br/>- "Batch Fundamentals Endpoint": `/v1/fundamentals/batch` sanitizes exception reasons to prevent leaking internal SQL errors to downstream LLM output. See `PLAN-0097` item #5.<br/><br/>**§ Knowledge Graph (S7) — Critical Patterns**<br/>- "AGE DDL → Session Invalidation": After creating/altering AGE virtual labels, call `await session.connection().invalidate()` before DML. See R36 + `age_sync_worker.py`.<br/>(Alternatively, add one-liners in existing summaries.) |
| **Commit Scope** | `docs/MASTER_PLAN.md` only. Combined with item 9 in one docs commit. |
| **Est. Time** | 10 min |

---

## Summary Table

| ID | Summary | File:Line | Estimated Time | Commit Scope |
|----|---------|-----------|-----------------|--------------|
| 1 | Sentinel × tenant SQL visibility | nlp-pipeline/.../news_query.py:139 | 20 min | nlp-pipeline |
| 2 | Period-type integration test | market-data/tests/.../test_fundamentals_query_defaults.py:57–122 | 30 min | market-data/tests |
| 3 | Migration 019 `IF NOT EXISTS` | market-data/alembic/.../019_*.py:106–114 | 15 min | market-data/alembic |
| 4 | AGE invalidate + rollback | knowledge-graph/.../age_sync_worker.py:516–525 | 25 min | knowledge-graph |
| 5 | Batch endpoint reason sanitization | market-data/.../routers/fundamentals.py:205 | 20 min (combined w/ 2) | market-data |
| 6 | Classifier-before-cache flush | rag-chat/.../chat_orchestrator.py + docs/BUG_PATTERNS.md | 45 min | rag-chat + docs |
| 7 | R35 fundamentals contract | RULES.md (new rule) | 10 min (combined w/ 8) | docs |
| 8 | R36 AGE DDL pattern | RULES.md (new rule) | 10 min | docs |
| 9 | Market-data period-type docs | docs/services/market-data.md | 25 min (combined w/ 10) | docs |
| 10 | MASTER_PLAN.md cross-refs | docs/MASTER_PLAN.md | 10 min | docs |
| **TOTAL** | — | — | **170–190 min** (2.8–3.2 hrs) | 6 commits |

---

## Recommended Wave Allocation (PLAN-0097)

| Wave | Items | Services | Est. Time | Rationale |
|------|-------|----------|-----------|-----------|
| W1 | 1, 4 | nlp-pipeline, knowledge-graph | 45 min | Cross-service infrastructure (SQL visibility, AGE patterns); low risk, high clarity |
| W2 | 2, 3, 5 | market-data | 65 min | Cluster data integrity fixes (period-type test, migration safety, reason sanitization); medium risk, high impact |
| W3 | 6 | rag-chat, docs | 45 min | Cache safety + first observability pattern (BP-572 precondition); medium risk, high ROI |
| W4 | 7–10 | docs | 35 min | Rules + service docs; low risk, high reference value; can be deferred or fast-tracked |

**Alternative (aggressive):** Combine W1+W2 for data-integrity focus (110 min), defer W3+W4 to month-end doc pass.

---

## Notes

- **R35/R36 adoption:** Once merged, reference in code reviews and `.claude-context.md` for market-data and knowledge-graph services.
- **Deployment preconditions:** Item 6 (cache flush) must run on first rag-chat startup post-merge to guarantee consistency.
- **Rollback safety:** All changes are additive or constraints-tightening; rollback is safe and low-risk.
- **Cross-PLAN interaction:** If PLAN-0098 (docs pass) is active, items 7–10 can be merged into that wave instead.
