# Fundamentals Tab QA + Finviz-Inspired Improvements

**Date:** 2026-05-09
**Author:** Senior Product Engineer (QA pass)
**Scope:** `/instruments/{id}` Fundamentals tab — root-cause analysis for the
five reported issues plus a Finviz/Stockanalysis-inspired improvement list.

---

## TL;DR

Five reported issues, all confirmed via live API testing against the running
S9 gateway. **Three are real bugs**, **one is dead code** (an explicit TODO
that was left in production), and **one is a UX papercut** that masks
real-but-uncommon nulls.

| # | Reported issue | Root cause | Severity | Fix |
|---|----------------|-----------|----------|-----|
| 1 | "Analyst consensus data unavailable" everywhere | `AnalystConsensusStrip` is a hardcoded placeholder; data is in the API response (`analyst_consensus` section), never rendered | **High** | Wire the existing data into the strip |
| 2 | Revenue / EPS charts showing 1985–1988 data | `query_timeseries` ignores `order` parameter; always sorts `ASC` and limits → returns the OLDEST 12 quarters | **Critical** | Honour `order=desc` in the query helper |
| 3 | Revenue Trend chart "looks floppy" | Caused by #2 — pre-IPO Apple revenue (under $1B/quarter) compresses the more-recent end of the chart, plus only 12 ancient bars rendered | **Critical** | Resolved by #2 |
| 4 | Financial table has "—" placeholders | Many fields ARE genuinely null in EODHD (e.g. `interest_coverage` is null for AAPL despite valid OCF/CapEx). UX shows "—" with a hover tooltip but the user reads it as a broken cell | **Medium** | Use "n/a" for fields globally unavailable from the data provider; keep "—" only for "missing for this ticker" |
| 5 | "Latest data not displayed even when available" | Confirmed root cause is #2 — when limit=12 and order ignored, the latest 36+ years of quarters are never returned. AnalystConsensus, Snapshot, Highlights all return current data correctly when the endpoint is honoured | **Critical** | Resolved by #2 + #1 |

---

## Live API evidence

```bash
TOKEN=$(curl -fsS -X POST http://localhost:8000/v1/auth/dev-login \
  -H 'content-type: application/json' \
  -d '{"email":"demo@worldview.local"}' | jq -r .access_token)
MD_ID="01900000-0000-7000-8000-000000001001"  # AAPL
```

### 1) Analyst consensus — data is present, UI ignores it

```bash
$ curl ".../v1/fundamentals/$MD_ID" \
   | jq '[.records[]|select(.section=="analyst_consensus")][0].data'
{
  "Buy": 6, "Hold": 15, "Sell": 1,
  "StrongBuy": 25, "StrongSell": 1,
  "Rating": 4.1042,
  "TargetPrice": 303.3762
}
```

Yet `components/instrument/AnalystConsensusStrip.tsx` renders unconditionally:

```tsx
<span className="text-[11px] text-muted-foreground">
  Analyst consensus data unavailable
</span>
```

The strip is a placeholder left from PRD-0031 Wave 5 with a `TODO(T-C-3-03)`
comment. **The data has been in the API for at least 6 weeks** — never wired up.

### 2 & 3) The 1980s dates bug — `order=desc` is silently ignored

```bash
$ curl ".../v1/fundamentals/timeseries?instrument_id=$MD_ID&metric=revenue&period_type=QUARTERLY&limit=12&order=desc" \
  | jq '.data[0:2]'
[
  { "as_of_date": "1985-09-30", "value_numeric": 409700000.0, ... },
  { "as_of_date": "1985-12-31", "value_numeric": 533900000.0, ... }
]
```

The frontend sends `order=desc` (see `lib/api/instruments.ts:354`):

```ts
...(params?.order ? { order: params.order } : {}),
```

The S3 router does not accept `order` (`api/routers/fundamental_metrics.py:46`).
The repo signature accepts it but the helper drops it
(`fundamental_metrics_read_repo.py:47`):

```python
order: str = "asc",  # accepted to match port signature; query helper ignores it.
del order
```

And `query_timeseries` always sorts ASC:

```python
.order_by(m.as_of_date.asc())
.limit(limit)
```

**Effect:** with `limit=12` we get `[1985, 1986, 1987, 1988]` and never see
the recent quarters. The chart renders 12 ancient bars; the latest bar is
~37 years old.

### 4) "—" placeholders mix two distinct cases

The audit/snapshot endpoint returns:

```bash
$ curl ".../v1/fundamentals/$MD_ID/snapshot" | jq
{
  "eps_ttm": 8.27,
  "operating_cash_flow": 111482000000.0,
  "capex": 12715000000.0,
  "free_cash_flow": 98767000000.0,
  "fcf_margin": 0.218,
  "interest_coverage": null,    # genuinely missing in EODHD for AAPL (interestExpense=null)
  "net_debt_to_ebitda": 0.478,
  "credit_rating": null         # globally not exposed by EODHD
}
```

`credit_rating` is **globally** unavailable (EODHD doesn't sell it on this
plan). The UI already renders "n/a" with an explainer tooltip. ✅

`interest_coverage` is **available for many tickers but null for AAPL** because
EODHD's income-statement record has `interestExpense=null`. The UI renders
"—" with the generic "Not available for this ticker" tooltip. This is
*technically correct* but visually identical to a generic dash, so users
read it as broken.

### 5) Main `/v1/fundamentals/{id}` is fine

The transformer in `lib/api/instruments.ts:260` correctly extracts
`market_cap=4308095467520`, `pe_ratio=35.468`, etc. from the `highlights`
section. **All numeric fields render correctly when the data is fetched.**
The "no latest data" symptom was a downstream artefact of the timeseries
bug — the chart-driven sections (Revenue Trend, EPS Trend) were the only
broken surfaces.

---

## Finviz-inspired improvement list

Finviz packs ~60 metrics on a single 1080px-wide screen using a tightly-packed
multi-column grid. Stockanalysis.com puts 6 fiscal years across columns with
TTM as the leftmost reference. Both treat unavailable cells with subtle muting,
not a bold dash.

### Adopted now (Wave 1 fixes — committed in this pass)

1. **Analyst Consensus strip** — coloured Buy/Hold/Sell stack bar with
   target-price delta vs. current price (Bloomberg BEST equivalent). Data
   was already there.
2. **Honour `order=desc` in timeseries** — fixes Revenue/EPS charts to
   render the most-recent 12 quarters instead of the oldest.
3. **Distinguish "n/a" vs "—"** — in the `Debt & Credit` and `Cash Flow`
   sections, render `n/a` (with a tooltip) when the data provider does not
   expose this field for *any* ticker; render `—` when this specific ticker
   lacks the value.

### Backlog (future waves — not committed in this pass)

4. **Income-statement table with FY columns** (Stockanalysis-style) — show
   Revenue / Gross Profit / Operating Income / Net Income / EPS as 5 rows ×
   6 fiscal-year columns. Data is already in `income_statement` records.
5. **Performance row** — Finviz packs week / 1M / 3M / 6M / 1Y / YTD price
   returns into a single 7-column strip. Today we only show daily return.
6. **Short interest row** — Float, Short Float %, Short Ratio, Short
   Interest. Available in `share_statistics` records.
7. **Inline analyst price-target distribution** — sparkline of analyst
   targets (range + median + current price). `TargetPrice` field is already
   exposed.
8. **Compact 2-column Performance section** — combine `daily_return`,
   `1M`, `3M`, `1Y`, `YTD` percentages into a single section instead of
   only daily.
9. **Earnings beat/miss markers** — colour the EPS Trend bars by surprise
   (actual vs. estimate); requires joining `earnings_history` (EODHD has
   both fields).

---

## Files changed in this pass

- `services/market-data/src/market_data/api/routers/fundamental_metrics.py`
  — accept `order` query param.
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py`
  — honour `order` in SQL.
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_read_repo.py`
  — propagate `order` instead of `del order`.
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx`
  — render real consensus data (Buy/Hold/Sell stack + target-price line).
- `apps/worldview-web/types/api.ts` — extend `Fundamentals` with
  `analyst_buy_count`, `analyst_hold_count`, `analyst_sell_count`,
  `analyst_strong_buy_count`, `analyst_strong_sell_count`,
  `analyst_target_price`, `analyst_rating`.
- `apps/worldview-web/lib/api/instruments.ts` — extract analyst_consensus
  section in `getFundamentals` transformer.
