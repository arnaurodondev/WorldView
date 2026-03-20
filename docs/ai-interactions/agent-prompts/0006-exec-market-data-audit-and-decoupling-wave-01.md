> **STATUS: IMPLEMENTED** — All tasks in this wave have been completed and merged. See git history for implementation evidence.

# Execution Prompt 0006 — market-data audit and decoupling wave 01

## Context (read first)

- **Source**: Codebase audit of `services/market-data` conducted 2026-03-12. This prompt is the authoritative scope; there is no separate planning document. The audit covered: all DB models and migrations, API routers and endpoints, fundamentals consumer and query layer, session/UoW wiring, and config.
- **Source planning context links**: N/A — no `agent-planning/0006-*.md` or `agent-responses/0006-*.md`; this wave is scoped entirely from this prompt and the audit.
- **Goal**: Fix fundamentals read-side gaps (5 sections missing from query map, no section endpoints), clarify API semantics (security_id vs instrument_id), improve list endpoints (filters in DB where applicable), and enable read/write DB decoupling so that switching to a separate Postgres or TimescaleDB instance is a config change only.

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/backend-engineer.md`
- Prefer same patterns as in `docs/ai-interactions/agent-prompts/0005-exec-eodhd-pipeline-fixes-and-extensions-wave-01.md` for task structure and validation.

---

## Mandatory pre-read

Read **all** of these before writing any code:

1. `AGENTS.md` — coding standards, naming conventions, architecture patterns
2. `CLAUDE.md` — fail-fast validation loop, task-scoped gates, no deferred fixes
3. `docs/services/market-data.md` — current API surface, DB schema, consumers, UoW
4. `docs/ai-interactions/BUG_PATTERNS.md` — entries relevant to async ORM, idempotency, datetime
5. `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py` — current `_SECTION_MODEL_MAP` and `query_fundamentals`
6. `services/market-data/src/market_data/infrastructure/db/session.py` — `build_write_engine` / `build_read_engine`
7. `services/market-data/src/market_data/app.py` — lifespan: engine and UoW factory wiring
8. `services/market-data/src/market_data/api/dependencies.py` — `get_uow` and session factory usage

When handing off, explicitly list which BUG_PATTERNS entries (if any) were applied.

---

## Scope & Token Budget

- **Bounded write paths** (do not edit outside without explicit justification):
  - `services/market-data/src/market_data/config.py`
  - `services/market-data/src/market_data/app.py`
  - `services/market-data/src/market_data/api/dependencies.py`
  - `services/market-data/src/market_data/api/routers/fundamentals.py`
  - `services/market-data/src/market_data/infrastructure/db/session.py`
  - `services/market-data/src/market_data/infrastructure/db/uow.py`
  - `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py`
  - `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py`
  - `services/market-data/configs/dev.local.env.example`
  - `services/market-data/configs/prod.env.example` (if present)
  - `docs/services/market-data.md`
  - New or updated tests under `services/market-data/tests/`

---

## Objective

By the end of this wave:

1. **Fundamentals read-side**: All 18 fundamentals sections are queryable via the existing API. The read-side query helper (`fundamentals_query.py`) includes all 18 sections in its model map, with correct row→domain mapping for both mixin-based tables and `company_profiles` (which has no `period_type`/`period_end_date`).
2. **Fundamentals section endpoints**: Dedicated GET routes exist for the five sections that currently have no route: highlights, company-profile, institutional-holders, fund-holders, insider-transactions-snapshot (path segments: `highlights`, `company-profile`, `institutional-holders`, `fund-holders`, `insider-transactions-snapshot`).
3. **API semantics**: The fundamentals path parameter is documented as **instrument_id** (the ID of the instrument whose fundamentals we are fetching). Optionally add a short note in the API doc or OpenAPI description that "historically named security_id in the path but represents instrument UUID". No path rename is required in this wave unless the team prefers a breaking rename to `/fundamentals/{instrument_id}` (if so, do it and document).
4. **List instruments**: Filters (`has_ohlcv`, `has_quotes`, `has_fundamentals`, `exchange`) are applied in the **database** (WHERE clause) instead of in-memory after search. The repository (or a new query helper) accepts these filters and the router passes them through.
5. **List securities**: Either add a proper "list all" (with optional limit/offset) to the security repository and router, or document clearly in `docs/services/market-data.md` that "list without figi/isin returns empty" and add a note in the API response schema/description. Prefer implementing a simple list with limit/offset if the repository can support it without large refactors.
6. **Read/write DB decoupling**: (a) `Settings` has an optional `read_replica_url` (or equivalent name). (b) App lifespan builds both write and read engines and two session factories; the UoW factory receives `(write_factory, read_factory)`. (c) For "same URL for both", leaving `read_replica_url` unset means the read engine uses `database_url`. (d) Read-only operations (fundamentals query, instrument search/list, OHLCV/quote reads if any go through a session) use the **read** session. Repositories that only read must use the read session when invoked from API handlers; repositories that write continue to use the write session. The UoW must expose or use the read session for read-only repo operations (e.g. a dedicated read-only accessor or wiring `query_fundamentals` and instrument/ohlcv/quote reads to the read session).

---

## Task scope

**Total tasks: 8**

### Parallel group A — fundamentals read-side and section endpoints (no cross-dependencies)

| Task ID    | Short title | Primary paths |
|-----------|-------------|----------------|
| AUDIT-FQ1 | Add 5 missing sections to fundamentals read-side map and row→domain mapping for company_profiles | `fundamentals_query.py` |
| AUDIT-FQ2 | Add 5 section GET endpoints (highlights, company-profile, institutional-holders, fund-holders, insider-transactions-snapshot) | `api/routers/fundamentals.py` |

### Sequential dependency

- AUDIT-FQ2 may use the same `_fetch_section` helper and response model; it depends on AUDIT-FQ1 so that the new sections return data (not empty) once the map is complete.

### Parallel group B — API semantics and list improvements

| Task ID    | Short title | Primary paths |
|-----------|-------------|----------------|
| AUDIT-API1 | Document fundamentals path param as instrument_id; optionally rename path to /fundamentals/{instrument_id} | `api/routers/fundamentals.py`, `docs/services/market-data.md` |
| AUDIT-API2 | Push list-instruments filters (has_ohlcv, has_quotes, has_fundamentals, exchange) to DB | `instrument_repo.py`, `api/routers/instruments.py` |
| AUDIT-API3 | List securities: add list-all with limit/offset or document limitation | `application/ports/repositories.py`, `security_repo.py`, `api/routers/securities.py` and/or `docs/services/market-data.md` |

### Parallel group C — read/write decoupling

| Task ID    | Short title | Primary paths |
|-----------|-------------|----------------|
| AUDIT-DB1 | Add read_replica_url to Settings; build read engine and read factory in app lifespan; pass (write_factory, read_factory) to UoW | `config.py`, `app.py`, `api/dependencies.py` |
| AUDIT-DB2 | Wire read session to read-only operations (query_fundamentals, instrument find/search, ohlcv/quote reads) | `uow.py`, `fundamentals_query.py`, dependencies or router layer |

### Documentation (mandatory after implementation)

| Task ID     | Short title |
|------------|-------------|
| AUDIT-DOC1 | Update docs/services/market-data.md: API table (new section endpoints, path param semantics), list endpoints behavior, env vars (read_replica_url), Data Access Layer (read vs write session usage). Add or update Common Pitfalls. |

---

## Implementation instructions

---

### AUDIT-FQ1 — Add 5 missing sections to fundamentals read-side

**Why:** `fundamentals_query._SECTION_MODEL_MAP` currently has 14 entries. The enum `FundamentalsSection` has 18 values. The missing sections are: HIGHLIGHTS, COMPANY_PROFILE, INSTITUTIONAL_HOLDERS, FUND_HOLDERS, INSIDER_TRANSACTIONS_SNAPSHOT. As a result, `GET /fundamentals/{id}` and any section-specific endpoint that goes through `query_fundamentals` return empty for these five sections even when data exists in the DB.

**How:**

1. In `fundamentals_query.py`, add to `_SECTION_MODEL_MAP`:
   - `FundamentalsSection.HIGHLIGHTS` → `HighlightsModel`
   - `FundamentalsSection.COMPANY_PROFILE` → `CompanyProfileModel`
   - `FundamentalsSection.INSTITUTIONAL_HOLDERS` → `InstitutionalHoldersModel`
   - `FundamentalsSection.FUND_HOLDERS` → `FundHoldersModel`
   - `FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT` → `InsiderTransactionsSnapshotModel`
2. Import the five model classes from `market_data.infrastructure.db.models.fundamentals` (they are already exported from the package).
3. **CompanyProfileModel** does not use `FundamentalsModelMixin`; it has no `period_type` or `period_end_date` columns. Implement a separate branch in the query logic for `COMPANY_PROFILE`:
   - Query `CompanyProfileModel` by `instrument_id` (single row per instrument).
   - Map the row to `FundamentalsRecord`: use `ingested_at` as `period_end`, `PeriodType.SNAPSHOT` for `period_type`, `row.data` for `data`, `row.instrument_id` for `security_id` (domain field name). Set `source` from a column if present, else empty string.
4. Ensure `query_fundamentals` (or a small helper) uses the correct model and row→domain mapping for `COMPANY_PROFILE` so that the API response shape remains consistent (FundamentalsRecord → FundamentalsRecordResponse).

**Tests:**

- Unit test: for each of the 5 sections, given a session with one inserted row (or use existing integration fixtures), call `query_fundamentals(uow, instrument_id, section)` and assert the result list has length ≥ 1 and the first record’s `section` and `data` (or key fields) match. For COMPANY_PROFILE, assert `period_type == SNAPSHOT` and `period_end` is set (e.g. from `ingested_at`).
- If integration tests already exist for fundamentals API, run them and add one test that requests the full fundamentals response and asserts that at least one of the previously missing sections (e.g. highlights or company_profile) can appear in the response when data exists.

**Documentation:** Covered in AUDIT-DOC1 (no separate doc file for this task).

---

### AUDIT-FQ2 — Add 5 section GET endpoints

**Why:** The service doc lists "Full fundamentals (all 18 sections)" but only 7 section-specific routes exist (income-statement, balance-sheet, cash-flow, valuation, analyst-consensus, dividends, earnings). Clients cannot request highlights, company-profile, institutional-holders, fund-holders, or insider-transactions-snapshot by section without fetching the full payload.

**How:**

1. In `api/routers/fundamentals.py`, add five new GET routes following the existing pattern:
   - `GET /fundamentals/{security_id}/highlights` → `_fetch_section(..., FundamentalsSection.HIGHLIGHTS)`
   - `GET /fundamentals/{security_id}/company-profile` → `_fetch_section(..., FundamentalsSection.COMPANY_PROFILE)`
   - `GET /fundamentals/{security_id}/institutional-holders` → `_fetch_section(..., FundamentalsSection.INSTITUTIONAL_HOLDERS)`
   - `GET /fundamentals/{security_id}/fund-holders` → `_fetch_section(..., FundamentalsSection.FUND_HOLDERS)`
   - `GET /fundamentals/{security_id}/insider-transactions-snapshot` → `_fetch_section(..., FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT)`
2. Use the same `FundamentalsResponse` and `_to_record_response` as existing section endpoints. Path parameter name can remain `security_id` (see AUDIT-API1 for semantics).
3. Register routes in the same order as other section routes (no path ordering conflict with the generic `GET /fundamentals/{security_id}`).

**Tests:**

- Unit test: for each new route, mock UoW/query to return one record; assert status 200 and response body contains the expected section data.
- Optional: integration test that hits one of the new endpoints with a real DB row and asserts non-empty records.

**Documentation:** AUDIT-DOC1 will update the API table in `docs/services/market-data.md` with the 5 new paths.

---

### AUDIT-API1 — Document fundamentals path param as instrument_id

**Why:** The path is `/fundamentals/{security_id}` but the implementation treats the value as `instrument_id` (FK in fundamentals tables). This is confusing for API consumers and can lead to wrong usage (e.g. passing a security UUID that does not match any instrument).

**How:**

1. In `docs/services/market-data.md`, in the API Surface table and in any paragraph describing the fundamentals endpoints, state clearly that the path parameter is the **instrument UUID** (not the security UUID). Add a line such as: "Path parameter `security_id` is the instrument ID; fundamentals are stored per instrument."
2. Optionally in code: add a short OpenAPI description on the `get_fundamentals` and section endpoints: e.g. "Returns fundamentals for the given instrument (path parameter is instrument UUID)."
3. **Optional breaking change**: Rename the path parameter to `instrument_id` and the route to `/fundamentals/{instrument_id}` (and section routes to `/fundamentals/{instrument_id}/...`). If you do this, update all docs and any gateway or client references in the repo. If not done in this wave, the doc clarification above is sufficient.

**Tests:** No code logic change if only docs + OpenAPI description; no new tests required. If you rename the path, add a quick E2E or router test that the new path works.

**Documentation:** AUDIT-DOC1.

---

### AUDIT-API2 — Push list-instruments filters to DB

**Why:** Currently `list_instruments` calls `uow.instruments.search(query)` and then filters the result list in Python by `has_ohlcv`, `has_quotes`, `has_fundamentals`, and `exchange`. For large result sets this is inefficient and does not scale.

**How:**

1. Extend `InstrumentRepository` (port) with a method that supports optional filters, e.g. `search(query: str, *, has_ohlcv: bool | None = None, has_quotes: bool | None = None, has_fundamentals: bool | None = None, exchange: str | None = None, limit: int = 100, offset: int = 0) -> list[Instrument]` (or keep `search` and add `list_with_filters`). The implementation must add WHERE conditions for each non-None filter.
2. In `instrument_repo.py` (PgInstrumentRepository), implement the new signature: build a SQL SELECT with optional filters and apply limit/offset. Preserve existing behavior when all filters are None (e.g. same as current search).
3. In `api/routers/instruments.py`, replace the current flow (search then in-memory filter and slice) with a single call to the repository passing `has_ohlcv`, `has_quotes`, `has_fundamentals`, `exchange`, `limit`, `offset`. Return total count: either from a separate COUNT query or from the same query with a window/count (repository contract must support the response shape: items + total).
4. Ensure pagination (limit/offset) is applied in the DB so that the response is bounded.

**Tests:**

- Unit test: mock repository returns filtered list; assert router response items and total.
- Integration test: insert instruments with different flag/exchange values; call list endpoint with filters and assert only matching instruments are returned and count is correct.

**Documentation:** AUDIT-DOC1 (list instruments behavior and parameters).

---

### AUDIT-API3 — List securities: list-all or document limitation

**Why:** `GET /securities` without query params returns empty because the repository has no "list all" method; only find_by_figi and find_by_isin are used. This is surprising for clients and limits usability.

**How (choose one):**

- **Option A (preferred):** Add a repository method that lists securities with optional limit/offset (e.g. `list(limit: int = 100, offset: int = 0) -> tuple[list[Security], int]` or similar). Implement in `security_repo.py` with a simple `SELECT ... ORDER BY id LIMIT :limit OFFSET :offset` and a separate or combined count. Expose in the router: when no figi/isin is provided, call this list method and return paginated results.
- **Option B:** Do not add list-all. In `docs/services/market-data.md`, document clearly: "GET /securities without figi or isin returns an empty list; use query parameters to look up by FIGI or ISIN." Add a short description in the OpenAPI for the list endpoint. No repository change.

Implement Option A unless there is a strong reason (e.g. very large securities table and no indexing) to defer.

**Tests:**

- If Option A: unit test for repository list (with limit/offset); integration test for GET /securities with no params returning a non-empty list when DB has rows.
- If Option B: no new tests; doc-only.

**Documentation:** AUDIT-DOC1.

---

### AUDIT-DB1 — Add read_replica_url and wire two engines in app

**Why:** The codebase already has `build_read_engine(settings)` and UoW accepts `(write_factory, read_factory)`, but the app only builds one engine and passes the same factory twice. To support read replicas (or a future separate Postgres/TimescaleDB for reads), we need two URLs and two session factories. For "same URL for both", leaving the read URL unset uses the primary URL.

**How:**

1. In `config.py` (Settings), add:
   - `read_replica_url: str | None = None`
   - Document in the docstring or comment: "If set, read-only queries use this URL (e.g. read replica). If None, reads use database_url."
2. In `app.py` lifespan:
   - Call `build_read_engine(settings)` in addition to `build_write_engine(settings)`.
   - Build two session factories: `write_factory = build_session_factory(write_engine)`, `read_factory = build_session_factory(read_engine)`.
   - Store both on app.state if needed (e.g. `app.state.write_session_factory`, `app.state.read_session_factory`).
   - Change the UoW factory to `SqlAlchemyUnitOfWork(write_factory, read_factory)`.
3. In `api/dependencies.py`, obtain both factories from app.state and pass them to `SqlAlchemyUnitOfWork(write_factory, read_factory)` so that each request gets a UoW with write and read sessions.
4. Ensure `session.py`'s `build_read_engine` uses `getattr(settings, "read_replica_url", None) or settings.database_url` so that when `read_replica_url` is None, the read engine points to the same DB.
5. Update `configs/dev.local.env.example` and any prod example: add a commented line such as `# MARKET_DATA_READ_REPLICA_URL=postgresql+asyncpg://...` with a short comment that it is optional and defaults to DATABASE_URL.

**Tests:**

- Unit or integration test: create Settings with `read_replica_url=None`, build read engine, assert the URL used is the same as database_url. With `read_replica_url` set, assert the read engine uses that URL.
- No change to existing repository tests unless they depend on UoW construction (then ensure they pass with two factories).

**Documentation:** AUDIT-DOC1 (env vars, Data Access Layer).

---

### AUDIT-DB2 — Use read session for read-only operations

**Why:** Even with two engines, all repositories are currently bound to the write session. Read traffic should use the read session so that when a read replica is configured, it is actually used.

**How:**

1. In `uow.py`, the UoW already has `_read_session`. Expose a way for read-only operations to use it. Options:
   - (a) Add a method or property that returns the read session for "query" use cases, and have the API layer (or a dedicated query service) use that session when calling read-only helpers; or
   - (b) Add read-only repository accessors that are bound to `_read_session` (e.g. `instruments_read`, `fundamentals_query_read`). The fundamentals API currently uses `query_fundamentals(uow, ...)` which internally uses `uow._write()`. Change that to use the read session for the SELECT only.
2. **Fundamentals:** In `fundamentals_query.py`, `query_fundamentals` currently takes `uow` and uses `uow._write()` (via private access to SqlAlchemyUnitOfWork). Change the contract so that it uses the **read** session: either pass the read session explicitly, or add a UoW method like `get_read_session()` and use that inside `query_fundamentals`. Ensure no other caller of `query_fundamentals` relies on it running in the write transaction.
3. **Instruments:** InstrumentRepository is used for both writes (consumers, upsert) and reads (find_by_id, find_by_symbol_exchange, search/list). The reads in the API layer should use the read session. Options: (i) Split into read and write repos (larger refactor), or (ii) Have the UoW pass the read session to a "query" path. Simplest approach: from the API dependency, when calling methods that are read-only (find_by_id, find_by_symbol_exchange, search/list_with_filters), use a repository instance that is bound to the read session. That requires the UoW to expose a read-bound instrument repository (e.g. `instruments_read`) that uses `_read_session`, and the router to use that for GETs. Implement the minimal change: e.g. add `instruments_read` property that returns `PgInstrumentRepository(self._read_session)` and use it in the instruments and securities routers for all read operations.
4. **OHLCV and Quotes:** Similarly, if the OHLCV and quote repositories are only read in the API (and written only in consumers), use the read session for the API-side repo. Add `ohlcv_read`, `quotes_read` (or equivalent) on the UoW bound to the read session, and use them in the ohlcv and quotes routers.
5. Ensure consumers and outbox dispatcher still use only the write session (they already do via the existing repo accessors).

**Tests:**

- Integration test: with two different database URLs (e.g. two in-memory SQLite or two Postgres DBs), set read_replica_url to the second; run a read-only API request (e.g. GET fundamentals or GET instruments) and verify the query hits the read engine (e.g. via logging or a simple probe). If that is complex, at least verify that when read_replica_url is None, all existing tests pass and the UoW still commits writes on the write session.
- Unit test: UoW exposes read-side repos and they use a different session than write-side (e.g. assert read_session is not write_session when both are set).

**Documentation:** AUDIT-DOC1 (Data Access Layer: which operations use read vs write session).

---

### AUDIT-DOC1 — Update service documentation

**Why:** All behavior, API, and config changes must be reflected in the service doc so that the doc remains the single source of truth.

**How:**

1. **API Surface table** in `docs/services/market-data.md`:
   - Add the 5 new GET routes: `/fundamentals/{security_id}/highlights`, `.../company-profile`, `.../institutional-holders`, `.../fund-holders`, `.../insider-transactions-snapshot`.
   - Add a note that the path parameter for fundamentals is the **instrument UUID** (not security UUID).
2. **List endpoints:**
   - Document that list instruments supports query parameters (has_ohlcv, has_quotes, has_fundamentals, exchange) and that filtering is done in the DB. Document limit/offset.
   - Document list securities: either "supports optional limit/offset when no figi/isin provided" or "returns empty when no figi/isin provided" per AUDIT-API3.
3. **Configuration / Env vars:**
   - Add `MARKET_DATA_READ_REPLICA_URL` (optional). State that when unset, read and write both use `MARKET_DATA_DATABASE_URL`.
4. **Data Access Layer:**
   - Describe that the UoW has separate write and read session factories; read-only operations (fundamentals query, instrument/ohlcv/quote reads from API) use the read session; writes (consumers, outbox) use the write session.
5. **Common Pitfalls:**
   - Add at least one pitfall related to fundamentals path parameter (e.g. "Using a security UUID in the fundamentals path returns 404 or wrong data; the path expects an instrument UUID.").
   - Add one for read replica (e.g. "Setting read_replica_url to the same value as database_url is redundant but valid; leave unset to use a single DB.").
6. Ensure no orphan or stale text (e.g. remove or update any sentence that says "security_id is the security UUID" for fundamentals).

**Documentation quality standard:** The updated doc must satisfy the 8 criteria from `0000-exec-wave-generation-template.md` (accuracy, diagrams if needed, examples, pitfalls, etc.). For this wave, focus on accuracy and the new pitfalls; add a diagram only if you introduce a new flow (e.g. read vs write session routing).

---

## Task-scoped fail-fast gate (mandatory)

After **each** task:

1. Run targeted tests that cover the changed behavior (unit and/or integration as specified per task).
2. Run `ruff check` on the changed paths.
3. Run `mypy` on the changed package(s) (e.g. `market_data`).

Fix any failure before starting the next task. **No deferred fixes:** do not carry ruff/mypy/test failures into a later task.

---

## Regression guardrails

Before marking the wave done:

1. **Fundamentals sections:** Request `GET /api/v1/fundamentals/{instrument_id}` for an instrument that has at least highlights or company_profile data; assert the response includes those sections (non-empty records).
2. **New section endpoints:** For the same instrument, call `GET /api/v1/fundamentals/{instrument_id}/highlights` and `.../company-profile`; assert 200 and correct section data in the body.
3. **List instruments:** Call with `?has_fundamentals=true&exchange=US` (or equivalent); assert only matching instruments are returned and filters are applied in DB (e.g. check query count or logs).
4. **Read/write:** With `read_replica_url` unset, run the full test suite for market-data; all tests must pass. Optionally with `read_replica_url` set to the same URL, repeat.
5. **No naive datetimes:** Grep modified files for `datetime.now()` or `datetime(` without `tz=` and fix.
6. **Documentation:** Every changed API, config var, and behavior is reflected in `docs/services/market-data.md`.

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|------------------|
| `docs/services/market-data.md` | API table: 5 new section endpoints; path param semantics (instrument_id); list instruments (filters + DB); list securities (list-all or limitation); Configuration: `MARKET_DATA_READ_REPLICA_URL`; Data Access Layer: read vs write session; Common Pitfalls: ≥2 new entries (path param, read replica). |
| `services/market-data/configs/dev.local.env.example` | Add commented `MARKET_DATA_READ_REPLICA_URL` with one-line description. |

If no other docs are changed, state "N/A" for libs and other services in the handoff.

---

## Done criteria (wave complete when all pass)

- [ ] All 18 fundamentals sections are present in `_SECTION_MODEL_MAP` (or equivalent) and COMPANY_PROFILE uses correct row→domain mapping.
- [ ] Five new GET routes for fundamentals sections return 200 and correct data when data exists.
- [ ] Fundamentals path parameter is documented as instrument UUID; OpenAPI or doc updated.
- [ ] List instruments applies has_ohlcv, has_quotes, has_fundamentals, exchange in the DB; pagination (limit/offset) works.
- [ ] List securities: either implements list-all with limit/offset or documents empty-without-figi/isin.
- [ ] Settings has `read_replica_url`; app builds write and read engines and passes (write_factory, read_factory) to UoW.
- [ ] Read-only API operations use the read session (query_fundamentals, instrument/ohlcv/quote reads from routers).
- [ ] `make test` and `make lint` (or equivalent) pass in `services/market-data`.
- [ ] All documentation in the table above is updated and Documentation quality checklist is completed.

---

## Handoff evidence required

1. List of task IDs completed and the corresponding changed files per task.
2. Output of targeted tests per task (command + pass/fail).
3. Output of `ruff check` and `mypy` on changed paths (exit codes).
4. Confirmation that with `read_replica_url` unset, full market-data test suite passes.
5. **Documentation quality checklist:**

| Criterion | Status | Notes |
|-----------|--------|-------|
| Accuracy — API, config, behavior match implementation | ✓ / N/A | |
| Diagrams for non-trivial flows | ✓ / N/A | List if added |
| Realistic code examples | ✓ / N/A | |
| Abstract methods documented | ✓ / N/A | |
| Common pitfalls — ≥2 new entries market-data.md | ✓ / N/A | |
| Service docs reflect final state | ✓ | List exact sections updated |
| No orphan documentation | ✓ | |

6. Exact list of documentation files updated (with section names).
7. Proposed commit message (concise title + 1–2 sentences).

---

## Proposed commit message (template)

```
feat(market-data): fundamentals read-side completeness, list filters in DB, read/write decoupling

- Add 5 missing fundamentals sections to read query map (highlights, company_profile,
  institutional_holders, fund_holders, insider_transactions_snapshot) with correct
  row→domain mapping for company_profiles. Add 5 section GET endpoints.
- Document fundamentals path param as instrument ID; push list-instruments filters
  to DB; list securities with list-all or document limitation.
- Add optional read_replica_url; build read engine and wire read session to
  read-only operations (fundamentals query, instrument/ohlcv/quote reads).
- Update docs/services/market-data.md (API, config, data access, pitfalls).

Validated: all 18 sections queryable; new section endpoints return data; list
filters applied in DB; tests and lint pass.
```
