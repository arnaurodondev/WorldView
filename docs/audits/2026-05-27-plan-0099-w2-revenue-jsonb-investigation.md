# PLAN-0099 W2 T-W2-03 — Revenue JSONB Empty-Data Investigation

**Date**: 2026-05-27
**Author**: agent (T-W2-03 deferred-fix scope)
**Audit ref**: PLAN-0098 W2 §A5 ("revenue JSONB hydration bug").
**Verdict**: **Symptom does not reproduce on live DB.** Audit §A5 appears to conflate two different EODHD sections. **No fix shipped. Deferred to PLAN-0100** for re-scoping.

## Live evidence (collected 2026-05-27)

### `earnings_history` table — empty/null check

```sql
SELECT count(*) AS total,
       count(*) FILTER (WHERE data IS NULL) AS data_null,
       count(*) FILTER (WHERE jsonb_typeof(data) = 'object' AND data::text = '{}') AS data_empty_obj
FROM earnings_history;
```

Result:

| total | data_null | data_empty_obj |
|---|---|---|
| **55,360** | **0** | **0** |

Zero offending rows.  The audit's stated symptom (`data = {}` or `data IS NULL`) does not exist in the live DB.

### `earnings_history` actual JSONB key shape

```sql
SELECT jsonb_object_keys(data) AS k, count(*)
FROM earnings_history GROUP BY k ORDER BY count(*) DESC;
```

| key | count |
|---|---|
| `currency` | 55,360 |
| `epsActual` | 55,360 |
| `beforeAfterMarket` | 55,360 |
| `epsDifference` | 55,360 |
| `date` | 55,360 |
| `epsEstimate` | 55,360 |
| `surprisePercent` | 55,360 |
| `reportDate` | 55,360 |

Every row is fully populated with **8 EPS-related fields**.  Crucially, there is **no `revenue` key** in any row and there never should be: EODHD's `earnings_history` endpoint returns EPS announcements only — revenue belongs to the `income_statement` section, a separate EODHD payload tree handled by a different branch of `fundamentals_consumer.py` (the `_FINANCIAL_STATEMENT_SECTIONS` branch at lines 451-478, not the `_DATE_KEYED_SERIES_SECTIONS` branch at lines 504-526 that handles `earnings_history`).

### Revenue cross-check on `income_statements`

```sql
SELECT count(*) FILTER (WHERE data ? 'totalRevenue') AS has_totalRevenue,
       count(*) FILTER (WHERE data ? 'revenue') AS has_revenue,
       count(*) FILTER (WHERE data IS NULL OR (jsonb_typeof(data)='object' AND data::text = '{}')) AS empty,
       count(*) AS total
FROM income_statements;
```

| has_totalRevenue | has_revenue | empty | total |
|---|---|---|---|
| **86,059** | 0 | **0** | **86,059** |

Every income-statement row carries `totalRevenue` (EODHD's canonical key — `revenue` is never used).  Zero empty/null payloads.

## Consumer-code review

`services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`:

- **L443**: `section_data = payload.get(section_key)` — silent default `None` (no exception). If EODHD omits a section, the consumer skips it cleanly via the L444 `if section_data is None: continue` guard — no empty-`{}` row is written.
- **L504-526** (`_DATE_KEYED_SERIES_SECTIONS` branch handling `earnings_history`): `data=row_data if isinstance(row_data, dict) else {"value": row_data}` — empty `{}` could only be written if EODHD sent an explicitly empty row dict, which the live data shows never happens.
- **L451-478** (`_FINANCIAL_STATEMENT_SECTIONS` branch handling `income_statement`): identical defensive pattern; same conclusion.

No silent field-drop bug found.  The dispatcher's only failure mode is **skipping** an absent section (correct behaviour) — it never **writes** an empty row.

## Root-cause hypothesis

The PLAN-0098 W2 §A5 audit entry **misidentifies the section**:

1. **Wrong table** — `earnings_history` was never expected to carry `revenue`; revenue lives in `income_statements`.  Querying `earnings_history` for an absent field will always show "missing".
2. **Wrong field name** — even on `income_statements`, EODHD's canonical key is `totalRevenue`, not `revenue`.  A downstream reader that expects `data->>'revenue'` will see `NULL` on **every** row, which mimics the "empty data" symptom from an API-contract perspective.
3. **No live empty-row bug exists** in either table; revenue hydration on the **producer/consumer side** is healthy.

The actual gap (if there is one) is likely on the **reader side**: a frontend or API consumer that asks for `data->>'revenue'` and gets nothing.  That is **not** a `fundamentals_consumer.py` bug.

## Fix sketch (NOT shipped)

If a downstream reader actually expects `revenue` to be populated on `earnings_history`, the correct fix is **not** in the consumer.  Options:

- **A. Reader-side**: change the reader to `JOIN income_statements ON instrument_id` and read `data->>'totalRevenue'`.
- **B. Cross-section enrichment**: extend `_upsert_metrics_for_record` (L134-150) to compute a derived `revenue` field on `earnings_history` rows by looking up the matching `income_statements` row for the same `period_end`.  Adds coupling between two repos; needs a PRD-level decision.
- **C. Alias**: keep `totalRevenue` as the JSONB key; add a SQL view `earnings_with_revenue` exposing both tables.

All three are PRD-scope, not bug-fix-scope.

## Regression-test sketch (deferred)

If Option B is chosen, the regression test would be in
`services/market-data/tests/unit/infrastructure/messaging/consumers/test_fundamentals_consumer_revenue_hydration.py`:

- Fixture: realistic EODHD payload with both `earnings_history` and `income_statement` sections for the same instrument.
- Assert: after ingestion, every `earnings_history` row for that instrument carries the matching quarter's `totalRevenue` value (joined from `income_statements`).

For Option A/C, no consumer-side test is needed — the fix is in the reader.

## Decision

- **No code change shipped under PLAN-0099 W2 T-W2-03.**
- **BP-595** ("revenue Avro field mapping") **WITHDRAWN** — the bug pattern does not exist as described.
- **Deferred to PLAN-0100**: re-scope §A5 as a reader-side gap once the actual failing query/UI surface is identified.  The PLAN-0098 W2 §A5 entry should be amended to cite the **reader** site that returns no revenue, not the consumer.

## Files referenced

- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py` lines 442-541 (dispatcher).
- `docs/plans/0099-iter-9-final-followups-plan.md` lines 453-479 (T-W2-03 spec).
