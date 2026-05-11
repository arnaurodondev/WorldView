# PLAN-0030: Security Hardening — QA-2026-04-19 Remediation

**Source**: `docs/audits/2026-04-19-qa-security-patterns-report.md`
**Status**: completed
**Created**: 2026-04-19
**Updated**: 2026-04-19
**Completed**: 2026-04-19
**Total Waves**: 6
**Estimated Effort**: 4–6 hours (agent time)

---

## Overview

This plan remediates all **open findings** from the 2026-04-19 security patterns QA audit.
The audit identified 52 findings across 5 specialist agents; 9 were auto-fixed during the QA pass.
This plan covers the remaining **20 open items** (6 CRITICAL, 8 MAJOR, 2 MINOR, plus 4 supplementary).

### Already Fixed (Not in Scope)

| Finding | Fix | Applied By |
|---------|-----|-----------|
| F-001 | `sanitizeRedirect()` in login + callback | QA pass |
| F-005 | Grafana anonymous admin disabled | QA pass |
| F-007 | pnpm CI pin to `@10.33.0` | QA pass |
| F-010 | `safeExternalUrl()` for API hrefs | QA pass |
| FE-008 | AuthContext security check to useEffect | QA pass |
| PKG-025 | `.npmrc` with `save-exact=true` | QA pass |
| INFRA-017/018/019 | Docker image tag pins | QA pass |

### Codebase State Verification

| Finding | Type | Location | Current State | Required State | Delta |
|---------|------|----------|---------------|----------------|-------|
| F-004 PyJWT | pyproject.toml | 8 backend services | `"PyJWT[crypto]>=2.8"` (no upper) | `"PyJWT[crypto]>=2.8,<3"` | add `<3` bound |
| F-004 cryptography | pyproject.toml | 9 services (incl. api-gw) | `"cryptography>=42.0"` (no upper) | `"cryptography>=42.0,<43"` | add `<43` bound |
| F-004 portfolio | pyproject.toml | portfolio | `"PyJWT[cryptography]>=2.8,<3"` | already correct | **none** |
| F-004 api-gw PyJWT | pyproject.toml | api-gateway | `"pyjwt[crypto]==2.8"` (exact pin) | already correct | **none** |
| F-008 pnpm-lock | lockfile | worldview-web | **MISSING** | must exist | `pnpm install` |
| F-017 datasketch | pyproject.toml | content-store | `"datasketch==1.6"` (prefix) | `"datasketch==1.6.5"` | exact pin |
| F-018 intel-mig deps | requirements.txt | intelligence-migrations | `>=` no upper bounds | exact pins | pin all 4 |
| F-002 headers | next.config.ts | worldview-web | no `headers()` export | security headers | add function |
| F-003 action pins | ci.yml, deploy.yml | CI/CD | floating `@v4` tags | SHA-pinned | update all |
| F-006 yq checksum | deploy.yml | CI/CD | wget no checksum | SHA-256 verify | add step |
| F-009 Dockerfiles | Dockerfile | 3 images | no USER instruction | non-root user | add USER |
| F-011 fail-open | middleware.py | api-gateway | silent `pass` | log error | add `logger.error` |
| F-012 JTI replay | internal_jwt.py | 8 backends | no JTI check | Valkey set-NX | add check |
| F-013 cookie_secure | config.py | api-gateway | `False` default | `True` default | change default |
| F-014 dev JWT require | middleware.py | api-gateway | no `require` option | add `require` | add options dict |
| F-015 issuer= param | internal_jwt.py | 8 backends | post-decode string check | `issuer=` param | change decode call |
| F-016 CORS wildcard | middleware.py | api-gateway | no guard | startup validator | add check |
| F-019 ws:// default | next.config.ts | worldview-web | `ws://` default | prod warning | add env check |
| F-020 DB URL defaults | config.py | 7 services | hardcoded `postgres:postgres` | startup warning | add validator |

---

## Plan Structure

| Wave | Title | Findings | Effort |
|------|-------|----------|--------|
| 1 | Dependency Pinning & Lockfile | F-004, F-008, F-017, F-018 | 30–45 min |
| 2 | CI/CD Supply Chain Hardening | F-003, F-006 | 30–45 min |
| 3 | Frontend Security Headers | F-002, F-019 | 20–30 min |
| 4 | API Gateway Security Hardening | F-011, F-013, F-014, F-016 | 30–45 min |
| 5 | Backend JWT Issuer + Docker Non-Root + Config Warnings | F-015, F-009, F-020 | 45–60 min |
| 6 | JTI Replay Protection | F-012 | 45–60 min |

### Dependency Graph

```
Wave 1 (deps)  ─┐
Wave 2 (CI/CD) ─┤── all independent, can run in parallel
Wave 3 (FE)    ─┤
Wave 4 (S9)    ─┘
                 │
Wave 5 (backends + Docker) ── depends on Wave 4 (gateway must be correct before backends)
                 │
Wave 6 (JTI)    ── depends on Wave 5 (issuer= must be in place before adding JTI)
```

**Critical path**: Wave 4 → Wave 5 → Wave 6
**Parallelizable**: Waves 1, 2, 3, 4 are fully independent

---

## Wave 1: Dependency Pinning & Lockfile

**Goal**: Pin all security-critical dependencies to bounded ranges and generate the missing pnpm lockfile.
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: config

### Tasks

#### T-1-01: Add upper bounds on PyJWT and cryptography in 8 backend services

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/alert/pyproject.toml`
- `services/content-ingestion/pyproject.toml`
- `services/content-store/pyproject.toml`
- `services/knowledge-graph/pyproject.toml`
- `services/market-data/pyproject.toml`
- `services/market-ingestion/pyproject.toml`
- `services/nlp-pipeline/pyproject.toml`
- `services/rag-chat/pyproject.toml`
- `services/api-gateway/pyproject.toml` (cryptography only)
**QA reference**: F-004

**What to build**:
In each of the 8 backend `pyproject.toml` files, change:
- `"PyJWT[crypto]>=2.8"` → `"PyJWT[crypto]>=2.8,<3"`
- `"cryptography>=42.0"` → `"cryptography>=42.0,<43"`

In `services/api-gateway/pyproject.toml`, change:
- `"cryptography>=42.0"` → `"cryptography>=42.0,<43"`
(api-gateway's PyJWT is already exact-pinned at `==2.8`)

**Note**: `services/portfolio/pyproject.toml` already uses `"PyJWT[cryptography]>=2.8,<3"` — verify and leave unchanged. Portfolio uses the `[cryptography]` extra name instead of `[crypto]` — both are valid PyJWT extras, do NOT change.

**Acceptance criteria**:
- [ ] All 8 backend services have `<3` bound on PyJWT
- [ ] All 9 services (incl. api-gateway) have `<43` bound on cryptography
- [ ] `pip install -e services/<svc>` still resolves for at least one service (spot-check)

#### T-1-02: Generate pnpm-lock.yaml for worldview-web

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/pnpm-lock.yaml` (created)
**QA reference**: F-008

**What to build**:
Run `cd apps/worldview-web && pnpm install` to generate `pnpm-lock.yaml` from the existing `package.json`. The lockfile must be committed. Verify it is not gitignored.

**Acceptance criteria**:
- [ ] `apps/worldview-web/pnpm-lock.yaml` exists and is committed
- [ ] `pnpm install --frozen-lockfile` succeeds (CI simulation)
- [ ] `pnpm build` succeeds

#### T-1-03: Pin datasketch to exact version

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/content-store/pyproject.toml`
**QA reference**: F-017

**What to build**:
Change `"datasketch==1.6"` → `"datasketch==1.6.5"`. The `==1.6` is a prefix match that could resolve to any `1.6.x` release. Pin to the exact version currently installed.

**Acceptance criteria**:
- [ ] `datasketch==1.6.5` in content-store pyproject.toml

#### T-1-04: Pin intelligence-migrations requirements.txt

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/intelligence-migrations/requirements.txt`
**QA reference**: F-018

**What to build**:
Pin all 4 dependencies to exact versions with upper bounds:
```
alembic>=1.13,<2
psycopg2-binary>=2.9,<3
sqlalchemy>=2.0,<3
structlog>=24.0,<25
```
This service owns DDL for `intelligence_db` — unbounded deps are unacceptable.

**Acceptance criteria**:
- [ ] All 4 deps have upper bounds
- [ ] `pip install -r requirements.txt` resolves successfully

### Pre-read (agent must read before starting)
- `services/api-gateway/pyproject.toml`
- `services/portfolio/pyproject.toml`
- `services/content-store/pyproject.toml`
- `services/intelligence-migrations/requirements.txt`
- `apps/worldview-web/package.json`

### Validation Gate
- [ ] All modified `pyproject.toml` files parse correctly (`pip install -e` spot check)
- [ ] `pnpm install --frozen-lockfile` succeeds in `apps/worldview-web/`
- [ ] `pnpm build` succeeds in `apps/worldview-web/`

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | Dependency version bounds only add ceilings, not floors | N/A |

### Regression Guardrails
- BP-127: pre-commit ruff version mismatch — not applicable (no Python source changes)
- Verify `pnpm-lock.yaml` is not in `.gitignore`

---

## Wave 2: CI/CD Supply Chain Hardening

**Goal**: SHA-pin all GitHub Actions and add integrity verification for binary downloads.
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: config

### Tasks

#### T-2-01: SHA-pin all GitHub Actions in ci.yml

**Type**: config
**depends_on**: none
**blocks**: [T-2-02]
**Target files**:
- `.github/workflows/ci.yml`
**QA reference**: F-003

**What to build**:
Replace every floating tag with its SHA-pinned equivalent. For each action, look up the commit SHA for the current tag version using `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` or `git ls-remote`.

Actions to pin in `ci.yml` (all currently on floating tags):
- `actions/checkout@v4` → `actions/checkout@<SHA> # v4`
- `actions/setup-python@v5` → `actions/setup-python@<SHA> # v5`
- `actions/upload-artifact@v4` → `actions/upload-artifact@<SHA> # v4`
- `actions/setup-node@v4` → `actions/setup-node@<SHA> # v4`
- `actions/cache@v4` → `actions/cache@<SHA> # v4`

Format: `uses: actions/checkout@abc1234567890 # v4` — keep the version comment for readability.

**Acceptance criteria**:
- [ ] Every `uses:` in ci.yml is SHA-pinned
- [ ] Version comment appended to each line for readability
- [ ] CI workflow YAML is valid (`yq '.' .github/workflows/ci.yml`)

#### T-2-02: SHA-pin all GitHub Actions in deploy.yml + yq integrity check

**Type**: config
**depends_on**: [T-2-01] (use same SHA lookup results)
**blocks**: none
**Target files**:
- `.github/workflows/deploy.yml`
**QA reference**: F-003, F-006

**What to build**:

**Part A — SHA-pin actions in deploy.yml:**
- `actions/checkout@v4` → SHA-pinned
- `docker/setup-buildx-action@v3` → SHA-pinned
- `docker/login-action@v3` → SHA-pinned
- `docker/build-push-action@v6` → SHA-pinned
- `dorny/paths-filter@v3` → SHA-pinned
- `tibdex/github-app-token@v2` → SHA-pinned (**CRITICAL** — this receives the GitHub App private key)

**Part B — Add yq SHA-256 integrity check (F-006):**
Replace the current `Install yq` step:
```yaml
- name: Install yq
  run: |
    YQ_VERSION="v4.44.3"
    YQ_BINARY="yq_linux_amd64"
    YQ_URL="https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/${YQ_BINARY}"
    YQ_CHECKSUM_URL="https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/checksums"
    sudo wget -qO /usr/local/bin/yq "$YQ_URL"
    EXPECTED=$(curl -sL "$YQ_CHECKSUM_URL" | grep "${YQ_BINARY}$" | awk '{print $1}')
    echo "${EXPECTED}  /usr/local/bin/yq" | sha256sum -c -
    sudo chmod +x /usr/local/bin/yq
```

**Acceptance criteria**:
- [ ] Every `uses:` in deploy.yml is SHA-pinned
- [ ] `tibdex/github-app-token` is SHA-pinned (highest priority)
- [ ] yq install step includes SHA-256 verification
- [ ] Deploy workflow YAML is valid

### Pre-read (agent must read before starting)
- `.github/workflows/ci.yml`
- `.github/workflows/deploy.yml`

### Validation Gate
- [ ] Both workflow files are valid YAML
- [ ] All `uses:` lines are SHA-pinned with version comments
- [ ] yq checksum verification step is present in deploy.yml

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | SHA pins are functionally identical to tag references | N/A |

### Regression Guardrails
- BP-148: Avro schema validation — not applicable (no schema changes)
- Verify deploy.yml `bump-image-tag` job still functions correctly after action pin changes

---

## Wave 3: Frontend Security Headers

**Goal**: Add HTTP security headers to the Next.js frontend and warn about insecure WebSocket defaults.
**Depends on**: none
**Estimated effort**: 20–30 min
**Architecture layer**: config / frontend

### Tasks

#### T-3-01: Add security headers to next.config.ts

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/next.config.ts`
**QA reference**: F-002

**What to build**:
Add an `async headers()` function to `nextConfig` that returns security headers for all routes:

```typescript
async headers() {
  return [
    {
      source: "/(.*)",
      headers: [
        // Prevent clickjacking — no page should ever be framed
        { key: "X-Frame-Options", value: "DENY" },
        // Prevent MIME-type sniffing (e.g., serving JS as text/html)
        { key: "X-Content-Type-Options", value: "nosniff" },
        // Control referrer information leaked to external sites (news article links)
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        // Disable browser features we never use
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        // HSTS only in production — localhost breaks with HSTS preload
        ...(process.env.NODE_ENV === "production"
          ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
          : []),
      ],
    },
  ];
},
```

**Note**: A full Content-Security-Policy (CSP) with nonce support requires deeper Next.js integration (middleware.ts + nonce injection). Defer CSP to a future wave — the 5 headers above provide the most impactful protection immediately.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_security_headers_present | Build output includes X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy | unit |

- Minimum test count: 1
- Edge case: verify HSTS is NOT present in development mode

**Acceptance criteria**:
- [ ] `next.config.ts` exports `headers()` with all 5 headers
- [ ] `pnpm build` succeeds
- [ ] `pnpm typecheck` succeeds

#### T-3-02: Add production warning for ws:// WebSocket default

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/next.config.ts`
**QA reference**: F-019

**What to build**:
Add a build-time console warning when `NEXT_PUBLIC_WS_BASE_URL` starts with `ws://` and `NODE_ENV` is `production`. This alerts operators that WebSocket JWT tokens will travel unencrypted.

```typescript
// Warn if WS is insecure in production — JWT token travels in query param
const wsBaseUrl = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
if (process.env.NODE_ENV === "production" && wsBaseUrl.startsWith("ws://")) {
  console.warn(
    "[SECURITY] NEXT_PUBLIC_WS_BASE_URL uses ws:// (plaintext). " +
    "In production, use wss:// to encrypt WebSocket JWT tokens in transit."
  );
}
```

**Acceptance criteria**:
- [ ] Warning is emitted at build time when `NODE_ENV=production` and `ws://` is used
- [ ] No warning in development mode
- [ ] `pnpm build` still succeeds

### Pre-read (agent must read before starting)
- `apps/worldview-web/next.config.ts`

### Validation Gate
- [ ] `pnpm typecheck` passes
- [ ] `pnpm build` passes
- [ ] `pnpm test` passes (no regressions)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | Adding headers + build-time warning has no runtime behavioral change | N/A |

### Regression Guardrails
- BP-065: pre-commit stash conflict — not applicable (TypeScript files, no ruff)
- Verify Next.js API rewrites still function correctly after config changes

---

## Wave 4: API Gateway Security Hardening

**Goal**: Fix 4 security issues in the api-gateway middleware and config.
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: application / infrastructure (api-gateway only)

### Tasks

#### T-4-01: Add error logging to fail-open JWT issuance

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/middleware.py`
**QA reference**: F-011

**What to build**:
In `InternalJWTIssuerMiddleware.dispatch()`, replace the bare `pass` in the exception handler with `logger.error`:

```python
except Exception:
    logger.error(
        "internal_jwt_issuance_failed",
        user_id=user.get("user_id", ""),
        path=str(request.url.path),
        exc_info=True,
    )
```

**Design decision**: Keep fail-open (Option A from the QA report). Rationale: backends already return 401 on missing JWT, so the security boundary is maintained. The critical fix is observability — the failure was previously invisible. Option B (fail-closed with 503) can be evaluated as a follow-up if the error is seen in production logs.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_jwt_issuance_failure_logs_error | When signing raises, logger.error is called with exc_info | unit |

**Acceptance criteria**:
- [ ] Exception handler logs at ERROR level with `exc_info=True`
- [ ] No bare `pass` in the exception handler
- [ ] Unit test verifies logging on signing failure

#### T-4-02: Change cookie_secure default to True

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/config.py`
**QA reference**: F-013

**What to build**:
Change `cookie_secure: bool = False` → `cookie_secure: bool = True`.
Local dev must now explicitly set `API_GATEWAY_COOKIE_SECURE=false` in their env.

Update `services/api-gateway/configs/dev.local.env.example` (if it exists) or add a comment in config.py explaining the override.

**Downstream test impact**:
Tests that create a `Settings` instance may need `cookie_secure=False` if they don't set the env var. Check all test fixtures.

**Acceptance criteria**:
- [ ] `cookie_secure` defaults to `True`
- [ ] All existing tests pass (update fixtures if needed)
- [ ] `dev.local.env.example` includes `API_GATEWAY_COOKIE_SECURE=false`

#### T-4-03: Add `require` options to dev-mode JWT decode

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/middleware.py`
**QA reference**: F-014

**What to build**:
In `OIDCAuthMiddleware.dispatch()`, when `oidc_config is None` (dev-mode path), add `options={"require": ["iss", "sub", "exp"]}` to the `jwt.decode()` call at line ~69:

```python
payload = jwt.decode(
    token, pub_key, algorithms=["RS256"],
    options={"require": ["iss", "sub", "exp"]},
)
```

This ensures that dev-mode JWTs missing required claims are rejected, not silently accepted with missing fields.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_dev_mode_rejects_jwt_without_exp | JWT without `exp` claim is rejected in dev-mode | unit |
| test_dev_mode_rejects_jwt_without_sub | JWT without `sub` claim is rejected in dev-mode | unit |

**Acceptance criteria**:
- [ ] Dev-mode JWT decode enforces `iss`, `sub`, `exp` claims
- [ ] Existing dev-login flow still works (dev-login tokens include all 3 claims)
- [ ] 2 new tests pass

#### T-4-04: Add CORS wildcard guard

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/middleware.py`
**QA reference**: F-016

**What to build**:
In the `add_cors()` function, add a startup-time guard that raises `ValueError` if `"*"` appears in `origin_list` — because `allow_credentials=True` with `allow_origins=["*"]` is a misconfiguration that browsers reject silently:

```python
def add_cors(app: FastAPI, origins: str) -> None:
    origin_list = [o.strip() for o in origins.split(",") if o.strip()]
    if "*" in origin_list:
        raise ValueError(
            "CORS misconfiguration: allow_origins=['*'] with allow_credentials=True "
            "is rejected by browsers. Set explicit origins in API_GATEWAY_CORS_ORIGINS."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Cookie"],
    )
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_cors_rejects_wildcard_with_credentials | `add_cors(app, "*")` raises ValueError | unit |
| test_cors_accepts_explicit_origins | `add_cors(app, "http://localhost:3000")` succeeds | unit |

**Acceptance criteria**:
- [ ] `add_cors()` raises on `"*"` origin
- [ ] 2 new tests pass
- [ ] Existing tests pass (no test uses `"*"` as CORS origin)

### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/middleware.py`
- `services/api-gateway/src/api_gateway/config.py`
- `services/api-gateway/tests/` (fixture files for Settings)

### Validation Gate
- [ ] `ruff check services/api-gateway/` passes
- [ ] `mypy services/api-gateway/src/` passes
- [ ] All existing api-gateway tests pass + 6 new tests
- [ ] No architecture violations

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/api-gateway/tests/conftest.py` | `cookie_secure=True` default may cause test failures if cookie tests assume `False` | Add `cookie_secure=False` to test Settings fixture |
| `services/api-gateway/configs/dev.local.env.example` | Local dev needs `COOKIE_SECURE=false` | Add env var to example |

### Regression Guardrails
- BP-145: OIDC jwt.decode missing issuer= — this wave fixes the dev-mode path; production path already has `issuer=`
- BP-144: RateLimitMiddleware stores valkey_client=None — unrelated, but verify rate limiting still works in tests
- BP-065: pre-commit stash conflict — fix ruff before `git add`

---

## Wave 5: Backend JWT Issuer + Docker Non-Root + Config Warnings

**Goal**: Harden 8 backend InternalJWTMiddleware with `issuer=` param, add non-root users to 3 Dockerfiles, and add startup warnings for default DB credentials.
**Depends on**: Wave 4 (gateway must be correct before backends)
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure (8 backend services + Docker)

### Tasks

#### T-5-01: Add `issuer=` param to all 8 backend InternalJWTMiddleware

**Type**: impl
**depends_on**: none
**blocks**: [T-6-01]
**Target files**:
- `services/alert/src/alert/infrastructure/middleware/internal_jwt.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/middleware/internal_jwt.py`
- `services/content-store/src/content_store/infrastructure/middleware/internal_jwt.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/middleware/internal_jwt.py`
- `services/market-data/src/market_data/infrastructure/middleware/internal_jwt.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/middleware/internal_jwt.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/middleware/internal_jwt.py`
- `services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py`
**QA reference**: F-015

**What to build**:
In each backend's `InternalJWTMiddleware.dispatch()`, change the `jwt.decode()` call to include `issuer="worldview-gateway"` and remove the post-decode string check.

**Current pattern** (line ~195-201 in alert's middleware, same pattern in all 8):
```python
payload = jwt.decode(
    token,
    public_key,
    algorithms=["RS256"],
    options={"require": ["sub", "tenant_id", "role", "exp", "iss"]},
)
if payload.get("iss") != "worldview-gateway":
    raise jwt.InvalidIssuerError("iss != worldview-gateway")
```

**New pattern**:
```python
payload = jwt.decode(
    token,
    public_key,
    algorithms=["RS256"],
    issuer="worldview-gateway",
    options={"require": ["sub", "tenant_id", "role", "exp", "iss"]},
)
```

The `issuer=` parameter makes PyJWT enforce the issuer claim before the payload is accessible to application code. This prevents any code path from accessing a payload with a spoofed issuer.

Remove the now-redundant `if payload.get("iss") != "worldview-gateway"` check after adding `issuer=`.

**Tests to write** (per service, 1 test each — 8 total):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_internal_jwt_rejects_wrong_issuer | JWT with `iss=evil` returns 401 | unit |

**Acceptance criteria**:
- [ ] All 8 backends use `issuer="worldview-gateway"` in `jwt.decode()`
- [ ] Post-decode issuer string check is removed
- [ ] 8 new tests (one per service) verify wrong-issuer rejection
- [ ] All existing tests pass in all 8 services

#### T-5-02: Add non-root USER to 3 Dockerfiles

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `infra/gliner/Dockerfile`
- `services/intelligence-migrations/Dockerfile`
- `infra/postgres/Dockerfile`
**QA reference**: F-009

**What to build**:

**infra/gliner/Dockerfile** — Add before `CMD`:
```dockerfile
# Security: run as non-root (F-009)
RUN useradd --create-home --uid 1001 appuser
USER appuser
```

**services/intelligence-migrations/Dockerfile** — Add before `ENTRYPOINT`:
```dockerfile
# Security: run as non-root (F-009)
# Note: entrypoint.sh must not require root privileges (no sudo, no privileged ports)
RUN useradd --create-home --uid 1001 appuser && \
    chown -R appuser:appuser /app
USER appuser
```

**infra/postgres/Dockerfile** — Add at the end (after extension installation):
```dockerfile
# Restore non-root user after extension build (F-009)
USER postgres
```

**Acceptance criteria**:
- [ ] All 3 Dockerfiles have a non-root `USER` instruction before `CMD`/`ENTRYPOINT`
- [ ] `docker build` succeeds for all 3 images (spot check at least gliner)
- [ ] Postgres Dockerfile ends with `USER postgres` (not `USER root`)

#### T-5-03: Add startup warning for default DB credentials

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/portfolio/src/portfolio/config.py`
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-data/src/market_data/config.py`
- `services/content-ingestion/src/content_ingestion/config.py`
- `services/content-store/src/content_store/config.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `services/alert/src/alert/config.py`
**QA reference**: F-020

**What to build**:
Add a `model_validator(mode="after")` to each service's `Settings` class that emits a `structlog` warning if `database_url` contains `postgres:postgres` (the default credentials). This surfaces the misconfiguration in logs without blocking startup.

Pattern (adapt to each service's Settings class):
```python
from pydantic import model_validator

@model_validator(mode="after")
def _warn_default_credentials(self) -> Self:
    db_url = self.database_url.get_secret_value()
    if "postgres:postgres@" in db_url:
        import structlog
        structlog.get_logger().warning(
            "default_database_credentials_detected",
            hint="Set DATABASE_URL with production credentials",
        )
    return self
```

**Note**: Check if `content-ingestion` already has this pattern (the QA report mentions it does). If so, use the same pattern for consistency.

**Acceptance criteria**:
- [ ] All 7 services (excluding content-ingestion if it already has it) emit a warning on default credentials
- [ ] Warning does NOT block startup
- [ ] `ruff check` and `mypy` pass for all modified services

### Pre-read (agent must read before starting)
- `services/alert/src/alert/infrastructure/middleware/internal_jwt.py` (reference implementation)
- `services/content-ingestion/src/content_ingestion/config.py` (existing credential warning pattern)
- `infra/gliner/Dockerfile`
- `services/intelligence-migrations/Dockerfile`
- `infra/postgres/Dockerfile`

### Validation Gate
- [ ] `ruff check` passes on all modified services
- [ ] `mypy` passes on all modified services
- [ ] Unit tests pass in all 8 backend services
- [ ] Docker builds succeed for at least gliner and intelligence-migrations

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Tests using wrong-issuer JWTs | Tests that explicitly set a wrong issuer may see different error messages | Verify test assertions match PyJWT's `InvalidIssuerError` message format |
| intelligence-migrations entrypoint.sh | If script uses `chown` or writes to root-owned paths, non-root user may fail | Verify entrypoint.sh doesn't require root |

### Regression Guardrails
- BP-145: OIDCAuthMiddleware jwt.decode() missing issuer= — this was flagged as BP-145; Wave 4 fixes the gateway side, this wave fixes the backend side
- BP-134: Missing X-Internal-JWT header in tests — verify test conftest fixtures still generate valid JWTs with `iss=worldview-gateway`
- BP-065: pre-commit stash conflict — fix ruff before `git add`

---

## Wave 6: JTI Replay Protection

**Goal**: Implement JWT ID (JTI) replay detection in all 8 backend InternalJWTMiddleware using Valkey SET NX.
**Depends on**: Wave 5 (issuer= param must be in place first)
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure (8 backend services)

### Tasks

#### T-6-01: Implement JTI replay detection in InternalJWTMiddleware

**Type**: impl
**depends_on**: [T-5-01]
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/middleware/internal_jwt.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/middleware/internal_jwt.py`
- `services/content-store/src/content_store/infrastructure/middleware/internal_jwt.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/middleware/internal_jwt.py`
- `services/market-data/src/market_data/infrastructure/middleware/internal_jwt.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/middleware/internal_jwt.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/middleware/internal_jwt.py`
- `services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py`
**QA reference**: F-012

**What to build**:
After successful JWT decode in `dispatch()`, check the `jti` claim against Valkey using `SET NX` with a TTL equal to the token's remaining lifetime + 60s buffer. If the `jti` has been seen before, return 401.

**Implementation pattern** (add after the `jwt.decode()` block, before setting `request.state`):
```python
import time

# JTI replay detection (F-012): prevent token reuse within TTL
jti = payload.get("jti")
exp = payload.get("exp", 0)
if jti:
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        ttl = max(1, int(exp - time.time()) + 60)
        try:
            was_new = await valkey.set(f"jti:{jti}", "1", ex=ttl, nx=True)
            if not was_new:
                logger.warning("jti_replay_detected", jti=jti)
                return Response(
                    content='{"detail":"Token replay detected"}',
                    status_code=401,
                    media_type="application/json",
                )
        except Exception:
            # Fail-open for JTI check — Valkey unavailability should not block requests.
            # The JWT signature and expiry are still validated.
            logger.warning("jti_check_valkey_unavailable", jti=jti)
```

**Important design decisions**:
1. **Fail-open on Valkey error**: JTI replay is a defense-in-depth layer. The JWT signature + expiry are the primary security boundary. If Valkey is down, we log a warning but don't block the request.
2. **TTL = remaining_exp + 60s**: Extra buffer ensures the JTI record outlives the token.
3. **Only check if `jti` is present**: Some test JWTs may not include `jti` — gracefully skip.
4. **Valkey from `app.state`**: All services already have `valkey` on `app.state` for rate limiting or caching. Verify each service's lifespan initializes Valkey. If a service doesn't have Valkey, the check is safely skipped.

**Services needing Valkey availability verification**:
Check that each of these services initializes `app.state.valkey` in their lifespan/startup:
- alert ✓ (has Valkey for dupcheck)
- content-ingestion ✓ (has Valkey for dedup)
- content-store ✓ (has Valkey for caching)
- knowledge-graph ✓ (has Valkey for caching)
- market-data ✓ (has Valkey for caching)
- market-ingestion ✓ (has Valkey for dedup)
- nlp-pipeline ✓ (has Valkey for task locking)
- rag-chat — verify; may need to add Valkey initialization if missing

**Tests to write** (per service, 2 tests each — 16 total minimum):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_jti_replay_rejected | Second request with same `jti` returns 401 | unit |
| test_jti_first_use_accepted | First request with `jti` is accepted | unit |
| test_jti_check_skipped_when_valkey_unavailable | Request proceeds when Valkey is None | unit |
| test_jti_check_skipped_when_no_jti | JWT without `jti` is accepted | unit |

- Minimum test count: 2 per service (16 total), 4 for one reference service
- Edge cases: expired token with valid JTI, Valkey connection error, JWT without jti field

**Acceptance criteria**:
- [ ] All 8 backends check JTI against Valkey after JWT decode
- [ ] Replay returns 401 with `"Token replay detected"` detail
- [ ] Valkey unavailability logs warning but doesn't block requests
- [ ] Missing `jti` claim gracefully skips the check
- [ ] Minimum 16 new tests across 8 services
- [ ] All existing tests pass in all 8 services

### Pre-read (agent must read before starting)
- `services/alert/src/alert/infrastructure/middleware/internal_jwt.py` (reference)
- `services/alert/src/alert/app.py` (verify Valkey initialization in lifespan)
- `services/rag-chat/src/rag_chat/app.py` (verify Valkey availability)

### Validation Gate
- [ ] `ruff check` passes on all modified services
- [ ] `mypy` passes on all modified services
- [ ] Unit tests pass in all 8 backend services
- [ ] Minimum 16 new tests across services

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Tests reusing JWT tokens across multiple requests | If test fixtures generate a JWT once and reuse it in multiple requests, the second request will be rejected as replay | Update test fixtures to generate a new `jti` (UUID) per request, or mock Valkey to return `True` for `set()` |

### Regression Guardrails
- BP-144: RateLimitMiddleware Valkey — JTI check uses the same Valkey instance; verify no key collision (different prefix `jti:` vs `rl:`)
- BP-134: Missing X-Internal-JWT header in tests — tests must generate JWTs with unique `jti` per request
- BP-065: pre-commit stash conflict — fix ruff before `git add`

---

## Cross-Cutting Concerns

### Contract Changes
- None. No Avro schemas, API contracts, or response shapes change.

### Migration Needs
- None. No database schema changes.

### Event Flow Changes
- None. No Kafka topics or event semantics change.

### Configuration Changes
- `API_GATEWAY_COOKIE_SECURE=false` must be added to dev env examples (Wave 4)
- All 7 services will log a warning if using default DB credentials (Wave 5)

### Documentation Updates
- Update `docs/services/api-gateway.md` with `cookie_secure` default change
- Update security section of `docs/MASTER_PLAN.md` to note JTI replay protection

---

## Risk Assessment

### Critical Path
Wave 4 (gateway) → Wave 5 (backend JWT issuer) → Wave 6 (JTI replay)

### Highest Risk
**Wave 6 (JTI replay)**: Touches all 8 backend middleware with a stateful Valkey check. Test fixtures that reuse JWTs will break. The agent must update test helpers to generate unique `jti` values per request.

### Rollback Strategy
- Each wave is independently committable and revertable via `git revert`
- Waves 1-3 are pure config/metadata — zero runtime risk
- Wave 4-6 changes are additive (logging, validation, replay check) — can be reverted individually
- JTI replay (Wave 6) can be disabled by removing the Valkey check without affecting other security changes

### Testing Gaps
- Docker non-root (T-5-02) is hard to test in CI without building all 3 images. Spot-check locally.
- JTI replay (Wave 6) requires Valkey in integration tests. Unit tests will mock Valkey.
- GitHub Actions SHA pins (Wave 2) can only be fully verified by a CI run on the branch.

---

## Tracking

| Wave | Status | Tasks |
|------|--------|-------|
| Wave 1 — Dependency Pinning | ✅ done 2026-04-19 | T-1-01, T-1-02, T-1-03, T-1-04 |
| Wave 2 — CI/CD Hardening | ✅ done 2026-04-19 | T-2-01, T-2-02 |
| Wave 3 — Frontend Headers | ✅ done 2026-04-19 | T-3-01, T-3-02 |
| Wave 4 — Gateway Security | ✅ done 2026-04-19 | T-4-01, T-4-02, T-4-03, T-4-04 |
| Wave 5 — Backend JWT + Docker + Config | ✅ done 2026-04-19 | T-5-01, T-5-02, T-5-03 |
| Wave 6 — JTI Replay | ✅ done 2026-04-19 | T-6-01 |
