# QA Report: PLAN-0045 Follow-Up + Dashboard UX Improvements Phase 2

**Date**: 2026-04-28
**Skill**: qa
**Scope**: PLAN-0045 post-implementation follow-up + user feedback analysis
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS (tests pass; 8 actionable findings remain)
**Report file**: docs/audits/2026-04-28-qa-plan-0045-follow-up-report.md

---

## Executive Summary

Five specialist agents reviewed the PLAN-0045 dashboard UX implementation alongside fresh user feedback from a live demo screenshot. The plan completed successfully: all unit tests (418 frontend, 535 market-data) pass, and typecheck is clean. However, 8 actionable findings remain — 4 of which are MAJOR residual issues from PLAN-0045 that the implementation did not fully address, and 4 new design improvements requested by the user. The platform is **stable but several widgets still degrade the UX** for non-finance users and investors who need more actionable data.

Key issues: (1) Recent alert rows are not individually clickable; fallback title still falls through to "LOW SIGNAL alert" when S10 payload fields are absent. (2) Prediction market volume always shows "$0 vol" because S3 list endpoint hardcodes `volume_24h=None`. (3) TopBar "D"/"U" labels are cryptic single-character abbreviations with no visible context. (4) Morning Brief header is not the compact single-line format the user expects. (5) TOP MOVERS widget shows `$0.00` prices for all instruments. (6) Portfolio Movers widget identified as useless by investor users. (7) Sector heatmap 2-col table is not visually attractive (treemap requested). (8) Test coverage for dashboard widgets is thin.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 6 | 6 | 0 | 0 | 3 | 2 | 1 |
| Security | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| Data Platform | 5 | 2 | 0 | 1 | 1 | 0 | 0 |
| Distributed Systems | 4 | 0 | 0 | 0 | 0 | 0 | 0 |
| Architecture | 5 | 5 | 0 | 0 | 4 | 1 | 0 |
| **Total** | — | **13** | **0** | **1** | **8** | **3** | **1** |

### Cross-Agent Signals (HIGH Confidence)
- **F-001**: Prediction markets volume always `$0` — Data Platform + Architecture both flagged
- **F-004**: Morning Brief header layout does not match user expectation — QA/Test + Architecture both flagged

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Lint (ruff) | full | — | — | 0 | — | PASS |
| Type Check (tsc) | frontend | — | — | 0 | — | PASS |
| Frontend Unit | apps/worldview-web | 418 | 418 | 0 | 0 | PASS |
| Market-Data Unit | services/market-data | 535 | 535 | 0 | 0 | PASS |
| Integration/E2E | all services | — | — | — | — | SKIP (infra not started) |

---

## Issues — Full Investigation

---

## Issue F-001: Prediction Markets Volume Always "$0 vol" (CRITICAL)

### Summary
The Prediction Markets widget always displays "$0 vol" for every market because S3's list endpoint hardcodes `volume_24h=None`. The gateway maps `null → 0`, which the widget formats as "$0 vol".

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Data Platform, Architecture

### Root Cause Analysis
- **What**: `services/market-data/src/market_data/api/routers/prediction_markets.py:87` has `volume_24h=None` hardcoded in the list response
- **Why**: Volume is stored on `prediction_market_snapshots` (TimescaleDB hypertable), not on the `prediction_markets` entity. The list endpoint was written to return market entities only; the snapshot JOIN was never implemented
- **Where**: S3 list endpoint → S9 proxy → frontend gateway → widget display
- **History**: Not tracked in BUG_PATTERNS.md

### Evidence
```python
# prediction_markets.py:87 (list endpoint)
volume_24h=None,  # stored in snapshot, not on market entity

# gateway.ts:1526
volume_usd: m.volume_24h ?? 0,  // null → 0

# PredictionMarketsWidget.tsx:174
const formattedVolume = market.volume_usd >= 1_000_000 ...
// volume_usd=0 → "$0 vol"
```

### Solution Options

#### Option A: Frontend null-guard (immediate, low risk)
**Description**: Show "—" when `volume_usd` is 0 or null; never show "$0 vol"
**Changes required**:
- [ ] `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx:174` — guard `volume_usd > 0`
**Effort**: Low | **Risk**: Low

#### Option B: S3 JOIN latest snapshot (proper fix, medium effort)
**Description**: Modify S3 list endpoint to LEFT JOIN `prediction_market_snapshots` for the latest `volume_24h` per market
**Changes required**:
- [ ] `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py` — add DISTINCT ON JOIN
- [ ] `services/market-data/src/market_data/api/routers/prediction_markets.py:87` — use actual value
**Effort**: Medium | **Risk**: Low (read-only, indexed JOIN)

### Recommended Option
**Option A first** (immediate display fix) + **Option B in PLAN-0047** (proper data fix).

---

## Issue F-002: Alert Rows Not Clickable / Navigable (MAJOR)

### Summary
Each alert row in `RecentAlerts.tsx` has a hover effect but is not a link — no per-row navigation to the Alerts page. The user expects clicking an alert to open the Alerts page with that alert's context visible.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture

### Root Cause Analysis
- **What**: `RecentAlerts.tsx:159-182` renders each alert as a `<div>` with hover styles but no click handler or `<Link>` wrapper
- **Why**: Original implementation omitted per-row navigation; only the footer "View all alerts →" link navigates
- **When**: Always — every alert row is non-navigable

### Evidence
```tsx
// RecentAlerts.tsx:159-182 (current)
<div
  key={alert.id}
  className="flex h-[22px] items-center gap-2 px-2 py-0 hover:bg-muted/40"
>
  // No onClick, no <Link> wrapper
```

### Solution
Wrap each alert row in `<Link href="/alerts">` for immediate navigation, or `<Link href={`/alerts?focus=${alert.id}`}>` when the alerts page supports focus-by-id.

---

## Issue F-003: Alert Title Fallback Still Shows "LOW SIGNAL alert" (MAJOR)

### Summary
The message-building fallback chain in `RecentAlerts.tsx:77-98` fires when S10's alert payload has none of the expected fields (`message`, `signal_label`, `entity_name`, `title`, `body`). The final fallback produces "LOW SIGNAL alert" — generic and non-actionable.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture, QA/Test

### Root Cause Analysis
- **What**: S10 SIGNAL alerts are sent without `signal_label`, `entity_name`, `message`, or `title` in the `payload` dict
- **Why**: The signal scoring pipeline (S6) does not inject ticker or instrument context into the alert payload
- **When**: For any SIGNAL-type alert where the payload lacks all five tried fields

### Evidence
```tsx
// RecentAlerts.tsx:98 (fallback)
return `${(a.severity ?? "").toUpperCase()} ${a.alert_type} alert`.trim();
// → "LOW SIGNAL alert" when no other field found
```

### Solution Options

#### Option A: Frontend ticker enrichment (immediate)
When `alert.entity_id` is available (it's set on the alert row), show the entity ticker using a cached overview lookup — or at minimum show `entity_id.slice(0, 8)` as context.

#### Option B: S10 payload enrichment (proper fix)
S10's `SignalAlertWorker` should inject `entity_name`, `ticker`, and `signal_label` into the payload before persisting, so consumers always have actionable context.

### Recommended Option
**Option A** first (frontend display) + **Option B** as a backend improvement in PLAN-0047.

---

## Issue F-004: Morning Brief Header Layout Not Compact Enough (MAJOR)

### Summary
The current `MorningBriefCard` shows the timestamp in a narrow h-5 header, then the LLM brief in the text area. The brief text area begins with redundant LLM-generated headers ("Market Overview", "Morning Market Briefing", "Date: 2026-04-28") that consume the first 3 visible lines of the `line-clamp-3` collapsed view, leaving no room for actual content.

The user wants: `[Date left] | [Morning Briefing title center] | [Read more → right]` on one line, with the content area showing only the substantive brief paragraph.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: QA/Test, Architecture

### Root Cause Analysis
- **What**: `MorningBriefCard.tsx:183-205` shows only the timestamp in the header. "Read more →" is buried in the text area after the content. The LLM generates preamble headers that are rendered inline.
- **Why**: The component was redesigned in PLAN-0045 Wave A-2 to have a headline + line-clamp-3 preview, but the LLM output format wasn't updated to avoid preamble headers

### Solution
1. Add `stripBriefPreamble()` to remove LLM meta-headers (Market Overview, Morning Market Briefing, Date:) from the markdown before rendering
2. Redesign the h-5 header to: `[timestamp left] | [Morning Briefing center] | [Read more → / show less right]`
3. Remove "Read more →" from the text area and the "show less" footer — both move to the header bar

---

## Issue F-005: TOP MOVERS Prices Always "$0.00" (MAJOR)

### Summary
The `PreMarketMoversWidget` shows all instrument prices as "$0.00" because the `getTopMovers()` gateway function explicitly hardcodes `price: 0` (screener results don't include current price).

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: QA/Test, Architecture

### Root Cause Analysis
- **What**: `apps/worldview-web/lib/gateway.ts:1642` has `price: 0, // Not available from screener`
- **Why**: The screener endpoint returns metrics (daily_return %) but not price; a separate quote lookup would be needed
- **When**: Always — every mover row shows $0.00

### Solution
Hide the price column when `price === 0` (show "—"). In `MoverRow`, change `mover.price != null ? \`$${...}\` : "—"` to `mover.price != null && mover.price > 0 ? \`$${...}\` : "—"`.

---

## Issue F-006: TopBar "D" / "U" Labels Cryptic (MAJOR)

### Summary
Daily P&L is labeled "D" and Unrealised P&L is labeled "U" in the TopBar. These are only explained via tooltip hover — invisible to new users and inaccessible to screen readers.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture, QA/Test

### Solution
Change labels from `"D "` and `"U "` to `"Daily "` and `"Unrlzd "` — slightly longer but unambiguous. Add `aria-label` attributes for screen reader accessibility.

---

## Issue F-007: Portfolio Movers Widget Useless for Investors (MAJOR)

### Summary
The `PreMarketMoversWidget` (TOP MOVERS section) shows market-wide gainers/losers but with `$0.00` prices (see F-005). More fundamentally, market-wide movers are less actionable than portfolio-specific or watchlist-specific data. The adjacent `PortfolioGainersLosers` (PORTFOLIO MOVERS) serves a more actionable role and is working correctly.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: MEDIUM (user feedback)
**Flagged by**: User (live demo screenshot)

### Investigation
For investors, the most valuable data in that 4-column slot would be:
1. **Watchlist Movers** — movers from the user's watchlist (requires `GET /v1/watchlists/{id}/members` + quotes)
2. **Portfolio Holdings by Daily Change** — redundant with `PortfolioGainersLosers`
3. **News-Driven Movers** — top mentioned instruments in today's news

### Decision Needed
Replace `PreMarketMoversWidget` with **Watchlist Movers** widget that shows the user's watchlist instruments and their daily moves? This is more actionable than market-wide movers. Watchlist data is already available via `getWatchlistMembers()` + `getBatchQuotes()`.

---

## Issue F-008: Test Coverage Thin for Dashboard Widgets (MINOR)

### Summary
6 key dashboard components have sparse or zero unit tests. The test suite catches regressions at the page integration level (mock-heavy) but doesn't verify individual widget behavior (fallback chains, edge cases, data transforms).

| Component | Test LOC | Production LOC | Coverage % |
|-----------|---------|---------------|------------|
| RecentAlerts | 0 dedicated | 213 | ~0% |
| PredictionMarketsWidget | 2 tests | 259 | ~10% |
| TopBar | 0 dedicated | 228 | ~0% |
| PortfolioSummary | 0 dedicated | 398 | ~0% |
| PortfolioGainersLosers | 0 dedicated | 218 | ~0% |
| MorningBriefCard | 3 tests | 343 | ~15% |

### Solution
Add to PLAN-0047 as Wave X: unit tests for the alert message fallback chain, portfolio computation logic, and morning brief extraction helpers.

---

## Fixes Applied (Phase 4)

| Finding | Fix | Status |
|---------|-----|--------|
| F-001 | Frontend null-guard for volume_usd === 0 in PredictionMarketsWidget.tsx | ✅ APPLIED |
| F-002 | Alert rows wrapped in `<Link href="/alerts">` in RecentAlerts.tsx | ✅ APPLIED |
| F-004 | MorningBriefCard: single-line header (date\|title\|CTA) + stripBriefPreamble() | ✅ APPLIED |
| F-005 | MoverRow price: show "—" when price === 0 in PreMarketMoversWidget.tsx | ✅ APPLIED |
| F-006 | TopBar labels "D"→"Daily", "U"→"Unrlzd" + aria-label attrs in TopBar.tsx | ✅ APPLIED |
| Test | briefing.test.tsx updated to match new header format (no "Generated" prefix) | ✅ APPLIED |

## Decisions Needed

| Finding | Question | Options |
|---------|----------|---------|
| F-007 | Replace PreMarketMoversWidget with what? | Watchlist Movers vs Portfolio Sector Breakdown vs other |
| F-007 | Should sector heatmap become treemap? | recharts Treemap vs custom CSS heatmap |

---

## Recommendations

1. **Immediate** (this commit): Apply fixes F-001, F-002, F-004, F-005, F-006
2. **PLAN-0047 Wave A**: S3 prediction markets volume JOIN fix (Option B from F-001)
3. **PLAN-0047 Wave B**: Replace `PreMarketMoversWidget` with Watchlist Movers widget
4. **PLAN-0047 Wave C**: Sector heatmap treemap redesign
5. **PLAN-0047 Wave D**: S10 SIGNAL alert payload enrichment (ticker/entity context)
6. **PLAN-0047 Wave E**: Dashboard widget unit test coverage

---

## Bug Patterns Added

- **BP-263** (documented in RecentAlerts.tsx): S10 PendingAlertResponse `payload` dict may lack all display fields; consumers must use a multi-step fallback chain ending in a severity+type label
- **BP-264** (new): S3 prediction market list endpoint always returns `volume_24h=None` — volume is only available from the `/history` endpoint (snapshot-level). Frontend must guard against null/0 volume display.
- **BP-265** (new): `getTopMovers` screener transform hardcodes `price: 0` — the screener endpoint does not return current prices; consumers must treat `price=0` as absent and show "—"
