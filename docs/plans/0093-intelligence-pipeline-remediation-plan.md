---
id: PLAN-0093
title: Intelligence Pipeline Remediation — KG-RAG + Infrastructure
source_audit: docs/audits/2026-05-23-qa-intelligence-pipelines-report.md
status: draft
created: 2026-05-23
updated: 2026-05-23
revision_log:
  - 2026-05-23 — Initial draft (24 waves, ~95 tasks).
  - 2026-05-23 — Q1-Q4 open questions resolved. T-E-2-01 amended (per-FieldKind tolerance). T-G-3-05 expanded (multi-quarter × multi-question-variant). T-G-3-11 added (Weak-Point Survey: 5×5×3 = 75 queries). T-C-3-01 amended (agent investigates + 3 explicit outcome paths). Total tasks 95→96. Sub-Plan G effort 2.0d→2.5d. Total 15.5d→16.0d.
---

# PLAN-0093 — Intelligence Pipeline Remediation (KG-RAG + Infrastructure)

> **Source**: QA audit at `docs/audits/2026-05-23-qa-intelligence-pipelines-report.md` — 66 findings (5 BLOCKING, 11 CRITICAL, 27 MAJOR).
> **Pre-prod assumption**: production has not been launched. **No data backfill is required** — schemas can be tightened destructively, and data emitted before this plan does not need to be preserved.
> **Goal**: bring the KG-RAG pipeline from FAIL to PASS_WITH_WARNINGS — useful answers for ≥ 6/8 investor questions, zero BLOCKING data-corruption findings, surviving a host reboot without manual intervention.

## Overview

- **Services affected**: `knowledge-graph`, `nlp-pipeline`, `rag-chat`, `api-gateway`, `market-data`, `intelligence-migrations`
- **Libs affected**: `libs/messaging` (rdkafka config), `libs/prompts` (intent), `libs/tools` (manifest)
- **Frontend affected**: minimal — only `direction` field consumption (F-KG-103)
- **Infra affected**: `infra/compose/docker-compose.yml` (restart policies, depends_on, APP_ENV)
- **Total sub-plans**: 7
- **Total waves**: 24
- **Total tasks**: ~96
- **Estimated effort**: 9-12 engineer-days (one engineer); 5-7 days with two engineers running parallel sub-plans

## Sub-Plan Index

| ID | Title | Waves | Tasks | Depends on | Critical-path? |
|---|---|---|---|---|---|
| **A** | Infrastructure Hardening | 3 | 10 | none | ✓ blocks everything |
| **B** | Knowledge Graph Persistence | 4 | 16 | A-1 | ✓ |
| **C** | NLP Pipeline Routing & Enrichment | 4 | 14 | A-1 | parallel with B |
| **D** | KG Refresh Workers | 3 | 11 | B-1, B-2 | parallel with C |
| **E** | RAG Agent Quality | 5 | 19 | none (independent code) | parallel with B/C/D |
| **F** | Migration / Schema-Drift Fixes | 2 | 7 | A-1 | parallel with B/C |
| **G** | Validation Test Suite | 3 | 19 | A-F all done | gate before merge |

## Dependency Graph

```
A (Infrastructure) ──┬─→ B (KG Persistence) ──→ D (KG Refresh)
                     ├─→ C (NLP) ────────────────────────────────┐
                     └─→ F (Migration drift) ───────────────────┐│
                                                                ▼▼
E (RAG Agent) ──────────────────────────────────────────────→ G (Validation)
```

Execution order: **A → (B || C || E || F) → D → G**. Sub-plans B, C, E, F can be parallelized after A-1 lands.

## Critical Path

A-1 (`docker-compose.yml` restart policies + healthchecks) → B-1 (AGE label bootstrap + watermark reset) → D-1 (path-insight worker verification) → G-1 (data quality SLO tests).

## Pre-Prod Simplifications

Because prod has not launched, the following are **out of scope**:
- ❌ Backfill scripts for the 12,689 path_insights, 3,475 definition embeddings, 1,782 missing descriptions
- ❌ DLQ replay jobs for 93 + 924 + 1,218 dead-lettered articles + 800 dead-lettered predictions
- ❌ Migration `UPDATE ... WHERE confidence IS NULL` step (we can drop relations table contents instead)
- ❌ Tenant_id retroactive population for 51,761 mentions
- ❌ Outbox event replay
- ❌ AGE incremental backfill (a full resync via watermark DEL is fine)

Each remediation produces *forward-correct* writes; legacy bad data can be wiped via `TRUNCATE` or container/volume reset before launch.

## Coding Rules (all waves)

- **R10 / R11 / R12** — UUIDv7, UTC, structlog (mandatory)
- **R25** — every use case must import only ABC ports, never infrastructure classes
- **R27** — read-only use cases use `ReadOnlyUnitOfWork`/`ReadUoWDep`; writes use `UnitOfWork`/`UoWDep`
- **R8** — DB+Kafka dual writes via outbox (`libs/messaging`)
- **R19** — never delete, skip, or weaken a test to make a suite pass
- **R32** — Alembic numbers from filesystem HEAD only (never assumed)

## Sub-Plans

(Each sub-plan with full wave + task detail is in the sections below.)

---

> The waves and tasks below are written in execution order. Each task lists its `depends_on`, exact target files, PRD/audit reference, and acceptance criteria. An agent picking up `/implement PLAN-0093 Wave X-N` should not need to make any design decisions — all decisions trace back to the QA report and this plan.

---

## Sub-Plan A — Infrastructure Hardening

**Goal**: make the local platform survive a host reboot or any dependency restart without manual intervention; eliminate the "silent consumer freeze" failure mode.

**Waves**: 3 | **Tasks**: 10 | **Estimated**: 1.5 engineer-days

### Wave A-1: docker-compose restart + dependency policies

**Goal**: every long-running container restarts on host events; every worker waits for its dependencies to be healthy before starting.
**Depends on**: none
**Architecture layer**: infrastructure
**Estimated**: 3 hours

#### Task T-A-1-01: Add `restart: unless-stopped` to ollama, schema-registry, market-data

**Type**: config
**depends_on**: none
**blocks**: T-A-1-02, T-A-1-03
**Target files**:
- `infra/compose/docker-compose.yml` (or wherever the compose file lives — verify via `find infra -name "docker-compose*.yml"`)
**Audit reference**: F-LOG-INFRA-001 / F-LOG-001

**What to build**: add `restart: unless-stopped` to the three dependency service blocks that today have no restart policy. These exited at the 21:40 Docker event and stayed down for 50 minutes, dragging 21 Kafka consumers + 3 workers into failure.

**Logic & Behavior**:
- Locate the `ollama:`, `schema-registry:`, and `market-data:` service blocks.
- Add `restart: unless-stopped` to each (same value used by every other service in the file).
- Do NOT use `restart: always` — that would prevent a developer `docker stop` from sticking.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `tests/infra/test_compose_restart_policy.py::test_critical_services_have_restart_policy` | every service in a critical-list (ollama, schema-registry, market-data, postgres, kafka, valkey) has `restart: unless-stopped` | unit |

**Acceptance criteria**:
- [ ] `docker compose config | grep -A1 "^  ollama:" | grep "unless-stopped"` matches
- [ ] Same for schema-registry and market-data
- [ ] Test passes

---

#### Task T-A-1-02: Add `depends_on: { service_healthy }` on path-insight + embedding-retry + unresolved-resolution workers

**Type**: config
**depends_on**: T-A-1-01
**blocks**: T-A-1-03
**Target files**: `infra/compose/docker-compose.yml`
**Audit reference**: F-LOG-002, F-REF-006, F-NPL-002

**What to build**: declare service-level dependencies so compose doesn't start retry workers until their backing services are healthy. Today these workers `sys.exit(1)` on first DB/Valkey call when the dep isn't up, triggering 60-second restart loops.

**Logic & Behavior**:
Add `depends_on` blocks to the following services (use `condition: service_healthy` for all):
- `knowledge-graph-path-insight-worker`: depends on `postgres`, `valkey`, `intelligence-migrations` (already), `ollama`
- `nlp-pipeline-embedding-retry-worker`: depends on `postgres`, `valkey`, `nlp-pipeline-migrate`, `ollama`
- `nlp-pipeline-unresolved-resolution-worker`: depends on `postgres`, `valkey`, `nlp-pipeline-migrate`, `ollama`

**Acceptance criteria**:
- [ ] `docker compose config` shows each worker's `depends_on` with `condition: service_healthy` on all 4 deps
- [ ] `docker compose stop postgres && docker compose start postgres` no longer triggers restart-loop on these 3 workers (workers stay paused until postgres healthcheck passes)

---

#### Task T-A-1-03: Add `APP_ENV=local` to every service env block; assert at boot

**Type**: config + impl
**depends_on**: T-A-1-01
**blocks**: T-G-2-04 (security test)
**Target files**:
- `infra/compose/docker-compose.yml`
- `services/rag-chat/src/rag_chat/api/app.py` (or wherever lifespan/startup lives)
- `libs/observability/src/observability/startup_assert.py` **(NEW — created in this plan)**
**Audit reference**: F-LOG-JWT-001 / F-LOG-005

**What to build**:
1. Add `APP_ENV=local` to every service block in compose (not just rag-chat).
2. Create a shared helper `assert_app_env_or_die()` in `libs/observability/startup_assert.py` that:
   - Reads `APP_ENV` from settings
   - If unset AND `internal_jwt_skip_verification=True`, raises `RuntimeError` with the message `"BLOCKING SECURITY: APP_ENV unset and JWT verification disabled — refusing to start"`
   - Logs critical-level `startup_security_check_failed` before the raise
3. Call the helper from every service's FastAPI `lifespan` BEFORE the app starts accepting requests.

**Acceptance criteria**:
- [ ] `docker compose config | grep APP_ENV | wc -l` ≥ 10 (one per service)
- [ ] Removing `APP_ENV` from rag-chat env and running `docker compose up rag-chat` → container exits with non-zero AND logs `startup_security_check_failed`
- [ ] Test `tests/unit/test_startup_assert.py::test_app_env_unset_with_skip_verification_raises` passes

#### Pre-read
- `infra/compose/docker-compose.yml`
- `services/rag-chat/src/rag_chat/api/app.py`
- `libs/observability/src/observability/__init__.py`

#### Validation Gate
- [ ] `docker compose config --quiet` parses cleanly
- [ ] `ruff check libs/observability services/rag-chat` passes
- [ ] mypy passes on both
- [ ] New test `tests/unit/test_startup_assert.py` passes
- [ ] No existing tests broken

#### Architecture Compliance
- [ ] R25 — `assert_app_env_or_die` is a library helper, no infra deps
- [ ] R12 — uses `structlog` for the security log
- [ ] R32 — no Alembic changes in this wave

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| existing `lifespan` callers in every service | new helper call appended | Patch every `lifespan` function — see `services/*/src/*/api/app.py` |

#### Regression Guardrails
- **BP-005** (config drift): every service must have parity on `APP_ENV` — the test in T-A-1-03 enforces this.
- **HR-005** (secrets-in-code): the `internal_jwt_skip_verification=True` default is a known footgun; this fix wraps it.

---

### Wave A-2: rdkafka DNS TTL + Kafka client resilience

**Goal**: prevent the "21 consumers silently stuck on stale Kafka IP" failure mode after a Kafka restart.
**Depends on**: A-1
**Architecture layer**: shared library
**Estimated**: 4 hours

#### Task T-A-2-01: Set `broker.address.ttl=30000` + `broker.address.family=v4` in messaging lib

**Type**: impl
**depends_on**: none
**blocks**: T-A-2-02
**Target files**:
- `libs/messaging/src/messaging/kafka_config.py` (verify path via `find libs/messaging -name "*.py" | xargs grep -l "rdkafka\|bootstrap.servers"`)
**Audit reference**: F-LOG-003

**What to build**: every Kafka producer/consumer constructor in `libs/messaging` must pass these librdkafka config values:
```python
{
    "broker.address.ttl": 30000,        # ms — re-resolve DNS every 30s (default 1000 is buggy)
    "broker.address.family": "v4",      # force IPv4; jdosc gives mixed results otherwise
    # ... existing config ...
}
```

**Logic & Behavior**:
- Locate every `Producer({...})` and `Consumer({...})` constructor in `libs/messaging`.
- Inject the two keys into the config dict at construction time (or add to a `_BASE_RDKAFKA_CONFIG` constant that's spread into all consumers/producers).
- Both keys go BEFORE user-provided config so user can override if needed.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `libs/messaging/tests/unit/test_kafka_config.py::test_broker_address_ttl_is_30s` | every constructed config has `broker.address.ttl == 30000` | unit |
| `libs/messaging/tests/unit/test_kafka_config.py::test_broker_address_family_v4` | every constructed config has `broker.address.family == "v4"` | unit |

**Acceptance criteria**:
- [ ] All `BaseKafkaConsumer` + `BaseKafkaProducer` configs carry the two new keys
- [ ] Tests pass
- [ ] No service-side changes required (consumers/producers inherit the new defaults)

---

#### Task T-A-2-02: Add a `kafka_connectivity_probe` background task to `BaseKafkaConsumer`

**Type**: impl
**depends_on**: T-A-2-01
**blocks**: T-G-1-03
**Target files**:
- `libs/messaging/src/messaging/consumer_base.py` (verify via `git grep -l "class BaseKafkaConsumer"`)
**Audit reference**: F-LOG-003

**What to build**: an asyncio background task that runs every 60s inside `BaseKafkaConsumer.run()`:
- Calls `consumer.list_topics(timeout=5)` to probe the broker
- If 3 consecutive probes fail, logs `kafka_unreachable_for_5min` at CRITICAL level and **exits the process** with code 2 (lets compose's `restart: unless-stopped` give it a fresh DNS lookup)
- On success, resets the failure counter

**Logic & Behavior**:
- Start the probe task inside the consumer's main `async def run()` loop using `asyncio.create_task()`
- Cancel the task in `finally` to avoid leak
- Probe failures must NOT bubble up — they only cause exit after 3 consecutive misses

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_probe_exits_after_3_failures` | mocked `list_topics` raising 3 times → `sys.exit(2)` called | unit |
| `test_probe_resets_counter_on_success` | failure → success → 2 more failures → no exit | unit |
| `test_probe_does_not_block_consume_loop` | consumer continues processing while probe runs | unit |

**Acceptance criteria**:
- [ ] All 3 tests pass
- [ ] `consumer.run()` integration test still passes (consumer still consumes events when broker is up)

---

#### Task T-A-2-03: Add per-consumer `kafka_consumer_messages_consumed_total` metric

**Type**: impl
**depends_on**: T-A-2-02
**blocks**: T-G-1-03
**Target files**: `libs/messaging/src/messaging/consumer_base.py`, `libs/observability/src/observability/metrics.py`
**Audit reference**: F-LOG-003 (silent freeze visibility)

**What to build**: Prometheus counter incremented on every successful message processed:
```python
KAFKA_CONSUMER_MESSAGES = Counter(
    "kafka_consumer_messages_consumed_total",
    "Total Kafka messages consumed by this client",
    ["service", "topic", "consumer_group"],
)
```
Plus a Grafana alert rule (in `infra/grafana/alerts/`) that fires `KafkaConsumerStalled` when `rate(kafka_consumer_messages_consumed_total[5m]) == 0 AND kafka_topic_size{topic=~"<the topic>"} > 0`.

**Acceptance criteria**:
- [ ] Metric registered and exposed on `/metrics` endpoint
- [ ] Alert rule file exists in `infra/grafana/alerts/kafka_stalled.yml`
- [ ] Integration test: consume 1 message → counter == 1

#### Pre-read
- `libs/messaging/src/messaging/consumer_base.py`
- `libs/messaging/src/messaging/kafka_config.py`
- `libs/observability/src/observability/metrics.py`

#### Validation Gate
- [ ] `ruff check libs/messaging libs/observability` passes
- [ ] `mypy libs/messaging libs/observability` passes
- [ ] 6 new unit tests pass
- [ ] Existing consumer integration tests pass
- [ ] No service requires re-wiring (library-only change)

#### Architecture Compliance
- [ ] R25 — library change only, no infra coupling
- [ ] R12 — structlog for the unreachable log
- [ ] R32 — no migrations

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| no service code | library-only change; consumers pick up new config automatically | none |

#### Regression Guardrails
- **BP-001** (Kafka offset commit): the probe must not interfere with offset commits — verified by `test_probe_does_not_block_consume_loop`
- **BP-017** (consumer rebalance): the probe is purely read-only (`list_topics`), no rebalance impact
- **HR-031** (silent failure pattern): this wave's whole point — make the silent freeze visible

---

### Wave A-3: Worker startup retry decorator

**Goal**: any worker that crashes on transient DB/Valkey/HTTP startup blip must retry with backoff before `sys.exit(1)`.
**Depends on**: A-1
**Architecture layer**: shared library
**Estimated**: 3 hours

#### Task T-A-3-01: Create `@retry_on_startup` decorator in `libs/common`

**Type**: impl
**depends_on**: none
**blocks**: T-A-3-02, T-A-3-03, T-A-3-04
**Target files**:
- `libs/common/src/common/retry.py` **(NEW — created in this plan)**
**Audit reference**: F-NPL-002, F-REF-009

**What to build**: a decorator that wraps an async function and retries it on a configurable set of exception types with exponential backoff:
```python
def retry_on_startup(
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 5.0,
    retry_on: tuple[type[BaseException], ...] = (
        socket.gaierror,
        ConnectionRefusedError,
        OSError,            # asyncpg wraps gaierror as OSError sometimes
        asyncio.TimeoutError,
    ),
) -> Callable[[F], F]: ...
```
- Logs each retry at WARNING with attempt count and remaining attempts
- Logs final failure at CRITICAL and re-raises (so process exits cleanly under compose's restart policy)
- Uses `common.time.utc_now()` for any timestamps

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_retries_on_gaierror` | function raising gaierror twice then succeeding returns success | unit |
| `test_exhausts_then_raises` | 4 raises → final raise after 3 attempts | unit |
| `test_does_not_retry_on_unexpected_exception` | `ValueError` propagates immediately | unit |
| `test_backoff_doubles_each_attempt` | attempt 1: 5s, attempt 2: 10s, attempt 3: 20s (verify via mocked sleep) | unit |

**Acceptance criteria**:
- [ ] Decorator importable as `from common.retry import retry_on_startup`
- [ ] All 4 tests pass

---

#### Task T-A-3-02: Apply `@retry_on_startup` to `embedding_retry_worker_main.py`

**Type**: impl
**depends_on**: T-A-3-01
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/workers/embedding_retry_worker_main.py`
**Audit reference**: F-NPL-002 part 1

**What to build**: wrap the startup `count_abandoned()` call (line 84-86) with the decorator. Before:
```python
async with nlp_sf() as session:
    repo = EmbeddingPendingRepository(session)
    abandoned = await repo.count_abandoned(max_retries=max_retries)
```
After:
```python
@retry_on_startup()
async def _count_initial_abandoned() -> int:
    async with nlp_sf() as session:
        repo = EmbeddingPendingRepository(session)
        return await repo.count_abandoned(max_retries=max_retries)

abandoned = await _count_initial_abandoned()
```

**Acceptance criteria**:
- [ ] After applying, simulating postgres-down at startup → worker logs 3 WARN retries then exits with CRITICAL log (instead of crash-looping every 60s)
- [ ] Existing worker startup integration test still passes

---

#### Task T-A-3-03: Apply `@retry_on_startup` to `unresolved_resolution_worker_main.py`

**Type**: impl
**depends_on**: T-A-3-01
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/workers/unresolved_resolution_worker_main.py`
**Audit reference**: F-NPL-002 part 2

**What to build**: same pattern as T-A-3-02 — wrap the unguarded `await worker.recover_stale_escalated()` startup call (line 83) with `@retry_on_startup()`.

**Acceptance criteria**:
- [ ] Same as T-A-3-02 for this worker

---

#### Task T-A-3-04: Apply `@retry_on_startup` to `path_insight_worker_main.py`

**Type**: impl
**depends_on**: T-A-3-01
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker_main.py`
**Audit reference**: F-KG-102, F-REF-006

**What to build**: wrap `_build_factories(...)` and the first `worker.run_loop()` claim with `@retry_on_startup()`.

**Acceptance criteria**:
- [ ] Same as T-A-3-02 for this worker
- [ ] `docker logs worldview-knowledge-graph-path-insight-worker-1` after a postgres restart shows max 3 retry logs in a 30s window, not the previous 60s/restart loop

#### Pre-read
- `libs/common/src/common/__init__.py`
- `services/nlp-pipeline/src/nlp_pipeline/workers/embedding_retry_worker_main.py`
- `services/nlp-pipeline/src/nlp_pipeline/workers/unresolved_resolution_worker_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker_main.py`

#### Validation Gate
- [ ] `ruff check libs/common services/nlp-pipeline services/knowledge-graph` passes
- [ ] `mypy` passes on all three packages
- [ ] 4 new unit tests pass (decorator)
- [ ] Integration test: stop postgres → start 3 workers → workers retry and only exit after 3 attempts (manual or scripted)

#### Architecture Compliance
- [ ] R25 — decorator in `libs/common`, used by workers (not by use cases — workers are infrastructure-level)
- [ ] R12 — structlog logging inside decorator
- [ ] R32 — no migrations

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| 3 worker `_main.py` files | startup call wrapped in nested function | inline change — see T-A-3-02/03/04 |

#### Regression Guardrails
- **BP-403** (resource leak on shutdown): the decorator must not leave background tasks dangling on exhaustion — verified by `test_exhausts_then_raises`
- **HR-031** (silent failure): retries are WARN, final exhaustion is CRITICAL — visible in logs

---

## Sub-Plan B — Knowledge Graph Persistence

**Goal**: eliminate the BLOCKING data-corruption findings — AGE missing 70% of relations and 100% of events, 60% NULL confidence, orphan FKs, missing macro sentinel.

**Waves**: 4 | **Tasks**: 16 | **Estimated**: 2.5 engineer-days

### Wave B-1: AGE label bootstrap + watermark per-phase

**Goal**: AGE has `TemporalEvent` vlabel + `EVENT_EXPOSES` elabel; a failure in one sync phase doesn't poison the others.
**Depends on**: A-1 (so postgres is healthchecked)
**Architecture layer**: infrastructure
**Estimated**: 5 hours

#### Task T-B-1-01: Add AGE label bootstrap to age_sync_worker startup

**Type**: impl
**depends_on**: none
**blocks**: T-B-1-02, T-B-1-03, T-B-1-04
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`
**Audit reference**: F-KG-PERSIST-001 / F-REF-001

**What to build**: a new private method `async def _bootstrap_age_labels(session)` that runs ONCE on worker startup BEFORE any MERGE attempt:
```python
async def _bootstrap_age_labels(self, session: AsyncSession) -> None:
    """Create all vlabels and elabels used by the sync worker.

    AGE requires labels to exist before MERGE can target them.  Today the
    TemporalEvent vlabel and EVENT_EXPOSES elabel were never created;
    every sync attempt raises ProgrammingError and is silently swallowed
    by the outer try-except, leaving 0 events in AGE.
    """
    statements = [
        # Vertex labels — entity already exists; ensure all needed types
        "SELECT create_vlabel('worldview_graph', 'entity')",
        "SELECT create_vlabel('worldview_graph', 'TemporalEvent')",
        # Edge labels — every value in _VALID_EDGE_LABELS + EVENT_EXPOSES
        *[f"SELECT create_elabel('worldview_graph', '{lbl}')" for lbl in _VALID_EDGE_LABELS],
        "SELECT create_elabel('worldview_graph', 'EVENT_EXPOSES')",
    ]
    await self._setup_age_session(session)
    for stmt in statements:
        try:
            await session.execute(text(stmt))
        except ProgrammingError as exc:
            # "label already exists" — desired idempotency; swallow
            if "already exists" not in str(exc).lower():
                raise
    await session.commit()
```
Call this from the worker's main `run()` loop BEFORE the first sync iteration.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_bootstrap_creates_temporal_event_vlabel` | calls bootstrap on empty graph → `ag_label` table has `TemporalEvent` row | integration |
| `test_bootstrap_idempotent` | calls bootstrap twice → no error, no duplicate labels | integration |
| `test_bootstrap_creates_all_lever4_predicates` | post-bootstrap, every `_VALID_EDGE_LABELS` value exists as an elabel | integration |

**Acceptance criteria**:
- [ ] `_bootstrap_age_labels` is called exactly once per worker process startup
- [ ] All 3 integration tests pass
- [ ] After deploy, `psql ... -c "SELECT name FROM ag_catalog.ag_label WHERE graph = (SELECT graphid FROM ag_catalog.ag_graph WHERE name='worldview_graph')"` returns ≥ 30 rows

---

#### Task T-B-1-02: Split `age_sync` into per-phase try-except + per-phase watermark

**Type**: impl
**depends_on**: T-B-1-01
**blocks**: T-B-1-04
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`
**Audit reference**: F-REF-001, F-REF-002, F-REF-007

**What to build**: change the single global `s7:age:sync:watermark` Valkey key to three independent keys:
- `s7:age:sync:watermark:entities`
- `s7:age:sync:watermark:relations`
- `s7:age:sync:watermark:temporal_events`

Each phase reads its own watermark, syncs, advances its own watermark on success. The outer try-except is removed; each phase has its own. A failure in temporal_events no longer skips the entities/relations watermark advance.

**Logic & Behavior**:
- Each phase wrapped in `try/except ProgrammingError` (logs `age_sync_phase_failed` with the phase name, does NOT advance that phase's watermark)
- `except Exception` (non-Programming) is re-raised so the worker exits and compose restarts
- Add a structured log `age_sync_phase_complete` per phase with `synced_count` and `new_watermark`

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_temporal_event_failure_does_not_block_relation_watermark` | mock events phase raises ProgrammingError → relations watermark still advances | unit |
| `test_per_phase_watermark_keys_are_distinct` | Valkey shows 3 keys after a successful run | integration |
| `test_phase_failure_logs_with_phase_name` | log emitted on failure has `phase` field | unit |

**Acceptance criteria**:
- [ ] After 1 run with the temporal-events query forced to fail, entities + relations watermarks have both advanced
- [ ] Worker exits on non-ProgrammingError (verified by mocking `OperationalError`)
- [ ] All 3 tests pass

---

#### Task T-B-1-03: Add `age_sync_phase_stalled` warning when DB has rows newer than watermark for >24h

**Type**: impl
**depends_on**: T-B-1-02
**blocks**: T-G-1-01
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`
**Audit reference**: F-REF-010

**What to build**: after each phase completes, if `synced_count == 0` AND there exist rows in the source table where `updated_at > watermark`, increment a Prometheus counter `age_sync_phase_stalled_total{phase=...}` and log WARNING `age_sync_phase_stalled` with the phase name + lag in seconds.

**Acceptance criteria**:
- [ ] Counter exposed on `/metrics`
- [ ] Test: insert a relation, advance watermark past it manually, run sync → counter increments

---

#### Task T-B-1-04: One-off Valkey watermark reset documented in plan + helper script

**Type**: docs + impl
**depends_on**: T-B-1-01, T-B-1-02
**blocks**: T-D-1-01
**Target files**:
- `scripts/ops/reset_age_watermark.sh` **(NEW — created in this plan)**
- `docs/services/knowledge-graph.md` (add a "Recovering from AGE undercount" section)

**What to build**: a one-line ops script + doc that explains when/how to reset:
```bash
#!/usr/bin/env bash
# Resets all 3 AGE sync watermarks to epoch — next worker cycle does a full resync.
# AGE MERGE is idempotent so re-running over already-synced rows is safe.
docker exec worldview-valkey-1 valkey-cli DEL \
  s7:age:sync:watermark \
  s7:age:sync:watermark:entities \
  s7:age:sync:watermark:relations \
  s7:age:sync:watermark:temporal_events
```

**Acceptance criteria**:
- [ ] Script exists and is executable (`chmod +x`)
- [ ] Doc section explains: when to run it (after label bootstrap or schema change), what happens (full resync), risk (none — idempotent)

#### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py` (590 lines)
- `services/intelligence-migrations/alembic/versions/0029_age_lever4_labels.py` (or wherever the elabel migration lives)

#### Validation Gate
- [ ] `ruff check services/knowledge-graph` passes
- [ ] `mypy services/knowledge-graph` passes
- [ ] 6 new tests pass (3 integration + 3 unit)
- [ ] `docker exec worldview-valkey-1 valkey-cli DEL s7:age:sync:watermark*` then restart kg-scheduler → AGE has 14,762 events + 7,884 edges within 10 minutes
- [ ] No regression in existing 29 age_sync tests

#### Architecture Compliance
- [ ] R25 — `_bootstrap_age_labels` is a private method on the infrastructure worker; no use-case coupling
- [ ] R12 — all new logs use structlog
- [ ] R32 — no new migration needed; the AGE label DDL is bootstrapped at runtime

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/knowledge-graph/tests/unit/infrastructure/workers/test_age_sync_worker.py` | watermark key changed from single → 3 | update test fixtures to set/read the 3 new keys |

#### Regression Guardrails
- **BP-539** (NULL confidence in sync filter) — already fixed; verify the fix still in place after the per-phase split
- **BP-385** (self-loop guard) — verify still in `graph_write.py`
- **BP-520, BP-521** (direction normalization) — verify still in place
- **BP-NEW-1** (AGE label bootstrap) — this wave creates the pattern; add to BUG_PATTERNS.md as part of this wave

---

### Wave B-2: Relations confidence NOT NULL + FK constraints + macro sentinel seed

**Goal**: every relation row has a valid confidence value and points to real entity IDs. No more orphan FKs.
**Depends on**: A-1 (postgres healthchecked)
**Architecture layer**: schema + infrastructure
**Estimated**: 6 hours

#### Task T-B-2-01: Migration 0044 — seed macro sentinel + entity placeholders

**Type**: schema
**depends_on**: none
**blocks**: T-B-2-02
**Target files**:
- `services/intelligence-migrations/alembic/versions/0044_seed_kg_system_entities.py` **(NEW — created in this plan; current HEAD verified as 0043)**
**Audit reference**: F-DB-012, F-KG-PERSIST-002

**What to build**: an Alembic upgrade migration that inserts a small set of system entities into `canonical_entities`:
- `11111111-0004-7000-8000-000000000001` — "Macro Sentinel" (entity_type=`macro_indicator`, used as fallback when extraction cannot resolve subject AND object)
- `11111111-0004-7000-8000-000000000002` — "Unknown Person" (entity_type=`person`, fallback)
- `11111111-0004-7000-8000-000000000003` — "Unknown Organization" (entity_type=`organization`, fallback)
- `11111111-0004-7000-8000-000000000004` — "Unknown Place" (entity_type=`place`, fallback)
- `11111111-0004-7000-8000-000000000005` — "Unknown Product" (entity_type=`product`, fallback)

Each row has `is_system=true` (NEW column — add via this migration), `description='System placeholder used when extraction cannot resolve a real entity'`, `created_at=utc_now()`, `enriched_at=utc_now()` (so the sweep doesn't try to enrich them).

Downgrade: DELETE WHERE is_system=true.

**Logic & Behavior**:
- Migration uses `op.execute(text(...))` not raw connection
- Migration is idempotent (`INSERT ... ON CONFLICT (entity_id) DO NOTHING`)
- Add CHECK constraint `relations.subject_entity_id != relations.object_entity_id OR subject_entity_id IN (<system entity IDs>)` — system entities are allowed to self-loop; real entities are not

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_migration_0044_upgrade_inserts_5_system_entities` | post-upgrade, `SELECT count(*) FROM canonical_entities WHERE is_system=true` == 5 | integration |
| `test_migration_0044_idempotent` | second upgrade does not duplicate | integration |
| `test_migration_0044_downgrade_removes_them` | downgrade removes all is_system rows | integration |

**Acceptance criteria**:
- [ ] `alembic upgrade head` from 0043 → 0044 succeeds in a fresh container
- [ ] Tests pass

---

#### Task T-B-2-02: Migration 0045 — add FK constraint to relations.subject_entity_id + object_entity_id

**Type**: schema
**depends_on**: T-B-2-01
**blocks**: T-B-2-03
**Target files**:
- `services/intelligence-migrations/alembic/versions/0045_add_relations_fk_constraints.py` **(NEW)**
**Audit reference**: F-KG-PERSIST-002 / F-DB-001

**What to build**:
```python
def upgrade():
    # Truncate first (pre-prod, no data preservation needed)
    op.execute("TRUNCATE TABLE relations CASCADE")
    op.execute("TRUNCATE TABLE relation_evidence_raw CASCADE")
    op.execute("TRUNCATE TABLE relation_summaries CASCADE")
    op.execute("TRUNCATE TABLE relation_contradiction_links CASCADE")
    # Now add the FKs
    op.create_foreign_key(
        "fk_relations_subject_entity",
        "relations", "canonical_entities",
        ["subject_entity_id"], ["entity_id"],
        deferrable=True, initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_relations_object_entity",
        "relations", "canonical_entities",
        ["object_entity_id"], ["entity_id"],
        deferrable=True, initially="DEFERRED",
    )

def downgrade():
    op.drop_constraint("fk_relations_subject_entity", "relations", type_="foreignkey")
    op.drop_constraint("fk_relations_object_entity", "relations", type_="foreignkey")
```

**Logic & Behavior**:
- TRUNCATE is allowed because pre-prod (per plan preamble)
- DEFERRABLE INITIALLY DEFERRED — outbox writes can insert entity + relation in the same transaction
- After migration, any new relation pointing to a non-existent entity raises `ForeignKeyViolation` at commit time

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_migration_0045_blocks_orphan_relation_write` | INSERT relation with bogus entity_id outside same transaction → ForeignKeyViolation | integration |
| `test_migration_0045_allows_same_transaction_entity_plus_relation` | insert entity + relation in same tx → commits | integration |

**Acceptance criteria**:
- [ ] Migration runs forward and back cleanly
- [ ] Both tests pass

---

#### Task T-B-2-03: Migration 0046 — relations.confidence NOT NULL DEFAULT base_confidence

**Type**: schema
**depends_on**: T-B-2-02
**blocks**: T-B-2-04
**Target files**:
- `services/intelligence-migrations/alembic/versions/0046_relations_confidence_not_null.py` **(NEW)**
**Audit reference**: F-KG-PERSIST-002 / F-DB-001

**What to build**:
```python
def upgrade():
    # Pre-prod: tables already truncated by 0045, so no UPDATE backfill needed
    op.alter_column(
        "relations", "confidence",
        existing_type=sa.Float(),
        nullable=False,
        server_default=sa.text("base_confidence"),
    )
    # Also drop the now-redundant confidence_stale column — its semantic is unnecessary
    # because every write must produce a non-NULL confidence
    op.drop_column("relations", "confidence_stale")
```

**Acceptance criteria**:
- [ ] After migration, attempting `INSERT INTO relations (..., confidence) VALUES (..., NULL)` raises NOT NULL violation
- [ ] Inserting without specifying confidence → row gets `base_confidence` value
- [ ] Test confirms BP-539 logic in `age_sync_worker.py` still works (confidence is now never NULL, so the `OR confidence IS NULL` branch is dead but harmless)

---

#### Task T-B-2-04: Update relation writer to always set confidence

**Type**: impl
**depends_on**: T-B-2-03
**blocks**: T-B-2-05
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py` (find the relation insert path)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/materialize_graph.py` (or wherever relations get written)
**Audit reference**: F-KG-PERSIST-002

**What to build**: every code path that inserts a row into `relations` must compute or pass a `confidence` value. The default `base_confidence` from DDL is the fallback; the writer should pass an explicit value derived from extraction confidence (typically `extraction_confidence * source_trust_weight`).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_relation_writer_sets_confidence_from_extraction` | insert path produces row with confidence > 0 | unit |
| `test_relation_writer_falls_back_to_base_when_extraction_missing` | when extraction_confidence is None, row uses base_confidence default | unit |

**Acceptance criteria**:
- [ ] After 1 hour of ingestion, no relations row has NULL confidence
- [ ] Tests pass

---

#### Task T-B-2-05: Update extraction fallback to use macro sentinel when both subject + object are unresolvable

**Type**: impl
**depends_on**: T-B-2-01, T-B-2-04
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py`
**Audit reference**: F-DB-012

**What to build**: locate the current fallback path (where the worker tries to insert a self-loop on `11111111-0004-7000-8000-000000000001`). Change the logic to:
- Drop the relation entirely if BOTH subject and object are unresolvable (no signal)
- OR if only one is unresolvable, use the appropriate "Unknown <Type>" sentinel
- Self-loops on real entities are rejected at the CHECK constraint level (added in T-B-2-01); self-loops on sentinels are allowed (intentional placeholder)

**Acceptance criteria**:
- [ ] No new self-loops in production data
- [ ] Unit test: extraction with both refs unresolvable → no DB write, log `relation_dropped_unresolvable`

#### Pre-read
- `services/intelligence-migrations/alembic/versions/0043_seed_entity_enrichment_bootstrap.py` (current HEAD)
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py`
- `services/knowledge-graph/src/knowledge_graph/domain/relation.py`

#### Validation Gate
- [ ] 3 new migrations apply cleanly on fresh DB and on a stack with prior data (after TRUNCATE)
- [ ] `ruff check services/intelligence-migrations services/knowledge-graph` passes
- [ ] `mypy services/knowledge-graph` passes
- [ ] 9 new tests pass (3 per migration + 2 writer)
- [ ] No regression in existing KG unit tests

#### Architecture Compliance
- [ ] R32 — migrations 0044/0045/0046 are based on verified HEAD 0043
- [ ] R25 — writer code uses ports; the DDL change is infrastructure
- [ ] R8 — outbox pattern preserved (DEFERRED FK allows entity + relation in same tx)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py` | `confidence_stale` column dropped; query references it | remove `confidence_stale` from SELECT in `_sync_relations` |
| existing extraction tests | self-loop fallback removed | update test fixtures to not produce self-loops, or expect drop |

#### Regression Guardrails
- **BP-539** — verify the COALESCE in age_sync still works (now redundant but should not error)
- **BP-385** — self-loop guard now enforced at DDL level too
- **BP-007** (DDL safety): TRUNCATE is destructive — gated by pre-prod assumption documented at top of plan

---

### Wave B-3: relation_evidence_raw FK propagation (claim_id + chunk_id NOT NULL)

**Goal**: every evidence row links back to a real claim AND a real chunk — full provenance from relation to source paragraph.
**Depends on**: B-2 (so relations table is FK-clean)
**Architecture layer**: schema + infrastructure
**Estimated**: 4 hours

#### Task T-B-3-01: Migration 0047 — relation_evidence_raw.claim_id + chunk_id NOT NULL + FK

**Type**: schema
**depends_on**: none
**blocks**: T-B-3-02
**Target files**: `services/intelligence-migrations/alembic/versions/0047_evidence_raw_not_null_fks.py` **(NEW)**
**Audit reference**: F-DB-008

**What to build**:
```python
def upgrade():
    op.execute("TRUNCATE TABLE relation_evidence_raw CASCADE")  # pre-prod
    op.alter_column("relation_evidence_raw", "claim_id", nullable=False)
    op.alter_column("relation_evidence_raw", "chunk_id", nullable=False)
    op.create_foreign_key(
        "fk_evidence_raw_claim",
        "relation_evidence_raw", "claims",
        ["claim_id"], ["claim_id"],
        deferrable=True, initially="DEFERRED",
    )
    # chunk_id lives in nlp_db.chunks — cross-database FK not possible; add app-level check only
    # (Recommended index for joins:)
    op.create_index("ix_evidence_raw_chunk_id", "relation_evidence_raw", ["chunk_id"])
```

**Note**: cross-database FK is not enforceable at the DB level (chunk_id is in nlp_db, evidence is in intelligence_db). The app-level invariant is enforced by the writer in T-B-3-02.

**Acceptance criteria**:
- [ ] Migration runs cleanly
- [ ] Writing a NULL claim_id raises NOT NULL violation
- [ ] FK on claim_id catches orphan claims

---

#### Task T-B-3-02: Update enriched_consumer to propagate claim_id + chunk_id into every evidence row

**Type**: impl
**depends_on**: T-B-3-01
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py`, `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py`
**Audit reference**: F-DB-008

**What to build**: the enriched event envelope (from S6) already carries `doc_id`, `chunk_id`, and the claim text. The current writer in `materialize_graph()` inserts `relation_evidence_raw` but does NOT populate `claim_id` (because claims are inserted in a separate query). Fix:
1. Insert the claim first (via `_insert_claim` — already exists)
2. Capture the returned `claim_id`
3. Pass `claim_id` + `chunk_id` into the evidence insert

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_evidence_row_has_claim_id_and_chunk_id` | after consume, every row in evidence_raw has both set | integration |
| `test_app_level_chunk_id_validation` | writer rejects message with no chunk_id (raises before DB call) | unit |

**Acceptance criteria**:
- [ ] After 1 hour of ingestion, no evidence row has NULL claim_id or chunk_id
- [ ] Tests pass

---

#### Task T-B-3-03: Migration 0048 — entity_mentions.tenant_id NOT NULL

**Type**: schema
**depends_on**: none
**blocks**: T-B-3-04
**Target files**: `services/nlp-pipeline/alembic/versions/0020_entity_mentions_tenant_not_null.py` **(NEW — current HEAD verified as 0019)**
**Audit reference**: F-DB-010

**What to build**:
```python
def upgrade():
    op.execute("TRUNCATE TABLE entity_mentions CASCADE")  # pre-prod
    op.alter_column(
        "entity_mentions", "tenant_id",
        existing_type=postgresql.UUID(),
        nullable=False,
    )
    # Add index for tenant-filtered queries
    op.create_index("ix_entity_mentions_tenant", "entity_mentions", ["tenant_id"])
```

---

#### Task T-B-3-04: Wire tenant_id into entity_mentions writer in nlp-pipeline

**Type**: impl
**depends_on**: T-B-3-03
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/persist.py` (or wherever entity_mentions writes happen)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py`
**Audit reference**: F-DB-010

**What to build**: thread `tenant_id` (already on the article envelope) through the NER and write paths. Every `EntityMention(...)` constructor must require it.

**Acceptance criteria**:
- [ ] After 1 hour of ingestion, no entity_mentions row has NULL tenant_id
- [ ] Unit test: omitting tenant_id from constructor raises ValueError

#### Pre-read
- `services/intelligence-migrations/alembic/versions/0043_*.py`
- `services/nlp-pipeline/alembic/versions/0019_*.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/enriched_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/persist.py`

#### Validation Gate
- [ ] Migrations 0047 + 0020 apply cleanly
- [ ] ruff + mypy pass on KG + NLP
- [ ] 4 new tests pass
- [ ] After 1h ingestion, SELECT verifies zero NULL claim_id, chunk_id, tenant_id

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| existing NER tests | EntityMention now requires tenant_id | add tenant_id="00000000-0000-0000-0000-000000000001" to test constructors |
| existing evidence writer tests | claim_id/chunk_id now required | update fixtures |

#### Regression Guardrails
- **BP-008** (tenant leakage): the NOT NULL constraint enforces what was previously schema-lying
- **BP-007** (DDL safety): TRUNCATE allowed by pre-prod assumption

---

### Wave B-4: graph_query QW-3 — direction field + entity_summary helper

**Goal**: graph response includes `direction` field per edge so frontend can render correctly; entity summary block deduplicated.
**Depends on**: B-1
**Architecture layer**: application
**Estimated**: 2 hours

#### Task T-B-4-01: Add `direction` field to graph_query response

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/graph_query.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/get_entity_paths.py`
- `services/api-gateway/src/api_gateway/schemas/intelligence.py` (response model)
**Audit reference**: F-KG-103 (QW-3)

**What to build**: in `GetEntityRelationsUseCase.execute`, for every returned relation dict, set:
```python
r["direction"] = "outgoing" if r["subject_entity_id"] == entity_id else "incoming"
```
Mirror in `get_entity_paths.py`. Update the S9 Pydantic response model to include `direction: Literal["outgoing", "incoming"]`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_outgoing_relation_marked_outgoing` | entity is subject → direction == "outgoing" | unit |
| `test_incoming_relation_marked_incoming` | entity is object → direction == "incoming" | unit |
| `test_s9_response_schema_includes_direction` | API client receives the field | contract |

**Acceptance criteria**:
- [ ] All 3 tests pass
- [ ] Frontend renders edges with correct arrow direction (verified manually on InlineSelectionPanel)

---

#### Task T-B-4-02: Extract `_entity_summary()` shared helper

**Type**: refactor
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routes/intelligence.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/cypher.py`
- `libs/contracts/src/contracts/entity_summary.py` **(NEW)**
**Audit reference**: F-607 (from PLAN-0089 W2 follow-up)

**What to build**: move the duplicated entity-summary formatting code to a shared helper in `libs/contracts`. Both call sites import from there.

**Acceptance criteria**:
- [ ] Two former call sites now import the helper
- [ ] No behavior change (verified by existing tests)

#### Validation Gate
- [ ] ruff + mypy pass
- [ ] All 3 tests pass
- [ ] Existing routes still pass

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| Frontend `EdgeTooltipPanel.tsx` | new `direction` field arrives | update type definition + render arrow accordingly |

---

## Sub-Plan C — NLP Pipeline Routing & Enrichment

**Goal**: fix the 3-of-8 dead routing signals, the `gliner_mention_floor` enforcement gap, the empty `article_impact_windows`, the always-NULL `impact_score`, and the frozen `enrichment_attempts` counter.

**Waves**: 4 | **Tasks**: 14 | **Estimated**: 2.5 engineer-days

### Wave C-1: Routing signals — drop dead signals + rebalance weights

**Goal**: stop pretending we have 8 signals when 3 are permanently zero. Either fix or drop them.

**Depends on**: A-1
**Architecture layer**: application
**Estimated**: 4 hours

#### Task T-C-1-01: Drop watchlist_signal + novelty_score + price_impact_score from composite formula

**Type**: impl
**depends_on**: none
**blocks**: T-C-1-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
**Audit reference**: F-NPL-003, F-NPL-004, F-NPL-006, F-NPL-ROUTING-001

**Decision**: this plan does NOT implement the two-pass routing (route → resolve → re-route) because that's a substantial architecture change. Instead, drop the dead signals and re-weight the remaining 5 to sum to 1.0. A follow-up plan can add two-pass routing later.

**What to build**:
- Remove `watchlist_signal`, `novelty_score`, `price_impact_score` from `compute_routing_score()` function signature, body, and tests.
- Re-weight remaining signals (currently sums to 0.75 because the 3 dead signals had weights 0.10 + 0.15 + 0.10):
  - Pre-change weights (per PRD): document_type=0.30, source_trust=0.20, entity_count=0.15, recency=0.10
  - Post-change weights (sum to 1.0): document_type=0.40, source_trust=0.27, entity_count=0.20, recency=0.13
- Update `routing_tier_deep`/`routing_tier_standard` thresholds accordingly (the comment in config.py:158 about "effective max ~0.44" becomes obsolete)
- Add deprecation note in `routing.py` referencing this plan for the dropped signals

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_composite_score_sums_to_one_when_all_signals_max` | mock all signals → 1.0 | unit |
| `test_removed_signals_not_in_function_signature` | watchlist/novelty/price_impact not present | unit |
| `test_routing_tier_thresholds_updated` | new thresholds in config match new max-achievable score | unit |

**Acceptance criteria**:
- [ ] `compute_routing_score()` accepts 5 args (not 8)
- [ ] Composite score range is exactly [0.0, 1.0]
- [ ] Existing 5,919 routing decisions still readable; new rows reflect new formula
- [ ] PRD-0026 + `docs/services/nlp-pipeline.md` updated to reflect the change

---

#### Task T-C-1-02: Update PRD-0026 + nlp-pipeline service docs to document dropped signals

**Type**: docs
**depends_on**: T-C-1-01
**blocks**: none
**Target files**:
- `docs/specs/0026-news-intelligence-apis.md`
- `docs/services/nlp-pipeline.md`
- `services/nlp-pipeline/.claude-context.md`
**Audit reference**: F-NPL-003/004/006

**What to build**: a new section in each doc titled "Routing signal v2 (PLAN-0093)" listing the dropped signals, the rationale (cannot fire in single-pass arch), and the new weight distribution. Note that re-adding them requires implementing two-pass routing first.

**Acceptance criteria**:
- [ ] All 3 docs reference PLAN-0093 and the new weights

#### Validation Gate
- [ ] ruff + mypy pass
- [ ] 3 new tests pass; existing routing tests updated
- [ ] PRD-0026 reflects v2

#### Architecture Compliance
- [ ] R25 — routing is application-layer, no infra coupling
- [ ] R32 — no migration

---

### Wave C-2: gliner_mention_floor enforcement on entity_mentions table

**Goal**: stop persisting sub-floor mentions to `entity_mentions` (26% of all rows today). Only ≥ 0.6 mentions make it into the audited table.

**Depends on**: A-1
**Architecture layer**: application + infrastructure
**Estimated**: 3 hours

#### Task T-C-2-01: Add `min_persist_floor` setting + apply in entity_mentions writer

**Type**: impl
**depends_on**: none
**blocks**: T-C-2-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (add `min_persist_floor: float = 0.6`)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/persist.py` (filter before write)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py` (or wherever mentions are deduplicated)
**Audit reference**: F-NPL-005

**What to build**: introduce `Settings.min_persist_floor: float = 0.6` (env: `NLP_PIPELINE_MIN_PERSIST_FLOOR`). Before inserting into `entity_mentions`, filter out mentions with `score < min_persist_floor`. The `chunks.entity_mentions` JSONB cache (which already uses this floor) is unchanged; this just brings the table writer into parity.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_sub_floor_mentions_not_persisted` | mentions at score 0.5 → not in entity_mentions | unit |
| `test_floor_configurable_via_env` | env var override changes behavior | unit |
| `test_above_floor_mentions_persisted` | score 0.7 → row present | unit |

**Acceptance criteria**:
- [ ] After 1h ingestion, `SELECT count(*) FROM entity_mentions WHERE score < 0.6` == 0
- [ ] Tests pass

---

#### Task T-C-2-02: Drop sub-floor mentions from resolution cascade

**Type**: impl
**depends_on**: T-C-2-01
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/resolve_mentions.py` (or equivalent)
**Audit reference**: F-NPL-005 (downstream effect)

**What to build**: the resolution worker reads `entity_mentions`. Since T-C-2-01 ensures no sub-floor rows exist, the resolver's filter `WHERE score >= min_persist_floor` is now redundant but should be added for defense-in-depth.

**Acceptance criteria**:
- [ ] Resolver no longer issues LLM calls for sub-floor mentions

#### Validation Gate
- [ ] ruff + mypy pass
- [ ] 3 new tests pass
- [ ] After deploy + 1h, `mention_resolutions` row growth rate drops by ≥ 50% (because 26% of mentions used to consume 3.3 resolution attempts each)

---

### Wave C-3: impact_score writer + market-data symbol resolver

**Goal**: populate `document_source_metadata.impact_score` and `article_impact_windows`; fix the market-data API contract mismatch.

**Depends on**: A-1
**Architecture layer**: application + cross-service
**Estimated**: 5 hours

#### Task T-C-3-01: Investigate and document the market-data symbol resolver contract

**Type**: docs + investigation
**depends_on**: none
**blocks**: T-C-3-02
**Target files**:
- `docs/services/market-data.md`
- `services/market-data/src/market_data/api/routes/` (read all)
**Audit reference**: F-NPL-FUNDAMENTALS-001

**What to build** (Q2 decision 2026-05-23: agent investigates first): read every route in market-data, then `curl` each candidate endpoint against the live container with a known ticker (e.g. AAPL) to confirm what actually responds. Three possible outcomes — the agent must pick exactly one and document it:

| Outcome | Means | Next action (precondition for T-C-3-02) |
|---|---|---|
| **(A) Correct path found** | e.g. `GET /api/v1/instruments?symbol=AAPL` returns 200 with instrument_id | T-C-3-02 proceeds — uses the corrected path |
| **(B) No symbol resolver exists** | every candidate returns 404 | T-C-3-02 is BLOCKED — agent must propose a new market-data wave (precursor) that adds `GET /api/v1/instruments/by-symbol/{symbol}`, including the use case, repo query (`WHERE symbol = :symbol AND active = true`), test, and OpenAPI registration. Surface this as a blocker to the user before continuing. |
| **(C) Path exists but uses different arg shape** | e.g. `?ticker=AAPL` instead of `?symbol=AAPL` | T-C-3-02 proceeds with the corrected arg name; no new endpoint needed |

Whichever outcome wins, document it in `docs/services/market-data.md` with:
- Complete endpoint table (paths, query params, path params, response shapes, status codes)
- A "symbol resolution" subsection that explicitly states the chosen path + arg shape, and links back to PLAN-0093 T-C-3-01 for the audit history

**Acceptance criteria**:
- [ ] Live curl verification recorded in the doc (request + response captured)
- [ ] Exactly one of outcomes (A/B/C) is selected and explicit in the doc
- [ ] If outcome (B), a new precursor task `T-C-3-00` is added to this plan with full task spec for the new endpoint, and T-C-3-02 `depends_on` is updated to `T-C-3-00`
- [ ] `docs/services/market-data.md` has a complete endpoint table with paths, params, response shapes

---

#### Task T-C-3-02: Fix market-data symbol resolver path in PriceImpactLabellingWorker

**Type**: impl
**depends_on**: T-C-3-01
**blocks**: T-C-3-03
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
**Audit reference**: F-NPL-FUNDAMENTALS-001

**What to build**: update the URL template to use whatever was discovered in T-C-3-01. Add exponential backoff: after 3 consecutive 404s for the same ticker, mark the entity in a Valkey set `nlp:price_impact:unknown_tickers` with 7-day TTL and skip subsequent attempts until expiry.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_resolver_uses_correct_path` | mocked market-data → calls right URL | unit |
| `test_backoff_after_3_404s` | 3 calls all 404 → ticker added to skip set | unit |
| `test_skip_set_expires` | TTL respected | unit |

**Acceptance criteria**:
- [ ] After 1h, `article_impact_windows` has > 100 rows (for the top tickers)
- [ ] Logs show no more than 10 404s per ticker per day

---

#### Task T-C-3-03: Wire `impact_score` writer into ArticleRelevanceScoringWorker

**Type**: impl
**depends_on**: T-C-3-02
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py` (or similar)
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/score_relevance.py`
**Audit reference**: F-DB-IMPACT-SCORE-001 / F-NPL-008

**What to build**: when the worker computes article relevance, it also reads from `article_impact_windows` (populated by T-C-3-02) and writes `impact_score = MAX(abs(return_t0), abs(return_t1), ...)` to `document_source_metadata.impact_score`. The exact formula comes from PRD-0026 §6.5.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_impact_score_computed_from_windows` | mock impact_windows → impact_score == max abs return | unit |
| `test_impact_score_null_when_no_windows` | no windows row → impact_score stays NULL (don't write 0) | unit |

**Acceptance criteria**:
- [ ] After 24h ingestion, `SELECT count(*) FROM document_source_metadata WHERE impact_score IS NOT NULL` > 0
- [ ] PRD-0026 weighted display formula now uses all 3 components

#### Pre-read
- `docs/specs/0026-news-intelligence-apis.md`
- `services/market-data/src/market_data/api/routes/*.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`

#### Validation Gate
- [ ] ruff + mypy pass on both services
- [ ] 5 new tests pass
- [ ] After 24h, impact_score populated for ≥ 30% of docs
- [ ] No 404 storms in logs

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/api-gateway/src/api_gateway/routes/news.py` | display_relevance_score formula now sums all 3 components | already correct in formula; no change needed |

---

### Wave C-4: Atomic enrichment_attempts UPDATE + NULL-embedding refresh priority

**Goal**: the partial-index sweep actually advances; entities with NULL embeddings get re-tried first.

**Depends on**: A-1
**Architecture layer**: application
**Estimated**: 3 hours

#### Task T-C-4-01: Make enrichment_attempts UPDATE atomic with the worker claim

**Type**: impl
**depends_on**: none
**blocks**: T-C-4-02
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_worker.py` (or wherever the sweep happens)
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/enrich_entity.py`
**Audit reference**: F-DB-ENRICHMENT-001 / F-DB-005

**What to build**: when the worker claims an entity for enrichment, the SAME transaction must:
```sql
UPDATE canonical_entities
SET enrichment_attempts = enrichment_attempts + 1, last_enrichment_attempt_at = utc_now()
WHERE entity_id = :id AND enrichment_attempts < 3
RETURNING entity_id
```
If `RETURNING` returns nothing → another worker already claimed it OR attempts maxed out → skip.

After enrichment succeeds: `UPDATE canonical_entities SET enriched_at = utc_now(), description = :desc WHERE entity_id = :id`.
After enrichment fails: do nothing extra — `enrichment_attempts` was already incremented at claim time.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_claim_increments_attempts` | post-claim row has attempts=1 | integration |
| `test_concurrent_workers_only_one_claims` | 2 workers race → only 1 row updated, other claims new entity | integration |
| `test_failed_enrichment_still_counts_attempt` | exception during enrichment → attempts stays at incremented value | integration |
| `test_3rd_attempt_exhausts_entity` | after 3 attempts row is excluded from partial index | integration |

**Acceptance criteria**:
- [ ] After 24h, `SELECT count(*) FROM canonical_entities WHERE enrichment_attempts > 0` ≥ 100
- [ ] Partial index `ix_canonical_entities_enrichment_sweep` shrinks over time

---

#### Task T-C-4-02: Prioritize NULL-embedding rows in entity_embedding_state refresh

**Type**: impl
**depends_on**: none (parallel)
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/narrative_refresh.py`
**Audit reference**: F-REF-004, F-REF-005

**What to build**: change the worker's claim query from `ORDER BY next_refresh_at ASC` to `ORDER BY (embedding IS NULL) DESC, next_refresh_at ASC LIMIT :batch`. This forces stuck NULL-embedding rows to the front.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_null_embedding_claimed_before_stale_one` | row with NULL embedding + future next_refresh beats row with non-NULL + past next_refresh | integration |

**Acceptance criteria**:
- [ ] After 24h, NULL-embedding row count drops to < 5% across all 3 view types

---

#### Task T-C-4-03: Add fundamentals_ohlcv refresh support for non-equity entity types

**Type**: impl
**depends_on**: T-C-4-02
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/refresh_fundamentals.py`
**Audit reference**: F-REF-003, F-DB-005

**What to build**: today the worker schedules `fundamentals_ohlcv` rows for ALL canonical_entities but only equity tickers can be embedded — the rest return NULL. Either:
- Restrict the schedule to `WHERE entity_type = 'financial_instrument'` (matches the partial-index condition that should already exist)
- Or update the source_text generator to handle non-equity types (produces a generic description for products/events/macro_indicators)

**Choice**: restrict the schedule. Non-equity types don't have OHLCV data by definition.

**Acceptance criteria**:
- [ ] `entity_embedding_state` rows of type `fundamentals_ohlcv` exist only for `entity_type='financial_instrument'`
- [ ] After 24h, ≥ 80% of equity rows have non-NULL embedding (the other 20% are non-US tickers or new IPOs)

#### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/*.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/*.py`

#### Validation Gate
- [ ] 5 new tests pass
- [ ] After 24h ingestion, all 4 success metrics above are green

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| existing enrichment worker tests | claim now requires RETURNING | update mocks |

---

## Sub-Plan D — KG Refresh Workers

**Goal**: deploy + verify path-insight LLM explanations, fix fundamentals refresh backoff, catch up SummaryWorker.

**Waves**: 3 | **Tasks**: 11 | **Estimated**: 2 engineer-days

### Wave D-1: Path-insight LLM explanation worker — deploy + verify

**Goal**: the flagship feature ships writes to `path_insights.llm_explanation`.

**Depends on**: B-1 (AGE bootstrap must work first), A-1 (restart policies)
**Architecture layer**: application + infrastructure
**Estimated**: 4 hours

#### Task T-D-1-01: Verify path-insight worker is scheduled in compose + scheduler

**Type**: investigation + config
**depends_on**: none
**blocks**: T-D-1-02
**Target files**:
- `infra/compose/docker-compose.yml` (verify `knowledge-graph-path-insight-worker` service exists and is enabled)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/*.py` (verify scheduler enables it)
**Audit reference**: F-KG-PERSIST-003 / F-DB-002

**What to build**: read both files and confirm:
- Compose service exists with correct image + env
- Scheduler `_should_enable_path_insight()` returns True
- The worker's PRIMARY query (in commit `99f1845a`) is what's running

Document any gap in a remediation task in this wave.

**Acceptance criteria**:
- [ ] Worker container is running (`docker ps | grep path-insight`)
- [ ] Worker logs show `path_insight_worker_iteration_complete` events

---

#### Task T-D-1-02: Add `path_insight_explanation_pending_total` metric + alert

**Type**: impl
**depends_on**: T-D-1-01
**blocks**: T-D-1-03
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker.py` (or main file)
- `infra/grafana/alerts/path_insight_stalled.yml` **(NEW)**
**Audit reference**: F-KG-PERSIST-003

**What to build**: Gauge metric exposing the current count of `path_insights` rows where `llm_explanation IS NULL AND computed_at < now() - interval '1 hour'`. Updated once per worker cycle. Alert fires when value > 100 for 30 min.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_pending_gauge_increments_on_stale_rows` | DB has 5 stale rows → gauge == 5 | integration |
| `test_pending_gauge_excludes_recent_rows` | row computed 30s ago → not counted | integration |

**Acceptance criteria**:
- [ ] Metric exposed
- [ ] Alert rule loads in Grafana
- [ ] After 24h, the metric reads < 100

---

#### Task T-D-1-03: Add narrative_chat_client null-guard + fail-fast on missing API key

**Type**: impl
**depends_on**: T-D-1-02
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_path_insight.py` (or wherever the LLM call lives)
**Audit reference**: F-KG-PERSIST-003 (root cause investigation)

**What to build**: if `DEEPINFRA_API_KEY` is unset OR the LLM client returns None for every call, log `path_insight_llm_client_unavailable` at CRITICAL and stop processing for this cycle (instead of silently writing NULL explanations). This prevents the worker from "looking healthy" while producing nothing.

**Acceptance criteria**:
- [ ] Unsetting `DEEPINFRA_API_KEY` → worker exits with CRITICAL log
- [ ] Setting it back → worker resumes and writes explanations

#### Pre-read
- Commit `99f1845a` diff
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker_main.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_path_insight.py`
- `infra/compose/docker-compose.yml` (path-insight-worker block)

#### Validation Gate
- [ ] 2 new tests pass
- [ ] After 1h of fresh ingestion + worker running, `SELECT count(*) FROM path_insights WHERE llm_explanation IS NOT NULL` > 0 (no backfill needed; new writes only)
- [ ] Pending gauge approaches 0

#### Architecture Compliance
- [ ] R25 — generate_path_insight is a use case; depends on ABC LLM client port
- [ ] R12 — structlog
- [ ] R27 — read-only — uses ReadOnlyUnitOfWork

#### Regression Guardrails
- **HR-031** (silent failure): the null-guard prevents the worker from looking healthy while producing nothing

---

### Wave D-2: Fundamentals refresh — exponential backoff + status logging

**Goal**: stop hammering market-data on persistent 404s; surface actual HTTP status codes.

**Depends on**: A-1, C-3 (market-data path fix)
**Architecture layer**: infrastructure
**Estimated**: 3 hours

#### Task T-D-2-01: Add per-ticker exponential backoff to fundamentals_refresh

**Type**: impl
**depends_on**: none
**blocks**: T-D-2-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py`
**Audit reference**: F-REF-003

**What to build**: maintain a Valkey hash `s7:fundamentals:backoff_seconds:{ticker}` storing the current backoff in seconds. On HTTP error from market-data:
- First error: store 3600 (1h), set next_refresh_at = now + 1h
- Second consecutive error: 86400 (1d), next_refresh_at = now + 1d
- Third+: 604800 (7d), next_refresh_at = now + 7d
- Success: DELETE the key, normal cadence

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_first_404_backs_off_1h` | initial error → 3600s key + 1h next_refresh | unit |
| `test_consecutive_errors_escalate_to_7d` | 3rd error → 7d backoff | unit |
| `test_success_resets_backoff` | post-success → key deleted | unit |

**Acceptance criteria**:
- [ ] After 24h, log shows max ~10 calls to market-data per ticker per day (was: 1 per cycle = hundreds)
- [ ] Tests pass

---

#### Task T-D-2-02: Log actual HTTP status code on every market-data call

**Type**: impl
**depends_on**: T-D-2-01
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/clients/market_data_client.py`
**Audit reference**: F-REF-003

**What to build**: every call to market-data logs status + URL + body length at INFO if 2xx, WARN if 4xx, ERROR if 5xx. Today everything is collapsed to a generic "unavailable" warning.

**Acceptance criteria**:
- [ ] Log structured fields: `status_code`, `url`, `ticker`, `latency_ms`
- [ ] Test: mock 503 → log emitted at ERROR with correct fields

#### Validation Gate
- [ ] 3 new tests pass
- [ ] After 24h, status_code distribution visible in logs (not just "unavailable" everywhere)

---

### Wave D-3: SummaryWorker catchup + backlog metric

**Goal**: relations have summaries (currently 1.3% covered).

**Depends on**: B-2 (confidence NOT NULL so summaries have valid input)
**Architecture layer**: infrastructure
**Estimated**: 4 hours

#### Task T-D-3-01: Add `relation_summary_backlog` Prometheus gauge

**Type**: impl
**depends_on**: none
**blocks**: T-D-3-02
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary_worker.py`
**Audit reference**: F-DB-SUMMARIES-001 / F-DB-003

**What to build**: gauge counting rows in `relations` where `summary_stale=true OR NOT EXISTS (SELECT 1 FROM relation_summaries WHERE relation_id = r.relation_id)`. Updated once per worker cycle.

**Acceptance criteria**:
- [ ] Metric exposed; alert fires when value > 1000 for 1h

---

#### Task T-D-3-02: Increase SummaryWorker concurrency + add starve-avoidance ordering

**Type**: impl
**depends_on**: T-D-3-01
**blocks**: T-D-3-03
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary_worker.py`
**Audit reference**: F-DB-SUMMARIES-001

**What to build**:
- Raise per-cycle batch size (today: TBD — read code; raise to 50)
- Raise concurrency limit (today: TBD — raise to 5 concurrent LLM calls)
- Change claim ordering: `ORDER BY (summary_stale = true) DESC, last_summary_attempt_at NULLS FIRST` so fresh-stale rows beat rows that have failed N times

**Acceptance criteria**:
- [ ] After 24h, backlog drops by ≥ 50%
- [ ] No worker OOM under increased concurrency

---

#### Task T-D-3-03: Add `summary_worker_stuck_relations_total` counter

**Type**: impl
**depends_on**: T-D-3-02
**blocks**: none
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary_worker.py`
**Audit reference**: F-DB-003

**What to build**: counter that increments when a relation has been attempted ≥ 3 times without success. Lets us identify pathological relations (e.g., zero evidence) and tombstone them.

**Acceptance criteria**:
- [ ] Counter exposed
- [ ] Test: mock 3 failures → counter increments by 1

#### Pre-read
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/summary_worker.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/generate_summary.py`

#### Validation Gate
- [ ] 4 new tests pass
- [ ] After 48h, summary coverage > 20% (was 1.3%); backlog metric trending down

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| existing summary worker tests | concurrency limit changed | update fixtures |

---

## Sub-Plan E — RAG Agent Quality

**Goal**: stop the agent fabricating numbers. Replace the hallucination-inviting prompt. Wire intent classification. Fix the 4 broken KG tools. Add post-tool numeric grounding validation. Add multi-tool fallback. Fix response duplication. Fix citation marker validation.

**Waves**: 5 | **Tasks**: 19 | **Estimated**: 3.5 engineer-days

### Wave E-1: Replace tool-use system prompt + wire intent classification

**Goal**: kill the "supplement from training knowledge" clause. Make the per-intent prompts in `libs/prompts` reach the LLM.

**Depends on**: none (independent of A-F)
**Architecture layer**: application + libs
**Estimated**: 5 hours

#### Task T-E-1-01: Rewrite the tool-use system prompt — no training-knowledge supplement for facts

**Type**: impl
**depends_on**: none
**blocks**: T-E-1-02
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (lines 323-339, the inline prompt string)
- `libs/prompts/src/prompts/chat/tool_use.py` **(NEW — move the prompt out of the orchestrator and into the prompts lib)**
**Audit reference**: F-RAG-001 / F-CHAT-AGENT-001 / F-CHAT-003

**What to build**:
1. Delete the inline tool-use prompt at `chat_orchestrator.py:323-339`.
2. Create `libs/prompts/src/prompts/chat/tool_use.py` exporting `TOOL_USE_SYSTEM_PROMPT_TEMPLATE` — a stricter prompt:
   ```
   You are a research agent for institutional investors.

   STRICT RULES:
   - Only state facts that appear verbatim in tool responses.
   - For every numerical claim, cite the tool name AND the row index.
   - If a tool returns 0 rows or fails, say so explicitly. Never substitute
     pretraining knowledge for numerical, financial, or temporal data.
   - For relationship facts (e.g. "X is a subsidiary of Y") drawn from
     widely-known public knowledge, you MAY supplement only when:
     * The tool returned 0 items, AND
     * The fact is structural (no numbers, no dates), AND
     * You explicitly prefix with "Public knowledge (unverified):"

   FORBIDDEN:
   - Inventing revenue, EPS, market cap, ratios, or price figures.
   - Inventing quarter or year labels for financial data.
   - Inventing product names, executive names, or M&A events.
   - Rationalising your own bad numbers ("this may reflect volatility...").
   ```
3. Replace the inline prompt construction with a call to `get_tool_use_system_prompt(intent, retrieval_counts)`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_prompt_forbids_numeric_supplement` | inspect prompt string contains "FORBIDDEN" + "Inventing revenue" | unit |
| `test_intent_is_threaded_into_prompt` | GENERAL vs FINANCIAL_DATA produce different prompts | unit |

**Acceptance criteria**:
- [ ] Inline prompt deleted from `chat_orchestrator.py`
- [ ] All tool-use turns pull from `libs/prompts`
- [ ] Tests pass

---

#### Task T-E-1-02: Wire intent inference from first tool calls

**Type**: impl
**depends_on**: T-E-1-01
**blocks**: T-E-1-03
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
- `services/rag-chat/src/rag_chat/application/services/intent_inference.py` **(NEW)**
**Audit reference**: F-RAG-002 / F-RAG-INTENT-001

**Decision**: option (b) from the audit — infer intent from the first batch of tool calls, not a one-shot LLM call (saves a turn).

**What to build**: a pure function `infer_intent(tool_calls: list[ToolCall]) -> QueryIntent`:
- `compare_entities` OR ≥ 2 distinct entity_ids in tool args → `COMPARISON`
- `traverse_graph` OR `get_entity_paths` → `RELATIONSHIP`
- `get_fundamentals_history` OR `screen_universe` → `FINANCIAL_DATA`
- `get_economic_calendar` OR `get_temporal_events` → `MACRO`
- `search_documents` OR `search_claims` → `FACTUAL_LOOKUP`
- Default: `GENERAL`

Update the orchestrator: after the first tool-call iteration, call `infer_intent()` and use it for the SECOND prompt build, metrics, and audit logs.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_compare_entities_implies_COMPARISON` | input → COMPARISON | unit |
| `test_two_distinct_entities_implies_COMPARISON` | input → COMPARISON | unit |
| `test_traverse_graph_implies_RELATIONSHIP` | input → RELATIONSHIP | unit |
| `test_fundamentals_implies_FINANCIAL_DATA` | input → FINANCIAL_DATA | unit |
| `test_empty_tool_calls_default_to_GENERAL` | input → GENERAL | unit |

**Acceptance criteria**:
- [ ] All 5 tests pass
- [ ] Metrics `rag_queries_total{intent=...}` now show non-trivial distribution

---

#### Task T-E-1-03: Update prompt-builder + rerank to use inferred intent

**Type**: impl
**depends_on**: T-E-1-02
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/prompt_builder.py`
- `services/rag-chat/src/rag_chat/application/pipeline/reranker.py` (or equivalent)
**Audit reference**: F-RAG-002

**What to build**: pass the inferred intent into both call sites so the per-intent rerank weights and prompt variants are no longer dead code.

**Acceptance criteria**:
- [ ] After deploy, metrics show 4+ distinct intent values
- [ ] No regression in retrieval quality (covered by G-3 chat eval suite)

#### Validation Gate
- [ ] ruff + mypy pass on rag-chat + libs/prompts
- [ ] 7 new tests pass
- [ ] Q4 NVDA/AMD test in G-3 returns only quoted numbers

---

### Wave E-2: Post-tool numeric-grounding validator

**Goal**: reject responses whose numerical claims don't appear in any tool result.

**Depends on**: E-1
**Architecture layer**: application
**Estimated**: 6 hours

#### Task T-E-2-01: Create `NumericGroundingValidator` service

**Type**: impl
**depends_on**: none
**blocks**: T-E-2-02
**Target files**:
- `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py` **(NEW)**
- `services/rag-chat/tests/unit/application/services/test_numeric_grounding.py` **(NEW)**
**Audit reference**: F-CHAT-AGENT-001 / F-CHAT-003

**What to build**: a class with per-field tolerance configuration. Different financial fields tolerate different rounding levels — EPS quoted as $0.45 vs the actual $0.50 is 11% off and absolutely wrong; employee headcount quoted as 161,000 vs 161,400 is 0.25% off and acceptable. A single global tolerance cannot serve both.

```python
# libs/contracts/src/contracts/numeric_grounding.py (NEW — shared dataclass)
class FieldKind(str, Enum):
    """Financial field families that share rounding behaviour."""
    PRICE = "price"                # daily price, intraday — LLM must quote exact
    RETURN_PCT = "return_pct"      # day/week/period returns — exact
    YEAR = "year"                  # 2024, 2025 — exact (or skip)
    QUARTER = "quarter"            # Q1 2026 — exact (treated specially — must match label, not numeric)
    EPS = "eps"                    # earnings per share — tighter than revenue
    RATIO = "ratio"                # P/E, P/B, ROE, ROA, gross/operating margin — tight
    REVENUE = "revenue"            # revenue, EBIT, net income, FCF — LLM rounds these
    MARKET_CAP = "market_cap"      # often quoted in B/T with rounding
    SHARES = "shares"              # share count
    HEADCOUNT = "headcount"        # employee count
    UNKNOWN = "unknown"            # default fallback for any number we can't classify

# Default per-kind tolerances (% relative diff). Override via settings.
DEFAULT_TOLERANCES: dict[FieldKind, float] = {
    FieldKind.PRICE: 0.001,        # 0.1% — analyst will spot a 1¢ error on a $100 stock
    FieldKind.RETURN_PCT: 0.001,   # 0.1% — exact match expected
    FieldKind.YEAR: 0.0,           # exact
    FieldKind.QUARTER: 0.0,        # exact label match, not numeric
    FieldKind.EPS: 0.02,           # 2% — EPS quoted to 2 decimals; $0.45 vs $0.46 ok
    FieldKind.RATIO: 0.02,         # 2% — P/E 23.7 vs 24.1 ok; 23.7 vs 28.0 NOT
    FieldKind.REVENUE: 0.005,      # 0.5% — $68.1B vs $68.127B passes; $34.6B vs $10.25B fails
    FieldKind.MARKET_CAP: 0.005,   # 0.5% — same as revenue
    FieldKind.SHARES: 0.01,        # 1% — share counts are usually exact in filings but LLM rounds
    FieldKind.HEADCOUNT: 0.05,     # 5% — headcounts are quarterly snapshots; some lag ok
    FieldKind.UNKNOWN: 0.005,      # conservative default
}
```

**Logic & Behavior**:
1. Extract every number from the response (regex `[-+]?\d[\d,]*\.?\d*[BMKbmk%]?`).
2. **Classify each extracted number** into a `FieldKind` based on:
   - Surrounding ±50 chars of context (e.g. "EPS of $0.45" → `EPS`; "revenue was $68B" → `REVENUE`; "P/E of 23.7" → `RATIO`)
   - Numeric magnitude heuristics (numbers > 10^9 → likely `REVENUE`/`MARKET_CAP`; 4-digit 1900-2099 → `YEAR`)
   - Currency / suffix presence (`$` + B/M/K → REVENUE-family; `%` → RATIO or RETURN_PCT depending on context)
   - Unclassifiable → `UNKNOWN` (conservative default)
3. For each tool response, flatten into structured `(value, field_kind)` pairs using the same classifier on the source-row column name (so tool data has known `FieldKind` from schema).
4. For each response number:
   - Look up its `FieldKind` → tolerance
   - Find best match in tool results of the SAME `FieldKind` first; if none, try any kind (loose)
   - Pass if abs((response - tool) / tool) ≤ tolerance
   - Fail otherwise → add to `unsupported` with `(value, field_kind, tolerance_used, closest_tool_value)`
5. Return `GroundingResult(passed, unsupported, total_numbers, per_kind_stats)`.

**Settings override** (operator can tune):
```python
# rag-chat config.py
numeric_grounding_tolerances: dict[str, float] = Field(
    default_factory=lambda: {kind.value: tol for kind, tol in DEFAULT_TOLERANCES.items()},
    description="Per-field-kind relative tolerance for NumericGroundingValidator. Env: NUMERIC_GROUNDING_TOLERANCES_JSON",
)
```

Special handling:
- Numbers in dates (4-digit 1900-2099 alone, or "Q[1-4] 20XX") classified as `YEAR`/`QUARTER`; tolerance 0 → must match exactly (so an invented "$10.3B in Q2 2026" before AMD has reported Q2 fails immediately).
- Numbers in citation markers (`[N\d+]`) are skipped (handled by T-E-5-01).
- Percentages match against fractions (`50%` ↔ `0.50`).
- Negative numbers must match sign too (a loss reported as a gain is an outright lie, not a tolerance issue).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_exact_revenue_match_passes` | response "$10.253B" + tool returns 10.253e9 → REVENUE kind, passes | unit |
| `test_invented_revenue_fails` | response "$34.6B" + tool 10.253B → REVENUE kind, fails (337% diff > 0.5%) | unit |
| `test_rounded_revenue_within_tolerance` | response "$68.1B" + tool 68.127B → REVENUE, passes (0.04% < 0.5%) | unit |
| `test_eps_tighter_tolerance_catches_wrong_cents` | response "$0.50" + tool $0.40 → EPS kind, fails (25% > 2%) | unit |
| `test_eps_within_2pct_passes` | response "$0.45" + tool $0.456 → passes (1.3% ≤ 2%) | unit |
| `test_pe_ratio_fails_on_4pt_drift` | response "P/E 28" + tool "P/E 23.7" → RATIO, fails (18% > 2%) | unit |
| `test_headcount_5pct_tolerance` | response "161,000" + tool 161,400 → HEADCOUNT, passes (0.25% < 5%); response "150,000" → fails (7% > 5%) | unit |
| `test_year_must_match_exactly` | response "2025" + tool "2026" → YEAR, fails | unit |
| `test_quarter_must_match_exactly` | response "Q1 2026" + tool "Q4 2025" → QUARTER, fails | unit |
| `test_invented_quarter_for_unreported_period` | response "Q2 2026 revenue $10.3B" but AMD hasn't reported Q2 2026 → unsupported, fails | unit |
| `test_classifier_revenue_from_context` | "revenue of $X" → REVENUE; "EPS of $X" → EPS; same number, different kind | unit |
| `test_classifier_falls_back_to_unknown_safely` | unclassifiable context → UNKNOWN with 0.5% tol | unit |
| `test_year_numbers_ignored_when_skipped` | when skip_kinds={YEAR}, year numbers not validated | unit |
| `test_citation_markers_ignored` | `[N1]` not extracted as number | unit |
| `test_percentage_to_fraction_match` | "50%" matches "0.5" within RATIO tolerance | unit |
| `test_no_numbers_response_passes` | qualitative response → passes | unit |
| `test_empty_tool_results_fails_any_number` | response has number, no tools called → fails | unit |
| `test_settings_override_applies` | env override → headcount tol 0.10 → "150K" vs "161K" now passes | unit |
| `test_sign_must_match_loss_vs_gain` | response "earned $1.5B" + tool "lost $1.5B" → fails (sign mismatch, not tolerance) | unit |
| `test_per_kind_stats_in_result` | result includes breakdown of (passed, failed) per FieldKind | unit |

**Acceptance criteria**:
- [ ] All 20 tests pass
- [ ] False-positive rate on a hand-curated set of 20 correct responses ≤ 1
- [ ] False-negative rate on a hand-curated set of 10 known-bad responses (incl. the $34.6B AMD case) ≤ 0 — zero hallucinations may slip through
- [ ] Per-kind tolerances overridable via `NUMERIC_GROUNDING_TOLERANCES_JSON` env var

---

#### Task T-E-2-02: Wire validator into `chat_orchestrator` post-tool-loop

**Type**: impl
**depends_on**: T-E-2-01
**blocks**: T-E-2-03
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
**Audit reference**: F-CHAT-AGENT-001

**What to build**: after the LLM produces its final response and BEFORE the egress citation scrubber:
1. Collect every `tool_result` from the orchestrator's call log
2. Run `NumericGroundingValidator.validate(response, tool_results)`
3. If `passed=False` AND `unsupported` is non-empty:
   - Log `numeric_grounding_failed` at WARNING with `unsupported` list
   - Re-prompt the LLM ONCE with: `"The following numbers in your previous response cannot be found in tool results: {unsupported}. Rewrite your response, removing or marking each as [unverified]."`
   - Re-validate the rewrite. If still failing, return the rewrite anyway with a `⚠ Some numbers could not be verified against retrieved data.` banner appended.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_validator_invoked_after_tool_loop` | mock validator called once | integration |
| `test_failed_grounding_triggers_one_rewrite` | invented number → 2 LLM calls (initial + rewrite) | integration |
| `test_second_failure_appends_banner` | both fail → response ends with the warning banner | integration |

**Acceptance criteria**:
- [ ] All 3 tests pass
- [ ] Q4 NVDA/AMD test in G-3 no longer returns "$34.6B" — either gets rewritten or banner-flagged

---

#### Task T-E-2-03: Add grounding metric + Grafana panel

**Type**: impl
**depends_on**: T-E-2-02
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/services/numeric_grounding.py`
- `infra/grafana/dashboards/rag_chat.json` (add panel)
**Audit reference**: F-CHAT-003

**What to build**: counter `rag_grounding_validation_total{result="passed"|"failed_one_rewrite"|"failed_banner"}`. Panel showing the ratio over 24h.

**Acceptance criteria**:
- [ ] Metric exposed
- [ ] After 24h of chat traffic, panel shows the distribution

#### Validation Gate
- [ ] 11 new tests pass
- [ ] Q4 regression test in G-3 passes

---

### Wave E-3: Fix the 4 silent-empty KG tools (name resolution path)

**Goal**: `search_claims`, `search_events`, `search_entity_relations`, `get_contradictions` work even without a scoped entity_context.

**Depends on**: none
**Architecture layer**: application
**Estimated**: 4 hours

#### Task T-E-3-01: Add `_resolve_entity_by_name` to all 4 KG tool handlers

**Type**: impl
**depends_on**: none
**blocks**: T-E-3-02
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/handlers/intelligence.py` (lines 144-154, 360, 429, 504, 575)
**Audit reference**: F-RAG-003

**What to build**: replace every call to `_require_context_entity(...)` (which silently returns None) with the same `_resolve_entity_by_name(name)` path used by `_handle_get_entity_graph`. If the tool args include an `entity_name` field, use it. If not, the LLM should be told (via tool schema description update) to provide one.

Update tool input schemas in `libs/tools/src/tools/capability_manifest.yaml`:
- Add `entity_name: string` as required for each of the 4 tools
- Update descriptions to clarify: "If no scoped entity context, provide entity_name."

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_search_claims_resolves_by_name` | call with entity_name="Apple" + no scope → returns claims | unit |
| `test_search_events_resolves_by_name` | similar | unit |
| `test_search_entity_relations_resolves_by_name` | similar | unit |
| `test_get_contradictions_resolves_by_name` | similar | unit |
| `test_unknown_entity_name_returns_empty_with_log` | entity_name="ZZZZZZ" → [] + log `entity_name_not_found` | unit |

**Acceptance criteria**:
- [ ] All 5 tests pass
- [ ] Q7 (TSLA contradictions) in G-3 returns data instead of 503

---

#### Task T-E-3-02: Update tool manifest descriptions to disambiguate the 4 graph tools

**Type**: impl
**depends_on**: T-E-3-01
**blocks**: none
**Target files**: `libs/tools/src/tools/capability_manifest.yaml`
**Audit reference**: F-RAG-009

**What to build**: add a "tool selection guide" block to the system prompt + clarify each tool description:
- `get_entity_intelligence` — preferred for any "tell me about X" query; aggregates intelligence
- `get_entity_paths` — preferred for "how is X connected to Y" with a known target
- `get_entity_graph` — for visualizing 1-2 hops around an entity
- `traverse_graph` — for explicit Cypher-style path queries (advanced)
- `search_entity_relations` — for filtering by relation_type (e.g. "all M&A by Microsoft")

**Acceptance criteria**:
- [ ] All 4 tool descriptions are ≥ 2x longer with clear "use when" / "do NOT use when" guidance
- [ ] System prompt includes the precedence list

#### Validation Gate
- [ ] 5 new tests pass
- [ ] Q3 (Tim Cook) returns multiple companies (was: just Apple)
- [ ] Q7 (TSLA contradictions) returns data (was: 503)

---

### Wave E-4: Real embedding for `search_entity_relations` + multi-tool fallback + `entity_tickers` resolution

**Goal**: stop using zero-vector ANN. Stop ignoring `entity_tickers`. Add multi-tool fallback on empty results.

**Depends on**: E-3
**Architecture layer**: application
**Estimated**: 5 hours

#### Task T-E-4-01: Replace zero-vector with real query-embedding call in `search_entity_relations`

**Type**: impl
**depends_on**: none
**blocks**: T-E-4-02
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/handlers/intelligence.py:363-364`, `services/nlp-pipeline/src/nlp_pipeline/api/routes/embeddings.py` (add endpoint if missing)
**Audit reference**: F-RAG-004

**What to build**:
1. Add a new S6 endpoint `POST /api/v1/embeddings/text` accepting `{text: string}` and returning `{embedding: float[1024]}` (using the existing BGE-large client). Already may exist — check first.
2. In `search_entity_relations` handler, replace `placeholder_embedding: list[float] = [0.0] * 1024` with `embedding = await self._s6.embed_text(self._extract_query_text_from_args(args))`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_real_embedding_used_not_zero_vector` | mock embedding client called with right text | unit |
| `test_relations_returned_sorted_by_real_similarity` | relations ranked by actual cosine | integration |

**Acceptance criteria**:
- [ ] Both tests pass
- [ ] Q-acquisitions-like queries return semantically-relevant relations first

---

#### Task T-E-4-02: Wire `entity_tickers` → UUID resolution in `search_documents`

**Type**: impl
**depends_on**: none (parallel)
**blocks**: T-E-4-03
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py:124-143`
**Audit reference**: F-RAG-005

**What to build**: when the LLM passes `entity_tickers=["AAPL", "MSFT"]`, the handler must resolve each ticker → entity_id via S6's `resolve_entities` endpoint (or equivalent), then pass the resolved list to the S5 search call. Today the field is documented as TODO and silently ignored.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_entity_tickers_resolved_to_uuids` | input [AAPL, MSFT] → S5 call has 2 UUIDs | integration |
| `test_unknown_ticker_logged_and_skipped` | input [ZZZZZ] → log + empty | unit |

**Acceptance criteria**:
- [ ] Tests pass
- [ ] Comparison queries (e.g. "compare Apple and Microsoft news") return docs about both entities

---

#### Task T-E-4-03: Add multi-tool fallback to `chat_orchestrator`

**Type**: impl
**depends_on**: T-E-3-01, T-E-4-01, T-E-4-02
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`
**Audit reference**: F-CHAT-001, F-CHAT-004, F-CHAT-006

**What to build**: when a tool returns 0 items and the orchestrator has `consecutive_empty_tool_results >= 1`, before surfacing `[PROVIDER_UNAVAILABLE]` 503, attempt ONE alternate tool from a fallback map:
- `search_documents` empty → try `get_entity_intelligence`
- `get_contradictions` empty → try `search_claims(polarity=negative)`
- `get_economic_calendar` empty → try `get_temporal_events`
- `search_claims` empty → try `search_documents`

If the fallback also returns empty, then surface 503. Log `tool_fallback_attempted` and `tool_fallback_succeeded`/`tool_fallback_failed`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_search_documents_empty_falls_back_to_intelligence` | first tool empty → fallback called | integration |
| `test_double_empty_returns_503` | both empty → 503 surfaces | integration |
| `test_fallback_logged` | log emitted at each step | unit |

**Acceptance criteria**:
- [ ] Tests pass
- [ ] Q2 (MSTR news) and Q5 (TSLA macro) in G-3 no longer return 503 — they return either fallback data or "no relevant data found" with an explanation

#### Validation Gate
- [ ] 7 new tests pass
- [ ] G-3 chat eval shows ≥ 5/8 useful answers (target: 6/8)

---

### Wave E-5: Citation marker validation + tool dedup + response duplication fix

**Goal**: fix the cosmetic + correctness bugs: `[N1]` markers must point to real items, repeated tool calls don't waste budget, the answer doesn't repeat itself.

**Depends on**: E-1, E-2
**Architecture layer**: application
**Estimated**: 4 hours

#### Task T-E-5-01: Validate `[N\d+]` citation markers against retrieved items

**Type**: impl
**depends_on**: none
**blocks**: T-E-5-02
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:119-145`
**Audit reference**: F-RAG-006

**What to build**: after `process_output`, parse all `[N\d+]` markers. For each:
- If `N > len(retrieved_items)`: strip it from the response + log `citation_marker_orphan`
- Optional: lint that each numbered claim's surrounding sentence has the citation among retrieved items (string match on entity name)

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_orphan_marker_stripped` | response `"...[N7]"` with 3 items → marker removed | unit |
| `test_valid_marker_preserved` | response `"...[N2]"` with 3 items → preserved | unit |

**Acceptance criteria**:
- [ ] Tests pass
- [ ] No more `[N7]` in responses when only 3 items retrieved

---

#### Task T-E-5-02: Add tool-call dedup across iterations

**Type**: impl
**depends_on**: T-E-5-01
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:368-588`
**Audit reference**: F-RAG-007

**What to build**: maintain a `set` of `(tool_name, frozenset(input.items()))` already executed. When a new tool_call matches an executed one, return the cached result without re-executing and log `tool_dedup_hit`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_duplicate_tool_call_returns_cached_result` | call same tool with same args twice → second call hits cache | integration |
| `test_different_args_dont_dedup` | same tool, different args → both execute | integration |

**Acceptance criteria**:
- [ ] Tests pass
- [ ] After 24h, `rag_tool_dedup_hit_total` metric is non-zero

---

#### Task T-E-5-03: Fix sync coalescer response duplication

**Type**: impl
**depends_on**: none (parallel)
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (`execute_sync` method)
- `services/rag-chat/src/rag_chat/api/routes/chat.py` (find where sync emit happens)
**Audit reference**: F-CHAT-002

**What to build**: today the sync API emits both intermediate and final tokens, concatenated, producing visible duplication. Either:
- Buffer all tokens and emit only the final assistant message text
- Or split the streaming and sync code paths so sync skips intermediate emits

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_sync_response_no_duplication` | response field has only one copy of the answer | integration |

**Acceptance criteria**:
- [ ] Test passes
- [ ] Q3, Q4, Q6, Q8 responses in G-3 are not duplicated

---

#### Task T-E-5-04: Warn on tool-call truncation (> 5 in one turn)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py:243`
**Audit reference**: F-RAG-011

**What to build**: before the `capped = tool_calls[:_MAX_CONCURRENT_TOOLS]` truncation, emit:
```python
if len(tool_calls) > _MAX_CONCURRENT_TOOLS:
    log.warning("tool_calls_truncated", requested=len(tool_calls), kept=_MAX_CONCURRENT_TOOLS, dropped_tool_names=[c.tool_name for c in tool_calls[_MAX_CONCURRENT_TOOLS:]])
```

**Acceptance criteria**:
- [ ] Log emitted on truncation event
- [ ] Test confirms log fires when input is 7 calls

---

#### Task T-E-5-05: Raise `_TOOL_RESULT_MAX_CHARS` to 16000

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:81`
**Audit reference**: F-RAG-012

**What to build**: per-chunk cap is 4000 and aggregate cap is 4000 — only the first chunk survives. Raise aggregate to 16,000 (well under Llama-3.1-8B's 128K context).

**Acceptance criteria**:
- [ ] After change, search_documents returning 5 chunks contributes all 5 to LLM context
- [ ] Regression: latency doesn't increase meaningfully (verified via G-3)

#### Validation Gate
- [ ] 6 new tests pass
- [ ] G-3 chat regression suite shows ≥ 6/8 useful answers

#### Architecture Compliance
- [ ] R12 — all new logs use structlog
- [ ] R25 — validators are application services (no infra coupling)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| existing chat orchestrator tests | new validator + dedup steps | update fixtures to handle new code paths |
| `services/rag-chat/tests/integration/test_chat_streaming.py` | dedup may change tool call counts | adjust expected counts |

#### Regression Guardrails
- **HR-NEW-1** (LLM agent extrapolates from N=1): this whole sub-plan addresses it
- **BP-405** (name verification): the new tool schemas must align with the actual tool handler signatures — verified by name-resolution tests

---

## Sub-Plan F — Migration / Schema-Drift Fixes

**Goal**: stop the ~10/min "column does not exist" errors. Add CI guardrail so this can never happen again.

**Waves**: 2 | **Tasks**: 7 | **Estimated**: 1.5 engineer-days

### Wave F-1: CI test — PREPARE every repository SELECT against current schema

**Goal**: catch stale column references at PR time, not at runtime.

**Depends on**: A-1
**Architecture layer**: tests
**Estimated**: 5 hours

#### Task T-F-1-01: Static SQL extractor — discover every SQL string in repositories

**Type**: impl
**depends_on**: none
**blocks**: T-F-1-02
**Target files**:
- `tests/architecture/repository_sql_extractor.py` **(NEW)**
- `tests/architecture/test_repository_sql_prepare.py` **(NEW)**
**Audit reference**: F-LOG-MIGRATION-001 / F-LOG-004

**What to build**: a pytest fixture that:
1. Walks `services/*/src/*/infrastructure/*/repositories/*.py`
2. Parses each file with `ast` and extracts every string literal that starts with `SELECT`, `INSERT`, `UPDATE`, `DELETE`, or `WITH` (covering `sa.text(...)`, `session.execute(text(...))`, and raw asyncpg `fetch(...)` patterns)
3. Returns a list of `(file_path, line_number, sql_text)` tuples

This needs to handle SQL that has `:param` placeholders (sqlalchemy named-param syntax) and `$1` placeholders (asyncpg). For PREPARE, both work.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_extractor_finds_sa_text_sql` | finds a known SELECT in a known file | unit |
| `test_extractor_handles_multiline_strings` | f-string + dedent indented SELECT | unit |
| `test_extractor_skips_string_concat` | non-literal SQL is logged as skipped | unit |

**Acceptance criteria**:
- [ ] Tests pass
- [ ] Extractor finds ≥ 100 SQL statements across the repo (estimated from current code base)

---

#### Task T-F-1-02: PREPARE-test every extracted SQL against the current schema

**Type**: impl
**depends_on**: T-F-1-01
**blocks**: T-F-1-03
**Target files**: `tests/architecture/test_repository_sql_prepare.py`
**Audit reference**: F-LOG-MIGRATION-001

**What to build**: in the test, for each extracted SQL:
- Spin up a transactional psycopg connection to nlp_db / intelligence_db (use existing test-DB fixture)
- Run `await conn.execute(f"PREPARE _qatest AS {sql}; DEALLOCATE _qatest")` — pgsql validates column existence, table existence, function existence WITHOUT actually running the query
- If PREPARE raises `column "X" does not exist` → assertion failure with the file:line and the missing column name

Handle the case where a SQL references a temporary table or a CTE — PREPARE handles these correctly. Cross-database queries (rare) skip with a warning.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_all_repository_sql_prepares_successfully` | every extracted SQL prepares | integration |
| `test_catches_known_column_typo` | injecting `SELECT gliner_score FROM chunks` fails with clear error | integration |

**Acceptance criteria**:
- [ ] Test runs in CI and passes on a clean schema
- [ ] If T-F-2-01/02 missed any stale column, this test surfaces it

---

#### Task T-F-1-03: Add `--migrations-applied` mode for CI integration

**Type**: impl
**depends_on**: T-F-1-02
**blocks**: none
**Target files**: `tests/architecture/test_repository_sql_prepare.py`
**Audit reference**: F-LOG-MIGRATION-001

**What to build**: pytest fixture that ensures all alembic migrations are applied to a fresh test DB before the PREPARE pass runs. This is the canonical "schema head" against which to validate.

**Acceptance criteria**:
- [ ] CI runs alembic upgrade head → runs PREPARE pass → passes
- [ ] If a PR adds a SELECT referencing a column that doesn't exist in the head, CI fails

#### Validation Gate
- [ ] 5 new tests pass
- [ ] CI integration: PR with bad column reference is blocked

#### Architecture Compliance
- [ ] R32 — uses real migration head, not assumed

---

### Wave F-2: Patch the specific column-not-exist errors observed in logs

**Goal**: fix the actual repo SQLs that reference `gliner_score`, `embedding_type`, `published_at`, `label`, `entity_provisional`, `updated_at`.

**Depends on**: F-1 (so CI catches the fixes are correct)
**Architecture layer**: infrastructure
**Estimated**: 3 hours

#### Task T-F-2-01: Trace + fix `gliner_score` reference

**Type**: impl
**depends_on**: T-F-1-02
**blocks**: T-F-2-02 ... (independent — can parallelize)
**Target files**: TBD — discovered via `git grep "gliner_score" services/`
**Audit reference**: F-LOG-MIGRATION-001

**What to build**: grep, find, fix. Probably the column was renamed during migrations 0026-0029 to `gliner_confidence` or similar. Update the SELECT to use the new column name.

**Acceptance criteria**:
- [ ] PREPARE test passes for the file
- [ ] No log occurrences in `docker logs worldview-postgres-1` after deploy

---

#### Task T-F-2-02: Trace + fix `embedding_type`, `published_at`, `label`, `entity_provisional`, `updated_at` references

**Type**: impl
**depends_on**: T-F-1-02
**blocks**: none
**Target files**: TBD — discovered per column
**Audit reference**: F-LOG-MIGRATION-001

**What to build**: same pattern as T-F-2-01 for each column. Bundle as one task because each is a ~10-line change once found.

**Acceptance criteria**:
- [ ] `docker logs worldview-postgres-1 | grep "does not exist"` returns 0 lines for 1 hour after deploy
- [ ] PREPARE test passes for every changed file

#### Validation Gate
- [ ] All references fixed
- [ ] PREPARE CI test green

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| Tests asserting on column names | renamed columns | update assertions to new names |

---

## Sub-Plan G — Validation Test Suite (Post-Remediation Verification)

> **This sub-plan is the explicit verification gate the user requested**: "I want you to include a section of all tests that would need to be done after this plan to verify again all sections."
>
> Every test in this sub-plan corresponds to a specific finding from the QA audit. After this plan ships, running these tests must produce a green report — that is the only way to confirm the audit findings are actually resolved.

**Goal**: a comprehensive, automated, reproducible test suite that re-verifies every BLOCKING/CRITICAL/MAJOR finding from the QA report.

**Waves**: 3 | **Tasks**: 19 | **Estimated**: 2.5 engineer-days

### Wave G-1: Data Quality SLO Tests (Postgres + AGE)

**Goal**: programmatic tests that read live nlp_db + intelligence_db + AGE and assert on the metrics that drove the BLOCKING findings.

**Depends on**: A-F all complete
**Architecture layer**: integration tests
**Estimated**: 5 hours

#### Task T-G-1-01: AGE coverage assertion test

**Type**: test
**depends_on**: none
**blocks**: T-G-1-02
**Target files**: `tests/validation/test_age_coverage.py` **(NEW)**
**Audit reference**: F-KG-PERSIST-001, F-REF-001, F-REF-002, F-DB-009

**What to build**: a pytest integration test that:
1. Queries `intelligence_db` row counts: canonical_entities, relations, temporal_events
2. Queries AGE: count of `:entity` vertices, `:TemporalEvent` vertices, all edges
3. Asserts:
   - `age_entity_count >= 0.95 * canonical_entity_count` (allow 5% lag for in-flight writes)
   - `age_edge_count >= 0.95 * relation_count`
   - `age_temporal_event_count >= 0.95 * temporal_event_count`
   - `age_event_exposures_count >= 0.95 * entity_event_exposure_count`

**Sub-tests**:
| Sub-test | Verifies | Acceptance threshold |
|---|---|---|
| `test_age_entity_coverage` | AGE has all entities | ≥ 95% |
| `test_age_relation_coverage` | AGE has all relations | ≥ 95% |
| `test_age_temporal_event_coverage` | AGE has all events | ≥ 95% (was: 0%) |
| `test_age_event_exposures_coverage` | AGE has all exposures | ≥ 95% (was: 0%) |
| `test_age_label_case_matches_lowercase_entity` | `MATCH (n:entity)` returns rows; `MATCH (n:Entity)` is documented as wrong | docs alignment |

**Acceptance criteria**:
- [ ] All 5 sub-tests pass after a fresh deploy with PLAN-0093 applied
- [ ] Test runs in CI nightly

---

#### Task T-G-1-02: Relations data-quality SLO test

**Type**: test
**depends_on**: T-G-1-01
**blocks**: T-G-1-03
**Target files**: `tests/validation/test_relations_quality.py` **(NEW)**
**Audit reference**: F-KG-PERSIST-002, F-DB-001, F-DB-012

**What to build**:
| Sub-test | Verifies | Acceptance threshold |
|---|---|---|
| `test_zero_null_confidence` | `SELECT count(*) FROM relations WHERE confidence IS NULL` | == 0 |
| `test_zero_orphan_subject_fk` | `SELECT count(*) FROM relations r WHERE NOT EXISTS (SELECT 1 FROM canonical_entities ce WHERE ce.entity_id = r.subject_entity_id)` | == 0 |
| `test_zero_orphan_object_fk` | same for object | == 0 |
| `test_zero_self_loops_on_non_system_entities` | self-loops only allowed on `is_system=true` entities | == 0 non-system |
| `test_confidence_distribution_reasonable` | < 5% of relations have confidence < 0.1 | ≤ 5% |
| `test_summary_coverage` | `SELECT count(*) FROM relations WHERE EXISTS summary` / total | ≥ 30% (was 1.3%) |
| `test_summary_stale_flag_drains` | `SELECT count(*) FROM relations WHERE summary_stale=true` | ≤ 100 |
| `test_macro_sentinel_entity_exists` | row with id `11111111-0004-7000-8000-000000000001` exists | exists |

**Acceptance criteria**:
- [ ] All 8 sub-tests pass

---

#### Task T-G-1-03: NLP data-quality SLO test

**Type**: test
**depends_on**: T-G-1-02
**blocks**: T-G-1-04
**Target files**: `tests/validation/test_nlp_quality.py` **(NEW)**
**Audit reference**: F-NPL-005, F-NPL-006, F-NPL-008, F-DB-004, F-DB-008, F-DB-010

**What to build**:
| Sub-test | Verifies | Acceptance threshold |
|---|---|---|
| `test_zero_sub_floor_entity_mentions` | `SELECT count(*) FROM entity_mentions WHERE score < min_persist_floor` | == 0 |
| `test_zero_null_tenant_id_in_mentions` | `SELECT count(*) FROM entity_mentions WHERE tenant_id IS NULL` | == 0 |
| `test_impact_score_populated` | `SELECT count(*) FROM document_source_metadata WHERE impact_score IS NOT NULL` after 24h | ≥ 30% of total |
| `test_article_impact_windows_populated` | row count after 24h | ≥ 100 |
| `test_llm_relevance_score_lag` | `SELECT count(*) FROM document_source_metadata WHERE llm_relevance_score IS NULL` over last 24h | ≤ 5% |
| `test_relation_evidence_raw_has_claim_id` | `SELECT count(*) FROM relation_evidence_raw WHERE claim_id IS NULL` | == 0 |
| `test_relation_evidence_raw_has_chunk_id` | same for chunk_id | == 0 |

**Acceptance criteria**:
- [ ] All 7 sub-tests pass

---

#### Task T-G-1-04: Enrichment + embedding SLO test

**Type**: test
**depends_on**: T-G-1-03
**blocks**: T-G-1-05
**Target files**: `tests/validation/test_enrichment_quality.py` **(NEW)**
**Audit reference**: F-DB-005, F-REF-003, F-REF-004, F-REF-005, F-DB-ENRICHMENT-001

**What to build**:
| Sub-test | Verifies | Acceptance threshold |
|---|---|---|
| `test_enrichment_attempts_counter_advances` | over 24h, sum of attempts > 0 across entities; partial-index shrinks | non-zero progress |
| `test_definition_embedding_coverage` | `SELECT count(*) FROM entity_embedding_state WHERE view_type='definition' AND embedding IS NULL` | ≤ 5% |
| `test_narrative_embedding_coverage` | same for narrative | ≤ 5% |
| `test_fundamentals_ohlcv_embedding_coverage` | only equity rows considered (after T-C-4-03 scope reduction); ≥ 80% have non-NULL | ≥ 80% |
| `test_description_coverage_for_company_entities` | `SELECT count(*) FROM canonical_entities WHERE entity_type IN ('organization', 'financial_instrument') AND description IS NULL` | ≤ 10% |

**Acceptance criteria**:
- [ ] All 5 sub-tests pass after 24h of ingestion

---

#### Task T-G-1-05: Path-insight LLM explanation SLO test

**Type**: test
**depends_on**: T-G-1-04
**blocks**: none
**Target files**: `tests/validation/test_path_insight_quality.py` **(NEW)**
**Audit reference**: F-KG-PERSIST-003 / F-DB-002

**What to build**:
| Sub-test | Verifies | Acceptance threshold |
|---|---|---|
| `test_path_insight_llm_explanation_coverage` | `SELECT count(*) FROM path_insights WHERE llm_explanation IS NULL AND computed_at < now() - interval '1 hour'` | ≤ 100 |
| `test_path_insight_explanation_at_is_set` | non-NULL explanation rows also have explanation_at set | 100% alignment |
| `test_path_insight_pending_metric_exposed` | `path_insight_explanation_pending_total` exposed on /metrics | metric exists |

**Acceptance criteria**:
- [ ] All 3 sub-tests pass

#### Validation Gate (Wave G-1)
- [ ] 5 new test files, 28 sub-tests, all passing
- [ ] All tests reproducible against a fresh deploy
- [ ] Tests added to nightly CI

---

### Wave G-2: Infrastructure + Security SLO Tests

**Goal**: programmatic validation that the infrastructure hardening from Sub-Plan A actually delivers.

**Depends on**: A-F all complete
**Architecture layer**: integration tests
**Estimated**: 4 hours

#### Task T-G-2-01: Restart-policy reachability test

**Type**: test
**depends_on**: none
**blocks**: T-G-2-02
**Target files**: `tests/validation/test_restart_policy.py` **(NEW)**
**Audit reference**: F-LOG-INFRA-001

**What to build**: docker-compose parser-based test that:
- Loads the compose file
- For every service in the critical list `{ollama, schema-registry, market-data, postgres, kafka, valkey, minio}`, asserts `restart: unless-stopped`
- For every retry worker in the dependent list `{path-insight-worker, embedding-retry-worker, unresolved-resolution-worker}`, asserts `depends_on` has all required services with `condition: service_healthy`

**Acceptance criteria**: file parses cleanly + all assertions pass

---

#### Task T-G-2-02: Host-event survival simulation (manual procedure documented)

**Type**: docs + test
**depends_on**: T-G-2-01
**blocks**: T-G-2-03
**Target files**: `tests/validation/manual/host_event_survival.md` **(NEW)**
**Audit reference**: F-LOG-INFRA-001

**What to build**: a runbook + checklist for manually simulating the 21:40 Docker event:
```
1. Run: docker stop worldview-postgres-1 worldview-kafka-1 worldview-valkey-1 worldview-ollama-1 worldview-schema-registry-1 worldview-market-data-1
2. Wait 60 seconds
3. Verify all 6 are stopped: docker ps -a | grep -E "postgres|kafka|valkey|ollama|schema-registry|market-data"
4. Run: docker start (all 6)
5. Wait 120 seconds for healthchecks
6. Verify: docker ps -a | grep -v Exited | grep worldview | wc -l == EXPECTED_TOTAL
7. Run rdkafka probe test (T-G-2-03)
```

**Acceptance criteria**: runbook produces a green outcome (every container Up, every consumer consuming)

---

#### Task T-G-2-03: rdkafka DNS-recovery test

**Type**: test
**depends_on**: T-G-2-02
**blocks**: T-G-2-04
**Target files**: `tests/validation/test_kafka_dns_recovery.py` **(NEW)**
**Audit reference**: F-LOG-003

**What to build**: integration test that:
- Starts a kafka container
- Connects a consumer
- Restarts kafka (gets new IP)
- Asserts: consumer reconnects within 60s (verified via metric `kafka_consumer_messages_consumed_total` advancing post-restart)

**Acceptance criteria**: test passes within 90s

---

#### Task T-G-2-04: APP_ENV enforcement test

**Type**: test
**depends_on**: T-G-2-03
**blocks**: T-G-2-05
**Target files**: `tests/validation/test_app_env_enforcement.py` **(NEW)**
**Audit reference**: F-LOG-JWT-001

**What to build**: integration test that:
1. Spins up rag-chat container with `APP_ENV` unset AND `INTERNAL_JWT_SKIP_VERIFICATION=true`
2. Asserts container exits within 30s with non-zero code
3. Asserts logs contain `startup_security_check_failed`

**Acceptance criteria**: test passes

---

#### Task T-G-2-05: No restart-loop test (24h soak)

**Type**: test (nightly soak)
**depends_on**: T-G-2-04
**blocks**: none
**Target files**: `tests/validation/soak/test_no_restart_loops.py` **(NEW)**
**Audit reference**: F-LOG-002, F-NPL-002, F-REF-006

**What to build**: a long-running test scheduled nightly:
- Every 5 minutes, runs `docker ps -a --format "{{.Status}}\t{{.Names}}" | grep worldview | grep -i restart`
- If ANY container shows `Restarting` for 3 consecutive samples → fail the test with the container name + the last 50 log lines

**Acceptance criteria**: 24h soak passes; no container in restart loop

#### Validation Gate (Wave G-2)
- [ ] 5 new test files, all passing
- [ ] T-G-2-05 added to nightly CI

---

### Wave G-3: RAG-chat Behavioral Regression Suite

**Goal**: convert the 8 audit questions into automated tests with quantitative grading. ≥ 6/8 must score USEFUL for the audit verdict to flip from FAIL to PASS_WITH_WARNINGS.

**Depends on**: E-1 ... E-5 all complete (the RAG agent quality wave)
**Architecture layer**: E2E integration
**Estimated**: 6 hours

#### Task T-G-3-01: Build E2E chat eval harness with deterministic scoring

**Type**: test
**depends_on**: none
**blocks**: T-G-3-02
**Target files**:
- `tests/validation/chat_eval/harness.py` **(NEW)**
- `tests/validation/chat_eval/questions.yaml` **(NEW — the 8 audit questions)**
- `tests/validation/chat_eval/grading.py` **(NEW)**
**Audit reference**: F-CHAT-AGENT-001 / F-CHAT-001 .. 006 / A5 entire section

**What to build**:
1. `harness.py`: pytest fixture that:
   - Gets a dev JWT via `POST /v1/auth/dev-login`
   - Loads `questions.yaml`
   - For each question, POSTs to `/v1/chat`, captures full response + tool calls + latency
   - Saves results to `tests/validation/chat_eval/runs/<timestamp>/q<N>.json`
2. `grading.py`: pure function `grade_response(question, response_json, ground_truth_assertions) -> dict[str, str]`:
   - `tools_called`: list of tool names from response
   - `numbers_in_response`: list of extracted numbers
   - `unsupported_numbers`: numbers not present in tool results (using `NumericGroundingValidator` from E-2)
   - `hallucination`: YES if `len(unsupported_numbers) > 0`, NO otherwise
   - `citations_valid`: are all `[N\d+]` markers within bounds?
   - `verdict`: USEFUL / MARGINAL / USELESS / HARMFUL (based on rubric)
3. `questions.yaml`: the 8 audit questions + ground_truth_assertions per question (e.g. for Q4: "AMD Q1FY26 revenue MUST equal 10.253B ± 0.1; NVDA Q4FY26 MUST equal 68.127B ± 0.1")

**Acceptance criteria**:
- [ ] Harness runs all 8 questions end-to-end
- [ ] Output JSON saved per question
- [ ] Grading produces a verdict per question

---

#### Task T-G-3-02: Q1 — competitors-of-Apple test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q1_competitors.py` **(NEW)**
**Audit reference**: A5 Q1

**What to build**: assertions:
- HTTP 200
- `tools_called` includes `compare_entities` OR `get_entity_intelligence`
- Response mentions ≥ 2 of {Samsung, Microsoft, Google, Huawei, Xiaomi} (real competitors)
- `hallucination == NO` (no invented market cap figures)
- `verdict in {USEFUL, MARGINAL}`

---

#### Task T-G-3-03: Q2 — MSTR news test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q2_mstr_news.py` **(NEW)**
**Audit reference**: A5 Q2 / F-CHAT-001

**What to build**: assertions:
- HTTP 200 (not 503 — multi-tool fallback should kick in)
- `tools_called` includes ≥ 2 distinct tools (`search_documents` + fallback)
- Response mentions Bitcoin / BTC
- `verdict != USELESS`

---

#### Task T-G-3-04: Q3 — Tim Cook executive history test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q3_tim_cook.py` **(NEW)**
**Audit reference**: A5 Q3

**What to build**: assertions:
- `tools_called` includes `get_entity_intelligence` OR `traverse_graph`
- Response mentions Apple (required) AND ideally Compaq, IBM (historical roles)
- No response duplication (text doesn't repeat itself — checked via `text.count(text[:50]) == 1`)
- `verdict in {USEFUL, MARGINAL}`

---

#### Task T-G-3-05: Q4 — NVDA vs AMD revenue test (HARDEST — primary hallucination check, multi-quarter)

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q4_nvda_amd_revenue.py` **(NEW)**, `tests/validation/chat_eval/fixtures/q4_ground_truth.yaml` **(NEW)**
**Audit reference**: A5 Q4 / F-CHAT-003 / F-CHAT-AGENT-001

**What to build**: assertions across **6 quarters × 2 tickers (12 datapoints)**. Loads ground truth from a fixture file (`q4_ground_truth.yaml`) generated by querying `market_data_db.fundamental_metrics` at test setup, so the test is self-updating as new quarters arrive.

**Ground-truth fixture** (auto-generated by test setup; this is the schema):
```yaml
NVDA:
  - quarter: Q4FY26   # 2026-01-31
    revenue: 68127000000
    eps: 0.89
    gross_margin: 0.745
  - quarter: Q3FY26   # 2025-10-31
    revenue: 57000000000
    eps: 0.80
    gross_margin: 0.732
  # ... 4 more quarters
AMD:
  - quarter: Q1FY26   # 2026-03-31
    revenue: 10253000000
    eps: 0.45
    gross_margin: 0.508
  # ... 5 more quarters
```

**Question variants fired** (all must pass — 6 variants per test run):
1. "Compare the revenue trajectories of NVIDIA and AMD over the last 4 quarters."
2. "What was NVIDIA's revenue in Q4 of fiscal 2026?"
3. "What was AMD's Q1 2026 revenue and EPS?"
4. "Show me NVIDIA's gross margin trend over the past 6 quarters."
5. "What is AMD's revenue growth YoY for the most recent quarter?"
6. "Compare NVDA and AMD on revenue, EPS, and gross margin for the latest reported quarter."

**Per-question assertions**:
- HTTP 200
- `tools_called` includes `get_fundamentals_history` (called ≥ 2 times for comparison questions)
- For every numeric claim:
  - Classify into `FieldKind` via `NumericGroundingValidator` (T-E-2-01)
  - Match against fixture using per-kind tolerance
  - Fail with `assert_grounded(extracted_numbers, fixture)` helper
- **Forbidden phrases** (regex-checked):
  - Any AMD revenue figure > $15B for any quarter (the $34.6B fabrication signature)
  - Any NVDA revenue figure > $100B for any quarter (current ceiling ~$70B)
  - Rationalisation patterns: `r"(potential volatility|one-time event|may reflect|likely (due|caused))"` — ONLY allowed if followed by a citation marker
- **Quarter labels MUST match fixture exactly** (no inventing "Q2 2026" for AMD when only Q1 has reported)
- `verdict == USEFUL`

**Sub-tests (separate pytest functions)**:
| Sub-test | Verifies |
|---|---|
| `test_q4_v1_compare_revenues` | full comparison question; all 8 quarters across both tickers grounded |
| `test_q4_v2_nvda_single_quarter` | single-quarter NVDA query — exact revenue match |
| `test_q4_v3_amd_revenue_and_eps` | AMD multi-field; revenue (REVENUE tol) + EPS (EPS tighter tol) both pass |
| `test_q4_v4_nvda_margin_trend` | gross margin sequence; RATIO kind tolerance applies |
| `test_q4_v5_amd_yoy_growth` | derived value (YoY %) computed correctly from quarterly fixture |
| `test_q4_v6_full_comparison_table` | revenue + EPS + margin for both tickers simultaneously |
| `test_q4_zero_amd_figures_above_15b` | regex check: no fabricated AMD numbers in any v1-v6 response |
| `test_q4_zero_orphan_rationalisations` | no "potential volatility" without a citation in any response |
| `test_q4_no_invented_quarter_labels` | every "Q[1-4] 20XX" mentioned exists in fixture |

**Critical**: if any sub-test fails, the entire remediation fails. Q4 is the bellwether — it's the exact scenario where the audit caught the agent fabricating a 3.4×-wrong revenue figure. This test must catch the same failure mode under any of the 6 question variants.

---

#### Task T-G-3-06: Q5 — TSLA macro events test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q5_tsla_macro.py` **(NEW)**
**Audit reference**: A5 Q5 / F-CHAT-004

**What to build**: assertions:
- HTTP 200 (not 503 — multi-tool fallback)
- `tools_called` includes ≥ 2 of {`get_economic_calendar`, `get_temporal_events`, `get_entity_event_exposures`}
- `verdict != USELESS`

---

#### Task T-G-3-07: Q6 — AI semiconductor screener test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q6_ai_chip_screener.py` **(NEW)**
**Audit reference**: A5 Q6 / F-CHAT-005

**What to build**: assertions:
- `tools_called` includes `screen_universe` with proper filter args (sector=Semiconductors)
- Response mentions ≥ 3 ticker symbols (NVDA, AMD, AVGO, etc.)
- `hallucination == NO` (no invented product names like "MI300 design wins")
- `verdict in {USEFUL, MARGINAL}`

---

#### Task T-G-3-08: Q7 — TSLA contradictions test

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q7_tsla_contradictions.py` **(NEW)**
**Audit reference**: A5 Q7 / F-CHAT-006

**What to build**: assertions:
- HTTP 200 (not 503 — `get_contradictions` now works via name resolution)
- `tools_called` includes `get_contradictions` with entity_name="Tesla"
- Response either returns contradiction data OR says explicitly "no contradictions detected for Tesla in the current window"
- `verdict != USELESS`

---

#### Task T-G-3-09: Q8 — OpenAI→MSFT path test (PASS baseline — was the only USEFUL answer)

**Type**: test
**depends_on**: T-G-3-01
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_q8_openai_msft_paths.py` **(NEW)**
**Audit reference**: A5 Q8 (positive baseline)

**What to build**: assertions:
- HTTP 200
- `tools_called` includes `traverse_graph` OR `get_entity_paths`
- Response includes ≥ 1 path mention (OpenAI, Microsoft both appear)
- `verdict == USEFUL`
- This test acts as a regression guard — if it ever drops below USEFUL, we've broken the working path

---

#### Task T-G-3-10: Aggregate suite — pass gate ≥ 6/8 USEFUL

**Type**: test
**depends_on**: T-G-3-02 ... T-G-3-09
**blocks**: none
**Target files**: `tests/validation/chat_eval/test_aggregate_score.py` **(NEW)**
**Audit reference**: A5 overall

**What to build**: collects verdicts from all 8 questions, asserts:
- USEFUL count ≥ 6
- HARMFUL count == 0 (zero tolerance for confident hallucinations)
- Median latency ≤ 30s
- p99 latency ≤ 60s

**Acceptance criteria**: this is the **gate test** for the 8-question audit-regression suite. If it passes AND T-G-3-11 (below) finds no new BLOCKING weak points, PLAN-0093 is complete.

---

#### Task T-G-3-11: Weak-Point Survey — 5 × 5 × 3 matrix to find new failure modes (Q4 follow-up)

**Type**: test + investigation
**depends_on**: T-G-3-02 ... T-G-3-10
**blocks**: none
**Target files**:
- `tests/validation/chat_eval/test_weak_point_survey.py` **(NEW)**
- `tests/validation/chat_eval/fixtures/survey_matrix.yaml` **(NEW)**
- `tests/validation/chat_eval/weak_point_report.py` **(NEW — generates a markdown report from the run)**
**Audit reference**: Q4 decision (2026-05-23) — "investigate other quarters and informations to search for other weak points/corners/edges where our platform is failing"

**What to build**: a systematic sweep across the surface area that the original 8-question audit only sampled. The audit revealed Q4's $34.6B AMD fabrication by accident — we got lucky. This task tries to be unlucky on purpose by firing a much larger matrix of queries and using `NumericGroundingValidator` to surface every ungrounded number, grouped by (ticker, metric_kind, question_form). The output is a report listing the (ticker × metric) cells where the agent systematically fabricates or refuses — those are the next BLOCKING items.

**The matrix**: 5 tickers × 5 metric families × 3 question variants = 75 queries per run.

**Tickers (representative + diverse)**:
| Ticker | Selection reason |
|---|---|
| AAPL | Mega-cap, abundant data, original audit target |
| NVDA | Recent high-volatility, exotic FY (Jan year-end) — already-known edge case |
| AMD | Original Q4 hallucination victim |
| TSM | Non-US (Taiwan), tests ADR / foreign filer path |
| BRK.B | Class-B share, holding company — tests entity disambiguation + non-traditional financials |

**Metric families (one from each FieldKind cluster)**:
| Family | Probes | Why included |
|---|---|---|
| REVENUE | quarterly revenue | the original $34.6B failure mode |
| EPS | TTM EPS, last-quarter EPS | tighter tolerance kind |
| RATIO | P/E, P/B, gross margin, ROE | derived metrics where LLM loves to guess |
| HEADCOUNT | employee count | EODHD field — often stale, looser tol |
| CORPORATE_ACTION | last buyback, last dividend, last M&A | KG-side data (relations table) — different surface |

**Question variants (3 forms per family)**:
1. **Specific lookup**: "What is {ticker}'s {metric}?"
2. **Comparative**: "Compare {ticker} and AAPL on {metric}."
3. **Trend**: "Show me {ticker}'s {metric} over the last 4 quarters."

Total: 5 × 5 × 3 = **75 queries**.

**Per-query analysis (using NumericGroundingValidator + classifiers)**:
For each response, record:
- HTTP status + latency
- Tools called
- Numbers extracted with classified `FieldKind`
- Numbers ungrounded (via T-E-2-01 validator)
- Quarter labels invented (not present in `market_data_db.fundamental_metrics`)
- Refusal indicators (`PROVIDER_UNAVAILABLE`, `unable to retrieve`)
- Hallucination indicators (rationalisation phrases)

**Aggregation report** (written to `tests/validation/chat_eval/runs/<timestamp>/weak_point_report.md`):
| Section | Content |
|---|---|
| Headline | "X of 75 queries had ungrounded numbers" + worst-offender cell |
| Per-ticker | for each ticker: query count, ungrounded count, refusal count, top failure pattern |
| Per-metric-family | same breakdown by metric family — surfaces "platform always fabricates EPS for non-US tickers" patterns |
| Per-question-form | which form (specific / comparative / trend) fails most often |
| Newly-discovered patterns | regex extraction of common hallucinations across queries — surfaces e.g. "agent invents 'AMD MI300' in 4 of 5 AI-context queries" |
| Top-10 (ticker, metric, form) cells to fix | ranked by `ungrounded_count / total_queries_for_cell` |

**Gating logic** (pytest assertions, BLOCKING the overall plan completion):
- **HARMFUL count** (ungrounded numerical claim in a confident response) must be 0 for any of the 75 queries → BLOCKING
- **Refusal rate** (HTTP 503 or "unable to retrieve") must be ≤ 20% across the 75 queries
- **Ungrounded-numbers rate** (any unsupported number per validator) must be ≤ 10% across all numbers extracted
- **New invented-quarter** (a quarter label not in the fixture) count must be 0 — zero tolerance

**Sub-tests**:
| Sub-test | Verifies |
|---|---|
| `test_survey_runs_all_75_queries` | full sweep completes; no infrastructure failure |
| `test_survey_zero_harmful_responses` | 0 confident-fabrication queries (BLOCKING gate) |
| `test_survey_refusal_rate_under_20pct` | ≤ 15 of 75 return 503 |
| `test_survey_ungrounded_numbers_under_10pct` | per-query average ungrounded ≤ 10% |
| `test_survey_zero_invented_quarter_labels` | no fabricated quarters across all queries |
| `test_survey_report_artifact_written` | markdown report written and well-formed |
| `test_survey_per_ticker_breakdown_complete` | each ticker has its breakdown in report |
| `test_survey_per_metric_breakdown_complete` | each metric family has its breakdown |
| `test_survey_no_systematic_metric_failure` | no metric family fails > 50% across all tickers (catches "platform always fails on EPS" class bugs) |

**Acceptance criteria**:
- [ ] All 9 sub-tests pass
- [ ] `weak_point_report.md` produced and reviewed by a human; any newly-discovered systematic failure pattern is filed as a BP-NEW-NNN candidate or a follow-up plan
- [ ] Report includes a "newly-discovered patterns" section that future audits use as baseline

**Why this matters**: the original audit found the $34.6B AMD bug by firing 8 questions. With 75, we have ~10× the coverage and ~10× the chance of catching the next class of bug BEFORE a paying analyst does. This task is the difference between "we patched what we found" and "we have confidence in what we did NOT find."

#### Validation Gate (Wave G-3)
- [ ] All 11 task files exist and tests run
- [ ] T-G-3-10 aggregate suite shows ≥ 6/8 USEFUL, zero HARMFUL
- [ ] T-G-3-11 weak-point survey: zero HARMFUL across 75 queries, refusal ≤ 20%, ungrounded ≤ 10%, zero invented quarters
- [ ] Suite scheduled to run on every PR touching `services/rag-chat/`, `services/knowledge-graph/`, or `services/nlp-pipeline/`
- [ ] Weak-point report committed to `docs/audits/` for each scheduled nightly run

---

## Cross-Cutting Concerns

### Contract Changes
- **API response shape**: `direction` field added to graph_query response (T-B-4-01) — frontend `EdgeTooltipPanel.tsx` must be updated. Backwards-compatible (field added, not renamed).
- **Tool schemas in `libs/tools/.../capability_manifest.yaml`**: 4 tools get a required `entity_name` arg (T-E-3-01). Backwards-incompatible for any LLM-generated tool call lacking it — but the LLM is re-prompted from the new manifest so no rolling-deploy issue.
- **No Avro schema changes** in this plan.

### Migration Order (Mandatory Sequence)
1. `intelligence-migrations/0044_seed_kg_system_entities.py` — must apply before any relation write
2. `intelligence-migrations/0045_add_relations_fk_constraints.py` — applies after 0044 (TRUNCATEs first)
3. `intelligence-migrations/0046_relations_confidence_not_null.py` — applies after 0045
4. `intelligence-migrations/0047_evidence_raw_not_null_fks.py` — applies after 0046
5. `nlp-pipeline/0020_entity_mentions_tenant_not_null.py` — independent of intelligence migrations

### Configuration Changes (env vars)
| Env Var | Default | Service | Wave |
|---|---|---|---|
| `APP_ENV` | `local` | all | A-1 |
| `NLP_PIPELINE_MIN_PERSIST_FLOOR` | `0.6` | nlp-pipeline | C-2 |
| `BROKER_ADDRESS_TTL_MS` | `30000` | (in libs/messaging defaults) | A-2 |
| `RAG_NUMERIC_GROUNDING_ENABLED` | `true` | rag-chat | E-2 |

### Documentation Updates
- `docs/services/knowledge-graph.md` — AGE bootstrap section + per-phase watermark
- `docs/services/nlp-pipeline.md` — routing v2 (dropped signals + new weights)
- `docs/services/rag-chat.md` — intent inference + numeric grounding validator
- `docs/services/market-data.md` — verified endpoint contract (T-C-3-01)
- `docs/specs/0026-news-intelligence-apis.md` — routing v2 amendment
- `services/{kg,nlp,rag-chat}/.claude-context.md` — new pitfalls + new test commands
- `docs/MASTER_PLAN.md` — no architectural change; status update only
- `docs/BUG_PATTERNS.md` — 5 new entries (BP-NEW-1 through BP-NEW-5 from audit report)
- `RULES.md` — 1 new rule (R35 — "every service must declare `depends_on: service_healthy` for all hard infrastructure dependencies")
- `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — 3 new patterns (silent-failure-as-restart-loop, prompt-supplements-pretraining, watermark-advances-on-partial-sync)

### TRACKING.md Update (MANDATORY)
Append the following row to `docs/plans/TRACKING.md` Active Plans table:

```
| PLAN-0093 | Intelligence Pipeline Remediation (KG-RAG + Infra) | 2026-05-23-qa-intelligence-pipelines-report.md | draft | 0/24 | — | 2026-05-23 |
```

---

## Risk Assessment

### Critical Path
**A-1 → B-1 → D-1 → G-3** — without A-1, every other wave can be undone by a host restart. Without B-1, no AGE Cypher query produces correct results. Without D-1, the path-insight flagship feature stays empty. Without G-3, we have no proof the remediation worked.

### Highest Risk
- **B-2 migrations 0044/0045/0046** use `TRUNCATE` — only acceptable because pre-prod. If anyone misreads this plan as production-applicable, real customer data would be lost. **Mitigation**: every migration's `upgrade()` starts with an assertion `assert os.environ.get("APP_ENV") != "production"` (added in T-A-1-03).
- **E-2 numeric grounding validator** has false-positive risk — if it rejects too aggressively, the user sees "⚠ Some numbers could not be verified" on legitimate answers. **Mitigation**: tolerance is 0.5%; G-3 grades both false positives and false negatives.
- **C-3 market-data path fix** depends on actually finding the right endpoint — if T-C-3-01 reveals there is NO symbol resolver, we need a new precursor wave to add one (and reschedule). **Mitigation**: T-C-3-01 is an investigation task; outcome gates T-C-3-02.

### Rollback Strategy
- **Sub-Plan A** rollback: revert the compose file (single file change)
- **Sub-Plan B** rollback: `alembic downgrade -3` (drops 0046, 0045, 0044). Data lost (we TRUNCATEd) — acceptable pre-prod
- **Sub-Plan C** rollback: revert code; data already in tables is preserved (we only added fields, didn't drop)
- **Sub-Plan D** rollback: revert code; workers resume previous behaviour
- **Sub-Plan E** rollback: revert code; agent reverts to current (degraded) behaviour
- **Sub-Plan F** rollback: revert code; CI test no longer runs
- **Sub-Plan G** rollback: drop the tests (but you wouldn't — they're independent of remediation)

### Testing Gaps
- **Live LLM cost**: G-3 fires 8 real chat questions per CI run. At Llama-3.1-8B prices this is ~$0.01/run. Acceptable.
- **Long-running soak**: T-G-2-05 runs 24h. Cannot fit in a normal PR pipeline — gated to nightly only.
- **Cross-database FK**: claim_id (intelligence_db) ↔ chunk_id (nlp_db) — no DB-level enforcement possible. Mitigated by app-level invariant + PREPARE test (T-F-1-02).

---

## Effort Summary

| Sub-Plan | Waves | Tasks | Effort | Critical-path |
|---|---|---|---|---|
| A | 3 | 10 | 1.5 days | ✓ |
| B | 4 | 16 | 2.5 days | ✓ |
| C | 4 | 14 | 2.5 days | parallel |
| D | 3 | 11 | 2.0 days | depends on B |
| E | 5 | 19 | 3.5 days | parallel |
| F | 2 | 7 | 1.5 days | parallel |
| G | 3 | 19 | 2.5 days | gate |
| **Total** | **24** | **96** | **16.0 days** (1 eng) / **7.5-9.5 days** (2 eng parallel) | — |

---

## Resolved Decisions (2026-05-23)

All 4 open questions resolved by the product owner; sections of this plan have been amended accordingly. Original questions + final decisions:

1. **Q1 (T-C-1-01) — RESOLVED: drop dead signals**. Two-pass routing deferred to a follow-up plan. T-C-1-01 as written.
2. **Q2 (T-C-3-01) — RESOLVED: agent investigates first**. T-C-3-01 is the investigation task; if it discovers no symbol resolver exists, the implementing agent must surface this as a blocker before starting T-C-3-02 and propose either (a) adding the endpoint to market-data, or (b) using the existing path with a corrected argument shape. Now explicit in T-C-3-01 acceptance criteria.
3. **Q3 (T-E-2-01) — RESOLVED: per-field tolerance config**. T-E-2-01 amended to use a `NUMERIC_GROUNDING_TOLERANCES` settings dict keyed by financial-field type (tighter for EPS/ratios/prices; looser for headcount). Global 0.5% is no longer the design — see the amended task spec.
4. **Q4 (T-G-3-05) — RESOLVED: multi-quarter + new investigation task**. T-G-3-05 expanded to assert on 6 quarters × 2 tickers (12 datapoints) AND a new task **T-G-3-11 (Weak-Point Survey)** added at the end of Wave G-3 to fire a 5 × 5 × 3 matrix (75 chat queries) surfacing systematic data-layer gaps the original audit didn't cover.

---

## Compounding (Mandatory)

- **BUG_PATTERNS.md**: add BP-545 through BP-549 (the 5 new patterns identified in the audit's compounding section)
- **HIGH_RISK_PATTERNS.md**: add HR-051/052/053 (3 new patterns)
- **REVIEW_CHECKLIST.md**: add 3 checks (every worker has `depends_on: service_healthy`; every repository SELECT references only existing columns; every LLM prompt forbids pretraining for numerical claims)
- **RULES.md R35**: "Every long-running service that calls postgres/valkey/kafka/an LLM endpoint MUST declare `depends_on: { <dep>: { condition: service_healthy } }` in docker-compose. Workers that need optional deps (e.g. ollama for fallback) MUST wrap startup probes in `@retry_on_startup`."

---

**END OF PLAN PLAN-0093.**

This plan implements the full QA report remediation, gated by a **28-sub-test SLO suite + 8-question chat regression + a 75-query Weak-Point Survey** (T-G-3-11) that fires 5 tickers × 5 metric families × 3 question variants to surface failure modes the original audit could not have found. Verdict reversal (FAIL → PASS_WITH_WARNINGS) is gated by **both** T-G-3-10 (≥ 6/8 useful answers) AND T-G-3-11 (zero HARMFUL across 75 queries) — once both pass, the platform is shippable.
