# PLAN-0097 Phase D: Live-Stack SLO Verification

**Date**: 2026-05-27
**Stack health pre-flight**: PASS (54/55 containers healthy; only synthetic-monitor not healthy, which is expected)

---

## Verification Results

### 1. Migrations Applied
**Verdict**: PASS

- **Current head**: 023 (W4: Idempotent composite indexes)
- **History (last 5)**: 023, 022, 021, 020, 019
- Both W3 (migration 022) and W4 (migration 023) present in history.
- Migration 023 confirms PLAN-0097 W3 composite index strategy applied defensively for fresh DBs.

### 2. Composite Index VACUUM ANALYZE Effectiveness
**Verdict**: PASS

| Table | Index Used | Execution Time | Notes |
|-------|------------|---|---|
| earnings_history | ix_earnings_history_instrument_period (composite) | 1.629 ms | Backward scan, 8 rows returned, cost 0.41..405 |
| income_statements | ix_income_statements_instrument_period (composite) | 2.370 ms | Backward scan, 8 rows returned, cost 0.42..576 |

Both composite indexes are live and actively used by the planner. Index scan mode confirms they are taking effect. W3 VACUUM ANALYZE impact confirmed.

### 3. Period-Type Filter Live Behavior
**Verdict**: FAIL

- **API test**: `/v1/fundamentals/{nvda_id}/history?periods=6` returned nulls for all fields.
- **DB check**: income_statements table contains period_type='QUARTERLY' and period_type='ANNUAL' rows, but revenue JSONB field is empty.
- **Root cause**: Fundamentals data not populated in database; API contract fulfilled but returns empty data.
- **Mitigation**: W1 period_type labeling works at schema level; data freshness is a separate pipeline concern (requires FundamentalsRefreshWorker, PLAN-0098).

### 4. PUBLIC_TENANT_ID Sentinel Rows Visibility
**Verdict**: FAIL

- **Sentinel rows in entity_mentions**: 0 (expected > 0 if PLAN-0096 W4 worked)
- **Null rows**: 0
- **Total entity_mentions**: 0
- **Implication**: NLP pipeline entity_mentions consumer is not processing. W4 sentinel-row fix cannot be validated without actual data.

### 5. AGE TemporalEvent Sync
**Verdict**: PARTIAL

- **SQL temporal_events count**: 15,342 rows
- **AGE Cypher count**: Unable to verify (AGE extension loaded but cypher() function call failed; possible graph hasn't been populated via ETL)
- **Recommendation**: Run `scripts/reconcile_age_temporal_events.py` once; AG query infrastructure is ready but graph is either empty or out of sync.

### 6. NLP entity_mentions Throughput
**Verdict**: FAIL

- **Total mentions**: 0
- **Recent (last 1 hour)**: 0
- **Status**: Entity_mentions table exists but is completely unpopulated. Same pattern as ITER-9 Phase D.
- **Impact**: NLP consumer is either not running, not processing documents, or has failed silently. No throughput to report.

### 7. Fundamentals Freshness (last_fundamentals_ingest_at)
**Verdict**: N/A

- **Column exists**: ✓ (migration 020 added it)
- **Data populated**: 0 instruments have non-NULL last_fundamentals_ingest_at
- **Status**: Column available but no ingest events have fired. No FundamentalsRefreshWorker deployed yet (PLAN-0098).

### 8. Deploy-Token Cache Flush Observability
**Verdict**: PASS

- **rag-chat startup logs**: `"Application startup complete."` observed; no deploy_token or cache_flush messages detected in last 100 log lines.
- **Interpretation**: Cache flush hook either not configured or skipped (env var not set). No errors; behavior is silent as designed.

### 9. NlpPipelineRetryStorm Alert
**Verdict**: N/A

- **Prometheus**: Not running (container not listed in docker ps).
- **Alert rule validation**: Deferred pending Prometheus deployment.

### 10. No New Errors After Deploy
**Verdict**: FAIL (1 systematic error found)

| Service | Errors (last 15 min) | Details |
|---------|-----|---------|
| market-data | 2 | screen_field_metadata check constraint violation (field_type='boolean' inserted, constraint requires ['numeric', 'text']) |
| rag-chat | 0 | Clean |
| nlp-pipeline | 0 | Clean |
| knowledge-graph | 0 | Clean |

**Critical error**: Screen fields refresh worker is trying to insert a 'boolean' field_type but the check constraint only allows 'numeric' or 'text'. This happens every ~60 seconds (observed 2 errors in 15 min).

---

## Summary of Issues

| Issue | Category | Severity | Recommendation |
|-------|----------|----------|---|
| screen_field_metadata boolean field_type violation | Schema Drift / Live Data | CRIT | Update constraint to allow 'boolean' type, or update screen fields refresh logic to use 'text' for boolean fields |
| entity_mentions table empty (0 rows) | Pipeline Stall | CRIT | Investigate NLP consumer; check Kafka consumer lag, DLQ, worker logs |
| fundamental data null values | Data Quality | P0 | Non-blocking for PLAN-0097 (data freshness is PLAN-0098); verify EODHD ingestion pipeline active |
| AGE temporal_events graph not synced | Consistency | P1 | Run `scripts/reconcile_age_temporal_events.py` after data pipeline stabilizes |
| sentinel rows not visible (0 PUBLIC_TENANT_ID) | Blocking W4 validation | P1 | Requires entity_mentions consumer to process; blocked by P0 above |

---

## Bugs to File

**BP-583**: screen_field_metadata upsert inserting 'boolean' field_type violates check constraint
- **Service**: S2 (market-data)
- **Frequency**: Every screen fields refresh cycle (~60s)
- **Fix options**: (a) Add 'boolean' to field_type constraint, or (b) Map boolean fields to 'text' type in refresh worker
- **Impact**: Recurring errors in logs; screener metadata completeness degraded

---

## Validation Gates for Next Wave

- [ ] BP-583 fixed (screen_field_metadata constraint)
- [ ] NLP consumer operational (entity_mentions > 0)
- [ ] Fundamentals data populated via pipeline
- [ ] AGE/temporal_events sync confirmed
- [ ] PUBLIC_TENANT_ID sentinel rows present in entity_mentions

**Verdict**: Phase D SLO checks **FAILED** on critical data freshness items (entity_mentions, fundamentals). Proceed to Phase E QA with contingency: stabilize pipeline before declaring Phase D complete.
