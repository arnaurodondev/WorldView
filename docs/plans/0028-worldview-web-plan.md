# PLAN-0028 — Worldview Web Frontend Implementation Plan

> **PRD**: `docs/specs/0028-worldview-web-frontend.md`
> **Status**: draft
> **Created**: 2026-04-17
> **Total waves**: 17 (3 S9 backend + 14 frontend)
> **Total tasks**: ~72

---

## Pre-Flight Gate

| Check | Status | Notes |
|-------|--------|-------|
| Unresolved BLOCKING OQs | ✅ RESOLVED | All 5 OQs resolved by audit — see §OQ Resolution below |
| Cross-plan conflicts | PASS | No other in-progress plan touches `apps/worldview-web/` or S9 proxy routes |
| PRD recency | PASS | PRD written 2026-04-17 (today) |
| Architecture compliance | PASS | Frontend → S9 only; token in React state; dark mode permanent |
| External API reality check | N/A | No external APIs — all calls go through S9 |

### BLOCKING OQ Resolution (from S9 source audit)

| OQ | Endpoint | S9 Status | Downstream Exists? | Resolution |
|----|----------|-----------|-------------------|------------|
| OQ-01 | `GET /v1/search/instruments?q=` | **MISSING** | S3 `GET /instruments` (with filters) | Add to S9 Wave S9-3 |
| OQ-02 | `GET /v1/market/heatmap` | **MISSING** | No dedicated endpoint | S9 Wave S9-3: compose from `POST /fundamentals/screen` grouped by GICS sector |
| OQ-03 | `GET /v1/market/top-movers` | **MISSING** | No dedicated endpoint | S9 Wave S9-3: compose from screener sorted by daily_return |
| OQ-04 | `GET /v1/fundamentals/economic-calendar` | **MISSING** | S7 `GET /api/v1/temporal-events` | Add proxy to S7 in S9 Wave S9-3 |
| OQ-05 | `GET /v1/auth/register` | **MISSING** | Zitadel self-registration URL | Add redirect in S9 Wave S9-2 auth router |

### Additional Missing S9 Routes (discovered during audit)

Beyond the 5 BLOCKING OQs, the following routes are referenced in PRD-0028 §6.2 but absent from `services/api-gateway/src/api_gateway/routes/proxy.py`:

| Endpoint | Downstream | Wave |
|----------|-----------|------|
| `GET /v1/ohlcv/{id}` | S3 `GET /ohlcv/{instrument_id}` | S9-1 |
| `GET /v1/quotes/{id}` | S3 `GET /quotes/{instrument_id}` | S9-1 |
| `POST /v1/quotes/batch` | S3 `POST /quotes/batch` | S9-1 |
| `GET /v1/fundamentals/{id}` | S3 `GET /fundamentals/{instrument_id}` | S9-1 |
| `GET /v1/entities/{id}/graph` | S7 `GET /api/v1/entities/{entity_id}/graph` | S9-1 |
| `GET /v1/entities/{id}/contradictions` | S7 `GET /api/v1/entities/{entity_id}/contradictions` | S9-1 |
| `GET /v1/news/top` | content_store (PRD-0026 stub) | S9-1 |
| `GET /v1/news/entity/{entityId}` | content_store (PRD-0026 stub) | S9-1 |
| `GET /v1/briefings/morning` | S8 (stub — endpoint not yet in S8) | S9-1 |
| `GET /v1/briefings/instrument/{id}` | S8 (stub — endpoint not yet in S8) | S9-1 |
| `GET /v1/portfolios` | S1 `GET /portfolios` | S9-2 |
| `GET /v1/holdings/{portfolioId}` | S1 `GET /holdings/{portfolio_id}` | S9-2 |
| `GET /v1/transactions` | S1 `GET /transactions` | S9-2 |
| `POST /v1/transactions` | S1 `POST /transactions` | S9-2 |
| `GET /v1/watchlists` | S1 `GET /watchlists` | S9-2 |
| `POST /v1/watchlists` | S1 `POST /watchlists` | S9-2 |
| `GET /v1/watchlists/{id}` | S1 `GET /watchlists/{watchlist_id}` | S9-2 |
| `DELETE /v1/watchlists/{id}` | S1 `DELETE /watchlists/{watchlist_id}` | S9-2 |
| `POST /v1/watchlists/{id}/members` | S1 `POST /watchlists/{watchlist_id}/members` | S9-2 |
| `DELETE /v1/watchlists/{id}/members/{entityId}` | S1 `DELETE /watchlists/{watchlist_id}/members/{entity_id}` | S9-2 |

---

## Dependency Graph

```
S9-1 (market data + entity + news + briefing proxy routes)
S9-2 (portfolio + watchlist + auth/register proxy routes)  ─┐
S9-3 (composed: search, heatmap, top-movers, calendar)     ─┤
         │                                                   │
         ▼                                                   │
F-1 (Bootstrap apps/worldview-web/ — no S9 dep)             │
         │                                                   │
F-2 (Auth layer) ──────────────────────────────────────────┘│
         │                                                    │
    ┌────┴────┐                                               │
F-3 (Shell)  F-4 (Alert stream)                              │
    │             │                                           │
    └─────┬───────┘                                           │
          │                                                   │
F-5 (Dashboard) ← depends S9-1, S9-2, S9-3 all done        ─┘
F-6 (Instrument Detail) ← depends S9-1
F-7 (News components) ← depends S9-1
F-8 (Screener) ← depends S9 screener routes (already in S9)
F-9 (Portfolio) ← depends S9-2
F-10 (Chat) ← depends S9 chat routes (already in S9)
F-11 (Alerts) ← depends S9 alert routes (already in S9)
F-12 (Workspace) ← depends F-3, F-4, F-6, F-10
F-13 (Settings + Landing) ← depends F-2
T-1 (Full test suite) ← depends F-1..F-13
```

**Parallelisable groups:**
- S9-1, S9-2 can run in parallel (different route files)
- F-3 and F-4 can run in parallel after F-2
- F-6, F-7, F-8, F-9, F-10, F-11 can run in parallel after F-3
- F-12, F-13 are later-stage and can partially parallel

**Critical path**: F-1 → F-2 → F-3/F-4 → F-5 → F-12 → T-1

---

## Execution Order

| # | Wave | Status | Depends On | Effort |
|---|------|--------|-----------|--------|
| 1 | S9-1: Market Data + Entity + News proxy routes ✅ | **done** | none | 45 min |
| 2 | S9-2: Portfolio + Watchlist + Auth register routes ✅ | **done** | none | 45 min |
| 3 | S9-3: Composed endpoints (OQ resolution) ✅ | **done** | none | 60 min |
| 4 | F-1: Bootstrap apps/worldview-web/ | pending | none | 60 min |
| 5 | F-2: Auth layer | pending | F-1 | 75 min |
| 6 | F-3: Shell (TopBar, Sidebar, MarketStatusPill) | pending | F-2 | 90 min |
| 7 | F-4: Alert stream + FlashOverlay + AskAiPanel | pending | F-2 | 60 min |
| 8 | F-5: Dashboard page (9 widgets) | pending | F-3, F-4, S9-1/2/3 | 90 min |
| 9 | F-6: Instrument Detail (chart, 4 tabs, entity graph) | pending | F-3, S9-1 | 90 min |
| 10 | F-7: News components | pending | F-3, S9-1 | 45 min |
| 11 | F-8: Screener page | pending | F-3 | 45 min |
| 12 | F-9: Portfolio page | pending | F-3, S9-2 | 60 min |
| 13 | F-10: Chat page (SSE stream) | pending | F-3, F-4 | 60 min |
| 14 | F-11: Alerts page | pending | F-4 | 45 min |
| 15 | F-12: Workspace page (8 panel types) | pending | F-3, F-4, F-6, F-10 | 90 min |
| 16 | F-13: Settings + Landing page | pending | F-2 | 60 min |
| 17 | T-1: Full test suite | pending | F-1..F-13 | 90 min |

**Total estimated effort**: ~17.5 hours (agent execution time)

---

## Sub-Plan A: S9 Proxy Route Additions

### Wave S9-1: Market Data, Entity, News, Briefing Routes ✅

**Status**: **DONE** — 2026-04-18 · 127 tests pass · lint + typecheck clean
**Goal**: Add proxy routes to S9 for OHLCV, quotes, fundamentals, entity graph/contradictions, news, and briefings — all of which exist in downstream services but are missing from `proxy.py`.
**Depends on**: none
**Estimated effort**: 45 min
**Architecture layer**: API (S9 gateway extension)

#### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — existing pattern to follow exactly
- `services/api-gateway/src/api_gateway/clients.py` — ServiceClients fields available
- `services/api-gateway/src/api_gateway/app.py` — confirms `knowledge_graph` and `content_store` clients exist
- `docs/specs/0028-worldview-web-frontend.md §6.2` — full list of expected routes

#### Tasks

##### T-S9-1-01: OHLCV, Quotes, and Fundamentals Proxy Routes
**Type**: impl
**depends_on**: none
**blocks**: T-F6-02 (chart), T-F9-01 (portfolio quotes), T-F3-03 (index tickers)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Instrument / Market Data Routes

**What to build**: Add five pass-through proxy endpoints to `proxy.py` that proxy to `clients.market_data`. Follow the exact pattern of existing routes (e.g., `get_pending_alerts`): forward `_auth_headers(request)`, proxy query params with `dict(request.query_params)`, return `Response(content=resp.content, status_code=resp.status_code, media_type="application/json")`.

**Endpoints to add**:
```python
GET  /v1/ohlcv/{instrument_id}          → market_data  GET  /ohlcv/{instrument_id}
GET  /v1/quotes/{instrument_id}         → market_data  GET  /quotes/{instrument_id}
POST /v1/quotes/batch                   → market_data  POST /quotes/batch
GET  /v1/fundamentals/{instrument_id}   → market_data  GET  /fundamentals/{instrument_id}
```

**Auth note**: All four routes require authentication (forward `_auth_headers`). Check `request.state.user` and raise `HTTPException(401)` if not authenticated — same pattern as `get_pending_alerts`.

**Docstrings**: Copy docstring format from existing proxy routes, mentioning the downstream service and return shape.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_proxy_authenticated` | 200 with valid auth headers forwarded to market_data | unit |
| `test_quotes_batch_proxy` | POST body forwarded correctly | unit |
| `test_fundamentals_proxy_unauthenticated` | 401 when no user in request.state | unit |

**Acceptance criteria**:
- [ ] `GET /v1/ohlcv/{id}` added with auth check + forward to `clients.market_data`
- [ ] `GET /v1/quotes/{id}` added with auth check
- [ ] `POST /v1/quotes/batch` added with auth check + body forward
- [ ] `GET /v1/fundamentals/{id}` added with auth check + query param forward
- [ ] All routes use `Response(content=..., status_code=..., media_type="application/json")` — not JSONResponse
- [ ] Existing tests still pass: `cd services/api-gateway && python -m pytest tests/ -v`

---

##### T-S9-1-02: Entity Graph and Contradictions Proxy Routes
**Type**: impl
**depends_on**: none
**blocks**: T-F6-04 (EntityGraph), T-F6-05 (IntelligenceTab)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Instrument / Market Data Routes

**What to build**: Two proxy routes to `clients.knowledge_graph`. The S7 knowledge graph service already exposes these endpoints at `/api/v1/entities/{entity_id}/graph` and `/api/v1/entities/{entity_id}/contradictions`.

**Endpoints to add**:
```python
GET /v1/entities/{entity_id}/graph           → knowledge_graph  GET /api/v1/entities/{entity_id}/graph
GET /v1/entities/{entity_id}/contradictions  → knowledge_graph  GET /api/v1/entities/{entity_id}/contradictions
```

**Query param forwarding**: Both routes should forward query params (graph takes `depth=2` param).

**Auth**: Both require authentication.

**Acceptance criteria**:
- [ ] `/v1/entities/{entity_id}/graph` proxies to S7 with `?depth=` query param forwarded
- [ ] `/v1/entities/{entity_id}/contradictions` proxies to S7
- [ ] Both require `request.state.user` (401 if missing)

---

##### T-S9-1-03: News Top + News Entity Proxy Routes
**Type**: impl
**depends_on**: none
**blocks**: T-F5-04 (WatchlistNews), T-F6-03 (NewsTab), T-F11-01 (Alerts/News page)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 News Routes

**What to build**: Two news proxy routes. These depend on PRD-0026 for the full ranked/scored news implementation. For now, proxy to `clients.content_store` at the best available endpoint; the response shape will be enriched when PRD-0026 is implemented.

**Endpoints to add**:
```python
GET /v1/news/top?hours=&limit=&offset=     → content_store  GET /v1/articles/relevant  (PRD-0026 TODO)
GET /v1/news/entity/{entity_id}?...        → content_store  GET /v1/articles?entity_id=...
```

**Implementation note**: Add a `# TODO(PRD-0026): update downstream URL once news-intelligence endpoint is live` comment. The frontend gracefully handles the current response shape — just needs valid article data.

**Auth**: `news/top` is public (no auth check). `news/entity` requires auth.

**Acceptance criteria**:
- [ ] `/v1/news/top` proxies to content_store; no auth required
- [ ] `/v1/news/entity/{entity_id}` proxies to content_store; auth required; query params forwarded
- [ ] Both routes have TODO comment for PRD-0026 update
- [ ] ruff/mypy pass

---

##### T-S9-1-04: Briefings Proxy Routes (Morning + Instrument)
**Type**: impl
**depends_on**: none
**blocks**: T-F5-01 (MorningBriefCard), T-F6-05 (IntelligenceTab brief)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Dashboard Routes

**What to build**: Two briefing routes. S8 currently exposes `POST /internal/v1/briefings` (email digest only) and no GET briefing endpoints. Add S9 proxy routes that will proxy to S8 once S8 implements GET briefing endpoints. For now, return a 503 stub response with a clear error message so the frontend shows "Brief unavailable — retry" state.

**Endpoints to add**:
```python
GET /v1/briefings/morning                   → S8  GET /api/v1/briefings/morning  (S8 TODO)
GET /v1/briefings/instrument/{entity_id}    → S8  GET /api/v1/briefings/instrument/{entity_id}  (S8 TODO)
```

**Implementation**:
```python
@router.get("/briefings/morning")
async def morning_briefing(request: Request) -> Any:
    """Proxy GET /api/v1/briefings/morning → S8 RAG/Chat service.

    TODO: S8 does not yet expose GET briefing endpoints (PRD-0015/0016 pending).
    This route stubs with 503 until S8 adds GET /api/v1/briefings/morning.
    The frontend MorningBriefCard handles 503 with a retry state gracefully.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get("/api/v1/briefings/morning", headers=headers)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

**Note**: When S8 adds the briefing endpoints, the S9 proxy route above needs NO change — it will automatically work.

**Acceptance criteria**:
- [ ] `/v1/briefings/morning` returns whatever S8 returns (currently likely 404 until S8 adds the endpoint)
- [ ] `/v1/briefings/instrument/{id}` same pattern
- [ ] Both require auth
- [ ] TODO comment references S8 pending endpoint implementation

---

##### T-S9-1-05: S9 Tests for New Wave S9-1 Routes
**Type**: test
**depends_on**: T-S9-1-01, T-S9-1-02, T-S9-1-03, T-S9-1-04
**blocks**: none
**Target files**: `services/api-gateway/tests/`
**PRD reference**: §11 Test Strategy

**What to build**: Add unit/integration tests for all S9-1 routes. Follow existing test patterns in the api-gateway tests directory.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_proxy_requires_auth` | 401 when request.state.user absent | unit |
| `test_ohlcv_proxy_forwards_query_params` | query params forwarded to downstream | unit |
| `test_quotes_batch_body_forwarded` | request body forwarded unchanged | unit |
| `test_entity_graph_depth_param` | ?depth=2 forwarded to knowledge_graph | unit |
| `test_news_top_no_auth_required` | 200 without auth | unit |
| `test_briefings_requires_auth` | 401 without auth | unit |

**Acceptance criteria**:
- [ ] All existing api-gateway tests continue to pass
- [ ] ≥ 6 new tests added
- [ ] `cd services/api-gateway && python -m pytest tests/ -v` shows all pass

#### Validation Gate
- [ ] `cd services/api-gateway && ruff check . --fix && ruff format .`
- [ ] `cd services/api-gateway && mypy src/`
- [ ] `cd services/api-gateway && python -m pytest tests/ -v` — all pass
- [ ] All 4 new route groups present in proxy.py
- [ ] No existing proxy routes broken

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None — only additions | Adding new routes to proxy.py is non-breaking | None |

#### Regression Guardrails
- **BP-144**: `RateLimitMiddleware` stores `valkey_client=None` at construction — new routes go through the same middleware; no new middleware added so this doesn't regress
- **BP-145**: `OIDCAuthMiddleware jwt.decode()` issuer= param — new routes don't touch auth middleware; existing protection applies
- **BP-159**: `BaseHTTPMiddleware` dual-instance `startup()` bypass — don't add any new middleware instances in this wave

---

### Wave S9-2: Portfolio, Watchlist, Auth Register Routes ✅

**Status**: **DONE** — 2026-04-18 · 127 tests pass · lint + typecheck clean
**Goal**: Add proxy routes to S9 for portfolio, holdings, transactions, all watchlist CRUD, and the new `GET /v1/auth/register` redirect endpoint.
**Depends on**: none (independent of S9-1)
**Estimated effort**: 45 min
**Architecture layer**: API (S9 gateway extension)

#### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — existing proxy pattern
- `services/api-gateway/src/api_gateway/routes/auth.py` — existing auth routes pattern (for register endpoint)
- `services/api-gateway/src/api_gateway/config.py` — Settings fields (for Zitadel registration URL)
- `services/portfolio/src/portfolio/api/` — confirm S1 endpoint paths and header requirements

#### Tasks

##### T-S9-2-01: Portfolio and Holdings Proxy Routes
**Type**: impl
**depends_on**: none
**blocks**: T-F9-01 (Portfolio page)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Portfolio Routes

**What to build**: Proxy routes for portfolio and holdings. S1 requires `X-Owner-ID` and `X-Tenant-ID` headers — these must be forwarded from `_auth_headers(request)` (the function already extracts `X-User-Id` and `X-Tenant-Id` from `request.state.user`).

**Note on header naming**: S1 uses `X-Owner-ID` but `_auth_headers()` produces `X-User-Id`. Verify in S1's route handler what exact header name is expected. If S1 expects `X-Owner-ID`, either: (a) add that mapping to `_auth_headers`, or (b) add explicit header mapping in the portfolio routes. Check `services/portfolio/src/portfolio/api/routes/portfolios.py` before implementing.

**Endpoints to add**:
```python
GET /v1/portfolios                    → S1  GET /api/v1/portfolios
GET /v1/holdings/{portfolio_id}       → S1  GET /api/v1/holdings/{portfolio_id}
GET /v1/transactions                  → S1  GET /api/v1/transactions  (query params: portfolio_id, limit, offset)
POST /v1/transactions                 → S1  POST /api/v1/transactions
```

**Auth**: All require authentication.

**Acceptance criteria**:
- [ ] All 4 routes added with auth checks
- [ ] Query params forwarded for list endpoints
- [ ] POST body forwarded for `POST /v1/transactions`
- [ ] Header mapping verified against S1's actual expected headers

---

##### T-S9-2-02: Watchlist CRUD Proxy Routes
**Type**: impl
**depends_on**: none
**blocks**: T-F3-02 (Sidebar watchlist), T-F5-07 (WatchlistNews panel)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Watchlist Routes

**What to build**: Full watchlist CRUD — 7 endpoints proxying to S1. Same auth header pattern as portfolio routes.

**Endpoints to add**:
```python
GET    /v1/watchlists                              → S1  GET    /api/v1/watchlists
POST   /v1/watchlists                              → S1  POST   /api/v1/watchlists
GET    /v1/watchlists/{watchlist_id}               → S1  GET    /api/v1/watchlists/{watchlist_id}
DELETE /v1/watchlists/{watchlist_id}               → S1  DELETE /api/v1/watchlists/{watchlist_id}
POST   /v1/watchlists/{watchlist_id}/members       → S1  POST   /api/v1/watchlists/{watchlist_id}/members
DELETE /v1/watchlists/{watchlist_id}/members/{entity_id}  → S1  DELETE equivalent
```

**Note on PATCH**: PRD-0028 lists `PATCH /v1/watchlists/:id` for rename. S1 does not expose a watchlist rename endpoint (only portfolio rename exists). Omit PATCH for now; add a TODO comment. The Sidebar will not support rename in MVP.

**Acceptance criteria**:
- [ ] All 6 watchlist routes added (no PATCH — deferred)
- [ ] DELETE routes use `status_code=200` on the S9 side (even if S1 returns 204 — follow BP-064 pattern)
- [ ] All require auth

---

##### T-S9-2-03: Auth Register Endpoint
**Type**: impl
**depends_on**: none
**blocks**: T-F2-03 (RegisterPage)
**Target files**: `services/api-gateway/src/api_gateway/routes/auth.py`
**PRD reference**: §6.5 Page: Register

**What to build**: Add `GET /v1/auth/register` to the auth router. This endpoint redirects the browser to Zitadel's self-registration page. Zitadel Cloud registration URL pattern: `{issuer}/ui/console/register` (confirm exact path from Zitadel dashboard — use `{settings.oidc_issuer_url}/ui/console/register` as default).

**Implementation**:
```python
@router.get("/register")
async def register(request: Request) -> Response:
    """Redirect browser to Zitadel self-registration page (ADR-F-05, OQ-05).

    Zitadel self-registration URL: {issuer}/ui/console/register.
    If OIDC discovery is unavailable, return 503 rather than 500.
    """
    settings = request.app.state.settings
    registration_url = f"{settings.oidc_issuer_url}/ui/console/register"
    return RedirectResponse(url=registration_url, status_code=302)
```

**Acceptance criteria**:
- [ ] `GET /v1/auth/register` redirects to `{oidc_issuer_url}/ui/console/register` with 302
- [ ] No auth required (public endpoint)
- [ ] Test: `test_register_redirect_302`

---

##### T-S9-2-04: WebSocket Short-Lived Token Endpoint + S10 Middleware Update
**Type**: impl
**depends_on**: none
**blocks**: T-F4-01 (useAlertStream)
**Target files**:
- `services/api-gateway/src/api_gateway/routes/auth.py` — add `GET /v1/auth/ws-token`
- `services/alert/src/alert/infrastructure/middleware/internal_jwt.py` — add `?token=` fallback for WS upgrades
**PRD reference**: §6.2 Auth Routes (`GET /v1/auth/ws-token`), ADR-F-02

**What to build**:

**Part A — S9 `GET /v1/auth/ws-token`**: Issues a short-lived (30s TTL) RS256 internal JWT scoped to `alerts:stream`. The frontend calls this endpoint (with its regular Bearer access token) before opening a WebSocket connection. This solves the browser WebSocket API limitation: browsers cannot set custom headers on `new WebSocket(url)`.

```python
@router.get("/ws-token")
async def get_ws_token(request: Request) -> dict:
    """Issue a 30-second short-lived internal JWT for WebSocket authentication.

    Called by the frontend immediately before opening the alert stream WebSocket.
    The returned token goes in ?token= on the WS URL.

    Why 30s TTL (not 15 min like the regular access token):
    - The token appears in the URL and therefore in server logs
    - Short TTL limits log-based exposure to a narrow window
    - Frontend fetches a fresh token on each reconnect attempt anyway

    Auth: requires Bearer access token in Authorization header (normal auth flow).
    """
    user = request.state.user  # set by OIDCAuthMiddleware
    settings = request.app.state.settings

    # Build short-lived internal JWT with narrow scope
    ws_token = _create_internal_jwt(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        ttl_seconds=30,
        scope="alerts:stream",
        private_key=settings.internal_jwt_private_key,
    )
    return {"token": ws_token, "expires_in": 30}
```

**Part B — S10 `InternalJWTMiddleware` query-param fallback**: Modify `services/alert/src/alert/infrastructure/middleware/internal_jwt.py` to also read `?token=` for WebSocket upgrade requests. WebSocket upgrades are standard HTTP GETs with `Connection: Upgrade` + `Upgrade: websocket` headers — the middleware can detect this and read from query params instead.

```python
# In InternalJWTMiddleware.dispatch():
# Current: token = request.headers.get("X-Internal-JWT")
# New:
is_ws_upgrade = (
    request.headers.get("upgrade", "").lower() == "websocket"
)
if is_ws_upgrade:
    # For WebSocket upgrades: browsers cannot set custom headers via
    # new WebSocket(url) — token must come from ?token= query param.
    # Token was issued by GET /v1/auth/ws-token (30s TTL, RS256 signed).
    token = request.query_params.get("token")
else:
    # Regular HTTP requests: use X-Internal-JWT header (set by S9 proxy)
    token = request.headers.get("X-Internal-JWT")
```

**Acceptance criteria**:
- [ ] `GET /v1/auth/ws-token` returns `{token, expires_in: 30}` when authenticated
- [ ] `GET /v1/auth/ws-token` returns 401 when unauthenticated
- [ ] S10 `InternalJWTMiddleware` reads `?token=` for WS upgrade requests
- [ ] S10 `InternalJWTMiddleware` still reads `X-Internal-JWT` header for normal HTTP requests
- [ ] S10 WS endpoint reachable with `?token=<ws_token>` (no header needed)

---

##### T-S9-2-05: Tests for Wave S9-2 Routes
**Type**: test
**depends_on**: T-S9-2-01, T-S9-2-02, T-S9-2-03, T-S9-2-04
**blocks**: none
**Target files**: `services/api-gateway/tests/`, `services/alert/tests/`
**PRD reference**: §11

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_portfolios_proxy_requires_auth` | 401 without auth | unit |
| `test_holdings_proxy_requires_auth` | 401 without auth | unit |
| `test_transactions_post_body_forwarded` | POST body reaches S1 client | unit |
| `test_watchlists_list_requires_auth` | 401 without auth | unit |
| `test_watchlist_member_delete` | DELETE proxied with correct path | unit |
| `test_register_redirect_302` | Redirects to oidc_issuer_url/ui/console/register | unit |
| `test_ws_token_returns_jwt_30s` | GET /v1/auth/ws-token → `{token, expires_in: 30}` | unit |
| `test_ws_token_requires_auth` | GET /v1/auth/ws-token without Bearer → 401 | unit |
| `test_internal_jwt_ws_upgrade_reads_query_param` | WS upgrade request with `?token=<jwt>` → auth succeeds | unit |
| `test_internal_jwt_http_still_reads_header` | Normal HTTP request still reads `X-Internal-JWT` header | unit |
| `test_internal_jwt_ws_upgrade_missing_token` | WS upgrade without `?token=` → 401 | unit |

**Acceptance criteria**:
- [ ] ≥ 11 new tests pass
- [ ] `python -m pytest tests/ -v` all green (both api-gateway and alert service)

#### Validation Gate
- [ ] ruff + mypy pass on `services/api-gateway/` and `services/alert/`
- [ ] All api-gateway tests pass (both existing + new)
- [ ] All 12 new routes (4 portfolio + 6 watchlist + 1 auth/register + 1 ws-token) present
- [ ] S10 alert service tests pass with updated middleware

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/alert/tests/` — any test that mocks `InternalJWTMiddleware` with WS upgrade | Middleware behavior changed for WS upgrades | Verify existing WS tests still pass; update fixtures to use `?token=` if needed |
| None for other services | Only additions + non-breaking middleware extension | None |

#### Regression Guardrails
- **BP-064**: `status_code=204` with body → FastAPI validation error — use `status_code=200` for DELETE routes on the S9 side
- **BP-145**: OIDCAuthMiddleware must be in middleware stack for `GET /v1/auth/ws-token` so `request.state.user` is populated — verify middleware order in `app.py`
- **BP-159**: `BaseHTTPMiddleware` dual-instance startup() bypass — verify S10's middleware is not double-added after this change

---

### Wave S9-3: Composed Endpoints (OQ-01..OQ-04 Resolution) ✅

**Status**: **DONE** — 2026-04-18 · 127 tests pass · lint + typecheck clean
**Goal**: Implement the 5 composed/new S9 endpoints that resolve BLOCKING OQs: instrument search, market heatmap, top movers, economic calendar, and AI signals stub.
**Depends on**: none (independent of S9-1, S9-2)
**Estimated effort**: 60 min
**Architecture layer**: API (S9 composed endpoints)

#### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — composed endpoint pattern (`get_company_overview` in `clients.py` is the best example)
- `services/api-gateway/src/api_gateway/clients.py` — add composed functions here
- `services/market-data/src/market_data/api/` — confirm S3 screener + instruments search params

#### Tasks

##### T-S9-3-01: Instrument Search Endpoint
**Type**: impl
**depends_on**: none
**blocks**: T-F3-04 (GlobalSearch component)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`, `services/api-gateway/src/api_gateway/clients.py`
**PRD reference**: §6.2 Search Route, §6.5 GlobalSearch component

**What to build**: `GET /v1/search/instruments?q=<query>&limit=<n>` proxied to S3 `GET /instruments?search=<q>&limit=<n>`. The S3 endpoint accepts query parameters for filtering instruments.

**Implementation in proxy.py**:
```python
@router.get("/search/instruments")
async def search_instruments(
    request: Request,
    q: str = Query("", description="Search query"),
    limit: int = Query(10, ge=1, le=50),
) -> Any:
    """Instrument search for the top-bar command palette.

    Proxies to S3 GET /instruments with search filter.
    No auth required — instrument names are public data.
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/instruments",
        params={"search": q, "limit": limit},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

**Note**: Verify the exact query parameter name S3 accepts for search (`search=` vs `q=` vs `name=`) by reading `services/market-data/src/market_data/api/routers/instruments.py` before implementing.

**Acceptance criteria**:
- [ ] `GET /v1/search/instruments?q=apple&limit=10` returns S3 instrument list
- [ ] No auth required
- [ ] q param validated (min 0 chars — allow empty for initial "show popular" UX)
- [ ] limit capped at 50

---

##### T-S9-3-02: Market Heatmap Composed Endpoint
**Type**: impl
**depends_on**: none
**blocks**: T-F5-03 (MarketHeatmap widget)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`, `services/api-gateway/src/api_gateway/clients.py`
**PRD reference**: §6.2 Dashboard Routes, §6.5 MarketHeatmap

**What to build**: `GET /v1/market/heatmap` — composed endpoint that returns S&P 500 sector performance by calling S3 screener for each of the 11 GICS sectors and aggregating daily returns.

**Composition logic** (add to `clients.py`):
```python
GICS_SECTORS = [
    "Energy", "Materials", "Industrials", "Consumer Discretionary",
    "Consumer Staples", "Health Care", "Financials", "Information Technology",
    "Communication Services", "Utilities", "Real Estate",
]

async def get_market_heatmap(clients: ServiceClients) -> dict[str, Any]:
    """Compute sector heatmap from S3 screener data.

    For each GICS sector, fetches top instruments and computes average daily_return.
    Returns list of {sector, avg_change, color_step} for the frontend HeatCell grid.
    """
    # Call S3 screener with sector filters; aggregate by GICS sector
    # Use POST /fundamentals/screen with sort_by=daily_return for each sector
    ...
```

**Simplified alternative**: If the S3 screener supports `group_by=sector` or returns a sector field, use a single call. Otherwise, make 11 parallel calls (one per sector). Use `asyncio.gather` for parallelism (same pattern as `get_company_overview`).

**Response shape**:
```json
{
  "sectors": [
    {"name": "Energy", "change_pct": 1.23, "instrument_count": 28},
    {"name": "Technology", "change_pct": -0.45, "instrument_count": 65}
  ]
}
```

**Acceptance criteria**:
- [ ] Returns 11 GICS sectors with change_pct
- [ ] Auth required
- [ ] Uses asyncio.gather for parallel S3 calls (not serial)
- [ ] Handles partial S3 failures gracefully (missing sector → change_pct: null)

---

##### T-S9-3-03: Top Movers Composed Endpoint
**Type**: impl
**depends_on**: none
**blocks**: T-F5-04 (TopMovers widget)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Dashboard Routes, §6.5 TopMovers

**What to build**: `GET /v1/market/top-movers?limit=10&type=gainers` — proxies to S3 screener sorted by `daily_return` descending (gainers) or ascending (losers).

**Implementation**: Single S3 screener call with `sort_by=daily_return`, `sort_dir=desc|asc`, `limit=10`. No extra composition needed.

**Response**: Pass through S3 screener response directly.

**Acceptance criteria**:
- [ ] `?type=gainers` → `sort_dir=desc`
- [ ] `?type=losers` → `sort_dir=asc`
- [ ] limit param forwarded (default 10, max 20)
- [ ] Auth required

---

##### T-S9-3-04: Economic Calendar Proxy + AI Signals Stub
**Type**: impl
**depends_on**: none
**blocks**: T-F5-06 (EconomicCalendar), T-F5-08 (AiSignals)
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: §6.2 Dashboard Routes

**What to build**: Two endpoints:

1. `GET /v1/fundamentals/economic-calendar` — proxies to S7 `GET /api/v1/temporal-events?type=economic` (S7 stores macro events from PRD-0018 EODHD economic event ingestion).

2. `GET /v1/signals/ai?limit=` — S6 price_impact signals (from PRD-0020). For now, return an empty stub since S9 has no S6 client. Add a TODO comment referencing PRD-0020. The frontend AiSignals shows empty state gracefully.

**Economic calendar implementation**:
```python
@router.get("/fundamentals/economic-calendar")
async def economic_calendar(request: Request) -> Any:
    """Proxy GET /api/v1/temporal-events → S7 Knowledge Graph.

    Returns upcoming macro economic events for the EconomicCalendar dashboard widget.
    Filters for economic event type from S7's temporal events store (PRD-0018).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        "/api/v1/temporal-events",
        params={"type": "economic", **dict(request.query_params)},
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
```

**AI signals stub**:
```python
@router.get("/signals/ai")
async def ai_signals(request: Request) -> Any:
    """AI price-impact signal scores (PRD-0020).

    TODO: S9 does not yet have an S6 NLP Pipeline client. Returns empty list.
    Once S9 gets an nlp_pipeline client and S6 exposes GET /api/v1/signals/price-impact,
    replace this stub with a real proxy.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"signals": [], "total": 0}
```

**Acceptance criteria**:
- [ ] `GET /v1/fundamentals/economic-calendar` proxies to S7 temporal-events
- [ ] `GET /v1/signals/ai` returns `{"signals": [], "total": 0}` stub with TODO comment
- [ ] Both require auth
- [ ] ruff/mypy pass

---

##### T-S9-3-05: Tests for Wave S9-3 Routes
**Type**: test
**depends_on**: T-S9-3-01, T-S9-3-02, T-S9-3-03, T-S9-3-04
**blocks**: none
**Target files**: `services/api-gateway/tests/`
**PRD reference**: §11

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_search_instruments_no_auth` | 200 without auth | unit |
| `test_search_instruments_q_param` | q param forwarded as `search=` to S3 | unit |
| `test_top_movers_gainers_desc` | type=gainers → sort_dir=desc | unit |
| `test_top_movers_losers_asc` | type=losers → sort_dir=asc | unit |
| `test_economic_calendar_requires_auth` | 401 without auth | unit |
| `test_ai_signals_stub_returns_empty` | Returns {"signals": [], "total": 0} | unit |

**Acceptance criteria**:
- [ ] ≥ 6 new tests pass
- [ ] All api-gateway tests green

#### Validation Gate
- [ ] ruff + mypy pass on `services/api-gateway/`
- [ ] All api-gateway tests pass
- [ ] Verify new route list in Swagger at `GET /docs` (if running)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | Only additions | None |

#### Regression Guardrails
- **BP-114**: EODHD demo rate-limit under concurrent load — the heatmap endpoint makes 11 parallel S3 screener calls. If S3 is rate-limited, use `asyncio.gather(*calls, return_exceptions=True)` to avoid crashing; return null for failed sectors.

---

## Sub-Plan B: Frontend Implementation

### Wave F-1: Bootstrap apps/worldview-web/

**Goal**: Create the new `apps/worldview-web/` Next.js 15 service from scratch: project scaffold, shadcn/ui, Midnight Pro design system, fonts, env vars, docker-compose entry.
**Depends on**: none
**Estimated effort**: 60 min
**Architecture layer**: config + foundation

#### Pre-read (agent must read before starting)
- `docs/specs/0028-worldview-web-frontend.md §6.4` — full directory structure + tech stack
- `docs/specs/0028-worldview-web-frontend.md §6.4 Visual Identity` — exact CSS variables
- `docs/frontend/NEXTJS_GUIDE.md` — Next.js 15 patterns for this project
- `infra/docker-compose.yml` — existing format for adding new service entry

#### Tasks

##### T-F1-01: Project Scaffold + Dependencies
**Type**: impl
**depends_on**: none
**blocks**: all F-* waves
**Target files**: `apps/worldview-web/` (new directory), `apps/worldview-web/package.json`, `apps/worldview-web/pnpm-lock.yaml`
**PRD reference**: §6.4 Technology Stack

**What to build**: Run `pnpm create next-app` (non-interactive) to scaffold the project, then configure dependencies.

**Commands**:
```bash
cd apps
pnpm create next-app worldview-web \
  --typescript \
  --tailwind \
  --app \
  --src-dir \
  --import-alias "@/*" \
  --no-turbopack \
  --no-eslint
```

**Post-scaffold: install exact version deps** (no `^`):
```json
{
  "dependencies": {
    "next": "15.3.1",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "@tanstack/react-query": "5.74.4",
    "lightweight-charts": "4.2.2",
    "sigma": "3.0.0",
    "graphology": "0.26.0",
    "graphology-layout-forceatlas2": "0.10.1",
    "@react-sigma/core": "4.0.7",
    "react-grid-layout": "1.5.0",
    "cmdk": "1.0.4",
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "tailwind-merge": "2.6.0",
    "lucide-react": "0.503.0"
  },
  "devDependencies": {
    "typescript": "5.8.3",
    "@types/node": "22.14.1",
    "@types/react": "19.1.2",
    "@types/react-dom": "19.1.2",
    "vitest": "3.1.2",
    "@vitest/ui": "3.1.2",
    "@testing-library/react": "16.3.0",
    "@testing-library/user-event": "14.6.1",
    "msw": "2.7.5",
    "jsdom": "26.1.0",
    "@playwright/test": "1.52.0"
  }
}
```

**Run after install**: `pnpm dlx shadcn@latest init` — choose: dark theme, slate base, CSS variables yes.

**Install shadcn/ui components** (exact list for MVP):
```bash
pnpm dlx shadcn@latest add button input badge card separator skeleton \
  dropdown-menu popover select sheet tabs dialog command scroll-area \
  tooltip progress avatar
```

**Acceptance criteria**:
- [ ] `apps/worldview-web/` directory exists with full Next.js 15 scaffold
- [ ] `package.json` has no `^` in any version (exact only)
- [ ] `pnpm audit` shows 0 critical CVEs
- [ ] `pnpm build` succeeds (empty app builds without errors)
- [ ] `components.json` exists (shadcn/ui initialized)
- [ ] `src/components/ui/` populated with shadcn components

---

##### T-F1-02: Midnight Pro Design System + Fonts
**Type**: impl
**depends_on**: T-F1-01
**blocks**: all F-* waves (design tokens)
**Target files**: `apps/worldview-web/app/globals.css`, `apps/worldview-web/app/layout.tsx`, `apps/worldview-web/tailwind.config.ts`
**PRD reference**: §6.4 Visual Identity, ADR-F-04 (dark only), ADR-F-15 (font-mono for numbers)

**What to build**: Replace the default shadcn CSS variables with the Midnight Pro design system. Load IBM Plex fonts.

**globals.css** must contain the exact variables from PRD §6.4:
```css
:root {
  /* Dark mode only — ADR-F-04 */
}
.dark {
  --background:        222 47% 11%;   /* #131722 */
  --card:              215 28% 14%;   /* #1E2329 */
  --muted:             213 20% 19%;   /* #2B3139 */
  --popover:           222 47% 11%;
  --foreground:        220 14% 85%;   /* #D1D4DC */
  --muted-foreground:  220 9% 50%;    /* #787B86 */
  --primary:           199 89% 48%;   /* #0EA5E9 */
  --primary-foreground: 222 47% 11%;
  --border:            213 20% 19%;
  --input:             213 20% 19%;
  --ring:              199 89% 48%;
  --destructive:       0 63% 62%;     /* #EF5350 */
  --radius: 0.375rem;
}
/* Custom utility classes not in shadcn */
.text-positive { color: #26A69A; }
.text-negative { color: #EF5350; }
.bg-positive { background-color: #26A69A; }
.bg-negative { background-color: #EF5350; }
```

**root layout.tsx**: Load IBM Plex Sans + IBM Plex Mono via `next/font/google`. Set `<html className="dark">` permanently (ADR-F-04). Add `QueryClientProvider` + `AuthProvider` wrappers (providers implemented in F-2).

**tailwind.config.ts**: Extend with `font-mono: ["IBM Plex Mono", "monospace"]` for `font-mono` class.

**Acceptance criteria**:
- [ ] `<html className="dark">` in root layout (never changes — ADR-F-04)
- [ ] All 15 CSS variables defined in `.dark` block
- [ ] IBM Plex Sans loaded for UI text, IBM Plex Mono for numbers
- [ ] `text-positive` and `text-negative` utilities available
- [ ] `pnpm build` still succeeds

---

##### T-F1-03: next.config.ts + Environment Variables
**Type**: impl + config
**depends_on**: T-F1-01
**blocks**: T-F2-01 (auth), T-F3-01 (shell API calls)
**Target files**: `apps/worldview-web/next.config.ts`, `apps/worldview-web/.env.local.example`, `infra/docker-compose.yml`
**PRD reference**: §6.4 Environment Variables, ADR-F-01 (Node SSR), ADR-F-17 (port 3001)

**What to build**:

`next.config.ts`:
```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // ADR-F-01: Node SSR (not static export) — needed for Middleware auth redirects
  output: undefined, // explicitly not "export"

  async rewrites() {
    return [
      {
        // All /api/* requests proxy to the API gateway (S9)
        // In dev: localhost:8000; in Docker: http://api-gateway:8000
        source: "/api/:path*",
        destination: `${process.env.API_GATEWAY_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            // ADR-F-02: WS must use direct URL (NEXT_PUBLIC_WS_BASE_URL), not /api proxy
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-eval'", // unsafe-eval needed for Next.js HMR in dev
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
              "font-src 'self' https://fonts.gstatic.com",
              "img-src 'self' data:",
              // WS base: S10 direct (8010), not S9 (8000) — S9 has no WS proxy (ADR-F-02)
      `connect-src 'self' ${process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010"} ${process.env.NEXT_PUBLIC_WS_BASE_URL?.replace("ws://", "wss://") ?? "wss://localhost:8010"}`,
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
```

`.env.local.example`:
```
# API gateway base URL (server-side rewrite target)
API_GATEWAY_URL=http://localhost:8000

# WebSocket base URL (client-side — must be directly reachable from browser)
# ADR-F-02: Next.js rewrites() do NOT proxy WebSocket upgrades
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8010  # S10 direct — NOT S9 (8000)

# Platform display name (optional)
NEXT_PUBLIC_APP_NAME=Worldview
```

**docker-compose.yml** addition (add after `frontend` service):
```yaml
  worldview-web:
    build:
      context: ./apps/worldview-web
      dockerfile: Dockerfile
    ports:
      - "3001:3000"
    environment:
      API_GATEWAY_URL: http://api-gateway:8000
      NEXT_PUBLIC_WS_BASE_URL: ws://localhost:8010  # S10 direct — NOT S9 (8000); ADR-F-02
      NEXT_PUBLIC_APP_NAME: Worldview
    depends_on:
      - api-gateway
      - alert-delivery  # S10: WS connects to alert-delivery:8010 directly
```

**Acceptance criteria**:
- [ ] `/api/*` rewrite configured to `API_GATEWAY_URL`
- [ ] Security headers added (X-Frame-Options, CSP, etc.)
- [ ] `.env.local.example` committed (not `.env.local` — secrets never committed)
- [ ] docker-compose.yml updated with `worldview-web` service on port 3001 + `alert-delivery` dependency
- [ ] S9 config updated: `API_GATEWAY_FRONTEND_URL=http://localhost:3001` and CORS origins include port 3001 (in `.env.local` or docker-compose override for `api-gateway` service)
- [ ] `pnpm build` succeeds

---

##### T-F1-04: Dockerfile + tsconfig + Initial CI check
**Type**: impl + config
**depends_on**: T-F1-01
**blocks**: none
**Target files**: `apps/worldview-web/Dockerfile`, `apps/worldview-web/tsconfig.json`
**PRD reference**: §6.4 directory listing (Dockerfile line)

**What to build**: Multi-stage Dockerfile + tsconfig verification.

**Dockerfile** (multi-stage):
```dockerfile
# Stage 1: Dependencies
FROM node:22-alpine AS deps
RUN npm install -g pnpm@9
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Stage 2: Build
FROM node:22-alpine AS builder
RUN npm install -g pnpm@9
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# Stage 3: Runner
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

**Note**: Add `output: "standalone"` to `next.config.ts` for the standalone build to work.

**Acceptance criteria**:
- [ ] Dockerfile builds successfully (test with `docker build apps/worldview-web/`)
- [ ] `tsconfig.json` has `@/*` alias pointing to `./src/*` + `./app/*`
- [ ] `pnpm typecheck` (tsc --noEmit) passes on empty scaffold

#### Validation Gate
- [ ] `cd apps/worldview-web && pnpm build` succeeds
- [ ] `cd apps/worldview-web && pnpm typecheck` passes
- [ ] `pnpm audit` shows 0 critical CVEs
- [ ] docker-compose.yml has `worldview-web` entry
- [ ] No `^` in package.json dependencies

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `infra/docker-compose.yml` | New service entry added | Verify existing services still start; new port 3001 must not conflict |

#### Regression Guardrails
- **BP-023**: ruff version mismatch for pre-commit — this is a frontend service using pnpm, not Python; ruff does not apply; but note that adding files to the repo may trigger the pre-commit hook for Python files in other services
- No backend Python files are changed in this wave

---

### Wave F-2: Authentication Layer

**Goal**: Implement the full auth layer: `AuthContext`, `authClient.ts`, `LoginPage`, `RegisterPage`, `CallbackPage`, and the protected `(app)/layout.tsx` auth guard.
**Depends on**: F-1
**Estimated effort**: 75 min
**Architecture layer**: application (auth context + pages)

#### Pre-read (agent must read before starting)
- `docs/specs/0028-worldview-web-frontend.md §6.5` — LoginPage, RegisterPage, CallbackPage, protected layout specs
- `docs/specs/0028-worldview-web-frontend.md §6.6 Flow 1 and Flow 2` — auth boot + login PKCE flows
- `docs/frontend/NEXTJS_GUIDE.md §3 Auth Pattern` — heavy comments on auth pattern
- `apps/frontend/src/contexts/AuthContext.tsx` — existing auth context to port/reference (NOT copy verbatim — update for new structure)
- Security rule: access_token in React state ONLY — never localStorage, never non-httpOnly cookie

#### Tasks

##### T-F2-01: AuthContext + useAuth hook
**Type**: impl
**depends_on**: T-F1-01
**blocks**: T-F2-02, T-F2-04, T-F3-01
**Target files**:
- `apps/worldview-web/src/contexts/AuthContext.tsx`
- `apps/worldview-web/src/hooks/useAuth.ts`
**PRD reference**: §6.6 Flow 1 (auth boot), §8.1 Auth Security

**What to build**: AuthContext with `isAuthenticated`, `isLoading`, `accessToken`, `user` state. On mount: check expiry first via `isTokenExpiringSoon()` (ADR-F-18) — if current token has >60s remaining, skip the refresh call. If token is missing or expiring, call `POST /api/v1/auth/refresh` — 200 sets state to authenticated, 401 sets to unauthenticated. Include silent refresh timer: re-call refresh 60s before `expires_in` to prevent expiry mid-session.

**Token expiry check** (ADR-F-18) — include this helper inline in `AuthContext.tsx`:
```typescript
// ADR-F-18: Check expiry before firing POST /auth/refresh
// Reading exp from the JWT payload is safe — payload is public (not secret)
// We are NOT skipping S9/S10 signature verification, just avoiding a redundant network call
function isTokenExpiringSoon(token: string | null): boolean {
  if (!token) return true; // no token → definitely need refresh
  try {
    // JWT payload is base64url-encoded; atob() decodes it
    const { exp } = JSON.parse(atob(token.split(".")[1]));
    return exp * 1000 - Date.now() < 60_000; // refresh if <60s left
  } catch {
    return true; // malformed token → force refresh to be safe
  }
}
```

**Key AuthContext interface**:
```typescript
interface AuthContextValue {
  isAuthenticated: boolean;        // true after successful refresh/callback
  isLoading: boolean;              // true during initial refresh check on mount
  accessToken: string | null;      // NEVER stored in localStorage — React state only
  user: User | null;               // { user_id, tenant_id, email, sub }
  setTokens: (token: string, user: User, expiresIn: number) => void;  // called from CallbackPage
  logout: () => Promise<void>;     // calls POST /api/v1/auth/logout, clears state
}
```

**Critical comments to include** (per memory: user is new to Next.js):
- Explain why `"use client"` is first line (context uses React hooks, which are client-only)
- Explain why token is in state and not localStorage (XSS: JS can read localStorage; React state is harder to access from injected scripts)
- Explain the silent refresh timer pattern
- Comment on useEffect cleanup (clearInterval to prevent memory leak)

**Security invariant test** (inline assertion):
```typescript
// Security invariant: verify token is never in localStorage
// This check runs in dev only to catch accidental regressions
if (process.env.NODE_ENV === 'development') {
  if (localStorage.getItem('access_token')) {
    throw new Error('SECURITY VIOLATION: access_token found in localStorage');
  }
}
```

**Acceptance criteria**:
- [ ] `isLoading=true` while initial refresh is in-flight
- [ ] `isAuthenticated=true` after 200 from `/api/v1/auth/refresh`
- [ ] `isAuthenticated=false` after 401 (no redirect — that's the protected layout's job)
- [ ] Token NEVER stored in localStorage (enforced by dev-mode assertion)
- [ ] Silent refresh timer fires at `expires_in - 60` seconds
- [ ] `logout()` clears state AND calls `POST /api/v1/auth/logout`
- [ ] `useAuth()` hook exported from `src/hooks/useAuth.ts`
- [ ] On mount with fresh token (exp > 60s): `POST /auth/refresh` is NOT called (ADR-F-18)
- [ ] On mount with expiring token (exp ≤ 60s): `POST /auth/refresh` IS called

---

##### T-F2-02: authClient.ts — Authenticated Fetch Wrapper
**Type**: impl
**depends_on**: T-F2-01
**blocks**: T-F3-01, all data-fetching components
**Target files**: `apps/worldview-web/src/lib/authClient.ts`
**PRD reference**: §6.6 Flow 3 (dashboard load), §9 Failure Modes

**What to build**: A fetch wrapper that:
1. Attaches `Authorization: Bearer <token>` to every request
2. On 401: triggers `POST /api/v1/auth/refresh` once (deduplicated via singleton — ADR-F-19), retries original request with new token
3. On second 401: calls `router.push("/login")`

**Critical pattern — singleton `refreshPromise` (ADR-F-19)**:

The dashboard fires 9 parallel TanStack Query fetches on mount. If the token expires at that moment, all 9 get 401 simultaneously. Without the singleton, all 9 would fire `POST /auth/refresh` — redundant calls that could cause a race. The singleton ensures exactly one refresh fires.

```typescript
// authClient.ts — the single fetch wrapper all components must use
// Never use raw fetch() in components; always use authFetch() from this module

// ADR-F-19: Module-level singleton to deduplicate concurrent 401 responses
// When 9 queries all get 401 at once (token expired during parallel dashboard load),
// all 9 await THIS same promise — only one actual refresh network call fires.
// The variable resets to null after the promise settles so future 401s can refresh again.
let refreshPromise: Promise<string | null> | null = null;

// Module-level token store — AuthContext calls setCurrentToken() when it sets state
// Using module-level state (not React context) because authClient.ts is used outside
// of React render trees (e.g., in Suspense boundaries, early during mount)
let currentToken: string | null = null;

export function setCurrentToken(token: string | null): void {
  currentToken = token;
}

async function doRefresh(): Promise<string | null> {
  // If a refresh is already in-flight, return the existing promise
  // This is the core of ADR-F-19 — the singleton deduplication
  if (!refreshPromise) {
    refreshPromise = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then(r => {
        if (!r.ok) return null;
        return r.json().then((d: { access_token: string }) => {
          currentToken = d.access_token; // update module-level store
          return d.access_token;
        });
      })
      .finally(() => {
        refreshPromise = null; // reset so next expiry can trigger a fresh refresh
      });
  }
  return refreshPromise;
}

export async function authFetch(url: string, options?: RequestInit): Promise<Response> {
  const headers = new Headers(options?.headers);
  if (currentToken) {
    headers.set("Authorization", `Bearer ${currentToken}`);
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // First 401: attempt refresh (deduplicated — other concurrent callers await same promise)
    const newToken = await doRefresh();

    if (!newToken) {
      // Refresh failed — user needs to re-authenticate
      // Router push happens here; import router lazily to avoid circular deps
      window.location.href = "/login";
      return response;
    }

    // Retry original request with fresh token
    headers.set("Authorization", `Bearer ${newToken}`);
    const retryResponse = await fetch(url, { ...options, headers });

    if (retryResponse.status === 401) {
      // Second 401 after fresh token — should not happen; force re-login
      window.location.href = "/login";
    }

    return retryResponse;
  }

  return response;
}

// Convenience wrappers matching gateway-client.ts usage pattern
export const authClient = {
  get: <T>(url: string) => authFetch(url).then(r => r.json() as Promise<T>),
  post: <T>(url: string, body: unknown) =>
    authFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => r.json() as Promise<T>),
};
```

**Acceptance criteria**:
- [ ] Attaches Bearer header to all requests
- [ ] Retries once on 401 after token refresh
- [ ] Redirects to /login on double 401
- [ ] Exported as named functions: `authFetch`, `setCurrentToken`, `authClient`
- [ ] Concurrent 401s all await the same `refreshPromise` — only ONE `POST /auth/refresh` fires (ADR-F-19)
- [ ] `refreshPromise` resets to null after settling so future expirations can refresh

---

##### T-F2-03: LoginPage, RegisterPage, CallbackPage
**Type**: impl
**depends_on**: T-F2-01
**blocks**: T-F2-04 (needs login flow complete)
**Target files**:
- `apps/worldview-web/app/login/page.tsx`
- `apps/worldview-web/app/register/page.tsx`
- `apps/worldview-web/app/callback/page.tsx`
**PRD reference**: §6.5 Login, Register, Callback pages

**What to build**:

**LoginPage** (`/login`):
- `"use client"` — redirects authenticated users to `/dashboard`
- Single button: `onClick={() => window.location.href = "/api/v1/auth/login"}`
- Simple centered card: logo + "Log in to Worldview" button

**RegisterPage** (`/register`):
- `"use client"` — redirects authenticated users to `/dashboard`
- Single button: `onClick={() => window.location.href = "/api/v1/auth/register"}`
- "Create account" button + "Already have an account? Log in" link

**CallbackPage** (`/callback`):
- `"use client"` — uses `useSearchParams()` (must be in Suspense boundary per Next.js 15)
- On mount: read `?code=` and `?state=` from URL
- Call `GET /api/v1/auth/callback?code=&state=`
- On 200: call `setTokens(data.access_token, data.user, data.expires_in)` → `router.push("/dashboard")`
- On error: show error message + "Back to login" link
- Show skeleton/spinner while in-flight

**Important Next.js 15 note**: `useSearchParams()` must be wrapped in a `<Suspense>` boundary. Create a `CallbackContent` component wrapped in Suspense inside the page.

**Acceptance criteria**:
- [ ] Login button navigates to `/api/v1/auth/login` (full page redirect, not fetch)
- [ ] Callback exchanges code and sets token, then pushes to `/dashboard`
- [ ] `useSearchParams()` wrapped in Suspense (no build error)
- [ ] Error state shown if callback fails

---

##### T-F2-04: Protected Layout (app)/layout.tsx
**Type**: impl
**depends_on**: T-F2-01
**blocks**: all protected pages (F-3 through F-13)
**Target files**:
- `apps/worldview-web/app/(app)/layout.tsx`
- `apps/worldview-web/app/layout.tsx` (root layout update — add QueryClientProvider + AuthProvider)
**PRD reference**: §6.5 Shell: Protected Layout, ADR-F-06

**What to build**:

**Root layout** (`app/layout.tsx`):
```typescript
// Root layout: wraps the entire app in providers
// QueryClientProvider: TanStack Query cache shared across all pages
// AuthProvider: auth state shared across all pages
// html className="dark": permanent dark mode (ADR-F-04)
```

**Protected layout** (`app/(app)/layout.tsx`):
- `"use client"` — uses `useAuth()` and `useRouter()`
- Auth guard: if `!isLoading && !isAuthenticated` → `router.push("/login")`
- While loading: show full-page spinner (not flash of protected content)
- When authenticated: render `<TopBar />` + `<Sidebar />` + `{children}` in shell layout

**Shell layout structure** (from PRD §6.5):
```tsx
<div className="flex flex-col h-screen">
  <TopBar />                  {/* fixed top, h-12 */}
  <div className="flex flex-1 pt-12"> {/* pt-12 to offset fixed TopBar */}
    <Sidebar />               {/* fixed left, w-56 */}
    <main className="flex-1 ml-56 overflow-auto p-4">
      {children}
    </main>
  </div>
</div>
```

**Acceptance criteria**:
- [ ] Unauthenticated users redirected to `/login`
- [ ] `isLoading=true` shows spinner (no flash of protected content)
- [ ] Shell renders TopBar + Sidebar (stubs are fine — real components in F-3)
- [ ] Root layout has `dark` class on `<html>` permanently

##### T-F2-05: Auth Tests
**Type**: test
**depends_on**: T-F2-01, T-F2-02, T-F2-03, T-F2-04
**blocks**: none
**Target files**: `apps/worldview-web/tests/`
**PRD reference**: §11 Unit Tests

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `AuthContext_refresh_200_sets_authenticated` | POST /auth/refresh 200 → isAuthenticated=true | unit |
| `AuthContext_refresh_401_not_authenticated` | 401 → isAuthenticated=false | unit |
| `AuthContext_skips_refresh_if_token_fresh` | ADR-F-18: token with exp > 60s → POST /auth/refresh NOT called | unit |
| `AuthContext_calls_refresh_if_token_expiring` | ADR-F-18: token with exp ≤ 60s → POST /auth/refresh IS called | unit |
| `AuthContext_refresh_scheduled_60s_before_expiry` | Silent refresh timer fires at `expires_in - 60` seconds | unit |
| `authClient_attaches_bearer_header` | Bearer token in Authorization header | unit |
| `authClient_retries_on_401` | 401 → refresh → retry with new token | unit |
| `authClient_concurrent_401_single_refresh` | ADR-F-19: 5 parallel 401s → exactly 1 POST /auth/refresh call | unit |
| `authClient_refresh_promise_resets_after_settle` | ADR-F-19: refreshPromise is null after resolution; next 401 creates new promise | unit |
| `CallbackPage_success_redirects_dashboard` | code exchange 200 → router.push("/dashboard") | unit |
| `ProtectedLayout_unauthenticated_redirects` | Not auth → redirects to /login | unit |
| `localStorage_security_invariant` | access_token and refresh_token both null in localStorage | unit |

**Test implementation notes for ADR-F-18 and ADR-F-19 tests**:

For `AuthContext_skips_refresh_if_token_fresh`:
```typescript
// Build a fake JWT with exp = now + 300 seconds (5 min — well within fresh threshold)
const futureExp = Math.floor(Date.now() / 1000) + 300;
const fakePayload = btoa(JSON.stringify({ exp: futureExp, sub: "test-user" }));
const fakeToken = `header.${fakePayload}.signature`;
// Pre-seed AuthContext state with this token, then trigger mount re-run
// Assert: POST /api/v1/auth/refresh was NOT called (check MSW handler call count)
```

For `authClient_concurrent_401_single_refresh`:
```typescript
// Arrange: MSW handler for /api/v1/auth/refresh with call counter
let refreshCallCount = 0;
server.use(http.post("/api/v1/auth/refresh", () => {
  refreshCallCount++;
  return HttpResponse.json({ access_token: "new-token" });
}));
// Act: fire 5 parallel authFetch() calls, all of which get 401
await Promise.all([...Array(5)].map(() => authFetch("/api/v1/test")));
// Assert: refresh was called exactly once
expect(refreshCallCount).toBe(1);
```

**Acceptance criteria**:
- [ ] ≥ 12 tests written and passing
- [ ] MSW (Mock Service Worker) used for HTTP mocking
- [ ] Security invariant test passes (tokens not in localStorage)
- [ ] ADR-F-18 test: POST /auth/refresh skipped when token exp > 60s
- [ ] ADR-F-19 test: concurrent 401s fire exactly 1 refresh call

#### Validation Gate
- [ ] `pnpm typecheck` passes
- [ ] `pnpm test:run` passes (all Vitest tests — minimum 12 new tests in this wave)
- [ ] `pnpm lint` passes
- [ ] No `localStorage.setItem` with token in any auth file (grep check)
- [ ] Auth files contain inline comments explaining "why" (per ADR memory)
- [ ] ADR-F-18: `isTokenExpiringSoon()` exists in `AuthContext.tsx` with the `atob(token.split(".")[1])` pattern
- [ ] ADR-F-18 behaviour verified by `AuthContext_skips_refresh_if_token_fresh` test
- [ ] ADR-F-19: module-level `refreshPromise` exists in `authClient.ts` (not inside any function)
- [ ] ADR-F-19 behaviour verified by `authClient_concurrent_401_single_refresh` test
- [ ] `authClient.ts` exports `authFetch`, `setCurrentToken`, `authClient` (get/post wrappers)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None new — F-1 was pure scaffold | Auth is new code with no existing consumers | None |

#### Regression Guardrails
- **Security: token-in-localStorage** — every auth file must be audited for any localStorage usage before commit
- **BP-159**: `BaseHTTPMiddleware` dual startup bypass — not applicable (frontend wave)

---

### Wave F-3: Shell — TopBar, Sidebar, MarketStatusPill

**Goal**: Implement the persistent shell components: `TopBar`, `Sidebar`, `MarketStatusPill`, `GlobalSearch`, `IndexTicker`, `UtcClock`, and the `market-schedule.ts` utility.
**Depends on**: F-2
**Estimated effort**: 90 min
**Architecture layer**: application (shell components)

#### Pre-read (agent must read before starting)
- `docs/specs/0028-worldview-web-frontend.md §6.5 TopBar, Sidebar, MarketStatusPill` — full component specs
- `docs/specs/0028-worldview-web-frontend.md §6.5.1` — MarketStatusPill exchange table + computeMarketStatus spec
- `docs/frontend/NEXTJS_GUIDE.md §5 State Management` — when to use useState vs context vs TanStack Query
- `apps/worldview-web/src/lib/gateway-client.ts` — will need to create this in this wave

#### Tasks

##### T-F3-01: gateway-client.ts + utils.ts
**Type**: impl
**depends_on**: T-F2-02
**blocks**: all data-fetching tasks
**Target files**:
- `apps/worldview-web/src/lib/gateway-client.ts`
- `apps/worldview-web/src/lib/utils.ts`
**PRD reference**: §6.2 (all S9 routes)

**What to build**: The typed API client object `gateway` with methods for every S9 endpoint. All methods use `authFetch` from `authClient.ts`.

```typescript
// gateway-client.ts — the ONLY place API calls originate in the frontend
// Never use fetch() directly in components; always use gateway.methodName()
// All paths go through /api/* which is rewritten to API_GATEWAY_URL by next.config.ts

export const gateway = {
  // Auth
  getMe: () => authFetch("/api/v1/auth/me").then(r => r.json()),

  // Quotes
  getQuote: (id: string) => authFetch(`/api/v1/quotes/${id}`).then(r => r.json()),
  getBatchQuotes: (ids: string[]) => authFetch("/api/v1/quotes/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  }).then(r => r.json()),

  // OHLCV
  getOhlcv: (id: string, params?: { timeframe?: string; start?: string; end?: string }) => ...

  // ... all other methods from PRD §6.2 ...
};
```

**utils.ts** must include:
- `cn(...inputs)` from `clsx` + `tailwind-merge` (standard shadcn/ui helper)
- `formatPrice(value: number): string` — 2 decimal places, locale-formatted
- `formatPercent(value: number): string` — sign prefix, 2 decimal places, `%` suffix
- `formatRelativeTime(date: Date | string): string` — "2h ago", "3d ago"
- `formatUsdCompact(value: number): string` — "$12.4B", "$340M"

**Acceptance criteria**:
- [ ] `gateway` object exported with ≥ 20 typed methods (one per major PRD §6.2 endpoint)
- [ ] All methods return typed promises (use `as` assertions if full typing is complex for MVP)
- [ ] `cn()`, `formatPrice()`, `formatPercent()`, `formatRelativeTime()` exported from utils.ts
- [ ] No raw `fetch()` calls in any component — all via `gateway.*`

---

##### T-F3-02: market-schedule.ts + useMarketStatus hook
**Type**: impl
**depends_on**: T-F1-01
**blocks**: T-F3-04 (MarketStatusPill)
**Target files**:
- `apps/worldview-web/src/lib/market-schedule.ts`
- `apps/worldview-web/src/hooks/useMarketStatus.ts`
**PRD reference**: §6.5.1 MarketStatusPill detailed spec

**What to build**: Pure UTC-based market status computation with no API calls.

**market-schedule.ts** (implement exactly per PRD §6.5.1):
```typescript
export interface ExchangeStatus {
  name: string;
  status: "open" | "closed" | "pre-market" | "after-hours";
  utcOpen: string;   // "HH:MM"
  utcClose: string;  // "HH:MM"
  days: string;      // "Mon–Fri" | "24/7" | "Sun–Fri"
}

// The 8 exchanges from PRD table (UTC hours, Mon=1...Sun=0):
// NYSE/NASDAQ: 14:30-21:00 Mon-Fri; pre-market 10:00-14:30; after-hours 21:00-00:00
// LSE: 08:00-16:30 Mon-Fri
// TSE: 00:00-06:00 Mon-Fri (lunch 02:30-03:30 = CLOSED)
// HKEX: 01:30-08:00 Mon-Fri (lunch 04:00-05:00 = CLOSED)
// Euronext: 08:00-16:30 Mon-Fri
// CME: Sun 23:00 - Fri 22:00 (nearly continuous)
// FOREX: Sun 22:00 - Fri 22:00 (24/5)
// Crypto: 24/7 (always open)

export function computeMarketStatus(utcNow: Date): {
  overall: "open" | "closed" | "pre-after-hours";
  exchanges: ExchangeStatus[];
}
```

**Overall status rules** (from PRD §6.5.1):
- `"open"` → NYSE/NASDAQ, LSE, TSE, HKEX, or Euronext is in regular session
- `"pre-after-hours"` → NYSE/NASDAQ in pre-market or after-hours ONLY
- `"closed"` → no equity market in regular session

**useMarketStatus hook**: Re-computes every 60s via `setInterval`. Returns `computeMarketStatus(new Date())`.

**Comments**: Heavily comment the time arithmetic. Explain UTC vs local time, why `getUTCHours()` is used (not `getHours()`), why weekdays are checked with `getUTCDay()`.

**Acceptance criteria**:
- [ ] `computeMarketStatus` is a pure function (no side effects, no API calls)
- [ ] Returns correct status for all 8 exchanges at any given UTC moment
- [ ] `useMarketStatus` re-computes on 60s interval with cleanup in useEffect return
- [ ] Test file `market-schedule.test.ts` covers at least 5 scenarios from PRD §11

---

##### T-F3-03: UtcClock + IndexTicker
**Type**: impl
**depends_on**: T-F3-01
**blocks**: T-F3-05 (TopBar assembly)
**Target files**:
- `apps/worldview-web/src/components/shell/UtcClock.tsx`
- `apps/worldview-web/src/components/shell/IndexTicker.tsx`
**PRD reference**: §6.5 TopBar sub-components

**UtcClock**: Updates every second via `setInterval`. Format: `HH:MM:SS UTC`. Use `font-mono` class (ADR-F-15). Clean up interval in useEffect return. Comment why `toISOString().slice(11, 19)` gives UTC time.

**IndexTicker**: Fetches SPY, QQQ, VIX, BTC via `POST /api/v1/quotes/batch` (TanStack Query, refetchInterval: 15000). Each ticker shows: symbol + price (font-mono) + % change (text-positive/text-negative). Loading: skeleton. Error: `—`.

**Acceptance criteria**:
- [ ] UtcClock shows `HH:MM:SS UTC` updated every second
- [ ] UtcClock cleans up interval on unmount
- [ ] IndexTicker shows 4 tickers with live prices (15s refresh)
- [ ] Prices use `font-mono` class (ADR-F-15)

---

##### T-F3-04: MarketStatusPill + GlobalSearch
**Type**: impl
**depends_on**: T-F3-02, T-F3-01
**blocks**: T-F3-05
**Target files**:
- `apps/worldview-web/src/components/shell/MarketStatusPill.tsx`
- `apps/worldview-web/src/components/shell/GlobalSearch.tsx`
**PRD reference**: §6.5.1 MarketStatusPill, §6.5 GlobalSearch

**MarketStatusPill**:
- Consumes `useMarketStatus()` hook
- Green/amber/red pill based on `overall` status (see PRD §6.5.1 display states)
- On hover: `Popover` showing per-exchange table with 8 rows
- Each row: exchange name + colored status dot + hours (UTC)
- Current UTC time shown at bottom of popover
- Heavy comments: why pure computation vs API call (ADR-F-16), why 60s interval is sufficient

**GlobalSearch** (cmdk-powered):
- `useDebounce(query, 300)` before firing search request
- `GET /api/v1/search/instruments?q=<query>&limit=10` (TanStack Query with `enabled: q.length >= 1`)
- Results in `Command` dropdown: ticker symbol + company name
- On select: `router.push("/instruments/" + result.entity_id)`
- Close on Escape or outside click

**Acceptance criteria**:
- [ ] MarketStatusPill shows correct color for current UTC time
- [ ] Popover shows 8 exchanges with correct status on hover
- [ ] GlobalSearch fires after 300ms debounce
- [ ] GlobalSearch navigates to `/instruments/:id` on selection
- [ ] `MarketStatusPill.test.tsx` verifies open/closed/pre-after-hours states

---

##### T-F3-05: TopBar + Sidebar assembly
**Type**: impl
**depends_on**: T-F3-03, T-F3-04
**blocks**: T-F5 (dashboard page)
**Target files**:
- `apps/worldview-web/src/components/shell/TopBar.tsx`
- `apps/worldview-web/src/components/shell/Sidebar.tsx`
**PRD reference**: §6.5 TopBar, Sidebar

**TopBar**: Assemble sub-components in the layout from PRD §6.5. Left: logo + GlobalSearch. Center: IndexTicker. Right: UtcClock + MarketStatusPill + AskAiButton (stub for now — AskAiPanel in F-4) + AlertBell + user avatar dropdown.

**Sidebar**: Nav links (Dashboard, Instruments, Screener, Portfolio, Workspace, Alerts & News, Intelligence/Chat) with active state from `usePathname()`. Watchlist sub-section (data from `GET /v1/watchlists` → active watchlist members, live quotes via batch). Recent alerts sub-section (from `AlertStreamContext` — will be wired in F-4; show empty placeholder for now). Settings + Help links at bottom.

**Acceptance criteria**:
- [ ] TopBar renders all sub-components in the layout order from PRD
- [ ] Sidebar nav links use `usePathname()` for active state
- [ ] Sidebar watchlist shows live prices (30s refetch) with font-mono
- [ ] User avatar dropdown: Profile, Settings, Sign out (Sign out calls `logout()`)

#### Validation Gate
- [ ] `pnpm typecheck` passes
- [ ] `pnpm test:run` — market-schedule tests pass
- [ ] `pnpm lint` passes
- [ ] MarketStatusPill renders without API calls (pure computation confirmed)
- [ ] No raw `fetch()` calls — all via `gateway.*`

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `app/(app)/layout.tsx` | TopBar + Sidebar imported here | Verify imports resolve after F-3 implementation |

#### Regression Guardrails
- **ADR-F-15**: Every price/number in IndexTicker and Sidebar watchlist must use `font-mono`
- **ADR-F-02**: WebSocket URL must use `NEXT_PUBLIC_WS_BASE_URL` directly (not `/api/*`) — enforced in F-4

---

### Wave F-4: Alert Stream + FlashOverlay + AskAiPanel

**Goal**: Implement the real-time alert WebSocket stream, FlashOverlay for critical alerts, and AskAiPanel floating mini-chat.
**Depends on**: F-2
**Estimated effort**: 60 min
**Architecture layer**: application (real-time + overlay)

#### Tasks

##### T-F4-01: useAlertStream hook + AlertStreamContext
**Type**: impl
**depends_on**: T-F2-01
**blocks**: T-F4-02, T-F5-08, T-F11-01
**Target files**:
- `apps/worldview-web/src/hooks/useAlertStream.ts`
- `apps/worldview-web/src/contexts/AlertStreamContext.tsx`
**PRD reference**: §6.6 Flow 5 (real-time alert), ADR-F-02 (WS auth via ?token=)

**What to build**:

**useAlertStream** — WebSocket hook with ws-token fetch + exponential backoff:

```typescript
// Step 1: fetch short-lived ws-token from S9 before opening WS
// Why: browsers cannot set headers on new WebSocket(url) — ADR-F-02
// Why short-lived (30s): token appears in URL → in server logs; narrow TTL limits exposure
const { data: wsTokenData } = await authClient.get<{ token: string }>("/api/v1/auth/ws-token");

// Step 2: open WS directly to S10 (not through /api/ — Next.js rewrites don't proxy WS)
// NEXT_PUBLIC_WS_BASE_URL = ws://localhost:8010 (S10 direct)
const ws = new WebSocket(
  `${process.env.NEXT_PUBLIC_WS_BASE_URL}/v1/alerts/stream?token=${wsTokenData.token}`
);
```

- On each reconnect attempt: fetch **fresh** ws-token (old token is 30s TTL — expired by reconnect time)
- Reconnect with exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (cap)
- Cleanup: `ws.close()` + clear reconnect timer in `useEffect` return (prevents memory leak)
- Uses `useRef` for ws instance (not useState — avoids re-render on reconnect)
- Types alert payload as `AlertPayload { id, severity, alert_type, entity_id, message, created_at }`

**AlertStreamContext** — shared state:
```typescript
interface AlertStreamContextValue {
  recentAlerts: AlertPayload[];       // last 50 non-critical alerts
  criticalQueue: AlertPayload[];      // CRITICAL alerts awaiting display
  dequeueCritical: () => void;        // called by FlashOverlay after showing alert
  unreadCount: number;                // recentAlerts.length
}
```

**Comments to include**: Why ws-token pattern (browser WS no-headers limitation); exponential backoff reasoning; why `useRef` for ws (not useState); criticalQueue/dequeue pattern; why fresh ws-token on each reconnect.

**Acceptance criteria**:
- [ ] WS opens with `?token=<ws_token>` (not Bearer header — browser WS API limitation per ADR-F-02)
- [ ] `GET /api/v1/auth/ws-token` called before opening WS; Bearer token in that call's header
- [ ] Fresh ws-token fetched on each reconnect attempt
- [ ] CRITICAL severity → pushed to `criticalQueue`
- [ ] Other severity → pushed to `recentAlerts` (max 50)
- [ ] Reconnects with 1s → 2s → 4s → ... → 30s cap
- [ ] Cleanup: ws.close() + reconnect timer cleared on unmount
- [ ] `NEXT_PUBLIC_WS_BASE_URL` defaults to `ws://localhost:8010` (S10 port, not S9 8000)

---

##### T-F4-02: FlashOverlay
**Type**: impl
**depends_on**: T-F4-01
**blocks**: none
**Target files**: `apps/worldview-web/src/components/shell/FlashOverlay.tsx`
**PRD reference**: §6.5 FlashOverlay, §3 FR-15

**What to build**: Port `FlashOverlay` from `apps/frontend/src/components/alerts/FlashOverlay.tsx` to the new service with updates for the new AlertStreamContext.

- Full-viewport overlay, `z-[9999]`, dark background with alert content
- Shows first item from `AlertStreamContext.criticalQueue`
- 12s auto-dismiss: countdown progress bar; `dequeueCritical()` after 12s
- Escape key + click-outside dismiss (also calls `dequeueCritical()`)
- Class-based `ErrorBoundary` wrapper (in separate file `ErrorBoundary.tsx`) — catches render errors so a bad alert payload doesn't crash the whole app
- Uses `useEffect` for timer + keyboard listener; comments explain every cleanup function

**Acceptance criteria**:
- [ ] Renders when `criticalQueue.length > 0`
- [ ] Auto-dismisses after 12s (countdown bar shows progress)
- [ ] Escape key dismisses
- [ ] Click outside dismisses
- [ ] ErrorBoundary wraps the overlay content
- [ ] Test: `FlashOverlay.test.tsx` with fake timers (vitest.useFakeTimers)

---

##### T-F4-03: AskAiPanel
**Type**: impl
**depends_on**: T-F2-02
**blocks**: T-F3-05 (TopBar needs AskAiButton)
**Target files**: `apps/worldview-web/src/components/shell/AskAiPanel.tsx`
**PRD reference**: §6.5 AskAiPanel

**What to build**: Floating mini-chat panel:
- Position: `fixed bottom-4 right-4` when open
- Single message input + Send button
- On send: `POST /api/v1/chat/stream` (SSE) — stream response into panel
- "Open full chat →" link to `/chat`
- Controlled by `isOpen` prop from TopBar's `AskAiButton` toggle
- Closes on Escape or click-outside (using `useEffect` + event listener)

**Acceptance criteria**:
- [ ] Opens/closes via AskAiButton in TopBar
- [ ] Streams chat response
- [ ] "Open full chat" navigates to `/chat`
- [ ] Closes on Escape or outside click

##### T-F4-04: Alert Stream Tests
**Type**: test
**depends_on**: T-F4-01, T-F4-02
**Target files**: `apps/worldview-web/tests/`

**Tests to write** (from PRD §11):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `useAlertStream_critical_to_queue` | CRITICAL severity → criticalQueue | unit |
| `useAlertStream_non_critical_to_recent` | non-critical → recentAlerts | unit |
| `useAlertStream_dequeueCritical_removes_first` | dequeue removes first item | unit |
| `FlashOverlay_renders_critical_alert` | Shows when criticalQueue.length > 0 | unit |
| `FlashOverlay_auto_dismisses_after_12s` | fake timers: dismissed at 12s | unit |
| `FlashOverlay_escape_dismisses` | Escape key fires dequeueCritical | unit |

#### Validation Gate
- [ ] `pnpm test:run` — alert stream + FlashOverlay tests pass
- [ ] `pnpm typecheck` passes
- [ ] WS URL uses `NEXT_PUBLIC_WS_BASE_URL` (not `/api/`) in useAlertStream

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `app/(app)/layout.tsx` | Add `AlertStreamContext.Provider` wrap | Add after F-4 implementation |

---

### Wave F-5: Dashboard Page (9 Widgets)

**Goal**: Implement all 9 dashboard widgets: MorningBriefCard, PortfolioSummary, MarketHeatmap, TopMovers, WatchlistNews, EconomicCalendar, RecentAlerts, AiSignals, TopBets.
**Depends on**: F-3, F-4, S9-1, S9-2, S9-3
**Estimated effort**: 90 min
**Architecture layer**: application (pages)

#### Tasks

##### T-F5-01: MorningBriefCard + PortfolioSummary
**Type**: impl
**depends_on**: T-F3-01, T-F2-01
**Target files**:
- `apps/worldview-web/src/components/dashboard/MorningBriefCard.tsx`
- `apps/worldview-web/src/components/dashboard/PortfolioSummary.tsx`
**PRD reference**: §6.5 Dashboard — MorningBriefCard, PortfolioSummary

**MorningBriefCard**: TanStack Query for `GET /v1/briefings/morning`. Loading: 5-line text skeleton. Loaded: AI brief text, expandable (show first 200 chars, "Read more"). Refresh button if brief is > 12h old. Error (503 from S9 stub): "Brief unavailable — generating..." with retry. Entity names hyperlinked: regex-replace known entity IDs with `<Link href="/instruments/id">`.

**PortfolioSummary**: Three-query parallel load:
1. `GET /v1/portfolios` → pick first portfolio
2. `GET /v1/holdings/:portfolioId` → list
3. `POST /v1/quotes/batch` → live prices for holdings

Computed: total value, today P&L, unrealised P&L. 5D/5W toggle (persisted to `localStorage`). Top 4 holdings shown. Click → `/portfolio`.

**Acceptance criteria**:
- [ ] Three-state pattern (loading/error/empty/data) for both components
- [ ] font-mono for all monetary values (ADR-F-15)
- [ ] PortfolioSummary shows correct P&L calculation

---

##### T-F5-02: MarketHeatmap + TopMovers
**Type**: impl
**depends_on**: T-F3-01
**Target files**:
- `apps/worldview-web/src/components/dashboard/MarketHeatmap.tsx`
- `apps/worldview-web/src/components/dashboard/TopMovers.tsx`
**PRD reference**: §6.5 Dashboard — MarketHeatmap, TopMovers

**MarketHeatmap**: TanStack Query for `GET /v1/market/heatmap`. 11 GICS sector tiles in a CSS grid. HeatCell color: 7-step scale from `-3%` (deep red `#EF5350`) → `0%` (neutral `#2B3139`) → `+3%` (deep teal `#26A69A`). Intermediate steps use linear interpolation. Each tile: sector name + `±X.XX%` in font-mono.

**TopMovers**: Two tabs: Gainers / Losers. `GET /v1/market/top-movers?type=gainers|losers&limit=10`. Horizontal scroll row of tiles. Each tile: ticker (font-mono, large) + price + % change (colored, large).

**Acceptance criteria**:
- [ ] 11 sector tiles with color interpolation
- [ ] Gainers/Losers tabs switch correctly
- [ ] All numeric values use font-mono

---

##### T-F5-03: WatchlistNews + EconomicCalendar
**Type**: impl
**depends_on**: T-F3-01
**Target files**:
- `apps/worldview-web/src/components/dashboard/WatchlistNews.tsx`
- `apps/worldview-web/src/components/dashboard/EconomicCalendar.tsx`

**WatchlistNews**: `GET /v1/news/top?hours=48&limit=10`. Shows `ArticleCard` components (built in F-7). Loading: 3 skeleton cards.

**EconomicCalendar**: `GET /v1/fundamentals/economic-calendar`. Shows upcoming events sorted by date/time (UTC). Each: date (font-mono), event name, forecast vs previous, impact badge (HIGH=amber/MEDIUM=gray/LOW=muted).

---

##### T-F5-04: RecentAlerts + AiSignals + TopBets
**Type**: impl
**depends_on**: T-F4-01, T-F3-01
**Target files**:
- `apps/worldview-web/src/components/dashboard/RecentAlerts.tsx`
- `apps/worldview-web/src/components/dashboard/AiSignals.tsx`
- `apps/worldview-web/src/components/dashboard/TopBets.tsx`

**RecentAlerts**: Combines `AlertStreamContext.recentAlerts` (live) + `GET /v1/alerts/pending?limit=10` (polled every 30s). Each row: `SeverityBadge` + type + entity + relative time (font-mono). "View all" → `/alerts`.

**AiSignals**: `GET /v1/signals/ai?limit=8`. Currently returns empty stub — shows empty state "Signal data coming soon". When stub is replaced, will show signal score + direction badge.

**TopBets**: `GET /v1/signals/prediction-markets?limit=5&status=open`. Each bet: question (truncated 80 chars) + probability bar + volume (font-mono) + close date.

---

##### T-F5-05: Dashboard Page Assembly
**Type**: impl
**depends_on**: T-F5-01, T-F5-02, T-F5-03, T-F5-04
**Target files**: `apps/worldview-web/app/(app)/dashboard/page.tsx`
**PRD reference**: §6.5 Dashboard page layout

**Layout**: Two-column grid (main col-span-2, sidebar col-span-1). Section order per PRD:
1. MorningBriefCard (full width)
2. PortfolioSummary (left) + MarketHeatmap (right)
3. TopMovers (full width)
4. WatchlistNews (left) + EconomicCalendar (right)
5. RecentAlerts (left) + AiSignals (right)
6. TopBets (full width)

Each widget wrapped in a `<Card>` with consistent padding/spacing.

#### Validation Gate
- [ ] Dashboard page loads with all 9 widget placeholders (loading states work)
- [ ] No console errors on first load
- [ ] `pnpm typecheck` passes

---

### Wave F-6: Instrument Detail Page

**Goal**: Implement the full Instrument Detail page with InstrumentHeader, OHLCVChart, FundamentalsBar, and all 4 tabs (Overview, Fundamentals, News, Intelligence).
**Depends on**: F-3, S9-1
**Estimated effort**: 90 min

#### Tasks

##### T-F6-01: InstrumentHeader + FundamentalsBar
**Target files**: `src/components/instrument/InstrumentHeader.tsx`, `src/components/instrument/FundamentalsBar.tsx`
**What to build**: Header shows ticker, name, current price (font-mono), % change (colored), market cap, volume. FundamentalsBar shows 6 compact key metrics (P/E, EPS, Market Cap, Revenue, Div Yield, 52W High/Low) as a horizontal bar below the chart.

##### T-F6-02: OHLCVChart (lightweight-charts)
**Target files**: `src/components/instrument/OHLCVChart.tsx`
**What to build**: Client-side wrapper for `lightweight-charts` TradingView library. Uses `dynamic(() => import(...), { ssr: false })` — WebGL must be client-only. Timeframe selector (1D/5D/1M/3M/1Y/5Y) triggers new `GET /v1/ohlcv/{id}?timeframe=&start=&end=` query. Chart styled with Midnight Pro colors (grid lines, candle colors positive=`#26A69A`, negative=`#EF5350`).

##### T-F6-03: NewsTab
**Target files**: `src/components/instrument/NewsTab.tsx`
**What to build**: `GET /v1/news/entity/:entityId` with TopNewsFilters (time range, min score, source). Article list using `ArticleCard` (built in F-7 — use stub for now). Sorted by display_relevance_score.

##### T-F6-04: FundamentalsTab (18 sections)
**Target files**: `src/components/instrument/FundamentalsTab.tsx`
**What to build**: 18-section accordion. `GET /v1/fundamentals/{id}`. Sections: Highlights, Valuation, Profitability, Growth, Balance Sheet, Cash Flow, Dividends, Analyst Consensus, Insider Transactions, Institutional Holdings, ESG, Earnings History, Revenue Segments, Geographic Revenue, Officers/Board, Corporate Actions, Financial Ratios, Macro Indicators. Missing sections display `—` gracefully. All numeric values use font-mono.

##### T-F6-05: IntelligenceTab + EntityGraph (sigma.js)
**Target files**: `src/components/instrument/IntelligenceTab.tsx`, `src/components/instrument/EntityGraph.tsx`
**What to build**: EntityGraph uses sigma.js + graphology. Dynamic import (`ssr: false`). `GET /v1/entities/{id}/graph?depth=2`. ForceAtlas2 layout from `graphology-layout-forceatlas2`. Node colors: entity type-based (financial_instrument=sky, person=amber, org=teal). Wrap in ErrorBoundary (WebGL context can fail). IntelligenceTab also shows: AI instrument brief, contradictions panel, prediction market odds.

##### T-F6-06: Instrument Detail Page Assembly + SimilarEntities
**Target files**: `app/(app)/instruments/[id]/page.tsx`, `src/components/instrument/SimilarEntities.tsx`
**What to build**: Page assembles InstrumentHeader + tab bar (Overview/Fundamentals/News/Intelligence). Tab state via `useState`. SimilarEntities: `POST /v1/entities/similar` → 5 cards linking to other instruments.

#### Validation Gate
- [ ] `/instruments/[id]` page loads with all 4 tabs navigable
- [ ] OHLCVChart renders without SSR error
- [ ] EntityGraph renders without crash (ErrorBoundary catches WebGL failure)
- [ ] `pnpm typecheck` passes

---

### Wave F-7: News Components

**Goal**: Implement the reusable news display components: `ArticleCard`, `RelevanceBadge`, `ImpactSparkline`, `TopNewsFilters`.
**Depends on**: F-3
**Estimated effort**: 45 min

#### Tasks

##### T-F7-01: ArticleCard + RelevanceBadge + ImpactSparkline
**Target files**:
- `src/components/news/ArticleCard.tsx` (Server Component — no hooks)
- `src/components/news/RelevanceBadge.tsx` (Server Component)
- `src/components/news/ImpactSparkline.tsx` ("use client" — lightweight-charts)

**ArticleCard**: Displays article title (linked), source, time (relative, font-mono), entity tag, `RelevanceBadge`, `ImpactSparkline` (if ≥ 2 impact windows). LIGHT tier → `opacity-60`.

**RelevanceBadge**: Score 0–1 → percentage display. Color: ≥ 0.8 = red-600 (high impact), 0.5–0.8 = amber-600, < 0.5 = slate-600. Example: score 0.87 → "87%".

**ImpactSparkline**: Mini chart showing price impact across windows (t0, t1, t2, t5). Renders if ≥ 2 non-null windows; returns null otherwise.

##### T-F7-02: TopNewsFilters
**Target files**: `src/components/news/TopNewsFilters.tsx` ("use client")
**What to build**: Filter form: time range select (24h/48h/7d), min score slider (0–1), source type multi-select. Controlled component — parent manages filter state. On change: fires new query in parent via callback.

#### Validation Gate
- [ ] `RelevanceBadge.test.tsx` — score 0.87 → "87%"; score ≥ 0.8 → high-impact color
- [ ] `ArticleCard.test.tsx` — LIGHT tier → opacity-60; ImpactSparkline shown with ≥2 windows
- [ ] `pnpm typecheck` passes

---

### Wave F-8: Screener Page

**Goal**: Implement the Screener page with dynamic filter form and paginated results table.
**Depends on**: F-3
**Estimated effort**: 45 min

#### Tasks

##### T-F8-01: FilterForm + ResultsTable + Screener Page
**Target files**:
- `src/components/screener/FilterForm.tsx`
- `src/components/screener/ResultsTable.tsx`
- `app/(app)/screener/page.tsx`

**FilterForm**: `GET /v1/fundamentals/screen/fields` for available fields. Dynamic rows: field selector (Select) + operator selector (Select: >, <, =, >=, <=) + value input (Input type=number). Add/remove row buttons. "Run Screener" button fires `POST /v1/fundamentals/screen`.

**ResultsTable**: Columns from PRD (Ticker, Name, Price, Market Cap, P/E, EPS, Revenue TTM, Signal Score, % Change). 20 rows/page. Offset pagination. Click row → `/instruments/:entityId`. Client-side sort for < 100 results.

**Screener page**: Left panel (w-72) FilterForm + right flex-1 ResultsTable.

#### Validation Gate
- [ ] Screener loads fields, allows adding filters, runs query, shows results
- [ ] Click on result navigates to instrument detail

---

### Wave F-9: Portfolio Page

**Goal**: Implement the Portfolio page with full holdings view, performance chart, and add transaction form.
**Depends on**: F-3, S9-2
**Estimated effort**: 60 min

#### Tasks

##### T-F9-01: HoldingsTable + PortfolioChart
**Target files**:
- `src/components/portfolio/HoldingsTable.tsx`
- `src/components/portfolio/PortfolioChart.tsx`

**HoldingsTable**: `GET /v1/holdings/{portfolioId}` + `POST /v1/quotes/batch` (30s refetch). Columns: Ticker, Name, Shares, Avg Cost (font-mono), Current Price (font-mono), Today P&L (colored), Total P&L (colored), Portfolio %. Click row → `/instruments/:entityId`.

**PortfolioChart**: `GET /v1/ohlcv/{id}` for portfolio performance (aggregate value over time, built from holdings). 5D/5W toggle. lightweight-charts line chart.

##### T-F9-02: AddTransactionForm + Portfolio Page Assembly
**Target files**:
- `src/components/portfolio/AddTransactionForm.tsx`
- `app/(app)/portfolio/page.tsx`

**AddTransactionForm**: shadcn/ui `Sheet` component (slides in from right). Fields: action (Buy/Sell), ticker (Input), shares (Input type=number positive only), price (Input type=number), date (Input type=date). Submit → `POST /v1/transactions`. Validate: shares > 0, price > 0, max 6 decimal places per PRD §8.2.

**Portfolio page**: PortfolioSummary (expanded) + PortfolioChart + HoldingsTable + TransactionHistory + AddTransactionForm (trigger button).

#### Validation Gate
- [ ] Holdings show live P&L with font-mono
- [ ] Add transaction form validates and submits
- [ ] `PortfolioSummary.test.tsx` — font-mono on values; 5D/5W toggle

---

### Wave F-10: Chat Page (SSE Streaming)

**Goal**: Implement the Intelligence/Chat page with thread sidebar and SSE streaming chat.
**Depends on**: F-3, F-4
**Estimated effort**: 60 min

#### Tasks

##### T-F10-01: ThreadSidebar + ChatStream
**Target files**:
- `src/components/chat/ThreadSidebar.tsx`
- `src/components/chat/ChatStream.tsx`

**ThreadSidebar**: `GET /v1/threads` list. "New chat" → `POST /v1/threads`. Delete thread (hover icon). Client-side search by title.

**ChatStream**: SSE state machine (idle → sending → streaming → settled). Uses `fetch()` with POST — **not** EventSource. EventSource is GET-only and cannot send the question in a request body.

```typescript
// State machine: idle → sending → streaming → settled (or → error)
// Why fetch + POST instead of EventSource:
//   1. EventSource only supports GET — no request body for the question
//   2. fetch() lets us put the Bearer token in the Authorization header (not the URL)
//   3. ReadableStream gives us the same chunk-by-chunk behavior

const response = await fetch("/api/v1/chat/stream", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ question: msg, thread_id: threadId }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value, { stream: true });
  if (chunk === "[DONE]") break;     // S8 sentinel: stream is complete
  setStreamingText(prev => prev + chunk);
}
// Move assembled streamingText to messages array; reset to ""
```

- `[DONE]` sentinel: move `streamingText` → `messages` array; reset to `""`
- Citation format `[[TICKER:entityId]]` → rendered as `<Link href="/instruments/{entityId}">{TICKER}</Link>`
- Cancel button: calls `reader.cancel()` + resets to idle state
- Network error: state → error; partial text preserved; Retry button shown

**Comments to include**: Why fetch+POST not EventSource (GET-only limitation); why token in header not URL (security); state machine transition diagram; why `useRef` for the reader (cancellable from outside the async loop).

##### T-F10-02: Chat Page Assembly
**Target files**: `app/(app)/chat/page.tsx`
**Layout**: ThreadSidebar (w-64, left) + ChatStream (flex-1, center) + MorningBriefCard (w-80, right, reused from F-5).

#### Validation Gate
- [ ] `chat-stream.test.tsx` — POST /chat/stream fires with Bearer header; tokens assembled; `[DONE]` → message finalized
- [ ] Chat request has NO `?token=` in URL (Bearer header only — security)
- [ ] Cancel button calls `reader.cancel()` during streaming
- [ ] Thread sidebar creates/deletes threads

---

### Wave F-11: Alerts Page

**Goal**: Implement the Alerts & News page with tabbed layout (Alerts, News Feed, Top Today).
**Depends on**: F-4 (alert stream context), F-7 (news components)
**Estimated effort**: 45 min

#### Tasks

##### T-F11-01: AlertsList + AlertCard + SeverityBadge + Alerts Page
**Target files**:
- `src/components/alerts/AlertsList.tsx`
- `src/components/alerts/AlertCard.tsx`
- `src/components/alerts/SeverityBadge.tsx`
- `app/(app)/alerts/page.tsx`

**AlertsList**: `GET /v1/alerts/pending?limit=50`. Filter by severity. Ack button calls `DELETE /v1/alerts/{id}/ack`. Real-time updates from `AlertStreamContext`.

**AlertCard**: Server Component. Severity badge + type + entity + time (font-mono) + message.

**SeverityBadge**: CRITICAL=destructive, HIGH=amber, MEDIUM=blue, LOW=muted.

**Page tabs**: Alerts | News Feed (`GET /v1/news/relevant`) | Top Today (`GET /v1/news/top`).

#### Validation Gate
- [ ] Alerts tab shows paginated list with ack button
- [ ] Severity badge colors correct for each level
- [ ] News tabs render article cards

---

### Wave F-12: Workspace Page

**Goal**: Implement the configurable Workspace with drag-and-drop panel grid and all 8 panel types.
**Depends on**: F-3, F-4, F-6, F-10
**Estimated effort**: 90 min

#### Tasks

##### T-F12-01: WorkspaceContext + WorkspaceGrid
**Target files**:
- `src/contexts/WorkspaceContext.tsx`
- `src/components/workspace/WorkspaceGrid.tsx`
- `app/(app)/workspace/page.tsx`

**WorkspaceContext**: Active ticker shared across panels. Layout persisted to `localStorage` (key: `wv:workspace:layout:{user_id}`). Parse with try/catch, fall back to default layout on error (per §9 Failure Modes — "localStorage quota exceeded").

**WorkspaceGrid**: `react-grid-layout` with `<ResponsiveGridLayout>`. Dynamic import (`ssr: false` — browser API). 12-column grid. Default layout: ChartPanel (large, left) + NewsPanel (medium, right) + AlertsPanel (small, right).

##### T-F12-02: Panel Types (8 panels)
**Target files**: `src/components/workspace/panels/`

Each panel is a thin wrapper around existing page components:
- `ChartPanel` — OHLCVChart + ticker input (uses WorkspaceContext active ticker)
- `NewsPanel` — WatchlistNews for active ticker
- `AlertsPanel` — AlertsList (compact version)
- `ChatPanel` — ChatStream (mini version from F-10)
- `WatchlistPanel` — Watchlist price list
- `ScreenerPanel` — FilterForm + ResultsTable (compact)
- `GraphPanel` — EntityGraph for active ticker
- `BriefingPanel` — MorningBriefCard (compact)

Add panel button: dropdown to add any panel type to the grid.

#### Validation Gate
- [ ] Workspace renders with default layout
- [ ] Panels draggable and resizable
- [ ] Layout persisted to localStorage
- [ ] Active ticker shared across panels via WorkspaceContext

---

### Wave F-13: Settings + Landing Page

**Goal**: Implement the Settings page and the public Landing page with all sections.
**Depends on**: F-2
**Estimated effort**: 60 min

#### Tasks

##### T-F13-01: Settings Page
**Target files**: `app/(app)/settings/page.tsx`, `src/components/settings/`
**Sections**: Profile (display name, email read-only from `GET /v1/auth/me`), Notifications (alert severity threshold, email digest via `PUT /v1/email/preferences`), Appearance (dark mode note — always dark for MVP), Connected accounts (brokerage connection list from PLAN-0022).

##### T-F13-02: Landing Page
**Target files**: `app/page.tsx`, `src/components/landing/`
**Sections** (per PRD §6.5):
1. Nav bar — logo + "Log in" + "Get started" buttons
2. Hero — headline + CTA + hero mockup image
3. Feature comparison table (Worldview vs Bloomberg vs TradingView)
4. 6 feature highlight cards
5. Pricing — 3 tiers (Free, Pro $29/mo, Enterprise)
6. Trust bar
7. FAQ accordion (5 questions)
8. Footer

No auth required. Pure Server Components (no `"use client"` except FAQ accordion interactive element).

**`next/image` requirement (ADR-F-20)**:
The hero mockup image MUST use `next/image` `<Image>` with `priority` prop (it is the LCP element):
```tsx
import Image from "next/image";
// ...
<Image
  src="/images/dashboard-mockup.png"
  alt="Worldview dashboard — Bloomberg-grade research"
  width={1200}
  height={720}
  priority  // ADR-F-20: LCP element — priority disables lazy-load to avoid LCP penalty
  className="rounded-lg shadow-2xl"
/>
```
All other images on the landing page (trust logos, feature icons) also use `<Image>` but WITHOUT `priority` (lazy loading is correct for below-fold content).

All internal navigation links (nav bar, CTA buttons linking to `/login`) use `next/link` `<Link>`, not `<a>`. Exception: external links (e.g. terms of service) may use `<a target="_blank" rel="noopener noreferrer">`.

#### Validation Gate
- [ ] Landing page loads without auth
- [ ] Settings page shows profile data
- [ ] `e2e/landing.spec.ts` — all sections visible; CTA links to /login

---

### Wave T-1: Full Test Suite

**Goal**: Complete Vitest unit tests, integration tests with MSW, and Playwright E2E specs for the full application.
**Depends on**: F-1..F-13 (all frontend waves)
**Estimated effort**: 90 min

#### Tasks

##### T-T1-01: Vitest Unit Test Completion
**Target files**: `apps/worldview-web/tests/unit/`
**Tests to write**: All unit tests from PRD §11.1 not yet written inline in F-2..F-13 waves. See PRD §11.1 for the full test matrix. Key files with the most scenarios:

| Priority File | # Scenarios | Key scenarios |
|---|---|---|
| `market-schedule.test.ts` | 17 | All exchanges, boundary times, weekends, lunch breaks |
| `useAlertStream.test.ts` | 9 | ws-token fetch, WS open with token, backoff, reconnect, cleanup |
| `ChatStream.test.tsx` | 14 | POST body, header, streaming, [DONE], cancel, error, citations |
| `AuthContext.test.tsx` | 6 | refresh, expiry timer, login/logout |
| `FlashOverlay.test.tsx` | 7 | render, 12s auto-dismiss, Escape, multiple criticals, cleanup |
| `authClient.test.ts` | 4 | Bearer header, 401 retry, double-401, concurrent-401 |

**Setup**: `vitest.config.ts` with jsdom environment + MSW browser setup file.

##### T-T1-02: Integration Tests (MSW server)
**Target files**: `apps/worldview-web/tests/integration/`
**Tests** (per PRD §11.2 — complete list):

| Test File | Key Behavior | Priority |
|---|---|---|
| `dashboard-load.test.tsx` | All 7 panels query simultaneously (no waterfall) | HIGH |
| `auth-flow.test.tsx` | Silent refresh → isAuthenticated → children render | HIGH |
| `auth-double-401.test.tsx` | Concurrent 401s → single refresh → both retried | HIGH |
| `auth-expired-mid-session.test.tsx` | Token expiry → silent refresh (fake timers) | HIGH |
| `alert-ws-connect.test.tsx` | ws-token fetch → WS open → CRITICAL → FlashOverlay | HIGH |
| `alert-ws-reconnect.test.tsx` | WS drop → reconnect → fresh ws-token fetched | HIGH |
| `alert-ack.test.tsx` | Acknowledge → DELETE → removed from list | HIGH |
| `chat-full-flow.test.tsx` | No thread → POST /threads → POST /chat/stream → [DONE] → message | HIGH |
| `chat-cancel.test.tsx` | Cancel → reader.cancel() → state idle | HIGH |
| `chat-error-retry.test.tsx` | Network error → error state → Retry → new POST | HIGH |
| `chat-citations.test.tsx` | `[[AAPL:uuid]]` → Link to /instruments/uuid | HIGH |
| `instrument-tabs.test.tsx` | Tab switching loads correct content | HIGH |
| `workspace-persist.test.tsx` | Drag → localStorage → reload → restored | HIGH |
| `portfolio-add-transaction.test.tsx` | Form submit → POST /transactions → holdings refresh | HIGH |
| `screener-filter-run.test.tsx` | Add filter → submit → results in table | HIGH |

##### T-T1-03: Playwright E2E Specs
**Target files**: `apps/worldview-web/tests/e2e/`
**Specs** (per PRD §11.3 — complete list):

| Spec File | # Tests | Highlights |
|---|---|---|
| `auth.spec.ts` | 8 | Full PKCE mock, redirect chain, localStorage null, logout |
| `landing.spec.ts` | 6 | All sections, FAQ, CTA buttons |
| `dashboard.spec.ts` | 6 | Skeleton → data, clock ticks, market pill |
| `chat.spec.ts` | 8 | Streaming tokens, [DONE], cancel, citations, thread nav |
| `alerts.spec.ts` | 8 | WS connect, CRITICAL overlay, Escape, bell badge, ack, reconnect |
| `market-status.spec.ts` | 4 | Stub Date to open/closed, exchange dropdown |
| `instrument.spec.ts` | 6 | Chart canvas, tab switching, graph canvas |
| `screener.spec.ts` | 5 | Add filter, run, results, navigate, paginate |
| `portfolio.spec.ts` | 5 | Holdings table, P&L font-mono, add transaction |
| `workspace.spec.ts` | 5 | Drag, persist, restore, ticker context, corrupt localStorage |
| `settings.spec.ts` | 2 | Profile visible, notification toggle |
| `security.spec.ts` | 5 | localStorage null, no token in URL, CSP header, no direct backend calls, chat header |

##### T-T1-04: Security Invariant Assertions
**Target files**: `apps/worldview-web/tests/e2e/security.spec.ts`
**Required assertions** (from PRD §11.4 — all must pass in CI):
```typescript
// 1. No tokens in localStorage (after full auth flow)
expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBeNull();
expect(await page.evaluate(() => localStorage.getItem("refresh_token"))).toBeNull();
expect(await page.evaluate(() =>
  Object.keys(localStorage).filter(k => k.includes("token"))
)).toHaveLength(0);

// 2. Chat token in header, not URL
const chatRequests = capturedRequests.filter(r => r.url().includes("/chat/stream"));
for (const req of chatRequests) {
  expect(req.url()).not.toContain("token=");
  expect(req.headers()["authorization"]).toMatch(/^Bearer /);
}

// 3. Only WS alerts/stream uses ?token= in URL (not other requests)
const nonWsTokenReqs = capturedRequests.filter(r =>
  r.url().includes("token=") && !r.url().includes("/alerts/stream")
);
expect(nonWsTokenReqs).toHaveLength(0);

// 4. CSP header present on all pages
const res = await page.request.get("/");
expect(res.headers()["content-security-policy"]).toBeDefined();
```

##### T-T1-05: pnpm scripts + CI check
**Target files**: `apps/worldview-web/package.json`
**Scripts to add**:
```json
{
  "scripts": {
    "dev": "next dev --port 3001",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "typecheck": "tsc --noEmit",
    "test": "vitest",
    "test:run": "vitest run",
    "test:e2e": "playwright test",
    "test:security": "playwright test tests/e2e/security.spec.ts"
  }
}
```

#### Validation Gate
- [ ] `pnpm test:run` — all Vitest tests pass (unit + integration)
- [ ] `pnpm typecheck` — no type errors
- [ ] `pnpm lint` — no lint errors
- [ ] `pnpm build` — production build succeeds
- [ ] `pnpm test:e2e` — all Playwright specs pass (mock server required)
- [ ] Security invariants: all 4 assertions pass
- [ ] ≥ 50 unit test scenarios across 17+ test files (see PRD §11.1)
- [ ] ≥ 15 integration tests (see PRD §11.2)
- [ ] ≥ 70 E2E test scenarios across 12 spec files (see PRD §11.3)

---

## Risk Assessment

### Critical Path
F-1 → F-2 → F-3 + F-4 → F-5 → F-12 → T-1

The longest dependency chain. F-5 (Dashboard) requires all S9 waves + F-3 + F-4 to be complete.

### Highest Risk Waves
1. **F-6** (Instrument Detail + sigma.js): sigma.js WebGL in SSR environment requires careful `dynamic(() => import(...), { ssr: false })` usage. ErrorBoundary is mandatory.
2. **F-4** (Alert WebSocket): ADR-F-02 pitfall — WebSocket through Next.js rewrites fails silently. Must use `NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8010` (S10 direct). Additionally, must fetch a fresh ws-token via `GET /api/v1/auth/ws-token` before each connection attempt (added in S9-2 T-S9-2-04). Token in `?token=` URL param (not header — browser WS API limitation).
3. **S9-3** (Heatmap composition): Making 11 parallel S3 calls may expose rate limiting issues (BP-114). Use `asyncio.gather(*calls, return_exceptions=True)`.

### Rollback Strategy
- S9 waves only add routes; they are non-breaking. Roll back by removing the routes from proxy.py.
- Frontend is a new service (`apps/worldview-web/`); the old `apps/frontend/` continues running. Rollback = stop `worldview-web` service.

### Testing Gaps
- S9 composed endpoints (heatmap, top-movers) will have limited unit tests since they compose from S3 screener data. Integration tests require a running S3 instance.
- Briefing routes (S9-1) currently stub against a non-existent S8 endpoint — Playwright E2E will see 404/503 from briefings until S8 adds the GET endpoint.

---

## Compounding Check

After completing this plan:
- `docs/services/api-gateway.md` should be updated to document the ~20 new proxy routes added in S9-1..S9-3 waves.
- `apps/worldview-web/.claude-context.md` should be created in Wave F-1 (or after) documenting the new service structure, key patterns, pitfalls, and test commands.
- `docs/plans/TRACKING.md` must be updated to register this plan (done below).
