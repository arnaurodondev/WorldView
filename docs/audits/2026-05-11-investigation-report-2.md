# Investigation Report: Multi-Issue Frontend + Pipeline (2026-05-11 Session 2)

**Date**: 2026-05-11
**Investigator**: Claude (investigation skill)
**Status**: Root causes identified; fixes applied

---

## 1. Issue Summary

Six issues investigated:
1. Day P&L in KPI strip vs DayPnLDistribution strip show different values
2. AI Signals component looks "sloppy"
3. Sector performance heatmap has many empty/flat tiles despite hundreds of tickers
4. Better alternatives or visual improvements for MarketSnapshot widget
5. HoldingLotsPanel UNREAL column spacing wrong; PositionBarHeat alignment inconsistent
6. Docker build used cached layers — previous session's bug fixes not in the running container

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| Container creation time 07:36:50 | `docker inspect` | QA agent built image before fix agents finished |
| Local source files have fixes | `grep` on local .tsx files | Fixes applied by previous fix agents exist locally |
| Container has no `.tsx` files | `docker exec find /app` | Next.js standalone mode — only compiled JS, no source |
| `kpi.ts:computePortfolioKPI` | `lib/kpi.ts:144–158` | KPI strip uses `quote.change × qty` |
| `DayPnLDistribution.tsx:47–70` | Component file | Uses `getValueHistory()` → daily snapshot deltas |
| `HoldingsTab.tsx:165–171` | Before fix | HoldingLotsPanel wrapped in `<div className="px-2">` |
| `HoldingLotsPanel.tsx:162` | Before fix | `grid-cols-[...90px]` — 90px too narrow for `+$XXX.XX +XX.XX%` |
| `SectorHeatmapWidget.tsx:135` | Component file | Fetches `getMarketHeatmap(period)` from S9 |
| `AiSignalsWidget.tsx:55–57` | Component file | Fetches `getAiSignals(6)` — empty when ML pipeline has no data |

---

## 3. Root Causes

### Issue 1 — Day P&L discrepancy (by design)

**KPI strip** (`PortfolioKPIStrip`) shows `kpi.dayPnl = sum(quote.change × qty)` — today's **intraday** price movement from previous close to now.

**DayPnLDistribution strip** (`DAY P&L 30D`) shows `value[i] - value[i-1]` from stored daily portfolio snapshots — a historical **end-of-day** delta for each of the last 30 trading days.

These are fundamentally different metrics:
- KPI strip: "how much has my portfolio changed **today** (live, intraday)"
- DayPnLDistribution: "what was each **day's** gain/loss over the last month (historical)"

They will never exactly match because:
1. KPI strip updates every 15s (intraday); DayPnLDistribution's most recent bar is yesterday's close-to-close
2. For freshly seeded demo portfolios, `portfolio_value_snapshots` table may be empty → DayPnLDistribution shows "insufficient history" while KPI strip shows live values
3. Cash holdings affect snapshot-based value but don't contribute to `quote.change`

**Verdict**: Not a bug. Two intentionally different data views. The label "DAY P&L 30D" distinguishes the strip from the KPI tile's "DAY P&L".

**Recommended clarification**: Add a tooltip or `title` attribute to the KPI strip Day P&L tile explaining "Today's intraday change from previous close" vs the 30D strip's "30-day historical daily change distribution".

---

### Issue 2 — AI Signals "sloppy" appearance

**What it is**: `AiSignalsWidget` shows top-6 ML price-impact signals from S6 pipeline. Each signal = ticker + proportional score bar + confidence %. Generated when `ArticleRelevanceScoringWorker` processes an article and tags it POSITIVE/NEGATIVE/NEUTRAL.

**Why it looks sloppy**: For a demo environment where the ML article-impact pipeline hasn't processed many articles, `GET /v1/signals/ai` returns 0 signals → shows "No signals yet — processing articles…" empty state.

**Component quality**: The design is correct (ticker | bar | % at 22px rows). The issue is **data availability**, not component design.

**Fix path**: The signals will populate naturally as the NLP pipeline (`ArticleRelevanceScoringWorker` in S6) processes incoming articles. For a live demo, ensure:
- Content ingestion is running (`content-ingestion` service healthy)
- `ArticleRelevanceScoringWorker` is active (check S6 worker logs)
- At least some articles have been processed with POSITIVE/NEGATIVE labels

---

### Issue 3 — Sector performance tiles empty

**Data path**: `SectorHeatmapWidget` → `GET /v1/market/heatmap?period=1D` → S9 computes sector `change_pct` from constituent stocks' daily price changes.

**Why many are empty**: S9's sector heatmap aggregates price changes across all instruments in each GICS sector. If those instruments:
- Have no live quotes (market data not ingested yet)
- Have `change = null` (no daily price movement data)
- Have `price = 0` (instruments seeded but no OHLCV yet)

then the sector's `change_pct` is `null`, shown as "—" or a flat tile.

**Hundreds of tickers** are seeded but only a subset may have live OHLCV data loaded by `MarketDataIngestionWorker`. Specifically:
- Batch quote endpoint returns `change` only for instruments with intraday price data
- Many seeded instruments may only have end-of-day OHLCV from EODHD, not intraday quotes
- The sector heatmap uses the same quote source as the portfolio — if quotes are stale, sectors are flat

**Fix path**: Ensure `market-data-ingestion` service is fetching live daily prices for the full seeded universe. Check `market_data_db.daily_prices` table for coverage. Alternatively, the heatmap backend could fall back to using end-of-day price changes from `daily_prices` when intraday quotes are unavailable.

---

### Issue 4 — MarketSnapshot visual improvements

**Current state**: Clean two-column layout (ticker | price | change%). Functional but visually plain.

**Improvement applied**: Added row-level heat tinting (same convention as SectorHeatmapWidget tiles). Rows with `|change%| ≥ 0.5` get `bg-positive/5` or `bg-negative/5` background, giving directional color cues at a glance without overwhelming the monospace data.

**Future improvements** (not blocking):
- Mini sparklines per row (requires 5-day OHLCV)
- VIX, 10Y yield, DXY, gold (require specialized data sources)
- Volume indicator (tiny dot scaled to relative volume)

---

### Issue 5 — HoldingLotsPanel spacing + UNREAL column overflow

**Root causes**:

**A. px-2 wrapper inconsistency**: `HoldingLotsPanel` was inside `<div className="px-2">` in `HoldingsTab`, making it 16px narrower than adjacent full-width strips (`PositionBarHeat`, `RealizedPnLSparkline`, `DividendYTDStrip`). This broke horizontal rhythm.

**B. UNREAL column 90px overflow**: The "UNREAL" column renders `+$X,XXX.XX` (dollar value) + `+XX.XX%` (percentage sub-label at `text-[9px] ml-1`). Worst-case content like `+$1,234.56 +25.43%` requires ~110px in 11px monospace. The column was 90px, causing text overflow.

**Fixes applied**:
- `HoldingsTab.tsx`: Removed `<div className="px-2">` wrapper — `HoldingLotsPanel` now renders edge-to-edge matching all other strips
- `HoldingLotsPanel.tsx`: Changed outer container from `border-b border-border bg-card mt-2` to `border-y border-border bg-card` (border-t provides the top separator; border-b preserved; mt-2 no longer needed without the wrapper)
- `HoldingLotsPanel.tsx`: Column widened from `90px` → `110px` in both header and data rows

---

### Issue 6 — Docker build used cached layers (previous session's fixes not live)

**Root cause**: The previous session launched three agents in parallel: Fix Agent A, Fix Agent B, and QA Agent. QA Agent started the Docker build concurrently with the fix agents. The build completed at **07:36:50** before Fix Agents A+B had finished writing their changes to disk. Compiled Next.js bundle = old code.

**Evidence**: Local source files had all 3 bug fixes (confirmed by grep), but container was built before those files existed.

**Fix**: Ran `docker compose build --no-cache worldview-web` (full no-cache rebuild). Container restarted at 00:42 with all previous session fixes + new fixes from this session.

---

## 4. Fixes Applied This Session

| Fix | File | Change |
|-----|------|--------|
| Remove px-2 wrapper from HoldingLotsPanel | `features/portfolio/components/HoldingsTab.tsx` | Removed `<div className="px-2">` |
| border-y on HoldingLotsPanel (was border-b+mt-2) | `components/portfolio/HoldingLotsPanel.tsx` | `border-y border-border bg-card` |
| UNREAL column widened 90px → 110px | `components/portfolio/HoldingLotsPanel.tsx` | `grid-cols-[...110px]` header + data rows |
| MarketSnapshot row heat tinting | `components/dashboard/MarketSnapshotWidget.tsx` | `bg-positive/5` / `bg-negative/5` on rows with `|change%| ≥ 0.5` |
| Docker --no-cache rebuild | Docker Compose | Previous session fixes now live |
| Docker incremental rebuild | Docker Compose | New HoldingsTab/HoldingLotsPanel/MarketSnapshot changes now live |

---

## 5. Impact Analysis

- **HoldingLotsPanel spacing**: Visual fix — no functional regression risk
- **UNREAL column width**: Data always fits now; 110px still narrower than default table columns
- **MarketSnapshot tinting**: Additive only — rows with no data or flat price stay untinted
- **Docker rebuild**: All 7 bug fixes from both sessions are now live in the container

---

## 6. Prevention Recommendations

- **Parallel agent ordering**: When launching fix + QA agents in parallel, the QA agent's Docker build step should be a separate, sequential phase that runs ONLY after all fix agents confirm completion. Consider adding a "barrier" step.
- **Container fix verification**: Pre-build, always verify via `docker run --rm <image> grep <pattern> <file>` against a temporary container rather than relying on the running container (which may predate the build).
- **Day P&L tooltip**: Add a `title` or hover tooltip to the KPI strip's Day P&L tile clarifying it shows intraday live change vs the 30D historical strip.
