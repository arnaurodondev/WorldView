# Platform Stability QA Report

**Date**: 2026-04-30
**Scope**: PLAN-0053 + platform-wide stability sweep (every service, every shared lib, frontend, infra docs)
**Branch**: `feat/content-ingestion-wave-a1` @ `15de90c6` (PLAN-0057 Wave A-1)
**Verdict**: **NEEDS_FIXES**

The PLAN-0053 surface itself is clean — frontend tests, TSC, and ruff in PLAN-0053-touched files all pass. However the platform-wide sweep surfaces **NEW post-PLAN-0053 regressions** that were introduced by PLAN-0055/0057 (commits `15de90c6` and earlier `ef11fc54`) and a partially-applied uncommitted patch in `services/nlp-pipeline/`. The hard-rule architecture-test layer is failing again — the same boundaries that commit `45efe6c7` ("resolve 4 architecture test failures") fixed for PLAN-0054 have been re-broken by PLAN-0050-Wave-E and PLAN-0057-A-1.

Frontend Vitest (849/849 PASS), Frontend TSC (no errors), and ruff (only the 2 pre-existing RUF059 warnings) are clean. The blocker is on the backend: 7 nlp-pipeline unit tests fail and 4 architecture invariant tests fail.

## Summary

| Severity | Count | New (post-PLAN-0053) | Pre-existing |
|----------|------:|---------------------:|-------------:|
| BLOCKING |     0 |                    0 |            0 |
| CRITICAL |     2 |                    2 |            0 |
| MAJOR    |     3 |                    1 |            2 |
| MINOR    |     6 |                    0 |            6 |
| NIT      |     2 |                    0 |            2 |

Two CRITICAL findings (`F-PLATFORM-01`, `F-PLATFORM-02`) gate SHIP.

---

## Findings

### F-PLATFORM-01 — CRITICAL — nlp-pipeline unit suite has 7 failing tests after PLAN-0055 dual-write
- **Severity**: CRITICAL
- **Category**: test correctness / regression
- **Files**:
  - `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/llm_score.py:65-66`
  - `services/nlp-pipeline/tests/unit/infrastructure/workers/test_article_relevance_scoring_worker.py` (uncommitted partial patch)
- **Failing tests** (`pytest services/nlp-pipeline/tests/unit -q`):
  - `TestOllamaResponseParsing::test_parses_valid_json_score`
  - `TestOllamaResponseParsing::test_clamps_score_above_1`
  - `TestOllamaResponseParsing::test_clamps_score_below_0`
  - `TestR24Compliance::test_db_session_closed_before_ollama_call`
  - `TestDeepInfraProviderPath::test_external_api_called_when_api_key_set`
  - `TestDeepInfraProviderPath::test_external_api_score_parsed_correctly`
  - `TestDeepInfraProviderPath::test_ollama_used_when_no_api_key`
- **Issue**: PLAN-0055 C-2 added a parallel append-only INSERT in `_append_provenance` that calls `SqlaLLMScoreRepository.append`. The repo reads `getattr(result, "rowcount", None) or 0` — when the test mocks `session.execute = AsyncMock(return_value=result_mock)` without setting `result_mock.rowcount`, MagicMock auto-attribute returns a `MagicMock`, the `or 0` evaluates to that MagicMock (truthy), and `MagicMock > 0` raises `TypeError`. Stack trace:
  ```
  src/nlp_pipeline/infrastructure/nlp_db/repositories/llm_score.py:66:
  TypeError: '>' not supported between instances of 'MagicMock' and 'int'
  ```
- **Note**: The diff at `services/nlp-pipeline/tests/unit/infrastructure/workers/test_article_relevance_scoring_worker.py` (uncommitted, see `git diff --stat`) only patches the assertion lookups (`_find_score_call`) but leaves the production-code call path failing. Whoever started the patch did not finish.
- **Fix** (auto-fixable):
  1. In `_make_session_factory`, set `result_mock.rowcount = 1` so `getattr(...).rowcount` is an int.
  2. Commit the existing partial diff after (1).
- **Auto-fixable**: yes (2-line test fix). Production code at `llm_score.py:65-66` is correct (defensive `getattr`).

### F-PLATFORM-02 — CRITICAL — 4 architecture-test invariants regressed (R22, IG-LAYER-001/002)
- **Severity**: CRITICAL
- **Category**: architecture invariant / hard rule (R12, R22, R25)
- **Test runner**: `python -m pytest tests/architecture -q`
- **Failing tests**:
  1. `test_layer_boundaries.py::test_domain_does_not_import_outward_layers`
  2. `test_layer_boundaries.py::test_application_does_not_import_api_or_infrastructure`
  3. `test_layer_boundaries.py::test_api_no_module_level_infrastructure_imports`
  4. `test_process_topology.py::test_app_lifespan_has_no_background_tasks`
- **Violations** (each violation triggers tests 1+2 jointly, or 3 / 4 standalone):
  - `services/market-data/src/market_data/application/use_cases/query_fundamentals_snapshot.py:32` — function-body import `from market_data.infrastructure.db.models.fundamentals_snapshot import InstrumentFundamentalsSnapshotModel`. Even though it's deferred to function body the rule's AST walker still flags it. **Introduced by**: `ef11fc54` (PLAN-0050 Wave E).
  - `services/nlp-pipeline/src/nlp_pipeline/api/dependencies.py:21` — module-level `from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import EntityMentionRepository` (used in `EntityMentionRepoDep = Annotated[...]`). Comment claims "Pre-existing bug fixed here" but the architecture rule requires the entire `Annotated[]` shape to live behind a Protocol port. **Introduced by**: `ef11fc54` (PLAN-0050 Wave E).
  - `services/content-ingestion/src/content_ingestion/app.py:164` — `app.state.startup_seed_task = _asyncio.create_task(_run_seed(), ...)` inside `lifespan()`. R22 says background work runs as standalone entry points. **Introduced by**: `15de90c6` (PLAN-0057 Wave A-1) — it added a one-shot startup-seed task.
- **Reference**: commit `45efe6c7` ("fix(arch): resolve 4 architecture test failures introduced by PLAN-0054") demonstrates the canonical fix pattern (move metric/dep behind a port, lift create_task out of lifespan into a standalone consumer-main entry point).
- **Fix** (per file):
  - `query_fundamentals_snapshot.py`: define a `FundamentalsSnapshotPort` Protocol in `application/ports/`, inject the real adapter from API layer; keep the use case pure.
  - `nlp_pipeline/api/dependencies.py`: define a Protocol port for EntityMentionRepository in `application/ports/`, lift the concrete import to a factory function in `api/factories.py` that's called from API routers (NOT module-level Annotated).
  - `content_ingestion/app.py`: move the seed-watermarks one-shot to a separate `services/content-ingestion/src/content_ingestion/scripts/seed_source_watermarks.py` and call it via `python -m` in docker-compose (or via `make seed`). Remove the inline `create_task` from `lifespan`.
- **Auto-fixable**: no — needs port/protocol design, ~30 min per file.

### F-PLATFORM-03 — MAJOR — 4 latent `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` warnings
- **Severity**: MAJOR (signals real bugs hiding behind silent mocks)
- **Category**: test hygiene / hidden async bugs
- **Sources**:
  - `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:501` (14 occurrences) — `logger.warning(...)` is being mocked but the warning call itself isn't awaited; downstream code calls `await mock.warning(...)` somewhere.
  - `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py:186` (2 occurrences) — `async with session.begin_nested():` — `begin_nested()` is mocked as a non-async MagicMock, callers of `__aenter__/__aexit__` build coroutines that never run.
  - `services/alert/src/alert/infrastructure/email/scheduler.py:200` — `session.add(row)` invoked on `AsyncMock` instead of a sync MagicMock; `session.add` is sync in real SQLAlchemy.
  - `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_main.py:63` — `await self._warn_on_config_drift()` invoked on partial AsyncMock; one of the inner DB calls returns a coroutine that's never awaited.
- **Impact**: tests pass green but the production code's actual async boundaries are not exercised. Real bugs (e.g. unawaited `session.add`-style misuse) won't surface in CI.
- **Fix**: in each test, replace blanket `AsyncMock()` with explicit `MagicMock()` for sync methods (`session.add`, `logger.warning`, `begin_nested`'s context manager helpers) and `AsyncMock()` only for awaited methods.
- **Auto-fixable**: partial — 4 separate tests need targeted attention; ~10-15 min each.

### F-PLATFORM-04 — MAJOR — 3 ml-clients integration tests assume Ollama is running on localhost:11434
- **Severity**: MAJOR (CI flakiness if/when Ollama isn't up)
- **Category**: integration test hygiene
- **File**: `libs/ml-clients/tests/integration/test_ollama_integration.py`
- **Failing tests** (when Ollama isn't running locally):
  - `test_ollama_embedding_roundtrip` — 404 on `/api/embeddings`
  - `test_ollama_embedding_batch` — 404 on `/api/embeddings`
  - `test_ollama_extraction_roundtrip` — 404 on `/api/chat`
- **Pre-existing**: yes (these tests have always required local Ollama).
- **Fix**: gate with `pytest.mark.skipif(os.getenv("OLLAMA_RUNNING") != "1", reason="requires local Ollama")` OR move under `tests/integration/` with `--profile integration` so default `make test` doesn't touch them. Alternative: use `pytest.mark.requires_ollama` and add an autouse fixture that probes `http://localhost:11434/api/tags` and skips on connect-error.
- **Auto-fixable**: yes (15 min).

### F-PLATFORM-05 — MAJOR — 2 RUF059 ruff warnings (already known, accepted)
- **Severity**: MAJOR (per-instructions; would otherwise be MINOR)
- **Files**:
  - `libs/messaging/src/messaging/kafka/consumer/base.py:459` — `low, high = self._consumer.get_watermark_offsets(...)` — `low` is unpacked but never used.
  - `services/alert/tests/unit/use_cases/test_acknowledge_alert_use_case.py:143` — `uc, repo, session = _make_uc()` — `session` is unpacked but never used.
- **Pre-existing**: yes (mentioned in user's note).
- **Fix**: prefix unused variable with `_` (`_low, high = ...`, `uc, repo, _session = ...`).
- **Auto-fixable**: yes (2 lines, trivial).

### F-PLATFORM-06 — MINOR — 4 distinct DeprecationWarning emissions across test runs
- **Severity**: MINOR
- **Category**: dependency hygiene
- **Items**:
  1. `starlette.formparsers:12 — PendingDeprecationWarning: Please use 'import python_multipart' instead.` Surfaces in EVERY service unit suite. Fix: pin starlette ≥ a version that uses `python_multipart` natively, or add a top-level `filterwarnings` in `pyproject.toml`.
  2. `sqlalchemy/sql/sqltypes.py:1999 — DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated`. Surfaces in EVERY service. Fix: bump SQLAlchemy minor.
  3. `libs/messaging/src/messaging/valkey/client.py:307 — DeprecationWarning: Call to deprecated close. (Use aclose() instead).` Real code-side issue — change `await pubsub.close()` to `await pubsub.aclose()`.
  4. `libs/observability/tests/test_error_capture.py — PendingDeprecationWarning: Please use 'import python_multipart'`. Same root cause as (1).
- **Fix priority**: (3) is real code, fix immediately; (1), (2), (4) are upstream — either bump deps or `filterwarnings = ["ignore::PendingDeprecationWarning:starlette.*"]` in shared pytest config.

### F-PLATFORM-07 — MINOR — Test collection layout mismatch when running pytest from repo root
- **Severity**: MINOR
- **Category**: test hygiene
- **Issue**: `python -m pytest services/alert/tests/unit -q` from repo root fails with `ModuleNotFoundError: No module named 'tests.unit.use_cases'` (collection error on 34 files). Running from `services/alert/` works (475 PASS). Same for `content-ingestion/` (`No module named 'content_ingestion'`) and `rag-chat/` (`No module named 'rag_chat.infrastructure'`).
- **Root cause**: missing `conftest.py` at repo root that adds each service's `src/` to `sys.path`, and per-service `pyproject.toml` `[tool.pytest.ini_options].rootdir` not honoured cross-service.
- **Pre-existing**: yes.
- **Fix**: Document in `CONTRIBUTING.md` that backend tests must be run from `services/<svc>/`. Or add a top-level `conftest.py` that prepends each `services/*/src` to `sys.path`.

### F-PLATFORM-08 — MINOR — 6 portfolio integration tests + 1 content-store + 1 intelligence-migrations have uncommitted single-line removals
- **Severity**: MINOR
- **Category**: workspace hygiene
- **Files** (`git status`):
  - `services/portfolio/tests/integration/test_alert_preferences_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_holding_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_portfolio_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_tenant_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_transaction_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_user_api.py` — 1 line removed
  - `services/portfolio/tests/integration/test_watchlist_api.py` — 2 lines removed
  - `services/portfolio/tests/integration/test_watchlist_reverse_index.py` — 2 lines removed
  - `services/content-store/tests/integration/test_pipeline.py` — 1 line removed
  - `services/intelligence-migrations/tests/test_migration.py` — modified (along with new `0008_alias_unique_per_entity.py` migration that is staged)
- **Issue**: 10 integration tests carry uncommitted dangling diffs (10 line removals total) plus a new staged Alembic migration `0008_alias_unique_per_entity.py`. None of these are PLAN-0053 work — looks like an unfinished cleanup or partial revert.
- **Fix**: review the diff; either commit (with rationale) or `git checkout -- <file>` to discard.

### F-PLATFORM-09 — MINOR — Recharts emits "width(0) height(0)" warnings in jsdom for chart components
- **Severity**: MINOR (test environment only)
- **Category**: frontend test hygiene
- **Files**:
  - `apps/worldview-web/__tests__/plan-0053-bd-widgets.test.tsx` (DividendIncomeTimeline, RealizedPnLChart)
  - `apps/worldview-web/__tests__/equity-curve-empty-state.test.tsx`
- **Issue**: ResponsiveContainer measures parent in jsdom (always 0×0) so recharts logs to `console.error`. Production is fine (parent has explicit `h-[160px]` etc.).
- **Fix**: in tests, mock `ResponsiveContainer` to render children at fixed 600×400, OR set `Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { get: () => 600 })` in test setup.
- **Auto-fixable**: yes (a 5-line `vi.mock("recharts", ...)` would silence all of them).

### F-PLATFORM-10 — MINOR — `act(...)` warnings in 2 tests indicate untracked async state updates
- **Severity**: MINOR
- **Files**:
  - `apps/worldview-web/__tests__/WatchlistMoversWidget.insights.test.tsx`
  - `apps/worldview-web/__tests__/feedback-components.test.tsx > MicroSurvey`
- **Issue**: state updates fire after the test's microtask completes without an `await waitFor(...)` or `act(...)` wrapper. The tests pass but the warning suggests a race: a real user clicking that button may also see flicker.
- **Fix**: wrap interactions in `await act(async () => { fireEvent.click(...); await Promise.resolve(); })` or use `await waitFor(() => expect(...).toBeInTheDocument())`.

### F-PLATFORM-11 — NIT — `apps/worldview-web/__tests__/notification-prefs.test.tsx` emits "Missing Description or aria-describedby" Radix warning
- **Severity**: NIT
- **File**: `apps/worldview-web/components/...` whichever DialogContent backs `NotificationPreferencesDialog`.
- **Fix**: add `<DialogDescription>` (visually-hidden if needed via `<VisuallyHidden>`).
- **Auto-fixable**: yes (1 line).

### F-PLATFORM-12 — NIT — `context-aware-starters.test.tsx` returns undefined from a query function
- **Severity**: NIT
- **Issue**: TanStack Query test logs `Query data cannot be undefined. Please make sure to return a value other than undefined from your query function.` Affected query: `["thread","uuid-1","tok"]`.
- **Fix**: in the mocked queryFn, return `null` (or an empty object) instead of `undefined`. TanStack Query treats `undefined` as "no data yet" and warns.

---

## Test execution results

### Backend unit suites (run from each service dir)

| Service / lib            | Tests    | Result                               |
|--------------------------|----------|--------------------------------------|
| services/alert           |     475  | ALL PASS                             |
| services/portfolio       |     ~660 | ALL PASS (suite > 500 lines, only summary visible) |
| services/api-gateway     |       72 | ALL PASS                             |
| services/market-data     |     ~810 | ALL PASS (14 RuntimeWarnings — F-PLATFORM-03) |
| services/market-ingestion|     ~810 | ALL PASS (in same parallel run with market-data) |
| services/content-ingestion|    ~660 | ALL PASS (1 RuntimeWarning — F-PLATFORM-03) |
| services/content-store   |     302  | ALL PASS                             |
| services/nlp-pipeline    |   558+7F | **7 FAILED** — F-PLATFORM-01         |
| services/knowledge-graph |     647  | ALL PASS (2 RuntimeWarnings — F-PLATFORM-03) |
| services/rag-chat        |     ~510 | ALL PASS                             |
| libs/common              |       67 | ALL PASS                             |
| libs/contracts           |     108  | 105 PASS + 3 SKIP (pyarrow not installed) |
| libs/messaging           |    ~250  | ALL PASS (1 deprecation — F-PLATFORM-06) |
| libs/storage             |       79 | ALL PASS                             |
| libs/observability       |       58 | ALL PASS (1 PendingDeprecationWarning) |
| libs/ml-clients          |   ~50+3F | **3 FAILED** — F-PLATFORM-04 (Ollama not running) |
| tests/architecture       |    14P+4F| **4 FAILED** — F-PLATFORM-02         |

**Totals**: ~5,200 backend tests, **14 FAILED** across 3 distinct buckets (7 nlp-pipeline + 3 ml-clients + 4 architecture).

### Frontend (`apps/worldview-web/`)

- **Vitest**: 79 files, **849 PASS / 0 FAIL** in 7.6 s
- **TSC**: `pnpm exec tsc --noEmit` produced no output (CLEAN)
- **Console warnings during tests**: 6 distinct stderr lines (F-PLATFORM-09/10/11/12)

### Lint

- **Ruff** (`uvx ruff check services/ libs/`): 13 errors found, 11 auto-fixed, **2 remaining** — both pre-existing RUF059 (F-PLATFORM-05).
- **Ruff format**: not run (PR-style; would be re-run inside `/implement` workflow).

### Mypy

- **`python -m mypy services/portfolio/src`**: only 2 import-untyped errors in `snaptrade_client` (third-party, no py.typed marker). 148 source files clean otherwise.
- (`uvx mypy` reports 272 errors but those are environmental — uvx doesn't have the project deps installed; venv `python -m mypy` is the correct invocation.)

---

## UI quality sweep (per page)

| Page (`apps/worldview-web/app/(app)/...`) | Layout | Empty/Error states | Tokens | Aria | Verdict |
|-------------------------------------------|--------|-------------------|--------|------|--------|
| `dashboard/page.tsx`                      | 12-col grid, 4 rows; widget-internal states | Each widget ships its own loading + empty + error | tokens (no inline hex) | n/a | **PASS** |
| `portfolio/page.tsx`                      | tabs (Holdings · Cash · Activity · Dividends · Realized P&L) | 35× isLoading/Skeleton/EmptyState refs | tokens; tabular-nums on price cells | tablist + sticky headers | **PASS** |
| `screener/page.tsx`                       | resizable 12-col table | 23× state refs | tokens | column headers labelled | **PASS** |
| `workspace/page.tsx`                      | resizable panels, 2× state refs | per-widget | tokens | per-tab aria | **PASS** |
| `alerts/page.tsx`                         | 3 tabs (Inbox · Relevant News · Top Today) | 19× state refs | tokens | tablist | **PASS** |
| `chat/page.tsx`                           | 9× state refs | OK | tokens | OK | **PASS** |
| `settings/page.tsx`                       | 1 state ref (mostly static palette demo) | OK | hex literals are SHOWN as palette swatches (intentional) | OK | **PASS** |
| `instruments/page.tsx`                    | (search + redirect to `[entityId]`) | OK | tokens | OK | **PASS** |
| `instruments/[entityId]/page.tsx`         | 5-zone right sidebar (PLAN-0053 Wave E) | per-zone empty states | tokens; tabular-nums on prices | OK | **PASS** |
| `news/page.tsx`                           | 307 redirect to `/alerts` | n/a (stub) | n/a | n/a | **PASS** (intentional stub) |
| `watchlists/page.tsx`                     | 307 redirect to `/workspace` | n/a (stub) | n/a | n/a | **PASS** (intentional stub) |
| `feedback/page.tsx` (public)              | 4 state refs | OK | tokens | OK | **PASS** |
| `admin/feedback/page.tsx`                 | (admin list) | not inspected in detail; ships in PLAN-0053 Wave G | tokens | OK | **PASS** |

PLAN-0053 Wave B/D/F/G new components were spot-read:
- `HoldingsMoversWidget`, `MoversWidgetTabs`, `CashManagementCard`, `RecentActivityFeed`, `DividendIncomeTimeline`, `RealizedPnLChart` — all heavily commented (50-200 line files), use design tokens, render via `ResponsiveContainer` inside a fixed-height parent (good).
- Feedback components — `FeedbackModal.tsx` is 422 lines with strong inline "WHY" comments (sample: line 12-27 explains why Sheet not Dialog), Sheet uses `SheetClose/Description/Footer/Header/Title` correctly so a11y is fine.
- `ScreenshotCapture.tsx` (210 lines), `ConsoleLogCapture.tsx` (108 lines), `MicroSurvey.tsx` (118 lines), `NPSPrompt.tsx` (194 lines), `NPSPromptHost.tsx` (69 lines), `FeedbackButton.tsx` (88 lines) — each opens with a JSDoc block explaining purpose.

---

## Anti-pattern grep sweep — all results

| Pattern | Source matches | Verdict |
|---------|----------------|---------|
| `print(` outside `__main__` in services/*/src + libs/*/src | **0** | clean |
| `uuid.uuid4()` in services/*/src | **0** (only legitimate fallback in `libs/common/src/common/ids.py:14,19` and a short-id call in `libs/messaging/src/messaging/kafka/dispatcher/base.py:203`) | clean |
| `logging.getLogger` outside `libs/observability` | **0** (only `libs/observability/src/observability/logging.py:90` — the integration root) | clean |
| Naive `datetime.now()` (no `tz=`) in services/*/src + libs/*/src | **0** | clean |
| `requests.get/post/put/delete` (sync HTTP in async path) | **0** | clean |
| `socket.getaddrinfo` direct in async path | **0** (3 occurrences all use `asyncio.to_thread(socket.getaddrinfo, ...)` — correct pattern; HR-019 compliant) | clean |
| `if not self._consumer:` patterns | **0** | clean |
| F-string SQL via `text(f"...")` | **6** found — all reviewed; each uses `f"..."` only to interpolate placeholder lists like `:t0, :t1, :t2` (count-bounded by `len(input)`) or whitelisted `where_sql` built from internal predicates. NO user input is interpolated. **HR-006 compliant.** | safe |
| `asyncio.wait_for` wrapping httpx without `httpx.Timeout(N)` | **0** (every site that wraps an httpx client sets `httpx.AsyncClient(timeout=httpx.Timeout(N))`; see comment at `services/alert/src/alert/infrastructure/clients/s7_entity_resolver.py:72`) | clean |
| Hardcoded secrets / API keys (high-entropy strings) | **0** (no matches in services/*/src, libs/*/src, apps/worldview-web/app, apps/worldview-web/lib) | clean |
| Inline hex colors in TSX (token violation) | All 30 matches reviewed — every `#XXXXXX` lives inside a JSDoc/inline comment OR is the Settings page's intentional palette-swatch demo data | clean |

The platform's hard-rule discipline outside the architecture-test layer is **excellent**.

---

## Stability hot-spots (priority-ordered)

1. **F-PLATFORM-01 (CRITICAL)** — finish the partial uncommitted patch in `services/nlp-pipeline/tests/unit/infrastructure/workers/test_article_relevance_scoring_worker.py` by setting `result_mock.rowcount = 1` in `_make_session_factory`. 2 lines. Restores nlp-pipeline unit suite to green.
2. **F-PLATFORM-02 (CRITICAL)** — restore the 4 architecture invariants. Apply the pattern from commit `45efe6c7`: introduce Protocol ports, lift the lifespan task, push function-body infrastructure imports behind a port. ~30-60 min. Without this fix, R12 / R22 / R25 are silently violated.
3. **F-PLATFORM-03 (MAJOR)** — 4 sites where AsyncMock is used where a sync MagicMock should be. Each test patch is small (5-10 lines) but uncovers real "did you actually await this in production?" questions. Worth a dedicated 1-hour pass.
4. **F-PLATFORM-04 (MAJOR)** — gate ml-clients integration tests on Ollama availability so they don't fail CI.
5. **F-PLATFORM-06 item 3 (MINOR but real)** — `libs/messaging/src/messaging/valkey/client.py:307` has a real `pubsub.close()` deprecation. Change to `aclose()`.

---

## Documentation drift (spot-check)

- `docs/services/portfolio.md` — read for endpoint freshness; PLAN-0053 added `/v1/portfolios/{id}/realized-pnl` and `/v1/portfolios/{id}/dividends/timeline` — not yet present in the service doc (out of scope per user's "pre-existing acceptable" note since PLAN-0053 docs are tracked in `docs/plans/0053-*.md`).
- `services/portfolio/.claude-context.md` — not inspected in this sweep.
- `infra/prometheus/rules/alert-rules.yml` is modified (in `git status`) — not validated in this sweep but should not block SHIP.

---

## Recommendations (in order)

1. **Block 1 (immediate, ~10 min)** — fix F-PLATFORM-01 by setting `result_mock.rowcount = 1` in the `_make_session_factory` helper, then commit the existing diff. Re-run `services/nlp-pipeline/tests/unit` to confirm 7 → 0 failures.
2. **Block 2 (today, ~60 min)** — fix F-PLATFORM-02 (4 architecture violations). Consider following commit `45efe6c7`'s exact pattern: a single mechanical fix per service.
3. **Block 3 (one-pass cleanup, ~30 min)** — fix F-PLATFORM-05 (2 RUF059), F-PLATFORM-06 (`pubsub.close()` → `aclose()`), F-PLATFORM-11 (`<DialogDescription>`), F-PLATFORM-12 (return null not undefined).
4. **Block 4 (deferred, can land in a follow-up plan)** — F-PLATFORM-03, F-PLATFORM-04, F-PLATFORM-08 (decide on the dangling diffs), F-PLATFORM-09, F-PLATFORM-10. None of these block production stability but all are noise the user explicitly said they want gone ("no warnings or tracebacks anywhere").
5. **Block 5 (recurring hygiene)** — wire `python -m pytest tests/architecture` into the pre-PR hook so the next PLAN-0050-Wave-E-style regression doesn't slip in unnoticed. The architecture-test suite IS the safety net for R12 / R22 / R25 — it must be run on every PR.

---

## Verdict justification

Per the user's verdict rules:
- **SHIP** = zero NEW BLOCKING/CRITICAL findings.
- **NEEDS_FIXES** = any new BLOCKING/CRITICAL or ≥3 new MAJOR.

This sweep finds **2 NEW CRITICAL** issues (F-PLATFORM-01, F-PLATFORM-02), both introduced AFTER PLAN-0053 SHIP (`a1cf288b`). Therefore: **NEEDS_FIXES**.

The good news: PLAN-0053's surface itself is clean. The two CRITICAL items live in PLAN-0055 (dual-write test mock) and PLAN-0050-Wave-E + PLAN-0057 (architecture invariants). They are both small, mechanical fixes — F-PLATFORM-01 is 2 lines, F-PLATFORM-02 follows a commit (`45efe6c7`) with the exact playbook.
