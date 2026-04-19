# UI Requirements — News Intelligence Display

> **Status**: Holding doc — requirements captured from PRD discussions, not yet implemented
> **Source PRDs**: PRD-0020 (market_impact_score), PRD-0021 (AlertSeverity), PRD-0026 (ranked news APIs)
> **Implements**: Frontend UI PRD (TBD — depends on this doc)
> **APIs available**: `GET /api/v1/news/top`, `GET /api/v1/news/entity/{entity_id}` (PRD-0026)

---

## Purpose

This document captures UI/UX requirements, open decisions, and component sketches for the news intelligence display features. It is maintained as a holding doc so that when a dedicated UI PRD is written, these requirements are not lost.

All API endpoints this UI depends on are specified in PRD-0026.

---

## 1. "Top News of the Day" Feature

### Context
A tab/section showing the globally most market-relevant news articles for a configurable recent time window, ranked by `display_relevance_score`.

### Requirements
- Accessible as a **tab** in the frontend navigation (exact placement TBD — see §5 Open Decisions)
- Default time window: **24h** or **48h** (TBD — see Open Decision #1)
- Shows **top 20 articles** by default, with "Load more" or pagination
- Each article card displays:
  - Title (linked to source URL)
  - Source name + source type icon
  - Published timestamp (relative: "2h ago", "yesterday")
  - `display_relevance_score` as a visual badge (see §3 Impact Display)
  - Ticker symbol of primary entity (e.g., "AAPL") if available
  - Routing tier indicator (DEEP/MEDIUM/LIGHT) — optional, for thesis demo visibility
- Articles with `routing_tier = LIGHT` (routing_score * 0.4 only) should be visually de-emphasised
- Filter controls:
  - Time range: 24h / 48h / 7d selector (maps to `hours` param: 24, 48, 168)
  - Min relevance threshold: slider or quick filters (All / Relevant ≥0.4 / High ≥0.7)
  - Source type filter: All / News / Filings / Transcripts

### Data source
`GET /api/v1/news/top` via `getTopNews({ hours, limit, offset, min_display_score })`

---

## 2. Instrument News Panel (Company Detail Page)

### Context
When viewing a company/instrument detail page, show ranked news articles linked to that specific company, aligned to the chart's selected time range.

### Requirements
- Lives on the `CompanyDetailPage.tsx` alongside the OHLCV chart and fundamentals
- News panel shows articles for the **same date range as the active chart time range**
  - Chart shows 1-week bars → news shows last 7 days
  - Chart shows 1-month bars → news shows last 30 days
  - Chart has a sliding window → `start_date` / `end_date` move with it
  - This is purely a **frontend state linkage** — the backend accepts `start_date` / `end_date`
- Sort options:
  - Default: `display_relevance_score` DESC
  - Toggle: `published_at` DESC (chronological)
- Each article card shows (same fields as §1, but no entity info since entity is known from page context)
- **Impact windows panel** (expandable): show day_t0/t1/t2/t5 scores as a small sparkline or table for DEEP/MEDIUM articles — valuable for thesis demo
- Shows "No scored articles yet" placeholder for very new articles where impact = null

### Data source
`GET /api/v1/news/entity/{entity_id}` via `getEntityNews(entityId, { start_date, end_date, order_by })`

---

## 3. Impact / Relevance Score Display

### Open Decision (OQ-004)

**Option A — Reuse `SeverityBadge` component** (maps `display_relevance_score` → LOW/MED/HIGH/CRITICAL using PRD-0021 thresholds):
- Pro: Consistent with alert severity display; no new components
- Con: Conflates "alert severity" with "article relevance" conceptually

**Option B — New `RelevanceBadge` component** (coloured percentage or bar):
- Shows `display_relevance_score` as `0–100` score or coloured bar
- Colour scale: grey (0–0.3) → yellow (0.3–0.6) → orange (0.6–0.8) → red (0.8–1.0)
- Pro: Visually distinct from alert severity; more granular
- Con: New component needed

**Option C — `ImpactSparkline`**:
- Shows the per-window impact progression (day_t0 → day_t1 → day_t2 → day_t5) as a mini line chart
- Only for articles with ≥ 2 windows computed
- Pro: Visually rich, demonstrates the multi-window value in a thesis demo
- Con: More complex; needs chart library integration

**Recommended**: Option B (`RelevanceBadge`) for article cards; Option C (`ImpactSparkline`) as an expandable detail within the instrument news panel.

---

## 4. Fundamentals Panel (Company Detail Page)

### Context
Users want to see key financial fundamentals alongside the OHLCV chart on the company detail page. The API already returns fundamentals data via `getCompanyOverview()`.

### Requirements (captured)
- **Configurable**: users can select which metrics to display (e.g., P/E, P/B, EPS, revenue, market cap, dividend yield)
- **Default set** (TBD — need to decide which ~6-8 metrics to show by default)
- Display as a **compact metrics bar** or **collapsible sidebar panel**
- User preference for displayed metrics: stored locally (localStorage) for v1; per-user server-side after PRD-0025 auth

### Open items
- Which fundamentals are most valuable to show by default? (Candidates: P/E, EPS, Revenue TTM, Market Cap, Dividend Yield, Debt/Equity, P/S, 52-week high/low)
- Should fundamentals be in a sidebar, below the chart, or in a tab?
- Whether user preference is stored in localStorage (v1) or server-side (after PRD-0025)

### Data source
`getCompanyOverview(entityId)` → `CompanyOverview.fundamentals` (already available)

---

## 5. Open Decisions

| # | Decision | Options | Notes |
|---|----------|---------|-------|
| 1 | Default time window for "Top News" tab | 24h vs 48h | 24h is "today"; 48h avoids empty weekends |
| 2 | Navigation placement of "Top News" tab | New top-level route vs tab within existing News page | News page is currently at `/news` |
| 3 | Impact badge style | SeverityBadge reuse vs RelevanceBadge vs ImpactSparkline | See §3 |
| 4 | Fundamentals default metric set | P/E + EPS + Revenue + Market Cap + Dividend Yield + Debt/Equity | Need user validation |
| 5 | Fundamentals persistence | localStorage vs server-side | Server-side needs PRD-0025 auth |
| 6 | Should LIGHT tier articles appear in "Top News" tab? | Show with visual de-emphasis vs hide by default | LIGHT = unscored; routing_score * 0.4 only |
| 7 | Impact windows sparkline threshold | Show sparkline for ≥2 windows vs ≥3 windows | 2 windows = day_t0 + day_t1 (available after 49h) |

---

## 6. Component Inventory (to be built in UI PRD)

| Component | Location | Status | PRD-0026 dependency |
|-----------|----------|--------|---------------------|
| `TopNewsPage` or `TopNewsTab` | `pages/` or `components/` | Not built | `getTopNews()` type |
| `RelevanceBadge` | `components/news/` | Not built | `display_relevance_score` field |
| `ArticleCard` (enhanced) | `components/news/` | Not built (NewsList exists but unscored) | `RankedArticle` type |
| `ImpactSparkline` | `components/news/` | Not built | `impact_windows` field |
| `EntityNewsPanel` | `components/instrument/` | Not built | `getEntityNews()` type |
| `FundamentalsBar` | `components/instrument/` | Not built | Existing `CompanyOverview` data |
| Instrument detail page (enhanced) | `pages/CompanyDetailPage.tsx` | Partially built (chart + news) | `getEntityNews()` |

---

## 7. UX Flows

### Flow 1: Analyst checking morning news
1. User opens worldview → default route
2. Navigates to "Top News" tab
3. Sees today's top 20 articles by `display_relevance_score`
4. Clicks article title → opens source URL in new tab
5. Filters to "High ≥0.7" → sees only market-moving articles
6. Sorts by "Published At" to check timeline

### Flow 2: Investor researching a company
1. User opens company detail page for AAPL
2. Selects "1-week" chart time range
3. Entity news panel auto-updates to show last 7 days of AAPL news
4. Sees article from 3 days ago with `display_relevance_score = 0.88`, `day_t0 = 0.72`
5. Clicks article → reads why market moved
6. Toggles ImpactSparkline → sees market recovered by day_t5

---

## 8. Technical Constraints for UI Implementation

- All calls go through **S9 API gateway** (frontend never calls S6 directly)
- `start_date` / `end_date` must be **ISO-8601 UTC** strings
- `display_relevance_score` is always present; all other score fields are nullable
- `impact_windows` is null for LIGHT tier and articles < 25h old
- `primary_entity_symbol` is null when no OHLCV data was found for any entity
- Max `limit` per request: 100 (pagination required for large windows)
- Rate limit: 100 req/min via S9

---

## 9. Revision History

| Date | Change | Source |
|------|--------|--------|
| 2026-04-11 | Initial capture from PRD-0026 discussion | PRD-0026 session |
