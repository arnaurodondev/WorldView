# API Gateway / BFF Service

> **Owner**: Gateway domain · **Database**: None (stateless) · **Port**: 8000
> **Status**: New

---

## Mission & Boundaries

**Owns**: Unified API entry point for the frontend, request routing, response
composition (BFF pattern), authentication/authorization, rate limiting, per-endpoint
caching (Valkey), CORS enforcement, error standardization, API key validation.

**Never does**: Business logic, data persistence, direct database access, LLM
completions, NLP processing.

---

## API Surface

All `/api/v1/*` endpoints are proxied or composed from backend services.
See `docs/MASTER_PLAN.md` § Contracts for the full endpoint table.

### Key Composition Endpoints

| Method | Path | Composed From | Cache Tier |
|--------|------|---------------|------------|
| GET | `/api/v1/company/{id}/overview` | Market Data (instrument + quote + valuation) + Content (recent articles) + Intelligence (signals) | medium |
| GET | `/api/v1/portfolios/{id}/holdings` | Portfolio (holdings) + Market Data (current prices) | private |
| GET | `/api/v1/bootstrap` | Multiple services (critical startup data) | fast |

### Pass-through Endpoints

| Path Prefix | Backend Service |
|-------------|----------------|
| `/api/v1/instruments`, `/api/v1/ohlcv`, `/api/v1/quotes`, `/api/v1/fundamentals`, `/api/v1/securities` | Market Data |
| `/api/v1/portfolios`, `/api/v1/transactions`, `/api/v1/holdings` | Portfolio |
| `/api/v1/articles`, `/api/v1/sources` | Content |
| `/api/v1/signals`, `/api/v1/entities`, `/api/v1/topics`, `/api/v1/search` | Intelligence |
| `/v1/chat` | RAG/Chat S8 — sync chat (buffered) |
| `/v1/chat/stream` | RAG/Chat S8 — SSE streaming (unbuffered, chunked) |
| `/v1/threads`, `/v1/threads/{id}` | RAG/Chat S8 — conversation thread CRUD |

**SSE Note**: `POST /v1/chat/stream` uses `StreamingResponse` with `aiter_bytes()` to forward
Server-Sent Events without buffering. `X-Tenant-Id` and `X-User-Id` headers are injected from
the decoded JWT before forwarding to S8.

---

## Routing Architecture

O(1) route lookup via dictionary-based router (inspired by WorldMonitor):

```python
ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("GET", "/api/v1/instruments"):              ("market-data", "/api/v1/instruments"),
    ("GET", "/api/v1/ohlcv/{instrument_id}"):    ("market-data", "/api/v1/ohlcv/{instrument_id}"),
    ("GET", "/api/v1/quotes/{instrument_id}"):   ("market-data", "/api/v1/quotes/{instrument_id}"),
    ("POST", "/api/v1/chat"):                    ("rag-chat", "/api/v1/chat"),
    # ... full table in service source
}
```

---

## Cross-Cutting Concerns

### Authentication (PRD-0025 — OIDC/Zitadel + RS256 Internal JWT)

Auth is handled entirely by S9. Backends never validate user tokens directly.

| Middleware | Role |
|-----------|------|
| `OIDCAuthMiddleware` | Validates Zitadel RS256 access tokens via JWKS cache. Sets `request.state.user`. |
| `InternalJWTIssuerMiddleware` | Issues RS256 `X-Internal-JWT` header for every proxied backend request. |
| `SecurityHeadersMiddleware` | Injects security headers (X-Frame-Options, CSP, etc.) on all responses. |

**Auth flow endpoints** (skip OIDC validation):
- `GET /v1/auth/login` — PKCE login redirect to Zitadel
- `GET /v1/auth/callback` — PKCE callback, provisions S1 user, sets session cookies
- `POST /v1/auth/refresh` — Refresh tokens via Zitadel token endpoint
- `POST /v1/auth/logout` — Revoke tokens, clear cookies
- `GET /v1/auth/me` — Return current user profile

**JWKS endpoint**: `GET /internal/jwks` — returns S9's RS256 public key for backend JWT verification.

**Config vars**:
```
OIDC_ISSUER_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_AUDIENCE
INTERNAL_JWT_PRIVATE_KEY (PEM RSA-2048), INTERNAL_JWT_PUBLIC_KEY
FRONTEND_URL, COOKIE_SECURE
```

### Rate Limiting
- Valkey sliding window counter
- Authenticated: 100 req/min per user (`rl:v1:user:{user_id}`)
- Unauthenticated: 20 req/min per IP (`rl:v1:ip:{sha256(ip)[:16]}`)
- **Fail-open**: if Valkey is unavailable, allow requests (don't block on cache failure)

### CORS
- Explicit origin allowlist (no wildcards)
- Production domain + `localhost:*` for development
- Configurable via env vars

### Error Standardization
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
- 4xx: descriptive message
- 5xx: generic "Internal server error" (never leak internals)
- 429: include `Retry-After` header

---

## Caching Architecture

### In-Flight Dedup

```python
_inflight: dict[str, asyncio.Future] = {}

async def cached_fetch(key: str, ttl: int, fetcher: Callable) -> Any:
    cached = await valkey.get(key)
    if cached and cached != NEGATIVE_SENTINEL:
        return json.loads(cached)
    if key in _inflight:
        return await _inflight[key]
    future = asyncio.get_event_loop().create_future()
    _inflight[key] = future
    try:
        result = await fetcher()
        await valkey.set(key, json.dumps(result), ex=ttl)
        future.set_result(result)
        return result
    except Exception as e:
        await valkey.set(key, NEGATIVE_SENTINEL, ex=120)
        future.set_exception(e)
        raise
    finally:
        _inflight.pop(key, None)
```

### Cache Tier Mapping

Each route is annotated with a cache tier. The middleware reads the tier and applies
the appropriate `Cache-Control` header and Valkey TTL.

---

## Internal Modules

```
services/api-gateway/src/api_gateway/
├── app.py                   # FastAPI app factory, lifespan (OIDC discovery, RSA keypair)
├── config.py                # Settings (OIDC vars, RSA keys, service URLs, rate limits)
├── domain.py                # OIDCProviderConfig, InternalJWTClaims dataclasses
├── middleware.py            # OIDCAuthMiddleware, InternalJWTIssuerMiddleware,
│                            #   RateLimitMiddleware, SecurityHeadersMiddleware
├── oidc.py                  # OIDC discovery, JWKS parse, RSA key utilities
├── jwt_utils.py             # RS256 internal JWT issuance (issue_user_jwt, issue_system_jwt)
├── pkce.py                  # PKCE utilities (verifier, challenge, state) + Valkey state mgmt
├── clients.py               # Typed httpx clients for downstream services
└── routes/
    ├── __init__.py          # Re-exports main_router, auth_router
    ├── auth.py              # OIDC auth endpoints (/v1/auth/login|callback|refresh|logout|me)
    ├── health.py            # /health, /ready
    ├── internal.py          # GET /internal/jwks
    └── proxy.py             # Proxy/composition routes (/v1/chat, /v1/companies, etc.)
```

---

## Observability

- **Metrics**: request count/latency by route, cache hit/miss ratio, rate limit triggers, upstream service latency
- **Log fields**: `service=gateway`, `route`, `upstream_service`, `cache_status`, `tenant_id`

---

## Testing Plan

| Type | What | Command |
|------|------|---------|
| Unit | Route matching, cache tier assignment, rate limiter logic | `make test` |
| Unit | Error handler, auth middleware | `make test` |
| Integration | End-to-end proxy with mocked backends | `make test-integration` |

---

## Local Run

```bash
cd services/api-gateway
cp configs/dev.local.env.example .env
make run       # gateway on port 8000
make test
make lint
```
