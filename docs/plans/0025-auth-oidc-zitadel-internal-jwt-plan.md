# PLAN-0025 — Authentication & Security Foundation
# OIDC/Zitadel, RS256 Internal JWT, S9 Hardening

> **PRD**: `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md`
> **Status**: in-progress (Wave E frontend pending)
> **Total Waves**: 6
> **Estimated Effort**: 8–12 hours
> **Created**: 2026-04-10
> **Updated**: 2026-04-12
> **Blocks**: PLAN-0022 Waves 4–9

---

## Pre-Flight Gate

| Check | Result |
|-------|--------|
| No BLOCKING open questions | PASS — all OQs resolved or DEFERRED (non-blocking) |
| No unverified external API fields | PASS — §16 Reality Check complete in PRD |
| No active cross-plan conflicts | PASS — PLAN-0022 blocked at Wave 3; no active plan modifies same service tables |
| PRD recency | PASS — created 2026-04-10 (today) |
| Architecture compliance | PASS — §17 compliance gate in PRD all green |

---

## Codebase State Verification

| PRD Reference | Type | Expected State | Actual State | Delta |
|--------------|------|---------------|--------------|-------|
| `users.external_id` | DB column | new column | does not exist | add in Wave C |
| `users.role` | DB column | new column | does not exist | add in Wave C |
| `invitations` table | DB table | new | does not exist | create in Wave C |
| `auth_audit_log` table | DB table | new | does not exist | create in Wave C |
| `api_gateway/config.py jwt_secret` | Config var | must be removed | exists (line 29) | remove in Wave A |
| `api_gateway/config.py OIDC_ISSUER_URL` | Config var | must be added | does not exist | add in Wave A |
| `api_gateway/middleware.py AuthMiddleware` | Class | replace with OIDCAuthMiddleware | exists (HS256) | replace in Wave A |
| `api_gateway/middleware.py RateLimitMiddleware` | Class | wired in app | class exists but NOT wired in create_app | wire in Wave A |
| `api_gateway/middleware.py add_cors` | Function | explicit allowlist | wildcard `allow_methods=["*"]` (line 113) | fix in Wave A |
| `portfolio/domain/entities/user.py User` | Domain entity | add external_id, role fields | missing both | update in Wave C |
| `portfolio/domain/enums.py TenantUserRole` | Enum | new enum | does not exist | add in Wave C |
| `portfolio/api/internal.py InternalAuthDep` | Route dep | replace with middleware | all internal routes use it | remove in Wave C |
| `portfolio/api/dependencies.py verify_internal_token` | Function | replace with InternalJWTMiddleware | exists (hmac) | remove in Wave C |
| S2–S10 `InternalJWTMiddleware` | Middleware class | add to all backends | none have it | add in Wave D |

---

## Plan Dependency Graph

```
Wave A (S9 Foundation: config, domain types, middleware classes, JWKS)
    │
    ├──→ Wave B (S9 Auth endpoints: login/callback/refresh/logout/me + tests)
    │       │
    │       └──→ Wave E (Frontend: AuthContext, pages, 401 interceptor)
    │
    ├──→ Wave C (S1 Schema + provision endpoint + InternalJWTMiddleware)
    │
    ├──→ Wave D (S2–S10 InternalJWTMiddleware, remove old InternalAuthDep)
    │
    └──→ Wave F (Infrastructure: Zitadel Terraform, docker-compose.zitadel.yml,
                 keypair script, Traefik, S9+S1 integration tests)
         │
         └── Wave F partially depends on Wave B (integration tests need auth endpoints)
```

**Critical path**: Wave A → Wave B → Wave E
**Parallelizable after Wave A**: Wave C ∥ Wave D ∥ Wave F (infra parts)

---

## Wave Status Tracking

| Wave | Title | Status | Tasks Done/Total |
|------|-------|--------|-----------------|
| Wave A | S9 Foundation & Security Hardening ✅ | done | 7/7 |
| Wave B | S9 Auth Endpoints ✅ | done | 3/3 |
| Wave C | S1 Schema + Provision Endpoint ✅ | done | 8/8 |
| Wave D | Backend Services InternalJWTMiddleware ✅ | done | 10/10 |
| Wave E | Frontend Auth | pending | 0/7 |
| Wave F | Infrastructure + Integration Tests ✅ | done | 6/6 |

---

## Wave A: S9 Foundation & Security Hardening ✅

**Goal**: Replace HS256 `AuthMiddleware` with OIDC-aware middleware classes, expose `/internal/jwks`, fix SEC-001/003/004/007/008, and wire everything into `create_app`.
**Depends on**: none
**Estimated effort**: 90–120 min
**Architecture layer**: infrastructure + config
**Status**: **DONE** — 2026-04-12 · 55 tests pass (23 new) · ruff + mypy clean

### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/config.py` — current config (will be rewritten)
- `services/api-gateway/src/api_gateway/middleware.py` — existing middleware (will be rewritten)
- `services/api-gateway/src/api_gateway/app.py` — lifespan and `create_app` (will be modified)
- `services/api-gateway/src/api_gateway/routes/` — proxy router and health router
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §6.5 (domain model: `OIDCProviderConfig`, `InternalJWTClaims`), §3.4 (security hardening F-20..F-23), §6.2 JWKS endpoint spec

### Tasks

#### T-A-1-01: Update S9 Config — Remove jwt_secret, Add OIDC + Internal JWT vars

**Type**: config
**depends_on**: none
**blocks**: [T-A-1-02, T-A-1-03, T-A-1-04, T-A-1-05]
**Target files**:
- `services/api-gateway/src/api_gateway/config.py`
- `services/api-gateway/pyproject.toml` (add `cryptography` + `PyJWT>=2.8` if not present)

**What to build**:
Remove the insecure `jwt_secret` and `jwt_algorithm` fields (SEC-001). Add OIDC provider config, internal JWT RSA key config, and frontend URL. These are all `SecretStr` or required string fields with no defaults — S9 fails fast on startup if any are missing. This enforces R13 (no secrets in code).

**Entities / Components**:
- **Name**: `Settings` (modified)
- **Key attributes added**:
  ```python
  # OIDC (Zitadel Cloud)
  oidc_issuer_url: str                    # Required; no default (e.g. https://<instance>.zitadel.cloud)
  oidc_client_id: str                     # Required; no default
  oidc_client_secret: SecretStr           # Required; no default
  oidc_audience: str                      # Required; no default (usually same as client_id)

  # Internal JWT (RS256)
  internal_jwt_private_key: SecretStr     # Required; no default — PEM RSA-2048 private key
  internal_jwt_public_key: str            # Required; no default — PEM RSA-2048 public key

  # Frontend
  frontend_url: str = "http://localhost:5173"  # Redirect URI base; overridden in production
  cookie_secure: bool = False             # True in production (Secure cookie flag)
  ```
- **Key attributes removed**: `jwt_secret`, `jwt_algorithm`
- **Key attributes retained**: `valkey_url`, all downstream service URLs, `cors_origins`, `rate_limit_*`, observability vars

**Logic & Behavior**:
- `internal_jwt_private_key` and `oidc_client_secret` must be `SecretStr` so they are never printed in logs or tracebacks
- All new OIDC vars have no defaults (no `= "..."`) so the service refuses to start without them — same fail-fast pattern as existing `jwt_secret` removal
- Add `pyproject.toml` dependency: `cryptography>=42.0`, `PyJWT[crypto]>=2.8` (PyJWT with RSA support)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_settings_fails_without_oidc_issuer_url` | Missing `OIDC_ISSUER_URL` raises `ValidationError` | unit |
| `test_settings_fails_without_internal_private_key` | Missing `INTERNAL_JWT_PRIVATE_KEY` raises `ValidationError` | unit |
| `test_settings_jwt_secret_removed` | `Settings` has no `jwt_secret` attribute | unit |

**Acceptance criteria**:
- [ ] `Settings` has no `jwt_secret` or `jwt_algorithm` fields
- [ ] All 7 new fields are present with correct types
- [ ] `internal_jwt_private_key` and `oidc_client_secret` are `SecretStr`
- [ ] `pyproject.toml` includes `cryptography` and `PyJWT[crypto]`
- [ ] 3 new tests pass

---

#### T-A-1-02: S9 Domain Types — OIDCProviderConfig, InternalJWTClaims

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03, T-A-1-04]
**Target files**:
- `services/api-gateway/src/api_gateway/domain.py` (new file)

**What to build**:
Add the two pure-Python domain types that S9 uses internally. These live in a `domain.py` module (no DB, no external dependencies) following the domain layer independence rule (R12 — domain has no infra imports).

**Entities / Components**:

- **Name**: `OIDCProviderConfig`
  - **Purpose**: In-memory cache of OIDC discovery document for Zitadel
  - **Key attributes**:
    ```python
    @dataclass
    class OIDCProviderConfig:
        issuer: str
        authorization_endpoint: str
        token_endpoint: str
        end_session_endpoint: str
        jwks_uri: str
        public_keys: dict[str, Any]   # kid → RSAPublicKey; typed as Any to avoid cryptography import in domain
        last_refreshed_at: datetime   # UTC-aware
    ```
  - **Invariants**: `last_refreshed_at` is UTC-aware

- **Name**: `InternalJWTClaims`
  - **Purpose**: Typed claim set for RS256 internal JWTs issued by S9
  - **Key attributes**:
    ```python
    @dataclass(frozen=True)
    class InternalJWTClaims:
        sub: str        # user_id (UUIDv7 string) or "system"
        tenant_id: str  # UUIDv7 string; "" for system calls
        oidc_sub: str   # Zitadel subject (for traceability)
        role: str       # "user" | "system"
        jti: str        # new_uuid7() string — for replay prevention
        iat: int        # Unix timestamp UTC
        exp: int        # iat + 300 (user) or iat + 60 (system)
        kid: str        # RSA key ID (sha256 thumbprint)
        iss: str = "worldview-gateway"
    ```
  - **Invariants**: `exp > iat`; `iss == "worldview-gateway"`; `role in ("user", "system")`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_internal_jwt_claims_frozen` | Cannot mutate fields on `InternalJWTClaims` | unit |
| `test_internal_jwt_claims_default_iss` | `iss` defaults to `"worldview-gateway"` | unit |
| `test_oidc_provider_config_created_at_utc` | `last_refreshed_at` is UTC-aware | unit |

**Acceptance criteria**:
- [ ] `services/api-gateway/src/api_gateway/domain.py` exists
- [ ] Both dataclasses defined with correct types
- [ ] No infrastructure imports in domain.py
- [ ] 3 tests pass

---

#### T-A-1-03: OIDCAuthMiddleware + InternalJWTIssuerMiddleware

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: [T-A-1-06]
**Target files**:
- `services/api-gateway/src/api_gateway/middleware.py` (rewrite)

**What to build**:
Replace `AuthMiddleware` (HS256) with two new middleware classes. `OIDCAuthMiddleware` validates Zitadel access tokens via in-memory JWKS cache. `InternalJWTIssuerMiddleware` signs a new RS256 internal JWT for every proxied request. Both classes receive the `OIDCProviderConfig` (set on `app.state` at startup) and the RSA private key.

**Entities / Components**:

- **Name**: `OIDCAuthMiddleware`
  - **Purpose**: Validate Zitadel RS256 access tokens; set `request.state.user` (dict with sub, email, email_verified, tenant_id, user_id from Valkey cache)
  - **Skip paths**: `/v1/auth/login`, `/v1/auth/callback`, `/v1/auth/refresh`, `/v1/auth/logout`, `/health`, `/ready`, `/metrics`, `/internal/jwks`
  - **Key logic**:
    1. Extract `Authorization: Bearer <token>` header
    2. If missing on a non-public path: set `request.state.user = None` (not 401 — individual routes enforce auth)
    3. Decode with `jwt.decode(token, oidc_public_key, algorithms=["RS256"], audience=settings.oidc_audience, options={"require": ["iss","sub","exp","aud"]})`
    4. On `kid` miss in cached keys: call `_refresh_oidc_jwks()` and retry once
    5. On success: lookup `auth:user:{sub}` in Valkey → set `request.state.user = {sub, email, email_verified, user_id, tenant_id}` (from Valkey if hit, else from token claims for me/login/callback routes)
    6. On failure: set `request.state.user = None`

- **Name**: `InternalJWTIssuerMiddleware`
  - **Purpose**: Sign and attach `X-Internal-JWT` to every proxied backend request
  - **When active**: Proxied requests only (paths matching backend service prefixes), not auth endpoints
  - **Key logic**: Issue `InternalJWTClaims` from `request.state.user`; sign with `rsa_private_key`; add `X-Internal-JWT: <token>` to request before forwarding
  - **System JWT**: When `request.state.user` is None (unauthenticated proxied route), skip (individual routes block unauthenticated)

- **Name**: `SecurityHeadersMiddleware`
  - **Purpose**: Inject security headers on every response (SEC-007)
  - **Headers injected**:
    - `X-Frame-Options: DENY`
    - `X-Content-Type-Options: nosniff`
    - `Referrer-Policy: strict-origin-when-cross-origin`
    - `X-XSS-Protection: 0`
    - `Permissions-Policy: geolocation=(), microphone=()`
    - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (only if `COOKIE_SECURE=true`)

- **Updated**: `add_cors(app, origins)` — fix to explicit allowlist:
  ```python
  app.add_middleware(CORSMiddleware,
      allow_origins=origin_list,
      allow_credentials=True,
      allow_methods=["GET","POST","PUT","DELETE","OPTIONS"],
      allow_headers=["Authorization","Content-Type","X-Request-ID","Cookie"],
  )
  ```

- **Retained**: `RateLimitMiddleware` — but update rate-limit key logic to use `user_id` if `request.state.user` is set, else `sha256(IP)[:16]` (SEC-008):
  ```python
  user = getattr(request.state, "user", None)
  if user:
      key = f"rl:v1:user:{user['user_id']}"
      limit = self.max_requests           # 100/min per user
  else:
      ip = request.client.host if request.client else "unknown"
      key = f"rl:v1:ip:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
      limit = 20                          # 20/min per unauthenticated IP
  ```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_security_headers_present_on_all_responses` | `X-Frame-Options`, `X-Content-Type-Options` in every response | unit |
| `test_cors_allows_explicit_methods_only` | OPTIONS request with non-allowlisted method → 403 | unit |
| `test_rate_limit_key_uses_user_id_when_authenticated` | Authenticated request uses `rl:v1:user:{id}` key | unit |
| `test_rate_limit_key_uses_ip_hash_when_unauthenticated` | Unauthenticated uses `rl:v1:ip:{hash}` | unit |
| `test_oidc_middleware_sets_user_on_valid_token` | Valid RS256 JWT → `request.state.user` set | unit |
| `test_oidc_middleware_skips_auth_endpoints` | `/v1/auth/login` passes without Authorization header | unit |

**Acceptance criteria**:
- [ ] `AuthMiddleware` (HS256) deleted
- [ ] `OIDCAuthMiddleware`, `InternalJWTIssuerMiddleware`, `SecurityHeadersMiddleware` defined
- [ ] `add_cors` uses explicit method/header allowlist
- [ ] `RateLimitMiddleware.dispatch` uses user_id or ip-hash key
- [ ] 6 tests pass

---

#### T-A-1-04: JWKS Endpoint + OIDC Discovery Lifespan

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: [T-A-1-06]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/internal.py` (new file)
- `services/api-gateway/src/api_gateway/oidc.py` (new file — OIDC discovery + JWKS utils)
- `services/api-gateway/src/api_gateway/app.py` (add OIDC discovery to lifespan)

**What to build**:
Create the `GET /internal/jwks` endpoint and a module for OIDC discovery and RSA key management. At startup (lifespan), fetch `{OIDC_ISSUER_URL}/.well-known/openid-configuration`, parse into `OIDCProviderConfig`, cache on `app.state.oidc_config`. Load RSA private key from `settings.internal_jwt_private_key`. Expose JWKS of internal public key at `/internal/jwks`.

**Entities / Components**:

- **Name**: `oidc.py` module
  - **`fetch_oidc_discovery(issuer_url, httpx_client) → OIDCProviderConfig`**: GETs `{issuer_url}/.well-known/openid-configuration`; fetches `jwks_uri` to get Zitadel public keys; returns `OIDCProviderConfig`
  - **`load_rsa_private_key(pem: str) → RSAPrivateKey`**: Parses PEM with `cryptography.hazmat.primitives.serialization.load_pem_private_key()`
  - **`rsa_key_id(public_key) → str`**: Returns SHA-256 thumbprint of public key DER bytes (base64url, first 16 chars as kid)
  - **`build_jwks_response(public_key, kid) → dict`**: Returns JWKS JSON `{"keys": [{"kty":"RSA","alg":"RS256","use":"sig","kid":<kid>,"n":<modulus>,"e":"AQAB"}]}`

- **Name**: `/internal/jwks` endpoint
  - **Router**: `internal_router = APIRouter(prefix="/internal")` mounted WITHOUT prefix strip
  - **`GET /internal/jwks`**: Returns `app.state.internal_jwks` (pre-built at startup); `Cache-Control: public, max-age=3600`
  - **Error**: 503 if `app.state.internal_jwks` is None (startup validation prevents this)

- **Lifespan additions** in `app.py`:
  1. Call `fetch_oidc_discovery(settings.oidc_issuer_url, httpx_client)` → set `app.state.oidc_config`
  2. Call `load_rsa_private_key(settings.internal_jwt_private_key.get_secret_value())` → set `app.state.rsa_private_key`
  3. Derive `app.state.rsa_public_key` from private key
  4. Build and set `app.state.internal_jwks = build_jwks_response(public_key, kid)`
  5. If OIDC discovery fails at startup: log error + raise RuntimeError (service cannot function without it)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_jwks_endpoint_returns_rsa_key` | `GET /internal/jwks` returns valid JWKS JSON with `kty=RSA` | unit |
| `test_jwks_endpoint_has_cache_control` | Response has `Cache-Control: public, max-age=3600` | unit |
| `test_rsa_key_id_is_deterministic` | `rsa_key_id(key)` returns same value on repeated calls | unit |
| `test_build_jwks_contains_correct_fields` | `build_jwks_response` includes `kty`, `alg`, `use`, `kid`, `n`, `e` | unit |

**Acceptance criteria**:
- [ ] `services/api-gateway/src/api_gateway/oidc.py` exists with 4 utility functions
- [ ] `services/api-gateway/src/api_gateway/routes/internal.py` has JWKS route
- [ ] `app.py` lifespan fetches OIDC discovery and loads RSA key before yield
- [ ] Service fails to start if OIDC discovery fails (RuntimeError)
- [ ] 4 tests pass

---

#### T-A-1-05: Internal JWT Issuer Utility

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: [T-A-1-06, T-B-1-01]
**Target files**:
- `services/api-gateway/src/api_gateway/jwt_utils.py` (new file)

**What to build**:
Utility functions for issuing internal RS256 JWTs. These are used both by the `InternalJWTIssuerMiddleware` (for proxied user requests) and by the auth callback endpoint (for the system JWT used to call S1's provision endpoint).

**Entities / Components**:
- **`issue_user_jwt(user_id, tenant_id, oidc_sub, private_key, kid) → str`**: Issues user-scoped JWT; `exp = iat + 300`, `role = "user"`, `jti = new_uuid7()`
- **`issue_system_jwt(oidc_sub, private_key, kid) → str`**: Issues system JWT for provisioning; `sub = "system"`, `tenant_id = ""`, `role = "system"`, `exp = iat + 60`
- **`decode_internal_jwt(token, public_key) → dict`**: Decodes and validates RS256 internal JWT; raises `jwt.InvalidTokenError` on failure
- All functions use `jwt.encode()` with `algorithm="RS256"` from PyJWT

**Logic & Behavior**:
- `jti` is always `str(new_uuid7())` — new UUID7 per token
- `iat = int(utc_now().timestamp())`
- `kid` is passed in (from `rsa_key_id(public_key)` computed at startup)
- Never log the full JWT string — only log `kid` and `jti`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_issue_user_jwt_claims_structure` | User JWT has iss, sub, tenant_id, role=user, 5-min exp, jti | unit |
| `test_issue_system_jwt_has_system_role` | System JWT has sub=system, role=system, 60s exp | unit |
| `test_decode_internal_jwt_validates_issuer` | JWT with wrong `iss` → `jwt.InvalidTokenError` | unit |
| `test_decode_internal_jwt_validates_expiry` | Expired JWT → `jwt.InvalidTokenError` | unit |
| `test_jti_is_different_on_each_call` | Two `issue_user_jwt` calls produce different `jti` | unit |

**Acceptance criteria**:
- [ ] `jwt_utils.py` with 3 public functions
- [ ] All use `algorithm="RS256"`
- [ ] Tests use real RSA-2048 keypair generated with `cryptography` (no mocking of key operations)
- [ ] 5 tests pass

---

#### T-A-1-06: Wire Middleware into create_app + Update lifespan

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-03, T-A-1-04, T-A-1-05]
**blocks**: [T-B-1-01]
**Target files**:
- `services/api-gateway/src/api_gateway/app.py`
- `services/api-gateway/src/api_gateway/routes/__init__.py` (add internal router)

**What to build**:
Rewrite `create_app()` to register the new middleware stack in the correct order and mount the internal router. Remove all references to `jwt_secret` and `AuthMiddleware`.

**Logic & Behavior**:
Middleware registration order (Starlette: last added = outermost):
```python
app.add_middleware(RequestIdMiddleware)            # outermost
app.add_middleware(SecurityHeadersMiddleware)      # next
add_prometheus_middleware(app, metrics)
add_otel_middleware(app)
add_cors(app, settings.cors_origins)              # fixed allowlist
app.add_middleware(RateLimitMiddleware, valkey_client=None)  # client set after lifespan
app.add_middleware(OIDCAuthMiddleware, oidc_config=None)    # config set after lifespan
app.add_middleware(InternalJWTIssuerMiddleware, ...)         # innermost (set after lifespan)
```
Note: Middleware that requires `app.state` objects (OIDC config, RSA key) must access them via `app.state` in `dispatch()` rather than in `__init__()`, because lifespan runs after middleware registration.

Include `internal_router` in app's route registration.

**Acceptance criteria**:
- [ ] `create_app()` has no references to `jwt_secret` or `AuthMiddleware`
- [ ] All 5 middleware classes registered
- [ ] `internal_router` included
- [ ] Application starts successfully with valid env vars
- [ ] `GET /health` returns 200 without auth

---

#### T-A-1-07: S9 Foundation Unit Tests

**Type**: test
**depends_on**: [T-A-1-01, T-A-1-02, T-A-1-03, T-A-1-04, T-A-1-05, T-A-1-06]
**blocks**: none
**Target files**:
- `services/api-gateway/tests/unit/test_middleware.py`
- `services/api-gateway/tests/unit/test_jwt_utils.py`
- `services/api-gateway/tests/unit/test_config.py`

**What to build**: Consolidated unit test suite for Wave A components. All unit tests from T-A-1-01 through T-A-1-05 that aren't yet written.

**Tests to write** (minimum 18 total across test files):
| Test Name | File | What It Verifies |
|-----------|------|-----------------|
| `test_settings_fails_without_oidc_issuer_url` | test_config.py | Missing env var → ValidationError |
| `test_settings_fails_without_internal_private_key` | test_config.py | Missing env var → ValidationError |
| `test_settings_jwt_secret_removed` | test_config.py | No jwt_secret attribute |
| `test_security_headers_present` | test_middleware.py | All 5 security headers on every response |
| `test_cors_explicit_allowlist` | test_middleware.py | Wildcard methods rejected |
| `test_rate_limit_user_id_key` | test_middleware.py | Authenticated → rl:v1:user:{id} |
| `test_rate_limit_ip_hash_key` | test_middleware.py | Unauthenticated → rl:v1:ip:{hash} |
| `test_oidc_middleware_skips_auth_paths` | test_middleware.py | /v1/auth/* passes without token |
| `test_oidc_middleware_sets_user_state` | test_middleware.py | Valid token → request.state.user populated |
| `test_jwks_endpoint_200` | test_middleware.py (or test_routes_internal.py) | GET /internal/jwks → 200 |
| `test_build_jwks_structure` | test_jwt_utils.py | JWKS has kty, alg, use, kid, n, e |
| `test_issue_user_jwt_claims` | test_jwt_utils.py | iss, sub, tenant_id, role=user, exp=iat+300 |
| `test_issue_system_jwt_claims` | test_jwt_utils.py | role=system, sub=system, exp=iat+60 |
| `test_decode_jwt_wrong_issuer` | test_jwt_utils.py | InvalidTokenError |
| `test_decode_jwt_expired` | test_jwt_utils.py | InvalidTokenError |
| `test_jti_uniqueness` | test_jwt_utils.py | Two issues → different jti |
| `test_rsa_key_id_deterministic` | test_jwt_utils.py | Same key → same kid |
| `test_internal_jwt_claims_frozen` | test_jwt_utils.py | Cannot mutate InternalJWTClaims |

**Acceptance criteria**:
- [x] All 18+ tests pass
- [x] `ruff check` passes on test files
- [x] `mypy` passes on test files

### Validation Gate
- [x] `ruff check services/api-gateway/src/` — zero errors
- [x] `mypy services/api-gateway/src/` — zero errors
- [x] `python -m pytest services/api-gateway/tests/unit/ -v` — 23 new tests pass
- [x] `GET /health` returns 200 without auth
- [x] `GET /internal/jwks` returns valid JWKS JSON

### Regression Guardrails
- **BP-023 / BP-127** (pre-commit ruff version mismatch): Use `~/.cache/pre-commit/` ruff, not `uvx ruff`. Run `git diff --name-only --cached | grep ".py$" | xargs ~/.cache/pre-commit/repo*/bin/ruff format --check` before committing.
- **BP-065** (pre-commit stash conflict): Fix ruff BEFORE `git add`. Then `git diff --name-only | xargs git add` to sync staged/working-tree copies.
- **R13** (no secrets in code): `INTERNAL_JWT_PRIVATE_KEY` must be `SecretStr` — verify it never appears in `repr()` output.
- **R26** (UoW no auto-commit): Not applicable this wave (stateless S9), but ensure no DB sessions are opened.

---

## Wave B: S9 Auth Endpoints ✅

**Goal**: Implement the 5 OIDC auth endpoints (`/v1/auth/login`, `/v1/auth/callback`, `/v1/auth/refresh`, `/v1/auth/logout`, `/v1/auth/me`) with PKCE, Valkey state management, and user provisioning call to S1.
**Depends on**: Wave A (JWKS, OIDCAuthMiddleware, InternalJWTIssuerMiddleware, jwt_utils)
**Estimated effort**: 90–120 min
**Architecture layer**: application + API
**Status**: **DONE** — 2026-04-12 · 80 tests pass (25 new) · ruff + mypy clean

### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/app.py` — current lifespan, `create_app`
- `services/api-gateway/src/api_gateway/jwt_utils.py` — from Wave A
- `services/api-gateway/src/api_gateway/oidc.py` — from Wave A
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §6.2 (all 6 API specs), §6.7 (data flow A, B, C, D)

### Tasks

#### T-B-1-01: PKCE Utilities + Valkey State Manager

**Type**: impl
**depends_on**: [T-A-1-05] (jwt_utils from Wave A)
**blocks**: [T-B-1-02]
**Target files**:
- `services/api-gateway/src/api_gateway/pkce.py` (new file)

**What to build**:
PKCE-related utilities and Valkey state management for the PKCE auth flow. All pure functions (no side effects), easy to unit test.

**Entities / Components**:
- **`generate_code_verifier() → str`**: Returns 43-char base64url string (32 random bytes, URL-safe base64, no padding) using `secrets.token_urlsafe(32)`
- **`generate_code_challenge(code_verifier: str) → str`**: Returns `base64url(sha256(code_verifier.encode()))` with no padding
- **`generate_state() → str`**: Returns UUID4 string (random nonce for CSRF protection)
- **`store_pkce_state(valkey, state, code_verifier, ttl=600) → None`**: Stores `auth:pkce:{state}` → `code_verifier` with EX=600
- **`retrieve_and_delete_pkce_state(valkey, state) → str | None`**: Gets `auth:pkce:{state}` then DELetes it (atomic single-use); returns None if key missing

**Logic & Behavior**:
- `store_pkce_state` raises `RuntimeError("valkey_unavailable")` if Valkey is None or raises exception — login endpoint catches this and returns 503 (fail-closed per F-02, §9)
- `retrieve_and_delete_pkce_state` uses Valkey pipeline: `GET` + `DEL` in one round-trip

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_pkce_challenge_s256` | `generate_code_challenge(v) == base64url(sha256(v.encode()))` | unit |
| `test_pkce_challenge_no_padding` | No `=` in output | unit |
| `test_code_verifier_length` | 43 chars | unit |
| `test_state_is_uuid4_format` | UUID4 pattern | unit |
| `test_retrieve_deletes_key` | Second retrieve returns None | unit (mock Valkey) |
| `test_retrieve_returns_none_on_missing_key` | Unknown state → None | unit (mock Valkey) |

**Acceptance criteria**:
- [ ] All 5 public functions implemented
- [ ] `generate_code_challenge` produces correct S256 hash (verify against RFC 7636 test vector)
- [ ] 6 tests pass

---

#### T-B-1-02: Auth Endpoints Router

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-03]
**Target files**:
- `services/api-gateway/src/api_gateway/routes/auth.py` (new file)
- `services/api-gateway/src/api_gateway/routes/__init__.py` (add auth_router)

**What to build**:
Implement all 5 auth endpoints as FastAPI route handlers. Each handler reads from `request.app.state` for access to Valkey, OIDCProviderConfig, RSA keys, settings. All endpoints follow F-01..F-07 and §6.2 API specs exactly.

**Entities / Components**:

- **`GET /v1/auth/login`** — F-02:
  1. Generate `state = generate_state()`, `code_verifier = generate_code_verifier()`, `code_challenge = generate_code_challenge(code_verifier)`
  2. Store `state → code_verifier` in Valkey (TTL=600). If Valkey unavailable: return 503
  3. Build Zitadel authorization URL with `client_id`, `redirect_uri = f"{settings.frontend_url}/callback"`, `scope = "openid profile email offline_access"`, `state`, `code_challenge`, `code_challenge_method=S256`
  4. Return `RedirectResponse(url, status_code=302)`

- **`GET /v1/auth/callback`** — F-03:
  1. If `error` query param present → return 400 `{"error": error, "error_description": error_description}`
  2. Validate `code` and `state` present → 400 if missing
  3. Retrieve `code_verifier` from Valkey (delete on read) → 400 if not found ("state expired or invalid")
  4. POST to `oidc_config.token_endpoint` with `{grant_type=authorization_code, code, redirect_uri, client_id, code_verifier, client_secret}` → 400 if Zitadel rejects
  5. Validate returned `access_token` via `jwt.decode()` with Zitadel JWKS → 401 if invalid
  6. Extract `{sub, email, email_verified, preferred_username}` from claims
  7. Issue system internal JWT via `issue_system_jwt(sub, private_key, kid)`
  8. POST to `{settings.portfolio_url}/internal/v1/users/provision` with body `{sub, email, username=preferred_username}` and header `X-Internal-JWT: <system_jwt>` → 503 if S1 unreachable
  9. Cache `auth:user:{sub}` → `{user_id, tenant_id}` in Valkey (TTL=3600)
  10. Set httpOnly cookie (per §4 cookie attributes)
  11. Return 200 JSON: `{access_token, expires_in, token_type="Bearer", user: {user_id, tenant_id, email, sub, email_verified}}`

- **`POST /v1/auth/refresh`** — F-04:
  1. Read `refresh_token` from cookie (`request.cookies.get("refresh_token")`) → 401 if missing
  2. POST to `oidc_config.token_endpoint` with `{grant_type=refresh_token, refresh_token, client_id, client_secret}` → 401 if Zitadel rejects
  3. Set new `refresh_token` cookie (rotate)
  4. Return 200 `{access_token, expires_in, token_type}`

- **`POST /v1/auth/logout`** — F-05:
  1. Read `refresh_token` from cookie (continue even if missing — best-effort)
  2. If `refresh_token`: POST to Zitadel `end_session_endpoint` (timeout=5s; log error, continue if fails)
  3. Extract `sub` from `Authorization: Bearer` access_token if present → delete `auth:user:{sub}` from Valkey
  4. Set `Set-Cookie: refresh_token=; Max-Age=0; Path=/v1/auth/refresh; HttpOnly; SameSite=Strict`
  5. Return 200 `{"message": "Logged out successfully"}`

- **`GET /v1/auth/me`** — F-06:
  1. Require `Authorization: Bearer` header; decode with Zitadel JWKS → 401 if invalid
  2. Lookup `auth:user:{sub}` in Valkey → get `{user_id, tenant_id}`
  3. Return 200 `{user_id, tenant_id, email, sub, email_verified}`

**Logic & Behavior**:
- Cookie attributes: `httponly=True`, `samesite="strict"`, `path="/v1/auth/refresh"`, `max_age=2592000`, `secure=settings.cookie_secure`
- Log structured fields: `sub=<sub>`, `email=<email>`, `event=<login|refresh|logout|me>`, `result=<success|error>`
- **Never log**: `access_token`, `refresh_token`, `code_verifier`, full JWT strings
- Metrics: `gateway_auth_logins_total`, `gateway_auth_token_refreshes_total`, `gateway_auth_logouts_total` (use Prometheus counter from `app.state.metrics` if available)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_login_redirect_contains_required_params` | 302 URL has client_id, scope, code_challenge, state, redirect_uri | unit |
| `test_login_stores_state_in_valkey` | `auth:pkce:{state}` set with TTL=600 | unit |
| `test_login_503_on_valkey_unavailable` | Valkey down → 503 (fail-closed) | unit |
| `test_callback_missing_state_400` | No state param → 400 | unit |
| `test_callback_unknown_state_400` | State not in Valkey → 400 | unit |
| `test_callback_single_use_state` | Second callback with same state → 400 | unit |
| `test_callback_error_param_400` | `?error=access_denied` → 400 | unit |
| `test_refresh_no_cookie_401` | Missing refresh_token cookie → 401 | unit |
| `test_logout_clears_cookie` | Response has `Set-Cookie: refresh_token=; Max-Age=0` | unit |
| `test_me_endpoint_requires_auth` | No Authorization header → 401 | unit |

**Acceptance criteria**:
- [ ] 5 endpoints implemented at correct paths
- [ ] Cookie attributes exactly match §4 spec (HttpOnly, SameSite=Strict, Path=/v1/auth/refresh)
- [ ] System JWT used for S1 provision call (not user JWT)
- [ ] 10 tests pass

---

#### T-B-1-03: S9 Auth Endpoint Integration Tests

**Type**: test
**depends_on**: [T-B-1-02]
**blocks**: none
**Target files**:
- `services/api-gateway/tests/integration/test_auth_flow.py` (new file)

**What to build**:
Integration tests using `httpx.AsyncClient` with the FastAPI test client, mocking Zitadel token endpoint and S1 provision endpoint with `respx` (or `httpx_mock`). Valkey is mocked in-process.

**Tests to write**:
| Test Name | Infrastructure | What It Verifies |
|-----------|---------------|-----------------|
| `test_login_callback_full_flow` | mock Zitadel + mock S1 + mock Valkey | Login → callback → access_token issued, cookie set, user returned |
| `test_refresh_token_rotation` | mock Zitadel + mock Valkey | Refresh → new access_token, new cookie set |
| `test_logout_best_effort` | mock Zitadel | Logout revokes token, clears cookie, returns 200 even if Zitadel fails |
| `test_proxy_request_includes_internal_jwt` | mock backend | Proxied request has `X-Internal-JWT` header |

**Acceptance criteria**:
- [ ] 4 integration tests pass
- [ ] Tests use `AsyncClient` with `ASGITransport`

### Validation Gate
- [x] `ruff check services/api-gateway/src/` — zero errors
- [x] `mypy services/api-gateway/src/` — zero errors
- [x] Unit tests: ≥10 new tests pass (21 new: 9 pkce + 12 auth_routes)
- [x] Integration tests: 4 pass
- [x] No token strings appear in structured logs (verified — only `sub`, `email` in log fields)
- [x] Cookie attributes verified in `test_login_callback_full_flow`

### Regression Guardrails
- **BP-023/BP-127** (ruff version mismatch): See Wave A guardrail.
- **R14** (sanitize logs): Add assertion in at least one test that `access_token` and `refresh_token` values are NOT present in captured log output.
- **PKCE RFC 7636**: `code_challenge` must use S256 method — add RFC test vector assertion.
- **State single-use**: Ensure `retrieve_and_delete_pkce_state` is called (not just `GET`) — test that second callback attempt returns 400.
- **Fail-closed on Valkey down during login**: Do NOT redirect if state cannot be stored (§9 failure modes).
- **BP-NEW — Starlette middleware order**: In Starlette/FastAPI, last `add_middleware()` = outermost (runs FIRST for requests). `InternalJWTIssuerMiddleware` must be registered BEFORE `OIDCAuthMiddleware` so it runs AFTER (is innermost). If registered after OIDCAuth, it runs first with `user=None` and never issues the JWT. Fixed by swapping registration order in `create_app()`.

---

## Wave C: S1 Schema + Provision Endpoint ✅

**Status**: **DONE** — 2026-04-12 · 463 unit tests pass · ruff + mypy clean

**Goal**: Add `external_id`/`role` to users, create `invitations` + `auth_audit_log` tables, implement `ProvisionUserUseCase`, add `POST /internal/v1/users/provision` endpoint, and replace `InternalAuthDep` (hmac) with `InternalJWTMiddleware` (RS256).
**Depends on**: Wave A (InternalJWTMiddleware class pattern from PRD spec; JWKS endpoint running)
**Estimated effort**: 90–120 min
**Architecture layer**: domain → infrastructure → application → API

### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/domain/entities/user.py` — current User entity
- `services/portfolio/src/portfolio/domain/enums.py` — current enums
- `services/portfolio/src/portfolio/api/internal.py` — InternalAuthDep usage on all routes
- `services/portfolio/src/portfolio/api/dependencies.py` — verify_internal_token, InternalAuthDep
- `services/portfolio/src/portfolio/infrastructure/db/models/user.py` — ORM model
- `services/portfolio/src/portfolio/infrastructure/db/repositories/user.py` — user repo
- `services/portfolio/alembic/versions/0006_add_brokerage_tables.py` — last migration (for chain)
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §6.4 (tables), §6.5 (domain model), §3.3 (provisioning), §6.2 provision endpoint

### Tasks

#### T-C-1-01: S1 Domain Changes — User Entity + New Enums + Invitation + AuthAuditEvent

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-03, T-C-1-05]
**Target files**:
- `services/portfolio/src/portfolio/domain/enums.py`
- `services/portfolio/src/portfolio/domain/entities/user.py`
- `services/portfolio/src/portfolio/domain/entities/invitation.py` (new file)
- `services/portfolio/src/portfolio/domain/value_objects.py`

**What to build**:
Extend the S1 domain model with two new enums, two new fields on `User`, a stub `Invitation` entity (domain model only, no use case), and the `AuthAuditEvent` value object used by the provision use case.

**Entities / Components**:

- **`TenantUserRole`** (add to `enums.py`):
  ```python
  class TenantUserRole(StrEnum):
      OWNER = "owner"
      ADMIN = "admin"
      MEMBER = "member"
  ```

- **`AuthAuditEventType`** (add to `enums.py`):
  ```python
  class AuthAuditEventType(StrEnum):
      USER_CREATED = "user_created"
      ACCOUNT_LINKED = "account_linked"
      LOGIN_PROVISIONED = "login_provisioned"
      PROVISION_CONFLICT_409 = "provision_conflict_409"
  ```

- **`User`** (add two fields to existing `@dataclass`):
  ```python
  external_id: str | None = None                    # Zitadel sub; None until OIDC login
  role: TenantUserRole = TenantUserRole.OWNER       # B2B-ready; all OIDC users are OWNER
  ```
  **Invariants**: `external_id` is either None or a non-empty string ≤255 chars; `role` must be a valid `TenantUserRole` member.

- **`Invitation`** (new `entities/invitation.py`):
  ```python
  @dataclass
  class Invitation:
      tenant_id: UUID
      email: str
      role: TenantUserRole          # ADMIN or MEMBER only
      token: str                    # 43-char base64url (32 bytes)
      expires_at: datetime          # UTC-aware; > created_at
      id: UUID = field(default_factory=new_uuid)
      accepted_at: datetime | None = None
      created_at: datetime = field(default_factory=utc_now)
  ```
  **Note**: Schema stub only. No use cases, no endpoints, no repository. The Alembic migration creates the table.

- **`AuthAuditEvent`** (add to `value_objects.py`):
  ```python
  @dataclass(frozen=True)
  class AuthAuditEvent:
      event_type: AuthAuditEventType
      sub: str
      user_id: UUID | None
      email: str | None
      detail: dict[str, str]
      ip_address: str | None = None    # SHA-256[:16] of client IP
  ```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_user_external_id_defaults_to_none` | `User(tenant_id=..., email=...)` has `external_id=None` | unit |
| `test_user_role_defaults_to_owner` | `User(...)` without role → `TenantUserRole.OWNER` | unit |
| `test_invitation_role_not_owner` | `Invitation(role=TenantUserRole.OWNER)` raises ValueError (add validation) | unit |
| `test_auth_audit_event_frozen` | Cannot mutate `AuthAuditEvent` fields | unit |
| `test_tenant_user_role_enum_values` | OWNER=owner, ADMIN=admin, MEMBER=member | unit |

**Acceptance criteria**:
- [ ] `TenantUserRole` and `AuthAuditEventType` in `enums.py`
- [ ] `User` has `external_id` and `role` fields (new optional fields, no change to existing field ordering)
- [ ] `Invitation` dataclass created (schema stub)
- [ ] `AuthAuditEvent` value object created
- [ ] 5 tests pass

---

#### T-C-1-02: S1 Alembic Migrations

**Type**: schema
**depends_on**: none
**blocks**: [T-C-1-03]
**Target files**:
- `services/portfolio/alembic/versions/0007_add_external_id_and_role_to_users.py` (new)
- `services/portfolio/alembic/versions/0008_create_invitations_and_auth_audit_log.py` (new)

**What to build**:
Two forward-compatible migrations. Must not break existing rows. Must follow BP-126 (NOT NULL with server_default).

**Migration 0007** — ALTER users table:
```sql
ALTER TABLE users ADD COLUMN external_id TEXT;
ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner'
    CHECK (role IN ('owner','admin','member'));
CREATE UNIQUE INDEX idx_users_external_id ON users (external_id) WHERE external_id IS NOT NULL;
```
- `external_id`: nullable (existing rows get NULL)
- `role`: NOT NULL with `server_default='owner'` on ORM column + SA `server_default` in migration (BP-126)

**Migration 0008** — CREATE invitations + auth_audit_log:
```sql
CREATE TABLE invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin','member')),
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_invitations_tenant_email ON invitations (tenant_id, email);
CREATE INDEX idx_invitations_expires_at ON invitations (expires_at DESC);

CREATE TABLE auth_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    event_type VARCHAR(50) NOT NULL,
    sub TEXT NOT NULL,
    email TEXT,
    ip_address TEXT,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_auth_audit_sub ON auth_audit_log (sub, created_at DESC);
CREATE INDEX idx_auth_audit_user ON auth_audit_log (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX idx_auth_audit_event_type ON auth_audit_log (event_type, created_at DESC);
```

**Note**: `invitations.id` and `auth_audit_log.id` use `gen_random_uuid()` as DB default. The application layer uses `new_uuid()` (UUIDv7) and passes the ID explicitly. The DB default is a fallback, not the primary source of IDs.

**Downstream test impact**:
- `services/portfolio/tests/integration/test_migrations.py` — if it asserts on migration count or specific head revision, it must be updated to expect head `0008`.

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds on clean DB from 0006
- [ ] `alembic downgrade -1` from 0008 and from 0007 succeed (rollback tested)
- [ ] `users` table has `external_id` (nullable TEXT) and `role` (NOT NULL VARCHAR(20) DEFAULT 'owner')
- [ ] `invitations` table created with all columns
- [ ] `auth_audit_log` table created with all indexes

---

#### T-C-1-03: S1 ORM Models + Repository Updates

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-02]
**blocks**: [T-C-1-04]
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/db/models/user.py`
- `services/portfolio/src/portfolio/infrastructure/db/models/invitation.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/models/auth_audit_log.py` (new)
- `services/portfolio/src/portfolio/infrastructure/db/models/__init__.py`
- `services/portfolio/src/portfolio/infrastructure/db/repositories/user.py`

**What to build**:
Update the `UserModel` ORM to add `external_id` and `role`. Create `InvitationModel` and `AuthAuditLogModel` ORM models (needed for Alembic to detect schema). Add `find_by_external_id` and `find_by_email_without_external_id` methods to the user repository.

**Entities / Components**:

- **`UserModel`** (add columns):
  ```python
  external_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True, index=True)
  role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="owner")
  ```

- **`InvitationModel`** (new model):
  ```python
  __tablename__ = "invitations"
  id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
  tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
  email: Mapped[str] = mapped_column(Text, nullable=False)
  role: Mapped[str] = mapped_column(String(20), nullable=False)
  token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
  expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
  accepted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
  created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
  ```

- **`AuthAuditLogModel`** (new model):
  ```python
  __tablename__ = "auth_audit_log"
  id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
  user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
  event_type: Mapped[str] = mapped_column(String(50), nullable=False)
  sub: Mapped[str] = mapped_column(Text, nullable=False)
  email: Mapped[str | None] = mapped_column(Text, nullable=True)
  ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
  detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
  ```

- **User repository additions**:
  - `async def find_by_external_id(self, external_id: str) → User | None`
  - `async def find_by_email_without_external_id(self, email: str) → User | None` (WHERE external_id IS NULL)
  - `async def link_external_id(self, user_id: UUID, external_id: str) → None` (UPDATE SET external_id=sub)

- **New `AuthAuditLogRepository`** (inline in same file or separate):
  - `async def create(self, event: AuthAuditEvent, user_id: UUID | None) → None`

**Acceptance criteria**:
- [ ] `UserModel` has `external_id` + `role` columns
- [ ] `InvitationModel` and `AuthAuditLogModel` exist and are importable
- [ ] `models/__init__.py` exports all 3 new models
- [ ] 3 new repository methods on user repo
- [ ] `AuthAuditLogRepository.create` implemented

---

#### T-C-1-04: ProvisionUserUseCase

**Type**: impl
**depends_on**: [T-C-1-03]
**blocks**: [T-C-1-05]
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/provision_user.py` (new file)

**What to build**:
The core business logic for idempotent user provisioning via Zitadel `sub`. Follows the 4-step logic from §6.2 and §6.7 (data flow A steps 17–22).

**Logic & Behavior**:
```
Input: sub: str, email: str, username: str | None

1. QUERY: user = repo.find_by_external_id(sub)
   → FOUND: return ProvisionResult(user_id, tenant_id, created=False, linked=False)

2. QUERY: user = repo.find_by_email_without_external_id(email)
   → FOUND:
     UPDATE user SET external_id = sub
     INSERT auth_audit_log {event_type=ACCOUNT_LINKED, sub, user_id=user.id, email, detail={linked_user_id: str(user.id)}}
     COMMIT
     return ProvisionResult(user.id, user.tenant_id, created=False, linked=True)

3. NEITHER FOUND:
     INSERT tenant {id=new_uuid(), name=username or email.split('@')[0], status=active}
     INSERT user {id=new_uuid(), tenant_id=tenant.id, email, external_id=sub, role=owner}
     INSERT auth_audit_log {event_type=USER_CREATED, sub, user_id=user.id, email}
     COMMIT
     return ProvisionResult(user.id, tenant.id, created=True, linked=False)

4. CONFLICT CHECK (before step 3, after step 2 returns None):
   QUERY: user = repo.find_by_email_with_different_external_id(email, sub)
   → FOUND:
     INSERT auth_audit_log {event_type=PROVISION_CONFLICT_409, sub, user_id=user.id, email, detail={conflict_sub: user.external_id}}
     COMMIT
     raise ProvisionConflictError(email=email, conflict_sub=user.external_id)
```

**Notes**:
- Steps 2 and 3 use a single DB transaction (atomicity per §6.2)
- `ProvisionResult` is a dataclass: `{user_id: UUID, tenant_id: UUID, email: str, created: bool, linked: bool}`
- `ProvisionConflictError(DomainError)` raised on step 4 → route handler returns 409

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_provision_creates_user_and_tenant` | New sub → tenant+user created, created=True, linked=False | unit |
| `test_provision_idempotent_same_sub` | Same sub called twice → same user_id, created=False | unit |
| `test_provision_links_by_email` | Existing user with NULL external_id → linked=True | unit |
| `test_provision_409_on_conflict` | Same email, different sub → ProvisionConflictError | unit |
| `test_provision_writes_audit_log_on_create` | auth_audit_log row with USER_CREATED | unit |
| `test_provision_writes_audit_log_on_link` | auth_audit_log row with ACCOUNT_LINKED | unit |

**Acceptance criteria**:
- [ ] `ProvisionUserUseCase.execute(sub, email, username, uow)` implemented
- [ ] `ProvisionResult` dataclass defined
- [ ] `ProvisionConflictError(DomainError)` defined
- [ ] 6 unit tests pass (with mocked UoW/repositories)

---

#### T-C-1-05: S1 InternalJWTMiddleware + Provision Endpoint + SEC-005 Fix

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-04]
**blocks**: none
**Target files**:
- `services/portfolio/src/portfolio/infrastructure/middleware/__init__.py` (new dir)
- `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py` (new file)
- `services/portfolio/src/portfolio/api/routes/provision.py` (new file)
- `services/portfolio/src/portfolio/api/internal.py` (modify: remove InternalAuthDep from all routes)
- `services/portfolio/src/portfolio/api/dependencies.py` (remove verify_internal_token, InternalAuthDep)
- `services/portfolio/src/portfolio/api/routes/tenant.py` (add role=system check on POST /tenants)
- `services/portfolio/src/portfolio/infrastructure/config.py` (add API_GATEWAY_URL)
- `services/portfolio/src/portfolio/api/app.py` (wire InternalJWTMiddleware + lifespan JWKS fetch)

**What to build**:
Add `InternalJWTMiddleware` (RS256 verifier) to S1 to replace the HS256 `InternalAuthDep` pattern. Add the provision endpoint. Fix SEC-005 by restricting `POST /tenants` to system JWTs.

**Entities / Components**:

- **`InternalJWTMiddleware`** (exact implementation from PRD §6.5, code block):
  ```python
  class InternalJWTMiddleware(BaseHTTPMiddleware):
      SKIP_PATHS: frozenset[str] = frozenset({"/health", "/ready", "/metrics", "/internal/v1/health"})
      SKIP_PREFIXES: tuple[str, ...] = ("/health", "/metrics")
      # __init__(self, app, jwks_url: str)
      # startup(): fetch /internal/jwks from API_GATEWAY_URL, cache RSAPublicKey
      # dispatch(): validate X-Internal-JWT; set request.state.tenant_id, user_id, role
      # _refresh_public_key(): fetch JWKS, parse RSA key
  ```
  - Called in FastAPI lifespan: `await middleware_instance.startup()` on 3 attempts with 3s sleep; fail if still down after 3 tries
  - Background task: re-fetch JWKS every 1h via `asyncio.create_task()`

- **Config addition** (S1 settings):
  ```python
  api_gateway_url: str = "http://api-gateway:8000"
  ```
  Remove: `internal_service_token`

- **`POST /internal/v1/users/provision`** (new route in `provision.py`):
  - No `InternalAuthDep` (middleware handles auth)
  - Check `request.state.role == "system"` → 401 if not
  - Pydantic schema:
    ```python
    class ProvisionRequest(BaseModel):
        sub: str            # non-empty, max_length=255
        email: EmailStr     # valid email
        username: str | None = None   # max_length=100
    ```
  - Calls `ProvisionUserUseCase.execute(body.sub, body.email, body.username, uow)`
  - On `ProvisionConflictError`: return 409 `{"detail": "sub conflict on email"}`
  - Response schema:
    ```python
    class ProvisionResponse(BaseModel):
        user_id: UUID
        tenant_id: UUID
        email: str
        created: bool
        linked: bool
    ```

- **Remove `InternalAuthDep`** from all routes in `internal.py`:
  Remove `_auth: InternalAuthDep` parameter from all 5 route handlers. The `InternalJWTMiddleware` now handles authentication. Also remove from `dependencies.py`: `verify_internal_token` function and `InternalAuthDep` type alias.

- **SEC-005 fix** (`tenant.py`): Add `role = request.state.role` check on `POST /v1/tenants`: if `role` is not set or not `"system"`, return 401. (This was previously unauthenticated — middleware now ensures all requests are internally authorized.)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_internal_jwt_middleware_rejects_missing_jwt` | No X-Internal-JWT header → 401 | unit |
| `test_internal_jwt_middleware_rejects_expired` | Expired JWT → 401 | unit |
| `test_internal_jwt_middleware_rejects_wrong_issuer` | iss != worldview-gateway → 401 | unit |
| `test_internal_jwt_middleware_sets_tenant_id` | Valid JWT → request.state.tenant_id set | unit |
| `test_internal_jwt_middleware_skips_health` | GET /health passes without JWT | unit |
| `test_provision_endpoint_creates_user` | POST /internal/v1/users/provision → 200 + user_id | unit |
| `test_provision_endpoint_requires_system_role` | JWT with role=user → 401 | unit |
| `test_provision_endpoint_409_on_conflict` | Conflict sub → 409 | unit |
| `test_post_tenants_requires_system_role` | POST /v1/tenants without system role → 401 | unit |

**Acceptance criteria**:
- [ ] `InternalJWTMiddleware` validates X-Internal-JWT on all non-health S1 routes
- [ ] `verify_internal_token` and `InternalAuthDep` removed from codebase
- [ ] `internal_service_token` config var removed from S1 settings
- [ ] `POST /internal/v1/users/provision` accepts `{sub, email, username}`, returns `{user_id, tenant_id, email, created, linked}`
- [ ] `POST /v1/tenants` requires `role=system`
- [ ] 9 tests pass

---

#### T-C-1-06: S1 Integration Tests (Provision Endpoint)

**Type**: test
**depends_on**: [T-C-1-04, T-C-1-05]
**blocks**: none
**Target files**:
- `services/portfolio/tests/integration/test_provision_endpoint.py` (new file)

**What to build**: Integration tests against real Postgres (using the test database container pattern established in existing integration tests).

**Tests to write**:
| Test Name | Infrastructure | What It Verifies |
|-----------|---------------|-----------------|
| `test_provision_new_user_transaction` | Postgres | tenant + user + audit_log in single transaction; all 3 rows exist after one call |
| `test_provision_links_existing_atomic` | Postgres | UPDATE external_id + audit_log in single transaction |
| `test_provision_concurrent_same_sub` | Postgres | Two concurrent calls for same sub → exactly one user created |
| `test_provision_idempotent_db` | Postgres | Two sequential calls for same sub → same user_id returned |

**Acceptance criteria**:
- [ ] 4 integration tests pass against real Postgres

### Validation Gate
- [x] `ruff check services/portfolio/src/` — zero errors
- [x] `mypy services/portfolio/src/` — zero errors
- [x] `alembic upgrade head` + `alembic downgrade -1` succeeds for both migrations
- [x] Unit tests: 28 new tests pass (8 provision, 8 middleware, 8 endpoint, 4 tenant-auth)
- [ ] Integration tests: 4 pass (requires Docker Postgres)
- [x] `InternalAuthDep` has zero references in codebase (grep confirms)

### Regression Guardrails
- **BP-126** (NOT NULL without server_default): `role` column must have `server_default="owner"` in both the migration AND the ORM `mapped_column`. Test with existing rows.
- **BP-065** (pre-commit stash): Fix ruff before git add.
- **R25** (API layer isolation): `provision.py` route must call `ProvisionUserUseCase`, not repository directly.
- **R26** (explicit UoW commit): `ProvisionUserUseCase` must call `await uow.commit()` explicitly — never rely on context manager auto-commit.
- **R10** (UUIDv7): tenant.id and user.id created in use case use `new_uuid()` from `common.ids`.
- **R11** (UTC timestamps): `expires_at` on Invitation uses UTC-aware datetime.

---

## Wave D: Backend Services InternalJWTMiddleware ✅

**Goal**: Add `InternalJWTMiddleware` to S2, S3, S4, S5, S6, S7, S8, S10. Remove old `X-Internal-Token` / `InternalAuthDep` from each. Add `API_GATEWAY_URL` config to each. Wire auth guards on S10 alert endpoints (D-1 security fix).
**Depends on**: Wave A (`InternalJWTMiddleware` pattern is defined; S9 JWKS endpoint running)
**Estimated effort**: 90–120 min (9 services middleware + S10 route auth guards)
**Architecture layer**: infrastructure (middleware) + config
**Status**: **DONE** — 2026-04-12 · S2=409, S3=432, S4=533, S5=290, S6=403, S7=575, S8=319, S10=334, S9=80, arch=95 tests pass · ruff + mypy clean

### Pre-read (agent must read before starting)
- `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py` — from Wave C (copy this pattern exactly)
- One example service to understand current InternalAuthDep pattern (e.g. `services/alert/` or `services/nlp-pipeline/`)
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §6.5 `InternalJWTMiddleware` code block, §12 migration plan (X-Internal-Token removal)

### Tasks

#### T-D-1-01 through T-D-1-08: Add InternalJWTMiddleware to S2–S8, S10

These 8 tasks are structurally identical. Each is one sub-task for one service. They can be executed in **parallel worktrees** since they touch different services.

For each service `S<N>`:

**Target files**:
- `services/<service>/src/<package>/infrastructure/middleware/__init__.py` (new dir)
- `services/<service>/src/<package>/infrastructure/middleware/internal_jwt.py` (copy from S1 Wave C)
- `services/<service>/src/<package>/infrastructure/config.py` (add `api_gateway_url: str = "http://api-gateway:8000"`)
- `services/<service>/src/<package>/api/app.py` (wire InternalJWTMiddleware + lifespan startup)
- `services/<service>/src/<package>/api/dependencies.py` or routes — remove `verify_internal_token`, `InternalAuthDep`, `X-Internal-Token` references

**Services and their packages**:
| Task | Service | Package |
|------|---------|---------|
| T-D-1-01 | market-ingestion (S2) | `market_ingestion` |
| T-D-1-02 | market-data (S3) | `market_data` |
| T-D-1-03 | content-ingestion (S4) | `content_ingestion` |
| T-D-1-04 | content-store (S5) | `content_store` |
| T-D-1-05 | nlp-pipeline (S6) | `nlp_pipeline` |
| T-D-1-06 | knowledge-graph (S7) | `knowledge_graph` |
| T-D-1-07 | rag-chat (S8) | `rag_chat` |
| T-D-1-08 | alert (S10) | `alert` |

**What to build for each service**:
1. Create `infrastructure/middleware/internal_jwt.py` — exact copy of S1's implementation from Wave C (same class, same SKIP_PATHS, same `startup()`, same `dispatch()`, same `_refresh_public_key()`)
2. Add `api_gateway_url: str = "http://api-gateway:8000"` to `Settings` (no env prefix conflicts — each service has its own env prefix)
3. Remove `internal_service_token` from `Settings` if present
4. In `app.py` lifespan: instantiate `InternalJWTMiddleware(app, jwks_url=f"{settings.api_gateway_url}/internal/jwks")`, call `await middleware.startup()` (3 retries, 3s sleep, RuntimeError if fails), register background JWKS refresh task
5. Wire `InternalJWTMiddleware` in `create_app()` via `app.add_middleware()`
6. Grep for `InternalAuthDep`, `verify_internal_token`, `X-Internal-Token`, `INTERNAL_SERVICE_TOKEN` in this service — remove all occurrences. Routes no longer need a route-level auth dependency; middleware handles it.

**Tests to write** (per service, minimum 3 tests each):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_middleware_rejects_missing_jwt` | No X-Internal-JWT → 401 | unit |
| `test_middleware_rejects_expired_jwt` | Expired JWT → 401 | unit |
| `test_middleware_skips_health_path` | GET /health passes without JWT | unit |

**Acceptance criteria per service**:
- [ ] `InternalJWTMiddleware` wired in `create_app()`
- [ ] `api_gateway_url` in `Settings`
- [ ] `internal_service_token` removed from config and codebase
- [ ] `InternalAuthDep` / `verify_internal_token` / `X-Internal-Token` removed
- [ ] 3 tests pass per service (24 total)
- [ ] `ruff check` + `mypy` pass

---

#### T-D-1-10: S10 Alert Endpoint Auth Guards (D-1 Security Fix)

**Type**: impl
**depends_on**: [T-D-1-08]
**blocks**: [T-D-1-09]
**Target files**:
- `services/alert/src/alert/api/routes.py`
- `services/alert/src/alert/api/dependencies.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py` (add S10 proxy routes)

**What to build**:
All 6 alert endpoints (3 REST + 1 WebSocket) are currently unauthenticated — any caller knowing `user_id` can read any user's alerts. After `InternalJWTMiddleware` is wired in T-D-1-08, the route layer must enforce identity by reading the JWT-injected user identity from `request.state`.

The auth pattern:
- InternalJWTMiddleware sets `request.state.user_id` and `request.state.tenant_id` from the verified RS256 internal JWT
- Routes read these from state instead of accepting them as query parameters
- WebSocket: JWT must be passed as `?token=<access_token>` (browser WS APIs don't support Authorization headers); S9 validates and injects `X-Internal-JWT`

**Logic for each endpoint**:

1. **`GET /api/v1/alerts/pending`**: Remove `user_id: UUID = Query(...)` param. Read from `request.state.user_id`. If missing (unauthenticated): raise `HTTPException(401, "Not authenticated")`.

2. **`DELETE /api/v1/alerts/{alert_id}/ack`**: Same — read `user_id` from `request.state.user_id`.

3. **`GET /api/v1/alerts/stream` (WebSocket)**: WebSocket auth is done via `?token=<access_token>` query param. After accepting the connection, call `app.state.oidc_middleware.validate_token(token)` to get user context. If invalid: send `{"type":"error","code":401}` and close. Set `user_id` from validated token.

4. **Add a `TenantContext` dependency** in `dependencies.py`:
   ```python
   def get_current_user_id(request: Request) -> UUID:
       user_id = getattr(request.state, "user_id", None)
       if user_id is None:
           raise HTTPException(status_code=401, detail="Not authenticated")
       return UUID(str(user_id))
   ```

5. **S9 proxy routes**: Add to S9's proxy config — S10 alert endpoints must be proxied through S9 so the frontend always hits S9 first (rule: frontend never talks directly to backend services). Routes to add:
   - `GET /v1/alerts/pending` → `http://alert-delivery:8010/api/v1/alerts/pending`
   - `DELETE /v1/alerts/{alert_id}/ack` → `http://alert-delivery:8010/api/v1/alerts/{alert_id}/ack`
   - `WS /v1/alerts/stream` → `ws://alert-delivery:8010/api/v1/alerts/stream`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_pending_alerts_requires_auth` | No `request.state.user_id` → 401 | unit |
| `test_ack_requires_auth` | No `request.state.user_id` → 401 | unit |
| `test_pending_alerts_uses_state_user_id` | `request.state.user_id` used, not query param | unit |

**Acceptance criteria**:
- [ ] `user_id` query parameter removed from `GET /api/v1/alerts/pending` and `DELETE` routes
- [ ] `get_current_user_id` dependency raises 401 when `request.state.user_id` absent
- [ ] WebSocket validates token before streaming
- [ ] S9 proxy routes added for all 3 S10 paths
- [ ] 3 new tests pass

---

#### T-D-1-09: Verify X-Internal-Token Removal Across Codebase

**Type**: impl + docs
**depends_on**: [T-D-1-01, T-D-1-02, T-D-1-03, T-D-1-04, T-D-1-05, T-D-1-06, T-D-1-07, T-D-1-08, T-D-1-10]
**blocks**: none
**Target files**:
- `scripts/import_guards/rules.yaml` (add rule: no service reads `request.headers.get("X-Tenant-Id")` directly)
- `docs/services/api-gateway.md` (update auth section)

**What to build**:
1. Add import guard rule per PRD §8 threat model: no backend service should read `X-Tenant-Id` header directly after PRD-0025 (this header is dead — middleware sets `request.state.tenant_id` from the verified JWT).
2. Verify via `grep -r "X-Internal-Token\|InternalAuthDep\|verify_internal_token\|INTERNAL_SERVICE_TOKEN" services/` that zero results remain.
3. Update `docs/services/api-gateway.md` auth section to document the new RS256 internal JWT pattern.

**Acceptance criteria**:
- [ ] Zero grep matches for `X-Internal-Token` in services/ (excluding comments)
- [x] Import guard rule added for `X-Tenant-Id` header direct read
- [x] API gateway service doc updated

### Validation Gate
- [x] `ruff check services/<each service>/src/` — zero errors per service
- [x] `mypy services/<each service>/src/` — zero errors per service
- [x] ≥27 new tests across all services pass (24 middleware + 3 S10 auth guard tests)
- [x] Zero `InternalAuthDep` / `X-Internal-Token` references remaining in any service src
- [x] `GET /api/v1/alerts/pending` returns 401 without valid internal JWT in test

### Regression Guardrails
- **R25** (API layer isolation): Do NOT import `InternalJWTMiddleware` into route handlers. It belongs in infrastructure, wired in `create_app`.
- **Startup ordering**: Backend services require S9 to be healthy (JWKS endpoint reachable) before starting. Ensure `depends_on: api-gateway` in `docker-compose.yml` for each service.
- **BP-023/BP-127**: Pre-commit ruff version. See Wave A.
- **`kid` miss → re-fetch**: Verify each copy of `InternalJWTMiddleware` has the `kid` miss → `_refresh_public_key()` branch.
- **D-1 auth bypass**: Alert `user_id` must come from verified JWT state, never from a user-controllable query parameter. The old `user_id: UUID = Query(...)` pattern on alert routes is a BROKEN access control — any user can read any other user's alerts by passing a different UUID.

---

## Wave E: Frontend Auth

**Goal**: Implement `AuthContext`, `useAuth`, `LoginPage`, `CallbackPage`, `ProtectedRoute`, `authClient`, and wire into `App.tsx`. Add `Authorization` header to all API calls. Handle 401 with silent refresh.
**Depends on**: Wave B (S9 auth endpoints must exist and be callable)
**Estimated effort**: 60–90 min
**Architecture layer**: frontend (React + TypeScript)

### Pre-read (agent must read before starting)
- `apps/frontend/src/App.tsx` — current routing and top-level structure
- `apps/frontend/src/` — existing hooks (e.g. `useAlertStream.ts`) to understand 401 pattern
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §6.6 (frontend changes spec, full detail)
- `apps/frontend/package.json` / `pnpm-lock.yaml` — current dependencies

### Tasks

#### T-E-1-01: AuthContext + useAuth + authClient

**Type**: impl
**depends_on**: none
**blocks**: [T-E-1-02, T-E-1-03]
**Target files**:
- `apps/frontend/src/contexts/AuthContext.tsx` (new)
- `apps/frontend/src/hooks/useAuth.ts` (new)
- `apps/frontend/src/lib/authClient.ts` (new)

**What to build**: React context for auth state + typed API client functions.

**Entities / Components**:

- **`AuthContext.tsx`** — full spec from §6.6:
  ```typescript
  interface AuthUser {
    user_id: string;    // UUIDv7
    tenant_id: string;  // UUIDv7
    email: string;
    sub: string;
    email_verified: boolean;
  }
  interface AuthContextValue {
    user: AuthUser | null;
    access_token: string | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    login: () => void;               // window.location.href = "/v1/auth/login"
    logout: () => Promise<void>;     // POST /v1/auth/logout
    refresh: () => Promise<void>;    // POST /v1/auth/refresh
  }
  ```
  - `AuthProvider` on mount: calls `POST /v1/auth/refresh` silently
    - 200: store `access_token` in state, set `isAuthenticated=true`
    - 401/error: set `isAuthenticated=false`, `isLoading=false` (no redirect — let routes handle)
  - `logout()`: calls `authClient.logout()` → clears `access_token` state → sets `isAuthenticated=false`

- **`useAuth.ts`**: `export const useAuth = () => useContext(AuthContext)`

- **`authClient.ts`** — typed functions:
  - `initiateLogin(): void` — `window.location.href = "/v1/auth/login"`
  - `handleCallback(code: string, state: string): Promise<{access_token: string, user: AuthUser}>` — calls `GET /v1/auth/callback?code=...&state=...`
  - `refreshToken(): Promise<{access_token: string}>` — calls `POST /v1/auth/refresh`
  - `logout(): Promise<void>` — calls `POST /v1/auth/logout`
  - `getMe(access_token: string): Promise<AuthUser>` — calls `GET /v1/auth/me` with Bearer token

**Token storage**:
- `access_token`: React state only (in-memory, never `localStorage`, never cookies). Lost on page refresh → triggers silent `POST /v1/auth/refresh` on mount.
- `refresh_token`: httpOnly cookie managed by S9 (frontend never reads it).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_auth_provider_calls_refresh_on_mount` | POST /v1/auth/refresh called when AuthProvider mounts | unit (Vitest + MSW) |
| `test_auth_context_authenticated_on_200_refresh` | 200 from refresh → isAuthenticated=true | unit |
| `test_auth_context_unauthenticated_on_401_refresh` | 401 from refresh → isAuthenticated=false | unit |
| `test_auth_context_clears_on_logout` | logout() → isAuthenticated=false, access_token=null | unit |

**Acceptance criteria**:
- [ ] `AuthContext.tsx` exports `AuthProvider` and `AuthContext`
- [ ] `useAuth.ts` exports `useAuth` hook
- [ ] `authClient.ts` exports 5 typed functions
- [ ] Token NOT stored in localStorage (assertion in tests)
- [ ] 4 tests pass

---

#### T-E-1-02: LoginPage + CallbackPage + ProtectedRoute

**Type**: impl
**depends_on**: [T-E-1-01]
**blocks**: [T-E-1-04]
**Target files**:
- `apps/frontend/src/pages/LoginPage.tsx` (new)
- `apps/frontend/src/pages/CallbackPage.tsx` (new)
- `apps/frontend/src/components/ProtectedRoute.tsx` (new)

**What to build**: Full auth UI pages per §6.6.

**Entities / Components**:

- **`LoginPage.tsx`**:
  - Renders a single "Log in to Worldview" button
  - On click: `window.location.href = "/v1/auth/login"` (full-page redirect, not AJAX)
  - No form fields, no password handling

- **`CallbackPage.tsx`** (mounted at `/callback`):
  - On mount: extract `code` and `state` from `window.location.search`
  - If `error` param present: show error message + link to `/login`
  - Call `authClient.handleCallback(code, state)` → `GET /v1/auth/callback?code=...&state=...`
  - On success: store `access_token` in `AuthContext` via context setter, navigate to `/` (or stored `returnTo`)
  - On error: show error message with retry link

- **`ProtectedRoute.tsx`**:
  - Wraps child routes
  - If `isLoading`: show spinner/loading state
  - If `!isAuthenticated`: redirect to `/login`
  - If `isAuthenticated`: render children

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_callback_page_navigates_on_success` | Successful callback → stores token, navigates to / | unit |
| `test_callback_page_shows_error_on_error_param` | ?error=access_denied → error message shown | unit |
| `test_protected_route_redirects_unauthenticated` | Not authenticated → redirect to /login | unit |
| `test_protected_route_renders_children_when_authenticated` | Authenticated → renders children | unit |

**Acceptance criteria**:
- [ ] All 3 components created
- [ ] `CallbackPage` handles `error` query param
- [ ] `ProtectedRoute` shows loading state while `isLoading=true`
- [ ] 4 tests pass

---

#### T-E-1-03: App.tsx Wiring — AuthProvider, Routes, 401 Interceptor

**Type**: impl
**depends_on**: [T-E-1-01, T-E-1-02]
**blocks**: [T-E-1-04]
**Target files**:
- `apps/frontend/src/App.tsx`
- `apps/frontend/src/hooks/useAlertStream.ts` (add 401 handling per §6.6 modified files)
- Any other API-calling hooks (add `Authorization: Bearer ${access_token}` header)

**What to build**:
Wrap `App` with `<AuthProvider>`, add `/login` and `/callback` routes, wrap existing routes with `<ProtectedRoute>`.

**Changes to `App.tsx`**:
```tsx
// Wrap entire app
<AuthProvider>
  <Router>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/callback" element={<CallbackPage />} />
      <Route path="/*" element={
        <ProtectedRoute>
          {/* existing app routes */}
        </ProtectedRoute>
      } />
    </Routes>
  </Router>
</AuthProvider>
```

**401 interceptor in `useAlertStream.ts`**:
- Replace `userId: null` with `userId: user?.user_id ?? null`
- If WebSocket gets `401` message: call `refresh()` from `useAuth()`, then reconnect

**API calls in existing hooks**:
- Add `Authorization: Bearer ${access_token}` to all `fetch()` / `axios` calls
- If response is 401: call `refresh()` then retry the original request once

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_401_triggers_refresh_and_retry` | 401 response → POST /v1/auth/refresh called, then original request retried | unit |
| `test_app_renders_login_when_unauthenticated` | Unauthenticated → shows LoginPage | unit |

**Acceptance criteria**:
- [ ] `App.tsx` wrapped with `AuthProvider`
- [ ] `/login` and `/callback` routes added
- [ ] All existing routes wrapped with `ProtectedRoute`
- [ ] `useAlertStream.ts` uses `user?.user_id`
- [ ] 2 tests pass

---

#### T-E-1-04: Frontend Auth Test Suite

**Type**: test
**depends_on**: [T-E-1-01, T-E-1-02, T-E-1-03]
**blocks**: none
**Target files**:
- `apps/frontend/src/contexts/__tests__/AuthContext.test.tsx`
- `apps/frontend/src/pages/__tests__/CallbackPage.test.tsx`
- `apps/frontend/src/components/__tests__/ProtectedRoute.test.tsx`

**What to build**: Consolidate all frontend auth tests. Use Vitest + React Testing Library + MSW for API mocking.

**Minimum test count**: 12 tests total (from T-E-1-01 through T-E-1-03 combined).

**Acceptance criteria**:
- [ ] All 12+ tests pass
- [ ] `pnpm test` from `apps/frontend/` passes
- [ ] No `localStorage` usage for auth state (assert in tests)
- [ ] `pnpm lint` passes (ESLint + TypeScript strict)

### Validation Gate
- [ ] `pnpm lint` — zero errors
- [ ] `pnpm test` — ≥12 new auth tests pass
- [ ] `pnpm build` — TypeScript compilation succeeds with strict mode
- [ ] Manual smoke: Login button visible on unauthenticated visit to `/`

### Regression Guardrails
- **MEMORY: frontend pnpm enforcement**: Use `pnpm` only, exact versions (no `^`). Do NOT use `npm` or `yarn`. Run `pnpm audit --prod` to confirm 0 new CVEs before committing.
- **Token in localStorage**: Assert in at least one test that `localStorage.getItem("access_token")` is null after successful auth.
- **SameSite cookie**: The `refresh_token` cookie is `SameSite=Strict` — ensure frontend calls `POST /v1/auth/refresh` from the same origin as S9 (or the shared domain).

---

## Wave F: Infrastructure + Integration Tests ✅

**Goal**: Add Zitadel Terraform resources, self-hosted Zitadel docker-compose for local dev, RSA keypair generation script, Traefik `/internal/*` block, update dev env example, run full S9+S1 integration tests.
**Depends on**: Wave A (for keypair script context), Wave B (for integration tests)
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure + config
**Status**: **DONE** — 2026-04-12 · 84 tests pass (4 new integration) · ruff + mypy clean

### Pre-read (agent must read before starting)
- `infra/compose/docker-compose.yml` — current compose structure
- `configs/dev.local.env.example` — current env var example file
- `infra/traefik/` (if exists) or docker-compose labels for Traefik config
- `docs/specs/0025-auth-oidc-zitadel-internal-jwt.md` §3.5 (F-24..F-28), §6.7 D (JWKS fetch flow)

### Tasks

#### T-F-1-01: RSA Keypair Generation Script

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `scripts/generate-internal-keypair.sh` (new file)

**What to build**:
Shell script that generates an RSA-2048 keypair and prints the env var instructions for `INTERNAL_JWT_PRIVATE_KEY` and `INTERNAL_JWT_PUBLIC_KEY`.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Generate RSA-2048 keypair
openssl genrsa -out /tmp/internal_jwt_key.pem 2048
openssl rsa -in /tmp/internal_jwt_key.pem -pubout -out /tmp/internal_jwt_key.pub

echo "=== Add to your .env file ==="
echo "API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=\"$(cat /tmp/internal_jwt_key.pem | tr '\n' '~' | sed 's/~/\\n/g')\""
echo "API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=\"$(cat /tmp/internal_jwt_key.pub | tr '\n' '~' | sed 's/~/\\n/g')\""

rm /tmp/internal_jwt_key.pem /tmp/internal_jwt_key.pub
```

**Acceptance criteria**:
- [ ] Script is executable (`chmod +x`)
- [ ] Outputs both env vars in copy-paste format
- [ ] Deletes temp files on completion

---

#### T-F-1-02: docker-compose.zitadel.yml (Self-hosted Zitadel for local dev)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/compose/docker-compose.zitadel.yml` (new file)
- `infra/zitadel/README.md` (new file — setup instructions)

**What to build**:
Docker Compose file for offline local dev with self-hosted Zitadel + Postgres. This is for dev only — production uses Zitadel Cloud.

```yaml
# infra/compose/docker-compose.zitadel.yml
services:
  zitadel-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: zitadel
      POSTGRES_USER: zitadel
      POSTGRES_PASSWORD: zitadel
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U zitadel"]
      interval: 5s
      timeout: 3s
      retries: 10
  zitadel:
    image: ghcr.io/zitadel/zitadel:stable
    command: start-from-init --masterkeyFromEnv --tlsMode disabled
    environment:
      ZITADEL_DATABASE_POSTGRES_HOST: zitadel-db
      ZITADEL_DATABASE_POSTGRES_PORT: 5432
      ZITADEL_DATABASE_POSTGRES_DATABASE: zitadel
      ZITADEL_DATABASE_POSTGRES_USER_USERNAME: zitadel
      ZITADEL_DATABASE_POSTGRES_USER_PASSWORD: zitadel
      ZITADEL_DATABASE_POSTGRES_USER_SSL_MODE: disable
      ZITADEL_DATABASE_POSTGRES_ADMIN_USERNAME: zitadel
      ZITADEL_DATABASE_POSTGRES_ADMIN_PASSWORD: zitadel
      ZITADEL_DATABASE_POSTGRES_ADMIN_SSL_MODE: disable
      ZITADEL_MASTERKEY: "MasterkeyNeedsToHave32Characters"
      ZITADEL_EXTERNALPORT: 8088
      ZITADEL_EXTERNALDOMAIN: localhost
      ZITADEL_EXTERNALPROTOCOL: http
    ports:
      - "8088:8080"
    depends_on:
      zitadel-db:
        condition: service_healthy
```

`infra/zitadel/README.md`: Document:
1. Local dev setup: `docker compose -f infra/compose/docker-compose.zitadel.yml up -d`
2. Zitadel Cloud setup (manual): Create instance → Project → Web App (PKCE) → configure redirect URIs → get CLIENT_ID
3. Required env vars for S9

**Acceptance criteria**:
- [ ] `docker-compose.zitadel.yml` exists and is valid YAML
- [ ] `infra/zitadel/README.md` covers both local and cloud setup

---

#### T-F-1-03: Zitadel Terraform Resources

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/zitadel/terraform/main.tf` (new)
- `infra/zitadel/terraform/variables.tf` (new)
- `infra/zitadel/terraform/outputs.tf` (new)

**What to build**:
Terraform resources for Zitadel Cloud using the `zitadel/zitadel` provider. Manages: Project, Web App (PKCE), allowed redirect URIs, token settings.

```hcl
# main.tf
terraform {
  required_providers {
    zitadel = { source = "zitadel/zitadel", version = "~> 1.0" }
  }
}
provider "zitadel" {
  domain = var.zitadel_domain
  insecure = false
  port = "443"
  jwt_profile_file = var.zitadel_service_account_key_file
}

resource "zitadel_project" "worldview" {
  name = "worldview"
  org_id = var.zitadel_org_id
}

resource "zitadel_application_oidc" "worldview_web" {
  project_id = zitadel_project.worldview.id
  org_id = var.zitadel_org_id
  name = "worldview-web"
  redirect_uris = var.redirect_uris           # ["https://app.<DOMAIN>/callback"]
  post_logout_redirect_uris = [var.frontend_url]
  response_types = ["CODE"]
  grant_types = ["AUTHORIZATION_CODE", "REFRESH_TOKEN"]
  auth_method_type = "NONE"                   # PKCE — no client secret needed (public client)
  access_token_type = "JWT"
  id_token_userinfo_assertion = true
  clock_skew = "1s"
  dev_mode = var.dev_mode
}
```

**Note**: If Terraform proves impractical (OQ-007 DEFERRED), the `infra/zitadel/README.md` manual steps are the authoritative fallback.

**Acceptance criteria**:
- [ ] `terraform validate` passes on `infra/zitadel/terraform/`
- [ ] Resources cover: project, web app (PKCE), redirect URIs

---

#### T-F-1-04: Traefik `/internal/*` Block + Rate Limit Middleware

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/traefik/` or `infra/compose/docker-compose.yml` (Traefik label additions)

**What to build**:
Add Traefik middleware to:
1. Block all `/internal/*` requests from the public-facing entrypoint (returns 403 to external callers)
2. Add Traefik-level rate limiting middleware (200 req/min per IP, burst=50) as a defense-in-depth layer

```yaml
# Traefik labels on api-gateway service
labels:
  - "traefik.http.middlewares.block-internal.replacepathregex.regex=^/internal/.*"
  - "traefik.http.middlewares.block-internal.replacepathregex.replacement=/404-not-found"
  # Alternatively use middleware chain with stripprefix and deny
  - "traefik.http.middlewares.ratelimit.ratelimit.average=200"
  - "traefik.http.middlewares.ratelimit.ratelimit.burst=50"
  - "traefik.http.middlewares.ratelimit.ratelimit.period=1m"
```

**Acceptance criteria**:
- [ ] Traefik configuration blocks `/internal/*` from external entrypoint
- [ ] Rate limiting middleware defined at Traefik level

---

#### T-F-1-05: Update dev.local.env.example + Docs

**Type**: docs + config
**depends_on**: none
**blocks**: none
**Target files**:
- `configs/dev.local.env.example`
- `docs/services/api-gateway.md`
- `services/api-gateway/.claude-context.md` (add auth endpoint details)

**What to build**:
Add all new env vars to the example file. Update service docs.

**New env vars to add** (with example values, NOT real secrets):
```bash
# S9 API Gateway — OIDC (Zitadel Cloud)
API_GATEWAY_OIDC_ISSUER_URL=https://your-instance.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=your-client-id
API_GATEWAY_OIDC_CLIENT_SECRET=your-client-secret
API_GATEWAY_OIDC_AUDIENCE=your-client-id
API_GATEWAY_FRONTEND_URL=http://localhost:5173
API_GATEWAY_COOKIE_SECURE=false

# S9 API Gateway — Internal JWT (RS256)
# Generate with: ./scripts/generate-internal-keypair.sh
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<RSA-2048-PEM-private-key>
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<RSA-2048-PEM-public-key>

# All backend services — internal auth
PORTFOLIO_API_GATEWAY_URL=http://api-gateway:8000
MARKET_DATA_API_GATEWAY_URL=http://api-gateway:8000
# ... (one per service)
```

**Remove from example**:
```bash
API_GATEWAY_JWT_SECRET=...
PORTFOLIO_INTERNAL_SERVICE_TOKEN=...
# ... all INTERNAL_SERVICE_TOKEN entries
```

**Acceptance criteria**:
- [ ] `configs/dev.local.env.example` has all new vars
- [ ] No `JWT_SECRET` or `INTERNAL_SERVICE_TOKEN` entries remain
- [ ] `docs/services/api-gateway.md` auth section updated

---

#### T-F-1-06: S9 + S1 Full Integration Tests

**Type**: test
**depends_on**: [T-F-1-01, T-F-1-05] (all Wave A, B, C changes must be in place)
**blocks**: none
**Target files**:
- `services/api-gateway/tests/integration/test_auth_e2e.py`

**What to build**:
End-to-end integration tests for the auth flow (Valkey running; mock Zitadel via `respx`; mock S1 via `respx`). These tests verify the full S9 auth flow including internal JWT issuance and security headers.

**Tests to write**:
| Test Name | Infrastructure | What It Verifies |
|-----------|---------------|-----------------|
| `test_security_headers_on_all_responses` | ASGI test client | All 5 security headers present on 200 + 401 responses |
| `test_jwks_endpoint_public` | ASGI test client | `/internal/jwks` returns 200 without auth |
| `test_rate_limit_429_after_threshold` | ASGI + mock Valkey | 21st unauthenticated request in window → 429 |
| `test_cors_preflight_explicit_methods` | ASGI test client | OPTIONS returns explicit methods, not `*` |

**Acceptance criteria**:
- [ ] 4 integration tests pass
- [ ] Tests run without real Zitadel instance (all Zitadel calls mocked)

### Validation Gate
- [ ] `scripts/generate-internal-keypair.sh` runs and outputs valid PEM
- [ ] `docker compose -f infra/compose/docker-compose.zitadel.yml up -d` succeeds
- [ ] `terraform validate` passes on `infra/zitadel/terraform/`
- [ ] 4 integration tests pass
- [ ] `configs/dev.local.env.example` has no JWT_SECRET or INTERNAL_SERVICE_TOKEN entries

### Regression Guardrails
- **R13** (no secrets in code): `dev.local.env.example` must have placeholder values (never real keys). Assert in CI that `INTERNAL_JWT_PRIVATE_KEY` in the example file starts with `<` (placeholder).
- **Zitadel TF provider OQ-007**: If Terraform apply fails on Zitadel provider, fall back to `infra/zitadel/README.md` manual setup — this is documented as a DEFERRED fallback.

---

## Cross-Cutting Concerns

### Contract Changes
No Avro schemas modified (§6.3 confirms no new Kafka topics). No contract tests need updating.

### Migration Order
1. `0007_add_external_id_and_role_to_users.py`
2. `0008_create_invitations_and_auth_audit_log.py`

Both are in `services/portfolio/alembic/` (S1 owns its own DB). No `intelligence-migrations` changes.

### Event Flow Changes
None. Authentication is fully synchronous.

### Configuration Changes
| Service | New Vars | Removed Vars |
|---------|----------|-------------|
| S9 | `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_AUDIENCE`, `INTERNAL_JWT_PRIVATE_KEY`, `INTERNAL_JWT_PUBLIC_KEY`, `FRONTEND_URL`, `COOKIE_SECURE` | `JWT_SECRET`, `JWT_ALGORITHM` |
| S1 | `API_GATEWAY_URL` | `INTERNAL_SERVICE_TOKEN` |
| S2–S10 | `API_GATEWAY_URL` | `INTERNAL_SERVICE_TOKEN` |

### Documentation Updates
- `docs/services/api-gateway.md` — auth section (Wave F)
- `services/api-gateway/.claude-context.md` — new auth endpoints (Wave F)
- `configs/dev.local.env.example` — new env vars (Wave F)
- `services/<each backend>/.claude-context.md` — note InternalJWTMiddleware wired (Wave D, per service)

---

## Risk Assessment

### Critical Path
**Wave A → Wave B → Wave E** (frontend depends on auth endpoints)

### Highest Risk Waves
1. **Wave C** — Alembic migrations are irreversible; `NOT NULL role` column without `server_default` would fail on existing rows (BP-126 must be followed exactly)
2. **Wave D** — Removing `InternalAuthDep` from 8 services simultaneously; if any service is missed, internal routes become inaccessible (S9 sends `X-Internal-JWT` but service still expects `X-Internal-Token`)

### Rollback Strategy
- Wave A/B: stateless S9 changes; rollback = revert to `jwt_secret` branch
- Wave C: `alembic downgrade -1` twice (both migrations are additive, downgrade removes new tables/columns)
- Wave D: Reintroduce `InternalAuthDep` on each service's internal routes

### Testing Gaps
- Real Zitadel integration is not tested (mocked in all tests) — tested manually via `docker-compose.zitadel.yml`
- Key rotation procedure is defined in PRD §9 but not tested (deferred hardening per OQ-006)

---

## PLAN-0022 Resumption Notes

After all 6 waves are complete and QA passes:
- **Wave 7** (S9 SnapTrade routes): replace `_auth_headers()` with `_build_internal_headers(request)` — issue user internal JWT from `request.state`
- `X-Tenant-Id` header is dead — all backends read `request.state.tenant_id` from `InternalJWTMiddleware`
- Remove the `blocked` status from PLAN-0022 in TRACKING.md and set to `in-progress`
