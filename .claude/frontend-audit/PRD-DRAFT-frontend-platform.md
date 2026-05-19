# PRD: Frontend Platform Hardening (non-instrument routes)

**Status:** DONE — completed 2026-05-19
**Branch (recommended):** `feat/frontend-platform-hardening` (do NOT collide with `fix/instrument-page-redesign` which owns PRD-0088)
**Generated:** 2026-05-19
**Scope:** Every frontend route, shared component, lib, and design token EXCEPT `components/instrument/` and `/instruments/[entityId]` (already covered by PRD-0088).

---

## 1. Problem Statement

The frontend has been built route-by-route over the past two months by different waves of work (PLAN-0025 auth, PLAN-0031 terminal UI, PLAN-0059 polish sprint, PLAN-0070 bundles, PLAN-0088 instrument redesign). Each landed working, but the seams between them now show:

- **Five settings sub-pages are mocked**: security, data, integrations, notifications, alerts-prefs all fire `console.log + toast` and never round-trip a backend. A thesis committee opens any one of them and the illusion of a complete product breaks.
- **The news → entity → graph workflow that the thesis architecture sells is broken**: clicking a ticker symbol on a news article does nothing; sentiment badges render blank because the field is always null from S6; refreshing the page wipes filter state.
- **A flagship route (the dashboard) ships 4 design-system violations** — bare `rounded` instead of `rounded-[2px]`, `text-[9px]` outside the approved scale, hardcoded `calc(100vh - 36px)` topbar height, tablet grid that fragments on iPad.
- **Chart colors drifted off the design-token system** — sentiment constants (`#26A69A` / `#EF5350`) are hardcoded in sparkline files and never got migrated when PLAN-0059 W0 updated the official `--positive` / `--negative` tokens. Charts now render with a different green than the rest of the UI.
- **Twelve routes have no `loading.tsx`** — every navigation between pages shows a blank white flash before content paints. For a "terminal-grade" platform, this is an instant credibility loss.
- **API mutations have zero retry config** — a transient 5xx on `POST /v1/transactions` silently drops the user's transaction with no feedback. Same for portfolio creation, watchlist member adds, brokerage syncs.
- **Performance leaks**: `NewsTab` (835 lines) and `AlertsList` (895 lines) are statically imported on routes where they live behind a collapsed tab or panel — ~150KB of unused JS on first paint.

PRD-0088 is fixing one route at a time (the instrument detail page). This PRD fixes the remaining 13 routes and the global infrastructure they share, applying one consistent design system instead of letting each route drift.

---

## 2. Target Users

- **Arnau (thesis defence)** — needs every visible surface to be coherent, fast, and fully functional, not 75% complete with stub buttons. The "polish bar" is a thesis committee on a 27" display in a quiet room.
- **Beta users** (~5 in PRD-0022 free-tier) — analysts who will click every settings tab once. Mocked tabs erode trust faster than missing tabs.
- **Solo institutional analyst (target ICP, PRD-0027)** — keyboard-driven, dense-data, Bloomberg-Terminal-fluent. They notice 1px misalignments in tabular data.

---

## 3. Functional Requirements

### FR-1 Dashboard — Visual + Behavioral Fixes
- **FR-1.1** Replace all bare `rounded` with `rounded-[2px]` in: `MorningBriefCard.tsx:569`, `PredictionMarketsWidget.tsx:134/155/156`, `PreMarketMoversWidget.tsx:266`, `WatchlistMoversWidget.tsx:281`. Acceptance: visual diff shows 2px corners on every card/chip on `/dashboard`.
- **FR-1.2** Change responsive grid from `md:grid-cols-6` to `md:grid-cols-2` so tablet (iPad Pro) lays out as 2-up instead of fragmenting Row 2's asymmetric 3+4+5 layout. File: `app/(app)/dashboard/page.tsx:120`.
- **FR-1.3** Replace `height: "calc(100vh - 36px)"` with CSS variable `--topbar-height` injected by `(app)/layout.tsx`. File: `app/(app)/dashboard/page.tsx:122`.
- **FR-1.4** `MorningBriefCard` staleTime changes from `30min` to `12h`, with a hook that invalidates the query at next 00:00 UTC. File: `MorningBriefCard.tsx:156`. WHY: brief is generated once per day; a 30-min stale window is meaningless and surfaces a brief that's hours old at 10am.
- **FR-1.5** `MarketSnapshotWidget` "LIVE" badge shows if AT LEAST ONE ticker resolved (current: only if ALL resolved). File: `:170-171`.
- **FR-1.6** `RecentAlerts` merges WS + poll results sorted by `(severity DESC, created_at DESC)`, not live-first.
- **FR-1.7** `SectorHeatmapWidget` grid auto-sizes to N sectors via `grid-cols-[repeat(auto-fit,minmax(120px,1fr))]` instead of hardcoding 11.
- **FR-1.8** `/v1/market/heatmap` query sets `staleTime: 300000` (5 min) — current `0` causes refetch on every render.

### FR-2 News — Workflow Repair
- **FR-2.1** Article row uses `py-1.5` (28px row height), matching CompactArticleRow standard. File: `app/(app)/news/page.tsx:280-282`.
- **FR-2.2** Primary entity (e.g., "AAPL") renders as a `<Link href={`/intelligence/${entity_id}`}>` — currently plain text. File: `app/(app)/news/page.tsx:301-305`. Requires the article payload to carry `primary_entity_id` (it already does; just not used).
- **FR-2.3** Sentiment label: render explicit `BULLISH` / `BEARISH` / `NEUTRAL` text badge next to the icon, using `text-positive` / `text-negative` / `text-muted-foreground` colors. Color-only signal is insufficient.
- **FR-2.4** Sentiment-source fix: `ArticleCard` no longer falls through when `RankedArticle.sentiment` is null. Instead, derive sentiment from `display_relevance_score` thresholds OR add a dedicated `signal_direction` field to `RankedArticle` type. (Decision: defer the field; use threshold derivation for now.)
- **FR-2.5** Filter state (`windowKey`, `tier`, future `sentiment`) is persisted via `nuqs` URL params. Refresh and shareable links work.
- **FR-2.6** Add sentiment filter to the filter bar (positive / negative / neutral / all).
- **FR-2.7** "Load 50 more" button gets `aria-busy={isFetching}` and a hard cap of 1000 articles loaded (after which it shows "Show all 5,000 — use date range to narrow").

### FR-3 Intelligence — Navigation + Tab Symmetry
- **FR-3.1** `SelectedEntityProvider` resets `selectedEntityId` to the route's `entity_id` whenever the route param changes. File: wrap provider in a key-on-param effect at `intelligence/[entity_id]/page.tsx:59`. Fixes stale sidebar on browser back/forward.
- **FR-3.2** PathsTab + NarrativeHistoryTab render the same "Filtered to: [entity]" banner that EvidenceTab + RelationsTab render. Acceptance: all 4 tabs show consistent filtered-state UI.
- **FR-3.3** `EntitySidebar` graph fetch uses the same depth as `GraphPanel` (currently sidebar always depth=2, panel can be 3+) — pass depth via context.

### FR-4 Screener / Instruments — Consistency
- **FR-4.1** Both `/screener` and `/instruments` use the same entity-id resolution: `router.push(`/instruments/${row.entity_id ?? row.instrument_id}`)`. Verify with backend that screener response always carries `entity_id`.
- **FR-4.2** Search debounce standardized to 300ms across `/instruments` and `/search` (currently 400ms vs 300ms).
- **FR-4.3** AG Grid column-group headers get explicit color tokens via CSS rule for `.ag-header-group-text` in `globals.css`.
- **FR-4.4** Filter-bar metrics marked "backend-pending" (gross margin, debt/equity, current ratio, news velocity, controversy, recent earnings, insider activity) are hidden behind a feature flag `NEXT_PUBLIC_ENABLE_PENDING_METRICS=false` (default off) until backend support lands. WHY: avoid showing the user a filter that silently doesn't work.
- **FR-4.5** Sparkline column on screener: when >200 rows, render an em-dash placeholder instead of an empty cell.

### FR-5 Chat — Streaming + Tool Indicator
- **FR-5.1** `chat/page.tsx:258` sync effect drops the `!streaming` guard — always sync messages from the active thread query so opening Thread A while Thread B is streaming works.
- **FR-5.2** Replace `animate-spin` on `ToolCallIndicator` with a static icon + text label ("Calling tool: <name>…"). WHY: terminal design rule (TypingIndicator comment :70) forbids animations on data surfaces.
- **FR-5.3** Set `isStreamingRef.current = true` immediately after input validation, before request setup, closing the 0-1ms double-send window.
- **FR-5.4** Default `severity: "low"` is REMOVED from `ActionConfirmModal:254` — severity is required in the request body when the backend asks for it.
- **FR-5.5** Streaming bubble shows a `<TypingIndicator>` (already static dots) while the `react-markdown` bundle loads, not blank space.
- **FR-5.6** Extract shared SSE parser into `lib/sse-parser.ts`; both `useChatStream` and `ActionConfirmModal` import it.

### FR-6 Settings — Wire or Hide
- **FR-6.1** Profile page (`/settings/profile`) — already correct (reads JWT claims, read-only). No changes.
- **FR-6.2** Preferences page (`/settings/preferences`) — wires retention dropdowns and notification toggles to localStorage via `PreferencesContext` (already exists for density/currency/timezone). Acceptance: select "30 days", reload, still "30 days".
- **FR-6.3** Notifications page — wire the 4 toggles (price alerts, news, movers, contradictions) to `POST /v1/users/me/notification-preferences` (NEW endpoint — see FR-8). Until backend lands, hide the page from the sidebar and return 404.
- **FR-6.4** Security page — same treatment: until S1 backend lands `PATCH /v1/auth/password`, `POST /v1/auth/mfa`, `GET /v1/auth/sessions`, the page is hidden from the sidebar and the route returns 404. WHY: shipping a fake "Change password" button is worse than shipping no button.
- **FR-6.5** Data page — chat/search retention selectors wire to PreferencesContext (localStorage); export and delete-account buttons are hidden behind `NEXT_PUBLIC_ENABLE_DATA_OPS=false` until backend exists.
- **FR-6.6** Integrations page — brokerage link kept (it works); Slack/webhooks/email-digest hidden behind `NEXT_PUBLIC_ENABLE_INTEGRATIONS=false`.
- **FR-6.7** Beta program page — already fully wired. No changes.
- **FR-6.8** Settings sidebar — items hidden by feature flags collapse cleanly; long labels get `max-w-[140px]` + truncate.
- **FR-6.9** Password field (when security page eventually ships): add eye-icon show/hide toggle.

### FR-7 Auth + Layout
- **FR-7.1** Add an inline comment on `callback/page.tsx:169` `eslint-disable-line` explaining why `setTokens` is stable (from context). One line.
- **FR-7.2** Dev login fallback `setTimeout(..., 600)` wrapped in try/catch with a hard timeout of 5s — failure clears `isDevLoggingIn`.
- **FR-7.3** Dev Login button restyle: `variant="ghost"` + smaller + `text-muted-foreground` — currently amber/warning styling implies danger semantics.
- **FR-7.4** PRD-0031 §4.2 amendment note: document that PLAN-0071 Phase 6.5 reduced collapsed sidebar from 48px to 40px. (Documentation-only; code is correct.)

### FR-8 API Surface — Hardening
- **FR-8.1** All mutations (POST/PATCH/DELETE) get retry config: `retry: 3, retryDelay: (n) => Math.min(1000 * 2 ** (n-1), 4000)`. Apply to: `createPortfolio`, `addTransaction`, `addWatchlistMember`, `syncBrokerage`, `submitFeedback`, `voteFeatureRequest`, etc. WHY: silent dropping of user actions on transient 5xx is unacceptable for a finance app.
- **FR-8.2** Standardize 404 handling for entity endpoints: `getEntityDetail`, `getEntityGraph`, `getContradictions`, `getEntityNarratives` all catch 404 and return `null` (currently only `getEntityDetail` does). WHY: 404 means "not yet enriched", same semantic across all entity endpoints.
- **FR-8.3** Add 404 fallback to `POST /v1/quotes/batch` mirroring `POST /v1/ohlcv/batch` — fall back to per-instrument calls.
- **FR-8.4** Add API-method-level `defaultStaleTime` to: `getTopNews` (300s), `getFundamentals` (3600s), `getEntityGraph` (60s), `getBatchQuotes` (15s), `runScreener` (30s), `getScreenerFields` (21600s = 6h). Encode in a single helper:
  ```ts
  export const DEFAULT_STALE = {
    news: 300_000, fundamentals: 3_600_000, entityGraph: 60_000,
    quotes: 15_000, screener: 30_000, screenerFields: 21_600_000,
    portfolio: 60_000, alerts: 15_000,
  } as const;
  ```
- **FR-8.5** New endpoint: `GET /v1/users/me/notification-preferences` + `PATCH /v1/users/me/notification-preferences` — required by FR-6.3. Backend wave dependency.
- **FR-8.6** Migrate 4 of the 7 paginated endpoints to `useInfiniteQuery`: `/v1/alerts/history`, `/v1/transactions`, `/v1/news/top`, `/v1/search` (documents). The other 3 (feedback submissions, feature requests, brokerage sync errors) can stay on static `useQuery` (low volume).

### FR-9 Performance + Loading States
- **FR-9.1** Add `loading.tsx` to every route under `app/(app)/`: dashboard, screener, screen, portfolio, instruments, news, intelligence, chat, alerts, workspace, watchlists, search, settings (and sub-routes), prediction-markets. Each renders a route-appropriate skeleton matching the page's first-paint layout.
- **FR-9.2** Add `error.tsx` to every top-level `app/(app)/<route>/` — minimum: error message + "Try again" + "Back to dashboard".
- **FR-9.3** Wrap `NewsTab` and `AlertsList` in `dynamic(() => import(...), { ssr: false, loading: () => <Skeleton /> })` when imported into routes where they are not visible at first paint (instrument detail, workspace).
- **FR-9.4** Wrap `html2canvas`, `jspdf`, `jspdf-autotable` in dynamic imports inside the export menu / screenshot capture entry points — currently in main bundle.

### FR-10 Design System — Token Migration
- **FR-10.1** Add chart-specific tokens to `globals.css`:
  ```css
  --chart-positive: 150 100% 41%;  /* matches --positive */
  --chart-negative: 350 100% 62%;  /* matches --negative */
  --chart-neutral: 240 4% 56%;
  --chart-ma-fast: 47 100% 52%;    /* yellow */
  --chart-ma-slow: 217 91% 60%;    /* blue replacement for #0EA5E9 */
  ```
- **FR-10.2** Migrate `COLOR_POSITIVE`/`COLOR_NEGATIVE` constants in 4 sparkline files to `hsl(var(--chart-positive))` / `hsl(var(--chart-negative))` form. Files: `AnalystTargetSparkline.tsx:8-9`, `EarningsHistoryChart.tsx:9-10`, `RevenueTrendSparklines.tsx:7-8`, `OHLCVChart.tsx:135`.
- **FR-10.3** Add entity-graph node tokens:
  ```css
  --entity-type-person-fill: ...; --entity-type-person-stroke: ...;
  --entity-type-event-fill: ...;  --entity-type-event-stroke: ...;
  --entity-type-topic-fill: ...;  --entity-type-topic-stroke: ...;
  --entity-type-default-fill: ...; --entity-type-default-stroke: ...;
  ```
  Migrate `EntityGraphPanel.tsx:11-14` to reference them.
- **FR-10.4** Replace `bg-[#131722]` in `data-table.stories.tsx:13` with `bg-background`.
- **FR-10.5** Decide on `text-[9px]`: either bump every instance to `text-[10px]` OR amend ADR-F-15 to permit 9px for labels (not data values). Recommendation: amend ADR-F-15 — 9px is useful for secondary metadata.
- **FR-10.6** Create `<FormattedNumber>` shared primitive that always applies `font-mono tabular-nums`. Replace inline numeric renders in: news "Load N more" button, PathsTab `hop_count`, PricingTiers, screener counters.
- **FR-10.7** Extract shared hooks: `useCopyToClipboard()` (replaces 3 implementations), `useKeyboardShortcuts()` (replaces 3+), `useFormattedTimestamp()` (replaces 3).
- **FR-10.8** Replace inline `style={{ color: "#26A69A" }}` in `ConnectedBrokeragesList.tsx:36-38` with `text-positive` classes.

---

## 4. Non-Functional Requirements

- **NFR-1** Every numeric value rendered to the user uses `font-mono tabular-nums` (ADR-F-15). Enforced via `<FormattedNumber>` primitive + ESLint rule (custom rule in next phase).
- **NFR-2** First Contentful Paint on `/dashboard` cold load < 1.5s on 4G; LCP < 2.5s. Bundlewatch budget unchanged.
- **NFR-3** Route transition: < 100ms to skeleton paint (FR-9.1 loading.tsx files).
- **NFR-4** Every mutation has retry; no silent failure on transient 5xx.
- **NFR-5** All settings sub-pages either fully functional or returning 404 with a feature flag. No mocked buttons in shipped routes.
- **NFR-6** Lighthouse a11y ≥ 95 on dashboard, news, portfolio.

---

## 5. Out of Scope

- `components/instrument/` and `/instruments/[entityId]` — owned by PRD-0088 on branch `fix/instrument-page-redesign`.
- New backend endpoints beyond FR-8.5 (notification-preferences). All other backend gaps stay backend-side.
- Mobile/responsive support below 1280px — explicitly desktop-only per PRD-0031.
- Light theme — permanently dark, per PRD-0031.
- Component-library migration (no move off shadcn/ui).
- AG Grid → alternative grid migration.
- Polymarket / prediction-markets visual redesign (separate PRD if needed).
- Admin LLM costs dashboard (defer to follow-up PRD).
- Workspace named-instances CRUD (defer; key reservations only).

---

## 6. Technical Design

### 6.1 Affected Routes (13)

| Route | Severity (this PRD) | Wave |
|-------|---------------------|------|
| /dashboard | HIGH | 3 |
| /news | CRITICAL | 4 |
| /intelligence/[entity_id] | CRITICAL | 4 |
| /screener, /screen | MEDIUM | 5 |
| /instruments (list only) | MEDIUM | 5 |
| /search | LOW | 5 |
| /watchlists | LOW | 5 |
| /chat | MEDIUM | 6 |
| /portfolio | LOW | 7 (only realized-P&L refresh affordance) |
| /alerts | MEDIUM | 7 |
| /settings (+ subroutes) | CRITICAL | 8 |
| /login, /callback | LOW | 8 |
| (app)/layout, root | LOW | 1 |

### 6.2 Design System Fixes (Global — Wave 0/1)

All of FR-10 ships as Wave 0 (tokens, hooks, primitives) before any route-level work. Route waves consume the new tokens and primitives.

New shared primitives (Wave 0):
- `<FormattedNumber value={x} format="currency" />` — always `font-mono tabular-nums`
- `<SignalBadge sentiment="bullish" />` — text + icon + correct token color
- `useCopyToClipboard()` hook
- `useKeyboardShortcuts(map)` hook
- `useFormattedTimestamp()` hook
- `DENSITY_CLASSES` constant export from `lib/ui-constants.ts`
- `lib/sse-parser.ts` — shared SSE event parser (FR-5.6)
- `DEFAULT_STALE` constant export from `lib/api/_client.ts` (FR-8.4)

### 6.3 Per-Route Specifications

(Sections 6.3.1–6.3.13 mirror PRD-0088 structure: for each route, list the FRs that apply, the files touched, the test plan. Omitted from this draft for length; will be expanded after FR list is approved.)

### 6.N Visual Density Reference

| Surface | Row height | Font size | Padding | Border radius |
|---------|------------|-----------|---------|---------------|
| Tabular data row (holdings, transactions, screener) | 22px (`h-[22px]`) | `text-[11px]` | `px-2 py-0.5` | `rounded-[2px]` |
| News / article row | 28px (`py-1.5`) | `text-[11px]` | `px-3 py-1.5` | n/a (border-b divider) |
| Tab bar | 32px (`h-8`) | `text-[11px]` | `px-3` | `rounded-none` |
| Header / topbar | 36px (CSS var `--topbar-height`) | `text-[12px]` | `px-3` | n/a |
| Banner / collapsed | 24px | `text-[10px]` | `px-2` | `rounded-[2px]` |
| Sidebar nav item | 28px | `text-[11px]` | `px-2 py-1.5` | `rounded-[2px]` |
| Card | n/a | `text-[12px]` body | `p-3` | `rounded-[2px]` |
| Button (default density) | 36px (`h-9`) | `text-[12px]` | `px-3` | `rounded-[2px]` |
| Button (compact) | 28px (`h-7`) | `text-[11px]` | `px-2` | `rounded-[2px]` |
| Badge / pill | n/a | `text-[10px]` or `text-[11px]` | `px-1.5 py-0.5` | `rounded-full` |

All numeric values: `font-mono tabular-nums slashed-zero`.
All P&L: `text-positive` (gain) / `text-negative` (loss) — no other colors permitted for gain/loss.

---

## 7. Architecture Compliance Gate

- **R14 Frontend → S9 only** — every API call must remain proxied through S9. Verified per-endpoint in audit; FR-8 maintains this.
- **R16 API uses only use cases (backend)** — N/A frontend-side, but FR-8.5 requires backend wave to expose new endpoint through use cases, not direct DB.
- **R27 Read replica routing (backend)** — N/A frontend.
- **ADR-F-15 font-mono on numerics** — NFR-1 + FR-10.6 enforce.
- **ADR-F-03 in-place migration** — N/A (we're not migrating frontend location).
- **PRD-0031 Terminal UI** — this PRD honors the established density spec; does NOT propose a v4 redesign.

---

## 8. Break-Surface Analysis

- **Existing tests** — DataTable, AlertsList, MorningBriefCard have substantial unit-test coverage; route changes need new component tests, not modified ones (R19: never delete tests).
- **Bundle budgets** — FR-9.3/9.4 dynamic imports should REDUCE bundle sizes; revalidate `bundlewatch.config.json` after Wave 2 implementation. Lower budgets are OK; don't raise.
- **URL params** — FR-2.5 introduces `nuqs` params on `/news`; existing direct links continue to work because defaults are unchanged.
- **Settings hidden routes** — FR-6.3/6.4/6.5/6.6 hide pages from the sidebar but keep route registered (return 404). Any documentation link to `/settings/security` becomes a 404; update docs.
- **API method signatures** — FR-8.4 adds optional `staleTime` argument to query helpers (currently passed by component). Backwards compatible if argument is `?: number`.
- **Token rename** — FR-10.1 introduces new tokens; existing `--positive`/`--negative` are kept (chart tokens are additive).

---

## 9. Security Analysis

- **No new auth surface** added.
- **Settings security page hidden** until backend lands — eliminates the risk that the mocked "Change password" button could be misinterpreted as functional.
- **FR-8.1 retries** — must verify each mutation is idempotent server-side OR carries an idempotency key. List of mutations to audit before enabling retry:
  - `POST /v1/transactions` — has idempotency? **Check S1**
  - `POST /v1/portfolios` — idempotent on (owner, name)? **Check S1**
  - `POST /v1/watchlists/{id}/members` — idempotent on (watchlist_id, entity_id)? **Check S1**
  - `POST /v1/brokerage-connections/{id}/sync` — already 202-async; retry safe
- **CSP** — no new external scripts; no change.
- **PKCE flow** — untouched.

---

## 10. Failure Modes

- **FM-1: chart tokens not migrated in lockstep** — if `globals.css` ships `--chart-positive` before sparkline files migrate, charts render with `--positive` (correct) via fallback; no visual regression. Migrate `globals.css` first, then files.
- **FM-2: settings page hidden but bookmarked** — user with stored bookmark to `/settings/security` gets 404. Mitigate: 404 page links back to `/settings/profile`.
- **FM-3: nuqs URL state collides with existing query params** — verify on `/news` that no other code reads `?hours=` etc.
- **FM-4: retry on non-idempotent mutation** — at-most-once becomes at-least-once. Critical to validate per-mutation before enabling. If unsafe, ship idempotency-key header first.
- **FM-5: loading.tsx skeletons mismatch real layout** — skeleton-real layout drift causes layout shift. Each skeleton ships with a side-by-side screenshot test.
- **FM-6: dynamic-imported NewsTab loads slower than static** — for instrument-detail users who DO click News tab, latency increases. Mitigate: prefetch `import("@/components/instrument/NewsTab")` on tab hover.

---

## 11. Test Strategy

- **Unit (Vitest)** — every new primitive (`FormattedNumber`, `SignalBadge`, hooks, SSE parser) ships with > 90% line coverage.
- **Component (Vitest + RTL)** — every modified route component has a regression test covering the specific issue ID it fixes (e.g., CRIT-001 → test that "primary entity is a link with correct href").
- **E2E (Playwright)** — full smoke suite re-runs:
  1. login → dashboard → no console errors
  2. news → click ticker → land on intelligence page
  3. news → set filters → reload → filters persist
  4. settings → preferences → change retention → reload → retention persists
  5. chat → start stream → switch threads → no message loss
  6. portfolio → add transaction with simulated 5xx → see retry success
- **Visual regression** — Chromatic / Percy snapshot of `/dashboard`, `/news`, `/intelligence/[id]`, `/screener`, `/portfolio` at 1440px + 1024px.
- **Bundle regression** — bundlewatch check on PR for every wave.
- **a11y** — axe-core scan on each route via Playwright; targets Lighthouse a11y ≥ 95.

---

## 12. Migration Strategy

Sequential waves. Wave 0/1 are global; Waves 2+ are per-route and can ship independently.

| Wave | Focus | Est. (hrs) | Blocks |
|------|-------|-----------|--------|
| **W0** | Design-system tokens + shared primitives (FR-10) | 6h | none |
| **W1** | API layer hardening + loading/error boundaries (FR-8.1–8.4, FR-9.1, FR-9.2) | 5h | W0 |
| **W2** | Performance: dynamic imports + bundle trim (FR-9.3, FR-9.4) | 3h | W0 |
| **W3** | Dashboard fixes (FR-1) | 4h | W0 |
| **W4** | News + Intelligence (FR-2, FR-3) — biggest UX win | 8h | W0 |
| **W5** | Screener + Instruments list + Search + Watchlists (FR-4) | 4h | W0 |
| **W6** | Chat (FR-5) | 4h | W0 |
| **W7** | Alerts + Portfolio polish (FR-1.6 + HIGH-016) | 2h | W0 |
| **W8** | Settings wire-or-hide + auth polish (FR-6, FR-7) | 6h | W1 (for notification-prefs API gating) |

**Total estimate: 42h** (one focused dev-week or two part-time weeks). Excludes backend wave for FR-8.5 / FR-6.3 (notification-preferences endpoint).

**Sequencing rationale:**
- W0 first so every other wave can consume the new tokens/primitives.
- W1 second so API + loading-state infrastructure is in place before route-level work; routes can adopt it as they touch each component.
- W2 next because it's mostly mechanical dynamic-import wrapping; low-risk and improves every other demo path.
- W3/W4 prioritized because dashboard and news are the highest-traffic, highest-visibility routes.
- W8 last because it's gated on backend (FR-8.5) and is mostly "hide what doesn't work" — non-blocking for thesis demo if other waves land.

---

## 13. Open Questions

| OQ | Question | Default if Deferred |
|----|----------|---------------------|
| OQ-001 | Should mocked settings pages return 404 or render a "Coming soon" placeholder? Either is honest; 404 is cleaner. | **DEFER**: 404 + sidebar hidden. Easier to re-enable than rewrite. |
| OQ-002 | Backend wave for `GET/PATCH /v1/users/me/notification-preferences` — is there bandwidth, or should we ship FR-6.3 hidden? | **DEFER**: ship hidden behind feature flag; backend wave separate. |
| OQ-003 | Is `text-[9px]` permitted? Multiple components use it for secondary labels. | **DEFER**: amend ADR-F-15 to permit 9px for non-data labels only. |
| OQ-004 | Should retries on mutations require an idempotency-key header? | **DEFER**: audit each mutation; for ones lacking idempotency, ship idempotency-key + retry together. |
| OQ-005 | Should we redesign `/chat` from scratch (currently 7.5/10) or polish? | **DEFER**: polish (FR-5). Full redesign would be a separate PRD. |
| OQ-006 | Are 12-column tablet/iPad users a target? Or is desktop ≥ 1280px the only support window? | **DEFER**: stay desktop-only per PRD-0031; FR-1.2 keeps the dashboard from looking shattered on 1024-1280px viewports but mobile is explicitly out. |
| OQ-007 | Should the prediction-markets route get a redesign pass? It was not deeply audited in this scope. | **DEFER**: separate audit + PRD. |

---

## 14. Estimation

| Wave | Hours | Critical/High issues closed |
|------|-------|----------------------------|
| W0 | 6 | DS-001..014, CRIT-007, MED-018..020 |
| W1 | 5 | CRIT-005, CRIT-006, HIGH-009, HIGH-011, HIGH-018 |
| W2 | 3 | HIGH-008, HIGH-012 |
| W3 | 4 | CRIT-009, HIGH-002, HIGH-003, HIGH-007, HIGH-013, MED-001..005 |
| W4 | 8 | CRIT-001, CRIT-002, CRIT-008, HIGH-001, HIGH-004, HIGH-005, MED-006..009 |
| W5 | 4 | HIGH-014, LOW-007..010, MED-010..011 |
| W6 | 4 | HIGH-010, HIGH-015, MED-012..014, LOW-006 |
| W7 | 2 | HIGH-016, MED-003 |
| W8 | 6 | CRIT-003, CRIT-004, HIGH-006, HIGH-017, MED-015..017, LOW-011..017 |
| **Total** | **42h** | **9 CRIT + 18 HIGH + 24 MED + 17 LOW + 14 DS = 82 issues closed** |

Remaining 17 issues (MISS-001..008, INC-001..009 not directly addressed by an FR) are documented as follow-up work — most require backend coordination or product decisions outside this PRD.

---

## 15. Compounding Updates

- **BUG_PATTERNS.md** — new entry per critical issue closed:
  - BP-XXX: "Mutation without retry config silently drops user actions on transient 5xx" — applies to all POST/PATCH/DELETE
  - BP-XXX: "Hardcoded chart color constants drift from design tokens across palette updates"
  - BP-XXX: "Mocked settings page indistinguishable from functional one harms user trust"
- **REVIEW_CHECKLIST.md** — add:
  - "Every new mutation has retry config + idempotency confirmed"
  - "Every new route has loading.tsx + error.tsx"
  - "Every numeric render uses `<FormattedNumber>` or explicit `font-mono tabular-nums`"
  - "No hardcoded #hex outside globals.css token definitions"
- **DESIGN_SYSTEM.md** — document FR-10 tokens; document the `<FormattedNumber>` / `<SignalBadge>` primitives; document the dual-header convention (h-9 for action pages, h-7 for browse pages); amend ADR-F-15 for 9px label exception (OQ-003).
- **CLAUDE.md** — add a "Frontend route invariants" section listing the loading.tsx + error.tsx + retry + token rules.
- **`.claude/review/heuristics/HIGH_RISK_PATTERNS.md`** — add: "Mocked UI buttons that pretend to work" + "Settings stored as component-local state" + "Stale staleTime defaults on shared endpoints".

---

## Appendix: Issue Registry Reference

Full issue list with file:line citations: `.claude/frontend-audit/issue-registry.md` (99 issues, locked).
