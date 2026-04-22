# PLAN-0032 — Forensic QA Remediation

> **Source**: Forensic QA & Security Certification (2026-04-21)
> **Status**: completed
> **Updated**: 2026-04-22
> **Scope**: Fix all unresolved CRITICAL/HIGH/MEDIUM findings from the forensic QA that prevented `READY_FOR_EXECUTIVE_DEMO` certification.
> **Goal**: Resolve all blockers → re-run forensic QA → achieve certification.

---

## Findings → Wave Mapping

| ID | Finding | Severity | Wave |
|----|---------|----------|------|
| SEC-001 | `next@15.1.7` has 3 critical CVEs (RCE, Auth Bypass, DoS) | CRITICAL | A-1 |
| SEC-002 | `vitest@2.1.8` RCE vulnerability | CRITICAL | A-1 |
| API-002 | S8 rag-chat JWKS startup race — `depends_on: api-gateway` missing (BP-164) | CRITICAL | B-1 |
| API-002b | S4 content-ingestion same JWKS race | CRITICAL | B-1 |
| SEC-004 | Missing Content-Security-Policy header on frontend | HIGH | A-2 |
| SEC-003 | S9 callback reflects unsanitized error/error_description in JSON | HIGH | C-1 |
| SEC-008 | CORS default includes port 3000 (should be 3001) | MEDIUM | C-1 |
| API-004 | GET /v1/transactions missing X-Portfolio-ID header forwarding | MEDIUM | C-1 |
| API-005 | PATCH /v1/watchlists/{id} returns 405 from S1 | MEDIUM | C-2 |
| API-007 | S7 /v1/fundamentals/economic-calendar returns 500 | MEDIUM | D-1 |
| API-008 | S7 /v1/entities/{id}/contradictions returns 500 | MEDIUM | D-1 |
| BT-017 | DESIGN_SYSTEM.md says "Tailwind v4" but v3.4.17 installed | LOW | E-1 |

---

## Plan Structure

```
PLAN-0032
├── Sub-Plan A: Frontend Security (2 waves)
│   ├── Wave A-1: Upgrade next + vitest (critical CVEs)
│   └── Wave A-2: Add Content-Security-Policy header
├── Sub-Plan B: Infrastructure (1 wave)
│   └── Wave B-1: Fix JWKS startup race in Docker Compose
├── Sub-Plan C: S9 API Gateway Fixes (1 wave)
│   └── Wave C-1: Callback sanitization + CORS + transaction header
├── Sub-Plan D: S7 Knowledge Graph Fixes (1 wave)
│   └── Wave D-1: Fix economic-calendar + contradictions 500 errors
└── Sub-Plan E: Documentation (1 wave)
    └── Wave E-1: Fix doc inconsistencies
```

**Note**: Wave C-2 (S1 watchlist PATCH) removed — already implemented by PLAN-0029 (completed 2026-04-19).
`services/portfolio/src/portfolio/api/routes/watchlist.py:143` has the full `PATCH /{watchlist_id}` handler.

**Dependency graph**: `A-1 → A-2` | `B-1` (independent) | `C-1` (independent) | `D-1` (independent) | `E-1` (independent)

**Parallelism**: A, B, C, D, E can all start simultaneously. Only A-2 depends on A-1.

---

## Sub-Plan A: Frontend Security

### Wave A-1: Upgrade Next.js and Vitest (Critical CVEs) ✅

**Goal**: Eliminate 3 critical + 1 high CVE in `next` and 1 critical CVE in `vitest`.
**Depends on**: none
**Estimated effort**: 30–60 min
**Status**: **DONE** — 2026-04-22 · next→15.5.15, vitest→2.1.9, 0 CVEs, 264 tests pass, pnpm build OK
**Architecture layer**: config

#### Tasks

##### T-A-1-01: Upgrade `next` to >=15.2.3

**Type**: config
**depends_on**: none
**blocks**: [T-A-2-01]
**Target files**: `apps/worldview-web/package.json`, `apps/worldview-web/pnpm-lock.yaml`
**PRD reference**: SEC-001 (forensic QA finding)

**What to build**:
Upgrade the `next` package from `15.1.7` to the latest stable `15.x` release (at least `15.2.3`). This patches:
- GHSA-9qr9-h5gf-34mp (RCE via React Flight Protocol, patched 15.1.9)
- GHSA-f82v-jwr5-mffw (Authorization Bypass in Middleware, patched 15.2.3)
- GHSA-67rr-84xm-4c7r (DoS via cache poisoning, patched 15.1.8)

**Steps**:
1. `cd apps/worldview-web && pnpm up next@latest`
2. Run `pnpm build` to verify no breaking API changes
3. Run `pnpm test` to verify all 246 unit tests pass
4. Run `pnpm test:e2e` to verify all 122 E2E tests pass
5. Run `pnpm audit` to confirm the 3 critical next CVEs are resolved
6. If any test breaks, check Next.js migration guide for the version jump and fix

**Acceptance criteria**:
- [ ] `next` version is >=15.2.3 in package.json
- [ ] `pnpm audit` shows 0 critical CVEs from `next`
- [ ] All 246 unit tests pass
- [ ] All 122 E2E tests pass
- [ ] `pnpm build` succeeds (15 routes)

##### T-A-1-02: Upgrade `vitest` to >=2.1.9

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/package.json`, `apps/worldview-web/pnpm-lock.yaml`
**PRD reference**: SEC-002 (forensic QA finding)

**What to build**:
Upgrade `vitest` from `2.1.8` to `>=2.1.9` to patch GHSA-9crc-q9x8-hgqq (RCE when accessing malicious website while Vitest API server is listening).

**Steps**:
1. `cd apps/worldview-web && pnpm up vitest@latest`
2. Run `pnpm test` to verify all 246 unit tests still pass
3. Check for any vitest config API changes in the release notes

**Acceptance criteria**:
- [ ] `vitest` version is >=2.1.9 in package.json
- [ ] All 246 unit tests pass

#### Validation Gate
- [x] `pnpm audit` shows 0 critical CVEs
- [x] `pnpm lint` — 0 errors
- [x] `pnpm typecheck` — 0 errors
- [x] `pnpm test` — 264/264 pass
- [ ] `pnpm test:e2e` — N/A (E2E requires live stack; not run in this session)
- [x] `pnpm build` — success

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Potentially all tests | Next.js major upgrade may change SSR/RSC behavior | Check migration guide; fix any test assertion changes |
| `vitest.config.ts` | Vitest API may have changed | Check release notes; update config if needed |

#### Regression Guardrails
- BP-127: pre-commit ruff version mismatch — N/A (frontend only)
- General: Run full E2E after any framework upgrade to catch subtle rendering regressions

---

### Wave A-2: Add Content-Security-Policy Header ✅

**Goal**: Add CSP header to defend against XSS in depth.
**Depends on**: Wave A-1 (to ensure new Next.js version handles headers correctly)
**Estimated effort**: 20–30 min
**Status**: **DONE** — 2026-04-22 · CSP with script-src/style-src/connect-src in next.config.ts · pnpm build OK
**Architecture layer**: config

#### Tasks

##### T-A-2-01: Add CSP to next.config.ts headers()

**Type**: config
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `apps/worldview-web/next.config.ts`
**PRD reference**: SEC-004 (forensic QA finding)

**What to build**:
Add a `Content-Security-Policy` header to the existing `headers()` function in `next.config.ts`. The policy must:
- Allow `self` for scripts (Next.js bundles)
- Allow `unsafe-inline` for styles (shadcn/ui + Tailwind use inline styles)
- Allow Google Fonts for font loading (`fonts.googleapis.com`, `fonts.gstatic.com`)
- Allow EODHD and Clearbit for images
- Allow WebSocket connections to S10 (`ws://localhost:8010` in dev, `wss://` in prod)
- Block all frame ancestors (clickjacking prevention, complements X-Frame-Options)

**CSP value**:
```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' https://*.eodhd.com https://*.clearbit.com data:; connect-src 'self' ws://localhost:8010 wss://localhost:8010; frame-ancestors 'none'
```

**Steps**:
1. Add the CSP header to the headers array in `next.config.ts`
2. Rebuild the worldview-web Docker image
3. Verify via `curl -I http://localhost:3001/` that the CSP header is present
4. Run E2E tests to confirm the CSP doesn't break any page functionality
5. If Google Fonts loading breaks, adjust the `font-src` directive

**Acceptance criteria**:
- [ ] `Content-Security-Policy` header present in frontend responses
- [ ] All 122 E2E tests pass (no CSP violations breaking functionality)
- [ ] No console CSP violation errors on dashboard, portfolio, screener pages

#### Validation Gate
- [x] CSP header added to `next.config.ts` headers() function
- [ ] `curl -I http://localhost:3001/ | grep Content-Security-Policy` — requires live stack
- [ ] `pnpm test:e2e` — N/A (requires live stack)
- [x] `pnpm build` — success

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| E2E tests with inline scripts | CSP may block eval() in test runners | Playwright runs in its own context — should not be affected |
| Google Fonts | `font-src` may need `https://fonts.gstatic.com` | Already included in proposed CSP |

#### Regression Guardrails
- BP-167: Docker image staleness — rebuild container after config change

---

## Sub-Plan B: Infrastructure

### Wave B-1: Fix JWKS Startup Race in Docker Compose ✅

**Goal**: Ensure rag-chat and content-ingestion wait for api-gateway to be healthy before starting, preventing permanent JWKS fetch failure (BP-164).
**Depends on**: none
**Estimated effort**: 15–20 min
**Status**: **DONE** — 2026-04-22 · api-gateway dependency added to rag-chat + content-ingestion; circular dep broken by removing those services from api-gateway depends_on
**Architecture layer**: infrastructure

#### Tasks

##### T-B-1-01: Add `api-gateway` dependency to rag-chat and content-ingestion

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `infra/compose/docker-compose.yml`
**PRD reference**: API-002 (forensic QA finding), BP-164

**What to build**:
Add `api-gateway: condition: service_healthy` to the `depends_on` block of both `rag-chat` and `content-ingestion` services in `docker-compose.yml`.

**Current state** (rag-chat, lines 1478–1482):
```yaml
depends_on:
  rag-chat-migrate:
    condition: service_completed_successfully
  valkey:
    condition: service_healthy
  ollama:
    condition: service_started
```

**Target state** (rag-chat):
```yaml
depends_on:
  rag-chat-migrate:
    condition: service_completed_successfully
  valkey:
    condition: service_healthy
  ollama:
    condition: service_started
  api-gateway:
    condition: service_healthy
```

Apply the same pattern to `content-ingestion` (add `api-gateway: condition: service_healthy`).

Also check if any other services that use `InternalJWTMiddleware` are missing this dependency. Services to check: `portfolio`, `market-data`, `market-ingestion`, `content-store`, `nlp-pipeline`, `knowledge-graph`, `alert`. Any service that fetches JWKS from S9 at startup should depend on `api-gateway: service_healthy`.

**Steps**:
1. Edit `infra/compose/docker-compose.yml`
2. Add `api-gateway: condition: service_healthy` to rag-chat depends_on
3. Add `api-gateway: condition: service_healthy` to content-ingestion depends_on
4. Check all other services — if they already have it, skip; if missing, add
5. Verify no circular dependency (api-gateway must NOT depend on any of these services with `service_healthy`)
6. Run `make dev-reset && make dev && make seed`
7. Verify rag-chat logs show successful JWKS fetch: `docker logs worldview-rag-chat-1 2>&1 | grep -i jwks`
8. Verify `curl http://localhost:8000/v1/threads -H "Authorization: Bearer $TOKEN"` returns 200 (not 503)

**Acceptance criteria**:
- [ ] rag-chat starts after api-gateway is healthy
- [ ] content-ingestion starts after api-gateway is healthy
- [ ] `GET /v1/threads` returns 200 (not 503)
- [ ] `POST /v1/chat/stream` returns 200 (not 503)
- [ ] `GET /v1/briefings/morning` returns 200 (not 503)
- [ ] No circular dependency in Docker Compose

#### Validation Gate
- [x] docker-compose.yml updated (rag-chat + content-ingestion → api-gateway: service_healthy)
- [x] Circular dependency resolved (rag-chat/content-ingestion removed from api-gateway depends_on)
- [ ] `make dev` — requires live stack; not validated in this session
- [ ] rag-chat JWKS logs — requires live stack

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `make dev` startup time | Services wait for api-gateway health (~15s longer) | Acceptable tradeoff |
| CI pipeline | If CI uses docker-compose, startup order changes | Verify CI still works |

#### Regression Guardrails
- BP-164: JWKS startup race — this wave directly fixes it
- BP-159: Middleware dual-instance startup — verify api-gateway is fully initialized before dependents start

---

## Sub-Plan C: S9 API Gateway Fixes

### Wave C-1: Callback Sanitization + CORS Default + Transaction Header ✅

**Goal**: Fix 3 medium-severity S9 issues: unsanitized callback errors, wrong CORS default port, and missing transaction header forwarding.
**Depends on**: none
**Estimated effort**: 30–45 min
**Status**: **DONE** — 2026-04-22 · 5 SEC-003 tests + 2 API-004 tests added · 175 unit tests pass · ruff + mypy clean
**Architecture layer**: API

#### Tasks

##### T-C-1-01: Sanitize callback error/error_description parameters

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/api-gateway/src/api_gateway/routes/auth.py`
**PRD reference**: SEC-003 (forensic QA finding)

**What to build**:
Add a whitelist of valid RFC 6749 error codes to the S9 callback handler. Currently (line 123–128), `error` and `error_description` query params are reflected directly into the JSON response. An attacker can inject HTML/JS into the JSON body via crafted redirect URLs.

**Logic**:
1. Define `KNOWN_OIDC_ERRORS` set: `{"invalid_request", "unauthorized_client", "access_denied", "unsupported_response_type", "invalid_scope", "server_error", "temporarily_unavailable", "interaction_required", "login_required", "account_selection_required", "consent_required"}`
2. If `error` is not in the whitelist, replace with `"unknown_error"`
3. Sanitize `error_description`: strip all characters except `[a-zA-Z0-9 _.,!?()-]` (alphanumeric + safe punctuation), truncate to 200 chars
4. Log the original (unsanitized) values at WARNING level for debugging

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_callback_known_oidc_error_passes_through | Known error codes are returned as-is | unit |
| test_callback_unknown_error_sanitized | Unknown error values replaced with "unknown_error" | unit |
| test_callback_xss_in_error_stripped | `<script>alert(1)</script>` becomes "unknown_error" | unit |
| test_callback_description_html_stripped | HTML in error_description is stripped to safe chars | unit |
| test_callback_description_truncated | Long descriptions truncated to 200 chars | unit |

**Acceptance criteria**:
- [ ] `GET /v1/auth/callback?error=<script>alert(1)</script>` returns `{"error":"unknown_error",...}`
- [ ] `GET /v1/auth/callback?error=access_denied` returns `{"error":"access_denied",...}`
- [ ] `error_description` with HTML tags has tags stripped
- [ ] All 5 tests pass

##### T-C-1-02: Fix CORS default to include port 3001

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `services/api-gateway/src/api_gateway/config.py`
**PRD reference**: SEC-008 (forensic QA finding)

**What to build**:
Change the default `cors_origins` from `"http://localhost:5173,http://localhost:3000"` to `"http://localhost:5173,http://localhost:3001"` on line 61 of config.py. Port 3001 is the actual frontend port (worldview-web). Port 3000 is unused and could be attacker-controlled.

**Acceptance criteria**:
- [ ] `cors_origins` default includes `:3001`
- [ ] `cors_origins` default does NOT include `:3000`

##### T-C-1-03: Fix GET /v1/transactions header forwarding

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: API-004 (forensic QA finding)

**What to build**:
The `list_transactions` route (line 808–824) passes `portfolio_id` as a query parameter, but S1 expects it as the `X-Portfolio-ID` header. Fix by extracting `portfolio_id` from query params and adding it as a header.

**Current code** (line 819):
```python
resp = await clients.portfolio.get(
    "/api/v1/transactions",
    params=dict(request.query_params),
    headers=headers,
)
```

**Fix**: Extract `portfolio_id` from query params and inject into headers:
```python
qp = dict(request.query_params)
portfolio_id = qp.pop("portfolio_id", None)
if portfolio_id:
    headers["X-Portfolio-ID"] = portfolio_id
resp = await clients.portfolio.get(
    "/api/v1/transactions",
    params=qp,
    headers=headers,
)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_transactions_forwards_portfolio_id_as_header | portfolio_id query param sent as X-Portfolio-ID header | unit |
| test_transactions_without_portfolio_id | Missing portfolio_id still proxies (S1 returns 422) | unit |

**Acceptance criteria**:
- [ ] `GET /v1/transactions?portfolio_id=<id>` returns 200 (not 422)
- [ ] S1 receives `X-Portfolio-ID` header with the correct value

#### Validation Gate
- [x] `ruff check` passes on api-gateway
- [x] `mypy` passes on api-gateway
- [x] api-gateway unit tests pass (175 pass)
- [x] New tests pass (7 total: 5 SEC-003 + 2 API-004)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Existing callback tests | May assert on raw error reflection | Update to expect sanitized values |

#### Regression Guardrails
- BP-145: OIDC jwt.decode missing issuer — already fixed in PLAN-0030; don't regress
- BP-146: PKCE GETDEL atomic — don't touch PKCE code

---

> **Wave C-2 REMOVED** — API-005 (PATCH /v1/watchlists/{id} → 405) was already fixed by PLAN-0029
> (completed 2026-04-19). `services/portfolio/src/portfolio/api/routes/watchlist.py:143` has the
> full `PATCH /{watchlist_id}` handler wired to `RenameWatchlistUseCase`. No action required.

---

## Sub-Plan D: S7 Knowledge Graph Fixes

### Wave D-1: Fix Economic Calendar + Contradictions 500 Errors ✅

**Goal**: Fix two S7 endpoints that return 500 Internal Server Error.
**Depends on**: none
**Estimated effort**: 30–45 min
**Status**: **DONE** — 2026-04-22 · R-002 param name fixed in proxy.py · BP-069 conditional WHERE in claim_repository.py · 6 new unit tests · 596 unit tests pass
**Architecture layer**: infrastructure (repository layer)

#### Tasks

##### T-D-1-01: Fix economic calendar 500 error + S9 param name mismatch

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/temporal_event_repository.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py`
**PRD reference**: API-007 (forensic QA finding) + R-002 (revise-prd 2026-04-22)

**What to build**:
Two independent bugs to fix:

**Bug 1 — S7 returns 500**: The `GET /v1/fundamentals/economic-calendar` endpoint proxies to S7's temporal events endpoint, which returns 500. Investigate and fix:
1. Check S7 logs: `docker logs worldview-knowledge-graph-1 2>&1 | grep -i "error\|traceback" | tail -20`
2. Identify the root cause (likely asyncpg parameter type ambiguity per BP-076/BP-069, or a missing DB migration)
3. Fix the query — if it uses nullable params without conditional building, refactor per BP-069/BP-076
4. Add unit test for the fix

**Bug 2 — S9 passes wrong parameter name (R-002)**: `proxy.py:631` passes `type=economic` to S7 but S7's `list_temporal_events` endpoint expects `event_type`. FastAPI silently ignores the unknown `type` param so the economic filter is always dropped — all temporal event types are returned, not just economic ones.

Fix at `services/api-gateway/src/api_gateway/routes/proxy.py` line ~631:
```python
# Before (wrong key — filter silently dropped by S7):
params={"type": "economic", **{k: v for k, v in dict(request.query_params).items() if k != "type"}}

# After (correct key matching S7's event_type Query param):
params={"event_type": "economic", **{k: v for k, v in dict(request.query_params).items() if k != "event_type"}}
```

**Acceptance criteria**:
- [ ] `GET /api/v1/temporal-events` on S7 returns 200 (empty list is OK)
- [ ] `GET /v1/fundamentals/economic-calendar` on S9 returns 200
- [ ] `GET /v1/fundamentals/economic-calendar` filters to `event_type=economic` events only (not all types)

##### T-D-1-02: Fix contradictions 500 error

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/claim_repository.py`
**PRD reference**: API-008 (forensic QA finding)

**What to build**:
The `GET /v1/entities/{id}/contradictions` endpoint returns 500. Root cause confirmed (revise-prd 2026-04-22): `claim_repository.py:125` passes `claim_type=None` alongside `rcl.contradiction_type = :claim_type` in a single query, causing asyncpg AmbiguousParameterError — asyncpg cannot infer the type of a `None`-valued parameter used in a column equality comparison.

Current buggy code at `claim_repository.py:125`:
```sql
AND (:claim_type IS NULL OR rcl.contradiction_type = :claim_type)
```
with `params = {..., "claim_type": claim_type}` where `claim_type` may be `None`.

Fix — use conditional query building (BP-069 pattern):
```python
conditions = [
    "rer.subject_entity_id = :entity_id",
    "rcl.invalidated_at IS NULL",
]
params: dict[str, object] = {"entity_id": str(entity_id), "top_k": top_k}
if claim_type is not None:
    conditions.append("rcl.contradiction_type = :claim_type")
    params["claim_type"] = claim_type
```

Remove the `:claim_type IS NULL OR` line from the SQL and replace with the conditional `WHERE` clause built above.

Add unit test covering:
- `claim_type=None` (no filter, should return all contradiction types)
- `claim_type="earnings"` (filter applied, should return only matching type)

**Acceptance criteria**:
- [ ] `GET /api/v1/entities/{id}/contradictions` on S7 returns 200 when `claim_type` is absent
- [ ] `GET /api/v1/entities/{id}/contradictions?claim_type=earnings` on S7 returns 200 with filtered results
- [ ] `GET /v1/entities/{id}/contradictions` on S9 returns 200

#### Validation Gate
- [x] `ruff check` passes on knowledge-graph
- [x] `mypy` passes on knowledge-graph
- [x] Knowledge-graph unit tests pass (596 pass, 42 deselected)
- [ ] Both endpoints return 200 on live stack — requires live stack; not validated in this session

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Existing S7 tests | May assert on specific query shapes | Update if query structure changes |

#### Regression Guardrails
- BP-076: asyncpg `::type` cast — use `CAST(:param AS type)` not `::type`
- BP-069: asyncpg AmbiguousParameterError — use conditional query building for optional params

---

## Sub-Plan E: Documentation

### Wave E-1: Fix Documentation Inconsistencies ✅

**Goal**: Correct minor doc errors found during forensic QA.
**Depends on**: none
**Estimated effort**: 10 min
**Status**: **DONE** — 2026-04-22 · Tailwind v4→v3 in DESIGN_SYSTEM.md · api-gateway.md CORS port + proxy fixes documented
**Architecture layer**: docs

#### Tasks

##### T-E-1-01: Fix Tailwind version in DESIGN_SYSTEM.md

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**: `docs/ui/DESIGN_SYSTEM.md`
**PRD reference**: BT-017 (forensic QA finding)

**What to build**:
Line 19 of DESIGN_SYSTEM.md states "Tailwind CSS v4" but `package.json` has `tailwindcss: 3.4.17`. Change to "Tailwind CSS v3" to match reality.

**Acceptance criteria**:
- [ ] DESIGN_SYSTEM.md §1 Stack table says "Tailwind CSS v3"

#### Validation Gate
- [x] No code changes — docs only

#### Break Impact
None.

#### Regression Guardrails
None.

---

## Cross-Cutting Concerns

- **Contract changes**: None — no Avro schemas or API contracts change shape
- **Migration needs**: None — no DB schema changes
- **Event flow changes**: None — no Kafka topic changes
- **Configuration changes**: `API_GATEWAY_CORS_ORIGINS` default updated; Docker Compose startup ordering changed
- **Documentation updates**: DESIGN_SYSTEM.md Tailwind version

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Next.js upgrade breaks SSR/RSC behavior | Medium | High | Run full E2E suite; check migration guide; can pin to 15.2.3 instead of latest |
| CSP blocks inline styles (shadcn/ui) | Medium | Medium | `unsafe-inline` in style-src; test all pages |
| Docker Compose ordering causes slower startup | Certain | Low | Acceptable — 15s delay prevents 503 errors |
| S7 query fixes may expose new bugs in intelligence_db | Low | Medium | Test with empty DB and with seed data |

**Critical path**: Wave A-1 (Next.js upgrade) is the highest risk — framework upgrades can cascade. Everything else is low risk.

**Rollback**: All changes are isolated. Any wave can be reverted independently via `git revert`.

---

## Execution Plan

**Recommended order** (parallelizable groups):

```
Group 1 (parallel): B-1, C-1, D-1, E-1
Group 2 (after all): A-1
Group 3 (after A-1): A-2
```

**Why A-1 last?** The Next.js upgrade carries the most regression risk. Do all other fixes first so the re-validation has a clean baseline. If A-1 causes regressions, the other fixes are already committed and won't be lost.

**Total estimated effort**: 2–3 hours
**Total waves**: 6
**Total tasks**: 9
