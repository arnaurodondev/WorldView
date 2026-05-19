# Frontend Issue Registry
**Generated:** 2026-05-19
**Status:** LOCKED
**Scope:** All frontend routes/components/libs EXCEPT `components/instrument/` and `/instruments/[entityId]` (covered by PRD-0088)

---

## Summary
| Severity | Count |
|----------|-------|
| Critical (blocks demo / unprofessional) | 9 |
| High (clearly visible problem) | 18 |
| Medium (noticeable, fixable) | 24 |
| Low (polish) | 17 |
| Design System Violations (global) | 14 |
| Missing Features | 8 |
| Cross-route Inconsistencies | 9 |
| **Total** | **99** |

---

## CRITICAL — Blocks Thesis Demo / Embarrassing in Committee

| ID | Route | Issue | File:Line | Subagent |
|----|-------|-------|-----------|----------|
| CRIT-001 | /news | Primary entity in article (e.g. "AAPL") is plain text, NOT a link → no pivot to `/intelligence/[entity_id]` — breaks the core "news → entity graph" workflow that the thesis architecture sells | `app/(app)/news/page.tsx:301-305` | 1C |
| CRIT-002 | /news | Sentiment badge broken for `RankedArticle` — sentiment field is always null from S6, so `ArticleCard` falls through silently. No BULLISH/BEARISH/NEUTRAL signal visible to user | `components/news/ArticleCard.tsx:102-110` | 1C |
| CRIT-003 | /settings/preferences | Retention/preferences dropdowns are component-local state ONLY — refresh resets to defaults. User picks "30 days", reloads, sees "90". No persistence, no warning | `app/(app)/settings/preferences/page.tsx:80-105` + `data/page.tsx:80` | 1F |
| CRIT-004 | /settings/* | 5 of 8 settings subpages are MOCKED (security, data, integrations, notifications, alerts prefs) — buttons fire `console.log + toast`, no backend. Looks complete; isn't | `settings/{security,data,integrations,notifications}/page.tsx` | 1F |
| CRIT-005 | global | Zero `loading.tsx` files under `app/(app)/` → every route transition shows blank flash before content | 12+ routes | 1K |
| CRIT-006 | mutations | No retry config on any POST/PATCH/DELETE — transaction creates, portfolio creates, watchlist adds, brokerage syncs all fail silently on transient 5xx. User clicks "Add transaction", network blips, transaction is lost with no feedback | `lib/api/{portfolios,watchlists,brokerage,feedback}.ts` | 1J |
| CRIT-007 | design system | Chart sentiment colors hardcoded as constants `#26A69A` / `#EF5350` in 4+ sparkline files — STALE values (PLAN-0059 W0 updated tokens to `#00D26A` / `#FF3B5C` but constants weren't migrated). Charts render with wrong palette vs rest of UI | `AnalystTargetSparkline.tsx:8-9`, `EarningsHistoryChart.tsx:9-10`, `RevenueTrendSparklines.tsx:7-8`, `OHLCVChart.tsx:135` | 1H |
| CRIT-008 | /intelligence | `SelectedEntityProvider` doesn't reset on `entity_id` route param change → browser back/forward shows wrong entity's data in sidebar. Stale `selectedEntityId` persists across navigations | `EntitySidebar.tsx:215-224` + `intelligence/[entity_id]/page.tsx:59` | 1C |
| CRIT-009 | /dashboard | MorningBriefCard `staleTime: 30min` conflicts with "brief generated once per day" reality → user opens at 10:05am sees a brief stale by hours, with no auto-refresh signal | `MorningBriefCard.tsx:156` | 1A |

---

## HIGH — Clearly Visible Problem

| ID | Route | Issue | File:Line | Subagent |
|----|-------|-------|-----------|----------|
| HIGH-001 | /news | Article row height is 24-26px (uses `py-1`) vs the 28px CompactArticleRow standard set by PRD-0088 — feed reads cramped | `app/(app)/news/page.tsx:280-282` | 1C |
| HIGH-002 | /dashboard | 4 components use bare `rounded` (4px default) instead of `rounded-[2px]` — `MorningBriefCard:569`, `PredictionMarketsWidget:134/155/156`, `PreMarketMoversWidget:266`, `WatchlistMoversWidget:281` | (multiple) | 1A |
| HIGH-003 | /dashboard | Tablet responsive grid broken — `md:grid-cols-6` cannot reflow asymmetric Row 2 (3+4+5); iPad users see fragmented dashboard. Should be `md:grid-cols-2` | `app/(app)/dashboard/page.tsx:120` | 1A |
| HIGH-004 | /news | Sentiment shown as icon only (TrendingUp/Down/Zap) — no BULLISH/BEARISH/NEUTRAL text label. Color-blind users see nothing; non-traders don't recognize | `app/(app)/news/page.tsx:256-263` | 1C |
| HIGH-005 | /news | Filters (window, tier) NOT persisted to URL — refresh resets to defaults; no shareable "/news?hours=168&tier=DEEP" links | `app/(app)/news/page.tsx:66-76` | 1C |
| HIGH-006 | /settings | Password change form has no show/hide masking toggle — users entering 12+ char passwords can't verify they typed correctly | `app/(app)/settings/security/page.tsx:306-353` | 1F |
| HIGH-007 | /dashboard | `/v1/market/heatmap` query has `staleTime: 0` → every render refetches sector heatmap | `SectorHeatmapWidget` | 1A |
| HIGH-008 | global | `NewsTab` (835 lines) and `AlertsList` (895 lines) are statically imported on instrument-detail and workspace routes → tabs not visible at first paint still bloat bundle by ~150KB combined | `components/instrument/NewsTab.tsx`, `components/alerts/AlertsList.tsx` | 1K |
| HIGH-009 | global | Zero per-route `error.tsx` — only global error boundary catches anything; per-route recovery impossible | (all routes) | 1K |
| HIGH-010 | /chat | `chat/page.tsx:258` syncs messages from `activeThread` only when `!streaming` → opening Thread A while Thread B is streaming leaves Thread A empty until B finishes | `app/(app)/chat/page.tsx:258` | 1E |
| HIGH-011 | API | `getEntityDetail` catches 404→null; `getEntityGraph` and `getContradictions` bubble 404 as errors — inconsistent failure modes for same entity domain | `lib/api/knowledge-graph.ts:124` | 1J |
| HIGH-012 | global | `MorningBriefCard` (648 lines) loads with dashboard shell; only react-markdown is dynamic — Card chrome still costs ~30KB on initial paint | `components/dashboard/MorningBriefCard.tsx` | 1K |
| HIGH-013 | /dashboard | `MarketSnapshotWidget` "LIVE" badge hides if ANY ticker search fails → partial success looks like total failure | `MarketSnapshotWidget.tsx:170-171` | 1A |
| HIGH-014 | /screener vs /instruments | Inconsistent entity-id fallback: screener uses `row.instrument_id ?? row.entity_id`; instruments list uses `row.entity_id` only. Same destination, different paths | `screener/page.tsx:357`, `instruments/page.tsx:220` | 1D |
| HIGH-015 | /chat | `ToolCallIndicator` uses `animate-spin` — Bloomberg/terminal design rule (TypingIndicator comment :70) explicitly forbids animations on data surfaces | `features/chat/components/ToolCallIndicator.tsx:95` | 1E |
| HIGH-016 | /portfolio | Realized P&L "(approx)" badge when fallback math kicks in has no refresh affordance — users can't tell when they're looking at approximation vs actual | `PortfolioKPIStrip.tsx:256-293` | 1B |
| HIGH-017 | /settings | Settings sidebar long labels ("Search & view history") truncate without `max-w` on the span — overflow on narrower viewports | `app/(app)/settings/layout.tsx:88-89` | 1F |
| HIGH-018 | API | `getTopNews()`, `getFundamentals()`, `getEntityGraph()`, `runScreener()`, `getBatchQuotes()` have NO staleTime in the API method — every consumer guesses → same endpoint hit with different staleTimes across components | `lib/api/{news,instruments,knowledge-graph,screener}.ts` | 1J |

---

## MEDIUM — Noticeable

| ID | Route | Issue | Subagent |
|----|-------|-------|----------|
| MED-001 | /dashboard | `MorningBriefCard` spans full 12 cols with no max-width on narrative text — reads as full-width article, not compact dashboard signal | 1A |
| MED-002 | /dashboard | Hardcoded `calc(100vh - 36px)` topbar height in dashboard grid; fragile if topbar resizes for mobile/responsive | 1A |
| MED-003 | /dashboard | `RecentAlerts` merges WebSocket + 30s poll but orders live-first — HIGH-severity alert after a LOW poll appears below it | 1A |
| MED-004 | /dashboard | `EconomicCalendar.parseDesc()` regex breaks on real-world strings like "Forecast: $1.2B" or "Actual: 1,234.5" | 1A |
| MED-005 | /dashboard | `SectorHeatmapWidget` hardcoded for exactly 11 sector tiles — 12th sector wraps row, breaks grid budget | 1A |
| MED-006 | /news | `ArticleCard` and news page render `display_relevance_score` in different positions (top-right after source vs after timestamp) | 1C |
| MED-007 | /news | No sentiment filter UI despite PRD-0026 specifying sentiment scoring as a tier in display_relevance_score | 1C |
| MED-008 | /news | Article detail view NOT IMPLEMENTED — clicking article opens external URL in new tab; no in-app summary/related | 1C |
| MED-009 | /intelligence | EvidenceTab + RelationsTab render "Filtered to:" banner; PathsTab + NarrativeHistoryTab do NOT — asymmetric tab UX | 1C |
| MED-010 | /screener | ~10 filter metrics (gross margin, debt/equity, current ratio, news velocity, controversy, recent earnings, insider activity) are UI-only — wired but documented as "backend-pending" | 1D |
| MED-011 | /screener | AG Grid column-group headers (PRICE, FUNDAMENTALS) have no text-color styling — may render white-on-white | 1D |
| MED-012 | /chat | Streaming bubble lazy-loads `react-markdown` with no fallback → ~100ms blank flash on first response | 1E |
| MED-013 | /chat | SSE parser duplicated between `useChatStream.ts` and `ActionConfirmModal.tsx` — protocol drift risk | 1E |
| MED-014 | /chat | `ActionConfirmModal:254` defaults `severity: "low"` when omitted → could silently create alerts with wrong severity | 1E |
| MED-015 | /settings | Delete-account confirmation input has zero visual feedback on wrong phrase (no aria-invalid, no red border) | 1F |
| MED-016 | /settings | Retention dropdown trigger uses fixed `w-44` — labels like "90 days (recommended)" may overflow | 1F |
| MED-017 | /settings | Login "Dev Login" uses `border-warning/50 text-warning` (amber/danger) — semantically wrong for a dev bypass | 1F |
| MED-018 | design system | `EntityGraphPanel` hardcodes entity-type node colors (person=teal, event=amber, topic=blue, default=grey) outside the token system — limits theming | 1H |
| MED-019 | design system | `OHLCVChart.tsx:135` uses `#0EA5E9` (legacy Midnight Pro blue) for MA line — palette drift | 1H |
| MED-020 | design system | `data-table.stories.tsx:13` uses `bg-[#131722]` (old Midnight Pro background) instead of `bg-background` | 1H |
| MED-021 | API | 7 paginated endpoints (alerts, feedback, transactions, news, search docs, watchlists members, brokerage sync errors) use static `useQuery` with manual offset — not `useInfiniteQuery` | 1J |
| MED-022 | /settings | Missing API: `getNotificationPreferences()` / `setNotificationPreferences()` — key exists in `qk.user.notificationPrefs` but no method | 1J |
| MED-023 | /portfolio | Holdings AG Grid column-width localStorage persistence silently fails on quota error — user loses layout without warning | 1B |
| MED-024 | /chat | Hardcoded model names/endpoints check came back clean but `getTopNews` / `getFundamentals` have no comment on cache strategy → future stale-time confusion | 1J |

---

## LOW — Polish

| ID | Description | Subagent |
|----|-------------|----------|
| LOW-001 | News "Load 50 more" button missing `aria-busy` during fetch | 1C |
| LOW-002 | News "Load more" has no upper bound — DOM bloat at 10K articles | 1C |
| LOW-003 | News page `(score*100).toFixed(0)` not tabular-nums on "Load N more" text | 1C |
| LOW-004 | PathsTab `hop_count` NOT tabular-nums (composite score is) | 1C |
| LOW-005 | MorningBriefCard `text-[9px]` outside approved [10-13px] range (multiple instances) | 1A |
| LOW-006 | `useChatStream.ts:286` `isStreamingRef` set after validation, not before — 0-1ms race window if user spam-clicks Send | 1E |
| LOW-007 | Search debounce inconsistency: 400ms in instruments, 300ms in /search | 1D |
| LOW-008 | Screener "Load More" count `accumulator.length` lags behind grid re-render briefly (~100ms) | 1D |
| LOW-009 | AG Grid sort state lost on tab-switch + return; intentional but worth documenting | 1D |
| LOW-010 | `/screen` is a 307 redirect to `/screener` — intentional alias but should be in sitemap/robots | 1D |
| LOW-011 | Sentry session list IPv6/long-IP rendering without `break-all` | 1F |
| LOW-012 | Webhook URL display has `break-all` but no max-height — long URLs balloon row vertically | 1F |
| LOW-013 | `ConnectedBrokeragesList.tsx:36-38` uses inline `style={{ color: "#26A69A" }}` instead of `text-positive` class | 1H |
| LOW-014 | Settings `CardHeader pb-3` + page `space-y-3` → inverted hierarchy (items tighter inside cards than between) | 1F |
| LOW-015 | Markdown inline code uses `text-[8px]` — outside approved range but visually justified for de-emphasis | 1H |
| LOW-016 | Auth refresh: `eslint-disable-line` on `callback/page.tsx:169` without inline comment explaining why setTokens isn't in deps | 1F |
| LOW-017 | Dev login fallback `setTimeout(..., 600)` has no error handling — promise never rejects on failure | 1F |

---

## DESIGN SYSTEM VIOLATIONS (Apply Globally — Fix Once)

| Violation | Instances | Resolution |
|-----------|-----------|------------|
| DS-001 | Bare `rounded` (4px default) instead of `rounded-[2px]` | 4 dashboard widgets confirmed; full sweep needed | grep + replace `rounded\s` → `rounded-[2px]` |
| DS-002 | Hardcoded chart sentiment colors (`#26A69A`, `#EF5350`) — stale | 4 files: AnalystTarget, EarningsHistory, RevenueTrend, OHLCV | Add `--chart-positive` / `--chart-negative` tokens; replace constants with `hsl(var(--chart-positive))` |
| DS-003 | Stale palette references (`#0EA5E9`, `#131722`) | OHLCVChart MA line, data-table story bg | Replace with current tokens |
| DS-004 | Entity graph node colors hardcoded outside tokens | `EntityGraphPanel.tsx:11-14` | Define `--entity-type-{person,event,topic,default}` tokens |
| DS-005 | `text-[9px]` outside the approved [10-13px] range | Dashboard widgets (multiple) | Either bump to text-[10px] or amend ADR-F-15 to permit 9px |
| DS-006 | font-mono missing on numeric values (selective) | PathsTab hop_count; "Load N more" button; PricingTiers % | Wrap numerics in `<FormattedNumber>` component (new shared primitive) |
| DS-007 | Inline `style={{ color: "#hex" }}` instead of class | `ConnectedBrokeragesList`, sparkline annotations | Use Tailwind class with token |
| DS-008 | News sentiment icon-only (no BULLISH/BEARISH/NEUTRAL label) | News page article rows | Add text label next to icon |
| DS-009 | Duplicate clipboard logic (AliasPill, MarkdownContent, DataTable each implement) | 3 sites | Extract `useCopyToClipboard()` hook |
| DS-010 | Duplicate keyboard-shortcut logic (GlobalSearch, QuickEditPopover, FlashOverlay) | 3+ sites | Extract `useKeyboardShortcuts()` hook |
| DS-011 | Number formatting fragmented (`formatPrice`, `formatShorthand`, `formatCompactCurrency`) | 3 utilities, no canonical | Consolidate into `lib/format.ts` exports |
| DS-012 | Density-height classes redeclared (Button, Input, DateRangePicker, etc.) | 4+ components | Move to `lib/ui-constants.ts` as `DENSITY_CLASSES` record |
| DS-013 | Sparkline column suppressed at >200 rows but column still renders empty (no skeleton) | Screener | Hide column or show "—" placeholder |
| DS-014 | Settings icons use `strokeWidth={1.5}` vs sidebar nav defaults (2) — inconsistent weight | Settings tabs | Standardize to one stroke width |

---

## MISSING FEATURES (Implied by Architecture, Not Built)

| ID | Feature | Evidence |
|----|---------|----------|
| MISS-001 | News article detail view (in-app) — modal, slide-over, or route | Articles open external URL; PRD-0026 implies in-app summary |
| MISS-002 | News sentiment filter UI | PRD-0026 sentiment tier in display_relevance_score; no filter exposes it |
| MISS-003 | Notification preferences (settings) | `qk.user.notificationPrefs` key exists; no API or UI |
| MISS-004 | Workspace CRUD APIs (named workspaces) | `qk.workspace.*` keys exist; PRD-0031 references named workspaces; no API |
| MISS-005 | Briefing subscription/frequency preferences | BriefingResponse implies email delivery; no preference API |
| MISS-006 | Admin LLM costs dashboard | `S9AdminLlmCostsResponse` type exported; no getAdminLlmCosts method |
| MISS-007 | Entity enrichment manual trigger | KG enrichment API exists backend; no "refresh entity" frontend trigger |
| MISS-008 | Settings retention persistence (chat/search history retention) | UI exists but is component-local state only |

---

## CROSS-ROUTE INCONSISTENCIES

| ID | Inconsistency | Resolution |
|----|---------------|------------|
| INC-001 | entity-id navigation fallback: screener uses `instrument_id ?? entity_id`; instruments list uses `entity_id` only | Pick one; verify backend always populates `entity_id` |
| INC-002 | Search debounce: 400ms (instruments) vs 300ms (search) | Standardize to 300ms |
| INC-003 | 404 handling: `getEntityDetail` catches→null; `getEntityGraph`/`getContradictions` throw | Pick one (recommend: all return null on 404 for entity domain) |
| INC-004 | Batch endpoint fallback: `POST /v1/ohlcv/batch` falls back to per-instrument on 404; `POST /v1/quotes/batch` does not | Both should fall back consistently |
| INC-005 | Tab "Filtered to:" banner: shown in EvidenceTab + RelationsTab, missing in PathsTab + NarrativeHistoryTab | Add to all 4 |
| INC-006 | Header heights: /screener uses `h-9` (36px), /search uses `h-7` (28px); intentional but undocumented | Document the dual-pattern in DESIGN_SYSTEM.md |
| INC-007 | Sentiment color mapping: news page (token classes) vs ArticleCard fallback (threshold-based) vs comments referencing `#787B86` | Single canonical sentiment palette across all surfaces |
| INC-008 | staleTime per endpoint varies by component (TopNews, Fundamentals, EntityGraph, Quotes, Screener) | Move to API method defaults |
| INC-009 | Empty states: `DashboardEmptyState` (full-panel) vs `InlineEmptyState` (inline) vs ad-hoc inline divs across portfolio/news | Always use one of the two; never ad-hoc |
