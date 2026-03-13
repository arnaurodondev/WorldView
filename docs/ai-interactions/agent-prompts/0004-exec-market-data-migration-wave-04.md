# Execution Prompt 0004 — market-data-migration wave 04

## Context (read first)

- **Planning prompt**: `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
- **Planning response (authoritative)**: `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md`

---

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`
- `.claude/agents/architecture-decision-lead.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture pattern
2. `CLAUDE.md` — Claude-specific workflow, diff discipline, logging rules
3. `docs/services/market-data.md` — current state of the target service specification (updated in wave 03)
4. `docs/libs/contracts.md` — CanonicalQuote, CanonicalFundamentals, parsing API
5. `docs/libs/messaging.md` — BaseKafkaConsumer, BaseOutboxDispatcher, ValkeyClient, error hierarchy
6. `docs/libs/storage.md` — ObjectStorage ABC and exception hierarchy
7. `docs/libs/observability.md` — ServiceMetrics and tracing API
8. All architecture ADRs in `docs/architecture/decisions/` — especially the TimescaleDB hypertable decision started in wave 02
9. `docs/ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md`
10. `docs/ai-interactions/agent-responses/0004-response-20260306-market-data-migration-plan.md` — §1 task backlog, Integration Testing and Release sections (MD-029..MD-035)
11. `docs/ai-interactions/BUG_PATTERNS.md` — mandatory for all integration/E2E/release validation tasks

When handing off, explicitly list which `BP-xxx` entries were applied.

---

## Objective

Complete the **final wave** of the Market Data migration: comprehensive integration testing, platform QA, performance validation, full documentation, and release preparation (MD-029 through MD-035).

This is the release gate wave. No new feature code is written. Every task either adds tests, completes documentation, or produces release artifacts. By the end of this wave the service is production-ready: all release gates G1–G14 are verified, every runbook exists, and the deployment is staged for rollout.

At the end of this wave:
- ≥25 container integration tests pass.
- 4 E2E pipeline tests pass (OHLCV, quotes, fundamentals, instrument lifecycle).
- All contract tests pass (Avro backward compatibility, API schema parity).
- Performance benchmarks are executed and documented.
- `docs/services/market-data.md` is complete and authoritative.
- All four lib docs are finalized.
- The TimescaleDB ADR is finalized.
- Four runbooks are created (troubleshooting, deployment, rollback, QA).
- `services/market-data/configs/prod.env.example` is complete.
- The PR description is highly detailed and covers the full migration scope.

---

## Task scope for this wave

**Total tasks: 6** (MD-029, MD-030, MD-032, MD-033, MD-034, MD-035)

### Parallel group A — start simultaneously (all prerequisites from waves 01–03 are complete)

| Task ID | Short title | Depends on |
|---------|-------------|------------|
| MD-029 | Comprehensive service container integration tests | MD-028 + all MD-019..MD-027 complete |
| MD-032 | Comprehensive documentation update | MD-031 complete |
| MD-034 | Avro contract and schema versioning verification | MD-001..MD-003 + MD-022..MD-025 complete |

### Sequential group B — after MD-029 completes

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| MD-030 | MD-029 done | Platform QA end-to-end test scenarios |
| MD-033 | MD-029 done | Performance validation and benchmarking |

### Sequential group C — after all of groups A and B complete

| Task ID | Unlocked by | Short title |
|---------|-------------|-------------|
| MD-035 | MD-029, MD-030, MD-032, MD-033, MD-034 all done | Release preparation and rollback planning |

---

## Why this chunk

**Coherence**: This wave is strictly tests, documentation, and release artifacts. No feature code. Grouping all validation and release tasks in one wave ensures that every decision about the final implementation state is made before any release artifact is produced.

**Dependency fit**: MD-029 (integration tests) must run against the fully wired service from waves 01–03. MD-030 (E2E) and MD-033 (performance) depend on the integration test infrastructure and conftest.py established in MD-029. MD-032 (docs) and MD-034 (contracts) can proceed in parallel with MD-029 since they only read the implementation. MD-035 (release) requires evidence from all other tasks to populate the runbooks and checklist.

**Size**: 6 tasks — within the [1, 20] bound.

**Final wave**: This wave includes the highly detailed PR description requirement per the documentation quality standard.

---

## Implementation instructions

### MD-029 — Comprehensive service container integration tests

1. Use `services/market-data/tests/integration/conftest.py` established in MD-028 (wave 02) as the base fixture. Do not recreate testcontainer setup — extend it.
2. **Migration tests** (`tests/integration/test_migrations.py`):
   - `test_upgrade_head` — run `alembic upgrade head`; assert exit code 0 and no exceptions.
   - `test_downgrade_base` — run `alembic upgrade head` then `alembic downgrade base`; assert clean.
   - `test_hypertable_created` — after `upgrade head`, execute `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'ohlcv_bars'`; assert one row returned.
3. **Repository tests**:
   - `tests/integration/test_ohlcv_repo.py`:
     - `test_ohlcv_bulk_upsert_with_priority` — insert bars from provider A; upsert same bars from higher-priority provider B → verify update; upsert from lower-priority provider C → verify no change.
     - `test_instrument_search` — create 5 instruments with varying flags; verify `InstrumentRepository.search()` filters correctly.
     - `test_quote_upsert` — insert quote; re-insert newer quote for same instrument → verify updated.
   - `tests/integration/test_fundamentals_repo.py`:
     - `test_fundamentals_merge_upsert` — merge-upsert `analyst_consensus`; verify existing fields not wiped when partial update applied.
4. **Consumer integration tests** (one file per consumer; each test produces a real Kafka message and verifies DB state):
   - `tests/integration/test_ohlcv_consumer_integration.py`: upload a JSONL fixture to MinIO → produce an Avro `market.dataset.fetched` message → wait for consumer to process (poll with timeout) → assert bars in DB via `OHLCVRepository` → assert instrument created in DB.
   - `tests/integration/test_quotes_consumer_integration.py`: produce event → assert quote in DB via `QuoteRepository` → assert Valkey key `quote:v1:{instrument_id}` set.
   - `tests/integration/test_fundamentals_consumer_integration.py`: produce event with full 13-section payload → assert data in all relevant tables across 20 DB tables.
5. **API integration tests** (seed DB first, use `TestClient` or `httpx.AsyncClient` against the wired app):
   - `tests/integration/test_ohlcv_api_integration.py` — seed bars → GET `/api/v1/ohlcv/{id}` → verify response matches seeded data.
   - `tests/integration/test_quotes_api_integration.py` — seed quote → GET `/api/v1/quotes/{id}` → verify cache miss fills Valkey → GET again → verify cache hit (DB not queried).
   - `tests/integration/test_fundamentals_api_integration.py` — seed fundamentals → GET each of the 8 section endpoints → verify all return correct data.
6. **Outbox integration test** (`tests/integration/test_outbox.py`):
   - Create an `InstrumentCreated` domain event → commit UoW → assert outbox row exists in DB with status `PENDING` → start dispatcher → assert Kafka message received on `market.instrument.created` topic → assert outbox row status is `SENT`.
7. **Idempotency test** (`tests/integration/test_idempotency.py`):
   - Produce the same `market.dataset.fetched` event twice with the same `event_id` → process both → assert exactly one row in `ingestion_events` and one set of bars in `ohlcv_bars`.
8. **Error path tests** (`tests/integration/test_error_paths.py`):
   - Inject an S3 failure (stop MinIO container) → produce event → verify `RetryableError` raised → verify no commit (no bars in DB) → verify no `ingestion_events` row → restart MinIO → verify consumer recovers and processes successfully on retry.
   - Produce a malformed Avro message → verify `FatalError` → verify `failed_tasks` row created.
9. Mark every integration test with `@pytest.mark.integration`.
10. Target: ≥25 distinct integration test cases across all files.
11. Update `docs/developer-guide/testing.md` (or create it if absent) with the integration test catalog: test file, test name, what it validates, infrastructure required.
12. Run: `cd services/market-data && make test -- tests/integration/ -m integration -v`.

**DoD**: ≥25 integration tests pass with real Kafka, TimescaleDB, MinIO, and Valkey containers; `alembic upgrade head && alembic downgrade base` cycle is clean; testing guide updated.

---

### MD-032 — Comprehensive documentation update

This task finalizes **all** documentation to match the complete implementation. Do not defer any section.

1. **`docs/services/market-data.md`** — perform a systematic section-by-section audit and update:
   - **Overview**: service purpose, high-level architecture, tech stack.
   - **API reference**: all 22 routes with method, path, query params, request body (where applicable), response schema, all possible HTTP status codes, and at least one copy-pasteable curl example per endpoint.
   - **Consumer behaviours**: OHLCV (with Mermaid sequence diagram), quotes (with cache invalidation note), fundamentals (with section-to-table mapping table and Mermaid flowchart). Confirm these match MD-019–MD-021 implementations exactly.
   - **Database schema**: all 26 tables with column names, types, constraints, indexes, and a Mermaid ER diagram covering the full schema (required: ≥3 entities, ≥4 relationships → Mermaid is mandatory).
   - **Caching strategy**: key format `quote:v1:{instrument_id}`, TTL = 5 seconds, invalidation trigger (on quote upsert by consumer), graceful degradation behaviour, `invalidate_many` for batch operations.
   - **Configuration reference**: complete env var table — variable name, type, default value, description, required or optional.
   - **Deployment guide**: startup dependency order, how to verify each dependency is healthy, `readyz` endpoint interpretation.
   - **`## Common Pitfalls`**: at minimum these 3 entries, plus any additional ones discovered during implementation:
     - Naive datetimes: using `datetime.now()` without `tz=timezone.utc` causes silent timezone bugs in TimescaleDB chunk pruning.
     - Unversioned cache keys: omitting the `v1` prefix means schema changes cannot be cache-busted without flushing the entire Valkey keyspace.
     - Dual-writes: writing to DB and publishing to Kafka outside a UoW transaction causes split-brain if the process crashes between the two writes.
2. **`docs/libs/contracts.md`** — add or update:
   - `CanonicalQuote` dataclass: all fields, `QUOTE_SCHEMA_VERSION` constant, `from_dict()`/`to_dict()` signatures.
   - `CanonicalFundamentals` dataclass: all 14 section types, nested handling note.
   - Parsing API: `parse_ohlcv_jsonl()`, `parse_quotes_json()`, `parse_fundamentals_json()`, `ParseError` behaviour, UTF-8/BOM handling note.
3. **`docs/libs/messaging.md`** — add or update:
   - `BaseKafkaConsumer` ABC with abstract methods table (method → when called → what to do → what to return).
   - `BaseOutboxDispatcher` with Mermaid sequence diagram and ABC table.
   - `ValkeyClient` with all 6 method signatures and usage example.
   - Error hierarchy: full inheritance tree.
4. **`docs/libs/storage.md`** — add or update:
   - `ObjectStorage` ABC: all 6 abstract methods, ABC table (method → when called → what to do → what to return).
   - `S3ObjectStorage`: boto3/botocore error mapping to typed exceptions.
   - Exception hierarchy: `StorageError` and all subclasses.
   - `## Common Pitfalls` with ≥3 entries.
5. **`docs/libs/observability.md`** — add or update:
   - `ServiceMetrics`: all 4 metric types, `create_metrics()` factory, `add_prometheus_middleware()`.
   - Tracing: `configure_tracing()`, `get_tracer()`, `add_otel_middleware()`, `shutdown_tracing()`, no-op fallback behaviour.
6. **`docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md`** — finalize the ADR started in wave 02: fill in the final decision, rationale, consequences, and alternatives considered. Assign the correct ADR number from the decisions directory sequence.
7. **`docs/runbooks/market-data-troubleshooting.md`** (create):
   - Common errors and their root causes (e.g., consumer lag spike, Valkey connection failures, S3 permission errors, outbox backlog growth).
   - Recovery procedures for each error type.
   - How to inspect `failed_tasks` table and force-retry a failed task.
   - How to check outbox status (`PENDING`, `SENT`, `DEAD`) and manually resolve DEAD events.
   - Consumer lag monitoring: which Kafka consumer group metrics to watch, alert thresholds.
8. Verify no stale documentation: search for any references to deleted or renamed symbols, endpoints, or config vars — remove or update them.

**DoD**: All 7 documentation artifacts updated/created; `docs/services/market-data.md` is authoritative and complete; all lib docs match final public APIs; ADR finalized; troubleshooting runbook created; no stale references.

---

### MD-034 — Avro contract and schema versioning verification

1. Create `services/market-data/tests/contract/` package with `__init__.py` and `conftest.py` (Schema Registry client fixture using testcontainers or a running registry).
2. Create `services/market-data/tests/contract/test_avro_compatibility.py`:
   - `test_avro_schema_backward_compatible` — register all Avro schemas used by the service (`market.dataset.fetched.v1`, `market.instrument.created.v1`, `market.instrument.updated.v1`) with the Schema Registry in BACKWARD compatibility mode; assert registration succeeds.
   - `test_avro_new_fields_have_defaults` — parse each Avro schema JSON; assert every field added since schema version 1 has a `"default"` defined.
   - `test_avro_no_field_removals` — compare each schema against its previous registered version; assert no fields were removed.
3. Create `services/market-data/tests/contract/test_api_contracts.py`:
   - `test_api_response_schema_matches_doc` — use `TestClient` + FastAPI `app.openapi()` to export the OpenAPI schema; compare response models for all 22 routes against the documented schemas in `docs/services/market-data.md` (spot-check key fields, not full deep equality).
   - `test_api_versioning_prefix` — assert every business endpoint path starts with `/api/v1/`; health endpoints (`/healthz`, `/readyz`, `/metrics`) are excluded.
   - `test_event_envelope_fields` — for each domain event class (`InstrumentCreated`, `InstrumentUpdated`), assert the dataclass has `event_id`, `event_type`, `schema_version`, and `occurred_at` fields.
   - `test_schema_versions_consistent` — assert `OHLCV_SCHEMA_VERSION`, `QUOTE_SCHEMA_VERSION`, and `FUNDAMENTAL_SCHEMA_VERSION` constants in the contracts lib match the corresponding Avro schema `version` field values.
4. Update `docs/contracts/` with a `compatibility-policy.md` file (create if absent) documenting:
   - BACKWARD compatibility mode requirement for all Avro schemas.
   - New fields must have defaults.
   - No field removals or renames on registered schemas.
   - REST API versioning policy (`/api/v1/`, `/api/v2/` for breaking changes).
5. Run: `cd services/market-data && make test -- tests/contract/ -v`.

**DoD**: All 7 contract tests pass, compatibility policy document created in `docs/contracts/`, lint clean.

---

### MD-030 — Platform QA end-to-end test scenarios (after MD-029)

1. Create `services/market-data/tests/e2e/` package with `conftest.py`. The conftest must start a full-stack set of containers (TimescaleDB, Kafka + Schema Registry, MinIO, Valkey) and the market-data service application itself (using `asyncio` lifespan or an in-process `TestClient` against the wired app).
2. **OHLCV pipeline test** (`tests/e2e/test_ohlcv_pipeline.py` — `@pytest.mark.slow`):
   - Upload a multi-row OHLCV JSONL fixture to MinIO.
   - Produce a `market.dataset.fetched` Avro message referencing the MinIO object.
   - Use `asyncio.wait_for` to poll the `ohlcv_bars` table until bars appear (timeout: 30 seconds).
   - Query `GET /api/v1/ohlcv/{instrument_id}` and assert response matches uploaded fixture rows.
3. **Quotes pipeline test** (`tests/e2e/test_quotes_pipeline.py` — `@pytest.mark.slow`):
   - Upload a quote JSON fixture to MinIO.
   - Produce event. Wait for quote to appear in DB (poll with timeout).
   - Query `GET /api/v1/quotes/{instrument_id}` — assert 200 response with correct data.
   - Query again — assert Valkey cache hit (instrument the Valkey mock or check TTL metadata).
4. **Fundamentals pipeline test** (`tests/e2e/test_fundamentals_pipeline.py` — `@pytest.mark.slow`):
   - Upload a full 13-section fundamentals JSON fixture to MinIO.
   - Produce event. Wait for data to appear in DB.
   - Query each of the 8 per-section fundamentals endpoints — assert data matches fixture across all tables.
5. **Instrument lifecycle test** (`tests/e2e/test_instrument_lifecycle.py` — `@pytest.mark.slow`):
   - Trigger an OHLCV ingestion for a symbol that does not yet exist in the DB.
   - Assert a `market.instrument.created` Kafka message appears on that topic.
   - Trigger a second OHLCV ingestion for the same symbol with updated data.
   - Assert a `market.instrument.updated` Kafka message appears.
6. Update `docs/services/market-data.md` QA scenarios section with the E2E test catalog: test name, what it exercises, expected outcome.
7. Create `docs/runbooks/market-data-qa-runbook.md` with: pre-QA environment setup checklist, manual QA steps for each pipeline (OHLCV, quotes, fundamentals, instrument lifecycle), how to interpret consumer lag during QA, how to reset test data between QA runs.
8. Run: `cd services/market-data && make test -- tests/e2e/ -m slow -v`.

**DoD**: 4 E2E pipeline tests pass, `market-data-qa-runbook.md` created, QA scenarios section in `docs/services/market-data.md` updated.

---

### MD-033 — Performance validation and benchmarking (after MD-029)

1. Create `services/market-data/tests/performance/` package with `conftest.py` (reuse integration testcontainer fixtures from MD-029 conftest).
2. **Consumer throughput test** (`tests/performance/test_ohlcv_throughput.py` — `@pytest.mark.slow`):
   - Produce 10,000 OHLCV bars (split across multiple events) to Kafka.
   - Measure wall-clock time from first message produced to last bar confirmed in DB.
   - Assert throughput ≥ 1,000 bars/second (warn and document if below, do not fail CI).
   - Log actual throughput value in the test output.
3. **API latency test** (`tests/performance/test_api_latency.py` — `@pytest.mark.slow`):
   - Seed 100,000 OHLCV bars in DB (direct insert via repository).
   - Make 100 sequential `GET /api/v1/ohlcv/{instrument_id}` requests with a realistic date-range filter.
   - Compute p50, p95, p99 latency.
   - Assert p95 < 100ms (warn and document if above, do not fail CI).
4. **TimescaleDB chunk pruning test** (`tests/performance/test_query_performance.py` — `@pytest.mark.slow`):
   - Seed bars across 3 months of data.
   - Execute `EXPLAIN ANALYZE` on a query targeting a single 7-day window.
   - Assert the query plan contains `Custom Scan (ChunkAppend)` and that only the relevant chunks are scanned (not all).
5. **Cache performance test** (included in `test_api_latency.py`):
   - Measure quotes API latency with cache hit (Valkey warm) vs cache miss (Valkey cold).
   - Assert cache-hit median latency < 5ms.
   - Document both measurements in the performance report.
6. **Bulk upsert benchmark** (`tests/performance/test_bulk_upsert.py` — `@pytest.mark.slow`):
   - Bulk upsert 5,000 bars via `OHLCVRepository.bulk_upsert_with_priority()`.
   - Record and log total time and rows/second.
7. Create `docs/services/market-data-performance.md` (new file) with:
   - Test environment specs (CPU, RAM, disk type, Kafka/DB container versions).
   - Benchmark results: consumer throughput, API p50/p95/p99, cache hit vs miss latency, bulk upsert rate.
   - TimescaleDB chunk pruning confirmation (include a sanitized EXPLAIN ANALYZE snippet).
   - Tuning recommendations for production (connection pool sizes, Kafka batch sizes, TimescaleDB chunk interval).
8. Run: `cd services/market-data && make test -- tests/performance/ -m slow -v`.

**DoD**: 4 benchmark tests execute without errors; results documented in `docs/services/market-data-performance.md`; throughput and latency warnings noted if targets not met (non-blocking for release).

---

### MD-035 — Release preparation and rollback planning (after MD-029, MD-030, MD-032, MD-033, MD-034)

1. Create `docs/runbooks/market-data-deployment.md` with:
   - **Pre-flight checklist**: all release gate tests pass (G1–G8 confirmed), Avro schemas registered with BACKWARD compatibility in production Schema Registry, monitoring dashboards configured, on-call engineer notified.
   - **6-phase staged rollout**:
     - Phase 1 — DB migrations only: run `alembic upgrade head` against production DB. Verify: `SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'` matches expected count.
     - Phase 2 — Service deployed, consumers disabled (API-only mode): deploy new image with all 3 consumers disabled via feature flag or env var. Verify: `GET /readyz` returns 200, `GET /metrics` returns Prometheus text, all API routes respond (even with empty data).
     - Phase 3 — Enable OHLCV consumer: set `OHLCV_CONSUMER_ENABLED=true`. Monitor Kafka consumer group lag for `market-data-ohlcv`. Verify: bars appear in DB within expected latency window.
     - Phase 4 — Enable quotes consumer: set `QUOTES_CONSUMER_ENABLED=true`. Monitor `market-data-quotes` lag. Verify: quotes appear in DB and Valkey cache is populated.
     - Phase 5 — Enable fundamentals consumer: set `FUNDAMENTALS_CONSUMER_ENABLED=true`. Monitor `market-data-fundamentals` lag. Verify: fundamentals data appears across expected tables.
     - Phase 6 — Enable outbox dispatcher: set `OUTBOX_DISPATCHER_ENABLED=true`. Verify: `market.instrument.created` messages appear on Kafka when new instruments are ingested.
   - **Per-phase canary verification steps**: exact log messages to check (structlog JSON fields), exact Prometheus metric names to verify, exact Kafka consumer group lag threshold to watch.
2. Create `docs/runbooks/market-data-rollback.md` with per-phase rollback steps:
   - Phase 6 rollback: set `OUTBOX_DISPATCHER_ENABLED=false`; drain in-flight dispatches (wait 30s); verify outbox table stops draining.
   - Phase 5 rollback: set `FUNDAMENTALS_CONSUMER_ENABLED=false`; reset consumer group: `kafka-consumer-groups.sh --reset-offsets --group market-data-fundamentals --to-latest`.
   - Phase 4 rollback: same for `market-data-quotes`.
   - Phase 3 rollback: same for `market-data-ohlcv`.
   - Phase 2 rollback: redeploy previous image tag.
   - Phase 1 rollback: run `alembic downgrade -1`; verify tables removed.
   - Known risk: TimescaleDB hypertable conversion (migration 002) cannot be reversed to LIST partitioning without data migration — document this explicitly and note the manual recovery procedure.
3. Update `services/market-data/configs/prod.env.example` with all environment variables from `config.py` — every variable must have a commented description, the expected production value format, and whether it is required or optional.

**DoD**: `market-data-deployment.md` with 6-phase rollout and per-phase canary steps created; `market-data-rollback.md` with per-phase rollback procedures created; `prod.env.example` updated with all config vars; all release gates G1–G14 assessed and documented.

---

## Constraints

- Do not implement any new feature code in this wave. If a bug is discovered during testing, create a tracked issue and fix the bug before re-running tests — do not skip failing tests or mark them `xfail` without a filed issue.
- Do not modify lib or service source code unless fixing a confirmed bug found during testing.
- Performance targets (G9, G10) are advisory warnings, not blocking failures — document actual results regardless of whether targets are met.
- All integration and E2E tests must use real testcontainers — no mocks for infrastructure in these test tiers.
- All new test files must be in the correct directory and marked with the correct pytest marker (`@pytest.mark.integration` or `@pytest.mark.slow`).
- The TimescaleDB hypertable downgrade limitation must be explicitly documented in the rollback runbook.

## Regression guardrails (compounding, mandatory)

- Integration and E2E suites in this wave must apply [BP-010], [BP-012], and [BP-013]: valid healthchecks for worker-style services, scalar polling in async loops, bounded deadlines, and deterministic success criteria.
- For container-based validation paths, apply [BP-011] to verify runtime schemas/assets are present in built images before executing test suites.
- For migration and DB consistency checks, apply [BP-007] and [BP-008] so release evidence includes `NULL` uniqueness semantics and migration/model parity verification.
- For dispatcher/outbox release checks, apply [BP-001] and [BP-009] explicitly in release QA evidence.

---

## Incremental quality gates (mandatory)

For each task ID, before moving to the next task, run and pass:

1. Targeted test command(s) for the task's changed behavior.
2. `ruff check` on changed paths only.
3. `mypy` on changed package/module only.

- No deferred fixes: do not carry ruff/mypy/test failures into later tasks.
- If the same failure repeats twice, capture root cause + remediation in handoff evidence.

## Required tests

### Contract tests

```bash
cd services/market-data && make test -- tests/contract/ -v
```

### Integration tests (Docker required)

```bash
cd services/market-data && make test -- tests/integration/ -m integration -v
```

### E2E / platform QA (Docker + slow markers)

```bash
cd services/market-data && make test -- tests/e2e/ -m slow -v
```

### Performance benchmarks

```bash
cd services/market-data && make test -- tests/performance/ -m slow -v
```

### Full release gate

```bash
cd services/market-data && make test && make lint
./scripts/lint.sh
mypy services/market-data/src/ --strict
```

**Pass criteria (release gates):**

| Gate | Requirement | Blocking |
|------|-------------|---------|
| G1 | All unit tests pass (≥60% coverage) | Yes |
| G2 | ≥25 integration tests pass | Yes |
| G3 | All contract tests pass (Avro backward compat, API schema match) | Yes |
| G4 | `ruff check` zero errors | Yes |
| G5 | `mypy --strict` zero errors | Yes |
| G6 | `alembic upgrade head && alembic downgrade base` clean | Yes |
| G7 | Avro schemas backward-compatible with Schema Registry | Yes |
| G8 | API endpoint parity: 22 routes (3 health/infra + 3 instruments + 4 OHLCV + 3 quotes + 9 fundamentals/securities) | Yes |
| G9 | Consumer throughput ≥ 1,000 bars/second | Warn only |
| G10 | API p95 < 100ms | Warn only |
| G11 | No critical/high-severity open bugs | Yes |
| G12 | Documentation up to date (all 8 quality criteria met) | Yes |
| G13 | Deployment runbook reviewed and approved | Yes |
| G14 | Rollback procedure documented and verified in staging | Yes |

---

## Documentation requirements

All documentation updated in this wave must meet the full **Documentation quality standard** (8 criteria). This is the final wave — every doc must be complete and authoritative before the PR is merged.

| Change type | File to update |
|-------------|---------------|
| Complete API reference update | `docs/services/market-data.md` — all 22 routes, all consumer behaviours, full DB schema ER diagram, caching strategy, config reference, `## Common Pitfalls` |
| Contracts lib doc finalized | `docs/libs/contracts.md` — CanonicalQuote, CanonicalFundamentals, parsing API |
| Messaging lib doc finalized | `docs/libs/messaging.md` — BaseKafkaConsumer ABC table, BaseOutboxDispatcher Mermaid + ABC table, ValkeyClient, error hierarchy |
| Storage lib doc finalized | `docs/libs/storage.md` — ObjectStorage ABC table, exception hierarchy, `## Common Pitfalls` |
| Observability lib doc finalized | `docs/libs/observability.md` — ServiceMetrics, tracing API |
| ADR finalized | `docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md` — final decision, rationale, consequences |
| Troubleshooting runbook | `docs/runbooks/market-data-troubleshooting.md` (create) |
| Deployment runbook | `docs/runbooks/market-data-deployment.md` (create) |
| Rollback runbook | `docs/runbooks/market-data-rollback.md` (create) |
| QA runbook | `docs/runbooks/market-data-qa-runbook.md` (create) |
| Performance report | `docs/services/market-data-performance.md` (create) |
| Prod env template | `services/market-data/configs/prod.env.example` |
| Contract compatibility policy | `docs/contracts/compatibility-policy.md` (create) |
| Integration test catalog | `docs/developer-guide/testing.md` |

**Documentation quality standard** — all 8 criteria must be confirmed ✓ or explicitly N/A with justification before this wave is done:

1. **Accuracy** — every endpoint path, field name, event type, config var, cache key pattern, and error code in all docs must match the final implementation exactly.
2. **Diagrams for non-trivial flows** — the full DB schema (26 tables) requires a Mermaid ER diagram; the consumer flows (already added in waves 02–03) must be verified correct; the app startup sequence must be present.
3. **Realistic code examples** — every public class and function across all updated docs must have a working usage example.
4. **Abstract methods documented** — `ObjectStorage` ABC table and `BaseKafkaConsumer` ABC table must be present and accurate.
5. **Common Pitfalls section** — `docs/services/market-data.md`, `docs/libs/storage.md`, and `docs/libs/messaging.md` must each have `## Common Pitfalls` with ≥3 concrete entries.
6. **Lib docs updated** — this wave finalizes all lib docs; every `docs/libs/<lib>.md` must be updated.
7. **Service doc reflects final state** — `docs/services/market-data.md` must be a complete authoritative reference after this wave.
8. **No orphan documentation** — remove any documentation for features that were not implemented (e.g., ESG section ingestion is intentionally deferred; docs must reflect this).

**Mandatory instruction**: If testing reveals any discrepancy between the implementation and existing documentation, correct the documentation immediately in this wave — do not carry forward inaccurate docs.

---

## Required handoff evidence

At wave completion, report all of the following:

### 1. Changed files (complete list)

List every file created or modified, with a one-line description of the change.

### 2. Tests run and results

```
unit tests:                 X tests, X passed, 0 failed
integration tests:          X tests, X passed, 0 failed  (must be ≥25)
contract tests:             X tests, X passed, 0 failed
e2e tests:                  X tests, X passed, 0 failed  (must be 4)
performance benchmarks:     X benchmarks executed, results: [throughput], [p95 latency]
./scripts/lint.sh:          exit code 0
mypy --strict:              0 errors
```

### 3. Release gate checklist (G1–G14)

| Gate | Requirement | Status | Evidence |
|------|-------------|--------|---------|
| G1 | Unit tests ≥60% coverage | ✓ / ⚠️ / ✗ | |
| G2 | ≥25 integration tests pass | ✓ / ⚠️ / ✗ | |
| G3 | All contract tests pass | ✓ / ⚠️ / ✗ | |
| G4 | ruff check zero errors | ✓ / ⚠️ / ✗ | |
| G5 | mypy --strict zero errors | ✓ / ⚠️ / ✗ | |
| G6 | alembic upgrade/downgrade cycle clean | ✓ / ⚠️ / ✗ | |
| G7 | Avro schemas backward-compatible | ✓ / ⚠️ / ✗ | |
| G8 | 22 API routes registered | ✓ / ⚠️ / ✗ | |
| G9 | Consumer throughput ≥1,000 bars/sec (warn) | ✓ / ⚠️ | actual: X bars/sec |
| G10 | API p95 < 100ms (warn) | ✓ / ⚠️ | actual: Xms |
| G11 | No critical/high-severity open bugs | ✓ / ⚠️ / ✗ | |
| G12 | Documentation up to date (8 quality criteria) | ✓ / ⚠️ / ✗ | |
| G13 | Deployment runbook reviewed | ✓ / ⚠️ / ✗ | |
| G14 | Rollback procedure documented | ✓ / ⚠️ / ✗ | |

### 4. Documentation changed (exact files + what was updated)

Example format:
- `docs/services/market-data.md` — complete API reference (all 22 routes), OHLCV/quotes/fundamentals consumer sections verified, DB schema ER diagram added, caching section updated, config reference table updated, `## Common Pitfalls` with 3+ entries.
- `docs/libs/contracts.md` — CanonicalQuote and CanonicalFundamentals finalized; parsing API reference added.
- `docs/libs/messaging.md` — BaseKafkaConsumer ABC table, outbox Mermaid diagram, ValkeyClient API, error hierarchy finalized.
- `docs/libs/storage.md` — ObjectStorage ABC table, exception hierarchy, `## Common Pitfalls` added.
- `docs/libs/observability.md` — ServiceMetrics and tracing API finalized.
- `docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md` — ADR finalized with decision, rationale, consequences.
- `docs/runbooks/market-data-troubleshooting.md` — created.
- `docs/runbooks/market-data-deployment.md` — created.
- `docs/runbooks/market-data-rollback.md` — created.
- `docs/runbooks/market-data-qa-runbook.md` — created.
- `docs/services/market-data-performance.md` — created.
- `docs/contracts/compatibility-policy.md` — created.
- `docs/developer-guide/testing.md` — integration test catalog added.
- `services/market-data/configs/prod.env.example` — all config vars documented.

### 5. Unresolved blockers

List anything that could not be implemented as specified and why. State `none` if there are no blockers.

### 6. Documentation quality checklist

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Accuracy — all endpoints, fields, event types, config vars, cache keys match implementation | ✓ / ⚠️ / N/A | |
| 2 | Diagrams for non-trivial flows (DB ER diagram, consumer flows, startup sequence) | ✓ / ⚠️ / N/A | List diagram titles |
| 3 | Realistic code examples — every public class/function has working usage example | ✓ / ⚠️ / N/A | |
| 4 | Abstract methods documented — ObjectStorage and BaseKafkaConsumer ABC tables accurate | ✓ / ⚠️ / N/A | |
| 5 | Common Pitfalls — market-data.md, messaging.md, storage.md each have ≥3 entries | ✓ / ⚠️ / N/A | |
| 6 | Lib docs updated — all 4 lib docs finalized | ✓ / ⚠️ / N/A | List files |
| 7 | Service doc reflects final state — market-data.md is authoritative and complete | ✓ / ⚠️ / N/A | |
| 8 | No orphan documentation — deferred features (ESG) noted as out of scope, not documented as implemented | ✓ / ⚠️ / N/A | |

### 7. Commit message proposal

```
feat(market-data): complete integration tests, QA pipelines, docs, and release preparation (MD-029..MD-035)

Implement ≥25 container integration tests (consumers, repositories, API, outbox, idempotency,
error paths); 4 E2E pipeline tests (OHLCV, quotes, fundamentals, instrument lifecycle);
performance benchmarks with TimescaleDB chunk-pruning verification. Complete all documentation:
full API reference, consumer diagrams, ER diagram, caching guide, troubleshooting and
deployment runbooks. Add contract compatibility tests for Avro schemas + REST API. All release
gates G1–G8 pass.
```

### 8. Highly detailed PR description (final wave — required)

```markdown
## Summary

This PR completes the full market-data service migration (scope `market-data-migration`, prompt ID 0004). It delivers:

- All 35 implemented tasks (MD-001–MD-031) from waves 01–03, plus wave 04 testing, documentation, and release tasks (MD-029–MD-035).
- A fully working market-data microservice: 3 Kafka consumers, 22 REST endpoints, Valkey caching, transactional outbox, TimescaleDB hypertable.

## Task IDs Covered

**Wave 01 (foundation):** MD-001, MD-002, MD-003, MD-004, MD-005, MD-006, MD-007, MD-008, MD-009, MD-010, MD-011, MD-012, MD-013
**Wave 02 (DB/infra):** MD-014, MD-015, MD-016, MD-017, MD-018, MD-027, MD-028
**Wave 03 (app layer):** MD-019, MD-020, MD-021, MD-022, MD-023, MD-024, MD-025, MD-026, MD-031
**Wave 04 (testing/docs/release):** MD-029, MD-030, MD-032, MD-033, MD-034, MD-035

## Grouped Changed Files

### Shared Libraries
- `libs/contracts/src/contracts/canonical/quotes.py` — CanonicalQuote
- `libs/contracts/src/contracts/canonical/fundamentals.py` — CanonicalFundamentals + 14 section types
- `libs/contracts/src/contracts/parsing.py` — JSONL/JSON parsers + ParseError
- `libs/messaging/src/messaging/errors.py` — RetryableError/FatalError hierarchy
- `libs/messaging/src/messaging/consumer.py` — BaseKafkaConsumer (async, asyncio.to_thread)
- `libs/messaging/src/messaging/producer.py` — KafkaProducerConfig + build_serializing_producer
- `libs/messaging/src/messaging/outbox.py` — BaseOutboxDispatcher with lease-based dispatch
- `libs/messaging/src/messaging/valkey.py` — ValkeyClient
- `libs/storage/src/storage/object_storage.py` — ObjectStorage ABC + S3ObjectStorage
- `libs/storage/src/storage/exceptions.py` — storage exception hierarchy
- `libs/storage/src/storage/health.py` — check_storage_health
- `libs/observability/src/observability/metrics.py` — ServiceMetrics + Prometheus middleware
- `libs/observability/src/observability/tracing.py` — configure_tracing + OTel middleware

### Market-Data Service — Domain
- `services/market-data/src/market_data/domain/enums.py`
- `services/market-data/src/market_data/domain/entities.py`
- `services/market-data/src/market_data/domain/value_objects.py`
- `services/market-data/src/market_data/domain/events.py`
- `services/market-data/src/market_data/domain/errors.py`

### Market-Data Service — Infrastructure / DB
- `services/market-data/src/market_data/infrastructure/db/base.py`
- `services/market-data/src/market_data/infrastructure/db/models/` (securities, instruments, ohlcv, quotes, fundamentals/*, infrastructure)
- `services/market-data/alembic/env.py`
- `services/market-data/alembic/versions/001_initial_schema.py`
- `services/market-data/alembic/versions/002_timescaledb_hypertable.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/` (all repositories)
- `services/market-data/src/market_data/infrastructure/db/uow.py`
- `services/market-data/src/market_data/infrastructure/db/session.py`
- `services/market-data/src/market_data/infrastructure/db/queries/ohlcv_queries.py`
- `services/market-data/src/market_data/infrastructure/cache/quote_cache.py`

### Market-Data Service — Messaging
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
- `services/market-data/src/market_data/infrastructure/messaging/outbox/dispatcher.py`

### Market-Data Service — API
- `services/market-data/src/market_data/api/schemas/instruments.py`
- `services/market-data/src/market_data/api/schemas/ohlcv.py`
- `services/market-data/src/market_data/api/schemas/quotes.py`
- `services/market-data/src/market_data/api/schemas/fundamentals.py`
- `services/market-data/src/market_data/api/schemas/securities.py`
- `services/market-data/src/market_data/api/routers/instruments.py`
- `services/market-data/src/market_data/api/routers/ohlcv.py`
- `services/market-data/src/market_data/api/routers/quotes.py`
- `services/market-data/src/market_data/api/routers/fundamentals.py`
- `services/market-data/src/market_data/api/routers/securities.py`
- `services/market-data/src/market_data/api/dependencies.py`
- `services/market-data/src/market_data/app.py` (full lifespan rewrite)

### Market-Data Service — Tests
- `services/market-data/tests/unit/` (35+ unit test files covering all components)
- `services/market-data/tests/integration/conftest.py` + 9 integration test files (≥25 test cases)
- `services/market-data/tests/e2e/conftest.py` + 4 E2E pipeline test files
- `services/market-data/tests/performance/conftest.py` + 4 benchmark files
- `services/market-data/tests/contract/conftest.py` + 2 contract test files

### Documentation
- `docs/services/market-data.md` (major update — complete API reference, consumer diagrams, ER diagram, caching, config, Common Pitfalls)
- `docs/libs/contracts.md` (finalized)
- `docs/libs/messaging.md` (finalized)
- `docs/libs/storage.md` (finalized)
- `docs/libs/observability.md` (finalized)
- `docs/architecture/decisions/XXXX-timescaledb-hypertable-vs-list-partitioning.md` (new ADR)
- `docs/runbooks/market-data-troubleshooting.md` (new)
- `docs/runbooks/market-data-deployment.md` (new)
- `docs/runbooks/market-data-rollback.md` (new)
- `docs/runbooks/market-data-qa-runbook.md` (new)
- `docs/services/market-data-performance.md` (new)
- `docs/contracts/compatibility-policy.md` (new)
- `docs/developer-guide/testing.md` (integration test catalog added)
- `services/market-data/configs/prod.env.example` (all config vars)

## Test / Lint / Type Evidence

| Gate | Command | Result |
|------|---------|--------|
| Unit tests | `pytest tests/unit/` | ✅ Pass |
| Integration tests | `pytest -m integration tests/integration/` | ✅ ≥25 pass |
| Contract tests | `pytest tests/contract/` | ✅ Pass |
| E2E tests | `pytest -m slow tests/e2e/` | ✅ 4 pipeline pass |
| Ruff lint | `ruff check` | ✅ 0 errors |
| MyPy strict | `mypy src/ --strict` | ✅ 0 errors |
| Alembic cycle | `alembic upgrade head && alembic downgrade base` | ✅ Clean |

## Docs / ADR Updates

- ADR created for TimescaleDB hypertable decision (vs LIST partitioning)
- `docs/services/market-data.md` fully updated with all endpoints, consumers, schema, caching, config, and Common Pitfalls
- All four lib docs updated to reflect final public APIs
- 4 runbooks created (troubleshooting, deployment, rollback, QA)
- Performance report created with benchmark results and tuning recommendations

## Compatibility Notes

- All Avro schemas registered with BACKWARD compatibility mode in Schema Registry
- REST API versioned at `/api/v1/` — breaking changes require a new `/api/v2/` prefix
- Legacy LIST partitioning replaced with TimescaleDB hypertable (migration 002 handles conversion; downgrade path documented but is destructive — see rollback runbook)
- Outbox Decimal/UUID serialization bug (from legacy) fixed in `BaseOutboxDispatcher`
- Fundamentals field mapping duplicate-key bug (from legacy) fixed in `FundamentalsConsumer`

## Risks

- TimescaleDB extension must be available in the production PostgreSQL instance before Phase 1 of the rollout
- Schema Registry must support BACKWARD compatibility mode for `instrument.created.v1` and related schemas
- Consumer throughput benchmark is hardware-dependent; results are documented with test environment specs
- TimescaleDB hypertable migration (002) cannot be reversed to LIST partitioning without a full data migration — this is explicitly documented in the rollback runbook

## Rollback

Phase-by-phase rollback documented in `docs/runbooks/market-data-rollback.md`:
1. Disable consumers via feature flags (per-phase, reversible)
2. Redeploy previous image tag (Phase 2 rollback)
3. `alembic downgrade -1` for migration rollback (Phase 1 rollback; TimescaleDB hypertable caveat applies)
4. Consumer group reset: `kafka-consumer-groups.sh --reset-offsets --to-latest`
5. Full runbook verified in staging before production rollout

## Follow-ups (out of scope for this PR)

- Historical backfill mechanism (known limitation, documented in `docs/services/market-data.md`)
- ESG scores ingestion (intentionally deferred — `FundamentalsConsumer` silently skips ESG section by design; documented)
- Monitoring dashboard setup (infra team dependency)
- OpenTelemetry collector deployment (infra dependency)
```

---

## Definition of done

- [ ] MD-029: ≥25 integration tests pass with real Kafka, TimescaleDB, MinIO, and Valkey containers; `alembic upgrade head && alembic downgrade base` cycle clean; all test tiers (migration, repository, consumer, API, outbox, idempotency, error paths) covered; integration test catalog in `docs/developer-guide/testing.md`.
- [ ] MD-030: 4 E2E pipeline tests pass (OHLCV, quotes, fundamentals, instrument lifecycle), all marked `@pytest.mark.slow`; `docs/runbooks/market-data-qa-runbook.md` created; QA scenarios section in `docs/services/market-data.md` updated.
- [ ] MD-032: `docs/services/market-data.md` complete with all 22 API routes, consumer diagrams, full DB schema ER diagram, caching section, config reference, `## Common Pitfalls`; all 4 lib docs finalized; TimescaleDB ADR finalized; `docs/runbooks/market-data-troubleshooting.md` created.
- [ ] MD-033: 4 performance benchmark files execute without errors; results documented in `docs/services/market-data-performance.md` with test environment specs; throughput and latency results recorded (warnings noted if targets not met).
- [ ] MD-034: 7 contract tests pass (Avro backward compat, API schema match, event envelope fields, schema version consistency); `docs/contracts/compatibility-policy.md` created.
- [ ] MD-035: `docs/runbooks/market-data-deployment.md` created with 6-phase staged rollout and per-phase canary steps; `docs/runbooks/market-data-rollback.md` created with per-phase rollback procedures; `services/market-data/configs/prod.env.example` updated with all config vars.
- [ ] All release gates G1–G8 confirmed ✓ (G9, G10 — documented with actual results, warn if below target).
- [ ] ≥25 integration tests pass.
- [ ] 4 E2E pipeline tests pass.
- [ ] Performance benchmarks executed and documented.
- [ ] All 4 runbooks created (troubleshooting, deployment, rollback, QA).
- [ ] `docs/services/market-data.md` includes `## Common Pitfalls` with ≥3 entries.
- [ ] `docs/libs/messaging.md` and `docs/libs/storage.md` each include `## Common Pitfalls` with ≥3 entries.
- [ ] All 4 lib docs updated and finalized.
- [ ] TimescaleDB ADR finalized with correct ADR number.
- [ ] `services/market-data/configs/prod.env.example` complete.
- [ ] Documentation quality gate: all 8 criteria confirmed ✓ or N/A with justification — no criterion left blank.
- [ ] `./scripts/lint.sh` passes with zero errors.
- [ ] `mypy services/market-data/src/ --strict` passes with zero errors.
- [ ] Commit message proposal included in handoff evidence.
- [ ] Highly detailed PR description included in handoff evidence (final wave requirement).
