# UI Endpoint Requirements Report

> **Purpose**: Complete mapping of every UI page → required S9 API endpoints.
> **Source**: PRD-0027 (Frontend MVP), canvas designs in `apps/frontend/designs/worldview-mvp_v2.pen`, actual gateway source (`services/api-gateway/src/api_gateway/routes/`), and backend service implementations.
> **Date**: 2026-04-16

---

## TL;DR

| Stat | Count |
|------|-------|
| UI pages/routes | **13** |
| Total unique S9 endpoints required | **53** |
| Endpoints already implemented in S9 | **35** |
| Endpoints required but **missing or incomplete** | **18** |
| Real-time streams (WebSocket + SSE) | **2** |
| Backend services touched | **7** (S1, S3, S5, S6, S7, S8, S10) |

Frontend hits S9 exclusively — no direct backend service calls.

---

## 1. Page Inventory

| # | Page | Route | Auth | Canvas State |
|---|------|-------|------|-------------|
| 1 | Landing | `/` | public | — |
| 2 | Login | `/login` | public | — |
| 3 | OIDC Callback | `/callback` | public | — |
| 4 | Dashboard | `/dashboard` | protected | 02-Dashboard A/B/C |
| 5 | Workspace Terminal | `/workspace` | protected | 09-Workspace |
| 6 | Company Detail | `/companies/{id}` | protected | 03-Instrument Detail (tabs) |
| 7 | Companies List | `/companies` | protected | — |
| 8 | Portfolio | `/portfolio` | protected | 06-Portfolio |
| 9 | News | `/news` | protected | 04-Intelligence / 05-News |
| 10 | Screener | `/screener` | protected | 07-Screener A–F |
| 11 | Chat | `/chat` | protected | 08-Chat / Quick-Ask |
| 12 | Map | `/map` | protected | placeholder |
| 13 | Feedback Dialog | global | protected | — |

---

## 2. Endpoint Requirements per Page

### 2.1 Landing / Login / Callback

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/auth/login` | GET | S9 | ✅ implemented |
| `/v1/auth/callback` | GET | S9 | ✅ implemented |
| `/v1/auth/refresh` | POST | S9 | ✅ implemented |
| `/v1/auth/me` | GET | S9 | ✅ implemented |
| `/v1/auth/logout` | POST | S9 | ✅ implemented |

All auth flow fully covered.

---

### 2.2 Dashboard (`/dashboard`)

Components: MorningBriefCard · PortfolioSummaryCard · MarketHeatmapCard · TopMoversCard · MyHoldings · RecentAlertsCard · MarketPulseCard · WatchlistNewsCard · IntelligenceStreamCard · EconomicCalendarCard

| Endpoint | Method | Service | Status | Cache |
|----------|--------|---------|--------|-------|
| `/v1/briefings/morning` | GET | S8 | ⚠️ **missing** | 24h Valkey |
| `/v1/portfolios` | GET | S1 | ⚠️ **missing from S9 proxy** | private |
| `/v1/holdings/{portfolio_id}` | GET | S1 | ⚠️ **missing from S9 proxy** | private |
| `/v1/quotes/batch` | POST | S3 | ✅ implemented (S3 native, **no S9 proxy**) | 30s |
| `/v1/quotes/{id}` | GET | S3 | ✅ implemented (S3 native, **no S9 proxy**) | 5s |
| `/v1/alerts/pending?limit=5` | GET | S10 | ✅ implemented | — |
| `/v1/news/relevant?limit=5` | GET | S5 | ✅ implemented | 30s |
| `/v1/temporal-events?limit=5` | GET | S7 | ⚠️ **missing from S9 proxy** | 5min |
| `/v1/signals` (for Intelligence Stream) | GET | S6 | ⚠️ **missing from S9 proxy, needs pagination** | 30s |
| **WS** `/api/v1/alerts/stream?token=...` | WS | S10 | ⚠️ **missing** | — |

**Gap**: Dashboard needs 6 endpoints that are either not in gateway proxy router or not implemented at all.

---

### 2.3 Workspace (`/workspace`)

11 panel types, drag-and-drop `react-grid-layout`.

| Panel | Endpoint | Method | Service | Status |
|-------|----------|--------|---------|--------|
| Chart | `/v1/ohlcv/{id}` | GET | S3 | ⚠️ **no S9 proxy** |
| News Feed | `/v1/news/relevant` or `/v1/entities/{id}/articles` | GET | S5/S6 | partial |
| Alerts | `/v1/alerts/pending` + WS stream | GET+WS | S10 | partial |
| Fundamentals | `/v1/fundamentals/{id}/highlights` | GET | S3 | ⚠️ **no S9 proxy** |
| Chat | `/v1/chat/stream` | POST SSE | S8 | ✅ implemented |
| Prediction Markets | `/v1/signals/prediction-markets` | GET | S3 | ✅ implemented |
| Screener (mini) | `/v1/fundamentals/screen` | POST | S3 | ✅ implemented |
| Entity Graph | `/v1/entities/{id}/graph` | GET | S7 | ⚠️ **no S9 proxy** |
| Heatmap | `/v1/quotes/batch` (sector ETFs) | POST | S3 | ⚠️ **no S9 proxy** |
| Portfolio Summary | `/v1/portfolios` + `/v1/quotes/batch` | GET+POST | S1/S3 | ⚠️ **no S9 proxy** |
| Macro Events | `/v1/temporal-events` | GET | S7 | ⚠️ **no S9 proxy** |

---

### 2.4 Company Detail (`/companies/{instrument_id}`)

5 tabs: Overview · News · Fundamentals · Intelligence · Chat

#### Header (all tabs)
| Endpoint | Service | Status |
|----------|---------|--------|
| `/v1/instruments/{id}/context` (composed) | S9 | ⚠️ **not implemented** |
| `/v1/quotes/{id}` | S3 | ⚠️ no S9 proxy |
| `/v1/fundamentals/{id}/highlights` | S3 | ⚠️ no S9 proxy |
| `POST /v1/watchlists/{id}/members` | S1 | ⚠️ **no S9 proxy** |

#### Overview tab
| Endpoint | Service | Status |
|----------|---------|--------|
| `/v1/briefings/instrument/{id}` | S8 | ⚠️ **missing** |
| `/v1/fundamentals/{id}/highlights` | S3 | ⚠️ no S9 proxy |
| `/v1/fundamentals/{id}/analyst-consensus` | S3 | ⚠️ no S9 proxy |
| `/v1/fundamentals/{id}/earnings-trend` | S3 | ⚠️ no S9 proxy |
| `/v1/ohlcv/{id}` | S3 | ⚠️ no S9 proxy |

#### News tab
| Endpoint | Service | Status |
|----------|---------|--------|
| `/v1/entities/{id}/articles` | S6 | ⚠️ **no S9 proxy** |
| `/v1/news/relevant` (fallback) | S5 | ✅ implemented |

#### Fundamentals tab — 12 sections
All map to `/v1/fundamentals/{id}/{section}` on S3. **Currently NO S9 proxy for any section.**
Sections: income-statement, balance-sheet, cash-flow, highlights, valuation, analyst-consensus, dividends, earnings, company-profile, institutional-holders, fund-holders, insider-transactions-snapshot.

#### Intelligence tab
| Endpoint | Service | Status |
|----------|---------|--------|
| `/v1/entities/{id}/graph?hops=2` | S7 | ⚠️ **no S9 proxy** |
| `POST /v1/entities/similar` | S7 | ✅ implemented |
| `/v1/entities/{id}/contradictions` | S7 | ⚠️ **no S9 proxy** |
| `/v1/signals/prediction-markets?query={ticker}` | S3 | ✅ implemented |
| `POST /v1/claims/search` | S7 | ⚠️ **no S9 proxy** |
| `POST /v1/events/search` | S7 | ⚠️ **no S9 proxy** |

#### Chat tab
| Endpoint | Service | Status |
|----------|---------|--------|
| `POST /v1/chat/stream` (SSE) | S8 | ✅ implemented |
| `POST /v1/threads` | S8 | ✅ implemented |
| `GET /v1/threads` | S8 | ✅ implemented |

---

### 2.5 Companies List (`/companies`)

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/instruments?query=...&exchange=...&limit=50&offset=...` | GET | S3 | ⚠️ **no S9 proxy** |
| `POST /v1/watchlists/{id}/members` | POST | S1 | ⚠️ **no S9 proxy** |

---

### 2.6 Portfolio (`/portfolio`)

Strategy cards + 5 tabs per strategy: Holdings · Transactions · Analytics · Watchlists · Settings

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/portfolios` | GET, POST | S1 | ⚠️ **no S9 proxy** |
| `/v1/holdings/{portfolio_id}` | GET | S1 | ⚠️ **no S9 proxy** |
| `/v1/transactions` | GET, POST | S1 | ⚠️ **no S9 proxy** |
| `/v1/quotes/batch` | POST | S3 | ⚠️ **no S9 proxy** |
| `/v1/watchlists` | GET, POST | S1 | ⚠️ **no S9 proxy** |
| `/v1/watchlists/{id}/members` | POST, DELETE | S1 | ⚠️ **no S9 proxy** |
| `/v1/watchlists/{id}` | DELETE | S1 | ⚠️ **no S9 proxy** |
| `/v1/brokerage-connections` (CRUD + callback + sync-errors) | all | S1 | ✅ implemented |

---

### 2.7 News (`/news`)

Two tabs: Feed (chronological) · Top Today (ranked)

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/news/relevant` | GET | S5 | ✅ implemented |
| `/v1/news/top?hours=48&min_display_score=...` | GET | S6 | ⚠️ **missing (PRD-0026 pending)** |

---

### 2.8 Screener (`/screener`) — **THE PAGE WE JUST DESIGNED (6 STATES)**

Needs metric catalog + execution + field metadata. All in S3, all proxied via S9.

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/fundamentals/screen/fields` | GET | S3 | ✅ implemented |
| `POST /v1/fundamentals/screen` | POST | S3 | ✅ implemented |
| `GET /v1/fundamentals/timeseries` | GET | S3 | ✅ implemented |
| `GET /v1/fundamentals/metrics/{id}` | GET | S3 | ⚠️ **S3 native only, no S9 proxy** |
| `/v1/instruments/{id}/context` (sector lookup) | GET | S9 composed | ⚠️ not implemented |

Additional endpoints needed for **State D (My Screens)** — frontend-only (localStorage). No backend required.

**For Signal-tier column** added in this session: needs `/v1/signals?instrument_id={id}&limit=1` → **no S9 proxy, S6 needs pagination added**.

---

### 2.9 Chat (`/chat`)

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `POST /v1/chat/stream` (SSE) | POST | S8 | ✅ implemented |
| `GET /v1/threads` | GET | S8 | ✅ implemented |
| `POST /v1/threads` | POST | S8 | ✅ implemented |
| `GET /v1/threads/{id}` | GET | S8 | ✅ implemented |
| `DELETE /v1/threads/{id}` | DELETE | S8 | ✅ implemented |
| `POST /v1/feedback` | POST | S9 | ⚠️ **not in gateway** |

---

### 2.10 Map & Feedback Widget

| Endpoint | Method | Service | Status |
|----------|--------|---------|--------|
| `/v1/map/layers` | GET | S9 | ✅ placeholder only |
| `POST /v1/feedback` | POST | S9 | ⚠️ **missing** |

---

## 3. Real-Time Endpoints

| Endpoint | Type | Used By | Status |
|----------|------|---------|--------|
| `/api/v1/alerts/stream?token=...` | WebSocket | Dashboard, Workspace AlertsPanel, TopBar badge | ⚠️ **not implemented** |
| `POST /v1/chat/stream` | Server-Sent Events | Chat, Company Chat tab, Workspace ChatPanel | ✅ implemented |

---

## 4. Gap Analysis — What Needs to Be Built

### 4.1 Missing S9 Proxy Routes (18 endpoints)
These exist in backend services but the gateway lacks proxy routes:

**Market Data (S3) — pass-through proxies needed:**
- `GET /v1/instruments` (list + search)
- `GET /v1/instruments/{id}`
- `GET /v1/ohlcv/{id}`
- `GET /v1/quotes/{id}`
- `POST /v1/quotes/batch`
- `GET /v1/fundamentals/{id}/{section}` (12 section routes)
- `GET /v1/fundamentals/metrics/{id}`

**Portfolio (S1) — pass-through proxies needed:**
- `GET/POST /v1/portfolios`
- `GET /v1/holdings/{portfolio_id}`
- `GET/POST /v1/transactions`
- `GET/POST /v1/watchlists` + members CRUD

**Knowledge Graph (S7) — pass-through proxies needed:**
- `GET /v1/entities/{id}/graph`
- `GET /v1/entities/{id}/contradictions`
- `POST /v1/claims/search`
- `POST /v1/events/search`
- `GET /v1/temporal-events`

**Content / NLP (S6) — pass-through proxies needed:**
- `GET /v1/entities/{id}/articles`
- `GET /v1/signals` (+ add pagination to S6 first)

### 4.2 Missing Composed Endpoints (S9 BFF work)
- `GET /v1/instruments/{id}/context` (originally ADR-F-12; post-F2 see [ADR-F-16](../architecture/decisions/ADR-F-16-instrument-entity-id-unification.md)) — single call returning instrument + entity_id + sector/industry/exchange. Post-F2: `entity_id == instrument_id` for tradable kinds; the endpoint still returns both for backwards compatibility (v1.1 drops the redundant field).
- `GET /v1/companies/{id}/overview` — partially implemented, needs expansion

### 4.3 Missing Backend Features
- **S8 Briefings**: `/v1/briefings/morning` and `/v1/briefings/instrument/{id}` — backend not implemented
- **S10 WebSocket**: `/api/v1/alerts/stream` — no WS implementation yet
- **S6 News Top**: `/v1/news/top` — depends on PRD-0026 (multi-window impact scores, LLM relevance)
- **S6 Pagination**: `GET /v1/signals` needs `limit` + `offset` params
- **S9 Feedback**: `POST /v1/feedback` — no route exists

### 4.4 Data Gaps (Backend Limitations Surfaced in Designs)
- **Analyst Rating** column in Screener — requires `/v1/fundamentals/{id}/analyst-consensus` (exists, needs proxy)
- **RSI, MACD, Bollinger Bands** — not computed by backend, must be client-computed from OHLCV
- **Sentiment polarity** — not implemented (future PRD)
- **Earnings calendar, IPO age, short interest, options OI** — not ingested

---

## 5. Priority Order for Implementation

### Phase 1 — Unblock Dashboard + Screener (most critical)
1. Add S9 proxy routes for all S3 fundamentals (12 sections + highlights + metrics)
2. Add S9 proxy for `/v1/quotes/batch`, `/v1/quotes/{id}`, `/v1/ohlcv/{id}`
3. Add S9 proxy for `/v1/instruments` and `/v1/instruments/{id}`
4. Implement `/v1/instruments/{id}/context` composition endpoint
5. Add pagination to S6 `/v1/signals` + gateway proxy

### Phase 2 — Portfolio & Watchlists
6. S9 proxies for S1 portfolios, holdings, transactions, watchlists
7. Wire `POST /v1/watchlists/{id}/members` from Company Detail

### Phase 3 — Intelligence Features
8. S9 proxies for S7 entities/graph, contradictions, claims/search, events/search, temporal-events
9. S9 proxy for S6 entities/{id}/articles
10. Implement S8 Briefings (morning + instrument)

### Phase 4 — Real-Time & News
11. S10 WebSocket `/api/v1/alerts/stream`
12. S6 `/v1/news/top` (depends on PRD-0026)
13. S9 `POST /v1/feedback`

---

## 6. Summary

- **35 of 53** required endpoints are already implemented
- **15 of 18** missing endpoints are simple pass-through proxies in S9 (backend exists, gateway routes missing)
- **3 missing features** require backend implementation: S8 Briefings, S10 WebSocket alerts, S6 News Top
- **1 composition endpoint** requires BFF logic: `/v1/instruments/{id}/context`

Most of the UI can go live once S9 gets its missing proxy routes. The long-pole items are S8 Briefings and S10 WebSocket streaming.
