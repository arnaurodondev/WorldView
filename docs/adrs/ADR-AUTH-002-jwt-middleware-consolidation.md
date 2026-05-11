# ADR-AUTH-002: InternalJWTMiddleware Shared Library Extraction

**Status**: Proposed
**Date**: 2026-04-24
**Context**: The `InternalJWTMiddleware` class is copy-pasted identically across all 9 backend services. Every security fix (F-003 crash-on-failure, F-007 skip_verification guard, F-012 JTI replay, readyz JWKS check) must be applied 9 times, creating maintenance burden and drift risk.

---

## Decision

Extract `InternalJWTMiddleware` into a shared library `libs/auth-middleware` that all 9 services import.

---

## Current State

9 identical files, each ~250 lines:
- `services/{alert,content-ingestion,content-store,knowledge-graph,market-data,market-ingestion,nlp-pipeline,portfolio,rag-chat}/src/*/infrastructure/middleware/internal_jwt.py`

All files share:
- RS256 JWKS key fetching with 3-retry startup
- Background key refresh (hourly)
- `skip_verification` flag for E2E tests
- JTI replay detection via Valkey
- Skip paths for health/metrics
- WebSocket token support via query param

No service-specific divergence exists today. All differences are the import path for `observability.get_logger`.

---

## Proposed Migration

### Wave 1: Create shared library
- Create `libs/auth-middleware/` with `pyproject.toml`, `src/auth_middleware/`, `py.typed`
- Move `InternalJWTMiddleware` to `auth_middleware.middleware`
- Export helper `create_readyz_jwks_check()` for health routes
- Add unit tests in `libs/auth-middleware/tests/`

### Wave 2: Migrate services (mechanical)
- For each of the 9 services:
  1. Add `auth-middleware` to `pyproject.toml` dependencies
  2. Replace `from <pkg>.infrastructure.middleware.internal_jwt import InternalJWTMiddleware` with `from auth_middleware import InternalJWTMiddleware`
  3. Delete the service-local `internal_jwt.py`
  4. Update test imports
  5. Verify all tests pass

### Wave 3: Cleanup
- Remove 9 duplicate files
- Update `.claude-context.md` for each service

---

## Acceptance Criteria

- [ ] `libs/auth-middleware/` exists with full test coverage
- [ ] All 9 services import from the shared library
- [ ] Zero duplicate `internal_jwt.py` files remain
- [ ] All 3,869+ unit tests pass
- [ ] Architecture tests pass (0 failures)
- [ ] ruff + mypy clean

## Risk Assessment

- **Blast radius**: HIGH (all 9 services change imports)
- **Reversibility**: HIGH (can revert to local files at any time)
- **Test safety**: HIGH (purely mechanical import path changes)
- **Runtime risk**: NONE (identical code, different import path)

## Timeline

Recommended: Next sprint (not blocking current merge). The duplication is a maintenance risk, not a correctness risk. All 9 files are currently identical and tested.

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| Keep duplicated files | Maintenance burden scales with every future JWT change |
| Use a mixin/base class | Over-engineered — the middleware is a complete unit |
| Symlinks | Fragile, confusing tooling, IDE issues |

---

## References

- F-003: JWKS crash-on-failure (applied 9 times)
- F-007: skip_verification production guard (applied 9 times)
- F-012: JTI replay detection (applied 9 times)
- PRD-0025: Auth Foundation
