# Worldview Web — Frontend Documentation

> **Package**: `worldview-web` · **Port**: 3001 (dev + prod)
> **Location**: `apps/worldview-web/`
> **Stack**: Next.js 15 App Router · React 19 · TypeScript · shadcn/ui · TanStack Query · pnpm

---

## 1. Overview

Worldview Web is the production browser UI for the Worldview platform — a Bloomberg/TradingView-grade
financial intelligence terminal built for retail investors who want professional-grade tools without
a Bloomberg Terminal subscription.

**What it looks like**: A dark "Terminal Dark" UI (#09090B background, Bloomberg yellow accent).
Dense data tables, TradingView-style candlestick charts, a drag-and-drop multi-panel workspace,
AI-powered RAG chat, real-time WebSocket alerts, and an entity knowledge graph — all in a single
web application.

**Hard boundary**: The frontend never calls backend services directly. Every API call goes
through S9 (API Gateway) via `/api/*` (Next.js rewrites). Auth tokens live in React state only —
never localStorage, sessionStorage, or cookies that the frontend writes.

**Design canon**: `docs/ui/DESIGN_SYSTEM.md` — Terminal Dark palette, IBM Plex fonts, shadcn/ui only.

---

## 2. Tech Stack

| Concern | Choice | Version | Notes |
|---------|--------|---------|-------|
| Framework | Next.js App Router | 15.5.15 | Node SSR; no `output: 'export'` (ADR-F-01) |
| React | React | 19.0.0 | Server + Client components |
| Language | TypeScript | 5.7.2 | Strict mode, `@/` path alias |
| UI components | shadcn/ui only | Radix UI + Tailwind | 40+ primitives; no other component library |
| Data grid | AG Grid Community | 35.2.1 | Screener + portfolio tables only |
| Charts | lightweight-charts | 5.2.0 | TradingView candlestick/OHLCV charts |
| Portfolio charts | recharts | bundled | Donut/bar charts, code-split to `/portfolio` |
| Server state | TanStack Query | 5.62.7 | `useQuery`, `useMutation`, HydrationBoundary |
| Tables | TanStack Table | 8.21.3 | Column definitions, sorting, selection |
| Virtualisation | TanStack Virtual | 3.13.24 | Large row lists |
| Workspace layout | react-resizable-panels | 4.10.0 | Resizable split panels |
| Graph (entity) | sigma + graphology | 3.0.2 / 0.26.0 | Sigma.js knowledge graph |
| Markdown | react-markdown + remark-gfm | 9.0.3 | Chat and briefing rendering |
| Search | cmdk | 1.0.4 | ⌘K command palette |
| Forms | react-hook-form + zod | 7.54.2 / 3.24.2 | Type-safe form validation |
| URL state | nuqs | 2.4.3 | `useQueryState` for shareable URL-encoded filters |
| Dates | date-fns | 4.1.0 | Date formatting and calculations |
| Toast notifications | sonner | 1.7.4 | Non-blocking user feedback |
| Real-time | WebSocket (alerts), SSE (chat) | — | `useAlertStream` + `EventSource` |
| Auth | Zitadel OIDC + PKCE via S9 | — | Access token in React state only |
| Error tracking | @sentry/nextjs | 10.51.0 | Browser + SSR; no-op in dev when DSN is empty |
| React Compiler | babel-plugin-react-compiler | 1.0.0 | Auto-memoization; enabled via `reactCompiler: true` |
| Styling | Tailwind CSS | 3.4.17 | Terminal Dark design tokens |
| Icons | lucide-react | 0.454.0 | |
| Package manager | pnpm | 10.x exact | `pnpm audit` must show 0 CVEs |
| Unit tests | Vitest + RTL + MSW | 2.1.9 | jsdom environment, 400+ test files |
| E2E tests | Playwright | 1.59.1 | Chrome + WebKit; 40+ spec files |
| Component catalogue | Storybook | 8.6.12 | `pnpm storybook` |

---

## 3. Prerequisites

| Tool | Minimum Version | How to install |
|------|----------------|---------------|
| Node.js | **20.0.0** | [nvm](https://github.com/nvm-sh/nvm) or [fnm](https://github.com/Schniz/fnm) |
| pnpm | **10.0.0** | `corepack enable && corepack prepare pnpm@10 --activate` |

> Do not use npm or yarn. The lock file is pnpm-only (`pnpm-lock.yaml`).

---

## 4. Local Development Setup

### 4.1 Quick Start (minimal)

```bash
# 1. From the repo root, install workspace dependencies
cd apps/worldview-web
pnpm install

# 2. Copy the example environment file
cp .env.example .env.local

# 3. Start the dev server (hot reload on http://localhost:3001)
pnpm dev

# 4. Open http://localhost:3001
#    Without Zitadel configured, the login page shows a "Dev Login" button.
#    Click it to log in with the demo user (no Zitadel needed).
```

### 4.2 With Backend Services

The frontend talks to S9 (API Gateway) at `http://localhost:8000`. For a full working
stack, run the platform first:

```bash
# From the repo root — starts all 46 containers including worldview-web
make dev

# Then seed sample data (demo user, portfolios, watchlists, instruments)
make seed
```

After `make dev` + `make seed`, navigate to `http://localhost:3001`, click **Dev Login**.

### 4.3 Dev Server Protocol (HTTP/1.1 — no HTTP/2)

The Next.js dev server (`next dev`) runs over **HTTP/1.1** only. Next.js 15 has an
`--experimental-https` flag but **no `--experimental-http2` flag**; the HTTPS dev
mode still serves H/1.1 underneath. We evaluated two paths to enable H/2 in dev:

| Option | Decision | Rationale |
| --- | --- | --- |
| `next dev --experimental-https --experimental-http2` | **Rejected** | No such flag exists in Next.js 15. The closest (`--experimental-https`) is still H/1.1. |
| Add a Caddy/nginx reverse proxy in front of `worldview-web:3000` serving H/2 to the browser | **Deferred** | Adds infra complexity and a TLS cert dance for a dev-only optimization. Production already runs over H/2 behind the platform's TLS terminator. |

**Mitigation** for the dev-mode H/1.1 connection cap (6 concurrent sockets per
origin to `/api`): below-fold dashboard widgets defer their TanStack queries by
two animation frames via [`hooks/useAboveFoldReady.ts`](../../apps/worldview-web/hooks/useAboveFoldReady.ts).
This lets above-fold widgets enqueue their fetches first so the dev waterfall
prioritises what the user actually sees.

In **production**, requests fan out through the platform's TLS terminator which
multiplexes them over a single H/2 connection — the dev cap does not apply.
See `/investigate` report F-3/F-4 for the full network-waterfall analysis.

### 4.3 Environment Variables

Copy `apps/worldview-web/.env.example` to `apps/worldview-web/.env.local`:

| Variable | Default | Side | Description |
|----------|---------|------|-------------|
| `API_GATEWAY_URL` | `http://localhost:8000` | Server | S9 gateway URL for Next.js rewrites (NOT exposed to browser) |
| `NEXT_PUBLIC_WS_BASE_URL` | `ws://localhost:8010` | Client | S10 WebSocket URL for alert stream |
| `NEXT_PUBLIC_APP_NAME` | `Worldview` | Client | App name in TopBar and page titles |
| `NEXT_PUBLIC_ZITADEL_URL` | *(empty)* | Client | Zitadel OIDC issuer — **leave blank** to enable Dev Login |
| `NEXT_PUBLIC_ZITADEL_CLIENT_ID` | `worldview-web` | Client | OIDC client ID |
| `NEXT_PUBLIC_SENTRY_DSN` | *(empty)* | Client | Sentry DSN — empty = disabled (no-op in dev) |
| `SENTRY_AUTH_TOKEN` | *(CI only)* | Build | Sentry sourcemap upload; never put in `.env.local` |

> `NEXT_PUBLIC_ZITADEL_URL` is intentionally left without a default. If it is empty,
> the login page detects this and shows the "Dev Login" button instead of the Zitadel OIDC flow.
> Adding a `??` fallback would suppress the dev button even when Zitadel isn't running.

### 4.4 Dev Login Mode

When `NEXT_PUBLIC_ZITADEL_URL` is not set, the platform's dev-login shortcut activates:

1. Navigate to `http://localhost:3001` — you are redirected to `/login`.
2. The login page detects that Zitadel is not configured and renders a **"Dev Login"** button.
3. Clicking "Dev Login" calls `POST /api/v1/auth/dev-login` on S9, which returns an internal JWT
   for the seed demo user.
4. The frontend stores the token in React state and redirects to `/dashboard`.

**Security**: The dev-login endpoint returns `403 Forbidden` when `OIDC_DISCOVERY_OPTIONAL=false`
(i.e., in production). It is never accessible in a properly configured deployment.

**Prerequisite**: Run `make seed` to ensure the demo user and sample data exist in the database.

---

## 5. Project Structure

```
apps/worldview-web/
├── app/                         # Next.js App Router — all pages and layouts
│   ├── layout.tsx               # Root layout: <html class="dark">, IBM Plex fonts, providers
│   ├── providers.tsx            # Client providers: QueryClient + Auth + Alert + AG Grid init
│   ├── globals.css              # Tailwind base + Terminal Dark CSS custom properties
│   ├── page.tsx                 # Public landing page (marketing)
│   ├── error.tsx                # Global error boundary
│   ├── not-found.tsx            # 404 page
│   ├── login/page.tsx           # OIDC login: PKCE code_verifier → Zitadel redirect
│   ├── callback/page.tsx        # OIDC callback: code + verifier → tokens via S9
│   ├── register/page.tsx        # New user registration
│   ├── (app)/                   # Protected route group (auth guard in layout.tsx)
│   │   ├── layout.tsx           # Guards auth, renders shell: TopBar + CollapsibleSidebar
│   │   ├── dashboard/           # Morning brief, portfolio summary, alerts, movers, heatmap
│   │   ├── workspace/           # Drag-drop multi-panel terminal workspace
│   │   ├── instruments/[ticker]/    # Instrument detail: OHLCV chart, tabs, graph (+ /insiders sub-page)
│   │   ├── indices/[ticker]/         # Index detail page (e.g. SPY, QQQ)
│   │   ├── screener/            # Fundamentals screener with filter builder
│   │   ├── portfolio/           # Holdings, P&L, equity curve; sub-pages: /analytics, /transactions, /brokerage (+ /callback)
│   │   ├── alerts/              # Alert rules, history, notification preferences
│   │   ├── news/                # News feed and top today tabs
│   │   ├── chat/                # RAG chat threads with slash commands
│   │   ├── watchlists/[id]/     # Watchlist hub and members
│   │   ├── prediction-markets/  # Polymarket prediction market page
│   │   ├── search/              # Search results page
│   │   ├── connections/         # Global "Weird Connections" feed (PLAN-0112)
│   │   ├── settings/            # Profile, notifications, appearance, data, integrations, security, preferences, beta-program
│   │   ├── status/              # Platform status page
│   │   └── dev-tools/sentry-test/ # Dev-only: synthetic error for Sentry testing
│   ├── (public)/                # Public (unauthenticated) pages
│   ├── admin/                   # Admin panel (feedback review, version info)
│   ├── intelligence/[entity_id]/ # 3-column entity intelligence page
│   ├── feedback/                # Public feedback routes
│   ├── legal/                   # Privacy policy (MDX-driven, [[...slug]])
│   ├── docs/                    # In-app documentation pages
│   └── api/                     # Next.js API routes (version + feedback endpoints)
├── components/                  # React components, organised by domain
│   ├── ui/                      # shadcn/ui auto-generated primitives (40+)
│   ├── shell/                   # App-wide shell: Sidebar, TopBar, FlashOverlay, AskAiPanel
│   ├── dashboard/               # Dashboard widgets: MorningBriefCard, TopMovers, etc.
│   ├── instrument/              # Instrument detail: OHLCVChart, FundamentalsTab, etc.
│   ├── news/                    # ArticleCard, ArticleImpactBadge
│   ├── screener/                # HeatCell, MiniChart, ExportMenu, ColumnSettingsPopover
│   ├── portfolio/               # Holdings table, equity curve, exposure breakdown
│   ├── alerts/                  # AlertsList, RuleManagerDialog, SeverityBadge
│   ├── chat/                    # Chat UI, CitationBar, SlashCommandCard
│   ├── workspace/               # Panel widgets, SymbolLinkColorPicker
│   ├── data/                    # Generic data primitives: DataTable, CompactTable, Sparkline
│   ├── landing/                 # Public landing page sections
│   └── feedback/                # FeedbackWidget, FeedbackDialog
├── features/                    # Co-located feature slices (components + hooks + lib)
│   ├── chat/                    # Chat feature internals
│   ├── dashboard/               # Dashboard feature internals
│   ├── portfolio/               # Portfolio feature internals
│   └── screener/                # Screener feature internals
├── hooks/                       # Custom React hooks
│   ├── useAuth.ts               # Token + auth state access
│   ├── useDebounce.ts           # Input debounce
│   ├── useMarketStatus.ts       # Exchange hours open/closed logic
│   ├── usePortfolioMetrics.ts   # Derived portfolio KPIs
│   ├── useRealizedPnL.ts        # Realized P&L from S9
│   ├── useScreenerSparklines.ts # Batch OHLCV for screener mini-charts
│   └── ... (20+ hooks total)
├── contexts/                    # React Context providers
│   ├── AuthContext.tsx           # OIDC state: isAuthenticated, accessToken, user
│   ├── AlertStreamContext.tsx    # WebSocket alert stream + FlashOverlay trigger
│   ├── SymbolLinkingContext.tsx  # Workspace panel symbol-linking (Bloomberg groups)
│   ├── WorkspaceContext.tsx      # Workspace tab + layout state
│   ├── PreferencesContext.tsx    # User UI preferences
│   ├── HotkeyContext.tsx         # Global keyboard shortcut registration
│   └── SelectedEntityContext.tsx # Cross-panel entity sync (intelligence page)
├── lib/                         # Pure utilities and API client
│   ├── gateway.ts               # Typed S9 API client (composition shim merging 16 domain modules, ~91 call sites)
│   ├── api/                     # Per-domain API modules (auth, instruments, portfolios, …)
│   │   ├── _client.ts           # Base fetch wrapper + GatewayError
│   │   ├── auth.ts
│   │   ├── instruments.ts
│   │   ├── portfolios.ts
│   │   ├── alertRules.ts + useAlertRules.ts  # Standing-rule CRUD + TanStack hooks
│   │   ├── briefing.ts + intelligence.ts + notification-preferences.ts
│   │   └── ... (19 source files total)
│   ├── api-client.tsx           # ApiClientProvider: memoises createGateway(token)
│   ├── format.ts                # Currency, percentage, compact number formatters
│   ├── market-schedule.ts       # Exchange hours and market status helpers
│   ├── instrument-context.ts    # Chart annotations (IndexedDB) + indicator computations
│   ├── workspace-templates.ts   # 5 pre-built workspace starter layouts
│   ├── workspace-share.ts       # Workspace share-via-URL encoding/decoding
│   ├── saved-screens.ts         # Screener saved configurations (localStorage)
│   ├── screener-columns.ts      # Screener column visibility + order (localStorage)
│   ├── notification-prefs.ts    # Alert notification preferences (localStorage)
│   ├── csv-export.ts            # CSV download (papaparse + UTF-8 BOM)
│   ├── xlsx-export.ts           # Excel download (write-excel-file)
│   ├── pdf-export.ts            # PDF download (jspdf + jspdf-autotable)
│   ├── chat/                    # Chat utilities: slash commands, thread export
│   ├── format/                  # TSV/CSV serialisation (CWE-1236 defang)
│   ├── query/                   # TanStack Query key factories
│   ├── storage/                 # Safe localStorage wrapper
│   ├── auth/                    # Session channel (cross-tab signout)
│   ├── sentry/                  # PII stripping for Sentry events
│   └── utils.ts                 # cn() (clsx + tailwind-merge), misc formatters
├── types/
│   └── api.ts                   # TypeScript API contract types
├── __tests__/                   # Co-located Vitest unit tests (400+ files across the tree)
├── e2e/                         # 40+ Playwright e2e spec files
├── next.config.ts               # API rewrite, security headers, Sentry wrap
├── tailwind.config.ts           # Terminal Dark palette tokens
├── vitest.config.ts             # Vitest + jsdom + path alias
├── vitest.setup.ts              # MSW setup + @testing-library/jest-dom
├── playwright.config.ts         # Chrome + WebKit; auto-starts dev server
├── middleware.ts                # Per-request CSP nonce injection
├── components.json              # shadcn/ui config
├── tsconfig.json                # `@` → project root, strict mode
├── package.json                 # Engine: Node ≥20, pnpm ≥10
└── Dockerfile                   # Multi-stage: deps → builder → runner (~120 MB)
```

---

## 6. Routes

### Public Routes (no auth required)

| URL | Purpose | Notes |
|-----|---------|-------|
| `/` | Landing page | Marketing, comparison table, CTA |
| `/login` | OIDC login entry | Generates PKCE `code_verifier`, redirects to Zitadel; shows "Dev Login" when `NEXT_PUBLIC_ZITADEL_URL` is unset |
| `/callback` | OIDC callback handler | Exchanges `code` + `verifier` → tokens via `POST /api/v1/auth/callback`; sanitizes OIDC error params against RFC 6749 whitelist (XSS protection) |
| `/register` | New user registration | `POST /api/v1/auth/register` via S9 |
| `/legal/[[...slug]]` | Privacy policy etc. | MDX-driven |
| `/docs/*` | In-app documentation | Static content |
| `/feedback` | Public feedback | |

### Protected Routes (require auth — redirect to `/login` if not authenticated)

| URL | Purpose | Key Data |
|-----|---------|----------|
| `/dashboard` | Morning brief, market snapshot | Briefings, portfolio summary, top movers, heatmap, alerts |
| `/workspace` | Drag-drop multi-panel terminal | User-configurable panel grid (localStorage, v2 key) |
| `/instruments/[ticker]` | Instrument detail | OHLCV chart, fundamentals, intelligence, entity graph, news. Sub-page `/instruments/[ticker]/insiders` for insider transactions |
| `/indices/[ticker]` | Index detail | Index quote + constituents (e.g. SPY, QQQ, DIA) |
| `/screener` | Fundamental screener | `POST /v1/fundamentals/screen`; collapsible filter sections; saved screens; column settings; CSV/Excel/PDF export; inline sparklines |
| `/portfolio` | Holdings, P&L | Portfolios, holdings, equity curve, sector allocation, realized P&L. Sub-pages: `/portfolio/analytics`, `/portfolio/transactions`, `/portfolio/brokerage` (+ `/callback`) |
| `/alerts` | Alerts & news | Pending + history alerts; snooze/acknowledge; alert rules (CRUD); notification preferences |
| `/news` | News feed | Top today + full feed tabs |
| `/chat` | RAG chat | Thread list with rename/search; slash commands (`/quote`, `/portfolio`, `/news`, etc.); citation confidence bar; context-aware starters |
| `/watchlists/[id]` | Watchlist detail | Members, price summary |
| `/prediction-markets` | Prediction markets | Polymarket data via S9. PLAN-0056 Wave E2 analytical enrichment: collapsible `EventGroupings` (`/events`), per-row honest `SignalBadge` (resolved/closed from status), and a click-to-open right-side **`MarketDetailSheet`** (NOT a route — preserves the infinite-scroll list's scroll+filter state) containing `ProbabilityChart` (recharts LineChart, 1h/1d/1w toggle, HEX palette), current YES/NO odds, liquidity/OI/24h-volume stats (OI honestly "n/a" — not in S3 payload), a recent-flow strip (`/trades`), a history-derived "moving" signal badge (measured YES Δpp ≥ 8pp), and the external Polymarket link (`buildPolymarketUrl`). |
| `/search` | Search results | Full-text entity + instrument search |
| `/settings` | User settings | Profile, notifications, appearance, data, integrations, security, beta program |
| `/intelligence/[entity_id]` | Entity intelligence | 3-column: sigma.js graph, relations/evidence/paths, entity sidebar; full-width RAG chat panel. Sidebar includes `EntityPredictionsSection` (PLAN-0056 Wave E2) — prediction markets referencing the entity via `/entities/{id}/predictions`, with bullish-green/bearish-red/neutral-muted polarity + market link; renders nothing (no header) when the entity has no linked markets. |
| `/connections` | Weird Connections feed | Global graph-wide "weird connections" feed (PLAN-0112 W5). `WeirdConnectionsFeed` consumes `GET /v1/connections/weird` via `useWeirdConnections` (TanStack Query, 5-min staleTime); ranked connections with the reliability/unexpectedness/semantic-distance/novelty sub-score breakdown + a pairwise "how are these related?" picker (`usePathBetween` → `GET /v1/paths/between`). PathsTab/PathInsightsBlock re-labelled from harmonic/diversity/surprise → weirdness. |
| `/status` | Platform status | Service health |
| `/dev-tools/sentry-test` | Dev only | Throws synthetic Sentry error; `notFound()` in production |

### Next.js API Routes

| URL | Purpose |
|-----|---------|
| `/api/v1/*` | Rewritten to `API_GATEWAY_URL` (S9) by `next.config.ts` rewrites |
| `/api/v1/chat/[...path]` | **Dedicated route handler** (not a rewrite) — proxies all `/api/v1/chat/*` (incl. SSE `/stream`) with `no-transform` to avoid gzip-buffering the event stream. App Router route handlers take precedence over `rewrites()` |
| `/api/version` | Returns frontend version info |
| `/status/api/uptime` | Public uptime probe for the status page (`app/(public)/status/api/uptime/route.ts`) |

### Redirect

`/instruments` → `/screener` (307 temporary; server-side via `next.config.ts`)

---

## 7. Key Components

### Shell Components (`components/shell/`)

| Component | Purpose |
|-----------|---------|
| `CollapsibleSidebar` | 48px icon-only rail (collapsed) / 220px with watchlist (expanded); keyboard hint strip; active nav item uses `bg-primary/10 text-primary` |
| `TopBar` | Logo + GlobalSearch + IndexTicker + alerts badge + avatar + UTC clock |
| `FlashOverlay` | Full-screen CRITICAL alert overlay; 12s auto-dismiss; Escape to close; `animate-flash-in` |
| `AskAiPanel` | Mini RAG chat panel accessible from any page |
| `GlobalSearch` | ⌘K command palette (`cmdk`) — entity/instrument search + keyboard navigation |
| `IndexTicker` | Live market index quotes (SPY, QQQ, DIA) in TopBar center |
| `MarketStatusPill` | OPEN / CLOSED / PRE badge based on NYSE hours |
| `UtcClock` | Real-time UTC clock (1-second interval) |

### Instrument Components (`components/instrument/`)

| Component | Purpose |
|-----------|---------|
| `OHLCVChart` | lightweight-charts v5 candlestick chart; wrapped in `next/dynamic` with `ssr: false`; error boundary for chunk failures |
| `ChartToolbar` | h-7 strip: MA50/MA200 toggles + VOL submenu + IND dropdown (RSI/MACD/BB/ATR/STOCH/OBV/VWAP) + Fullscreen |
| `DrawingPalette` | Left-side 28px drawing tools: Trend Line, H-Level, Rectangle, Arrow, Fib, Channel, Text |
| `DrawingCanvas` | Absolutely-positioned SVG overlay for annotations; persisted to IndexedDB |
| `CrosshairHUD` | Bloomberg-style HUD: Date · change-pill · O H L C V at crosshair position |
| `VolumeProfileOverlay` | Right-side SVG histogram; Point of Control highlighted in brand yellow |
| `FundamentalsTab` | Fundamental metrics in expandable sections |
| `IntelligenceTab` | News + relations + narrative |
| `EntityGraphPanel` | Sigma.js entity knowledge graph within instrument detail |
| `LiveQuoteBadge` | Price with freshness dot (green <30s / amber <5m / red stale) |
| `52WeekRangeBar` | Visual slider: current price position in 52-week range |

### Data Primitive Components (`components/data/`, `components/ui/`)

| Component | Purpose |
|-----------|---------|
| `DataTable` | Universal table primitive: 22px compact rows, multi-sort, multi-select, bulk actions, context menu, copy-as-TSV, CSV export |
| `HeatCell` | 7-step heat background for percentage change values in tables |
| `Sparkline` | 20px inline SVG mini-chart for trend context (no chart library) |
| `LivePriceBadge` | Price + freshness dot |
| `CompactTable` | Dense financial table (text-xs, h-8 rows, mono numbers) |
| `NumberInput` | TradingView-style shorthand parser (1.5m / +2% / 25bps / accounting parens) |
| `MultiCombobox` | Multi-select picker with type-ahead and grouped items |
| `SquarifiedTreemap` | Bruls/Huijsen/van Wijk treemap algorithm; used in MarketHeatmap |

### Portfolio Components (`components/portfolio/`)

| Component | Purpose |
|-----------|---------|
| `SemanticHoldingsTable` | Holdings with P&L, heat cells, sparklines; pinned-right ACTIONS kebab (Edit/Close + view) that reuses the right-click floating menu (PLAN-0122 W-D); mode/column-group aware |
| `ExposureBreakdown` | Cash vs Invested visual (colour-blind safe: pattern + label) |
| `SectorAllocationPanel` | Sector bars with `aria-label` + diagonal-stripe pattern |
| `TransactionsTable` | Paginated transactions with filter bar (date, type, ticker, amount range) |
| `PortfolioModeToggle` | Simple \| Advanced segmented control (`role="radiogroup"`, `data-tour-target="mode-toggle"`) driving the dual-mode render gate (PLAN-0122 W-A) |
| `HoldingsColumnGroupToggle` | ⚙ Popover to show/hide the Core/Portfolio/Advanced column groups (Advanced only; PLAN-0122 W-E) |
| `EditPositionDialog` | Honest **adjusting-trade** edit — records a BUY/SELL of the delta via `POST /v1/transactions`; never mutates a holding or rewrites history (PLAN-0122 W-D) |
| `ClosePositionDialog` | Full **or partial** close — editable quantity (default full), "Sell all" reset, validated `0 < qty ≤ holding` (PLAN-0122 W-D) |
| `PortfolioTour` | Dismissible, non-blocking onboarding tour — custom shadcn `Popover` state machine (no new dependency) anchored to `data-tour-target` attrs; auto-starts once after first portfolio create (PLAN-0122 W-F) |

> **Dual-mode portfolio page (PLAN-0122, PRD-0122).** `/portfolio` renders in two
> detail levels driven by a single value from `hooks/usePortfolioMode.ts` — a
> **rendering gate, never a fork** (one `page.tsx` / `HoldingsTab` /
> `SemanticHoldingsTable`; each surface conditionally renders its power-user chrome).
> - **Simple** (public default): 4 KPI tiles (Total Value / Day P&L / Unrealised P&L / Cash),
>   no tab bar (Holdings body rendered directly), no donut/overview/concentration/
>   perf-chart/sector-bar/bottom-cluster/detail-pills, Core-only holdings columns.
>   Brokerage sync strips + `PerformanceStrip` stay shown.
> - **Advanced** (opt-in, byte-for-byte today's layout; guarded by the
>   `test_advanced_mode_is_todays_layout` snapshot): 8 tiles + donut + all strips +
>   4 tabs + column-group toggle.
> - **State**: `usePortfolioMode` resolves URL `?mode=` → localStorage
>   `worldview:portfolioMode:v1` → the `PORTFOLIO_SIMPLE_DEFAULT` flag default
>   (`lib/portfolio/mode-flag.ts`, now `true`). Selecting a mode writes both sinks
>   (sticky + shareable). Rollback = flip the flag back to `false`.
> - **Onboarding tour**: `CreatePortfolioDialog.onSuccess` arms
>   `worldview:portfolioTourSeen:v1="pending"` on a first-ever create;
>   `PortfolioTour` auto-starts once and immediately writes `"done"` (never re-shows);
>   existing users are backfilled to `"done"`. ×/Skip/Escape/outside-click dismiss.

### Alert Components (`components/alerts/`)

| Component | Purpose |
|-----------|---------|
| `AlertsList` | Severity-grouped pending alerts |
| `AlertHistoryTab` | Paginated history with severity + date + entity filters + Load More |
| `AlertDetailSheet` | Right-anchored sheet + Suggested Actions strip |
| `RuleManagerDialog` | Server-backed standing-rule manager (list/pause/edit/delete); opens `AlertWizard` (PLAN-0113) |
| `AlertWizard` | Type-first 2-step rule creator/editor: 5 type cards → per-type editor + severity + notify + live NL summary; real `/v1/alert-rules` CRUD. Accepts `initialRuleType` + a partial `prefillCondition`/`prefillNames` so entry points can pre-scope a rule (PLAN-0113 W5) |
| `condition-editors/*` | Per-type structured editors: `PriceCrossEditor`, `FundamentalCrossEditor`, `NewsVolumeEditor`, `NewsMomentumEditor`, `KgConnectionEditor`. Each accepts an optional partial `value` (prefill) + `names` (id→display-name for seeded chips) |
| `InstrumentAlertButton` | "＋ Alert" affordance on the instrument detail header — opens `AlertWizard` pre-scoped to `PRICE_CROSS` with the instrument seeded (PLAN-0113 W5) |
| `MetricPicker` | Fundamental metric dropdown sourced from S3 `/v1/fundamentals/screen/fields` (emits a backend-valid `metric_key`) |
| `NotificationPreferencesDialog` | Quiet hours + severity floor settings |
| `SeverityBadge` | LOW / MEDIUM / HIGH / CRITICAL colored badge |

> **Standing alert rules (PLAN-0113 W4):** rule CRUD goes through `lib/api/alertRules.ts`
> (gateway factory) + `lib/api/useAlertRules.ts` (TanStack hooks) → S9 `/v1/alert-rules`.
> The 5 rule types (`PRICE_CROSS`, `NEWS_COUNT`, `NEWS_MOMENTUM`, `KG_CONNECTION`,
> `FUNDAMENTAL_CROSS`) carry a discriminated-union `condition`. The legacy
> localStorage rule layer (`lib/alerts/rules.ts`, `AlertRuleBuilder`) is retired —
> `rules.ts` is now a thin type/`defaultRuleName` shim with no browser persistence.
> Shared pickers: `components/common/EntityPicker` (real KG `entity_id` via
> `searchFundamentals`) and `components/common/InstrumentPicker` (S3 `instrument_id`
> via `searchInstruments`).
>
> **Creation entry points (PLAN-0113 W5, FR-11):** besides the `/alerts` page
> (`RuleManagerDialog`), users can launch the wizard pre-scoped where they already
> are: (1) the **instrument detail header** "＋ Alert" button
> (`components/instrument/header/InstrumentAlertButton`) opens it on `PRICE_CROSS`
> with the current `instrument_id` seeded (the user can switch to fundamental/news
> types via Back — they key on the same subject); (2) the **KG path panel**
> (`components/intelligence/PathBetweenPanel`) shows an "Alert on connection"
> button once both entities are chosen, opening the wizard on `KG_CONNECTION` with
> both `source_entity_id`/`target_entity_id` seeded. Both pass a partial
> `prefillCondition` + a `prefillNames` map so the seeded chips and live NL summary
> show tickers/names instead of UUIDs; the wizard still requires the user to
> complete the remaining fields before Save enables.

### Chat Components (`components/chat/`)

| Component | Purpose |
|-----------|---------|
| `CitationBar` | Segmented confidence bar below assistant messages (green ≥0.7 / amber 0.4–0.7 / red <0.4) |
| `SlashCommandCard` | Structured card rendered for slash command responses |
| `SlashCommandAutocomplete` | Autocomplete popover on `/` keypress |

### Workspace Components (`components/workspace/`)

| Component | Purpose |
|-----------|---------|
| `WorkspaceChartWidget` | OHLCV candle chart panel; 5 timeframes; ResizeObserver-driven |
| `WorkspaceFundamentalsWidget` | Compact 6-row fundamentals panel |
| `SymbolLinkColorPicker` | 5-color + "none" symbol-linking dot for panel group sync |
| `NewFromTemplateDialog` | 5 starter workspace templates (Day Trader, Research, etc.) |
| `ShareWorkspaceDialog` | Encode active workspace as URL-safe base64 token in `?config=` |

---

## 8. API Integration

### How It Works

All API calls go through Next.js rewrites defined in `next.config.ts`:

```
Browser → /api/v1/portfolios
  → Next.js server rewrites to → API_GATEWAY_URL/v1/portfolios
    → S9 (api-gateway:8000) routes to the correct backend service
```

This means:
- Components never construct backend URLs — they call `/api/v1/...`.
- `API_GATEWAY_URL` is a **server-side** variable (not `NEXT_PUBLIC_`), so the backend address is never leaked to the browser.
- In production Docker, `API_GATEWAY_URL=http://api-gateway:8000` (Docker-internal DNS).

### Gateway Client (`lib/gateway.ts`)

The typed API client is a composition shim that merges 16 per-domain modules (spread in dependency
order so cross-domain `this.*` calls resolve — e.g. instruments before search):

```typescript
import { createGateway } from "@/lib/gateway"

// In a TanStack Query hook:
const { accessToken } = useAuth()
const { data } = useQuery({
  queryKey: ["portfolios"],
  queryFn: () => createGateway(accessToken).getPortfolios(),
})
```

`createGateway(token)` returns a plain object with all ~91 typed methods. The factory
pattern ensures the latest token is always used on every refetch.

**Domain modules in `lib/api/`**:

| Module | Covers |
|--------|--------|
| `auth.ts` | login, callback, refresh, logout, dev-login, ws-token |
| `instruments.ts` | overview, quotes, OHLCV, fundamentals, context |
| `portfolios.ts` | portfolios CRUD, holdings, transactions, realized P&L |
| `watchlists.ts` | watchlists CRUD, members |
| `alerts.ts` | pending alerts, history, acknowledge, snooze |
| `alertRules.ts` | standing alert-rule CRUD (`/v1/alert-rules`); `useAlertRules.ts` wraps it in TanStack hooks |
| `news.ts` | top news, entity articles, article detail |
| `screener.ts` | screen, saved screens |
| `chat.ts` | threads, stream, messages |
| `briefing.ts` | morning brief, brief diff, brief chat/discuss, brief→alert |
| `dashboard.ts` | dashboard bundle/snapshot, movers, heatmap, sparklines, calendars |
| `knowledge-graph.ts` | entity graph, paths |
| `intelligence.ts` | entity intelligence page data |
| `search.ts` | entity + instrument search |
| `brokerage.ts` | brokerage connections |
| `prediction-markets.ts` | Polymarket signals, categories, history. Wave E2 added `getPredictionMarketPriceHistory(conditionId, interval)` (interval bars, distinct from the legacy days-based `getPredictionMarketHistory` snapshots), `getPredictionMarketTrades`, `getPredictionEvents`, `getEntityPredictions`. TanStack hooks in `prediction-markets-hooks.ts`: `usePredictionMarketPriceHistory` / `usePredictionMarketTrades` / `usePredictionEvents` / `useEntityPredictions` (useAuth token-gated, staleTime 60s/60s/5m/2m). |
| `feedback.ts` | feedback submissions, feature votes, NPS, micro-survey, beta-program |
| `notification-preferences.ts` | per-user notification preferences (`/v1/users/me/notification-preferences`) |

### Real-Time Patterns

**WebSocket (Alert Stream)**:
- URL: `NEXT_PUBLIC_WS_BASE_URL/v1/alerts/stream?token=<ws_token>`
- Token: short-lived RS256 JWT from `GET /api/v1/auth/ws-token`
- `AlertStreamContext` manages the connection; `FlashOverlay` triggers on CRITICAL alerts
- Exponential backoff reconnect: 1s → 2s → 4s → ... → 30s cap
- Security: production enforces `wss://` (plain `ws://` throws a startup error in `next.config.ts`)

**SSE (Chat Streaming)**:
- `fetch()` **POST** to `/api/v1/chat/stream` (not `EventSource` — EventSource is GET-only and cannot send the message body or `Authorization` header). The response body is read as a `ReadableStream` and parsed by `lib/sse-parser.ts`.
- Served by the dedicated route handler `app/api/v1/chat/[...path]/route.ts` (with `no-transform`) rather than the `next.config.ts` rewrite, so the event stream is not gzip-buffered (frontend-rework Wave 3 streaming-paint fix).
- State machine: `idle → sending → streaming → reconciling → settled`
- `AbortController` per request for cancel support
- Auto-scroll to bottom; stops if user scrolls up

---

## 9. Authentication Flow

### 9.1 Production: Zitadel OIDC/PKCE

```
1. Protected page loads → (app)/layout.tsx detects unauthenticated → router.push("/login")

2. /login page:
   - generateCodeVerifier() — 128-char random base64url (crypto.getRandomValues)
   - generateCodeChallenge() — SHA-256 of verifier, base64url encoded
   - Store verifier in sessionStorage (tab-scoped, short-lived)
   - Redirect to: NEXT_PUBLIC_ZITADEL_URL/oauth/v2/authorize
       ?response_type=code&client_id=...&redirect_uri=/callback
       &code_challenge=...&code_challenge_method=S256&state=...

3. Zitadel handles authentication, redirects to /callback?code=...&state=...

4. /callback page:
   - Sanitize error params against RFC 6749 whitelist (XSS protection)
   - Retrieve verifier from sessionStorage
   - POST /api/v1/auth/callback { code, code_verifier, redirect_uri }
   - S9 exchanges code → Zitadel tokens, issues RS256 internal JWT
   - Response: { access_token, token_type, expires_in, user }
   - Call AuthContext.setTokens() → accessToken stored in React state only

5. AuthContext provides accessToken to all components via useAuth()

6. Silent refresh: timer fires 60 seconds before token expiry
   → POST /api/v1/auth/refresh (httpOnly cookie-based)
   → 200: update token in React state
   → 401: session expired, redirect to /login
```

### 9.2 Dev Login Mode

When `NEXT_PUBLIC_ZITADEL_URL` is not set:

```
1. /login detects empty NEXT_PUBLIC_ZITADEL_URL → shows "Dev Login" button
2. Click Dev Login → POST /api/v1/auth/dev-login
3. S9 returns internal JWT for seed demo user
4. AuthContext.setTokens() called → redirect to /dashboard
```

### 9.3 Security Properties

- **Token location**: React state only — never localStorage, never sessionStorage (only PKCE verifier is in sessionStorage, not the token), never a JS-writable cookie
- **XSS resistance**: Token in React state cannot be read by injected scripts
- **Cross-tab signout**: `lib/auth/session-channel.ts` broadcasts signout via BroadcastChannel API
- **WS auth**: Short-lived JWT in query param (browser WebSocket API cannot set headers)

---

## 10. Design System

Full reference: `docs/ui/DESIGN_SYSTEM.md`. Key rules:

### 10.1 Color Palette — "Terminal Dark"

All colors use CSS custom properties. Never use hardcoded hex in components.

| Token (Tailwind) | CSS Variable | Hex | Use |
|-----------------|-------------|-----|-----|
| `bg-background` | `--background` | `#09090B` | Page background |
| `bg-card` | `--card` | `#111113` | Cards, panels |
| `bg-muted` | `--muted` | `#18181B` | Elevated surfaces, hover |
| `bg-surface-2` | `--surface-2` | `#18181B` | Alias for muted |
| `bg-surface-3` | `--surface-3` | `#27272A` | Borders, inputs |
| `text-foreground` | `--foreground` | `#E4E4E7` | Primary text |
| `text-muted-foreground` | `--muted-foreground` | `#71717A` | Labels, captions |
| `bg-primary` | `--primary` | `#FFD60A` | Bloomberg yellow — CTA buttons, active states |
| `text-primary-foreground` | `--primary-foreground` | `#000000` | Text on yellow buttons |
| `text-positive` | `--positive` | `#26A69A` | Price up, gains |
| `text-negative` | `--negative` | `#EF5350` | Price down, losses |
| `text-warning` | `--warning` | `#F59E0B` | Medium severity alerts |
| `border-border` | `--border` | `#27272A` | Panel edges, separators |

> Old "Bloomberg Dark" palette (`#0A0E14` + `#E8A317`) is retired. Never use it.

### 10.2 Typography (ADR-F-15)

| Use | Font | Tailwind |
|-----|------|---------|
| UI text, headings | IBM Plex Sans | `font-sans` |
| **ALL numbers** (prices, %, quantities, dates in tables) | **IBM Plex Mono** | `font-mono tabular-nums` |

**The mono rule is non-negotiable**: every numeric value displayed to the user must use
`font-mono tabular-nums`. Mixing sans and mono within a number column is a typography error.

### 10.3 Layout Density (PRD-0031 Terminal v3)

| Token | Value | CSS Variable |
|-------|-------|-------------|
| Data row height | 22px | `--data-row-height` |
| Panel header | 24px | `--panel-header-height` |
| Top bar | 36px | `--topbar-height` |
| Border radius | 2px (sharp) | `--radius` |
| Sidebar collapsed | 48px | `--sidebar-collapsed-width` |
| Sidebar expanded | 220px | `--sidebar-expanded-width` |

### 10.4 Component Policy

- **Only shadcn/ui** — no other pre-built component library
- Install new components: `pnpm dlx shadcn@latest add <component>`
- Exception: AG Grid Community for data-heavy screener/portfolio tables
- Exception: sigma.js for the knowledge graph (no equivalent in shadcn)
- Charts: lightweight-charts for OHLCV, recharts for portfolio analytics (code-split)

---

## 11. State Management

| State type | Tool | Where |
|------------|------|-------|
| Server data | TanStack Query v5 | `useQuery` / `useMutation` / `useSuspenseQuery` |
| Auth | `AuthContext` | React context, client-only |
| Alert stream | `AlertStreamContext` | React context, shared WebSocket |
| URL state | `nuqs` | `useQueryState` — filters, active tab, etc. |
| Workspace layout | `localStorage` + React state | key `worldview:workspaces:v2` (300ms debounced write) |
| Chart annotations | `IndexedDB` | Per-instrument, managed by `lib/instrument-context.ts` |
| Chart indicators | `localStorage` | key `worldview:chart:indicators:v1` |
| Screener columns | `localStorage` | key `worldview:screenerColumns:v1` |
| Saved screens | `localStorage` | key `worldview:savedScreens:v1` |
| Symbol linking | `localStorage` | key `worldview:symbolLinks:v1` |
| Portfolio detail level | `localStorage` + `nuqs` `?mode=` | key `worldview:portfolioMode:v1` (Simple\|Advanced; `hooks/usePortfolioMode.ts`) |
| Holdings column widths/order | `localStorage` | key `worldview-holdings-cols` (AG-Grid column state) |
| Holdings column groups | `localStorage` | key `worldview:holdingsColGroups:v1` (Core/Portfolio/Advanced visibility; `lib/portfolio/holdings-column-groups.ts`) |
| Onboarding tour seen | `localStorage` | key `worldview:portfolioTourSeen:v1` (`pending`\|`done`; `components/portfolio/PortfolioTour.tsx`) |
| Notification prefs | `localStorage` | Managed by `lib/notification-prefs.ts` |
| Local UI state | `useState` / `useReducer` | Filters, modals, selections |

### TanStack Query: staleTime Defaults

Set at the hook level, not globally:

| Data type | staleTime |
|-----------|-----------|
| Company overview / fundamentals | 5 min |
| OHLCV chart data | 1 min |
| Live quotes (single) | 5 sec |
| Batch quotes (portfolio, heatmap) | 30 sec |
| News articles | 30 sec |
| Screener results | 1 min |
| Prediction markets | 15 sec |
| Chat threads | 30 sec |
| Temporal/macro events | 5 min |

### HydrationBoundary (server prefetch pattern)

Data-heavy pages (Instrument Detail, Portfolio, Screener) use server component prefetch:

```typescript
// page.tsx — Server Component
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query"

export default async function Page({ params }) {
  const queryClient = new QueryClient()
  await queryClient.prefetchQuery({ queryKey: ["data", params.id], queryFn: ... })
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <PageClient entityId={params.id} />
    </HydrationBoundary>
  )
}
```

The client component's `useQuery` finds prefetched data in cache → renders immediately with no loading flash.

---

## 12. Testing

### 12.1 Unit Tests (Vitest)

| Aspect | Detail |
|--------|--------|
| Test runner | Vitest 2.1.9 |
| Environment | jsdom (browser DOM simulation) |
| Component testing | @testing-library/react 16.1.0 |
| API mocking | MSW 2.6.8 (Mock Service Worker) |
| Location | Co-located `**/__tests__/*.test.{ts,tsx}` — 400+ files |
| Coverage | v8 provider; `pnpm test:coverage` |

```bash
pnpm test              # Single run (CI mode)
pnpm test:watch        # Interactive watch mode
pnpm test:coverage     # + HTML coverage report in coverage/
```

**Test requirements**: every component needs at minimum a loading-state test and a happy-path test.
Error states and empty states must also be covered for data-fetching components.

### 12.2 E2E Tests (Playwright)

| Aspect | Detail |
|--------|--------|
| Test runner | Playwright 1.59.1 |
| Browsers | Desktop Chrome + Desktop Safari (WebKit) |
| Location | `e2e/*.spec.ts` — 40+ spec files |
| Server | Auto-started by Playwright (`pnpm dev`; `reuseExistingServer` locally) |
| A11y | `@axe-core/playwright` for accessibility scans |

```bash
pnpm test:e2e          # Run all e2e tests (Chrome + WebKit)
```

Key spec files:
- `e2e/auth.spec.ts` — login / callback / signout flow
- `e2e/dashboard.spec.ts` — dashboard data load
- `e2e/workspace.spec.ts` — workspace panel drag-drop
- `e2e/navigation.spec.ts` — keyboard shortcuts, sidebar navigation
- `e2e/intelligence-page.spec.ts` — entity intelligence page

### 12.3 Storybook

```bash
pnpm storybook          # Component catalogue at http://localhost:6006
pnpm build-storybook    # Static build
```

### 12.4 Other Quality Tools

| Command | Purpose |
|---------|---------|
| `pnpm lint` | Next.js ESLint |
| `pnpm typecheck` | `tsc --noEmit` strict TypeScript |
| `pnpm ci:knip` | Dead code detection (knip) |
| `pnpm ci:depcheck` | Undeclared/unused dependency check |
| `pnpm ci:bundlewatch` | Bundle size regression guard |

---

## 13. Building for Production

### 13.1 Local Build

```bash
cd apps/worldview-web
pnpm build       # Runs prebuild (brand asset generation) then next build
pnpm start       # Serves the production build on http://localhost:3001
```

The build outputs Next.js standalone mode (`.next/standalone/`), which includes only
the modules the app actually imports. The output is ~120 MB vs ~500 MB with full node_modules.

### 13.2 Docker Build

The Dockerfile uses a 3-stage multi-stage build. Build context is the **repo root** (not the
app directory), because `pnpm-lock.yaml` and `pnpm-workspace.yaml` live at the workspace root.

```bash
# From repo root
docker build -t worldview-web -f apps/worldview-web/Dockerfile .

# Run standalone (point at a running S9)
docker run -p 3001:3001 \
  -e API_GATEWAY_URL=http://host.docker.internal:8000 \
  -e NEXT_PUBLIC_WS_BASE_URL=ws://host.docker.internal:8010 \
  worldview-web
```

**Build stages**:

| Stage | Base | What it does |
|-------|------|-------------|
| `deps` | `node:20-alpine` | `pnpm install --frozen-lockfile --filter worldview-web` |
| `builder` | `node:20-alpine` | `next build` → `.next/standalone` |
| `runner` | `node:20-alpine` | Copy standalone output; non-root `nextjs` user; `EXPOSE 3001` |

**Docker Compose** (full platform with frontend):

```bash
# From repo root
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# Frontend logs
docker compose -f infra/compose/docker-compose.yml logs -f worldview-web
```

---

## 14. Observability

**Error tracking**: Sentry (`@sentry/nextjs` 10.51.0)

| Concern | Implementation |
|---------|----------------|
| Browser exceptions | `sentry.client.config.ts` — no-op when `NEXT_PUBLIC_SENTRY_DSN=""` |
| Server-side SSR errors | `sentry.server.config.ts` loaded via `instrumentation.ts` |
| React render errors | `<Sentry.ErrorBoundary>` wraps the full app in `providers.tsx` |
| Source maps | `withSentryConfig` in `next.config.ts` — only when `SENTRY_AUTH_TOKEN` is set; maps deleted after upload |
| PII guard | `lib/sentry/strip-pii.ts` — strips cookies, auth headers, URL slugs; hashes `user.email` with SHA-256 |

**Security headers** (all set in `next.config.ts`):
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security` (only when `NEXT_PUBLIC_WS_BASE_URL` starts with `wss://`)
- Per-request nonce-based CSP via `middleware.ts`

---

## 15. Contributing

### 15.1 Coding Conventions

| Rule | Detail |
|------|--------|
| Components | `"use client"` only when using hooks, DOM APIs, or event handlers |
| Components > 80 lines | Own file; never inline a large component inside another |
| Imports | `@/` alias always (never relative `../../`) |
| Types | No `any`; use `interface` for objects, `type` for unions |
| Numbers | Always `font-mono tabular-nums` — non-negotiable |
| Colors | Always CSS variables / Tailwind tokens — never hardcoded hex |
| UI components | shadcn/ui only — `pnpm dlx shadcn@latest add <name>` |
| Error boundaries | Per page section (`react-error-boundary`) |
| Data fetching | TanStack Query only — no raw `useState+useEffect` for API calls |
| Auth | `createGateway(accessToken).method()` — never construct `Authorization` headers manually |

### 15.2 Adding a New Page

1. Create `app/(app)/<route>/page.tsx` (or a public page under `app/(public)/`).
2. If data-heavy, prefetch in a Server Component with `HydrationBoundary`.
3. Add the route to `components/shell/CollapsibleSidebar.tsx` navigation if user-facing.
4. Add a Vitest test in `__tests__/<route>.test.tsx` (at minimum: loading state + happy path).
5. Add a Playwright spec in `e2e/<route>.spec.ts` for critical user journeys.

### 15.3 Adding a New Component

1. Check `components/ui/` for an existing shadcn/ui primitive first.
2. If not available, create under the relevant domain folder (`components/<domain>/`).
3. Follow the data loading pattern: loading skeleton → error card → empty state → content.
4. All numeric values: `font-mono tabular-nums`.
5. Write a Vitest test.

### 15.4 Adding a New API Method

1. Find the correct domain module in `lib/api/<domain>.ts`.
2. Add the typed method following the pattern in that file.
3. The method is automatically available on `createGateway(token).<method>()`.
4. Update `types/api.ts` with any new response types.
5. Add a gateway test in `__tests__/gateway.test.ts`.

### 15.5 Keyboard Shortcuts

Global shortcuts use a custom data-driven registry: bindings are registered at runtime in
`lib/hotkey-registry.ts` (the single source of truth that `StatusBar` and `HotkeyCheatSheet`
also read, so the UI can't advertise an unwired chord). A single document-level keydown listener
in `hooks/useChordHotkeys.ts` resolves completed chords (e.g. `g d`) against the registry,
respecting a scope stack (modal > input > chart > table > page > global). No third-party
hotkey library is used.

| Shortcut | Action |
|----------|--------|
| `g d` | Navigate to /dashboard |
| `g w` | Navigate to /workspace |
| `g p` | Navigate to /portfolio |
| `g s` | Navigate to /screener |
| `g n` | Navigate to /news |
| `g h` | Navigate to /chat |
| `⌘K` / `Ctrl+K` | Open GlobalSearch command palette |
| `Escape` | Close active modal/overlay |

---

## 16. Key Architectural Decisions

| ADR | Decision |
|-----|----------|
| ADR-F-01 | Node SSR (not static export) — middleware for auth redirects requires Node runtime |
| ADR-F-02 | WS auth via `?token=` query param — browser WebSocket API cannot set custom headers |
| ADR-F-03 | New app at `apps/worldview-web/` (parallel dev, not in-place migration) |
| ADR-F-04 | Dark mode only — `class="dark"` permanent on `<html>`; no toggle |
| ADR-F-06 | `/(app)/*` protected route group — auth guard in group layout |
| ADR-F-07 | Workspace layout in localStorage — user-customizable grid persists across sessions |
| ADR-F-12 | `entity_id` ≠ `instrument_id` — distinct UUIDs; S9 `GET /v1/instruments/{id}/page-bundle` resolves both alongside the rest of the instrument-page data |
| ADR-F-14 | HeatCell for % change values — 7-step colour scale for data-heavy tables |
| ADR-F-15 | IBM Plex Mono for ALL numbers — single highest-impact change for professional appearance |

Full ADR text: `docs/ui/frontend-migration.md §1`

---

## 17. Design Resources

| Resource | Purpose |
|----------|---------|
| `docs/ui/DESIGN_SYSTEM.md` | Complete design system: tokens, component catalogue, UX patterns |
| `docs/ui/frontend-migration.md` | Full ADR set, component inventory, migration history |
| `docs/ui/news-intelligence.md` | News feature UI requirements |
| `docs/ui/competitive-design-research.md` | Bloomberg/TradingView/Finviz competitive analysis |
| `docs/frontend/NEXTJS_GUIDE.md` | Next.js 15 developer reference guide |
| `apps/worldview-web/designs/*.pen` | pencil.dev canvas design files (all 9 states complete) |
