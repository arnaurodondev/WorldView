# Investigation Report: Brokerage Connection POST Returns 503

**Date**: 2026-04-28
**Investigator**: Claude (investigation skill)
**Severity**: HIGH (brokerage connection initiation blocked for all users after dev rebuild)
**Status**: Root cause identified and fixed ✓

---

## 1. Issue Summary

`POST /api/v1/brokerage-connections` returned `503 Service Unavailable` after `make dev-rebuild`. The portfolio service was reachable and healthy, but the SnapTrade registration step was throwing an unhandled exception.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `snaptrade_user_already_registered` warning | `docker logs worldview-portfolio-1` | SnapTrade returned HTTP 409 — user already exists in the external service |
| `ApiException` then 503 | Portfolio access log | Unhandled exception → domain_error_handler → 503 |
| `BrokerageApiError: 503` mapping | `portfolio/api/error_mapping.py:36` | All `BrokerageApiError` instances map to 503 regardless of recoverable/unrecoverable |
| Fresh DB (no brokerage_connections rows) | After `make dev-rebuild` | Seed script doesn't create brokerage connections; only portfolio/watchlist data |
| SnapTrade persistent state | External API fact | SnapTrade maintains user registrations independently of the local DB |

---

## 3. Execution Path Analysis

```
1. POST /api/v1/brokerage-connections → S9 api-gateway → portfolio /api/v1/brokerage-connections
2. Route calls InitiateBrokerageConnectionUseCase.execute()
3. ToS check: passes (snaptrade_tos_accepted=True)
4. Portfolio ownership check: passes (demo portfolio exists via seed)
5. brokerage_client.register_user("01900000-...-0010") →
   └─ SnapTradeClient.register_user() → snaptrade SDK call
   └─ SnapTrade returns HTTP 409 (user already registered from before DB wipe)
   └─ SnapTradeClient raises BrokerageApiError(reason="already_exists")
6. InitiateBrokerageConnectionUseCase does NOT catch BrokerageApiError → propagates
7. FastAPI exception handler (domain_error_handler) catches DomainError
8. error_mapping: BrokerageApiError → HTTP 503
9. S9 returns 503 to frontend
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | SnapTrade user already registered from before DB wipe → unhandled 409 | CONFIRMED | `docker logs` shows `snaptrade_user_already_registered` warning + 503 |
| H-2 | Portfolio service down or DB unreachable | REFUTED | `GET /healthz` returns OK; other portfolio routes work fine |
| H-3 | S9 proxy misconfiguration | REFUTED | S9 correctly proxies the request; 503 comes from portfolio (Server: uvicorn) |

---

## 5. Root Cause

**Statement**: `InitiateBrokerageConnectionUseCase` did not catch `BrokerageApiError(reason="already_exists")`. SnapTrade is a persistent external service — the demo user `01900000-...-0010` was still registered after `make dev-rebuild` wiped the local DB. The unhandled exception propagated to the domain error handler which maps ALL `BrokerageApiError` to HTTP 503.

**Location**: `services/portfolio/src/portfolio/application/use_cases/brokerage_connection.py:84`
**Trigger condition**: Any `POST /brokerage-connections` after the local portfolio_db is wiped while SnapTrade still has the user registered.

---

## 6. Impact Analysis

- **Immediate**: Brokerage connection initiation returns 503 for all users after any dev rebuild.
- **Blast radius**: Only `POST /brokerage-connections`; other endpoints (GET, DELETE) unaffected.
- **Data integrity**: No data corrupted — the use case never reached the DB commit step.

---

## 7. Fix Applied

Two-path recovery in `InitiateBrokerageConnectionUseCase`:

**Path A (credentials in DB)**: When `register_user()` raises `BrokerageApiError(reason="already_exists")`, look up existing brokerage connections for this user. If found, reuse `snaptrade_user_id/snaptrade_user_secret` from the most recent non-disconnected connection to generate a new portal URL.

**Path B (credentials lost — DB wiped)**: If no existing connections are found, call `brokerage_client.delete_user(user_id_hint)` to remove the stale SnapTrade registration, then re-register fresh.

**New method added**: `delete_user(user_id_hint)` added to `IBrokerageClient` protocol, `SnapTradeClient`, and `FakeBrokerageClient`.

### Validation

```
docker logs worldview-portfolio-1 (after fix):
  "event": "snaptrade_user_already_registered"  ← 409 detected
  "event": "brokerage_snaptrade_user_deleted_and_reregistered"  ← path B ran
  "event": "brokerage_connection_initiated"  ← success
  POST /api/v1/brokerage-connections → 201 Created  ✓
```

---

## 8. Tests Added

- `test_already_registered_reuses_existing_db_credentials` — path A (reuse stored credentials)
- `test_already_registered_no_db_creds_deletes_and_reregisters` — path B (delete + re-register)
- All 487 portfolio unit tests pass.

---

## 9. Prevention Recommendations

- **External service recovery pattern**: Every use case that calls an external registration API must handle "already exists" responses as a recoverable condition with explicit fallback logic, not as a generic service error. `BrokerageApiError` mapped to 503 is correct for truly unavailable services — not for recoverable conflicts.
- **New pattern rule**: When integrating an external service with persistent user state (SnapTrade, Stripe, Auth0), always handle "already registered" (HTTP 409) with a delete + re-register fallback path, and document it in the `IBrokerageClient` protocol.
- **Seed script consideration**: Could add a `DELETE /api/v1/brokerage-connections` cleanup step in a future "reset-dev" script to sync the local DB with SnapTrade state.

---

## 10. Bug Pattern Added

**BP-251** — "SnapTrade 'User Already Registered' (409) Returns 503 After DB Wipe" — added to `docs/BUG_PATTERNS.md`.

---

## Compounding Check

- ✅ `docs/BUG_PATTERNS.md` — BP-251 added
- ✅ `services/portfolio/tests/unit/test_use_cases_brokerage.py` — 2 regression tests added
- `services/portfolio/src/portfolio/infrastructure/brokerage/snaptrade_client.py` — `delete_user` implemented
- `services/portfolio/src/portfolio/application/ports/brokerage_client.py` — `delete_user` added to Protocol
- `services/portfolio/tests/unit/fakes.py` — `FakeBrokerageClient.delete_user` + `register_already_exists` flag
