# PLAN-0055 — Auto-Backfill, Source Stability, and LLM Provenance

| Field | Value |
|---|---|
| **Created** | 2026-04-29 |
| **Owner** | Arnau Rodon |
| **Status** | draft |
| **Drives PRD** | None (architectural improvements; no new PRD needed) |
| **Source investigation** | `/investigate` rounds 2026-04-29 (this conversation) |
| **Related PRD that follows** | PRD-0033 Polymarket Comprehensive Ingestion (separate PLAN-0056) |
| **Branch policy** | continue on `feat/content-ingestion-wave-a1` (no merge yet); single PR per sub-plan |

---

## 0. Overview and decomposition

### 0.1 What this plan delivers

Three independent tracks identified in the 2026-04-29 ingestion-architecture investigation:

| Sub-plan | Scope | Risk | Effort |
|---|---|---|---|
| **A — Auto-backfill on startup (S3 + S4)** | Env-driven startup hook, larger chunk_days, raised _MAX_CHUNKS, configurable horizon (default 14d initial, prod ramps to 10y OHLCV / 3y news) | LOW | XS-S |
| **B — S4 source dedup + cursor stability** | `config_hash` column on `sources`, UNIQUE constraint, idempotent `CreateSourceUseCase`, watermark-vs-config drift WARN | LOW | XS |
| **C — LLM provenance + replay endpoint + relevance materialization** | New `document_source_llm_scores` table, worker rewrite to append-only, `POST /admin/llm-replay` endpoint, materialized view `document_source_llm_latest` with renormalized fallback formula | MEDIUM | M |

### 0.2 Decomposition rationale

Sub-plans A and B are mechanically simple and zero-risk. They ship first to give immediate "deploy and walk away" semantics and cursor stability. Sub-plan C is the architectural improvement that closes the LLM provenance gap; it's larger because it requires schema migration, worker rewrite, API surface change, and a materialized-view caching strategy.

The three sub-plans are **independent at the wave level** — no cross-sub-plan dependencies. They can be implemented sequentially or in parallel worktrees.

### 0.3 Decisions baked in (from user prompt)

| Decision | Resolution |
|---|---|
| Default backfill auto-trigger | `true` in worldview-gitops `values/*.yaml` (prod) AND in `env/dev/*.env` (compose) |
| Initial backfill horizon | **14 days for ALL streams** to validate the capability without burning provider/LLM budget |
| Configurable max | OHLCV: up to 10 years (`MARKET_INGESTION_AUTO_BACKFILL_YEARS=10`); news: up to 3 years (`CONTENT_INGESTION_BACKFILL_YEARS=3`) |
| Polymarket entity scope | Routed through S6 NER pipeline as synthetic documents (PRD-0033) |
| LLM relevance fallback strategy | Keep `display_relevance_score` formula. When `llm_relevance_score IS NULL`, **renormalize weights** (0.5/0.6 market + 0.1/0.6 routing = 0.83 + 0.17). Implementation via materialized view (Sub-Plan C, Wave C-3). |

### 0.4 Plan dependency graph

```
                            ┌─ Sub-Plan A (S3+S4 auto-backfill) ─┐
                            │                                    │
[no dependencies] ──────────┼─ Sub-Plan B (source dedup)         │── PR review → merge
                            │                                    │
                            └─ Sub-Plan C (LLM provenance) ──────┘
```

All sub-plans land on `feat/content-ingestion-wave-a1`. Each as a separate commit; squash-merge as one PR after final QA.

### 0.5 Total scope

| Sub-plan | Waves | Tasks | New env vars | New tables | New endpoints |
|---|---|---|---|---|---|
| A | 3 | 11 | 6 | 0 | 0 |
| B | 1 | 4 | 0 | 0 (extends 1) | 0 |
| C | 4 | 14 | 1 | 1 (+1 view) | 1 |
| **Total** | **8** | **29** | **7** | **1+1view** | **1** |

Estimated total effort: 4-6 implementer-days across all sub-plans.

---

## 1. Codebase state verification (read from source)

Verified during /investigate rounds; reproduced here for /implement:

| PRD reference | Type | Service | Actual current state | Target state | Delta |
|---|---|---|---|---|---|
| `BackfillUseCase.execute(chunk_days=90)` | code | S3 | `chunk_days: int = 90` at `services/market-ingestion/src/market_ingestion/application/use_cases/backfill.py:48` | `chunk_days: int = 365` (daily) / `90` (intraday) | bump default + add per-timeframe logic |
| `_MAX_CHUNKS = 100` | constant | S3 | `services/market-ingestion/src/market_ingestion/application/use_cases/backfill.py:19` | `_MAX_CHUNKS = 500` | constant bump |
| `auto_backfill_on_startup` | config | S3 | does not exist | new field on Settings | add with default `False` |
| `backfill_on_startup` | config | S4 | does not exist (only `backfill_enabled`) | new field on Settings | add with default `False` |
| `sources` table UNIQUE constraint | DB | S4 | UNIQUE on `name` only (`services/content-ingestion/src/content_ingestion/infrastructure/db/models.py:31-41`) | UNIQUE on `(source_type, config_hash)` | new generated column + new constraint |
| `CreateSourceUseCase` | code | S4 | naive INSERT (`services/content-ingestion/src/content_ingestion/application/use_cases/create_source.py:37-52`) | INSERT ON CONFLICT DO NOTHING RETURNING id | rewrite |
| `document_source_metadata.llm_relevance_score` | DB | S6 | `Numeric(6,4)` nullable, no `model_id` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py:232-233`) | deprecated; latest values served via `document_source_llm_latest` materialized view | data movement + view + worker rewrite |
| `document_source_llm_scores` table | DB | S6 | does not exist | new append-only table | new migration `0012_llm_provenance.py` |
| `article_impact_windows` UNIQUE constraint | DB | S6 | **UNIQUE INDEX** (not a named UNIQUE CONSTRAINT) — `idx_article_impact_windows_unique` on `(article_id, entity_id, window_type)` (migration 0009, line 116: `CREATE UNIQUE INDEX`) | UNIQUE CONSTRAINT `uq_article_impact_windows_dedup` on `(article_id, entity_id, window_type, model_id, prompt_version)` | drop index → create named constraint (`migration 0012`) |
| `ArticleRelevanceScoringWorker` | code | S6 | UPDATE-style writes to `document_source_metadata` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py:296-322`) | INSERT-only writes to `document_source_llm_scores`, ON CONFLICT DO NOTHING | worker rewrite |
| `POST /api/v1/reprocess/{article_id}` | endpoint | S6 | exists, single article (`services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py:240`) | unchanged; new `POST /api/v1/admin/llm-replay` added alongside | additive |
| Routing weights env vars | config | S3 | exist (`MARKET_INGESTION_ROUTING_OHLCV_EOD=yahoo_finance:100,eodhd:80`) | unchanged (auto-backfill must respect them) | add invariant test |
| `CONTENT_INGESTION_BACKFILL_ENABLED` | env | S4 | exists, default `false` (`worldview-gitops/env/dev/content-ingestion.env:35`) | preserved; new `BACKFILL_ON_STARTUP` is independent | additive |

---

## 2. Sub-Plan A — Auto-backfill on startup

### A.0 Scope

Add env-driven, non-blocking, idempotent startup backfill for both S3 (market data) and S4 (content). Bump default chunk size and max-chunks to allow long horizons in fewer API calls. Default `BACKFILL_ON_STARTUP=true` with **horizon = 14 days** in both dev compose and prod gitops; configurable up to 10y OHLCV / 3y news.

### A.1 Wave A-1: Config and chunk-size changes

**Goal**: Land all configuration and constant changes in the codebase. No behavior change yet — auto-backfill remains gated on env until Wave A-2.

**Depends on**: none
**Estimated effort**: 30-45 minutes
**Architecture layer**: domain + config

#### Pre-read

- `services/market-ingestion/src/market_ingestion/config.py` (full file)
- `services/market-ingestion/src/market_ingestion/application/use_cases/backfill.py` (full file)
- `services/content-ingestion/src/content_ingestion/config.py` (full file)
- `worldview-gitops/env/dev/market-ingestion.env`
- `worldview-gitops/env/dev/content-ingestion.env`
- `worldview-gitops/values/market-ingestion.yaml`
- `worldview-gitops/values/content-ingestion.yaml`

#### Tasks

##### T-A-1-01: Bump S3 backfill defaults

**Type**: impl
**depends_on**: none
**blocks**: T-A-2-01
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/backfill.py`
**PRD reference**: §A.0

**What to build**:
Bump `_MAX_CHUNKS` to 500 (line 19). Change `BackfillUseCase.execute()` signature so `chunk_days` defaults remain backwards-compatible but a new `_default_chunk_days_for_timeframe(tf)` helper returns 365 for `"1d"`/`"1w"`/`"1mo"`/`"1M"` and 30 for any intraday timeframe (`"1m"` through `"4h"`). Modify the auto-backfill caller (Wave A-2) to use the helper; existing direct callers retain their explicit `chunk_days` values.

**Logic & Behavior**:
- Add module-level helper `_default_chunk_days_for_timeframe(tf: str) -> int` returning 365 for daily-or-coarser, 30 for intraday.
- Keep existing `chunk_days: int = 90` default on `execute()` for backward compat with the existing API endpoint.
- Update docstring on `BackfillUseCase` to mention the helper and the `_MAX_CHUNKS = 500` bump.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| test_default_chunk_days_daily | `_default_chunk_days_for_timeframe("1d") == 365` | unit |
| test_default_chunk_days_intraday | `_default_chunk_days_for_timeframe("5m") == 30` | unit |
| test_max_chunks_500_no_raise | A 365-day × 500-chunk range builds successfully | unit |
| test_max_chunks_501_raises | 501 chunks raises ValueError | unit |
| test_existing_default_unchanged | `BackfillUseCase(...).execute(...)` without chunk_days arg still uses 90 | unit |

Minimum tests: 5
Edge cases: zero-day range, exactly-_MAX_CHUNKS range
Error paths: ValueError on excess chunks (preserved)

**Downstream test impact**:
- `services/market-ingestion/tests/unit/use_cases/test_backfill.py` — existing assertions around `_MAX_CHUNKS = 100` must update to 500.

**Acceptance criteria**:
- [ ] `ruff check` clean
- [ ] `mypy` clean on `market_ingestion.application.use_cases.backfill`
- [ ] All 5 new tests pass; existing test still passes (with constant bump)
- [ ] No behavior change to existing `/api/v1/ingest/backfill` endpoint when chunk_days omitted

##### T-A-1-02: Add S3 auto-backfill config fields

**Type**: config
**depends_on**: none
**blocks**: T-A-2-01, T-A-3-01
**Target files**: `services/market-ingestion/src/market_ingestion/config.py`
**PRD reference**: §A.0

**What to build**:
Add three pydantic-settings fields to `Settings`:
- `auto_backfill_on_startup: bool = False`
- `auto_backfill_years: int = 10`
- `auto_backfill_initial_days: int = 14`

The two horizon fields drive a min(`auto_backfill_initial_days`, `auto_backfill_years * 365`) selection at runtime so an operator can ratchet the horizon up by changing only `auto_backfill_initial_days` without redeploying. Default disabled; gitops will set true.

**Logic & Behavior**:
- pydantic-settings auto-binds to env vars `MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP`, `MARKET_INGESTION_AUTO_BACKFILL_YEARS`, `MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS`.
- Validate `auto_backfill_initial_days >= 1` and `auto_backfill_years >= 1` via pydantic `Field(ge=1)`.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| test_settings_default_off | Settings() has `auto_backfill_on_startup=False`, `auto_backfill_initial_days=14`, `auto_backfill_years=10` | unit |
| test_settings_env_override | Setting env vars yields correct fields | unit |
| test_settings_validation_zero_days | `auto_backfill_initial_days=0` raises ValidationError | unit |

**Downstream test impact**:
- `services/market-ingestion/tests/unit/test_config.py` — add new fields to whatever default-fixture builds Settings.

**Acceptance criteria**:
- [ ] Three new fields exist and parse from env
- [ ] `mypy --strict` clean
- [ ] All 3 new tests pass

##### T-A-1-03: Add S4 auto-backfill config fields

**Type**: config
**depends_on**: none
**blocks**: T-A-2-02, T-A-3-02
**Target files**: `services/content-ingestion/src/content_ingestion/config.py`
**PRD reference**: §A.0

**What to build**:
Mirror of T-A-1-02 for S4. Three fields:
- `backfill_on_startup: bool = False`
- `backfill_years: int = 3`
- `backfill_initial_days: int = 14`

Note: existing `backfill_enabled` remains and gates per-source backfill behavior independently. The new `backfill_on_startup` is the orchestration trigger.

**Tests**: mirror of T-A-1-02. 3 new tests.

**Acceptance criteria**:
- [ ] Three new fields exist
- [ ] mypy clean
- [ ] Existing `backfill_enabled` semantics unchanged

##### T-A-1-04: Update gitops env files (compose dev)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `worldview-gitops/env/dev/market-ingestion.env`, `worldview-gitops/env/dev/content-ingestion.env`
**PRD reference**: §A.0, user decision §0.3

**What to build**:
Append the six new env vars with the agreed defaults:

```
# market-ingestion.env
MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP=true
MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS=14
MARKET_INGESTION_AUTO_BACKFILL_YEARS=10
```

```
# content-ingestion.env
CONTENT_INGESTION_BACKFILL_ON_STARTUP=true
CONTENT_INGESTION_BACKFILL_INITIAL_DAYS=14
CONTENT_INGESTION_BACKFILL_YEARS=3
```

Add an inline comment above each block referencing this plan.

**Acceptance criteria**:
- [ ] Six new env lines present
- [ ] `scripts/setup-dev.sh` (which copies these to `services/*/configs/docker.env`) confirmed unchanged-and-still-valid via dry-run

##### T-A-1-05: Update gitops Helm values (k8s prod)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `worldview-gitops/values/market-ingestion.yaml`, `worldview-gitops/values/content-ingestion.yaml`
**PRD reference**: §A.0

**What to build**:
Mirror the six env vars in the `env:` list of each Helm values file. Same default values as compose.

**Acceptance criteria**:
- [ ] Six new env entries in each values file
- [ ] `helm template` against the chart produces a valid Deployment manifest with the new envs

#### Pre-read for /implement (Wave A-1)

- All files in T-A-1-0X target lists
- `services/market-ingestion/src/market_ingestion/main.py` (just to understand startup wiring; no edits this wave)

#### Validation Gate (Wave A-1)

- [ ] `ruff check services/market-ingestion services/content-ingestion` clean
- [ ] `mypy services/market-ingestion/src services/content-ingestion/src` clean
- [ ] 11 new unit tests pass (5 + 3 + 3)
- [ ] No production behavior change — auto-backfill remains off by default at runtime; only the *defaults* and *configurability* shifted

#### Break Impact (Wave A-1)

| Broken file | Why | Fix |
|---|---|---|
| `services/market-ingestion/tests/unit/use_cases/test_backfill.py` | `_MAX_CHUNKS = 100` assertions | bump to 500 in any constant assert |
| `services/market-ingestion/tests/unit/test_config.py` | new fields on Settings | extend default-fixture |
| `services/content-ingestion/tests/unit/test_config.py` | same | same |

#### Regression Guardrails (Wave A-1)

- **BP-019** (constants in 2 places): the bump from 100 → 500 is a single source of truth; no copy elsewhere — verified via `grep -r "_MAX_CHUNKS"`.
- **BP-032** (env var name typos): use exactly the `MARKET_INGESTION_AUTO_BACKFILL_*` and `CONTENT_INGESTION_BACKFILL_*` prefixes that pydantic-settings auto-resolves; cross-check both `.env` and `values.yaml` for typos.
- **BP-179** (pydantic-settings empty-string Optional gotcha): the new fields are non-Optional `int`/`bool`, so this BP doesn't apply, but the existing pattern in the codebase must not be regressed.

---

### A.2 Wave A-2: S3 startup hook

**Goal**: Wire a non-blocking startup task in S3 that calls `BackfillUseCase` for every enabled `polling_policy` once, gated by `auto_backfill_on_startup`.

**Depends on**: T-A-1-01, T-A-1-02
**Estimated effort**: 60 minutes
**Architecture layer**: application + main wiring

#### Tasks

##### T-A-2-01: Implement `RunStartupBackfillUseCase`

**Type**: impl
**depends_on**: T-A-1-01, T-A-1-02
**blocks**: T-A-2-02 (no — but ordering for review clarity)
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/run_startup_backfill.py` (new), `services/market-ingestion/src/market_ingestion/application/use_cases/__init__.py`
**PRD reference**: §A.0

**What to build**:
A new use case that:
1. Reads `Settings` to determine `enabled` + horizon.
2. Calls `PollingPolicyRepository.list_enabled()` (the only method on the port that returns all enabled policies — `list_enabled_with_backfill()` does not exist). Filter in-memory: `[p for p in policies if p.backfill_enabled]`.
3. For each backfill-enabled policy, computes `horizon_start = now - timedelta(days=settings.auto_backfill_initial_days)`.
4. Skips any policy where `policy.backfill_start_date is not None and policy.backfill_start_date <= horizon_start` — this means we already have a backfill covering this window (no `backfill_status` field exists on `PollingPolicy`; `backfill_start_date` is the only cursor).
5. Calls `BackfillUseCase.execute(...)` with `chunk_days = _default_chunk_days_for_timeframe(policy.timeframe)`.
6. Resolves `provider` via `ProviderRoutingCache.primary_for(dataset_type, timeframe)` (existing — `MARKET_INGESTION_ROUTING_OHLCV_EOD` etc.); falls back to `str(policy.provider)` if no route.
7. Catches per-policy failures (logs WARN, continues).
8. Logs summary at end: total enqueued, skipped, failed.

**Entities / Components**:
- **Name**: `RunStartupBackfillUseCase`
- **Purpose**: One-shot orchestrator invoked at startup
- **Key attributes**: takes `uow_factory: Callable[[], UnitOfWork]`, `settings: Settings`, `routing: ProviderRoutingCache`
- **Key methods**:
  - `async def execute(self) -> StartupBackfillSummary`
- **Invariants**: must not raise on per-policy failure (best-effort)
- **Depends on**: existing `BackfillUseCase`, `PollingPolicyRepository.list_enabled()` (filter by `policy.backfill_enabled` in-memory; `list_enabled_with_backfill()` does not exist on the port)

**Logic & Behavior**:
- Idempotent: re-running on a restarted container checks `policy.backfill_start_date` against the horizon; if the policy already has a `backfill_start_date` ≤ `horizon_start`, it is skipped. The `backfill_start_date` is set by the existing `WatermarkUseCase` once backfill tasks are claimed and executed — the startup hook only enqueues.
- Note: `PollingPolicy` has no `backfill_status` field. Skip detection is purely based on `backfill_start_date`.
- All work happens in a single fresh transaction per policy (via `uow_factory()`).
- Returns a `StartupBackfillSummary(enqueued: int, skipped: int, failed: int)` for logging.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| test_disabled_no_op | `auto_backfill_on_startup=False` → executes 0 calls to BackfillUseCase | unit |
| test_enabled_calls_backfill_for_each_policy | 3 enabled policies → 3 BackfillUseCase calls | unit |
| test_skips_covered_policies | A policy with `backfill_start_date <= horizon_start` (i.e. already backfilled past the window) is skipped | unit |
| test_per_policy_failure_isolated | One policy raises; the other 2 still get called; summary.failed=1 | unit |
| test_uses_routing_provider | Policy provider is overridden by routing cache when route exists | unit |

Minimum tests: 5
Edge cases: empty policy list, all-skipped, all-failed
Error paths: per-policy exception caught and logged

**Downstream test impact**:
- None at this layer (existing BackfillUseCase unchanged).

**Acceptance criteria**:
- [ ] Use case file created with full type annotations
- [ ] 5 unit tests pass
- [ ] mypy clean
- [ ] No imports from `infrastructure/` (R12)

##### T-A-2-02: Wire startup hook in S3 scheduler process

**Type**: impl
**depends_on**: T-A-2-01
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/scheduler/scheduler.py`
**PRD reference**: §A.0

**Why scheduler, not API lifespan**: The FastAPI `app.py` lifespan stores only `write_session_factory`, `read_session_factory`, `metrics`, `settings`, and `_jwt_middleware` — it does NOT store `uow_factory` or `routing_cache` in `app.state`. Building those in the API process would duplicate the scheduler's setup and violate R22 (independent processes). The scheduler process already builds `_write_factory` / `_read_factory` in `__init__` and knows all policies. It is the correct owner of backfill orchestration.

**What to build**:
Add to `SchedulerProcess.run()`, immediately before the main loop starts:

```python
async def run(self) -> None:
    logger.info("scheduler_starting", ...)

    # Non-blocking startup backfill — spawned as a background task so the
    # scheduler loop begins immediately without waiting for backfill to complete.
    if self._settings.auto_backfill_on_startup:
        routing = ProviderRoutingCache()
        routing.load_from_config(self._settings)
        use_case = RunStartupBackfillUseCase(
            uow_factory=lambda: SqlaUnitOfWork(self._write_factory, self._read_factory),
            settings=self._settings,
            routing=routing,
        )
        asyncio.create_task(_run_startup_backfill(use_case), name="startup_backfill")

    # Main scheduler loop unchanged below
    while not self._stop_event.is_set():
        ...
```

```python
async def _run_startup_backfill(use_case: RunStartupBackfillUseCase) -> None:
    try:
        summary = await use_case.execute()
        logger.info("startup_backfill_completed", **asdict(summary))
    except Exception as exc:  # noqa: BLE001
        logger.exception("startup_backfill_failed", error=str(exc))
```

The `create_task` makes backfill fire-and-forget — the scheduler loop starts its first tick without waiting, so the system is operational immediately.

**Tests to write**:
| Test name | What it verifies | Type |
|---|---|---|
| test_startup_backfill_task_created_when_enabled | `auto_backfill_on_startup=True` → `RunStartupBackfillUseCase.execute` called once | unit |
| test_startup_backfill_skipped_when_disabled | `auto_backfill_on_startup=False` → `execute` never called | unit |
| test_scheduler_loop_starts_without_waiting_for_backfill | Scheduler's first `_tick()` fires before backfill mock completes (mock backfill sleeps 0.1s; tick fires within 0.01s) | unit |

Minimum tests: 3 unit (no integration tests needed — the hook is a simple conditional spawn)

**Downstream test impact**:
- `services/market-ingestion/tests/unit/infrastructure/scheduler/test_scheduler.py` (if it exists) — extend to cover the new backfill branch.
- None for API tests — the hook lives in the scheduler process, not the API.

**Acceptance criteria**:
- [ ] Hook in `SchedulerProcess.run()`, gated by `settings.auto_backfill_on_startup`
- [ ] `asyncio.create_task` used (not `await`)
- [ ] 3 unit tests pass
- [ ] Manual run: `MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP=true make dev-rebuild` → scheduler logs `startup_backfill_completed` within 30s of startup

#### Validation Gate (Wave A-2)

- [ ] All tests in Wave A-1 still pass
- [ ] 8 new tests added in this wave pass (5 unit T-A-2-01 + 3 unit T-A-2-02)
- [ ] Manual smoke: `MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP=true MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS=14 make dev-rebuild` → scheduler container logs `startup_backfill_completed` within 30s
- [ ] API `/health` is unaffected (hook lives in scheduler process, not API)

#### Break Impact (Wave A-2)

| Broken file | Why | Fix |
|---|---|---|
| `services/market-ingestion/tests/unit/infrastructure/scheduler/test_scheduler.py` | `SchedulerProcess.run()` now has a conditional branch | extend with `auto_backfill_on_startup=True/False` variants |

#### Regression Guardrails (Wave A-2)

- **BP-026** (sync I/O in async): the use case must not call any blocking provider client; it only enqueues DB tasks. The task queue + worker consume the API calls.
- **BP-027** (httpx default 5s timeout): N/A here — no HTTP from this use case.
- **BP-007** (transaction-per-iteration): each policy's enqueue must be its own transaction; failure in one must not poison the next.

---

### A.3 Wave A-3: S4 startup hook + watermark seed

**Goal**: Same pattern as A-2 but for S4 (content). Set `last_watermark = NOW() - INTERVAL <initial_days>` for any source where it's NULL, then let the regular scheduler tick pick up the work.

**Depends on**: T-A-1-03
**Estimated effort**: 45-60 minutes
**Architecture layer**: application + main wiring

#### Tasks

##### T-A-3-01: Implement `SeedSourceWatermarksUseCase`

**Type**: impl
**depends_on**: T-A-1-03
**blocks**: T-A-3-02
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/seed_source_watermarks.py` (new)
**PRD reference**: §A.0

**What to build**:
A use case that:
1. Reads `Settings.backfill_on_startup` and short-circuits if False.
2. Iterates all enabled `Source` rows.
3. For each source, fetches its `SourceAdapterState`. If `last_watermark IS NULL`, set it to `now - timedelta(days=settings.backfill_initial_days)`.
4. If `last_watermark` exists but `last_watermark > now - INTERVAL <initial_days>` AND `settings.backfill_enabled=True`, leave alone (steady-state).
5. Returns a summary `SeedWatermarkSummary(seeded: int, skipped: int)`.

**Entities / Components**:
- **Name**: `SeedSourceWatermarksUseCase`
- **Purpose**: Initialize cursor for fresh sources at first deploy
- **Key methods**: `async def execute(self) -> SeedWatermarkSummary`
- **Invariants**: never advances a cursor backward in time

**Logic & Behavior**:
- Idempotent: subsequent runs (after watermarks are set) are no-ops.
- Safe to run on every startup.
- The actual fetching happens via the existing scheduler tick — this use case only seeds the cursor.

**Tests to write** (5 unit):
| Test | Verifies |
|---|---|
| test_disabled_no_op | flag False → 0 sources touched |
| test_seeds_null_watermarks | source with NULL watermark gets seeded to now-14d |
| test_skips_existing_watermarks | source with non-NULL watermark is left alone |
| test_per_source_failure_isolated | one source fails, others still seed |
| test_returns_summary | summary counts match |

**Acceptance criteria**:
- [ ] 5 tests pass
- [ ] mypy clean
- [ ] No infrastructure imports (R12)

##### T-A-3-02: Wire S4 startup hook

**Type**: impl
**depends_on**: T-A-3-01
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/main.py` (or equivalent)
**PRD reference**: §A.0

**What to build**: Mirror of T-A-2-02. Spawn `SeedSourceWatermarksUseCase` via `asyncio.create_task` in lifespan; non-blocking.

**Tests to write** (2 integration):
| Test | Verifies |
|---|---|
| test_startup_seeds_watermarks | Container start → after 5s, sources have non-NULL watermarks |
| test_startup_does_not_block_health | `/health` returns 200 within 100ms |

**Acceptance criteria**:
- [ ] Hook in lifespan
- [ ] 2 integration tests pass

##### T-A-3-03: Documentation update

**Type**: docs
**depends_on**: none (informational)
**blocks**: none
**Target files**: `docs/services/market-ingestion.md`, `docs/services/content-ingestion.md`, `worldview-gitops/docs/ENV_AUDIT.md`
**PRD reference**: §A.0

**What to build**:
- New section "Auto-Backfill on Startup" in each service doc, listing the new env vars, default values, the chunk-days helper, and the safety mechanisms (per-policy isolation, idempotency).
- ENV_AUDIT.md row per new env var: name, default, purpose, where consumed.

**Acceptance criteria**:
- [ ] Three docs updated
- [ ] Env vars cross-referenced

#### Validation Gate (Wave A-3)

- [ ] All tests through A-1 and A-2 still pass
- [ ] 7 new tests pass (5 unit + 2 integration)
- [ ] Documentation reflects new env vars
- [ ] Manual smoke: bring up dev stack with envs true, observe seeded watermarks within 30s of startup, observe S4 scheduler tick fetching backwards-in-time

#### Break Impact (Wave A-3)

| Broken file | Why | Fix |
|---|---|---|
| `services/content-ingestion/tests/integration/test_main.py` | startup adds task | adjust |

#### Regression Guardrails (Wave A-3)

- **BP-180** (asyncpg ambiguous param): when seeding, the `UPDATE ... WHERE last_watermark IS NULL` must use `CAST(:value AS TIMESTAMPTZ)` if any param is nullable; verify before merge.
- **BP-007** (per-row transactions): seed each source in its own UoW.

---

## 3. Sub-Plan B — S4 source dedup and cursor stability

### B.0 Scope

Add a generated `config_hash` column to `sources`, UNIQUE constraint on `(source_type, config_hash)`, rewrite `CreateSourceUseCase` to be idempotent, and add a startup invariant that WARNs if a source's config has drifted since last fetch.

### B.1 Wave B-1: Migration + use-case rewrite + invariant

**Goal**: Single wave delivering all of Sub-Plan B.

**Depends on**: none (independent of Sub-Plan A)
**Estimated effort**: 45-60 minutes
**Architecture layer**: schema + application

#### Pre-read

- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`
- `services/content-ingestion/src/content_ingestion/application/use_cases/create_source.py`
- `services/content-ingestion/alembic/versions/0001_initial_s4_schema.py`
- Most recent S4 migration (`alembic heads`)
- `services/content-ingestion/.claude-context.md`

#### Tasks

##### T-B-1-01: Alembic migration — add `config_hash` + UNIQUE

**Type**: schema
**depends_on**: none
**blocks**: T-B-1-02, T-B-1-03
**Target files**: `services/content-ingestion/alembic/versions/00XX_sources_dedup_constraint.py` (new)
**PRD reference**: Sub-Plan B §0

**What to build**:
- Add column `config_hash CHAR(64) NOT NULL` as a generated column from `encode(digest(config::text, 'sha256'), 'hex')`. Requires the `pgcrypto` extension — **already added** to `infra/postgres/init/init-databases.sh` for `content_ingestion_db` (B-001 fix). Verify with `SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'` in a test DB before running the migration.
- Add UNIQUE constraint `uq_sources_dedup` on `(source_type, config_hash)`.
- Add explicit comment on the column: `"Generated SHA-256 of canonical config — drives dedup constraint."`

**Logic & Behavior**:
- Generated column means we never write to it — Postgres maintains it.
- Existing rows: backfill works because the GENERATED column is computed from existing data on add-column — verify with a test migration on a copy.
- Rollback: drop UNIQUE + drop column.

**Tests to write**:
| Test | Verifies |
|---|---|
| test_migration_upgrade_idempotent | apply on a DB with N rows → all rows have config_hash; running upgrade twice is a no-op |
| test_migration_rollback | downgrade returns to pre-state |
| test_unique_blocks_dup | INSERT a dup `(source_type, config)` → IntegrityError |

**Downstream test impact**:
- `services/content-ingestion/tests/integration/test_migrations.py` — if exists, may need a new migration head check.

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds on a freshly-seeded DB
- [ ] `alembic downgrade -1` succeeds
- [ ] 3 tests pass
- [ ] pgcrypto verified enabled in compose Postgres init script

##### T-B-1-02: Update `Source` ORM model

**Type**: impl
**depends_on**: T-B-1-01
**blocks**: T-B-1-03
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`
**PRD reference**: Sub-Plan B §0

**What to build**:
Add `config_hash: Mapped[str] = mapped_column(String(64), Computed("encode(digest(config::text, 'sha256'), 'hex')", persisted=True), nullable=False)`. Mark as `init=False` so the dataclass doesn't expect it on construction.

**Tests to write**:
| Test | Verifies |
|---|---|
| test_orm_reads_config_hash | INSERT a row, reload via SELECT, `config_hash` is populated |
| test_orm_does_not_write_config_hash | mock cursor sees no INSERT-list reference to config_hash |

**Acceptance criteria**:
- [ ] Column declared in ORM
- [ ] 2 tests pass

##### T-B-1-03: Rewrite `CreateSourceUseCase` — idempotent insert

**Type**: impl
**depends_on**: T-B-1-02
**blocks**: T-B-1-04
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/create_source.py`, the `SourceRepository` port
**PRD reference**: Sub-Plan B §0

**What to build**:
Change the `create()` path to:
```sql
INSERT INTO sources (id, name, source_type, config, enabled)
VALUES (...)
ON CONFLICT ON CONSTRAINT uq_sources_dedup
DO UPDATE SET enabled = EXCLUDED.enabled  -- harmless touch to make RETURNING return the existing id
RETURNING id, ...
```
Returning `(source, was_created: bool)` — caller handles the no-op-create case.

**Tests to write**:
| Test | Verifies |
|---|---|
| test_first_call_creates | new (source_type, config) → was_created=True, new UUID |
| test_second_call_with_same_config_returns_existing | second call with same input → was_created=False, original UUID |
| test_different_config_creates_new_row | (eodhd, AAPL.US) and (eodhd, MSFT.US) are 2 rows |
| test_returning_id_matches_orm | the returned id equals `SELECT id WHERE source_type=... AND config_hash=...` |

**Acceptance criteria**:
- [ ] 4 tests pass
- [ ] Existing callers updated to handle `was_created` (warn-log if False but enabled changed; otherwise silent)
- [ ] mypy clean

##### T-B-1-04: Startup invariant — config-drift WARN

**Type**: impl
**depends_on**: T-B-1-03
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/main.py` (lifespan)
**PRD reference**: Sub-Plan B §0

**What to build**:
On startup, after the DB pool is up, run a one-shot query:
```sql
SELECT s.id, s.name, s.last_run_config_hash, s.config_hash
FROM sources s
JOIN source_adapter_state sas ON sas.source_id = s.id
WHERE s.last_run_config_hash IS NOT NULL
  AND s.last_run_config_hash != s.config_hash;
```
Note: this query references a new column `last_run_config_hash` on `source_adapter_state` (or on `sources` itself). Add this column in the same migration as T-B-1-01 (extend the migration). On every successful fetch, the existing watermark-update path should set `last_run_config_hash = source.config_hash`.

For each row returned, log a structlog WARN: `config_drift_detected source_id=... old_hash=... new_hash=... — last_watermark may refer to old config`.

**Tests to write** (1 integration): `test_startup_logs_drift_warning` — seed two sources, mutate one's `config`, restart, observe WARN.

**Acceptance criteria**:
- [ ] Startup query runs once, ≤ 50ms on N=1000 sources
- [ ] WARN logged on drift
- [ ] No FAIL — drift is informational

#### Validation Gate (Wave B-1)

- [ ] Migration + downgrade clean
- [ ] 10 new tests pass (3 + 2 + 4 + 1)
- [ ] Existing S4 unit tests unaffected
- [ ] Restart-twice with no config change → no WARN

#### Break Impact (Wave B-1)

| Broken file | Why | Fix |
|---|---|---|
| `services/content-ingestion/tests/unit/use_cases/test_create_source.py` | return shape changed | update assertions to unpack `(source, was_created)` |
| Seed scripts (`scripts/seed_sources.py` if exists) | now idempotent — ON CONFLICT path | no change required; behavior is strictly better |

#### Regression Guardrails (Wave B-1)

- **BP-007** (transaction boundary): the INSERT ON CONFLICT must be a single statement; do not split SELECT-then-INSERT.
- **BP-019** (constants in 2 places): the canonical-JSON serialization (sort_keys, no whitespace) must match between Python ORM expectations and the Postgres `digest(config::text)` — verify with a unit test that constructs a known config and asserts its hash.
- **BP-126** (NOT NULL without server_default): the `config_hash` column is GENERATED, so this BP doesn't apply, but verify the migration doesn't add a NOT NULL column without a server_default for any future ALTER.

---

## 4. Sub-Plan C — LLM provenance, replay endpoint, relevance materialization

### C.0 Scope

Largest sub-plan. Four waves:
- **Wave C-1**: New `document_source_llm_scores` table + `article_impact_windows` constraint change.
- **Wave C-2**: `ArticleRelevanceScoringWorker` rewrite (append-only).
- **Wave C-3**: Materialized view `document_source_llm_latest` + renormalized fallback formula in S6 read path.
- **Wave C-4**: `POST /api/v1/admin/llm-replay` endpoint + replay job consumer.

### C.1 Wave C-1: New schema for LLM provenance

**Goal**: Land the migration. No code change to workers yet.

**Depends on**: none
**Estimated effort**: 60 minutes
**Architecture layer**: schema

#### Pre-read

- `services/nlp-pipeline/alembic/versions/0009_article_impact_windows.py`
- `services/nlp-pipeline/alembic/versions/0011_add_sentiment_impact_to_document_source_metadata.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py:214-291`
- `services/nlp-pipeline/.claude-context.md`

#### Tasks

##### T-C-1-01: Migration — create `document_source_llm_scores`

**Type**: schema
**depends_on**: none
**blocks**: T-C-1-02, T-C-2-01
**Target files**: `services/nlp-pipeline/alembic/versions/0012_llm_provenance.py` (new; current head is `0011`)
**PRD reference**: Sub-Plan C §0

**What to build**:
Migration body (sketch — full SQL in /implement):
```python
def upgrade():
    op.create_table(
        "document_source_llm_scores",
        sa.Column("id", pg.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("doc_id", pg.UUID, nullable=False),
        sa.Column("score_type", sa.String(32), nullable=False),
        sa.Column("score_value", sa.Numeric(6, 4), nullable=True),
        sa.Column("score_label", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("doc_id", "score_type", "model_id", "prompt_version", name="uq_dsls_dedup"),
        sa.CheckConstraint("score_type IN ('relevance', 'sentiment', 'impact_label')", name="ck_dsls_score_type"),
    )
    op.create_index("ix_dsls_doc", "document_source_llm_scores", ["doc_id"])
    op.create_index("ix_dsls_doc_score_latest", "document_source_llm_scores",
                    ["doc_id", "score_type", sa.text("generated_at DESC")])

    # article_impact_windows: add provenance + change UNIQUE
    op.add_column("article_impact_windows", sa.Column("model_id", sa.String(128), nullable=True))
    op.add_column("article_impact_windows", sa.Column("prompt_version", sa.String(32), nullable=True))
    op.add_column("article_impact_windows", sa.Column("input_hash", sa.String(64), nullable=True))
    # The existing uniqueness is a bare UNIQUE INDEX (not a named UNIQUE CONSTRAINT) created in
    # migration 0009 as: CREATE UNIQUE INDEX idx_article_impact_windows_unique ON article_impact_windows
    # (article_id, entity_id, window_type). op.drop_constraint() would fail — must use drop_index().
    op.drop_index("idx_article_impact_windows_unique", table_name="article_impact_windows")
    op.create_unique_constraint(
        "uq_article_impact_windows_dedup",
        "article_impact_windows",
        ["article_id", "entity_id", "window_type", "model_id", "prompt_version"],
    )
```

Note: the new columns on `article_impact_windows` are **nullable** so existing rows survive the migration. Worker rewrite (C-2) will populate them on next write.

**Tests to write**:
| Test | Verifies |
|---|---|
| test_upgrade_creates_table | columns + constraints present |
| test_unique_blocks_dup | dup `(doc_id, score_type, model_id, prompt_version)` → IntegrityError |
| test_aiw_constraint_changed | the renamed UNIQUE allows multiple model_id versions for the same `(article_id, entity_id, window_type)` |
| test_downgrade | clean revert |

**Downstream test impact**:
- `services/nlp-pipeline/tests/contract/test_alembic_heads.py` — if it asserts the head revision, update.
- `tests/contract/test_avro_schemas.py` — N/A (no Avro change).

**Acceptance criteria**:
- [ ] `alembic upgrade head` clean
- [ ] `alembic downgrade -1` clean
- [ ] 4 tests pass

##### T-C-1-02: Update SQLAlchemy ORM models

**Type**: impl
**depends_on**: T-C-1-01
**blocks**: T-C-2-01
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py`
**PRD reference**: Sub-Plan C §0

**What to build**:
- Add new `DocumentSourceLLMScoreModel` class.
- Add `model_id`, `prompt_version`, `input_hash` columns to `ArticleImpactWindowsModel`.
- DO NOT remove `llm_relevance_score`, `sentiment`, `llm_scored_at` from `DocumentSourceMetadataModel` yet — that's a future deprecation after Wave C-3 lands the materialized view.

**Tests to write**:
| Test | Verifies |
|---|---|
| test_orm_dsls_roundtrip | INSERT + SELECT roundtrip |
| test_orm_aiw_new_columns_default_null | new columns nullable on existing rows |

**Acceptance criteria**:
- [ ] Both models compile and pass mypy
- [ ] 2 tests pass

#### Validation Gate (Wave C-1)

- [ ] Migration applies clean to dev DB
- [ ] 6 new tests pass
- [ ] Existing S6 tests unaffected (we did not yet rewrite the worker)

#### Break Impact (Wave C-1)

| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/contract/test_alembic_heads.py` | head revision changed | bump expected head |

#### Regression Guardrails (Wave C-1)

- **BP-126**: new columns on `article_impact_windows` are nullable — no NOT NULL without default.
- **BP-130**: migration head must increment by 1; do not skip a number.
- **R24**: `nlp_db` is owned by S6 Alembic, not `intelligence-migrations` — verified, this migration goes in the S6 alembic dir.

---

### C.2 Wave C-2: Worker rewrite

**Goal**: `ArticleRelevanceScoringWorker` writes append-only to `document_source_llm_scores` with full provenance. Existing reads continue to work via the legacy columns until Wave C-3 introduces the materialized view.

**Depends on**: T-C-1-02
**Estimated effort**: 90 minutes
**Architecture layer**: application/workers

#### Pre-read

- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
- `libs/ml-clients/` (model_id discovery)

#### Tasks

##### T-C-2-01: Add `LLMScoreRepository` port + impl

**Type**: impl
**depends_on**: T-C-1-02
**blocks**: T-C-2-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/llm_score_repository.py` (new port)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/llm_score_repository.py` (new impl)

**What to build**:
- Port: `class LLMScoreRepository(Protocol): async def append(self, *, doc_id, score_type, score_value, score_label, model_id, prompt_version, input_hash) -> bool`. Returns True if inserted, False if conflict.
- Impl: INSERT ON CONFLICT DO NOTHING; returns `result.rowcount == 1`.

**Tests to write** (4 unit):
| Test | Verifies |
|---|---|
| test_append_inserts_new | first call → returns True, row in DB |
| test_append_dedup | second call same key → returns False, no second row |
| test_append_different_model | same `(doc_id, score_type)` but new `model_id` → returns True, both rows present |
| test_append_input_hash_required | NULL input_hash → IntegrityError (NOT NULL) |

**Acceptance criteria**:
- [ ] Port + impl compile, mypy clean
- [ ] 4 tests pass
- [ ] No infra leakage into port

##### T-C-2-02: Rewrite `ArticleRelevanceScoringWorker`

**Type**: impl
**depends_on**: T-C-2-01
**blocks**: T-C-2-03
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py`
**PRD reference**: Sub-Plan C §0

**What to build**:
- Compute `input_hash = sha256((title + body[:2000]).encode("utf-8")).hexdigest()` before LLM call.
- Read `model_id` from the active LLM client (via `libs/ml-clients` — the client knows its own model_id).
- Read `prompt_version` from a module-level constant `_RELEVANCE_PROMPT_VERSION = "v1"` — bumped manually when the prompt template changes.
- After LLM responds, call `llm_score_repo.append(doc_id, "relevance", score, None, model_id, prompt_version, input_hash)` and `llm_score_repo.append(doc_id, "sentiment", None, sentiment_label, ...)`.
- DO NOT update `document_source_metadata.llm_relevance_score` directly anymore.
- For the duration until C-3 ships: write a parallel update to `document_source_metadata.llm_relevance_score` so the existing API readers still see fresh data. This compatibility-double-write is removed in C-3.

**Logic & Behavior**:
- Append-only — never UPDATE.
- Idempotent on `(doc_id, score_type, model_id, prompt_version)` — re-running on the same article with the same model is a no-op.
- Skip the LLM call entirely if `append()` would return False (i.e., already scored). Add a quick `exists` check before the LLM call to save tokens. (Implementation detail: the `exists` check is one indexed query; cheaper than a wasted LLM call.)

**Tests to write**:
| Test | Verifies |
|---|---|
| test_first_run_invokes_llm_and_appends | mocked LLM returns score → 2 rows in dsls (relevance + sentiment) |
| test_second_run_skips_llm | same article, same model, same prompt → no new LLM call (mock asserts call_count==1 across two runs) |
| test_model_change_re_invokes_llm | model_id changes → LLM called again, 2 new rows |
| test_input_hash_change_re_invokes_llm | body changes → input_hash differs → re-scored |
| test_legacy_double_write | `document_source_metadata.llm_relevance_score` is also updated (will remove in C-3) |

Minimum: 5
Edge cases: LLM raises (no rows written, task retried), score boundary 0.0/1.0
Error paths: LLM client RetryableError → task marked Retryable

**Downstream test impact**:
- `services/nlp-pipeline/tests/integration/test_article_relevance_scoring_worker.py` — major rewrite.
- `services/nlp-pipeline/tests/unit/test_workers.py` — possible.

**Acceptance criteria**:
- [ ] All 5 tests pass
- [ ] mypy clean
- [ ] Existing E2E `pytest tests/e2e/test_full_pipeline.py` passes (uses real model)

##### T-C-2-03: Mirror change for `PriceImpactLabellingWorker`

**Type**: impl
**depends_on**: T-C-2-01
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
**PRD reference**: Sub-Plan C §0

**What to build**:
- The price-impact worker writes to `article_impact_windows`. Add `model_id`, `prompt_version`, `input_hash` to its INSERT.
- Change INSERT ON CONFLICT path: `ON CONFLICT (article_id, entity_id, window_type, model_id, prompt_version) DO NOTHING` (was `(article_id, entity_id, window_type)`).
- model_id source: `libs/ml-clients` — same pattern.

**Tests to write** (3 unit):
| Test | Verifies |
|---|---|
| test_aiw_writes_provenance_columns | new columns populated |
| test_aiw_dedup_per_model | re-run with same model is no-op |
| test_aiw_new_model_appends | new model_id → new row, not overwrite |

**Acceptance criteria**:
- [ ] 3 tests pass
- [ ] Worker still produces an impact_score per (article, entity, window) but now per-model

#### Validation Gate (Wave C-2)

- [ ] All tests through C-1 still pass
- [ ] 12 new tests pass (4 + 5 + 3)
- [ ] E2E pipeline test passes
- [ ] No data loss on existing rows
- [ ] Manual smoke: process a fresh article, observe 2 rows in `document_source_llm_scores` (relevance + sentiment) AND legacy column populated

#### Break Impact (Wave C-2)

| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/integration/test_article_relevance_scoring_worker.py` | worker output target changed | rewrite assertions to query dsls |
| `services/nlp-pipeline/tests/integration/test_price_impact_labelling_worker.py` | new columns | extend assertions |

#### Regression Guardrails (Wave C-2)

- **BP-124** (BaseKafkaConsumer.is_duplicate before get_unit_of_work): if these workers run inside a Kafka consumer, the `_current_uow` reset must happen before `is_duplicate` — verify against the existing pattern.
- **BP-007**: a single article generates ≥ 2 INSERTs (relevance + sentiment); both must be in the same UoW or both in fresh UoWs — pick one and document it. Recommend separate UoWs (smaller transactions, less lock contention).

---

### C.3 Wave C-3: Materialized view + renormalized fallback formula

**Goal**: Land the `document_source_llm_latest` materialized view as the single source of truth for current LLM scores. Update the news read path (`GET /api/v1/news/top`) and any score-consumers to use the view + renormalized formula. Remove the legacy double-write from C-2.

**Depends on**: T-C-2-02
**Estimated effort**: 90 minutes
**Architecture layer**: schema + API + scheduler

#### Tasks

##### T-C-3-01: Migration — materialized view + refresh function

**Type**: schema
**depends_on**: T-C-1-01
**blocks**: T-C-3-02
**Target files**: `services/nlp-pipeline/alembic/versions/0013_llm_latest_view.py` (new; depends on 0012)

**What to build**:
```sql
CREATE MATERIALIZED VIEW document_source_llm_latest AS
SELECT DISTINCT ON (doc_id, score_type)
    doc_id, score_type, score_value, score_label, model_id, generated_at
FROM document_source_llm_scores
ORDER BY doc_id, score_type, generated_at DESC;

CREATE UNIQUE INDEX ix_dsl_latest_pk ON document_source_llm_latest(doc_id, score_type);
```
The UNIQUE index lets us use `REFRESH MATERIALIZED VIEW CONCURRENTLY`.

**Tests** (3): apply / refresh / downgrade.

**Acceptance criteria**:
- [ ] View exists, refreshes concurrently, drops cleanly

##### T-C-3-02: Wire APScheduler refresh job

**Type**: impl
**depends_on**: T-C-3-01
**blocks**: T-C-3-03
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/scheduler/scheduler_main.py`

**What to build**:
Add a 5-minute APScheduler job: `REFRESH MATERIALIZED VIEW CONCURRENTLY document_source_llm_latest`. Logged as `dsl_latest_refreshed elapsed_ms=N`.

**Tests** (2 integration): refresh runs / refresh handles concurrent writers without blocking.

##### T-C-3-03: Implement `compute_display_relevance_score()` with renormalization

**Type**: impl
**depends_on**: T-C-3-02
**blocks**: T-C-3-04
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/services/relevance_score.py` (new module)

**What to build**:
Pure function:
```python
def compute_display_relevance_score(
    *,
    market_score: float,
    routing_score: float,
    llm_score: float | None,
) -> float:
    """Compute display relevance with renormalization when LLM score is missing.

    When LLM score is present:
        display = 0.5*market + 0.4*llm + 0.1*routing  (PRD-0026 weights)

    When LLM score is None:
        display = (0.5/0.6)*market + (0.1/0.6)*routing
                = 0.833*market + 0.167*routing

    This avoids the bias of dropping the 0.4 weight without rebalancing.
    """
    if llm_score is not None:
        return 0.5 * market_score + 0.4 * llm_score + 0.1 * routing_score
    total = 0.5 + 0.1
    return (0.5 / total) * market_score + (0.1 / total) * routing_score
```

**Tests** (5):
| Test | Verifies |
|---|---|
| test_with_llm | exact formula |
| test_without_llm_renormalized | weights sum to 1.0; market dominates |
| test_with_llm_zero | LLM=0 produces 0.5*m + 0.1*r |
| test_clamping | output in [0, 1] |
| test_invariance | with llm=0.5 (mid), result close to without-llm result (when m≈r) |

##### T-C-3-04: Update news read path (S6 routes + S9 proxy)

**Type**: impl
**depends_on**: T-C-3-03
**blocks**: T-C-3-05
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/news.py` (or wherever `/news/top` lives)
- Any other consumer of `document_source_metadata.llm_relevance_score`

**What to build**:
Replace direct reads of `document_source_metadata.llm_relevance_score` with a LEFT JOIN to `document_source_llm_latest WHERE score_type='relevance'`. Compute display score via the new pure function. The market_score and routing_score sources are unchanged (they stay where they are).

**Tests** (4 integration):
| Test | Verifies |
|---|---|
| test_news_top_with_scored_articles | articles with LLM scores get display_relevance_score from formula |
| test_news_top_with_unscored_articles | articles WITHOUT LLM scores still rank, using renormalized formula |
| test_news_top_mixed | both ranked together, no NULL leak |
| test_news_top_after_model_swap | swap model_id; refresh view; new score active |

##### T-C-3-05: Remove legacy double-write from C-2

**Type**: impl
**depends_on**: T-C-3-04
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py`

**What to build**:
Delete the temporary legacy update to `document_source_metadata.llm_relevance_score`. Mark the legacy columns as deprecated in the model file with a `# DEPRECATED: served from document_source_llm_latest since 2026-04-29` comment. Plan to drop in a future migration.

**Tests**: existing C-2 test `test_legacy_double_write` is removed.

#### Validation Gate (Wave C-3)

- [ ] All prior waves' tests pass
- [ ] 14 new tests pass (3 + 2 + 5 + 4)
- [ ] `/news/top` returns ranked results identical to pre-migration values for articles that had LLM scores
- [ ] `/news/top` handles articles without LLM scores via renormalized formula
- [ ] Materialized view refreshes within 200ms on a DB with 100k articles

#### Break Impact (Wave C-3)

| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/integration/test_news_top.py` | data source changed | update join expectations |
| `services/api-gateway/src/api_gateway/routes/news.py` | proxies the same payload | likely no change; check |
| `apps/worldview-web/__tests__/news.test.tsx` | data shape unchanged | no change |

#### Regression Guardrails (Wave C-3)

- **BP-180** (asyncpg ambiguous param in CTE): the LEFT JOIN must NOT have ambiguous param types — verify with a real query under load.
- **BP-007** (mat view refresh blocking writes): use CONCURRENTLY only — never plain REFRESH on this view.

---

### C.4 Wave C-4: Mass-replay endpoint

**Goal**: `POST /api/v1/admin/llm-replay` for safe model rollouts.

**Depends on**: T-C-2-01 (the repository)
**Estimated effort**: 60 minutes
**Architecture layer**: API + application

#### Tasks

##### T-C-4-01: New `LLMReplayJob` table + ORM

**Type**: schema
**depends_on**: T-C-1-01
**blocks**: T-C-4-02
**Target files**: `services/nlp-pipeline/alembic/versions/0014_llm_replay_jobs.py` (new; depends on 0013), `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py`

**What to build**:
Table:
```
llm_replay_jobs(
  id UUID PK,
  model_id VARCHAR(128) NOT NULL,
  prompt_version VARCHAR(32) NOT NULL,
  score_types TEXT[] NOT NULL,
  since TIMESTAMPTZ,
  until TIMESTAMPTZ,
  status VARCHAR(16) NOT NULL,  -- PENDING|RUNNING|COMPLETED|FAILED
  total_articles INT,
  processed INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
)
```

##### T-C-4-02: `RunLLMReplayUseCase` + endpoint

**Type**: impl
**depends_on**: T-C-4-01, T-C-2-01
**blocks**: T-C-4-03
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/run_llm_replay.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py` (new or extended)

**What to build**:
Endpoint signature:
```
POST /api/v1/admin/llm-replay
{
  "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
  "prompt_version": "v2",
  "score_types": ["relevance", "sentiment"],
  "since": "2025-01-01T00:00:00Z",
  "until": "2025-12-31T23:59:59Z",
  "dry_run": true
}

→ 200 {
  "job_id": "<uuid>",
  "estimated_articles": 12345,
  "estimated_minutes": 87,
  "estimated_credits": 0,        // local Ollama
  "status": "PENDING"            // or "DRY_RUN"
}
```

Logic:
1. Validate model_id + prompt_version not empty.
2. Query `articles WHERE published_at BETWEEN since AND until AND id NOT IN (SELECT doc_id FROM document_source_llm_scores WHERE model_id=? AND prompt_version=? AND score_type IN ?)`.
3. If `dry_run`: return count + estimate; do not insert job.
4. Else: INSERT job row in PENDING; return job_id.

A separate worker (extension of existing scheduler) consumes PENDING jobs and re-enqueues each article through the worker pool with the override `(model_id, prompt_version)`. Reuses C-2 worker idempotency.

**Auth**: endpoint requires admin JWT (existing pattern in `/admin/*` routes — check `services/nlp-pipeline/src/nlp_pipeline/api/dependencies.py` for the admin dependency).

**Tests** (5):
| Test | Verifies |
|---|---|
| test_dry_run_no_job_inserted | dry_run=True → no row in llm_replay_jobs |
| test_dry_run_returns_estimate | count matches articles in window not yet scored by this model |
| test_real_run_creates_job | row inserted with status=PENDING |
| test_invalid_model_400 | empty model_id → 422 |
| test_unauthorized_admin_401 | no admin JWT → 401 |

##### T-C-4-03: Replay worker

**Type**: impl
**depends_on**: T-C-4-02
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/llm_replay_worker.py` (new)

**What to build**:
APScheduler job (every 30s) that:
1. SELECTs one PENDING `llm_replay_job` (FOR UPDATE SKIP LOCKED).
2. Sets status=RUNNING.
3. Iterates the articles in the window in batches of 50.
4. For each: invoke ArticleRelevanceScoringWorker.score_article(article_id, model_id_override, prompt_version_override).
5. Updates `processed` after each batch.
6. On finish: status=COMPLETED, completed_at=NOW.
7. On failure mid-stream: status=FAILED, error logged.

**Tests** (3): job picked up / processed counter increments / failure handling.

#### Validation Gate (Wave C-4)

- [ ] All prior tests pass
- [ ] 8 new tests pass (varies + 3 worker)
- [ ] dry_run smoke: against dev DB → returns plausible count

#### Break Impact (Wave C-4)

| Broken file | Why | Fix |
|---|---|---|
| `services/nlp-pipeline/tests/contract/test_admin_routes.py` | new route | add expectation |

#### Regression Guardrails (Wave C-4)

- **BP-007**: each replay batch is its own UoW.
- **BP-026**: replay worker uses async LLM client; do not block.
- **BP-202** (auth): admin endpoint MUST require admin JWT, not just any authenticated user.

---

## 5. Cross-cutting concerns

### 5.1 Contract changes

| Contract | Wave | Type |
|---|---|---|
| `document_source_llm_scores` table | C-1 | new schema |
| `document_source_llm_latest` mat view | C-3 | new schema |
| `article_impact_windows` UNIQUE | C-1 | constraint change |
| `sources.config_hash` | B-1 | new column |
| `POST /admin/llm-replay` | C-4 | new API |

No Avro topic changes in this plan. (PRD-0033 / PLAN-0056 will add new topics.)

### 5.2 Migration order

1. Sub-Plan B migration (independent)
2. Sub-Plan C-1 migration (LLM provenance schema)
3. Sub-Plan C-3 migration (materialized view)
4. Sub-Plan C-4 migration (replay jobs table)

All forward-only; downgrades supported but not required for prod.

### 5.3 Configuration changes

| Service | Env var | Default | Purpose |
|---|---|---|---|
| S3 | `MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP` | true (gitops) / false (code) | enable startup hook |
| S3 | `MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS` | 14 | initial validation horizon |
| S3 | `MARKET_INGESTION_AUTO_BACKFILL_YEARS` | 10 | configurable max |
| S4 | `CONTENT_INGESTION_BACKFILL_ON_STARTUP` | true (gitops) / false (code) | enable startup hook |
| S4 | `CONTENT_INGESTION_BACKFILL_INITIAL_DAYS` | 14 | initial validation horizon |
| S4 | `CONTENT_INGESTION_BACKFILL_YEARS` | 3 | configurable max |
| S6 | `NLP_LLM_REPLAY_BATCH_SIZE` | 50 | replay worker batch size |

### 5.4 Documentation updates

- `docs/services/market-ingestion.md` — auto-backfill section
- `docs/services/content-ingestion.md` — auto-backfill + source dedup sections
- `docs/services/nlp-pipeline.md` — LLM provenance section + new admin endpoint
- `worldview-gitops/docs/ENV_AUDIT.md` — 7 new env vars
- `docs/MASTER_PLAN.md` — small update on the LLM provenance pattern

### 5.5 Observability

New metrics:
- `s3_startup_backfill_enqueued_total` (counter)
- `s3_startup_backfill_skipped_total` (counter)
- `s4_startup_watermarks_seeded_total` (counter)
- `s6_llm_score_appended_total{score_type=, model_id=}` (counter)
- `s6_llm_score_dedup_skipped_total` (counter)
- `s6_llm_replay_articles_processed_total{job_id=}` (counter)
- `s6_dsl_latest_refresh_duration_seconds` (histogram)

---

## 6. Risk assessment

### 6.1 Critical path

Sub-Plan B is the smallest and zero-risk; ship first.
Sub-Plan A is mechanically simple and unblocks UX wins; ship second.
Sub-Plan C is the largest and most architectural; ship last because it touches the read path of `/news/top`.

### 6.2 Highest risk

**Wave C-3 — read path migration**. The materialized view replacing direct column reads is the only place where a regression could affect users. Mitigation:
- Keep legacy double-write (C-2) until C-3 ships and is verified.
- Run shadow comparison: before flipping the read path, run for 24h with both paths and assert score equality.
- Refresh frequency 5 min — accept mild staleness; if needed, can drop to 1 min.

### 6.3 Rollback strategy

| Sub-plan | Rollback |
|---|---|
| A | Set env vars false; redeploy. No schema change to revert. |
| B | `alembic downgrade -1` reverts the constraint and column; no data loss. |
| C | Each wave has a downgrade; revert C-3 first, then C-2 stops appending and resumes legacy writes via the double-write toggle (kept until C-5 cleanup). |

### 6.4 Testing gaps

- No E2E test exercises the full LLM replay flow against a real Ollama. Acceptable: E2E is out-of-scope; integration tests with mocked LLM cover idempotency.
- No load test on materialized view refresh under heavy ingestion. Acceptable: 5-min refresh is loose; will tune in production.

---

## 7. Open questions resolved

All four open questions from the /investigate round are answered in this plan:

| OQ | Resolution | Where |
|---|---|---|
| 1: scope of auto-trigger | both prod gitops + dev compose true; defaults conservative (14d) | §0.3, §A.0, T-A-1-04, T-A-1-05 |
| 2: backfill horizon | 14d initial, 10y/3y configurable max | §0.3, T-A-1-02, T-A-1-03 |
| 3: Polymarket scope | route through S6 NER pipeline | PRD-0033 §5 (separate plan) |
| 4: relevance score efficiency | renormalize weights when LLM score missing; serve via materialized view | T-C-3-03, T-C-3-04 |

---

## 8. Suggested execution order

```
Day 1:  /implement PLAN-0055 Sub-Plan B Wave B-1   (XS)
Day 1:  /implement PLAN-0055 Sub-Plan A Wave A-1   (XS)
Day 2:  /implement PLAN-0055 Sub-Plan A Wave A-2   (S)
Day 2:  /implement PLAN-0055 Sub-Plan A Wave A-3   (S)
Day 3:  /implement PLAN-0055 Sub-Plan C Wave C-1   (S)
Day 3:  /implement PLAN-0055 Sub-Plan C Wave C-2   (M)
Day 4:  /implement PLAN-0055 Sub-Plan C Wave C-3   (M) ← shadow-run 24h before merge
Day 5:  /implement PLAN-0055 Sub-Plan C Wave C-4   (S)
Day 5:  QA pass + merge
```

Parallel execution alternative: Sub-Plans A and B can be implemented in parallel worktrees (no shared files); C must be serial because waves chain.

---

## 9. Compounding entries to add post-implementation

- BUG_PATTERNS.md: "Worker writes LLM output without model_id provenance — overwrites silently on re-run. Fix: append-only table keyed on (artifact, model_id, prompt_version)."
- BUG_PATTERNS.md: "S4 source_id loses watermark when source is deleted+recreated. Fix: UNIQUE on (source_type, config_hash) + ON CONFLICT DO NOTHING."
- HIGH_RISK_PATTERNS.md: "Materialized view used as read path — verify CONCURRENTLY refresh is in place to avoid blocking writes."
- service .claude-context.md updates: 3 services x 3-5 lines each.
