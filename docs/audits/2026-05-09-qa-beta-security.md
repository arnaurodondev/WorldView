# QA Beta-Readiness Security Audit — 2026-05-09

**Scope**: 17 session commits between `974f4f1d^` and `2b359f73` on
`feat/content-ingestion-wave-a1` (~12 138 LOC added across 142 files).
**Bar**: real users (analysts/traders) inside a hedge fund — not a demo.
**Auditor**: Security Engineer specialist agent (read-only).
**Time-box**: ~75 min.

## Executive summary

The session demonstrates strong security hygiene on the **internal-JWT plane**
(audience claim added everywhere, JTI replay detection, fail-closed on missing
JWKS, atomic Cypher allowlist, sanitized error truncation). PRD-0025 invariants
are largely upheld. However, **three findings are blocking for beta** because
they are exploitable by an authenticated user against another tenant or against
the platform: a body-trusted `tenant_id` in the chunk-search route, the absence
of any tenant column on `document_source_metadata` (so `/v1/news/top` cannot
ever scope), and a permanently global MinIO key namespace. None of these were
introduced by this session — they are pre-existing — but they are now
load-bearing for the chat tool surface, and shipping beta with a real second
tenant on the platform will leak data.

**Verdict**: **REQUEST CHANGES** for beta launch. The dev-login + Zitadel
register URL works, the auth plane is hardened, and rate-limiting / CSRF /
CORS / CSP / OIDC are all configured. But multi-tenant isolation has explicit
gaps that must be closed before any second tenant joins.

| Severity | Count |
|----------|-------|
| BLOCKING | 3 |
| HIGH     | 4 |
| MEDIUM   | 6 |
| LOW      | 5 |
| INFO     | 4 |

---

## BLOCKING

### F-001 — `/api/v1/search/chunks` trusts caller-supplied `tenant_id`

**Severity**: BLOCKING (multi-tenant isolation bypass — authenticated)
**File**: `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py:42-58`
**Schema**: `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py:169` — `tenant_id: str | None = None`
**Pattern**: HR-053 violation (vector search without enforced tenant filter).

The route accepts `tenant_id` from the request body and forwards it directly
into `_build_entity_mention_filter` / `_search_chunks`. There is no comparison
against `request.state.tenant_id` (which is set by `InternalJWTMiddleware`
from the verified JWT). A malicious client able to reach `/api/v1/search/chunks`
through S9 (or any service that forwards an `X-Internal-JWT`) can supply
`tenant_id = <victim_tenant_uuid>` in the body and receive HNSW chunks
**owned by that tenant**.

This is the single highest-impact tenant breach path in the platform because
the underlying repository (`chunks_search.py:170-174`) honours the body value
verbatim:

```python
if tenant_id is not None:
    params["tenant_id_str"] = tenant_id
    where_clauses.append("(c.tenant_id IS NULL OR c.tenant_id = CAST(:tenant_id_str AS UUID))")
else:
    where_clauses.append("c.tenant_id IS NULL")
```

The repo is correct in isolation; the route layer is the problem.

The api-gateway proxy at `services/api-gateway/src/api_gateway/routes/proxy.py`
also passes the body unchanged to S6 (no `body.tenant_id` validation step).

**Fix (mandatory before beta)**:
1. Drop `tenant_id` from `ChunkSearchRequest` (caller cannot supply it).
2. Read `tenant_id` from `request.state.tenant_id` in the route handler and
   pass it to `use_case.execute(...)`.
3. Add a regression integration test: same JWT, body `{tenant_id: <other>}` →
   400 (or silently overridden — pick one and document).

### F-002 — `document_source_metadata` has no `tenant_id`; `/v1/news/top` returns globally

**Severity**: BLOCKING for B2B beta (data leak by design)
**Files**:
- `services/nlp-pipeline/alembic/versions/0019_add_tenant_id_to_chunks_sections.py` adds `tenant_id` only to `chunks` / `sections`.
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:67-125` (`_TOP_NEWS_SQL`) has no `tenant_id` predicate.
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/news.py:57-87` does not read `request.state.tenant_id`.

**Risk**: every authenticated user — regardless of tenant — sees the same
ranked top-news feed. If the platform ever onboards a second tenant whose
articles include broker research, internal-only feeds, or proprietary RSS
sources, those articles surface to every other tenant via this endpoint.

If the design intent is "all news is public reference data" (consistent with
SEC filings, Finnhub, EODHD), then this is acceptable but must be **explicitly
documented in `PRODUCT_CONTEXT.md` and `news-intelligence.md`** so future
contributors don't unwittingly add tenant-scoped feeds (e.g. a customer's
private email digest, internal-only EDGAR-watch list) to the same table.

If any tenant-private news source is on the roadmap, add `tenant_id` to
`document_source_metadata` (nullable, with `NULL = public`) and apply the
same `(tenant_id IS NULL OR tenant_id = :tid)` predicate as `chunks`.

**Beta blocker rationale**: a hedge fund running this expects *its* SEC
watchlist research to not be visible to a second hedge fund on the same
deployment. Right now the only thing standing between that and a leak is
"we don't ingest tenant-private feeds yet" — a runtime invariant, not a
schema invariant.

### F-003 — Search-relations / claims-search proxy passes body through with no auth-context binding

**Severity**: BLOCKING when claims/relations grow tenant attribution
**File**: `services/api-gateway/src/api_gateway/routes/proxy.py:2076-2115`

The proxy verifies `request.state.user` is non-null, then forwards the
**raw body** to S7. If S7 ever adds optional tenant-scope filters to claim
or relation search (a likely follow-on for B2B), the bypass pattern is
identical to F-001: the client supplies the tenant in the body, S9 does not
override.

Today this is a YELLOW because relations and claims are global reference data
(no tenant column on `relations` / `claims`). Promote to BLOCKING the moment
either table gains a `tenant_id` column.

**Fix**: convert these two endpoints to typed Pydantic-model handlers (not
raw `request.body()` passthrough). Validate the schema; reject any
client-supplied `tenant_id`; merge the JWT-derived tenant into the body before
forwarding. Same pattern as the existing typed routes higher in this file.

---

## HIGH

### F-004 — MinIO/S3 keys are globally namespaced (no tenant prefix)

**Severity**: HIGH (object-storage cross-tenant read possible by key guess)
**Files**: `libs/storage/src/...` and `services/content-store/...` (no `tenant` token in key composition).

Bronze / silver / gold MinIO keys are composed from `doc_id`, `bucket`,
`source_type` — never `tenant_id`. Any service holding a valid internal JWT
can issue a `get_object` for any `doc_id`. The DB-layer access checks (chunks
table tenant filter) protect at the *retrieval-list* level, but if a key leaks
(e.g. via a misconfigured logging line or a DB row from a partner-tenant
journey), the underlying bytes are readable.

This is a known design choice — the system today stores public reference
content (SEC EDGAR, Finnhub, RSS) where global keys are fine. The risk
materialises the moment a tenant uploads their own document (e.g. a private
research PDF). Recommend: namespace MinIO keys with `tenant_id/` prefix and
enforce the prefix at the storage adapter (`libs/storage`) so it cannot be
forgotten by callers.

### F-005 — `internal_jwt_skip_verification=True` ungated in `app.state` for WebSocket path

**Severity**: HIGH (test/dev escape hatch reachable in production if mis-configured)
**File**: `services/alert/src/alert/infrastructure/middleware/internal_jwt.py:80-91`,
        `services/alert/src/alert/api/routes.py:421` (WebSocket).

`InternalJWTMiddleware.__init__` accepts `skip_verification=True`; when set,
a CRITICAL log fires *and* `app.state._internal_jwt_skip_verification` is
populated so the WebSocket handler can read the same value. The HTTP path
on the alert service has a production guard at `config.py:135`
(raises ValueError when APP_ENV=production), but the **bare middleware
constructor itself does not check APP_ENV** — a misconfigured deploy that
loaded a different settings module could still instantiate the middleware
with `skip_verification=True`.

Eight other services use the same pattern. Verify each has an APP_ENV guard
in its config.py (random-sample looked good, but did not exhaustively check).

**Fix**: move the `if APP_ENV == "production": raise` check into the
middleware `__init__` itself so it cannot be bypassed via a custom DI path.

### F-006 — `relations` / `claims` SQL uses f-string-built `WHERE` clauses

**Severity**: HIGH only if any clause string ever interpolates user input
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py:503`
        (also other f-string SELECTs throughout)

Today the f-string content is composed from internally controlled column names
and the user value goes through `:param` binding. **Audited 6 such sites
this session — all bind user values via `params` dict.** No injection today.

But the pattern is fragile: a future contributor adding a `direction` filter
might write `where_clauses.append(f"r.direction = '{direction}'")` and the
review may not catch it because the surrounding code already uses f-strings.
Recommend a lint rule (`scripts/import_guards/`?) that flags any f-string
inside `text()` whose curly-braces contain anything other than a known-safe
variable.

### F-007 — Migration 0038 builds INSERT via Python string formatting, not parameterized

**Severity**: HIGH-INFO (no user input, but pattern dangerous)
**File**: `services/intelligence-migrations/alembic/versions/0038_seed_demo_entities.py:132-174`

`upgrade()` builds an `INSERT` by string-concatenating row literals. Single
quotes are escaped with `replace("'", "''")` — correct. Source data is the
hardcoded `_DEMO_SEEDS` constant — not user-controlled.

Recommendation: future seed migrations use `op.bulk_insert(table, rows)`
or `text(...).bindparams()`, not f-string composition. If a seed list ever
grows from environment-variable input or a YAML file, this pattern fails.

---

## MEDIUM

### F-008 — Rate limit 300 req/min/user is generous; financial-mutation 20/min appropriate

**Severity**: MEDIUM (UX vs DoS balance)
**File**: `services/api-gateway/src/api_gateway/middleware.py:329-462`

300/min on the general bucket is reasonable for a multi-panel dashboard
(~5 reqs/sec sustained). 20/min on `/v1/transactions`, `/v1/brokerage`,
`/v1/portfolios` POST/PUT/DELETE is appropriate.

**Concern**: the chat surface (`/v1/chat/stream`) is bucketed under the
general 300/min — but each streaming request can run for tens of seconds
and consume LLM budget. A user looping a chat client for 5 minutes can fire
1500 requests at the LLM provider. **Recommend**: add a sub-bucket for
`/v1/chat/stream` and `/v1/briefings/*` at e.g. 30/min/user, separate from
read-heavy dashboard calls.

### F-009 — Chat tool `create_alert` uses module-level lazy-import for `common.ids`

**Severity**: MEDIUM-LOW (correctness only)
**File**: `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:2115`

`from common.ids import new_uuid7` inside the handler. Works, but if `common`
is missing in the runtime environment (Dockerfile drift) the failure mode is
"500 on alert creation" rather than "import-time crash with clear stack". Move
to top-of-module import.

### F-010 — `_TOOL_RESULT_MAX_CHARS = 4000` truncation may cut MinIO citation URL mid-string

**Severity**: MEDIUM-LOW (data integrity)
**File**: `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:69`, `2149`

When a tool result exceeds 4000 chars, the truncation happens with a raw
`text[:4000]` slice. If the truncation lands inside a JSON URL (e.g.
`"https://finnhub.io/news/<hash>"`), the resulting context line is malformed
and may confuse the LLM into fabricating a citation. Recommend: truncate at
the last sentence boundary or last newline before the cap.

### F-011 — `lib/storage` MinIO presigned URLs (if any) — verify TTL ≤ 5 min

**Severity**: MEDIUM (not in this session's diff; flag for follow-up)

Did not audit presigned URL TTL during this pass. If `libs/storage` exposes
`presign_get(key, ttl)`, ensure callers cap TTL ≤ 5 min and that the URL is
never logged. Spot-check before beta.

### F-012 — `dev-login` issues role=admin from a comma-list of emails — single source of truth missing

**Severity**: MEDIUM (admin-grant management)
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:735-737`

Admin role assignment in dev-login is driven by `API_GATEWAY_DEV_ADMIN_EMAILS`
env var (comma-separated). Production OIDC carries the role in the Zitadel
token, so this only matters for dev. Two risks:

1. Drift between env-var values across services (only S9 reads it; downstream
   services trust the JWT role claim).
2. No audit trail when an admin is added.

Both acceptable for a thesis demo; flag for productionisation.

### F-013 — JTI replay detection fail-open by design

**Severity**: MEDIUM (intentional, but document it)
**File**: All 9 `internal_jwt.py` middlewares (e.g. `alert/.../internal_jwt.py:251-254`)

When Valkey is unavailable, JTI replay check is silently skipped. JWT
signature + expiry + audience still validated — so an attacker cannot forge
a token, but they CAN replay a stolen token within its 5-minute TTL window
during a Valkey outage. Documented as acceptable degradation; ensure ops
runbook lists "Valkey down ⇒ token-reuse window opens" so on-call doesn't
silently shrug it off.

---

## LOW

### F-014 — Zitadel sign-up flow redirects to Zitadel-hosted register page

**Severity**: LOW (UX / B2B onboarding gap, not a security bug)
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:610-618`

`GET /v1/auth/register` redirects to `{oidc_issuer_url}/ui/console/register`.
This works if Zitadel self-registration is enabled in the Zitadel project.
For an analyst onboarding flow, the Zitadel-hosted register page is jarring
and not branded. For thesis-demo scope: acceptable. For real beta with
hedge-fund users: build a branded proxy or use Zitadel embedded
register-form templates.

Verify: on Zitadel Cloud, self-registration is enabled in your tenant
config; otherwise users hit a 404 / login-only page.

### F-015 — `set_cookie(...)` does not set `domain=` explicitly

**Severity**: LOW (default behaviour is host-only, which is what we want)
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:84-101`

Cookies set without `domain=` are scoped to the exact host that issued them.
This is correct (no subdomain leak). Document explicitly so a future change
to add `domain=".worldview.example"` doesn't accidentally widen the scope.

### F-016 — `cookie_secure` env-driven; verify production sets `=true`

**Severity**: LOW
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:362`

`cookie_secure` is read from settings. Verify the production deploy template
sets it to `true`. If `false` over an HTTPS deployment, the refresh cookie
is also sent over HTTP fallback paths.

### F-017 — Logging: `_DEV_USER_ID` and `_DEV_TENANT_ID` are hardcoded UUIDs in source

**Severity**: LOW (dev-only constants, not secrets)
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:669-672`

Acceptable. Just confirm they don't appear in any production database snapshot
or analytics dump.

### F-018 — `ws_token` log line carries `result="success"` but no user_id

**Severity**: LOW (audit-trail completeness)
**File**: `services/api-gateway/src/api_gateway/routes/auth.py:661`

For incident triage, `ws_token_issued` should include the `sub` and `tenant_id`
(without the token itself). Today only `action` and `result` are logged.

---

## INFO / Beta-readiness checklist results

### F-019 — CORS lockdown ✅
`add_cors` rejects `*` when `allow_credentials=True` (`middleware.py:476-480`).
Origins are explicit per env. `allow_methods` is a closed list.

### F-020 — CSRF / SameSite ✅
Refresh cookie + `pkce_verifier_*` cookies set `samesite="strict"` and
`httponly=True`. PKCE verifier itself stored in Valkey with atomic GETDEL
(BP-146). PKCE state nonce documented in `pkce.py:39`.

### F-021 — Backups / durability — NOT VERIFIED IN THIS PASS
`user_briefs`, `holdings`, `watchlists`, `alerts` tables exist in
service-owned DBs. **Did not verify** Postgres pg_basebackup / WAL-archiving
config or a tested restore runbook. Beta blocker if unverified — add a
documented backup + tested-restore procedure before any real users.

### F-022 — `llm_usage_log` populated ✅
`SessionScopedRagUsageLogger` wired in `app.py:229-232`; every successful or
failed LLM call writes a cost row. `internal_costs.py` exposes a query
endpoint for ops dashboards.

### F-023 — PII / chat history retention policy — NOT FOUND
Searched for `retention\|expire\|TTL` across `rag_chat` / `user_briefs`.
No automated retention/expiry of chat threads or brief archives. Document
a policy (e.g. delete chat threads >90 days, keep briefs indefinitely) and
implement it before beta. GDPR Article 17 compliance for any EU user
requires this.

---

## Specialist mandate — answers to the 12 standard questions

1. **Pydantic input validation at API boundaries** — YES on typed routes;
   NO on the raw-body proxy passthroughs (F-003).
2. **SQL injection / f-string SQL** — F-strings are present (F-006 sites
   audited) but values are bound. Migration 0038 uses string literals on
   hardcoded data only (F-007). No injection found.
3. **Hardcoded secrets / API keys / tokens** — None found in this diff. Only
   dev demo UUIDs and example domain names. ✅
4. **Internal endpoints protected** — `InternalJWTMiddleware` mounted on all
   9 services; audience claim validated everywhere; JTI replay enforced
   (with documented fail-open on Valkey outage). ✅ subject to F-005.
5. **Tenant isolation** — `chunks` / `sections` / `entity_mentions` all have
   tenant columns and queries filter properly. **`document_source_metadata`
   does NOT have a tenant column** (F-002). Search route trusts body-supplied
   tenant_id (F-001). ❌ for beta.
6. **Kafka event validation** — Avro schema registry + Pydantic decode in
   consumers; `decode_raw_array` capped at 16 MiB (BP-018). Dedup via
   `ValkeyDedupMixin`. ✅
7. **MinIO / S3 authorization** — No tenant scoping in object keys (F-004).
   Access mediated by DB-layer checks. ⚠️
8. **External HTML / RSS sanitization** — Out of scope for these 17 commits;
   not regressed. Existing pipeline relies on `trafilatura`-style extraction;
   spot-checked, not exhaustively audited.
9. **Logging hygiene** — No tokens / passwords / API keys printed. JWT decode
   errors log only `error=str(exc)` (which is PyJWT's safe message). ✅
10. **Config via env / pydantic-settings** — All services use pydantic-settings;
    OIDC client secret read from env var, never hardcoded. ✅
11. **DDL safety** — Migration 0037 uses `IF NOT EXISTS` / `IF EXISTS`
    throughout; downgrade is intentional NO-OP for safety. Migration 0038
    is idempotent via `ON CONFLICT DO NOTHING`. ✅
12. **Dependency CVEs** — `openapi-typescript` pinned exact (`7.13.0` ←
    was `^7.13.0`); no other dep upgrades. `pnpm audit` not run during this
    pass — recommend running before beta tag.

---

## Beta-specific question matrix

| Question | Verdict | Notes |
|---|---|---|
| Real user can sign up via Zitadel? | YES with caveats | F-014: page is Zitadel-branded |
| Dev-login the only path? | NO — Zitadel + dev-login both work | dev-login hard-blocked by APP_ENV |
| Rate limits per user/tenant — sane? | MOSTLY | F-008: chat surface lacks own bucket |
| Session lifetime / refresh tokens | OK | access 5min, refresh httponly+strict |
| CSRF on POST | OK | samesite=strict + PKCE state |
| CORS locked down | OK | F-019 |
| Multi-tenant isolation | **NO** | F-001, F-002 |
| PII / chat history retention | **NOT IMPLEMENTED** | F-023 |
| `llm_usage_log` populated | OK | F-022 |
| Backup / durability | **NOT VERIFIED** | F-021 |

---

## Required pre-beta actions

1. Fix F-001 (search-chunks tenant override) — cannot ship beta with this open.
2. Resolve F-002 (either add `dsm.tenant_id` or formally document news as
   global reference data).
3. Address F-003 (typed proxy route for relations/claims search).
4. Verify F-021 (backup/restore runbook).
5. Implement F-023 (retention policy + delete cron).
6. Run `pnpm audit` and `pip-audit` in CI; require zero high/critical CVEs.
7. Smoke-test dev-login disabled in `APP_ENV=production`.

After 1-7, cross-cut review with a second pair of eyes specifically on
multi-tenant boundaries before any second tenant is invited.
