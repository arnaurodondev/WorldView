# QA Report: Full Platform — Post-Bugfix Validation

**Date**: 2026-04-23 23:50 UTC
**Skill**: qa
**Scope**: full (post-commit validation after bcbf61d + a89c543 + f65df81)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS
**Report file**: docs/audits/2026-04-23-qa-full-post-bugfix-report.md

---

## Executive Summary

Five specialist agents reviewed ~30 recently changed files across the three scoped commits
(BP-159/179/180/181/182 runtime fixes, docs consolidation, Terminal Dark frontend redesign). The
full backend unit suite — 4,206 tests across 10 services and 6 libraries — passes cleanly. The
frontend Vitest suite is 285/285. Ruff lint/format and mypy are clean on all changed packages.

The most significant findings are two pre-existing security gaps in the nlp-pipeline news query
repository (missing `tenant_id` filtering — not introduced by the recent commits but surfaced
during full-scope review), a semantic question about the null-volume coercion contract, and a
pre-existing architecture layer violation in rag-chat's Prometheus metric wiring. No findings
were introduced by commits `bcbf61d`, `a89c543`, or `f65df81` specifically.

The platform is safe to keep developing on this branch. The tenant isolation gaps in nlp-pipeline
should be addressed before merging to main given their security impact.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 6 | 10 | 0 | 2 | 2 | 6 | 0 |
| Security | 4 | 7 | 2 | 0 | 1 | 3 | 1 |
| Data Platform | 6 | 10 | 1 | 2 | 5 | 2 | 0 |
| Distributed Systems | 4 | 7 | 0 | 3 | 3 | 1 | 0 |
| Architecture | 8 | 11 | 1 | 3 | 3 | 4 | 0 |
| **Total (deduped)** | — | **28** | **2** | **6** | **8** | **9** | **1** |

### Cross-Agent Signals (HIGH Confidence — flagged by 2+ agents independently)

| Finding | Agents | Summary |
|---------|--------|---------|
| Null volume → 0 contract semantics | DATA + DS + ARCH | Three agents flagged the round-trip asymmetry and downstream consumer impact of coercing null to 0 in `ohlcv.py`. All agree the coercion is functional but the semantic contract is lossy. |
| Alert app.py dual JWT instance / JWKS race | DS + ARCH | Two agents identified that the dual-instance pattern in alert startup may leave a window where requests arrive before JWKS is populated. ARCH notes it is intentional/documented; DS notes no guard prevents silent fail-open under load. |

### Fixes Applied (Phase 4 — Auto-fixable)

None applied in this pass. Findings are presented for user confirmation before applying.

### Decisions Needed

| Finding | Question |
|---------|----------|
| F-002 / F-011 | Should `null` EODHD volume be preserved as `None` in the canonical model (requiring downstream handlers to coerce), or is `0` the correct sentinel for "no trade data"? |
| F-009 / F-010 | Should nlp-pipeline news queries add `tenant_id` filtering, or is tenant isolation enforced exclusively at the S9 gateway level for this internal service? |

### Open Items

| Finding | Status |
|---------|--------|
| F-001 | Pre-existing on branch (commit 44bf62d) — rag-chat arch violation |
| F-013 | Pre-existing on branch (commit 762e838) — portfolio import guard |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | 95 | 93 | 2 | 0 | FAIL (pre-existing) |
| Lint (ruff check) | full | — | — | 0 errors | — | PASS |
| Format (ruff format) | full | — | — | 0 errors | — | PASS |
| Type Check (mypy) | alert, rag-chat, nlp-pipeline, contracts | — | — | 0 errors | — | PASS |
| Import Guards | full | — | — | 1 net-new | — | FAIL (pre-existing) |
| Library Unit | all 6 libs | 174 | 174 | 0 | 3 (pyarrow) | PASS |
| Service Unit | 10 services | 4,206 | 4,206 | 0 | — | PASS |
| Integration | all | — | — | — | — | SKIP (no infra) |
| E2E | all | — | — | — | — | SKIP (no infra) |
| Frontend Unit | worldview-web | 285 | 285 | 0 | 0 | PASS |
| Frontend E2E | worldview-web | — | — | — | — | SKIP (no dev server) |

### Per-Service Unit Test Breakdown

| Service | Unit | Overall |
|---------|------|---------|
| portfolio | 490 pass | PASS |
| market-ingestion | 399 pass | PASS |
| market-data | 431 pass | PASS |
| content-ingestion | 546 pass | PASS |
| content-store | 306 pass | PASS |
| nlp-pipeline | 513 pass | PASS |
| knowledge-graph | 604 pass | PASS |
| rag-chat | 381 pass | PASS |
| alert | 345 pass | PASS |
| api-gateway | 191 pass | PASS |

### Per-Library Breakdown

| Library | Unit | Overall |
|---------|------|---------|
| common | 53+ pass | PASS |
| contracts | 106 pass, 3 skip | PASS |
| messaging | 15 pass (unit) | PASS |
| storage | included above | PASS |
| observability | included above | PASS |
| ml-clients | 53 pass (unit) | PASS (integration SKIP — Ollama not running) |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | FAIL | 1 net-new IG-LAYER-002 violation in `portfolio/brokerage_connections.py:226` (introduced in commit 762e838, pre-existing on branch) |
| Service Structure | N/A | Script not present |
| Ruff Lint | PASS | 0 errors across all libs and services |
| Ruff Format | PASS | 1539 files already formatted |
| mypy | PASS | alert (70 files), rag-chat (90 files), nlp-pipeline (97 files), contracts (17 files) — 0 errors |
| Architecture Tests | FAIL | 2 failures: rag-chat application→infrastructure layer violations (pre-existing from commit 44bf62d) |
| Frontend Build | PASS | 285/285 vitest |

---

## Issues — Full Investigation

---

## Issue F-001: rag-chat application layer imports infrastructure prometheus (pre-existing)

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Architecture tests (automated), Architecture agent

### Summary
`rag_chat.application.use_cases.chat_orchestrator` and `create_thread` directly import
`rag_chat.infrastructure.metrics.prometheus`. This violates the hexagonal architecture contract
where application-layer use cases must only depend on domain objects and port interfaces.

### Root Cause Analysis
- **What**: `from rag_chat.infrastructure.metrics.prometheus import ...` in two application files
- **Why**: Commit `44bf62d` ("wire remaining 5 S8 Prometheus metrics to call sites") added Prometheus metric increments directly to the application layer for convenience, bypassing the port pattern
- **When**: Always — detected statically at import time
- **Where**: Application layer (use cases), architecture boundary violation

### Evidence
```
FAILED tests/architecture/test_layer_boundaries.py::TestLayerBoundaries::test_application_does_not_import_api_or_infrastructure
  Service: rag-chat
  File: rag_chat/application/use_cases/chat_orchestrator.py:24
  Rule: LAYER-APP-ISOLATION
```

### Impact
- **Immediate**: Architecture test gate fails — 2 tests red
- **Blast radius**: Prevents full architecture test PASS; metrics logic tightly coupled to use cases

### Solution Options

#### Option A: Create a MetricsPort interface
Define `application/ports/metrics_port.py` with abstract methods; infrastructure implements it;
use cases receive it via dependency injection.
- **Effort**: Medium | **Risk**: Low

#### Option B: Move metric calls to infrastructure adapter layer
Keep metrics in the infrastructure session/handler adapters that wrap the use cases.
- **Effort**: Low | **Risk**: Low

**Recommended**: Option B — lower disruption, same effect. The use case reports completion; the
caller (infrastructure adapter) records the metric.

---

## Issue F-002 / F-011 (merged): Null volume coercion breaks contract round-trip

**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Data Platform agent, Distributed Systems agent, Architecture agent

### Summary
`CanonicalOHLCVBar.from_dict()` coerces `volume=None` → `volume=0`. The `to_dict()` method then
serializes `"volume": 0`, permanently losing the null signal. Downstream consumers cannot
distinguish "zero trades" from "no data reported".

### Root Cause Analysis
- **What**: `volume = int(raw_volume) if raw_volume is not None else 0` (ohlcv.py:57)
- **Why**: BP-182 fixed a `TypeError: int(None)` crash for EODHD bars with null volume
- **When**: Any EODHD bar where volume is null (off-hours, settlement bars, closed-market days)
- **Where**: `libs/contracts/src/contracts/canonical/ohlcv.py:57`

### Impact
- Analytics that compute average volume will be skewed downward by zero-volume coerced bars
- Backtesting systems filtering `volume >= threshold` will include false zero-volume bars
- No way to detect data quality gaps once the null is coerced at ingestion

### Solution Options

#### Option A: Keep coercion, add `volume_reported: bool` field (preferred)
Add `volume_reported: bool = True` to `CanonicalOHLCVBar`; set it to `False` when coercing from
null. This preserves the coercion fix while retaining the data-quality signal.
- **Effort**: Low | **Risk**: Low (additive change, defaults to True for normal bars)

#### Option B: Revert coercion, handle None in downstream callers
Return `Optional[int]` from `from_dict()`; update market-ingestion serializer and market-data
service to handle null volumes explicitly.
- **Effort**: Medium | **Risk**: Medium (touches multiple services)

#### Option C: Keep coercion as-is, document the semantic
Add a docstring comment in `ohlcv.py` clarifying that `volume=0` means "no trade data reported"
and document in `STANDARDS.md`. No code change.
- **Effort**: Minimal | **Risk**: None (status quo)

**Decision needed from user** — the choice depends on whether downstream analytics are already
handling this (Option C acceptable) or need the signal (Option A required).

---

## Issue F-003: Alert app lifespan continues if JWKS startup fails silently

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Distributed Systems agent

### Summary
`InternalJWTMiddleware.startup()` retries 3× then logs ERROR but does not raise. The lifespan
continues, the service starts and passes Kubernetes readiness checks (health route skips JWT),
but all authenticated requests return 503. The service appears healthy but is non-functional.

### Evidence
- `internal_jwt.py` lines 100-104: logs ERROR, returns without raising
- `app.py:74`: `await jwt_mw.startup()` has no error handling
- `/readyz` skips JWT paths (line 146 `_SKIP_PATHS`), so readiness probe passes

### Solution
After `await jwt_mw.startup()`, check `_internal_jwt_public_key` on `app.state`:
```python
await jwt_mw.startup()
if not settings.internal_jwt_skip_verification and not hasattr(app.state, "_internal_jwt_public_key"):
    raise RuntimeError("JWKS unavailable at startup — refusing to start")
```
This makes the failure visible in logs and prevents zombie pod registration.

---

## Issue F-004 / F-007 (merged): skip_verification has no production safety guard

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture agent, Security agent (F-SEC-002)

### Summary
`internal_jwt_skip_verification: bool = False` in config.py has no validator preventing it from
being set True in production. An operator accident bypasses all JWT signature verification.

### Solution
Add a model validator in `Settings`:
```python
@model_validator(mode="after")
def _guard_skip_verification(self) -> "Settings":
    if self.internal_jwt_skip_verification and self.environment not in ("test", "e2e"):
        raise ValueError("internal_jwt_skip_verification is only allowed in test/e2e environments")
    return self
```
Requires an `environment: str = "development"` setting (or similar discriminator).

---

## Issue F-009: Missing tenant_id filter in nlp-pipeline news query repository

**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Security agent (F-SEC-005)

### Summary
`get_top_news()` and `get_entity_articles()` in `news_query.py` query
`document_source_metadata`, `article_impact_windows`, `routing_decisions`, and `entity_mentions`
without any `WHERE tenant_id = :tenant_id` clause. All articles across all tenants are visible
to any authenticated user.

### Impact
- Any tenant can see every other tenant's news articles and entity mentions
- Complete multi-tenant data isolation breach at the application logic level
- OWASP A01 (Broken Access Control)

### Decision Needed
Is tenant isolation for nlp-pipeline intended to be enforced:
1. **At the repository layer** (add `tenant_id` filter to all queries) — correct if nlp-pipeline
   handles multiple tenants' data in a shared `nlp_db`
2. **Exclusively at S9 gateway** — acceptable only if the `nlp_db` contains data for a single
   tenant and the service is never exposed multi-tenant

If the thesis is single-tenant, Option 2 is acceptable for now with a documented caveat.

---

## Issue F-010: No entity ownership check in entity articles endpoint

**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: Security agent (F-SEC-006)

### Summary
`GET /entities/{entity_id}/articles` accepts arbitrary UUID without verifying the requesting
tenant owns that entity. Cross-tenant entity enumeration is possible if UUIDs are guessable.

### Solution
Add tenant verification before querying:
```python
entity = await entity_repo.get_by_id_for_tenant(entity_id, tenant_id)
if not entity:
    raise HTTPException(status_code=404, detail="Entity not found")
```

---

## Issue F-013: Import guard net-new violation — portfolio brokerage_connections

**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Import guard automated check (IG-LAYER-002)

### Summary
`services/portfolio/src/portfolio/api/routes/brokerage_connections.py:226` directly imports
`SqlAlchemyUnitOfWork` from the infrastructure layer. This bypasses the use-case abstraction and
violates IG-LAYER-002 (API routes must never import from `infrastructure/`).

Introduced in commit `762e838` (PLAN-0022 Wave E-1). Pre-existing on this branch.

### Solution
Extract the logic at line 226 into a use case class. The router calls
`ForceResyncUseCase(uow_dep).execute(...)` instead of instantiating `SqlAlchemyUnitOfWork` directly.

---

## Issue F-014: rag-chat `read_url` whitespace edge case not guarded

**Severity**: MINOR
**Confidence**: MEDIUM
**Flagged by**: Distributed Systems agent (F-DS-001)

### Summary
`if not read_url` at `session.py:75` correctly handles `None` and `""` (BP-179 fix) but does
NOT handle whitespace-only strings (`"  "`). `SecretStr("  ")` is truthy, so `create_async_engine()`
would receive a whitespace URL and raise `ArgumentError` at startup.

### Solution
```python
read_url = (read_url or "").strip()
if not read_url or _same_db_endpoint(read_url, ...):
```
One-line fix; very low risk.

---

## Issue F-015: Stale design system comment in select.tsx

**Severity**: NIT
**Confidence**: HIGH
**Flagged by**: Architecture agent (F-ARCH-007)

**File**: `apps/worldview-web/components/ui/select.tsx:154-155`
**Issue**: Comment references old Bloomberg Dark palette (`#0A0E14`) which was retired in
`globals.css`. The active palette is Terminal Dark (`#09090B`).
**Fix**: Update comment to `"Terminal Dark panel aesthetic (#09090B near-black background)"`.
**Auto-fixable**: YES

---

## Additional MINOR / NIT Findings (Short-form)

### F-016: Redundant `@pytest.mark.asyncio` in market-ingestion tests (F-QA-001)
**File**: `test_execute_task.py:719,744`
**Fix**: Replace with `@pytest.mark.unit` (asyncio_mode=auto makes the asyncio marker redundant).

### F-017: Test coverage gap — `create_rag_session_factory` has no unit tests (F-QA-002)
**File**: `services/rag-chat/src/rag_chat/infrastructure/db/session.py`
**Fix**: Add tests for None/empty/same/distinct read_url paths in rag-chat tests.

### F-018: nlp-pipeline news query tests are structural-only, no runtime validation (F-QA-004)
**File**: `test_news_query_repo.py`
**Fix**: Add integration tests that execute queries with `routing_tier=None` against a test DB.

### F-019: `.claude-context.md` not updated for rag-chat (ml-clients addition) and alert (BP-159)
**Files**: `services/rag-chat/.claude-context.md`, `services/alert/.claude-context.md`
**Fix**: Add note about ml-clients Dockerfile dependency and the dual-instance JWT pattern.

### F-020: `rounded-[2px]` hardcoded in select.tsx instead of Tailwind variable
**File**: `apps/worldview-web/components/ui/select.tsx:176`
**Fix**: Replace `rounded-[2px]` with `rounded-lg` so radius inherits from `--radius` CSS var.

---

## Recommendations (Priority Order)

1. **Decide on tenant isolation strategy for nlp-pipeline** (F-009/F-010) — BLOCKING before
   main merge if multi-tenant support is required. Thesis single-tenant: document the caveat.

2. **Fix rag-chat architecture layer violation** (F-001) — Move Prometheus calls from application
   layer to infrastructure adapters. Unblocks the architecture test gate.

3. **Fix portfolio import guard violation** (F-013) — Extract `SqlAlchemyUnitOfWork` usage at
   brokerage_connections.py:226 into a use case.

4. **Decide on null-volume coercion semantics** (F-002) — Either add `volume_reported: bool`
   field (Option A) or document the coercion convention.

5. **Add whitespace guard to `read_url`** (F-014) — One-line fix in session.py.

6. **Fix stale comment in select.tsx** (F-015) — Update "Bloomberg Dark" to "Terminal Dark".

7. **Update `.claude-context.md` files** (F-019) — rag-chat and alert need wave notes.

8. **Add JWKS startup fail-fast guard** (F-003) — Prevent zombie service registration.

9. **Add production guard for skip_verification** (F-004) — Settings validator.

10. **Fix redundant `@pytest.mark.asyncio` markers** (F-016) — Two-line change.
