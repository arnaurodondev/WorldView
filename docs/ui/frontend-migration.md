# Frontend Migration: React/Vite → Next.js

> **Purpose**: Complete specification for the Worldview frontend. Covers the current React/Vite inventory, all architectural decisions for the Next.js target, the auth layer (PLAN-0025 Wave E), and the news intelligence UI (PRD-0026).
> **Do not implement until the Next.js service is scaffolded** — this document is the implementation brief.
>
> **Current**: `apps/frontend/` — React 18 + Vite 6
> **Target**: `apps/frontend/` (replace in-place) — Next.js 15 App Router + shadcn/ui
> **Last updated**: 2026-04-12

---

## Table of Contents

1. [Architectural Decisions (resolved)](#1-architectural-decisions-resolved)
2. [Current Frontend Inventory](#2-current-frontend-inventory)
3. [Next.js Target Spec](#3-nextjs-target-spec)
4. [Auth Layer — PLAN-0025 Wave E](#4-auth-layer--plan-0025-wave-e)
5. [News Intelligence UI — PRD-0026](#5-news-intelligence-ui--prd-0026)
6. [Design System](#6-design-system)
7. [Component Catalogue](#7-component-catalogue)
8. [Gateway Client](#8-gateway-client)
9. [Infrastructure](#9-infrastructure)
10. [Test Strategy](#10-test-strategy)
11. [Implementation Order](#11-implementation-order)
12. [Open Items](#12-open-items)

---

## 1. Architectural Decisions (resolved)

### ADR-F-01: Rendering strategy — Node SSR (not static export)

**Decision**: Use the default Next.js Node server (`next start`). Do **not** set `output: 'export'`.

**Rationale**:
- Next.js Middleware (for auth redirects) requires a Node runtime — `output: 'export'` disables it.
- httpOnly cookie handling (`refresh_token`) works seamlessly with SSR; static export has no server to set/read cookies server-side.
- Future server components can prefetch data without extra client round-trips.

**Dockerfile impact**: Replace the current nginx static serving pattern with a multi-stage `next build` → `node:alpine` running `next start`.

---

### ADR-F-02: WebSocket auth — query param `?token=<access_token>`

**Decision**: Pass the `access_token` as a URL query param: `/api/v1/alerts/stream?token=<access_token>`.

**Rationale**:
- The browser `WebSocket` API has no `headers` option — custom auth headers are impossible from the browser.
- The `access_token` is short-lived (15-minute TTL via Zitadel), so URL exposure is acceptable.
- S9 already reads query params on this endpoint (current: `?user_id=`); updating to `?token=` and validating via `InternalJWTMiddleware` logic is a small change.
- A ticket endpoint (get-short-lived-ticket → use ticket in WS URL) adds complexity for marginal security gain at thesis scale.

**S9 impact**: The WS route handler must extract `token` query param, validate it (same RS256 public key), and extract `user_id` + `tenant_id` from the JWT claims. The old `?user_id=` param is removed (auth bypass risk — BP-141 class bug).

---

### ADR-F-03: Migration strategy — replace in-place

**Decision**: Migrate `apps/frontend/` in-place (delete the Vite app, scaffold Next.js in the same directory). Do not create `apps/nextjs/`.

**Rationale**: Cleaner monorepo structure; docker-compose paths, CI, and tooling stay unchanged; package name `@worldview/frontend` remains stable.

---

### ADR-F-04: Dark theme — enforced, no toggle

**Decision**: Dark mode only. Set `<html className="dark">` permanently in the root layout. No light/dark toggle.

**Rationale**:
- The existing React app already uses CSS custom properties (`--bg-secondary`, `--border`, `--text-secondary`) confirming dark theme intent.
- Market intelligence tools conventionally use dark UIs (reduce eye strain, better chart contrast).
- A toggle adds complexity with no thesis requirement.
- shadcn/ui's `class` strategy makes this trivial: set `dark` class once on `<html>`.

---

### ADR-F-05: News Intelligence UI decisions (from `docs/ui/news-intelligence.md`)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| OQ-1 | Default "Top News" time window | **48h** | 24h produces empty feeds on weekends; 48h always has content |
| OQ-2 | "Top News" navigation placement | **Tab within `/news` page** | Avoids adding a 4th top-level nav item; `/news` becomes tabbed: "Feed" / "Top Today" |
| OQ-3 | Impact score display | **`RelevanceBadge` + `ImpactSparkline` in detail** | Badge on cards (compact); sparkline in instrument panel (rich) — as recommended in the doc |
| OQ-4 | Fundamentals default metric set | **P/E, EPS, Revenue TTM, Market Cap, Dividend Yield, Debt/Equity** | Standard 6-metric set for equity analysts |
| OQ-5 | Fundamentals persistence | **`localStorage`** | PRD-0025 auth is complete; server-side prefs are out of scope for this phase |
| OQ-6 | LIGHT tier articles in "Top News" | **Show with visual de-emphasis** (opacity 0.6, italic source) | Hiding them loses signal; de-emphasis communicates lower confidence |
| OQ-7 | ImpactSparkline threshold | **≥ 2 windows** (day_t0 + day_t1, available after 49h) | More data = more value; 2-window minimum is achievable overnight |

---

### ADR-F-06: Public landing page at `/`; dashboard at `/dashboard` (PRD-0027)

**Decision**: Route `/` serves a public marketing landing page (no auth required). The authenticated dashboard moves to `/dashboard`.

**Rationale**: The landing page is the primary conversion surface for new users. Mixing the marketing page and app in the same route requires runtime auth checks that add complexity and hurt SEO. A dedicated `/` public page and `/dashboard` protected page are the Next.js idiomatic pattern.

**Impact**: `app/page.tsx` = landing (no auth guard). `app/(protected)/dashboard/page.tsx` = dashboard. Sidebar nav "Dashboard" links to `/dashboard`.

---

### ADR-F-07: Workspace state via React Context + localStorage (PRD-0027)

**Decision**: Workspace panel layout (positions, sizes, panel types) is persisted in `localStorage` keyed by user. `WorkspaceTickerContext` shares the active ticker across all panels in the workspace. No server-side persistence for layout.

**Rationale**: Drag-and-drop workspace via `react-grid-layout`. Server-side persistence requires a new API endpoint and migration — unnecessary for MVP. `localStorage` is per-browser which is acceptable for a personal workspace.

**Components**: `WorkspaceTickerContext.tsx` (`"use client"`), `WorkspacePanel.tsx`, panel types: Chart, News, Alerts, Chat, Watchlist, Screener, Graph, Briefing.

---

### ADR-F-08: sigma.js over D3.js for entity relationship graph (PRD-0027)

**Decision**: Use `sigma.js` + `graphology` + `@react-sigma/core` for the entity knowledge graph visualization. Do not use D3.js.

**Rationale**: sigma.js uses WebGL rendering — handles 100+ nodes at 60fps. D3.js SVG rendering degrades visibly at 200+ nodes. ForceAtlas2 layout algorithm from `graphology-layout-forceatlas2` is industry standard for knowledge graphs. React integration via `@react-sigma/core` is first-class.

---

### ADR-F-09: Morning brief generated on-demand at login (PRD-0027)

**Decision**: Morning brief is generated when the user requests it (Dashboard mount or explicit Refresh click), not by a nightly background worker.

**Rationale**: (1) Users span many timezones — a fixed nightly window cannot target everyone's "morning". (2) Inactive users waste LLM tokens on pre-generation. (3) 24h Valkey cache (`s8:v1:brief:morning:{user_id}:{date_utc}`) means the cost is paid once per user per day regardless.

**UX**: Dashboard shows skeleton (~3-5s first request), then cached result on subsequent loads same day.

---

### ADR-F-10: Briefing cache — Valkey only, 24h TTL (PRD-0027)

**Decision**: Both morning briefs and instrument briefs are cached in Valkey (not in DB). TTL = 24h, keyed by `user_id + date_utc` (morning) or `instrument_id + date_utc` (instrument).

**Rationale**: Briefs are date-specific and stale after one trading day. DB persistence adds migration cost for ephemeral data. Valkey eviction handles cache expiry without manual cleanup.

**Keys**: `s8:v1:brief:morning:{user_id}:{YYYY-MM-DD}`, `s8:v1:brief:instrument:{id}:{YYYY-MM-DD}`.

---

### ADR-F-11: Command palette via `cmdk` (PRD-0027)

**Decision**: Global command palette (Cmd+K / Ctrl+K) uses `cmdk` (already a shadcn/ui peer dependency). Shortcut dispatched via `useEffect` keyboard listener in root layout.

**Rationale**: `cmdk` is already available as a transitive dependency through shadcn/ui. No additional bundle cost. Powers entity search, navigation shortcuts, and action shortcuts from anywhere in the app.

---

## 2. Current Frontend Inventory

### 2.1 Technology Stack

| Concern | Current (to be removed) |
|---------|------------------------|
| Framework | React 18 + Vite 6 |
| Routing | react-router-dom 6 (`<Routes>`, `<Route>`) |
| Build | Vite 6 (`vite.config.ts`, `index.html`) |
| Dev proxy | Vite `server.proxy`: `/api → http://localhost:8000` |
| Env vars | `VITE_API_BASE_URL` (`import.meta.env.VITE_*`) |
| Styles | Inline styles using CSS custom properties; no CSS framework |
| Package manager | pnpm 10 (exact versions — keep this rule) |
| Port (dev) | 5173 |

### 2.2 Routes (current)

| Path | Component | Implementation state |
|------|-----------|---------------------|
| `/` | `DashboardPage` | Stub — shows `recentAlerts` from `AlertStreamContext` |
| `/companies` | `CompaniesPage` | Stub — empty |
| `/companies/:id` | `CompanyDetailPage` | Implemented — TanStack Query, OHLCV chart, NewsList, SimilarCompaniesPanel |
| `/portfolio` | `PortfolioPage` | Stub — empty |
| `/news` | `NewsPage` | Implemented — TanStack Query, NewsList + PredictionMarketsPanel |
| `/map` | `MapPage` | Stub — empty |
| `/countries/:code` | `CountryPage` | Stub — empty |
| `/chat` | `ChatPage` | Implemented — ChatUI with EventSource SSE |
| `/screener` | `ScreenerPage` | Implemented — dynamic filter form + paginated TanStack Query results |

### 2.3 Components (current)

| File | Description | Inline styles? |
|------|-------------|----------------|
| `Layout.tsx` | 220px sidebar + `<Outlet>` main area | Yes |
| `NewsList.tsx` | Renders `Article[]` list | Yes |
| `OHLCVChart.tsx` | `lightweight-charts` candlestick chart | Yes (canvas) |
| `ChatUI.tsx` | EventSource SSE chat | Yes |
| `SimilarCompaniesPanel.tsx` | Similar entities via TanStack Query | Yes |
| `PredictionMarketsPanel.tsx` | Prediction markets via TanStack Query | Yes |
| `alerts/AlertCard.tsx` | Single alert card | Yes |
| `alerts/SeverityBadge.tsx` | Coloured severity badge | Yes |
| `alerts/FlashOverlay.tsx` | Full-screen critical alert overlay (z-9999, 12s auto-dismiss, Escape key, error boundary) | Yes |

### 2.4 Hooks & Contexts (current)

| File | Description |
|------|-------------|
| `hooks/useAlertStream.ts` | WebSocket to `/api/v1/alerts/stream?user_id=` — no-ops when `userId=null`; exponential backoff reconnect (1s→30s); routes CRITICAL to `criticalQueue`, others to `recentAlerts` |
| `contexts/AlertStreamContext.tsx` | Provides `{criticalQueue, recentAlerts, dequeueCritical}` — single WS shared app-wide |

### 2.5 API Client (current — `lib/gateway-client.ts`)

Base: `import.meta.env.VITE_API_BASE_URL ?? "/api"` → in dev Vite proxies `/api → localhost:8000`

**Existing methods** (to be ported to Next.js `gateway-client.ts`):

| Method | Endpoint |
|--------|----------|
| `getCompanyOverview(id)` | `GET /v1/companies/:id/overview` |
| `getRelevantNews(limit)` | `GET /v1/news/relevant?limit=` |
| `getMapLayers()` | `GET /v1/map/layers` |
| `getScreenFields()` | `GET /v1/fundamentals/screen/fields` |
| `screenInstruments(filters, opts)` | `POST /v1/fundamentals/screen` |
| `findSimilarEntities(id, opts)` | `POST /v1/entities/similar` |
| `getPredictionMarkets(params)` | `GET /v1/signals/prediction-markets` |
| `streamChat(message)` | `EventSource /v1/chat/stream?q=` |

**New methods added by PRD-0027** (2026-04-12):

| Method | Endpoint | Notes |
|--------|----------|-------|
| `getMorningBrief()` | `GET /v1/briefings/morning` | Auth required; 24h Valkey cache |
| `getInstrumentBrief(instrumentId)` | `GET /v1/briefings/instrument/:id` | Auth required; 24h Valkey cache per instrument per day |
| `getOHLCV(instrumentId, params)` | `GET /v1/ohlcv/:id` | timeframe, start, end params |
| `getQuote(instrumentId)` | `GET /v1/quotes/:id` | Live quote, cached 5s |
| `getBatchQuotes(instrumentIds)` | `POST /v1/quotes/batch` | For portfolio holdings |
| `getFundamentals(instrumentId, section?)` | `GET /v1/fundamentals/:id[/:section]` | Optional section filter |
| `getFundamentalsTimeseries(params)` | `GET /v1/fundamentals/timeseries` | Metric + date range |
| `getPortfolios()` | `GET /v1/portfolios` | Auth required |
| `getHoldings(portfolioId)` | `GET /v1/holdings/:portfolioId` | Auth required |
| `getTransactions(portfolioId, opts)` | `GET /v1/transactions` | Auth required; paginated |
| `getWatchlists()` | `GET /v1/watchlists` | Auth required |
| `addWatchlistMember(watchlistId, entityId)` | `POST /v1/watchlists/:id/members` | Auth required |
| `getPendingAlerts(limit)` | `GET /v1/alerts/pending` | Auth required |
| `acknowledgeAlert(alertId)` | `DELETE /v1/alerts/:id/ack` | Auth required |
| `getTopNews(params)` | `GET /v1/news/top` | PRD-0026 dependency |
| `getEntityNews(entityId, params)` | `GET /v1/news/entity/:id` | PRD-0026 dependency |
| `getEntityGraph(entityId, params)` | `GET /v1/entities/:id/graph` | S7 egocentric graph |
| `getEntityContradictions(entityId)` | `GET /v1/entities/:id/contradictions` | S7 contradictions |
| `getChatThreads()` | `GET /v1/threads` | Auth required |
| `getChatThread(threadId)` | `GET /v1/threads/:id` | Auth required |
| `createChatThread()` | `POST /v1/threads` | Auth required |
| `deleteChatThread(threadId)` | `DELETE /v1/threads/:id` | Auth required |
| `getBrokerageConnections()` | `GET /v1/brokerage-connections` | Auth required; PLAN-0022 |

### 2.6 Existing Tests

| File | Coverage |
|------|----------|
| `tests/OHLCVChart.test.tsx` | Renders without crash |
| `tests/PredictionMarketsPanel.test.tsx` | TanStack Query + MSW mock |
| `e2e/homepage.spec.ts` | Playwright smoke — homepage loads |

### 2.7 Infrastructure (current)

| File | Purpose |
|------|---------|
| `Dockerfile` | `pnpm build` → nginx static serve |
| `deploy/nginx.conf` | nginx SPA config (try_files fallback) |
| `vite.config.ts` | Vite dev server + proxy |
| `.env.example` | `VITE_API_BASE_URL` |

---

## 3. Next.js Target Spec

### 3.1 Technology Stack

| Concern | Target |
|---------|--------|
| Framework | Next.js 15 (App Router) |
| Routing | File-based `app/` directory |
| Data fetching | TanStack Query 5 (client-side, keep exact version) |
| UI components | shadcn/ui (Radix UI primitives + Tailwind CSS) |
| Charts | lightweight-charts 4 (keep exact version, `"use client"` wrapper) |
| Real-time | WebSocket in `useAlertStream` hook (`"use client"`) |
| SSE | EventSource in `ChatUI` (`"use client"`) |
| Package manager | pnpm (exact versions, no `^`) |
| Testing | Vitest + RTL + MSW + Playwright (same) |
| Dev proxy | `next.config.ts` rewrites: `/api/* → http://localhost:8000/*` |
| Env vars | `NEXT_PUBLIC_API_BASE_URL` (replaces `VITE_API_BASE_URL`) |
| Port (dev) | 3000 |
| Theming | Dark mode only — `class="dark"` on `<html>`, shadcn/ui `class` strategy |

### 3.2 App Router Directory Structure

```
apps/frontend/
├── app/
│   ├── layout.tsx                    # Root layout: <html dark>, AuthProvider, QueryClientProvider, AlertStreamContext.Provider
│   ├── globals.css                   # Tailwind base + shadcn/ui CSS variables (dark theme)
│   ├── login/
│   │   └── page.tsx                  # Public — LoginPage ("Log in to Worldview" button)
│   ├── callback/
│   │   └── page.tsx                  # Public — CallbackPage (Zitadel OIDC callback handler)
│   └── (protected)/
│       ├── layout.tsx                # Auth guard — redirects to /login if not authenticated
│       ├── dashboard/
│       │   └── page.tsx              # DashboardPage (route: /dashboard) — ADR-F-06
│       ├── workspace/
│       │   └── page.tsx              # WorkspacePage (route: /workspace) — drag-and-drop terminal
│       ├── companies/
│       │   ├── page.tsx              # CompaniesPage
│       │   └── [id]/
│       │       └── page.tsx          # CompanyDetailPage
│       ├── portfolio/
│       │   └── page.tsx              # PortfolioPage
│       ├── news/
│       │   └── page.tsx              # NewsPage (tabs: Feed | Top Today)
│       ├── map/
│       │   └── page.tsx              # MapPage
│       ├── countries/
│       │   └── [code]/
│       │       └── page.tsx          # CountryPage
│       ├── chat/
│       │   └── page.tsx              # ChatPage
│       └── screener/
│           └── page.tsx              # ScreenerPage
├── src/
│   ├── components/
│   │   ├── ui/                       # shadcn/ui auto-generated components
│   │   ├── layout/
│   │   │   ├── AppSidebar.tsx        # Sidebar nav (shadcn/ui Sheet or Sidebar)
│   │   │   └── TopBar.tsx            # Optional top bar with user avatar + logout
│   │   ├── charts/
│   │   │   └── OHLCVChart.tsx        # lightweight-charts wrapper ("use client")
│   │   ├── chat/
│   │   │   └── ChatUI.tsx            # EventSource SSE chat ("use client")
│   │   ├── alerts/
│   │   │   ├── AlertCard.tsx
│   │   │   ├── SeverityBadge.tsx
│   │   │   └── FlashOverlay.tsx      # Error boundary + auto-dismiss + Escape key
│   │   ├── news/
│   │   │   ├── ArticleCard.tsx       # Enhanced card (title, source, timestamp, RelevanceBadge)
│   │   │   ├── NewsList.tsx          # List of ArticleCard (port + enhance)
│   │   │   ├── RelevanceBadge.tsx    # Coloured 0–100 score badge
│   │   │   ├── ImpactSparkline.tsx   # day_t0→t5 mini line chart (lightweight-charts)
│   │   │   └── TopNewsFilters.tsx    # Time range + score threshold + source type filters
│   │   ├── instrument/
│   │   │   ├── SimilarCompaniesPanel.tsx
│   │   │   ├── EntityNewsPanel.tsx   # Chart-range-linked news (PRD-0026)
│   │   │   ├── FundamentalsBar.tsx   # P/E, EPS, Revenue, Market Cap, Div Yield, D/E
│   │   │   ├── PriceChange.tsx       # +2.3% ▲ / -1.1% ▼ with semantic color
│   │   │   └── EntityGraph.tsx       # sigma.js WebGL entity relationship graph (ADR-F-08)
│   │   ├── workspace/
│   │   │   ├── WorkspaceGrid.tsx     # react-grid-layout 12-col drag-and-drop host
│   │   │   ├── WorkspacePanel.tsx    # Individual panel wrapper (title bar, drag handle, close)
│   │   │   └── panels/              # Panel type implementations
│   │   │       ├── ChartPanel.tsx
│   │   │       ├── NewsPanel.tsx
│   │   │       ├── AlertsPanel.tsx
│   │   │       ├── ChatPanel.tsx
│   │   │       └── WatchlistPanel.tsx
│   │   ├── landing/
│   │   │   └── LandingPage.tsx      # Marketing page sections (Hero, Features, Pricing, Footer)
│   │   ├── dashboard/
│   │   │   └── MorningBriefCard.tsx # On-demand brief with skeleton + retry (ADR-F-09)
│   │   └── markets/
│   │       └── PredictionMarketsPanel.tsx
│   ├── contexts/
│   │   ├── AuthContext.tsx           # "use client" — auth state, silent refresh, login/logout
│   │   ├── AlertStreamContext.tsx    # "use client" — WS state shared app-wide
│   │   └── WorkspaceTickerContext.tsx # "use client" — active ticker shared across workspace panels (ADR-F-07)
│   ├── hooks/
│   │   ├── useAuth.ts                # Reads AuthContext
│   │   └── useAlertStream.ts         # WS connection with auth token + exponential backoff
│   └── lib/
│       ├── authClient.ts             # fetch wrapper: Authorization header + 401 refresh + retry
│       └── gateway-client.ts         # Typed API methods (uses authClient.request)
├── next.config.ts
├── tailwind.config.ts
├── components.json                   # shadcn/ui config
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── Dockerfile                        # next build → node:alpine next start
└── deploy/
    └── docker-entrypoint.sh          # Optional: env injection at startup
```

### 3.3 Route Mapping

> **Updated by PRD-0027 (2026-04-12)**: `/` is now the public landing page. Dashboard moved to `/dashboard`. `/workspace` added for the trading terminal.

| Current React Router | Next.js App Router | Auth required? |
|---------------------|-------------------|----------------|
| (new) `/` | `app/page.tsx` | **No (public landing page)** |
| `/` (old dashboard) | `app/(protected)/dashboard/page.tsx` | Yes → `/dashboard` |
| (new) `/workspace` | `app/(protected)/workspace/page.tsx` | Yes |
| `/companies` | `app/(protected)/companies/page.tsx` | Yes |
| `/companies/:id` | `app/(protected)/companies/[id]/page.tsx` | Yes |
| `/portfolio` | `app/(protected)/portfolio/page.tsx` | Yes |
| `/news` | `app/(protected)/news/page.tsx` | Yes |
| `/map` | `app/(protected)/map/page.tsx` | Yes (stub) |
| `/countries/:code` | Deferred — see Map stub | — |
| `/chat` | `app/(protected)/chat/page.tsx` | Yes |
| `/screener` | `app/(protected)/screener/page.tsx` | Yes |
| (new) `/login` | `app/login/page.tsx` | No (public) |
| (new) `/callback` | `app/callback/page.tsx` | No (public) |

### 3.4 Server vs Client Component Classification

| Component / hook | Rendering | Reason |
|-----------------|-----------|--------|
| Root layout (`app/layout.tsx`) | Server layout wrapping client providers | Providers are `"use client"` boundaries |
| `AuthProvider` | `"use client"` | Browser state (access_token, fetch on mount) |
| `QueryClientProvider` | `"use client"` | TanStack Query requires browser |
| `AlertStreamContext.Provider` | `"use client"` | WebSocket |
| `AppSidebar` | Server Component | Static nav links, no interactivity |
| `TopBar` | `"use client"` | Reads `useAuth` for username/logout |
| All page components | `"use client"` | TanStack Query hooks |
| `OHLCVChart` | `"use client"` | lightweight-charts uses DOM |
| `ChatUI` | `"use client"` | EventSource |
| `FlashOverlay` | `"use client"` | useState, useEffect, event listeners |
| `ArticleCard`, `NewsList` | Server or Client (no hooks) | Prefer Server if no interactivity |
| `AlertCard`, `SeverityBadge` | Server Component | Pure display |
| `RelevanceBadge` | Server Component | Pure display |
| `ImpactSparkline` | `"use client"` | lightweight-charts |
| `TopNewsFilters` | `"use client"` | Controlled form state |
| `FundamentalsBar` | `"use client"` | localStorage read + metric selector |
| `SimilarCompaniesPanel` | `"use client"` | TanStack Query |
| `EntityNewsPanel` | `"use client"` | TanStack Query + chart range sync |
| `PredictionMarketsPanel` | `"use client"` | TanStack Query |
| `useAuth` | `"use client"` hook | Context consumer |
| `useAlertStream` | `"use client"` hook | WebSocket |
| `LoginPage` | `"use client"` | `useAuth` redirect if already logged in |
| `CallbackPage` | `"use client"` | `useSearchParams`, fetch on mount |
| `(protected)/layout.tsx` | `"use client"` | `useAuth` + `router.push('/login')` |

### 3.5 Dependency Changes

**Remove** (Vite-specific):
```
react-router-dom
vite
@vitejs/plugin-react
vite-env.d.ts
```

**Add** (Next.js + shadcn/ui):
```
next                          (15.x, exact)
tailwindcss                   (exact)
postcss                       (exact)
autoprefixer                  (exact)
@radix-ui/*                   (via shadcn/ui CLI — do not add manually)
class-variance-authority      (exact)
clsx                          (exact)
tailwind-merge                (exact)
lucide-react                  (exact)
shadcn                        (devDep, exact — CLI tool)
```

**Keep** (exact versions, same pins):
```
@tanstack/react-query         5.97.0
lightweight-charts            4.2.3
react                         18.3.1
react-dom                     18.3.1
@types/react                  18.3.28
@types/react-dom              18.3.7
typescript                    5.9.3
vitest                        2.1.9
@testing-library/react        16.3.2
@testing-library/jest-dom     6.9.1
@playwright/test              1.59.1
eslint                        9.39.4
prettier                      3.8.1
```

**Env var rename**:

| Old (Vite) | New (Next.js) |
|------------|--------------|
| `VITE_API_BASE_URL` | `NEXT_PUBLIC_API_BASE_URL` |
| `import.meta.env.VITE_*` | `process.env.NEXT_PUBLIC_*` |

### 3.6 Dev Proxy (`next.config.ts`)

```ts
// next.config.ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
```

> **Note on WebSocket**: Next.js `rewrites()` does not proxy WebSocket upgrades. In development, the `useAlertStream` hook must use the full WS URL `ws://localhost:8000/v1/alerts/stream?token=<token>` directly (not via `/api/`). In production, Traefik handles WS proxying. Use `NEXT_PUBLIC_WS_BASE_URL` env var (default: empty → derive from window.location in prod, `ws://localhost:8000` in dev).

---

## 4. Auth Layer — PLAN-0025 Wave E

Full spec is in `docs/plans/0025-auth-oidc-zitadel-internal-jwt-plan.md` §Wave E. This section is the Next.js translation.

### 4.1 `src/contexts/AuthContext.tsx`

```ts
// Shape
interface AuthState {
  user: { user_id: string; tenant_id: string; email: string; sub: string } | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  login: () => void;     // window.location.href = "/api/v1/auth/login"
  logout: () => void;    // POST /api/v1/auth/logout → clear state → router.push("/login")
  setAccessToken: (token: string, user: AuthState["user"]) => void;  // called by CallbackPage
}
```

**On mount**: `POST /api/v1/auth/refresh` (browser sends httpOnly cookie automatically) → if 200: store `access_token` + `user` in state; if 401: `isAuthenticated=false`, `isLoading=false`.

**Token storage**: access_token in React state ONLY. Never `localStorage`, never client-accessible cookie.

### 4.2 `src/hooks/useAuth.ts`

```ts
export function useAuth(): AuthContextValue
// Throws if used outside AuthProvider (invariant check)
```

### 4.3 `src/lib/authClient.ts`

```ts
async function request<T>(path: string, init?: RequestInit): Promise<T>
// 1. Attach Authorization: Bearer <accessToken> from AuthContext
// 2. If 401: attempt POST /api/v1/auth/refresh → update accessToken → retry original request once
// 3. If still 401 after retry: router.push("/login")
```

All `gateway-client.ts` methods must use `authClient.request()` instead of raw `fetch`.

### 4.4 `app/login/page.tsx`

```tsx
"use client"
// If isAuthenticated: redirect to /
// Otherwise: render single "Log in to Worldview" button
// onClick: window.location.href = "/api/v1/auth/login"
// No form fields. No password. Full page redirect — S9 issues 302 to Zitadel.
```

### 4.5 `app/callback/page.tsx`

```tsx
"use client"
// On mount:
// 1. Read ?code= and ?state= from useSearchParams()
// 2. GET /api/v1/auth/callback?code=<code>&state=<state>
// 3. On 200: call setAccessToken(data.access_token, data.user) → router.push("/")
// 4. On error: render error message + "Back to login" link
```

### 4.6 `app/(protected)/layout.tsx`

```tsx
"use client"
// const { isAuthenticated, isLoading } = useAuth()
// if isLoading: render loading spinner
// if !isAuthenticated: router.push("/login") (useEffect)
// otherwise: render <>{children}</>
```

### 4.7 WebSocket Auth (`src/hooks/useAlertStream.ts`)

Update the hook signature and WS URL:

```ts
// Before (insecure — user_id from caller, any value accepted by S9):
export function useAlertStream(userId: string | null)
// WebSocket URL: /api/v1/alerts/stream?user_id=${userId}

// After (secure — token validated by S9, user_id extracted from JWT claims):
export function useAlertStream(accessToken: string | null)
// WebSocket URL: ws://localhost:8000/v1/alerts/stream?token=${accessToken}  (dev)
//               wss://<domain>/v1/alerts/stream?token=${accessToken}        (prod)
// No-ops when accessToken is null (same as before with userId=null)
```

S9 must be updated to validate `?token=` on this route (extract user_id, tenant_id from JWT claims).

### 4.8 Auth Tests (minimum 12)

| Test | Type |
|------|------|
| AuthContext: silent refresh on mount (200) → isAuthenticated=true | Unit (Vitest + MSW) |
| AuthContext: silent refresh on mount (401) → isAuthenticated=false | Unit |
| AuthContext: login() navigates to /api/v1/auth/login | Unit |
| AuthContext: logout() clears token and redirects | Unit |
| authClient: attaches Authorization header | Unit |
| authClient: 401 triggers refresh + retry | Unit |
| authClient: double 401 redirects to /login | Unit |
| LoginPage: renders "Log in to Worldview" button when unauthenticated | RTL |
| LoginPage: redirects to / when already authenticated | RTL |
| CallbackPage: exchanges code+state → sets token → redirects to / | RTL + MSW |
| CallbackPage: shows error on failed callback | RTL + MSW |
| ProtectedRoute layout: unauthenticated user redirected to /login | RTL |
| localStorage.getItem("access_token") === null after auth | RTL assertion |

---

## 5. News Intelligence UI — PRD-0026

> All decisions in this section are resolved per §1 (ADR-F-05).

### 5.1 New API Methods (add to `gateway-client.ts`)

```ts
export interface RankedArticle {
  id: string;
  title: string;
  source: string;
  source_type: "news" | "filing" | "transcript";
  published_at: string;           // ISO-8601 UTC
  url: string;
  display_relevance_score: number; // 0.0–1.0, always present
  primary_entity_id: string | null;
  primary_entity_symbol: string | null;
  routing_tier: "DEEP" | "MEDIUM" | "LIGHT";
  llm_relevance_score: number | null;
  market_impact_score: number | null;
  routing_score: number | null;
  impact_windows: {
    day_t0: number | null;
    day_t1: number | null;
    day_t2: number | null;
    day_t5: number | null;
  } | null;
}

export interface TopNewsResponse {
  articles: RankedArticle[];
  total: number;
  hours: number;
  limit: number;
  offset: number;
}

export interface EntityNewsResponse {
  entity_id: string;
  canonical_name: string;
  articles: RankedArticle[];
  total: number;
}

// New gateway methods:
getTopNews: (params: {
  hours?: number;     // default 48 (ADR-F-05 OQ-1)
  limit?: number;     // default 20
  offset?: number;
  min_display_score?: number;
  source_type?: "news" | "filing" | "transcript";
}) => Promise<TopNewsResponse>
// → GET /v1/news/top?hours=&limit=&offset=&min_display_score=&source_type=

getEntityNews: (entityId: string, params: {
  start_date?: string;   // ISO-8601 UTC
  end_date?: string;
  order_by?: "display_relevance_score" | "published_at";
  limit?: number;
}) => Promise<EntityNewsResponse>
// → GET /v1/news/entity/:entityId?start_date=&end_date=&order_by=&limit=
```

### 5.2 `NewsPage` — Tabbed Layout

The `/news` route becomes a tabbed page (shadcn/ui `Tabs`):

- **Tab 1: "Feed"** — current `NewsPage` content: `getRelevantNews()` + `PredictionMarketsPanel`
- **Tab 2: "Top Today"** — `TopNewsPage` content (see §5.3)

Default active tab: **"Top Today"** (the higher-value feature).

### 5.3 `TopNewsPage` content (inside Tab 2)

**Filters** (sticky top bar within the tab):
- Time range: `24h | 48h | 7d` button group — default **48h**
- Relevance filter: `All | Relevant (≥0.4) | High (≥0.7)` button group — default **All**
- Source type: `All | News | Filings | Transcripts` dropdown — default **All**

**Article list**:
- 20 articles per page, "Load more" button (offset pagination — no page numbers)
- Each article uses `ArticleCard` (see §7.3)
- LIGHT tier articles: `opacity-60`, italic source name, optional "Unscored" label
- Empty state: "No articles found — try widening the time range or lowering the relevance threshold"

**TanStack Query key**: `["news", "top", { hours, limit, offset, min_display_score, source_type }]`

### 5.4 `CompanyDetailPage` — Enhanced

Add two panels alongside the existing OHLCV chart + NewsList:

#### `EntityNewsPanel`
- **Chart-range linkage**: `CompanyDetailPage` manages `chartRange: { start_date: string, end_date: string }` state; the chart component updates it when user changes the time range; `EntityNewsPanel` uses it as query params.
- Sort toggle: `display_relevance_score` (default) | `published_at`
- Each article uses `ArticleCard`; DEEP/MEDIUM articles show the `ImpactSparkline` if ≥ 2 windows are non-null
- Placeholder: "No scored articles for this period yet"

#### `FundamentalsBar`
- Display 6 default metrics: **P/E, EPS, Revenue TTM, Market Cap, Dividend Yield, Debt/Equity**
- Compact horizontal bar below the chart header
- User can click "Customize" to toggle metrics on/off via a popover (shadcn/ui `Popover` + `Checkbox`)
- Selection persisted to `localStorage` under key `worldview:fundamentals:metrics`
- Data source: `CompanyOverview.fundamentals` (already in TanStack Query cache)

### 5.5 Components (news intelligence)

See full spec in §7.

---

## 6. Design System

### 6.1 Theme: Dark Mode Only

shadcn/ui uses the `class` strategy. Set permanently in root layout:

```tsx
// app/layout.tsx
<html lang="en" className="dark">
```

`globals.css` uses shadcn/ui's CSS variable convention:

```css
@layer base {
  :root {
    /* shadcn/ui dark theme variables — applied to :root when class="dark" on <html> */
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    --card: 222.2 84% 4.9%;
    --card-foreground: 210 40% 98%;
    --primary: 210 40% 98%;
    --primary-foreground: 222.2 47.4% 11.2%;
    --muted: 217.2 32.6% 17.5%;
    --muted-foreground: 215 20.2% 65.1%;
    --accent: 217.2 32.6% 17.5%;
    --accent-foreground: 210 40% 98%;
    --destructive: 0 62.8% 30.6%;
    --border: 217.2 32.6% 17.5%;
    --input: 217.2 32.6% 17.5%;
    --ring: 212.7 26.8% 83.9%;
    --radius: 0.5rem;
  }
}
```

The current React app's CSS vars (`--bg-secondary`, `--text-secondary`, etc.) map to shadcn/ui tokens in `globals.css` for migration continuity.

### 6.2 shadcn/ui Components to Install

Run `pnpm dlx shadcn@latest add <component>` for each:

| Component | Used by |
|-----------|---------|
| `button` | LoginPage, CallbackPage, TopNewsFilters, FlashOverlay |
| `card` | ArticleCard, AlertCard, FundamentalsBar |
| `tabs` | NewsPage |
| `badge` | SeverityBadge, RelevanceBadge |
| `separator` | Layout, sidebars |
| `sheet` | Mobile sidebar (AppSidebar on small screens) |
| `sidebar` | Desktop AppSidebar |
| `popover` | FundamentalsBar metric selector |
| `checkbox` | FundamentalsBar metric selector |
| `select` | TopNewsFilters source type |
| `input` | ScreenerPage filter form |
| `table` | ScreenerPage results |
| `skeleton` | Loading states across all pages |
| `toast` | Auth errors, network errors |
| `dialog` | (reserved for future use) |
| `scroll-area` | Chat messages container |
| `toggle-group` | TopNewsFilters time range + relevance buttons |

### 6.3 Typography & Spacing

- Base font: system-ui (Next.js default) — no custom font loading for thesis
- Body font size: 14px (compact data-dense layout)
- Heading scale: 24px (h1), 18px (h2), 16px (h3)
- Spacing unit: Tailwind default (4px base)

### 6.4 Severity / Relevance Color Mapping

| Severity / Score | Color | Tailwind class |
|-----------------|-------|----------------|
| CRITICAL | Red | `bg-red-600` |
| HIGH | Orange | `bg-orange-500` |
| MEDIUM | Yellow | `bg-yellow-500` |
| LOW | Grey | `bg-slate-500` |
| Relevance ≥ 0.8 | Red | `bg-red-600 text-red-100` |
| Relevance 0.6–0.8 | Orange | `bg-orange-500 text-orange-100` |
| Relevance 0.3–0.6 | Yellow | `bg-yellow-500 text-yellow-100` |
| Relevance < 0.3 | Grey | `bg-slate-600 text-slate-300` |

---

## 7. Component Catalogue

### 7.1 Navigation

#### `AppSidebar`
- Desktop: fixed 220px left sidebar (shadcn/ui `Sidebar` or custom)
- Mobile: hidden by default, `Sheet` drawer opened by hamburger button
- Items: Dashboard, Companies, Screener, Portfolio, News, Map, Chat
- Active item highlighted via `usePathname()`
- Bottom: `TopBar` mini (user avatar, logout button)

### 7.2 Alert Components

#### `FlashOverlay` (port from current)
- Full-viewport fixed overlay, z-9999
- Backdrop: `bg-black/75 backdrop-blur-sm`
- Card: `bg-card border rounded-lg p-6 max-w-lg w-full`
- 12-second auto-dismiss (CSS animation countdown bar)
- Escape key dismisses
- Click outside card dismisses
- Error boundary: any render error silently dequeues
- Convert inline styles → Tailwind classes

#### `SeverityBadge` (port from current)
- shadcn/ui `Badge` variant per severity (see §6.4 color mapping)

#### `AlertCard` (port from current)
- shadcn/ui `Card` with `alert_type`, `entity_id`, `occurred_at`, `SeverityBadge`

### 7.3 News Components

#### `ArticleCard`
Props: `article: RankedArticle`, `showEntity?: boolean`

```
┌──────────────────────────────────────────────────────┐
│  [RelevanceBadge: 0.87]  [AAPL]  [News] [Transcript] │
│  Article Title (linked, opens new tab)               │
│  Reuters · 2h ago                                    │
│  [ImpactSparkline — only if ≥2 windows non-null]     │
└──────────────────────────────────────────────────────┘
```

LIGHT tier: full card has `opacity-60`, source in italics, optional "Unscored" text badge.

#### `RelevanceBadge`
Props: `score: number` (0.0–1.0)
- Displays as formatted percentage: `87%`
- Color per §6.4 relevance scale
- Tooltip: "Display relevance score: market × 0.5 + LLM × 0.4 + routing × 0.1"

#### `ImpactSparkline`
Props: `windows: { day_t0, day_t1, day_t2, day_t5 }`, `height?: number`
- Only rendered when ≥ 2 windows are non-null (ADR-F-05 OQ-7)
- Mini lightweight-charts `LineSeries` with fixed x-axis labels [t0, t1, t2, t5]
- `"use client"` — DOM dependency
- Default height: 48px (compact, inline within ArticleCard)

#### `TopNewsFilters`
Props: `value: FilterState`, `onChange: (f: FilterState) => void`
```ts
interface FilterState {
  hours: 24 | 48 | 168;
  minScore: 0 | 0.4 | 0.7;
  sourceType: "all" | "news" | "filing" | "transcript";
}
```
- shadcn/ui `ToggleGroup` for hours + minScore
- shadcn/ui `Select` for sourceType
- Sticky within the "Top Today" tab (not the whole page)

#### `EntityNewsPanel`
Props: `entityId: string`, `chartRange: { start_date: string; end_date: string }`
- TanStack Query key: `["news", "entity", entityId, chartRange]`
- Sort toggle (shadcn/ui `ToggleGroup`): relevance | chronological
- Renders list of `ArticleCard`s with `showEntity=false`
- Placeholder when loading: 3× `Skeleton` rows
- Placeholder when empty: "No scored articles for this period"

#### `FundamentalsBar`
Props: `fundamentals: Record<string, unknown>`
- Read selected metrics from `localStorage("worldview:fundamentals:metrics")`, default to `["pe_ratio", "eps", "revenue_ttm", "market_cap", "dividend_yield", "debt_to_equity"]`
- Horizontal scroll container (mobile-friendly)
- Each metric: label + formatted value (locale-aware number formatting)
- "Customize" button → `Popover` with `Checkbox` list of all available numeric fundamentals
- Missing/null metrics show `—`

### 7.4 Charts

#### `OHLCVChart` (port from current, add range callback)
Props: `data: OHLCVBar[]`, `onRangeChange?: (range: { start_date: string; end_date: string }) => void`
- `"use client"` wrapper
- Subscribe to `chart.timeScale().subscribeVisibleLogicalRangeChange` to fire `onRangeChange`
- `CompanyDetailPage` uses this callback to keep `EntityNewsPanel` in sync

### 7.5 Markets

#### `PredictionMarketsPanel` (port from current)
- TanStack Query, paginated list of prediction markets
- Each item: question, outcomes with probability bars, volume, close time

---

## 8. Gateway Client

`src/lib/gateway-client.ts` — complete method list for the Next.js app. All methods call `authClient.request<T>(...)`.

```ts
import { authClient } from "./authClient";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

export const gateway = {
  // ── Existing (port) ──────────────────────────────────────────────────────

  getCompanyOverview: (id: string) =>
    authClient.request<CompanyOverview>(`${BASE}/v1/companies/${id}/overview`),

  getRelevantNews: (limit = 20) =>
    authClient.request<{ articles: Article[] }>(`${BASE}/v1/news/relevant?limit=${limit}`),

  getMapLayers: () =>
    authClient.request<{ layers: MapLayer[] }>(`${BASE}/v1/map/layers`),

  getScreenFields: () =>
    authClient.request<{ fields: ScreenField[] }>(`${BASE}/v1/fundamentals/screen/fields`),

  screenInstruments: (filters: ScreenFilter[], opts: ScreenOpts = {}) =>
    authClient.request<ScreenResponse>(`${BASE}/v1/fundamentals/screen`, {
      method: "POST",
      body: JSON.stringify({ filters, ...opts }),
    }),

  findSimilarEntities: (entityId: string, opts: SimilarOpts = {}) =>
    authClient.request<SimilarEntitiesResponse>(`${BASE}/v1/entities/similar`, {
      method: "POST",
      body: JSON.stringify({ entity_id: entityId, ...opts }),
    }),

  getPredictionMarkets: (params: PredictionMarketsParams = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    return authClient.request<PredictionMarketsListResponse>(
      `${BASE}/v1/signals/prediction-markets?${qs}`,
    );
  },

  /** SSE streaming chat — does NOT go through authClient (EventSource limitation).
   *  Access token is passed as query param (same rationale as WS auth, ADR-F-02).
   */
  streamChat: (message: string, accessToken: string): EventSource =>
    new EventSource(
      `${BASE}/v1/chat/stream?q=${encodeURIComponent(message)}&token=${encodeURIComponent(accessToken)}`,
    ),

  // ── New (PRD-0026) ───────────────────────────────────────────────────────

  getTopNews: (params: TopNewsParams = {}) => {
    const qs = new URLSearchParams();
    qs.set("hours", String(params.hours ?? 48));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    if (params.min_display_score !== undefined)
      qs.set("min_display_score", String(params.min_display_score));
    if (params.source_type && params.source_type !== "all")
      qs.set("source_type", params.source_type);
    return authClient.request<TopNewsResponse>(`${BASE}/v1/news/top?${qs}`);
  },

  getEntityNews: (entityId: string, params: EntityNewsParams = {}) => {
    const qs = new URLSearchParams();
    if (params.start_date) qs.set("start_date", params.start_date);
    if (params.end_date) qs.set("end_date", params.end_date);
    if (params.order_by) qs.set("order_by", params.order_by);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    return authClient.request<EntityNewsResponse>(
      `${BASE}/v1/news/entity/${entityId}?${qs}`,
    );
  },
};
```

---

## 9. Infrastructure

### 9.1 `next.config.ts`

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_GATEWAY_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
```

### 9.2 `Dockerfile`

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
```

> Requires `output: 'standalone'` in `next.config.ts` for the minimal Node server.

### 9.3 `docker-compose.yml` changes

```yaml
frontend:
  build: ./apps/frontend
  ports:
    - "3000:3000"
  environment:
    API_GATEWAY_URL: http://api-gateway:8000
    NEXT_PUBLIC_WS_BASE_URL: ws://localhost:8000   # for dev; in prod use wss://<domain>
  depends_on:
    - api-gateway
```

### 9.4 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | No | `/api` | API base URL (proxied in dev; absolute in prod if needed) |
| `NEXT_PUBLIC_WS_BASE_URL` | No | `ws://localhost:8000` | WebSocket base (used by `useAlertStream`) |
| `API_GATEWAY_URL` | No | `http://localhost:8000` | Server-side: target for `next.config.ts` rewrites |

---

## 10. Test Strategy

### Unit + Integration (Vitest + RTL + MSW)

| File | Coverage |
|------|----------|
| `__tests__/AuthContext.test.tsx` | Auth state, silent refresh, login, logout |
| `__tests__/authClient.test.ts` | Header injection, 401 → refresh → retry, double 401 |
| `__tests__/CallbackPage.test.tsx` | Code exchange, redirect, error state |
| `__tests__/ProtectedRoute.test.tsx` | Redirect to /login when unauthenticated |
| `__tests__/OHLCVChart.test.tsx` | Renders without crash (port existing) |
| `__tests__/PredictionMarketsPanel.test.tsx` | MSW mock (port existing) |
| `__tests__/RelevanceBadge.test.tsx` | Score → correct colour + text |
| `__tests__/ImpactSparkline.test.tsx` | Shows when ≥2 windows, hides when <2 |
| `__tests__/TopNewsFilters.test.tsx` | Filter state changes |
| `__tests__/FundamentalsBar.test.tsx` | Renders 6 default metrics; localStorage persistence |
| `__tests__/ArticleCard.test.tsx` | LIGHT tier de-emphasis; ImpactSparkline conditional |

**Minimum totals**: 12 auth tests + 2 ported tests + 6 new component tests = **20+ tests**

### E2E (Playwright)

| Spec | Coverage |
|------|----------|
| `e2e/auth.spec.ts` | Login button visible on unauthenticated visit to `/`; redirect to `/login` |
| `e2e/homepage.spec.ts` | After auth: dashboard loads; recent alerts section visible |
| `e2e/news.spec.ts` | News page loads; tabs switch; article cards render |
| `e2e/screener.spec.ts` | Screener loads fields; submit returns results |

### Invariant tests (must not break)

- `localStorage.getItem("access_token")` is `null` after successful authentication
- `localStorage.getItem("refresh_token")` is `null` (cookie-only)

---

## 11. Implementation Order

> This order is optimised for dependency resolution. Do not start a step until the previous is complete.

| Step | What | Dependencies |
|------|------|-------------|
| 1 | Bootstrap Next.js app (pnpm create next-app, exact deps, shadcn init, proxy config) | None |
| 2 | `globals.css` + dark theme + shadcn/ui component installs | Step 1 |
| 3 | Auth: `AuthContext`, `authClient`, `LoginPage`, `CallbackPage`, `(protected)/layout` + auth tests | Step 2 |
| 4 | Root layout: `AuthProvider` + `QueryClientProvider` + `AlertStreamContext.Provider` (WS auth update) | Step 3 |
| 5 | Port implemented pages: Company Detail (with `FundamentalsBar` + `EntityNewsPanel` + `OHLCVChart` range callback), News (tabbed + `TopNewsFilters`), Chat, Screener | Step 4 |
| 6 | Port components: `FlashOverlay`, `AlertCard`, `SeverityBadge`, `NewsList`, `SimilarCompaniesPanel`, `PredictionMarketsPanel` | Step 4 |
| 7 | New components: `ArticleCard`, `RelevanceBadge`, `ImpactSparkline`, `EntityNewsPanel`, `FundamentalsBar`, `TopNewsFilters` | Step 5, 6 |
| 8 | Stub pages: Dashboard (with alerts feed), Companies, Portfolio, Map, Country | Step 4 |
| 9 | `AppSidebar` + `TopBar` (user info + logout) | Step 4 |
| 10 | All tests: auth suite, component tests, E2E | Step 5–9 |
| 11 | Dockerfile (standalone output), docker-compose update | Step 10 |

---

## 12. Open Items

All architectural decisions are resolved. The following are **product decisions** that can be deferred to implementation time:

| # | Item | Notes |
|---|------|-------|
| OI-01 | `CompaniesPage` full implementation | Currently a stub; no design spec yet — scope TBD |
| OI-02 | `PortfolioPage` full implementation | Currently a stub; depends on PRD-0022 (brokerage sync) |
| OI-03 | `MapPage` full implementation | Currently a stub; PRD not written |
| OI-04 | Mobile sidebar breakpoint | `<768px`? Define in tailwind config |
| OI-05 | `TopBar` user avatar | Zitadel provides `picture` claim — use if available, else initials |
| OI-06 | S9 WS route auth update | S9 must validate `?token=` on `/v1/alerts/stream`; this is a backend task, not frontend |
