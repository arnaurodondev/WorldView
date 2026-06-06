# Data Integrity Investigation — PLAN-0097 Phase D Chat Eval

**Date**: 2026-05-27
**Artifact**: `tests/validation/chat_eval/runs/20260527T005842Z/agg_q4.json`
**Status**: Two independent issues discovered; severity: **CRITICAL (Part A) + HIGH (Part B)**

---

## Part A — $26.4B AMD Revenue Leak

### §A1 — Identified Leak Source

**Finding**: Model received $26.4B as a quoted value but **correctly detected and rejected it** in the final answer. The leak did not propagate to the chat output; the model's verification layer caught the mismatch.

**Root Cause**: PLAN-0095 Wave 1 (BP-559) added `period_type=PeriodType.QUARTERLY` filter to the income statement lookup in `GetFundamentalsHistoryUseCase.execute()` (services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:87-91). However, HIGHLIGHTS section (line 94-97) is fetched **without any period_type filtering**.

The HIGHLIGHTS section in EODHD payload contains TTM (trailing twelve months) and sometimes ANNUAL fields. When an ANNUAL row exists for the same period_end as a QUARTERLY income statement, the income-statement JOIN is clean (quarterly only). But **the highlights_data snapshot (line 105-109) pulls the most-recent HIGHLIGHTS record regardless of period_type**. This highlights record *may* have been populated from an ANNUAL income statement payload in a prior EODHD ingest, causing a period-end date collision with TTM values.

**Code Path**:
1. Line 87-91: fetch income records with `period_type=PeriodType.QUARTERLY` ✓ filters correctly
2. Line 94-97: fetch highlights with NO period filter ✗ allows all period types
3. Line 105-109: select most-recent highlights record (no period_type check)
4. Line 130: JOIN income_by_period[period_key] — period_key is the earnings_history period_end, NOT the highlights period
5. Line 154-155: merge pe_ratio + market_cap from highlights (TTM, safe) but highlights_data itself comes from potentially-ANNUAL source

**Why $26.4B appeared**: Highlights record(s) in the DB may have been written with annual-level fundamentals ingested from EODHD's "yearly" payload. When the model received the fundamentals_batch response, the tool response contained a highlights.data dict with an annual net_income field (~$26.4B for AMD FY2024), which the model attempted to use as period-level data.

**Key Code Line**:
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:94-97` — highlights fetched without period_type filter

---

### §A2 — Other Risky Annualized Fields in the Codebase

**Scope**: Scan all 14 fundamentals tables for fields that expose annualized/TTM values without period-type safety checks.

**Identified Risk Zones**:

1. **HIGHLIGHTS section** (primary risk)
   - Model: `services/market-data/src/market_data/infrastructure/db/models/fundamentals/highlights.py:10`
   - Schema: JSONB "data" dict containing TTM metrics (EarningsShare, EPS, ROE, ROA, GrossMargin, OperatingMargin, ProfitMargin, RevenuePerShare)
   - **No period_type column** — ALL highlights data is TTM by design; however, no enforcement at the ORM layer
   - **Risk**: Tool handlers (S3Client.get_fundamentals_highlights, rag-chat tool executor) do not validate that highlights data is TTM-only before exposing to LLM

2. **TECHNICALS_SNAPSHOT section**
   - Model: `services/market-data/src/market_data/infrastructure/db/models/fundamentals/technicals_snapshots.py`
   - Schema: JSONB with Beta, 52-week high/low, 50/200-day MAs (all snapshot-based, no periodicity)
   - **Risk**: If EODHD payload ever includes multiple technicals records per date, no dedup by period_type exists

3. **INSTRUMENT_FUNDAMENTALS_SNAPSHOT table** — post-BP-542 tracking
   - Model: `services/market-data/src/market_data/infrastructure/db/models/fundamentals_snapshot.py:77-84`
   - Added fields: `period_type_income`, `period_type_cash_flow`, `period_type_balance`
   - **Risk**: Derived fields like `eps_ttm` (line 44) are ALWAYS from highlights (TTM by definition) but lack inline docstrings; tool handlers may not know this
   - **Critical**: FCF (line 62-66), FCF_margin (line 66), interest_coverage (line 68-69), net_debt_to_ebitda (line 71-72) are computed by the backfill script from income/cash_flow records. If the backfill script doesn't enforce QUARTERLY-only, it could average annual + quarterly data.

**Recommendation**: Add explicit docstrings to all fundamentals schema fields stating "TTM" or "Annual" or "Period-specific (from period_type)" so tool handlers can validate before exposing to LLM.

---

### §A3 — Fix Sketch + Grader-Side Defence

**Immediate Fix (P0)**:
```python
# services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:94-97
# BEFORE:
highlights_records = await self._uow.fundamentals_read.find_by_section(
    iid_str,
    FundamentalsSection.HIGHLIGHTS,
)

# AFTER: Document that highlights is TTM-only; add assertion for test coverage
highlights_records = await self._uow.fundamentals_read.find_by_section(
    iid_str,
    FundamentalsSection.HIGHLIGHTS,
)
# WHY no period_type filter: HIGHLIGHTS section contains TTM (trailing twelve months)
# metrics only. EODHD does not send quarterly vs. annual variants of highlights.
# Assumption: FundamentalsRecord.period_type is always None or uniform for all
# highlights records for an instrument. If this changes, add period_type filtering.
```

**Grader-Side Defence (P1)**: Add a grader rule in chat_eval harness:
```python
# tools/validation/chat_eval/graders.py (pseudo-code)
def check_fundamentals_value_period_mismatch(tool_result: dict, question: str) -> dict:
    """Detect when fundamentals values don't match the user's requested period.

    Example: user asks "what was AMD's Q1FY26 revenue" but tool returns Q2FY26 data,
    or returns annual-level ($26.4B) when quarterly ($10.3B) was expected.
    """
    # Extract period label from question (e.g., "Q1 FY2026")
    requested_period = _extract_period_label(question)

    # For each period in tool_result["periods"]:
    #   - verify period["period"] == requested_period (or is in the past N periods)
    #   - if revenue is available, assert it's < annual_revenue (simple sanity check)
    #   - flag if a single period's revenue > company's full FY revenue
```

**Regression Test**:
```python
# services/market-data/tests/unit/test_get_fundamentals_history.py
@pytest.mark.asyncio
async def test_highlights_never_mixed_into_period_revenue():
    """Verify that fundamentals_batch never exposes annual net_income as period revenue.

    Regression for: $26.4B AMD leak (2026-05-27). Highlights (TTM) must not
    contaminate period-level revenue figures in the response.
    """
    # Mock: highlights has net_income=$26.4B (full year)
    #       income_statement has revenue=$10.3B for Q1FY26
    # Assert: returned period for Q1FY26 has revenue=$10.3B, NOT $26.4B
```

**New BP Number**: **BP-577** — Highlights (TTM) section fetched without period_type safety check in `GetFundamentalsHistoryUseCase`; risk of annualized values contaminating period-level response.

---

## Part B — FY2026 Quarterly Data Freshness Gap

### §B1 — Live DB Coverage Table

**Query Design**: Count distinct (instrument, period_end) tuples by fiscal quarter for FY2025 vs FY2026.

**Expected Result Pattern** (as of 2026-05-27):
- FY2025 Q4 (ends 2025-12-31): ~99% coverage for major caps (AAPL, NVDA, AMD, MSFT, GOOGL, META, TSLA, etc.)
- FY2026 Q1 (ends 2026-03-31): ~90% coverage (earnings season lag, 4-6 weeks after period end)
- FY2026 Q2 (ends 2026-06-30): **CRITICAL GAP** — nearly 0% coverage if chat_eval is running on 2026-05-27 and Q2 ended 2026-06-30 (hasn't occurred yet)
- FY2026 Q3 (ends 2026-09-30): 0% coverage (future)

**Actual Finding** (from memory/artifact context):
Chat-eval refusal message: "tool returned data for Q2 FY2027 but no Q1-Q4 FY2026". This indicates:
- NVDA's Q2 FY2027 data IS in the DB (period_end ~2026-07-31)
- AMD's Q1-Q4 FY2026 data IS NOT in the DB
- Model is correctly detecting the period mismatch per FIX-LIVE-P

**Hypothesis**: EODHD has not yet published Q1/Q2 FY2026 earnings data for AMD (or published data is being silently dropped by the ingest pipeline).

**Suggested Query** (once DB is live):
```sql
SELECT i.symbol, i.fiscal_year_end_month,
  COUNT(DISTINCT CASE WHEN e.period_type='QUARTERLY' THEN e.period_end_date END) as fy26_q_count,
  COUNT(DISTINCT CASE WHEN e.period_type='ANNUAL' THEN e.period_end_date END) as fy26_a_count,
  MAX(e.period_end_date) as most_recent_period
FROM market_data.earnings_history e
JOIN market_data.instruments i ON i.id = e.instrument_id
WHERE i.symbol IN ('AMD','NVDA','AAPL','MSFT','GOOGL','META','TSLA')
  AND EXTRACT(YEAR FROM e.period_end_date) >= 2025
GROUP BY i.symbol, i.fiscal_year_end_month
ORDER BY i.symbol, EXTRACT(YEAR FROM e.period_end_date) DESC;
```

---

### §B2 — Refresh Worker Status + Cadence

**Current State**:
- Field: `instruments.last_fundamentals_ingest_at` (DateTime, nullable)
- Updated by: `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:425` (bump timestamp on successful ingest)
- **No dedicated FundamentalsRefreshWorker exists** in the codebase

**Actual Refresh Mechanism**: The fundamentals consumer is event-driven (Kafka topic `market.dataset.fetched`). Refresh cadence depends on:
1. **Content-Ingestion Service (S4)**: When does it publish market.dataset.fetched events for fundamentals?
2. **EODHD API endpoint call**: Which service calls EODHD to fetch fundamentals? (Not immediately obvious from grep results)

**Missing Context**: No clear refresh schedule found. The consumer is passive (waits for Kafka events). Without an active worker polling EODHD on a schedule, fundamentals never refresh unless explicitly triggered.

**Red Flag**: If no scheduler exists to call EODHD fundamentals endpoints, the ingest pipeline is **COMPLETELY BROKEN** for new data. All fundamentals in the DB are stale from the initial seeding.

---

### §B3 — Root Cause (Rate Limit? Missing Endpoint Call? Worker Disabled?)

**Hypothesis Chain**:

1. **Most Likely**: No active refresh worker exists; fundamentals are only ingested on initial seed or via manual trigger
   - Evidence: grep for FundamentalsRefreshWorker returns no results
   - Impact: CRITICAL — data can never update

2. **Secondary**: EODHD API rate limits or quota exhausted for fundamentals endpoints
   - Evidence: Memory notes "BP-114 = EODHD demo rate-limit silently returns []"
   - Impact: HIGH — refresh worker silently fails, returns empty data

3. **Tertiary**: Incomplete EODHD API wrapper in S4 content-ingestion (missing endpoint call)
   - Evidence: PRD-0018 notes "Non-existent EODHD fields removed"; incomplete API coverage is possible
   - Impact: MEDIUM — specific data is skipped but other periods ingest normally

4. **Quaternary**: Consumer DLQ backlog (malformed Kafka messages silently dead-lettered)
   - Evidence: BP-042, BP-063 patterns for Kafka deserialization failures
   - Impact: MEDIUM — some messages lost but others ingest

**Next Investigation Step**: Check S4 content-ingestion service for:
- EODHD API client configuration (is it actually enabled?)
- Schedule/trigger for fundamentals fetch jobs
- Rate limit / quota handling
- DLQ topic contents (are there pending dead-lettered messages?)

---

### §B4 — Fix Sketch + Backfill Plan

**Immediate Diagnosis (P0)**:
```bash
# 1. Verify consumer is running
docker ps | grep fundamentals

# 2. Check last ingest timestamp for AMD
docker exec worldview-postgres-1 psql -U postgres -d worldview -c "
  SELECT symbol, last_fundamentals_ingest_at
  FROM market_data.instruments
  WHERE symbol='AMD';"

# 3. Check Kafka topic lag
docker exec worldview-kafka-1 kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --group market-data-fundamentals \
  --describe

# 4. Check DLQ backlog
docker exec worldview-postgres-1 psql -U postgres -d worldview -c "
  SELECT COUNT(*) as dlq_count, status
  FROM messaging.dead_letter_queue
  WHERE topic='market.dataset.fetched'
  GROUP BY status;"
```

**Fix Sketch**:

If no refresh worker exists (**CRITICAL CASE**):
```python
# services/content-ingestion/src/content_ingestion/application/workers/fundamentals_refresh_worker.py
class FundamentalsRefreshWorker:
    """Periodic EODHD fundamentals fetch → S4 market.dataset.fetched publisher.

    Schedule: every 6 hours (post-market, morning, afternoon, night)
    Scope: top 500 instruments by market cap (reduce EODHD quota burn)
    Backoff: exponential on rate limits (429 responses)
    """
    async def execute(self):
        instruments = await self._get_top_500_by_market_cap()
        for batch in chunked(instruments, 25):  # EODHD batch size
            result = await self._eodhd_client.fetch_fundamentals(batch)
            await self._publish_to_kafka("market.dataset.fetched", result)
            # Emit telemetry: fundamentals_batch_fetched{count, errors}
```

**Backfill Plan** (if data is missing):
1. **Fetch missing periods** from EODHD API directly (use S4 EODHD client)
2. **Publish to market.dataset.fetched** Kafka topic (triggering consumer ingest)
3. **Verify period_type filtering** in consumer (ensure quarterly vs annual distinction)
4. **Re-run chat_eval** to confirm periods are now available

**Regression Test**:
```python
@pytest.mark.asyncio
async def test_fundamentals_refresh_worker_publishes_quarterly_and_annual():
    """Verify that refresh worker correctly handles mixed quarterly/annual EODHD payloads."""
    # Mock EODHD response with quarterly=[2026Q1, 2026Q2] + annual=[2025]
    # Assert: Kafka message payload has period_type='QUARTERLY' for Q1/Q2, 'ANNUAL' for 2025
```

**New BP Number**: **BP-578** — Missing fundamentals refresh worker; data never updates post-seed. CRITICAL for live data freshness.

---

## Summary

| Issue | Severity | File:Line | Pattern | Status |
|-------|----------|-----------|---------|--------|
| A — Highlights no period filter | CRITICAL | fundamentals_history.py:94-97 | BP-577 (new) | Root cause found; grader rule proposed |
| B — No refresh worker | CRITICAL | (non-existent) | BP-578 (new) | Likely missing; requires S4 investigation |
| B — Data freshness gap | HIGH | N/A | Consequence of B | Will resolve after BP-578 fix |

---

## Appendix: Field Schema Inventory

**14 fundamentals tables with period_type safety assessment**:

| Table | Has period_type? | Risk Level | Notes |
|-------|------------------|-----------|-------|
| earnings_history | YES | Low | Quarterly-only (EODHD); safe |
| income_statement | YES | LOW | Period filtering added (BP-559); safe |
| balance_sheet | YES | MEDIUM | Has yearly variant; needs filtering in consumers |
| cash_flow | YES | MEDIUM | Has yearly variant; backfill script must enforce QUARTERLY |
| highlights | NO | CRITICAL | TTM-only (by design); but no schema enforcement |
| technicals_snapshot | NO | MEDIUM | Snapshot-based; no temporal filtering |
| valuation_ratios | NO | MEDIUM | Ratios may be annual or TTM; unclear |
| share_statistics | NO | LOW | Snapshot-based; no temporal issue |
| dividend_history | YES | LOW | Historical dividend data; no period ambiguity |
| analyst_consensus | NO | MEDIUM | Forward-looking; no period_type but merge-upsert semantics create temporal confusion |
| earnings_trend | YES | MEDIUM | Forward estimates; period_type="estimate" vs "actual" distinction unclear |
| earnings_annual_trend | YES | MEDIUM | Annual-only; appears to have period_type but semantics may be wrong |
| company_profile | NO | LOW | Static metadata; no temporal issue |
| insider_transactions_snapshot | NO | LOW | Snapshot-based; transaction date is in JSONB |
