# PLAN-0100 W4 — AMD Q1 FY2026 Fundamentals Freshness Diagnostics

**Date:** 2026-05-28
**Owner:** PLAN-0100 W4 (`feat/plan-0099-w4`)
**Scope:** Walk H1 → H4 root-cause hypotheses for AMD Q1 FY2026 fundamentals returning empty in chat-eval, despite all PLAN-0096/0097/0099 fixes.

## Inputs

- 4/6 Q4 chat-eval variants reported `get_fundamentals_history(AMD)` empty for Q1 FY2026.
- PLAN-0099 W2-T02 shipped `FundamentalsRefreshWorker` but kept it **OFF by default** (`FUNDAMENTALS_REFRESH_ENABLED=false`).
- Hypotheses: H1 ingestion never ran (HIGH), H2 EODHD missing data (med), H3 `period_type` filter (low), H4 fiscal-year-end-month labelling (low).

## Diagnostics

### 1. Instrument row

```
 id (b08e56b2…) | symbol=AMD | fiscal_year_end_month=12 | last_fundamentals_ingest_at=NULL
```

`last_fundamentals_ingest_at` is **NULL** — never bumped. This is the smoking gun for H1 and the reason any freshness gate (or simple "is this stale" SQL on the column) would treat AMD as never ingested.

### 2. `earnings_history` (AMD, top 8)

```
 2026-06-30 QUARTERLY
 2026-03-31 QUARTERLY  ← Q1 FY2026 (calendar Q1 = fiscal Q1; FYE=12)
 2025-12-31 QUARTERLY
 2025-09-30 QUARTERLY
 …
```

Q1 FY2026 row is **present** with the expected QUARTERLY period_type. H3 (filter too aggressive) and H4 (FYE labelling) are eliminated — no remapping needed; calendar quarter aligns with fiscal quarter (`fiscal_year_end_month=12`).

### 3. `income_statements` (AMD, top 8)

```
 2026-03-31 QUARTERLY   ← Q1 FY2026 present
 2025-12-31 ANNUAL
 2025-12-31 QUARTERLY
 2025-09-30 QUARTERLY
 …
```

Q1 FY2026 income statement is also **present**. H2 (EODHD lacking data) is eliminated.

### 4. Manual refresh trigger (canary)

Triggered `POST /api/v1/ingest/trigger` for `AMD, NVDA, MSFT` with `dataset_type=fundamentals, provider=eodhd`. All 3 returned `202 {tasks_created: 1}`. After 75 s:

```
ingestion_tasks: all 3 status=succeeded (completed within ~6 s)
last_fundamentals_ingest_at: still NULL for AMD, NVDA, MSFT
```

Cross-platform check:

```
SELECT COUNT(*) AS total, COUNT(last_fundamentals_ingest_at) AS with_freshness
FROM instruments;
  total=629  with_freshness=0
```

**Zero instruments platform-wide have the freshness column populated.** Trigger / fetch / S3 / Kafka path works end-to-end, but the `touch_fundamentals_ingest_at(id, ts)` repo method shipped in PLAN-0096 T-W1-02 (BP-545) is **never called by the consumer** — separate market-data side bug, out of W4 scope.

## Verdict

- **H1 confirmed (primary)**: the recurring worker is OFF by default, so AMD was never on a refresh cadence. Even though data rows happen to exist from earlier manual triggers, no automated path keeps them fresh.
- **Secondary bug discovered (out of scope, defer to PLAN-0101):** `FundamentalsConsumer` does not call `touch_fundamentals_ingest_at`. The column is dead. Freshness-based stale-ticker queries (advertised in `services/market-data/.claude-context.md:87`) silently return *every* ticker as stale.
- **H2 eliminated**: EODHD already has Q1 FY2026 (earnings + income).
- **H3 eliminated**: `period_type=QUARTERLY` correctly applied.
- **H4 eliminated**: AMD's `fiscal_year_end_month=12`; calendar↔fiscal alignment 1:1, no remap needed.

## Operator dashboard SQL

Until a Grafana panel lands (deferred to PLAN-0101 alongside the consumer-bump fix), operators can monitor freshness with:

```sql
SELECT
  CASE
    WHEN last_fundamentals_ingest_at IS NULL THEN 'never'
    WHEN last_fundamentals_ingest_at >= NOW() - INTERVAL '1 day' THEN '0-1d'
    WHEN last_fundamentals_ingest_at >= NOW() - INTERVAL '7 days' THEN '1-7d'
    WHEN last_fundamentals_ingest_at >= NOW() - INTERVAL '30 days' THEN '7-30d'
    ELSE '>30d'
  END AS freshness_bucket,
  COUNT(*) AS instruments
FROM instruments
GROUP BY 1
ORDER BY 1;
```

## Actions (this wave)

- T-W4-03: flip `FUNDAMENTALS_REFRESH_ENABLED` default `False → True`. Operators retain opt-out by setting it explicitly to `False`.
- BP-608 logged for "scheduled worker shipped disabled by default, silently missed entity."
- Consumer-bump fix and Grafana panel: PLAN-0101 follow-up (touch_fundamentals_ingest_at never wired into FundamentalsConsumer despite PLAN-0096 T-W1-02 claim).
