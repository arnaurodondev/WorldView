# API Gateway / BFF Service (S9)

> **Owner**: Gateway domain · **Database**: None (stateless) · **Port**: 8000
> **Status**: Production-ready · **Spec**: PRD-0025 (auth), PRD-0028 (frontend routes)

---

## Mission & Boundaries

**Owns**: Unified API entry point for the frontend, request routing, response
composition (BFF pattern), authentication/authorization (OIDC + RS256 internal JWT),
rate limiting, per-endpoint caching (Valkey), CORS enforcement, error standardization,
security headers.

**Never does**: Business logic, data persistence, direct database access, LLM
completions, NLP processing.

---

## API Surface — Full Endpoint Reference

All routes are prefixed with `/v1` (main), `/v1/auth` (auth), or `/internal`.

### Authentication Endpoints (`/v1/auth`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/auth/login` | PKCE login — redirect to Zitadel | No |
| GET | `/v1/auth/callback` | PKCE callback — exchange code, provision S1 user, set cookie | No |
| POST | `/v1/auth/refresh` | Rotate refresh_token cookie → new access_token | No |
| POST | `/v1/auth/logout` | Revoke token at Zitadel, clear httpOnly cookie | No |
| GET | `/v1/auth/me` | Return current user profile from access token | Bearer |
| GET | `/v1/auth/register` | Redirect to Zitadel self-registration | No |
| GET | `/v1/auth/ws-token` | Issue 30-second short-lived JWT for WebSocket auth | Yes |
| POST | `/v1/auth/dev-login` | Dev-only login — returns JWT for seed demo user | No |

**`POST /v1/auth/dev-login`**: Available only when `OIDC_DISCOVERY_OPTIONAL=true` and Zitadel is not configured. Returns the same response shape as `/v1/auth/callback` (access token + user profile). Returns `403 Forbidden` when OIDC is configured (production). Used by the frontend "Dev Login" button for local development without Zitadel.

### Health & Internal Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/healthz` | Liveness probe | No |
| GET | `/readyz` | Readiness probe (checks Valkey) | No |
| GET | `/metrics` | Prometheus metrics | No |
| GET | `/internal/jwks` | RS256 public key (JWKS format) for backend JWT verification | No |
| POST | `/internal/v1/service-token` | Mint a service-account RS256 internal JWT (PLAN-0057 Wave A-1 / BP-303) | Shared secret |

**`POST /internal/v1/service-token`** (PLAN-0057 Wave A-1 — closes BP-303):

Mints a 5-minute RS256 internal JWT for background workers. Solves the production "OHLCV auth blackhole" problem where workers minted their `X-Internal-JWT` via `POST /v1/auth/dev-login`, which is hard-blocked when `app_env == "production"`.

Authentication: shared `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` secret + service identity on the allow-list (`routes/internal.py::_ALLOWED_SERVICE_NAMES`). Comparison uses `secrets.compare_digest` (constant-time).

Request body (`application/json`):

```json
{
  "service_name": "nlp-pipeline-price-impact",
  "secret": "<shared-secret>"
}
```

Response (200):

```json
{
  "access_token": "<rs256-jwt>",
  "expires_in": 300,
  "token_type": "Bearer"
}
```

Issued JWT claims: `sub="service:<service_name>"`, `tenant_id="system"`, `role="system"`, `service_name=<name>`, `iss="worldview-gateway"`, 5-minute expiry.

Status codes:
- **200**: secret valid AND `service_name` allow-listed → JWT issued.
- **401**: wrong secret OR unknown service_name (same error to avoid disclosing which check failed).
- **422**: missing/invalid request body (Pydantic validation).
- **503**: `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` unset (deployment misconfiguration) or RSA private key missing.

**This endpoint is NOT guarded by `app_env`** — the shared secret IS the auth boundary, and the endpoint must work in production (that is the whole reason it exists). Each successful mint logs `service_token_issued` with the `service_name` (never the secret nor the JWT).

To register a new service caller:
1. Add the canonical name to `_ALLOWED_SERVICE_NAMES` in `services/api-gateway/src/api_gateway/routes/internal.py`.
2. Distribute the shared `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` to the caller's deployment via sealed secret (matching env var on the caller side, e.g. `NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN`).
3. Update the caller to pass `service_account_token=settings.service_account_token` and `service_name=<canonical-name>` to its HTTP client (see `MarketDataClient` in services/nlp-pipeline for the reference pattern).

### Composition Endpoints (multi-service aggregation)

| Method | Path | Sources | Auth |
|--------|------|---------|------|
| GET | `/v1/companies/{id}/overview` | S3 (fundamentals + OHLCV) + S5 (news) | Yes |
| GET | `/v1/instruments/{id}/page-bundle` | Composes overview + fundamentals + technicals + insider + top-news in one round-trip (PLAN-0059 I-5) | Yes |
| GET | `/v1/market/heatmap` | S3 (11 parallel sector-average screener calls) | Yes |
| GET | `/v1/market/top-movers` | S3 (sorted by daily_return) | Yes |
| GET | `/v1/map/layers` | S3 (GeoJSON overlays) | No |

#### `/v1/instruments/{id}/page-bundle` — initial-load composite (PLAN-0059 I-5)

Collapses the instrument-detail page's overview-tab waterfall into a single
HTTP request. Behavior:

> **Post-F2 (PRD-0089, [ADR-F-16](../architecture/decisions/ADR-F-16-instrument-entity-id-unification.md))**: the historic Phase-1 → Phase-2 re-read (which resolved KG `entity_id` from `overview.instrument.instrument_id`) is gone. ~148 LOC deleted from `clients.py::get_instrument_page_bundle`. A single canonical UUID is used throughout; the bundle's `resolve_security_id(identifier)` accepts either a ticker or a UUID at the URL boundary. The two-phase fan-out is retained only for latency (composition of independent calls).

- **Composition** — two-phase `asyncio.gather`:
  - Phase 1: `get_company_overview` (parallelises 5 calls).
  - Phase 2: full `/api/v1/fundamentals/{id}` + `/technicals-snapshot` +
    `/insider-transactions-snapshot` + S6 `/api/v1/news/entity/{id}?limit=5`. The same id is used in both phases (post-F2: `entity_id == instrument_id`).
- **Per-call failures degrade gracefully** — failed sub-resources return
  `null` in the response. The bundle still returns 200 so the FE renders
  partial UIs rather than seeing a 5xx.
- **Overall timeout** — the whole composition is wrapped in
  `asyncio.wait_for(20s)`. On timeout the bundle returns 200 with all
  sub-fields `null`.
- **Auth required** — explicit `request.state.user is None → 401` guard
  at the route handler.
- **JWT-per-call** — each downstream gets a freshly-signed internal JWT
  via `make_headers` factory so InternalJWTMiddleware's JTI-replay
  detection accepts the parallel fan-out.

Response shape: `{instrument_id, entity_id, overview, fundamentals,
technicals, insider, top_news}`. Sub-resource shapes match the dedicated
endpoints' responses verbatim so clients can prime TanStack Query caches
with bundle.* values.

### News Endpoints (→ S5 Content Store)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/news/relevant` | Most relevant articles (all sources) | No |
| GET | `/v1/news/top` | Top-scored articles (PRD-0026); response includes `sentiment` (positive/negative/neutral/mixed/null) and `impact_score` (FLOAT 0-1/null) per article (PLAN-0050 Wave E) | No |
| GET | `/v1/news/entity/{entity_id}` | Articles for a specific entity; same `sentiment` + `impact_score` fields (PLAN-0050 Wave E) | Yes |

### Chat & Conversation Endpoints (→ S8 RAG/Chat)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat` | Synchronous chat (buffered) | Yes |
| POST | `/v1/chat/stream` | SSE streaming chat (unbuffered, chunked) | Yes |
| POST | `/v1/threads` | Create conversation thread | Yes |
| GET | `/v1/threads` | List threads | Yes |
| GET | `/v1/threads/{thread_id}` | Get thread by ID | Yes |
| PATCH | `/v1/threads/{thread_id}` | Patch mutable thread fields (currently only `title`). Body `{title?: string}`. PLAN-0051 T-E-5-06. Used by chat sidebar inline rename. | Yes |
| DELETE | `/v1/threads/{thread_id}` | Delete thread | Yes |

### Market Data Endpoints (→ S3 Market Data)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/ohlcv/{instrument_id}` | OHLCV price history | Yes |
| POST | `/v1/ohlcv/batch` | Batch OHLCV bars for up to 50 instruments (PLAN-0049 T-A-1-05) — fans out per-symbol calls in parallel; per-symbol failures populate `error` instead of failing the whole batch | Yes |
| GET | `/v1/quotes/{instrument_id}` | Latest quote | Yes |
| POST | `/v1/quotes/batch` | Batch quotes for multiple instruments | Yes |
| GET | `/v1/fundamentals/{instrument_id}` | All fundamentals sections (composite) | Yes |
| GET | `/v1/fundamentals/{instrument_id}/technicals` | Technical indicators snapshot (beta, SMA50/200, short interest) → S3 `/technicals-snapshot` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/share-statistics` | Share statistics (float, short interest, insider/institutional %) → S3 `/share-statistics` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/insider-transactions` | Recent insider buys/sells → S3 `/insider-transactions-snapshot` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/earnings-trend` | Forward EPS/revenue analyst estimates → S3 `/earnings-trend` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/earnings-annual-trend` | Annual earnings projections → S3 `/earnings-annual-trend` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/splits-dividends` | Stock splits and dividend history → S3 `/splits-dividends` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/snapshot` | Pre-computed derived metrics snapshot (eps_ttm, beta, avg_volume_30d, FCF, interest coverage, net_debt_to_ebitda, credit_rating) → S3 `instrument_fundamentals_snapshot` table. Always 200 — all fields null for un-backfilled instruments. PLAN-0050 Wave D. | Yes |
| POST | `/v1/fundamentals/screen` | Dynamic screener | No |
| GET | `/v1/fundamentals/screen/fields` | Available screener fields | No |
| GET | `/v1/fundamentals/timeseries` | Fundamental timeseries | No |
| GET | `/v1/fundamentals/economic-calendar` | Economic events (→ S7 temporal_events, passes `event_type=economic`) | Yes |

**Request body** for `POST /v1/ohlcv/batch` (PLAN-0049 T-A-1-05):

```python
{
    "requests": [
        {
            "instrument_id": str,    # required, ≤64 chars
            "timeframe": str,        # 1m | 5m | 15m | 30m | 1h | 4h | 1d | 1w | 1M (default "1d")
            "start": str | None,     # ISO date; defaults to lookback (3d for ≤5m, 30d for 1h, 90d otherwise)
            "end": str | None,
            "limit": int | None      # 1–2000
        },
        ...
    ]                                # max 50 entries (BP-026 — bounds external blast radius)
}
```

**Response** — partial-success batch (one entry per request, same order):

```python
{
    "results": [
        {"instrument_id": str, "timeframe": str, "bars": [...], "error"?: str},
        ...
    ],
    "fetched_at": str  # ISO-8601 UTC
}
```

Per-symbol failures populate `error` (e.g. `"market-data returned 502"`,
`"HTTPError: timeout"`) instead of failing the whole batch — partial success is
preferable to all-or-nothing for dashboard widgets.

### Entity & Knowledge Graph Endpoints (→ S7)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/entities/{entity_id}` | Entity enrichment detail (description, metadata, data_completeness) | Yes |
| GET | `/v1/entities/{entity_id}/graph` | Entity relationship graph. Query params: `limit`, `min_confidence`, `semantic_mode`, `confidence_breakdown`, `focus_node` (PLAN-0074 Wave G: `confidence_breakdown` + `focus_node` now forwarded) | Yes |
| GET | `/v1/entities/{entity_id}/contradictions` | Entity contradictions | Yes |
| POST | `/v1/entities/similar` | Find similar entities (vector search) | No |
| GET | `/v1/entities/{entity_id}/intelligence` | Full entity intelligence aggregate (health_score, narrative, confidence_breakdown, key_metrics). Valkey-cached 60 s. Query params: `confidence_breakdown`, `focus_node` (PLAN-0074 Wave G) | Yes |
| GET | `/v1/entities/{entity_id}/narratives` | Paginated narrative version history. Query params: `limit`, `cursor` (PLAN-0074 Wave G) | Yes |
| POST | `/v1/entities/{entity_id}/narratives/generate` | Manually trigger narrative generation. Proxy-layer rate limit: 1 req/hr/entity/user via `set_nx` (BP-200). Returns 202. (PLAN-0074 Wave G) | Yes |
| GET | `/v1/entities/{entity_id}/paths` | Pre-computed multi-hop opportunity paths. Valkey-cached 5 min. Query params: `limit`, `min_score`, `min_hops`, `max_hops` (PLAN-0074 Wave G) | Yes |
| GET | `/v1/entities/{entity_id}/sentiment-timeseries` | Daily sentiment aggregates for SENTI chart overlay (PLAN-0091 T-A-2-02). Query param: `days` (1-365, default 90). Proxies to S6 NLP. Returns `{entity_id, days, points: [{date, article_count, avg_relevance, positive_ratio, negative_ratio, avg_impact_score}]}`. All metric fields nullable. | Yes |

### Entity-Context Chat Endpoints (→ S8 RAG-Chat)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat/entity-context` | Synchronous entity-context chat. Pre-validates `entity_id` (UUID) and `question` (non-empty) before proxying to S8. Error pass-through: 429/400/404/422/503 forwarded. (PLAN-0074 Wave G) | Yes |
| POST | `/v1/chat/entity-context/stream` | SSE streaming entity-context chat. Same validation as synchronous endpoint; streams chunks with `text/event-stream`. (PLAN-0074 Wave G) | Yes |

### Portfolio Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/portfolios` | List portfolios. `response_model=list[PortfolioResponse]` | Yes |
| GET | `/v1/portfolios/{id}/value-history` | Equity-curve snapshots (PLAN-0046 / T-46-5-01) | Yes |
| GET | `/v1/portfolios/{id}/exposure` | Invested / cash / leverage breakdown (PLAN-0046 / T-46-5-02) | Yes |
| GET | `/v1/portfolios/{id}/realized-pnl` | Realised P&L (FIFO, PLAN-0051 / T-A-1-04). Forwards `from`/`to`. Adds `Cache-Control: max-age=300` on 200. | Yes |
| GET | `/v1/holdings/{portfolio_id}` | Holdings for a portfolio | Yes |
| GET | `/v1/transactions` | List transactions (API-004: `portfolio_id` forwarded as `X-Portfolio-ID` header, not query param) | Yes |
| POST | `/v1/transactions` | Create transaction | Yes |
| GET | `/v1/portfolio/{id}/bundle` | **BFF bundle (PLAN-0070 C-1)** — collapses portfolio + holdings + transactions + value_history into 1 round-trip. Each leg degrades independently (`null` on failure). `_meta.partial=True` when any leg fails. `asyncio.wait_for(25s)`. UUID validation on `id`. `response_model=PortfolioBundleResponse` | Yes |

### Watchlist Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/watchlists` | List watchlists | Yes |
| POST | `/v1/watchlists` | Create watchlist | Yes |
| GET | `/v1/watchlists/{id}` | Get watchlist | Yes |
| DELETE | `/v1/watchlists/{id}` | Delete watchlist | Yes |
| POST | `/v1/watchlists/{id}/members` | Add entity to watchlist | Yes |
| DELETE | `/v1/watchlists/{id}/members/{entity_id}` | Remove entity from watchlist | Yes |
| GET | `/v1/watchlists/{id}/insights` | Composite insights: `{members_count, movers[{ticker, price, change_pct, news_count, alert_active}], sectors, news, alerts}`. `movers` sorted by `|change_pct|` DESC. Prices sourced from `/internal/v1/price/{iid}` (PriceSnapshot — includes 1D change). Cache-Control max-age=60. PLAN-0050 Wave B / QA iter-1 F-Q1-02. | Yes |

### Brokerage Connection Endpoints (→ S1 Portfolio, PRD-0022)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/brokerage-connections` | Initiate SnapTrade connection | Yes |
| GET | `/v1/brokerage-connections` | List connections | Yes |
| DELETE | `/v1/brokerage-connections/{id}` | Disconnect and revoke | Yes |
| GET | `/v1/brokerage-connections/{id}/callback` | OAuth callback | Yes |
| GET | `/v1/brokerage-connections/{id}/sync-errors` | List sync errors | Yes |

### Alert Endpoints (→ S10 Alert)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/alerts/pending` | List pending alerts | Yes |
| DELETE | `/v1/alerts/{alert_id}/ack` | Acknowledge per-user delivery row | Yes |
| PATCH | `/v1/alerts/{alert_id}/acknowledge` | Tenant-level ack (sets `alerts.acknowledged_at`); idempotent. PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |
| PATCH | `/v1/alerts/{alert_id}/snooze` | Set `alerts.snooze_until` (body `{until: datetime}`; max 30 days out). PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |
| GET | `/v1/alerts/history` | Paginated tenant alert history; query: `severity`, `entity_id`, `from`, `to`, `status` (`active\|acknowledged\|snoozed\|all`), `limit` (≤200), `offset`. PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |

### Admin Endpoints (PLAN-0033)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/api/v1/admin/llm-costs` | Cross-service LLM cost aggregation (S6+S7+S8 fan-out) | Yes (admin role) |

**Query params** for `/api/v1/admin/llm-costs`:
- `period` (optional, `YYYY-MM`, default: current UTC month)
- `provider` (optional, default: `all`; choices: `all`, `deepinfra`, `openrouter`, `gemini`, `ollama`)
- `breakdown` (optional, default: `provider`; choices: `provider`, `capability`, `day`)

**Behaviour**: Fan-out to S6/S7/S8 via `asyncio.gather`. Returns 200 with partial results if 1–2 services fail (failed services return `error` field); returns 503 only when all three fail. Requires `role == "admin"` in the authenticated user context.

### Email Preference Endpoints (→ S10 Alert)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/email/preferences` | Get email preferences | Yes |
| PUT | `/v1/email/preferences` | Update email preferences | Yes |

### Prediction Market Endpoints (→ S3 Market Data, PRD-0019)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/signals/prediction-markets` | List prediction markets | Yes |
| GET | `/v1/signals/prediction-markets/{id}` | Get market detail | Yes |
| GET | `/v1/signals/prediction-markets/{id}/history` | Market price history | Yes |

**Query params** for `GET /v1/signals/prediction-markets`:
- `status` (optional, default `open`; choices: `open`, `resolved`, `cancelled`, `all`)
- `query` (optional, max 200 chars) — case-insensitive `question ILIKE` filter
- `category` (optional, max 50 chars) — PLAN-0049 T-C-3-03.  Suggested values: `macro`, `politics`, `sports`, `crypto`, `general` (non-binding — backend does case-insensitive equality only and never validates the enum, so future Polymarket tags pass through without a code change).  Rows with `category IS NULL` never match a filter.
- `limit` (optional, 1–200, default 50)
- `offset` (optional, default 0)

### Briefing Endpoints (→ S8 RAG/Chat, stub)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/briefings/morning` | AI morning briefing (stub) | Yes |
| GET | `/v1/briefings/instrument/{entity_id}` | Instrument briefing (stub) | Yes |

### Dashboard Snapshot (PLAN-0070 C-2)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/dashboard/snapshot` | **BFF bundle** — collapses 6 dashboard page queries into 1 round-trip: news (top 8), heatmap (11 sectors), prediction_markets (top 5), earnings_calendar (7-day), alerts (top 10), morning_brief. Each leg degrades independently (`null` on failure). `_meta.partial=True` when any leg fails. `asyncio.wait_for(20s)`. `response_model=DashboardSnapshotResponse` | Yes |

### Search & Signals Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/search` | Full-text document search (proxies → S6 /api/v1/search/documents). Params forwarded verbatim: q, entity_id (multi), scope, source_type, date_from, date_to, date_preset, page, page_size. Authenticated only. PLAN-0064 W6. | Yes |
| GET | `/v1/search/instruments` | Search instruments by name/ticker. `response_model=list[InstrumentSearchResult]` | No |
| GET | `/v1/signals/ai` | AI signals (stub — returns empty) | Yes |

### Feedback Endpoints (→ S1 Portfolio, PLAN-0052 Wave D)

Thin proxy from `/v1/feedback/*` → portfolio service `/api/v1/feedback/*`. Anonymous routes accept unauthenticated requests; the gateway issues a system JWT for those.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/feedback/submissions` | Create bug/feature/UX/design feedback | Optional (anon needs `email`) |
| GET | `/v1/feedback/submissions` | List submissions (admin) or own (`?mine=true`) | Yes |
| GET | `/v1/feedback/submissions/anonymous` | List submissions made by unauthenticated users (anon-tenant) | Admin |
| GET | `/v1/feedback/submissions/{id}` | Read one submission (admin or owner) | Yes |
| PATCH | `/v1/feedback/submissions/{id}` | Update status / tags / assigned_to | Admin |
| DELETE | `/v1/feedback/submissions/{id}` | Hard-delete submission (returns 204) | Admin |
| POST | `/v1/feedback/nps` | Submit NPS score (rate-limited to one per 30 days, application-layer) | Yes |
| GET | `/v1/feedback/nps/aggregate?days=30` | Promoter / passive / detractor counts + NPS score | Admin |
| GET | `/v1/feedback/features` | Public roadmap (vote-sorted) | Public |
| POST | `/v1/feedback/features` | Submit a new feature request | Yes |
| PATCH | `/v1/feedback/features/{id}` | Update status / category / is_public on a feature | Admin |
| POST | `/v1/feedback/features/{id}/vote` | Idempotent upvote | Yes |
| POST | `/v1/feedback/micro-survey` | Thumbs-up/down with `survey_key` (used by docs widget) | Optional (anon ok) |
| GET | `/v1/feedback/beta-program/enrollment` | Read user's beta-program state | Yes |
| PATCH | `/v1/feedback/beta-program/enrollment` | Toggle enrolled / programs list | Yes |

PII redaction: all user-supplied free-text fields (`description`, `comment`, `console_logs`) are scrubbed for Bearer/JWT/API-key/email/CC/SSN patterns before persist (see `services/portfolio/src/portfolio/security/pii_redaction.py`).

---

## Middleware Stack

Middleware executes in order for every request:

| Order | Middleware | Purpose |
|-------|-----------|---------|
| 1 | `RequestIdMiddleware` | Validate/generate `X-Request-ID` (ULID), bind to structlog |
| 2 | `SecurityHeadersMiddleware` | X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS |
| 3 | Prometheus middleware | Request count/latency metrics |
| 4 | OTel middleware | Distributed tracing spans |
| 5 | `CORSMiddleware` | Explicit origin allowlist (never `*`), credentials allowed |
| 6 | `RateLimitMiddleware` | Sliding-window counter via Valkey (fail-closed — D-001) |
| 7 | `OIDCAuthMiddleware` | Validate Zitadel RS256 access token → `request.state.user` |
| 8 | `InternalJWTIssuerMiddleware` | Issue RS256 `X-Internal-JWT` for downstream services |

---

## Authentication Architecture (PRD-0025)

### External Auth — OIDC/PKCE (Zitadel)

1. **Login**: `GET /v1/auth/login` generates PKCE state + S256 challenge, stores in Valkey (`auth:pkce:{state}`, TTL 10min), redirects to Zitadel authorization endpoint.
2. **Callback**: `GET /v1/auth/callback` exchanges code for tokens, validates access token, provisions user in S1 via system JWT, sets httpOnly refresh_token cookie.
3. **Refresh**: `POST /v1/auth/refresh` reads httpOnly cookie, exchanges at Zitadel token endpoint.
4. **Logout**: `POST /v1/auth/logout` revokes refresh_token at Zitadel, clears cookie, invalidates Valkey cache.

PKCE state uses **atomic GETDEL** (not GET+DEL) to prevent state replay attacks (BP-146).

### Internal Auth — RS256 JWT

S9 signs every proxied request with an RS256 internal JWT:

| JWT Type | TTL | Use Case |
|----------|-----|----------|
| User JWT | 5 min | Standard authenticated request forwarding |
| System JWT | 60 sec | S9 → S1 user provisioning during OIDC callback |
| WebSocket JWT | 30 sec | Short-lived token for direct WS connection to S10 |

**Backend verification**: All services (S1–S8, S10) run `InternalJWTMiddleware` which fetches S9's public key from `GET /internal/jwks` at startup and validates every non-health request.

**JWT payload** (user type):
```json
{
  "iss": "worldview-gateway",
  "sub": "<user-uuid>",
  "tenant_id": "<tenant-uuid>",
  "oidc_sub": "<zitadel-sub>",
  "role": "user",
  "jti": "<uuid7>",
  "iat": 1700000000,
  "exp": 1700000300,
  "kid": "<sha256-thumbprint>"
}
```

### Legacy Header Removal (2026-04-18)

The `_auth_headers()` helper in `routes/proxy.py` no longer forwards `X-Tenant-Id` or `X-User-Id` headers to downstream services. All backends now extract identity exclusively from the `X-Internal-JWT` token (verified via `InternalJWTMiddleware`). This eliminates the header-spoofing attack vector (see BP-161).

### Public Paths (skip OIDC validation)

`/v1/auth/*`, `/healthz`, `/readyz`, `/metrics`, `/internal/jwks`

---

## Rate Limiting

- **Authenticated**: 300 req/min per `user_id` (key: `rl:v1:user:{user_id}`) — raised from 100 to accommodate multi-panel workspace usage where a single page load may fire 4+ parallel OHLCV calls
- **Unauthenticated**: 20 req/min per IP hash (key: `rl:v1:ip:{sha256(ip)[:16]}`)
- **Fail-closed (D-001)**: If Valkey is unavailable, reject requests with 503 (previously fail-open; changed to fail-closed per security audit decision D-001 on 2026-04-18)
- 429 responses include `Retry-After` header

---

## Caching Architecture

### Valkey Cache

- **Request cache**: Per-endpoint response caching with configurable TTL per route
- **User identity cache**: `auth:user:{sub}` (TTL: 1 hour)
- **PKCE state**: `auth:pkce:{state}` (TTL: 10 min, atomic GETDEL)
- **Rate limit counters**: `rl:v1:{type}:{key}` (TTL: window seconds)

### In-Flight Deduplication

Concurrent identical requests share a single upstream call via `asyncio.Future` dedup:

```python
_inflight: dict[str, asyncio.Future] = {}

async def cached_fetch(key, ttl, fetcher):
    # Check Valkey → check in-flight → single upstream call → cache result
```

Negative caching (120s) prevents thundering herd on upstream failures.

---

## Configuration

All env vars are prefixed with `API_GATEWAY_`:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `HOST` | `0.0.0.0` | No | Bind address |
| `PORT` | `8000` | No | Bind port |
| `DEBUG` | `false` | No | Debug mode |
| `VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey connection |
| `OIDC_ISSUER_URL` | — | **Yes** | Zitadel issuer URL |
| `OIDC_CLIENT_ID` | — | **Yes** | Zitadel client ID |
| `OIDC_CLIENT_SECRET` | — | **Yes** | Zitadel client secret (SecretStr) |
| `OIDC_AUDIENCE` | — | **Yes** | Token audience |
| `OIDC_DISCOVERY_OPTIONAL` | `false` | No | Allow startup without Zitadel (dev/test) |
| `INTERNAL_JWT_PRIVATE_KEY` | — | **Yes** | PEM RSA-2048 private key (SecretStr) |
| `INTERNAL_JWT_PUBLIC_KEY` | — | **Yes** | PEM RSA-2048 public key |
| `FRONTEND_URL` | `http://localhost:5173` | No | CORS + redirect origin |
| `COOKIE_SECURE` | `true` | No | Defaults `true` (PLAN-0030 F-013); set `false` only in local dev |
| `PORTFOLIO_URL` | `http://localhost:8001` | No | S1 URL |
| `MARKET_INGESTION_URL` | `http://localhost:8002` | No | S2 URL |
| `MARKET_DATA_URL` | `http://localhost:8003` | No | S3 URL |
| `CONTENT_INGESTION_URL` | `http://localhost:8004` | No | S4 URL |
| `CONTENT_STORE_URL` | `http://localhost:8005` | No | S5 URL |
| `NLP_PIPELINE_URL` | `http://localhost:8006` | No | S6 URL |
| `KNOWLEDGE_GRAPH_URL` | `http://localhost:8007` | No | S7 URL |
| `RAG_CHAT_URL` | `http://localhost:8008` | No | S8 URL |
| `ALERT_URL` | `http://localhost:8010` | No | S10 HTTP URL |
| `ALERT_WS_URL` | `ws://localhost:8010` | No | S10 WebSocket base URL (separate from HTTP URL for WS routing) |
| `RATE_LIMIT_REQUESTS` | `300` | No | Authenticated rate limit per minute (raised from 100 for multi-panel workspace) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | No | Rate limit window |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3001` | No | Comma-separated allowed origins (SEC-008: port 3001 is worldview-web, not 3000) |
| `APP_ENV` | `development` | No | Environment guard: `development`, `staging`, or `production`. When `production`, `POST /v1/auth/dev-login` returns 403 regardless of OIDC config. |
| `DEV_ADMIN_EMAILS` | `""` | No | Comma-separated emails that receive `role=admin` in dev-login JWTs (dev/staging only; ignored when `APP_ENV=production`) |
| `SERVICE_ACCOUNT_TOKEN` | `""` | No | Shared secret for `POST /internal/v1/service-token`. Must be set in production for background workers to mint RS256 JWTs. |
| `SERVICE_NAME` | `api-gateway` | No | structlog service name |
| `LOG_LEVEL` | `INFO` | No | Logging level |
| `LOG_JSON` | `true` | No | JSON-formatted logs |
| `OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |

---

## S9 Reliability Guarantees (PLAN-0070)

**Timeouts** — every composition endpoint is wrapped in `asyncio.wait_for`:

| Endpoint | Budget |
|----------|--------|
| `GET /v1/instruments/{id}/page-bundle` | 20 s |
| `GET /v1/portfolio/{id}/bundle` | 25 s |
| `GET /v1/dashboard/snapshot` | 20 s |
| `GET /v1/market/heatmap` | 15 s |
| `GET /v1/watchlists/{id}/insights` | 15 s |
| `GET /v1/ohlcv/batch` | 30 s |

On timeout: HTTP 504 with `{"detail": "composition timeout"}`.

**Retry logic** — `_checked_get()` retries 3× with backoff (0.1 s, 0.5 s, 1.5 s) on 500/503 responses. `_checked_post()` does NOT retry (idempotency unsafe).

**JWT factory** — `make_headers=lambda: _auth_headers(request)` is passed to every `asyncio.gather` fan-out so each parallel downstream call gets a fresh JWT with a unique JTI, preventing JTI replay detection failures.

**Pydantic response_model** — 25+ S9 routes have `response_model=` annotations generating named OpenAPI component schemas. The committed spec is at `infra/contracts/s9-openapi.json`; TypeScript types at `apps/worldview-web/types/generated/api.ts`.

**Schemas package** — `services/api-gateway/src/api_gateway/schemas/` contains 9 modules:
`common`, `instruments`, `news`, `portfolios`, `alerts`, `watchlists`, `screener`, `prediction_markets`, `fundamentals`, `dashboard`. All schemas use `ConfigDict(extra="allow")`.

---

## Internal Modules

```
services/api-gateway/src/api_gateway/
├── app.py                   # FastAPI app factory, lifespan (OIDC discovery, RSA keypair)
├── config.py                # Settings (all env vars above)
├── domain.py                # OIDCProviderConfig, InternalJWTClaims dataclasses
├── middleware.py             # OIDCAuth, InternalJWTIssuer, RateLimit, SecurityHeaders
├── oidc.py                  # OIDC discovery, JWKS parse, RSA key utilities
├── jwt_utils.py             # RS256 JWT issuance (user/system/ws)
├── pkce.py                  # PKCE verifier/challenge/state + Valkey storage
├── clients.py               # Typed httpx clients for downstream services
├── schemas/                 # Pydantic response schemas (PLAN-0070 B-1+B-2+C-1+C-2)
│   ├── __init__.py          # Exports all public schemas
│   ├── common.py            # Meta helper
│   ├── instruments.py       # InstrumentSearchResult, OHLCVBar, OHLCVResponse, QuoteResponse
│   ├── news.py              # NewsArticle, NewsTopResponse
│   ├── portfolios.py        # PortfolioResponse, PortfolioBundleResponse
│   ├── alerts.py            # AlertResponse
│   ├── watchlists.py        # WatchlistResponse
│   ├── screener.py          # ScreenerResultItem, ScreenerResponse
│   ├── prediction_markets.py# PredictionMarket, PredictionMarketsListResponse
│   ├── fundamentals.py      # FundamentalsResponse, EarningsCalendarResponse
│   └── dashboard.py         # DashboardSnapshotResponse
└── routes/
    ├── auth.py              # 7 OIDC auth endpoints
    ├── health.py            # /healthz, /readyz
    ├── internal.py          # GET /internal/jwks
    └── proxy.py             # 96 proxy/composition routes
```

---

## Kafka Integration

**None.** S9 is stateless and does not produce or consume Kafka topics.

All messaging is via synchronous HTTP to downstream services and Valkey for caching/state.

---

## Security Headers

Every response includes (via `SecurityHeadersMiddleware`):

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 0`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Strict-Transport-Security: max-age=31536000` (production only, when `COOKIE_SECURE=true`)

### OIDC Callback Error Sanitization (SEC-003)

The `/v1/auth/callback` handler sanitizes `error` and `error_description` query params before JSON reflection:

- **`error`**: Only known RFC 6749 error codes pass through (e.g. `access_denied`, `invalid_scope`). Unknown values become `"unknown_error"`.
- **`error_description`**: Non-alphanumeric special characters are stripped by regex `[^a-zA-Z0-9 _.,!?()\-]`. Truncated to 200 chars.

---

## Error Standardization

```json
{
    "error": {
        "code": "NOT_FOUND",
        "message": "Instrument with ID abc123 not found",
        "status": 404,
        "details": {}
    }
}
```

- **4xx**: Descriptive message from downstream
- **5xx**: Generic "Internal server error" (never leak internals)
- **429**: Includes `Retry-After` header

---

### Portfolio Risk Metrics (Composition — PLAN-0046)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/portfolios/{id}/risk-metrics` | Drawdown, volatility, Sharpe, Sortino, beta vs SPY. Pure S9 composition over S1 value-history + S3 SPY OHLCV. Query param: `lookback_days` (10-3650, default 90). All metrics independently nullable. | Yes |

**Response fields**: `drawdown_max`, `drawdown_current`, `volatility_annualized`, `sharpe`,
`sortino`, `beta_vs_spy`, `n_returns`, `as_of`, `lookback_window`, `data_quality`.

**`data_quality.status` values**:
- `ok` — sufficient data and SPY available
- `insufficient_data` — fewer than 10 daily returns
- `benchmark_unavailable` — SPY OHLCV missing
- `data_anomaly_detected` — contaminated-zero in value series (all metrics suppressed)

### Additional Portfolio Endpoints (S9 → S1)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/portfolios` | Create portfolio | Yes |
| DELETE | `/v1/portfolios/{id}` | Archive portfolio | Yes |
| GET | `/v1/portfolios/{id}/holding-lots` | FIFO lot breakdown per instrument | Yes |
| GET | `/v1/portfolios/{id}/concentration` | Sector/asset class concentration | Yes |
| GET | `/v1/portfolios/{id}/sector-attribution` | Live-priced GICS sector breakdown with day P&L (PLAN-0091 T-A-2-03). Returns `{portfolio_id, buckets: [{sector, holding_count, market_value, sector_weight_pct, sector_day_pnl}], covered_pct, prices_stale?}` | Yes |
| GET | `/v1/portfolios/{id}/performance` | Performance metrics (Calmar, win-rate) | Yes |
| GET | `/v1/portfolios/{id}/transactions` | Transactions nested under portfolio | Yes |

**Transaction note**: `GET /v1/transactions` forwards `portfolio_id` as `X-Portfolio-ID`
header (not query param) to S1 — this is by design (API-004).

### Additional Brokerage Endpoints (S9 → S1)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/brokerage-connections/{id}/balance` | Cash/buying-power (best-effort) | Yes |
| POST | `/v1/brokerage-connections/{id}/sync` | Trigger immediate background sync (202 Accepted) | Yes |

### Prediction Market Categories

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/signals/prediction-markets/categories` | Category counts for currently-open markets | Yes |

### Additional Watchlist Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| PATCH | `/v1/watchlists/{id}` | Rename watchlist | Yes |
| GET | `/v1/watchlists/{id}/members` | List watchlist members | Yes |

### Additional Intelligence/Knowledge Graph Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/search/relations` | ANN search over relation summaries (proxy → S7) | Yes |
| POST | `/v1/claims/search` | Search analyst claims by entity + filters (proxy → S7) | Yes |

### Proposal Confirmation (PLAN-0082)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat/proposals/{proposal_id}/confirm` | Confirm a pending LLM-proposed action (proxied to S8) | Yes |

---

## Known Stubs & TODOs

| Endpoint | Status | Reason |
|----------|--------|--------|
| `GET /v1/briefings/morning` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/briefings/instrument/{id}` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/signals/ai` | Stub | Returns empty list — S6 signal API pending |
| `GET /v1/quotes/stream` | Stub | Returns 501 — streaming quotes not yet implemented |
| WebSocket proxy | N/A | S9 cannot transparently proxy WS; clients connect to S10 directly with 30s token from `GET /v1/auth/ws-token` |

---

## Observability

- **Metrics**: Request count/latency by route, cache hit/miss ratio, rate limit triggers, upstream service latency
- **Log fields**: `service=gateway`, `route`, `upstream_service`, `cache_status`, `tenant_id`
- **Tracing**: OpenTelemetry spans for every upstream call

---

## Testing

| Type | What | Command |
|------|------|---------|
| Unit | Route logic, middleware, JWT utils, PKCE, config | `make test` |
| Integration | Cross-cutting security (headers, CORS, rate limit, JWKS) | `make test-integration` |
| Lint | Ruff + mypy | `make lint` |

**Test suite**: 20 test files, ~3,700 lines of test code, 84+ tests passing.

---

## How to Run Locally

### Option A — Full Docker Compose (Recommended)

```bash
make dev       # launches full platform with MailHog, pgweb, kafka-ui
make seed      # load sample data (seeds a demo user)
make fetch-secrets   # pull API keys and OIDC credentials from worldview-config
```

### Option B — Dev Mode (No Zitadel)

When `OIDC_DISCOVERY_OPTIONAL=true` and no Zitadel is configured, the gateway
starts in **dev mode**:

- `POST /v1/auth/dev-login` is enabled (returns JWT for the seed demo user)
- The frontend's login page automatically shows a "Dev Login" button
- `OIDCAuthMiddleware` passes through requests (no Zitadel validation)

```bash
cd services/api-gateway

# Generate RSA keypair for internal JWT signing
./scripts/generate-internal-keypair.sh
# → writes INTERNAL_JWT_PRIVATE_KEY and INTERNAL_JWT_PUBLIC_KEY to stdout

# Configure
cat > configs/.env << 'EOF'
API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=true
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY="<generate with: openssl genrsa 2048>"
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY="<extract with: openssl rsa -pubout>"
API_GATEWAY_VALKEY_URL=redis://localhost:6379/0
API_GATEWAY_PORTFOLIO_URL=http://localhost:8001
API_GATEWAY_COOKIE_SECURE=false
EOF

make run    # uvicorn on port 8000

# Test dev-login:
curl -X POST http://localhost:8000/v1/auth/dev-login
# → {"access_token": "...", "user": {...}}
```

### Option C — Full Zitadel Integration

1. Create a Zitadel Cloud project at https://zitadel.cloud
2. Create a "Web App" application with PKCE (not client secret)
3. Add redirect URI: `http://localhost:8000/v1/auth/callback`
4. Set env vars:

```bash
API_GATEWAY_OIDC_ISSUER_URL=https://<your-domain>.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=<your-client-id>
API_GATEWAY_OIDC_CLIENT_SECRET=<your-client-secret>
API_GATEWAY_OIDC_AUDIENCE=<your-audience>
API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=false
```

---

## Runbook

### JWKS Endpoint

All backend services fetch S9's public key at startup:
```
GET /internal/jwks
→ {"keys": [{"kty":"RSA","use":"sig","kid":"...","n":"...","e":"AQAB"}]}
```

If a backend cannot reach this endpoint at startup, it retries 3× with 3 s sleep.
After 3 failures, `InternalJWTMiddleware._public_key` is `None` and the service
**passes all requests through** (test-safe, not production-safe).

### Service Token for Background Workers

Workers that need to make authenticated calls to backend services use the service
account token endpoint:

```bash
curl -X POST http://localhost:8000/internal/v1/service-token \
  -H "Content-Type: application/json" \
  -d '{"service_name": "my-worker", "secret": "<API_GATEWAY_SERVICE_ACCOUNT_TOKEN>"}'
# → {"access_token": "...", "expires_in": 300}
```

To add a new worker:
1. Add its name to `_ALLOWED_SERVICE_NAMES` in `routes/internal.py`
2. Set `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` on S9
3. Set the same token value on the worker service

### Registering New Backend Services

Add the service URL to S9's config (e.g. `API_GATEWAY_NEW_SERVICE_URL=http://...`)
and add a typed httpx client in `clients.py`.

---

## Testing

| Type | What | Command |
|------|------|---------|
| Unit | Route logic, middleware, JWT utils, PKCE, config | `make test` |
| Integration | Cross-cutting security (headers, CORS, rate limit, JWKS) | `make test-integration` |
| Lint | Ruff + mypy | `make lint` |

**Test suite**: 20 test files, ~3,700 lines of test code, 84+ tests passing.

Integration tests validate:
- Security headers on all responses
- JWKS endpoint accessible without auth
- Rate limit 429 after threshold
- CORS preflight returns explicit methods (never `*`)

---

## Docker

```yaml
# docker-compose.yml
svc-api-gateway:
  build: { context: ., dockerfile: services/api-gateway/Dockerfile }
  profiles: [runtime]
  ports: ["8000:8000"]
  env_file: services/api-gateway/configs/.env
  depends_on:
    svc-portfolio: { condition: service_started }
    svc-market-data: { condition: service_started }
    valkey: { condition: service_healthy }
```

---

## Common Pitfalls

- **CORS port**: default `CORS_ORIGINS` uses port 3001 (worldview-web), not 3000. Frontend
  on a non-standard port will get CORS errors. Set `API_GATEWAY_CORS_ORIGINS` accordingly.

- **`X-Tenant-Id` / `X-User-Id` headers are dead** — removed after PRD-0025. All backends
  extract identity from `X-Internal-JWT` only. Never forward raw header identity.

- **Rate limiting is fail-closed**: if Valkey is unavailable, all requests are rejected
  with 503 (D-001 security decision). Ensure Valkey is healthy before deploying S9.

- **JTI replay detection**: each parallel fan-out call (e.g. dashboard snapshot) must
  use `make_headers=lambda: _auth_headers(request)` to generate a fresh JWT with a unique
  JTI per downstream call. Reusing the same JWT across parallel calls triggers replay detection.

- **`dev-login` returns 403 in production**: the endpoint is gated behind
  `oidc_config is None`. It is never available when `OIDC_DISCOVERY_OPTIONAL=false`.

- **`COOKIE_SECURE=true` by default**: local dev without HTTPS requires
  `API_GATEWAY_COOKIE_SECURE=false`; otherwise the refresh_token cookie is not sent by the browser.
