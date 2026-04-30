# QA Audit — PLAN-0052 Wave D (Feedback System Backend) — Iter 1

**Auditor**: Claude Code (strict QA pass)
**Date**: 2026-04-29
**Commit under audit**: `7fc90e5a` (Wave D feedback files only — Wave D was committed under a misleading message that says PLAN-0051 Wave D Alerts; the diff carries both)
**Files in scope**: 25 files listed in the QA brief
**Runtime environment**: Postgres + api-gateway + portfolio-snapshot-worker + portfolio-brokerage-sync are running. Portfolio API container itself is NOT running, so end-to-end curl checks were not executed; static + DB-level checks were performed against the live Postgres.

---

## Executive summary

The feedback subsystem looks structurally clean — hexagonal layering, repo ports, redaction at the use-case layer, partial-unique NPS index attempt, idempotent vote upsert. Test coverage is wide (security 17 cases, use-cases 22 cases, routes 13 cases, gateway 13 cases — none skipped, none weakened).

But three issues will prevent the wave from working in production: a Postgres-rejected migration index expression (BLOCKING), an admin role that the gateway never issues (CRITICAL — every PATCH/DELETE/admin-list endpoint is unreachable), and an anonymous-submission code path that crashes with `ValueError: badly formed UUID string` because the gateway's system JWT carries `sub: "system:api-gateway"` and the route blindly passes that to `UUID(...)` (CRITICAL).

There is also a missing gateway proxy for `PATCH /v1/feedback/features/{id}` (admin) — the portfolio route exists but is unreachable from the frontend.

**Verdict: NEEDS-FIXES** (1 BLOCKING, 4 CRITICAL, 4 MAJOR, 6 MINOR, 4 NIT, 3 ENHANCE)

---

## Findings

### Finding F-Q1-01
- **Severity**: BLOCKING
- **Category**: schema
- **File**: `services/portfolio/alembic/versions/0015_create_feedback_tables.py:142-148`
- **Confidence**: HIGH
- **Issue**: The 30-day partial unique index on `nps_scores` uses `WHERE created_at > now() - INTERVAL '30 days'`. Postgres requires index predicate functions to be IMMUTABLE; `now()` is STABLE. The migration will fail with `ERROR: functions in index predicate must be marked IMMUTABLE` the moment it is applied to a real Postgres.
- **Evidence**: I reproduced the exact error against the running `worldview-postgres-1` container:

  ```
  $ docker exec worldview-postgres-1 psql -U postgres -d portfolio_db -c \
      "CREATE TEMP TABLE _qa_test_nps (...); \
       CREATE UNIQUE INDEX _qa_idx ON _qa_test_nps (tenant_id, user_id) \
       WHERE created_at > now() - INTERVAL '30 days';"
  ERROR:  functions in index predicate must be marked IMMUTABLE
  ```

  The migration's docstring claims this "mirrors migration 0014's pattern", but 0014 (`unique_watchlist_member_instrument`) has nothing to do with time-based partial indexes — the comment is misleading and there is no precedent in the repo for a `now()`-predicated index that actually deploys.
- **Suggestion**: Change the rate-limit invariant from "rolling 30 days" to "any single row, ever — application checks date in `aggregate()`" and use a plain `UNIQUE (tenant_id, user_id, date_bucket)` where `date_bucket` is a generated/explicit `DATE` column truncated to the day, or use a GENERATED column tied to `created_at` truncated to a 30-day epoch. Alternatively, drop the DB-level guarantee and enforce the rate limit by a SELECT-then-INSERT in `SqlAlchemyNPSScoreRepo.add()` (acknowledging the small race window). The current design is non-deployable.
- **Auto-fixable**: NO (requires design change)

### Finding F-Q1-02
- **Severity**: CRITICAL
- **Category**: security / contract
- **File**: `services/portfolio/src/portfolio/api/routes/feedback.py:106-116` and `services/api-gateway/src/api_gateway/jwt_utils.py:30-50`
- **Confidence**: HIGH
- **Issue**: `_require_admin(request)` checks `request.state.role == "admin"`, but `issue_user_jwt()` in the gateway hardcodes `"role": "user"` for every authenticated user. There is **no code path anywhere in the gateway that ever sets `role: "admin"` in an internal JWT**. Every admin endpoint will therefore return 403 in production.
- **Evidence**:
  - `services/api-gateway/src/api_gateway/jwt_utils.py:44` — `"role": "user"` (literal, no config).
  - `services/api-gateway/src/api_gateway/routes/admin_costs.py:61` — admin gating done at the **gateway** layer by checking `request.state.user.get("role")` (i.e., the OIDC payload from Zitadel, not the internal JWT). The portfolio service has no access to that OIDC role.
  - The admin routes affected: `PATCH /submissions/{id}`, `DELETE /submissions/{id}`, `GET /submissions` (without `mine=true`), `GET /nps/aggregate`, `PATCH /features/{id}`.
- **Suggestion**: Either (a) propagate the Zitadel role into `issue_user_jwt()` by adding a `role` parameter and reading `request.state.user.get("role")` at the call site (`services/api-gateway/src/api_gateway/routes/proxy.py:55`), or (b) move the admin check to the gateway layer and let the portfolio routes trust an `X-Role` header derived from the OIDC payload, or (c) implement a portfolio-side roles table queried per-request. Option (a) is the smallest patch.
- **Auto-fixable**: NO

### Finding F-Q1-03
- **Severity**: CRITICAL
- **Category**: runtime / contract
- **File**: `services/portfolio/src/portfolio/api/routes/feedback.py:86-96`
- **Confidence**: HIGH
- **Issue**: `_extract_user_id_optional` does `if not raw: return None; return UUID(str(raw))`. When the gateway proxies an unauthenticated request, `_system_headers()` issues a JWT via `issue_public_jwt()` which sets `sub: "system:api-gateway"`. `InternalJWTMiddleware` reads `payload.get("sub", "")` into `request.state.user_id`. The string `"system:api-gateway"` is truthy → the falsy guard does not trigger → `UUID("system:api-gateway")` raises `ValueError`. Every anonymous `POST /submissions`, `POST /micro-survey`, and `GET /features` (without auth) **will 500 in production**.
- **Evidence**:
  - `services/api-gateway/src/api_gateway/jwt_utils.py:88` — `"sub": "system:api-gateway"`.
  - `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py:188,205` — `request.state.user_id = payload.get("sub", "")`.
  - The unit test `test_create_submission_anonymous_with_email` only sets `X-Test-Tenant-Id` (no `X-Test-User-Id`), so `request.state.user_id = ""` (empty string is falsy and returns `None` cleanly). **The test does not simulate the production system-JWT path.**
- **Suggestion**: Treat any non-UUID `request.state.user_id` as anonymous:
  ```python
  def _extract_user_id_optional(request: Request) -> UUID | None:
      raw = getattr(request.state, "user_id", None)
      if not raw or raw == "system:api-gateway":
          return None
      try:
          return UUID(str(raw))
      except ValueError:
          return None
  ```
  Add an integration test that exercises the system-JWT path (create gateway with real `_system_headers` → portfolio route).
- **Auto-fixable**: YES

### Finding F-Q1-04
- **Severity**: CRITICAL
- **Category**: security / architecture
- **File**: `services/portfolio/src/portfolio/api/routes/feedback.py:155-180`, gateway `_system_headers` at `services/api-gateway/src/api_gateway/routes/proxy.py:68-84`
- **Confidence**: HIGH
- **Issue**: All anonymous submissions are bucketed under the **nil-UUID tenant** (`00000000-0000-0000-0000-000000000000`) because `issue_public_jwt()` hardcodes that tenant. Real tenants querying `GET /api/v1/feedback/submissions` filter by their own `tenant_id` and **never see anonymous feedback**. Anonymous feedback is effectively black-holed — the support team cannot read it via the standard admin list endpoint.
- **Evidence**:
  - `services/api-gateway/src/api_gateway/jwt_utils.py:90` — `"tenant_id": _NIL_UUID`.
  - `services/portfolio/src/portfolio/infrastructure/db/repositories/feedback_submission.py:91` — list query filters strictly by `tenant_id`.
- **Suggestion**: Decide product semantics: either (a) require auth for `POST /submissions` (drop anon path) and only allow `POST /micro-survey` anon (which is already nil-UUID-segregated by design), or (b) introduce a "platform support" tenant id served from settings, document it, and add an admin endpoint `GET /v1/feedback/anonymous` that queries the platform tenant explicitly. Either way: add a test that asserts an admin in tenant T can list submissions made anon from tenant T's docs page.
- **Auto-fixable**: NO

### Finding F-Q1-05
- **Severity**: CRITICAL
- **Category**: contract
- **File**: `services/api-gateway/src/api_gateway/routes/proxy.py` (no proxy for `PATCH /feedback/features/{id}`)
- **Confidence**: HIGH
- **Issue**: The portfolio service exposes `PATCH /api/v1/feedback/features/{feature_request_id}` (admin) at `services/portfolio/src/portfolio/api/routes/feedback.py:400-433`, but the gateway has no `@router.patch("/feedback/features/{id}")` proxy. Counted: portfolio router has 14 endpoints, gateway proxy has 13. Admins cannot update a feature request status (e.g. mark as `shipped`/`planned`) from the frontend. The plan brief says "12 endpoints" — both implementations exceed that, but the gateway still missed one of the admin routes.
- **Evidence**: `grep -c "^@router\." services/portfolio/src/portfolio/api/routes/feedback.py` = 14. `grep "@router\." services/api-gateway/src/api_gateway/routes/proxy.py | grep -i feedback | wc -l` = 13. No PATCH on `/feedback/features/{id}` at the gateway.
- **Suggestion**: Add the missing proxy:
  ```python
  @router.patch("/feedback/features/{feature_request_id}")
  async def feedback_update_feature(feature_request_id: str, request: Request) -> Response:
      if not getattr(request.state, "user", None):
          raise HTTPException(status_code=401, detail="Authentication required")
      body = await request.body()
      headers = _portfolio_headers(request)
      clients = _clients(request)
      resp = await clients.portfolio.patch(
          f"/api/v1/feedback/features/{feature_request_id}",
          content=body,
          headers={"Content-Type": "application/json", **headers},
      )
      return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
  ```
  Add a corresponding test.
- **Auto-fixable**: YES

### Finding F-Q1-06
- **Severity**: MAJOR
- **Category**: security / data integrity
- **File**: `services/portfolio/src/portfolio/application/use_cases/feedback.py:356-392`, `services/portfolio/src/portfolio/infrastructure/db/repositories/feature_request.py:127-143`
- **Confidence**: HIGH
- **Issue**: `UpsertFeatureVoteUseCase` has a lost-update race. Two concurrent `POST /features/{id}/vote` calls from different users:
  1. Each transaction `INSERT`s into `feature_votes` (different PKs, both succeed).
  2. Each runs `SELECT count() FROM feature_votes WHERE feature_request_id = X` — with default `READ COMMITTED` isolation, neither sees the other's uncommitted insert. Both compute `count=1`.
  3. Each runs `UPDATE feature_requests SET vote_count=1 WHERE id=X` — last writer wins. Both votes are persisted, but `vote_count` ends at 1 instead of 2.

  The drift compounds over time and silently corrupts the public roadmap ranking.
- **Evidence**: `refresh_vote_count` (`feature_request.py:127`) does no `SELECT … FOR UPDATE` on the `feature_requests` row, and the count subquery is a snapshot of the same transaction.
- **Suggestion**: Either (a) acquire a row-level lock on `feature_requests` before counting:
  ```python
  await self._session.execute(
      select(FeatureRequestModel).where(FeatureRequestModel.id == feature_request_id).with_for_update()
  )
  ```
  ...inside the same transaction, or (b) use `UPDATE feature_requests SET vote_count = (SELECT COUNT(*) FROM feature_votes WHERE feature_request_id=:id) WHERE id=:id` as a single atomic statement (recomputes inside the same statement, no lost-update window). Add a stress test that fires 10 parallel votes from 10 users and asserts `vote_count == 10`.
- **Auto-fixable**: YES (single-statement UPDATE is the smallest fix)

### Finding F-Q1-07
- **Severity**: MAJOR
- **Category**: tests
- **File**: `services/api-gateway/tests/test_feedback_proxy.py` and `services/portfolio/tests/unit/api/test_feedback_routes.py`
- **Confidence**: HIGH
- **Issue**: Neither test suite exercises the actual production wiring for the anonymous path. The gateway test mocks `clients.portfolio.post` and never lets a system JWT reach a real portfolio route. The portfolio test injects `request.state.user_id = ""` via a custom middleware, never simulating `"system:api-gateway"`. Together, F-Q1-03 was undetected by 35+ tests.
- **Evidence**: Grep showed no test stringifies `system:api-gateway` or the nil UUID. Anonymous test (`test_create_submission_anonymous_with_email`, line 95) sends only `X-Test-Tenant-Id`.
- **Suggestion**: Add a portfolio test that injects `request.state.user_id = "system:api-gateway"` and `tenant_id = "00000000-0000-0000-0000-000000000000"` and POSTs `/api/v1/feedback/submissions` with an email — assert 201, not 500.
- **Auto-fixable**: YES

### Finding F-Q1-08
- **Severity**: MAJOR
- **Category**: security
- **File**: `services/portfolio/src/portfolio/api/feedback_schemas.py:46`, `services/portfolio/src/portfolio/api/routes/feedback.py:175`
- **Confidence**: MEDIUM
- **Issue**: `screenshot_url` is accepted as an arbitrary string (max 2048) and stored verbatim. There is no allow-list of hosts, no scheme check (a `javascript:` URL passes Pydantic's `str` constraint), and the admin UI presumably renders it. The plan's TTL config (`PORTFOLIO_FEEDBACK_SCREENSHOT_TTL_DAYS=90`) and `feedback_s3_bucket` field imply the backend was supposed to mediate uploads — but the route just accepts whatever URL the client supplies, which means any user can store a `javascript:alert(...)` URL or a tracking-pixel URL that fires on admin view.
- **Evidence**: `feedback_schemas.py:46` uses `str` not `HttpUrl`; no host validation in `CreateFeedbackSubmissionUseCase`.
- **Suggestion**: At minimum, validate `screenshot_url` scheme is `https://` and host is the configured S3 bucket (or its public CDN). Even better — short-term — drop the field from the public schema and add the planned pre-signed PUT endpoint as a Wave D follow-up, then accept the `screenshot_url` only via a server-side flow.
- **Auto-fixable**: YES (validator)

### Finding F-Q1-09
- **Severity**: MAJOR
- **Category**: security
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/feature_vote.py:43-50`
- **Confidence**: MEDIUM
- **Issue**: `has_voted(feature_request_id, user_id)` does not filter by `tenant_id`. The vote table has tenant_id (set on insert), but the read query ignores it. With B2B + cross-tenant identities, a user belonging to two tenants could (after using `feature_request_id` enumeration) discover whether they voted on a feature in a different tenant. The list use case calls `feature_requests.get(..., tenant_id)` first to gate the request, so the surface is narrow but real.
- **Evidence**: Query `select(FeatureVoteModel).where(FeatureVoteModel.feature_request_id == feature_request_id, FeatureVoteModel.user_id == user_id)` — no tenant predicate.
- **Suggestion**: Pass tenant_id through to `has_voted` and add `FeatureVoteModel.tenant_id == tenant_id` to the predicate. Mirror in `FakeFeatureVoteRepo`.
- **Auto-fixable**: YES

### Finding F-Q1-10
- **Severity**: MINOR
- **Category**: security
- **File**: `services/portfolio/src/portfolio/security/pii_redaction.py:51`
- **Confidence**: MEDIUM
- **Issue**: `_RE_BEARER` matches `Bearer\s+[A-Za-z0-9_\-\.\=]{16,}` — any 16-char alphanumeric string after `Bearer ` is redacted. A user describing the platform with text like "the `Bearer abcdefghijklmnop` example" has the example token redacted as if it were real. The redaction philosophy stated in the docstring is "we'd rather over-redact" so this is acceptable, but worth documenting an explicit allow-list for documentation pages.
- **Evidence**: pattern + replacement reviewed.
- **Suggestion**: Document this as a deliberate decision in the module docstring (it nearly is already), and verify the docs widget's `survey_key` / comment fields handle the over-redaction gracefully (Wave B-2 follow-up).
- **Auto-fixable**: NO

### Finding F-Q1-11
- **Severity**: MINOR
- **Category**: schema
- **File**: `services/portfolio/alembic/versions/0015_create_feedback_tables.py:42-43`
- **Confidence**: HIGH
- **Issue**: `_table_exists` only checks public-schema table names. The downgrade unconditionally `DROP TABLE IF EXISTS` (six tables) — fine, but combined with the failing partial-index in upgrade, partial application is likely. There is no cleanup hook to drop the partial index if the table CREATE succeeded but the index CREATE failed and the user re-runs the migration: the second run skips the table create (idempotent) but then re-runs the `CREATE UNIQUE INDEX IF NOT EXISTS` — fine because of `IF NOT EXISTS`. So this is recoverable, but the current migration's docstring overstates the idempotency guarantee given F-Q1-01.
- **Evidence**: lines 142-148 use `CREATE UNIQUE INDEX IF NOT EXISTS` (good).
- **Suggestion**: Once F-Q1-01 is fixed with a non-`now()` predicate, re-validate idempotency by running upgrade twice on a fresh DB.
- **Auto-fixable**: tied to F-Q1-01

### Finding F-Q1-12
- **Severity**: MINOR
- **Category**: contract
- **File**: `services/api-gateway/src/api_gateway/routes/proxy.py:2567` (`feedback_delete_submission`)
- **Confidence**: HIGH
- **Issue**: Gateway declares `status_code=200` on the DELETE proxy but forwards backend's status verbatim — when the backend returns 204, the gateway responds 204 (good in practice, but OpenAPI consumers expecting 200 will see a mismatch). The portfolio route itself returns 204 (`response_class=Response, response_model=None`) which avoids BP-064 — that is fine.
- **Evidence**: `@router.delete("/feedback/submissions/{submission_id}", status_code=200)` with `Response(content=resp.content, status_code=resp.status_code, ...)`. OpenAPI will show 200; runtime is 204.
- **Suggestion**: Set `status_code=204` on the FastAPI decorator and use `response_class=Response, response_model=None`.
- **Auto-fixable**: YES

### Finding F-Q1-13
- **Severity**: MINOR
- **Category**: contract
- **File**: `services/api-gateway/src/api_gateway/routes/proxy.py:2570-2575`
- **Confidence**: HIGH
- **Issue**: Gateway forwards `media_type="application/json"` even when the backend returns 204 with empty body. 204 with a `Content-Type` header is unusual but technically allowed — most strict clients ignore it, but it inflates wire size by a header that should not exist.
- **Evidence**: `Response(content=resp.content, status_code=resp.status_code, media_type="application/json")` for the DELETE proxy.
- **Suggestion**: Branch on `resp.status_code`: when 204, omit `media_type`.
- **Auto-fixable**: YES

### Finding F-Q1-14
- **Severity**: MINOR
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/api/routes/feedback.py:409-412`
- **Confidence**: HIGH
- **Issue**: `update_feature` does an inline `from portfolio.application.use_cases.feedback import UpdateFeatureRequestCommand, UpdateFeatureRequestUseCase` instead of adding it to the top-of-file imports. Hides the dependency, breaks IDE jump-to-definition, and makes audit harder.
- **Evidence**: lines 409-412 — local import.
- **Suggestion**: Move to the top-level import block.
- **Auto-fixable**: YES

### Finding F-Q1-15
- **Severity**: MINOR
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/application/use_cases/feedback.py:382-391`
- **Confidence**: MEDIUM
- **Issue**: `UpsertFeatureVoteUseCase` does a defensive `assert refreshed is not None` followed by a "very unlikely" branch that synthesises a `dataclasses.replace(refreshed, vote_count=new_count)`. If F-Q1-06 is fixed (atomic UPDATE), this drift-compensation logic becomes dead code.
- **Evidence**: lines 382-391 + comment "Very unlikely (same transaction)".
- **Suggestion**: After fixing F-Q1-06, simplify to a single fetch-after-update.
- **Auto-fixable**: tied to F-Q1-06

### Finding F-Q1-16
- **Severity**: MINOR
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/feedback_submission.py:135-137`
- **Confidence**: HIGH
- **Issue**: Local `from common.time import utc_now` imports inside `update()` and `delete()`. The same import is needed once at module top.
- **Evidence**: lines 135-137 in `update()`, similarly in `feature_request.py:121-123` and `beta_enrollment.py:47`.
- **Suggestion**: Hoist to module-level imports.
- **Auto-fixable**: YES

### Finding F-Q1-17
- **Severity**: MINOR
- **Category**: tests
- **File**: `services/portfolio/tests/unit/api/test_feedback_routes.py:283`
- **Confidence**: HIGH
- **Issue**: `test_feature_vote_idempotent_returns_count_one` does not assert on `v1.json()["has_voted"]` — only `v2`. Symmetric assertion missing.
- **Evidence**: line 283.
- **Suggestion**: Add `assert v1.json()["has_voted"] is True`.
- **Auto-fixable**: YES

### Finding F-Q1-18
- **Severity**: NIT
- **Category**: docs
- **File**: `services/portfolio/alembic/versions/0015_create_feedback_tables.py:140-141`
- **Confidence**: HIGH
- **Issue**: Comment says "this mirrors migration 0014's pattern" — 0014 is `unique_watchlist_member_instrument` and contains no time-based partial index. Misleading reference.
- **Suggestion**: Remove the false reference; document why the predicate is invalid (per F-Q1-01).
- **Auto-fixable**: YES

### Finding F-Q1-19
- **Severity**: NIT
- **Category**: contract
- **File**: `services/portfolio/src/portfolio/application/use_cases/feedback.py:160`
- **Confidence**: HIGH
- **Issue**: `redact(cmd.description) or ""` — description is required by the schema (`min_length=10`), so it never returns `None` or empty. The `or ""` branch is dead code.
- **Suggestion**: `redacted_description = redact(cmd.description)` (assert it's a str via the type system); or accept the dead defensive code as belt-and-suspenders.
- **Auto-fixable**: YES

### Finding F-Q1-20
- **Severity**: NIT
- **Category**: docs
- **File**: `docs/services/api-gateway.md:233-249`
- **Confidence**: HIGH
- **Issue**: Doc lists 13 endpoints (no row for `PATCH /v1/feedback/features/{id}`). Plan TRACKING.md says "12 endpoints, PII redaction, 66 tests" — the count keeps drifting. After F-Q1-05 is fixed, the gateway will expose 14, the portfolio 14, and the doc must be updated.
- **Suggestion**: Update the table after F-Q1-05.
- **Auto-fixable**: tied to F-Q1-05

### Finding F-Q1-21
- **Severity**: NIT
- **Category**: docs
- **File**: TRACKING.md, plan file, commit message
- **Confidence**: HIGH
- **Issue**: Commit `7fc90e5a` message reads "feat(PLAN-0051): Wave D — Alerts ACK + Snooze + History + Rule Manager" but the diff also contains all of PLAN-0052 Wave D (28 feedback files). Future archaeology will be confused — the feedback work is not findable by `git log --grep PLAN-0052`.
- **Suggestion**: Going forward, split mixed commits. (Cannot fix retroactively without a force-push to a shared branch.)
- **Auto-fixable**: NO

### Finding F-Q1-22
- **Severity**: ENHANCE
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/application/use_cases/feedback.py:149-190`
- **Confidence**: HIGH
- **Issue**: No outbox event emitted for new submissions. A bug submission with `severity=critical` should reach Slack/email at minimum; right now it dies silently in the DB. Plan §B-2-08 implies this exists; reality is just an INSERT.
- **Suggestion**: After the existing DB insert, write a `feedback.submission.created` event to the outbox with `kind`/`severity` so a downstream consumer can route critical bugs.
- **Auto-fixable**: NO

### Finding F-Q1-23
- **Severity**: ENHANCE
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/application/use_cases/feedback.py:241-247`
- **Confidence**: HIGH
- **Issue**: `DeleteFeedbackSubmissionUseCase` performs a hard `DELETE`. Once admin clicks delete, the submission and its console_logs (which may be the only way to debug a flaky bug) are gone. Soft-delete (`deleted_at TIMESTAMPTZ NULL`) is the safer default.
- **Suggestion**: Add `deleted_at` column in a follow-up migration; treat `DELETE` as `UPDATE … SET deleted_at = now()`. List queries filter `WHERE deleted_at IS NULL`.
- **Auto-fixable**: NO

### Finding F-Q1-24
- **Severity**: ENHANCE
- **Category**: architecture
- **File**: `services/portfolio/src/portfolio/api/feedback_schemas.py:46`, `services/portfolio/src/portfolio/config.py:109-111`
- **Confidence**: HIGH
- **Issue**: `feedback_s3_bucket` and `feedback_screenshot_ttl_days` are added to settings/config files, but no upload route exists — the field is a dangling dead config. The plan task T-D-4-04 mentioned "90d S3 TTL on screenshots; 7d on console logs" but the implementation only touches the columns, not the lifecycle. Frontend cannot upload a screenshot (the field is just a string).
- **Suggestion**: Either implement `POST /api/v1/feedback/screenshots` returning a pre-signed PUT URL (matches F-Q1-08), or remove the unused config keys until the upload path is built. Document explicitly which one.
- **Auto-fixable**: NO

---

## Summary table

| Severity | Count |
| --- | --- |
| BLOCKING | 1 |
| CRITICAL | 4 |
| MAJOR | 4 |
| MINOR | 8 |
| NIT | 4 |
| ENHANCE | 3 |
| **Total** | **24** |

## Verdict

**NEEDS-FIXES**

Blocking + critical findings (5 total) prevent the wave from working in production:

1. **F-Q1-01** — Migration 0015 is rejected by Postgres (verified empirically against the running container). Cannot deploy.
2. **F-Q1-02** — Admin role is unreachable from the gateway. All admin endpoints (5 routes) return 403.
3. **F-Q1-03** — Anonymous submission path crashes with `ValueError("badly formed UUID string")` on the system JWT's `sub`. All anon traffic 500s.
4. **F-Q1-04** — Anonymous submissions land under nil-UUID tenant; no admin can see them via standard list.
5. **F-Q1-05** — `PATCH /v1/feedback/features/{id}` (admin) has no gateway proxy; admins cannot move features through the roadmap states.

Recommended fix order: F-Q1-01 (migration) → F-Q1-03 (anon UUID) → F-Q1-02 (admin role) → F-Q1-05 (missing proxy) → F-Q1-04 (tenant routing) → F-Q1-06 (vote race) → rest.

Tests must be augmented to exercise the production system-JWT path (F-Q1-07) — the existing 66 tests pass while the production path is broken.
