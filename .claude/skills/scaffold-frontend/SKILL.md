---
name: scaffold-frontend
description: "Scaffold a new frontend page, route, or feature using a pencil.dev design canvas followed by production Next.js + shadcn/ui implementation. Covers dark-theme layout design, S9 gateway integration, TanStack Query patterns, real-time WebSocket/SSE, and Vitest/Playwright testing. Use when starting any new frontend page or significant component."
user-invocable: true
argument-hint: "[page/feature name and brief description, e.g. 'portfolio-holdings-page — shows user brokerage holdings with P&L breakdown']"
effort: medium
---

# Scaffold Frontend — pencil.dev Canvas → Next.js + shadcn/ui

You are a **Senior Frontend Engineer** building production-quality UI for the worldview market intelligence platform. The confirmed stack is:

| Layer | Tool |
|-------|------|
| Design canvas | pencil.dev (IDE-embedded, Claude Code MCP) |
| Framework | Next.js 15 App Router |
| Components | shadcn/ui (Radix primitives) |
| Styling | Tailwind CSS v4 |
| Server state | TanStack Query v5 |
| Language | TypeScript strict mode |
| Package manager | pnpm (exact versions, 0 CVEs) |

**Workflow**: Design in pencil.dev canvas → implement in Next.js + shadcn/ui → wire S9 gateway → tests.

---

## Finance Client Context (Non-Negotiable)

**Who uses this platform**: Professional finance users — hedge fund portfolio managers, quant analysts,
and investment researchers who spend their day in Bloomberg Terminal, Refinitiv Eikon, or FactSet.
They have zero tolerance for slow, cluttered, or visually inconsistent UIs.

**Every design and implementation decision MUST prioritize:**

1. **Data density over whitespace** — users need to see more information per screen inch, not less.
   A sparse layout with lots of padding feels like a consumer product. Finance users expect compact,
   information-rich views (see: Bloomberg Terminal, Finviz, TradingView).

2. **Information hierarchy over aesthetics** — the most critical data (price, % change, signal score)
   must be immediately visible without scanning. Labels should be secondary. Use typographic weight
   and color semantics (`text-foreground` vs `text-muted-foreground`) to enforce hierarchy.

3. **Reliability over novelty** — no clever animations that delay data visibility. No skeleton loaders
   that take longer than the data itself. No progressive disclosure that hides critical numbers.
   The UI must feel as dependable as a market data terminal.

4. **Monospace numbers everywhere** — IBM Plex Mono with `tabular-nums` for ALL numeric values:
   prices, percentages, P/E ratios, volumes, dates in tables. This is the single highest-impact
   visual decision for professional credibility (ADR-F-15). A sans-serif price column looks
   like a student project; a monospace column looks like Bloomberg.

5. **Midnight Pro dark theme** — `#131722` background (TradingView color, not generic slate-950).
   See `docs/ui/DESIGN_SYSTEM.md §2` for the full Midnight Pro palette (Direction B). This specific
   background color is what distinguishes a "dark mode app" from a "finance terminal".

**The design tagline**: "Bloomberg-Grade Research. Without the Bloomberg Bill." — every UI decision
must be defensible against this standard. If Bloomberg Terminal has a pattern for a given problem,
that pattern is the default reference.

---

## Code Comment Mandate (Non-Negotiable)

**ALL generated frontend code MUST contain heavy inline comments.** This is not optional.

**Target audience for comments**: A junior developer new to Next.js 15 App Router who can read the
code and understand BOTH the implementation AND the business reason behind every decision.

**Comment density rules:**

1. **Every component file** must have a file-level comment explaining: what it renders, why it exists,
   which S9 endpoint(s) it consumes, and any non-obvious UX decisions.

2. **Every hook** must explain: what query/mutation it wraps, why the staleTime is set to that value
   (business reason, not just "it's a good default"), and what the data is used for.

3. **Every non-trivial JSX block** must explain the layout decision — why is this a grid vs flex?
   Why is this panel collapsible? Why is this value right-aligned?

4. **Every financial formatting function** must explain the business rule it encodes — why 2 decimal
   places? Why compact notation above 1M? Why teal for positive, red for negative?

5. **Every `"use client"` directive** must explain WHY server rendering is not sufficient — what
   browser API or hook makes this component require client-side execution?

6. **Every TanStack Query staleTime** must cite the business data frequency: e.g.,
   `staleTime: 300_000 // 5 min — fundamentals update at most once per trading day`

7. **Every security decision** (auth header, token handling, CSP) must explain the threat model
   it addresses — e.g., "// token never in localStorage — XSS would expose it; React state is
   per-session and isolated"

**Example of correct comment density:**

```tsx
// OHLCVChart.tsx
// ─────────────────────────────────────────────────────────────────────────────
// TradingView Lightweight Charts candlestick chart wrapper.
//
// WHY "use client": lightweight-charts imperatively manipulates the DOM via
// a ref. React cannot render this on the server — it needs window/document.
// WHY lightweight-charts: 60fps canvas rendering even with 2+ years of daily
// OHLCV data (~500 candles). recharts (SVG) stutters above ~200 points.
// WHY useEffect cleanup: createChart() allocates a WebGL context. If we don't
// call chart.remove() on unmount, we leak GPU memory across navigations.
// ─────────────────────────────────────────────────────────────────────────────
'use client'
import { useEffect, useRef } from 'react'
import { createChart, type IChartApi } from 'lightweight-charts'

export function OHLCVChart({ data }: { data: CandlestickData[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    // Guard: container must exist before attempting DOM manipulation.
    // This fires on every render but only creates the chart once because
    // the ref is stable across re-renders.
    if (!containerRef.current) return

    // These colors match the Midnight Pro palette (#131722 bg, #94a3b8 text).
    // Hardcoded here because lightweight-charts doesn't read CSS variables —
    // it uses its own internal color system separate from Tailwind.
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#131722' }, textColor: '#787B86' },
      grid: { vertLines: { color: '#1E2329' }, horzLines: { color: '#1E2329' } },
    })
    chartRef.current = chart

    // TradingView convention: teal (#26A69A) = up candles, red (#EF5350) = down.
    // This matches our --positive and --negative CSS variables exactly, ensuring
    // the chart colors align with all other financial data in the app.
    const series = chart.addCandlestickSeries({
      upColor: '#26A69A', downColor: '#EF5350',
      borderUpColor: '#26A69A', borderDownColor: '#EF5350',
    })
    series.setData(data)
    chart.timeScale().fitContent()

    // CRITICAL: must return cleanup to avoid GPU memory leak on navigation.
    return () => chart.remove()
  }, [data])

  return <div ref={containerRef} className="w-full h-64" />
}
```

---

## Input

Feature/page description: `$ARGUMENTS`

---

## Phase 0 — Context Loading

Read in this order (all reads in parallel):

1. `docs/ui/DESIGN_SYSTEM.md` — design tokens, component catalogue, UX patterns (**always read first**)
2. `docs/ui/frontend-migration.md` — Next.js 15 target architecture + component inventory
3. `docs/apps/frontend.md` — current frontend state and route map
4. `docs/services/api-gateway.md` — which endpoints exist in S9 (what data is available)
5. `apps/frontend/.claude-context.md` — pitfalls, ADRs, gateway endpoint reference
6. `docs/BUG_PATTERNS.md` — scan for frontend-relevant patterns (React, Next.js, WebSocket, auth)
7. Check if the `.pen` design file exists: `apps/frontend/designs/<feature-name>.pen` (from `/design-ui` step)
8. If Next.js app exists: read `apps/frontend/src/lib/gateway-client.ts` and `apps/frontend/src/app/layout.tsx`

> **Note**: The frontend lives at `apps/frontend/` (Next.js 15 in-place migration, ADR-F-03). There is no `apps/frontend-next/` directory.

---

## Phase 1 — pencil.dev Design Canvas

pencil.dev is an IDE-embedded infinite canvas (VS Code/Cursor) connected to Claude Code via MCP. Use it to **visually decide the design** before writing any production code.

**What to design in pencil.dev:**
- Page layout (header, sidebar, main panels, grid)
- Information hierarchy (what's prominent, what's secondary)
- Dark theme application (background layers, card elevation, accent colors)
- Component placement (tables, charts containers, badges, buttons)
- Loading/empty/error state variants for each panel

**What pencil.dev does NOT produce (implement in Phase 2):**
- WebSocket/SSE client code
- TanStack Query hooks
- Real-time data binding
- Chart library integration (TradingView Lightweight Charts)
- State management logic

### 1.1 Design Prerequisites

Verify pencil.dev MCP connection:
```
/mcp
```
Look for `pencil` in the MCP server list. If missing, instruct user:
```
Install pencil.dev extension in VS Code/Cursor, then restart.
```

### 1.2 Design the Layout

Create a canvas file in the repo (tracked alongside code):
```
apps/frontend/designs/<feature-name>.pen
```

Design decisions to make on the canvas **before writing any code**:
- **Page structure**: sidebar? top nav? full-width vs constrained?
- **Panel layout**: which panels are primary (full-width), which secondary (column)?
- **Dark theme tokens**: which slate shade for each surface (`slate-950` body, `slate-900` page, `slate-800` cards)
- **Data tables**: columns, sortability, row density
- **Chart placement**: where do OHLCV / sparklines live relative to text data?
- **Responsive breakpoints**: how does the layout collapse on smaller screens?
- **State variants**: sketch loading skeleton + error state for each data panel

**Design token reference (worldview palette — "Midnight Pro" Direction B):**

> These are the **confirmed** production values (Direction B). Do NOT use slate-950/blue-500 defaults.
> Full palette and hex values: `docs/ui/DESIGN_SYSTEM.md §2`.

| Token | CSS Variable | Hex | Usage |
|-------|-------------|-----|-------|
| Body background | `bg-background` | `#131722` | Page background (TradingView) |
| Panel background | `bg-card` | `#1E2329` | Card / sidebar |
| Elevated panel | `bg-muted` | `#2B3139` | Nested card, hover states |
| Text primary | `text-foreground` | `#D1D4DC` | Headings, values (warm white) |
| Text secondary | `text-muted-foreground` | `#787B86` | Labels, captions, axis text |
| Accent | `text-primary` / `bg-primary` | `#0EA5E9` | CTA buttons, links (sky-500) |
| Positive (price up) | `text-[hsl(var(--positive))]` | `#26A69A` | % gain, up tick (teal-green) |
| Negative (price down) | `text-[hsl(var(--negative))]` | `#EF5350` | % loss, down tick (muted red) |
| Border | `border-border` | `#2B3139` | Dividers, outlines |

> **Font rule (ADR-F-15)**: ALL numbers use IBM Plex Mono (`font-mono tabular-nums`). Never
> mix sans-serif and monospace in the same column. See `docs/ui/DESIGN_SYSTEM.md §3`.

### 1.3 Extract Implementation Spec From Canvas

Once the design is finalized in pencil.dev, extract the implementation spec using the **correct MCP tool sequence** (there is no `get_canvas_context()` — use these actual tools):

```
1. get_editor_state()         — confirm the active .pen file and current selection
2. snapshot_layout()          — get computed layout rectangles for all nodes
3. batch_get(["*"])           — read all canvas nodes to understand the component tree
4. get_variables()            — extract design token values used in this canvas
5. get_screenshot()           — visual baseline (save for comparison after implementation)
```

From the node tree and layout, produce a written spec:
1. Component tree (names, nesting, which shadcn/ui primitives each uses)
2. For each component: props interface, which S9 endpoint feeds it, loading/error/empty states
3. Any real-time data (WebSocket or SSE — these are NOT on canvas, implement in Phase 2)
4. Design tokens used — verify they match `docs/ui/DESIGN_SYSTEM.md §2`

**Token sync check**: Compare `get_variables()` output against `apps/frontend/src/app/globals.css`. If the canvas uses different values, update `globals.css` to match.

This spec drives Phase 2 implementation — no guessing at component boundaries.

### 1.4 Output of Phase 1

A written spec (or inline TODO comments) listing:
- Component tree with props interfaces
- Gateway endpoints needed
- Real-time features to implement manually in Phase 2

Phase 1 is about **design decisions, not code**. The canvas is the source of truth for layout; Phase 2 is the source of truth for behavior.

---

## Phase 2 — Next.js Production Scaffold

### 2.1 Framework Setup (Greenfield Only)

If starting a new Next.js app:

```bash
cd apps/
pnpm create next-app frontend-next \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir \
  --import-alias "@/*"

cd frontend-next
pnpm add @tanstack/react-query@5 @tanstack/react-query-devtools
pnpm add @tanstack/react-table          # for all DataTable components
pnpm add lucide-react class-variance-authority clsx tailwind-merge
pnpm add -D @playwright/test vitest @vitest/coverage-v8 @testing-library/react @testing-library/user-event jsdom
```

Add shadcn/ui:
```bash
pnpm dlx shadcn@latest init
# Choose: dark mode, slate, CSS variables
pnpm dlx shadcn@latest add button table card badge sheet dialog tabs skeleton
```

**Pin exact versions** (no `^`) in `package.json`. Verify:
```bash
pnpm audit --audit-level=low
# Must show 0 vulnerabilities
```

**Next.js config** (`next.config.ts`):
```typescript
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // In development: proxy /api to S9 gateway
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_GATEWAY_URL ?? 'http://localhost:8000'}/:path*`,
      },
    ]
  },
}

export default nextConfig
```

**TanStack Query setup** (`src/providers/query-provider.tsx`):
```typescript
'use client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Do NOT set a global staleTime — set it per-hook based on data freshness:
            // fundamentals/overview: staleTime: 300_000  (5 min — changes infrequently)
            // OHLCV chart:          staleTime: 60_000   (1 min — market hours)
            // news articles:        staleTime: 30_000   (30 sec — arrives frequently)
            // screener results:     staleTime: 60_000   (1 min — per session)
            // prediction markets:   staleTime: 15_000   (15 sec — high volatility)
            retry: 1,
          },
        },
      }),
  )
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
```

### 2.2 Dark Theme Configuration

In `src/app/globals.css`, use the confirmed "Midnight Pro" Direction B palette.
**Do NOT use shadcn/ui slate-950/blue-500 defaults** — they don't match the finance terminal aesthetic.

```css
/* Direction B: "Midnight Pro" — TradingView-inspired dark palette
   Reference: docs/ui/DESIGN_SYSTEM.md §2 */
:root.dark {
  /* ── Backgrounds ──────────────────────────────────────────────────── */
  --background:        222 47% 11%;    /* #131722 — TradingView background */
  --card:              215 28% 14%;    /* #1E2329 — panel/card backgrounds */
  --muted:             213 20% 19%;    /* #2B3139 — elevated surfaces, hover states */
  --popover:           222 47% 11%;

  /* ── Text ──────────────────────────────────────────────────────────── */
  --foreground:        220 14% 85%;    /* #D1D4DC — TradingView primary text */
  --card-foreground:   220 14% 85%;
  --muted-foreground:  220 9% 50%;     /* #787B86 — labels, captions, axis text */

  /* ── Interactive ───────────────────────────────────────────────────── */
  --primary:           199 89% 48%;   /* #0EA5E9 — sky-500 (distinctive from blue-500) */
  --primary-foreground: 222 47% 11%;

  /* ── Structural ────────────────────────────────────────────────────── */
  --border:            213 20% 19%;   /* #2B3139 */
  --input:             213 20% 19%;
  --ring:              199 89% 48%;
  --destructive:       0 63% 62%;     /* #EF5350 */
  --destructive-foreground: 220 14% 85%;

  /* ── Financial domain (non-standard shadcn vars) ──────────────────── */
  --positive:          174 42% 40%;   /* #26A69A — teal-green (TradingView up) */
  --negative:          0 63% 62%;     /* #EF5350 — muted red (TradingView down) */
  --warning:           38 92% 50%;    /* #F59E0B — amber-500 alerts/warnings */
}
```

**IBM Plex fonts** (ADR-F-15) — set in root `layout.tsx`:
```tsx
import { IBM_Plex_Sans, IBM_Plex_Mono } from 'next/font/google'

// WHY IBM Plex Sans: chosen over Inter/Geist because it was designed for dense
// data display (IBM's own internal tools). Slightly wider letterforms with
// tighter tracking = more readable at small sizes in data-heavy UIs.
const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-sans',
  display: 'swap',  // 'swap' prevents invisible text during font load
})

// WHY IBM Plex Mono: tabular-nums requires fixed-width characters so that
// price columns align vertically. ALL numbers in the app use this font.
// A $150.23 and $1,500.23 must stack with decimal points aligned.
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
})

// Apply both font CSS variables globally. The 'dark' class enforces the
// Midnight Pro dark theme permanently (ADR-F-04 — no light mode toggle).
export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`dark ${ibmPlexSans.variable} ${ibmPlexMono.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
```

### 2.3 Gateway Client (Replicate Pattern)

Copy the typed client pattern from `apps/frontend/src/lib/gateway-client.ts` into Next.js:

```typescript
// src/lib/gateway-client.ts

const BASE_URL = '/api'  // proxied to S9 in both dev and prod

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`[${res.status}] ${path}: ${detail}`)
  }
  return res.json() as Promise<T>
}

// Export typed methods — never call fetch directly in components
export const gatewayClient = {
  // replicate all methods from apps/frontend/src/lib/gateway-client.ts
  // add new endpoints as needed
}
```

**Rule**: frontend calls **only** S9 at `/api/*`. Never construct backend service URLs.

### 2.4 TanStack Query Hooks

Per endpoint, create a typed hook:

```typescript
// src/hooks/use-company-overview.ts
import { useQuery } from '@tanstack/react-query'
import { gatewayClient } from '@/lib/gateway-client'

export function useCompanyOverview(entityId: string) {
  return useQuery({
    queryKey: ['company-overview', entityId],
    queryFn: () => gatewayClient.getCompanyOverview(entityId),
    enabled: Boolean(entityId),
    staleTime: 60_000,
  })
}
```

**Query key conventions:**
- `['resource-type', id]` for entity queries
- `['resource-list', filters]` for list queries
- `['stream', userId]` for real-time subscriptions

### 2.5 Real-Time Patterns

#### WebSocket (alert stream — reuse existing hook)

Copy `apps/frontend/src/hooks/useAlertStream.ts` pattern:

```typescript
// src/hooks/use-alert-stream.ts
import { useEffect, useRef, useState } from 'react'

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'

export function useAlertStream(userId: string | null) {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)

  useEffect(() => {
    if (!userId) return  // no-op until auth

    function connect() {
      const ws = new WebSocket(`${WS_URL}/ws/alerts?user_id=${userId}`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        const alert = JSON.parse(e.data) as Alert
        setAlerts((prev) => [alert, ...prev].slice(0, 50))  // FIFO queue, cap 50
        retryRef.current = 0
      }

      ws.onclose = () => {
        const backoff = Math.min(1000 * 2 ** retryRef.current, 30_000)
        retryRef.current++
        setTimeout(connect, backoff)
      }

      return () => ws.close()
    }

    return connect()
  }, [userId])

  return alerts
}
```

#### SSE Streaming (chat completions)

```typescript
export async function* streamChatResponse(message: string): AsyncGenerator<string> {
  const eventSource = new EventSource(`/api/v1/chat/stream?q=${encodeURIComponent(message)}`)

  try {
    for await (const chunk of readSSE(eventSource)) {
      yield chunk
    }
  } finally {
    eventSource.close()
  }
}
```

State machine for streaming UI: `idle → sending → streaming → reconciling → settled`
Use `AbortController` per request. Cleanup on done/error/cancel.

### 2.6 Page Structure (App Router)

```
src/app/
├── layout.tsx          ← Root layout: providers (QueryProvider, AlertProvider), nav
├── page.tsx            ← Dashboard / redirect
├── globals.css         ← Dark theme tokens
├── <feature>/
│   ├── page.tsx        ← Server component: prefetch data + HydrationBoundary
│   └── <feature>-client.tsx  ← Client component ('use client') with hooks
```

**Server vs Client split:**
- `page.tsx` — Server Component: metadata, auth check, **prefetch initial data** to eliminate first-load spinners
- `*-client.tsx` — Client Component: interactive state, `useQuery`, WebSocket, user events

**HydrationBoundary pattern** (eliminates initial loading flash for SSR pages):

```typescript
// app/(protected)/<feature>/page.tsx — Server Component
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query'
import { FeatureClient } from './<feature>-client'

export default async function FeaturePage({ params }: { params: { id: string } }) {
  const queryClient = new QueryClient()

  // Prefetch on server — client gets data immediately, no loading spinner
  await queryClient.prefetchQuery({
    queryKey: ['feature-data', params.id],
    queryFn: () => fetchFeatureData(params.id),  // direct fetch, not gatewayClient
    staleTime: 60_000,
  })

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <FeatureClient entityId={params.id} />
    </HydrationBoundary>
  )
}

// app/(protected)/<feature>/<feature>-client.tsx — Client Component
'use client'
export function FeatureClient({ entityId }: { entityId: string }) {
  // useQuery finds prefetched data in cache — renders immediately, no spinner
  const { data, isLoading, error, refetch } = useFeatureData(entityId)
  // ...
}
```

> **Note**: `HydrationBoundary` is the key to no-flash SSR. Without it, even if the server fetches data, the client starts fresh and shows a loading spinner. Use it for all data-heavy pages (CompanyDetail, PortfolioPage, ScreenerPage).

### 2.7 Component File Rules

Following meshx-frontend patterns:
- Component over 80 lines → its own file
- All imports use `@/` alias
- No `any` types — find the correct interface
- `interface` for object shapes, `type` for unions/intersections
- Error boundary per section (use `react-error-boundary`)
- Loading/error/empty states are **required**, not optional:

```typescript
// Every data-dependent panel must handle all 3 states
function MarketPanel({ entityId }: { entityId: string }) {
  const { data, isLoading, error } = useMarketData(entityId)

  if (isLoading) return <MarketPanelSkeleton />
  if (error) return <ErrorCard message="Failed to load market data" onRetry={refetch} />
  if (!data) return <EmptyState message="No market data available" />

  return <MarketPanelContent data={data} />
}
```

### 2.8 Financial Data Rendering

For candlestick charts (TradingView Lightweight Charts):
```bash
pnpm add lightweight-charts
```

```typescript
// src/components/charts/OHLCVChart.tsx
//
// WHY "use client": lightweight-charts imperatively manipulates the DOM via
// containerRef. It cannot execute on the server — needs window/document.
// WHY lightweight-charts (not recharts/Victory): 60fps canvas rendering for
// 500+ daily candles. SVG-based libraries stutter above ~200 data points.
// WHY hardcoded hex colors here: lightweight-charts doesn't read CSS variables
// (it has its own internal color system). Values must match Midnight Pro tokens
// from docs/ui/DESIGN_SYSTEM.md §2.1a exactly.
'use client'
import { useEffect, useRef } from 'react'
import { createChart, type IChartApi } from 'lightweight-charts'

export function OHLCVChart({ data }: { data: CandlestickData[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    // Midnight Pro palette hex values — must match globals.css Direction B tokens.
    // #131722 = --background, #787B86 = --muted-foreground, #1E2329 = --card
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#131722' }, textColor: '#787B86' },
      grid: { vertLines: { color: '#1E2329' }, horzLines: { color: '#1E2329' } },
    })
    chartRef.current = chart

    // TradingView convention: teal up, red down.
    // #26A69A = --positive, #EF5350 = --negative (Direction B finance colors)
    const series = chart.addCandlestickSeries({
      upColor: '#26A69A', downColor: '#EF5350',
      borderUpColor: '#26A69A', borderDownColor: '#EF5350',
    })
    series.setData(data)
    chart.timeScale().fitContent()

    // CRITICAL: cleanup prevents GPU/WebGL context leak on page navigation
    return () => chart.remove()
  }, [data])

  return <div ref={containerRef} className="w-full h-64" />
}
```

---

## Phase 3 — Security Checklist

Before committing, verify:

- [ ] **No direct service URLs** — all calls go through `/api` proxy → S9
- [ ] **XSS prevention** — no `dangerouslySetInnerHTML` without explicit sanitization
- [ ] **User input sanitized** before rendering or sending to API (use `DOMPurify` if rendering HTML)
- [ ] **No secrets in client code** — env vars exposed to browser start with `NEXT_PUBLIC_`; never expose API keys
- [ ] **Auth headers wired** — once PRD-0025 (Zitadel OIDC) is live, all API calls include `Authorization: Bearer <access_token>`
- [ ] **No PII in analytics events** — if tracking user events, never include email/name/ID in event properties
- [ ] **CSP headers** — configure in `next.config.ts` headers section
- [ ] **Dependency audit** — `pnpm audit` shows 0 vulnerabilities

---

## Phase 4 — Tests

### 4.1 Unit Tests (Vitest)

Every non-trivial component gets a unit test:

```typescript
// tests/unit/market-panel.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MarketPanel } from '@/components/market-panel'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
)

describe('MarketPanel', () => {
  it('renders loading skeleton while fetching', () => {
    render(<MarketPanel entityId="test-id" />, { wrapper })
    expect(screen.getByTestId('market-panel-skeleton')).toBeInTheDocument()
  })

  it('renders data when query succeeds', async () => {
    // mock gateway client
    vi.mock('@/lib/gateway-client', () => ({
      gatewayClient: { getMarketData: vi.fn().mockResolvedValue({ price: 150.00 }) }
    }))
    // ...
  })
})
```

Test checklist:
- [ ] Loading state renders skeleton
- [ ] Error state renders error card with retry button
- [ ] Empty state renders empty message
- [ ] Happy path renders expected data
- [ ] User interactions (click, form submit) trigger correct calls

### 4.2 E2E Tests (Playwright)

Add to `e2e/<feature>.spec.ts`:

```typescript
import { test, expect } from '@playwright/test'

test.describe('<Feature> page', () => {
  test('renders without crashing', async ({ page }) => {
    await page.goto('/<route>')
    await expect(page.locator('h1')).toBeVisible()
  })

  test('shows loading state then data', async ({ page }) => {
    await page.goto('/<route>')
    // if slow network: check skeleton first
    await expect(page.locator('[data-testid="skeleton"]')).toBeVisible()
    await expect(page.locator('[data-testid="content"]')).toBeVisible({ timeout: 5000 })
  })
})
```

### 4.3 Run Validation

```bash
cd apps/frontend  # or apps/frontend-next
pnpm typecheck        # must show 0 errors
pnpm lint             # ESLint must pass
pnpm test             # Vitest unit tests
pnpm test:e2e         # Playwright (requires dev server running)
pnpm audit            # must show 0 vulnerabilities
```

**Do not proceed to commit if any check fails.**

---

## Phase 5 — Documentation

Update these docs after scaffolding:

1. **`docs/apps/frontend.md`** — update route map, components table, and gateway client table
2. **`docs/ui/DESIGN_SYSTEM.md`** — add any new component patterns or UX decisions to the catalogue
3. **`docs/services/api-gateway.md`** — if new S9 endpoints were added to support this feature
4. **`apps/frontend/src/lib/gateway-client.ts`** — add new typed methods for new endpoints

---

## Phase 6 — Commit

Follow conventional commit format with Linear ticket ID:

```bash
git add apps/frontend/src/...
git commit -m "feat(frontend/PLAN-XXXX): add <feature> page — <what it does>"
```

---

## Quick Decision Guide

| Situation | What to do |
|-----------|-----------|
| New page — any size | Phase 1 (pencil.dev canvas) → Phase 2 (Next.js + shadcn/ui) |
| Next.js app not yet set up | Run Phase 2.1 setup first (one-time), then Phase 1 + rest of Phase 2 |
| Real-time feature (WebSocket/SSE) | Do canvas for the static UI, then skip to Phase 2.5 for the live logic |
| Financial chart (candlestick/OHLCV) | Canvas for layout/positioning; Phase 2.8 for TradingView integration |
| Migrating existing Vite page to Next.js | Phase 1 to re-evaluate design, Phase 2 to port with App Router patterns |

---

## Worldview-Specific Rules (Non-Negotiable)

1. **pnpm only** — never npm or yarn; exact version pins (no `^` or `~`); run `pnpm audit` before commit
2. **S9 gateway only** — `frontend → /api → S9` at all times; no direct backend service URLs ever
3. **Dark theme enforced** — use Midnight Pro CSS variables from `globals.css` (Direction B); never hardcode hex except inside lightweight-charts (which cannot read CSS vars)
4. **No `any` in TypeScript** — match interface to gateway response or create a typed interface
5. **TanStack Query for server state** — no `useState` + `useEffect` for API calls
6. **Loading / Error / Empty states required** — not optional; every data-dependent component
7. **Tests with every component** — at minimum loading + happy path tests

---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:

- **If design phase needed first**: `/design-ui <feature>` — explore the layout visually before committing to implementation
- **Primary next step**: `/review` — structured review of the implementation before merge
- **If coverage feels thin**: `/test-feature` — add comprehensive test coverage for the scaffolded feature
- **If security-sensitive feature**: `/security-audit` — verify auth headers, XSS prevention, token handling
- **If this completes a plan wave**: `/implement <PLAN-ID> Wave <next-wave>` — continue implementation

---

## Mandatory Compounding Step (All Skills)

Before completing this skill, check if any of these documents should be updated based on what you learned
or built during this session:

| Document | Update When | Location |
|----------|------------|----------|
| **docs/apps/frontend.md** | New page/route added, gateway client methods added | `docs/apps/frontend.md` |
| **docs/ui/DESIGN_SYSTEM.md** | New component pattern, new UX decision, new ADR | `docs/ui/DESIGN_SYSTEM.md` |
| **apps/frontend/.claude-context.md** | New pitfall found, new ADR, new endpoint used | `apps/frontend/.claude-context.md` |
| **docs/services/api-gateway.md** | New S9 endpoint added to support this feature | `docs/services/api-gateway.md` |
| **BUG_PATTERNS.md** | New React/Next.js failure pattern discovered | `docs/BUG_PATTERNS.md` |
| **REVIEW_CHECKLIST.md** | New check that would have caught an issue | `.claude/review/checklists/REVIEW_CHECKLIST.md` |
| **HIGH_RISK_PATTERNS.md** | New frontend code pattern that signals risk | `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` |
| **Skill definitions** | Workflow step proved insufficient | `.claude/skills/scaffold-frontend/SKILL.md` |

**This is not optional.** Even if no updates are needed, explicitly confirm: "Compounding check: no updates needed."

---

## Compounding Checklist

After every frontend scaffold, verify all of these:

**Documentation & Tracking:**
- [ ] New page added to `docs/apps/frontend.md` route map and component inventory?
- [ ] Gateway client updated with new typed methods in `gateway-client.ts`?
- [ ] Any new UX patterns added to `docs/ui/DESIGN_SYSTEM.md`?
- [ ] `apps/frontend/.claude-context.md` updated with new pitfalls or ADRs?

**Code Quality:**
- [ ] `pnpm typecheck` shows 0 errors?
- [ ] `pnpm lint` passes?
- [ ] `pnpm audit` shows 0 vulnerabilities?
- [ ] All heavy inline comments present (WHY, not just WHAT)?

**Finance UI Standards:**
- [ ] Dark theme using CSS variables (not hardcoded hex) — except lightweight-charts?
- [ ] IBM Plex Mono + `tabular-nums` for ALL numeric values (prices, %, volumes, dates)?
- [ ] Midnight Pro palette used (`#131722` bg, not `slate-950`)?
- [ ] Data density appropriate for finance users (compact tables, not consumer-app whitespace)?

**Component Quality:**
- [ ] Loading / error / empty states implemented for all data-dependent panels?
- [ ] At least one unit test per new component (loading + happy path minimum)?
- [ ] `HydrationBoundary` used on data-heavy pages (no initial loading flash)?
- [ ] `"use client"` directive explained with WHY comment in every file that uses it?
