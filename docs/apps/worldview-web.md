# Worldview Web Application (Next.js 15)

> **Package**: `worldview-web` · **Port**: 3001 (dev + prod)
> **Status**: Active development (canonical frontend) · **Spec**: PRD-0028
> **Location**: `apps/worldview-web/`

---

## Mission & Boundaries

**Owns**: Production browser-based UI for the Worldview platform — professional
Bloomberg/TradingView-grade financial intelligence terminal with dashboard, instrument
explorer, portfolio view, news feed, screener, entity graph, workspace, and RAG chat.

**Never does**: Call backend services directly. All data fetching goes through S9 API
Gateway via `/api/*` (Next.js rewrites). Auth tokens are managed via S9 OIDC flow.

**Design canon**: `docs/ui/DESIGN_SYSTEM.md` — Midnight Pro palette, IBM Plex fonts, shadcn/ui only.

---

## Technology Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Next.js 15.1.7 (App Router) | Node SSR required (ADR-F-01) |
| React | 19.0.0 | React 19 with server components |
| UI components | shadcn/ui only | 40+ Radix UI primitives + Tailwind CSS |
| Charts | lightweight-charts 4.2.3 | `"use client"` wrapper required |
| Server state | TanStack Query 5.62.7 | No `useState+useEffect` for API calls |
| Workspace | react-grid-layout 1.5.0 | Drag-drop multi-panel layout |
| Markdown | react-markdown 9.0.3 + remark-gfm | Chat/briefing rendering |
| Search | cmdk 1.0.4 | Command palette (Cmd+K) |
| Theme | Dark only (permanent) | `class="dark"` on `<html>` (ADR-F-04) |
| Real-time | WebSocket (alerts), SSE (chat) | `useAlertStream` + `EventSource` |
| Auth | Zitadel OIDC + PKCE via S9 | Access token in React state only |
| Package manager | pnpm 10+ (exact versions) | `pnpm audit` must show 0 CVEs |
| Tests | Vitest 2.1.8 (unit) + Playwright 1.49.1 (E2E) | MSW for API mocking |
| TypeScript | 5.7.2 | Strict mode |
| Styling | Tailwind CSS 3.4.17 | Midnight Pro design tokens |

---

## Architecture

```
apps/worldview-web/
├── app/
│   ├── layout.tsx                       # Root: <html dark>, providers
│   ├── providers.tsx                    # QueryClient + Auth + Alert providers
│   ├── globals.css                      # Tailwind + Midnight Pro CSS vars
│   ├── page.tsx                         # Public landing page
│   ├── error.tsx                        # Global error boundary
│   ├── not-found.tsx                    # 404 page
│   ├── login/page.tsx                   # OIDC login entry
│   ├── callback/page.tsx                # OIDC callback handler
│   ├── register/page.tsx                # New user registration
│   └── (app)/                           # Protected routes (auth guard in layout)
│       ├── layout.tsx                   # Sidebar + TopBar + content outlet
│       ├── dashboard/page.tsx           # Dashboard (morning brief, portfolio, alerts)
│       ├── workspace/page.tsx           # Drag-drop multi-panel terminal
│       ├── instruments/[entityId]/page.tsx  # Instrument detail + chart
│       ├── screener/page.tsx            # Dynamic filter + results table
│       ├── portfolio/page.tsx           # Holdings, P&L, transactions
│       ├── alerts/page.tsx              # Alert history + news feed
│       ├── chat/page.tsx                # RAG chat threads
│       └── settings/page.tsx            # User profile + preferences
├── components/
│   ├── ui/                              # shadcn/ui auto-generated (40+)
│   ├── shell/                           # App-wide shell components
│   │   ├── Sidebar.tsx                  # Navigation + watchlist
│   │   ├── TopBar.tsx                   # Search + indices + status
│   │   ├── FlashOverlay.tsx             # WebSocket CRITICAL alert overlay
│   │   ├── AskAiPanel.tsx               # Mini RAG chat panel
│   │   ├── GlobalSearch.tsx             # cmdk command palette
│   │   ├── IndexTicker.tsx              # Live index quotes
│   │   ├── MarketStatusPill.tsx         # Market hours indicator
│   │   └── UtcClock.tsx                 # Real-time UTC clock
│   ├── dashboard/                       # Dashboard widgets
│   │   ├── MorningBriefCard.tsx
│   │   ├── PortfolioSummary.tsx
│   │   ├── RecentAlerts.tsx
│   │   ├── TopMovers.tsx
│   │   ├── WatchlistNews.tsx
│   │   ├── AiSignals.tsx
│   │   ├── MarketHeatmap.tsx
│   │   └── EconomicCalendar.tsx
│   ├── instrument/                      # Instrument detail components
│   │   ├── OHLCVChart.tsx               # lightweight-charts wrapper
│   │   ├── FundamentalsTab.tsx
│   │   ├── IntelligenceTab.tsx
│   │   ├── EntityGraphPanel.tsx         # Graph visualization
│   │   └── LiveQuoteBadge.tsx           # Real-time price
│   ├── news/
│   │   ├── ArticleCard.tsx
│   │   └── ArticleImpactBadge.tsx       # Relevance score badge
│   ├── screener/
│   │   └── HeatCell.tsx                 # 7-step colored metric cells
│   └── alerts/
│       ├── AlertsList.tsx
│       ├── AlertHistoryTab.tsx              # PLAN-0051 T-D-4-04 history tab
│       ├── AlertDetailSheet.tsx             # Right-anchored panel + Suggested Actions (T-D-4-05)
│       ├── AddToWatchlistDialog.tsx         # T-D-4-05 quick add to watchlist
│       ├── AlertRuleBuilder.tsx             # Legacy quick-add form
│       ├── RuleManagerDialog.tsx            # T-D-4-06 full CRUD + List/Edit tabs
│       ├── NotificationPreferencesDialog.tsx # T-D-4-07 quiet hours + severity floor
│       └── SeverityBadge.tsx
├── hooks/
│   ├── useAuth.ts                       # Token + auth state
│   ├── useDebounce.ts
│   └── useMarketStatus.ts              # Exchange hours logic
├── contexts/
│   ├── AuthContext.tsx                  # OIDC + silent refresh
│   └── AlertStreamContext.tsx           # WebSocket alert stream
├── lib/
│   ├── gateway.ts                       # Typed S9 API client (41 methods)
│   ├── market-schedule.ts               # Exchange hours
│   └── utils.ts                         # cn(), formatters
├── types/
│   └── api.ts                           # TypeScript API contracts
├── __tests__/                           # 13 Vitest test files
├── e2e/                                 # Playwright tests
├── next.config.ts                       # API rewrite: /api/* → API_GATEWAY_URL
├── vitest.config.ts
├── vitest.setup.ts                      # MSW + jest-dom matchers
├── playwright.config.ts                 # Chrome + WebKit
├── tailwind.config.ts                   # Midnight Pro palette
├── components.json                      # shadcn/ui config
├── tsconfig.json                        # Path alias: @ → ./
├── postcss.config.mjs
├── package.json
├── .env.example
└── .eslintrc.json
```

---

## Route Map

| Path | Page | Auth | Key Data Sources |
|------|------|------|-----------------|
| `/` | Landing | Public | — |
| `/login` | Login | Public | S9 `/v1/auth/login` |
| `/callback` | Callback | Public | S9 `/v1/auth/callback` |
| `/register` | Register | Public | S9 `/v1/auth/register` |
| `/(app)/dashboard` | Dashboard | Yes | Briefings, portfolio, alerts, movers, heatmap |
| `/(app)/workspace` | Workspace | Yes | User-configurable multi-panel grid |
| `/(app)/instruments/[entityId]` | Instrument Detail | Yes | OHLCV, fundamentals, graph, news |
| `/(app)/screener` | Screener | Yes | `POST /v1/fundamentals/screen` (PLAN-0051 Wave B: collapsible Valuation/Profitability/Growth/Leverage/Technical/News sections; "X of Y match" header; Load More pagination accumulator; client-side fallback for technical filters; metric names per `docs/services/market-data.md`; gaps documented in `docs/audits/2026-04-29-screener-metric-gap.md`. **Wave B Part 2:** Saved Screens dialog (localStorage CRUD via `lib/saved-screens.ts`); Column Settings popover (visibility + drag-reorder + Reset, persisted via `lib/screener-columns.ts`); Export menu (CSV via `lib/csv-export.ts` / Excel via `lib/xlsx-export.ts` write-excel-file 4.0.4 / PDF via `lib/pdf-export.ts` jspdf 4.2.1 + jspdf-autotable 5.0.7); inline 30-day SVG sparklines via `components/screener/MiniChart.tsx` powered by `hooks/useScreenerSparklines.ts` consuming `POST /v1/quotes/bars/batch` with 5-min `staleTime` and 50-id chunking) |
| `/(app)/portfolio` | Portfolio | Yes | Portfolios, holdings, transactions. **PLAN-0051 Wave F polish (21 items):** EquityCurveChart period state hoisted to the page (`useState<PeriodLabel>` in `app/(app)/portfolio/page.tsx`) so future panels can mirror the user's lookback choice; Holdings sort persisted to URL (`?sort=...&dir=...`) via `router.replace` so views are shareable and survive tab switches; ExposureBreakdown empty/error states vertically centered inside `min-h-[180px]`; RiskMetricsStrip collapses to 1-col stack at <640px (`grid-cols-1 sm:grid-cols-3 md:grid-cols-5` + dynamic `divide-y` ↔ `divide-x`); Day P&L tile renders `<Skeleton>` when value is `null` (genuinely unknown) vs `$0.00` when truly zero; sector allocation bars carry `aria-label="Sector X: Y%"` + diagonal-stripe pattern overlay for colour-blind safety; Cash vs Invested exposure segments distinguished by pattern (stripe vs solid) AND label; mobile safe-area insets applied via `pt-[env(safe-area-inset-top)]` / `pb-[env(safe-area-inset-bottom)]`; watchlist resolution badge escalates from "resolving…" to red "timeout — re-add" after 60s; placeholder transactions (qty=0 + price=0) rendered with `text-muted-foreground/50`; loading skeleton shape matches the populated KPI strip exactly (7 tiles, `divide-x`); empty-state copy guide (Title + Body + CTA) applied to Holdings and Transactions tables. |
| `/(app)/alerts` | Alerts & News | Yes | Pending alerts + top news. **PLAN-0051 Wave D:** nested status sub-tabs (Active / Snoozed / Acknowledged / History) — Active = severity-grouped pending list, Snoozed/Acknowledged/History = paginated `GET /v1/alerts/history` with severity + date range + entity filters and Load More pagination. ACK + Snooze are backend-synced via `PATCH /v1/alerts/{id}/acknowledge` and `PATCH /v1/alerts/{id}/snooze` (with localStorage fallback + "(local only)" badge on 404). The AlertDetailSheet adds a "Suggested Actions" strip (View Instrument, Add to Watchlist, Set Alert Rule, Open in Chat). The page header adds a "Preferences" button (`NotificationPreferencesDialog`, persisted via `lib/notification-prefs.ts`) and the "⚙ Rules" button now opens a full CRUD `RuleManagerDialog` (List/Edit tabs, localStorage-only — see `docs/audits/2026-04-29-alert-rule-crud-gap.md`). |
| `/(app)/chat` | Chat | Yes | SSE `/v1/chat/stream`. **PLAN-0051 Wave E:** slash commands (`/quote`, `/portfolio`, `/news`, `/watchlist`, `/alerts`, `/screener`) parsed via `lib/chat/slash-commands.ts` and rendered as inline structured cards via `components/chat/SlashCommandCard.tsx` — short-circuits the LLM call. Autocomplete popover (`SlashCommandAutocomplete.tsx`) appears on `/`. Assistant messages render through `<MarkdownContent>` (tables, lists, **code blocks with copy button**). **Citation visualisation**: each assistant turn shows a segmented confidence bar (`components/chat/CitationBar.tsx`) — green ≥0.7, amber 0.4–0.7, red <0.4 — with hover tooltip + anchor scroll. **Thread sidebar**: search input above list (200ms debounced substring filter on title + last messages); double-click a thread title to rename inline (`PATCH /v1/threads/{id}` via `gateway.updateThread()`, optimistic with rollback). **Header**: Export button downloads the conversation as a Markdown file via `lib/chat/export-thread.ts`. **Context-aware starters**: when `?entity_id=` is present, 4 entity-tailored starter cards replace the generic 6. |
| `/(app)/settings` | Settings | Yes | Email preferences |

### Route Groups

- **Public routes** (`/`, `/login`, `/callback`, `/register`) — no auth required
- **Protected routes** (`/(app)/*`) — `AuthContext` in `(app)/layout.tsx` redirects to `/login` if not authenticated (ADR-F-06)

---

## API Integration

### Gateway Client (`lib/gateway.ts`)

All API calls go through this typed client. Base URL is `/api` (proxied by `next.config.ts` rewrites to `API_GATEWAY_URL`).

```
/api/v1/portfolios → API_GATEWAY_URL/v1/portfolios → S1 Portfolio
```

**45 typed methods** covering: auth (4), instruments/market data (6 — adds `getBatchOhlcvBars` for screener sparklines, PLAN-0051 T-B-2-09), knowledge graph (2), news (3), screener (2), portfolio (5), watchlists (6), alerts (4 — PLAN-0051 T-D-4-03/04 adds `acknowledgeAlert` (now `PATCH /acknowledge`), `snoozeAlert`, `getAlertHistory`), chat (5), prediction markets (1), dashboard (5), search (1), AI signals (1).

#### Portfolio methods

- `getPortfolios()` → `Portfolio[]` — list portfolios for the authenticated user.
- `createPortfolio(name, currency?)` → `Portfolio` — create a manually-managed portfolio (S9 injects owner_user_id from JWT).
- `getHoldings(portfolioId)` → `HoldingsResponse` — current open positions with server-side P&L snapshot.
- `getTransactions(portfolioId, params?)` → `TransactionsResponse` — paginated, newest-first transaction history.
- `getRealizedPnL(portfolioId, from?, to?)` → `RealizedPnLResponse` *(PLAN-0051 T-A-1-04 / T-A-1-05)* — FIFO-computed realized P&L over a date window. Returns `total_realized`, `realized_long_term`, `realized_short_term`, `count`, and `breakdown_by_instrument`. Used by `useRealizedPnL` (`hooks/useRealizedPnL.ts`) which the Portfolio KPI Strip consumes; falls back to a client-side approximation with an "(approx)" badge when the endpoint is unavailable.

### Real-Time Patterns

**WebSocket (Alert Stream)**:
- URL: direct to S10 via `NEXT_PUBLIC_WS_BASE_URL` + `/v1/alerts/stream?token=<ws_token>`
- Token: 30-second RS256 JWT from `GET /v1/auth/ws-token` (ADR-F-02)
- Exponential backoff: 1s → 2s → 4s → ... → 30s cap
- CRITICAL alerts → FlashOverlay (full-screen, 12s auto-dismiss, Escape to close)

**SSE (Chat Streaming)**:
- State machine: `idle → sending → streaming → reconciling → settled`
- Cancel via AbortController per request
- `useRef` for closure safety

---

## State Management

| State Type | Tool | Pattern |
|------------|------|---------|
| Server data | TanStack Query v5 | `useQuery`, `useMutation`, `useSuspenseQuery` |
| Auth | React Context (`AuthContext`) | `"use client"` provider |
| Alert stream | React Context (`AlertStreamContext`) | `"use client"`, shared WS |
| Local UI state | `useState` / `useReducer` | Filters, modals, selections |
| Workspace layout | `localStorage` + React state | Persisted grid layout — versioned key `worldview:workspaces:v2` (300-ms debounced writes; auto-migrates from legacy `worldview-workspaces` v1 key on first load). PLAN-0051 T-C-3-01. |
| Symbol linking | React Context (`SymbolLinkingContext`) + `localStorage` | Per-workspace; persists per-panel link colors at `worldview:symbolLinks:v1` (active symbol intentionally NOT persisted). 5 colors + "none" with broadcast across same-color panels. PLAN-0051 T-C-3-05. |
| Workspace chart | `WorkspaceChartWidget` (lightweight-charts 4.2.3) | Panel-sized OHLCV candle chart with 5 timeframes (1D/1W/1M/3M/1Y), Midnight Pro palette, ResizeObserver-driven sizing. Renders an empty state when no symbol is linked; renders an error banner with retry on fetch failure. PLAN-0051 T-C-3-03. |
| Workspace fundamentals | `WorkspaceFundamentalsWidget` | Compact 6-row fundamentals table (Market Cap / P/E TTM / P/B / Div Yield / ROE / Beta). Reuses `getFundamentals` + `getFundamentalsSnapshot`. PLAN-0051 T-C-3-04. |
| Workspace templates | `lib/workspace-templates.ts` + `NewFromTemplateDialog` | 5 starter layouts (Day Trader, Research, Swing Trader, News Junkie, Investor) instantiated via the "+ Template" button. Each template's panel types are validated against `PanelType` at test time (`__tests__/workspace-templates.test.tsx`). PLAN-0051 T-C-3-06. |
| Workspace share-via-URL | `lib/workspace-share.ts` + `ShareWorkspaceDialog` | Encode the active workspace as a URL-safe base64 token in `?config=…`. 4096-char cap; oversize layouts surface an error banner. On page mount, `?config=…` is decoded, persisted as a new tab named "Imported: …", and the page reloads. PLAN-0051 T-C-3-07. |

---

## Configuration

Copy `.env.example` to `.env.local`:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_GATEWAY_URL` | `http://localhost:8000` | S9 gateway URL (server-side, NOT public) |
| `NEXT_PUBLIC_WS_BASE_URL` | `ws://localhost:8010` | S10 WebSocket URL (client-side) |
| `NEXT_PUBLIC_APP_NAME` | `Worldview` | App name for UI |
| `NEXT_PUBLIC_ZITADEL_URL` | `http://localhost:8080` | Zitadel OIDC endpoint |
| `NEXT_PUBLIC_ZITADEL_CLIENT_ID` | `worldview-web` | OIDC client ID |

---

## Development

```bash
cd apps/worldview-web

# 1. Install dependencies
pnpm install

# 2. Copy env
cp .env.example .env.local

# 3. Start dev server (requires S9 running on :8000)
pnpm dev              # → http://localhost:3001

# 4. Build for production
pnpm build            # → .next/
pnpm start            # Production server on :3001
```

### All Commands

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Dev server at http://localhost:3001 |
| `pnpm build` | Production build (`.next/`) |
| `pnpm start` | Run production build on :3001 |
| `pnpm test` | Vitest (single run) |
| `pnpm test:watch` | Vitest interactive mode |
| `pnpm test:coverage` | Vitest with v8 coverage report |
| `pnpm test:e2e` | Playwright (Chrome + WebKit) |
| `pnpm lint` | Next.js lint |
| `pnpm typecheck` | `tsc --noEmit` |

---

## Testing

| Type | Tool | Location | What |
|------|------|----------|------|
| Unit | Vitest + RTL + MSW | `__tests__/` | Components: loading/error/empty/happy path |
| E2E | Playwright | `e2e/` | Page loads, navigation, data flow |
| Mocking | MSW 2.6.8 | `vitest.setup.ts` | API response mocking |

**Every component must have**: loading state test + happy path test (minimum).

### Running Tests

```bash
pnpm test                  # Unit tests (CI mode)
pnpm test:coverage         # + coverage report
pnpm test:e2e              # Playwright (auto-starts dev server)
```

---

## Observability

**Error tracking**: `@sentry/nextjs 10.51.0` (PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1).

| Concern | Implementation |
|---------|----------------|
| Browser exceptions | `sentry.client.config.ts` — `Sentry.init()` with empty DSN no-op in dev |
| Server-side SSR errors | `sentry.server.config.ts` loaded via `instrumentation.ts` `register()` |
| Edge runtime | `sentry.edge.config.ts` (minimal; edge runtime not heavily used) |
| React render errors | `<Sentry.ErrorBoundary fallback={<GlobalErrorFallback />}>` wraps full app in `providers.tsx` |
| Build-time sourcemaps | `withSentryConfig(...)` in `next.config.ts` — **only when `SENTRY_AUTH_TOKEN` is set**; maps deleted after upload (`sourcemaps.deleteSourcemapsAfterUpload: true`) |
| PII guard | `lib/sentry/strip-pii.ts` — strips cookies, auth headers, URL slugs; hashes `user.email` with SHA-256 |

**Default-disabled in dev**: `NEXT_PUBLIC_SENTRY_DSN=""` puts the SDK in no-op mode — no network calls.

**Dev smoke-test route**: `/(app)/dev-tools/sentry-test` — throws a synthetic error when clicked; 404s in production via `notFound()` guard.

**Env vars** (see `.env.example`):

| Variable | Side | Purpose |
|----------|------|---------|
| `NEXT_PUBLIC_SENTRY_DSN` | client+server | Sentry DSN (empty = disabled) |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | client+server | Sentry environment label |
| `SENTRY_AUTH_TOKEN` | build-time CI only | Sourcemap upload; never in `.env.local` |
| `SENTRY_ORG` | build-time CI only | Sentry org slug |
| `SENTRY_PROJECT` | build-time CI only | Sentry project slug |

---

## Design System Reference

| Token | Value |
|-------|-------|
| Background | `#131722` (Midnight Pro) |
| Card | `#1E2329` |
| Text | `#D1D4DC` |
| Accent | `#0EA5E9` (sky-500) |
| Positive | `#26A69A` (teal) |
| Negative | `#EF5350` (muted red) |
| UI Font | IBM Plex Sans (300–700) |
| Data Font | IBM Plex Mono (400–600) — **mandatory for ALL numbers** |

Full reference: `docs/ui/DESIGN_SYSTEM.md`

---

## Key Architectural Decisions

| ADR | Decision | Rationale |
|-----|----------|-----------|
| ADR-F-01 | Node SSR (not static export) | Middleware for auth redirects requires Node runtime |
| ADR-F-02 | WS direct to S10 via `?token=` query param | Browser WebSocket API has no headers; Next.js rewrites don't support WS upgrade ([full ADR](../architecture/decisions/ADR-F-02-websocket-direct-connection.md)) |
| ADR-F-03 | New app (`apps/worldview-web/`), not in-place migration | Zero-risk parallel development |
| ADR-F-04 | Dark mode only (permanent) | Professional market intelligence convention |
| ADR-F-06 | `/(app)/*` protected route group | Auth guard in group layout |
| ADR-F-07 | Workspace layout in localStorage | User-customizable grid persists |
| ADR-F-15 | IBM Plex Mono for ALL numbers | Highest-impact professional appearance rule |

Full ADR details in `docs/ui/frontend-migration.md §1`.

### Recent Hardening (2026-04-18 QA, F-CRIT-006 / F-MAJOR-007/008)

- **OHLCVChart error boundary**: `OHLCVChart.tsx` uses `next/dynamic` with `ssr: false` for `lightweight-charts`. A React error boundary wraps the dynamic import to gracefully handle load failures (e.g., network errors, chunk 404) instead of crashing the instrument detail page.
- **Callback OIDC error sanitization**: `callback/page.tsx` sanitizes OIDC `error` and `error_description` query parameters against the RFC 6749 whitelist before rendering. Prevents reflected XSS from malicious error values in the redirect URL.
- **E2E strict per-endpoint mocks (D-002)**: Playwright E2E tests use strict per-endpoint MSW mocks — each test declares exactly which API endpoints it expects, and unmocked requests fail loudly. This replaces the previous blanket mock approach and catches missing/stale mock definitions.

---

## Dev Login (Local Development)

When Zitadel is not configured (`OIDC_DISCOVERY_OPTIONAL=true` and no OIDC issuer set on S9), the platform provides a simplified login flow for local development:

1. The frontend login page (`/login`) detects that Zitadel is unavailable and renders a **"Dev Login"** button alongside the normal OIDC login.
2. Clicking "Dev Login" calls `POST /v1/auth/dev-login` on S9, which returns a valid internal JWT (same shape as `/v1/auth/callback`) for the demo user from seed data.
3. The frontend stores the token and redirects to the dashboard as normal.

**Prerequisites**: Run `make seed` to populate the demo user and sample data (portfolios, watchlists, instruments).

**Security**: The dev-login endpoint returns `403 Forbidden` when OIDC is configured (i.e., in production). It is never accessible outside local development.

---

## Design Resources

| Resource | Purpose |
|----------|---------|
| `docs/ui/DESIGN_SYSTEM.md` | Tokens, component catalogue, UX patterns |
| `docs/ui/frontend-migration.md` | ADRs, component inventory, target architecture |
| `docs/ui/news-intelligence.md` | News feature UI requirements |
| `docs/ui/competitive-design-research.md` | Bloomberg/TradingView research |
| `docs/frontend/NEXTJS_GUIDE.md` | Next.js 15 developer guide |
| `apps/worldview-web/designs/*.pen` | pencil.dev canvas design files |

---

## Docker

The app uses a multi-stage Dockerfile (`apps/worldview-web/Dockerfile`) with Next.js standalone output:

```
Stage 1 (deps)    — pnpm install --frozen-lockfile
Stage 2 (builder) — pnpm build → .next/standalone
Stage 3 (runner)  — node:20-alpine, non-root user, ~120 MB
```

### Docker Compose

The `worldview-web` service is defined in `infra/compose/docker-compose.yml` (profiles: `infra`, `all`):

```bash
# Full platform including frontend
docker compose -f infra/compose/docker-compose.yml --profile infra up -d

# Frontend logs
docker compose -f infra/compose/docker-compose.yml logs -f worldview-web
```

| Env Var | Default | Purpose |
|---------|---------|---------|
| `API_GATEWAY_URL` | `http://api-gateway:8000` | S9 proxy target (server-side rewrites) |
| `NEXT_PUBLIC_ZITADEL_URL` | `http://localhost:8088` | OIDC provider for login |
| `NEXT_PUBLIC_ZITADEL_CLIENT_ID` | `worldview-web` | OIDC client ID |

### Standalone build

```bash
docker build -t worldview-web apps/worldview-web/
docker run -p 3001:3001 -e API_GATEWAY_URL=http://host.docker.internal:8000 worldview-web
```
