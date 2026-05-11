# PLAN-0048 QA Iteration 1 — Strict Live-Stack Audit

**Date**: 2026-04-28
**Scope**: PLAN-0048 (Waves A–F) + ad-hoc Holdings fixes (commit 20508b9)
**Branch**: feat/content-ingestion-wave-a1
**Stack**: 59 containers running; frontend rebuilt at HEAD ee1a7fa
**Verdict**: **FAIL**

> **TL;DR** — The frontend (worldview-web) and api-gateway containers were rebuilt and contain the new code. The backend services that PLAN-0048 modifies — **rag-chat (Wave A), alert (Wave B), market-data (Wave D)** — were **NOT** rebuilt. The features they back are not live. Several front-end bugs are present even with backend code committed: holdings-table double-`+` percent formatting, TopBar Day P&L / Total P&L slots are never rendered (layout never passes the props), AlertsList severity filter is case-mismatched (zero rows always), dashboard alert deep-links emit `?selected=undefined` for WS-sourced alerts, and existing TopMovers data is broken (all $0.00, gainers/losers duplicates, negative entries in gainers list).

---

## Summary

| Severity | Count |
|----------|-------|
| BLOCKING | 4 |
| CRITICAL | 7 |
| MAJOR    | 9 |
| MINOR    | 5 |
| NIT      | 4 |

## Wave Results

| Wave | Status | Findings |
|------|--------|----------|
| Holdings (ad-hoc) | CONDITIONAL_PASS | F-201, F-202, F-203, F-204, F-205, F-206 |
| Wave A — Brief | FAIL (container stale) | F-101, F-102, F-103 |
| Wave B — Alerts | FAIL (container stale) | F-111, F-112, F-113, F-114, F-115, F-116 |
| Wave C — TopBar | FAIL | F-121 (BLOCKING), F-122 |
| Wave D — Predictions | PARTIAL FAIL | F-131 (BLOCKING — backend stale), F-132 |
| Wave E — 4-row layout | PASS | F-141 |
| Wave F — Treemap + pills | CONDITIONAL_PASS | F-151, F-152, F-153 |
| Cross-cutting | — | F-301..F-307 |

---

## Stack rebuild gap (root cause for many findings)

```
$ docker inspect <ctr> --format '{{.State.StartedAt}}'
worldview-web      → 2026-04-28T18:22:46Z   (current — has Wave A-F code)
api-gateway        → 2026-04-28T18:22:40Z   (current)
market-data        → 2026-04-28T11:48:34Z   (BEFORE Wave D commit 18:01Z)
rag-chat           → 2026-04-28T08:19:52Z   (BEFORE Wave A commit 18:00Z)
alert              → 2026-04-27T21:03:19Z   (BEFORE Wave B commit)
```

I verified the code IS on disk at HEAD (`grep "summary"` in `services/rag-chat/.../schemas.py` finds the new field; `grep "LEFT JOIN LATERAL"` in `prediction_market_repo.py` matches; `services/alert/...` references `entity_resolver`). I verified the code is NOT in the running containers (`docker exec ... grep ...` returns 0 matches in the corresponding paths). So PLAN-0048's backend half is unshipped on this stack.

---

## BLOCKING findings

### F-101 — `BLOCKING` Wave A backend not running; brief still has duplicate "Morning Market Briefing / Date / Market Overview" preamble

- **File**: `services/rag-chat/src/rag_chat/api/schemas.py` (code present); container `worldview-rag-chat-1` (stale)
- **Issue**: Cached brief returned by `GET /v1/briefings/morning` has no `summary` field, no `top_stories`, and the narrative still leads with `# Morning Market Briefing` / `**Date:** 2026-04-28` / `## Market Overview` — exactly the duplication PLAN-0048 Wave A was scoped to remove.
- **Evidence**:
  ```
  $ curl ... /v1/briefings/morning | jq 'keys'
  ["narrative","risk_summary","citations","generated_at","cached","entity_id"]
  $ docker exec worldview-rag-chat-1 grep -c "summary" /app/src/rag_chat/api/schemas.py
  2     # only references in comments, not as a field
  ```
- **Suggestion**: rebuild rag-chat (`docker compose build rag-chat && docker compose up -d rag-chat`) and force-regenerate the cached brief (delete cache row or add `?force_refresh=true` support). Confirm response keys include `summary` AND that `narrative` no longer contains the verbatim "Morning Market Briefing" / "Date:" preamble.
- **Auto-fixable**: NO (requires container rebuild)

### F-111 — `BLOCKING` Wave B-1 alert payload enrichment not running; live alert payload contains zero display fields

- **File**: `services/alert/src/alert/application/use_cases/alert_fanout.py` (code present); container `worldview-alert-1` (stale)
- **Issue**: `GET /v1/alerts/pending` returns alerts whose `payload` field has only `{doc_id, claim_id, event_id, polarity, claim_type, event_type, is_backfill, occurred_at, correlation_id, schema_version, claimer_entity_id, subject_entity_id, market_impact_score, extraction_confidence}` — i.e. the raw Avro record. **`entity_name`, `ticker`, `signal_label` are NOT present.**
- **Evidence**: `docker exec worldview-alert-1 grep -l "EntityNameResolverPort" /app -r` → 0 results.
- **Impact**: F-001 (audit) is unfixed. Dashboard `RecentAlerts` widget renders rows as `LOW LOW alert 15m`, `LOW LOW alert 24m` — no entity context. The Wave B-2/B-3 frontend renderers depend on these fields, so the AlertDetailSheet would also show "—" placeholders for ticker/entity_name/signal_label.
- **Suggestion**: rebuild & restart `worldview-alert-1`. Verify `payload.entity_name`, `payload.ticker`, `payload.signal_label` are non-null on new alerts (`POST /v1/internal/...` test or wait for fresh signal events).
- **Auto-fixable**: NO

### F-121 — `BLOCKING` TopBar shows ONLY "PORT $42K" — Day P&L and Total P&L are never rendered

- **File**: `apps/worldview-web/app/(app)/layout.tsx:219`
- **Issue**: `<TopBar unreadAlerts={badgeCount} portfolioValue={portfolioValue} />` — `dailyPnl` and `unrealisedPnl` props are NEVER passed by the layout. `TopBar.tsx` correctly renders the Day P&L / Total P&L slots conditional on `dailyPnl != null && unrealisedPnl != null`, but layout has no compute for these (`navQuotes` is fetched but never sum-aggregated for delta or unrealised). Result: at every viewport (1280 / 1440 / 1920) the topbar shows ONLY `PORT $42K` next to the alert bell. The Wave C-1 spec's "three labeled values" goal is not delivered.
- **Evidence**: `/tmp/qa-iter1/d{1280,1440,1920}-topbar.png` show identical rails: `… 18:28:30 UTC  ● Open  PORT $42K  🔔 U`. The `formatPortfolioValue` returns `$42K` when `portfolioValue=42483.75` (rounded to thousands) but no Day or Total P&L number ever appears.
- **Suggestion**: in `app/(app)/layout.tsx`, after computing `portfolioValue`, also compute:
  ```ts
  const dailyPnl = holdingsResp?.holdings.reduce((sum, h) => {
    const q = navQuotes?.quotes?.[h.instrument_id];
    return sum + (q?.change ?? 0) * h.quantity;
  }, 0) ?? null;
  const totalCost = holdingsResp?.holdings.reduce(
    (s, h) => s + h.average_cost * h.quantity, 0) ?? 0;
  const unrealisedPnl = portfolioValue != null ? portfolioValue - totalCost : null;
  ```
  Pass to `<TopBar … dailyPnl={dailyPnl} unrealisedPnl={unrealisedPnl} />`.
- **Auto-fixable**: YES

### F-131 — `BLOCKING` Wave D-1 backend not running; `volume_24h` always null

- **File**: `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py` (code present); container `worldview-market-data-1` (stale)
- **Issue**: `GET /v1/signals/prediction-markets?status=open` returns `"volume_24h": null` for every market, despite all 521 markets having snapshots (`SELECT COUNT(*) FROM prediction_market_snapshots → 117500`). `docker exec worldview-market-data-1 grep "LEFT JOIN LATERAL" /app/src/market_data/.../prediction_market_repo.py` → 0 matches.
- **Evidence**: see backend curl output captured during audit; the `LATERAL` join exists in the source tree at HEAD but not in the live container.
- **Suggestion**: rebuild & restart market-data. Confirm a sample market returns non-null `volume_24h`.
- **Auto-fixable**: NO

---

## CRITICAL findings

### F-201 — `CRITICAL` Holdings table — every percent column shows DOUBLE plus sign

- **File**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:340, 360`
- **Issue**: `${dayChangePct >= 0 ? "+" : ""}${formatPercent(dayChangePct / 100)}` — `formatPercent` already prepends `+` for positive values (utils.ts:81). Result: `++0.00%`, `++51.76%`, `++30.92%` on every row. Same bug at line 360 for P&L %.
- **Evidence**: `/tmp/qa-iter1/holdings-table.png` — every DAY % and P&L % cell shows `++` instead of `+`.
- **Suggestion**: drop the redundant ternary at lines 340 and 360 — keep only `formatPercent(dayChangePct/100)` and `formatPercent(pnlPct/100)`. **Same bug also exists in `PortfolioKPIStrip.tsx:109-111`**: `unrealisedPnlPct >= 0 ? \`+${formatPercent(unrealisedPnlPct)}\` : formatPercent(unrealisedPnlPct)` produces `++30.92%` in the UNREALISED P&L tile.
- **Auto-fixable**: YES

### F-202 — `CRITICAL` Top Loser tile shows MSFT +1.70% — semantic bug; positive % is not a "loser"

- **File**: `apps/worldview-web/app/(app)/portfolio/page.tsx:912`
- **Issue**: `topLoser` is computed as `Math.min(pnlPct)` across holdings — when every holding is positive, this returns the smallest gainer (MSFT +1.70%) and labels it the Top Loser. No null-guard on positive case.
- **Evidence**: `/tmp/qa-iter1/holdings-kpi-strip.png` — TOP LOSER reads `MSFT +1.70%` in red text. A trader will read "MSFT down 1.70%" — false signal.
- **Suggestion**: only assign `topLoser` when `pnlPct < 0`. When no holding has negative pnlPct, KPITile should show `—` (parent can pass `topLoser={null}`).
- **Auto-fixable**: YES

### F-203 — `CRITICAL` Holdings table value × P&L% column overlap on dashboard PortfolioSummary

- **File**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx:402-413`
- **Issue**: `<span className="w-[54px] shrink-0 text-right font-mono text-[11px] tabular-nums text-foreground">{formatPrice(holdingValue)}</span>` — `54px` is too narrow for `$13,545.00` (9 chars × ~6.5px ≈ 58.5px) at the 11px monospace font. The value overflows its cell and visually collides with the next column (P&L %), so users see e.g. `$13,545.001.76%` jammed together.
- **Evidence**: `/tmp/qa-iter1/d{1280,1440,1920}-row3-detail.png` — every row of DEMO PORTFOLIO holdings shows price+percent fused on AAPL/MSFT/AMZN/TSLA.
- **Suggestion**: bump `w-[54px]` to `w-[68px]` (or use `min-w-[68px]`) to fit a 9-char `$XX,XXX.XX`. Better: use `formatPrice` to abbreviate (`$13.5K`) when the cell is narrow.
- **Auto-fixable**: YES

### F-301 — `CRITICAL` Dashboard RecentAlerts: deep-links emit `?selected=undefined` for WS-sourced alerts

- **File**: `apps/worldview-web/contexts/AlertStreamContext.tsx:154-156` + `components/dashboard/RecentAlerts.tsx:160-162`
- **Issue**: WS handler does `JSON.parse(event.data) as AlertPayload; dispatch(data)` — the payload is treated as `AlertPayload` (which expects `id`) but the S10 server sends `{alert_id, ...}` (see `services/alert/src/alert/application/use_cases/alert_fanout.py:219`). So `alert.id` is `undefined`. RecentAlerts then renders `<Link href={\`/alerts?selected=${encodeURIComponent(alert.id)}\`}>` → `/alerts?selected=undefined`.
- **Evidence**: Playwright `qa-deeplink2.mjs` found 8 `<a href="/alerts?selected=undefined">` rows on the dashboard. Clicking one loaded `/alerts?selected=undefined` and the AlertDetailSheet did not open (no alert with that id).
- **Suggestion**: in `AlertStreamContext.dispatch` normalise: `const normalised = { ...alert, id: alert.id ?? (alert as any).alert_id, severity: ... }`. OR fix S10 WS broadcast to also include `id` as an alias for `alert_id`. Add a regression unit test that asserts `RecentAlerts` rows always have a defined `alert.id`.
- **Auto-fixable**: YES

### F-302 — `CRITICAL` /alerts page shows "No pending alerts" while 45 alerts are pending — severity filter is case-mismatched

- **File**: `apps/worldview-web/components/alerts/AlertsList.tsx:158-166`
- **Issue**: `SEVERITY_ORDER = ["CRITICAL","HIGH","MEDIUM","LOW"]` (uppercase). The backend returns `severity: "low"` (lowercase StrEnum). `allAlerts.filter((a) => a.severity === sev)` is therefore always false for every group — `activeAlertsBySeverity` is always `{ CRITICAL: [], HIGH: [], MEDIUM: [], LOW: [] }` regardless of actual data. The fallback "No pending alerts — you're all caught up" empty state is shown ALWAYS.
- **Evidence**: `curl /v1/alerts/pending?limit=50` returns 45 alerts with `"severity":"low"`. `/tmp/qa-iter1/alerts-1440-content.png` shows the empty state.
- **Suggestion**: in `AlertsList.tsx`, normalise `a.severity` to uppercase before comparison (the existing `RecentAlerts.tsx:91` already does `(a.severity?.toUpperCase() ?? "LOW")`). Apply the same pattern in `AlertsList`.
- **Auto-fixable**: YES

### F-303 — `CRITICAL` First dashboard alert row shows `LOW NaNh` timestamp (NaN bug)

- **File**: `apps/worldview-web/components/dashboard/RecentAlerts.tsx:208-214`
- **Issue**: `relativeTime` doesn't guard against `Date(undefined).getTime() === NaN`. WS-sourced alerts may lack `created_at` (server payload uses different keys). The first row in `/tmp/qa-iter1/d1920-row4.png` shows `LOW NaNh` — the time-ago calculation produced NaN and was string-concatenated.
- **Suggestion**: in `relativeTime`, return `"—"` when `Number.isNaN(diffMs)` or when `isoStr` is falsy.
- **Auto-fixable**: YES

### F-304 — `CRITICAL` TopMovers / Watchlist Movers prices all $0.00; gainers list contains negative entries; same ticker appears in both gainers and losers

- **File**: data layer (S9 → S3 movers endpoint) + `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx`
- **Issue**: `/tmp/qa-iter1/d1920-top-movers.png`: GAINERS shows AAPL $0.00 +3.11%, ..., GOOGL $0.00 -0.54%, TSLA $0.00 -1.46% — gainers list is sorted by % but includes negative %. LOSERS shows NVDA $0.00 -3.45%, ..., GOOGL $0.00 -0.54% — GOOGL appears in BOTH lists. Every row shows `$0.00` price.
- **Suggestion**: investigate S3 top-movers endpoint — looks like quote price column is null and not falling back to the latest snapshot price. Also gainers should filter `change_pct > 0` and losers `change_pct < 0` strictly.
- **Auto-fixable**: PARTIAL (needs backend investigation)

### F-305 — `CRITICAL` UNREALISED P&L tile value truncated: "++30..." (also has F-201 double-plus + truncation)

- **File**: `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx` + same KPITile width
- **Issue**: `/tmp/qa-iter1/holdings-kpi-strip.png` — UNREALISED P&L shows `$10,032.75 (++30...` — the parenthesised pct is double-`+` AND truncated by the cell width. F-201 covers double-`+`; the truncation is a second layer of bug — KPI tiles use `flex-1` but content overflows under narrow inputs.
- **Suggestion**: fix F-201 first; the deduplicated `+30.92%` will fit. If still tight, allow tile to shrink the secondary value or wrap inside the tile.
- **Auto-fixable**: YES (after F-201)

---

## MAJOR findings

### F-141 — `MAJOR` Wave E layout matches spec at 1440 + 1920; at 1280 sector treemap row 2 wraps off-screen

- **File**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`
- **Issue**: at 1280px Row 2 col-4 width (~310px) the 11 sector tiles wrap to 3 rows; the cell is constrained to 130px height so the third row is hidden behind `overflow:hidden`. Verified visually in `d1280-row2-detail.png`: only 9 of 11 sectors visible (UTIL/REIT clipped).
- **Suggestion**: tighten tile heights at narrow viewports OR allow the cell height to grow when sectors > 9.
- **Auto-fixable**: PARTIAL

### F-142 — `MAJOR` Sector treemap: tiles with no `change_pct` data render as ENERGY/MAT/INDUS/STAPLE/HEALTH/UTIL/REIT all showing "—" — 7 of 11 sectors lack data

- **File**: data: heatmap query may be returning incomplete sector coverage
- **Issue**: only DISCR (+0.16%), FINS (-1.53%), TECH (-1.08%), COMM (+0.23%) have values; everything else shows "—". This is a backend-data finding, not strictly Wave F-1 — but the user's `/v1/market/heatmap` endpoint is supplying half-blank data. Visually it makes the treemap look broken.
- **Suggestion**: investigate heatmap source; ensure all 11 GICS sectors have at least a daily close-price computation.
- **Auto-fixable**: PARTIAL (backend)

### F-143 — `MAJOR` IndexTicker stale data — SPY/QQQ/VIX/BTC quotes all from prior session

- **File**: data: `/v1/quotes/batch`
- **Issue**: index ticker prices visible (SPY $711.17, QQQ $657.81, VIX $19.27, BTC $76,897.56) but no Δ — visually inert.
- **Suggestion**: include the daily change next to each price (matches Bloomberg). Cross-cutting; not strictly PLAN-0048 scope but this audit caught it.
- **Auto-fixable**: PARTIAL

### F-204 — `MAJOR` Holdings table — `DAY $` column shows `+$0.00` for every row; quote `change` field is null

- **File**: data: batch quotes daily change
- **Issue**: Every Holdings row shows `+$0.00` and `++0.00%` (after F-201 fix it'd still be `+0.00%`). The underlying quote `change` is null for delayed instruments. Display formats null as 0 instead of "—".
- **Suggestion**: when `q?.change == null`, display "—" instead of `$0.00`.
- **Auto-fixable**: YES

### F-205 — `MAJOR` Holdings table — SECTOR column always "—"

- **File**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx`
- **Issue**: `/tmp/qa-iter1/holdings-table.png`: SECTOR column shows `—` for every holding even though Allocation By Sector below it correctly identifies "Information Technology" + "Consumer Discretionary".
- **Suggestion**: wire the holding overview's `gics_sector` (already loaded for the allocation widget) into the table row.
- **Auto-fixable**: YES

### F-122 — `MAJOR` PORT formatPortfolioValue rounds aggressively — `$42K` for $42,483.75 loses precision

- **File**: `apps/worldview-web/components/shell/TopBar.tsx:43-46`
- **Issue**: `formatPortfolioValue(42483.75)` → `$42K` (rounded to thousands). At a value where the last $483 still matters to the trader, this loses signal. Bloomberg's account rail keeps two decimals for sub-$1M values.
- **Suggestion**: switch to `$42.5K` (one decimal place) or `$42,484` (whole-dollar with comma) — never rounded to thousands.
- **Auto-fixable**: YES

### F-132 — `MAJOR` Prediction widget shows "Δ 0.0pp closes in 30d" before any volume — sentence reads ambiguous

- **File**: `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx`
- **Issue**: `/tmp/qa-iter1/d1920-row3.png` — first market reads `Y 98% N 2% Δ 0.0pp closes in 30d` with no volume between Δ and "closes". Reads visually as if Δ refers to volume. When volume is null (F-131) the widget should drop the `Δ 0.0pp` segment OR show volume = "no vol".
- **Suggestion**: collapse data row when delta is null (loading) or 0 with no underlying snapshot.
- **Auto-fixable**: YES

### F-306 — `MAJOR` MarketSnapshot widget tickers show `+0.00%` for AAPL/MSFT/NVDA but +4.74% for AMZN — broken intraday data

- **File**: data
- **Issue**: At least three of four MarketSnapshot tickers show `+0.00%` change. Same pattern as F-304: change is null and falsely rendered as 0%.
- **Auto-fixable**: PARTIAL

### F-115 — `MAJOR` MorningBrief header timestamp wraps "2026-04-28 07:14\nUTC" to two lines

- **File**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:243`
- **Issue**: `<span className="w-[100px] shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground/60">{ts} UTC</span>` — at 9px monospace `2026-04-28 07:14 UTC` (19 chars) doesn't fit in 100px and wraps. The h-5 header ends up partially obscured.
- **Suggestion**: bump to `w-[120px]` OR drop the date (it's repeated in the body) and just show `07:14 UTC`.
- **Auto-fixable**: YES

---

## MINOR findings

### F-151 — `MINOR` Sector treemap "no data" tiles render with `bg-muted/30` and "—" — visually dead

- **File**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx:95`
- **Issue**: when `change_pct === null` the tile is grey with "—". Functional but communicates "broken" rather than "no data yet". A tighter empty state — e.g. dotted border, smaller font — would read better.
- **Auto-fixable**: PARTIAL

### F-206 — `MINOR` Realized P&L tile shows `$0.00` (no sign) while DAY P&L shows `$296.25` (no sign) — inconsistent vs UNREALISED's signed format

- **File**: `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx`
- **Issue**: REALIZED, DAY use `formatPrice` (no sign). UNREALISED uses `formatPrice + (formatPercent)`. Pick one and apply consistently — either every $ has a sign or none do (and color carries the sign).
- **Auto-fixable**: YES

### F-307 — `MINOR` Allocation `BY TYPE` shows "Equity +100.00%" — `+` on share allocations is a category error

- **File**: `apps/worldview-web/components/portfolio/SectorAllocationPanel.tsx`
- **Issue**: `formatPercent` always prepends `+` for positive values, but allocation shares are not P&L. Reads as if Equity gained 100%.
- **Suggestion**: use a no-sign formatter for shares.
- **Auto-fixable**: YES

### F-152 — `MINOR` WatchlistMovers `EV & Clean Energy · today` empty-state line is fine but the whole widget renders blank otherwise — no alternative CTA

- **File**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx`
- **Issue**: when watchlist is empty the widget shows "Add symbols in Portfolio → Watchlists" in the rail, but the widget itself just says "No movers in this watchlist" without a CTA.
- **Suggestion**: add a "+ Add symbols to watchlist" button inside the empty state, deep-linked to the watchlist editor.
- **Auto-fixable**: YES

### F-153 — `MINOR` Sector pill rail in TopMovers/WatchlistMovers exceeds widget width at all viewports — pills cut off (e.g. `INDUSTRIAL` truncated to `INDUSTRI...`)

- **File**: `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx` + WatchlistMoversWidget
- **Issue**: the pill row uses `overflow-hidden` rather than `overflow-x-auto` (or `flex-wrap`) — pills past the visible area are silently cut off without a horizontal scrollbar. Trader can't see/click sectors past the visible 7-8 pills.
- **Auto-fixable**: YES — switch to `overflow-x-auto` and add `scrollbar-thin`.

---

## NIT findings

### F-401 — `NIT` REALIZED P&L sample data is $0.00 — no realised activity in seed

Just an observation; not a bug. Confirms the realised computation only sums SELL transactions.

### F-402 — `NIT` `+1 more → View all` link is the only escape from PortfolioSummary's holdings table — no row-level clicks

Holdings rows in the dashboard PortfolioSummary aren't clickable. A trader who wants to drill into AAPL must move to the Portfolio page and click there. Worth wiring `<Link href={"/instruments/" + h.instrument_id}>`.

### F-403 — `NIT` Dashboard "PORTFOLIO NEWS" widget pinning the impact dots `••○○` left of each headline crowds the title

The 4-dot impact indicator + 6-char "5h ago" timestamp claims ~50px of horizontal real estate before the title. At narrow widths the title is heavily clipped.

### F-404 — `NIT` Brief header centerline shows `MORNING BRIEFING` in caps at the same y-coordinate as the timestamp's wrapped second line ("UTC") — visually overlapping despite being in separate flex slots

Cosmetic; once F-115 is fixed, this resolves.

---

## Cross-cutting findings

### F-501 — Frontend tokens — sample of pages spot-checked; no `bg-slate-900`, `bg-zinc-*`, or hardcoded `#000` overlay found in the rendered DOM

✓ Token compliance OK on the routes inspected (dashboard, portfolio, alerts, screener).

### F-502 — Numbers — most numeric data uses `font-mono tabular-nums` correctly. Two exceptions:
- TopBar `PORT $42K` — `font-mono tabular-nums` applied (good).
- ALARMS panel rail timestamps `15m`, `24m` — uses no monospace. Recommend bumping to `font-mono` for column-aligned digits.

### F-503 — No bouncy animations or gradient text observed.

### F-504 — Console — Playwright captured these errors during the audit pass (across all routes):
- 401 Unauthorized × 7 (token expired during 4-route navigation)
- 502 Bad Gateway × 5 (transient API gateway hiccup)
- 422 Unprocessable Entity × 5 (params; needs follow-up)
- 429 Too Many Requests × 11 (test loop hammered some endpoint — non-prod issue but visible)

The 429s suggest the dashboard may not be deduplicating overlapping queries — worth investigating `staleTime` settings. Saved to `/tmp/qa-iter1/console-errors.json`.

### F-505 — 60-30-10 rule — primary brand color (Bloomberg yellow) used in: brief border, nav active state, ALL pill, "Read more" link, pending-alert badge. That's already 5 distinct accents visible on dashboard. Watch for further accent creep.

### F-506 — Squint test — at any viewport, the most visually dominant elements are: brief border (yellow), AlertsBell red badge, Portfolio NAV `$42,483.75` (large bold). Acceptable, but the bell badge `1` competes with portfolio NAV for attention.

### F-507 — Verified: `PortfolioGainersLosers.tsx` is gone. Dashboard imports do NOT include it.

```
$ grep -l "PortfolioGainersLosers" apps/worldview-web/app/(app)/dashboard/page.tsx
(no matches)
```

✓ Wave E-3 deletion confirmed.

---

## Console / network errors

Captured during Playwright route walk (saved to `/tmp/qa-iter1/console-errors.json`):
- 7 × `401 Unauthorized` — token expiry during the test pass; not a bug, but worth confirming the frontend silently refreshes.
- 5 × `502 Bad Gateway` — transient.
- 5 × `422 Unprocessable Entity` — investigate which gateway endpoint(s).
- 11 × `429 Too Many Requests` — overlapping queries / rate limit; investigate.
- No raw uncaught JS exceptions — `pageerror` listener silent.

---

## Verdict reasoning

**FAIL** because:
1. **Three of six waves' backend halves are not on the running stack.** Even if the test passes against the frontend code, the user-visible behaviour is unchanged from the pre-PLAN-0048 state for: brief preamble (F-101), alert payload enrichment (F-111), prediction volume (F-131). The implementation reports claim "DONE" but the live stack proves otherwise.

2. **The frontend (which IS deployed) has its own correctness bugs that block PLAN-0048 acceptance**: TopBar's Day/Total P&L slots are never populated (F-121); double-`+` percent formatting in three places (F-201); AlertsList severity case mismatch produces "no alerts" forever (F-302); dashboard alert deep-links emit `?selected=undefined` (F-301); top loser tile shows positive-% holdings (F-202); holdings value/percent column overlap (F-203, was the central pre-PLAN-0048 complaint and is unsolved).

3. **Several existing data-layer bugs are unrelated to PLAN-0048 but make the pages look broken**: TopMovers $0.00 prices, gainers list contains negative entries, GOOGL appears in both gainers and losers, SectorHeatmap missing 7 of 11 sectors, MarketSnapshot all 0% changes.

The ad-hoc Holdings overlay fix (commit 20508b9) appears clean; the page no longer has a black-overlay perception issue. But the same Holdings page surfaces F-201, F-202, F-204, F-205, F-206 — none of which are part of PLAN-0048's ad-hoc scope but they are visible at the same paint as the user evaluating the fix.

Recommend a follow-up commit that:
1. Rebuilds the three stale containers (rag-chat, alert, market-data).
2. Patches `app/(app)/layout.tsx` to compute and pass `dailyPnl` + `unrealisedPnl` to `<TopBar>`.
3. Removes redundant `+` ternaries in `SemanticHoldingsTable.tsx:340,360` and `PortfolioKPIStrip.tsx:109-111`.
4. Adds severity-case normalisation to `AlertsList.tsx` filter.
5. Adds `id ?? alert_id` aliasing in `AlertStreamContext.dispatch`.
6. Null-guards `topLoser` to only assign when pnlPct < 0.
7. Bumps `PortfolioSummary` value cell width from `54px` to `68px`.

Then re-run this audit script and verify each item.

---

## Test artefacts

- Screenshots: `/tmp/qa-iter1/{dashboard,portfolio,alerts,screener,instruments}-{1280,1440,1920}.png`
- Detail crops: `/tmp/qa-iter1/d{1280,1440,1920}-{topbar,row1-brief,row2,row3,row4}.png`
- Console errors JSON: `/tmp/qa-iter1/console-errors.json`
- Playwright runner: `apps/worldview-web/qa-capture.mjs`, `apps/worldview-web/qa-deeplink2.mjs`
- Backend curls verified at: see audit body.
