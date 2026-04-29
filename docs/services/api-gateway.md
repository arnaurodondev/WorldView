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

### Composition Endpoints (multi-service aggregation)

| Method | Path | Sources | Auth |
|--------|------|---------|------|
| GET | `/v1/companies/{id}/overview` | S3 (fundamentals + OHLCV) + S5 (news) | Yes |
| GET | `/v1/market/heatmap` | S3 (11 parallel sector-average screener calls) | Yes |
| GET | `/v1/market/top-movers` | S3 (sorted by daily_return) | Yes |
| GET | `/v1/map/layers` | S3 (GeoJSON overlays) | No |

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
| GET | `/v1/entities/{entity_id}/graph` | Entity relationship graph | Yes |
| GET | `/v1/entities/{entity_id}/contradictions` | Entity contradictions | Yes |
| POST | `/v1/entities/similar` | Find similar entities (vector search) | No |

### Portfolio Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/portfolios` | List portfolios | Yes |
| GET | `/v1/portfolios/{id}/value-history` | Equity-curve snapshots (PLAN-0046 / T-46-5-01) | Yes |
| GET | `/v1/portfolios/{id}/exposure` | Invested / cash / leverage breakdown (PLAN-0046 / T-46-5-02) | Yes |
| GET | `/v1/portfolios/{id}/realized-pnl` | Realised P&L (FIFO, PLAN-0051 / T-A-1-04). Forwards `from`/`to`. Adds `Cache-Control: max-age=300` on 200. | Yes |
| GET | `/v1/holdings/{portfolio_id}` | Holdings for a portfolio | Yes |
| GET | `/v1/transactions` | List transactions (API-004: `portfolio_id` forwarded as `X-Portfolio-ID` header, not query param) | Yes |
| POST | `/v1/transactions` | Create transaction | Yes |

### Watchlist Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/watchlists` | List watchlists | Yes |
| POST | `/v1/watchlists` | Create watchlist | Yes |
| GET | `/v1/watchlists/{id}` | Get watchlist | Yes |
| DELETE | `/v1/watchlists/{id}` | Delete watchlist | Yes |
| POST | `/v1/watchlists/{id}/members` | Add entity to watchlist | Yes |
| DELETE | `/v1/watchlists/{id}/members/{entity_id}` | Remove entity from watchlist | Yes |

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
| DELETE | `/v1/alerts/{alert_id}/ack` | Acknowledge (dismiss) alert | Yes |

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

### Search & Signals Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/search/instruments` | Search instruments by name/ticker | No |
| GET | `/v1/signals/ai` | AI signals (stub — returns empty) | Yes |

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

- **Authenticated**: 100 req/min per `user_id` (key: `rl:v1:user:{user_id}`)
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
| `ALERT_URL` | `http://localhost:8010` | No | S10 URL |
| `RATE_LIMIT_REQUESTS` | `100` | No | Auth rate limit per minute |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | No | Rate limit window |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3001` | No | Comma-separated allowed origins (SEC-008: port 3001 is worldview-web, not 3000) |
| `SERVICE_NAME` | `api-gateway` | No | structlog service name |
| `LOG_LEVEL` | `INFO` | No | Logging level |
| `LOG_JSON` | `true` | No | JSON-formatted logs |
| `OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |

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
└── routes/
    ├── auth.py              # 7 OIDC auth endpoints
    ├── health.py            # /healthz, /readyz
    ├── internal.py          # GET /internal/jwks
    └── proxy.py             # 48 proxy/composition routes
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

## Known Stubs & TODOs

| Endpoint | Status | Reason |
|----------|--------|--------|
| `GET /v1/briefings/morning` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/briefings/instrument/{id}` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/signals/ai` | Stub | Returns empty list — S6 signal API pending |
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

## Local Run

```bash
cd services/api-gateway

# 1. Copy env and configure OIDC + RSA keys
cp configs/dev.local.env.example configs/.env
# Edit configs/.env — set OIDC_* and INTERNAL_JWT_* vars
# Or generate keys: ./scripts/generate-internal-keypair.sh

# 2. Start
make run          # uvicorn on port 8000

# 3. Validate
make test         # unit tests
make lint         # ruff + mypy
make test-integration  # security integration tests (requires Valkey)
```

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
