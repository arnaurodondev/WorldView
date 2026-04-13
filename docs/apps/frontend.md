# Frontend Web Application

> **Package**: `@worldview/frontend` · **Port**: 3000 (dev) / 3000 (production via `next start`)
> **Status**: Migration in progress (Vite → Next.js 15) · **Spec**: `docs/ui/frontend-migration.md`
> **Tech**: Next.js 15 App Router + shadcn/ui + TypeScript + TanStack Query

---

## Mission & Boundaries

**Owns**: Browser-based UI for the Worldview platform — dashboard, company explorer, portfolio view,
news feed (with news intelligence), interactive map, country profiles, screener, and RAG-powered chat.

**Never does**: Call backend services directly. All data fetching goes through S9 API Gateway
via a typed client (`src/lib/gateway-client.ts`). The gateway URL is always `/api/*`.

**Design canon**: `docs/ui/DESIGN_SYSTEM.md` — design tokens, component catalogue, UX patterns.

---

## Technology Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Next.js 15 (App Router) | Node SSR; no `output: 'export'` (ADR-F-01) |
| UI components | shadcn/ui only | Radix UI primitives + Tailwind CSS |
| Charts | lightweight-charts 4 | `"use client"` wrapper required |
| Server state | TanStack Query v5 | No `useState+useEffect` for API calls |
| Theme | Dark only | `class="dark"` on `<html>` permanently (ADR-F-04) |
| Real-time | WebSocket (alerts), SSE (chat) | Via `useAlertStream` + `EventSource` |
| Auth | Zitadel OIDC + PKCE | Callback → access token in React state only |
| Package manager | pnpm (exact versions) | `pnpm audit` must show 0 CVEs |
| Tests | Vitest (unit) + Playwright (E2E) | |

---

## Architecture

```
apps/frontend/
├── app/
│   ├── layout.tsx                    # Root: <html dark>, AuthProvider, QueryClientProvider
│   ├── globals.css                   # Tailwind base + shadcn/ui CSS variables (dark theme)
│   ├── login/page.tsx                # Public — Zitadel OIDC login
│   ├── callback/page.tsx             # Public — OIDC callback handler
│   └── (protected)/
│       ├── layout.tsx                # Auth guard → /login if not authenticated
│       ├── page.tsx                  # DashboardPage /
│       ├── companies/
│       │   ├── page.tsx              # CompaniesPage /companies
│       │   └── [id]/page.tsx         # CompanyDetailPage /companies/:id
│       ├── portfolio/page.tsx        # PortfolioPage /portfolio
│       ├── news/page.tsx             # NewsPage /news (tabs: Feed | Top Today)
│       ├── map/page.tsx              # MapPage /map
│       ├── countries/[code]/page.tsx # CountryPage /countries/:code
│       ├── chat/page.tsx             # ChatPage /chat (SSE streaming)
│       └── screener/page.tsx         # ScreenerPage /screener
├── src/
│   ├── components/
│   │   ├── ui/                       # shadcn/ui auto-generated
│   │   ├── layout/
│   │   │   ├── AppSidebar.tsx
│   │   │   └── TopBar.tsx
│   │   ├── charts/
│   │   │   └── OHLCVChart.tsx        # "use client" — lightweight-charts
│   │   ├── chat/
│   │   │   └── ChatUI.tsx            # "use client" — EventSource SSE
│   │   ├── alerts/
│   │   │   ├── AlertCard.tsx
│   │   │   ├── SeverityBadge.tsx
│   │   │   └── FlashOverlay.tsx      # Error boundary + auto-dismiss + Escape
│   │   ├── news/
│   │   │   ├── ArticleCard.tsx
│   │   │   ├── NewsList.tsx
│   │   │   ├── RelevanceBadge.tsx    # 0–100 coloured score badge
│   │   │   ├── ImpactSparkline.tsx   # "use client" — day_t0→t5 mini chart
│   │   │   └── TopNewsFilters.tsx    # "use client" — time range + score filters
│   │   ├── instrument/
│   │   │   ├── SimilarCompaniesPanel.tsx
│   │   │   ├── EntityNewsPanel.tsx   # "use client" — chart-range-linked news
│   │   │   └── FundamentalsBar.tsx   # "use client" — 6-metric bar + localStorage
│   │   └── markets/
│   │       └── PredictionMarketsPanel.tsx
│   ├── contexts/
│   │   ├── AuthContext.tsx           # "use client" — OIDC token, silent refresh
│   │   └── AlertStreamContext.tsx    # "use client" — shared WebSocket
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   └── useAlertStream.ts
│   └── lib/
│       ├── authClient.ts             # fetch wrapper with Bearer + 401 refresh
│       └── gateway-client.ts         # Typed API methods
├── designs/                          # pencil.dev canvas files (*.pen)
├── tests/                            # Vitest unit tests
├── e2e/                              # Playwright E2E tests
├── next.config.ts                    # rewrites: /api/* → http://localhost:8000/*
├── tailwind.config.ts
├── components.json                   # shadcn/ui config
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
└── Dockerfile                        # next build → node:alpine → next start
```

---

## Route Map

| Path | Page | Auth | Data Sources |
|------|------|------|-------------|
| `/login` | `LoginPage` | Public | — |
| `/callback` | `CallbackPage` | Public | POST /v1/auth/refresh |
| `/` | `DashboardPage` | Yes | alerts stream |
| `/companies` | `CompaniesPage` | Yes | — |
| `/companies/:id` | `CompanyDetailPage` | Yes | `GET /v1/companies/:id/overview`, OHLCV, news |
| `/portfolio` | `PortfolioPage` | Yes | — |
| `/news` | `NewsPage` (tabs) | Yes | `GET /v1/news/relevant`, `GET /v1/news/top` |
| `/map` | `MapPage` | Yes | `GET /v1/map/layers` |
| `/countries/:code` | `CountryPage` | Yes | — |
| `/chat` | `ChatPage` | Yes | SSE `/v1/chat/stream` |
| `/screener` | `ScreenerPage` | Yes | `POST /v1/fundamentals/screen` |

---

## Gateway Client (`src/lib/gateway-client.ts`)

All API calls MUST go through this typed client. The base URL is always `/api` (proxied to S9 via `next.config.ts` rewrites).

| Method | Endpoint | Notes |
|--------|----------|-------|
| `getCompanyOverview(id)` | `GET /v1/companies/:id/overview` | |
| `getRelevantNews(limit)` | `GET /v1/news/relevant?limit=` | |
| `getTopNews(params)` | `GET /v1/news/top` | PRD-0026 |
| `getEntityNews(id, params)` | `GET /v1/news/entity/:id` | PRD-0026 |
| `getMapLayers()` | `GET /v1/map/layers` | |
| `getScreenFields()` | `GET /v1/fundamentals/screen/fields` | |
| `screenInstruments(filters, opts)` | `POST /v1/fundamentals/screen` | |
| `findSimilarEntities(id, opts)` | `POST /v1/entities/similar` | |
| `getPredictionMarkets(params)` | `GET /v1/signals/prediction-markets` | PRD-0019 |
| `streamChat(message)` | EventSource `/v1/chat/stream?q=` | |

---

## State Management

| State type | Tool | Pattern |
|------------|------|---------|
| Server data | TanStack Query v5 | `useQuery`, `useMutation` |
| Auth + session | React Context (`AuthContext`) | `"use client"` provider |
| Alert WebSocket | React Context (`AlertStreamContext`) | `"use client"`, shared WS |
| Complex client state | Zustand | auth state, alert queue |
| Simple local UI state | `useState` / `useReducer` | filter values, modal open |

---

## Data Loading Pattern (Required for all data-dependent components)

```typescript
function Panel({ id }: { id: string }) {
  const { data, isLoading, error, refetch } = useMyData(id)

  if (isLoading) return <PanelSkeleton />
  if (error)    return <ErrorCard message="..." onRetry={refetch} />
  if (!data)    return <EmptyState message="..." />

  return <PanelContent data={data} />
}
```

**Never render a blank panel.** All three states are required, not optional.

---

## Real-Time Patterns

### WebSocket (alert stream)
- `useAlertStream(token)` — connects to `/api/v1/alerts/stream?token=<access_token>` (ADR-F-02)
- Exponential backoff: 1s → 2s → 4s → ... → 30s cap
- CRITICAL alerts → `criticalQueue` → `FlashOverlay`
- All other alerts → `recentAlerts` → sidebar badge + list

### SSE Streaming (chat)
- State machine: `idle → sending → streaming → reconciling → settled`
- `AbortController` per request; cancel button visible during streaming
- `useRef` for closure safety; cleanup on done/error/cancel

---

## Development

```bash
cd apps/frontend
pnpm install
pnpm dev          # → http://localhost:3000 (rewrites /api → localhost:8000)
pnpm build        # Production Next.js build
pnpm start        # Run production build
pnpm test         # Unit tests (Vitest)
pnpm test:e2e     # E2E tests (Playwright)
pnpm lint         # ESLint
pnpm typecheck    # tsc --noEmit
pnpm audit        # Must show 0 vulnerabilities
```

---

## Tests

| Type | Tool | Location | What |
|------|------|----------|------|
| Unit | Vitest + RTL + MSW | `tests/` | Components: loading/error/empty/happy path |
| E2E | Playwright | `e2e/` | Page loads, navigation, data flow |

**Every component must have at minimum**: a loading state test + a happy path test.

---

## Design Resources

| Resource | Purpose |
|----------|---------|
| `docs/ui/DESIGN_SYSTEM.md` | Design tokens, component catalogue, UX patterns |
| `docs/ui/frontend-migration.md` | ADRs, full Next.js target spec, component inventory |
| `docs/ui/news-intelligence.md` | News feature UI requirements |
| `apps/frontend/designs/*.pen` | pencil.dev canvas design files |

---

## Key Architectural Decisions

| ADR | Decision | Rationale |
|-----|----------|-----------|
| ADR-F-01 | Node SSR (not static export) | Middleware for auth redirects requires Node runtime |
| ADR-F-02 | WS auth via `?token=` query param | Browser WebSocket API has no headers option |
| ADR-F-03 | Migrate in-place (`apps/frontend/`) | Keeps docker-compose paths, CI unchanged |
| ADR-F-04 | Dark mode only | Conventional for market intelligence; simpler |

Full ADR details in `docs/ui/frontend-migration.md §1`.
