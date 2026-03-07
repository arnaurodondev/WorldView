# @worldview/frontend

Web UI for the Worldview financial intelligence platform.

Built with Vite + React + TypeScript + TanStack Query + React Router.

See [docs/apps/frontend.md](../../docs/apps/frontend.md) for full documentation.

## Quick Start

```bash
pnpm install
pnpm dev          # → http://localhost:5173
```

## Scripts

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Start dev server (port 5173) |
| `pnpm build` | Production build |
| `pnpm test` | Unit tests (Vitest) |
| `pnpm test:e2e` | E2E tests (Playwright) |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript check |

## Architecture

- **Router**: React Router v6 (client-side routing)
- **Data fetching**: TanStack Query → typed gateway client → S9 API Gateway
- **Charts**: TradingView lightweight-charts
- **Styling**: CSS variables (dark theme)

The frontend talks **only** to the API Gateway (S9). No direct calls to internal services.
