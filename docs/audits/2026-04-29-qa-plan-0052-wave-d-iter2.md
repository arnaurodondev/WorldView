# QA Audit — PLAN-0052 Wave D (Feedback System Backend) — Iter 2

**Auditor**: Claude Code (strict QA pass — iter-2)
**Date**: 2026-04-29
**Commit under audit**: `b2c61389` (fix(plan-0052-qa-iter1): close 1 BLOCKING + 4 CRITICAL + 4 MAJOR + 8 MINOR/NIT)
**Iter-1 audit**: `docs/audits/2026-04-29-qa-plan-0052-wave-d-iter1.md`
**Runtime environment**: postgres-1, api-gateway-1 healthy. portfolio container is NOT running. Migration 0015 has NOT been applied to the live `portfolio_db` (alembic_version = `0014`); migration source was reviewed statically and the new index syntax was empirically validated against the live Postgres (CREATE INDEX succeeds).

---

## Executive summary

Iter-1 closed almost everything: the BLOCKING migration index, the CRITICAL anonymous UUID parsing, the missing PATCH features proxy, and the anon tenant routing. New tests are well-targeted (anon system-JWT path, sequential-vote accumulation, scheme validator, tenant-filtered has_voted, dev-admin role propagation). 932 unit tests pass (643 portfolio + 289 gateway).

But one CRITICAL gap remains: **F-Q1-02 is a partial fix**. Role propagation works for the dev-login path (good) and is asserted by tests. In production, however, `OIDCAuthMiddleware` does NOT extract `role` from the Zitadel access token (`services/api-gateway/src/api_gateway/middleware.py:155-163` builds `request.state.user` without a `role` key) and `auth.py:325-329` caches only `{user_id, tenant_id}` in Valkey. Therefore real OIDC users always have `request.state.user.get("role") is None`, `_auth_headers()` defaults to `"user"`, and every backend admin endpoint (PATCH/DELETE submission, GET admin list, GET nps aggregate, PATCH feature, GET /submissions/anonymous) returns 403 in production.

Also a new MINOR was introduced: the F-Q1-04 admin endpoint calls `UUID(settings.feedback_anonymous_tenant_id)` with no try/except — a misconfigured env var crashes the route with 500 instead of returning a clean 5xx with a useful body.

A latent design risk: `InternalJWTIssuerMiddleware` at `middleware.py:192-198` still calls `issue_user_jwt(...)` without a `role` parameter. Feedback routes happen to overwrite this token via `_auth_headers()` so they're safe, but any future route that relies on the middleware-stamped header will silently lose the role claim.

**Verdict: NEEDS-FIXES** (1 CRITICAL, 1 MINOR, 2 NIT)

---

## Verification of iter-1 fixes

| ID | Severity | Status | Notes |
|---|---|---|---|
| F-Q1-01 | BLOCKING | ✅ VERIFIED | `now()`-based predicate gone (`alembic/versions/0015...py:144-159`). New `ix_nps_scores_user_recent (tenant_id, user_id, created_at DESC)` is present, non-unique. `SubmitNPSScoreUseCase` has the pre-insert `find_recent_by_user` check (`feedback.py:262-267`). Port + SQL repo + Fake repo all implement `find_recent_by_user`. CREATE INDEX validated against live Postgres successfully. |
| F-Q1-02 | CRITICAL | ⚠️ PARTIAL | Dev-login path works (auth.py:669-682) and tests assert it. **Real OIDC path is still broken** — see Finding F-Q2-01. |
| F-Q1-03 | CRITICAL | ✅ VERIFIED | `_extract_user_id_optional` returns None for `"system:api-gateway"` and ValueError/TypeError. `_extract_tenant_id` has the same defensive parsing. `_extract_user_id` (non-optional) raises 401 instead of 500 for non-UUID values. Dedicated test `test_anonymous_submission_via_system_jwt` simulates the production sub. |
| F-Q1-04 | CRITICAL | ✅ VERIFIED (with caveat) | `feedback_anonymous_tenant_id` setting added. New endpoint `GET /api/v1/feedback/submissions/anonymous` exists at `feedback.py:249-286`, declared BEFORE `/{submission_id}` route. Gateway proxy at `proxy.py:2565-2581`. Admin-gated. Tests cover admin success + non-admin 403. **Caveat**: see Finding F-Q2-02 (no defensive UUID parse on settings value). |
| F-Q1-05 | CRITICAL | ✅ VERIFIED | `@router.patch("/feedback/features/{feature_request_id}")` at `proxy.py:2705-2724`. Test `test_patch_feature_proxy` asserts forwarding; `test_patch_feature_proxy_requires_auth` asserts 401 without auth. Doc `docs/services/api-gateway.md:247` now lists the route. |
| F-Q1-06 | MAJOR | ✅ VERIFIED | Single-statement `UPDATE feature_requests SET vote_count = (SELECT COUNT(*) ...) RETURNING vote_count` at `feature_request.py:131-149`. `UpsertFeatureVoteUseCase` simplified — no drift-compensation branch (`feedback.py:398-410`). Test `test_five_sequential_votes_yield_count_five` covers 5-vote accumulation. |
| F-Q1-07 | MAJOR | ✅ VERIFIED | `test_anonymous_submission_via_system_jwt` injects `X-Test-User-Id: "system:api-gateway"` and `X-Test-Tenant-Id: NIL_UUID` verbatim and asserts 201. Fixture preserves the value (no auto-conversion). |
| F-Q1-08 | MAJOR | ✅ VERIFIED | `field_validator("screenshot_url")` at `feedback_schemas.py:52-72` rejects non-https / no-host / >2048-char URLs. Three new tests cover javascript:, http://, and a legitimate https URL with path. Static check confirms validator accepts URLs with query strings, fragments, ports, and percent-encoding. |
| F-Q1-09 | MAJOR | ✅ VERIFIED | `has_voted(feature_request_id, user_id, tenant_id)` — tenant_id is now required positional. SQL repo predicate includes `FeatureVoteModel.tenant_id == tenant_id`. Fake repo updated. Only caller (`ListFeatureRequestsUseCase` at `feedback.py:342`) updated. |
| F-Q1-10 | MINOR | ✅ VERIFIED | `pii_redaction.py:21-26` documents the intentional Bearer over-redaction with explicit "this is a deliberate choice" framing. |
| F-Q1-11 | MINOR | ✅ VERIFIED | Migration is now idempotent (no `now()` predicate). `_table_exists` guards each CREATE TABLE. `IF NOT EXISTS` used on indexes (implicit via `op.create_index`). Re-applies cleanly. |
| F-Q1-12 | MINOR | ✅ VERIFIED | DELETE proxy at `proxy.py:2612-2617` declares `status_code=204, response_class=Response, response_model=None`. |
| F-Q1-13 | MINOR | ✅ VERIFIED | `proxy.py:2630-2632` returns `Response(status_code=204)` (no media_type, no content) when backend is 204; falls back to JSON body for 4xx/5xx. |
| F-Q1-14 | MINOR | ✅ VERIFIED | `UpdateFeatureRequestCommand`/`UpdateFeatureRequestUseCase` are at the top-of-file imports in `feedback.py:46-72`. No inline imports left. |
| F-Q1-15 | MINOR | ✅ VERIFIED | Drift-compensation branch removed (tied to F-Q1-06). New code uses single re-fetch with assert (`feedback.py:404-410`). |
| F-Q1-16 | MINOR | ✅ VERIFIED | `from common.time import utc_now` at module top in `feedback_submission.py:11`, `feature_request.py:10`, `beta_enrollment.py:10`. No inline imports left in those files (only `nps_score.py:88` retains an inline import inside `aggregate()` — see Finding F-Q2-04). |
| F-Q1-17 | MINOR | ✅ VERIFIED | `test_feature_vote_idempotent_returns_count_one` at `test_feedback_routes.py:301-303` asserts both `v1.json()["has_voted"] is True` and `v2.json()["has_voted"] is True`. |
| F-Q1-18 | NIT | ✅ VERIFIED | Migration docstring no longer claims to mirror 0014. New "F-Q1-01 fix" block at lines 22-30 explains why the predicate moved to the application layer. |
| F-Q1-19 | NIT | ✅ VERIFIED | `feedback.py:164-165` — `redacted_description = redact(cmd.description); assert redacted_description is not None`. No `or ""` left. Same pattern in `CreateFeatureRequestUseCase:357-358`. |
| F-Q1-20 | NIT | ✅ VERIFIED | `docs/services/api-gateway.md:236-251` lists 15 feedback endpoints. (Commit message says "14 routes" but the actual count + doc count are 15 — F-Q2-03 minor doc/commit mismatch.) |

---

## New findings (introduced by iter-1 fixes or missed in iter-1)

### Finding F-Q2-01
- **Severity**: CRITICAL
- **Category**: security / partial fix
- **File**: `services/api-gateway/src/api_gateway/middleware.py:155-163`, `services/api-gateway/src/api_gateway/routes/auth.py:325-329`
- **Confidence**: HIGH
- **Issue**: F-Q1-02 is incomplete. The fix propagates `role` through `issue_user_jwt(...)` and adds the dev-login admin path, but the **production OIDC path** never sets `request.state.user["role"]`:
  1. `OIDCAuthMiddleware` builds `user_data_oidc` from the Zitadel token claims at lines 157-163 — there is no `role` key extracted. Zitadel's role can live in `payload["urn:zitadel:iam:org:project:roles"]` (Zitadel-specific projection), `payload.get("roles")`, or a custom claim, but the middleware never reads any of them.
  2. The Valkey cache write at `auth.py:325-329` stores `{"user_id": user_id, "tenant_id": tenant_id}` only — no role — so even if the Zitadel response contained a role, it would be lost on the next cache hit.
  3. `_auth_headers(request)` at `proxy.py:58` does `role = user.get("role") or "user"` → produces `"user"` for every real OIDC request.

  Net effect: every admin endpoint on every backend service (PATCH submission, DELETE submission, GET admin-list, GET /submissions/anonymous, GET /nps/aggregate, PATCH feature) **returns 403 for real Zitadel users in production**. The dev-login test passes only because the dev path explicitly sets `role`.
- **Evidence**:
  - `middleware.py:155-163` — no `role` key in `user_data_oidc`.
  - `auth.py:327` — `json.dumps({"user_id": user_id, "tenant_id": tenant_id})`.
  - `admin_costs.py:61` — `if user is None or user.get("role") != "admin"` → returns 403 for any user without an explicit role claim.
  - Tests use `_USER_PAYLOAD = {"sub": ..., "tenant_id": ..., "role": "user"}` and `_ADMIN_PAYLOAD = {"role": "admin"}` so the test fixture's `TestAuthMiddleware` (`conftest.py:106-109`) reads `payload.get("role", "user")` and passes — but that path does not exist in production.
- **Suggestion**:
  1. In `OIDCAuthMiddleware` (line 157-163), extract role from the OIDC token. The exact claim depends on how Zitadel projects roles for this org — common shapes: `payload.get("urn:zitadel:iam:org:project:roles")` (a dict whose keys are role names), or `payload.get("roles")` (a list). Pick one and document it. Map "admin" if the user has the admin role, else "user".
  2. Update `auth.py:325-329` and `auth.py:687-693` to include `role` in the cached user object so subsequent requests don't lose it on cache hit.
  3. Add an integration test that simulates a real OIDC payload (with the chosen Zitadel role claim shape) and asserts `_auth_headers` produces `role: admin` end-to-end.
  4. Decide explicitly: is admin gating going to live at the gateway (admin_costs pattern, gateway-only) or at the backend (feedback pattern, backend trusts the JWT)? Right now both patterns exist and the gateway pattern is correctly wired but the backend pattern is broken in prod.
- **Auto-fixable**: NO — requires a Zitadel role-claim decision.

### Finding F-Q2-02
- **Severity**: MINOR
- **Category**: robustness
- **File**: `services/portfolio/src/portfolio/api/routes/feedback.py:271-273`
- **Confidence**: HIGH
- **Issue**: The new `list_anonymous_submissions` endpoint reads `settings.feedback_anonymous_tenant_id` and parses it with bare `UUID(settings.feedback_anonymous_tenant_id)`. If an operator misconfigures `PORTFOLIO_FEEDBACK_ANONYMOUS_TENANT_ID` (typo, partial paste, etc.), the route raises `ValueError` → 500 with no useful body. Compare to the validated state-extraction helpers above (`_extract_tenant_id` returns 401 with a descriptive detail).
- **Evidence**: `feedback.py:271` — `_require_admin(request); settings = request.app.state.settings; anon_tenant_id = UUID(settings.feedback_anonymous_tenant_id)` — no try/except.
- **Suggestion**: Validate at startup (Pydantic settings field validator) so a bad value fails the service boot, not the request:
  ```python
  @field_validator("feedback_anonymous_tenant_id")
  @classmethod
  def _validate_anon_tenant_uuid(cls, v: str) -> str:
      UUID(v)  # raises ValueError → service fails to start
      return v
  ```
  Or wrap the `UUID(...)` call in a try/except and return 503 + descriptive detail.
- **Auto-fixable**: YES

### Finding F-Q2-03
- **Severity**: NIT
- **Category**: docs
- **File**: commit `b2c61389` message vs `docs/services/api-gateway.md:236-251`
- **Confidence**: HIGH
- **Issue**: Commit message says "docs/services/api-gateway.md feedback table now lists 14 routes (incl. PATCH features and anon-list)". Actual counts: portfolio router has 15 routes, gateway proxy has 15 routes (including the multi-line `@router.delete(...)` decorator at proxy.py:2612), and the doc table has 15 rows. The "14" in the commit message is off by one.
- **Suggestion**: Note the correct count in the next plan/audit doc; the doc itself is correct.
- **Auto-fixable**: N/A (commit immutable)

### Finding F-Q2-04
- **Severity**: NIT
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/nps_score.py:86-90`
- **Confidence**: HIGH
- **Issue**: F-Q1-16's intent was to hoist `from common.time import utc_now` to module top in three repo files. `feedback_submission.py`, `feature_request.py`, `beta_enrollment.py` were correctly hoisted. `nps_score.py` was not — `aggregate()` still does `from common.time import utc_now` inline at line 88 (and `from sqlalchemy import case` at line 86). Less impactful than the others (this method is only called by GetNPSAggregateUseCase, not on a hot path), but the inconsistency is a doc/process gap.
- **Evidence**: `nps_score.py:86-90` shows the inline imports.
- **Suggestion**: Hoist `utc_now` and `case` to the top of the module for consistency with the other three repos.
- **Auto-fixable**: YES

### Finding F-Q2-05 (latent — not introduced by iter-1, but worth flagging)
- **Severity**: MINOR
- **Category**: architecture
- **File**: `services/api-gateway/src/api_gateway/middleware.py:192-198`
- **Confidence**: HIGH
- **Issue**: `InternalJWTIssuerMiddleware.dispatch` still calls `issue_user_jwt(user_id=..., tenant_id=..., oidc_sub=..., private_key=..., kid=...)` without a `role` parameter. Feedback routes happen to override the middleware-stamped header by calling `_auth_headers()` per-route and merging the fresh JWT into outgoing headers, so the gap is invisible. But ANY future route that uses the middleware-stamped header verbatim will silently issue a JWT with `role: "user"`, which will 403 every backend admin endpoint regardless of the OIDC role.
- **Suggestion**: Add the `role=user.get("role")` parameter to the middleware call site (line 192-198) so the default JWT carries the correct role too. Belt-and-suspenders alongside the per-route `_auth_headers()` call.
- **Auto-fixable**: YES

---

## Summary table

| Severity | Count |
|---|---|
| CRITICAL | 1 |
| MINOR | 2 |
| NIT | 2 |
| **Total new findings** | **5** |

| Iter-1 verification | Count |
|---|---|
| ✅ Verified clean | 19 / 20 |
| ⚠️ Partial fix | 1 / 20 (F-Q1-02) |

## Test results (re-run)

- portfolio unit: **643 passed** (`tests/unit`)
- api-gateway unit + integration: **289 passed** (`tests/`)
- Total: 932 PASS — same count as commit message.

## Verdict

**NEEDS-FIXES**

The blocking + critical iter-1 findings are largely resolved, but F-Q1-02 was only half-fixed. The dev-login admin path works (and has tests), but real Zitadel admin role does not propagate end-to-end:

1. **F-Q2-01 (CRITICAL)** — Production OIDC users never get `role: admin` because `OIDCAuthMiddleware` doesn't extract role from Zitadel's token and the Valkey cache doesn't store it. Every backend admin endpoint will 403 in production.

Recommended fix order before SHIP:
1. F-Q2-01 — pick a Zitadel role-claim shape, extract in `OIDCAuthMiddleware`, store in Valkey cache, add an OIDC-shaped role test.
2. F-Q2-02 — validate `feedback_anonymous_tenant_id` at settings load time.
3. F-Q2-04 — hoist the `nps_score.aggregate` inline imports.
4. F-Q2-05 — add `role=user.get("role")` to `InternalJWTIssuerMiddleware`.
