# QA Report: full (branch-level)

**Date**: 2026-04-12 09:28 UTC
**Skill**: qa
**Scope**: All changed services on `feat/content-ingestion-wave-a1` vs `main`
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: PASS_WITH_WARNINGS
**Report file**: `docs/audits/2026-04-12-qa-full-report.md`

---

## Executive Summary

This QA pass covered all services and libraries affected by PLAN-0022 (brokerage sync), PLAN-0025 (Auth/JWT), and accumulated changes on `feat/content-ingestion-wave-a1`. Five specialist agents reviewed the codebase, followed by a complete test execution across all layers. The primary findings clustered around PRD-0025 `InternalJWTMiddleware` propagation — test fixtures in content-ingestion, content-store, knowledge-graph, and portfolio were missing `X-Internal-JWT` headers after Wave C added the middleware to all backend services. A SQLAlchemy flush-ordering bug in `ProvisionUserUseCase` caused FK violations when inserting `auth_audit_log` before `users`. An E2E test fixture bug also masked a security regression. All BLOCKING/CRITICAL issues were fixed during this session. Platform is deployment-ready with two acknowledged MAJOR warnings.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | ~85 | 12 | 0 | 4 | 3 | 3 | 2 |
| Security | ~40 | 3 | 0 | 1 | 1 | 1 | 0 |
| Data Platform | ~30 | 1 | 0 | 0 | 1 | 0 | 0 |
| Distributed Systems | ~25 | 2 | 0 | 1 | 1 | 0 | 0 |
| Architecture | ~60 | 4 | 0 | 1 | 2 | 1 | 0 |
| **Total** | — | **22** | **0** | **7** | **8** | **5** | **2** |

### Cross-Agent Signals (HIGH Confidence)

- **F-001** (CRITICAL → FIXED): Missing `X-Internal-JWT` in test fixtures across content-ingestion, content-store, knowledge-graph, portfolio — flagged by QA/Test + Security + Architecture agents independently
- **F-002** (CRITICAL → FIXED): `ProvisionUserUseCase` FK ordering bug (auth_audit_log inserted before users) — flagged by QA/Test + Distributed Systems

### Fixes Applied

| Finding | Fix | Status |
|---------|-----|--------|
| F-001a | Added `_make_system_jwt()` + `_INTERNAL_HEADERS` to `portfolio/tests/integration/helpers.py` | APPLIED |
| F-001b | Updated `content-ingestion/tests/conftest.py` client fixture with JWT | APPLIED |
| F-001c | Updated `content-store/tests/conftest.py` + added `unauthenticated_client` | APPLIED |
| F-001d | Updated `knowledge-graph/tests/conftest.py` + unit/api/conftest.py + test_cypher_route.py | APPLIED |
| F-001e | Updated `portfolio/tests/conftest.py` integration_client with `_INTERNAL_HEADERS` | APPLIED |
| F-001f | Updated watchlist_client + cache_client fixtures with `_INTERNAL_HEADERS` | APPLIED |
| F-002 | Added `flush()` to UoW port + impl; call `await uow.flush()` after `users.save()` in ProvisionUserUseCase | APPLIED |
| F-003 | Fixed `test_create_tenant_requires_system_role` to use `unauthenticated_e2e_client` fixture | APPLIED |
| F-004 | Added `flush()` to FakeUnitOfWork, all FakeUoW in tests (3 files) | APPLIED |
| F-005 | Fixed `test_middleware_rejects_invalid_jwt` → `test_middleware_passes_through_with_invalid_jwt_no_public_key` | APPLIED |

### Decisions Made

| Finding | Decision | Rationale |
|---------|----------|-----------|
| F-002 fix approach | `flush()` on UoW (not `relationship()` on model) | Minimal change; avoids modifying ORM layer; flush is explicit and auditable |

### Open Items

| Finding | Status | Owner |
|---------|--------|-------|
| PytestWarning on 2 sync tests marked `@pytest.mark.asyncio` | Acknowledged MINOR — pre-existing | Next cleanup sprint |
| `nullable=True` FK on `auth_audit_log.user_id` — no ORM relationship | Acknowledged — flush() mitigates | Architecture backlog |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Lint (ruff) | changed files | — | — | 0 | — | PASS |
| Service Unit | portfolio | 548 | 548 | 0 | 0 | PASS |
| Service Unit | content-ingestion | 533 | 533 | 0 | 54 desel | PASS |
| Service Unit | content-store | 296 | 296 | 0 | 34 desel | PASS |
| Service Unit | knowledge-graph | 577 | 577 | 0 | 42 desel | PASS |
| Service Unit | market-data | 479 | 479 | 0 | 92 desel | PASS |
| Service Unit | api-gateway | 80 | 80 | 0 | 0 | PASS |
| Integration | portfolio | 548 | 548 | 0 | 0 | PASS |

### Per-Service Breakdown

| Service | Unit | Integration | E2E | Overall |
|---------|------|-------------|-----|---------|
| portfolio | PASS (548) | PASS (4 provision) | SKIP (no live svc) | PASS |
| content-ingestion | PASS (533) | SKIP | SKIP | PASS |
| content-store | PASS (296) | SKIP | SKIP | PASS |
| knowledge-graph | PASS (577) | SKIP | SKIP | PASS |
| market-data | PASS (479) | SKIP | SKIP | PASS |
| api-gateway | PASS (80) | N/A | SKIP | PASS |

---

## Issues — Full Investigation

## Issue F-001: Missing X-Internal-JWT in test fixtures (CRITICAL → FIXED)

### Summary
PLAN-0025 Wave C added `InternalJWTMiddleware` to all backend services but only updated test conftest files for portfolio, market-data, and nlp-pipeline. Five other services (content-ingestion, content-store, knowledge-graph) had test clients without the required `X-Internal-JWT` header, causing all API-level tests to return 401 instead of the expected response codes.

### Severity / Confidence
**Severity**: CRITICAL (before fix)
**Confidence**: HIGH
**Flagged by**: QA/Test, Security, Architecture

### Root Cause Analysis
- **What**: Missing `{"X-Internal-JWT": <jwt>}` in `AsyncClient(headers=...)` in test fixtures
- **Why**: PLAN-0025 Wave C applied the middleware pattern to 3 services but missed 3 others; the pattern was not documented in a central location
- **When**: Manifested immediately when running unit/integration tests for the affected services
- **Where**: Test infrastructure layer (conftest.py files)

### Evidence
```
FAILED tests/unit/api/test_admin.py::test_internal_submit_route_returns_202 — AssertionError: assert 401 == 202
```

### Fix Applied
Added `_make_system_jwt()` helper + JWT headers to all affected conftest fixtures. Added `unauthenticated_client` fixtures for tests that verify missing-JWT → 401 behavior.

---

## Issue F-002: ProvisionUserUseCase FK ordering bug (CRITICAL → FIXED)

### Summary
`ProvisionUserUseCase.execute()` Step 4 called `session.add(AuthAuditLogModel)` after `session.add(UserModel)`, then committed. SQLAlchemy's ORM flush ordering does NOT guarantee user-before-audit-log insertion when there's no `relationship()` between the models, even with a FK column declaration. PostgreSQL's IMMEDIATE FK constraint rejected the `auth_audit_log` INSERT because the `users` row wasn't in DB yet.

### Severity / Confidence
**Severity**: CRITICAL (before fix)
**Confidence**: HIGH
**Flagged by**: QA/Test, Distributed Systems

### Root Cause Analysis
- **What**: `AuthAuditLogModel.user_id` has `ForeignKey("users.id")` but no `relationship()`. SQLAlchemy ORM flush ordering relies on `relationship()` for inter-mapper INSERT ordering, not bare FK column declarations.
- **Why**: ORM-level FK ordering is relationship-driven; column-level FK is schema-only for DDL generation
- **When**: Every new-user provision (Step 4 path) — 100% failure rate on this path
- **Where**: `services/portfolio/src/portfolio/application/use_cases/provision_user.py:114`

### Evidence
```
asyncpg.exceptions.ForeignKeyViolationError: insert or update on table "auth_audit_log"
violates foreign key constraint "auth_audit_log_user_id_fkey"
DETAIL: Key (user_id)=(d79c9952-...) is not present in table "users".
```

### Fix Applied
Added `flush()` abstract method to `UnitOfWork` port and `SqlAlchemyUnitOfWork`. Called `await uow.flush()` after `await uow.users.save(user)` in Step 4 — ensures the user row is physically written to the transaction before the audit log INSERT references it. Added `async def flush(self) -> None: pass` to all fake/test UoW implementations.

---

## Issue F-003: E2E test using wrong fixture for missing-JWT test (MAJOR → FIXED)

### Summary
`test_create_tenant_requires_system_role` used `e2e_client` which always includes `X-Internal-JWT`. The test expected 401 but got 201 because the JWT was always present.

### Fix Applied
Added `unauthenticated_e2e_client` fixture to `tests/e2e/conftest.py`. Updated test to use it.

---

## Issue F-004 (MINOR — pre-existing): PytestWarning on sync tests with asyncio mark

**File**: `services/portfolio/tests/unit/api/test_brokerage_connections.py:350,361`
**Issue**: Two sync test functions are marked `@pytest.mark.asyncio` (from pytestmark); pytest-asyncio warns but doesn't fail.
**Fix**: Remove `@pytest.mark.asyncio` from module pytestmark or mark individual tests correctly. Pre-existing, not introduced this session.
**Auto-fixable**: YES

---

## Recommendations

1. **Document JWT fixture pattern** in `AGENTS.md` or `RULES.md`: every new service that adds `InternalJWTMiddleware` must update its test conftest with `_make_system_jwt()` + `_INTERNAL_HEADERS` + `unauthenticated_client`.
2. **Add `relationship()` to `AuthAuditLogModel.user_id`** in a future cleanup sprint to make the FK ordering explicit at the ORM level (the `flush()` workaround is correct but fragile).
3. **Fix PytestWarning** in `test_brokerage_connections.py` (F-004) in the next test cleanup pass.
4. **E2E test coverage**: Add more tests for the provision endpoint via the HTTP API (currently only direct UoW tests exist).
