# Cluster 7 — Chart, Technicals, Peer Comparison

> **Status**: open-questions resolution draft (2026-05-19)
> **Scope**: closes OQs from `05-instrument-quote.md` (1–6), master PRD-0089
> `OQ-D3`, `OQ-D10`, `OQ-D11`, `OQ-D12`, `OQ-D20`, and column-related OQs
> from `08-screener.md`. Defines backend additions B-Q-1 (peers),
> B-Q-2 (intraday stats), B-Q-3 (multi-period returns), B-Q-4 (price levels).
> **Reads first**: `05-instrument-quote.md`, `00-backend-data-inventory.md`,
> `08-screener.md`, `services/market-data/src/market_data/` (domain +
> use-cases), `apps/worldview-web/components/instrument/chart/` (chart stack),
> `apps/worldview-web/components/instrument/quote/metrics/MetricsTable.tsx`.

---

## 1. Cluster summary

Cluster 7 covers everything that lives in or under the Quote tab's chart
column: the OHLCV chart itself, its toolbars and indicators, the strips that
sit directly below it (multi-period returns, intraday stats), and the
bottom-left triple-strip (peers, price levels, "what's moving"). Eight
open questions block implementation across these surfaces.

The cluster splits into three families:

| Family | OQs in scope | Backend gap |
|--------|-------------|-------------|
| **Peers** (relative-valuation grid) | OQ-D10, `05` OQ-2 | B-Q-1 (`/peers`) |
| **Price levels & technicals** (pivots, MA50/MA200, S/R) | OQ-D11, `05` OQ-3 | B-Q-4 (`/price-levels`) |
| **Returns + history** (multi-period strip, IPO baselines) | OQ-D12, `05` OQ-4 | B-Q-3 (`/multi-period-returns`) |
| **Chart + indicators** (timeframe, log scale, MA toggles, viewport) | `05` OQ-6 | none (frontend only) |
| **Brief border** (visual treatment) | OQ-D3, OQ-D20, `05` OQ-1 (sentiment dot source) | none (visual) |
| **Intraday stats** (VWAP/ATR/GAP/PREM/SI) | `05` OQ (band) | B-Q-2 (`/intraday-stats`) |

All four backend additions are **read-only compositions** over data the
platform already persists (OHLCV bars, fundamentals.technicals_snapshot,
instrument.gics_*). No new persistence, no new Kafka topics. Each endpoint
is a thin S9 wrapper plus an S3 use-case; together they fit in one wave.

The biggest design lever in this cluster is **deciding NOT to compute
multiple variants per surface** (Camarilla + Classic + Demark; multiple
peer heuristics; multiple return anchors). We pick one canonical answer
per OQ and ship it. Power-user variants are deferred to a post-MVP
"settings" sub-wave.

---

## 2. Per-OQ deep dive

### 2.1 OQ-D10 — Peer ranking heuristic (`05` OQ-2)

**Question.** How do we pick the 5 peers shown in the `PeersStrip`
(bottom-left of the Quote tab)?

**Candidate heuristics.**

| ID | Approach | Pros | Cons |
|----|----------|------|------|
| A | Same GICS sub-industry + market-cap proximity (±50% bucket) | Industry-standard convention used by Bloomberg RV, Finviz; pure SQL on existing `instruments.gics_industry` + `fundamentals_snapshot.market_cap`; 100% deterministic; computable in <30 ms. | Misses cross-industry economic peers (e.g. AAPL ↔ MSFT live in different GICS sub-industries: "Technology Hardware" vs "Systems Software"). |
| B | Analyst-target correlation (peers whose consensus targets move in sync) | Captures market-implied peer groups Bloomberg RV-style. | Requires historical analyst-target snapshots (currently NOT persisted — only latest target is stored). Cold start: zero data for new instruments. Adds 6+ weeks of backend persistence work. |
| C | Beta clustering (peers with 1Y beta within ±0.2 of subject) | Captures co-movement directly. | Beta available only for ~30% of US listings in our `technicals_snapshot`. Same-beta peers can come from totally unrelated industries (drug-co with same beta as a regional bank is not a useful peer). |
| D | Manual curation (override DB for the top 10 mega-caps; algorithm fallback for the long tail) | Best UX for the instruments users actually visit. | Manual maintenance burden; doesn't scale to the global universe (~30k instruments). |
| E | Embedding cosine over company descriptions (S6 BGE-large already indexes them) | Captures semantic similarity ("electric-vehicle maker" → matches TSLA + RIVN + LCID even across sub-industries). | Cosine peer set varies session-to-session as embeddings drift; harder to explain to users; needs a new S6 endpoint. |

**Bloomberg RV reference.** Bloomberg's Relative Value screen uses GICS
industry + free-float-adjusted market cap as the spine, with manual
overrides on the top ~500 names. Most retail tools (Finviz, Yahoo,
Stockanalysis.com) implement variant of (A).

**Recommendation.** **Heuristic A with a small (B-Q-1.1) refinement** —
ship pure GICS sub-industry + market-cap proximity in the first wave;
add a manual override JSON file (curated ~50 top instruments) in a
follow-up sub-wave. Defer B / C / E indefinitely until we have
multi-quarter analyst-target history or a clear user complaint.

**Why this wins.** It costs ~30 ms server-side, has 100% coverage for
any instrument that has a GICS classification (≈ 92% of our universe),
and matches user expectations (every competitor does this). Spec for
the endpoint is in §3.

**Edge cases.**
- Instrument has no GICS classification (e.g. crypto ETF, OTC small-cap)
  → return empty list `{peers: []}`; the UI shows "No peers (sector
  unclassified)" muted row.
- Subject is itself a peer hit by the ±50% market-cap rule → exclude
  by `instrument_id <> :subject_id`.
- Fewer than 5 peers in the band → return whatever exists (don't pad).
- Subject is a mega-cap with no equivalent (e.g. only AAPL fits 3T cap
  band) → widen the bucket to ±75% then ±100% before giving up.

### 2.2 OQ-D11 — Pivot / price-level formula (`05` OQ-3)

**Question.** Which pivot/price-level system populates the
`PriceLevelsStrip` (R3/R2/R1/PIVOT/S1/S2/S3 + MA50/MA200)?

**Candidate systems.**

| System | Formula | Pros | Cons |
|--------|---------|------|------|
| **Classic floor-trader pivots** | `PP = (H+L+C)/3`; `R1 = 2·PP - L`; `S1 = 2·PP - H`; `R2 = PP + (H-L)`; `S2 = PP - (H-L)`; `R3 = H + 2·(PP-L)`; `S3 = L - 2·(H-PP)` | Universally recognised; computable from yesterday's daily bar; symmetric; "the" pivot system most charting tools use as default (TradingView "Pivot Points Standard" = classic). | Generic — provides no edge over what's already on TradingView. |
| Camarilla pivots | 4 levels: `R1 = C + 1.1·(H-L)/12`; multipliers 1.1/12, 1.1/6, 1.1/4, 1.1/2 | Popular with retail intraday traders; tighter R1/S1 levels are useful for mean-reversion entries. | Less familiar to long-horizon investors; R4/S4 levels rarely useful for the daily/weekly chart the Quote tab shows by default. |
| Demark pivots | `X = H+L+2C` if `C < O`, else `H+L+2C` with conditions on prev open; `R1 = X/2 - L`; `S1 = X/2 - H` | Captures intraday momentum direction. | Requires the PRIOR open (we don't persist it on daily bars). Asymmetric, harder to explain. |
| Bollinger / Keltner channels | Bands rather than discrete levels (e.g. `MA20 ± 2σ`) | Match the chart visually as bands. | Already drawn ON the chart by the existing BB indicator; would duplicate. The strip's purpose is **discrete labelled levels**, not bands. |
| Algorithmic S/R from price action | Detect swing highs/lows over last 90 sessions; cluster by proximity (≤ 2% bucket) | Reflects actual price memory; "real" support/resistance. | Requires server-side clustering pass; results are non-deterministic across timeframes; explainability suffers ("why is 218.40 support?"). |

**Bloomberg precedent.** Bloomberg's PV screen uses Classic floor pivots
as default with a Camarilla toggle. TradingView's "Pivot Points
Standard" defaults to Classic.

**Recommendation.** **Classic floor-trader pivots with R1/R2/R3 +
PIVOT + S1/S2/S3** plus MA50 / MA200 / 52W H / 52W L as extra levels.
This matches the wireframe in `05-instrument-quote.md` §4.1 exactly.
Add a future Camarilla toggle as a power-user setting once a user
asks for it. Algorithmic S/R is interesting but doesn't fit the
"discrete labelled level" UI pattern this strip needs.

**Storage strategy.** **Compute on read.** Every level in the strip is
a pure function of yesterday's daily bar + technicals_snapshot fields
we already have. The endpoint reads 1 OHLCV bar + 1 technicals row,
computes 9 floats, returns. Total latency: < 20 ms warm. No caching
worth the complexity — we already cache the response in TanStack
Query (`staleTime: 5 min`).

**Why not nightly cache.** Persisting 9 floats × 30k instruments
nightly costs a worker, a table, a migration, a backfill, and a
freshness gate — none of which pays back when the on-read cost is
20 ms.

**Edge cases.**
- Yesterday's bar missing (instrument hasn't traded recently, halted,
  delisted) → return `{levels: {}, reason: "no_recent_bar"}`; UI
  shows muted "Insufficient history for pivots".
- Today is the first session (IPO day) → return MA50/MA200 nulls but
  still compute pivots from today's open if H/L available; flag with
  `is_partial_session: true` in response.

### 2.3 OQ-D12 — IPO baseline for short-history instruments (`05` OQ-4)

**Question.** How do we render the 1Y / 3Y / 5Y cells of the
`MultiPeriodReturnsStrip` for an instrument with insufficient history?

**Candidate behaviours.**

| Option | Display | Pros | Cons |
|--------|---------|------|------|
| A | `—` (em-dash) | Consistent with every other missing cell in the redesign; quiet UI. | Hides that ANY data exists for the instrument; user has to compute "this IPO'd recently" themselves. |
| B | `since IPO (Xd)` with the value rendered for the available window | Communicates partial data; informative for new listings. | Mixed units in the strip ("1Y +31%" next to "since IPO 142d +18%") breaks visual symmetry. |
| C | Hide cell entirely (collapse the strip to whatever's available) | Tightest. | Layout jitter — strip width changes per instrument. |
| D | `n/a` muted | Self-explanatory. | More verbose than `—`; same info. |
| E | Render the available-window return + small superscript `*`; hover shows "Listed YYYY-MM-DD; window truncated" | Best of both worlds — informative AND symmetric. | Slightly more code; superscript marker can be missed on dense rows. |

**Secondary-listing edge case.** META started life as FB on the same
`instrument_id` (ticker change); GOOG / GOOGL share Alphabet history.
We treat ticker changes as continuous history because we key on
`instrument_id`, not on ticker; OHLCV bars survive the rename.

**True secondary listing** (e.g. an instrument re-listed after a
spin-off or LBO) is rare and out of scope for v1; treat it as
"insufficient history" until a user complains.

**Recommendation.** **Option A (`—`) as the default**, paired with a
hover tooltip on the strip explaining "Insufficient history for this
period — instrument listed YYYY-MM-DD". Defer Option E (superscript
marker) to a follow-up — the dash is the path of least surprise and
matches `05`'s loading-state rules ("each of 8 cells renders `—`").

**Why not show "since IPO".** The Quote tab is a triage surface
where the user is comparing this instrument against a mental model
("how did it do over 5Y?"). A truncated-window return there is
actively misleading — a +400% number over 142 days is not the same
information as a 5Y CAGR. Better to render nothing than the wrong
thing.

**Sentinel value.** Backend returns `null` (JSON `null`) for any
period whose anchor predates the first available daily bar; the
frontend renders `null` as `—`. Never return `0` or `-1` — both are
valid returns.

### 2.4 OQ — Multi-period returns endpoint shape (B-Q-3)

**Question.** What does `GET /v1/instruments/{id}/returns` return
exactly?

**Recommended periods.** 1D, 1W, 1M, 3M, YTD, 1Y, 3Y, 5Y, All.
(`05` wireframe shows 7; we add 3Y and All for symmetry with Koyfin —
they fit in the 22-px strip at 11 px font.)

**Anchor strategy.** **Prior trading-day close.** Reasoning:

- All multi-period returns should anchor to the same reference (the
  last completed trading day) so the user can compare 1D vs 1Y vs 5Y
  on the same as-of date. Mixing "last tick" for 1D and "prior close"
  for longer periods would yield apples-to-oranges values.
- During market hours, "last tick" is a moving target; the strip
  would jitter at every quote refresh. Anchoring to prior close
  freezes the strip until next session.
- Exception: while we're showing live quote data in the header,
  the strip's 1D cell shows `(price - prior_close) / prior_close`
  with `price` being the current quote — so it tracks the header.
  All other periods anchor to prior close on both ends.

**Annualised vs compound.** **Compound (cumulative percent).** Never
annualise on the strip — that requires user knowledge ("3Y CAGR
+12.4%" is different from "3Y total +42%"). Show the raw
period-to-period percent change with sign. Annualised CAGR is a
future power-user toggle.

**Computation.** For each period:

```
return_pct = (last_close - anchor_close) / anchor_close
```

where `anchor_close` is the close of the trading day closest to
(but not after) `today - period_lookback`. If the precise anchor
date wasn't a trading day, walk back to the prior trading day.

**Lookback calendar days** (calendar, not trading days — we walk to
nearest prior trading day):

| Period | Lookback |
|--------|----------|
| 1D | 1 calendar day |
| 1W | 7 |
| 1M | 30 |
| 3M | 91 |
| YTD | (today - Jan 1 of current year) in calendar days |
| 1Y | 365 |
| 3Y | 1095 |
| 5Y | 1825 |
| All | (today - first_bar_date) |

This matches the existing `GetPeriodMoversUseCase._PERIOD_TO_LOOKBACK_DAYS`
pattern in `services/market-data/src/market_data/application/use_cases/get_period_movers.py`.

### 2.5 OQ — Intraday stats endpoint shape (B-Q-2)

**Question.** What does `GET /v1/fundamentals/{id}/intraday-stats`
return, and how is it cached?

**Fields.**

| Field | Source | Compute |
|-------|--------|---------|
| `vwap` | intraday 1m bars (TODAY only) | `Σ(typical_price × volume) / Σ(volume)` where `typical_price = (H+L+C)/3` |
| `atr_14` | daily bars (last 14 sessions) | Wilder's smoothed ATR formula |
| `rsi_14` | daily bars (last 14 sessions) | Wilder's RSI |
| `gap_pct` | today's open vs prior close | `(open - prior_close) / prior_close` |
| `prev_close` | yesterday's daily bar | `close` |
| `premarket_high` | intraday 1m bars (today, 04:00–09:30 ET) | `max(high)` |
| `premarket_low` | intraday 1m bars (today, 04:00–09:30 ET) | `min(low)` |
| `postmarket_high` | intraday 1m bars (today, 16:00–20:00 ET) | `max(high)` |
| `postmarket_low` | intraday 1m bars (today, 16:00–20:00 ET) | `min(low)` |
| `short_interest_delta_pct` | `technicals_snapshot.ShortPercent` (this month) vs prior month value | persist prior-month snapshot in a new view (deferred — return `null` for v1) |

**Cache TTL.**

| Market state | TTL | Rationale |
|--------------|-----|-----------|
| Regular hours (09:30 – 16:00 ET) | **60 s** | VWAP drifts every minute; RSI/ATR move once per close. 60 s balances freshness and S3 load. |
| Pre-market / after-hours | **300 s (5 min)** | Lower update frequency; reduces upstream load. |
| Weekend / closed | **3600 s (1 h)** | Static. |

**SSE vs polling.** **Polling.** Reasons:
1. The Quote tab is not a trading screen; users don't watch the strip
   tick-by-tick.
2. SSE adds infrastructure (S10 subscription? S9 fan-out?) for a strip
   that's already invisible to most user sessions.
3. The 60-s polling cadence matches the existing quote-refresh hook
   already on the page — zero extra TCP churn (same connection pool).

**Behaviour during outage.** If intraday 1m bars are unavailable (S3
upstream stalled), return `{vwap: null, premarket_high: null, ...}` but
keep RSI/ATR/gap_pct populated (they only need daily bars). The UI
strip silently renders `—` for null cells.

### 2.6 OQ — Chart timeframe defaults & behaviours (`05` OQ-6)

**Defaults.** Looking at `OHLCVChart.tsx:41`:

```ts
const [timeframe, setTimeframe] = useState<Timeframe>("1D");
```

Today the chart defaults to **1D bars**. The competitor analysis in
`05` §1 shows mixed defaults: Bloomberg GP = 1Y daily, TradingView =
1Y daily, Finviz = small 1Y candle, Yahoo = 1D intraday.

**Recommendation.** **Default = 1Y of daily bars.** Reasons:
1. The Quote tab's primary task is triage ("where is price vs its 52W
   range?"), which the WeekRangeBar already shows but the chart
   should reinforce.
2. 1D intraday for an instrument you've just opened is rarely useful;
   users want context first, then drill in.
3. 1Y daily = ~250 bars, fits comfortably in `lightweight-charts`
   and is what every competitor uses as default.

**Viewport behaviour.** **Reset to latest on timeframe change.**
Reasons:
1. The fix in BP-376 (`OHLCVChart.tsx:73-79` `memoizedPlaceholder`)
   was about preventing accidental scroll to 1985; preserving viewport
   across timeframe changes would risk re-triggering similar bugs.
2. When the user switches from 5Y to 1D, the prior 5Y "left edge"
   makes no sense in 1D space.
3. Industry convention: every charting tool resets to "most recent
   bar visible" on timeframe switch.

**Indicators on by default.** Current state: `showVolume = true`,
MA50 / MA200 / VolMA20 / VWAPLine all `false`. Recommendation:
**leave as-is.** Adding more default overlays clutters the chart and
slows initial paint. Power users discover the toolbar within seconds.

**Y-axis: log vs linear.** Current: linear default (`logScale = false`).
Recommendation: **leave linear default; surface the LOG toggle in the
TimeframeToolbar prominently.** Reasoning:
- For 1D / 1W / 1M timeframes, linear is correct (price-action scale).
- For 1Y / 5Y / All, log is technically more correct (percent
  changes are the right axis). But a "smart" auto-switch on timeframe
  change is jarring and confuses users who learned the chart in
  linear; explicit toggle is safer.
- Power-user setting persisted to localStorage in a future sub-wave.

### 2.7 OQ — Chart performance budget

**Question.** What's the max bar count the chart can render? Do we
need pagination or aggregation?

**Lightweight-charts limits.** Verified comfortable up to ~100k bars.
Above ~250k bars the WebGL pipeline starts dropping frames on
underpowered hardware.

**Our worst case:**

| Timeframe | Window | Bars |
|-----------|--------|------|
| 1D daily | 5Y | ~1,260 |
| 1D daily | All (since 1980) | ~11,300 |
| 1H | 1Y | ~2,000 |
| 5m | 1M | ~5,800 |
| 1m | 1Y | ~98,000 |
| 1m | 5Y | ~490,000 ⚠ |

**Recommendation.**
- **1m × ≤ 1Y**: ship as-is (under the 100k threshold).
- **1m × > 1Y**: cap server-side at 100k bars; UI shows a "limited
  to 1Y of 1m bars" muted note in the chart corner.
- **All other timeframes**: ship unrestricted.
- **Aggregation pass**: defer to a v2 when a user actually requests
  multi-year 1m data; the use-case is institutional micro-structure
  research which our personas don't do.

**Volume profile overlay.** Removed in PLAN-0090 T-B-01. Should we
bring it back?

| Argument | For | Against |
|----------|-----|---------|
| Bloomberg has it on GP | Industry-standard for institutional | Bloomberg also has TPO, FootPrint, and 50 other things — not a strong precedent. |
| Finviz doesn't | One of our density anchors | Finviz is daily-only, not a chart tool. |
| TradingView has it as opt-in | Most retail users have seen it | It's opt-in there for a reason — clutter. |
| We removed it to slim chart code | Already gone | Re-adding undoes the cleanup. |

**Recommendation.** **Do not re-add in this cluster.** Document as
a deferred power-user feature; revisit if usage metrics on the
Quote tab show retention drop tied to chart shallowness.

### 2.8 OQ-D3 / OQ-D20 — Brief border style (`05` OQ-1 sentiment dot)

**Question (border).** Border treatment of the AI brief banner —
top-only 1 px / left-only 2-3 px / full 1 px box?

User constraint: **no rounded borders** (already encoded in
`_INDEX.md` palette rule). So whatever we ship must be a straight 1
px hairline.

**Candidates.**

| Style | Visual | Reads as | Bloomberg precedent |
|-------|--------|----------|---------------------|
| Top-only 1 px | Hairline above the banner only | Plain section divider | Used between sub-screens |
| Left-only 2 px | Vertical 2-px rail on the left edge | "Editorial annotation" / Bloomberg amber rail | Iconic Bloomberg "amber news rail" |
| Left-only 3 px | Slightly heavier rail | Same as 2 px but louder | Bloomberg uses 2–3 px |
| Full 1 px box | Bordered rectangle | "Card" — even without radius, reads as a contained block | Less Bloomberg, more Stockanalysis |
| Top-and-bottom 1 px | Two hairlines | "Band" | Rarely used |

**Recommendation.** **Left-only 2 px hairline** in `var(--accent-amber)`
(or the closest token in `_INDEX.md` — likely `text-warning` since the
palette is constrained). Reasons:
1. It is the iconic Bloomberg look — instantly communicates "this is
   editorial content, not raw data".
2. A left rail integrates with the strip-stack layout (the banner sits
   between header and chart; left rail doesn't compete with the chart
   border below).
3. 2 px is enough to be visible at 11 px font; 3 px feels like a
   button.
4. The user's PRD spec table (`docs/specs/0089-platform-page-redesign.md`
   line 392) already lists "Left-2px primary stripe" for OQ-D3 (brief
   on dashboard) and "Top-only 1px" for OQ-D20 (brief on instrument).
   We **reconcile** here by recommending **left-2px on both** so the
   brief reads identically across pages — better than the current
   inconsistency.

**Conflict with PRD spec table.** The spec table currently shows
OQ-D20 = "Top-only 1px". We propose to change OQ-D20 to match
OQ-D3 ("Left-2px"). Filed as a follow-up to the spec author.

**Question (sentiment dot source).** `WhatsMovingStrip` shows a
coloured dot per headline by sentiment. Where does the value come
from?

Looking at `00-backend-data-inventory.md` §1.3 and §3.3:

```json
"sentiment": "positive",
"impact_score": 0.87,
```

The `Article.sentiment` field exists on every news response shape
(`/v1/news/top`, `/v1/news/entity/{id}`, and on `bundle.top_news`).
Enum is `positive | negative | neutral | mixed | null`.

**Recommendation.** **Use `article.sentiment` directly** with the
following dot-color mapping:

| Sentiment | Dot | Token |
|-----------|-----|-------|
| `positive` | green | `text-positive` |
| `negative` | red | `text-negative` |
| `neutral` | grey | `text-muted-foreground` |
| `mixed` | amber | `text-warning` |
| `null` | hidden | — |

Fall-through behaviour when sentiment is `null`: render the row with
no dot (don't substitute neutral — the user must be able to tell
"absence of signal" from "explicit neutral signal").

No additional fetch needed — `bundle.top_news` already carries the
field per `00-backend-data-inventory.md` §3.3.

---

## 3. Peer endpoint spec (B-Q-1)

### 3.1 Route

```
GET /v1/instruments/{instrument_id}/peers
```

### 3.2 Query parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1–20) | 5 | Max peers to return |
| `expand` | enum (`basic` \| `valuation`) | `valuation` | `basic` returns only id+ticker+name; `valuation` adds P/E, market cap, return_1y, change_pct (used by the UI). |

### 3.3 Response

```json
{
  "subject_instrument_id": "01900000-0000-7000-8000-000000001001",
  "peers": [
    {
      "instrument_id": "01900000-0000-7000-8000-000000001002",
      "ticker": "MSFT",
      "name": "Microsoft Corporation",
      "exchange": "NASDAQ",
      "market_cap": 3120000000000,
      "pe_ratio": 32.4,
      "return_1y": 0.18,
      "change_pct": 0.0042
    }
    // … 4 more …
  ],
  "heuristic": "gics_industry_marketcap",
  "as_of": "2026-05-19T15:47:00Z",
  "fallback_widened": false
}
```

`fallback_widened` = true when the algorithm had to widen the cap
bucket from ±50% to ±75% or ±100% to reach `limit`. UI may show
a small "⚠ widened" pill to power users.

### 3.4 Backend implementation sketch

S3 use-case `GetPeersUseCase` (read-only):

```python
class GetPeersUseCase:
    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str, limit: int = 5) -> PeersResult:
        subject = await self._uow.instruments.get(instrument_id)
        if subject is None or subject.industry is None:
            return PeersResult(peers=[], heuristic="none", fallback_widened=False)
        cap = await self._uow.fundamentals_snapshot.get_market_cap(instrument_id)
        if cap is None:
            return PeersResult(peers=[], heuristic="gics_only", fallback_widened=False)
        for window in (0.5, 0.75, 1.0):
            peers = await self._uow.instruments.find_peers(
                industry=subject.industry,
                cap_min=cap * (1 - window),
                cap_max=cap * (1 + window),
                exclude=instrument_id,
                limit=limit,
            )
            if len(peers) >= limit:
                return PeersResult(
                    peers=peers,
                    heuristic="gics_industry_marketcap",
                    fallback_widened=window > 0.5,
                )
        return PeersResult(peers=peers, heuristic="gics_industry_marketcap", fallback_widened=True)
```

Repository `find_peers` runs a single SQL:

```sql
SELECT i.id, i.symbol, i.exchange, ...
FROM instruments i
JOIN fundamentals_snapshot f ON f.instrument_id = i.id
WHERE i.industry = :industry
  AND i.id <> :exclude
  AND f.market_cap BETWEEN :cap_min AND :cap_max
  AND i.is_active = true
ORDER BY ABS(f.market_cap - :subject_cap) ASC
LIMIT :limit;
```

Index requirement: `(industry, market_cap)` btree on the join. We
already have an `industry` index from PLAN-0017; add a composite
in the same migration as B-Q-1.

### 3.5 S9 proxy

Pure pass-through; injects auth and tenant context (no tenant
scoping — instruments are public reference data).

```python
@router.get("/v1/instruments/{instrument_id}/peers")
async def get_peers(instrument_id: str, limit: int = 5, _user: User = Depends(current_user)):
    return await s3_client.get_peers(instrument_id, limit=limit)
```

### 3.6 Caching

- S9: no cache (cheap upstream).
- Frontend TanStack Query: `staleTime: 24h`, `gcTime: 7d` per
  `05` §8.2.

---

## 4. Multi-period returns endpoint spec (B-Q-3)

### 4.1 Route

```
GET /v1/instruments/{instrument_id}/returns
```

### 4.2 Query parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `periods` | CSV of period names | `1D,1W,1M,3M,YTD,1Y,3Y,5Y,All` | Subset selector |
| `anchor` | enum (`prior_close` \| `last_tick`) | `prior_close` | See §2.4 reasoning |

### 4.3 Response

```json
{
  "instrument_id": "01900000-0000-7000-8000-000000001001",
  "ticker": "AAPL",
  "anchor": "prior_close",
  "anchor_as_of": "2026-05-16T20:00:00Z",
  "last_price": 245.33,
  "returns": {
    "1D": 0.0066,
    "1W": 0.0241,
    "1M": -0.0184,
    "3M": 0.0592,
    "YTD": 0.1430,
    "1Y": 0.3170,
    "3Y": 0.6212,
    "5Y": 1.8930,
    "All": 12.4540
  },
  "missing_periods": []
}
```

Missing-history behaviour (per §2.3 recommendation): return
`null` for any period whose lookback predates first bar, AND add the
period name to `missing_periods` so the UI can render a hover
tooltip.

```json
{
  "returns": {"1D": 0.012, "1W": null, "1M": null, ...},
  "missing_periods": ["1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y"],
  "first_bar_at": "2026-04-01T00:00:00Z"
}
```

### 4.4 Backend implementation sketch

S3 use-case `GetMultiPeriodReturnsUseCase`:

```python
_PERIOD_LOOKBACK_DAYS = {
    "1D": 1, "1W": 7, "1M": 30, "3M": 91,
    "1Y": 365, "3Y": 1095, "5Y": 1825,
    # YTD computed dynamically; "All" = first_bar
}

async def execute(self, instrument_id: str, periods: list[str], anchor: str) -> ReturnsResult:
    bars = await self._uow.ohlcv_read.get_recent_bars(instrument_id, timeframe="1d", days=1830)
    if not bars:
        return ReturnsResult(returns={p: None for p in periods}, missing_periods=periods)
    last = await self._latest_price(instrument_id) if anchor == "last_tick" else bars[-1].close
    today = bars[-1].bar_date
    out: dict[str, float | None] = {}
    missing: list[str] = []
    for p in periods:
        anchor_close = self._find_anchor_close(bars, p, today)
        if anchor_close is None:
            out[p] = None
            missing.append(p)
        else:
            out[p] = float((last - anchor_close) / anchor_close)
    return ReturnsResult(returns=out, missing_periods=missing, ...)
```

Reads from existing `ohlcv_read.get_recent_bars` — no new repo.

### 4.5 Caching

- S9: no cache.
- Frontend: `staleTime: 5min` per `05` §8.2 (matches anchor freshness).

---

## 5. Intraday stats endpoint spec (B-Q-2)

### 5.1 Route

```
GET /v1/fundamentals/{instrument_id}/intraday-stats
```

### 5.2 Response

```json
{
  "instrument_id": "01900000-0000-7000-8000-000000001001",
  "ticker": "AAPL",
  "as_of": "2026-05-19T15:47:00Z",
  "vwap": 216.71,
  "atr_14": 3.84,
  "rsi_14": 58.2,
  "gap_pct": 0.0021,
  "prev_close": 243.18,
  "premarket_high": 217.95,
  "premarket_low": 215.40,
  "postmarket_high": null,
  "postmarket_low": null,
  "short_interest_delta_pct": 0.012,
  "intraday_bars_available": true
}
```

Null-aware: any field for which underlying data is missing returns
`null`. `intraday_bars_available` flags whether 1m bars are
populated for today — UI uses this to hide premarket cells before
showing `—`.

### 5.3 Backend implementation sketch

Pure composition:

- VWAP: aggregate over today's 1m bars (existing `ohlcv_read`).
- ATR(14), RSI(14): existing technical libraries (S3 already
  computes these for the chart indicators — extract the function
  into a shared util).
- Gap: today's open vs prior close (2 bar reads).
- Premarket H/L: filter today's 1m bars by ET hour ∈ [4, 9.5).
- Postmarket H/L: filter ET hour ∈ [16, 20).
- Short-interest delta: deferred — return `null` until a
  monthly-snapshot worker lands.

S9 wrapper: pure proxy + 60-s in-memory cache during market hours
(reuse the existing `quote_cache` Valkey TTL pattern, key on
`intraday_stats:{instrument_id}`).

### 5.4 Caching

- S9: Valkey 60 s during market hours, 5 min otherwise, 1 h on
  weekends.
- Frontend: `staleTime: 60 s`.

### 5.5 SSE vs polling

**Polling.** Per §2.5: the strip is not a trading surface;
60-s polling is sufficient. No SSE infrastructure required.

---

## 6. Price levels endpoint spec (B-Q-4)

### 6.1 Route

```
GET /v1/fundamentals/{instrument_id}/price-levels
```

### 6.2 Response

```json
{
  "instrument_id": "01900000-0000-7000-8000-000000001001",
  "system": "classic_floor_pivots",
  "anchor_bar_date": "2026-05-16",
  "anchor_h": 244.20,
  "anchor_l": 240.85,
  "anchor_c": 243.18,
  "levels": {
    "R3": 225.40,
    "R2": 221.10,
    "R1": 218.85,
    "PIVOT": 216.40,
    "S1": 214.15,
    "S2": 211.90,
    "S3": 208.65,
    "MA50": 218.10,
    "MA200": 198.40,
    "WEEK52_HIGH": 237.49,
    "WEEK52_LOW": 164.08
  },
  "trends": {
    "MA50": "up",
    "MA200": "up"
  }
}
```

### 6.3 Backend implementation sketch

Reads:
1. Yesterday's daily bar (H/L/C) from `ohlcv_read`.
2. `technicals_snapshot` for MA50 / MA200 / 52W H / 52W L.

Computes the 7 classic pivots inline (see §2.2 formulas). Trends are
derived by comparing current MA value vs the value 5 sessions ago
(simple slope; positive = "up", negative = "down").

No persistence — pure computation per request.

### 6.4 Caching

- S9: no cache (computation is ~20 ms).
- Frontend: `staleTime: 5 min` per `05` §8.2 (pivots fixed during
  the session).

---

## 7. Chart behavior defaults (frontend-only, no backend change)

| Behavior | Default |
|----------|---------|
| Initial timeframe | **1Y** (changed from current 1D) |
| Initial Y-axis | **Linear** (kept) |
| Initial indicators | **Volume only** (kept) — MA50/MA200/RSI/MACD/BB are opt-in |
| Viewport on timeframe change | **Reset to latest bar** (kept) |
| Viewport persistence across page navigations | **Reset** (kept; `OHLCVChart` unmounts) |
| Crosshair sync between chart + volume sub-pane | **Yes** (kept; lightweight-charts native) |
| Compare overlay | **Removed** (per PRD-0088 §5) |
| Volume profile overlay | **Removed**, deferred (per §2.7) |
| Drawing tools | **Removed** (PLAN-0090 T-B-01) |
| LOG/LIN toggle | Visible in the TimeframeToolbar (kept) |

**Hotkeys** (already in place but documented here for completeness):

| Key | Action |
|-----|--------|
| `1` | Switch to 1D timeframe |
| `5` | Switch to 5D timeframe |
| `30` | Switch to 30D timeframe |
| `L` | Toggle log/linear (proposed addition) |
| `V` | Toggle volume sub-pane (proposed) |
| `M` | Cycle MA overlays (none → MA50 → MA50+MA200 → none) (proposed) |
| `F` | Fullscreen toggle (kept; existing) |

---

## 8. Recommended decisions table

| OQ | Decision | Notes |
|----|----------|-------|
| OQ-D10 (peer ranking) | **GICS sub-industry + market-cap ±50% bucket**; fallback widens to ±75% then ±100% | Future: manual curation override for top-50 instruments |
| OQ-D11 (pivot formula) | **Classic floor-trader pivots** (R1/R2/R3 + PIVOT + S1/S2/S3) | Future: Camarilla toggle in settings |
| OQ-D12 (IPO baseline) | **`—` em-dash for missing periods**; tooltip explains "Insufficient history; listed YYYY-MM-DD" | Frontend renders `null` from backend response |
| OQ-D3 (brief border, dashboard) | **Left-2px hairline in warning/amber tone** | Already in spec table |
| OQ-D20 (brief border, instrument) | **Left-2px hairline** (reconcile with OQ-D3) | **CHANGE** from current spec table "Top-only 1px" |
| `05` OQ-1 (sentiment dot source) | **`article.sentiment` field already in `bundle.top_news`** | No new fetch |
| `05` OQ-4 (return baseline) | Same as OQ-D12 | — |
| `05` OQ-6 (sticky strips) | **Non-sticky** for now (whole left column scrolls together) | Revisit after live testing |
| Chart default timeframe | **1Y** (was 1D) | Matches Bloomberg/TradingView; better triage |
| Chart viewport on tf change | **Reset to latest** (kept) | BP-376 prevention |
| Chart performance | Cap 1m × > 1Y server-side at 100k bars | Defer aggregation pass to v2 |
| Volume profile overlay | **Do not re-add** | Defer indefinitely |
| Multi-period anchor | **Prior-trading-day close** | Consistent across periods |
| Intraday cache TTL | **60s market hours / 5min after-hours / 1h weekend** | Polling, no SSE |

---

## 9. Backend additions required

| ID | Endpoint | Owning service | Estimate | Migrations | New worker |
|----|----------|----------------|----------|------------|------------|
| **B-Q-1** | `GET /v1/instruments/{id}/peers?limit=5` | S3 + S9 wrapper | M (1 sub-wave) | 1 migration: composite index `(industry, market_cap)` on `instruments` + `fundamentals_snapshot` join | none |
| **B-Q-2** | `GET /v1/fundamentals/{id}/intraday-stats` | S3 + S9 wrapper | S (sub-wave) | none | none (short-interest delta deferred) |
| **B-Q-3** | `GET /v1/instruments/{id}/returns?periods=...` | S3 + S9 wrapper | S | none | none |
| **B-Q-4** | `GET /v1/fundamentals/{id}/price-levels` | S3 + S9 wrapper | S | none | none |

**Combined effort estimate**: 1 wave (4 small/medium sub-tasks). All
four endpoints can share a single PR since they touch the same
service layers (`market-data` use-cases + S9 routers).

**Schema impact**: zero new tables, one new index. No Kafka events.
No frontend type-generation surprises.

**Test plan (per endpoint)**:
- Use-case unit test: deterministic input → expected math.
- Repo integration test: SQL hits the right index (EXPLAIN check).
- API contract test: schema matches Pydantic response model.
- S9 proxy test: auth required (or not), tenant scoping (none).
- Frontend Vitest: hook fetches + caches + handles loading/error/empty.
- Playwright (smoke): Quote tab renders all 4 surfaces above the fold.

---

## 10. Follow-up open questions

These surfaced during the cluster investigation and are deferred.

1. **Bring back analyst-target history.** OQ-D10 heuristic B (analyst
   correlation) would unlock a more sophisticated peer ranking, but
   requires multi-quarter snapshot persistence. Filed as a backend
   exploration for the post-MVP roadmap. **Owner**: data-platform.
2. **Camarilla pivot toggle.** Once OQ-D11 ships with Classic, add a
   `?system=camarilla` query parameter to B-Q-4 and a settings toggle
   in the chart toolbar. **Owner**: frontend.
3. **Short-interest delta persistence.** B-Q-2 returns `null` for
   `short_interest_delta_pct` until we persist a monthly snapshot
   table. **Owner**: market-data service.
4. **Volume profile overlay re-introduction.** Deferred; revisit if
   product metrics show chart-shallowness affecting Quote tab
   retention. **Owner**: product + frontend.
5. **CAGR (annualised) returns.** Compound (cumulative) returns ship
   in v1; CAGR is a future toggle. **Owner**: frontend.
6. **Sentiment dot when `article.sentiment` is null.** We render no
   dot. Should we instead fall through to a default-grey "unknown"
   dot? Trade-off: explicit absence vs. dot-position consistency.
   **Owner**: product call.
7. **Brief border reconciliation in PRD spec.** OQ-D20 currently
   reads "Top-only 1px" in `docs/specs/0089-platform-page-redesign.md`
   line 409; this doc recommends "Left-2px" to match OQ-D3. Filed as
   a spec-table fix. **Owner**: PRD author.
8. **Index cost of `(industry, market_cap)` composite.** The
   composite index for B-Q-1 adds ~80 MB to `instruments` storage
   (estimate for 30k rows). Acceptable but worth confirming with
   DBA. **Owner**: data-platform.
9. **Peer set for ETFs / non-equity instruments.** Heuristic A
   requires `gics_industry`; ETFs typically have a fund-category
   tag instead. Deferred — ETFs don't show the Quote tab today.
   **Owner**: instrument-domain model.
10. **Pivot levels for futures / FX instruments.** Classic pivots
    assume equity OHLC semantics. Different markets may want
    different formulas. Deferred — non-equity surfaces are out of
    scope for PRD-0089. **Owner**: product.

---

**End of Cluster 7 design.**
