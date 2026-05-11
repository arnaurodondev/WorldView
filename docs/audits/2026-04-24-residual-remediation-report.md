# Residual Remediation Report

**Date**: 2026-04-24 13:30 UTC
**Scope**: Closure of all residual items from `2026-04-24-qa-remediation-report.md`
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: **READY**

---

## Executive Summary

All 4 residual items from the QA remediation report have been addressed. ReadOnlyUnitOfWork (R27) has been implemented in 3 services (portfolio, rag-chat, alert). SEC-003 was verified as already resolved. KG-002 closure has been explicitly validated with 21 new tests. Market-ingestion E2E drift confirmed as infrastructure-dependent by design.

**Total new tests added: 28** (7 rag-chat UoW + 21 KG-002 claim-path)

---

## Residual Issue Resolution Matrix

| Issue | Severity | Fix Applied | Files Changed | Tests Added/Updated | Status |
|-------|----------|-------------|---------------|---------------------|--------|
| **ReadOnlyUnitOfWork — portfolio** | MAJOR | Added `ReadOnlyUnitOfWork` port + `SqlAlchemyReadOnlyUnitOfWork` infra + `ReadUoWDep`. 8 use cases + 6 route files switched to read-only type. | 14 files (port, infra, deps, 8 use cases, 6 routes) | Existing 508 tests pass (type-level enforcement via mypy) | **FIXED** |
| **ReadOnlyUnitOfWork — rag-chat** | MAJOR | Added `ReadOnlyRagUnitOfWorkPort` protocol + `ReadOnlyRagUnitOfWork` infra. `get_read_uow()` returns read-only type. `ListThreadsUseCase` + `GetThreadUseCase` switched. | 5 source + 1 test file | 7 new tests (5 UoW behavior + 2 port compliance) | **FIXED** |
| **ReadOnlyUnitOfWork — alert** | MAJOR | Added `ReadOnlyUnitOfWork` port + `SqlaReadOnlyUnitOfWork` infra + `ReadUoWDep`. `GET /alerts/pending` wired through read-only UoW. `read_uow_factory` registered in app lifespan. | 2 new + 5 modified files | 3 test files updated with `read_uow_factory` in `_make_app()` | **FIXED** |
| **SEC-003 (dev-login APP_ENV guard)** | MINOR | Already implemented: dual guard (APP_ENV=="production" → 403 + OIDC configured → 403). 3 existing tests cover all scenarios including edge case. | 0 (no changes needed) | 3 existing tests verified | **ALREADY RESOLVED** |
| **Market-ingestion E2E drift (19 fail)** | MINOR | Confirmed: 16 E2E + 3 platform QA tests require running infra stack (`docker-compose.test.yml --profile market-ingestion-test`). All 495 non-infra tests pass. By design. | 0 (no changes needed) | N/A | **DEFERRED — by design** |
| **KG-002 (no S7 claim consumer)** | MAJOR | Verified: raw_claims flows S6→S7 via enriched event. Added 21 targeted tests validating full claim pipeline: build → serialize → parse → materialize. | 3 test files | 21 new tests (6 S6 build + 6 S7 parse + 8 S7 materialize + 1 E2E consumer) | **CLOSED — validated** |

---

## Validation Summary

### Lint

| Check | Status |
|-------|--------|
| ruff check (5 services) | **PASS** — 0 errors |
| ruff format (5 services) | **PASS** — 492 files formatted |

### Unit Tests

| Service | Passed | Failed | Delta vs QA Report |
|---------|--------|--------|-------------------|
| portfolio | 508 | 0 | Stable (type-level R27 enforcement) |
| rag-chat | 442 | 0 | +7 (new ReadOnlyUoW tests) |
| alert | 369 | 0 | +3 fixture updates |
| nlp-pipeline | 525 | 0 | +6 (new claim build tests) |
| knowledge-graph | 615 | 0 | +15 (new claim parse/materialize tests) |
| content-ingestion | 544 | 0 | Baseline (no changes) |
| content-store | 300 | 0 | Baseline (no changes) |
| market-data | 438 | 0 | Baseline (no changes) |
| api-gateway | 62 | 0 | Baseline (no changes) |
| **Backend Total** | **3,803** | **0** | **+28 new tests** |

### Libraries

| Library Suite | Passed | Failed | Skipped |
|---------------|--------|--------|---------|
| common + contracts + storage + observability + ml-clients | 412 | 3 (Ollama infra) | 3 |

### Frontend

| Suite | Passed | Failed |
|-------|--------|--------|
| Vitest (20 files) | 288 | 0 |

---

## Remaining Deferred Items

| Item | Severity | Owner | Impact | Next Action |
|------|----------|-------|--------|-------------|
| Market-ingestion E2E tests (16+3) | MINOR | Infra | No functional impact — tests pass when stack is running via `make test-e2e` | Run in CI with `docker-compose.test.yml` profile |
| ReadOnlyUnitOfWork — knowledge-graph, nlp-pipeline, content-store | LOW | Architecture | These services either share `intelligence_db` (KG/NLP) or have no DB (content-store). UoW pattern not applicable without refactoring shared-DB architecture. | Address if/when services get dedicated databases |
| Ollama integration tests (3 failures) | LOW | Infra | Pre-existing — require running Ollama container | Run in CI with `--profile all` |

---

## Architecture Impact

The ReadOnlyUnitOfWork implementation enforces R27 at the **type level**:
- `ReadOnlyUnitOfWork` has NO `commit()` or `rollback()` methods
- mypy catches any attempt to mutate through a read-only UoW
- Read-only API routes use `ReadUoWDep`, mutating routes use `UoWDep`
- Read sessions use the read replica URL when configured (R23 compliance)

Services with R27 compliance after this wave: **6/6 applicable services**
- market-ingestion ✓ (pre-existing)
- content-ingestion ✓ (pre-existing)
- market-data ✓ (pre-existing)
- portfolio ✓ (this wave)
- rag-chat ✓ (this wave)
- alert ✓ (this wave)

---

## Final Verdict

### **READY**

All CRITICAL and MAJOR residual items resolved. SEC-003 verified as already fixed. KG-002 explicitly validated with 21 new tests. No regressions introduced. MINOR debt reduced (R27 coverage from 3/6 → 6/6 applicable services). Platform is certified with 0 unresolved CRITICAL/MAJOR findings.
