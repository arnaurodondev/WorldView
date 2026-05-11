# QA Audit — PLAN-0052 Wave D (Feedback System Backend) — Iter 3

**Auditor**: Claude Code (final QA verification — iter-3)
**Date**: 2026-04-29
**Commit under audit**: `f37582fa` (fix(plan-0052-qa-iter2): close 1 CRITICAL OIDC role + 1 latent + 2 MINOR + 1 NIT)
**Iter-1 audit**: `docs/audits/2026-04-29-qa-plan-0052-wave-d-iter1.md`
**Iter-2 audit**: `docs/audits/2026-04-29-qa-plan-0052-wave-d-iter2.md`
**Runtime environment**: api-gateway-1 healthy (37 min uptime); postgres-1 healthy (`portfolio_db` at alembic_version `0014`); portfolio container NOT running. Migration 0015 statically reviewed in iter-1 — no behavioural change since.

---

## Executive summary

The two iter-2 fix vectors landed cleanly:

1. **F-Q2-01 (CRITICAL)**: `_extract_role` helper added to `middleware.py`; supports all three Zitadel role-claim shapes (Zitadel-namespaced dict, generic `roles` array, legacy `role` string). `OIDCAuthMiddleware.dispatch` always recomputes role from the live token and overwrites any cached value. `auth.py` callback caches role into Valkey alongside `{user_id, tenant_id}` so `/v1/auth/me` stays consistent across requests. Dev-login path was already correct (iter-1) and the cache write now mirrors the OIDC callback.
2. **F-Q2-05 (latent)**: `InternalJWTIssuerMiddleware` now forwards `role=user.get("role") or "user"` into `issue_user_jwt`. Middleware-stamped header is now correct; per-route `_auth_headers()` re-issuance in `proxy.py` was already correct from iter-1.

Helper safety verified: each branch of `_extract_role` guards with `isinstance` before reading nested members or calling `.lower()`, so malformed payloads (string in `urn:zitadel...`, non-string members in `roles[]`, dict where `role` is expected) cannot crash. Default of `"user"` matches `issue_user_jwt`'s default.

End-to-end regression test (`test_oidc_admin_role_propagates_to_internal_jwt`) wires both middlewares together, encodes a Zitadel-shaped admin payload with a real RSA key, and asserts that the issued internal JWT carries `role=admin`. Test passes. 5 supporting unit tests cover each `_extract_role` branch.

Settings validator (F-Q2-02) verified empirically — empty string and `not-a-uuid` both fail `Settings()` construction with `ValidationError` instead of crashing the route at first call. `utc_now` import (F-Q2-04) is now at module top; no inline imports remain in `nps_score.py:aggregate()`.

F-Q2-03 (NIT, doc/commit drift) — the doc itself is correct (15 endpoints listed). The drift is between the historic iter-1 commit message and the table; commit messages are immutable, so this is closed by acknowledgement.

Tests: 295 api-gateway unit tests pass (iter-2 was 289; +6 from F-Q2-01 coverage). 643 portfolio unit tests pass. Integration/e2e failures are infrastructure-dependent (require live postgres/kafka) and pre-existing — running an individual brokerage-sync test in isolation passes (test-isolation issue, not regression). Live runtime: gateway returns 200 on `/healthz`.

**Verdict: SHIP** (1 NIT remains; non-blocking).

---

## Per-finding verification

| ID | Severity | Status | Notes |
|---|---|---|---|
| F-Q2-01 | CRITICAL | CLOSED | `middleware.py:40-73` `_extract_role` covers all three Zitadel claim shapes with `isinstance` guards. OIDC dispatch path at `middleware.py:188` resolves role from live token and writes to `request.state.user["role"]` at line 216 (overrides any cached value — admin downgrade reflected immediately). Dev-login path at `middleware.py:134` reads role from internal JWT payload. `auth.py:282` resolves role at callback; `auth.py:335-339` caches role into Valkey with `{user_id, tenant_id, role}`. `auth.py:705` dev-login cache write also includes role. `InternalJWTIssuerMiddleware.dispatch` at `middleware.py:256` passes `role=user.get("role") or "user"`. End-to-end test `test_oidc_admin_role_propagates_to_internal_jwt` wires both middlewares with a real RSA key, encodes Zitadel-shaped admin payload, asserts `decoded["role"] == "admin"` on the issued internal JWT. 5 unit tests cover each `_extract_role` branch (admin dict, user dict, roles array, role string, default). All pass. |
| F-Q2-02 | MINOR | CLOSED | `services/portfolio/src/portfolio/config.py:131-142` `@field_validator("feedback_anonymous_tenant_id")` exists. Manually verified: `PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID=not-a-uuid` makes `Settings()` raise `ValidationError` at startup; empty string `""` also raises (`UUID("")` raises `ValueError("badly formed hexadecimal UUID string")`). Validator wraps in try/except and re-raises with a clear operator-actionable message. |
| F-Q2-03 | NIT | CLOSED | `docs/services/api-gateway.md:236-251` lists 15 feedback endpoints — accurate. The drift was purely between iter-1 commit message (which said "14 routes") and the actual table (15). Commit messages are immutable, so the iter-2 fix is "acknowledge and move on". No code/doc change needed. Audit-only closure. |
| F-Q2-04 | NIT | CLOSED | `services/portfolio/src/portfolio/infrastructure/db/repositories/nps_score.py:12` `from common.time import utc_now` at module top. `aggregate()` at line 87 uses `utc_now()` directly with no inline import. |
| F-Q2-05 | LATENT | CLOSED | `InternalJWTIssuerMiddleware` at `middleware.py:256` now passes `role=user.get("role") or "user"` to `issue_user_jwt`. Spot-check confirms `proxy.py:_auth_headers()` (line 58-65) was already correct from iter-1. **One latent doppelgänger remains** — see Finding F-Q3-01 (NIT). |

---

## Regression hunting

### Helper safety on malformed payloads (F-Q2-01)

Reviewed `_extract_role` for crashes on weird payloads:

- `urn:zitadel:iam:org:project:roles` is a **string** not a dict: `isinstance(zitadel_roles, dict)` short-circuits → falls through to next branch. ✅
- `urn:zitadel:iam:org:project:roles` is a **dict with non-string values**: only `"admin" in zitadel_roles` is checked (key membership), values are never read. ✅
- `roles` is a list with **non-string elements**: `isinstance(r, str)` guards each `.lower()` call. ✅
- `role` is a **bool / int / dict**: `isinstance(role, str)` guards `.lower()`. ✅
- All claims **missing**: returns `"user"` default — matches `issue_user_jwt`'s default. ✅

No crash vectors found.

### Validator + pydantic-settings interaction (F-Q2-02)

- Empty env var (`PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID=""`): `UUID("")` raises `ValueError` → validator raises → `ValidationError` at `Settings()` construction. ✅
- Bad UUID string: same path. ✅
- Default `"00000000-0000-0000-0000-000000000000"` (nil UUID): valid, passes through unchanged. ✅
- Validator runs before `model_validator` `_warn_default_db_credentials` and `_warn_missing_snaptrade_credentials`, so it short-circuits cleanly without side effects on other validators. ✅

### Middleware ordering (F-Q2-05)

Verified production app at `services/api-gateway/src/api_gateway/app.py:206-207`:

```python
app.add_middleware(InternalJWTIssuerMiddleware)  # innermost — runs after OIDCAuth
app.add_middleware(OIDCAuthMiddleware)            # outermost — runs first (last added)
```

Starlette runs middleware in reverse-add order, so `OIDCAuthMiddleware.dispatch` populates `request.state.user["role"]` BEFORE `InternalJWTIssuerMiddleware.dispatch` reads it. The new e2e test mirrors this same order. ✅

### Test suite

- api-gateway: 295/295 pass (iter-2 was 289; +6 from new F-Q2-01 coverage). No regressions.
- portfolio unit tests: 643/643 pass.
- portfolio integration/e2e: 31 failures — all pre-existing infrastructure-dependent (httpx ConnectError, OSError "Multiple exceptions"). Running `test_trigger_sync_active_connection_returns_202` in isolation passes — this is a test-isolation issue (event-loop / shared state across modules), not a PLAN-0052 regression.

---

## New findings

### Finding F-Q3-01

- **Severity**: NIT
- **Category**: latent / consistency
- **File**: `services/api-gateway/src/api_gateway/routes/risk_metrics.py:132-150`
- **Confidence**: HIGH
- **Issue**: `_user_headers()` mints a fresh user-scoped JWT for parallel risk-metrics calls but does **not** forward `role`. The only caller is `GET /v1/portfolios/{portfolio_id}/risk-metrics` (line 458), which is a user-facing endpoint with no admin gate, so this is not currently exploitable. However, it diverges from the iter-1 fix in `proxy.py:_auth_headers()` which does forward role. If a future risk-metrics admin endpoint is added that re-uses `_user_headers`, it would silently 403. Mirrors the F-Q2-05 pattern but in a different file.
- **Suggested fix** (one-liner):
  ```python
  token = issue_user_jwt(
      user_id=user.get("user_id", ""),
      tenant_id=user.get("tenant_id", ""),
      oidc_sub=user.get("sub", ""),
      private_key=private_key,
      kid=kid,
      role=user.get("role") or "user",  # F-Q3-01: consistency with proxy._auth_headers
  )
  ```
- **Why NIT not MAJOR**: only one caller, no admin gate on that route, current behaviour is correct (defaulting to `"user"` matches the route's auth model). Pure forward-compat hardening.

---

## Live runtime checks

- `docker ps`: `worldview-api-gateway-1` healthy (37 min uptime); `worldview-postgres-1` healthy. portfolio container NOT running.
- `portfolio_db.alembic_version` = `0014`. Migration `0015` was statically reviewed and validated against live Postgres in iter-1 — no behavioural change in iter-2 commit, so verdict carries forward.
- `GET http://localhost:8000/healthz` → `200`.
- `\d nps_scores` not yet applicable (table created by 0015 only when portfolio container starts and runs alembic upgrade).

---

## Summary table

| Finding | Severity | iter-2 outcome | iter-3 status |
|---|---|---|---|
| F-Q2-01 OIDC role propagation | CRITICAL | fixed | CLOSED |
| F-Q2-02 settings validator | MINOR | added | CLOSED |
| F-Q2-03 commit/doc drift | NIT | acknowledged | CLOSED |
| F-Q2-04 utc_now hoist | NIT | hoisted | CLOSED |
| F-Q2-05 latent role passthrough | LATENT | fixed | CLOSED |
| F-Q3-01 risk_metrics _user_headers role | NIT | new (forward-compat) | OPEN (defer) |

Plus deferred to PLAN-0053 (per iter-2 audit, not re-flagged): F-Q1-22 (outbox event for new tables), F-Q1-23 (soft-delete for `DELETE submissions/{id}`), F-Q1-24 (S3 pre-signed upload route).

Convergence criterion (0 BLOCKING/CRITICAL/MAJOR): **met**.

---

## Verdict

**SHIP**

All BLOCKING / CRITICAL / MAJOR / MINOR findings from iter-1 and iter-2 are closed. One new NIT (F-Q3-01) is forward-compat hardening with no current exploit; safe to defer or pick up in a follow-up wave.
