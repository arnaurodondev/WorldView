# Investigation Report: Dashboard & Portfolio UX Issues

**Date**: 2026-04-28
**Investigator**: Claude (investigation skill)
**Severity**: HIGH (multiple independent issues)
**Status**: Root cause identified for all 11 issues

---

## 1. Issue Summary

Multiple UX and data issues identified across the dashboard and portfolio pages during live QA. Issues span three categories: (a) data pipeline gaps causing empty widgets, (b) frontend rendering/layout bugs, and (c) UX design improvements needed for Bloomberg-grade quality. All issues investigated via live container API calls, source code tracing, and frontend component analysis.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| S8 brief generation logs: `chars: 465` | Docker logs `worldview-rag-query-1` | Confirms near-empty brief context |
| All 93 articles have `display_relevance_score` 0.23-0.26 | `GET /v1/news/top` response | Explains why score threshold 0.3 excludes everything |
| `getHoldings` gateway: `ticker: ""`, `name: ""` explicitly set | `lib/gateway.ts:714-726` | Root cause of missing ticker/name |
| S10 `AlertSeverity.LOW = "low"` (lowercase) | `services/alert/src/alert/domain/enums.py:11-14` | Severity case mismatch with frontend `"LOW"` type |
| `AlarmsPanel` query: `retry: false` | `components/shell/AlarmsPanel.tsx:84` | Silent failure hides alert data |
| `TopBar` bell navigates to `/alerts` page | `components/shell/TopBar.tsx:100` | Bell → page, not sidebar panel |
| `unreadCount = recentAlerts.length` | `contexts/AlertStreamContext.tsx:258` | Badge counts WebSocket session events, not DB pending count |
| `PortfolioSummary` A-3 comment: period buttons deliberately removed | `components/dashboard/PortfolioSummary.tsx:156-160` | Portfolio 1D/1W/1M never implemented |
| `gridTemplateRows: "auto 130px auto auto"` | `app/(app)/dashboard/page.tsx:67` | Rows 3/4 are unbounded auto-height |
| `SectorHeatmapWidget` renders single `divide-y` list | `components/dashboard/SectorHeatmapWidget.tsx:153` | No 2-column layout applied |
| `PredictionMarketsWidget` at `col-span-2` | `app/(app)/dashboard/page.tsx:112-113` | ~200px width truncates 40-80 char titles |

---

## 3. Issue Analysis

### Issue 1: Morning Brief — No Context (CRITICAL)

**Root Cause**: `BriefingContextGatherer` in S8 (rag-query service) calls nlp-pipeline's `/news/top` endpoint with `min_display_score=0.3`. All 93 currently available articles have `display_relevance_score` in the range 0.23–0.26 — all below the threshold. The gatherer receives 0 articles, producing a 465-character context consisting only of static boilerplate (portfolio value, sector data). The LLM then generates "Not available in retrieved context" for every brief section.

**Location**: `services/rag-query/src/rag_query/...` (BriefingContextGatherer)

**Impact**: Every morning brief section reads "Not available in retrieved context" — the entire primary dashboard intelligence widget is non-functional.

**Fix**: Lower `min_display_score` threshold from 0.3 to 0.15 in S8's BriefingContextGatherer.

---

### Issue 2: Morning Brief — Format Not Bloomberg-Grade (HIGH)

**Root Cause**: `MorningBriefCard` shows a 200-char raw text preview (sliced from markdown, may cut mid-sentence) with no prominent headline. The "more" button collapses/expands. Institutional users (BlackRock-grade) expect a title headline (summarising the most important signal), followed by 3+ full readable lines, then an expand affordance. The current layout uses `PREVIEW_CHARS = 200` which truncates aggressively in Row 1's compact height.

**Location**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:49,222`

**Impact**: Institutional users cannot extract actionable intelligence from the brief at a glance — truncated text reads like a broken feed.

**Fix**:
1. Extract a 1-line headline from the brief markdown (first H2 or first bold phrase)
2. Show first 3 content lines always visible without collapse
3. "Read more" expands remaining content inline

---

### Issue 3: AI Signals — Appears Empty (LOW)

**Root Cause**: Not a rendering bug. 6 signals exist in the DB, all with `NEUTRAL` sentiment label and `article_title: null`. The `AiSignalsWidget` renders these correctly but they appear as grey bars with no context text — indistinguishable from empty. This is a data quality issue from the signal scoring pipeline, not a frontend bug.

**Impact**: The AI Signals panel looks non-functional but technically works.

**Fix**: No frontend fix needed. The LLM signal scoring pipeline needs to produce non-NEUTRAL signals with article context. This is a separate data pipeline concern.

---

### Issue 4: Recent Alerts — Empty Display (HIGH)

**Root Cause (confirmed)**: Two separate issues:

**4a. Severity case mismatch**: S10 `AlertSeverity` StrEnum serialises as lowercase (`"low"`, `"medium"`, `"high"`, `"critical"`). The frontend `Alert.severity` TypeScript type is `"LOW" | "MEDIUM" | "HIGH" | "CRITICAL"` (uppercase). `AlarmsPanel`'s `severityDotClass()` switch has cases for uppercase — falls through on lowercase, returning `undefined`, making all dots invisible.

**4b. AlarmsPanel silent failure**: `retry: false` on the AlarmsPanel query means any transient auth failure, cold-start race, or 5xx error silently produces an empty state with "No pending alerts" text.

**Location**:
- `components/shell/AlarmsPanel.tsx:43-50` (switch with no default)
- `components/shell/AlarmsPanel.tsx:84` (retry: false)
- `services/alert/src/alert/domain/enums.py:11-14`

**4c. TopBar badge disconnection**: `TopBar` bell badge shows `unreadCount = recentAlerts.length` — the count of WebSocket alerts received during this browser SESSION (not the REST pending count). AlarmsPanel sidebar shows REST data. These two counts are independent and can diverge significantly: session badge shows "9+" while sidebar REST shows 0 (or vice versa).

**Impact**: Users see "9+" in the TopBar badge but "No pending alerts" in the sidebar. Clicking the bell navigates to `/alerts` page. Confusing UX.

---

### Issue 5: Portfolio Holdings — Missing Ticker and Name (HIGH)

**Root Cause**: `getHoldings()` in `lib/gateway.ts:714-726` explicitly hardcodes `entity_id: ""`, `ticker: ""`, `name: ""` because S1's `GET /v1/holdings/{portfolio_id}` only returns `{id, portfolio_id, instrument_id, quantity, average_cost, currency}` — no enrichment. The comment confirms: "S1 does not return entity_id, ticker, or name on holdings."

`PortfolioSummary` component displays `h.ticker` and `h.name` which are both empty strings, so holdings show only a dollar value with no identifying context.

**Location**:
- `apps/worldview-web/lib/gateway.ts:714-726`
- `services/portfolio/src/portfolio/api/...` (holdings endpoint)

**Impact**: Portfolio widget shows "13,382$" with no ticker, no company name, no position count context. Institutional-grade presentation requires ticker + name + quantity.

**Fix Options**:
1. (Preferred) Add `ticker`, `name`, and `entity_id` to S1's holdings response by joining the `instruments` table in the holdings query
2. Enrich in S9's gateway after fetching by batch-searching each `instrument_id` against S3

---

### Issue 6: Portfolio — No 1D/1W/1M Period Selector (MEDIUM)

**Root Cause**: `PortfolioSummary` component's PLAN-0043 A-3 wave deliberately removed the period selector buttons with the comment: "portfolio data doesn't have a period-based S9 endpoint yet." The dashboard widget has no period selector; the portfolio page also lacks a chart period toggle.

**Location**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx:156-160`

**Impact**: Users cannot view portfolio performance across different timeframes from the dashboard or portfolio page.

**Fix**: Add `1D/1W/1M` period selector to portfolio page chart; requires S9 portfolio performance endpoint that returns returns over different time windows.

---

### Issue 7: Components Not Filling Space / No Independent Scroll (MEDIUM)

**Root Cause**: `gridTemplateRows: "auto 130px auto auto"` in `dashboard/page.tsx:67` makes Rows 3 and 4 auto-height. When content is short, these rows don't fill the viewport. When content is tall, they push the page down rather than scrolling within the widget. Most widget content areas do have `overflow-auto` but the unbounded row height defeats this.

**Location**: `apps/worldview-web/app/(app)/dashboard/page.tsx:67`

**Impact**: Short lists (e.g., 3 prediction markets) don't fill their cell; users cannot scroll News/Alerts/Calendar independently.

**Fix**: Set minimum heights for rows 3/4 (e.g., `minmax(200px, auto)` or fixed height). Ensure each widget's content area has an explicit max-height + `overflow-y-auto`.

---

### Issue 8: Sector Heatmap — Single Column Layout (MEDIUM)

**Root Cause**: `SectorHeatmapWidget` renders all 11 sectors as a single vertical list (`divide-y`). In the 130px Row 2 height with a 20px header, only ~5 sectors are visible at 22px row height. The 8-column widget has significant unused horizontal space.

**Location**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx:153`

**Impact**: User sees only the top 5-6 sectors; bottom sectors require scrolling within a 110px area — practically invisible.

**Fix**: Split into 2-column CSS grid — display all 11 sectors in 6 rows side-by-side. Alternatively use a 3-column grid for even denser display.

---

### Issue 9: TopBar IndexTicker — No Portfolio Value (LOW)

**Root Cause**: `TopBar` IndexTicker strip shows SPY/QQQ/VIX/BTC quotes only. Bloomberg Terminal, E*TRADE, and Fidelity Pro all show account NAV in the top rail.

**Location**: `apps/worldview-web/components/shell/TopBar.tsx`

**Fix**: Add portfolio total value computed from `getPortfolios()` + holdings. Display as `PORT: $123,456` between the index tickers and the bell icon.

---

### Issue 10: Alarms Badge "9+" — Panel Shows None (HIGH)

Covered in Issue 4 above. The three root causes are:
1. `unreadCount` = WebSocket session count (not REST pending count) → badge and panel track different data
2. S10 lowercase severity → `severityDotClass` falls through, makes all rows visually broken
3. `retry: false` → any transient failure shows empty

---

### Issue 11: Prediction Markets — Insufficient Horizontal Space (MEDIUM)

**Root Cause**: `PredictionMarketsWidget` is placed at `col-span-2` in Row 3, giving approximately 200px. Prediction market titles average 40-80 characters. With font-mono text-[11px], these truncate after ~25 characters. The `title` tooltip helps on hover but doesn't solve the readability problem on first scan.

**Location**: `apps/worldview-web/app/(app)/dashboard/page.tsx:112-113`

**Investigation on MarketSnapshot replacement**: MarketSnapshot (6 tickers × price/change%) is compact and genuinely useful. The best layout option is:

**Option A (Recommended)**: Restructure Row 2:
- `MarketSnapshot` stays but shrinks to `col-span-3`
- `PredictionMarkets` gets `col-span-5` (new position in Row 2)
- `SectorHeatmap` shrinks to `col-span-4`
- Row 2 becomes: `col-3 (MarketSnapshot) + col-5 (PredictionMarkets) + col-4 (SectorHeatmap)`

**Option B**: Keep Row 3 layout, expand Prediction Markets to `col-span-4` and reduce TopMovers to `col-span-2` (two-column gainers/losers still fits at 4-col).

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | S8 min_display_score=0.3 excludes all articles (0.23-0.26) | CONFIRMED | API call to `/v1/news/top`, score comparison |
| H-2 | Holdings endpoint returns no ticker/name fields | CONFIRMED | `gateway.ts:714-726` comment + code trace |
| H-3 | S10 severity lowercase → severityDotClass switch miss | CONFIRMED | `enums.py:11-14` vs `AlarmsPanel.tsx:43-50` |
| H-4 | TopBar badge counts WS events ≠ REST pending count | CONFIRMED | `AlertStreamContext.tsx:258` + `TopBar.tsx:100` |
| H-5 | Prediction markets widget too narrow for text titles | CONFIRMED | `dashboard/page.tsx:112` col-span-2 at ~200px |
| H-6 | Sector heatmap single column wastes horizontal space | CONFIRMED | `SectorHeatmapWidget.tsx:153` single divide-y list |
| H-7 | Portfolio period selector deliberately removed | CONFIRMED | `PortfolioSummary.tsx:156-160` comment |

---

## 5. Root Cause Summary

| Issue | Root Cause | Fix Complexity |
|-------|-----------|---------------|
| Brief no context | S8 `min_display_score=0.3` > article scores 0.23-0.26 | LOW (1 config change) |
| Brief format | 200-char preview cuts sentences; no headline | MEDIUM (component redesign) |
| AI Signals empty-looking | Data quality: all NEUTRAL, null article_title | N/A (data pipeline) |
| Alerts empty | Severity case mismatch + retry:false + badge/panel divergence | MEDIUM (3 fixes) |
| Holdings ticker/name | S1 endpoint returns no enrichment fields | HIGH (S1 schema change) |
| Portfolio 1D/1W/1M | No S9 endpoint exists yet | HIGH (new endpoint) |
| Component scroll/fill | Grid rows auto-height; no fixed content constraints | MEDIUM (CSS) |
| Sector single column | No 2-col grid applied | LOW (CSS) |
| TopBar portfolio value | Not implemented | LOW (new query) |
| Prediction Markets space | col-span-2 too narrow for text-heavy titles | MEDIUM (layout reorg) |

---

## 6. Impact Analysis

- **Immediate impact**: Morning Brief is entirely non-functional (no context). Portfolio widget is misleading (shows values with no ticker/name). Alarms are visually broken (all dots invisible, count divergence).
- **Blast radius**: Dashboard is the primary user entry point. Three high-value widgets (Brief, Portfolio, Alerts) are either non-functional or severely degraded.
- **Data integrity**: No data corruption. All issues are presentation/pipeline threshold issues.

---

## 7. Recommended Fix Plan

Captured in **PLAN-0045** (see `docs/plans/0045-dashboard-ux-improvements-plan.md`).

**Priority order**:
1. Wave A: Morning Brief pipeline fix (S8 threshold) + Brief format redesign
2. Wave B: Alerts fixes (severity case, retry, badge/panel alignment)
3. Wave C: Holdings enrichment (S1 ticker/name) + Portfolio page enhancements
4. Wave D: Layout improvements (Prediction Markets placement, sector 2-col, scroll/fill)
5. Wave E: TopBar portfolio value + polish

---

## 8. Contributing Factors

- `min_display_score` threshold was set to 0.3 assuming articles would reach that score; the scoring pipeline's current model produces lower scores
- Holdings endpoint design choice (S1 returns IDs only) was never revisited when the frontend needed enriched data
- Severity StrEnum casing inconsistency (S10 returns lowercase, frontend expects uppercase) is a recurring pattern across S10 consumers
- `retry: false` on AlarmsPanel was intentional for responsiveness but masks real failures

---

## 9. Prevention Recommendations

- **New bug pattern BP-252**: S10 AlertSeverity StrEnum returns lowercase; all frontend consumers must `.toUpperCase()` before comparison or switch. Applies to `Alert.severity` wherever used in conditionals.
- Add E2E smoke test that validates morning brief narrative is non-empty and contains at least 3 sentences
- Add E2E smoke test that validates holdings contain at least one ticker + name
- Add contract test that verifies S10 severity values against frontend type expectations

---

## 10. Open Questions

- Should `min_display_score=0.15` be a configurable env var or hardcoded? (Recommend env var with 0.15 default)
- S1 holdings enrichment: prefer S1 join (simpler for consumer) vs S9 enrichment (follows separation of concerns). Decision needed before Wave C.
- Row 2 restructure (Option A vs B for Prediction Markets): which layout serves the institutional trader better?
