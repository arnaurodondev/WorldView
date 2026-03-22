> **STATUS: IMPLEMENTED** — Wave-02 fully implemented (2026-03-20). Tasks C-002, W-006, W-007, C-003 complete. All tests written. docs/services/portfolio.md updated.

# Execution Prompt 0010 — portfolio-watchlist-intelligence-layer wave 02

## Context (read first)

- **Source**: Portfolio service gap analysis: `docs/ai-interactions/agent-responses/0006-response-20260319-portfolio-watchlist-gap-analysis.md`
- **Wave plan**: `docs/ai-interactions/agent-prompts/0010-exec-wave-portfolio-watchlist-intelligence-layer-plan.md`
- **Prerequisite**: Wave-01 must be completed. Specifically: `application/use_cases/watchlist.py` (W-004), `application/ports/cache.py` (`WatchlistCachePort`, `NoOpWatchlistCache`), all 6 use cases, and `domain/entities/alert_preference.py` (C-001) must exist.
- **Goal**: Implement the watchlist API surface (7 endpoints), wire the Valkey reverse-index cache (replacing `NoOpWatchlistCache` with `ValkeyWatchlistCache`), and build the complete alert preference stack (DB layer + use cases + 4 API endpoints). By the end of this wave the portfolio service has a fully implemented watchlist and alert preference feature with full test coverage.

---

## Assigned agent profile(s)

- `.claude/agents/backend-engineer.md`
- `.claude/agents/qa-test-engineer.md`

---

## Mandatory pre-read

Read **all** of these before writing any code:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/ai-interactions/BUG_PATTERNS.md` — scan for async ORM, Valkey/Redis, FastAPI dependency injection patterns
4. `docs/services/portfolio.md` — current state (will be updated by this wave)
5. `docs/ai-interactions/agent-responses/0006-response-20260319-portfolio-watchlist-gap-analysis.md` — Section 4 (gap details for watchlist API + cache + alert preferences) and Section 6 (open questions Q1 and Q2)
6. `services/portfolio/src/portfolio/application/use_cases/watchlist.py` — from wave-01 (especially `AddWatchlistMemberUseCase` cache call)
7. `services/portfolio/src/portfolio/application/ports/cache.py` — `WatchlistCachePort` from wave-01
8. `services/portfolio/src/portfolio/api/routes/portfolio.py` — reference for endpoint pattern
9. `services/portfolio/src/portfolio/api/dependencies.py` — existing dependency injection pattern
10. `libs/messaging/src/messaging/valkey/client.py` — `ValkeyClient` interface

When handing off, list all BUG_PATTERNS entries applied.

---

## Scope & Bounded write paths

Only touch paths listed per task. Do not refactor surrounding code.

---

## Task scope for this wave

**Tasks: C-002, W-006, W-007, C-003**

### Sequential chain — alert preference DB layer → watchlist API → Valkey cache → alert preference API

| Task ID | Short title | Primary paths | Depends on |
|---------|-------------|---------------|------------|
| C-002 | Alert preference DB layer + migration | `db/models/alert_preference.py`, `db/models/entity_suppression.py`, `db/repositories/alert_preference.py`, `application/ports/repositories.py`, `application/ports/unit_of_work.py`, `alembic/versions/0004_add_alert_preferences.py` | C-001 from wave-01 |
| W-006 | Watchlist API — 7 endpoints | `api/schemas.py`, `api/routes/watchlist.py`, `api/routes/__init__.py`, `api/error_mapping.py` | W-004 and W-005 from wave-01 |
| W-007 | Valkey reverse-index cache wiring | `infrastructure/cache/watchlist_cache.py`, `app.py`, `api/dependencies.py`, `config.py` | W-004 from wave-01, W-006 (dependencies.py pattern) |
| C-003 | Alert preference use cases + API | `application/use_cases/alert_preferences.py`, `api/schemas.py`, `api/routes/alert_preferences.py`, `api/routes/__init__.py` | C-002 |

C-002 and W-006 can run in parallel (no shared files). W-007 and C-003 should follow W-006 (for dependency injection patterns) and C-002 (for UoW wiring) respectively.

---

## Implementation instructions

---

### C-002 — Alert preference DB layer and migration

**Why:** `AlertPreference` and `EntitySuppression` domain entities from C-001 have no storage. The application layer has no repo ABCs for them. Without this, C-003 (use cases + API) cannot be implemented.

**How:**

1. **`application/ports/repositories.py`** — Add:
   - `AlertPreferenceRepository(ABC)`:
     - `async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> list[AlertPreference]`
     - `async def upsert(self, pref: AlertPreference) -> None`
   - `EntitySuppressionRepository(ABC)`:
     - `async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[EntitySuppression]`
     - `async def get(self, user_id: UUID, entity_id: UUID) -> EntitySuppression | None`
     - `async def save(self, suppression: EntitySuppression) -> None`
     - `async def delete(self, user_id: UUID, entity_id: UUID) -> None`

2. **`application/ports/unit_of_work.py`** — Add abstract properties `alert_preferences: AlertPreferenceRepository` and `entity_suppressions: EntitySuppressionRepository`.

3. **`infrastructure/db/models/alert_preference.py`** — Create `AlertPreferenceModel(Base)` per gap analysis Section 4-C DB design.

4. **`infrastructure/db/models/entity_suppression.py`** — Create `EntitySuppressionModel(Base)` per Section 4-C.

5. **`alembic/versions/0004_add_alert_preferences.py`** — Create migration (after 0003):
   - Create `alert_preferences` table with `uq_alert_preferences_user_type` unique constraint and `ix_alert_preferences_user_id` index.
   - Create `entity_suppressions` table with `uq_entity_suppressions_user_entity` unique constraint and indexes on `user_id` and `entity_id`.
   - Run `alembic check` — must produce no diff.

6. **`infrastructure/db/repositories/alert_preference.py`** — Implement `SqlAlchemyAlertPreferenceRepository` and `SqlAlchemyEntitySuppressionRepository`:
   - For `upsert`, use `pg_insert(...).on_conflict_do_update(index_elements=["user_id", "alert_type"], set_={"enabled": ..., "updated_at": ...})`.

7. **`infrastructure/db/unit_of_work.py`** — Wire `alert_preferences` and `entity_suppressions` repos in `__aenter__` and add concrete properties.

8. **`infrastructure/db/models/__init__.py`** — Register both new models.

9. **`tests/unit/fakes.py`** — Add `FakeAlertPreferenceRepository` and `FakeEntitySuppressionRepository` in-memory implementations. Wire into `FakeUnitOfWork`.

**Tests (mandatory):**
- `alembic check` exits 0 after migration 0004.
- `tests/unit/test_use_cases_alert_preferences.py` (added in C-003) will exercise fakes implicitly.

**Documentation:** `docs/services/portfolio.md` — update DB schema section to add `alert_preferences` and `entity_suppressions` tables.

---

### W-006 — Watchlist API endpoints (7 routes)

**Why:** Users have no HTTP interface to manage watchlists. The 6 use cases from wave-01 are implemented but unreachable.

**How:**

1. **`api/schemas.py`** — Add:
   - `WatchlistCreateRequest(BaseModel)`: `name: str`
   - `WatchlistResponse(BaseModel)`: `id`, `tenant_id`, `user_id`, `name`, `status`, `created_at`
   - `WatchlistMemberCreateRequest(BaseModel)`: `entity_id: UUID`, `entity_type: str = "company"`
   - `WatchlistMemberResponse(BaseModel)`: `id`, `watchlist_id`, `entity_id`, `entity_type`, `added_at`

2. **`api/routes/watchlist.py`** — Create 6 endpoints (omit reverse-index — see open question Q1 note below):
   - `POST /watchlists` → `CreateWatchlistUseCase` → 201
   - `GET /watchlists` → `ListWatchlistsUseCase` → 200 `list[WatchlistResponse]`
   - `GET /watchlists/{watchlist_id}` → `GetWatchlistUseCase` → 200
   - `DELETE /watchlists/{watchlist_id}` → `DeleteWatchlistUseCase` → 204
   - `POST /watchlists/{watchlist_id}/members` → `AddWatchlistMemberUseCase` → 201
   - `DELETE /watchlists/{watchlist_id}/members/{entity_id}` → `RemoveWatchlistMemberUseCase` → 204

   All endpoints require `X-Tenant-ID: UUID` and `X-Owner-ID: UUID` request headers (same pattern as existing routes).

   **On Q1 (reverse-index endpoint):** Per the gap analysis recommendation (Option C), the alert service (S10) will consume `portfolio.watchlist.updated.v1` events directly. Therefore, do **not** implement `GET /watchlists/reverse/{entity_id}` in this wave. Add a comment in `routes/watchlist.py` referencing the open question.

3. **`api/routes/__init__.py`** — Register `watchlist_router` with prefix `/watchlists`.

4. **`api/error_mapping.py`** — Add error mappings:
   - `WatchlistNotFoundError` → 404
   - `WatchlistAlreadyExistsError` → 409
   - `WatchlistMemberNotFoundError` → 404
   - `WatchlistMemberAlreadyExistsError` → 409

5. **Dependency injection for `WatchlistCachePort`**: In `api/dependencies.py`, expose `WatchlistCacheDep` that returns a `NoOpWatchlistCache` by default. W-007 will replace this with `ValkeyWatchlistCache` once the client is wired.

**Tests (mandatory — full integration coverage):**
- `tests/integration/test_watchlist_api.py`:
  - `test_create_watchlist_returns_201`
  - `test_create_watchlist_duplicate_name_returns_409`
  - `test_list_watchlists_returns_user_watchlists_only`
  - `test_get_watchlist_returns_200`
  - `test_get_watchlist_not_found_returns_404`
  - `test_get_watchlist_wrong_owner_returns_403`
  - `test_delete_watchlist_returns_204`
  - `test_add_member_returns_201`
  - `test_add_member_duplicate_returns_409`
  - `test_remove_member_returns_204`
  - `test_remove_member_not_found_returns_404`

All integration tests must use `TestClient` with `testcontainers` Postgres (or existing integration test DB fixture).

**Documentation:** `docs/services/portfolio.md` — add Watchlist API table (all 6 routes, request/response schemas, error cases).

---

### W-007 — Valkey reverse-index cache wiring

**Why:** The wave-01 use cases call `cache.invalidate_entity(entity_id)` on a `NoOpWatchlistCache` stub. For the Intelligence Layer alerting fanout to work, a real Valkey reverse-index must be maintained. `config.py` already has `valkey_url` but `app.py` never creates a `ValkeyClient`.

**How:**

1. **`config.py`** — Add `watchlist_cache_ttl_seconds: int = 300`.

2. **`application/ports/cache.py`** (already created in wave-01) — no changes needed.

3. **`infrastructure/cache/watchlist_cache.py`** (new file) — Implement `ValkeyWatchlistCache(WatchlistCachePort)`:
   - Key: `pf:v1:watchlist:entity:{entity_id}` (Redis Set — `SADD`/`SMEMBERS`/`DEL`/`SREM`).
   - `get_user_ids(entity_id)`: `SMEMBERS key` → decode to `list[UUID]`. Return `[]` on miss.
   - `invalidate_entity(entity_id)`: `DEL key`.
   - `set_user_ids(entity_id, user_ids, ttl)`: `DEL key`, then `SADD key *user_ids`, then `EXPIRE key ttl`.

4. **`app.py`** — In lifespan, after DB engine setup:
   ```python
   from libs.messaging.valkey.client import ValkeyClient, ValkeyConfig
   valkey_client = ValkeyClient(config=ValkeyConfig(url=settings.valkey_url))
   app.state.valkey_client = valkey_client
   ```
   In shutdown, close the client.

5. **`api/dependencies.py`** — Replace `NoOpWatchlistCache` with:
   ```python
   async def get_watchlist_cache(request: Request) -> WatchlistCachePort:
       return ValkeyWatchlistCache(
           client=request.app.state.valkey_client,
           ttl=request.app.state.settings.watchlist_cache_ttl_seconds,
       )
   WatchlistCacheDep = Annotated[WatchlistCachePort, Depends(get_watchlist_cache)]
   ```

6. Update `api/routes/watchlist.py` to inject `WatchlistCacheDep` into `add_member` and `remove_member` endpoints and pass it to the use cases.

**Tests (mandatory):**
- `tests/unit/test_watchlist_cache.py` — using `fakeredis.aioredis.FakeRedis` injected into `ValkeyClient._redis`:
  - `test_invalidate_entity_deletes_key`
  - `test_set_user_ids_populates_set`
  - `test_get_user_ids_returns_list_from_set`
  - `test_get_user_ids_returns_empty_on_miss`
- `tests/integration/test_watchlist_reverse_index.py` — real Valkey via `testcontainers` (or mock if not available):
  - `test_add_member_populates_cache_after_invalidation` — call add_member API, then `GET /watchlists/reverse/{entity_id}` (if implemented) or query cache directly; confirm key exists.
  - `test_remove_member_invalidates_cache` — call remove_member, confirm key is deleted.

**Documentation:** `docs/services/portfolio.md` — add Observability/Cache section: Valkey key taxonomy, TTL, invalidation trigger.

---

### C-003 — Alert preference use cases and API (4 routes)

**Why:** Users have no way to configure alert preferences. The alerting service (S10) cannot query preferences without this endpoint.

**How:**

1. **`application/use_cases/alert_preferences.py`** — Implement:
   - `GetAlertPreferencesUseCase`: fetch `uow.alert_preferences.get_by_user(user_id, tenant_id)` and `uow.entity_suppressions.list_by_user(user_id, tenant_id)`. If no preference row exists for an `AlertType`, default to `enabled=True`.
   - `UpsertAlertPreferenceUseCase`: validate `alert_type` is a known `AlertType` value; call `uow.alert_preferences.upsert(AlertPreference(...))`.
   - `SetEntitySuppressionUseCase`: save an `EntitySuppression`.
   - `RemoveEntitySuppressionUseCase`: fetch suppression; raise `AlertPreferenceNotFoundError` if absent; delete.

   **On Q2 (alert service access):** Per the response recommendation, prefer Option D (S10 caches preferences locally with short TTL fetched from Portfolio on demand). Document this as a comment in the use case file. Do not implement a Kafka topic for preference changes in this wave — it can be deferred.

2. **`api/schemas.py`** — Add:
   - `AlertPreferenceResponse(BaseModel)`: `alert_type`, `enabled`, `updated_at`
   - `AlertPreferenceUpdateRequest(BaseModel)`: `enabled: bool`
   - `EntitySuppressionResponse(BaseModel)`: `entity_id`, `suppressed_at`
   - `EntitySuppressionCreateRequest(BaseModel)`: `entity_id: UUID`
   - `AlertPreferencesListResponse(BaseModel)`: `preferences: list[AlertPreferenceResponse]`, `suppressions: list[EntitySuppressionResponse]`

3. **`api/routes/alert_preferences.py`** — Create 4 endpoints:
   - `GET /alert-preferences` → `GetAlertPreferencesUseCase` → 200 `AlertPreferencesListResponse`
   - `PUT /alert-preferences/{alert_type}` → `UpsertAlertPreferenceUseCase` → 200 `AlertPreferenceResponse`
   - `POST /alert-preferences/suppressions` → `SetEntitySuppressionUseCase` → 201 `EntitySuppressionResponse`
   - `DELETE /alert-preferences/suppressions/{entity_id}` → `RemoveEntitySuppressionUseCase` → 204

   All endpoints require `X-Tenant-ID` and `X-Owner-ID` headers.

4. **`api/routes/__init__.py`** — Register `alert_preferences_router` with prefix `/alert-preferences`.

5. **`api/error_mapping.py`** — Add `AlertPreferenceNotFoundError` → 404.

**Tests (mandatory — full coverage):**
- `tests/unit/test_use_cases_alert_preferences.py`:
  - `test_get_alert_preferences_returns_defaults_when_empty`
  - `test_get_alert_preferences_returns_existing_rows`
  - `test_upsert_preference_persists_enabled_false`
  - `test_upsert_invalid_alert_type_raises`
  - `test_set_entity_suppression`
  - `test_remove_entity_suppression_not_found_raises`

- `tests/integration/test_alert_preferences_api.py`:
  - `test_get_alert_preferences_returns_200_with_defaults`
  - `test_put_preference_returns_200`
  - `test_put_invalid_alert_type_returns_422`
  - `test_post_suppression_returns_201`
  - `test_delete_suppression_returns_204`
  - `test_delete_suppression_not_found_returns_404`

**Documentation:** `docs/services/portfolio.md` — add Alert Preferences API table (all 4 routes, schemas, error cases). Add DB schema entries for `alert_preferences` and `entity_suppressions` tables.

---

## Task-scoped fail-fast gate (mandatory)

After **each** task:

1. Run `ruff check` on changed files.
2. Run `mypy` on changed packages.
3. Run targeted tests for that task.
4. `alembic check` exits 0 (after C-002).

Fix failures before starting the next task.

---

## Regression guardrails

Before marking wave-02 done:

1. `make test` passes in `services/portfolio` — all tests (including 253+ from before wave-01 plus all wave-01 and wave-02 new tests) pass.
2. `alembic check` exits 0 (4 migrations applied: 0001, 0002, 0003, 0004).
3. All 6 watchlist integration tests pass (W-006).
4. All cache unit tests pass (W-007).
5. All 6 alert preference integration tests pass (C-003).
6. `docs/services/portfolio.md` accurately describes all new endpoints, schemas, DB tables, and Valkey config.
7. No cross-service FK in any migration.
8. No `datetime.now()` without `tz=` in any modified file.

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|------------------|
| `docs/services/portfolio.md` | **Watchlist section**: 6 endpoint table, request/response schemas, error cases (W-006). **Alert Preferences section**: 4 endpoint table, schemas, error cases (C-003). **DB Schema section**: add `alert_preferences`, `entity_suppressions` tables (C-002). **Config**: add `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` (W-007). **Observability/Cache**: Valkey key taxonomy and invalidation strategy (W-007). |

The documentation quality standard (accuracy, realistic examples, common pitfalls, no orphans) from `0000-exec-wave-generation-template.md` applies. Add at least 2 new Common Pitfalls entries:
- "Alert preferences default to enabled=True when no row exists — do not treat a missing row as disabled."
- "Watchlist reverse-index cache may be stale briefly after member mutation — always treat it as eventually consistent."

---

## Done criteria (wave-02 complete when all pass)

- [ ] 6 watchlist API endpoints implemented; all integration tests pass.
- [ ] `WatchlistCacheDep` injects `ValkeyWatchlistCache` (not `NoOpWatchlistCache`) in production path.
- [ ] `ValkeyClient` instantiated in `app.py` lifespan.
- [ ] `PORTFOLIO_WATCHLIST_CACHE_TTL_SECONDS` configurable.
- [ ] Cache unit tests (fakeredis) pass for get/set/invalidate.
- [ ] C-002: `alert_preferences` and `entity_suppressions` tables created via migration 0004; `alembic check` exits 0.
- [ ] C-003: 4 alert preference endpoints implemented; all integration tests pass.
- [ ] `docs/services/portfolio.md` fully updated (watchlist, alert preferences, DB schema, config, cache, pitfalls).
- [ ] `make test` passes — full portfolio test suite (no regressions, new tests all green).
- [ ] Ruff and mypy clean on all modified files.

---

## Handoff evidence required

1. Task IDs completed + changed files per task.
2. `alembic check` output (exit 0 with all 4 migrations).
3. `make test` output: total pass count.
4. Integration test output: watchlist (11+ tests) and alert preference (6+ tests) pass counts.
5. Cache unit test output: all 4+ tests pass.
6. BUG_PATTERNS entries applied.
7. **Documentation quality checklist:**

| Criterion | Status | Notes |
|-----------|--------|-------|
| Accuracy — all endpoints, schemas, config in portfolio.md match implementation | ✓ / N/A | |
| Realistic code examples for watchlist and alert preference routes | ✓ / N/A | |
| Common pitfalls (≥2 new entries) | ✓ | |
| No orphan documentation | ✓ | |
| Service docs reflect final state | ✓ | List sections updated |

8. Exact list of documentation sections updated.
9. Proposed commit message.

---

## Proposed commit message (template)

```
feat(portfolio): watchlist API + Valkey cache, alert preferences full stack

- Implement 6 watchlist REST endpoints (POST/GET/DELETE watchlists and members);
  wire WatchlistCachePort → ValkeyWatchlistCache via app.state.valkey_client.
- Add alert_preferences and entity_suppressions tables (migration 0004);
  implement GetAlertPreferences, UpsertAlertPreference, SetEntitySuppression,
  RemoveEntitySuppression use cases and 4 REST endpoints.
- Update docs/services/portfolio.md: watchlist API, alert preferences, DB schema,
  Valkey config/cache, and 2 new common pitfall entries.

Validated: 253+ existing + all new tests pass; alembic check clean;
           ruff and mypy clean; fakeredis and integration cache tests pass.
```

---

## Full scope completion note

When **both wave-01 and wave-02** are completed and merged, update the following files to `IMPLEMENTED`:
- `docs/ai-interactions/agent-prompts/0010-exec-portfolio-watchlist-intelligence-layer-wave-01.md`
- `docs/ai-interactions/agent-prompts/0010-exec-portfolio-watchlist-intelligence-layer-wave-02.md` (this file)
- `docs/ai-interactions/agent-prompts/0010-exec-wave-portfolio-watchlist-intelligence-layer-plan.md`
