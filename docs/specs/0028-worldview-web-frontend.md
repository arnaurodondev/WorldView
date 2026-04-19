# PRD-0028 — Worldview Web: Standalone Frontend Application

> **Status**: Draft — 2026-04-17
> **Author**: Arnau Rodon
> **Replaces**: PRD-0027 (frontend design remains valid as canvas reference; this PRD supersedes the implementation direction)
> **Depends on**: PRD-0025 (auth foundation — complete), PRD-0026 (news intelligence APIs — draft)
> **New service location**: `apps/worldview-web/` (standalone, not in-place migration)
> **Next**: `/plan` → implementation waves F-1..F-12

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Target Users & Journeys](#2-target-users--journeys)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Out of Scope](#5-out-of-scope)
6. [Technical Design](#6-technical-design)
   - [6.1 Affected Services](#61-affected-services)
   - [6.2 S9 API Routes Consumed](#62-s9-api-routes-consumed)
   - [6.3 Kafka Events](#63-kafka-events)
   - [6.4 Frontend App Structure](#64-frontend-app-structure)
   - [6.5 Pages & Components](#65-pages--components)
   - [6.6 Data Flows](#66-data-flows)
7. [Architecture Decisions](#7-architecture-decisions)
8. [Security Design](#8-security-design)
9. [Failure Modes & Recovery](#9-failure-modes--recovery)
10. [Scalability & Performance](#10-scalability--performance)
11. [Test Strategy](#11-test-strategy)
12. [Migration Strategy](#12-migration-strategy)
13. [Observability](#13-observability)
14. [Open Questions](#14-open-questions)
15. [Estimation](#15-estimation)

---

## 1. Problem Statement

### 1.1 The Market Gap

The financial intelligence platform market has four distinct tiers:

| Platform | Price | Strengths | Fatal Gaps |
|----------|-------|-----------|-----------|
| **Bloomberg Terminal** | $32,000/yr | Comprehensive, real-time | Dated UX, inaccessible pricing, no AI copilot |
| **Koyfin** | $0–299/yr | Strong fundamentals UI | No AI, no entity graphs, no prediction markets |
| **Finviz** | $0–39.99/mo | Powerful screener, heat maps | No AI, no knowledge graph, shallow fundamentals |
| **TradingView Pro** | $0–59/mo | Excellent charts | No AI research copilot, no entity graph |

The **professional mid-market** has no platform combining: modern AI-native UX + deep fundamentals + news intelligence + entity knowledge graphs + prediction markets + configurable workspace at an affordable price point.

### 1.2 Worldview's Differentiation

Worldview has already built the backend intelligence layer: 10 microservices delivering fundamentals, NLP-scored news, entity knowledge graphs, prediction market integration, RAG chat, and real-time alert streaming. The frontend must surface ALL of this capability in a professional, information-dense interface.

**Design target**: Bloomberg depth × TradingView UX × ZeroTerminal AI integration × Finviz data density — at $29/month.

### 1.3 Why a New Service Directory

PRD-0027 targeted an in-place migration of `apps/frontend/` (Vite → Next.js). This created risk: the development environment breaks mid-migration, the Docker Compose setup becomes unstable, and rollback is destructive.

PRD-0028 creates `apps/worldview-web/` as a clean-slate Next.js service. The old `apps/frontend/` continues to run unchanged during development. Once `worldview-web` reaches feature parity, `apps/frontend/` is deprecated. This gives:
- Zero-risk parallel development
- Clean git history (new service in a new directory)
- Simpler Docker Compose diff (add one entry, later remove one entry)

---

## 2. Target Users & Journeys

| Segment | Key Journeys | Primary Pages |
|---------|-------------|---------------|
| **Retail Investors** | Dashboard → monitor portfolio, check AI brief, browse watchlist | Dashboard, Portfolio, Instrument Detail |
| **Research Analysts** | Screener → deep-dive companies, read news, run chat queries | Screener, Instrument Detail (Fundamentals + Intelligence tabs), Chat |
| **Quant Traders** | Market pulse → screener → watchlist → alerts | Dashboard, Screener, Workspace |
| **Thesis Evaluators** | Complete product walkthrough | All pages |

### Core User Flows

| Flow | Entry | Steps | Exit |
|------|-------|-------|------|
| F1: Discovery | Landing page | Scroll hero → see features → click CTA | Login |
| F2: Login | `/login` | Click "Log in" → Zitadel OIDC → callback → `/dashboard` | Dashboard |
| F3: Morning brief | Dashboard | Auto-load brief → read AI summary → click entity link | Instrument Detail |
| F4: Instrument research | Search or screener | Detail page → Fundamentals tab → Intelligence tab → Chat | Chat or back |
| F5: Portfolio review | Dashboard or `/portfolio` | See total P&L → click holding → instrument detail | Instrument Detail |
| F6: Alert response | Bell or `/alerts` | Read alert → click entity → open instrument detail | Instrument Detail |
| F7: Chat research | `/chat` or Ask AI button | Type question → stream response → follow citations | Instrument Detail |

---

## 3. Functional Requirements

### 3.1 Must-Have (MVP)

| ID | Requirement |
|----|-------------|
| FR-01 | Public landing page with feature highlights, pricing, and CTA |
| FR-02 | OIDC login via Zitadel; silent refresh on app mount; httpOnly cookie for refresh token |
| FR-03 | Persistent authenticated shell: sidebar + top bar across all protected pages |
| FR-04 | Dashboard page: morning brief, portfolio summary, market heatmap, top movers, watchlist news, economic calendar, recent alerts, AI signals, prediction markets top bets |
| FR-05 | Top bar: platform name, global instrument search, index prices (SPY/QQQ/VIX/BTC), UTC clock, markets-open status pill, Ask AI mini-chat, alerts bell, user profile menu |
| FR-06 | Sidebar: nav links, active watchlist with name + switch button, recent alarms list, settings + help at bottom |
| FR-07 | Instrument detail page: OHLCV chart, news tab, fundamentals tab, intelligence tab (entity graph + AI brief) |
| FR-08 | Screener page: dynamic filter form, paginated results table |
| FR-09 | Portfolio page: total value, today P&L, unrealised P&L, top holdings, 5D/5W chart, add transaction |
| FR-10 | Workspace page: drag-and-drop multi-panel terminal, panel types: Chart, News, Alerts, Chat, Watchlist, Screener, Graph, Briefing |
| FR-11 | Alerts & News page: paginated alert list, news feed tabs (Feed / Top Today) |
| FR-12 | Intelligence / Chat page: thread sidebar, RAG streaming chat with citations, morning brief panel |
| FR-13 | Settings page: profile info, notification preferences, appearance |
| FR-14 | Markets-open status widget: green pill ("Markets Open") or red pill ("Markets Closed"), hover → per-exchange UTC schedule dropdown |
| FR-15 | Real-time alert WebSocket stream; CRITICAL alerts shown in FlashOverlay (full-screen, 12s auto-dismiss, Escape) |
| FR-16 | Ask AI mini-chat: floating window with send + "Open full chat" link to `/chat` |

### 3.2 Nice-to-Have (Post-MVP)

| ID | Requirement |
|----|-------------|
| NF-01 | Dark/Light theme toggle (PRD-0027 deferred: dark only for now) |
| NF-02 | Multi-language support |
| NF-03 | Mobile-responsive layout (tablet breakpoints in MVP; phone-first deferred) |
| NF-04 | Export to CSV from screener/portfolio |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Initial page load | < 2.5s LCP on fast 3G |
| API-driven interactions | < 200ms p95 for data panels after page mount |
| Bundle size | Main bundle < 250KB gzipped; page code-split |
| Auth session | 15-min access token; silent refresh on expiry; no re-login needed |
| Accessibility | WCAG 2.1 AA minimum (keyboard nav, aria labels, focus rings) |
| Browser support | Chrome 120+, Firefox 120+, Safari 17+ |
| Dark theme | Permanent; no toggle for MVP |

---

## 5. Out of Scope (PRD-0028)

- Mobile-native app (React Native / Expo)
- Light mode
- Server-side data pre-fetching for protected pages (client-side only via TanStack Query)
- Internationalisation (i18n)
- Custom domain or white-labelling
- In-app notifications beyond alerts (no push notifications)
- Brokerage order execution (read-only portfolio from PLAN-0022)
- The old `apps/frontend/` Vite app — it is NOT modified by this PRD

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change | Why |
|---------|--------|-----|
| **S9 API Gateway** | Consumes existing endpoints; no new backend code required for MVP | Frontend talks only to S9 |
| **S1 User** | No change — OIDC handled by Zitadel + S9 | Auth flow already built (PRD-0025) |
| **`apps/worldview-web/`** | New service — create from scratch | This is the primary deliverable |
| **`apps/frontend/`** | No change — runs in parallel until deprecated | Parallel dev strategy |
| **`infra/docker-compose.yml`** | Add `worldview-web` service entry (port 3001 in dev) | New service needs compose entry |

**Backend services are not modified by this PRD.** PRD-0028 is purely a frontend application that consumes S9 via the existing API surface.

### 6.2 S9 API Routes Consumed

All routes go through `apps/worldview-web`'s `next.config.ts` rewrite: `/api/* → API_GATEWAY_URL/*`. The frontend never constructs backend URLs directly.

#### Auth Routes

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `GET` | `/v1/auth/login` | Redirect to Zitadel OIDC (S9 handles PKCE) | None |
| `GET` | `/v1/auth/register` | Redirect to Zitadel self-registration page | None |
| `GET` | `/v1/auth/callback` | Exchange code+state for tokens | None |
| `POST` | `/v1/auth/refresh` | Silent token refresh via httpOnly cookie | Cookie |
| `POST` | `/v1/auth/logout` | Revoke refresh token + clear cookie | Cookie |
| `GET` | `/v1/auth/ws-token` | Issue 30s short-lived internal JWT for WebSocket auth | Bearer |

**`GET /v1/auth/ws-token` response**:
```ts
{ token: string; expires_in: 30 }
```
Called by `useAlertStream` immediately before opening the WebSocket connection. The returned `token` is a signed RS256 internal JWT (same key as `X-Internal-JWT`) scoped only for `alerts:stream`. S10's `InternalJWTMiddleware` accepts this token from `?token=` query param for WebSocket upgrade requests (detected via `Upgrade: websocket` header).

#### Dashboard Routes

| Method | Path | Purpose | Cache TTL |
|--------|------|---------|-----------|
| `GET` | `/v1/briefings/morning` | Morning AI brief for current user | 24h (Valkey) |
| `POST` | `/v1/quotes/batch` | Index prices for top bar (SPY/QQQ/VIX/BTC) | 5s |
| `GET` | `/v1/alerts/pending?limit=5` | Recent alerts for sidebar | No cache |
| `GET` | `/v1/signals/prediction-markets?limit=5` | Top prediction market bets | 60s |
| `GET` | `/v1/news/top?hours=48&limit=10` | Watchlist news panel | 60s |
| `GET` | `/v1/fundamentals/economic-calendar` | Economic events this week | 1h |

#### Watchlist Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/watchlists` | List user's watchlists |
| `POST` | `/v1/watchlists` | Create new watchlist |
| `GET` | `/v1/watchlists/:id` | Get watchlist with members |
| `PATCH` | `/v1/watchlists/:id` | Rename watchlist |
| `DELETE` | `/v1/watchlists/:id` | Delete watchlist |
| `POST` | `/v1/watchlists/:id/members` | Add instrument to watchlist |
| `DELETE` | `/v1/watchlists/:id/members/:entityId` | Remove from watchlist |

#### Instrument / Market Data Routes

| Method | Path | Purpose | Notes |
|--------|------|---------|-------|
| `GET` | `/v1/companies/:id/overview` | Company summary + OHLCV + news | Composite response |
| `GET` | `/v1/ohlcv/:id?timeframe=1D&start=&end=` | OHLCV bars | Used by chart |
| `GET` | `/v1/quotes/:id` | Live quote (5s cache) | Top bar + instrument header |
| `POST` | `/v1/quotes/batch` | Batch quotes for portfolio/watchlist | Body: `{ ids: string[] }` |
| `GET` | `/v1/fundamentals/:id` | Full fundamentals (all sections) | Instrument detail fundamentals tab |
| `GET` | `/v1/fundamentals/:id/:section` | Single fundamentals section | Optional subsection fetch |
| `GET` | `/v1/entities/:id/graph?depth=2` | Knowledge graph egocentric view | Intelligence tab |
| `GET` | `/v1/entities/:id/contradictions` | Entity contradiction analysis | Intelligence tab |
| `GET` | `/v1/briefings/instrument/:id` | Per-instrument AI brief | 24h Valkey cache |
| `POST` | `/v1/entities/similar` | Similar companies | Body: `{ entity_id, limit }` |

#### News Routes

| Method | Path | Purpose | Notes |
|--------|------|---------|-------|
| `GET` | `/v1/news/relevant?limit=20` | News feed (general relevance) | Feed tab |
| `GET` | `/v1/news/top?hours=48&limit=20&offset=0` | Ranked news feed | Top Today tab |
| `GET` | `/v1/news/entity/:entityId?start_date=&end_date=&order_by=display_relevance_score&limit=20` | Entity-linked scored news | Instrument news tab |

#### Screener Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/fundamentals/screen/fields` | Available filter fields |
| `POST` | `/v1/fundamentals/screen` | Run screener query |

**POST /v1/fundamentals/screen request body:**
```ts
{
  filters: Array<{ field: string; operator: string; value: number | string }>;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;   // default 20, max 100
  offset?: number;  // default 0
}
```

#### Portfolio Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/portfolios` | List user's portfolios |
| `GET` | `/v1/holdings/:portfolioId` | Holdings for portfolio |
| `GET` | `/v1/transactions?portfolio_id=&limit=&offset=` | Transaction history |
| `POST` | `/v1/transactions` | Add transaction (buy/sell) |
| `GET` | `/v1/quotes/batch` | Live prices for holdings |

#### Alert Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/alerts/pending?limit=50&offset=0` | Paginated alert list |
| `DELETE` | `/v1/alerts/:id/ack` | Acknowledge/dismiss alert |
| `WS` | `/v1/alerts/stream?token=<ws_token>` | Real-time alert WebSocket (direct to S10:8010) |

> **WS auth**: `ws_token` is the short-lived JWT from `GET /v1/auth/ws-token` (30s TTL). The frontend calls that endpoint immediately before opening the connection. S10's `InternalJWTMiddleware` reads `?token=` for WebSocket upgrades (detected via `Upgrade: websocket` request header). `NEXT_PUBLIC_WS_BASE_URL` must point to S10 directly (`ws://localhost:8010` in dev) — Next.js rewrites do **not** proxy WebSocket upgrades (ADR-F-02).

#### Chat Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/threads` | User's chat thread list |
| `POST` | `/v1/threads` | Create new thread |
| `GET` | `/v1/threads/:id` | Thread with messages |
| `DELETE` | `/v1/threads/:id` | Delete thread |
| `POST` | `/v1/chat/stream` | SSE streaming response (HTTP streaming, **not** EventSource) |

**`POST /v1/chat/stream` request body**:
```ts
{ question: string; thread_id: string; }
```
**`POST /v1/chat/stream` streaming protocol**: The response is `Content-Type: text/event-stream`. Each chunk is a plain text token. The final chunk is the literal string `[DONE]`. The frontend reads chunks via `response.body.getReader()` (Fetch API `ReadableStream`). The Authorization Bearer token goes in the request header — **not** in the URL (no EventSource; `fetch()` with POST supports headers).

> **Why `fetch` + POST, not EventSource**: `EventSource` is GET-only and cannot send a request body with the question. `fetch()` with `ReadableStream` is the correct approach for POST-based SSE. This also avoids token exposure in the URL.

#### Search Route

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/search/instruments?q=&limit=10` | Global instrument search for top bar |

### 6.3 Kafka Events

**None.** The frontend application produces no Kafka events. It consumes data exclusively through the S9 REST/WebSocket/SSE API. This is a pure read/write client.

---

### 6.5 Pages & Components

#### Page: Landing (`/`)

**Auth**: Public (no redirect)

**Layout**: Full-width, no sidebar, no top bar

**Sections** (top to bottom):
1. **Nav bar** — logo left, "Log in" + "Get started" buttons right. Buttons use `next/link` `<Link>` (ADR-F-20).
2. **Hero** — headline ("The Intelligence Terminal for Modern Investors"), subheadline, CTA button "Get started free", screenshot/mockup. The mockup image MUST use `next/image` `<Image priority>` (ADR-F-20 — it is the LCP element; `priority` disables lazy loading to avoid LCP penalty).
3. **Feature comparison** — 3-column comparison table: Worldview vs Bloomberg vs TradingView
4. **Feature highlights** — 6 cards: AI Copilot, Entity Graph, News Intelligence, Prediction Markets, Configurable Terminal, Daily Briefs
5. **Pricing** — 3 tiers: Free (limited), Pro ($29/mo), Enterprise (contact)
6. **Trust bar** — "Built on EODHD data · Powered by local LLMs · Open architecture"
7. **FAQ** — 5 common questions collapsible
8. **Footer** — links, copyright. External links (privacy, terms) use `<a target="_blank" rel="noopener noreferrer">`.

**Implementation rules (ADR-F-20)**:
- All `<img>` tags → `next/image` `<Image>` (automatic WebP, `srcset`, layout-shift prevention)
- All internal navigation → `next/link` `<Link>` (prefetching); `<a>` only for external URLs
- Pure Server Components throughout (no `"use client"`) except the FAQ accordion (needs `useState`)

---

#### Page: Login (`/login`)

**Auth**: Public; redirect to `/dashboard` if already authenticated

**Components**: Single "Log in to Worldview" button
**On click**: `window.location.href = "/api/v1/auth/login"` (S9 issues 302 to Zitadel)
**Note**: No username/password form. Full OIDC redirect flow.

---

#### Page: Register (`/register`)

**Auth**: Public; redirect to `/dashboard` if already authenticated

**Components**: "Create account" button + link back to login
**On click**: `window.location.href = "/api/v1/auth/register"` (S9 redirects to Zitadel self-registration)

---

#### Page: Callback (`/callback`)

**Auth**: Public

**On mount**:
1. Read `?code=` and `?state=` from `useSearchParams()`
2. `GET /api/v1/auth/callback?code=&state=`
3. On 200: `setAccessToken(data.access_token, data.user)` → `router.push("/dashboard")`
4. On error: show error message + "Back to login" link

---

#### Shell: Protected Layout (`app/(app)/layout.tsx`)

**Auth**: Required — redirects to `/login` if not authenticated

**Structure**:
```
┌──────────────────────────────────────────────────────────────────┐
│  TopBar (fixed top, full width, h-12)                            │
├──────────────┬───────────────────────────────────────────────────┤
│  Sidebar     │  <page content>                                   │
│  (fixed      │  (scrollable, padding-top for TopBar height)      │
│  left,       │                                                   │
│  w-56)       │                                                   │
└──────────────┴───────────────────────────────────────────────────┘
```

---

#### Component: TopBar

**"use client"** — reads auth, renders clocks, handles search

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  [W] Worldview  [🔍 Search instruments...]  [SPY +0.23%] [QQQ -0.12%] [VIX 18.4] [BTC +1.2%]  │
│                 [🕐 14:32:08 UTC] [● Markets Open ▾]  [Ask AI ▾]  [🔔 3]  [👤 Menu]     │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**Sub-components**:

| Sub-component | Description |
|---|---|
| Logo | Platform name "Worldview" (or configurable `NEXT_PUBLIC_APP_NAME`) linking to `/dashboard` |
| `GlobalSearch` | cmdk-powered combobox; `GET /v1/search/instruments?q=&limit=10`; on select → `router.push("/instruments/:id")` |
| `IndexTicker` | 4 tickers: SPY, QQQ, VIX, BTC; `POST /v1/quotes/batch`; refetch every 15s; each shows symbol + price (font-mono) + % change (colored) |
| `UtcClock` | Client-side UTC time, updated every second via `setInterval`; format: `HH:MM:SS UTC` |
| `MarketStatusPill` | See §6.5.1 below |
| `AskAiButton` | Toggles `AskAiPanel` floating window |
| `AlertBell` | Bell icon with unread count badge; click → `/alerts`; count from `AlertStreamContext.recentAlerts.length` |
| User avatar menu | Avatar (initials if no picture); dropdown: Profile, Settings, Sign out |

##### 6.5.1 MarketStatusPill — Detailed Specification

**Component**: `src/components/shell/MarketStatusPill.tsx` — `"use client"`

**Display states**:
- Green pill: `● Markets Open` — when any primary equity market is in regular trading session
- Red pill: `● Markets Closed` — when all primary equity markets are outside regular hours
- Amber pill: `◐ Pre/After-Hours` — when US equity is in pre-market or after-hours only

**On hover/click**: `Popover` opens showing per-exchange table

**Exchange schedule** (defined in `src/lib/market-schedule.ts`):

| Exchange | Markets | UTC Open | UTC Close | Days | Notes |
|----------|---------|----------|-----------|------|-------|
| NYSE / NASDAQ | US Equities | 14:30 | 21:00 | Mon–Fri | Pre-market: 10:00–14:30; After-hours: 21:00–00:00 |
| LSE | UK Equities | 08:00 | 16:30 | Mon–Fri | |
| TSE | Japan Equities | 00:00 | 06:00 | Mon–Fri | Lunch break 02:30–03:30 |
| HKEX | HK Equities | 01:30 | 08:00 | Mon–Fri | Lunch break 04:00–05:00 |
| Euronext | EU Equities | 08:00 | 16:30 | Mon–Fri | Approximate |
| CME Futures | Futures | 23:00 (Sun) | 22:00 (Fri) | Sun–Fri | Nearly continuous |
| FOREX | FX | 22:00 (Sun) | 22:00 (Fri) | Sun–Fri | 24/5 |
| Crypto | Crypto | 00:00 | 23:59 | Every day | 24/7 |

**Hover dropdown layout**:
```
┌──────────────────────────────────────────────┐
│  Exchange           Status       Hours (UTC)  │
│  ─────────────────────────────────────────── │
│  NYSE / NASDAQ    ● OPEN       14:30 – 21:00  │
│  LSE              ● CLOSED     08:00 – 16:30  │
│  TSE              ● CLOSED     00:00 – 06:00  │
│  HKEX             ● CLOSED     01:30 – 08:00  │
│  Euronext         ● CLOSED     08:00 – 16:30  │
│  CME Futures      ● OPEN       Sun 23:00 – Fri│
│  FOREX            ● OPEN       24/5           │
│  Crypto           ● OPEN       24/7           │
│                                               │
│  Current UTC: 14:32 · Thu 2026-04-17          │
└──────────────────────────────────────────────┘
```

**Implementation** (`src/lib/market-schedule.ts`):
```ts
export interface ExchangeStatus {
  name: string;
  status: "open" | "closed" | "pre-market" | "after-hours";
  utcOpen: string;   // "HH:MM"
  utcClose: string;  // "HH:MM"
  days: string;      // "Mon–Fri" | "24/7" | "Sun–Fri"
}

// Pure function — no API calls. Called every minute via setInterval in useMarketStatus hook.
export function computeMarketStatus(utcNow: Date): {
  overall: "open" | "closed" | "pre-after-hours";
  exchanges: ExchangeStatus[];
}

// Rules for overall status:
// "open" → NYSE/NASDAQ, LSE, TSE, HKEX, or Euronext is in regular session
// "pre-after-hours" → NYSE/NASDAQ is in pre-market or after-hours (but no other regular market open)
// "closed" → no equity market in regular session
```

**Hook** (`src/hooks/useMarketStatus.ts`):
```ts
"use client"
export function useMarketStatus(): ReturnType<typeof computeMarketStatus> {
  // Re-computes every 60 seconds (minute boundary is sufficient)
  // Uses Date.now() in UTC — browser's JS Date is always UTC-relative
}
```

---

#### Component: Sidebar

**"use client"** — reads auth + alert stream context

```
┌─────────────────────────┐
│  ▪ Dashboard            │  ← active indicator
│  ▪ Instruments          │
│  ▪ Screener             │
│  ▪ Portfolio            │
│  ▪ Workspace            │
│  ▪ Alerts & News        │
│  ▪ Intelligence         │
├─────────────────────────┤
│  WATCHLIST              │
│  My Watchlist [switch]  │  ← title + button to switch active watchlist
│  ▸ AAPL  182.34 +1.2%   │
│  ▸ NVDA  875.20 -0.8%   │
│  ▸ TSLA  177.50 +3.1%   │
├─────────────────────────┤
│  RECENT ALERTS          │
│  ⚡ HIGH — AAPL 2h ago  │
│  ⚡ MED  — NVDA 5h ago  │
├─────────────────────────┤
│  ⚙ Settings             │
│  ❓ Help                 │
└─────────────────────────┘
```

**Watchlist sub-section**:
- Title shows active watchlist name
- "[switch]" button opens a `Select` dropdown listing all user watchlists
- Each member shows: ticker symbol + live price (font-mono) + % change (colored)
- Max 8 members visible; scroll within section
- Prices from `POST /v1/quotes/batch` (refetch every 30s)

**Recent alerts sub-section**:
- Shows last 5 alerts from `AlertStreamContext.recentAlerts`
- Each row: severity badge + alert_type + entity_id + relative time
- Click row → `/alerts`

---

#### Page: Dashboard (`/dashboard`)

**Layout**: Two-column grid (main 2/3 + sidebar 1/3) below the shell

**Section order** (top to bottom):
1. **MorningBriefCard** — full width, collapses after reading
2. **PortfolioSummary** — left column, prominent card
3. **MarketHeatmap** — right column, sector grid
4. **TopMovers** — horizontal row of top gainers/losers tiles
5. **WatchlistNews** — left column, news articles for watchlist entities
6. **EconomicCalendar** — right column, upcoming macro events
7. **RecentAlerts** — left column, last 10 alerts with severity
8. **AiSignals** — right column, top signal scores
9. **TopBets** — full width, prediction market odds for open markets

##### MorningBriefCard

- On mount: `GET /v1/briefings/morning` (24h Valkey cache — fast on return visits)
- Loading: skeleton of ~5 text lines (3–5s on cold cache)
- Loaded: AI-generated brief text, expandable; entity names hyperlinked to `/instruments/:id`
- Refresh button visible if brief is > 12h old (force-generates new brief)
- On error: "Unable to load brief — retry" with retry button

##### PortfolioSummary

```
┌─────────────────────────────────────────────────────────────┐
│  Portfolio                                    [5D] [5W] ←toggle│
│  Total Value    Today P&L    Unrealised P&L                 │
│  $124,580.34    +$843.20     +$12,340.00                    │
│  ─────────────────────────────────────────────────────────  │
│  Top Holdings:                                              │
│  AAPL  $32,410 (26%)  +1.2%   NVDA  $28,100 (22%)  -0.8%  │
│  TSLA  $18,750 (15%)  +3.1%   MSFT  $16,200 (13%)  +0.5%  │
│  ─────────────────────────────────────────────────────────  │
│  [Sparkline chart 5D or 5W depending on toggle]            │
└─────────────────────────────────────────────────────────────┘
```

- Data: `GET /v1/portfolios` + `GET /v1/holdings/:portfolioId` + `POST /v1/quotes/batch`
- 5D/5W toggle: changes the sparkline data range; persisted to `localStorage`
- Click "Portfolio" → `/portfolio`

##### MarketHeatmap

- S&P 500 sector tiles (11 GICS sectors)
- Each tile: sector name + % change + color scale (7 steps: deep red → deep green)
- HeatCell color scale: `-3%` (deep red) → `0%` (neutral gray) → `+3%` (deep teal-green)
- Data: `GET /v1/market/heatmap` (sector performance) or computed from holdings

##### TopMovers

- Horizontal scroll row of instrument tiles
- Two tabs: "Gainers" / "Losers"
- Each tile: ticker (font-mono) + price + % change (large, colored)
- Data: `GET /v1/market/top-movers?limit=10&type=gainers|losers`

##### WatchlistNews

- News articles for entities in the active watchlist
- Uses `GET /v1/news/top?hours=48&limit=10`
- Each article: `ArticleCard` (title, source, time, `RelevanceBadge`, entity tag)
- "View all news" → `/alerts?tab=news`

##### EconomicCalendar

- Upcoming economic events (this week + next week)
- Data: `GET /v1/fundamentals/economic-calendar`
- Each event: date/time (UTC), event name, forecast, previous value, impact level badge
- Impact: HIGH (amber) / MEDIUM (gray) / LOW (muted)

##### RecentAlerts

- Last 10 alerts from `AlertStreamContext.recentAlerts` (live) + polling `GET /v1/alerts/pending?limit=10`
- Each row: severity badge + type + entity + time (font-mono)
- "View all" → `/alerts`

##### AiSignals

- Signal scoring results from S6 (price_impact signals)
- Data: `GET /v1/signals/ai?limit=8`
- Each signal: entity, signal type, score (font-mono), direction badge

##### TopBets (Prediction Markets)

- Top 5 open Polymarket prediction markets
- Data: `GET /v1/signals/prediction-markets?limit=5&status=open`
- Each bet: question (truncated), probability bar, volume (font-mono), close date

---

#### Page: Instrument Detail (`/instruments/[id]`)

**URL**: `/instruments/:entityId` (entity_id ≠ instrument_id per ADR-F-12)

**Structure**:
```
[InstrumentHeader — ticker, full name, price, change, market cap, volume]
[Tab bar: Overview | Fundamentals | News | Intelligence]
[Tab content — changes with tab]
```

**Tab: Overview**
- `OHLCVChart` with timeframe selector (1D, 5D, 1M, 3M, 1Y, 5Y)
- `FundamentalsBar` — 6 key metrics compact bar below chart
- `SimilarEntities` — panel of 5 similar companies
- Chart range changes linked to NewsTab date filter (ADR-F-05)

**Tab: Fundamentals**
- `FundamentalsTab` — 18 sections accordion:
  Highlights, Valuation, Profitability, Growth, Balance Sheet, Cash Flow, Dividends, Analyst Consensus, Insider Transactions, Institutional Holdings, ESG, Earnings History, Revenue Segments, Geographic Revenue, Officers/Board, Corporate Actions, Financial Ratios, Macro Indicators
- Data: `GET /v1/fundamentals/:id`
- Missing sections show `—` gracefully

**Tab: News**
- `NewsTab` — entity-specific news sorted by display_relevance_score
- `TopNewsFilters` — time range, min score, source type
- Each article: `ArticleCard` with `ImpactSparkline` if ≥ 2 impact windows
- Data: `GET /v1/news/entity/:entityId?start_date=&end_date=&order_by=display_relevance_score`

**Tab: Intelligence**
- `EntityGraph` — sigma.js knowledge graph, egocentric around current entity (depth 2)
- `IntelligenceTab`:
  - AI instrument brief (`GET /v1/briefings/instrument/:id`, 24h cached)
  - Contradictions panel (`GET /v1/entities/:id/contradictions`)
  - Prediction market odds for entity (if available)
- Data: `GET /v1/entities/:id/graph`

---

#### Page: Screener (`/screener`)

**Layout**: Filter panel (left, w-72) + results (right, flex-1)

**FilterForm**:
- Fetch available fields: `GET /v1/fundamentals/screen/fields`
- Dynamic filter rows: field selector + operator + value input
- Add/remove filter rows
- Run screener: `POST /v1/fundamentals/screen`

**ResultsTable**:
- Columns: Ticker, Name, Price, Market Cap, P/E, EPS, Revenue TTM, Signal Score, % Change
- 20 rows per page, offset pagination
- Click row → `/instruments/:id`
- Sort by column (client-side if < 100 results, server-side otherwise)

---

#### Page: Portfolio (`/portfolio`)

```
[PortfolioSummary — expanded version of dashboard widget]
[PortfolioChart — 5D/5W performance, full width]
[HoldingsTable — all holdings with live P&L]
[TransactionHistory — recent buy/sell actions]
[AddTransactionForm — buy/sell form, opens in Sheet]
```

**HoldingsTable columns**: Ticker, Name, Shares, Avg Cost, Current Price, Today P&L, Total P&L, Portfolio %
- Live prices from `POST /v1/quotes/batch` (refetch every 30s)
- Click row → `/instruments/:id`

---

#### Page: Workspace (`/workspace`)

- `WorkspaceGrid` — `react-grid-layout` 12-column grid
- Initial layout: persisted to `localStorage` per user
- Panel types (user can add any combination):
  - `ChartPanel` — OHLCV chart with ticker input
  - `NewsPanel` — news feed for entered ticker
  - `AlertsPanel` — real-time alert stream
  - `ChatPanel` — mini embedded chat
  - `WatchlistPanel` — watchlist prices
  - `ScreenerPanel` — screener results
  - `GraphPanel` — entity knowledge graph
  - `BriefingPanel` — AI briefing
- Panels share the active ticker via `WorkspaceContext`

---

#### Page: Alerts & News (`/alerts`)

**Tabs**: "Alerts" | "News Feed" | "Top Today"

**Alerts tab**:
- `AlertsList` — `GET /v1/alerts/pending?limit=50`
- Filter by severity
- Acknowledge button (calls `DELETE /v1/alerts/:id/ack`)
- Real-time updates from `AlertStreamContext`

**News Feed tab**:
- General relevance news feed
- `GET /v1/news/relevant?limit=20`
- Infinite scroll / load more

**Top Today tab**:
- `TopNewsFilters` + ranked articles
- `GET /v1/news/top?hours=48`
- Load-more pagination

---

#### Page: Intelligence / Chat (`/chat`)

**Structure**:
```
[ThreadSidebar — left, w-64]  |  [ChatStream — center, flex-1]  |  [MorningBriefCard — right, w-80]
```

**ThreadSidebar**:
- List of threads (`GET /v1/threads`)
- "New chat" button (`POST /v1/threads`)
- Delete thread (hover reveals delete icon)
- Search threads by title (client-side filter)

**ChatStream**:
- Message list (thread messages)
- Input box + send button
- Streaming: `POST /v1/chat/stream` body `{question, thread_id}`, Authorization Bearer header; reads via `fetch` + `ReadableStream` (not EventSource — POST required for request body)
- State machine: idle → sending → streaming → settled
- Citations displayed inline (linked to entities/articles)
- Cancel stream button visible during streaming
- "Open in full chat" link → `/chat` (when used from mini Ask AI panel)

---

#### Page: Settings (`/settings`)

**Sections**:
- **Profile** — display name, email (read-only from Zitadel)
- **Notifications** — alert severity threshold, email digest frequency
- **Appearance** — compact/comfortable density toggle (deferred: dark only for now)
- **Connected accounts** — brokerage connection status (PLAN-0022)

---

#### Component: AskAiPanel (floating mini-chat)

- Triggered from "Ask AI" button in TopBar
- Floating panel (position: fixed, bottom-right)
- Single-message chat interface
- "Send" → calls `/v1/chat/stream` for one-shot answer
- "Open full chat →" link navigates to `/chat`
- Closes on Escape or click-outside

---

#### Component: FlashOverlay

Port from `apps/frontend/src/components/alerts/FlashOverlay.tsx` unchanged:
- Full-viewport overlay, z-9999
- 12s auto-dismiss with countdown bar
- Escape key and click-outside dismiss
- Class-based ErrorBoundary wrapper
- `"use client"` — uses useEffect for timers and keyboard events

### 6.4 Frontend App Structure

**Service path**: `apps/worldview-web/`

```
apps/worldview-web/
├── app/
│   ├── layout.tsx                    # Root layout: <html dark>, fonts, Providers
│   ├── globals.css                   # Tailwind base + Midnight Pro CSS vars
│   ├── page.tsx                      # Landing page (public)
│   ├── login/
│   │   └── page.tsx                  # "Log in to Worldview" (public)
│   ├── register/
│   │   └── page.tsx                  # "Create account" → Zitadel registration URL (public)
│   ├── callback/
│   │   └── page.tsx                  # OIDC callback: code exchange (public)
│   └── (app)/                        # Route group — all protected pages
│       ├── layout.tsx                # Auth guard + shell (Sidebar + TopBar)
│       ├── dashboard/
│       │   └── page.tsx
│       ├── instruments/
│       │   └── [id]/
│       │       └── page.tsx
│       ├── screener/
│       │   └── page.tsx
│       ├── portfolio/
│       │   └── page.tsx
│       ├── workspace/
│       │   └── page.tsx
│       ├── alerts/
│       │   └── page.tsx
│       ├── chat/
│       │   └── page.tsx
│       └── settings/
│           └── page.tsx
├── src/
│   ├── components/
│   │   ├── ui/                       # shadcn/ui generated — do not hand-edit
│   │   ├── shell/
│   │   │   ├── Sidebar.tsx           # "use client" — nav, watchlist, recent alarms
│   │   │   ├── TopBar.tsx            # "use client" — search, indexes, clock, Ask AI
│   │   │   ├── MarketStatusPill.tsx  # "use client" — UTC clock-driven status widget
│   │   │   ├── IndexTicker.tsx       # "use client" — SPY/QQQ/VIX/BTC live prices
│   │   │   ├── GlobalSearch.tsx      # "use client" — cmdk-powered instrument search
│   │   │   ├── AskAiPanel.tsx        # "use client" — floating mini-chat window
│   │   │   └── FlashOverlay.tsx      # "use client" — critical alert overlay
│   │   ├── dashboard/
│   │   │   ├── MorningBriefCard.tsx  # "use client" — on-demand, skeleton on load
│   │   │   ├── PortfolioSummary.tsx  # "use client" — total value, P&L, 5D/5W toggle
│   │   │   ├── MarketHeatmap.tsx     # "use client" — S&P 500 sector tile grid
│   │   │   ├── TopMovers.tsx         # "use client" — top gainers/losers tiles
│   │   │   ├── WatchlistNews.tsx     # "use client" — news for watchlist entities
│   │   │   ├── EconomicCalendar.tsx  # Server Component — static weekly calendar
│   │   │   ├── RecentAlerts.tsx      # "use client" — reads AlertStreamContext
│   │   │   ├── AiSignals.tsx         # "use client" — scoring signals list
│   │   │   └── TopBets.tsx           # "use client" — prediction market odds
│   │   ├── instrument/
│   │   │   ├── InstrumentHeader.tsx  # "use client" — price, change, key stats
│   │   │   ├── OHLCVChart.tsx        # "use client" — lightweight-charts wrapper
│   │   │   ├── NewsTab.tsx           # "use client" — entity news, relevance badges
│   │   │   ├── FundamentalsTab.tsx   # "use client" — 18-section fundamentals
│   │   │   ├── IntelligenceTab.tsx   # "use client" — entity graph + AI brief
│   │   │   ├── EntityGraph.tsx       # "use client" — sigma.js WebGL graph
│   │   │   ├── SimilarEntities.tsx   # "use client" — similar companies panel
│   │   │   └── FundamentalsBar.tsx   # "use client" — compact 6-metric bar
│   │   ├── screener/
│   │   │   ├── FilterForm.tsx        # "use client" — dynamic filter builder
│   │   │   └── ResultsTable.tsx      # "use client" — paginated screener results
│   │   ├── portfolio/
│   │   │   ├── PortfolioChart.tsx    # "use client" — 5D/5W performance chart
│   │   │   ├── HoldingsTable.tsx     # "use client" — live P&L per holding
│   │   │   └── AddTransactionForm.tsx # "use client" — buy/sell form
│   │   ├── alerts/
│   │   │   ├── AlertCard.tsx         # Server Component — pure display
│   │   │   ├── SeverityBadge.tsx     # Server Component — pure display
│   │   │   └── AlertsList.tsx        # "use client" — paginated alert list
│   │   ├── news/
│   │   │   ├── ArticleCard.tsx       # Server Component (no hooks) — pure display
│   │   │   ├── RelevanceBadge.tsx    # Server Component — pure display
│   │   │   ├── ImpactSparkline.tsx   # "use client" — lightweight-charts mini
│   │   │   └── TopNewsFilters.tsx    # "use client" — filter state
│   │   ├── chat/
│   │   │   ├── ThreadSidebar.tsx     # "use client" — thread list + create
│   │   │   └── ChatStream.tsx        # "use client" — SSE streaming + citations
│   │   ├── workspace/
│   │   │   ├── WorkspaceGrid.tsx     # "use client" — react-grid-layout host
│   │   │   └── panels/              # Panel type implementations
│   │   └── landing/
│   │       ├── Hero.tsx
│   │       ├── Features.tsx
│   │       ├── PricingTable.tsx
│   │       └── Footer.tsx
│   ├── contexts/
│   │   ├── AuthContext.tsx           # "use client" — OIDC token + silent refresh
│   │   ├── AlertStreamContext.tsx    # "use client" — shared WS state
│   │   └── WorkspaceContext.tsx      # "use client" — active ticker, panel layout
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   ├── useAlertStream.ts         # WS hook with token + exponential backoff
│   │   └── useMarketStatus.ts        # Pure UTC clock-driven computation (no API)
│   └── lib/
│       ├── authClient.ts             # fetch wrapper: Bearer + 401 refresh + retry
│       ├── gateway-client.ts         # All typed S9 API methods
│       ├── market-schedule.ts        # Exchange hours definition + computeMarketStatus()
│       └── utils.ts                  # cn(), formatters, relative time
├── next.config.ts                    # Rewrites /api/* → API_GATEWAY_URL
├── tailwind.config.ts
├── components.json                   # shadcn/ui config
├── package.json                      # pnpm; exact versions; no ^
├── pnpm-lock.yaml
├── tsconfig.json
└── Dockerfile                        # multi-stage: pnpm build → node:alpine next start
```

#### Technology Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Next.js 15 (App Router) | Node SSR; no `output: 'export'` |
| UI components | shadcn/ui only | Radix UI primitives + Tailwind CSS; no other component library |
| Charts | lightweight-charts 4 | TradingView Lightweight Charts for OHLCV + sparklines |
| Knowledge graph | sigma.js + graphology + @react-sigma/core | WebGL, 60fps at 100+ nodes (ADR-F-08) |
| Workspace | react-grid-layout | Drag-and-drop panel grid |
| Server state | TanStack Query v5 | No useState+useEffect for API calls |
| Command palette | cmdk (shadcn/ui peer) | Global search + Ask AI |
| Theme | Dark only | `class="dark"` on `<html>` permanently |
| Real-time | WebSocket (alerts), SSE (chat) | See §6.6 |
| Auth | Zitadel OIDC + PKCE | Token in React state only |
| Package manager | pnpm (exact versions) | `pnpm audit` must show 0 CVEs |
| Tests | Vitest + RTL + MSW + Playwright | |
| Dev port | 3001 | Avoids conflict with `apps/frontend` (3000) |

#### Visual Identity: "Midnight Pro"

```css
/* apps/worldview-web/app/globals.css */
:root.dark {
  --background:        222 47% 11%;    /* #131722 */
  --card:              215 28% 14%;    /* #1E2329 */
  --muted:             213 20% 19%;    /* #2B3139 */
  --popover:           222 47% 11%;
  --foreground:        220 14% 85%;    /* #D1D4DC */
  --muted-foreground:  220 9% 50%;     /* #787B86 */
  --primary:           199 89% 48%;    /* #0EA5E9 — sky accent */
  --primary-foreground: 222 47% 11%;
  --border:            213 20% 19%;    /* #2B3139 */
  --input:             213 20% 19%;
  --ring:              199 89% 48%;
  --accent:            213 20% 19%;
  --destructive:       0 63% 62%;      /* #EF5350 */
  --positive:          174 42% 40%;    /* #26A69A — teal-green */
  --negative:          0 63% 62%;      /* #EF5350 */
  --warning:           38 92% 50%;     /* #F59E0B */
  --neutral-value:     220 9% 50%;
  --radius: 0.375rem;
}
```

**Fonts** (loaded via `next/font/google` in root layout):
- UI text: IBM Plex Sans (weights 300/400/500/600/700)
- All numeric values: IBM Plex Mono (weights 400/500/600) — rule: ALL prices, percentages, quantities must use `font-mono`

#### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | no | `/api` | API base (proxied in dev via next.config.ts rewrites) |
| `NEXT_PUBLIC_WS_BASE_URL` | no | `ws://localhost:8010` | WebSocket base for alert stream — **must point to S10 directly** (not S9); Next.js rewrites don't proxy WS |
| `API_GATEWAY_URL` | no | `http://localhost:8000` | Server-side rewrite target (S9) |
| `NEXT_PUBLIC_APP_NAME` | no | `Worldview` | Platform display name |

> **S9 configuration required**: When running `worldview-web` alongside the rest of the stack, S9's `API_GATEWAY_FRONTEND_URL` must be overridden from `http://localhost:5173` (old Vite default) to `http://localhost:3001`. Additionally `API_GATEWAY_CORS_ORIGINS` must include `http://localhost:3001`. Set these in `infra/docker-compose.dev.yml` or a `.env` overlay for the `api-gateway` service. Failure to set these will cause: OIDC callback redirect to land on the wrong port (5173) and all preflight CORS requests to fail with 403.


### 6.6 Data Flows

#### Flow 1: App boot — auth silent refresh

```
1. User opens browser (or client-side navigates) → AuthProvider useEffect runs
2. Check if current token is still fresh (ADR-F-18):
   function isTokenExpiringSoon(token: string | null): boolean {
     if (!token) return true;
     try {
       const { exp } = JSON.parse(atob(token.split(".")[1]));
       return exp * 1000 - Date.now() < 60_000; // refresh if <60s left
     } catch { return true; }  // unparseable → assume expired
   }
2a. Token exists and exp > 60s → skip POST /auth/refresh entirely (ADR-F-18)
2b. Token missing or expiring soon → POST /api/v1/auth/refresh (browser auto-sends httpOnly cookie)
3a. 200 → store { access_token, user, expires_in } in React state; isAuthenticated=true
    Schedule next silent refresh at (expires_in - 60) seconds (ADR-F-18)
3b. 401 → isAuthenticated=false; if protected page → redirect to /login
4. AlertStreamContext.Provider mounts: opens WebSocket (useAlertStream hook)
5. Page content renders

Note: On every client-side navigation AuthProvider does NOT fire a new refresh (step 2a short-circuits).
The refresh only fires on: first mount with no/expiring token, or scheduled timer at expires_in-60s.
```

#### Flow 2: Login (OIDC PKCE)

```
1. User clicks "Log in" → window.location.href = "/api/v1/auth/login"
2. S9: generates PKCE verifier, stores state in Valkey, issues 302 to Zitadel
3. Zitadel: user authenticates
4. Zitadel: redirects to /callback?code=XXX&state=YYY
5. CallbackPage: GET /api/v1/auth/callback?code=XXX&state=YYY
6. S9: validates PKCE state from Valkey, exchanges code with Zitadel, issues:
   - httpOnly refresh_token cookie (SameSite=Strict)
   - Returns access_token + user in JSON body
7. CallbackPage: setAccessToken(token, user) → router.push("/dashboard")
```

#### Flow 3: Dashboard load

```
1. /dashboard mounts, all panels start queries simultaneously (TanStack Query)
2. Parallel fetches:
   - GET /v1/briefings/morning                (24h Valkey cache — may be instant)
   - GET /v1/portfolios → GET /v1/holdings/X  (portfolio data)
   - POST /v1/quotes/batch [SPY,QQQ,VIX,BTC]  (top bar indexes, 5s cache)
   - GET /v1/alerts/pending?limit=10          (no cache)
   - GET /v1/news/top?hours=48&limit=10       (60s cache)
   - GET /v1/signals/prediction-markets?limit=5 (60s cache)
   - GET /v1/fundamentals/economic-calendar   (1h cache)
3. Each panel renders skeleton while its own query is loading
4. Panels resolve independently — no waterfall
5. AlertStreamContext WebSocket already open from app boot → live updates arrive
```

#### Flow 4: Instrument search

```
1. User types in GlobalSearch input
2. Debounce 300ms → GET /api/v1/search/instruments?q=apple&limit=10
3. Combobox shows results: ticker + company name
4. User selects result → router.push("/instruments/:entityId")
5. Instrument Detail page mounts, parallel queries fire
```

#### Flow 5: Real-time alert

```
1. useAlertStream mounts (in AlertStreamContext.Provider, at app root)
2. Fetch ws-token: GET /api/v1/auth/ws-token (Bearer header, access_token from AuthContext)
   → { token, expires_in: 30 }
3. Open WebSocket: new WebSocket(`${NEXT_PUBLIC_WS_BASE_URL}/v1/alerts/stream?token=<ws_token>`)
   → connects directly to S10:8010 (not through S9)
   → S10 InternalJWTMiddleware reads ?token= for WS upgrades, validates RS256 JWT
4. ws.onmessage receives alert payload (JSON)
5. severity === "CRITICAL":
   - setCriticalQueue(prev => [...prev, alert])
   - FlashOverlay renders (consuming from criticalQueue via AlertStreamContext)
6. severity !== "CRITICAL":
   - setRecentAlerts(prev => [alert, ...prev].slice(0, 50))
   - Sidebar "Recent Alerts" section updates live
   - Bell badge count increments
7. ws.onclose: reconnect with exponential backoff (1s → 2s → 4s → 8s → 16s → 30s cap)
   - Fetch fresh ws-token before each reconnect attempt (old token is 30s TTL)
```

#### Flow 6: RAG Chat streaming

```
1. User submits message in ChatStream (state: idle → sending)
2. If no thread: POST /api/v1/threads → { thread_id }
3. POST /api/v1/chat/stream
   Headers: Authorization: Bearer <access_token>, Content-Type: application/json
   Body: { question: <msg>, thread_id: <id> }
   → S9 → S8 → RAG pipeline → streams SSE token chunks
4. Read response body as ReadableStream:
   const reader = response.body.getReader()
   const decoder = new TextDecoder()
   while (true) {
     const { done, value } = await reader.read()
     if (done) break
     const chunk = decoder.decode(value)
     if (chunk === "[DONE]") break    // sentinel: finalize
     setStreamingText(prev => prev + chunk)
   }
5. On "[DONE]": move streamingText → messages array; reset streamingText = ""
   → state: streaming → settled → idle
6. Citations: backend embeds `[[TICKER:entityId]]` markers in response text.
   Rendered client-side as <Link href="/instruments/{entityId}">{TICKER}</Link>
7. Cancel button visible during streaming: calls reader.cancel() + resets state to idle
8. On fetch error: state → error; show partial text + "Response interrupted" + Retry button
```

---

## 7. Architecture Decisions

### ADR-F-01: Node SSR (not static export)
**Decision**: Use `next start` Node server. No `output: 'export'`.
**Rationale**: Next.js Middleware for auth redirects requires Node runtime. httpOnly cookie handling works seamlessly. Future server components can prefetch.

### ADR-F-02: WebSocket auth via short-lived `?token=` query param (ws-token flow)
**Decision**: Alert stream WS URL includes `?token=<ws_token>` where `ws_token` is a 30s-TTL RS256 JWT fetched from `GET /v1/auth/ws-token` immediately before opening the connection.
**Rationale**: Browser WebSocket API has no headers — `new WebSocket(url)` accepts only a URL and optional subprotocol string. Using the main 15-min access token directly in a URL would leak it in server logs; a short-lived purpose-scoped token limits the exposure window to 30s. S10's `InternalJWTMiddleware` was extended to accept `?token=` for WebSocket upgrade requests (HTTP GET with `Upgrade: websocket` header) in addition to the `X-Internal-JWT` header used by regular HTTP endpoints.
**Note**: Next.js `rewrites()` does NOT proxy WebSocket upgrades. `useAlertStream` uses `NEXT_PUBLIC_WS_BASE_URL` directly (`ws://localhost:8010` in dev — S10's port). `NEXT_PUBLIC_WS_BASE_URL` must never be set to S9's port (8000) as S9 has no WS proxy.

### ADR-F-03 (REVISED): New directory, not in-place migration
**Decision**: `apps/worldview-web/` is a new standalone service. `apps/frontend/` runs in parallel until deprecated.
**Rationale**: Zero-risk parallel development. No docker-compose instability during migration.
**Deprecation plan**: Once `worldview-web` achieves feature parity (all pages implemented and tested), update docker-compose to replace `frontend` with `worldview-web`, then delete `apps/frontend/`.

### ADR-F-04: Dark mode only
**Decision**: `<html className="dark">` permanent in root layout. No toggle.
**Rationale**: Market intelligence tools use dark UIs (chart contrast, eye strain). Simplifies CSS variable system.

### ADR-F-06: Public landing at `/`; dashboard at `/dashboard`
**Decision**: `/` = public landing. `/dashboard` = protected dashboard.
**Route group**: `app/(app)/` wraps all protected pages without adding to URL.

### ADR-F-07: Workspace state in localStorage + WorkspaceContext
**Decision**: Panel layout persisted to `localStorage` keyed by `user_id`. `WorkspaceContext` shares active ticker across panels.
**Rationale**: No server-side API needed for layout persistence. Per-browser is acceptable for MVP.

### ADR-F-08: sigma.js for entity graph (not D3.js, not Cytoscape.js)
**Decision**: `sigma.js` + `graphology` + `@react-sigma/core` for entity knowledge graph.
**Rationale**: WebGL rendering handles 100+ nodes at 60fps. D3.js SVG degrades at 200+ nodes. Cytoscape.js uses Canvas but lacks React-first integration. ForceAtlas2 from `graphology-layout-forceatlas2` is industry standard.

### ADR-F-09: Morning brief on-demand (not nightly)
**Decision**: Brief generated on first request of the day (dashboard mount or explicit refresh).
**Rationale**: Users span timezones. Inactive users waste LLM tokens. 24h Valkey cache (`s8:v1:brief:morning:{user_id}:{date_utc}`) means cost is paid once per day regardless.

### ADR-F-11: cmdk for command palette / search
**Decision**: Global instrument search uses `cmdk` (shadcn/ui peer dependency).
**Rationale**: Already available as transitive dependency. Powers both global search and Ask AI launch.

### ADR-F-12: entity_id ≠ instrument_id
**Decision**: URL param is `entityId` (S7 entity, type `financial_instrument`). Not ticker symbol or EODHD instrument ID.
**Rationale**: The knowledge graph operates on entity IDs. S9 resolves entity_id → quotes/fundamentals internally.

### ADR-F-15: IBM Plex Mono for all numeric values
**Decision**: ALL prices, percentages, quantities, timestamps in tables must use `font-mono` class.
**Rationale**: Tabular alignment requires monospace. This is the single highest-impact rule for professional appearance.

### ADR-F-16: MarketStatusPill is pure client-side computation
**Decision**: No API call for market status. Computed from UTC time + static exchange schedule in `src/lib/market-schedule.ts`.
**Rationale**: Market hours are static calendar knowledge. An API call would be unnecessary latency. Updates every 60 seconds (minute-boundary re-computation).

### ADR-F-17: Dev port 3001 (not 3000)
**Decision**: `worldview-web` runs on port 3001 in development to avoid conflict with `apps/frontend` (3000).
**Rationale**: Both services may run simultaneously during the transition period.

### ADR-F-18: Token expiry check before silent refresh
**Decision**: Before calling `POST /api/v1/auth/refresh`, `AuthContext` checks whether the current token still has >60 seconds remaining by decoding the JWT `exp` claim client-side:
```typescript
function isTokenExpiringSoon(token: string | null): boolean {
  if (!token) return true;
  try {
    const { exp } = JSON.parse(atob(token.split(".")[1]));
    return exp * 1000 - Date.now() < 60_000; // refresh only if <60s left
  } catch { return true; }
}
```
If the token is still fresh, the refresh call is skipped entirely.
**Rationale**: The silent refresh timer fires at `expires_in - 60` seconds. On re-mount (e.g., React StrictMode double-invoke, or hot reload), `POST /api/v1/auth/refresh` would fire unnecessarily. Skipping the refresh when the token has >60s left eliminates these redundant network calls without any security trade-off (the token is still valid; the server-side refresh endpoint would succeed but produce no benefit).
**Security note**: Reading `exp` from the JWT payload is safe — the payload is public. We are NOT skipping signature verification; that is still performed by S9/S10 on every API call.

### ADR-F-19: Singleton `refreshPromise` in `authClient.ts` to deduplicate concurrent 401s
**Decision**: `authClient.ts` maintains a module-level `let refreshPromise: Promise<string | null> | null = null`. When any API call receives a 401:
1. If `refreshPromise` is null → create it (fire `POST /api/v1/auth/refresh`), store in module variable
2. If `refreshPromise` is already set → await the existing promise (don't fire a second refresh)
3. After promise settles → set `refreshPromise = null` so future 401s can refresh again
**Rationale**: The dashboard fires 9 parallel TanStack Query fetches on mount. If the access token has just expired, all 9 receive 401 simultaneously. Without the singleton pattern, all 9 would call `POST /api/v1/auth/refresh` — this is redundant at best and could cause a race condition at worst (two refreshes invalidating each other). The singleton ensures exactly one refresh fires regardless of concurrent requestors.
```typescript
// Module-level (not inside any function) — shared across all authFetch() calls
let refreshPromise: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", { method: "POST" })
      .then(r => r.ok ? r.json().then((d: { access_token: string }) => d.access_token) : null)
      .finally(() => { refreshPromise = null; }); // reset after settle
  }
  return refreshPromise;
}
```

### ADR-F-20: `next/image` for all images; `<Link>` for all internal navigation
**Decision**:
- All `<img>` tags must use `next/image` `<Image>` component.
- All internal navigation must use `next/link` `<Link>` component, never `<a href="...">`.
**Rationale**:
- `next/image` automatically generates `srcset` for responsive sizes, converts to WebP/AVIF, lazy-loads by default, and prevents Cumulative Layout Shift (CLS) by reserving space. The hero image on the landing page must add `priority` prop to prevent LCP penalty.
- `<Link>` prefetches route JavaScript and data when the link enters the viewport (Next.js App Router behaviour). A bare `<a>` tag causes a full page reload, losing all in-memory state. `<a>` is only acceptable for external URLs.

---

## 8. Security Design

### 8.1 Auth Security

| Threat | Mitigation |
|--------|-----------|
| XSS token theft | Access token in React state only — never localStorage, never non-httpOnly cookie |
| CSRF on auth endpoints | S9 validates PKCE state nonce (stored in Valkey); same-origin rewrite |
| Session fixation | New access token issued on every silent refresh |
| Token leakage in URL | Callback exchanges code server-side (S9); token never appears in URL |
| WS auth bypass | `?token=` is RS256 JWT validated by S9; expired tokens rejected |
| Open redirect | `/callback` only redirects to `/dashboard` (hard-coded, no open redirect) |

### 8.2 Input Validation

| Input | Where | Validation |
|-------|-------|-----------|
| Search query | `GlobalSearch` | Debounced, max 100 chars, URL-encoded before API call |
| Chat message | `ChatStream` | Max 2000 chars, trimmed, no HTML injection (displayed as text) |
| Screener filter values | `FilterForm` | Numeric inputs validated as `number` type; strings sanitised |
| Transaction amounts | `AddTransactionForm` | Positive numbers only, max precision 6 decimal places |
| Workspace layout | localStorage | Parsed with try/catch; falls back to default layout on parse error |

### 8.3 Content Security Policy

Add to `next.config.ts` security headers:
```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' ws://localhost:8010 wss://<domain>;
```
Note: `connect-src` uses port **8010** (S10 direct) for WebSocket. S9 port (8000) is covered by `'self'` via the `/api/*` rewrite. Adjust for production domain (S10 will be behind the same reverse-proxy domain).

### 8.4 Sensitive Data Handling

- `access_token`: React state only; cleared on logout; 15-min TTL
- `refresh_token`: httpOnly SameSite=Strict cookie; handled entirely by S9; never visible to JS
- No PII logged to console or error monitoring
- No financial data cached in localStorage (only layout preferences)

---

## 9. Failure Modes & Recovery

| Failure | Symptom | Recovery |
|---------|---------|---------|
| S9 unreachable | All API calls fail | Each panel shows `ErrorCard` with retry button; app shell still renders |
| Silent refresh fails (401) | `isAuthenticated=false` on mount | Redirect to `/login`; user sees login page |
| Access token expires mid-session | First 401 triggers silent refresh; `authClient.ts` retries | Transparent to user if refresh succeeds |
| Both token and refresh token expired | Second 401 → `router.push("/login")` | User redirected to login; no data loss |
| WebSocket drops | `ws.onclose` fires | `useAlertStream` reconnects with exponential backoff (1s → 30s) |
| Morning brief cold-cache timeout (>5s) | Skeleton visible | Loading skeleton acceptable; skeleton never disappears to empty state |
| Chat stream drops mid-response | `fetch()` ReadableStream reader throws or returns `done=true` early | Show partial response + "Response interrupted" message + Retry button; state reset to idle on retry |
| localStorage quota exceeded | `localStorage.setItem` throws | Catch error silently; fall back to default workspace layout; don't crash |
| TanStack Query max retries exceeded | Component shows `ErrorCard` | `refetch()` button available; user can manually retry |
| sigma.js WebGL context lost | Graph panel blank or crash | Catch error in React ErrorBoundary; show "Graph unavailable — reload" message |

---

## 10. Scalability & Performance

### 10.1 Bundle Strategy

| Chunk | What's in it | Loaded when |
|-------|-------------|-------------|
| Main bundle | React, Next.js router, AuthProvider, shadcn/ui base | Every page |
| `sigma.js` chunk | sigma + graphology (heavy) | `/instruments/[id]` Intelligence tab only (dynamic import) |
| `react-grid-layout` | Workspace grid | `/workspace` only (dynamic import) |
| `lightweight-charts` | OHLCV chart | `/instruments/[id]` + OHLCVChart (dynamic import) |
| Page chunks | Page-specific components | Per-page, auto code-split by Next.js |

**Pattern for heavy components**:
```tsx
const EntityGraph = dynamic(() => import("@/src/components/instrument/EntityGraph"), {
  ssr: false,          // WebGL — must be client-only
  loading: () => <Skeleton className="h-96 w-full" />,
});
```

### 10.2 Data Fetching Performance

| Query | Cache TTL | Stale-while-revalidate | Notes |
|-------|-----------|------------------------|-------|
| Index prices | 5s | Yes | Visible staleness acceptable |
| Morning brief | 24h | Yes | Valkey-cached at S9 level |
| Instrument brief | 24h | Yes | Valkey-cached per instrument |
| OHLCV data | 60s | Yes | Daily data; fine to cache |
| News feed | 60s | Yes | |
| Portfolio holdings | 30s | Yes | Prices update frequently |
| Screener results | No cache | No | User-initiated; should be fresh |
| Alerts | No cache | No | Real-time via WS anyway |

### 10.3 Re-render Control

- `useCallback` / `useMemo` on functions passed as props to heavy components (chart, graph)
- TanStack Query's structural sharing prevents unnecessary re-renders on refetch
- `WorkspaceContext` uses `useMemo` for context value to prevent provider-level re-render cascade

---

## 11. Test Strategy

All tests live in `apps/worldview-web/tests/`. The goal is exhaustive coverage: every component, every state transition, every real-time interaction, every security invariant.

---

### 11.1 Unit Tests (Vitest + RTL)

#### Auth

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `AuthContext.test.tsx` | Silent refresh 200 → `isAuthenticated=true`, access_token stored in state | HIGH |
| `AuthContext.test.tsx` | Silent refresh 401 → `isAuthenticated=false`; no retry | HIGH |
| `AuthContext.test.tsx` | `login()` sets `window.location.href` to `/api/v1/auth/login` | HIGH |
| `AuthContext.test.tsx` | `logout()` clears access_token state + calls POST /api/v1/auth/logout | HIGH |
| `AuthContext.test.tsx` | Silent refresh scheduled 60s before token expiry (fake timers) | HIGH |
| `authClient.test.ts` | All requests include `Authorization: Bearer <token>` header | HIGH |
| `authClient.test.ts` | First 401 triggers silent refresh; original request retried with new token | HIGH |
| `authClient.test.ts` | Second 401 after refresh fails → `router.push("/login")` (no infinite loop) | HIGH |
| `authClient.test.ts` | Concurrent 401s: only one refresh call made; both original requests retry after | HIGH |
| `CallbackPage.test.tsx` | `?code=` + `?state=` present → GET /api/v1/auth/callback → setToken → router.push("/dashboard") | HIGH |
| `CallbackPage.test.tsx` | Callback returns error → shows error message + "Back to login" link | HIGH |
| `CallbackPage.test.tsx` | Missing `?code=` param → shows "Invalid callback" error immediately | HIGH |
| `ProtectedLayout.test.tsx` | `isLoading=true` → renders `<Spinner>` | HIGH |
| `ProtectedLayout.test.tsx` | `isAuthenticated=false` (not loading) → `router.push("/login")` | HIGH |
| `ProtectedLayout.test.tsx` | `isAuthenticated=true` → renders `{children}` | HIGH |

#### Market Status

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `market-schedule.test.ts` | NYSE open at 15:00 UTC Mon (inside 14:30–21:00) | HIGH |
| `market-schedule.test.ts` | NYSE closed at 22:30 UTC Mon (after 21:00) | HIGH |
| `market-schedule.test.ts` | NYSE pre-market at 11:00 UTC Mon (inside 10:00–14:30) | HIGH |
| `market-schedule.test.ts` | NYSE after-hours at 22:00 UTC Mon (inside 21:00–00:00) | HIGH |
| `market-schedule.test.ts` | NYSE closed on Saturday 15:00 UTC (weekend) | HIGH |
| `market-schedule.test.ts` | LSE open at 09:00 UTC Mon; closed at 17:00 UTC Mon | HIGH |
| `market-schedule.test.ts` | TSE closed during lunch break 02:45 UTC Mon (02:30–03:30) | HIGH |
| `market-schedule.test.ts` | HKEX closed during lunch break 04:30 UTC Mon (04:00–05:00) | HIGH |
| `market-schedule.test.ts` | FOREX open on Saturday 14:00 UTC (24/5) | HIGH |
| `market-schedule.test.ts` | FOREX closed on Sunday 21:00 UTC (before 22:00 Sun open) | HIGH |
| `market-schedule.test.ts` | Crypto open 03:00 UTC Sunday (24/7) | HIGH |
| `market-schedule.test.ts` | CME Futures open on Sunday 23:30 UTC (Sun 23:00 open) | HIGH |
| `market-schedule.test.ts` | Exact boundary: NYSE opens at 14:30:00 → "open"; 14:29:59 → "closed" | HIGH |
| `market-schedule.test.ts` | `computeMarketStatus` overall="open" when NYSE in regular session | HIGH |
| `market-schedule.test.ts` | `computeMarketStatus` overall="pre-after-hours" when NYSE pre-market, no other regular market open | HIGH |
| `market-schedule.test.ts` | `computeMarketStatus` overall="closed" at Saturday 03:00 UTC (no regular equity market) | HIGH |
| `market-schedule.test.ts` | Returns array of 8 `ExchangeStatus` objects regardless of time | HIGH |
| `MarketStatusPill.test.tsx` | overall="open" → green pill with "● Markets Open" text | HIGH |
| `MarketStatusPill.test.tsx` | overall="closed" → red pill with "● Markets Closed" text | HIGH |
| `MarketStatusPill.test.tsx` | overall="pre-after-hours" → amber pill with "◐ Pre/After-Hours" text | HIGH |
| `MarketStatusPill.test.tsx` | Hover/focus → Popover opens with table of 8 exchange rows | HIGH |
| `MarketStatusPill.test.tsx` | Each table row shows exchange name, status indicator, UTC hours | MED |
| `MarketStatusPill.test.tsx` | Popover shows current UTC datetime | MED |
| `useMarketStatus.test.ts` | Returns result of `computeMarketStatus(new Date())` on mount | MED |
| `useMarketStatus.test.ts` | Re-computes every 60s via `setInterval` (fake timers advance 60s → new value) | MED |
| `useMarketStatus.test.ts` | Cleanup: `clearInterval` called on unmount (no memory leak) | HIGH |

#### Alert Stream

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `useAlertStream.test.ts` | On mount: calls GET /api/v1/auth/ws-token with Bearer header | HIGH |
| `useAlertStream.test.ts` | After ws-token: opens WebSocket to `${NEXT_PUBLIC_WS_BASE_URL}/v1/alerts/stream?token=<ws_token>` | HIGH |
| `useAlertStream.test.ts` | CRITICAL severity alert → added to `criticalQueue` | HIGH |
| `useAlertStream.test.ts` | Non-CRITICAL alert → added to `recentAlerts` (capped at 50) | HIGH |
| `useAlertStream.test.ts` | `dequeueCritical()` removes first item from `criticalQueue` | HIGH |
| `useAlertStream.test.ts` | WS close → reconnect after 1s (fake timers); exponential backoff 1→2→4→8→16→30 | HIGH |
| `useAlertStream.test.ts` | Each reconnect fetches fresh ws-token (separate GET /auth/ws-token call) | HIGH |
| `useAlertStream.test.ts` | WS close: backoff caps at 30s (verify 7th attempt = 30s not 64s) | MED |
| `useAlertStream.test.ts` | Cleanup on unmount: `ws.close()` called, reconnect timer cleared | HIGH |
| `useAlertStream.test.ts` | auth ws-token 401 → does not open WS; `router.push("/login")` | HIGH |
| `FlashOverlay.test.tsx` | Renders when `criticalQueue.length > 0` | HIGH |
| `FlashOverlay.test.tsx` | Auto-dismisses after 12s (vi.useFakeTimers; advance 12000ms) | HIGH |
| `FlashOverlay.test.tsx` | Escape key dismisses overlay (calls `dequeueCritical`) | HIGH |
| `FlashOverlay.test.tsx` | Click outside overlay area dismisses (or: click X button) | HIGH |
| `FlashOverlay.test.tsx` | Multiple criticals: first renders; dismiss → second renders | HIGH |
| `FlashOverlay.test.tsx` | ErrorBoundary wraps content; if render throws → fallback shown (no white screen) | HIGH |
| `FlashOverlay.test.tsx` | Cleanup: auto-dismiss timer cleared on unmount | HIGH |

#### Chat Stream

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `ChatStream.test.tsx` | Initial state: idle; input enabled; no streaming text | HIGH |
| `ChatStream.test.tsx` | Submit message: state → sending; POST /api/v1/chat/stream fires with correct body | HIGH |
| `ChatStream.test.tsx` | POST body: `{ question: "...", thread_id: "..." }` | HIGH |
| `ChatStream.test.tsx` | POST header: `Authorization: Bearer <access_token>` | HIGH |
| `ChatStream.test.tsx` | Token does NOT appear in POST URL (security: no ?token= for chat) | HIGH |
| `ChatStream.test.tsx` | Stream chunks: each chunk appended to `streamingText` state | HIGH |
| `ChatStream.test.tsx` | `[DONE]` sentinel: `streamingText` moves to `messages` array; `streamingText` reset to "" | HIGH |
| `ChatStream.test.tsx` | `[DONE]` with empty preceding text: empty message not added to array (or shown as empty) | MED |
| `ChatStream.test.tsx` | Cancel button visible during streaming; click → `reader.cancel()` + state → idle | HIGH |
| `ChatStream.test.tsx` | fetch error (network failure): state → error; partial text preserved; Retry button visible | HIGH |
| `ChatStream.test.tsx` | Retry button: new POST fires from idle state | HIGH |
| `ChatStream.test.tsx` | Citation format `[[AAPL:entity-uuid-123]]` → rendered as `<Link href="/instruments/entity-uuid-123">AAPL</Link>` | HIGH |
| `ChatStream.test.tsx` | Multiple citations in one message all rendered as separate links | MED |
| `ChatStream.test.tsx` | Max 2000 chars enforced in input; submit disabled if empty | MED |
| `ChatStream.test.tsx` | New thread: POST /api/v1/threads → thread_id; used in subsequent stream POST | HIGH |
| `ChatStream.test.tsx` | Existing thread: thread_id reused; no new POST /threads | HIGH |
| `ThreadSidebar.test.tsx` | Renders list of threads with names | MED |
| `ThreadSidebar.test.tsx` | Click thread → loads messages for that thread | MED |
| `ThreadSidebar.test.tsx` | "New chat" button → clears current thread | MED |
| `ThreadSidebar.test.tsx` | Delete thread → removed from list | MED |

#### Workspace

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `WorkspaceGrid.test.tsx` | Renders with default layout on first mount (no localStorage) | HIGH |
| `WorkspaceGrid.test.tsx` | After drag: localStorage updated with new panel positions | HIGH |
| `WorkspaceGrid.test.tsx` | On mount with existing localStorage: restores saved layout | HIGH |
| `WorkspaceGrid.test.tsx` | localStorage parse error (corrupted JSON): falls back to default layout, no crash | HIGH |
| `WorkspaceGrid.test.tsx` | localStorage quota exceeded (mock `setItem` throwing): silent fallback, no crash | HIGH |
| `WorkspaceGrid.test.tsx` | All 8 panel types render their content (Chart, News, Alerts, Chat, Watchlist, Screener, Graph, Briefing) | MED |
| `WorkspaceContext.test.tsx` | `setActiveTicker("AAPL")` → all panels consuming context update | HIGH |
| `WorkspaceContext.test.tsx` | `useMemo` on context value: provider doesn't re-render children on unrelated state change | MED |

#### Portfolio

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `PortfolioSummary.test.tsx` | Total value, today P&L, unrealised P&L rendered in `font-mono` class | HIGH |
| `PortfolioSummary.test.tsx` | Positive P&L → `text-positive` color class | HIGH |
| `PortfolioSummary.test.tsx` | Negative P&L → `text-negative` (destructive) color class | HIGH |
| `PortfolioSummary.test.tsx` | 5D/5W chart toggle changes displayed data range | MED |
| `AddTransactionForm.test.tsx` | Submit with positive quantity + positive price + valid date → POST /api/v1/transactions fires | HIGH |
| `AddTransactionForm.test.tsx` | Negative quantity → validation error; form not submitted | HIGH |
| `AddTransactionForm.test.tsx` | Price with > 6 decimal places → rounded or rejected | MED |
| `AddTransactionForm.test.tsx` | Missing required field → submit button disabled | HIGH |

#### Screener

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `FilterForm.test.tsx` | Loads filter fields from GET /v1/fundamentals/screen/fields on mount | HIGH |
| `FilterForm.test.tsx` | Adds filter row: field + operator + value | HIGH |
| `FilterForm.test.tsx` | Remove filter row: removed from form state | MED |
| `FilterForm.test.tsx` | Submit: POST /v1/fundamentals/screen with correct body | HIGH |
| `FilterForm.test.tsx` | Numeric field with non-numeric value → validation error | HIGH |
| `ResultsTable.test.tsx` | Renders paginated rows with font-mono numeric columns | MED |
| `ResultsTable.test.tsx` | "Next page" button increments offset by limit value | MED |
| `ResultsTable.test.tsx` | Click row → `router.push("/instruments/:entityId")` | HIGH |

#### Shared Components

| Test File | Scenario | Priority |
|-----------|----------|----------|
| `GlobalSearch.test.tsx` | Fewer than 3 chars → no API call fired | HIGH |
| `GlobalSearch.test.tsx` | 3+ chars → debounced 300ms → GET /v1/search/instruments?q=... | HIGH |
| `GlobalSearch.test.tsx` | Select result → `router.push("/instruments/:entityId")` | HIGH |
| `GlobalSearch.test.tsx` | Empty results → "No results" state shown | MED |
| `RelevanceBadge.test.tsx` | Score 0.87 → "87%"; score ≥ 0.8 → high-impact color | MED |
| `RelevanceBadge.test.tsx` | Score < 0.3 → low-impact muted color | MED |
| `ImpactSparkline.test.tsx` | ≥ 2 non-null windows → chart renders | MED |
| `ImpactSparkline.test.tsx` | < 2 windows → returns `null` (nothing rendered) | MED |
| `ArticleCard.test.tsx` | LIGHT source tier → `opacity-60` class | MED |
| `ArticleCard.test.tsx` | DEEP source tier → full opacity | MED |
| `ArticleCard.test.tsx` | ImpactSparkline shown only when ≥ 2 impact windows | MED |

---

### 11.2 Integration Tests (Vitest + MSW server)

MSW handlers mock all S9 endpoints. Tests exercise full component trees with realistic data flows.

| Test File | What It Verifies | Priority |
|-----------|-----------------|----------|
| `dashboard-load.test.tsx` | Dashboard mounts → all 7 panels fire queries in parallel (no waterfall) → each shows skeleton then real data | HIGH |
| `auth-flow.test.tsx` | Silent refresh 200 → isAuthenticated=true → protected layout renders children | HIGH |
| `auth-double-401.test.tsx` | Two concurrent requests both 401 → only one refresh POST fires → both requests retried | HIGH |
| `auth-expired-mid-session.test.tsx` | Token expires at T+500ms (fake timers): silent refresh fires at T+100ms (60s-before-expiry scheduling) | HIGH |
| `alert-ws-connect.test.tsx` | ws-token fetch → WS open to `NEXT_PUBLIC_WS_BASE_URL` with `?token=` → receive mock CRITICAL → FlashOverlay appears | HIGH |
| `alert-ws-reconnect.test.tsx` | Mock WS server drops connection → useAlertStream reconnects → fresh ws-token fetched before reconnect | HIGH |
| `alert-badge-count.test.tsx` | Non-CRITICAL alert received → bell badge count increments | MED |
| `alert-ack.test.tsx` | Acknowledge alert → DELETE /v1/alerts/:id/ack → removed from pending list | HIGH |
| `chat-full-flow.test.tsx` | No thread → POST /threads → POST /chat/stream → chunk assembly → [DONE] → message in list | HIGH |
| `chat-existing-thread.test.tsx` | Existing thread_id: no POST /threads; stream POST uses existing thread_id | HIGH |
| `chat-cancel.test.tsx` | Cancel during streaming → reader.cancel() → state idle → input re-enabled | HIGH |
| `chat-error-retry.test.tsx` | Network error during stream → error state + partial text shown → Retry → new POST fires | HIGH |
| `chat-citations.test.tsx` | Response contains `[[AAPL:abc-uuid]]` → rendered as `<a href="/instruments/abc-uuid">AAPL</a>` | HIGH |
| `instrument-tabs.test.tsx` | Instrument page mounts → News/Fundamentals/Intelligence tab switching loads different content | HIGH |
| `instrument-graph.test.tsx` | Intelligence tab → sigma.js graph component renders (dynamic import mock) | MED |
| `workspace-persist.test.tsx` | Drag panel → localStorage key updated → fresh mount with same localStorage → layout restored | HIGH |
| `workspace-ticker-context.test.tsx` | Set active ticker in Chart panel → News panel query uses same ticker | HIGH |
| `portfolio-add-transaction.test.tsx` | AddTransactionForm submit → POST /transactions → holdings refetch | HIGH |
| `screener-filter-run.test.tsx` | Add filter → submit → POST /fundamentals/screen → results in table | HIGH |

---

### 11.3 E2E Tests (Playwright)

Use MSW for network mocking in browser. All tests run against the full Next.js dev server on port 3001.

#### Auth & Navigation

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/auth.spec.ts` | Unauthenticated visit to `/dashboard` → redirected to `/login` | HIGH |
| `e2e/auth.spec.ts` | `/login` page renders "Log in to Worldview" button | HIGH |
| `e2e/auth.spec.ts` | Click login → navigates to `/api/v1/auth/login` URL | HIGH |
| `e2e/auth.spec.ts` | With mock auth: `/callback?code=X&state=Y` → redirected to `/dashboard` | HIGH |
| `e2e/auth.spec.ts` | After auth: `localStorage.getItem("access_token")` is null | HIGH |
| `e2e/auth.spec.ts` | After auth: `localStorage.getItem("refresh_token")` is null | HIGH |
| `e2e/auth.spec.ts` | Logout → `isAuthenticated=false` → redirect to `/login` | HIGH |
| `e2e/auth.spec.ts` | Back button after logout → cannot access protected page | HIGH |

#### Landing Page

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/landing.spec.ts` | `/` loads without auth; no redirect | HIGH |
| `e2e/landing.spec.ts` | Hero section visible; CTA button present | MED |
| `e2e/landing.spec.ts` | Feature comparison table renders 3 columns | MED |
| `e2e/landing.spec.ts` | Pricing section shows 3 tiers | MED |
| `e2e/landing.spec.ts` | FAQ accordion expands on click | MED |
| `e2e/landing.spec.ts` | "Log in" and "Get started" buttons in nav bar navigate to correct pages | HIGH |

#### Dashboard

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/dashboard.spec.ts` | Dashboard loads after mock auth; no redirect | HIGH |
| `e2e/dashboard.spec.ts` | Morning brief card: shows skeleton then content | HIGH |
| `e2e/dashboard.spec.ts` | Top bar: index tickers visible with font-mono prices | HIGH |
| `e2e/dashboard.spec.ts` | Market status pill visible; hover opens exchange dropdown | HIGH |
| `e2e/dashboard.spec.ts` | UTC clock ticks (wait 2s, assert text changed) | MED |
| `e2e/dashboard.spec.ts` | Portfolio summary card visible with P&L values | MED |

#### Chat

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/chat.spec.ts` | Navigate to `/chat`; input field focused | HIGH |
| `e2e/chat.spec.ts` | Type question → submit → streaming tokens appear in chat area | HIGH |
| `e2e/chat.spec.ts` | `[DONE]` received → input re-enabled; message shows in thread | HIGH |
| `e2e/chat.spec.ts` | Cancel button visible during streaming; click → streaming stops; input re-enabled | HIGH |
| `e2e/chat.spec.ts` | Citation link in response → clickable → navigates to `/instruments/:id` | HIGH |
| `e2e/chat.spec.ts` | New chat button → thread sidebar shows new thread | MED |
| `e2e/chat.spec.ts` | Thread in sidebar → click → loads thread messages | MED |
| `e2e/chat.spec.ts` | Network error mid-stream → "Response interrupted" message + Retry button shown | HIGH |

#### Alerts

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/alerts.spec.ts` | WS connection established to `NEXT_PUBLIC_WS_BASE_URL` (check network) | HIGH |
| `e2e/alerts.spec.ts` | Inject mock CRITICAL alert via WS → FlashOverlay appears | HIGH |
| `e2e/alerts.spec.ts` | FlashOverlay auto-dismisses after 12s (fake clock via CDP) | HIGH |
| `e2e/alerts.spec.ts` | FlashOverlay dismissed by Escape key | HIGH |
| `e2e/alerts.spec.ts` | Bell badge increments on non-CRITICAL alert | HIGH |
| `e2e/alerts.spec.ts` | Navigate to `/alerts` → alert list rendered | HIGH |
| `e2e/alerts.spec.ts` | Acknowledge alert → disappears from list (DELETE /alerts/:id/ack called) | HIGH |
| `e2e/alerts.spec.ts` | WS drop + reconnect: fresh ws-token fetched; alerts resume after reconnect | HIGH |

#### Market Status

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/market-status.spec.ts` | Stub `Date` to NYSE hours (15:00 UTC Mon) → green pill | HIGH |
| `e2e/market-status.spec.ts` | Stub `Date` to Saturday 10:00 UTC → red pill | HIGH |
| `e2e/market-status.spec.ts` | Hover pill → exchange dropdown shows 8 rows | HIGH |
| `e2e/market-status.spec.ts` | Each exchange row shows name, status indicator, UTC hours | MED |

#### Instrument Detail

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/instrument.spec.ts` | Navigate to `/instruments/:id` → page loads, header shows ticker | HIGH |
| `e2e/instrument.spec.ts` | Default tab (News) shows article cards | HIGH |
| `e2e/instrument.spec.ts` | Click "Fundamentals" tab → fundamentals data sections visible | HIGH |
| `e2e/instrument.spec.ts` | Click "Intelligence" tab → graph canvas element visible | HIGH |
| `e2e/instrument.spec.ts` | Click "Intelligence" tab → AI brief card renders | MED |
| `e2e/instrument.spec.ts` | OHLCV chart `<canvas>` element exists and has non-zero dimensions | HIGH |

#### Screener

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/screener.spec.ts` | Screener page loads; filter dropdowns visible | HIGH |
| `e2e/screener.spec.ts` | Add `market_cap > 1000000000` filter → click Run → results table renders | HIGH |
| `e2e/screener.spec.ts` | Results table shows entity rows with font-mono numeric columns | HIGH |
| `e2e/screener.spec.ts` | Click result row → navigates to `/instruments/:entityId` | HIGH |
| `e2e/screener.spec.ts` | Next page → new request with `offset=20` | MED |

#### Portfolio

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/portfolio.spec.ts` | `/portfolio` loads; holdings table visible | HIGH |
| `e2e/portfolio.spec.ts` | P&L values rendered with `font-mono` class | HIGH |
| `e2e/portfolio.spec.ts` | "Add Transaction" → modal opens | HIGH |
| `e2e/portfolio.spec.ts` | Fill form → submit → POST /transactions → holdings refresh | HIGH |
| `e2e/portfolio.spec.ts` | 5D/5W toggle changes portfolio chart data | MED |

#### Workspace

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/workspace.spec.ts` | `/workspace` loads; default panels visible | HIGH |
| `e2e/workspace.spec.ts` | Drag panel to new position → drag released → position maintained | HIGH |
| `e2e/workspace.spec.ts` | Navigate away and back → layout preserved (from localStorage) | HIGH |
| `e2e/workspace.spec.ts` | Set active ticker in Chart panel → Briefing panel header shows same ticker | HIGH |
| `e2e/workspace.spec.ts` | Corrupt localStorage key before load → default layout renders, no crash | HIGH |

#### Settings & Landing

| Spec File | Scenario | Priority |
|-----------|----------|----------|
| `e2e/settings.spec.ts` | `/settings` loads; profile section visible | MED |
| `e2e/settings.spec.ts` | Notification preference toggle → PATCH /email-preferences fires | MED |

---

### 11.4 Security Invariant Tests

These must never be allowed to fail. Run in CI on every PR.

```ts
// e2e/security.spec.ts — Playwright assertions after full auth flow

// 1. No tokens ever in localStorage
expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBeNull();
expect(await page.evaluate(() => localStorage.getItem("refresh_token"))).toBeNull();
expect(await page.evaluate(() => localStorage.getItem("token"))).toBeNull();
expect(await page.evaluate(() => Object.keys(localStorage).filter(k => k.includes("token")))).toHaveLength(0);

// 2. No Authorization header visible in URL (check requests captured by page.on("request"))
const requestsWithTokenInUrl = capturedRequests.filter(r => r.url().includes("access_token=") && !r.url().includes("/v1/alerts/stream"));
expect(requestsWithTokenInUrl).toHaveLength(0);

// 3. CSP header present
const res = await page.request.get("/");
expect(res.headers()["content-security-policy"]).toBeDefined();

// 4. No direct backend URL in any network request (all through /api/ proxy except WS)
const directBackendRequests = capturedRequests.filter(r =>
  r.url().includes("localhost:8000") && !r.url().includes("localhost:8010") // S9 direct
);
expect(directBackendRequests).toHaveLength(0); // all should go via /api/* rewrite

// 5. Chat POST: token in header, not URL
const chatRequests = capturedRequests.filter(r => r.url().includes("/chat/stream"));
for (const req of chatRequests) {
  expect(req.url()).not.toContain("token=");
  expect(req.headers()["authorization"]).toMatch(/^Bearer /);
}
```

---

## 12. Migration Strategy

### 12.1 Parallel Operation Phase

During implementation of `worldview-web`, both services run simultaneously:
- `apps/frontend/` — port 3000, unchanged Vite app
- `apps/worldview-web/` — port 3001, new Next.js app

docker-compose addition:
```yaml
worldview-web:
  build: ./apps/worldview-web
  ports:
    - "3001:3000"
  environment:
    API_GATEWAY_URL: http://api-gateway:8000
    NEXT_PUBLIC_WS_BASE_URL: ws://localhost:8010   # S10 direct — NOT S9 (8000)
  depends_on:
    - api-gateway
    - alert-delivery  # S10 — WS connects directly to alert-delivery:8010
```

**Required S9 configuration changes** for worldview-web (add to `api-gateway` service environment or `.env` overlay):
```yaml
api-gateway:
  environment:
    API_GATEWAY_FRONTEND_URL: http://localhost:3001    # was http://localhost:5173
    API_GATEWAY_CORS_ORIGINS: "http://localhost:3001,http://localhost:3000,http://localhost:5173"
```
Without these, OIDC callback will redirect to port 5173 (old Vite app) and CORS preflight will reject all requests from port 3001.

### 12.2 Deprecation Criteria

`apps/frontend/` can be deprecated when ALL of the following are true:
- All protected pages implemented (Dashboard, Instrument Detail, Screener, Portfolio, Workspace, Alerts/News, Chat, Settings)
- Auth flow working end-to-end (login, silent refresh, logout)
- All existing component functionality ported (FlashOverlay, AlertStream, OHLCVChart, ChatUI)
- E2E test suite passing

### 12.3 Deprecation Steps

1. Remove `frontend` from `docker-compose.yml`; rename `worldview-web` → `frontend` entry (port 3000)
2. Update `apps/worldview-web/` Dockerfile if needed
3. Archive (git mv + commit) `apps/frontend/` to `archive/frontend-vite/` or simply delete
4. Update any references in CI, README, docs
5. Update `TRACKING.md`: mark PLAN-0027 cancelled; mark PLAN-0028 replacing it

---

## 13. Observability

### 13.1 Metrics (client-side, future work)

- Core Web Vitals via Next.js built-in analytics (LCP, FID, CLS)
- API error rate: `authClient.ts` logs 4xx/5xx errors to structlog-equivalent browser logger

### 13.2 Error Monitoring

- Console errors suppressed in production; structured logs emitted for uncaught errors
- React ErrorBoundary wraps each major page section; caught errors show `ErrorCard` instead of white screen

### 13.3 Logging Convention

- No `console.log` in production code
- Errors logged with structured context: `{ component, action, error: error.message }`

---

## 14. Open Questions

| # | Question | Classification | Resolution |
|---|----------|---------------|------------|
| OQ-01 | Does S9 have `GET /v1/search/instruments?q=` endpoint? | ~~BLOCKING~~ **RESOLVED** | S9 has `GET /v1/entities/similar` but no text search. PLAN-0028 Wave S9-3 adds `GET /v1/search/instruments` proxying to S3's entity search. |
| OQ-02 | Does S9 have `GET /v1/market/heatmap` for sector performance? | ~~BLOCKING~~ **RESOLVED** | No native endpoint. PLAN-0028 Wave S9-3 adds `GET /v1/market/heatmap` composed from `POST /v1/fundamentals/screen` grouped by GICS sector (11 calls, cached 5 min). |
| OQ-03 | Does S9 have `GET /v1/market/top-movers`? | ~~BLOCKING~~ **RESOLVED** | No native endpoint. PLAN-0028 Wave S9-3 adds `GET /v1/market/top-movers` composed from screener sorted by `daily_return` descending (gainers) and ascending (losers). |
| OQ-04 | Does S9 have `GET /v1/fundamentals/economic-calendar`? | ~~BLOCKING~~ **RESOLVED** | No native endpoint. PLAN-0028 Wave S9-3 adds `GET /v1/fundamentals/economic-calendar` proxying to S7's temporal-events API filtered to economic type within ±7 days. |
| OQ-05 | Does S9 have `GET /v1/auth/register`? | ~~BLOCKING~~ **RESOLVED** | Missing. PLAN-0028 Wave S9-2 adds `GET /v1/auth/register` → 302 redirect to `{oidc_issuer_url}/ui/console/register`. |
| OQ-06 | Does S9 have `GET /v1/signals/ai?limit=` for AiSignals panel? | DEFERRED | No endpoint found. AiSignals panel shows empty state (stub) for MVP. Post-MVP: S6 AI signal scoring endpoint. |
| OQ-07 | Workspace panel persistence: localStorage vs S9 user prefs endpoint? | DEFERRED | localStorage acceptable for MVP (ADR-F-07). S9 prefs endpoint is post-MVP. |
| OQ-08 | Should `register` flow create a Worldview user in S1, or is S1 provisioning done automatically on first login? | DEFERRED | Assume auto-provisioning on OIDC first login (S1 has provisioning endpoint from PRD-0025). |

---

## 15. Estimation

### Implementation Waves (proposed — input to `/plan`)

| Wave | Contents | Dependencies |
|------|---------|-------------|
| F-1 | Bootstrap: `pnpm create next-app`, shadcn/ui init, globals.css (Midnight Pro), fonts, `next.config.ts`, env vars, docker-compose entry | None |
| F-2 | Auth: `AuthContext`, `authClient.ts`, `LoginPage`, `RegisterPage`, `CallbackPage`, `(app)/layout.tsx`, 12 auth tests | F-1 |
| F-3 | Shell: `TopBar`, `Sidebar`, `MarketStatusPill` + `market-schedule.ts` + `useMarketStatus`, `GlobalSearch`, `IndexTicker`, `UtcClock` | F-2 |
| F-4 | Alert stream: `useAlertStream`, `AlertStreamContext`, `FlashOverlay`, `AskAiPanel` | F-2 |
| F-5 | Dashboard page: all 9 dashboard widgets (MorningBriefCard, PortfolioSummary, MarketHeatmap, TopMovers, WatchlistNews, EconomicCalendar, RecentAlerts, AiSignals, TopBets) | F-3, F-4 |
| F-6 | Instrument Detail page: InstrumentHeader, OHLCVChart, FundamentalsBar, all 4 tabs | F-3 |
| F-7 | News components: ArticleCard, RelevanceBadge, ImpactSparkline, TopNewsFilters | F-3 |
| F-8 | Screener page: FilterForm, ResultsTable, gateway methods | F-3 |
| F-9 | Portfolio page: PortfolioChart, HoldingsTable, AddTransactionForm | F-3 |
| F-10 | Chat page: ThreadSidebar, ChatStream (SSE), MorningBriefCard reuse | F-3, F-4 |
| F-11 | Alerts page: AlertsList, AlertCard, SeverityBadge, tabbed layout | F-4 |
| F-12 | Workspace page: WorkspaceGrid, WorkspaceContext, all panel types | F-3, F-4, F-6, F-10 |
| F-13 | Settings page, Landing page (all sections), Register page final wiring | F-2 |
| T-1 | Full test suite: Vitest unit + Playwright E2E, all invariant assertions | F-1..F-13 |

### Resolve BLOCKING OQs (sub-wave before F-5 / F-6)

| OQ | Resolution Action |
|----|-----------------|
| OQ-01 (search) | Check S9 router; if missing, add `GET /v1/search/instruments` to S9 |
| OQ-02 (heatmap) | Check S9; if missing, derive from `POST /v1/fundamentals/screen` grouped by sector |
| OQ-03 (top-movers) | Check S9; if missing, derive from screener sorted by daily_change |
| OQ-04 (economic-calendar) | Check S9; if missing, add endpoint sourcing from S2/EODHD economic events |
| OQ-05 (register) | Check S9; if missing, use direct Zitadel registration URL |

---

## Architecture Compliance Gate

| Rule | Applies | Decision | Compliant |
|------|---------|---------|----------|
| R14 — Frontend → S9 only | YES | All calls via `/api/*` → S9; no direct backend URLs | PASS |
| R8 — No dual writes | N/A | Frontend makes no DB writes directly | N/A |
| R11 — UTC timestamps | YES | All times displayed in UTC; `UtcClock` is UTC; market schedule in UTC | PASS |
| R7 — No cross-service DB | N/A | Frontend has no DB | N/A |
| R10 — UUIDv7 | N/A | Entity IDs come from S9 responses; frontend doesn't generate IDs | N/A |
| Secrets not in code | YES | No API keys in frontend code; all via env vars | PASS |
| Token not in localStorage | YES | access_token in React state only; enforced by test invariants | PASS |

---

*Compounding check: `docs/apps/frontend.md` should be updated to reference PRD-0028 as the active frontend spec once implementation begins. `apps/frontend/.claude-context.md` should note the new service at `apps/worldview-web/`. TRACKING.md updated below.*
