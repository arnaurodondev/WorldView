# Security Issues — Open Items

> **Purpose**: Tracks known security issues that must be addressed when implementing or refactoring services.
> Agents implementing api-gateway, frontend, or any service should read this file and address relevant items.
>
> **Last audited**: 2026-03-26

---

## CRITICAL — Must fix before production

### SEC-001: Hardcoded JWT Secret (api-gateway)

**File**: `services/api-gateway/src/api_gateway/config.py`
**Issue**: `jwt_secret: str = "dev-secret-change-me"` — if the env var is not set, this default allows any attacker to forge valid JWT tokens.
**Fix**: Remove the default value. Require `API_GATEWAY_JWT_SECRET` via env var with no fallback. The service should fail to start if unset.
**Status**: ADDRESSED BY PRD-0025 — `jwt_secret` removed entirely; replaced by `OIDC_ISSUER_URL` (external Zitadel JWT validation via JWKS) + `INTERNAL_JWT_PRIVATE_KEY` (RS256 asymmetric, no shared secret).

### SEC-002: Hardcoded MinIO/S3 Credentials as Defaults

**Files**:
- `libs/storage/src/storage/settings.py` (access_key / secret_key defaults)
- `services/portfolio/src/portfolio/config.py`
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-data/src/market_data/config.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/rag-chat/src/rag_chat/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `infra/compose/docker-compose.yml`

**Issue**: Storage access/secret keys default to `"minioadmin"`. If env vars are unset in production, MinIO is accessible with well-known credentials.
**Fix**: For `libs/storage/settings.py`, remove defaults for `access_key` and `secret_key` so pydantic-settings raises on missing env var. For docker-compose (dev only), keep defaults but document they are dev-only.

---

## HIGH — Fix before merge to main

### SEC-003: CORS Allows All Methods and Headers (api-gateway)

**File**: `services/api-gateway/src/api_gateway/middleware.py`
**Issue**: `allow_methods=["*"]` and `allow_headers=["*"]` combined with `allow_credentials=True` enables CSRF attacks and Authorization header spoofing from any origin.
**Fix**: Whitelist specific methods (`GET`, `POST`, `PUT`, `DELETE`, `OPTIONS`) and headers (`Authorization`, `Content-Type`, `X-Request-ID`). Restrict `allow_origins` to the frontend domain.
**Status**: ADDRESSED BY PRD-0025 — CORS restricted to explicit method/header allowlist.

### SEC-004: Rate Limiting Middleware Not Wired (api-gateway)

**File**: `services/api-gateway/src/api_gateway/app.py`
**Issue**: `RateLimitMiddleware` class exists in `middleware.py` but is never added to the FastAPI application. No rate limiting protection is active.
**Fix**: Add `app.add_middleware(RateLimitMiddleware, ...)` in `app.py` lifespan or startup.
**Status**: ADDRESSED BY PRD-0025 — `RateLimitMiddleware` wired; rate limit key changed to user_id (authenticated) or IP hash (unauthenticated).

### SEC-005: Unauthenticated Tenant Creation (portfolio)

**File**: `services/portfolio/src/portfolio/api/routes/tenant.py`
**Issue**: `POST /tenants` and `GET /tenants/{tenant_id}` have no authentication. Any client can create and enumerate tenants.
**Fix**: Protect tenant endpoints with `@Depends(require_auth)` or restrict to internal-only (`X-Internal-Token` header check). Tenant creation should be an admin-only operation.

---

## MEDIUM — Address in next sprint

### SEC-006: Missing Input Validation on String Fields

**Files**: Multiple API schema files across services.
**Issue**: Request schemas like `TenantCreateRequest.name: str`, `UserCreateRequest.email: str`, `PortfolioCreateRequest.name: str` lack length limits and format validation.
**Fix**: Add `Field(..., min_length=1, max_length=255)` for name fields. Use `EmailStr` for email fields. Add length limits to all user-facing string inputs.

### SEC-007: Missing HTTP Security Headers (api-gateway)

**File**: `services/api-gateway/src/api_gateway/app.py`
**Issue**: No security headers middleware. Missing:
- `X-Frame-Options: DENY` (clickjacking)
- `X-Content-Type-Options: nosniff` (MIME sniffing)
- `Strict-Transport-Security` (HSTS)
- `Content-Security-Policy` (XSS)
**Fix**: Add a `SecurityHeadersMiddleware` that injects these headers on every response.
**Status**: ADDRESSED BY PRD-0025 — `SecurityHeadersMiddleware` added with HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.

### SEC-008: Rate Limiting by IP Only (api-gateway)

**File**: `services/api-gateway/src/api_gateway/middleware.py`
**Issue**: Rate limiting uses `client_ip` as key. Ineffective behind proxies or for per-user limits.
**Fix**: After authentication, rate limit by user ID. Fall back to IP for unauthenticated endpoints. Respect `X-Forwarded-For` behind trusted proxies.
**Status**: ADDRESSED BY PRD-0025 — Rate limit key = `user_id` (authenticated) or `sha256(IP)[:16]` (unauthenticated).

### SEC-009: Unescaped LIKE Patterns in Search (market-data)

**File**: `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py`
**Issue**: `ilike(pattern)` without escaping LIKE metacharacters (`%`, `_`). Not SQL injection (parameterized), but can cause unexpected results or performance issues.
**Fix**: Escape `%` and `_` in user input before passing to `ilike()`.

### SEC-010: Database Credentials in Default Connection Strings

**Files**:
- `services/portfolio/src/portfolio/config.py`
- `infra/compose/docker-compose.yml`
**Issue**: Connection strings contain `postgres:postgres` as defaults. If configs are logged or exposed, credentials are visible.
**Fix**: Compose connection strings from separate `db_user`, `db_password`, `db_host`, `db_port`, `db_name` fields in pydantic-settings, with no defaults for user/password.

---

## LOW — Nice to have

### SEC-011: No Audit Logging

**Issue**: Security-sensitive operations (tenant creation, portfolio deletion, auth failures, config changes) are not logged with user/tenant context for forensic analysis.
**Fix**: Add structured audit log entries for security events using structlog with `event_type="audit"`, `actor_id`, `tenant_id`, `action`, `resource`, `outcome` fields.

---

## Already Handled (no action needed)

- **SQL injection**: All queries use SQLAlchemy ORM or parameterized statements
- **Tenant isolation**: Repositories filter by `tenant_id` in all queries
- **Unsafe deserialization**: No pickle, yaml.load(), eval(), or exec() usage
- **Docker security**: Services run as non-root (`appuser`), multi-stage builds, Alpine base
- **Secrets in VCS**: `.env` files in `.gitignore`
- **Dependency pinning**: Standardized in this session (services `==`, libs `>=X,<Y`)
