# F-DB-005 — Fundamentals Data-Shape Audit (end-to-end)

**Date**: 2026-05-28
**Branch**: feat/plan-0099-w4 → worktree-agent-ad2312a2 (Wave 3)
**Investigation source**: docs/audits/2026-05-28-inv-iter11-findings-rootcause.md (Finding 3)

## TL;DR

The fundamentals refresh worker at
`services/knowledge-graph/.../workers/fundamentals_refresh.py:_build_fundamentals_narrative`
read TOP-LEVEL keys (`revenue_usd_millions`, `pe_ratio`, `price`, ...) from the JSON
returned by `GET /api/v1/fundamentals/{instrument_id}`. The endpoint has
ALWAYS returned `{security_id, records: [{section, period_end, period_type,
data, ...}, ...]}` — a list of section records keyed by `section` with
sub-payload under `data` (NOT `payload`). Every `.get()` resolved to `None`;
`build_fundamentals_narrative()` fell through its "header-only" guard and
returned `None`. The worker's `or "unknown"` fallback then logged
`failure_reason="unknown"` for 488 entities every cycle.

## Stage 1 — Upstream (EODHD)

- Endpoint: `https://eodhd.com/api/fundamentals/{ticker}` (called by
  `services/market-ingestion`, not market-data; see
  `services/market-ingestion/scripts/backfill_fundamentals.py:254`).
- Raw top-level keys observed in EODHD response:
  - `General` (company profile)
  - `Highlights` (TTM — `MarketCapitalization`, `PERatio`, `EarningsShare`,
    `RevenueTTM`, `EBITDA`, `WallStreetTargetPrice`, ...)
  - `Valuation` (PriceBookMRQ, EnterpriseValue, ...)
  - `SharesStats` (SharesOutstanding, SharesFloat, ...)
  - `Technicals` (Beta, 52WeekHigh, 52WeekLow, Price, ...)
  - `SplitsDividends`
  - `Earnings.History`, `Earnings.Trend`, `Earnings.Annual`
  - `Financials.Income_Statement.{quarterly,yearly}` →
    `totalRevenue`, `netIncome`, `grossProfit`, `eps`, `ebit`, `ebitda`, ...
  - `Financials.Balance_Sheet.{...}`
  - `Financials.Cash_Flow.{...}`
  - `Holders.Institutions`, `Holders.Funds`
  - `InsiderTransactions`
  - For ETFs: `ETF_Data` (replaces Highlights/Valuation/Financials)

## Stage 2 — Ingestion (market-ingestion → market-data DB)

`services/market-ingestion/.../strategies/canonicalize.py:184-240` decomposes
the EODHD blob into 13 logical sections matching `FundamentalsSection` enum
(`services/market-data/src/market_data/domain/enums.py:63-69`):

| EODHD key                          | Section enum value          |
|-----------------------------------|-----------------------------|
| `Highlights`                      | `highlights`                |
| `Valuation`                       | `valuation_ratios`          |
| `Financials.Income_Statement`     | `income_statement`          |
| `Financials.Balance_Sheet`        | `balance_sheet`             |
| `Financials.Cash_Flow`            | `cash_flow`                 |
| `Technicals`                      | `technicals_snapshot`       |
| `SharesStats`                     | `share_statistics`          |
| `SplitsDividends`                 | `splits_dividends`          |
| `AnalystRatings`                  | `analyst_consensus`         |
| `Earnings.History`                | `earnings_history`          |
| `Earnings.Trend`                  | `earnings_trend`            |
| `Earnings.Annual`                 | `earnings_annual_trend`     |
| `General`                         | `company_profile`           |
| `Holders.Institutions`/`Funds`    | `institutional_holders`/`fund_holders` |
| `InsiderTransactions`             | `insider_transactions_snapshot` |

Storage: per-section tables in `market_data_db` (`HighlightsModel`,
`IncomeStatementModel`, ...). Domain entity `FundamentalsRecord`
(`market_data/domain/entities.py:167-185`) has fields:
`id, security_id, section, period_end, period_type, data, source, ingested_at`.
`data` holds the sub-payload for the section, preserved with EODHD key
casing (e.g. `MarketCapitalization`, `totalRevenue`, ...).

## Stage 3 — Market-data API response

`GET /api/v1/fundamentals/{instrument_id}` returns
`FundamentalsResponse` (`market_data/api/schemas/fundamentals.py:24-28`):

```python
class FundamentalsResponse(BaseModel):
    security_id: str
    records: list[FundamentalsRecordResponse]

class FundamentalsRecordResponse(BaseModel):
    id: str
    security_id: str
    section: str       # e.g. "highlights", "income_statement"
    period_end: datetime
    period_type: str   # "QUARTERLY" | "ANNUAL"
    data: dict[str, Any]   # ← NOT "payload"
    source: str
    ingested_at: datetime
```

Returns **404** if `records` is empty (no fundamentals ingested for that instrument).

Canonical example shape (simplified):

```jsonc
{
  "security_id": "<UUID>",
  "records": [
    {
      "section": "highlights",
      "period_end": "2026-03-31T00:00:00Z",
      "period_type": "QUARTERLY",
      "data": {
        "MarketCapitalization": 3.0e12,
        "PERatio": 28.0,
        "EarningsShare": 6.74,
        "RevenueTTM": 3.94e11,
        ...
      }
    },
    {
      "section": "income_statement",
      "period_end": "2026-03-31T00:00:00Z",
      "period_type": "QUARTERLY",
      "data": {
        "totalRevenue": 9.4e10,
        "grossProfit": 4.5e10,
        "netIncome": 2.4e10,
        "eps": 1.56,
        ...
      }
    },
    ...
  ]
}
```

Field-name map for the keys the narrative actually needs:

| Narrative arg              | section            | data key (preferred)                   |
|---------------------------|--------------------|----------------------------------------|
| `revenue_usd_millions`    | `highlights`       | `RevenueTTM` (÷ 1e6); fallback `income_statement.totalRevenue` |
| `gross_margin_pct`        | `income_statement` | `100 * grossProfit / totalRevenue` (latest) |
| `net_margin_pct`          | `income_statement` | `100 * netIncome / totalRevenue` (latest)   |
| `pe_ratio`                | `highlights`       | `PERatio` (fallback `peRatio`)         |
| `price`                   | `technicals_snapshot` / `highlights` | `Price`                              |
| `week_52_high`            | `technicals_snapshot` | `52WeekHigh`                        |
| `week_52_low`             | `technicals_snapshot` | `52WeekLow`                         |
| `description`             | `company_profile`  | `Description`                          |

## Stage 4 — Worker consumption (where it breaks)

The OLD worker code at `fundamentals_refresh.py:_build_fundamentals_narrative`
called `_safe_float(fundamentals, "revenue_usd_millions")` etc. on the
top-level dict — but the top-level dict contains only `{security_id, records}`.
All args resolved to `None`. The narrative builder's guard at
`fundamentals_narrative.py:86-89` returned `None` when only the header line
was assembled. The caller saw `narrative is None`, fell into the
`or "unknown"` branch, logged `failure_reason="unknown"`, incremented
`failure_counts["unknown"]`. The 488 occurrences across one cycle were the
F-DB-005:`unknown` bucket.

## Stage 5 — Ingestion gap (1100 canonical FIs vs 629 market-data instruments)

The 471-row delta is FI canonicals created by S6's enrichment path (NER /
canonicalisation in the news pipeline) whose tickers were never ingested into
`market_data_db.instruments`. Likely composition:
- Foreign-exchange tickers with `.L`, `.DE`, `.TO`, `.HK` suffixes
- Delisted tickers (no longer in market-ingestion's `active=true` filter)
- Long-tail or ad-hoc tickers that S6's `_build_raw_*` extracted from article
  text without a corresponding seed in market-ingestion

## Stage 6 — Who SHOULD be importing them?

The canonical → market-data ticker import path does NOT exist as an event-driven
contract today. Market-ingestion (S3) seeds instruments from a curated
symbol-list and EODHD's exchange-symbol endpoint. There is no Kafka event of
the shape "S6 created a new FI canonical for ticker X → please ingest X into
market-data".

**Recommendation (not in this commit's scope)**: emit a new
`fi.canonical.created.v1` event from S6 when a ticker'd financial-instrument
canonical is created, consumed by market-ingestion which probes
`/api/instruments/lookup` via EODHD and inserts on hit. This deserves its
own PRD because it touches S6 ↔ S3 boundaries and needs back-pressure for
the long-tail of speculative tickers.

For NOW, long-skip the 312 `instrument_lookup_failed` rows in
`entity_embedding_state` so they stop consuming worker cycles.

## Phase 2 Fix Plan (this commit)

1. `_build_fundamentals_narrative` walks `records[]` keyed by `section` and
   reads sub-fields from `data` (NOT `payload`).
2. Replace `or "unknown"` with structured `FundamentalsRefreshError` enum and
   `fundamentals_refresh_failed_total{error_kind=...}` Prometheus counter.
3. Rewrite the 2 lying stub fixtures in
   `test_fundamentals_refresh_worker.py:144-152, 514` to the real `records[]`
   shape. (R19: do not delete tests; rewrite them to assert the actual contract.)
4. Long-skip the 312 `instrument_lookup_failed` rows (SQL script).
5. Add contract test that asserts the worker can parse the canonical schema.
