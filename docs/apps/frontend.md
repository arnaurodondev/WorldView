# Frontend Web Application

> **Package**: `@worldview/frontend` · **Port**: 5173 (dev) / 80 (production)
> **Status**: New · **Tech**: Vite + React 18 + TypeScript + TanStack Query

---

## Mission & Boundaries

**Owns**: Browser-based UI for the Worldview platform — dashboard, company
explorer, portfolio view, news timeline, interactive map, country profiles,
and RAG-powered chat interface.

**Never does**: Call backend services directly. All data fetching goes through
the API Gateway (S9) via a typed client (`src/lib/gateway-client.ts`).

---

## Architecture

```
apps/frontend/
├── index.html              # Vite entry point
├── src/
│   ├── main.tsx            # React root + providers (QueryClient, Router)
│   ├── App.tsx             # Route definitions
│   ├── index.css           # Global styles (CSS variables, dark theme)
│   ├── components/
│   │   ├── Layout.tsx      # App shell (sidebar nav + <Outlet/>)
│   │   ├── OHLCVChart.tsx  # Candlestick chart (lightweight-charts)
│   │   ├── NewsList.tsx    # Article list component
│   │   └── ChatUI.tsx      # Chat interface with SSE streaming
│   ├── pages/
│   │   ├── DashboardPage.tsx       # /
│   │   ├── CompaniesPage.tsx       # /companies
│   │   ├── CompanyDetailPage.tsx   # /companies/:id
│   │   ├── PortfolioPage.tsx       # /portfolio
│   │   ├── NewsPage.tsx            # /news
│   │   ├── MapPage.tsx             # /map
│   │   ├── CountryPage.tsx         # /countries/:code
│   │   └── ChatPage.tsx            # /chat
│   └── lib/
│       └── gateway-client.ts   # Typed API client for S9
├── tests/
│   ├── setup.ts
│   └── OHLCVChart.test.tsx
├── e2e/
│   └── homepage.spec.ts
├── deploy/
│   └── nginx.conf          # Production SPA + API proxy
├── Dockerfile              # Multi-stage: Node build → nginx serve
├── vite.config.ts          # Dev proxy /api → localhost:8000
├── vitest.config.ts        # Vitest + jsdom
├── playwright.config.ts    # E2E with Chromium
├── tsconfig.json
├── package.json
└── .env.example
```

---

## Routing Map

| Path | Page Component | Data Source |
|------|---------------|-------------|
| `/` | `DashboardPage` | — (placeholder) |
| `/companies` | `CompaniesPage` | — (placeholder) |
| `/companies/:id` | `CompanyDetailPage` | `GET /v1/companies/:id/overview` |
| `/portfolio` | `PortfolioPage` | — (placeholder) |
| `/news` | `NewsPage` | `GET /v1/news/relevant` |
| `/map` | `MapPage` | `GET /v1/map/layers` |
| `/countries/:code` | `CountryPage` | — (placeholder) |
| `/chat` | `ChatPage` | `POST /v1/chat/stream` (SSE) |

---

## Data Fetching

All API calls use TanStack Query for caching, deduplication, and background refetching.

```typescript
// Example: CompanyDetailPage
const { data } = useQuery({
  queryKey: ["company", id],
  queryFn: () => gateway.getCompanyOverview(id),
});
```

The gateway client (`src/lib/gateway-client.ts`) provides typed methods:

| Method | Gateway Endpoint | Return Type |
|--------|-----------------|-------------|
| `getCompanyOverview(id)` | `GET /v1/companies/:id/overview` | `CompanyOverview` |
| `getRelevantNews(limit)` | `GET /v1/news/relevant` | `{ articles: Article[] }` |
| `getMapLayers()` | `GET /v1/map/layers` | `{ layers: MapLayer[] }` |
| `streamChat(message)` | SSE | `EventSource` |

---

## Development

### Prerequisites

| Tool | Version |
|------|---------|
| Node.js | 20+ |
| pnpm | 9+ |

### Commands

```bash
cd apps/frontend
pnpm install
pnpm dev          # → http://localhost:5173 (proxies /api → localhost:8000)
pnpm build        # Production build → dist/
pnpm test         # Unit tests (Vitest)
pnpm test:e2e     # E2E tests (Playwright + Chromium)
pnpm lint         # ESLint
pnpm typecheck    # tsc --noEmit
```

### Dev Proxy

In development, Vite proxies `/api/*` to `http://localhost:8000` (S9 gateway),
stripping the `/api` prefix. This avoids CORS issues during local development.

---

## Testing Strategy

| Type | Tool | Location | What |
|------|------|----------|------|
| Unit | Vitest + Testing Library | `tests/` | Component rendering, chart mount |
| E2E | Playwright | `e2e/` | Navigation, page content |

### Coverage Targets

| Area | Target |
|------|--------|
| Components | ≥ 70% |
| Gateway client | ≥ 80% |
| Pages | ≥ 50% (mostly integration) |

---

## Deployment

### Docker

```bash
docker build -t worldview-frontend .
docker run -p 80:80 worldview-frontend
```

The Dockerfile uses a multi-stage build:
1. **Builder**: Node 20 + pnpm → `pnpm build` → static files in `dist/`
2. **Runtime**: nginx:alpine serving static files with SPA fallback

### Nginx Configuration

- SPA fallback: all routes → `index.html`
- API proxy: `/api/*` → `http://api-gateway:8000/`
- Static asset caching: 1 year with `immutable`

---

## Design Decisions

- **Dark theme only** (financial data readability)
- **CSS variables** (no CSS-in-JS library — keeps bundle small)
- **lightweight-charts** for OHLCV (TradingView open-source, ~45KB gzipped)
- **No state management library** — TanStack Query handles server state;
  local state uses React `useState`/`useReducer`
- See [ADR-0002](../architecture/decisions/0002-frontend-tooling.md) for
  full rationale on Vite + React + pnpm choice
