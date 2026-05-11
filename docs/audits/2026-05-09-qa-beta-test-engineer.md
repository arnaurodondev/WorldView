# PLAN-0087 — QA / Test-Engineer Beta-Readiness Review

**Date**: 2026-05-09
**Auditor**: qa-test-engineer subagent (read-only, ~75 min)
**Scope**: 19 commits on `feat/content-ingestion-wave-a1` from `974f4f1d..HEAD`
**Bar**: BETA DEPLOYMENT for real analysts (not "demo-survives once")
**Sources read**: `RULES.md` (R1, R4, R19), `AGENTS.md`, REVIEW_CHECKLIST.md §8/§9,
EDGE_CASE_GENERATION.md, defect register, qa-standards-rules-review.md.

> **TL;DR**: 19 commits added ~11.8 KLOC; about half of the behavioural commits
> shipped without a guard test. The qa-standards review already flagged 9 gaps
> (D-R3-003/005, D-R4-003/004, D-R3-001+follow-up, D-R3-NARR partially, 0038
> migration, D-F2-001). This pass adds **8 further BLOCKING/CRITICAL gaps**
> the standards pass missed, the most important of which are:
>
> - **F-001 (BLOCKING)** — JWT `aud=` enforcement was added across 6 services
>   but **no negative test** asserts that wrong/missing audience returns 401.
>   The test helpers were patched to *include* `aud` so the existing tests
>   still pass; that is precisely how a future regression will reach prod.
> - **F-002 (BLOCKING)** — `BriefArchiveWriteAdapter` (the central D-R4-004
>   fix; the whole brief-archive feature was previously dark) has **zero test
>   coverage** — no unit test, no smoke test, no wiring test.
> - **F-003 (CRITICAL)** — `IntelligenceAggregatesRepository` was rewritten
>   twice in this session (`8bbd7480`, `0f96c81c`) yet **has no test file at
>   all** — both broken queries reached `main` because nothing exercised the
>   repo at the SQL level.
> - **F-004 (CRITICAL)** — Migration 0038 (8 demo-critical entities + their
>   aliases) ships **without an apply / idempotency / rollback test**, while
>   migration 0037 in the same session got a 128-line test.
>
> R19 (no test deletion / weakening) was respected. One assertion was removed
> from `test_schemas_search.py` (`_no_html_in_snippet` validator), but the
> change is justified by a documented PRD-0064 decision and a defensive
> frontend rendering path; this is the R19 §2 escape hatch, not a violation.

---

## Severity Distribution

| Severity | Count |
|----------|-------|
| BLOCKING | 4 |
| CRITICAL | 4 |
| MAJOR    | 5 |
| MINOR    | 4 |
| NIT      | 2 |
| **Total** | **19** |

---

## Findings (F-NNN format)

### F-001 — JWT audience enforcement has no negative test (6 services)
- **Severity**: BLOCKING
- **Category**: Security / Test coverage (R1, REVIEW_CHECKLIST §6)
- **File:line**:
  - `services/content-store/src/content_store/infrastructure/middleware/internal_jwt.py:204-211`
  - `services/portfolio/src/portfolio/infrastructure/middleware/internal_jwt.py` (similar)
  - `services/market-ingestion/src/market_ingestion/infrastructure/middleware/internal_jwt.py:198-206`
  - `services/nlp-pipeline/src/nlp_pipeline/infrastructure/middleware/internal_jwt.py` (similar)
  - and tests at `services/{portfolio,alert,market-data,content-ingestion}/tests/.../test_internal_jwt_middleware.py`
- **Confidence**: HIGH
- **Evidence**: commit `80dfc0fc` added `audience="worldview-internal"` and
  `"aud"` to the `options.require` list in **6 services**. The test helper
  `_make_token()` was simultaneously updated to include `aud="worldview-internal"`
  in the payload so the existing happy-path tests still pass. **No new test
  asserts that a token with `aud="bad"` or no `aud` claim is rejected with
  401.** Cross-service grep:
  ```
  $ grep -rn 'aud="\|wrong_audience\|invalid_aud\|InvalidAudience' \
        services/{content-store,portfolio,market-ingestion,nlp-pipeline,alert,market-data}/tests/
  # 0 hits in service tests
  ```
  Only the api-gateway tests reference `aud=` at all (and there only as a
  payload field, not as a rejection assertion).
- **Why this is BLOCKING for beta**: a future commit that drops the
  `audience=` kwarg from `jwt.decode()` (or that flips the `options.require`
  list) will pass every existing test. Audience binding is a token-replay
  control; a beta deployment serving real analysts must have an automated
  guard.
- **Suggestion**: add three negative tests per service (parametrise across
  the 6 services or factor a shared helper):
  1. token signed with `aud="zitadel-frontend"` → 401 + `WWW-Authenticate`.
  2. token with no `aud` claim at all → 401 (`require: aud` triggers).
  3. token with `aud=["worldview-internal", "other"]` → 200 (PyJWT accepts
     list audiences when the expected value is in the list — pin the
     library behaviour).
- **Auto-fixable**: NO (requires test design decisions).

---

### F-002 — `BriefArchiveWriteAdapter` has zero tests
- **Severity**: BLOCKING
- **Category**: Test coverage (R1)
- **File:line**: `services/rag-chat/src/rag_chat/infrastructure/clients/brief_archive_write_adapter.py:1-122`
- **Confidence**: HIGH
- **Evidence**: this file is a brand-new 122-line adapter introduced by
  `97153b36` (D-R4-004). It is the *entire* fix for "brief archival was dark"
  — the previous wiring used `NullBriefArchive` and silently dropped every
  generated brief.
  ```
  $ find services/rag-chat/tests -name "*brief_archive_write*"
  # zero results
  ```
  The companion read adapter has a 200-line test
  (`test_brief_archive_read_adapter.py`); the write adapter has none.
  `_wire_briefing_uc` in `app.py:537-549` is also untested — there is no
  assertion that `app.state.briefing_uc.brief_archive` is the new write
  adapter (and not still `NullBriefArchive`).
- **Why this is BLOCKING for beta**: a regression that points the wiring back
  at `NullBriefArchive` (or that breaks the `save()` happy path) will be
  discovered only when an analyst notices "my brief history is empty
  again" — exactly the failure mode the fix targets.
- **Suggestion**: add three tests:
  1. **Unit (adapter)** — mock `write_factory` returning a session whose
     `commit()` is awaited; assert the repository's `save()` is called with
     the supplied `UserBriefRecord`, then `commit()` then session close.
  2. **Unit (failure swallow)** — mock the repo to raise; assert the
     adapter logs `brief_archive_write_adapter_save_failed` with `exc_info`
     and **does not** propagate (the use case relies on shield semantics).
  3. **Wiring** — `_wire_briefing_uc` test asserts
     `isinstance(app.state.briefing_uc.brief_archive, BriefArchiveWriteAdapter)`.
- **Auto-fixable**: NO.

---

### F-003 — `IntelligenceAggregatesRepository` has no test file
- **Severity**: CRITICAL
- **Category**: Test coverage (R1) + SQL repository regression
- **File:line**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/intelligence_aggregates_repository.py`
- **Confidence**: HIGH
- **Evidence**: this repository was rewritten **twice in this session**
  (`8bbd7480` then `0f96c81c`) because the first commit fixed only one of two
  broken SQL queries; the same repo had drifted twice from the live schema
  (`confidence_components` JSONB never shipped, `relation_evidence_raw.relation_id`
  never existed). Search:
  ```
  $ find services/knowledge-graph/tests -name "*intelligence_aggregates*"
  # zero results
  ```
  Both bugs were found in production by manual `curl` + log-tailing rather
  than by any test. The fact that the second bug surfaced *after* the first
  fix is the canonical "missing repository test" signal.
- **Why this is CRITICAL for beta**: every aggregate read on the Intelligence
  tab passes through this repo. A third silent SQL drift (e.g. the future
  `confidence_components` JSONB column landing with a different name) will
  500 the surface again with zero local guard.
- **Suggestion**: add an integration-style test using the existing test DB
  (the migration 0037 fixture in `test_migration.py` already provides a
  populated schema — reuse it). At minimum:
  1. `get_relation_aggregates(entity_id)` returns the documented dict shape
     for an entity with active relations.
  2. Same query when the entity has zero active relations — must return the
     "no relations" shape (`mean_support=None`, `relation_count=0`).
  3. `get_confidence_trend(entity_id, days=N)` over a seeded set of
     `relation_evidence_raw` rows returns the expected `[(date, avg)]`
     shape — pin the field name `extraction_confidence` so a future column
     rename is caught.
  4. Compile-time assertion of the SQL string: `assert "confidence_components"
     not in str(_QUERY)` so a future PR that re-adds the JSONB extraction
     fails the test until the migration ships.
- **Auto-fixable**: NO.

---

### F-004 — Migration 0038 (8 demo-critical entities) is untested
- **Severity**: CRITICAL
- **Category**: Test coverage (R1) + Migration safety
- **File:line**: `services/intelligence-migrations/alembic/versions/0038_seed_demo_entities.py`
- **Confidence**: HIGH
- **Evidence**: `5e1b18f5` adds an Alembic migration that seeds 8
  `canonical_entities` rows + their aliases with deterministic UUIDv7-shaped
  IDs. The companion migration 0037 (`5e1b18f5`'s sibling, also added in
  this session) got a 128-line `test_migration.py` extension; **0038 got 0
  lines** of test:
  ```
  $ grep -n "0038\|seed_demo_entities\|d001-" \
        services/intelligence-migrations/tests/test_migration.py
  # zero matches
  ```
  Risks not guarded:
  1. **Idempotency** — re-running upgrade head must not duplicate aliases
     (the `ON CONFLICT (entity_id) DO NOTHING` only protects canonicals; the
     aliases rely on a partial unique index that is itself untested).
  2. **Rollback** — `downgrade()` deletes by ID prefix `d001-`. A test must
     prove the rollback restores the table to its pre-0038 row count and
     does not leave orphan aliases.
  3. **Forward-compat** — `OpenAI` and `Anthropic` are inserted with
     `ticker=None`. A future tightening of the `ticker NOT NULL` constraint
     would fail the migration on apply; a test would catch this.
- **Why this is CRITICAL for beta**: the demo specifically requires these 8
  entities (D-R3-007, D-F2-005, D-R4-010 all closed by this migration).
  Beta deployment will run `alembic upgrade head` against a fresh DB
  multiple times; an idempotency or constraint regression will manifest
  as a startup crash on a clean install.
- **Suggestion**: extend `test_migration.py` with three test cases mirroring
  the 0037 pattern:
  1. After upgrade head: `SELECT count(*) FROM canonical_entities WHERE
     entity_id::text LIKE '0195daad-d001-%' = 8` and corresponding alias
     count check.
  2. Re-run the migration script body in a transaction — assert no
     `IntegrityError` (idempotency).
  3. Apply downgrade then upgrade — assert row counts match pre/post.
- **Auto-fixable**: NO (migration tests need a live DB fixture).

---

### F-005 — `BaseKafkaConsumer._record_consumer_lag` `run_in_executor` change is untested
- **Severity**: CRITICAL
- **Category**: Test coverage (R1) + Distributed systems / async correctness
- **File:line**: `libs/messaging/src/messaging/kafka/consumer/base.py:825-833` (D-P3-006)
- **Confidence**: HIGH
- **Evidence**: `92915986` introduced two distinct behavioural changes:
  1. **Config**: `partition_assignment_strategy="cooperative-sticky"` and
     `max.poll.records` propagated through `to_dict()` — **TESTED**
     (`test_consumer_config.py`, 6 cases).
  2. **Runtime**: `_record_consumer_lag()` now executes inside
     `loop.run_in_executor(None, ...)` to keep the event loop responsive
     while broker watermark calls (up to 12s of blocking time per commit
     for a 12-partition consumer) run — **NOT TESTED**:
     ```
     $ grep -rn "run_in_executor\|_record_consumer_lag" libs/messaging/tests/
     # zero hits
     ```
- **Why this is CRITICAL for beta**: the runtime change is the actually
  load-bearing fix for the "wedged consumer" symptom. The config change
  is necessary but not sufficient — a future commit that "tidies" the
  `await loop.run_in_executor(None, self._record_consumer_lag)` line back
  to `self._record_consumer_lag()` will pass every existing test and
  re-introduce the 12-second event-loop blocks under demo load.
- **Suggestion**: add a unit test that mocks `_record_consumer_lag` to a
  blocking function (`time.sleep(0.5)`) and asserts the surrounding
  `_run_consume_loop` does not block other coroutines for >100ms. Or, more
  simply: assert that `_record_consumer_lag` is called via
  `loop.run_in_executor` by patching `loop.run_in_executor` and observing
  the call.
- **Auto-fixable**: NO.

---

### F-006 — D-Q-002/D-Q-003 prompt fix has zero coverage
- **Severity**: CRITICAL
- **Category**: Test coverage (R1) + LLM correctness
- **File:line**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (system prompt)
- **Confidence**: HIGH
- **Evidence**: commit `5940b477` modifies the system prompt in two
  user-visible ways:
  1. Adds "Today's date is {utc_now().date().isoformat()}".
  2. Adds the `CITATIONS:` block instructing the LLM to emit `[N1]…[Nk]`
     markers and "do NOT invent citation numbers".
  ```
  $ grep -rn "Today's date is\|do NOT invent citation\|^CITATIONS:" \
        services/rag-chat/tests/
  # zero matches
  ```
  The commit message says "13 chat orchestrator tool-loop tests pass" —
  those tests pre-date the prompt change and assert nothing about the
  presence of these strings.
- **Why this is CRITICAL for beta**: D-Q-003 fixed the "LLM queries with
  2023 dates" failure mode (HF-4) that caused 503s on demo questions like
  "what's AAPL's earnings calendar". A future prompt refactor that drops
  the date anchor will regress to silent 503s with no test signal.
- **Suggestion**: add two tiny tests in `test_chat_orchestrator_*`:
  1. Assert `"Today's date is"` substring is in the prompt produced by
     the orchestrator's `_build_system_prompt()` (or wherever the prompt
     is assembled), and that the date matches `date.today().isoformat()`
     (use `freezegun` or pin to a known date).
  2. Assert the `CITATIONS:` instruction string is present, and that the
     "do NOT invent citation numbers" guard is present.
- **Auto-fixable**: NO.

---

### F-007 — Search use case JWT propagation (D-R2-?) is untested
- **Severity**: MAJOR
- **Category**: Test coverage (R1) + Security
- **File:line**: `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/search_documents.py:138-205`
  and `api/dependencies.py:245-256`.
- **Confidence**: HIGH
- **Evidence**: commit `b8982bcd` adds a `jwt: str | None` parameter to
  both `_S5BatchClient` and `_S7BatchClient` and forwards
  `request.state.internal_jwt` to them so S5/S7 InternalJWTMiddleware
  accepts the call. Without this propagation, every search request would
  return entities with `name = str(entity_id)` (the documented S7-miss
  fallback) — silent partial degradation, not a 500.
  ```
  $ grep -n "X-Internal-JWT\|jwt=" \
        services/nlp-pipeline/tests/unit/application/use_cases/test_search_documents.py
  # zero matches
  ```
- **Why this is MAJOR**: the failure mode is invisible — search results just
  show UUIDs instead of names — exactly the silent-degradation pattern the
  CLAUDE.md "audit return values must be persisted" memory warns about.
- **Suggestion**: in `test_search_documents.py` add a test that
  instantiates `_S5BatchClient(jwt="X-TOKEN")`, monkey-patches
  `httpx.AsyncClient.post` to capture the headers dict, and asserts
  `headers["X-Internal-JWT"] == "X-TOKEN"`. Same for `_S7BatchClient`.
  Cheap, deterministic, no network.
- **Auto-fixable**: NO.

---

### F-008 — D-F1-007 KG-fallback chain has only a *negative* test
- **Severity**: MAJOR
- **Category**: Test coverage (R1) + edge cases
- **File:line**: `services/api-gateway/src/api_gateway/clients.py:227-300` (`get_company_overview`),
  test at `services/api-gateway/tests/test_routes.py:170-200`.
- **Confidence**: HIGH
- **Evidence**: `97153b36` adds the entity_id → ticker → symbol-lookup
  fallback chain — a 70-line behavioural change. The test diff shows only
  ONE assertion change: `authed_mock_clients.knowledge_graph.get =
  AsyncMock(return_value=err_resp)` on the existing 404 test, ensuring
  the negative (both legs miss) path raises. **No positive test** asserts:
  1. id-based lookup misses → KG `GET /api/v1/entities/{entity_id}` returns
     `{"ticker": "AAPL"}` → second lookup `?symbol=AAPL` succeeds → bundle
     composer uses the resolved instrument id for the parallel legs.
  2. The `resolved_md_id` propagates to the 4 parallel fundamentals/quote/
     ohlcv calls.
- **Why this is MAJOR**: the entire D-F1-007 fix is the positive path; the
  negative path was already covered. A regression that drops the
  `resolved_md_id` propagation (e.g., a future refactor uses `company_id`
  for one of the four legs) will pass every test in `test_routes.py`.
- **Suggestion**: add a positive test mocking:
  - `clients.market_data.get` to 404 on `?id=<entity_id>&extra_info=true`
    and 200 on `?symbol=AAPL&extra_info=true`.
  - `clients.knowledge_graph.get` to 200 on `/api/v1/entities/{entity_id}`
    returning `{"ticker": "AAPL", "id": "<entity_id>"}`.
  Then assert all four parallel legs (`/fundamentals/<id>`, `/ohlcv/<id>`,
  etc.) use the resolved `id` from the symbol-lookup response, and that
  the final bundle has a non-null `overview`.
- **Auto-fixable**: NO.

---

### F-009 — Finnhub URL normalisation only unit-tested at the helper, not the integration call site
- **Severity**: MAJOR
- **Category**: Test coverage (R1)
- **File:line**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:215`
  (call site at `_row_to_ranked_article` — `url=_normalise_finnhub_api_url(row.url)`).
- **Confidence**: MEDIUM
- **Evidence**: `test_news_url_normaliser.py` has 6 tests for the pure
  helper `_normalise_finnhub_api_url` (excellent coverage). But there's no
  test asserting `_row_to_ranked_article(row)` actually calls the
  normaliser. A future refactor (e.g., moving normalisation to a query
  layer earlier or a future `RankedArticleData` field rename) could leave
  the helper green and the call site silently broken.
- **Suggestion**: add one integration-style test in
  `test_document_search_repository.py` (or a dedicated
  `test_news_query_repository.py` if it doesn't exist) that constructs a
  fake row with `url="https://finnhub.io/api/news?id=abc"` and asserts the
  resulting `RankedArticleData.url == "https://finnhub.io/news/abc"`.
- **Auto-fixable**: NO.

---

### F-010 — Scheduler interval/startup-fire change (D-R3-003) has no test
- **Severity**: MAJOR
- **Category**: Test coverage (R1)
- **File:line**: `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py:170-200`
- **Confidence**: HIGH
- **Evidence**: `97153b36` changes the narrative-generation job from a
  weekly cron (`Sun 03:00 UTC`) to `interval` every 6h with
  `next_run_time = utc_now() + 60s`. PathInsightSeeder gets the same
  treatment with a 90s startup delay. Existing `test_scheduler.py` does
  not assert the new behaviour:
  ```
  $ grep -n "next_run_time\|interval\|hours=6\|13d3_narrative" \
        services/knowledge-graph/tests/unit/infrastructure/test_scheduler.py
  # 0 matches in the relevant lines
  ```
- **Why this is MAJOR (not CRITICAL)**: the scheduler can be re-tuned
  post-demo without semantic risk; the bug class is "schedule drift"
  rather than "data corruption". But for *beta*, an analyst expects the
  Intelligence tab populated within ~1 minute of cold-start; a refactor
  that drops the `next_run_time` parameter would silently re-introduce a
  6-hour blank window.
- **Suggestion**: add a test that builds the scheduler against a mock
  `AsyncIOScheduler`, runs `_register_jobs()`, then asserts:
  - `add_job.call_args_list` has an entry for `worker_13d3_narrative_generation`
    with `trigger="interval"`, `hours=6`, and `next_run_time` within 120s
    of `now`.
  - Same for `worker_path_insight_seeder` (90s).
- **Auto-fixable**: NO.

---

### F-011 — `_HUB_MIN_RELATIONS` env override (D-R3-005) has no test
- **Severity**: MAJOR
- **Category**: Test coverage (R1)
- **File:line**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py:36-40`
- **Confidence**: HIGH
- **Evidence**: the worker now reads
  `os.environ.get("PATH_INSIGHT_HUB_MIN_RELATIONS", "2")`. Default
  changed from 10 → 2. No test:
  - asserts the new default (2),
  - asserts the env-var override path takes precedence,
  - asserts a non-integer env value falls back gracefully (or fails fast).
- **Suggestion**: 3-case parametrized test:
  1. unset env → `_HUB_MIN_RELATIONS == 2`
  2. `PATH_INSIGHT_HUB_MIN_RELATIONS=15` → loaded value `== 15`
  3. `PATH_INSIGHT_HUB_MIN_RELATIONS="not-an-int"` → either fails fast or
     falls back to default (whichever is the documented contract — the
     code currently calls `int(...)` so it will raise `ValueError` at
     import; pin that with a test).
- **Auto-fixable**: NO.

---

### F-012 — D-F2-001 logging-level change has no test
- **Severity**: MINOR
- **Category**: Test coverage (R1) + observability
- **File:line**: see commit `97153b36` for the affected log line; the
  defect register marks it as "log level DEBUG → WARNING + exception class".
- **Confidence**: MEDIUM
- **Evidence**: not asserted anywhere. Logging-level changes are typically
  low-risk, but this one was specifically called out by the audit as
  hiding errors that should have been visible.
- **Suggestion**: capture log records via `caplog` and assert level==
  WARNING for the trigger condition.
- **Auto-fixable**: YES (mechanical via `caplog`).

---

### F-013 — Removed `_no_html_in_snippet` validator: justification is correct, but no replacement assertion
- **Severity**: MINOR
- **Category**: R19 boundary case + test integrity
- **File:line**: `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py:342-349` (deleted),
  test at `services/nlp-pipeline/tests/unit/api/test_schemas_search.py:140-156`.
- **Confidence**: HIGH
- **Evidence**: PRD-0064 BUG-2 explicitly accepted financial text like
  `"P/E <15x"` so the validator was removed. The test was rewritten from
  "rejects HTML" to "accepts angle brackets". This is the R19 §2 escape
  hatch ("test was testing outdated behaviour") with documented rationale.
  The frontend renders snippets via string slicing (verified at
  `apps/worldview-web/app/(app)/search/page.tsx:88-130`) so XSS is not a
  live risk.
  However, **no positive XSS-defence assertion replaced the dropped
  validator**. The current contract is "snippet may contain `<` and `>`;
  the frontend's responsibility to escape". A schema-level test that
  asserts the snippet field is **plain string** (not HTMLSafeString or
  similar) and is rendered via `{snippet}` (not
  `dangerouslySetInnerHTML`) on at least one search-results component
  would lock the contract from both ends.
- **Suggestion**: optionally add a frontend test that mounts the search
  results component with `snippet="<script>alert(1)</script>"` and
  asserts the rendered HTML does not contain a `<script>` tag (DOM
  string-equality).
- **Auto-fixable**: NO.

---

### F-014 — Tool registry `to_tool_definitions` test does NOT assert per-parameter type/required equality
- **Severity**: MINOR
- **Category**: R29 manifest sync + test depth
- **File:line**: `services/rag-chat/tests/unit/application/pipeline/test_tool_registry_definitions.py:114-128`
- **Confidence**: HIGH
- **Evidence**: `test_representative_tool_param_names_match_yaml` asserts
  only `set` equality of param **names**, not `(name, type, required)`
  tuples. The standards review (`§SF-3`) already flagged this as the
  pre-existing weakness that let 18 tools ship with `parameters=[]` for
  half a year. The session fixed the data but not the guard.
  Test comment explicitly states: "We do not assert on description/required
  equality (those are subtly normalised in the Python registration)".
- **Suggestion**: add one parametrized test per audit-relevant tool
  asserting `(name, type, required)` tuples match the YAML manifest. The
  "subtle normalisation" excuse is the trap; if the Python and YAML
  shapes diverge, the audit pattern returns.
- **Auto-fixable**: NO.

---

### F-015 — `BriefArchiveWriteAdapter.get_*` no-op methods are not asserted
- **Severity**: MINOR
- **Category**: Test coverage (R1) + interface contract
- **File:line**: `services/rag-chat/src/rag_chat/infrastructure/clients/brief_archive_write_adapter.py:86-122`
- **Confidence**: HIGH
- **Evidence**: the adapter implements `get_latest`, `get_history`,
  `get_by_id` as no-ops that log a warning and return empty results,
  with the docstring "read path goes through `BriefArchiveReadAdapter`".
  No test asserts that these methods don't accidentally execute a SQL
  read or that the warning is logged. If a developer mistakenly calls
  these, they'll get silently empty results — same failure mode as the
  pre-fix `NullBriefArchive`.
- **Suggestion**: 3 cases — assert each `get_*` returns the empty shape
  AND emits a `brief_archive_write_adapter_*_called` warning (use
  `caplog`).
- **Auto-fixable**: YES (mechanical).

---

### F-016 — Article consumer `process_message` end-to-end source_name path not integration-tested
- **Severity**: MAJOR
- **Category**: Integration test coverage (R1, REVIEW_CHECKLIST §8)
- **File:line**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:297-345`
  and integration test at `tests/integration/test_consumer_pipeline.py`.
- **Confidence**: MEDIUM
- **Evidence**: D-INIT-6 propagates `source_name` through three layers:
  `process_message` → `_run_pipeline` → `_enqueue_enriched`. The unit
  test `TestEnqueueEnriched.test_enriched_payload_includes_source_name_when_provided`
  excellently covers the bottom layer. The integration test
  `test_consumer_pipeline.py` was modified only to add a
  `gliner_mention_floor` fixture value; **no integration assertion** that
  feeds an inbound event with `source_name="Reuters"` and confirms the
  outbox row carries it through. A regression in `process_message`'s line
  `source_name = value.get("source_name")` (e.g. typo to `source-name`)
  is invisible at the unit-test layer.
- **Suggestion**: extend `test_consumer_pipeline.py` integration test:
  feed an event with `source_name="Reuters"` to `process_message`, then
  assert the resulting outbox payload deserialised from Avro contains
  `source_name == "Reuters"`. The serialisation utilities are already
  imported by the unit test so the fixture cost is small.
- **Auto-fixable**: NO.

---

### F-017 — Tool executor 8-handler addition (700+ LOC) is not exercised end-to-end
- **Severity**: MAJOR
- **Category**: Test coverage (R1)
- **File:line**: `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:2306+`
  (~700 lines added in `8d8e6519` for the 8 PLAN-0067 W11-2 tools).
- **Confidence**: MEDIUM
- **Evidence**: the new ToolSpec metadata is well-tested by
  `test_tool_registry_definitions.py` (D-R1-002 coverage). What's missing
  is an end-to-end test for each of the 8 new tools' dispatch paths
  inside `ToolExecutor.execute()`:
  - `search_documents`, `get_entity_graph`, `traverse_graph`,
    `search_entity_relations`, `search_claims`, `search_events`,
    `get_contradictions`, `get_portfolio_context`.
  Each has its own port handler + cypher-allowlist guards (for
  `traverse_graph`). The audit already noted "13 tool-loop tests pass" —
  those tests pre-date the new handlers and don't exercise the new
  per-tool dispatch logic. A regression in any of the 8 dispatch arms is
  invisible.
- **Suggestion**: parametrized test in
  `test_tool_executor_dispatch.py` (create if missing) that asserts each
  of the 8 tool names routes to the correct port method (mock all 5
  ports; assert `s7.search_relations` is called for
  `search_entity_relations`, `s7.get_contradictions` for
  `get_contradictions`, etc.). One test per tool.
- **Auto-fixable**: NO.

---

### F-018 — Architecture frontend test `no-off-palette-colors.test.ts` has no allowlist regression test
- **Severity**: NIT
- **Category**: Test coverage of meta-tests
- **File:line**: `apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts:47-58`
- **Confidence**: LOW
- **Evidence**: `ALLOWED_FILES` is a manually curated 2-entry allowlist.
  The meta-test does not assert that the allowlist itself is "tight" —
  e.g., that all entries still exist on disk, or that each exists for a
  documented reason. The current entries (`lib/entity-types.ts`,
  `components/instrument/OHLCVChart.tsx`) are sound, but a future drift
  ("just add another file to the allowlist") cannot be detected.
- **Suggestion**: add a tiny meta-test asserting (a) every allowlist
  entry maps to a real file, (b) each allowlist entry has a comment
  explaining why (already true today; pin it with a regex).
- **Auto-fixable**: YES.

---

### F-019 — Test file naming convention drift: `test_chat_orchestrator_execute_sync.py` lives under `tests/unit/use_cases/`
- **Severity**: NIT
- **Category**: Test discoverability
- **File:line**: `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_execute_sync.py`
- **Confidence**: HIGH
- **Evidence**: every other rag-chat use case test lives under
  `tests/unit/application/use_cases/` (e.g., `test_chat_orchestrator_tool_loop.py`).
  This file is the only one under `tests/unit/use_cases/` (no
  `application/` segment). Future test discovery & coverage tooling that
  filters by `tests/unit/application/` will skip this file silently.
- **Suggestion**: move to
  `services/rag-chat/tests/unit/application/use_cases/test_chat_orchestrator_execute_sync.py`
  (next to its sibling tool-loop test).
- **Auto-fixable**: YES (mechanical mv).

---

## Cross-cutting observations

### O-1 (positive) — citation pipeline tests are exemplary
`test_citation_pipeline.py` covers happy path, edge cases, error paths,
boundary conditions (lead truncation, max-bullets, single-section guard),
v2.2 back-compat, and D-R4-002 placeholder leak — all in 500 lines with
clear "WHY" commentary. Use this as the template for F-002, F-003, F-005.

### O-2 (positive) — Avro forward-compat tests are well structured
`test_events_nlp_article_enriched.py` D-INIT-6 additions cover schema-shape
(nullable union + null default), round-trip with the field set, AND
round-trip with the field omitted. This is the right pattern for every
forward-compat schema change going forward.

### O-3 (concern) — tests-by-numbers misleading
`commit 80dfc0fc` claims "26 missing tests added" but inspection shows ~24
of those are `test_retrieval_plan_builder.py` (18) + `test_search_proxy.py`
(8) — both for orthogonal scope (PLAN-0064 retrieval) rather than for the
PLAN-0087 demo-defect bundle. Genuinely-new test cases for the 27 D-defects
fixed in this session: roughly 7 (the citation pipeline ones, 2 D-R3-NARR
ones, the 2 D-INIT-6 source_name ones, the news_url normaliser 6, the
consumer config 6 = ~22 total). The defect-to-test ratio is **~22 tests
for 27 defects** (0.8×), well below the project bar. Many defects shipped
without any test (see F-001 through F-006 above).

### O-4 (concern) — pytest markers are used inconsistently in new tests
`test_tool_registry_definitions.py` uses module-level
`pytestmark = pytest.mark.unit`. `test_chat_orchestrator_execute_sync.py`
also does. `test_news_url_normaliser.py` does **not** declare a marker.
`test_consumer_config.py` declares `pytest.mark.unit` at module level
(good). For a beta-ready suite, every new test file should declare the
appropriate marker so `pytest -m unit` selects them; the missing marker
means CI's marker-based filter would silently skip
`test_news_url_normaliser.py`.

### O-5 (concern) — async tests use mocks at deep boundaries
Several new tests mock at private functions / private class attributes
(e.g., `test_chat_orchestrator_execute_sync.py` directly assigns
`orch.execute_streaming = _fake_stream`; `test_generate_narrative.py`
patches private module-level constants like `_SANITIZE`). REVIEW_CHECKLIST
§8 requires "mocks at port boundaries (not deep inside implementation)".
This makes refactors brittle — renaming `execute_streaming` → `stream` will
silently break the test's monkey-patch, the test will pass on the real
function, and a regression in error mapping will reach production.

---

## Priority-ordered remediation plan

### Before beta (must)
1. **F-001** — JWT audience negative tests (≈45 min, 6 services × 3 cases)
2. **F-002** — `BriefArchiveWriteAdapter` test suite (≈30 min)
3. **F-003** — `IntelligenceAggregatesRepository` integration tests (≈45 min)
4. **F-004** — Migration 0038 apply/idempotency/rollback (≈30 min, mirror
   the 0037 test pattern)

### Before beta (should)
5. **F-005** — `run_in_executor` lag-recording test (≈20 min)
6. **F-006** — System prompt anchor + CITATIONS test (≈15 min)
7. **F-008** — Positive D-F1-007 KG-fallback test (≈20 min)
8. **F-016** — Integration test for source_name end-to-end (≈30 min)

### Post-beta (nice to have)
9. **F-007, F-009, F-010, F-011, F-012, F-014, F-015, F-017** — 2-3h total
10. **F-018, F-019** — mechanical (≈10 min combined)

**Total before-beta cost**: ≈4 hours. The "must" set closes the high-leverage
gaps that would otherwise let a future refactor silently re-introduce the
same defects this session just fixed.

---

## Auditor's summary

**R19 (test-integrity)**: PASS. One assertion was relaxed
(`_no_html_in_snippet`) but with documented PRD justification + safe
frontend-rendering path; this is the §2 escape hatch.

**R1 (tests for every behavioural change)**: FAIL on 8 of 19 commits.
The standards-rules subagent caught 9 of these. This pass adds 10 more
gaps (mostly around adapter wiring, JWT-audience negative paths, prompt
contracts, and async-runtime fixes that look identical at the API
surface but differ in event-loop behaviour).

**Overall verdict**: the runtime correctness of the 27 fixed defects is
high. The **test-debt** carried by this session is the dominant beta-
readiness risk. F-001, F-002, F-003, F-004 are the four mandatory
closures before declaring this branch beta-ready. The remaining 15
findings can be closed during the post-demo backlog burn-down.
