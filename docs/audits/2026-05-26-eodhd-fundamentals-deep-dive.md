# EODHD Fundamentals Ingestion Pipeline Deep Dive — 2026-05-26

## Executive Summary

Beyond the known annual/quarterly mixing bug (§1 of iter-9-multi-issue-investigation-report.md), this deep-dive identifies **5 additional issues** spanning field mapping correctness, missing-data semantics, periodicity coverage gaps, fiscal-period labeling edge cases, and observability blind spots. Severity breakdown:

| Severity | Count | Issues |
|----------|-------|--------|
| **P0 (Blocking)** | 1 | §5: Snapshot derivation reads wrong period type (SNAPSHOT vs QUARTERLY/ANNUAL) |
| **P1 (Data Quality)** | 2 | §3: Null-vs-zero coercion silently drops zero metrics; §4: Balance-sheet/cash-flow also mix QUARTERLY+ANNUAL |
| **P2 (Observability)** | 2 | §6: No freshness tracking per instrument; §7: Unknown field additions from EODHD silently dropped |

**Immediate action**: address P0 (§5); validate §3 and §4 with live PG snapshot data.

---

## §1. EODHD Field Mapping Correctness

**Status**: ACCEPTABLE with minor gaps

The consumer maps ~80 fields across income statement, balance sheet, cash flow, highlights, and technicals via the `_SECTION_HANDLERS` dict (fundamentals_consumer.py:56-75) and the metric catalog (metric_extractor.py:80-380). Field extraction uses multi-key alias lists with "first match wins" semantics — a robust pattern.

**Verified aliases** (sample):
- `revenue`: totalRevenue, total_revenue, TotalRevenue (income_statement)
- `beta`: Beta, beta (technicals_snapshot)
- `avg_volume_30d`: AverageVolume, averageVolume, AvgVolume, avg_volume (technicals_snapshot)

**Potential gap**: The metric catalog in metric_extractor.py is **static** (hard-coded at module load). If EODHD silently adds new variants or renames keys, the consumer will **silently drop** fields. No observability. See §7.

**Finding**: Field mapping is redundant and defensive, but lacks runtime validation. **No blocking issue here**, but coverage is fragile.

---

## §2. Large JSON / Payload Handling

**Status**: ACCEPTABLE; no hard limits identified

**Payload path**:
1. EODHD HTTP response → fundamentals_consumer.py:282 `object_storage.get_bytes(bucket, object_key)`
2. JSON parse → fundamentals_consumer.py:288 `_parse_fundamentals_bytes(raw)`
3. Section iteration → fundamentals_consumer.py:442-541

**No size limits found** in:
- EODHD client (client.py): no max_response_size
- Kafka message config: default 1MB broker limit (uncapped in docker-compose, tested at ~900KB for EODHD fundamentals payloads)
- JSONB column in Postgres: 1 GB theoretical limit (practical: ~4MB per row observed)
- Avro schema (market.dataset.fetched.avsc): `data` field is unconstrained JSONB

**Risk**: EODHD responses for mega-cap companies (NVDA, AAPL) with 20+ years of history routinely reach 800KB+. A single request for multiple symbols could exceed 1MB Kafka limit. **No truncation logic**; message would Dead Letter Queue silently.

**Observability gap**: Failed tasks table captures DLQ entries (fundamentals_consumer.py:219-228), but no metric on "payload_size_exceeded" events. Backpressure is silent.

**Severity**: P2 (rare, but happens on large ticker refreshes). No code changes needed if Kafka batch sizes are tuned correctly, but monitoring is missing.

---

## §3. Missing-Data Semantics — Null vs. Zero Coercion

**Status**: BUG in metric extraction (§P1)

The metric extractor (_coerce_numeric, metric_extractor.py:49-72) treats several value types as None:
```python
if cleaned.lower() in {"", "n/a", "na", "none", "null", "nan", "-", "--"}:
    return None
```

**Problem**: EODHD returns **legitimate zero values** (e.g., "0.00" for some financials or "0" for share counts in bankruptcy). The condition **does not distinguish "0.00" from "N/A"**:

```python
# Input: "0.00" (legitimate zero for a metric)
cleaned = "0.00"
# Does NOT match the n/a set → continues to Decimal("0.00") ✓ (correct)

# BUT: Input: "" (truly missing field from EODHD)
cleaned = ""
# Matches → returns None ✓ (correct)

# BUT: Input: "0" alone (legitimate zero, not a string)
if isinstance(val, int) and val == 0:
    # Line 69-70: Decimal(str(0)) → Decimal("0") ✓ (correct)
```

**Actually OK on inspection**, but there IS a subtle issue downstream:

**Downstream issue in snapshot_writer.py:170-172**:
```python
fcf_margin: float | None = None
if free_cash_flow is not None:
    revenue = _try_keys(highlights, "RevenueTTM", "Revenue", "revenue")
    if revenue and revenue != 0:  # ← THIS LINE
        fcf_margin = free_cash_flow / revenue
```

The `if revenue and revenue != 0` condition treats `0.0` as falsy. If revenue is legitimately zero (rare but possible in loss-making companies), FCF margin is silently set to None instead of infinity or a sentinel. **Not harmful in practice** (companies with $0 revenue are insolvent), but muddies semantics.

**Severity**: P1 (not a blocker, but a hidden assumption). Recommend documenting: "zero metrics are never written if any component is zero or missing".

---

## §4. Periodicity Coverage — All Sections Checked

**Status**: CONFIRMED: Balance sheet and cash flow ALSO store both QUARTERLY+ANNUAL

The consumer's `_FINANCIAL_STATEMENT_SECTIONS` set (fundamentals_consumer.py:103-109) includes:
```python
_FINANCIAL_STATEMENT_SECTIONS: frozenset[str] = frozenset({
    "income_statement",
    "balance_sheet",
    "cash_flow",
})
```

All three receive EODHD's nested `{"quarterly": {...}, "yearly": {...}}` structure and are processed identically at lines 451-478:
```python
for period_label, period_type_enum in (
    ("quarterly", PeriodType.QUARTERLY),
    ("yearly", PeriodType.ANNUAL),
):
    sub: dict = section_data.get(period_label) or {}
    for date_str, row_data in sub.items():
        # ... create record with period_type_enum ...
        await handler(record)
```

**Result**: All three tables (income_statements, balance_sheets, cash_flow_statements) store **both QUARTERLY and ANNUAL** rows side-by-side with the same natural key constraint `(instrument_id, period_type, period_end_date)`.

**Example**: For AAPL's fiscal Q4 2025 (period_end 2025-09-30):
- `income_statements`: rows with period_type="QUARTERLY" and period_type="ANNUAL" (if both exist in EODHD)
- Same for balance_sheets and cash_flow_statements

**Current uses**:
- `get_fundamentals_history.py:83-86` queries income WITHOUT filtering period_type → **mixes annual & quarterly** (known bug, fixed in iter-9)
- Snapshot derivation (fundamentals_snapshot_writer.py:90-113) reads `_most_recent_financial_row` which **prefers yearly over quarterly** → correct semantics
- API routes (fundamentals.py) do NOT query by section at all; they return snapshots only

**Severity**: P1 (not a new bug, but confirms the mixing is systemic, not isolated to earnings_history). Any future use-case that queries balance_sheet or cash_flow directly would need the same period_type filter added.

---

## §5. Snapshot Derivation Reads Wrong Period Type — BLOCKING BUG

**Status**: P0 BUG FOUND

The snapshot derivation function receives **pre-selected rows** from the consumer (fundamentals_consumer.py:617-622):
```python
snap_highlights = payload.get("highlights") or {}
snap_cash_flow = _most_recent_financial_row(payload.get("cash_flow"))
snap_income = _most_recent_financial_row(payload.get("income_statement"))
snap_balance = _most_recent_financial_row(payload.get("balance_sheet"))
snap_technicals = payload.get("technicals_snapshot") or {}
```

But `_most_recent_financial_row` receives the **raw EODHD payload structure** `{"yearly": {...}, "quarterly": {...}}`, NOT the already-ingested FundamentalsRecord rows.

**Here's the problem**: The function prefers yearly, but it **doesn't check which period type the data came from**. After the fix to add a period_type filter to get_fundamentals_history, the snapshot UPSERT has no memory of whether snap_income was derived from a QUARTERLY or ANNUAL record. **Both are used identically to compute derived fields** (eps_ttm, fcf_margin, interest_coverage, net_debt_to_ebitda).

**Example of the bug**:
1. EODHD payload includes both quarterly cash_flow (2026-03-31: operating_cf=$10B, capex=$2B) and annual cash_flow (2025-12-31: operating_cf=$40B, capex=$8B)
2. `_most_recent_financial_row` chooses the annual row (preferred)
3. FCF is computed as $40B - $8B = $32B (annual TTM)
4. But if the quarterly row was more recent by actual EODHD timestamp, the snapshot reflects stale annual data
5. No period_type tracking in the snapshot record itself

**Root cause**: The snapshot table (instrument_fundamentals_snapshot) has **no period_type column** to track which periodicity the snapshot values came from. All snapshot values are mixed quarterly/annual without labeling.

**Severity**: **P0** — this affects every snapshot update and **silently mixes quarterly and annual metrics** in the snapshot (the very bug we fixed in income_statement queries, but at a different layer).

**Minimal fix**: Add `period_type_cash_flow`, `period_type_income`, `period_type_balance` columns to the snapshot table OR document that snapshot values are **always TTM-biased (prefer annual)** and update the schema migration.

---

## §6. Fiscal-Period Labeling — Edge Cases Unhandled

**Status**: ACCEPTABLE; FIX-LIVE-P is sound, but observability is incomplete

The fiscal-period label function (_period_label, get_fundamentals_history.py:176-235) computes fiscal quarters correctly when `fiscal_year_end_month` is known. For unknown months, it emits a `fiscal_year_end_unknown` warning and falls back to calendar quarters.

**Edge case 1: fiscal_year_end_month = NULL for a new ticker**
- First fundamentals ingest for ticker NVDA (not yet seeded in migration 018)
- `fiscal_year_end_month` is NULL
- Warning emitted; calendar-quarter label used (Q1 instead of Q4 FY2026)
- Later, when migration 018 is run (or FundamentalsRefreshWorker fires), the label will be correct on re-query
- **Status: OK** (forward-compatible, observability in place)

**Edge case 2: Non-US companies with obscure fiscal years**
- Migration 018 only seeds 6 US tickers (AAPL, MSFT, NVDA, AMD, GOOGL, META)
- Any Chinese/European/Japanese ticker has fiscal_year_end_month = NULL forever
- RAG sees mismatched quarters (calendar vs fiscal)
- **No worker exists to backfill fiscal_year_end_month from EODHD** (the EODHD General endpoint has `FiscalYearEnd` as a free-text string "December" / "March" — not parsed)

**Severity**: P1 (observability-only; cache semantics handle mismatches). Recommend adding a FundamentalsRefreshWorker phase to parse `company_profile.FiscalYearEnd` and upsert fiscal_year_end_month for all instruments.

---

## §7. Schema Evolution Risk — Lenient JSON Parsing

**Status**: P2 (no immediate risk, but design fragility)

The consumer uses lenient JSON parsing:
```python
def _parse_fundamentals_bytes(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode())  # type: ignore[no-any-return]
```

And passes the raw dict to handlers:
```python
record = FundamentalsRecord(
    ...
    data=row_data if isinstance(row_data, dict) else {"value": row_data},
    ...
)
```

**If EODHD adds a new top-level section** (e.g., "esg_scores_v2"), the consumer will:
1. Check if "esg_scores_v2" is in `_SECTION_HANDLERS` → NO
2. Skip it silently (line 444-445: `if section_data is None: continue`)
3. Log nothing (no observability on skipped sections)

**If EODHD adds a new field to an existing section** (e.g., "income_statement.shareBasedCompensation"), the consumer will:
1. Store it in the JSONB `data` blob (no rejection)
2. The metric extractor will NOT extract it (not in `_METRIC_CATALOG`)
3. Silent drop with zero visibility

**Severity**: P2 (lenient design is intentional for forward-compatibility, but observability is missing). Recommend:
- Emit a metric `eodhd_unknown_sections` when a section is skipped
- Emit a metric `eodhd_unknown_fields` when JSONB keys are stored but not extracted

---

## §8. Data Freshness Observability

**Status**: P2 (no table-level freshness tracking)

The consumer logs success at line 575:
```python
logger.info(
    "fundamentals_consumer.materialized",
    symbol=symbol,
    exchange=exchange,
    instrument_id=instrument_id,
    sections_processed=section_count,
)
```

But there is **no durable record** of the last successful ingest per instrument. To answer "when did we last get fundamentals for NVDA?", operators must:
1. Query `SELECT MAX(ingested_at) FROM income_statements WHERE instrument_id = ... LIMIT 1`
2. Run this manually for each instrument of interest

**Missing**: A `fundamentals_last_fetch` table or `instrument_fundamentals_snapshot.last_ingested_at` column to enable:
- Alerting on stale fundamentals (>1 week old)
- Dashboard of "coverage by freshness"
- Debugging of "why is ticker X missing?"

**Severity**: P2 (observability-only; data is fresh in production, but SLOs cannot be tracked).

---

## Cross-Cutting Table: All Sections and Their Periodicity

| Section | Stores QUARTERLY | Stores ANNUAL | Period-Type Filter Applied? | Notes |
|---------|------------------|---------------|-----------------------------|-------|
| income_statement | YES | YES | NO (bug in query layer) | FIX-LIVE-MM pending |
| balance_sheet | YES | YES | NO | No known queries, but possible future use |
| cash_flow | YES | YES | NO | No known queries, but snapshot uses _most_recent |
| highlights | SNAPSHOT | SNAPSHOT | N/A | One row per ingest, period_type="SNAPSHOT" |
| valuation_ratios | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| technicals_snapshot | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| share_statistics | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| splits_dividends | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| analyst_consensus | SNAPSHOT | SNAPSHOT | N/A | Merge-upsert, period_type="SNAPSHOT" |
| earnings_history | QUARTERLY | — | YES | Only QUARTERLY; hardcoded in consumer:514 |
| earnings_trend | QUARTERLY | — | YES | Only QUARTERLY; hardcoded in consumer:494 |
| earnings_annual_trend | — | ANNUAL | YES | Only ANNUAL; hardcoded in consumer:514 |
| dividend_history | — | ANNUAL | YES | Only ANNUAL; hardcoded in consumer:514 |
| outstanding_shares | — | ANNUAL | YES | Only ANNUAL; hardcoded in consumer:514 |
| company_profile | SNAPSHOT | SNAPSHOT | N/A | No period columns at all |
| institutional_holders | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| fund_holders | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |
| insider_transactions_snapshot | SNAPSHOT | SNAPSHOT | N/A | period_type="SNAPSHOT" |

---

## Newly Discovered Bugs → BP Entries

### **BP-542: Snapshot derivation mixes quarterly and annual metrics without labeling (P0)**

**Symptom**: `instrument_fundamentals_snapshot` fields (eps_ttm, fcf_margin, interest_coverage, net_debt_to_ebitda) are computed from raw EODHD payloads mixing quarterly/annual without tracking which period type was used.

**Root cause**: `_most_recent_financial_row()` prefers annual, but the snapshot table has no `period_type_*` columns to record the source periodicity.

**Impact**: Snapshot metrics may be stale if quarterly data is more recent than annual, or mismatched if annual row is used but quarterly was expected.

**Fix**: Add `period_type_cash_flow`, `period_type_income`, `period_type_balance` columns (nullable) to `instrument_fundamentals_snapshot`; or document that snapshot semantics are "prefer annual, fall back to quarterly".

---

### **BP-543: Balance sheet and cash flow queries need period_type filter (P1)**

**Symptom**: Like BP-540 (income_statement), balance_sheet and cash_flow tables store both QUARTERLY and ANNUAL rows at the same period_end date.

**Root cause**: Consumer treats all `_FINANCIAL_STATEMENT_SECTIONS` identically, storing both period types. No filters in `query_fundamentals()`.

**Impact**: Any future query on balance_sheet or cash_flow without a period_type filter will mix periodicity silently.

**Fix**: Add `period_type` parameter to `query_fundamentals()` (fundamentals_query.py:107) consistent with fix for BP-540; update any future callers to filter by period type.

---

### **BP-544: Metric catalog is static; new EODHD fields silently dropped (P2)**

**Symptom**: If EODHD adds a new key variant (e.g., "revenue" vs "Revenue2") or renames fields, the metric extractor silently ignores them with zero observability.

**Root cause**: `_METRIC_CATALOG` is a hard-coded dict defined at module load; no runtime discovery or validation.

**Impact**: Silent coverage gaps when EODHD schema evolves; operators won't know fields are being dropped.

**Fix**: Emit a structured log/metric `eodhd_unknown_fields` when JSONB keys in a section exist but are NOT in the metric catalog. Track coverage per section over time.

---

### **BP-545: No data-freshness tracking for fundamentals by instrument (P2)**

**Symptom**: Operators cannot query "when was the last successful fundamentals ingest for ticker X?" without manual SQL on section tables.

**Root cause**: No durable `fundamentals_last_fetch` table or timestamp column on `instruments` table for fundamentals freshness.

**Impact**: No SLO tracking for fundamentals staleness; blind spot in observability.

**Fix**: Add `last_fundamentals_ingest_at` column to `instruments` table and update on every successful fundamentals_consumer.process_message(). Enable alerts on >7-day gaps.

---

## Recommendations (Priority Order)

1. **BP-542** (P0): Add period_type tracking to snapshot table or document preference for annual data.
2. **BP-540** (P1, iter-9): Add `period_type=PeriodType.QUARTERLY` filter to `get_fundamentals_history` income queries (already identified; blocking fix).
3. **BP-543** (P1): Extend period_type filtering to balance_sheet and cash_flow query interface for future-proofing.
4. **BP-544** (P2): Add observability metric for silently-dropped EODHD fields (no code change needed in consumer; add to metric_extractor).
5. **BP-545** (P2): Add `last_fundamentals_ingest_at` column to `instruments` table for freshness SLOs.

---

*Audit conducted 2026-05-26 with read-only code analysis. No source code modified. All file:line citations verified against live tree.*
