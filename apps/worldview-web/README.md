# worldview-web

Bloomberg/TradingView-grade financial intelligence terminal — the production Next.js 15 frontend
for the Worldview platform.

**Stack**: Next.js 15 App Router · React 19 · TypeScript · shadcn/ui · TanStack Query · pnpm

---

## Quick Start

```bash
# Prerequisites: Node.js >=20, pnpm >=10
# From this directory:

pnpm install
cp .env.example .env.local
pnpm dev              # → http://localhost:3001
```

No Zitadel required for local development. The login page automatically shows a **"Dev Login"**
button when `NEXT_PUBLIC_ZITADEL_URL` is not set. Run `make seed` from the repo root first to
populate the demo user and sample data.

For the full backend stack: `make dev` from the repo root starts all services.

---

## Commands

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Dev server at http://localhost:3001 |
| `pnpm build` | Production build (Next.js standalone output) |
| `pnpm start` | Run the production build on :3001 |
| `pnpm test` | Vitest unit tests (single run) |
| `pnpm test:watch` | Vitest interactive mode |
| `pnpm test:coverage` | Coverage report |
| `pnpm test:e2e` | Playwright e2e tests (Chrome + WebKit) |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript strict check |
| `pnpm storybook` | Component catalogue at :6006 |

---

## Key Constraints

- **All API calls go through S9** (`/api/*` → `API_GATEWAY_URL`). Never construct direct backend URLs.
- **shadcn/ui only** — no other component library. `pnpm dlx shadcn@latest add <name>` to add.
- **IBM Plex Mono for ALL numbers** — prices, percentages, quantities, dates in tables.
- **Dark mode only** — `class="dark"` is permanent on `<html>`. No light/dark toggle.
- **pnpm only** — exact versions, `pnpm audit` must show 0 CVEs.

---

## Full Documentation

`docs/apps/worldview-web.md` — complete reference covering all routes, components, API integration,
auth flow, state management, testing, and contributing guidelines.

`docs/ui/DESIGN_SYSTEM.md` — Terminal Dark palette, typography, spacing, UX patterns.
