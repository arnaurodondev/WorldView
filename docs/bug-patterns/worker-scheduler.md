# Bug Patterns — Workers & Schedulers

> **Category**: worker-scheduler
> **Description**: Task scheduling, worker lease patterns, backfill logic, rate limiting, watermarks, ingestion pipeline correctness
> **Count**: 37 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-030 — Token-bucket `last_refill_at` not wired — tokens never replenished

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ProviderBudget / ScheduleDueTasksUseCase)

### Symptom

Provider budget drains to 0 tokens under sustained load and never recovers until service restart.

### Root cause

`ProviderBudget` entity had no `last_refill_at` field. `_to_domain()` ignored the DB `last_refill_at` column. `refill()` was never called in `_apply_budgets()`.

### Fix

1. Add `last_refill_at: datetime` to `ProviderBudget` (default `utc_now()`).
2. `refill()` sets `self.last_refill_at`.
3. `_to_domain()` maps `row.last_refill_at`.
4. `save()` persists `last_refill_at`.
5. `_apply_budgets()` calls `budget.refill(elapsed)` before consuming.

---

---

## BP-031 — Backfill flag flipped before budget/cap filtering

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ScheduleDueTasksUseCase)

### Symptom

Backfill enters incremental mode even when budget was exhausted and zero backfill tasks were actually enqueued.

### Root cause

`_build_tasks_for_policy()` set `policy.backfill_enabled = False` during Phase 2 (candidate construction), before Phase 3 applied the budget/cap filter.

### Fix

Collect backfill policies in a list during Phase 2. After Phase 3 produces `final_tasks`, only flip `backfill_enabled=False` for policies with at least one task in `final_tasks`.

---

---

## BP-048 — D-008 skip-if-exists guard applied to first storage step only; subsequent steps re-upload on retry

**Category**: Idempotency / Object storage
**Services affected**: market-ingestion `ExecuteTaskUseCase` (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-011

### Symptom

On retry after a crash between canonical write and watermark commit:
- Bronze object already exists → skip-if-exists fires, bronze upload is skipped ✓
- Canonical object already exists → NO guard → canonical is re-uploaded (possibly with different bytes if data changed) ✗

### Root cause

The D-008 guard was applied to `_store_bronze` but not to `_store_canonical`:

```python
async def _store_bronze(self, task, raw_bytes):
    key = build_bronze_key(task)
    if await self._store.exists(bucket, key):  # D-008 ✓
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return ObjectRef(bucket=bucket, key=key, sha256=sha256, ...)
    return await self._store.put(bucket, key, raw_bytes, ...)

async def _store_canonical(self, task, canonical_bytes):
    key = build_canonical_key(task)
    # MISSING: no exists() check here ✗
    return await self._store.put(bucket, key, canonical_bytes, ...)
```

### Fix

Apply D-008 to **every** storage step, not just the first:

```python
async def _store_canonical(self, task, canonical_bytes):
    key = build_canonical_key(task)
    if await self._store.exists(self._canonical_bucket, key):  # D-008 ✓
        sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        return ObjectRef(bucket=self._canonical_bucket, key=key,
                         sha256=sha256, byte_length=len(canonical_bytes), ...)
    return await self._store.put(self._canonical_bucket, key, canonical_bytes, ...)
```

### Test pattern: watch out for `return_value=True` when multiple `exists()` calls occur

```python
# WRONG — returns True for ALL exists() calls; canonical also skipped
store.exists = AsyncMock(return_value=True)

# CORRECT — bronze exists (skip), canonical doesn't yet (allow put)
store.exists = AsyncMock(side_effect=[True, False])
# assertion must also change: assert_awaited_once() → assert await_count == 2
```

---

---

## BP-061

**Category**: Domain events — missing `InstrumentUpdated` on flag change

**Symptom**: Portfolio (S1) `InstrumentRef` cache never shows `has_ohlcv=True` / `has_quotes=True` / `has_fundamentals=True` even after data has been materialized.

**Root cause**: Consumers correctly call `uow.instruments.update_flags()` when a new data type is materialized for an existing instrument, but never emit `InstrumentUpdated`. S1 only learns of flag changes via events; without the event, it never refreshes its cache.

**Affected areas**: S3 consumers (`ohlcv_consumer`, `quotes_consumer`, `fundamentals_consumer`); any consumer that updates an entity's capability flags.

**Fix**: Always emit an `InstrumentUpdated` (or equivalent) event atomically with the flag update, listing the changed fields in `fields_updated`.

---

---

## BP-072 — Scheduler dedupe key drift: `range_end=now` changes every tick

**Category**: Scheduler / deduplication
**Services affected**: market-ingestion (S2)
**First seen**: 2026-03-31 — investigation into 120K+ task accumulation and MinIO OOM

### Symptom

The `ingestion_tasks` table grows unboundedly (~500+ rows/hour). MinIO runs out of memory from accumulated bronze/canonical objects (2 per task). `ON CONFLICT DO NOTHING` on `(provider, dedupe_key)` never fires for incremental tasks.

### Root Cause

`_build_incremental_task` set `range_end = now` (line 188) and `range_start = now - timedelta(days=1)`. The `_build_dedupe_key` method hashes `f"{range_start}:{range_end}"` into the dedupe key. Since `now` changes every scheduler tick (60s), every tick produces a unique dedupe key, bypassing the ON CONFLICT guard entirely. The `has_active_task` check limits creation rate to ~1 task per 2 ticks per policy, but completed/failed tasks accumulate forever.

### Fix

Truncate `range_start` and `range_end` to UTC-day boundaries (midnight-to-midnight), matching the pattern already used by `TriggerIngestionUseCase`:

```python
today = now.replace(hour=0, minute=0, second=0, microsecond=0)
range_start = today
range_end = today + timedelta(days=1)
```

Same fix applied to `_build_backfill_tasks` where `end_dt = now` also drifted.

### Prevention

Never embed `utc_now()` in a deduplication key. Truncate to the coarsest stable boundary that still provides correct behaviour (UTC day for daily, UTC hour for hourly). The `TriggerIngestionUseCase` already follows this pattern — scheduler should match.

---

## BP-073 — `has_active_task(variant=None)` bypass for FUNDAMENTALS tasks

**Category**: Scheduler / active-task guard
**Services affected**: market-ingestion (S2)
**First seen**: 2026-03-31

### Symptom

FUNDAMENTALS tasks are created on every scheduler tick regardless of whether a pending/running/retry task already exists for the same symbol. The `has_active_task` guard always returns False for fundamentals.

### Root Cause

The `has_active_task` call in `_build_tasks_for_policy` (line 163) hardcoded `variant=None`. The SQL query generates `dataset_variant IS NULL` as the predicate. But fundamentals tasks are created with `variant="annual"` (via `FundamentalsVariant.ANNUAL.value`), so the predicate never matches any existing fundamentals task row.

### Fix

Derive the variant using the same logic as the task factory (`_derive_variant` helper) and pass it to `has_active_task`. For FUNDAMENTALS → `"annual"`, for OHLCV/QUOTES → `None`.

### Prevention

When a guard query uses dimension columns (variant, exchange, timeframe) that can be NULL, always derive the filter value from the same source that creates the entity being guarded. Add regression tests that verify `has_active_task` call arguments for each dataset type.

---

## BP-074 — Watermark key collision: scheduler omits `variant` parameter

**Category**: Scheduler / watermark
**Services affected**: market-ingestion (S2)
**First seen**: 2026-03-31

### Symptom

The watermark table accumulates duplicate rows for the same logical watermark key — one with `dataset_variant=NULL` (created by scheduler) and one with `dataset_variant='annual'` (created by worker's `execute_task.py`). The scheduler checks the NULL-variant row's `current_bar_ts` to determine if a policy is due, but the worker advances the `'annual'`-variant row, so the scheduler sees a stale (never-advanced) watermark.

### Root Cause

`_build_tasks_for_policy` called `self._uow.watermarks.get_or_create(...)` without passing `variant`. The watermark's natural key includes `dataset_variant` in its ON CONFLICT clause, so omitting variant creates a separate row with `dataset_variant=NULL`.

### Fix

Pass `variant=self._derive_variant(policy)` to `watermarks.get_or_create()` so the scheduler and worker reference the same watermark row.

### Prevention

Watermark `get_or_create` calls must always pass the same key dimensions as the task creation path. The natural key is `(provider, dataset_type, dataset_variant, symbol, exchange, timeframe)` — omitting any dimension creates a separate row.

---

---

## BP-075 — Backfill flag match too broad: provider+symbol only

**Category**: Scheduler / deduplication
**Services affected**: market-ingestion (S2)
**First seen**: 2026-03-31

### Symptom

When two OHLCV backfill policies share the same `provider` and `symbol` but differ in `timeframe` (e.g., `EODHD/AAPL/1d` and `EODHD/AAPL/1h`), and the provider budget is exhausted after only one policy's tasks are enqueued, **both** policies have `backfill_enabled` set to `False`. The budget-limited policy's backfill is permanently lost — it will never retry the historical range.

### Root Cause

The post-enqueue flag flip (lines 93–101 in `schedule_tasks.py`) matched tasks using only `provider + symbol`:

```python
policy_tasks_enqueued = any(
    str(t.provider) == str(bp.provider) and t.symbol == bp.symbol
    for t in final_tasks
)
```

When Policy A's tasks (timeframe=1d) survived budget filtering and Policy B's tasks (timeframe=1h) were dropped, the check incorrectly matched Policy A's tasks for Policy B, since both share the same provider+symbol.

### Fix

Include `dataset_type` and `timeframe` in the match condition (FIX-BACKFILL-FLAG):

```python
policy_tasks_enqueued = any(
    str(t.provider) == str(bp.provider)
    and t.symbol == bp.symbol
    and str(t.dataset_type) == str(bp.dataset_type)
    and (t.timeframe or "") == (bp.timeframe or "")
    for t in final_tasks
)
```

### Prevention

Post-enqueue flag matching must use all dimensions of the policy's identity. Any scheduler that modifies entity state after budget/cap filtering must match by the full natural key, not a partial projection. Add a regression test with two policies sharing a partial key prefix to verify isolation.

---

---

## BP-079 — asyncpg `AmbiguousParameterError` when using `IS NULL` on a bound parameter in `text()` query

**Affected areas**: Any service using asyncpg + SQLAlchemy `text()` with optional (`None`-able) parameters

**Symptom**

Test or runtime query fails with:

```
asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $N
```

when the query contains a pattern like:

```sql
AND (:param IS NULL OR col = :param)
```

**Root Cause**

asyncpg requires every bound parameter to have a deterministic PostgreSQL type. When `$N IS NULL` is the only occurrence of the parameter (or the only usage that asyncpg sees first), it cannot infer the type from the `IS NULL` expression alone. This causes asyncpg to reject the query at the protocol level before execution.

**Fix**

Wrap the parameter in an explicit `CAST` to provide the type hint:

```sql
-- Before (ambiguous):
AND (:param IS NULL OR col = :param)

-- After (explicit type):
AND (CAST(:param AS TEXT) IS NULL OR col = CAST(:param AS TEXT))
```

Note: PostgreSQL's `::type` cast syntax (e.g., `:param::TEXT`) is NOT supported inside SQLAlchemy `text()` queries with asyncpg — use the ANSI SQL `CAST(:param AS TYPE)` form instead (see BP-076).

**Prevention**

- Every optional filter parameter in a `text()` query that may be `None` MUST use `CAST(:param AS TYPE) IS NULL` instead of bare `:param IS NULL`
- When writing `text()` queries with asyncpg, verify all parameters have unambiguous types

---

---

## BP-079 — Expired worker lease stalls source permanently

**Date discovered**: 2026-04-01
**Service affected**: `content-ingestion` (S4)

### Symptom

A polling source silently stops producing tasks. No errors in the scheduler log. The
worker log shows no activity for the affected source. `GET /api/v1/status` shows the
source as "active" (last fetch time is stale). Other sources continue to run normally.

### Root cause

The scheduler's `has_active_task(source_id)` guard checks for any task in
`PENDING | CLAIMED | RUNNING` state before creating a new task. When a worker process
crashes mid-execution (OOM, SIGKILL, container restart), the task row remains in
`CLAIMED` or `RUNNING` state with a `lease_expires` timestamp that has long since
passed. The guard finds this zombie task and returns `True` — so the scheduler never
creates a replacement task. The source is permanently stalled.

### Fix

Add a `recover_expired_leases(now, lease_timeout_seconds)` method to `TaskRepository`
that resets all `CLAIMED`/`RUNNING` tasks whose `lease_expires < now - grace_period`
back to `RETRY`. Call this at the **start** of every scheduler tick (before the
`ScheduleDueSourcesUseCase`), so expired leases are cleaned up before the
`has_active_task` guard runs.

```python
# scheduler_main.py — _tick() runs recovery before scheduling
async def _tick(self) -> None:
    now = common.time.utc_now()
    async with uow_recover:
        recovered = await uow_recover.tasks.recover_expired_leases(
            now, lease_timeout_seconds=self._settings.worker_lease_seconds
        )
        await uow_recover.commit()
    if recovered:
        logger.warning("scheduler_leases_recovered", count=recovered)
    # ... then run ScheduleDueSourcesUseCase as normal
```

### Prevention

Any scheduler-worker pattern that uses lease-based task ownership MUST include a
periodic lease-recovery sweep. The `has_active_task` guard is only safe when paired
with `recover_expired_leases`. Document this invariant in the service context.

**Related**: `TaskRepository.has_active_task` does NOT exclude expired leases by design
(it would create a TOCTOU window). Always call `recover_expired_leases` first.

---

## BP-090 — Ephemeral event in `relations` table — wrong decay behaviour

**Services affected**: knowledge-graph (S7), intelligence-migrations
**Detected**: PRD-0018 design session (2026-04-04)

### Symptom

Geopolitical, regulatory, or macroeconomic events stored as rows in the `relations` table
display wrong confidence values: near-zero before they become active (treated as very old
evidence), and continuous decay even after the event ends (instead of binary end + residual decay).
The event confidence never spikes to its full value during its active period.

### Root Cause

The `relations` table uses continuous confidence decay from the moment evidence was created
(`evidence_created_at`). This models timeless facts (e.g., "TSMC manufactures chips for NVIDIA")
that degrade in relevance over time. Ephemeral events have a completely different lifecycle:
they are **inactive** before their start date, **fully active** between start and end, and
**residually decaying** after they end.

Using the `TEMPORAL_CLAIM` semantic mode on a relation doesn't help — it still applies a
continuous half-life from evidence creation, not binary activation at `active_from`.

### Fix

Ephemeral events MUST go in the separate `temporal_events` table (PRD-0018), NOT in `relations`.
The `temporal_events.lifecycle_phase` property correctly models the binary lifecycle:

```python
@property
def lifecycle_phase(self) -> str:
    now = utc_now()
    if now < self.active_from:
        return "PENDING_ACTIVE"
    if self.active_until is None or now <= self.active_until:
        return "ACTIVE"
    days_since_end = (now - self.active_until).days
    if days_since_end <= self.residual_impact_days:
        return "RESIDUAL"
    return "EXPIRED"
```

### Prevention

If a relation type represents something that: (1) has a clear start date, (2) has a clear end
or could end, and (3) has a residual impact period — it belongs in `temporal_events`, not `relations`.
Code review checklist: "Does this relation type model a timeless fact (use `relations`) or a
time-bounded event (use `temporal_events`)?"

---

---

## BP-092 — GLOBAL temporal event → entity_event_exposures explosion

**Services affected**: knowledge-graph (S7) `TemporalEventConsumer`, intelligence-migrations
**Detected**: PRD-0018 design session (2026-04-04)

### Symptom

After consuming a GLOBAL-scope temporal event (e.g., COVID-19 pandemic, global interest
rate cycle), the `entity_event_exposures` table balloons with one row per company entity
in the database — potentially 50,000+ rows from a single event. This causes:
- INSERT latency spike in the consumer
- Table size explosion (~50MB per GLOBAL event × thousands of events/year)
- Cascading slowdowns on queries that JOIN `entity_event_exposures`

### Root Cause

The `TemporalEventConsumer` iterates over all `entity_id` values from `exposed_entities[]`
in the Kafka message. If the NLP pipeline sets scope=GLOBAL and includes every company in
the affected sector, the consumer creates one exposure row per company.

### Fix

Apply scope-tiered entity exposure logic:

```python
if event.scope == EventScope.GLOBAL:
    # Link to sector/industry entities ONLY
    # Company exposure is inferred at query time via is_in_sector traversal
    for entity in event.exposed_entities:
        assert entity.entity_type in ("sector", "industry"), (
            f"GLOBAL event {event.event_id} must only link to sector/industry entities, "
            f"not {entity.entity_type}"
        )
elif event.scope == EventScope.NATIONAL:
    # Link to country entities only
    ...
else:  # LOCAL or REGIONAL
    # Create per-company/per-country rows as normal
    ...
```

The NLP pipeline (S6 Block 13E) must enforce this constraint before producing the Kafka event:
only include company entities in `exposed_entities[]` for LOCAL/REGIONAL events.

### Prevention

The Avro schema for `intelligence.temporal_event.v1` should include a validation hint
in the `ExposedEntity` record: when `scope=GLOBAL`, `entity_type` must be `sector` or `industry`.
Consumer validates this invariant before INSERT and logs + skips violating rows.

---

---

## BP-102 — intelligence-migrations Numbering Conflict

**Category**: Database migrations / PRD quality
**Affected areas**: Any PRD that schedules a new `intelligence-migrations` migration by number; any `/plan` wave targeting `intelligence-migrations`

**Symptom**: Two plans try to create migrations with the same revision number (e.g., both reference "migration 0002"). Alembic fails at `alembic upgrade head` with `Multiple head revisions are not supported`.

**Root cause**: PRDs are written independently and each assumes the next available migration number. When a migration actually lands before the PRD is implemented, the number assigned in the PRD is stale.

**Real example**: PRD-0017 was written with "cleanup migration 0002"; `0002_enhance_events_and_relations.py` had already landed. PRD-0018 then also referenced 0003 for its AGE migration. Both PRDs required renumbering (0017 → 0003, 0018 → 0004).

**Prevention**:
1. `/revise-prd` — Phase 3 checks `services/intelligence-migrations/alembic/versions/` for the current highest migration file and flags any mismatch against the PRD's claimed number
2. Before implementing any `intelligence-migrations` wave: `ls services/intelligence-migrations/alembic/versions/` and use the next available number

**Fix pattern**: Renumber the PRD migration reference to the next available integer; update all §6.4, §12, §15 occurrences, the cross-PRD dependency note in any downstream PRD, and the `down_revision` in the Alembic file.

---

---

## BP-112 — `claim_batch` Never Reclaims RUNNING Tasks with Expired Leases

**Date discovered**: 2026-04-07
**Category**: Worker reliability / task lease management · **Severity**: HIGH (data pipeline stall)
**Affected areas**: `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py`

**Symptom**: Tasks remain permanently stuck in `running` state with `locked_until` in the past. No worker ever picks them up again. The pipeline stalls silently — tasks never fail, never retry, never succeed.

**Root cause**: `SqlaTaskRepository.claim_batch` only selects tasks with `status IN ('pending', 'retry')`. When a worker crashes mid-execution (e.g., container OOM, timeout, unhandled exception before `_persist_fail`), the task stays `running` with an expired lease. The `claim_batch` CTE silently skips it forever because `running` is not in the claimable set.

**Evidence (from investigation)**:
- 7 tasks stuck `running` since 13:26:50 with `locked_until=13:32:26` (5-minute lease expired)
- All locked by the same worker ID that crashed
- No code path ever transitions them to `pending` or `retry`

**Fix**: Add `OR (status = 'running' AND locked_until < now)` to the CTE WHERE clause:
```python
# task_repository.py — claim_batch CTE
.where(
    or_(
        IngestionTaskModel.status.in_(claimable_statuses),
        (IngestionTaskModel.status == IngestionTaskStatus.RUNNING.value)
        & (IngestionTaskModel.locked_until < now),
    ),
    ...
)
```

**Prevention**: Any distributed worker system that uses lease-based task claiming MUST include expired-lease reclaim logic. The lease duration (`WORKER_LEASE_SECONDS`) must be > worst-case task execution time, and the claim query must include `OR (status=running AND locked_until < now)`.

**First seen**: E2E investigation (2026-04-07), S2 market-ingestion.

---

---

## BP-113 — `TypeError` from None-Valued OHLCV Field Bypasses `_persist_fail` in ExecuteTaskUseCase

**Date discovered**: 2026-04-07
**Category**: Exception handling gap · **Severity**: HIGH (task stuck in running)
**Affected areas**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**Symptom**: `worker_task_error: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'` in worker logs. Task remains in `running` state despite the canonicalize step failing.

**Root cause**: The EODHD intraday API sometimes returns bars with `None` for the `volume` field. `CanonicalOHLCVBar.from_dict()` calls `int(None)` → `TypeError`. The canonicalize exception handler catches `(ProviderDataError, ValueError, KeyError)` but NOT `TypeError`, so `_persist_fail` is never called and the task stays RUNNING forever.

**Evidence**: Worker logs at 2026-04-07 13:27:27 show the exact error for 7 intraday task IDs; those tasks remain `running` with expired leases.

**Fix**: Add `TypeError` to the canonicalize exception handler:
```python
except (ProviderDataError, ValueError, KeyError, TypeError) as exc:
    log.error("canonicalize_fatal", error=str(exc))
    await self._persist_fail(task, ProviderDataError(str(exc)))
    raise ProviderDataError(str(exc)) from exc
```

**Prevention**: Any exception handler that calls `_persist_fail` to persist task failure should include `TypeError` and `AttributeError` in the caught set — these commonly arise from None/missing fields in provider responses. The pattern `except (SomeDomainError, ValueError, KeyError)` is fragile; consider `except Exception` with a narrow re-raise guard for truly unexpected errors.

**First seen**: E2E investigation (2026-04-07), S2 market-ingestion 1h/5m intraday tasks.

---

---

## BP-133 — New Consumer Entry Point Missing From docker-compose.test.yml

**Symptom**: Architecture test `COMPOSE-MAIN-MISSING` fails with `<service>: <consumer_main.py> has no matching container in docker-compose.test.yml`. All unit tests pass but the architecture gate fails.

**Root cause**: When a new `*_consumer_main.py` (or `*_worker_main.py`) entry point is added to a service, a matching container must be registered in `infra/compose/docker-compose.test.yml`. The architecture test `test_every_entry_point_has_compose_container` scans all `*_main.py` files in `infrastructure/messaging/consumers/` and verifies a matching container command exists.

**Example (PLAN-0019)**: `prediction_market_consumer_main.py` was added to market-data in Wave B-1 but the `market-data-prediction-market-consumer` container was not added to `docker-compose.test.yml`.

**Fix**: Add a container entry following the pattern of sibling consumers (e.g., `market-data-ohlcv-consumer`). The container must appear under the same profiles and depend on `market-data-migrate`, `schema-registry-init`, `kafka-init`.

**Prevention**: Include the `docker-compose.test.yml` entry as an explicit task in every plan wave that adds a `*_main.py` entry point. The `/implement` skill should verify no `COMPOSE-MAIN-MISSING` violations remain before committing.

**Affected areas**: `infra/compose/docker-compose.test.yml`, any service adding a new consumer or worker process entry point.

**First seen**: PLAN-0019 QA pass, 2026-04-09.

---

## BP-135 — Consumer `process_message` Calls `uow.commit()` — Double-Commit Per Message

**Symptom**: Each Kafka message is committed twice: once inside `process_message` and once by the `BaseKafkaConsumer` base class after the method returns. Downstream effects include double-write errors for idempotency constraints, and test assertions like `uow.commit.assert_called_once()` failing unexpectedly.

**Root cause**: `process_message` calls `await uow.commit()` directly. The `BaseKafkaConsumer` already calls `commit()` after `process_message` returns (if no exception), so the transaction is committed twice.

**Fix**: Remove `await uow.commit()` from `process_message`. The base class owns the single commit. If the use case needs to commit mid-method (e.g., for outbox dispatch), use a different pattern or document why explicitly.

**In unit tests**: Assert `uow.commit.assert_not_called()` inside `process_message` tests — the base class mock is the correct location for commit assertions in integration/e2e tests.

**First seen**: QA pass PLAN-0019, 2026-04-09 (M-04). Fixed in `PredictionMarketConsumer.process_message`.

---

## BP-185 — Content-Ingestion TokenBucket Rate Limiters Not Shared Across Worker Processes

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (investigate skill: S4 `_build_adapter()` constructs a fresh in-memory `TokenBucket` on every call) |
| **Severity** | MEDIUM — at default concurrency=2 workers within a single process the impact is low; if the S4 worker container is horizontally scaled to N replicas, effective Finnhub request rate becomes N×55 req/min, triggering 429 responses and task retries |
| **Affected areas** | `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py:_build_adapter()`; any service where rate-limiter state must be shared across concurrent coroutines or processes |
| **Root cause** | `_build_adapter()` creates `TokenBucket(capacity=int(eodhd_rps), ...)` and Finnhub-specific `TokenBucket(capacity=settings.finnhub.rate_limit_per_minute, ...)` as fresh in-memory objects. These are local to each `asyncio` coroutine invocation. Under `worker_concurrency=2`, two coroutines can simultaneously build independent buckets and each consume tokens at the full rate. |
| **Symptom** | `429 Too Many Requests` responses from Finnhub logged as `finnhub_rate_limited`; tasks re-try after sleeping to next minute boundary; higher task latency and occasional FAILED tasks. More severe under horizontal scaling. |
| **Fix** | Move rate-limiter state to Valkey (already used by S4). Key: `s4:ratelimit:{source_type}`. Use atomic `INCR` + `EXPIRE` for per-minute counting, or use Valkey's `token_bucket` key pattern. Inject the Valkey-backed rate limiter into `_build_adapter()`. Short-term mitigation: cap `worker_concurrency` at 1 and enforce single-replica constraint in Docker Compose. |

### Prevention

- Rate limiters that enforce external API quotas MUST be backed by a shared store (Valkey, DB) when the service has `worker_concurrency > 1` or runs as multiple replicas.
- The `TokenBucket` domain entity in S4 is designed for in-process use only. Document this constraint on the class.
- See also: BP-036 (token bucket non-atomic with DB under concurrent load).

---

---

## BP-186 — Content-Ingestion Missing Startup Validators for Optional API Keys

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (investigate skill: S4 `config.py` has `finnhub_api_key: str = ""` and `newsapi_key: str = ""` with no startup validator; contrast with S2 `_warn_demo_eodhd_key`) |
| **Severity** | MEDIUM — with an empty API key, S4 task creation succeeds, but the adapter's first HTTP request returns HTTP 401, the task marks RETRY (up to max_attempts), then FAILED. Operators have no early warning; data gap is only visible via DLQ or failed-task count. |
| **Affected areas** | `services/content-ingestion/src/content_ingestion/config.py`; any service with optional external API keys whose absence silently degrades ingestion |
| **Root cause** | S4 `Settings` defines `finnhub_api_key: str = ""`, `newsapi_key: str = ""`, and `eodhd_api_key: str = ""` with empty defaults and no `@model_validator` that warns on empty values. S2 added `_warn_demo_eodhd_key` for its analogous field; S4 was not updated to match. |
| **Symptom** | No log warning at startup. First fetch cycle: `task_retryable_error error="401 Unauthorized"` for Finnhub; `task_retryable_error error="QuotaExhaustedError"` or 401 for NewsAPI. Tasks eventually reach FAILED with `error_detail="401 Unauthorized"`. DLQ accumulates entries. |
| **Fix** | Add `@model_validator(mode="after")` methods in `content_ingestion/config.py` mirroring S2's pattern: `_warn_empty_finnhub_key`, `_warn_empty_newsapi_key`, `_warn_empty_eodhd_key`. Emit `structlog.warning("missing_api_key", source="finnhub", ...)` at startup when the key is empty. |

### Prevention

- Every service with an optional external API key that enables a data source MUST emit a WARNING at startup if the key is empty or equals a known-placeholder value (`""`, `"demo"`, `"YOUR_KEY_HERE"`).
- Pattern: `@model_validator(mode="after")` in `Settings` — same pattern as `_warn_default_db_credentials` already used in S2 and S4.
- See also: BP-140 (settings fields defined but never read — operators believe they can tune behaviour via env vars but the code ignores them).

---

---

## BP-215 — Consumer `_parse_symbol()` Format Inversion

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 QA of commit f0a031f (MacroIndicatorDatasetConsumer) |
| **Severity** | BLOCKING — macro indicator metadata never written |
| **Root cause** | Consumer assumed `INDICATOR.COUNTRY` symbol format but S2 seeds/emits `COUNTRY.INDICATOR`. `rsplit(".", 1)` on `"USA.gdp_current_usd"` returned `("usa", "gdp_current_usd")` — indicator_code and country completely swapped. Entity lookup always returned None; no metadata ever updated. |
| **Symptom** | No macro indicator data in knowledge graph despite successful Kafka consumption |
| **Fix** | Use `symbol.partition(".")` and unpack as `country, _, indicator_code` then return `(indicator_code.lower(), country)`. Verify against seed format before writing. |

### Prevention

Before writing a `_parse_symbol()` helper: grep actual seed data to confirm the symbol format. Write a test with the literal seed value (e.g. `"USA.gdp_current_usd"`) and assert the expected return order.

---

---

## BP-216 — ISO3 Country Codes Passed to Alpha-2 Entity Lookups

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 QA of commit f0a031f (EconomicEventsDatasetConsumer) |
| **Severity** | CRITICAL — entity-event exposure links never created |
| **Root cause** | S2 symbol suffix is alpha-3 (`"USA"`, `"JPN"`). `find_country_entity()` queries `WHERE metadata->>'country_iso' = :iso2` — seeded with alpha-2. No normalization → always returns None → exposure link skipped. |
| **Symptom** | Events upserted but no `entity_event_exposures` rows created for any country |
| **Fix** | Add `_ISO3_TO_ISO2` dict in consumer. Call `_ISO3_TO_ISO2.get(code, code[:2])` before passing to entity repo. |

### Prevention

Whenever a consumer receives a country code from a Kafka message, check whether the entity lookup field uses alpha-2 or alpha-3. Add an explicit normalization step and test it with seeded values.

---

---

## BP-218 — Dead Watermark `last_success_at` Column Never Written

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 — PLAN-0036 W0 audit |
| **Severity** | HIGH — pre-fetch freshness gate inoperable; every task treated as stale regardless of recent fetch |
| **Root cause** | `ingestion_watermarks.last_success_at` was added in migration `0001_initial.py` but `SqlaWatermarkRepository.save()` only wrote `last_success_bar_ts`, `last_success_sha256`, `backfill_phase`, and `updated_at`. The domain entity `Watermark` also lacked the field. The scheduler gate compared against a perpetually-`None` column, so the freshness check always evaluated as "stale" → task always enqueued. |
| **Symptom** | No task is ever skipped by the pre-fetch gate; EODHD credit consumption equals the theoretical maximum (no skip savings). Watermark records have `last_success_at = NULL` even after hundreds of successful fetches. |
| **Fix** | Add `last_success_at: datetime \| None = None` to `Watermark` entity. Add `last_success_at=now` to `save()` UPDATE statement. No migration needed — column already exists. Covered by `test_watermark_save_writes_last_success_at`. |

### Prevention

When adding a new column to an existing table, immediately add it to:
1. The domain entity dataclass (`entities/<entity>.py`)
2. The repo `_to_domain()` mapping
3. The repo `save()` UPDATE statement
4. A unit test verifying the UPDATE statement includes the new column

---

---

## BP-219 — Per-Replica In-Process Monthly Quota Counter (Market Ingestion)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 — PLAN-0036 W0 investigation |
| **Severity** | HIGH — monthly quota 4× underenforced under typical 4-replica deployment |
| **Root cause** | `provider_budgets` table tracks daily credits per provider but each worker process holds its own in-memory counter. The DB column is never incremented atomically; multiple replicas each think the budget is fresh. With 4 replicas and a 100K/month budget, the effective combined spend can reach 400K/month before any process blocks. |
| **Symptom** | `s2_eodhd_quota_blocked_total` is always 0 despite credit overruns; EODHD API key reaches monthly limit mid-month with no platform-side block. |
| **Fix** | Replace per-process budget check with `EodhdQuotaService` in `libs/messaging/eodhd_quota`. Uses Valkey `INCRBY` (atomic, cross-replica) for monthly key `eodhd:v1:quota:{YYYY-MM}:credits_used`. Hard-limit pre-check (GET before INCRBY) blocks at exactly 100K. Post-increment check handles TOCTOU races near the boundary. 32-day TTL provides automatic monthly reset. |

### Prevention

Shared budgets (quota, rate limits, credit counters) that span multiple replicas MUST use a shared backing store (Valkey, Redis, Postgres advisory lock) — never in-process memory or per-replica DB rows. Use Valkey INCRBY for atomic increment with TTL. Document the replica-multiplication risk in the service `.claude-context.md`.

---

---

## BP-220 — `_fallback_provider()` Returns `None` for Intraday — Silent Failover Gap

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-26 — PRD-0032 / PLAN-0040 audit |
| **Severity** | HIGH — entire zero-bar failover chain silently aborts for all intraday tasks; Polygon adapter is registered but never called |
| **Root cause** | `_fallback_provider()` in `execute_task.py` was added by PLAN-0038 Wave A-4 with explicit `return None` for intraday timeframes ("no free intraday alternative"). When PRD-0032 added Polygon as an intraday failover, the zero-bar failover code path (`ZeroBarTracker.should_failover() → True → _fallback_provider()`) was not updated. The caller treats `None` as "no fallback available" and returns the empty result. |
| **Symptom** | `ZeroBarTracker` reaches `FAILOVER_THRESHOLD` (5 consecutive zeros) and `should_failover()` returns `True`, but the task's `fetched_by_provider` remains `"alpaca"` and no Polygon request is made. Log shows `zero_bar_failover_skipped` but no `provider_routing_cache_selected` event for intraday tasks. |
| **Fix** | In Wave A-4 T-A-4-06: when `routing_cache` is set, replace the `_fallback_provider()` call with an ordered iteration over `routing_cache.get_providers_for(dataset_type, timeframe)[1:]` — skipping the current provider and trying each remaining one in weight order. |

### Prevention

When adding a new provider to a failover chain, **always** audit every `_fallback_*` function in `execute_task.py` for exhaustive coverage. The pattern `if fallback is None: return` is a silent failure — no exception, no log, no metric. Any new provider capability (intraday, quotes, etc.) must be reflected in every fallback/routing decision point, not just the primary selection.

Add a test: `test_zero_bar_failover_reaches_polygon` — verifies that after 5 zero-bar Alpaca responses, the Polygon adapter is called.

---

---

## BP-221 — Intraday Dispatch Set Missing Timeframes (`15m`, `30m`, `4h`)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-26 — PRD-0032 / PLAN-0040 audit |
| **Severity** | MEDIUM — `15m`, `30m`, `4h` tasks silently fall through to `fetch_ohlcv()` path; Alpaca/Polygon raise `ProviderUnavailable` with a confusing "wrong method" error, or worse, EODHD is incorrectly called instead |
| **Root cause** | `_fetch()` in `execute_task.py` dispatches intraday timeframes via `fetch_intraday()` using a hardcoded set `{"1m", "5m", "1h"}`. PRD-0032 added `15m`, `30m`, `4h` as new intraday timeframes, but the dispatch set was not extended. |
| **Symptom** | Tasks with `timeframe="15m"` reach `_fetch()` and fall into the `else` branch (`fetch_ohlcv()`). EODHD's `fetch_ohlcv()` doesn't handle intraday; Alpaca's `fetch_ohlcv()` is correct but was intended to be called via `fetch_intraday()` alias. Result: incorrect data or `ProviderUnavailable`. |
| **Fix** | Extend `_INTRADAY_TFS` (or equivalent constant/set) to `{"1m", "5m", "15m", "30m", "1h", "4h"}` in `execute_task.py`. Add `fetch_intraday()` as an alias on all new intraday adapters. |

### Prevention

When adding a new timeframe that is semantically "intraday", always search `execute_task.py` for any hardcoded set of intraday timeframes and update it. Treat the dispatch set as an enum-exhaustive match — add a test that asserts `fetch_intraday()` is called for every timeframe in `_INTRADAY_TFS`.

---

---

## BP-227 — Polymarket Adapter Crashes on Zero/One-Outcome Markets

| Field | Value |
|-------|-------|
| **Service** | content-ingestion (S4) Polymarket adapter |
| **Severity** | MEDIUM (recurring noisy logs; affected markets silently skipped) |
| **Discovered** | 2026-04-26 live-stack investigation |
| **Root cause** | The Gamma API returns markets with `tokens: []` or `tokens: [one_entry]` for closed/unresolved single-binary markets (e.g., "Harvey Weinstein sentenced to no prison time"). `PredictionMarketFetchResult.__post_init__` enforces `outcomes >= 2` and raises `ValueError`. The outer `try/except Exception` in `_process_market()` caught the error correctly but emitted a full `exc_info=True` WARNING log for each such market on every poll cycle — creating noise that looked like crashes. |
| **Symptom** | Worker logs flood with `polymarket_market_parse_failed` WARNING + full traceback on every poll cycle. Polymarket metrics show high skip rate. |
| **Fix** | Added a pre-guard in `_process_market()` before calling `from_gamma_response`: check `len(market.get("tokens") or []) < 2` and return `None` with a DEBUG-level log (`polymarket_market_skip_insufficient_outcomes`). This avoids constructing the domain entity only to fail validation. |

### Prevention

When a domain entity has a post-init invariant that can be violated by structurally valid external API responses (not malformed data), add an explicit pre-check in the adapter before constructing the entity. Reserve WARNING logs for unexpected failures, not for normal filtering. Use DEBUG for skips caused by known data variations.

---

---

## BP-228 — Content-Ingestion Sources Table Never Seeded for Finnhub/NewsAPI

| Field | Value |
|-------|-------|
| **Service** | content-ingestion (S4) |
| **Severity** | HIGH (entire news/sentiment pipeline produces zero data) |
| **Discovered** | 2026-04-26 live-stack investigation |
| **Root cause** | The `content_ingestion.sources` table drives the scheduler — only enabled rows produce tasks. The `seed_demo_data.py` script did not insert any rows for `source_type='finnhub'` or `source_type='newsapi'` despite both adapters being fully wired and API keys present in `docker.env`. Result: zero Finnhub articles or NewsAPI articles ever ingested. |
| **Symptom** | Earnings calendar, news, and alerts tabs show no data. `content_ingestion_tasks` table empty except for Polymarket. |
| **Fix** | Updated `seed_demo_data.py` to insert 8 Finnhub sources (one per ticker: AAPL/MSFT/NVDA/AMZN/TSLA/GOOGL/META/JPM) and 2 NewsAPI sources (tech earnings + market news queries). Also disables EODHD sources (`UPDATE sources SET enabled=false WHERE source_type='eodhd'`) because the demo API key returns 403 on news/sentiment endpoints. |

### Prevention

When adding a new source adapter, include a corresponding seed entry in `seed_demo_data.py` in the same PR. Add a `validate_seeding()` assertion for the new source type count. Run `make seed` as part of the acceptance criteria for new adapter waves.

---

---

## BP-229 — Market-Ingestion Scheduler Missing Dispatch for EARNINGS_CALENDAR and NEWS_SENTIMENT

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) |
| **Severity** | HIGH (two entire dataset types never scheduled despite policies in DB) |
| **Discovered** | 2026-04-26 live-stack investigation |
| **Root cause** | `ScheduleDueTasksUseCase._build_incremental_task()` had dispatch branches only for `OHLCV`, `QUOTES`, and `FUNDAMENTALS`. Policies with `dataset_type=EARNINGS_CALENDAR` or `dataset_type=NEWS_SENTIMENT` fell through to the `logger.debug("scheduler_unsupported_dataset_type")` early-return, producing no tasks. The execution layer (`execute_task.py`) and the `IngestionTask` entity both had no factory methods for these types either. |
| **Symptom** | `scheduler_unsupported_dataset_type` in market-ingestion logs for EARNINGS_CALENDAR and NEWS_SENTIMENT policies. Zero tasks in DB for these types. Earnings calendar and sentiment scores never populated. |
| **Fix** | Added `IngestionTask.create_earnings_calendar_task()` and `create_news_sentiment_task()` factory methods. Added the corresponding `if policy.dataset_type == DatasetType.EARNINGS_CALENDAR` and `NEWS_SENTIMENT` dispatch branches in `_build_incremental_task()`. |

### Prevention

When defining a new `DatasetType` enum value, immediately add: (1) a factory method in `IngestionTask`, (2) a dispatch branch in `_build_incremental_task()`, (3) an execution handler in `execute_task.py`, (4) a credit cost in `_EODHD_CREDIT_COST`. Add a unit test for the scheduler that asserts all DatasetType values produce a non-None task (parametrize over all enum values).

---

---

## BP-233 — asyncpg Vector ANN Parameter Must Be str, Not list[float]

| Field | Value |
|-------|-------|
| **Service** | knowledge-graph (S7) — any service using pgvector via asyncpg |
| **Severity** | HIGH (search/relations returns 500 on every request) |
| **Discovered** | 2026-04-27 live pipeline investigation |
| **Root cause** | asyncpg cannot directly bind a Python `list[float]` as a PostgreSQL `vector` type parameter. Passing a list raises `DataError: invalid input for query argument $N (expected str, got list)`. The `CAST($N AS vector)` CAST hint helps PostgreSQL infer the type but does NOT change how asyncpg encodes the Python value — it still needs a string in pgvector wire format `[f1,f2,...,fN]`. The `entity_embedding_ann.py` already used `str(query_embedding)` correctly; `relation_summary.py` and `relation_type_registry.py` did not. |
| **Symptom** | `sqlalchemy.exc.DBAPIError: DataError: invalid input for query argument $1: [0.1, 0.1, ...] (expected str, got list)`. All ANN relation searches fail with 500. |
| **Fix** | Convert embedding list to string before binding: `"query_embedding": str(query_embedding)`. Pattern confirmed in `entity_embedding_ann.py:55`. |

### Prevention

Any repository that uses `CAST(:param AS vector)` with asyncpg must pass the embedding as `str(embedding)`, NOT as a `list[float]`. Add this to vector search repository code review checklist. The `str()` of a Python list produces `[f1, f2, ...]` which pgvector accepts.

---

---

## BP-233 — Polymarket Gamma API Format Change Silently Drops All Markets

| Field | Value |
|-------|-------|
| **Service** | content-ingestion (S4) — PolymarketAdapter, PredictionMarketFetchResult |
| **Severity** | HIGH (all Polymarket data ingestion silently stopped) |
| **Discovered** | 2026-04-27 ingestion pipeline audit |
| **Root cause** | Polymarket Gamma API changed response format circa April 2026. Old format: `tokens` was a list of `{outcome, token_id, price}` dicts. New format: `tokens` field is absent (or empty list); outcomes are in JSON-encoded string fields `outcomes`, `outcomePrices`, `clobTokenIds`. The adapter pre-check `len(market.get("tokens") or []) < 2` evaluates to True for all markets → all skipped; `polymarket_fetch_complete new=0` every run. |
| **Symptom** | `polymarket_fetch_complete new=0 pages=1` on every run despite 500+ active markets. All markets logged as `polymarket_market_skip_insufficient_outcomes token_count=0`. Zero rows in `market_data_db.prediction_markets`. |
| **Fix** | Updated pre-check to use `max(len(tokens), len(clob_token_ids))` where `clob_token_ids` is parsed from the JSON string `clobTokenIds` field. Updated `from_gamma_response()` to fall back to parsing `outcomes`/`outcomePrices`/`clobTokenIds` JSON strings when `tokens` is absent. Old format still supported. |

### Prevention

Any external API adapter that checks response field cardinality MUST be validated against live API responses periodically. When an adapter reports `new=0` for many consecutive runs without network errors, immediately check the raw API response structure against the parser. Add `gamma_api_page_fetched market_count=N` debug log and monitor it.

---

---

## BP-234 — asyncpg DATE Parameter Requires Python date Object, Not ISO String

| Field | Value |
|-------|-------|
| **Service** | nlp-pipeline (S6) — `get_llm_costs.py` |
| **Severity** | MEDIUM (LLM cost dashboard endpoint returns 500) |
| **Discovered** | 2026-04-27 live pipeline log scan |
| **Root cause** | asyncpg infers the type of `CAST($N AS DATE)` as `DATE`, then tries to encode the Python value as a PostgreSQL date. When the value is a string `'2026-04-01'`, asyncpg fails with `AttributeError: 'str' object has no attribute 'toordinal'` (asyncpg tries to call `.toordinal()` which is a `datetime.date` method). |
| **Symptom** | `asyncpg.exceptions.DataError: invalid input for query argument $1: '2026-04-01' ('str' object has no attribute 'toordinal')`. Endpoint returns 500. |
| **Fix** | Pass a Python `datetime.date` object: `date.fromisoformat(f"{period}-01")`. Never pass ISO date strings when the SQL uses `CAST(:param AS DATE)`. |

### Prevention

asyncpg requires native Python types for typed parameters: `datetime.date` for DATE, `datetime.datetime` for TIMESTAMP, `list[float]` does NOT work for vector (use `str()`). When writing raw SQL with `CAST(:param AS TYPE)`, use the matching Python type in the parameters dict.

---

---

## BP-234 — Market Ingestion Scheduler Silently Drops ECONOMIC_EVENTS / MACRO_INDICATOR / INSIDER_TRANSACTIONS

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) — `schedule_tasks.py:_build_incremental_task()` |
| **Severity** | HIGH (economic events, macro indicators, insider transactions never ingested) |
| **Discovered** | 2026-04-27 ingestion pipeline audit |
| **Root cause** | `_build_incremental_task()` has if-elif chains for OHLCV, QUOTES, FUNDAMENTALS, EARNINGS_CALENDAR, NEWS_SENTIMENT but falls through to `logger.debug("scheduler_unsupported_dataset_type")` and returns `None` for ECONOMIC_EVENTS, MACRO_INDICATOR, and INSIDER_TRANSACTIONS. No factory methods existed for these types on `IngestionTask`. The scheduling priority weights dict (`_EODHD_CREDIT_COST`) included these types, creating a false impression they were handled. |
| **Symptom** | `scheduler_unsupported_dataset_type dataset_type=economic_events` logged on every scheduler tick. `temporal_events` table empty. `economic_events`, `macro_indicators`, `earnings_calendar` tables in market_data_db all at 0 rows despite polling policies being present. EODHD 403 errors (demo key) obscured the fact that tasks were never even created. |
| **Fix** | Added `create_economic_events_task()`, `create_macro_indicator_task()`, `create_insider_transactions_task()` factory methods to `IngestionTask`. Added corresponding branches to `_build_incremental_task()`. |

### Prevention

When adding a new `DatasetType` enum value, always add the corresponding `_build_incremental_task` branch AND factory method atomically. Write a unit test for each dataset type in `tests/application/test_schedule_tasks.py`. If the type is in `_EODHD_CREDIT_COST` it MUST have a factory method and scheduler branch.

---

---

## BP-244 — Alpaca Class Share Symbols Rejected (BRK-B → BRK.B)

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) — `infrastructure/adapters/providers/alpaca.py` |
| **Severity** | MEDIUM (class shares permanently fail) |
| **Discovered** | 2026-04-27 ingestion pipeline investigation |
| **Root cause** | Our house symbol format uses dashes for class shares (`BRK-B`), but Alpaca requires dots (`BRK.B`). Alpaca returns HTTP 400 `{"message":"invalid symbol: BRK-B"}`. |
| **Fix** | Added `_to_alpaca_equity_symbol()` that converts `-` → `.` for non-crypto equity symbols before sending to Alpaca. Applied in both `fetch_ohlcv()` and `fetch_ohlcv_batch()`. |

### Prevention

- All provider adapters must document their symbol format requirements.
- Symbol normalization belongs in the adapter, not the use case or scheduler.
- Class share symbols with dashes appear in multiple providers — always verify the expected format in provider docs.

---

---

## BP-244 — Stale Closure Over React State in useEffect ResizeObserver

| Field | Value |
|-------|-------|
| **Services** | worldview-web — `components/instrument/OHLCVChart.tsx` |
| **Severity** | LOW (incorrect resize behavior when chart is in fullscreen — chart width is reset during fullscreen) |
| **Discovered** | 2026-04-27 instrument page QA |
| **Root cause** | A `useEffect(() => { ... }, [])` (empty deps) sets up a `ResizeObserver` callback. The callback captures `isFullscreen` from the closure at mount time, which is always `false`. When the user enters fullscreen, the callback still reads `false` and incorrectly calls `chart.applyOptions({ width })`, overriding the fullscreen layout. |
| **Symptom** | Chart may flicker or shrink when the browser window is resized while the chart is in fullscreen mode. The ResizeObserver fires and resets the chart width, collapsing the fullscreen view. |
| **Fix** | Add a `useRef` that shadows the state value and a sync `useEffect` that keeps the ref current. The stale closure reads from the ref instead of the captured state variable. See `OHLCVChart.tsx` `isFullscreenRef` pattern. |

### Prevention

- Any callback registered inside an empty-dep `useEffect` (event listeners, observers, timers) will hold a **stale closure** over all state and props from the mount render.
- If the callback needs to read current state, use a `useRef` + sync `useEffect` to track it: `const fooRef = useRef(foo); useEffect(() => { fooRef.current = foo; }, [foo]);`
- Lint rule `react-hooks/exhaustive-deps` will warn about missing dependencies — prefer fixing the deps if possible; use the ref pattern only when the effect must run only once (e.g., chart init).

---

## BP-247 — Batch OHLCV Fetch Uses First Task's Date Range for All Symbols

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) — `infrastructure/workers/worker.py:284-289` |
| **Severity** | LOW (latent — does not manifest in current scheduler configuration) |
| **Discovered** | 2026-04-27 batch efficiency investigation |
| **Root cause** | `_try_batch_execute()` passes `start=group_tasks[0].range_start, end=group_tasks[0].range_end` to `fetch_ohlcv_batch()` — the first task's date range is used for ALL symbols in the batch. This is safe only when all tasks in the group have the same date range (which the scheduler guarantees for same-day tasks via `today_midnight` truncation). If backfill tasks with different date ranges are mixed with regular tasks, some symbols will get data from the wrong date range. |
| **Symptom** | Silent: symbols get bars for the first task's date range rather than their own. No error — Alpaca returns bars for whatever range is requested. Data may be missing or doubled for affected symbols. |
| **Fix** | Group tasks by `(provider, timeframe, range_start, range_end)` instead of `(provider, timeframe)` so each unique date-range combination gets its own batch call. |

### Prevention

- Batch grouping keys must include ALL parameters that vary between tasks — not just the subset that enables grouping.
- When adding backfill task support, always verify that batch execution handles mixed date-range groups correctly.

---

## BP-254 — Derivation Consumer Hardcodes Source Timeframe

**Date discovered**: 2026-04-28
**Affected areas**: Market-data intraday resampling, multi-timeframe OHLCV pipelines

**Pattern**:
When a Kafka consumer derives coarser bars from a fine-grained OHLCV source (e.g., 1m → 5m/15m/1h), the source timeframe is hardcoded in both the consumer filter AND the use-case DB query. If the finest available granularity later changes from 1m to 5m or 15m, the consumer silently stops processing (wrong filter) and the use case fetches zero source bars (wrong timeframe query).

**Root cause**:
`IntradayResamplingConsumer` filters `timeframe == "1m"` (hardcoded string) and `ResampledOHLCVUseCase` queries `timeframe=Timeframe.ONE_MIN` (hardcoded enum). Neither is driven by configuration.

**Fix**:
Inject `source_timeframe: Timeframe` via constructor into `ResampledOHLCVUseCase` (defaults to `ONE_MIN`). Pass it from `IntradayResamplingConsumer` which reads it from `Settings.intraday_source_tf`. Consumer filter also driven from the same setting. Changing the env var then migrates the entire pipeline to the new finest granularity without code changes.

**Prevention**:
- Any consumer that filters on a specific timeframe string must read that string from config, not hardcode it.
- Any use case that queries bars of a specific timeframe must accept that timeframe as a constructor parameter.
- Add a test asserting that changing `source_timeframe` in the use case changes the DB query timeframe.

---

---

## BP-263 — SnapTrade Adapter Dropped `amount` and `fee`, Causing $0 Dividends

**Category**: Integration / Data correctness
**Severity**: CRITICAL
**First seen**: 2026-04-28 (PLAN-0046 Wave 1)
**Services**: portfolio (S1)

**Symptoms**:
- All DIVIDEND rows in the Transactions tab show `$0` total.
- Cost-basis / fee-aware P&L is silently inaccurate for BUY/SELL because broker commissions never reach the database.

**Root cause**:
`SnapTradeClient._parse_activity_list` only read `id, type, symbol, units, price, currency, trade_date, institution` from `UniversalActivity` and discarded `amount` and `fee`. SnapTrade encodes dividends as `units≈0, price≈0, amount=<cash_paid>` — without `amount` the row reaches the UI as zero. Trade fees were similarly lost.

**Fix**:
Capture both fields end-to-end:
1. Add `amount Numeric(18,8) NULL` to `transactions` (Alembic 0009; nullable, no backfill).
2. Add `amount` / `fee` to `SnapTradeActivity` VO and `RecordTransactionCommand`.
3. Adapter `_parse_activity_list` parses both via `_parse_optional_decimal` (handles None/empty/non-numeric).
4. Worker passes `fees=activity.fee or 0` and `amount=activity.amount` to the use case.
5. API schema and frontend `Transaction` type both expose `amount: Decimal | null`; `TransactionsTable` reads `tx.amount` for DIVIDEND total.

**Prevention**:
- When wrapping a third-party SDK, write a mapping table in the adapter docstring listing every source field consumed AND every documented field deliberately ignored. Reviewers catch omissions.
- Recorded-fixture unit tests for adapter parsing (see `tests/unit/test_snaptrade_parsing.py`).

**Regression test**: `services/portfolio/tests/unit/test_snaptrade_parsing.py::TestParseActivityList`

---

---

### BP-343: SummaryWorker Always Produces Zero Summaries — Missing Evidence Promotion Step

**Category**: Workers & Schedulers
**Severity**: HIGH
**First seen**: 2026-05-03
**Services**: knowledge-graph (S7)

**Symptoms**:
- `summary_worker_complete summaries_created=0 summaries_skipped=0` every run
- 26 relations have `summary_stale=true AND confidence IS NOT NULL` but nothing is processed
- `relation_evidence` table is always empty (0 rows) despite `relation_evidence_raw` having 100+ rows

**Root cause**:
Two compounding failures:
1. `RelationEvidenceRepository.insert_immutable()` has zero callers anywhere in the codebase — the "promotion step" from `relation_evidence_raw` → `relation_evidence` was designed but never implemented in any worker
2. `relation_evidence_raw` had no `evidence_text` column, and `insert_raw()` silently dropped `RawRelation.evidence_text` even though the enriched consumer parsed it from Kafka messages
Result: `SummaryWorker.get_all_for_relation()` queries `relation_evidence` → always 0 rows → always skips every relation

**Example**:
```python
# Bad: SummaryWorker queries only the immutable table (always empty)
evidence_rows = await ev_repo.get_all_for_relation(relation_id, limit=10)
if not evidence_rows:
    continue  # Always hits this — no summaries ever produced

# Good: Fall back to raw staging table until promotion is implemented
evidence_rows = await ev_repo.get_all_for_relation(relation_id, limit=10)
if not evidence_rows:
    evidence_rows = await ev_repo.get_raw_for_relation_id(relation_id, limit=10)
if not evidence_rows:
    continue
```

**Fix**:
1. Migration 0019: `ALTER TABLE relation_evidence_raw ADD COLUMN evidence_text TEXT`
2. `insert_raw()`: add `evidence_text: str | None = None` parameter, include in INSERT
3. `materialize_graph()`: pass `evidence_text=rel.evidence_text` to `insert_raw()`
4. Add `get_raw_for_relation_id(relation_id, limit)` to `RelationEvidenceRepository` — JOINs `relations` to resolve triple, queries `relation_evidence_raw`
5. `SummaryWorker.run()`: use `get_raw_for_relation_id()` as fallback when `get_all_for_relation()` returns empty

**Prevention**:
- Any repository method that has zero callers across the codebase is a red flag — grep for the method name before shipping
- When designing a two-stage pipeline (raw → immutable), implement both stages in the same PR or the pipeline silently produces no output
- Add a `SELECT COUNT(*) FROM relation_evidence` to the worker's log output as a health check

**Regression test**: `services/knowledge-graph/tests/unit/infrastructure/workers/test_summary_worker.py::TestSummaryWorkerRawFallback`

---

---

### BP-355: ProviderAuthError Permanently Blocks Re-scheduling After API Key Rotation

**Category**: Workers & Schedulers
**Severity**: HIGH
**First seen**: 2026-05-04
**Services**: market-ingestion

**Symptoms**:
- Tasks for a dataset type fail with `EODHD auth failed: HTTP 403` (or similar) after an API key rotation
- Scheduler logs show `tasks_enqueued=0` every tick despite the new key being active
- Watermarks show `last_success_bar_ts` from a previous successful run but `last_success_at = NULL`
- Data freshness is stale for weeks/months — scheduler doesn't re-run until the polling interval expires from the old watermark date

**Root cause**:
`ProviderAuthError` is treated as a **fatal, non-retryable** error by design: `_persist_fail()` sets `status='failed', next_attempt_at=NULL`. This is correct for permanent auth failures (e.g., revoked key, wrong service URL). However, when the underlying cause is a temporary auth issue (wrong API key that was later fixed in gitops), the tasks are permanently dead with no automatic recovery path.

Additionally, watermarks for previously-successful tasks retain `last_success_bar_ts` from the last successful run. With a long polling interval (e.g., 90 days for fundamentals), the scheduler correctly computes `is_due(last_success_bar_ts) = False` and doesn't re-schedule. The fix requires manually resetting the watermarks.

**Root cause detail (why last_success_bar_ts was set without last_success_at)**:
In an older version of `watermark_repository.py::save()` (pre-commit `66258435`), `last_success_at` was not written — only `last_success_bar_ts`. Watermarks from that era have `last_success_bar_ts` set from genuine successful runs but `last_success_at = NULL`. The scheduler uses `last_success_bar_ts` for the `is_due()` check and correctly considers these symbols as recently-fetched (not due for 90 days).

**Fix**:
```sql
-- Reset watermarks for symbols that never succeeded under the new code
-- (last_success_at IS NULL = "was set by old code or never succeeded")
UPDATE ingestion_watermarks
SET last_success_bar_ts = NULL,
    last_success_at = NULL,
    updated_at = NOW()
WHERE provider = 'eodhd'
  AND dataset_type = '<affected_dataset_type>'
  AND last_success_at IS NULL;
-- The scheduler will treat reset symbols as "never run" (is_due(NULL) = True)
-- and create new tasks on the next tick.
```

After the watermark reset, the scheduler creates new tasks on the next tick and processes them with the updated API key.

**Prevention**:
- When an API key is rotated in gitops, document the runbook: reset watermarks for the affected provider + dataset_types
- Consider adding an admin API endpoint: `POST /v1/admin/providers/{provider}/reset-watermarks?dataset_type=X` to avoid direct SQL manipulation
- Add a check to the `_persist_fail()` path: log `scheduler_will_not_retry_until=<date>` so the silence is visible in logs
- Log `watermark_stale_bar_ts_without_success` at startup when `last_success_at IS NULL AND last_success_bar_ts IS NOT NULL` is detected

**Regression test**: N/A (operational runbook, not a code bug)

---

### BP-359: Single-item embed loop — batch API never called with full batch

**Category**: Workers & Schedulers
**Severity**: HIGH
**First seen**: 2026-05-04
**Services**: knowledge-graph (NarrativeRefreshWorker, DefinitionRefreshWorker, EmbeddingRefreshWorker, FundamentalsRefreshWorker), nlp-pipeline (Block 7 run_embeddings_block)

**Symptoms**:
- Embedding backlog drains slowly despite healthy worker logs (e.g., 807/1888 narrative embeddings after multiple days)
- `llm_usage_log` shows hundreds of individual 1-item embedding entries per worker cycle instead of 1 multi-item entry
- Worker cycle completes but processes only 100 entities per hour at DeepInfra latency (~15s for 100 × 150ms sequential calls)
- `entity_embedding_state` overdue count stays high relative to the cycle interval

**Root cause**:
Every embedding worker called `embed([single_input])` once per entity inside a sequential `for` loop. The `DeepInfraEmbeddingAdapter.embed()` method already accepts a list of any size and sends all texts in a single HTTP request body (`"input": [text1, text2, ...]`). The workers were never updated to exploit batch semantics, resulting in N HTTP round-trips where N = number of due entities (up to 100+).

Additionally, the hardcoded `_BATCH_LIMIT` constants (50–100) capped how many entities were fetched per cycle, meaning the backlog shrank by at most 100 entities per hour even if the embed call itself was fast.

```python
# Bad — 100 sequential HTTP calls for 100 entities
for row in due:
    outputs = await self._llm.embed([inp])   # 1 item, 1 HTTP call
    await emb_repo.upsert(...)

# Good — 1 HTTP call for all entities
all_inputs = [EmbeddingInput(text=t) for _, t in texts_with_meta]
all_outputs = await self._llm.embed(all_inputs)  # all items, 1 HTTP call
```

**Fix**:
1. In each worker's `run()`, collect ALL texts first (Phase 1).
2. Call `embed(all_inputs)` once, chunked by `_EMBED_CHUNK_SIZE = 200` when len > 200.
3. Map outputs back to entity_ids by index.
4. Remove hardcoded `_BATCH_LIMIT`; replace with `batch_limit=0` constructor param (0 = all due entities, translated to `LIMIT 100_000` in the DB query).
5. For workers with per-entity external I/O (FundamentalsRefreshWorker), parallelize entity fetches with `asyncio.gather` + `asyncio.Semaphore(concurrency)` before the batch embed.

**Performance impact**:
- DeepInfra (~150ms/call): 100 entities sequential = 15s → 1 batch call = 150ms (100× speedup)
- Ollama CPU (~10s/call): 100 entities sequential = 1000s → minimal improvement (Ollama processes sequentially on CPU even in batch mode, but fewer Python/event-loop overhead)
- Backlog drain: with `batch_limit=0`, all overdue entities drain in a single cycle instead of 100/cycle/hour

**Prevention**:
- Any new worker that embeds N entities MUST call `embed(all_N_inputs)` outside the loop, not `embed([single])` inside the loop.
- Review checklist: when reviewing a worker with a `for row in batch` loop that calls `embed()`, flag if the call is inside the loop with a single input.
- `_EMBED_CHUNK_SIZE = 200` constant guards against API request-size limits — always chunk when > 200 inputs.

**Regression tests**:
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_narrative_refresh_worker.py::TestNarrativeRefreshWorker::test_embed_called_once_for_batch_of_entities`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_embedding_refresh_worker.py::TestEmbeddingRefreshWorker::test_embed_called_once_for_batch`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py::TestBatchEmbedding::test_multiple_entities_embed_called_once_with_all_inputs`
- `services/nlp-pipeline/tests/unit/application/blocks/test_embeddings.py::TestBatchEmbedSingleCall::test_batch_embed_single_call_for_multiple_sections`

---

## BP-365: `_store_canonical` skip-if-exists serves stale empty canonical to consumers

**Service**: market-ingestion
**Severity**: HIGH
**Discovered**: 2026-05-03

**Symptom**: Kafka consumers download canonical NDJSON from MinIO and find `payload: []` — zero rows — even though the ingestion worker logged a successful fetch. `temporal_events` stays empty for all non-EU economic event symbols.

**Root cause**: `_store_canonical` in `execute_task.py` had a D-008 idempotency guard that skipped the MinIO PUT if the object key already existed:

```python
if await self._store.exists(self._canonical_bucket, key):
    sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    return ObjectRef(...)  # returns without uploading!
```

This is correct when a task is retried with identical bytes. But when a task is rescheduled after a provider bug fix (e.g., alpha-2 country code correction), the old empty canonical file (144 bytes, `payload: []`) remains on disk while the outbox records the new SHA-256. The consumer downloads the old file and silently drops all rows.

**Fix**: Always PUT the canonical file — MinIO PUT is idempotent (overwrites). Remove the skip-if-exists guard entirely. Also reset `last_success_sha256 = NULL` in `ingestion_watermarks` for affected symbols to force outbox re-publication.

**Also required**: Purge Valkey dedup cache keys (`kg:eco_events:*`) so the consumer re-processes the new Kafka messages (TTL is 7 days; stale event_ids would otherwise be deduplicated).

**File**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` — `_store_canonical`

---

## BP-366: ISO-3166 alpha-3 codes sent to EODHD `/economic-events`

**Service**: market-ingestion
**Severity**: HIGH
**Discovered**: 2026-05-03

**Symptom**: All economic event symbols except `EVENTS.EU` returned empty payloads. EU happened to work because EODHD accepts "EU" as both an alpha-2 and unofficial alpha-3 code; "USA", "JPN", "CHN" returned empty lists.

**Root cause**: `_fetch_provider_data` extracted the country code from the task symbol (`EVENTS.USA` → `"USA"`) and passed it directly to `ext_adapter.fetch_economic_events(country="USA")`. EODHD `/economic-events` requires ISO-3166 alpha-2 codes (US, JP, CN).

**Fix**: Add `iso3_to_iso2` dict in `_fetch_provider_data` before the API call:

```python
iso3_to_iso2 = {"USA": "US", "GBR": "GB", "JPN": "JP", "CHN": "CN", ...}
country = iso3_to_iso2.get(_raw_country, _raw_country)
```

The `get(x, x)` fallback means valid alpha-2 codes (e.g., "EU") pass through unchanged.

**File**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` — `_fetch_provider_data`, `DatasetType.ECONOMIC_EVENTS` branch

---

## BP-386: KG relation type exact-match canonicalization is case-sensitive

**Service**: knowledge-graph (S7)
**Severity**: HIGH
**Discovered**: 2026-05-05

**Symptom**: ~30% of LLM-extracted relations have `canonical_type=NULL` in the `relations` table, appearing as untyped edges in the graph. `relation.type.proposed.v1` Kafka events generated for types that should have matched exactly.

**Root cause**: `canonicalize_relation_type()` Step 1 exact-match lookup compares `raw_type` directly to `relation_type_registry.canonical_type`. LLM extraction emits lowercase types (`competes_with`, `has_executive`) but migration 0004 seeded AGE graph labels in UPPERCASE (`COMPETES_WITH`). The string comparison `"competes_with" == "COMPETES_WITH"` fails, Step 1 misses, Step 2 ANN may also miss on close embeddings → `canonical_type=NULL`.

**Fix**:
```python
# In canonicalize_relation_type(), before Step 1:
normalized_raw_type = raw_type.lower().strip().replace(" ", "_")
# Use normalized_raw_type for exact lookup
result = await registry_repo.find_by_canonical_type(normalized_raw_type)
```
Plus a data migration to normalize all `relation_type_registry.canonical_type` values to lowercase, and all existing `relations.canonical_type` values.

**Prevention**: Always normalize string keys before exact database lookups when the source (LLM) and target (seed data) may use different casing conventions.

**File**: `services/knowledge-graph/src/knowledge_graph/application/blocks/canonicalization.py` — `canonicalize_relation_type()`

---

## BP-387: KG SummaryWorker generates 0 summaries due to NULL evidence_text + unregistered model ID

**Service**: knowledge-graph (S7)
**Severity**: HIGH
**Discovered**: 2026-05-05

**Symptom**: `SummaryWorker` logs `summary_worker_complete` with `summaries_created=0, skipped_null_evidence_text=N` for all N stale relations. No relation summaries ever generated.

**Root cause**: Two compounding issues:
1. `relation_evidence_raw` rows inserted before BP-346 (evidence_text propagation fix) have `evidence_text=NULL` and `canonicalized_evidence_text=NULL`. The worker's list comprehension `[str(e.get("evidence_text", "")) or str(e.get("canonicalized_evidence_text", "")) for e in rows if e.get("evidence_text") or e.get("canonicalized_evidence_text")]` fails because the `if` guard checks the raw value before any string coercion — NULL values fail both guards → all texts filtered → `evidence_texts=[]` → `skipped_null_evidence_text` counter incremented → `continue`.
2. `_SUMMARY_MODEL_ID = "kg-summary-v1"` may not be registered in `FallbackChainClient` routing table → `extract()` returns `None` silently → `summaries_failed` path even when evidence_text is non-null.

**Fix**:
```python
# Normalize to use either column
evidence_texts = []
for e in evidence_rows:
    text = e.get("evidence_text") or e.get("canonicalized_evidence_text")
    if text:
        evidence_texts.append(str(text))
```
And verify `kg-summary-v1` is mapped to a valid model in `FallbackChainClient` config; add a fallback to the default extraction model if unregistered.

**Prevention**: When writing evidence fallback filters with `or`, test with rows where the PRIMARY column is NULL — the `dict.get(key, "")` pattern evaluates the empty string (`""`) as falsy if converted back to bool, but here the filter checks `.get()` output directly before conversion.

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary.py` — `SummaryWorker.run()` evidence text filter

---

## BP-462 — SEC EDGAR routing silently stuck at LIGHT tier — never LLM-scored

**Date discovered**: 2026-05-11
**Service affected**: `nlp-pipeline` (Block 5 routing, `ArticleRelevanceScoringWorker`)

### Symptom

All SEC EDGAR documents that passed through the NLP pipeline received `routing_tier = 'light'` regardless of their informational value, and zero had `llm_relevance_score` set. The `ArticleRelevanceScoringWorker` only scores MEDIUM/DEEP documents, so all SEC filings were permanently excluded from relevance scoring and therefore excluded from news feed ranking.

### Root Cause (two combined gaps)

**Gap 1 — Missing DOCUMENT_TYPE_SIGNAL entry**: `routing.py::DOCUMENT_TYPE_SIGNAL` had entries for `sec_8k` (0.95), `sec_10k` (0.90), `sec_10q` (0.90), `sec_def14a` (0.88), but NOT for `sec_edgar` — the actual source_type emitted by `content-ingestion/adapters/sec_edgar/adapter.py`. Because `source_type = "sec_edgar"` fell through to `_DEFAULT_DOCUMENT_TYPE_SIGNAL = 0.50`, the document_type contribution was 0.50 × 0.05 = 0.025 instead of the intended ~0.044.

**Gap 2 — Missing source_trust_weights row**: The `source_trust_weights` table was seeded in migration 0001 with entries for specific form types (sec_10k, sec_8k, etc.) but not for the generic `sec_edgar` source type. The routing block used `_DEFAULT_SOURCE_TRUST = 0.5` (manual content level) instead of the 0.90+ that SEC regulatory filings warrant.

Combined effect: SEC EDGAR docs scored ~0.32 composite (LIGHT) because entity_density is structurally low in raw EDGAR HTML (boilerplate content, not a signal of low value).

### Fix

1. Added `"sec_edgar": 0.88` to `DOCUMENT_TYPE_SIGNAL` in `routing.py`.
2. Added `_AUTHORITATIVE_FILING_SOURCES` frozenset (`sec_edgar`, `sec_8k`, `sec_10k`, `sec_10q`, `sec_def14a`, `tenant_upload`) with a minimum-tier override in `compute_routing_score`: if `routing_tier == LIGHT and source_type in _AUTHORITATIVE_FILING_SOURCES` → upgrade to MEDIUM.
3. Created migration `0039_add_sec_edgar_source_trust_weight.py` adding `sec_edgar → trust_weight=0.90`.
4. Backfilled 130 pre-fix routing decisions via `UPDATE routing_decisions SET final_routing_tier = 'medium' WHERE source_type = 'sec_edgar' AND routing_tier = 'light'`.

### Detection

```sql
-- Check for authoritative sources stuck at light tier
SELECT dsm.source_type, rd.routing_tier, COUNT(*)
FROM routing_decisions rd
JOIN document_source_metadata dsm ON rd.doc_id = dsm.doc_id
WHERE dsm.source_type IN ('sec_edgar', 'sec_8k', 'sec_10k', 'sec_10q', 'tenant_upload')
  AND rd.routing_tier = 'light'
  AND rd.final_routing_tier IS NULL
GROUP BY dsm.source_type, rd.routing_tier;
```

### Prevention

When adding a new source adapter in content-ingestion:
1. Verify `source_type` is in `DOCUMENT_TYPE_SIGNAL` in `routing.py`.
2. Verify `source_type` is in `source_trust_weights` table (or add via migration).
3. If source is an authoritative filing, add to `_AUTHORITATIVE_FILING_SOURCES`.

**File**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` — `DOCUMENT_TYPE_SIGNAL`, `_AUTHORITATIVE_FILING_SOURCES`, `compute_routing_score`
**Migration**: `services/intelligence-migrations/alembic/versions/0039_add_sec_edgar_source_trust_weight.py`
