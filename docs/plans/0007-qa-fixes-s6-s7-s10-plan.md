---
id: PLAN-0007
prd: PLAN-0001-C (QA pass)
title: "PLAN-0001-C QA Fixes — Idempotency, Valkey Hardening, Observability, Deployment Constraints"
status: draft
created: 2026-03-30
updated: 2026-03-30
waves_done: 0
plans: 1
waves: 2
tasks: 8
---

# PLAN-0007: PLAN-0001-C QA Fixes

## Overview

**Source**: PLAN-0001-C QA pass (2026-03-30) — 8 findings deferred as "decisions needed"
**Goal**: Resolve all deferred CRITICAL/MAJOR findings from the PLAN-0001-C review.
**Total scope**: 1 sub-plan, 2 waves, 8 tasks.
**Services affected**: S6 (nlp-pipeline), S7 (knowledge-graph), S10 (alert)

---

## Summary of Open Items

| ID | Severity | Service | Issue | Decision |
|----|----------|---------|-------|----------|
| D-002 | CRITICAL | S6 | `is_duplicate` always False + `add_batch` uses `session.add()` — re-delivery creates duplicate sections/chunks | Add `ON CONFLICT DO NOTHING` to section + chunk repos |
| F-DATA-004 | MAJOR | S7 | `is_duplicate` / `mark_processed` call Valkey without try/except — exception propagates if Valkey configured but unreachable | Wrap in try/except; `is_duplicate` → False on error |
| F-DATA-007 | MAJOR | S10 | `_resolve_topic` returns `event_type` as-is when no known topic matches — no whitelist validation | Add `KNOWN_TOPICS` set; log warning + return sentinel on fallthrough |
| F-DS-011 | MAJOR | S7 | Worker `run()` exceptions not visible in Prometheus metrics — APScheduler swallows them silently | Wrap `worker.run` in error-catching closure; increment `s7_worker_crash_total` |
| F-DS-008 | MAJOR | S10 | `WatchlistCache.get_watchers()` cannot distinguish S1 failure from "entity has no watchers" — failure is silent at fanout | Add `s10_s1_lookup_failed_total` counter; log warning at cache level |
| D-004 | MAJOR | S6 | Block 9 `intel_session` commits before outer `nlp_session` commit (line 279 vs 341) — if nlp commit fails, intel_db writes are orphaned | Accept eventual consistency; add warning log + document in `.claude-context.md` |
| D-005 + F-DS-010 | MAJOR | S10 | WebSocket `user_id` relies on S9 gateway injection (not validated at S10); in-memory `_connections` is single-replica only | Confirm + document both constraints (code is already correct; docs need updating) |

---

## Wave A-1: Consumer Idempotency & Valkey Hardening

**Goal**: Eliminate duplicate-on-redelivery risk in S6 and make Valkey dedup failure-safe in S7 + S10.
**Depends on**: none
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/section.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` (lines 23–55, PK definitions)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/consumer/enriched_consumer.py` (lines 246–256)
- `services/alert/src/alert/infrastructure/consumer/intelligence_consumer.py` (lines 108–148)

---

#### T-A-1-01: S6 — Add `ON CONFLICT DO NOTHING` to `SectionRepository` and `ChunkRepository`

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/section.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk.py`
- `services/nlp-pipeline/tests/unit/infrastructure/test_section_repository.py` (new or extend)
- `services/nlp-pipeline/tests/unit/infrastructure/test_chunk_repository.py` (new or extend)

**PRD reference**: D-002 from PLAN-0001-C QA pass

**What to build**:
Replace `session.add(row)` with a PostgreSQL-dialect `INSERT … ON CONFLICT DO NOTHING` statement in both repositories. On re-delivery of the same `doc_id`, sections and chunks already exist with the same `section_id`/`chunk_id` UUID (deterministic from doc_id + index). The upsert silently skips duplicates instead of raising.

Note: `section_id` and `chunk_id` use `uuid.uuid4()` (random) in models, but the pipeline generates them deterministically before calling `add_batch` via domain model construction. The PKs are stable across re-deliveries of the same event.

**Entities / Components**:
- **`SectionRepository.add`**: Replace `self._session.add(row)` with:
  ```python
  from sqlalchemy.dialects.postgresql import insert as pg_insert
  stmt = (
      pg_insert(SectionModel)
      .values(
          section_id=section.section_id,
          doc_id=section.doc_id,
          section_index=section.section_index,
          section_type=section.section_type,
          title=section.title,
          speaker=section.speaker,
          char_start=section.char_start,
          char_end=section.char_end,
          token_count=section.token_count,
      )
      .on_conflict_do_nothing(index_elements=["section_id"])
  )
  await self._session.execute(stmt)
  ```
- **`ChunkRepository.add`**: Same pattern, all ChunkModel fields, `index_elements=["chunk_id"]`.
- Remove the `_new_id` helper from `SectionRepository` if it's now unused (it was generating IDs that aren't used by `add`).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_add_section_idempotent` | Adding the same Section twice does not raise and yields one DB row | unit |
| `test_add_chunk_idempotent` | Adding the same Chunk twice does not raise and yields one DB row | unit |
| `test_add_batch_partial_redelivery` | `add_batch` with mix of new + existing section_ids inserts only new rows | unit |

**Acceptance criteria**:
- [ ] `SectionRepository.add` uses `pg_insert(...).on_conflict_do_nothing()`
- [ ] `ChunkRepository.add` uses `pg_insert(...).on_conflict_do_nothing()`
- [ ] Re-inserting a row with the same PK raises no exception in tests
- [ ] ruff + mypy pass on changed files
- [ ] Minimum 3 new unit tests

---

#### T-A-1-02: S7 — Wrap Valkey dedup in try/except in `EnrichedConsumer`

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/consumer/enriched_consumer.py` (lines 246–256)
- `services/knowledge-graph/tests/unit/consumer/test_enriched_consumer.py` (new tests)

**PRD reference**: F-DATA-004 from PLAN-0001-C QA pass

**What to build**:
Currently, `is_duplicate` and `mark_processed` call Valkey without exception handling. If Valkey is configured (`_dedup_client is not None`) but temporarily unavailable (network partition, restart), the exception propagates through the consumer loop and retries the message unnecessarily. The fix: wrap both Valkey calls in try/except. On error, `is_duplicate` returns `False` (prefer re-processing over skipping) and `mark_processed` logs a warning and returns silently.

**Logic & Behavior**:
```python
async def is_duplicate(self, event_id: str) -> bool:
    if self._dedup_client is None:
        return False
    key = f"{self._dedup_prefix}:{event_id}"
    try:
        return bool(await self._dedup_client.exists(key))
    except Exception:
        logger.warning("enriched_consumer.valkey_check_failed", event_id=event_id, exc_info=True)
        return False  # Prefer at-least-once over skipping

async def mark_processed(self, event_id: str) -> None:
    if self._dedup_client is None:
        return
    key = f"{self._dedup_prefix}:{event_id}"
    try:
        await self._dedup_client.set(key, "1", ex=86400)
    except Exception:
        logger.warning("enriched_consumer.valkey_mark_failed", event_id=event_id, exc_info=True)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_is_duplicate_valkey_error_returns_false` | When Valkey raises, `is_duplicate` returns False (no exception propagates) | unit |
| `test_mark_processed_valkey_error_logs_warning` | When Valkey raises, `mark_processed` logs warning and returns silently | unit |
| `test_is_duplicate_none_client_returns_false` | Existing behavior: `None` client returns False (no regression) | unit |

**Acceptance criteria**:
- [ ] `is_duplicate` never raises even when Valkey client raises
- [ ] `mark_processed` never raises even when Valkey client raises
- [ ] Both log `exc_info=True` warnings on Valkey error
- [ ] Existing dedup behavior (with working Valkey) is unchanged
- [ ] ruff + mypy pass

---

#### T-A-1-03: S10 — Wrap Valkey dedup in try/except in `IntelligenceConsumer`

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/consumer/intelligence_consumer.py` (lines 138–148)
- `services/alert/tests/unit/consumer/test_intelligence_consumer.py` (new tests)

**PRD reference**: F-DATA-004 (same pattern as T-A-1-02) from PLAN-0001-C QA pass

**What to build**:
Identical fix to T-A-1-02 but in the S10 `IntelligenceConsumer`. The `is_duplicate` and `mark_processed` methods have the same unguarded Valkey calls at lines 138–148. Apply the same try/except pattern with `intelligence_consumer.valkey_check_failed` and `intelligence_consumer.valkey_mark_failed` log event names.

**Logic & Behavior**: Same as T-A-1-02 — `is_duplicate` returns `False` on error; `mark_processed` logs and returns silently on error.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_is_duplicate_valkey_error_returns_false` | Valkey error → False, no raise | unit |
| `test_mark_processed_valkey_error_logs_warning` | Valkey error → warning log, no raise | unit |

**Acceptance criteria**:
- [ ] Same criteria as T-A-1-02
- [ ] Log event names are `intelligence_consumer.valkey_check_failed` / `intelligence_consumer.valkey_mark_failed`

---

#### T-A-1-04: S10 — Validate `_resolve_topic` against known topic whitelist

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/consumer/intelligence_consumer.py` (lines 108–126)
- `services/alert/tests/unit/consumer/test_intelligence_consumer.py`

**PRD reference**: F-DATA-007 from PLAN-0001-C QA pass

**What to build**:
`_resolve_topic` currently falls through to `return event_type` (line 126) for unknown topics. The `AlertFanoutUseCase.execute()` will then call `_extract_entity_id(event, topic)` which returns `None` for any topic not in its `if/elif` chain, correctly suppressing the event. But the fallthrough is silent — no observability for malformed events. The fix: add a `_KNOWN_TOPICS` constant and a warning log when the topic cannot be resolved to a known value.

**Logic & Behavior**:
```python
_KNOWN_TOPICS: frozenset[str] = frozenset({
    "nlp.signal.detected.v1",
    "graph.state.changed.v1",
    "intelligence.contradiction.v1",
})

@staticmethod
def _resolve_topic(value: dict[str, Any], headers: dict[str, str]) -> str:
    # 1. Try X-Source-Topic header first
    topic_header = headers.get("X-Source-Topic", "")
    if topic_header:
        if topic_header not in _KNOWN_TOPICS:
            logger.warning(
                "intelligence_consumer.unknown_topic_from_header",
                topic=topic_header,
            )
        return topic_header

    # 2. Fall back to event_type field
    event_type: str = str(value.get("event_type", ""))
    if event_type.startswith("nlp.signal"):
        return "nlp.signal.detected.v1"
    if event_type.startswith("graph.state"):
        return "graph.state.changed.v1"
    if event_type.startswith("intelligence.contradiction"):
        return "intelligence.contradiction.v1"

    # 3. Unresolvable — log warning; fanout will suppress via _extract_entity_id → None
    logger.warning(
        "intelligence_consumer.unresolvable_topic",
        event_type=event_type,
        event_id=value.get("event_id"),
    )
    return event_type  # fanout degrades gracefully for unknown topics
```

Note: `_resolve_topic` is `@staticmethod` — the logger call needs to use the module-level `logger` variable. Either remove `@staticmethod` or access the module-level logger. Preferred: keep it a regular method (remove `@staticmethod`) so it can use `self._logger` or the module `logger`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_resolve_topic_from_header_known` | X-Source-Topic header returns header value | unit |
| `test_resolve_topic_from_header_unknown_logs_warning` | Unknown header value logs warning | unit |
| `test_resolve_topic_fallback_signal` | `event_type="nlp.signal.detected"` → `"nlp.signal.detected.v1"` | unit |
| `test_resolve_topic_fallback_graph` | `event_type="graph.state.changed"` → `"graph.state.changed.v1"` | unit |
| `test_resolve_topic_unknown_logs_warning` | Unknown event_type logs warning + returns event_type as-is | unit |

**Acceptance criteria**:
- [ ] `_KNOWN_TOPICS` constant defined at module level
- [ ] Warning logged on both unknown header and unknown event_type fallthrough
- [ ] Known event_type prefixes still resolve correctly
- [ ] `@staticmethod` either removed (preferred) or logger accessed at module scope
- [ ] 5 new unit tests pass
- [ ] ruff + mypy pass

---

### Wave A-1 Validation Gate
- [ ] `ruff check` + `ruff format --check` on changed files
- [ ] `mypy` on changed packages
- [ ] `python -m pytest tests/ -m "unit" -v` in each changed service (S6, S7, S10) — all pass
- [ ] Minimum 10 new unit tests total across all 4 tasks
- [ ] No architecture violations

### Regression Guardrails
- **BP-064**: No `204` response + `None` body. Not applicable here (no API changes).
- **BP-066**: `Mapped[datetime]` with `from __future__ import annotations` needs runtime import. S6 models already have this; don't move `datetime` under `TYPE_CHECKING` in models.
- Verify: `SectionRepository.add` still handles the case where `section.section_id` is already set by the domain model (not auto-generated by the DB).

---

## Wave A-2: Observability, S1 Signaling & Documentation

**Goal**: Make S7 worker crashes visible in Prometheus; add S1 availability signaling in S10; document the D-004 eventual consistency gap and the S10 single-replica + auth-injection constraints.
**Depends on**: Wave A-1 (can share test session setup patterns)
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure + observability + docs

### Pre-read (agent must read before starting)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/alert/src/alert/infrastructure/cache/watchlist_cache.py`
- `services/alert/src/alert/infrastructure/clients/s1_client.py`
- `services/alert/src/alert/infrastructure/metrics/prometheus.py`
- `services/alert/src/alert/api/routes.py` (WebSocket route auth comment)
- `services/alert/src/alert/infrastructure/websocket/manager.py` (single-replica docstring)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumer/article_consumer.py` (lines 256–341)
- `docs/services/alert-service.md`
- `services/alert/.claude-context.md`
- `services/nlp-pipeline/.claude-context.md`

---

#### T-A-2-01: S7 — Worker crash counter and exception-catching wrapper

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/tests/unit/infrastructure/test_scheduler.py` (new tests)

**PRD reference**: F-DS-011 from PLAN-0001-C QA pass

**What to build**:
APScheduler catches all exceptions from job functions and logs them, but the S7 Prometheus metrics have no `worker_crash_total` counter. When a worker raises, the crash is invisible to dashboards and alerting rules. The fix is two parts:
1. Add `s7_worker_crash_total` counter to `prometheus.py` with label `["worker"]`.
2. In `KnowledgeGraphScheduler._resolve_job`, wrap the returned `worker.run` in a closure that catches `Exception`, increments the counter with the worker name, logs a structured error, and re-raises (so APScheduler can handle retries via its own coalesce logic).

**Entities / Components**:
- **`s7_worker_crash_total`** (new Counter in `prometheus.py`):
  ```python
  s7_worker_crash_total = Counter(
      "s7_worker_crash_total",
      "Total unhandled exceptions from background worker jobs, by worker.",
      ["worker"],
  )
  ```
- **`_wrap_worker`** (new method on `KnowledgeGraphScheduler`):
  ```python
  def _wrap_worker(self, name: str, fn: Any) -> Any:
      """Wrap a worker.run coroutine function with crash instrumentation."""
      from knowledge_graph.infrastructure.metrics.prometheus import s7_worker_crash_total

      async def _instrumented() -> None:
          try:
              await fn()
          except Exception:
              s7_worker_crash_total.labels(worker=name).inc()
              logger.error(  # type: ignore[no-any-return]
                  "kg_worker_crashed",
                  worker=name,
                  exc_info=True,
              )
              raise  # re-raise so APScheduler records the failure

      _instrumented.__name__ = f"instrumented_{name}"
      return _instrumented
  ```
- **`_resolve_job`** update:
  ```python
  def _resolve_job(self, name: str) -> Any:
      worker = self._workers.get(name)
      if worker is not None and hasattr(worker, "run"):
          return self._wrap_worker(name, worker.run)
      return self._make_stub(name)
  ```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_worker_crash_increments_counter` | When a worker raises, `s7_worker_crash_total` is incremented with correct worker label | unit |
| `test_worker_crash_logs_error` | When a worker raises, `kg_worker_crashed` error is logged | unit |
| `test_worker_crash_reraises` | Exception is re-raised after instrumentation | unit |
| `test_stub_does_not_increment_counter` | No-op stub does not trigger the crash counter | unit |

**Acceptance criteria**:
- [ ] `s7_worker_crash_total` counter exists in `prometheus.py` with `["worker"]` label
- [ ] `_wrap_worker` wraps real workers; stubs are not wrapped
- [ ] Exception is re-raised after counter increment
- [ ] `kg_worker_crashed` logged at ERROR with `exc_info=True`
- [ ] 4 new unit tests pass
- [ ] ruff + mypy pass

---

#### T-A-2-02: S10 — S1 unavailability counter and warning in `WatchlistCache`

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/metrics/prometheus.py`
- `services/alert/src/alert/infrastructure/cache/watchlist_cache.py`
- `services/alert/tests/unit/infrastructure/test_watchlist_cache.py` (new tests)

**PRD reference**: F-DS-008 from PLAN-0001-C QA pass

**What to build**:
When S1 is down, `S1Client._get_json` returns `None` and logs `s1_client_request_failed`. But `WatchlistCache.get_watchers` cannot distinguish between "S1 returned empty watchlist" and "S1 request failed". The fanout then returns `FanoutResult(suppressed=False, watchers_count=0)` silently. Alerts for affected entities are silently skipped with no Prometheus signal.

Fix: Add `s10_s1_lookup_failed_total` counter. Modify `WatchlistCache` to distinguish the error case by checking whether S1 returned `None` (error) vs returned an empty `watchers` list (legitimate). Requires passing the raw `_get_json` result through or restructuring `S1Client.get_watchers_by_entity` to return a named result.

**Preferred approach** (minimal API change): Add a private `_get_watchers_raw` method to `S1Client` that returns `(list[WatcherInfo], bool)` where the bool is `True` if the call succeeded (even if empty), `False` if it failed. Update `WatchlistCache.get_watchers` to increment `s10_s1_lookup_failed_total` and log `watchlist_s1_unavailable` when `S1Client` signals failure.

**Entities / Components**:
- **`s10_s1_lookup_failed_total`** (new Counter in `prometheus.py`):
  ```python
  s10_s1_lookup_failed_total = Counter(
      "s10_s1_lookup_failed_total",
      "Total S1 watchlist lookup failures (network/HTTP error), by entity.",
  )
  ```
- **`S1Client.get_watchers_by_entity`** updated to return `(list[WatcherInfo], bool)` — bool indicates success:
  - On HTTP error: return `([], False)`
  - On success with empty list: return `([], True)`
  - On success with items: return `(items, True)`

  **Note**: This changes the method signature. `WatchlistCache` is the only caller; update it accordingly.

- **`WatchlistCache.get_watchers`** updated:
  ```python
  watchers, ok = await self._s1.get_watchers_by_entity(entity_id)
  if not ok:
      s10_s1_lookup_failed_total.inc()
      logger.warning("watchlist_s1_unavailable", entity_id=entity_id)
  elif watchers:
      await self._safe_set(key, self._serialise(watchers))
  return watchers
  ```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_s1_failure_increments_counter` | S1 network error → `s10_s1_lookup_failed_total` incremented | unit |
| `test_s1_failure_logs_warning` | S1 network error → `watchlist_s1_unavailable` warning logged | unit |
| `test_s1_empty_ok_no_counter` | S1 returns empty list (success) → counter NOT incremented | unit |
| `test_s1_success_cached` | S1 returns watchers → result cached in Valkey | unit |

**Acceptance criteria**:
- [ ] `s10_s1_lookup_failed_total` counter exists in `prometheus.py`
- [ ] `WatchlistCache.get_watchers` increments counter on S1 failure
- [ ] `watchlist_s1_unavailable` warning logged with `entity_id`
- [ ] Legitimate empty watchlist (S1 success, 0 watchers) does NOT increment the counter
- [ ] 4 new unit tests pass
- [ ] ruff + mypy pass

---

#### T-A-2-03: S10 — Confirm and document WebSocket auth-injection and single-replica constraints

**Type**: docs + test
**depends_on**: none
**blocks**: none
**Target files**:
- `docs/services/alert-service.md`
- `services/alert/src/alert/api/routes.py` (verify docstring is accurate — no code change expected)
- `services/alert/src/alert/infrastructure/websocket/manager.py` (verify docstring is accurate — no code change expected)
- `services/alert/tests/unit/api/test_alerts_api.py` (add WebSocket user_id requirement test)

**PRD reference**: D-005 and F-DS-010 from PLAN-0001-C QA pass

**What to build**:
Two related constraints need documentation confirmation:
1. **D-005 (user_id auth)**: The WebSocket endpoint `/api/v1/alerts/stream` accepts `user_id` as a query parameter without server-side validation. The `routes.py` docstring already notes this is by design (S9 gateway injects it from the auth token). Verify this comment is present and add a test confirming the endpoint requires the `user_id` parameter.
2. **F-DS-010 (single-replica)**: The `manager.py` module already has a `.. warning::` docstring documenting the single-replica constraint. Verify `docs/services/alert-service.md` contains a corresponding deployment note.

**Logic & Behavior**:
- Read `docs/services/alert-service.md` and add a `## Deployment Constraints` section if not present, documenting:
  - Single-replica requirement (WebSocket in-memory `_connections`)
  - S9 auth-injection assumption for `user_id` query parameters
- Add 1 unit test: `test_websocket_stream_requires_user_id` — GET request to WebSocket URL without `user_id` parameter returns 422.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_websocket_stream_requires_user_id` | WebSocket connect without `user_id` returns 422 | unit |

**Acceptance criteria**:
- [ ] `docs/services/alert-service.md` has a `## Deployment Constraints` section covering single-replica and S9 auth-injection
- [ ] `routes.py` WebSocket docstring confirms S9 auth-injection (no code change needed if already present)
- [ ] `manager.py` single-replica `.. warning::` docstring is present (no code change needed if already present)
- [ ] 1 new test: `test_websocket_stream_requires_user_id` passes
- [ ] ruff + mypy pass

---

#### T-A-2-04: S6 — Document D-004 eventual consistency gap; add warning log on nlp commit failure

**Type**: impl + docs
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumer/article_consumer.py` (line 341)
- `services/nlp-pipeline/.claude-context.md`

**PRD reference**: D-004 from PLAN-0001-C QA pass

**What to build**:
Block 9 of the article consumer opens an `async with self._intel_sf() as intel_session:` context inside the outer `async with self._nlp_sf() as session:` block. The inner intel_session commits (via `async with` exit) at line ~279, before the outer nlp_session commit at line 341. If the nlp commit fails, the intel_db writes from Block 9 entity resolution are already committed and cannot be rolled back.

**Decision** (accepted): This is an accepted eventual consistency trade-off. The intel_db writes in Block 9 are entity resolution audit records (mention resolutions, alias references). These are:
- Not load-bearing for downstream correctness (S7 reads from intel_db directly via its own consumer)
- Additive — re-delivery will attempt to write them again (which may succeed or be idempotent)

The fix adds observability so that if the nlp commit fails, the correlation to orphaned intel writes is visible.

**Logic & Behavior**:
Wrap the nlp commit at line 341 in a try/except to add a warning log:
```python
try:
    await session.commit()
except Exception:
    logger.warning(  # type: ignore[no-any-return]
        "nlp_commit_failed_intel_writes_may_be_orphaned",
        doc_id=str(doc_id),
        exc_info=True,
    )
    raise
```

Update `.claude-context.md` Pitfalls section with:
> **D-004 Eventual consistency gap**: Block 9 opens an `intel_sf()` session inside the outer `nlp_sf()` session. The intel_session commits before the nlp_session commit (line ~279 vs ~341). If the nlp commit fails, intel_db writes from entity resolution Block 9 are already persisted. Re-delivery will retry, which may create duplicate audit records. This is accepted as eventually consistent behaviour. The `nlp_commit_failed_intel_writes_may_be_orphaned` warning log is emitted when this occurs.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_nlp_commit_failure_logs_warning` | When session.commit() raises, `nlp_commit_failed_intel_writes_may_be_orphaned` is logged at WARNING | unit |
| `test_nlp_commit_failure_reraises` | The exception is re-raised after logging | unit |

**Acceptance criteria**:
- [ ] `article_consumer.py` wraps the nlp commit in try/except with warning log
- [ ] Warning includes `doc_id` and `exc_info=True`
- [ ] Exception is re-raised (no silent swallowing)
- [ ] `services/nlp-pipeline/.claude-context.md` updated with D-004 note under Pitfalls
- [ ] 2 new unit tests pass
- [ ] ruff + mypy pass

---

### Wave A-2 Validation Gate
- [ ] `ruff check` + `ruff format --check` on changed files
- [ ] `mypy` on changed packages
- [ ] `python -m pytest tests/ -m "unit" -v` in each changed service (S6, S7, S10) — all pass
- [ ] Minimum 11 new unit tests total across all 4 tasks
- [ ] Documentation: `docs/services/alert-service.md` has `## Deployment Constraints` section
- [ ] `services/nlp-pipeline/.claude-context.md` updated with D-004 note

### Regression Guardrails
- **BP-067**: Direct Kafka produce (bypassing outbox) must be wrapped in try/except. Not applicable here (no new Kafka produces), but check `alert_consumer.py` if touching that file.
- Verify that wrapping `worker.run` in a closure does not break APScheduler's `max_instances=1` / `coalesce=True` logic (APScheduler tracks job by id, not by function identity — the wrapper is safe).

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| ON CONFLICT DO NOTHING masks a legitimate uniqueness bug | LOW | MEDIUM | Add test verifying only the expected row exists after double-insert |
| `S1Client.get_watchers_by_entity` signature change breaks other callers | LOW | HIGH | `WatchlistCache` is the only caller — grep confirms before merging |
| `_wrap_worker` closure captured variable issues | LOW | LOW | Explicitly pass `name` as default arg to avoid late binding |
| D-004 log wrapping masks a real crash pattern | LOW | LOW | Exception is always re-raised; log is additive only |

## Critical Path
Wave A-1 → Wave A-2 (sequential by convention; tasks within each wave are independent and can be parallelized)

## Rollback Strategy
All changes are additive (new counters, try/except wrappers, log statements, doc updates). No schema migrations. Rollback = revert commits for the affected service.
