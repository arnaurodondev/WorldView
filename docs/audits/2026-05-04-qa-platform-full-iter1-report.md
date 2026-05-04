# QA Report: Full Platform Pass — Iteration 1

**Date**: 2026-05-04
**Skill**: qa
**Scope**: Full platform — PLAN-0069, PLAN-0070, KG pipeline, data ingestion, API gateway, frontend
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: FAIL (1 BLOCKING test failure + 5 CRITICAL findings)
**Report file**: docs/audits/2026-05-04-qa-platform-full-iter1-report.md

---

## Executive Summary

Five specialist agents reviewed the full worldview platform following completion of PLAN-0069 (UI professional polish) and PLAN-0070 (S9 contract spine + BFF completion). PLAN-0069 is **fully clean — all 4 waves PASS**. PLAN-0070 is largely sound but has 3 critical security regressions on S9 authentication and 2 critical BFF issues. The knowledge-graph service has 1 BLOCKING test failure due to a stale mock after the batch-embed refactor and 1 CRITICAL data-integrity issue on contradiction detection (sentinel UUID FKs). The frontend has 1 CRITICAL optimistic-update cache key mismatch and 14 Bloomberg-standard violations. Platform is offline (0/0 healthy containers) so live tests were skipped; all findings are code-audit driven.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA-1 Static Analysis | ~200 | 5 | 1 | 0 | 0 | 3 | 1 |
| QA-2 API Gateway | ~10 | 23 | 0 | 3 | 11 | 4 | 5 |
| QA-3 KG + Ingestion | ~30 | 14 | 0 | 1 | 7 | 5 | 1 |
| QA-5 Frontend | ~60 | 19 | 0 | 1 | 9 | 6 | 3 |
| QA-7 Security + Systemic | ~40 | 12 | 0 | 0 | 5 | 4 | 3 |
| **Total** | — | **73** | **1** | **5** | **32** | **22** | **13** |

Note: QA-7 initially classified `confidence.py mark_processed before commit` as BLOCKING. After verification, `mark_processed` uses the same SQLAlchemy session and is committed atomically — this is NOT a bug. Downgraded to no-action-required.

### Cross-Agent Signals (HIGH Confidence)
- Auth guards missing on 6 S9 routes — independently confirmed by QA-2 and QA-7
- `animate-pulse` in data surfaces — QA-5 found 3+ instances post-PLAN-0069 wave D
- Inline queryKey arrays still present at 135 sites — QA-5 and QA-1 (ESLint warnings)

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Lint (ruff) | full | — | — | 6 errors (0013 migration only) | — | WARN |
| Format (ruff) | full | — | — | 1 file | — | WARN |
| Type Check (mypy) | api-gateway | 27 files | ✓ | 0 | — | PASS |
| api-gateway unit | 324 | 324 | 0 | — | PASS |
| nlp-pipeline unit | 706 | 706 | 0 | 46 skip | PASS |
| knowledge-graph unit | 807 | **806** | **1** | — | **FAIL** |
| Frontend typecheck | — | ✓ | 0 | — | PASS |
| Frontend lint | — | — | 0 errors | 119 warnings | PASS (warnings) |
| Frontend unit | 1708 | 1708 | 0 | — | PASS |
| Integration/E2E | — | — | — | SKIP (platform offline) | SKIP |

### Failing Test
`services/knowledge-graph/tests/unit/infrastructure/test_definition_refresh.py::TestDefinitionRefreshWorkerPhasedRun::test_run_closes_session_before_embed` — **TypeError: `_embed_and_record()` missing 1 required positional argument: `'entity_id'`**. Production refactored to single-arg batch signature; test mock not updated.

---

## PLAN Status

| Plan | Status | Notes |
|------|--------|-------|
| PLAN-0069 UI Polish | **ALL 4 WAVES PASS** | All 18 pre-flight items verified in code |
| PLAN-0070 S9 Spine + BFF | PARTIAL — see findings | 3 CRITICAL auth gaps; timeouts partial |

---

## Container Status

Platform offline (0 healthy containers). All live integration tests skipped. Docker Compose not started.

---

## Issues — Full Investigation

### Finding F-001 (BLOCKING)
**KG test broken — `_embed_and_record` mock signature mismatch**

**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA-1

**Root Cause**: `DefinitionRefreshWorker` was refactored to call `await self._llm.embed(chunk_inputs)` with a single list argument (batch API). The test `test_run_closes_session_before_embed` still defines the mock as `async def _embed_and_record(inp, entity_id)` — a two-argument signature from the old per-entity API. Python raises `TypeError` when the production code calls the mock with 1 argument.

**Evidence**:
```
FAILED tests/unit/infrastructure/test_definition_refresh.py::test_run_closes_session_before_embed
TypeError: _embed_and_record() missing 1 required positional argument: 'entity_id'
```

**Fix**:
```python
# Before (test_definition_refresh.py:300)
async def _embed_and_record(inp, entity_id):

# After
async def _embed_and_record(inp):
```

**Verification**: `cd services/knowledge-graph && python -m pytest tests/unit/infrastructure/test_definition_refresh.py -v`

---

### Finding F-003 (CRITICAL)
**`GET /v1/companies/{company_id}/overview` has no authentication guard**

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA-2, QA-7

**Root Cause**: `proxy.py:114` — the `company_overview` route does not check `request.state.user`. Every other composition endpoint (`/page-bundle`, `/market/heatmap`, `/portfolio/bundle`, `/dashboard/snapshot`) includes `if not getattr(request.state, "user", None): raise HTTPException(401)`. `_auth_headers(request)` returns `{}` when no user, so unauthenticated requests reach all 5 downstream S3 calls with no JWT — exposing instrument data, OHLCV history, and fundamentals without authentication.

**Fix**: Add auth check as first statement in `company_overview`:
```python
if getattr(request.state, "user", None) is None:
    raise HTTPException(status_code=401, detail="Authentication required")
```

**Blast radius**: All instrument detail page loads from unauthenticated clients.

---

### Finding F-004 (CRITICAL)
**Thread CRUD routes have no authentication guards (6 routes)**

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA-2

**Root Cause**: `proxy.py:241,255,268,280,292` — `create_thread`, `list_threads`, `get_thread`, `delete_thread`, `update_thread` all lack auth checks. An unauthenticated caller can create threads (attributable to no tenant), list any user's threads (if S8 doesn't enforce it), and delete/rename threads. `POST /v1/chat` (line 193) correctly checks auth but the thread management routes don't.

**Fix**: Add the standard guard to all 5 routes:
```python
if getattr(request.state, "user", None) is None:
    raise HTTPException(status_code=401, detail="Authentication required")
```

---

### Finding F-005 (CRITICAL)
**Email preferences routes have no authentication guards**

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA-2

**Root Cause**: `proxy.py:316,332` — `get_email_preferences` and `update_email_preferences` pass `X-Tenant-Id`/`X-User-Id` headers to S10 derived from the JWT — but if no JWT is present, `_auth_headers` returns `{}`. An unauthenticated request reaches S10 with no headers. S10's InternalJWTMiddleware should reject it, but the gateway should fail fast.

**Fix**: Add auth guards to both routes.

---

### Finding F-006 (CRITICAL)
**Contradiction detection writes dangling FK rows with sentinel UUIDs**

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA-3

**Root Cause**: `enriched_consumer.py:321-334` — Block 12b (contradiction detection) in the hot-path consumer calls `detect_and_record_contradictions()` with `raw_evidence_id=_sentinel_uuid()` and `claim_id=_sentinel_uuid()`. These are freshly-minted random UUIDs with no corresponding rows in `relation_evidence_raw` or `claims`. `insert_link()` uses `ON CONFLICT DO NOTHING`, so no error surfaces — but `relation_contradiction_links` accumulates rows with dangling FKs. Every contradiction detected via the hot path is written with fake `claim_id` values that don't match any materialized claim.

**Evidence**: `materialize_graph()` returns a `MaterializationSummary` but no per-claim IDs, so the consumer has no way to pass real IDs.

**Fix**: `materialize_graph()` must return `(claim_id, evidence_id)` pairs for each inserted claim. Pass the real IDs to contradiction detection. Until that structural change is made, skip contradiction detection in the hot path (it runs in the batch worker anyway).

---

### Finding F-007 (CRITICAL)
**Chat rename optimistic update writes to wrong cache key**

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA-5

**Root Cause**: `chat/page.tsx:374,378,391` — `handleRenameThread` reads/writes TanStack Query cache at `["threads", accessToken]` — the pre-migration legacy key. The thread-list query now uses `qk.chat.threads()` = `["chat", "threads"]`. The `getQueryData` call returns `undefined` (cache miss on wrong key), so the optimistic update is silently a no-op. The rollback also writes to the wrong key. Users see no title change during rename until `refetchThreads()` resolves.

**Fix**:
```typescript
// Before
queryClient.getQueryData<Thread[]>(["threads", accessToken])
queryClient.setQueryData<Thread[]>(["threads", accessToken], ...)

// After
queryClient.getQueryData<Thread[]>(qk.chat.threads())
queryClient.setQueryData<Thread[]>(qk.chat.threads(), ...)
```

---

## MAJOR Issues (abbreviated)

### F-008 — `get_company_overview()` missing `asyncio.wait_for` (PLAN-0070 gap)
**File**: `services/api-gateway/src/api_gateway/clients.py:171`
**Issue**: The overview endpoint fans out to 5 downstream calls with no outer timeout budget. Only the httpx 30s timeout is the backstop (BP-235 applies).
**Fix**: Wrap gather in `asyncio.wait_for(_compose(), timeout=15.0)` mirroring `get_market_heatmap`.

### F-009 — `get_top_movers()` missing `asyncio.wait_for`
**File**: `services/api-gateway/src/api_gateway/clients.py:957`
**Fix**: Wrap with `asyncio.wait_for(..., timeout=10.0)`.

### F-010 — Instrument bundle `_safe` wrappers swallow exceptions silently
**File**: `services/api-gateway/src/api_gateway/clients.py:441`
**Fix**: Add `logger.warning("instrument_bundle_leg_failed", leg=path, exc_info=True)` before each `return None`.

### F-011 — Portfolio bundle `_safe` wrapper swallows exceptions silently
**File**: `services/api-gateway/src/api_gateway/clients.py:556`
**Fix**: Same as F-010 for portfolio legs.

### F-012 — `batch_ohlcv` uses `return_exceptions=False`
**File**: `services/api-gateway/src/api_gateway/routes/proxy.py:974`
**Issue**: A single unhandled `RuntimeError` or `ssl.SSLError` from any symbol would fail the entire batch (10-15 mini-charts wiped).
**Fix**: Switch to `return_exceptions=True` with isinstance-based error handling in result loop.

### F-013 — Admin recompute endpoint has no role check
**File**: `services/api-gateway/src/api_gateway/routes/proxy.py:2259`
**Fix**: Add `if user.get("role") != "admin": raise HTTPException(403)`.

### F-014 — Migration 0013 seeds embeddings via Ollama, runtime uses DeepInfra
**File**: `services/intelligence-migrations/alembic/versions/0013_seed_relation_type_registry_embeddings.py:52`
**Issue**: If Ollama is down at migration time, embeddings remain NULL and ANN soft-map (Step 2) is permanently bypassed.

### F-015 — `FundamentalsRefreshWorker` uses HS256 dev JWT (fails RS256 in production)
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py:150`
**Issue**: Market-data validates RS256 via JWKS in production. Every fundamentals HTTP call returns 401 silently in prod.

### F-016 — AGE sync held in one monolithic transaction
**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py:199`
**Fix**: Add intermediate commits after each of entities/relations/temporal_events sync.

### F-017 — N+1 query in `GetEntityGraphUseCase`
**File**: `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py:57`
**Fix**: Replace per-entity `get()` loop with `get_batch()`.

### F-018 — `RecentAlerts` widget missing `isError` handling
**File**: `apps/worldview-web/components/dashboard/RecentAlerts.tsx:40`
**Fix**: Destructure `isError`, render error row with retry.

### F-019/F-020 — `animate-pulse` on data skeletons
**Files**: `components/dashboard/MarketHeatmap.tsx:60`, `components/ui/squarified-treemap.tsx:146`
**Fix**: Remove `animate-pulse`, static skeleton only.

### F-021 — `text-sm` on live price data
**File**: `apps/worldview-web/components/instrument/LiveQuoteBadge.tsx:162,165`
**Fix**: Change to `text-[11px]`.

### F-022 — `text-sm` on chart error text
**File**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:1124`
**Fix**: Change to `text-[11px]`.

### F-023 — `text-sm` on brokerage list
**File**: `apps/worldview-web/components/brokerage/ConnectedBrokeragesList.tsx:200,365`
**Fix**: Change to `text-[11px]`.

### F-024 — Rate limit `EXPIRE` resets TTL on every request (window never fires for sustained streams)
**File**: `services/api-gateway/src/api_gateway/middleware.py:374`
**Issue**: `await valkey.expire(key, self.window_seconds)` always overwrites TTL. A sustained 1-req/sec stream never triggers the limit because the window resets each time.
**Fix**: Only set TTL when key is new: `if current == 1: await valkey.expire(key, self.window_seconds)`.

### F-025 — JWKS startup fetch has no retry logic
**File**: `services/api-gateway/src/api_gateway/app.py:99`
**Fix**: Add 3-attempt exponential backoff before raising/falling back.

### F-026 — Path parameters unsanitized (path traversal risk)
**File**: `services/api-gateway/src/api_gateway/routes/proxy.py:837` et al.
**Issue**: `company_id`, `instrument_id`, `entity_id` passed directly into downstream URL paths with no UUID/regex validation.
**Fix**: Apply UUID validation pattern (already used for `portfolio_id` at line 1943) to all forwarded ID params.

### F-027 — `AskAiPanel` SSE fetch missing `AbortController`
**File**: `apps/worldview-web/components/shell/AskAiPanel.tsx:119`
**Fix**: Add `AbortController`, pass `signal`, abort on unmount.

### F-028 — Unicode arrows in `MorningBriefCard` buttons
**File**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:344,353`
**Fix**: Replace `→`/`↑` with Lucide icons or remove.

---

## MINOR Issues (abbreviated)

| ID | File | Issue | Auto-fix |
|----|------|-------|----------|
| F-029 | `0013_seed_relation_type_registry_embeddings.py:64,71` | S310 urllib.request audit warning | NO (noqa) |
| F-030 | `0013_seed_relation_type_registry_embeddings.py:90,93,126,128` | T201 bare print() | NO (noqa) |
| F-031 | `0013_seed_relation_type_registry_embeddings.py` | ruff format drift | YES |
| F-032 | `ForceUpdateBanner.test.tsx:42-78` | act() warnings in timer tests | NO |
| F-033 | `alerts/page.tsx:424,532` | `text-xs` on pagination fallbacks | YES |
| F-034 | `components/instrument/EntityGraph.tsx:544` | `text-sm` on empty state | YES |
| F-035 | `app/admin/feedback/page.tsx:154` | `animate-pulse` on admin skeleton | YES |
| F-036 | `components/dashboard/RecentAlerts.tsx:126` | `hover:underline` on "Alerts page" link | YES |
| F-037 | `components/dashboard/PortfolioSummary.tsx:166` | `hover:underline` on portfolio link | YES |
| F-038 | `components/instrument/OverviewSidebar.tsx:564` | `hover:underline` on "View all" | YES |
| F-039 | `components/instrument/InstrumentTopNews.tsx:172` | `hover:underline` on news link | YES |
| F-040 | `middleware.py:136` | `except (jwt.InvalidTokenError, Exception): pass` should be split | YES |
| F-041 | `middleware.py:200` | Valkey cache miss fully silent | YES |
| F-042 | `clients.py:254` | KG warning missing `exc_info=True` | YES |
| F-043 | `proxy.py:2629` | `/news/relevant` missing `response_model` | NO |
| F-044 | `FundamentalsTab.tsx / WorkspaceBriefWidget.tsx` | `["morning-brief"]` inline key | YES |
| F-045 | `usePortfolioData.ts:448` | `["holdings-quotes"]` inline key | YES |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| ruff lint | WARN | 6 errors in untracked 0013 migration file only |
| ruff format | WARN | 1 file (same migration) |
| mypy api-gateway | PASS | 0 errors |
| Import Guards | N/A | Script not found |
| Service Structure | N/A | Script not found |
| Doc Freshness | PASS | No new APIs introduced |
| Security Scan | WARN | Auth gaps F-003/F-004/F-005 |

---

## Recommendations (Priority-Ordered)

1. **Fix F-001** (BLOCKING): Update `test_definition_refresh.py` mock — 1-line change, unblocks CI
2. **Fix F-003/F-004/F-005** (CRITICAL): Add auth guards to 6 unauthenticated S9 routes
3. **Fix F-007** (CRITICAL): Update chat rename optimistic update to use `qk.chat.threads()`
4. **Fix F-006** (CRITICAL): Disable hot-path contradiction detection until materialize_graph returns real claim IDs (complex structural fix)
5. **Fix F-024** (MAJOR): Rate limit TTL — 1-line conditional change, prevents window bypass
6. **Fix F-010/F-011** (MAJOR): Add logging to instrument/portfolio bundle `_safe` wrappers
7. **Fix F-018/F-019/F-020/F-021/F-022/F-023** (MAJOR): Bloomberg standard violations (easy frontend fixes)
8. **Fix F-008/F-009** (MAJOR): Add asyncio.wait_for to overview and top-movers
9. **Fix F-015** (MAJOR): FundamentalsRefreshWorker RS256 JWT for production
10. **Wave 2**: F-012 return_exceptions, F-016 AGE transactions, F-017 N+1, F-025 JWKS retry, F-026 path validation

---

## New Bug Patterns

| ID | Pattern | File | Description |
|----|---------|------|-------------|
| BP-350 | Test mock signature stale after batch-API refactor | test_definition_refresh.py | After refactoring `embed(inp, entity_id)` → `embed(chunk_inputs)`, mock kept old 2-arg signature |
| BP-351 | Rate limit TTL window bypass via unconditional EXPIRE | middleware.py | `expire()` always resets TTL; only set when `current == 1` |
| BP-352 | Auth guard missing on composition endpoints with make_headers factory | proxy.py | Routes using `_auth_headers()` factory but no explicit `user is None` check |
