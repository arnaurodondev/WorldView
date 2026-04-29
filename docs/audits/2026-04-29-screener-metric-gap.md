# Screener metric availability gap (PLAN-0051 Wave B Part 1, T-B-2-01)

**Date**: 2026-04-29
**Owner**: Frontend / Market Data
**Status**: Recorded — fixes deferred (Part 1 frontend ships with documented gaps)

## TL;DR

The PLAN-0051 Wave B filter bar requires **12 fundamental filters** plus **5 technical** plus **4 news/signals** filters. A walk of `services/market-data/src/market_data/infrastructure/db/metric_extractor.py` (`_METRIC_CATALOG`) and the `_screen_fields_refresh_loop` seed in `app.py` shows two important misalignments:

1. The `screen_field_metadata` table is **seeded with 12 aspirational field names** (`pe_ratio`, `revenue_usd`, `gross_margin_pct`, `net_margin_pct`, `ev_ebitda`, `debt_to_equity`, `return_on_equity`, `dividend_yield_pct`, `market_cap_usd`, `price_to_book`, `operating_margin_pct`, `current_ratio`). **None of these names are populated by the extractor** — the extractor uses different names (see table below).
2. Several metrics required by the plan (gross margin, debt/equity, current ratio, market cap in USD) are **not extracted as ratios** — only the underlying components are stored, so the screener's `WHERE metric = 'debt_to_equity'` query will always return zero rows on real data.

## Metric availability map (authoritative)

| Filter group | UI label | Plan name | Extractor metric (truth) | Status |
|---|---|---|---|---|
| Valuation | P/E | `pe_ratio` | `pe_ratio` | **OK** (extracted from `valuation_ratios.TrailingPE` and `highlights.PERatio`) |
| Valuation | P/B | `pb_ratio` / `price_to_book` | `pb_ratio` | **OK** (extracted from `valuation_ratios.PriceBookMRQ`) |
| Valuation | P/S | `price_sales_ttm` | `price_sales_ttm` | **OK** (`valuation_ratios.PriceSalesTTM`) |
| Valuation | Dividend yield | `dividend_yield_pct` | `dividend_yield` | **NAME MISMATCH** — use `dividend_yield`. Stored as decimal (e.g. 0.015), not pct. |
| Profitability | ROE | `return_on_equity` | `roe_ttm` | **NAME MISMATCH** — use `roe_ttm`. |
| Profitability | Gross margin | `gross_margin_pct` | _(none)_ | **GAP** — only `gross_profit_ttm` + `revenue_ttm` extracted. Ratio not computed. |
| Profitability | Net margin | `net_margin_pct` | `profit_margin` | **NAME MISMATCH** — use `profit_margin`. |
| Profitability | Operating margin | `operating_margin_pct` | `operating_margin_ttm` | **NAME MISMATCH** — use `operating_margin_ttm`. |
| Growth | Revenue YoY | `revenue_growth_yoy` | `quarterly_revenue_growth_yoy` | **NAME MISMATCH** — use `quarterly_revenue_growth_yoy`. |
| Growth | Earnings YoY | `earnings_growth_yoy` | `quarterly_earnings_growth_yoy` | **NAME MISMATCH** — use `quarterly_earnings_growth_yoy`. |
| Leverage | Debt/Equity | `debt_to_equity` | _(none)_ | **GAP** — `long_term_debt` + `total_equity` are extracted. Ratio not computed. |
| Leverage | Current ratio | `current_ratio` | _(none)_ | **GAP** — `total_current_assets` + `total_current_liabilities` are extracted. Ratio not computed. |
| Cap | Market cap | `market_cap_usd` | `market_capitalization` | **NAME MISMATCH** — use `market_capitalization`. |

## Technical filters

S3's `fundamental_metrics` table is fundamentals-only. Technical signals (above 50d MA, RSI, distance from 52W high/low, volume vs 30d avg) live in:
- `instrument_fundamentals_snapshot` — `beta`, `avg_volume_30d` (PLAN-0050 Wave D)
- OHLCV daily bars (S3 `ohlcv` table)

Per the plan brief, technical filters are accepted as **client-side fallback** for Part 1 — apply post-fetch using fields the screener already enriches via PRD-0017 quote enrichment (`current_price`, `daily_return`) plus the `beta` field. RSI, 52W range, MA50, volume-vs-avg are **client-side stubbed for now**.

## News & Signals filters

`news_velocity_7d`, `controversy_score`, `recent_earnings`, `insider_activity` are **not** in S3. These belong in S6 (signals) / S7 (knowledge graph) and would need new joins or a new endpoint. Marked client-side stub TODO.

## Recommended remediation (NOT done in Part 1)

1. **Fix the seed** (`services/market-data/src/market_data/app.py` `_seed_fields()`) so `screen_field_metadata.field_name` matches the extractor: rename `revenue_usd` → `revenue_ttm`, `dividend_yield_pct` → `dividend_yield`, `return_on_equity` → `roe_ttm`, `net_margin_pct` → `profit_margin`, `operating_margin_pct` → `operating_margin_ttm`, `market_cap_usd` → `market_capitalization`, `price_to_book` → `pb_ratio`. Drop `gross_margin_pct`, `debt_to_equity`, `current_ratio`, `ev_ebitda` (or compute them).
2. **Add a derivation step** in `backfill_fundamental_metrics.py` to compute and store `gross_margin`, `debt_to_equity`, `current_ratio` as their own metric rows.
3. **Extend snapshot** with technical fields (`rsi_14`, `dist_from_52w_high_pct`, `dist_from_52w_low_pct`, `volume_30d_ratio`) to support technical screeners server-side.
4. **Add S9 composed endpoint** that joins fundamentals screen + S6 signals (news velocity, controversy) + S7 (insider activity).

## How Part 1 frontend ships safely

- The filter bar uses the **truth column** (extractor metric names) so any value the user enters reaches a real metric in `fundamental_metrics`.
- For "GAP" filters (gross margin, debt/equity, current ratio), the request is **NOT** sent to S9 — the field input is rendered but a `disabled` overlay reads "Backend pending" (TODO badge). When the backend gains them, removing the badge is a one-line change.
- Technical and news filters apply post-fetch where the data field exists in the response, and are tagged `// CLIENT_SIDE_FILTER` inline so the eventual server-side migration is a 30-second find-replace.

## Reference

- `services/market-data/src/market_data/app.py` lines 36–161 (`_seed_fields()`)
- `services/market-data/src/market_data/infrastructure/db/metric_extractor.py` (`_METRIC_CATALOG`)
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py` (`query_screen`)
- PRD-0017 §6.4 (screen field metadata)
