# PLAN-0095 + PLAN-0096 — Final Adversarial Code Review

**Date:** 2026-05-26
**Branch:** `feat/plan-0093-remediation`
**Scope:** 11 commits (PLAN-0095 W1/W2/W3/W4 + PLAN-0096 W1/W2/W3/W4)
**Reviewer mode:** Read-only adversarial. No source modifications.

---

## Verdict: **CONDITIONAL PASS**

All eleven commits are coherent, additive, and largely defensible. No P0 regressions identified. Two **P1** issues warrant a fast follow-up in PLAN-0097 (a tenant-leak vector via the public-briefing path that now intersects W4's sentinel, and a tautological period-type test). Seven **P2** observations are documented for future hardening. The branch is safe to merge **provided** P1-1 (sentinel cross-coupling) is at least documented as a known risk before deploy.

---

## 1. Hidden Regression Risk

**Severity: P2.** I traced call sites of every modified function:

- `query_fundamentals` (8450666b) — new defaulted `period_type` keyword. Callers: `fundamentals_read_repo.find_by_section` (passes `period_type` explicitly post-4a5b6cae) and the `GetFundamentalsHistoryUseCase` (explicit QUARTERLY). All call sites updated.
- `ArticleProcessingConsumer.process_message` (d8ff0a22) — only consumer call site is the Kafka loop; `tenant_id` now always non-None which propagates into `_handle_*` helpers downstream. No nullability regression — downstream `entity_mentions.tenant_id` was already typed `UUID`.
- `ChatOrchestratorUseCase._execute_streaming` (0e2ef9bc) — reorder of `check_cache` vs. `validate_input`. The cache-miss path is unchanged. The cache-hit path no longer touches `validate_input`; nothing downstream of `validate_input` runs on cache-hit anyway (`request.message` was only used by `validate_input`'s sanitiser → discarded on hit). Safe.
- `_bootstrap_age_labels` (baba6b2b) — new `_invalidate_session_connection` call appended after `commit()`. No new exception surface (try/except + warn). Safe.

**Fix recommendation:** none.

---

## 2. Security — Sentinel `PUBLIC_TENANT_ID` Exploitability

**Severity: P1.** File: `libs/common/src/common/ids.py:28`, applied at `services/nlp-pipeline/.../article_consumer.py:469`.

The sentinel choice (`00000000-…`) is consistent with existing convention: `api-gateway/jwt_utils.py:28`, `kg/scheduler/scheduler.py:713-714`, `kg/fundamentals_refresh.py:135-136`, `rag-chat/generate_briefing.py:289,421,425`, and `rag-chat/public_briefings.py:135` all use the same nil UUID for system/anonymous identities.

**The exploit vector that does exist:** `services/rag-chat/.../generate_briefing.py:289,421-425` falls back to `UUID("00000000-…")` when `user_id`/`tenant_id` parses fail. The public-briefing route (`public_briefings.py:135`) deliberately returns this UUID for anonymous traffic. Combined with W4's sentinel, the tenant-filter SQL at `services/nlp-pipeline/.../news_query.py:139` (`em.tenant_id IS NULL OR em.tenant_id = :tenant_id`) means:

- Legacy articles consumed under the W4 fix get `tenant_id = 00000000…` (no longer `NULL`).
- An anonymous public-briefing request with `tenant_id = 00000000…` will match legacy article rows via the equality branch — by design.
- A real-tenant request will **not** see legacy articles (the `IS NULL` branch no longer fires, and the equality branch doesn't match).

This is not a privilege escalation — legacy articles were presumed public anyway — but it **silently inverts the visibility model**: legacy articles are now visible *only* to anonymous public traffic and *invisible* to real authenticated tenants. Before the fix, the `IS NULL` branch made them visible to all. **No commit documents this invariant change.**

**Fix recommendation:** Either (a) update the SQL filter to `em.tenant_id IN (:tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)` when the caller is not anonymous, or (b) explicitly document that the W4 sentinel removes legacy-article visibility from authenticated tenants and add a one-shot backfill to remap historical NULLs. File: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:139`.

---

## 3. Migration Safety (019, 020, 021)

**Severity: P2.**

- **019** (`019_composite_fundamentals_indexes.py`): Creates 18 plain `CREATE INDEX` statements inside one Alembic transaction. With 50k+ rows per table this holds an ACCESS EXCLUSIVE lock on each table sequentially — total wall-clock estimate 30-120 s; writes to those tables block for the duration. The migration is **idempotent on re-run only because** `op.create_index` raises if the index already exists, aborting the migration (Alembic re-running a head it's already applied is the normal failure path, fine). **Not safe to manually re-run partially** — failure halfway through leaves some indexes created and the Alembic head un-bumped; re-running will fail on the first already-created index. Recommendation: add `if not exists` guards or split into 18 separate revisions.
- **020** (`020_snapshot_period_type_columns.py`): Three nullable VARCHAR additions on `instrument_fundamentals_snapshot`. ADD COLUMN nullable is metadata-only in PG ≥11 — safe and fast. Truly additive.
- **021** (`021_instruments_last_fundamentals_ingest_at.py`): One nullable TIMESTAMPTZ column on `instruments`. Same metadata-only safety. Safe.

**Fix recommendation (P2):** Wrap 019's index creations with `IF NOT EXISTS` (`op.execute("CREATE INDEX IF NOT EXISTS …")`) to make partial re-runs safe. File: `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py:106-114`.

---

## 4. Hexagonal / Architecture Violations

**Severity: none.** I grepped for cross-layer imports in every touched file:

- `api/routers/fundamentals.py` imports from `api/dependencies`, `api/schemas`, `domain/entities`, `domain/enums`, `domain/errors`, plus the use-case ports `GetFundamentalsHistoryUseCase` / `InstrumentLookupUseCase`. No `infrastructure/` import. R16 satisfied.
- `rag-chat/handlers/market.py` adds a port-typed `_s3` field; no infra import.
- `kg/age_sync_worker.py` is infrastructure; uses `AsyncSession` directly — already an infrastructure-layer worker.
- No domain-layer file was touched.
- No direct cross-service DB access introduced (batch endpoint stays in market-data, no rag-chat → market-data DB shortcut).

**Fix recommendation:** none.

---

## 5. Forward-Compat (Avro)

**Severity: none.** `git show --stat <all>` shows **zero `.avsc` files modified**. The W4 fix deliberately works around legacy Avro shape rather than evolving it. Safe.

---

## 6. Test Quality

**Severity: P1.** File: `services/market-data/tests/unit/test_fundamentals_query_defaults.py`.

The four "period_type filter" tests are **string-inspection tests, not behavioral tests**. They mock `session.execute`, compile the SQL with `literal_binds=True`, and grep the WHERE clause for the substring `"QUARTERLY"`. This proves the SQL *contains* the filter but does **not** prove the filter actually excludes ANNUAL rows — there is no fixture seeding both QUARTERLY and ANNUAL rows and asserting only QUARTERLY comes back. If a future refactor accidentally changes `period_type = :p` to `period_type IS NOT NULL OR period_type = :p`, every test still passes.

PLAN-0095 W1's test in `test_period_label_fiscal.py` was likewise updated only to accept the new kwarg signature, not to verify exclusion behavior.

**Fix recommendation:** add an integration test that seeds both periodicities and asserts row exclusion. The unit-level SQL inspection should stay (it's cheap regression cover), but the strong claim "the wrong periodicity is excluded" needs DB-level proof. File: `services/market-data/tests/unit/test_fundamentals_query_defaults.py:57-122`.

The W4 tests (`test_article_consumer_legacy_tenant.py`) are stronger — they mock the full Kafka envelope and assert the `tenant_id` kwarg reaches the downstream save call. Good.

The W3 AGE tests (`test_age_sync_worker.py` `TestLabelBootstrap`) assert `connection.invalidate()` is awaited — that's structural, not behavioral (does not prove the fix actually causes MERGEs to see the new label). Acceptable given the integration marker stub.

---

## 7. AGE `session.connection.invalidate()` Correctness

**Severity: P2.** File: `services/knowledge-graph/.../age_sync_worker.py:489-525`.

SQLAlchemy's `AsyncConnection.invalidate()` marks the underlying DBAPI connection as invalid; the pool discards it on return. The next `session.connection()` call (driven by the next `_setup_age_session` → SQL execute inside `_run_phase`) checks out a **fresh** raw connection. PostgreSQL `plpgsql` catalog cache is **per backend**, so a fresh connection = fresh cache. The mechanism is correct in principle.

**Latent risk:** the `AsyncSession` still holds transactional state. After `invalidate()`, the session enters an invalidated state until the next `begin()`. The `_run_phase` flow does `await _setup_age_session(session)` → SQL execute → `await session.commit()`. SQLAlchemy will silently reissue a connection on the implicit BEGIN, so this should work. **However**, if APScheduler interleaves a second phase before the first connection acquisition, the invalidated session may raise `InvalidRequestError`. The try/except in `_invalidate_session_connection` covers invalidate-failure but not subsequent-session-error.

**Fix recommendation:** the reconcile script's pattern (fresh session per writer) is the bulletproof version. For the worker, prefer `session.close()` + `session.begin()` over `invalidate()` to make the next BEGIN explicit. Lower-risk alternative: keep current code, add an `await session.rollback()` immediately before invalidate to make the state transition explicit. File: `services/knowledge-graph/.../age_sync_worker.py:516-525`.

---

## 8. Batch Endpoint Partial-Failure Behavior

**Severity: none.** File: `services/market-data/src/market_data/api/routers/fundamentals.py:177-213` + `services/market-data/tests/unit/test_fundamentals_api.py:286-313`.

`asyncio.gather(..., return_exceptions=True)` with `zip(body.tickers, raw_results, strict=True)` preserves order. The response keys each ticker with `status="ok"` or `status="error"` + `reason=str(exc)`. The test `test_fundamentals_batch_returns_per_ticker_status` exercises a mixed input (`["AAPL", "BADTICKER", "NVDA"]`) and asserts each ticker's status independently. Contract confirmed.

**One minor observation (P2):** `reason=str(exc)` for unexpected exceptions could leak internal error detail (e.g. a malformed SQL exception's `repr` with table/column names) to the LLM and ultimately to user-visible chat output. Recommend redacting non-`InstrumentNotFoundError` reasons to `"upstream error"`. File: `services/market-data/.../routers/fundamentals.py:205`.

---

## 9. Classifier-Before-Cache Reorder — Poisoned-Cache Risk

**Severity: P2.** File: `services/rag-chat/.../use_cases/chat_orchestrator.py:456-475` + `docs/BUG_PATTERNS.md` (BP-572).

The security argument in the commit message is sound *in steady state*: any cache entry was classified before being written. But the argument depends on a clean precondition. Pre-existing cache entries (from before this commit landed in dev/staging/prod) were also written through the prior `validate_input` → `check_cache` → `cache.set` flow, so they too passed the classifier at least once. **In this codebase the risk is theoretical** — but the BUG_PATTERNS entry should explicitly call out the deployment precondition: "this reorder is safe **only if** every prior cache-write went through the classifier. If the classifier was ever bypassed (e.g. a feature flag, a dev override, an `if not validate_input:` short-circuit), poisoned entries become permanent."

**Fix recommendation (P2):** add a one-shot Valkey `SCAN + DEL rag:completion:*` on next deploy as a belt-and-suspenders cache flush, and pin the precondition in BP-572.

---

## 10. Cross-Commit Interactions

**Severity: none (verified).** I traced the suspicion that the batch endpoint (W2) bypasses W1's `period_type` filter:

- Batch endpoint (`api/routers/fundamentals.py:179`) → `uc.execute(instrument_id=…, periods=body.periods)`.
- That use case (`get_fundamentals_history.py:87-91`) hardcodes `period_type=PeriodType.QUARTERLY` for INCOME_STATEMENT.

So **the batch path inherits the W1 fix for free**. No oversight. The W3 AGE fix and W4 DLQ fix are in disjoint services, no interaction. PLAN-0096 W1's defensive default at the repo layer is a defence-in-depth duplicate of the W1 use-case-layer fix — that's intentional and called out in the commit message.

The only real cross-commit issue is the **W4 sentinel × tenant-filter SQL interaction documented in §2.**

---

## Punch-list for PLAN-0097

1. **[P1]** Document or fix the W4 sentinel × `news_query.py` tenant-filter visibility inversion (§2). Either widen the SQL filter to include the sentinel for authenticated callers, or backfill historical NULLs to a deterministic mapping.
2. **[P1]** Add a real DB-fixture integration test for the period_type filter that seeds both QUARTERLY and ANNUAL rows and asserts the wrong one is excluded (§6).
3. **[P2]** Make migration 019 idempotent on partial re-run via `CREATE INDEX IF NOT EXISTS` (§3).
4. **[P2]** Switch AGE worker to `session.rollback()` + explicit fresh session, or document the invalidate-then-implicit-BEGIN contract (§7).
5. **[P2]** Redact unexpected-exception `reason` strings in the batch endpoint to avoid leaking internal error detail to LLM output (§8).
6. **[P2]** Add a one-shot Valkey completion-cache flush on the next rag-chat deploy and pin the classifier-reorder deployment precondition in BP-572 (§9).
7. **[P2]** Add an alert for `article_consumer.legacy_tenant_id_sentinel_applied` rate — if it stays non-zero for >7 days post-deploy, a producer is still emitting tenant-less Avro and the "drain in-flight backlog" framing of W4 has silently shifted to "permanent legacy passthrough."
8. **[P2]** AGE label bootstrap should have a true integration test that exercises a real AGE container + MERGE + assertion of `1409 == ROW count` post-sync (the stub-skip is acceptable for unit CI but does not prove the BP-574 fix end-to-end).
