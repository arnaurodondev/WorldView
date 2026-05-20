# ADR-0002: Frontend Tooling — Vite + React + pnpm

> **Status**: Superseded by Next.js 15 migration (2026-04-17) — `apps/worldview-web/` is the production frontend (Next.js 15 App Router + shadcn/ui). The `apps/frontend/` Vite+React app is no longer active. See `docs/apps/worldview-web.md` and `docs/ui/frontend-migration.md`.
> **Original Date**: 2026-02-28 · **Author**: Arnau Rodon

## Context

Worldview needs a browser-based frontend to visualize financial data (charts,
fundamentals, news), browse entity relationships, and interact with the RAG chatbot.

The frontend communicates exclusively with the API Gateway (S9) — no direct access
to backend services. Key requirements:

1. Fast developer feedback loop (hot-reload < 100ms)
2. TypeScript-first for type safety across gateway client and components
3. Lightweight charting (TradingView-style candlestick charts)
4. SSE streaming support for chat interface
5. Thesis-appropriate: minimal config, well-documented, widely adopted

## Decision

| Choice | Selected | Alternatives Considered |
|--------|----------|------------------------|
| **Bundler** | Vite 5 | Webpack 5, Turbopack, Parcel |
| **Framework** | React 18 | Vue 3, Svelte, Solid |
| **Package Manager** | pnpm 9 | npm, yarn, bun |
| **Data Fetching** | TanStack Query v5 | SWR, raw fetch, RTK Query |
| **Router** | React Router v6 | TanStack Router |
| **Charts** | lightweight-charts 4 | Recharts, Chart.js, D3 |
| **Unit Tests** | Vitest + Testing Library | Jest |
| **E2E Tests** | Playwright | Cypress |
| **Styling** | CSS Variables | Tailwind, styled-components, CSS Modules |

## Rationale

- **Vite** over Webpack: 10–50× faster HMR; native ESM; simpler config; Vitest integration.
- **React** over alternatives: largest ecosystem for financial dashboards; best TanStack Query support; team familiarity.
- **pnpm** over npm/yarn: strict node_modules (no phantom deps); fast installs via content-addressable store; monorepo-friendly.
- **TanStack Query** over SWR: built-in devtools, query invalidation, optimistic updates, SSR support.
- **lightweight-charts** over D3: purpose-built for OHLCV data; 45KB gzipped; TradingView-quality; minimal API surface.
- **CSS Variables** over Tailwind: zero build-time overhead; dark theme only; small component count doesn't justify a utility framework.
- **Vitest** over Jest: native Vite integration; same transform pipeline; faster startup.
- **Playwright** over Cypress: multi-browser support; better CI performance; native `async/await`.

## Consequences

### Positive
- Sub-second HMR in development
- Type-safe gateway client catches API drift at compile time
- Minimal dependencies (~15 prod deps)
- No CSS build step; variables work natively

### Negative
- React bundle size (~45KB gzipped) larger than Svelte/Solid
- CSS Variables lack component scoping (mitigated by simple component tree)
- Team must maintain Vite config for proxy setup

### Risks
- lightweight-charts API may not cover all chart types needed — fallback: add Recharts for non-OHLCV charts
- pnpm strict mode may conflict with some libraries — mitigated: `.npmrc` with `shamefully-hoist=true` if needed

## Related

- [MASTER_PLAN.md](../../MASTER_PLAN.md) § Service Catalog
- [docs/apps/frontend.md](../../apps/frontend.md) — frontend architecture doc
- [ADR-0001](0001-initial-architecture.md) — initial backend architecture
