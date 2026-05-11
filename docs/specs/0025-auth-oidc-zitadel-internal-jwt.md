---
id: PRD-0025
title: "Authentication & Security Foundation — OIDC/Zitadel, RS256 Internal JWT, S9 Hardening"
status: draft
created: 2026-04-10
updated: 2026-04-10
authors: [arnau]
services_affected: [S9, S1, S2, S3, S4, S5, S6, S7, S8, S10, frontend]
depends_on: []
blocks: [PLAN-0022-waves-4-9]
security_classification: CRITICAL
---

# PRD-0025 — Authentication & Security Foundation

> **Purpose**: Establish end-to-end authentication via Zitadel Cloud (OIDC/PKCE),
> RS256 internal JWT for inter-service trust, and resolve all open security issues in S9.
> This PRD is the prerequisite for PLAN-0022 Waves 4–9 and any future feature that requires
> user identity in the API.

---

## §1 Problem Statement

The worldview platform has a critical identity gap: S9 (API Gateway) validates JWTs but
**no service issues them**. There is no login endpoint, no registration flow, and no way for
a user to obtain a token. The current auth design has five open security vulnerabilities:

| ID | Severity | Issue |
|----|----------|-------|
| SEC-001 | CRITICAL | `jwt_secret` defaults to `dev-secret-change-me` — anyone can forge tokens |
| SEC-003 | HIGH | CORS allows all methods and headers (`*`) |
| SEC-004 | HIGH | `RateLimitMiddleware` exists but is not wired into the app |
| SEC-007 | MEDIUM | No security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options) |
| SEC-008 | MEDIUM | Rate limiting keys by IP only, not user ID |

Beyond the security issues, there is a deeper architectural flaw: backend services (S1–S8, S10)
accept `X-Tenant-Id` and `X-User-Id` headers unconditionally. Any process that can reach a
backend service on the internal Docker/k8s network can impersonate any tenant. There is no
cryptographic boundary between S9 and the backends.

This PRD addresses all of the above by:
1. Integrating **Zitadel Cloud** as the OIDC provider (external, zero-ops, free tier)
2. Implementing a complete **PKCE auth flow** in S9 (login → callback → token → refresh → logout)
3. Replacing unconditional header trust with **RS256 internal JWTs** (S9 signs; backends verify)
4. Resolving SEC-001, SEC-003, SEC-004, SEC-007, SEC-008
5. Adding **B2B-ready schema** to S1 (schema only; no endpoints) to avoid future painful migrations

The design is startup-grade, not just thesis-grade. Zitadel Cloud can be replaced with Auth0,
WorkOS, or self-hosted Zitadel by changing three env vars — S9's code does not change.

---

## §2 Target Users

| User | Goal | How This PRD Helps |
|------|------|-------------------|
| **Retail investors / analysts** | Create an account, log in, and access their portfolio | Working registration + login via Zitadel UI |
| **Thesis evaluators** | Assess end-to-end auth security architecture | Demonstrates OIDC PKCE, inter-service JWT, security headers |
| **Future startup B2B users** | Belong to an org with multiple seats | Schema is ready; invite flow is deferred |
| **Developers** | Build features that require user identity | Consistent `request.state.tenant_id` / `request.state.user_id` across all services |

---

## §3 Functional Requirements

### 3.1 Authentication Flow (OIDC PKCE)

| ID | Requirement |
|----|-------------|
| F-01 | Users register and log in exclusively via Zitadel Cloud (no password stored in Worldview) |
| F-02 | `GET /v1/auth/login` initiates PKCE flow: generates `state` + `code_verifier`, stores in Valkey (10-min TTL), redirects to Zitadel |
| F-03 | `GET /v1/auth/callback` validates `state`, exchanges `code` for tokens via Zitadel token endpoint, lazy-provisions user in S1, sets httpOnly `refresh_token` cookie, returns `access_token` in body |
| F-04 | `POST /v1/auth/refresh` reads httpOnly cookie, exchanges `refresh_token` at Zitadel, returns new `access_token` |
| F-05 | `POST /v1/auth/logout` revokes `refresh_token` at Zitadel end_session_endpoint, clears cookie, deletes Valkey cache entry |
| F-06 | `GET /v1/auth/me` returns user identity from validated access_token |
| F-07 | Zitadel JWKS endpoint is discovered via `{OIDC_ISSUER_URL}/.well-known/openid-configuration`; S9 caches JWKS in memory at startup |

### 3.2 Internal JWT (RS256 Inter-Service Trust)

| ID | Requirement |
|----|-------------|
| F-08 | S9 holds an RSA private key; exposes public key at `GET /internal/jwks` (JWKS format) |
| F-09 | S9 issues RS256 internal JWTs on every proxied authenticated request; claims include `sub` (user_id), `tenant_id`, `oidc_sub`, `role`, `jti`, `iat`, `exp` (5-min TTL), `kid` |
| F-10 | All backend services (S1–S8, S10) fetch `GET /internal/jwks` at startup, cache public key, refresh every 1h or on `kid` miss |
| F-11 | All backend services validate `X-Internal-JWT` on every non-health request; unauthenticated requests receive 401 |
| F-12 | S9 issues a "system" internal JWT (role=`system`, sub=`system`) for its own provisioning call to S1 |
| F-13 | `GET /internal/jwks` is **not** reachable from outside (Traefik blocks `/internal/*` paths from public ingress) |

### 3.3 User Provisioning (S1)

| ID | Requirement |
|----|-------------|
| F-14 | `POST /internal/v1/users/provision` is a new S1 endpoint; accepts `{sub, email, username}` |
| F-15 | If `sub` is new and email is new: create Tenant (name = username or email prefix) + User atomically; return `created=true` |
| F-16 | If `sub` is new but email matches existing user with `external_id IS NULL`: link by updating `external_id`, write audit log, return `linked=true` |
| F-17 | If `sub` already exists: return existing user+tenant, return `created=false`, `linked=false` |
| F-18 | If `sub` is new but email matches a user whose `external_id` is a *different* sub: return 409 (should be impossible per Zitadel's email-uniqueness constraint; surfaced as admin alert) |
| F-19 | Provision call is idempotent: calling twice with the same `sub` returns same `{user_id, tenant_id}` both times |

### 3.4 Security Hardening

| ID | Requirement |
|----|-------------|
| F-20 | Remove `jwt_secret` from S9 config; replace with `OIDC_ISSUER_URL` (required, no default) — fixes SEC-001 |
| F-21 | CORS: explicit allowlist `methods=["GET","POST","PUT","DELETE","OPTIONS"]`, `headers=["Authorization","Content-Type","X-Request-ID","Cookie"]` — fixes SEC-003 |
| F-22 | `RateLimitMiddleware` wired in `create_app()` with Valkey; rate limit key = `user_id` if authenticated, `sha256(IP)[:16]` otherwise — fixes SEC-004 + SEC-008 |
| F-23 | New `SecurityHeadersMiddleware` injects: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-XSS-Protection: 0`, `Permissions-Policy: geolocation=(), microphone=()`, `Strict-Transport-Security: max-age=31536000; includeSubDomains` (only when `COOKIE_SECURE=true`) — fixes SEC-007 |

### 3.5 Infrastructure

| ID | Requirement |
|----|-------------|
| F-24 | `infra/zitadel/terraform/` contains Zitadel Terraform provider resources for the project, applications, allowed redirect URIs, and token settings |
| F-25 | `infra/zitadel/README.md` documents manual Zitadel Cloud console setup as a fallback |
| F-26 | `docker-compose.zitadel.yml` provides self-hosted Zitadel + Postgres for offline local dev |
| F-27 | `scripts/generate-internal-keypair.sh` generates RSA-2048 keypair and prints env var instructions |
| F-28 | Traefik ingress configuration adds rate limiting middleware (e.g. 200 req/min per IP burst) and blocks `/internal/*` paths from the public LoadBalancer entrypoint |

---

## §4 Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| Auth endpoint latency | < 500ms p95 (S9 processing; excludes browser redirect + Zitadel UI time) |
| JWKS fetch + JWT validation | < 5ms per request (in-memory after startup) |
| Internal JWT signing | < 2ms per request (RSA-2048 sign) |
| Internal JWT verification | < 1ms per request (RSA verify is faster than sign) |
| Valkey cache miss (sub → tenant) | Graceful degradation: one synchronous S1 call, no crash |
| Token refresh | Silent (no user interaction); frontend intercepts 401 and retries |
| Cookie attributes | `HttpOnly`, `Secure` (production), `SameSite=Strict`, `Path=/v1/auth/refresh`, `Max-Age=2592000` (30 days) |
| PKCE flow resilience | `state` stored in Valkey with 10-min TTL; deleted on use (single-use) |
| Security header coverage | 100% of responses from S9 (including error responses) |

---

## §5 Out of Scope

| Item | Rationale |
|------|-----------|
| Social login (Google, GitHub) | Zero code change — add via Zitadel console when needed |
| MFA / passkeys | Zero code change — enable via Zitadel console |
| B2B invite flow (invitations endpoints) | Schema defined here; endpoints deferred |
| PLAN-0022 Waves 4–9 | Resumes after this PRD is implemented; blocked dependency |
| PLAN-0001-D (S9 proxy routing) | Separate PRD; this PRD only adds auth infrastructure |
| Email verification enforcement | Zitadel handles this natively; S9 reads `email_verified` claim |
| Password reset, account deletion | Zitadel self-service console |
| Audit log endpoints (read) | No API to query `auth_audit_log` in this PRD |
| S9 SnapTrade routes | Part of PLAN-0022 Wave 7+ |

---

## §6 Technical Changes

### §6.1 Affected Services

| Service | Change Type | Summary |
|---------|------------|---------|
| **S9 API Gateway** | MAJOR | OIDC auth flow, JWKS endpoint, RS256 JWT issuance, OIDCAuthMiddleware, security hardening (SEC-001/003/004/007/008) |
| **S1 Portfolio** | MODERATE | `external_id` + `role` on users, `invitations` table stub, `auth_audit_log` table, provision endpoint |
| **S2 Market Ingestion** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S3 Market Data** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S4 Content Ingestion** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S5 Content Store** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S6 NLP Pipeline** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S7 Knowledge Graph** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S8 RAG/Chat** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **S10 Alert Service** | MINOR | `InternalJWTMiddleware`, `API_GATEWAY_URL` config var |
| **Frontend** | MODERATE | `LoginPage`, `CallbackPage`, `AuthContext`, `useAuth`, `ProtectedRoute`, token storage, 401 interceptor |
| **Infrastructure** | MINOR | Zitadel Terraform, `docker-compose.zitadel.yml`, Traefik rate limit + `/internal/*` block |

---

### §6.2 API Changes

#### S9 — GET /v1/auth/login

- **Purpose**: Initiate OIDC PKCE flow — generate state + code_challenge, store in Valkey, redirect to Zitadel
- **Auth**: None (public)
- **Query params**: none
- **Response**: 302 redirect to Zitadel authorization endpoint
  - Redirect URL: `{OIDC_ISSUER_URL}/oauth/v2/authorize?client_id={OIDC_CLIENT_ID}&response_type=code&redirect_uri={FRONTEND_URL}/callback&scope=openid+profile+email+offline_access&state={state_uuid}&code_challenge={base64url_sha256_code_verifier}&code_challenge_method=S256`
  - Valkey key stored: `auth:pkce:{state}` → `{code_verifier}`, TTL=600s (10 min)
- **Error responses**:
  - 503 — Valkey unavailable (state cannot be stored; fail closed — do not redirect)
  - 502 — OIDC discovery failed at startup (authorization endpoint unknown)
- **Rate limit**: 20 req/min per IP hash (unauthenticated)
- **CSRF protection**: `state` is a UUID4 random nonce, single-use

#### S9 — GET /v1/auth/callback

- **Purpose**: Handle Zitadel redirect; validate state; exchange code for tokens; provision user; return tokens
- **Auth**: None (public — CSRF protected by state)
- **Query params**:
  | Param | Type | Required | Description |
  |-------|------|----------|-------------|
  | code | string | yes* | Authorization code from Zitadel |
  | state | string | yes* | Must match stored Valkey state |
  | error | string | no | Zitadel error code (e.g. `access_denied`) |
  | error_description | string | no | Human-readable Zitadel error |
  *Required unless `error` is present
- **Processing steps**:
  1. If `error` present → return 400 with `{error, error_description}`
  2. Validate `state` exists in Valkey; retrieve `code_verifier`; delete key (single-use)
  3. POST to `{token_endpoint}` with `{grant_type=authorization_code, code, redirect_uri, client_id, code_verifier}`
  4. Validate returned `access_token`: signature via JWKS, `iss`, `aud`, `exp`
  5. Extract `sub`, `email`, `email_verified`, `preferred_username` from claims
  6. Call S1 `POST /internal/v1/users/provision` with system JWT
  7. Cache `auth:user:{sub}` → `{user_id, tenant_id}` in Valkey, TTL=3600s
  8. Set httpOnly cookie with `refresh_token`
  9. Return 200 JSON body
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | access_token | string | Zitadel-issued JWT (RS256, 15-min TTL) |
  | expires_in | int | Seconds until access_token expires (typically 900) |
  | token_type | string | Always `"Bearer"` |
  | user.user_id | string (UUID) | Internal user ID from S1 (UUIDv7) |
  | user.tenant_id | string (UUID) | Internal tenant ID from S1 (UUIDv7) |
  | user.email | string | Verified email from Zitadel |
  | user.sub | string | Zitadel subject (UUID) |
  | user.email_verified | bool | Whether Zitadel has verified the email |
- **Cookie set**: `Set-Cookie: refresh_token=<token>; HttpOnly; SameSite=Strict; Path=/v1/auth/refresh; Max-Age=2592000` (+ `Secure` when `COOKIE_SECURE=true`)
- **Error responses**:
  - 400 — `error` param present from Zitadel
  - 400 — `state` not in Valkey (expired or never existed)
  - 400 — `code` or `state` missing
  - 400 — Zitadel token exchange failed (e.g. code already used, wrong redirect_uri)
  - 401 — Zitadel access_token validation failed (invalid sig, wrong iss/aud)
  - 503 — S1 provisioning call failed (non-retryable: return error to user)
  - 503 — Valkey unavailable (state lookup impossible)
- **Rate limit**: 20 req/min per IP hash

#### S9 — POST /v1/auth/refresh

- **Purpose**: Exchange httpOnly `refresh_token` cookie for a new `access_token`
- **Auth**: httpOnly `refresh_token` cookie (automatically sent by browser to `Path=/v1/auth/refresh`)
- **Request body**: none
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | access_token | string | New Zitadel JWT |
  | expires_in | int | Seconds until expiry |
  | token_type | string | `"Bearer"` |
- **Side effects**: Sets updated `Set-Cookie` with new `refresh_token` (rotation)
- **Error responses**:
  - 401 — `refresh_token` cookie absent
  - 401 — Zitadel rejected refresh (expired, revoked, user deleted in Zitadel)
  - 503 — Zitadel unreachable
- **Rate limit**: 30 req/min per IP hash (cookie-based, user not yet identified)

#### S9 — POST /v1/auth/logout

- **Purpose**: Revoke refresh_token at Zitadel; clear cookie; invalidate Valkey user cache
- **Auth**: Optional `Authorization: Bearer <access_token>` (used to extract sub for cache invalidation)
- **Request body**: none
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | message | string | `"Logged out successfully"` |
- **Side effects**:
  1. Reads `refresh_token` from cookie
  2. POST to Zitadel `end_session_endpoint` to revoke token (best-effort; timeout 5s)
  3. If `sub` extractable from access_token: delete Valkey `auth:user:{sub}`
  4. `Set-Cookie: refresh_token=; Max-Age=0; Path=/v1/auth/refresh; HttpOnly; SameSite=Strict`
- **Error responses**: Always 200 (best-effort logout; partial failures logged but not surfaced to user)
- **Rate limit**: 10 req/min per IP hash

#### S9 — GET /v1/auth/me

- **Purpose**: Return current user identity from validated access_token
- **Auth**: Required — `Authorization: Bearer <access_token>`
- **Request body**: none
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | user_id | string (UUID) | Internal user ID |
  | tenant_id | string (UUID) | Internal tenant ID |
  | email | string | Verified email |
  | sub | string | Zitadel subject |
  | email_verified | bool | Email verification status |
- **Error responses**:
  - 401 — missing or invalid access_token
- **Rate limit**: 100 req/min per user_id

#### S9 — GET /internal/jwks

- **Purpose**: Expose S9's RS256 public key for internal JWT verification by backend services
- **Auth**: None (but Traefik blocks `/internal/*` from the public-facing entrypoint)
- **Response (200)**:
  ```json
  {
    "keys": [{
      "kty": "RSA",
      "alg": "RS256",
      "use": "sig",
      "kid": "<sha256-thumbprint>",
      "n": "<base64url RSA modulus>",
      "e": "AQAB"
    }]
  }
  ```
- **Cache-Control**: `public, max-age=3600`
- **Error responses**: 503 — private key not loaded (startup validation prevents this in practice)

#### S1 — POST /internal/v1/users/provision

- **Purpose**: Idempotent user + tenant creation by Zitadel `sub`; links existing user by email if needed
- **Auth**: `X-Internal-JWT` header — RS256 JWT from S9 with `role = "system"` (internal only)
- **Request body**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | sub | string | yes | — | non-empty, max 255 | Zitadel user UUID |
  | email | string | yes | — | valid email format, max 255 | Verified by Zitadel |
  | username | string | no | — | max 100 chars | Used as tenant name on new creation |
- **Response (200)**:
  | Field | Type | Description |
  |-------|------|-------------|
  | user_id | string (UUID) | UUIDv7 — existing or newly created |
  | tenant_id | string (UUID) | UUIDv7 — existing or newly created |
  | email | string | Stored email |
  | created | bool | True if user+tenant were just created |
  | linked | bool | True if existing user was linked by email |
- **Logic**:
  ```
  1. SELECT user WHERE external_id = sub
     → found: return (user_id, tenant_id, created=False, linked=False)
  2. SELECT user WHERE email = email AND external_id IS NULL
     → found: UPDATE SET external_id = sub; write audit log; return (..., linked=True)
  3. Neither found: INSERT tenant (name=username or email.split('@')[0]); INSERT user (external_id=sub, role=owner); write audit log (user_created); return (..., created=True)
  4. SELECT user WHERE email = email AND external_id != sub AND external_id IS NOT NULL
     → write audit log (conflict_409); return 409
  ```
- **Atomicity**: Steps 2 and 3 use a single DB transaction to prevent race conditions
- **Error responses**:
  - 401 — missing/invalid `X-Internal-JWT` or `role != "system"`
  - 409 — `external_id` conflict (different sub)
  - 422 — invalid `sub` (empty) or `email` (invalid format)
- **Rate limit**: Not applicable (internal-only, not reachable from public)

---

### §6.3 Event Changes

**None.** This PRD introduces no new Kafka topics or Avro schemas. Authentication state changes are fully synchronous within S9 and S1. The `auth_audit_log` is written directly to `portfolio_db` (not via Kafka) because it is a write-and-forget audit trail, not an event that drives downstream processing.

---

### §6.4 Database Changes

#### Table: `users` (portfolio_db) — ALTER

Add two columns to existing `users` table:

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `external_id` | TEXT | yes | NULL | UNIQUE (partial, WHERE NOT NULL) | Zitadel `sub`; NULL for manually-created users |
| `role` | VARCHAR(20) | no | `'owner'` | CHECK (`role` IN ('owner','admin','member')) | B2B-ready; all new OIDC users are `'owner'` |

- **Index**: `CREATE UNIQUE INDEX idx_users_external_id ON users (external_id) WHERE external_id IS NOT NULL`
- **Migration notes**: Forward-compatible — both are additive. `external_id` is nullable so existing rows are unaffected. `role` gets a `server_default='owner'` so the NOT NULL constraint does not break the migration.
- **Existing users**: Will have `external_id = NULL` and `role = 'owner'` (set by migration default). On first Zitadel login, the provision endpoint links them via email and sets `external_id`.

#### Table: `invitations` (portfolio_db) — CREATE NEW

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | UUIDv7 |
| `tenant_id` | UUID | no | — | FK → tenants.id ON DELETE CASCADE | Inviting tenant |
| `email` | TEXT | no | — | — | Invitee email; not required to be unique |
| `role` | VARCHAR(20) | no | `'member'` | CHECK IN ('admin','member') — not 'owner' | Target role |
| `token` | TEXT | no | — | UNIQUE | Secure random (32 bytes base64url) |
| `expires_at` | TIMESTAMPTZ | no | — | CHECK > `created_at` | UTC; typically created_at + 7 days |
| `accepted_at` | TIMESTAMPTZ | yes | NULL | — | Set when invitation accepted; UTC |
| `created_at` | TIMESTAMPTZ | no | `now()` | — | UTC |

- **Indexes**: `(token) UNIQUE`, `(tenant_id, email)`, `(expires_at DESC)` for cleanup
- **Estimated rows**: 0 in B2C phase; no application code reads/writes this table in this PRD
- **Purpose**: Prevents a painful multi-table migration when the B2B invite feature is built

#### Table: `auth_audit_log` (portfolio_db) — CREATE NEW

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | UUID | no | `new_uuid7()` | PK | UUIDv7 |
| `user_id` | UUID | yes | NULL | FK → users.id (nullable) | NULL if user does not exist yet at event time |
| `event_type` | VARCHAR(50) | no | — | — | `user_created`, `account_linked`, `login_provisioned`, `provision_conflict_409` |
| `sub` | TEXT | no | — | — | Zitadel sub (always present) |
| `email` | TEXT | yes | NULL | — | Email at event time |
| `ip_address` | TEXT | yes | NULL | — | SHA-256[:16] of client IP (privacy-preserving) |
| `detail` | JSONB | yes | NULL | — | Extra context: `{linked_user_id, conflict_sub, ...}` |
| `created_at` | TIMESTAMPTZ | no | `now()` | — | UTC |

- **Indexes**: `(sub, created_at DESC)`, `(user_id, created_at DESC)` WHERE user_id IS NOT NULL, `(event_type, created_at DESC)`
- **Retention**: No automatic cleanup; keep indefinitely (small table)
- **Estimated rows**: ~5 rows per new user lifetime

---

### §6.5 Domain Model Changes

#### Entity: `User` (S1 Portfolio domain) — MODIFIED

Current attributes: `{id, tenant_id, email, status, created_at}`

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| id | UUID | yes | UUIDv7 | Generated on creation |
| tenant_id | UUID | yes | UUIDv7 | Owner tenant (FK) |
| email | str | yes | valid email, ≤255 chars | From Zitadel; verified |
| status | UserStatus | yes | enum member | ACTIVE / INACTIVE / DELETED |
| external_id | str \| None | no | ≤255 chars | Zitadel `sub`; None until OIDC login |
| role | TenantUserRole | yes | enum member | OWNER / ADMIN / MEMBER; default OWNER |
| created_at | datetime | yes | UTC-aware | Set on creation |

**New enum: `TenantUserRole`** (added to `domain/enums.py`):
```python
class TenantUserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
```

**Modified `User` dataclass** — add two fields to existing `@dataclass`:
```python
external_id: str | None = None
role: TenantUserRole = TenantUserRole.OWNER
```

**Invariants**: `external_id` is either None or a non-empty string ≤255 chars. `role` must be a valid `TenantUserRole` member.

#### Entity: `Invitation` (S1 Portfolio domain) — NEW (schema stub only)

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| id | UUID | yes | UUIDv7 | Generated on creation |
| tenant_id | UUID | yes | UUIDv7 | FK → Tenant |
| email | str | yes | valid email, ≤255 | Invitee email |
| role | TenantUserRole | yes | ADMIN or MEMBER only | Target role |
| token | str | yes | 43 chars (32 bytes base64url) | Unique, secure random |
| expires_at | datetime | yes | UTC, > created_at | Typically +7 days |
| accepted_at | datetime \| None | no | UTC or None | None until accepted |
| created_at | datetime | yes | UTC-aware | Set on creation |

**Invariants**: `expires_at > created_at`; `role != OWNER`; `accepted_at >= created_at or None`.
**Note**: ORM model + Alembic migration only. No use cases, no endpoints.

#### Value Object: `AuthAuditEvent` (S1 domain)

```python
@dataclass(frozen=True)
class AuthAuditEvent:
    event_type: AuthAuditEventType
    sub: str
    user_id: UUID | None
    email: str | None
    detail: dict[str, str]
    ip_address: str | None = None   # SHA-256[:16] of client IP; set from request state in use case
```

**New enum: `AuthAuditEventType`** (in `domain/enums.py`):
```python
class AuthAuditEventType(StrEnum):
    USER_CREATED = "user_created"
    ACCOUNT_LINKED = "account_linked"
    LOGIN_PROVISIONED = "login_provisioned"
    PROVISION_CONFLICT_409 = "provision_conflict_409"
```

#### Value Object: `InternalJWTClaims` (S9 domain)

```python
@dataclass(frozen=True)
class InternalJWTClaims:
    sub: str       # user_id (UUIDv7 string); "system" for provisioning calls
    tenant_id: str # tenant_id (UUIDv7 string); "" for system calls
    oidc_sub: str  # OIDC provider sub (for traceability; provider-agnostic)
    role: str      # "user" | "system"
    jti: str       # new_uuid7() — for replay prevention
    iat: int       # Unix timestamp (UTC)
    exp: int       # iat + 300 (5 min for user JWTs, 60s for system JWTs)
    kid: str       # RSA key ID matching JWKS endpoint
    iss: str = "worldview-gateway"
```

**Invariants**: `exp > iat`; `iss == "worldview-gateway"`; `role in ("user", "system")`.

#### Entity: `OIDCProviderConfig` (S9 in-memory state, NOT persisted)

```python
@dataclass
class OIDCProviderConfig:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    end_session_endpoint: str
    jwks_uri: str
    public_keys: dict[str, RSAPublicKey]   # kid → key
    last_refreshed_at: datetime             # UTC
```

Fetched from `{OIDC_ISSUER_URL}/.well-known/openid-configuration` at S9 startup. Refreshed every 1h or on `kid` miss (unknown key ID in incoming JWT triggers immediate refresh).

#### `InternalJWTMiddleware` (shared, added to every backend service)

Location: each service's `infrastructure/middleware/internal_jwt.py`

```python
class InternalJWTMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS: frozenset[str] = frozenset({"/health", "/ready", "/metrics", "/internal/v1/health"})
    SKIP_PREFIXES: tuple[str, ...] = ("/health", "/metrics")

    def __init__(self, app: ASGIApp, jwks_url: str) -> None:
        super().__init__(app)
        self._jwks_url = jwks_url
        self._public_key: RSAPublicKey | None = None
        self._key_id: str | None = None

    async def startup(self) -> None:
        """Fetch public key from S9 JWKS endpoint."""
        await self._refresh_public_key()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS or any(
            request.url.path.startswith(p) for p in self.SKIP_PREFIXES
        ):
            return await call_next(request)
        token = request.headers.get("X-Internal-JWT", "")
        if not token:
            return JSONResponse({"error": "missing_internal_jwt"}, status_code=401)
        try:
            payload = jwt.decode(
                token, self._public_key, algorithms=["RS256"],
                options={"require": ["iss", "sub", "exp", "jti", "tenant_id"]}
            )
            if payload.get("iss") != "worldview-gateway":
                raise jwt.InvalidTokenError("wrong issuer")
            if payload.get("kid") != self._key_id:
                await self._refresh_public_key()  # kid miss → refresh
                payload = jwt.decode(token, self._public_key, algorithms=["RS256"])
        except jwt.InvalidTokenError:
            return JSONResponse({"error": "invalid_internal_jwt"}, status_code=401)
        request.state.tenant_id = payload.get("tenant_id")
        request.state.user_id = payload.get("sub")
        request.state.role = payload.get("role", "user")
        return await call_next(request)
```

**Config var added to every backend service**: `API_GATEWAY_URL: str = "http://api-gateway:8000"` (Docker service name).

---

### §6.6 Frontend Changes

#### New files

| File | Purpose |
|------|---------|
| `src/contexts/AuthContext.tsx` | React Context: `{access_token, user, isAuthenticated, login, logout, refresh}` |
| `src/hooks/useAuth.ts` | Hook returning `AuthContext` values |
| `src/pages/LoginPage.tsx` | Login button → calls `/v1/auth/login` redirect |
| `src/pages/CallbackPage.tsx` | Handles `/callback` route — extracts `code`+`state` from URL, calls `/v1/auth/callback`, stores token in context |
| `src/components/ProtectedRoute.tsx` | Wrapper: redirects to `/login` if `isAuthenticated == false` |
| `src/lib/authClient.ts` | Typed functions: `initiateLogin()`, `handleCallback(code, state)`, `refreshToken()`, `logout()`, `getMe()` |

#### `AuthContext` shape

```typescript
interface AuthUser {
  user_id: string;   // UUIDv7
  tenant_id: string; // UUIDv7
  email: string;
  sub: string;
  email_verified: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  access_token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: () => void;             // redirects browser to /v1/auth/login
  logout: () => Promise<void>;   // calls POST /v1/auth/logout
  refresh: () => Promise<void>;  // calls POST /v1/auth/refresh
}
```

#### Token storage strategy

- **`access_token`**: Stored in React state (in-memory only). Never in `localStorage` or cookies (XSS protection). Lost on page refresh → triggers silent refresh via `POST /v1/auth/refresh` (cookie is httpOnly and browser-managed).
- **`refresh_token`**: Stored in httpOnly `Secure SameSite=Strict` cookie managed by S9 (transparent to frontend). Frontend never reads this value.
- **On page load**: `AuthProvider` mounts → calls `POST /v1/auth/refresh` silently → if 200, stores new `access_token`; if 401, sets `isAuthenticated=false`.

#### Modified files

| File | Change |
|------|--------|
| `src/App.tsx` | Wrap with `<AuthProvider>`, add `/login` and `/callback` routes, wrap protected routes with `<ProtectedRoute>` |
| `src/hooks/useAlertStream.ts` | Replace `userId: null` with `userId: user?.user_id ?? null`; handle 401 by calling `refresh()` before reconnecting WebSocket |
| All API-calling hooks | Add `Authorization: Bearer ${access_token}` to requests |

#### `LoginPage` component

Renders a single "Log in to Worldview" button. On click: `window.location.href = "/v1/auth/login"` (full page redirect, not AJAX, because S9 will issue a 302 to Zitadel). No form fields; no password handling in frontend.

#### `CallbackPage` component

Mounted at route `/callback`. On mount:
1. Extract `code` and `state` from `window.location.search`
2. If `error` param present: show error message + link to `/login`
3. Call `authClient.handleCallback(code, state)` → `GET /v1/auth/callback?code=...&state=...`
4. On success: store `access_token` in `AuthContext`, navigate to `/` (or stored `returnTo` path)
5. On error: show error message with retry link

---

### §6.7 Data Flow Design

#### A. First login (new user)

```
1. User clicks "Log in" on LoginPage
2. Frontend: window.location.href = "http://localhost:8000/v1/auth/login"
3. S9: generate state=UUID4, code_verifier=32-byte-random, code_challenge=base64url(sha256(code_verifier))
4. S9: SET Valkey auth:pkce:{state} = {code_verifier}, EX=600
5. S9: 302 → https://<instance>.zitadel.cloud/oauth/v2/authorize?...&state={state}&code_challenge={challenge}
6. Browser: renders Zitadel login/register UI
7. User registers or logs in at Zitadel
8. Zitadel: 302 → http://localhost:5173/callback?code=<code>&state=<state>
9. Frontend (CallbackPage): GET http://localhost:8000/v1/auth/callback?code=<code>&state=<state>
10. S9: GET Valkey auth:pkce:{state} → code_verifier (validate state matches); DEL key
11. S9: POST https://.../oauth/v2/token {code, code_verifier, client_id, redirect_uri, grant_type=authorization_code}
12. Zitadel: {access_token (RS256), refresh_token, id_token, expires_in=900}
13. S9: decode access_token → {sub, email, email_verified, preferred_username}
14. S9: issue system internal JWT {role=system, sub=system, oidc_sub=<sub>}
15. S9: POST http://portfolio:8001/internal/v1/users/provision {sub, email, username} + X-Internal-JWT
16. S1 InternalJWTMiddleware: validate X-Internal-JWT (RS256, iss=worldview-gateway, role=system) → OK
17. S1: SELECT user WHERE external_id = sub → not found
18. S1: SELECT user WHERE email = email → not found
19. S1: INSERT tenant {id=new_uuid7(), name=username, status=active}
20. S1: INSERT user {id=new_uuid7(), tenant_id=tenant.id, email, external_id=sub, role=owner}
21. S1: INSERT auth_audit_log {event_type=user_created, sub, user_id, email}
22. S1: COMMIT; return {user_id, tenant_id, email, created=True, linked=False}
23. S9: SET Valkey auth:user:{sub} = {user_id, tenant_id}, EX=3600
24. S9: Set-Cookie: refresh_token=<refresh_token>; HttpOnly; SameSite=Strict; Path=/v1/auth/refresh; Max-Age=2592000
25. S9: return 200 {access_token, expires_in=900, token_type=Bearer, user: {user_id, tenant_id, email, sub, email_verified}}
26. Frontend: store access_token in AuthContext, navigate to "/"
```

#### B. Authenticated API request

```
1. Frontend: GET /v1/companies/AAPL/overview
   Headers: Authorization: Bearer <access_token>
2. S9 OIDCAuthMiddleware: decode access_token → {sub, email, ...} → request.state.user
3. S9: GET Valkey auth:user:{sub} → {user_id, tenant_id} (cache hit, ~0.5ms)
4. S9 InternalJWTIssuerMiddleware: sign RS256 JWT {sub=user_id, tenant_id, oidc_sub=sub, role=user, jti=UUID7, exp=now+300}
5. S9: GET http://market-data:8003/api/v1/companies/AAPL/overview
   Headers: X-Internal-JWT: <signed_jwt>
6. S3 InternalJWTMiddleware: verify RS256 JWT (public key cached from /internal/jwks)
7. S3: request.state.tenant_id = tenant_id, request.state.user_id = user_id
8. S3: execute query (tenant_id used for any tenant-scoped resources)
9. S3 → S9 → Frontend: response
```

#### C. Token refresh (silent, on page load or 401)

```
1. Frontend: POST /v1/auth/refresh (browser auto-sends httpOnly cookie)
2. S9: read refresh_token from cookie
3. S9: POST https://.../oauth/v2/token {grant_type=refresh_token, refresh_token, client_id}
4. Zitadel: {new access_token, new refresh_token, expires_in=900}
5. S9: Set-Cookie: refresh_token=<new_token>; [same attrs]  (rotate refresh token)
6. S9: return 200 {access_token, expires_in, token_type}
7. Frontend: store new access_token in AuthContext, retry original request
```

#### D. Backend service startup (JWKS fetch)

```
1. Service starts; InternalJWTMiddleware.startup() is called from FastAPI lifespan
2. Middleware: GET http://api-gateway:8000/internal/jwks (timeout=10s, retry 3×)
3. S9: return {keys: [{kty: RSA, kid, n, e, alg: RS256, use: sig}]}
4. Middleware: cache {kid → RSAPublicKey} in memory
5. Future requests: jwt.decode(token, public_key, algorithms=["RS256"])
6. Every 1h: background task re-fetches /internal/jwks (background asyncio task)
7. On kid miss: immediate re-fetch before rejecting the request
```

---

## §7 Architecture Decisions

### ADR-025-1: Zitadel Cloud instead of self-hosted Keycloak

**Decision**: Use Zitadel Cloud (managed SaaS, EU region) as the OIDC provider.

| Factor | Keycloak (self-hosted) | Zitadel Cloud |
|--------|----------------------|---------------|
| Ops burden | High — DB backup, patching, HA, Java heap | Zero |
| Startup time | 30–60s (Java cold start) | N/A (external) |
| Memory | 256–512MB heap | N/A |
| Cost | $0 infra but 2–4h/week ops | $0 free tier ≤ 100 DAU |
| OIDC compliance | Full | Full |
| Future migration | Self-hosted → Cloud trivial | Cloud → self-hosted trivial |
| B2B multi-tenancy | Bolted-on Realms | First-class Organizations |

**Why Zitadel Cloud**: The auth system is the worst possible component to have an incident on. At startup scale, engineering time is the constraint — not server resources. Zitadel Cloud eliminates the entire auth ops problem space.

**Provider-agnosticism**: S9 uses `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_AUDIENCE`. Switching to Auth0, WorkOS, or self-hosted Zitadel requires changing these three env vars only. No code changes.

### ADR-025-2: RS256 internal JWT over HS256 shared secret

**Decision**: S9 signs internal JWTs with an RSA private key; backends verify with the public key from `GET /internal/jwks`.

**Why RS256**:
- A compromised backend service cannot forge requests to other backends (no private key held)
- Standard JWKS distribution pattern — works identically whether S9 is a sidecar, a separate pod, or a remote service
- PyJWT overhead: RS256 sign ≈ 1.5ms, verify ≈ 0.3ms (RSA-2048; negligible vs network latency)
- The implementation cost over HS256 is ~10 additional lines in S9 (keypair loading) and identical code in backends (just different `algorithms=["RS256"]`)

**Rejected alternative (HS256)**: All backends hold the signing secret. Compromise of any backend exposes the secret, allowing that backend (or an attacker with its credentials) to forge requests as any tenant.

### ADR-025-3: PKCE flow only — no Resource Owner Password Credentials

**Decision**: The only supported OAuth2 grant is Authorization Code with PKCE (S256). Password grant and implicit flow are disabled in Zitadel.

**Why**: OAuth 2.1 explicitly removes implicit flow and ROPC. PKCE means Worldview never handles, stores, or transmits passwords — they never leave Zitadel's infrastructure. This satisfies GDPR's data minimization principle for credential handling.

**UX trade-off**: Users see a Zitadel-hosted login page (redirect) instead of an inline form. This is industry-standard (Google, GitHub, Okta all work this way). The redirect round-trip adds ~100ms latency to the login flow, which happens once per session.

### ADR-025-4: Lazy provisioning on first callback

**Decision**: User+Tenant records in S1 are created synchronously during `GET /v1/auth/callback`, not via Zitadel webhooks.

**Why**: Webhooks require a publicly reachable endpoint during registration, retry handling, ordering guarantees, and dead-letter processing. Lazy provisioning is synchronous, testable with standard integration tests, has exactly-once semantics (single-use `state` prevents double-callback), and needs no additional infrastructure.

**Failure mode**: If S1 is down during callback, the user sees a 503. This is acceptable — users cannot use the app if S1 is down regardless (portfolio features fail). The fix is: retry login after S1 recovers.

### ADR-025-5: httpOnly cookie for refresh token

**Decision**: `refresh_token` is stored in an httpOnly, SameSite=Strict, Secure (production) cookie at `Path=/v1/auth/refresh`.

**Why**: httpOnly prevents XSS scripts from reading the refresh token. `SameSite=Strict` prevents CSRF on the refresh endpoint. `Path=/v1/auth/refresh` means the cookie is only sent to the refresh endpoint (not to every API request). The access_token is short-lived (15 min) and held only in React state — even XSS can only steal a 15-min window.

**Local dev**: `COOKIE_SECURE=false` removes the `Secure` flag so cookies work over `http://localhost`. The `SameSite=Strict` and `HttpOnly` flags remain.

**Vercel + custom domain**: Frontend at `https://app.<DOMAIN>` + S9 at `https://api.<DOMAIN>` share the second-level domain `<DOMAIN>`. Cookie with `Domain=.<DOMAIN>` (no explicit Domain means host-only in most browsers). Since the cookie path is `/v1/auth/refresh` and the frontend calls `https://api.<DOMAIN>/v1/auth/refresh`, the cookie is sent correctly. This works because the cookie is set by the S9 domain and returned to the S9 domain only.

### ADR-025-6: B2C now, B2B-ready schema

**Decision**: Every OIDC user gets their own Tenant. The `users` table gets a `role` column and a stub `invitations` table is created.

**Why**: Adding a `role` column to an existing table after the fact requires a multi-step migration (add nullable → backfill → add constraint). The `invitations` table requires FK relationships that are cleaner to establish when the core schema is first defined. The cost now is one column + one table with zero application code. The saving later is avoiding a complex live migration.

**Future B2B path**: When B2B is activated, the provisioning logic switches from "sub → create new tenant" to "org_id from Zitadel JWT → look up or create tenant". The Valkey cache `auth:user:{sub}` → `{user_id, tenant_id}` continues to work unchanged.

---

## §8 Security Analysis

### Threat Model

| Threat | Vector | Mitigation |
|--------|--------|-----------|
| Token forgery | Attacker creates fake JWT with any tenant_id | Zitadel RS256 JWT: forging requires Zitadel's private key. Internal JWT: forging requires S9's RSA private key. Neither is exposed in code or environment of backend services. |
| CSRF on auth callback | Attacker tricks user into using attacker's auth code | `state` validated against Valkey (single-use, 10-min TTL). Without the matching state, callback returns 400. |
| XSS stealing access_token | Injected script reads JS-accessible token | access_token in React state (in-memory). XSS can steal it, but TTL is 15 min and no persistent refresh capability (httpOnly cookie not readable by script). |
| XSS stealing refresh_token | Injected script reads cookie | httpOnly cookie — script cannot access. |
| CSRF on refresh endpoint | Attacker triggers refresh from another origin | `SameSite=Strict` cookie prevents cross-site request. |
| Replay of internal JWT | Attacker captures X-Internal-JWT and replays | 5-min TTL + `jti` (UUID7). Backend should check `jti` in a short-lived seen-set (Valkey, TTL=300s) if replay prevention is required. This PRD notes it as a DEFERRED hardening step. |
| Backend service impersonation | Compromised service forges requests as S9 | RS256 internal JWT — compromised backend holds no private key and cannot forge. |
| Tenant isolation bypass | Route handler uses wrong tenant_id | `request.state.tenant_id` is set exclusively by `InternalJWTMiddleware` from the validated JWT. Route handlers must never read `X-Tenant-Id` directly. |
| Path traversal to /internal/* | Attacker calls `GET /internal/jwks` from internet | Traefik ingress blocks all `/internal/*` paths from the public entrypoint. |
| Zitadel outage | OIDC provider unavailable | Existing sessions remain valid (access_token 15 min, refresh_token 30 days). New logins fail gracefully with 503. |

### Multi-Tenant Isolation

`InternalJWTMiddleware` extracts `tenant_id` from the cryptographically verified internal JWT and stores it in `request.state.tenant_id`. All repository methods that query tenant-scoped data must use `request.state.tenant_id` (injected via FastAPI `Depends`). Route handlers must never read `X-Tenant-Id` header directly — this is now a dead header.

Architecture test should be added: `scripts/import_guards/` rule verifying no service reads `request.headers.get("X-Tenant-Id")` directly after this PRD lands.

### Input Validation

| Input Surface | Validation |
|--------------|-----------|
| `state` param in callback | UUID4 format check; existence in Valkey |
| `code` param in callback | Forwarded to Zitadel (Zitadel validates) |
| `sub` in provision request | Non-empty, max 255 chars, UTF-8 |
| `email` in provision request | Valid email format via Pydantic `EmailStr`, max 255 chars |
| `username` in provision request | Optional, max 100 chars, stripped whitespace |
| Access tokens | RS256 validated (sig + iss + aud + exp) |
| Internal JWTs | RS256 validated (sig + iss + exp + required claims) |
| `X-Internal-JWT` | Not logged in full — only `kid` and `jti` are logged |

---

## §9 Failure Modes

| Failure | Scope | Behavior | Recovery |
|---------|-------|----------|----------|
| Zitadel Cloud outage | New logins, token refresh | `GET /login` → 502 (OIDC discovery cached, but `/token` fails). Existing sessions continue working until access_token expires (15 min). After 15 min, refresh fails → user is logged out. | Monitor Zitadel status page; Zitadel SLA is 99.9% |
| Valkey down during login | State storage for PKCE | `GET /login` returns 503 (fail-closed: cannot store state). Prevents login until Valkey recovers. | Valkey is a shared infra dep; recovery < 30s typical |
| Valkey down during callback | State validation | `GET /callback` returns 503 (state unreadable). | User retries login after Valkey recovers |
| S1 down during callback | User provisioning | `GET /callback` returns 503. Login impossible until S1 recovers. | Acceptable: S1 down = app unusable anyway |
| S9 down | All traffic | No access to any endpoint | k8s liveness probe restarts S9 |
| Backend service can't reach `/internal/jwks` on startup | JWKS fetch | Service logs warning, retries 3× (3s intervals). If still failing after 3 retries: service fails to start (startup fails). | S9 must be healthy before backend services start |
| `/internal/jwks` unavailable after startup | Runtime JWT validation | `kid` miss triggers refresh; if refresh fails, serve from stale cache (up to 1h). If public_key is None (never loaded), return 503 for all authenticated requests. | S9 health probe covers this |
| Internal JWT expired in transit | Clock skew between services | Internal JWT has 5-min TTL; adds 1-2s of clock drift tolerance. Ensure NTP sync on all nodes. | Docker/k8s NTP is typically < 100ms |
| Internal JWT `kid` mismatch after key rotation | Backends hold stale public key | On `kid` miss: immediate `/internal/jwks` refresh. During key rotation, old key should remain in JWKS for 1h alongside new key. | Key rotation procedure: add new key to JWKS → update S9 to sign with new key → wait 1h → remove old key |
| Stale Valkey `auth:user:{sub}` after user deletion in S1 | Deleted user still authenticated for 1h | On next Valkey miss (or forced logout), cache is not repopulated. Acceptable: user has no portfolio data to access. | If immediate revocation needed: `DEL auth:user:{sub}` from Valkey admin |
| Double-callback (state reuse attempt) | Attacker replays valid code+state | `state` is deleted from Valkey on first use. Second callback returns 400. Code is now invalid at Zitadel regardless. | By design |

---

## §10 Scalability & Performance

### S9 Auth Overhead Per Request

| Step | Overhead | Notes |
|------|----------|-------|
| JWT decode (Zitadel RS256) | ~0.2ms | RSA verify, in-process |
| Valkey lookup `auth:user:{sub}` | ~0.5ms | Sub-millisecond cache hit |
| Internal JWT sign (RS256) | ~1.5ms | RSA-2048 sign; dominates |
| Total added overhead | ~2.2ms p50 | Negligible vs 10–200ms upstream latency |

### S9 JWKS Cache

- Fetched once at startup; refreshed every 1h in background
- Memory: ~1KB per key (RSA-2048 public key)
- No per-request I/O

### Backend `InternalJWTMiddleware` Overhead

| Step | Overhead | Notes |
|------|----------|-------|
| JWT verify (RS256) | ~0.3ms | RSA verify from in-memory public key |
| State extraction | <0.01ms | Dictionary access |
| Total | ~0.3ms | Negligible |

### Rate Limiting Under Load

- Valkey `INCR` + `EXPIRE`: ~0.3ms per request
- Fail-open if Valkey unavailable (no latency added)
- Key pattern: `rl:v1:user:{user_id}` (authenticated), `rl:v1:ip:{hash}` (unauthenticated)
- Sliding window: 100 req/min per authenticated user, 20 req/min per unauthenticated IP

### Zitadel Cloud Capacity

- Free tier: 100 DAU, 10K MAU — more than sufficient for thesis + early startup
- Token endpoint latency: ~50–100ms (EU region, measured from EU)
- This latency only occurs during login and token refresh — not on every API request

---

## §11 Test Strategy

### Unit Tests (S9)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_pkce_challenge_s256` | `code_challenge = base64url(sha256(code_verifier))` exact | HIGH |
| `test_login_stores_state_in_valkey` | `GET /v1/auth/login` stores `auth:pkce:{state}` with 600s TTL | HIGH |
| `test_login_redirect_url_contains_all_params` | 302 URL has client_id, scope, code_challenge, state, redirect_uri | HIGH |
| `test_callback_validates_state` | Unknown state returns 400 | HIGH |
| `test_callback_single_use_state` | Second call with same state returns 400 | HIGH |
| `test_callback_error_param_returns_400` | `?error=access_denied` returns 400 with error_description | HIGH |
| `test_oidc_jwt_validation_expired` | Expired access_token returns 401 | HIGH |
| `test_oidc_jwt_validation_wrong_issuer` | Wrong iss returns 401 | HIGH |
| `test_oidc_jwt_validation_wrong_audience` | Wrong aud returns 401 | HIGH |
| `test_internal_jwt_claims_structure` | `InternalJWTClaims` has iss=worldview-gateway, 5-min exp | HIGH |
| `test_system_jwt_has_system_role` | Provisioning JWT has role=system, sub=system | HIGH |
| `test_refresh_no_cookie_returns_401` | Missing cookie → 401 | HIGH |
| `test_logout_clears_cookie` | Response has `Set-Cookie: refresh_token=; Max-Age=0` | HIGH |
| `test_security_headers_present` | Every response has X-Frame-Options, X-Content-Type-Options | HIGH |
| `test_cors_rejects_wildcard_methods` | OPTIONS from unknown origin returns 403 | HIGH |
| `test_rate_limit_by_user_id` | 101st request from same user_id returns 429 | MEDIUM |
| `test_jwks_endpoint_returns_rsa_key` | `/internal/jwks` returns valid RSA JWKS JSON | HIGH |
| `test_me_endpoint_returns_user_identity` | `/v1/auth/me` returns user_id, tenant_id, email | HIGH |

### Unit Tests (S1)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_provision_creates_user_and_tenant` | New sub → tenant + user created, created=True | HIGH |
| `test_provision_idempotent` | Same sub called twice → same user_id returned | HIGH |
| `test_provision_links_by_email` | Existing user with NULL external_id linked, linked=True | HIGH |
| `test_provision_409_on_sub_conflict` | Sub conflicts with different sub on same email → 409 | HIGH |
| `test_provision_requires_system_role` | JWT with role=user rejected with 401 | HIGH |
| `test_provision_writes_audit_log_on_create` | `auth_audit_log` row with event_type=user_created | HIGH |
| `test_provision_writes_audit_log_on_link` | `auth_audit_log` row with event_type=account_linked | HIGH |
| `test_user_entity_external_id_nullable` | `User(external_id=None)` is valid | MEDIUM |
| `test_user_entity_role_defaults_to_owner` | `User(...)` without role → role=OWNER | MEDIUM |
| `test_invitation_stub_table_exists` | `invitations` table has correct columns via reflection | LOW |

### Unit Tests (backend services — InternalJWTMiddleware)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_middleware_rejects_missing_jwt` | No `X-Internal-JWT` header → 401 | HIGH |
| `test_middleware_rejects_expired_jwt` | Expired JWT → 401 | HIGH |
| `test_middleware_rejects_wrong_issuer` | `iss != worldview-gateway` → 401 | HIGH |
| `test_middleware_sets_tenant_id` | Valid JWT → `request.state.tenant_id` set correctly | HIGH |
| `test_middleware_sets_user_id` | Valid JWT → `request.state.user_id` set correctly | HIGH |
| `test_middleware_skips_health_path` | `GET /health` passes without JWT | HIGH |
| `test_middleware_skips_metrics_path` | `GET /metrics` passes without JWT | HIGH |
| `test_middleware_refreshes_on_kid_miss` | Unknown `kid` triggers JWKS re-fetch | MEDIUM |

### Integration Tests (S9 — with Zitadel mock)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_login_callback_full_flow` | Valkey + mock Zitadel token endpoint + mock S1 | Login → callback → access_token issued, cookie set |
| `test_refresh_token_rotation` | Valkey + mock Zitadel | Refresh returns new token, new cookie |
| `test_logout_revokes_and_clears` | Valkey + mock Zitadel | Logout calls revocation endpoint, clears cookie, deletes Valkey key |
| `test_proxy_request_includes_internal_jwt` | Valkey + mock backend | Proxied request has X-Internal-JWT header |

### Integration Tests (S1)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_provision_new_user_transaction` | Postgres | tenant + user + audit_log in single transaction |
| `test_provision_links_existing_atomic` | Postgres | UPDATE + audit_log in single transaction |
| `test_provision_concurrent_same_sub` | Postgres | Concurrent calls for same sub → exactly one user created (no duplicate) |

### Frontend Unit Tests

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_auth_provider_calls_refresh_on_mount` | `POST /v1/auth/refresh` called on mount | HIGH |
| `test_callback_page_navigates_on_success` | Successful callback stores token and navigates to / | HIGH |
| `test_protected_route_redirects_unauthenticated` | Unauthenticated user redirected to /login | HIGH |
| `test_auth_context_clears_on_logout` | After logout, `isAuthenticated = false` | HIGH |
| `test_401_triggers_refresh_and_retry` | 401 response triggers `POST /v1/auth/refresh` then retries | HIGH |

---

## §12 Migration Plan

### Existing users with manually-created accounts

Currently, users may be created manually via `POST /tenants` + `POST /users` (unauthenticated — SEC-005, also tracked as a separate issue). After this PRD:

1. Existing users continue to exist in `portfolio_db` with `external_id = NULL`
2. On their first Zitadel login, `GET /v1/auth/callback` triggers provisioning
3. Provisioning finds their email, sets `external_id = sub`, writes audit log `account_linked`
4. From that point on, the user is fully OIDC-authenticated with no action needed

### Securing `POST /tenants` (SEC-005)

After this PRD, `POST /tenants` in S1 must be protected. Options:
- **Recommended**: Make it internal-only (require `X-Internal-JWT` with `role=system`) — tenant creation now happens exclusively through the provision endpoint
- The provision endpoint is the canonical way to create users+tenants in the OIDC world

This PRD adds `InternalJWTMiddleware` to S1, so restricting `POST /tenants` can be done in the same wave.

### Alembic migrations order

1. `services/portfolio/alembic/versions/<new>_add_external_id_and_role_to_users.py`
   - `ALTER TABLE users ADD COLUMN external_id TEXT;`
   - `ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','admin','member'));`
   - `CREATE UNIQUE INDEX idx_users_external_id ON users (external_id) WHERE external_id IS NOT NULL;`

2. `services/portfolio/alembic/versions/<new>_create_invitations_and_auth_audit_log.py`
   - `CREATE TABLE invitations (...)`
   - `CREATE TABLE auth_audit_log (...)`

Both migrations are forward-compatible (additive only).

### Removing the old `X-Internal-Token` pattern

Every backend service (S1–S8, S10) currently uses `X-Internal-Token` (shared secret, `hmac.compare_digest`) for route-level auth via an `InternalAuthDep` dependency. S9 currently sends this token via `_auth_headers()`.

After PRD-0025 adds `InternalJWTMiddleware` to each backend service:

- The middleware validates `X-Internal-JWT` on **every** request before it reaches any route handler.
- S9 (post-PRD-0025) sends `X-Internal-JWT`, not `X-Internal-Token`.
- The old `InternalAuthDep` / `verify_internal_token` / `X-Internal-Token` check on each route becomes redundant AND harmful: it will reject requests because S9 no longer sends `X-Internal-Token`.

**Migration rule**: In the same wave that adds `InternalJWTMiddleware` to a service, remove all route-level `InternalAuthDep` dependencies from that service's internal routes. The middleware is the sole authentication gate after PRD-0025. The `INTERNAL_SERVICE_TOKEN` env var and `verify_internal_token` function can be removed from each service once its wave is complete.

This applies to S1's `internal.py` (watchlist routes, portfolio context, user digest endpoint) and to any other service that has `InternalAuthDep`-protected routes.

### PLAN-0022 resumption

When PLAN-0022 Waves 4–9 resume:
- Wave 7 (S9 SnapTrade routes): replace `_auth_headers()` with `_build_internal_headers(request)` pattern
- Route handlers read `request.state.tenant_id` and `request.state.user_id` set by the new middleware
- No auth logic in route handlers — consistent with all other proxy routes

---

## §13 Observability

### Metrics (Prometheus)

| Metric | Labels | Description |
|--------|--------|-------------|
| `gateway_auth_logins_total` | `result: success\|error` | PKCE callback completions |
| `gateway_auth_token_refreshes_total` | `result: success\|error` | Token refresh attempts |
| `gateway_auth_logouts_total` | — | Logout calls |
| `gateway_oidc_jwks_refreshes_total` | `result: success\|error` | JWKS cache refreshes |
| `gateway_internal_jwt_issuances_total` | — | Internal JWTs issued |
| `gateway_rate_limit_triggers_total` | `key_type: user\|ip` | Rate limit hits |
| `portfolio_provision_calls_total` | `result: created\|linked\|existing\|error` | Provisioning outcomes |

### Structured Log Fields

S9 auth events add these fields to all auth endpoint logs:
```
sub=<zitadel_sub> email=<email> event=<login|refresh|logout|me> result=<success|error>
```

S1 provision endpoint:
```
sub=<sub> email=<email> outcome=<created|linked|existing|conflict_409> user_id=<id> tenant_id=<id>
```

Backend `InternalJWTMiddleware`:
```
internal_jwt_kid=<kid> internal_jwt_jti=<jti> tenant_id=<id> user_id=<id>
```

**Never logged**: `access_token`, `refresh_token`, `code_verifier`, full JWT strings.

---

## §14 Open Questions

| ID | Question | Severity | Resolution |
|----|----------|----------|-----------|
| OQ-001 | Nginx vs Traefik | RESOLVED | Keep Traefik; no nginx |
| OQ-002 | Auth provider | RESOLVED | Zitadel Cloud |
| OQ-003 | Keycloak vs lighter alternative | RESOLVED | Zitadel Cloud |
| OQ-004 | Frontend hosting | RESOLVED | Vercel (PRD-0024); Vercel custom domain `app.<DOMAIN>` for cookie compatibility |
| OQ-005 | PLAN-0022 coordination | RESOLVED | Paused at Wave 3; resumes after this PRD |
| OQ-006 | JWT replay prevention via `jti` Valkey seen-set | DEFERRED | `jti` is included in JWT for future replay prevention; the Valkey `SETEX jti TTL` check is deferred until replay attacks are a realistic threat (internal network, short TTL) |
| OQ-007 | Zitadel Terraform provider availability | DEFERRED | Zitadel has a maintained Terraform provider (`zitadel/zitadel`); if not suitable, fallback to `infra/zitadel/README.md` manual steps only |
| OQ-008 | B2B org_id claim mapping | DEFERRED | `org_id` parsed but not used in B2C phase; future PRD defines Zitadel Org → internal Tenant mapping |
| OQ-009 | SEC-005 (`POST /tenants` unauthenticated) | RESOLVED | Addressed in Wave B (S1 changes) — restrict to system JWT only; `InternalJWTMiddleware` + role=system check replaces unauthenticated access |

---

## §15 Effort Estimation

| Area | Waves | Est. Tasks | Notes |
|------|-------|-----------|-------|
| S9 auth endpoints + middleware | 2 waves | ~15 tasks | OIDC flow, JWKS endpoint, OIDCAuthMiddleware, InternalJWTIssuerMiddleware, security hardening |
| S1 schema + provision endpoint | 1 wave | ~8 tasks | Alembic migrations, entity changes, provision use case, audit log |
| Backend middleware (S2–S8, S10) | 1 wave | ~9 tasks (1 per service) | InternalJWTMiddleware + config; identical pattern |
| Frontend auth | 1 wave | ~8 tasks | AuthContext, LoginPage, CallbackPage, ProtectedRoute, 401 interceptor |
| Infrastructure | 1 wave | ~5 tasks | Zitadel Terraform, docker-compose.zitadel.yml, keypair script, Traefik middleware |
| **Total** | **~6 waves** | **~45 tasks** | |

**Plan file**: `docs/plans/0025-auth-oidc-zitadel-internal-jwt-plan.md` (to be generated by `/plan`)

---

## §16 External API Reality Check

| Assertion | Provider | Endpoint | Verified? | Source |
|-----------|----------|---------|-----------|--------|
| Zitadel exposes `/.well-known/openid-configuration` | Zitadel Cloud | `{issuer}/.well-known/openid-configuration` | YES | OIDC Core 1.0 §4; Zitadel docs https://zitadel.com/docs/apis/openidoauth/endpoints |
| Zitadel `openid-configuration` includes `jwks_uri` | Zitadel Cloud | OIDC discovery response | YES | OIDC Discovery 1.0 §3 — mandatory field |
| Zitadel `openid-configuration` includes `end_session_endpoint` | Zitadel Cloud | OIDC discovery response | YES | Zitadel docs: end session endpoint documented |
| Zitadel access token contains `sub`, `email`, `email_verified` | Zitadel Cloud | Token response | YES | Zitadel docs: standard OIDC claims; `email` + `email_verified` available with `email` scope |
| Zitadel supports `offline_access` scope for refresh tokens | Zitadel Cloud | Token request | YES | Zitadel docs: offline_access scope returns refresh_token |
| Zitadel enforces email uniqueness per instance | Zitadel Cloud | User registration | YES | Zitadel docs: email uniqueness is enforced globally within an instance |
| Zitadel free tier available in EU region with no credit card | Zitadel Cloud | Pricing | YES | https://zitadel.com/pricing — free tier up to 100 DAU |
| Zitadel has a Terraform provider | Zitadel Cloud | Infra | YES | `registry.terraform.io/providers/zitadel/zitadel` — actively maintained |

---

## §17 Architecture Compliance Gate

| Rule | Applies? | Design Decision | Compliant? |
|------|----------|----------------|------------|
| R5 — Avro forward compat | No | No new Kafka events | N/A |
| R6 — REST API versioning | Yes | New endpoints at `/v1/auth/*`; existing endpoints unchanged | PASS |
| R7 — No cross-service DB | Yes | S9 calls S1 REST API for provisioning; no direct DB access | PASS |
| R8 — No dual writes | No | No Kafka produced; S1 provision uses single transaction for user+tenant+audit_log | PASS |
| R9 — Kafka idempotent consumers | No | No Kafka consumers | N/A |
| R10 — UUIDv7 for all IDs | Yes | `jti` in internal JWTs uses `new_uuid7()`; user.id, tenant.id, invitation.id, auth_audit_log.id all UUIDv7 | PASS |
| R11 — UTC timestamps | Yes | `iat`/`exp` are Unix UTC; `created_at` / `expires_at` are `TIMESTAMPTZ`; `utc_now()` used throughout | PASS |
| R12 — Claim-check pattern | No | No large Kafka payloads | N/A |
| R13 — No secrets in code | Yes | `INTERNAL_JWT_PRIVATE_KEY`, `OIDC_CLIENT_SECRET` are `SecretStr` with no defaults; service fails to start if unset | PASS |
| R14 — Sanitize logs | Yes | Tokens never logged; only `kid`, `jti` logged from JWT | PASS |
| R15 — Validate external input | Yes | `sub`, `email`, `username` validated via Pydantic; JWT validated via PyJWT + JWKS | PASS |
| R22 — Independent processes | No | No new worker processes | N/A |
| R23 — Dual DB URLs | Yes | S1 provision endpoint is write path; uses `UoWDep` (primary) | PASS |
| R25 — API layer isolation | Yes | S9 auth routes call use cases; S1 provision endpoint routes through `ProvisionUserUseCase` | PASS |
| R26 — UoW explicit commit | Yes | `ProvisionUserUseCase` calls `await uow.commit()` explicitly | PASS |
| R27 — ReadOnlyUoW for reads | Yes | `/v1/auth/me` in S9 is stateless; no DB read; N/A for S1 provision (it writes) | PASS |
