# PLAN-0097 Phase-D Adversarial Code Review

**Date**: 2026-05-27
**Reviewer**: read-only sub-agent (Claude Opus 4.7)
**Scope**: 13 PLAN-0097 commits on `feat/plan-0089-wi-a` (W1 + W2 + W3 + W4)
**Verdict**: **CONDITIONAL PASS** — ship the wave, but one **P1 regression-class miss** (R40 only half-applied) and three **P2** items belong on a PLAN-0098 follow-up. No P0s found.

Commits reviewed: `b422126d`, `d83bb127`, `8ada0c77` (W1); `fb5631c3`, `e7dfa8b6` (W2); `a960d8f7`, `cfe7c01d`, `d2689b79` (W3); `8c3a9249`, `593b3344`, `1a8077ae`, `8906009f`, `88bef8bc` (W4). Note: `c60c7810` carried `feat(plan-0089-wi-a): T-IA-05+07` and is **NOT** a PLAN-0097 commit despite being in the listed range — excluded.

---

## 1. Hidden regression risk — test suites

Ran full unit suite per touched service:

| Service              | Result                                    |
|----------------------|-------------------------------------------|
| rag-chat             | 1274 passed, 14 skipped (live-gated)      |
| market-data          | 730 passed                                 |
| nlp-pipeline         | 1014 passed, 3 xfailed                    |
| knowledge-graph      | 1411 passed, 6 skipped, 2 xfailed         |

No newly-failing tests. **PASS.**

## 2. Security review

### 2.1 `DEBUG_SKIP_CLASSIFIER` env gate (`llm_injection_classifier.py:169-177`)

The gate reads `APP_ENV` with default `"development"`. If a production deploy ships **without** `APP_ENV=production`, the classifier-skip is bypassable by an operator setting `DEBUG_SKIP_CLASSIFIER=1`. This is correctly mitigated by **BP-567 / `assert_app_env_or_die`**, which is invoked in `app.py` lifespan and refuses to boot unless `APP_ENV in {"production","dev","test","staging"}`. The full chain is sound: no-`APP_ENV` boot fails before the classifier ever runs, so the default `"development"` is unreachable in prod.

**Risk**: low. Recommended P2: tighten the test name `test_production_app_env_ignores_skip_flag` to also assert behaviour when `APP_ENV` is unset (currently the test only parameterises explicit values).

### 2.2 `RAG_CACHE_DEPLOY_TOKEN` comparison (`app.py:815`)

Comparison is `previous == deploy_token` — plain `==`. Not constant-time. **This is fine**: the token is not a credential; it is an operator-bumped string used solely for cache-bust ordering. Even if leaked it grants nothing. No change required.

### 2.3 PUBLIC_TENANT_ID sentinel — **P1 finding**

W4 T-W4-01 added the third OR-leg only to `news_query._ENTITY_ARTICLES_SQL` (line 149-151). A grep `grep -rn "tenant_id IS NULL" services/` reveals **identical inverse-visibility patterns at 8 other sites** in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` lines **172, 174, 261, 263, 312, 318, 426, 428**:

```python
where_clauses.append("(c.tenant_id IS NULL OR c.tenant_id = CAST(:tenant_id_str AS UUID))")
```

Each of these is a violation of the newly-codified **R40**. Any chunk/section row populated with `PUBLIC_TENANT_ID` (from a PLAN-0096 W4 fallback) is invisible to authenticated callers using the chunk-search retrieval path — exactly the bug R40 was written to prevent. The W4 commit message and T-W4-01 description only fix `news_query`. Either the audit missed `chunk_search.py`, or the scope was implicitly narrowed without documentation.

**Severity**: P1. **Recommended fix**: PLAN-0098 W1 — add the third OR-leg to all 8 sites in `chunk_search.py` and extend `test_tenant_id_chunk_isolation.py` to assert the PUBLIC_TENANT_ID row class. The existing R40 unit test in `test_news_query_tenant_filter.py` is insufficient because it only pins the news_query path.

## 3. Migration safety

### 3.1 022 ANALYZE atomicity

`022_analyze_fundamentals_tables.py:93-98` runs `with op.get_context().autocommit_block():` then iterates 18 tables issuing one `op.execute(f"ANALYZE {table}")` each. Because the block is **autocommit**, every statement commits independently. If statement N fails (e.g. missing table), statements 1..N-1 are already committed and statements N+1..18 are skipped. Alembic will record the revision as failed and re-running `alembic upgrade head` will re-execute all 18 ANALYZEs (ANALYZE is idempotent — safe). **Acceptable.** Inline comment line 96 should call this out; currently it doesn't.

### 3.2 023 idempotency

`023_composite_fundamentals_indexes_idempotent.py:83-84` emits `CREATE INDEX IF NOT EXISTS "ix_{table}_instrument_period" ON "{table}" (instrument_id, period_end_date ASC)` for all 18 tables. Every statement is IF NOT EXISTS. Downgrade is a documented no-op. **Idempotent — PASS.**

### 3.3 down_revision chaining

`022.down_revision = "021"` ✓, `023.down_revision = "022"` ✓. Linear, no branch. **PASS.**

### 3.4 Plan ↔ docs drift on ANALYZE table count

Commit msgs and `docs/services/market-data.md:1019` say "18 tables". Plan TRACKING.md row says "14 tables" (one place). Migration 022 list is 18. **Plan TRACKING.md is wrong — P2 doc drift.**

## 4. Architecture / hexagonal

### 4.1 `scripts/refresh_fundamentals.py`

Imports only `argparse`, `asyncio`, `os`, `sys`, `httpx`. It calls the **HTTP API** (`POST /api/v1/ingest/trigger`), not the application/use-case layer. **Correct** — ops scripts must not reach across service boundaries through Python imports (would violate R9/R12); HTTP is the right edge.

### 4.2 Deploy-token flush blocking startup

`app.py:120` awaits `_maybe_flush_completion_cache(...)` inside lifespan. The function is bounded: SCAN is non-blocking, batched DEL is O(N/batch_size) with batch_size=500. For a typical < 10k key cache it returns in < 100 ms. **All Valkey errors are caught and swallowed** (lines 807, 826, 838) — a Valkey outage logs WARNING and returns; startup never blocks. **PASS.**

**Caveat**: a non-degraded but slow Valkey + a multi-million-key keyspace could theoretically hold startup for several seconds. Not a real concern for the rag-chat completion cache (capped by TTL + low write rate) but worth a follow-up `asyncio.wait_for` wrapper. **P2.**

## 5. Test quality

### 5.1 W1 periodicity test (`test_get_fundamentals_history_periodicity.py`)

The fake `find_by_section` (line 78 onward) **honours the `period_type` kwarg** — it filters its returned rows by the requested PeriodType, exactly as the real `query_fundamentals` repo does. The QUARTERLY-wins assertion ($10B not $40B) therefore validates the use case's filter argument is forwarded. **Not a tautology — PASS.**

### 5.2 W2 benign-relationship tests — **partial-tautology concern**

`test_llm_injection_classifier_benign_relationships.py:97-116` mocks the LLM call to return SAFE then asserts `classify()` returns False. This proves the **plumbing** (response parsing → boolean) works for SAFE responses; it does **not** prove the classifier prompt actually classifies "How is OpenAI connected to Microsoft?" as SAFE. That assurance lives only in the live-gated suite (line 148), which is skipped in CI (confirmed: 14 skipped in the run).

The audit's own framing acknowledges this — the regression catches model drift only when `INTEGRATION_TEST=1 + RAG_CHAT_DEEPINFRA_API_KEY` are set. **Severity P2** — recommended follow-up: schedule a nightly job that runs the live tier; today, a future prompt-text regression that re-flags Q8 would not be caught by CI.

### 5.3 W3 parallel-resolve timing test

`test_fundamentals_batch_resolves_tickers_in_parallel` (line 357) sleeps 100 ms × 5 then asserts `elapsed < 0.3s`. Headroom = 3× over the parallel ideal. On a heavily-loaded CI runner (e.g. shared GH-Actions VM), event-loop scheduling can introduce 50-100 ms of jitter — this test is **flaky-prone**, especially during full-suite runs that warm up many other event loops in parallel. **Severity P2** — recommended fix: bump threshold to 0.4 s OR replace the wall-clock assertion with a call-order assertion (assert all 5 `lookup_uc.execute` invocations were entered before any returned, using a barrier).

### 5.4 W3 typed-reason-codes test

`test_fundamentals_batch_reason_uses_typed_codes_not_raw_exception_text` plants ONE sentinel substring and asserts it never appears in the response body. **Not comprehensive** but sufficient for the defense-in-depth claim: the production path now goes through `_classify(exc)` which has only four return values, so a single-sentinel test pins the contract. A fuzz harness over exception messages would be overkill; current coverage is acceptable.

## 6. Compounding accuracy

### 6.1 BP numbers

Verified BP-577 / 578 / 579 / 580 / 581 / 582 all present in `docs/BUG_PATTERNS.md`. Previous max was BP-576 — **no collisions**. Audit's note that BP-562/563 were "already taken" is correct (they were assigned in PLAN-0093 ITER-4). **PASS.**

### 6.2 RULES R35/R36 → R40/R41

`RULES.md` lines 454 (R40) + 480 (R41) carry the explicit renumbering note: "Pre-existing code commits that reference this rule by its plan name (R35/R36) refer to this same rule — R40/R41 is the canonical RULES.md number." Summary table lines 557-558 list both. **PASS.**

**Drift**: code comments in `age_sync_worker.py:515, 534` still say `R36`. Acceptable (per the renumbering note) but a follow-up cleanup that swaps `R36` → `R41` would tighten search-ability. **P2 cosmetic.**

### 6.3 TRACKING.md row

`docs/plans/TRACKING.md:40` reads "complete | 4/4" ✓.

## 7. Race / async issues

### 7.1 `asyncio.gather(*tasks, return_exceptions=True)`

Both Phase 1 (`resolutions`, line 209) and Phase 2 (`fetch_results`, line 231) use `return_exceptions=True`, so a single raised exception does **not** cancel sibling tasks. All five tickers' lookups run to completion; failures are classified per-ticker. **Correct.**

### 7.2 Deploy-token flush race between two simultaneously-starting app instances

If two rag-chat replicas boot concurrently after a token bump, both will:
1. read `previous` from Valkey → both see the old value
2. both call `delete_pattern(...)`
3. both `SET` the new token (last-write-wins, both are identical)

Result: cache is double-flushed (harmless), token is correctly persisted. **No race hazard.** Worst case is one redundant SCAN — acceptable.

## 8. Cross-commit interactions

### 8.1 W1 rag-chat `_format_fundamentals_table` (`market.py:801-842`) vs W3 batch tool description

W1 added the Periodicity column to the table renderer. W3 touched the **tool description string** (separate file: `chat_router` tool catalog). They edit different surfaces — **no collision.**

### 8.2 W2 grader vs W3 typed-reason-codes

W3 changed the per-ticker `reason` field from `str(exc)` to one of four typed codes. The grader (`tests/validation/chat_eval/grading.py`) does **not** parse the body for free-form text matches; it grades on tool-name selection. **No grader breakage.**

## 9. Documentation drift

- `docs/services/market-data.md:1019-1020` — migration table includes 022 + 023 ✓
- `services/market-data/.claude-context.md` — `grep -i "periodicity\|QUARTERLY\|BP-577"` confirms entry exists ✓
- `docs/MASTER_PLAN.md` — PLAN-0097 cross-reference block added per commit `88bef8bc` ✓
- `CLAUDE.md` — does **not** cross-reference R40/R41 (RULES.md addition stands alone). CLAUDE.md doesn't enumerate individual rules, so this is **by design**, not drift.
- **Drift**: TRACKING.md says ANALYZE covers "14 tables" but the migration covers 18 (see §3.4). **P2.**

## 10. Other (open-ended)

### 10.1 Resolution code path raises if `result.instrument.id` is missing

`fundamentals.py:222` does `UUID(resolution.instrument.id)` outside any try/except. If a downstream contract change makes `result.instrument` None, this raises **inside the for-loop** — outside `asyncio.gather`, so the entire batch endpoint 500s instead of failing one ticker. Today `lookup_uc.execute` always returns a populated `result` or raises `InstrumentNotFoundError`, so the risk is hypothetical. **P2 defensiveness.** Recommended: wrap line 222 in try/except, classify as `upstream_error`.

### 10.2 Classifier broad `except Exception` (line 208)

Catches all non-Timeout exceptions and fail-closes. This includes `httpx.TimeoutException` (which is NOT a subclass of `TimeoutError`). On httpx timeouts the classifier will fail-closed rather than fail-open. Given the inner httpx timeout is 15 s and the outer asyncio is 10 s, the asyncio one fires first — so this is dead code in practice. Acceptable.

### 10.3 BP-578 documents a gap, not a fix

The bug-pattern entry honestly labels itself MITIGATED, with the full FundamentalsRefreshWorker deferred to PLAN-0098. This is the right discipline — readers see the gap. **No action.**

---

## Prioritised punch-list for PLAN-0098

1. **P1** — Apply R40 third-OR-leg to `chunk_search.py` (8 sites: lines 172, 174, 261, 263, 312, 318, 426, 428) + extend `test_tenant_id_chunk_isolation.py` to cover the PUBLIC_TENANT_ID row class. (See §2.3.)
2. **P2** — Schedule nightly run of the live-gated classifier-drift suite (set `INTEGRATION_TEST=1` + `RAG_CHAT_DEEPINFRA_API_KEY` in CI cron). (§5.2.)
3. **P2** — De-flake `test_fundamentals_batch_resolves_tickers_in_parallel`: replace wall-clock with call-order barrier assertion OR raise threshold to 0.4 s. (§5.3.)
4. **P2** — Fix TRACKING.md "14 tables" → "18 tables" for migration 022. (§3.4.)
5. **P2** — Cleanup: swap `R36` → `R41` comment references in `age_sync_worker.py:515, 534`. (§6.2.)
6. **P2** — Wrap deploy-token flush in `asyncio.wait_for(..., timeout=10s)` so a slow-but-not-erroring Valkey cannot stall startup. (§4.2.)
7. **P2** — Wrap `UUID(resolution.instrument.id)` in try/except (fundamentals.py:222) to convert future contract breakage into per-ticker `upstream_error` not a 500. (§10.1.)
8. **P2** — Implement the proper FundamentalsRefreshWorker promised by BP-578. (§10.3.)

End of review.
