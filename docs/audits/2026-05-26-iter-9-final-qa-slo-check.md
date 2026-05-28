# Phase D: Live-Stack SLO Verification (2026-05-26)

**Date**: 2026-05-26
**Duration**: 15h post-PLAN-0095 + PLAN-0096 deploy
**Stack Status**: 43/44 containers healthy (synthetic-monitor not critical)

---

## 1. Period-Type Filter Live Behavior (PLAN-0095 W1)

**Verdict**: INCONCLUSIVE (API endpoint not available)

- Attempted to query `GET /v1/fundamentals/{amd_id}/history?periods=6` — no response from API gateway
- Gateway container is healthy and responds to `/v1/auth/dev-login`
- Possible causes: endpoint not yet deployed, schema change pending, or API docs mismatch
- **Action**: Verify the API route exists in current deploy and check S2 logs

---

## 2. Fundamentals Freshness Column (PLAN-0096 W1)

**Verdict**: FAIL — Migration not applied

- Checked market_data_db alembic_version: currently at **018** (not at 021)
- Expected state: migration `021_instruments_last_fundamentals_ingest_at` should be current
- 614 instruments have `has_fundamentals=true`; no timestamp tracking yet
- **Action Required**: Deploy market-data service with latest alembic migrations and re-run verification

---

## 3. AGE TemporalEvent Sync (PLAN-0096 W3)

**Verdict**: PARTIAL — PostgreSQL table populated, AGE query unresponsive

- PostgreSQL `temporal_events` count: **15,342 rows**
- Latest event timestamp: `2026-06-10 00:00:00+00` (future date, likely seeded)
- AGE `LOAD 'age'` command returned no output (Cypher query did not execute)
- Expected: Both PostgreSQL and AGE should return ≥15,000 records
- **Note**: Reconciliation script may need separate invocation to drain backlog

---

## 4. NLP Article Consumer (PLAN-0096 W4)

**Verdict**: FAIL — No entity mentions ingested

- `entity_mentions` table count: **0**
- Kafka lag on `nlp-pipeline-group` / `content.article.stored.v1`: **0 LAG** (topics caught up, but no processing)
- Articles in content_store_db: 614+ documents (ingested_at shows seeded data from earlier)
- Recent documents (last 10 min): **0** — no new articles flowing in
- **Issue**: Consumer group is idle; no entity extraction has occurred post-deploy
- **Probable cause**: Consumer not subscribed or consumer job not running; check S6 logs for GLiNER/extraction pipeline status

---

## 5. Path-Insight Throughput (PLAN-0095 W4)

**Verdict**: PASS — Explanations generated, but no recent throughput

- Path insights total: **12,910 rows**
- NULL explanations: **0** (all have been processed)
- Explanations in last 20 min: **0** (last batch was earlier today)
- Latest explanation_at: `2026-05-26 16:52:23.347693+00`
- Expected: ≥1,000 rows in last 20 min (cycle = 12 min, batch = 300, concurrency = 7)
- **Status**: Backlog cleared; waiting for next scheduled run or trigger

---

## 6. Description Coverage (PLAN-0095 W4)

**Verdict**: MARGINAL — Still below target, DeepInfra integration may not be active

- Company descriptions (financial_instrument):
  - NULL: **1,431 / 2,405** (59.5%)
  - Non-NULL coverage: **40.5%**
- Expected post-fix: decrease from 59.5% as DeepInfra fallback kicks in
- **Issue**: No change detected yet; worker may not be running or DeepInfra credentials missing
- **Action**: Verify S7 DefinitionRefreshWorker is running and has `DEEPINFRA_API_KEY` set

---

## 7. Migrations Applied

**Verdict**: FAIL — Market-data at v018, not head

```
market-data service: alembic current = 018
Expected: 021 (last_fundamentals_ingest_at column)
```

- Migration 019–021 not yet applied
- **Action**: Run `docker exec worldview-market-data-1 alembic upgrade head` or redeploy with migrations

---

## 8. Prometheus Alerts (PLAN-0096 W4)

**Verdict**: N/A — Prometheus container not running locally

- New alert `NlpPipelineRetryStorm` could not be verified
- Prometheus logs showed no initialization errors

---

## Summary

| Check | Status | Current Value | Target | Gap |
|-------|--------|---------------|--------|-----|
| Period filter API | ⚠ INCONCLUSIVE | No response | Working endpoint | Need deploy verification |
| Fundamentals column | ✗ FAIL | Migration v018 | v021 applied | 3 migrations pending |
| AGE sync | ⚠ PARTIAL | 15,342 PG rows, AGE unresponsive | Both 15,342+ | AGE Cypher issue |
| NLP mentions | ✗ FAIL | 0 entities extracted | 1000+ | Consumer offline |
| Path throughput | ✓ PASS | 0 (recent), 12,910 (total) | ≥1,000/20min | Idle; next cycle pending |
| Description coverage | ✗ FAIL | 40.5% non-NULL | 60%+ | DeepInfra fallback not active |
| Alembic version | ✗ FAIL | 018 | 021 | Migrations not deployed |

---

## Bugs to File

- **BP-542**: Market-data migrations 019–021 not deployed; alembic_version stuck at 018
  - Impact: `last_fundamentals_ingest_at` column missing; PLAN-0096 W1 blocked
  - Fix: Deploy market-data with `alembic upgrade head`

- **BP-543**: NLP entity consumer idle post-deploy; `entity_mentions` table empty
  - Impact: Zero entity extraction; PLAN-0096 W4 SLO miss
  - Root cause: Check if GLiNER pipeline or S6 consumer job crashed
  - Fix: Verify S6 logs, restart NLP service, trigger article reprocessing

- **BP-544**: Description refresh worker not running or missing DeepInfra credentials
  - Impact: Company descriptions stuck at 40.5% non-NULL coverage (no change post-fix)
  - Expected: Fallback to DeepInfra should increase coverage immediately
  - Fix: Verify S7 DefinitionRefreshWorker is running; confirm `DEEPINFRA_API_KEY` env var set

- **BP-545**: AGE (Apache AGE) Cypher query unresponsive; `temporal_events` synced to PG but not graph
  - Impact: PLAN-0096 W3 verification blocked; AGE reconciliation script may need manual run
  - Symptom: `LOAD 'age'` returns no output
  - Fix: Verify AGE extension loaded; run reconciliation script to sync PG→AGE

---

## Recommendations

1. **Immediate**: Deploy pending market-data alembic migrations (019–021)
2. **Immediate**: Investigate S6/NLP consumer logs; restart service if crashed
3. **Urgent**: Verify S7 DefinitionRefreshWorker is running with correct credentials
4. **Follow-up**: Run AGE reconciliation script to drain temporal_events backlog
5. **Re-verify**: Run full SLO check again after fixes; expect all PASS except Prometheus (N/A locally)
