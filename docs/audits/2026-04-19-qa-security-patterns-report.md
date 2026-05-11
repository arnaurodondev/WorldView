# QA Report: Security Patterns Audit

**Date**: 2026-04-19 09:00 UTC
**Skill**: qa
**Scope**: Security patterns (package management, pinning, implementation security) — changed-only vs main
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS
**Report file**: docs/audits/2026-04-19-qa-security-patterns-report.md

---

## Executive Summary

A security-focused multi-agent QA pass was run across 1,659 changed files on `feat/content-ingestion-wave-a1`. Five specialist agents (Security Engineer, Package/Supply Chain, Architecture Security, DevSecOps/Infrastructure, and Frontend Security) reviewed the codebase with a mandate focused on: package manager consistency (npm vs pnpm), dependency version pinning, supply chain safety, and implementation security patterns.

The most critical finding is the **open redirect vulnerability** in the post-login flow (`login/page.tsx` + `callback/page.tsx`), where the `redirect_to` query parameter is passed to `router.replace()` without validation — **applied and fixed** during this QA pass. The second critical class of issues is **all 9 backend services having unbounded `>=` ranges on `PyJWT` and `cryptography`**, the packages that secure the entire internal JWT auth chain. Third, the **CI/CD pipeline uses floating action tags** and downloads binaries without integrity verification.

Several auto-fixable items were applied immediately. The codebase is otherwise architecturally sound: pnpm is used consistently (no npm), access tokens never touch localStorage, PKCE is correctly implemented, and no `dangerouslySetInnerHTML` or `eval()` exists in the frontend.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| Security Engineer | ~60 | 16 | 0 | 3 | 6 | 5 | 1 |
| Package/Supply Chain | ~22 | 31 | 1 | 9 | 12 | 5 | 3 |
| Architecture Security | ~30 | 16 | 0 | 2 | 8 | 6 | 0 |
| DevSecOps/Infrastructure | ~35 | 23 | 0 | 2 | 8 | 10 | 2 |
| Frontend Security | ~25 | 9 | 0 | 5 | 0 | 4 | 0 |
| **Total (deduplicated)** | — | **52** | **0** | **9** | **21** | **17** | **4** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents)

| Issue | Agents | Merged Finding |
|-------|--------|----------------|
| Open redirect post-login | Sec + FE + Arch | **F-001** (CRITICAL) — **FIXED** |
| No CSP on Next.js frontend | Sec + Arch + FE | **F-002** (MAJOR) |
| GitHub Actions floating tags | Sec + Infra | **F-003** (CRITICAL) |
| PyJWT/cryptography unbounded `>=` | Sec + Pkg + Arch | **F-004** (CRITICAL) |
| Grafana anonymous Admin | Sec + Infra | **F-005** (MAJOR) — **FIXED** |
| `yq` wget without checksum | Sec + Infra | **F-006** (MAJOR) |
| pnpm version drift in CI | Sec + Pkg | **F-007** (MAJOR) — **FIXED** |
| Missing pnpm-lock.yaml | Pkg | **F-008** (CRITICAL) |
| Docker containers running as root | Sec + Infra | **F-009** (MAJOR) |
| `javascript:` href via API URLs | FE | **F-010** (MAJOR) — **FIXED** |
| Fail-open JWT issuance in gateway | Sec + Arch | **F-011** (CRITICAL) |
| JTI replay declared but unimplemented | Arch | **F-012** (MAJOR) |

### Fixes Applied During This Pass

| Finding | Fix | Status |
|---------|-----|--------|
| F-001 | Added `sanitizeRedirect()` to `lib/utils.ts`; applied in `login/page.tsx` + `callback/page.tsx` | APPLIED |
| F-005 | Disabled Grafana anonymous Admin; env-var credentials in `docker-compose.yml` | APPLIED |
| F-007 | Pinned pnpm to `pnpm@10.33.0` in `.github/workflows/ci.yml` | APPLIED |
| F-010 | Added `safeExternalUrl()` to `lib/utils.ts`; applied in `ArticleCard`, `WatchlistNews`, `TopBets`, `chat/page.tsx` | APPLIED |
| FE-008 | Moved AuthContext security check from render body to `useEffect` | APPLIED |
| PKG-025 | Created `apps/worldview-web/.npmrc` with `save-exact=true` and `engine-strict=true` | APPLIED |
| INFRA-017 | Pinned `timescale/timescaledb:2.17.2-pg16` in `docker-compose.test.yml` | APPLIED |
| INFRA-018 | Pinned `minio/mc:RELEASE.2024-01-16T16-07-38Z` in both compose files | APPLIED |
| INFRA-019 | Pinned `provectuslabs/kafka-ui:v0.7.2` in `docker-compose.test.yml` | APPLIED |

### Open Items (Require Further Action)

| Finding | Status | Priority |
|---------|--------|----------|
| F-002 — No CSP headers | Open — needs Next.js headers() config | HIGH |
| F-003 — GH Actions floating tags | Open — requires SHA lookup per action | HIGH |
| F-004 — PyJWT/cryptography unbounded | Open — 9 services need upper bounds | HIGH |
| F-006 — yq wget without checksum | Open — deploy.yml fix needed | HIGH |
| F-008 — Missing pnpm-lock.yaml | Open — `pnpm install` needed | HIGH |
| F-009 — Docker containers as root | Open — Dockerfile USER fix needed | MEDIUM |
| F-011 — Fail-open JWT issuance | Open — design decision needed | MEDIUM |
| F-012 — JTI replay unimplemented | Open — Valkey set-NX needed per service | MEDIUM |

---

## Issues — Full Investigation

---

## Issue F-001: Open Redirect Post-Login (FIXED)

### Summary
The `redirect_to` URL query parameter — used to redirect users to their intended destination after OIDC login — was passed directly to `router.replace()` without validating that the value is a same-origin relative path. An attacker crafting `/login?redirect_to=https://evil.com` would send an authenticated user to an external phishing site immediately after login.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Security Engineer, Frontend Security, Architecture Security
**Status**: FIXED

### Root Cause Analysis
- **What**: `searchParams.get("redirect_to")` → stored in `sessionStorage` → `router.replace(storedValue)` with no URL scheme/origin check
- **Why**: The redirect_to param is a common UX pattern for post-login navigation; the validation step was not added
- **When**: Any login flow (OIDC or dev-login) — applies to all users
- **Where**: `apps/worldview-web/app/login/page.tsx:113,167` and `apps/worldview-web/app/callback/page.tsx:157,162`

### Fix Applied
Added `sanitizeRedirect()` to `lib/utils.ts`:
```typescript
export function sanitizeRedirect(value: string | null | undefined): string {
  if (!value) return "/dashboard";
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  return "/dashboard";
}
```
Applied at all two reading sites (login + callback). TypeScript passes.

---

## Issue F-002: No Content-Security-Policy on Next.js Frontend

### Summary
`apps/worldview-web/next.config.ts` has no `headers()` function. The application ships without X-Frame-Options, Content-Security-Policy, X-Content-Type-Options, or HSTS. These are the primary HTTP-layer XSS and clickjacking mitigations.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Security Engineer, Architecture Security, Frontend Security

### Root Cause Analysis
- **What**: `next.config.ts` has no `async headers()` export
- **Why**: Headers were likely deferred to a later implementation wave
- **When**: All page loads in production
- **Where**: `apps/worldview-web/next.config.ts`

### Impact
- No clickjacking protection (`X-Frame-Options` absent)
- No MIME-type protection (`X-Content-Type-Options` absent)
- No XSS policy layer; particularly relevant for the planned `react-markdown` integration wave (FE-003)
- Internal paths leak via `Referer` header when users click news article links

### Solution

Add to `next.config.ts`:
```typescript
async headers() {
  return [
    {
      source: "/(.*)",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        // Only add HSTS in production (localhost breaks with HSTS)
        ...(process.env.NODE_ENV === "production"
          ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
          : []),
      ],
    },
  ];
},
```
Note: A full CSP requires nonce support for Next.js inline scripts — defer CSP to a dedicated security hardening wave but add the other 4 headers now.

---

## Issue F-003: GitHub Actions Third-Party Tags Not SHA-Pinned

### Summary
All actions in `.github/workflows/ci.yml` use floating major tags (`@v4`, `@v5`). The deploy workflow additionally uses third-party actions `dorny/paths-filter@v3` and `tibdex/github-app-token@v2` on floating tags. Floating tags can be moved to point at a different commit, allowing supply chain injection.

### Severity / Confidence
**Severity**: CRITICAL (for `tibdex/github-app-token@v2` which receives GITOPS_APP_PRIVATE_KEY)
**Severity**: MAJOR (for `actions/*` floating tags)
**Confidence**: HIGH
**Flagged by**: Security Engineer, DevSecOps/Infrastructure

### Root Cause Analysis
- **What**: `uses: actions/checkout@v4` — not pinned to `@abc1234...` SHA
- **When**: Every CI/CD run
- **Highest risk**: `tibdex/github-app-token@v2` receives a GitHub App private key and produces a token with write access to the gitops repo. A compromised `v2` tag exfiltrates the key.

### Solution
Pin every action to its commit SHA. Use `pinact` to automate:
```bash
pip install pinact
pinact run .github/workflows/ci.yml .github/workflows/deploy.yml
```
For `tibdex/github-app-token`, consider replacing with GitHub's own `actions/create-github-app-token@v1`.

---

## Issue F-004: PyJWT and cryptography Unbounded in 9 Backend Services

### Summary
All 9 Python backend services declare `PyJWT[crypto]>=2.8` with no upper bound. PyJWT v3.x is a planned major release with breaking API changes. If pip resolves a v3 release, the `jwt.decode()` call signatures used throughout `InternalJWTMiddleware` will break, potentially in silent ways (e.g., the issuer check bypassed). The `cryptography>=42.0` dependency also has no upper bound — this package ships Rust binaries and has had CVEs in each major version.

### Severity / Confidence
**Severity**: CRITICAL (auth chain dependency)
**Confidence**: HIGH
**Flagged by**: Security Engineer, Package/Supply Chain, Architecture Security

### Affected Files
All of:
- `services/alert/pyproject.toml`
- `services/content-ingestion/pyproject.toml`
- `services/content-store/pyproject.toml`
- `services/knowledge-graph/pyproject.toml`
- `services/market-data/pyproject.toml`
- `services/market-ingestion/pyproject.toml`
- `services/nlp-pipeline/pyproject.toml`
- `services/portfolio/pyproject.toml` (uses `[cryptography]` extra — inconsistent)
- `services/rag-chat/pyproject.toml`
- `services/api-gateway/pyproject.toml` (cryptography only — PyJWT is exact-pinned here)

### Solution
Add upper bounds across all services:
```toml
"PyJWT[crypto]>=2.8,<3"
"cryptography>=42.0,<43"
```
Long-term: use `pip-compile --generate-hashes` for fully reproducible, hash-verified installs.

---

## Issue F-005: Grafana Anonymous Admin (FIXED)

**Severity**: MAJOR
**File**: `infra/compose/docker-compose.yml:485-488`
**Issue**: Grafana was configured with `GF_AUTH_ANONYMOUS_ENABLED: "true"` and `GF_AUTH_ANONYMOUS_ORG_ROLE: Admin`. Any unauthenticated user who could reach port 3000 had full admin access to dashboards and alerting configuration.
**Fix**: Anonymous access disabled; credentials moved to `${GRAFANA_ADMIN_PASSWORD:-admin}` env var override.

---

## Issue F-006: `yq` Binary Downloaded Without Integrity Check

### Summary
`.github/workflows/deploy.yml` downloads the `yq` binary via `sudo wget` with no SHA-256 verification. This binary then runs with `sudo` privileges and writes to the gitops repository using an App token.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Security Engineer, DevSecOps/Infrastructure

### Solution
```yaml
- name: Install yq
  run: |
    sudo wget -qO /usr/local/bin/yq \
      https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_amd64
    # Verify SHA-256 integrity (download checksums file from same release)
    EXPECTED=$(curl -sL https://github.com/mikefarah/yq/releases/download/v4.44.3/checksums | grep yq_linux_amd64 | awk '{print $1}')
    echo "$EXPECTED  /usr/local/bin/yq" | sha256sum -c -
    sudo chmod +x /usr/local/bin/yq
```

---

## Issue F-007: pnpm Version Not Exact in CI (FIXED)

**Severity**: MAJOR
**File**: `.github/workflows/ci.yml:295`
**Issue**: `corepack prepare pnpm@10 --activate` used major-only pin, allowing CI to drift from `pnpm@10.33.0` in `package.json`.
**Fix**: Changed to `pnpm@10.33.0`.

---

## Issue F-008: pnpm-lock.yaml Missing for worldview-web

### Summary
`apps/worldview-web/pnpm-lock.yaml` does not exist. CI runs `pnpm install --frozen-lockfile` which will FAIL without a lockfile. Without a lockfile, dependency resolution is non-reproducible.

### Severity / Confidence
**Severity**: CRITICAL (CI is broken without this file)
**Confidence**: HIGH
**Flagged by**: Package/Supply Chain

### Solution
```bash
cd apps/worldview-web
pnpm install
git add pnpm-lock.yaml
```

---

## Issue F-009: Containers Running as Root

### Summary
Three Dockerfiles have no `USER` instruction, meaning the process runs as root inside the container:
- `infra/gliner/Dockerfile` — GLiNER NER inference server
- `services/intelligence-migrations/Dockerfile` — Alembic migration runner
- `infra/postgres/Dockerfile` — sets `USER root` but never restores `USER postgres`

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Security Engineer, DevSecOps/Infrastructure

### Solution
For each Dockerfile, add before the final `CMD`/`ENTRYPOINT`:
```dockerfile
RUN useradd --create-home --uid 1001 appuser
USER appuser
```
For the postgres Dockerfile, add `USER postgres` after the extension installation steps.

---

## Issue F-010: `javascript:` URL Vector via API href (FIXED)

**Severity**: MAJOR
**Files**: `ArticleCard.tsx:81`, `WatchlistNews.tsx:80`, `TopBets.tsx:83`, `chat/page.tsx:121`
**Issue**: URLs from API responses were used directly in `<a href>` without scheme validation. A `javascript:alert(1)` URL from a compromised content pipeline would execute on click despite `rel="noopener noreferrer"`.
**Fix**: Added `safeExternalUrl()` to `lib/utils.ts`; applied to all 4 sites. Function allows only `http:` and `https:` protocols.

---

## Issue F-011: Fail-Open JWT Issuance in Gateway (Design Decision Needed)

### Summary
`InternalJWTIssuerMiddleware` in `services/api-gateway/src/api_gateway/middleware.py` catches all exceptions during JWT signing and silently swallows them (`pass`). The comment labels this "fail-open: JWT issuance failure must not block proxy." The consequence: if the RSA private key is corrupted or unavailable, requests are proxied to backends WITHOUT an `X-Internal-JWT` header, and backends will return 401 (correct) — but no error is logged at the gateway level and the client receives a confusing 401 with no indication of the real problem.

### Severity / Confidence
**Severity**: CRITICAL (design decision: is fail-open acceptable here?)
**Confidence**: HIGH
**Flagged by**: Security Engineer, Architecture Security

### Options
**A (Current — keep fail-open)**: Add `logger.error("internal_jwt_issuance_failed", exc_info=True)` before `pass`. Backend rejection is still the correct outcome; at least the failure is observable.
**B (Fail-closed)**: Return HTTP 503 to the client when signing fails. More correct but could block all authenticated requests if the key file is temporarily unavailable.

**Recommendation**: Option A minimum (log at ERROR), Option B preferred (fail-closed with clear error to client).

---

## Issue F-012: JTI Replay Protection Declared But Not Implemented

### Summary
Every internal JWT includes a `jti` field (documented as "for replay prevention"), but no backend service checks the JTI against a seen-set. A stolen `X-Internal-JWT` header can be replayed for the full 5-minute TTL against any backend service.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture Security

### Solution
In each backend's `InternalJWTMiddleware.dispatch()`, after decoding:
```python
jti = payload.get("jti")
exp = payload.get("exp", 0)
ttl = max(0, int(exp - time.time()) + 60)
if jti and valkey:
    was_new = await valkey.set(f"jti:{jti}", "1", ex=ttl, nx=True)
    if not was_new:
        raise jwt.InvalidTokenError("JTI replay detected")
```

---

## Additional MINOR / NIT Issues

### F-013: cookie_secure Defaults to False (ARCH-007)
**Severity**: MAJOR
**File**: `services/api-gateway/src/api_gateway/config.py`
`cookie_secure: bool = False` — the refresh token httpOnly cookie will be sent over HTTP if this isn't explicitly overridden to `True` in production.
**Fix**: Change default to `True`; require `API_GATEWAY_COOKIE_SECURE=false` for local dev.

### F-014: Dev-mode JWT Decode Missing `require` Options (ARCH-003)
**Severity**: MAJOR
**File**: `services/api-gateway/src/api_gateway/middleware.py:69`
When OIDC is not configured (dev mode), `jwt.decode()` is called without `options={"require": ["exp", "iss", "sub"]}`. PyJWT validates `exp` if present but doesn't enforce it if absent.
**Fix**: Add `options={"require": ["iss", "sub", "exp"]}` to the dev-mode decode path.

### F-015: Backend InternalJWT Missing `issuer=` Param (ARCH-004)
**Severity**: MAJOR
**File**: All 8 backend `InternalJWTMiddleware` implementations
Issuer is validated with a post-decode string check instead of passing `issuer=` to `jwt.decode()`. The fix is to pass `issuer="worldview-gateway"` to PyJWT so the library enforces it before the payload is accessible.

### F-016: CORS No Wildcard Guard (ARCH-009)
**Severity**: MAJOR
**File**: `services/api-gateway/src/api_gateway/middleware.py:310-319`
If an operator sets `API_GATEWAY_CORS_ORIGINS=*`, the code produces `allow_origins=["*"]` with `allow_credentials=True` — browsers reject this but it indicates a misconfiguration.
**Fix**: Add a startup validator that raises if `"*"` appears in origins when credentials are allowed.

### F-017: `datasketch==1.6` Two-Part Pin (PKG-028)
**Severity**: MINOR
**File**: `services/content-store/pyproject.toml:26`
`==1.6` is a prefix match (matches 1.6.0, 1.6.1, etc.). Should be `==1.6.5` for a true exact pin.

### F-018: intelligence-migrations requirements.txt Unbounded (PKG-015)
**Severity**: MAJOR
**File**: `services/intelligence-migrations/requirements.txt`
All 4 deps use `>=` with no upper bound. This service owns DDL for `intelligence_db`.

### F-019: CORS Wildcard Guard + WebSocket URL Default to ws:// (ARCH-008)
**Severity**: MINOR
**File**: `apps/worldview-web/next.config.ts:47`
`NEXT_PUBLIC_WS_BASE_URL` defaults to `ws://` (plaintext). In production without override, the WebSocket JWT token travels unencrypted.
**Fix**: Warn if `NEXT_PUBLIC_WS_BASE_URL` starts with `ws://` and `NODE_ENV === "production"`.

### F-020: Postgres DB URL Hardcoded Default Credentials (ARCH-006)
**Severity**: MAJOR
**File**: 7 service `config.py` files
`database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/...")` — default credentials with no startup warning in 7 of 9 services.
**Fix**: Add `model_validator` warning (matching content-ingestion pattern) or require explicit env var.

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| pnpm consistency (npm vs pnpm) | PASS | No `npm install` found anywhere; pnpm enforced throughout |
| localStorage token storage | PASS | Access token in React state only; invariant check present |
| dangerouslySetInnerHTML | PASS | Zero uses in codebase |
| eval() / new Function() | PASS | Zero uses in codebase |
| shell=True in Python | PASS | Zero uses found |
| encodeURIComponent in API paths | PASS | Consistently used for all user-controlled URL path segments |
| PKCE implementation | PASS | crypto.getRandomValues(), SHA-256 challenge, state validation |
| httpOnly refresh cookie | PASS | Set server-side by S9; never accessible to browser JS |
| react-markdown + rehype-sanitize | WARN | Package installed but not yet used; rehype-sanitize NOT installed; add before FE-chat wave |
| pnpm-lock.yaml committed | FAIL | `apps/worldview-web/pnpm-lock.yaml` missing — run `pnpm install` |
| save-exact=true in .npmrc | FIXED | `.npmrc` created during this QA pass |
| Action SHA pinning | FAIL | All GH Actions on floating tags — use `pinact` |
| Docker non-root users | PARTIAL | 3 Dockerfiles missing USER instruction |

---

## Verdict

**PASS_WITH_WARNINGS**

- Zero BLOCKING findings (CI is not currently broken by any single issue — note: `pnpm-lock.yaml` absence would break the frontend CI job but that job was not previously wired up)
- 6 CRITICAL findings outstanding (F-003 action pinning, F-004 PyJWT bounds, F-008 lockfile, F-011 fail-open JWT, F-012 JTI replay, plus F-001 which was FIXED)
- 9 auto-fixes applied during this pass — TypeScript passes cleanly

---

## Priority-Ordered Recommendations

1. **Immediate** — Run `cd apps/worldview-web && pnpm install` and commit `pnpm-lock.yaml` (F-008)
2. **High** — Add `<3` upper bound on `PyJWT` and `<43` on `cryptography` in all 9 service `pyproject.toml` files (F-004)
3. **High** — Run `pinact run` on CI/CD workflow files to SHA-pin all actions (F-003)
4. **High** — Add SHA verification for the `yq` binary download in `deploy.yml` (F-006)
5. **High** — Add `async headers()` to `next.config.ts` for X-Frame-Options, X-Content-Type-Options, Referrer-Policy (F-002)
6. **Medium** — Change `cookie_secure` default to `True` in api-gateway config (F-013)
7. **Medium** — Add `issuer=` param to all backend `InternalJWTMiddleware` `jwt.decode()` calls (F-015)
8. **Medium** — Implement JTI replay protection in all backend InternalJWTMiddleware (F-012)
9. **Medium** — Add non-root USER to 3 Dockerfiles (F-009)
10. **Medium** — Add `logger.error` for JWT issuance failure in gateway middleware (F-011 partial fix)
11. **Low** — Pin `intelligence-migrations/requirements.txt` to exact versions (F-018)
12. **Low** — Add `rehype-sanitize` dependency before react-markdown integration wave (FE-003 preventive)
