# Market-Data Fundamentals Coverage Gap — Investigation

**Date**: 2026-06-14
**Scope**: S3 market-data instrument/fundamentals coverage vs KG ticker'd universe
**Mode**: Read-only investigation (no code/DB mutations; R42 — sibling sessions active on KG/PLAN-0109)

---

## 1. Why coverage is ~646 — the actual selection logic

market_data does **not** select instruments from the KG. Instruments enter market_data
only when **market-ingestion (S2)** fetches a dataset for a symbol and emits
`market.dataset.fetched`; the `FundamentalsConsumer` then materializes fundamentals and
emits `InstrumentCreated` (gated on a real EODHD `Name`).

The symbol universe is therefore whatever **`ingestion_db.polling_policies`** covers:

| dataset_type | distinct symbols |
|---|---|
| ohlcv | 645 |
| **fundamentals** | **523** |
| market_cap | 101 |
| insider_transactions | 100 |

These policies were seeded by migrations (`0002_initial_seeds`, `0014_sp500_universe_expansion`
~440 S&P names, `0011` Alpaca-50) plus the market-cap / insider universe loaders. The KG's
news-discovered tickers are **never wired into `polling_policies`**, so they are never fetched.

Two workers exist but **neither expands the fundamentals universe**:
- `services/market-ingestion/.../workers/fundamentals_refresh_worker.py` — runs every 6h, but
  its symbol source is `GET /internal/v1/instruments/top-by-market-cap` (top-N=500) **of
  instruments already in market_data**. It only *refreshes* existing rows (live logs:
  `symbol_count=500` per tick). It cannot pull a ticker market_data has never seen.
- `services/market-ingestion/.../workers/instrument_policy_sync_worker.py` — only adds **Alpaca
  1m OHLCV** policies for already-known US/CC instruments (live `created=0`). Not fundamentals.

> NOTE: `services/market-data/.claude-context.md` BP-578 ("No active fundamentals refresh
> worker exists") is **stale** — the worker landed in PLAN-0099 W2 / PLAN-0100 W4 and is ON by
> default. It refreshes, it does not expand. The context file should be updated.

`OnDemandProfileUseCase` (`services/market-data/src/market_data/application/use_cases/on_demand_profile.py:184`)
calls EODHD `get_fundamentals()` but **only extracts `General` (description/sector/industry)
into `securities`** — it does NOT materialize the 18 fundamentals tables, and it raises
`InstrumentNotFoundError` for any ticker not already in market_data (line 247). So it is not a
lazy-fundamentals path for uncovered tickers.

Live key is a **real paid EODHD key** (`667bca96…`, not `demo`), so BP-114 (demo silent-`[]`)
does not currently apply.

---

## 2. Universe breakdown (live, 2026-06-14)

market_data: **646 instruments**, **637 `has_fundamentals=true`** (644 have ≥1
`fundamental_metrics` row; 646 have a snapshot row). By exchange:
`US 600 (595 fund) · CC 29 · INDX 11 (7) · FOREX 6`.

KG ticker'd financial_instrument entities: **2,202 distinct tickers** (of 4,758 FI total).
Exchange hint present on only 659 of them (1,543 have NULL exchange — pure news extraction).

Cross-reference (symbol-level match, exchange-agnostic):

| Category | Count |
|---|---|
| KG ticker'd FI total (distinct) | **2,202** |
| (a) in market_data **WITH** fundamentals | **637** |
| (b) in market_data **WITHOUT** fundamentals | **7** (4 index, 3 equity-ish) |
| (c) **ABSENT** from market_data | **1,558** |

Split of the 1,558 absent:

| Bucket | Count | Fetchable fundamentals? |
|---|---|---|
| crypto (`-USD`, CC, BTC/ETH/…) | 18 | No (no real fundamentals by nature) |
| foreign-listed (`.HK .T .KS .SS .SZ .MI .F .TO .PA .DE …` + numeric KR/CN codes) | 244 | Only if EODHD plan includes those exchanges; non-US |
| **US-like (no exchange suffix, alpha)** | **1,295** | Plausibly EODHD-fetchable US equities |
| └ of which clean US-shape (1–5 alpha) | 1,270 | Best backfill candidates |
| └ noisy/foreign-mislabeled (`1COV`, `ADYEN`, `SUNPHARMA`, `GS-PA`, `SX5E`…) | 25 | Mostly junk / foreign |

**Interpretation**: the real "didn't fetch but could" gap is ~**1,270 US-shaped equity
tickers** discovered from news. The remaining ~280 (crypto + foreign + noisy) are
"can't/shouldn't fetch" — either no fundamentals exist or they need non-US exchange coverage.

---

## 3. Quality-critical subset — held + watchlisted

- Holdings: **10 distinct instrument_ids**. Watchlist: **9 instrument_ids / 9 tickers** (a
  subset of the held set).
- All 10 (AAPL, AMZN, DIS, GOOGL, JPM, META, MSFT, NFLX, NVDA, TSLA) exist in market_data with
  `has_fundamentals=true` **and** ≥1 `fundamental_metrics` row.

**The quality-critical subset is 100% covered.** The practical brief-quality gap is **only the
long tail of news-discovered tickers a user might navigate to** — not anything held/watchlisted.

This means the ~13% per-entity `fundamentals_ohlcv` description fill rate is dominated by the
1,558 absent KG tickers, the overwhelming majority of which are tickers no demo user holds,
watches, or is likely to open a brief for.

---

## 4. Feasibility of expansion + cost notes

- **No market_data-side mechanism expands coverage.** The lever is `polling_policies`
  (market-ingestion) or the refresh worker's symbol source — both **out of this task's scope**
  (R42: market-data files only; sibling on PLAN-0109 / KG workers).
- A full backfill of ~1,270 US tickers is **one EODHD fundamentals call each** (the worker
  serializes one symbol at a time with 4× exponential backoff on 429). At EODHD paid limits
  (typ. 1,000 req/min, daily quota by plan) this is a few minutes of wall-clock but consumes
  ~1,270 fundamentals credits + ongoing 6h refresh credits forever after. Cost is real but
  bounded; the risk is the **recurring** refresh cost once these become part of top-N.
- `POST /api/v1/fundamentals/batch` (market-data) caps at 25 tickers and only *reads* existing
  data — it is not an ingestion path.

---

## 5. Why no code change was made

The only safe, bounded fix the task contemplated — "ensure all held/watchlisted instruments
have fundamentals" — is **already satisfied** (§3). Every other expansion path requires editing
**market-ingestion** (polling-policy seeding or the refresh worker's symbol source), which is
explicitly off-limits this session (sibling sessions active; R42). Implementing universe
expansion also carries EODHD cost/rate-limit risk that the task says to avoid doing blindly.
Therefore: **plan, not patch.**

---

## 6. Ranked plan to expand coverage safely

### P0 — Update stale context (market-data, safe, in-scope)
- Fix `services/market-data/.claude-context.md` BP-578: the refresh worker now exists but only
  *refreshes top-N existing* instruments; it does **not** expand the universe. (Left for a
  committed change; this session leaves it documented here.)

### P1 — Bounded KG-driven universe expansion (market-ingestion — needs its own session)
- Add a worker/loader in **market-ingestion** that reads the KG ticker'd FI universe (via S9 or
  an internal endpoint — **not** cross-service DB, R9) and inserts **fundamentals + ohlcv-eod
  `polling_policies`** for the **US-shaped, exchange-NULL, clean (1–5 alpha)** subset (~1,270),
  *filtered* through a one-time EODHD existence probe to drop delisted/foreign-mislabeled names.
  - Throttle: reuse the refresh worker's 4× backoff; cap inserts per tick (e.g. 100/run) so the
    first full pass spreads over several hours and never bursts EODHD.
  - Idempotent `ON CONFLICT DO NOTHING` (same pattern as `instrument_policy_sync_worker`).
  - Bound recurring cost: keep these at a **lower refresh tier** so they don't inflate the 6h
    top-500 refresh every cycle.

### P2 — Lazy on-demand fundamentals on first brief request (cross-service)
- Extend the brief/instrument path so that when a brief is requested for a ticker **absent**
  from market_data, S9 fires a single market-ingestion `fundamentals` trigger (async,
  fire-and-forget, deduped) so coverage grows by actual user demand rather than a blind
  backfill. This naturally caps cost to tickers users actually open. Requires a new market-data
  "is-covered?" probe + S9 wiring (out of market-data-only scope).

### Explicitly out of scope (do NOT do)
- Backfilling crypto/FX/index "fundamentals" (no real data).
- Backfilling foreign-suffixed tickers without confirming EODHD exchange coverage.
- Any unthrottled fan-out of all 1,558 absent tickers.

---

## Evidence appendix (commands run)

- market_data counts: `psql market_data_db` — 646 instruments / 637 has_fundamentals / 644
  distinct in `fundamental_metrics`.
- KG universe: `psql intelligence_db` `canonical_entities` — 2,202 distinct ticker'd FI.
- Held/watchlist: `psql portfolio_db` `holdings` (10) + `watchlist_members` (9) → all 10
  instrument_ids resolve in market_data with fundamentals.
- polling_policies: `psql ingestion_db` — 523 distinct fundamentals symbols.
- Refresh worker live logs: `symbol_count=500` per 6h tick (refresh of existing top-N only).
