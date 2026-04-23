# Bug Patterns & Post-Mortems

> **Purpose**: A living knowledge base of bugs encountered during development.
> AI agents MUST read this file before implementing any component that matches
> the "Affected areas" column in the index. Prompt authors SHOULD reference
> pattern IDs (e.g., `BP-001`) when writing implementation instructions to
> prevent recurrence.

---

## How to use this file

1. **Before implementing**: scan the index below for categories matching your
   task (e.g., "Kafka", "outbox", "serializer"). Read the full entry for any match.
2. **When you hit a runtime error**: search this file for the error message string
   before debugging from scratch.
3. **After fixing a new bug**: add an entry here and update any affected prompts,
   linking back to the pattern ID.

---

## Quick-reference index

| ID | Category | Symptom (error message or behaviour) | Affected areas |
|----|----------|---------------------------------------|----------------|
| [BP-184](#bp-184) | Scheduler / provider registry | S2 scheduler creates tasks for providers whose adapters are not registered (`ProviderRegistry`) — tasks burn all retries and permanently FAIL; creates noise in failed-task counts | `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`; any service whose scheduler creates tasks without validating provider registration |
| [BP-185](#bp-185) | Content ingestion / rate limiting | S4 `TokenBucket` built fresh per `_build_adapter()` call — in-memory, not shared across worker processes; multiple workers multiply effective rate limit (N workers × 55 req/min for Finnhub = N×55 effective) | `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py:_build_adapter()`; any service with per-call rate limiter construction under concurrent workers |
| [BP-186](#bp-186) | Content ingestion / startup | S4 missing startup validators for `finnhub_api_key`, `newsapi_key`, `eodhd_api_key` — empty keys: task creation succeeds, HTTP 401 at runtime, task retries then FAILS with no early operator warning | `services/content-ingestion/src/content_ingestion/config.py`; any service with optional API keys whose absence silently degrades ingestion |
| [BP-182](#bp-182) | Canonical serializer / OHLCV | `int() argument must be a string, a bytes-like object or a real number, not 'NoneType'` — EODHD `volume: null` bars crash `CanonicalOHLCVBar.from_dict()`, task marked FAILED | `libs/contracts/src/contracts/canonical/ohlcv.py`; any `from_dict` with `int(d["volume"])` |
| [BP-176](#bp-176) | Observability / Alertmanager | Alertmanager receiver has no notification channels — all alerts fire and are silently discarded | `infra/alertmanager/alertmanager.yml` default receiver; any new Alertmanager config |
| [BP-175](#bp-175) | Observability / Prometheus | Prometheus scrape target uses host-mapped port instead of container-internal port — `target: "service:8001"` fails because within Docker network containers expose their internal port, not the host-mapped one | `infra/prometheus/prometheus.yml` scrape targets; any new service added to Prometheus scrape config |
| [BP-174](#bp-174) | Observability / Prometheus | Dead metric definition — `Counter`/`Gauge`/`Histogram` defined at module level but `.inc()`/`.set()`/`.observe()` never called anywhere; metric emits no data | S5 `content-store`, S6 `nlp-pipeline`, S8 `rag-chat` custom metrics modules; any service that copies a metrics file without wiring call sites |
| [BP-173](#bp-173) | Observability / Prometheus | `libs/observability` `create_metrics()` isolated `CollectorRegistry` — all shared-lib metrics invisible to Prometheus; `generate_latest()` uses the global `REGISTRY`, not the isolated one | `libs/observability/src/observability/metrics.py:52`; all services using `create_metrics()` |
| [BP-161](#bp-161) | FastAPI / security | Unannotated `UUID` path function parameter silently maps to **query string** — allows callers to pass arbitrary `?tenant_id=<uuid>` and impersonate any tenant | Any FastAPI endpoint with `tenant_id: UUID` or `user_id: UUID` without `Header()`, `Path()`, or `Depends()` annotation; fix: read from `request.state.tenant_id` (set by InternalJWTMiddleware) |
| [BP-160](#bp-160) | Frontend / Testing | `TypeError: localStorage.clear is not a function` in Vitest under Node.js 22+ | Any Vitest test that calls `localStorage.clear()` in `beforeEach` |
| [BP-159](#bp-159) | FastAPI middleware / Starlette | `app.add_middleware()` creates a DIFFERENT instance than `MiddlewareClass(app, ...)` — `startup()` on the stored instance never populates `self._public_key` on the serving instance | Any middleware that calls startup() to load external keys/config and stores them in `self.*` |
| [BP-149](#bp-149) | Kafka consumer / idempotency | Silent duplicate artifacts (sections, chunks, mentions) accumulate when entity PKs are non-deterministic UUIDs — ON CONFLICT on PK never fires on re-delivery | S6 `ArticleProcessingConsumer`, any consumer where domain entity IDs are generated with `new_uuid7()` |
| [BP-150](#bp-150) | Kafka / message retention | Services down >7 days silently lose the backlog — Kafka default 7-day retention causes consumer group to start from oldest *remaining* message after extended downtime | All pipeline-critical topics: `content.article.stored.v1`, `market.dataset.fetched`, `nlp.article.enriched.v1` |
| [BP-138](#bp-138) | Kafka consumer / type coercion | `TypeError: float() argument must be a string or a number, not 'NoneType'` — consumer dead-letters on non-numeric field | Any consumer extracting float fields from Avro events (market_impact_score, etc.) |
| [BP-139](#bp-139) | Frontend WebSocket / JSON | Uncaught `SyntaxError` in `onmessage` handler crashes React tree on malformed frame | Any React hook wrapping `WebSocket.onmessage` that calls `JSON.parse` |
| [BP-140](#bp-140) | Config wiring / dead settings | Settings fields defined in `config.py` but never read — operators believe they can tune behavior via env vars but the code ignores them | Any new `Settings` field used to construct domain objects (ValueObjects, thresholds) |
| [BP-141](#bp-141) | Shared-session rollback / repo layer | `await self._session.rollback()` inside an exception handler within a repo `save()` poisons the outer `async with session_factory()` context and can cause subsequent write loss | Any repository method that catches IntegrityError and calls session.rollback() directly |
| [BP-001](#bp-001) | Kafka / outbox serialization | `"a bytes-like object is required, not 'OutboxKafkaValue'"` | Any service implementing `BaseOutboxDispatcher` |
| [BP-002](#bp-002) | Env loading / Docker Compose | Service starts but reads wrong config (wrong DB URL, wrong hostnames, 500 errors at runtime) | All services — `Makefile`, `docker-compose.yml`, `docker-compose.test.yml` |
| [BP-003](#bp-003) | pytest-asyncio / session fixtures | `RuntimeError: Event loop is closed` at fixture teardown | Any service with `scope="session"` async fixtures (`e2e_client`, `_e2e_engine`) |
| [BP-004](#bp-004) | pytest fixture resolution | `fixture 'settings' not found` — `ERROR at setup` instead of SKIP | Integration tests in any service that need a `Settings()` instance |
| [BP-005](#bp-005) | Docker multi-stage builds | `exec /app/.venv/bin/alembic: no such file or directory` — migrate container exits 255 | All services using `uv venv` in a builder stage |
| [BP-006](#bp-006) | Alembic env.py / DB URL | Alembic migrate container connects to `localhost:5432` instead of Docker service name — connection refused | All services with `alembic/env.py` that use static `alembic.ini` URL |
| [BP-007](#bp-007) | PostgreSQL NULL semantics in unique index | `MultipleResultsFound` at runtime; duplicate rows allowed when nullable columns are NULL | Any table with nullable columns in a multi-column unique constraint |
| [BP-008](#bp-008) | Migration schema drift | `UndefinedColumnError` during migration — 0001 creates stale columns, ORM model has different columns | Any service where the initial schema migration was written before the final ORM model |
| [BP-009](#bp-009) | DispatcherProcess wrong config arg | `AttributeError: 'dict' object has no attribute 'worker_id'` — raw Kafka dict passed as DispatcherConfig | `dispatcher_main.py` in any service using `build_*_dispatcher` factory |
| [BP-010](#bp-010) | Compose `--wait` with non-HTTP workers | `container <worker> has no healthcheck configured` or endless wait/early failure when background process inherits API healthcheck | Any `docker-compose*.yml` profile that starts scheduler/worker/dispatcher processes |
| [BP-011](#bp-011) | Missing runtime non-code assets in image | `FileNotFoundError` for Avro/schema/config files only in containers (works locally) | Services loading schemas/files from `infra/` or repo-relative paths |
| [BP-012](#bp-012) | Async SQLAlchemy expired-row access | `sqlalchemy.exc.MissingGreenlet` in polling loops after rollback | Async tests using `AsyncSession` and ORM objects in long polling loops |
| [BP-013](#bp-013) | E2E perceived infinite loops | Test appears stuck for minutes due to long poll windows, noisy schedulers, or assertions on unstable async conditions | Service E2E tests with scheduler/worker/dispatcher and eventual consistency |
| [BP-014](#bp-014) | Import guard allowlist `fnmatch` vs `**` | CI Import Guards job fails with violations that should be allowlisted — `services/*/tests/*.py` files not covered | Any service with test files directly in `tests/` (not in subdirectories) |
| [BP-015](#bp-015) | Python `hash()` for cross-process coordination | Advisory lock IDs differ between processes — concurrent fetches not locked | Any service using `pg_try_advisory_lock` with Python `hash()` |
| [BP-016](#bp-016) | Advisory lock spanning external I/O | DB connection held during multi-second HTTP fetch — pool exhaustion | Any service holding advisory lock during adapter.fetch() |
| [BP-017](#bp-017) | Outbox payload fields mismatch Avro schema | `SerializationError` or silent field drops at dispatcher time | Any service writing outbox events that feed an Avro-serialized Kafka topic |
| [BP-018](#bp-018) | Client constructor mismatch in wiring code | `TypeError: __init__() got an unexpected keyword argument` at runtime | Any service building adapter clients in a factory or lifespan function |
| [BP-019](#bp-019) | Migration DDL vs ORM column mismatch | `UndefinedColumnError` or `ProgrammingError` at runtime — migration DDL defines different columns than ORM model | Any service where migration DDL is hand-written separately from ORM |
| [BP-020](#bp-020) | DLQ `move_to_dead_letter` only updates status | Dead-lettered events cannot be inspected or requeued — DLQ table has no row, only outbox status changed | Any service with outbox + DLQ pattern |
| [BP-021](#bp-021) | SQLAlchemy ORM `metadata` column name collision | `Cannot override class variable (previously declared on base class "DeclarativeBase") with instance variable` — mypy error, and incorrect table binding | Any ORM model with a column named `metadata` |
| [BP-022](#bp-022) | NMS IoU boundary ambiguity | Overlapping spans with IoU exactly = threshold are NOT suppressed — must be **strictly greater** | Any NER/span deduplication implementation using IoU-based NMS |
| [BP-023](#bp-023) | pre-commit ruff-format stash conflict loop | Commit fails in loop: ruff-format reformats a staged file, stash restore conflicts, hook rolls back, commit never succeeds | Any service where the service venv's ruff version differs from the pre-commit hook's ruff version |
| [BP-024](#bp-024) | DLQ requeue corrupts aggregate_id | DLQ `requeue()` creates outbox event with outbox PK as `aggregate_id` instead of the original doc UUID — silent data corruption, downstream consumers get wrong entity references | Any service with outbox + DLQ pattern |
| [BP-025](#bp-025) | Blocking DNS in async context | `socket.getaddrinfo()` called on event loop — freezes entire async service under slow/failing DNS | Any service doing SSRF validation or DNS lookups in async handlers |
| [BP-026](#bp-026) | SSRF missing IPv4-mapped IPv6 | `::ffff:127.0.0.1` bypasses manual IP blocklist — private IPv4 addresses reachable via IPv4-mapped IPv6 notation | Any service with URL/SSRF validation |
| [BP-027](#bp-027) | DNS rebinding TOCTOU | DNS resolves to public IP at validation time, rebinds to private IP at connection time — validation passes but SSRF succeeds | Any service fetching user-supplied URLs |
| [BP-028](#bp-028) | AsyncMock used for sync method — unawaited coroutine warning | `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` — test passes but has contract mismatch | Any test using `mock_uow = AsyncMock()` where the UoW has sync methods (e.g., `collect_event`) |
| [BP-029](#bp-029) | Content-hash dedup event_type mismatch | Dedup check always misses — `exists_by_content_hash(sha256, _DATASET_TYPE)` never finds rows stored with `event_type=_TOPIC` | Any Kafka consumer using content-hash dedup in market-data |
| [BP-030](#bp-030) | Token-bucket domain entity missing `last_refill_at` | Tokens consumed but never replenished — bucket drains under sustained load until restart | Any service with a token-bucket rate limiter that persists `last_refill_at` in DB |
| [BP-031](#bp-031) | Backfill flag flipped before budget/cap check | Backfill enters incremental mode even if zero tasks were actually enqueued (all blocked by budget/cap) | Any scheduler with a one-shot backfill mode that modifies policy state during candidate task construction |
| [BP-032](#bp-032) | Repository `upsert()` missing `.returning()` | Caller cannot determine the stable DB identity of the upserted row — local entity ID is transient, differs from DB on conflict | Any repository with `ON CONFLICT DO UPDATE` that must return the persisted entity |
| [BP-033](#bp-033) | Concurrent flag updates use read-modify-write | One consumer's `has_quotes=True` update overwrites another's `has_ohlcv=True` — flags silently cleared | Any repo that updates a flags struct with a plain `UPDATE SET ... WHERE id=` under concurrent consumers |
| [BP-034](#bp-034) | Content-hash dedup early return skips `mark_processed` | Same Kafka message replayed passes dedup check again — event_id never recorded when skipping unchanged data | Kafka consumers that do content-hash dedup before event-id dedup |
| [BP-035](#bp-035) | `is_duplicate()` check-then-insert race under concurrent consumers | Two consumers both pass `is_duplicate()` before either writes to the dedup table — duplicate processing despite `ON CONFLICT DO NOTHING` | Any consumer with check-then-insert idempotency pattern |
| [BP-100](#bp-100) | PRD references non-existent external API field | Implementation hits `KeyError` or `None` at runtime — field never existed in the external provider's response | Any PRD/plan that references EODHD, SnapTrade, Polymarket, or other external provider fields without verification |
| [BP-101](#bp-101) | PRD describes stale architecture baseline | Implementation conflicts with existing code — duplicated logic, incompatible indexes, or wrong migration baseline | Any PRD written before an architectural change lands; any plan derived from a PRD created >14 days ago |
| [BP-036](#bp-036) | Token bucket `try_consume()` non-atomic with DB | Two workers both pass `tokens >= n` check before either persists the decrement — tokens over-consumed under concurrent load | Any in-memory token bucket that persists state to DB |
| [BP-037](#bp-037) | `UnitOfWork.__aexit__` exception masking | Rollback failure during `__aexit__` suppresses the original exception — root cause invisible in logs | All services using async UnitOfWork context managers |
| [BP-038](#bp-038) | `assert` used for production error handling | `python -O` strips assertions — critical guards silently disabled, `AssertionError` raises without context | Any service using `assert x is not None` in non-test code |
| [BP-039](#bp-039) | `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic | Missing entry in topic map uses event_type string as topic name — creates spurious topics, messages lost | Any service resolving Kafka topic from an in-memory dict at outbox read time |
| [BP-040](#bp-040) | Idempotency `INSERT` missing `ON CONFLICT DO NOTHING` | Duplicate event replay raises `IntegrityError` instead of being silently ignored — consumer crashes | Any service with a dedicated idempotency/processed-events table using plain INSERT |
| [BP-041](#bp-041) | ruff `TCH003`→`TC003` noqa code rename breaks pre-commit | Pre-commit ruff v0.4.0 reports `TCH003`; newer local ruff auto-converts `# noqa: TCH003` → `# noqa: TC003`; hook then re-flags the violation → infinite loop | All SQLAlchemy ORM models with `Mapped[datetime]` imports |
| [BP-042](#bp-042) | `FailureInfo[None]` has no `value`/`key`/`headers` fields | `AttributeError: 'FailureInfo' object has no attribute 'value'` — only `event_id`, `topic`, `partition`, `offset`, `attempt`, `last_error`, `record` exist | Any `dead_letter` / `process_message_from_failure` implementation on `BaseKafkaConsumer[None]` |
| [BP-043](#bp-043) | Pydantic V2 `Field(strip_whitespace=True)` is deprecated | `PydanticDeprecatedSince20` warning — `strip_whitespace` is not a valid V2 `Field` kwarg; use `StringConstraints(strip_whitespace=True)` via `Annotated` instead | API request schemas using `Field(...)` |
| [BP-057](#bp-057) | Database session held across external I/O | `TimeoutError` on `pool.acquire()` — connection pool exhaustion under load | Any background process (worker, scheduler, dispatcher) holding session during HTTP/MinIO/Kafka calls |
| [BP-058](#bp-058) | `collect_event()` with no outbox_notifier — silent event loss | `uow.collect_event(...)` accumulates events but they are never dispatched: `outbox_notifier` is `None` in `uow_factory()` in `app.py` — Kafka topic never receives messages | S3 (market-data), any service wiring `SqlAlchemyUnitOfWork` without injecting `outbox_notifier` |
| [BP-059](#bp-059) | EVENT_TOPIC_MAP routes events to wrong/shared topic | Both `InstrumentCreated` and `InstrumentUpdated` routed to `market.events.v1` instead of dedicated topics — consumers subscribed to correct topics receive nothing | S3 (market-data) `infrastructure/messaging/outbox/dispatcher.py` EVENT_TOPIC_MAP; any service using a shared routing constant |
| [BP-060](#bp-060) | `collect_event()` for cross-service events instead of atomic outbox write | `collect_event` + `uow.commit()` is a two-step path that can fail if `outbox_notifier` is not wired; direct `await uow.outbox_events.create()` within the same transaction is atomic | S3 consumers; any consumer emitting domain events that other services depend on |
| [BP-061](#bp-061) | Missing `InstrumentUpdated` on capability flag change | Consumer updates `instrument.flags.has_ohlcv/has_quotes/has_fundamentals` via `update_flags()` but never emits `InstrumentUpdated` event — downstream service (S1) cache never refreshed | S3 consumers; any service that updates entity capability flags without publishing a change event |
| [BP-062](#bp-062) | Cross-service field name mismatch: `entity_id` vs `instrument_id` | Producer event only has `instrument_id`; consumer reads `entity_id` — field is always `None`, stable ID (M-017) never populated; `InstrumentRef.id` becomes transient `new_uuid7()` instead of deterministic | S3→S1 instrument sync; any event containing a cross-service stable ID that differs from the local field name |
| [BP-063](#bp-063) | Consumer uses JSON deserialization for Avro-encoded messages | `json.loads(raw)` when producer sends Confluent Avro (magic byte + schema ID + avro bytes) — `json.JSONDecodeError` or garbled data | S1 portfolio `InstrumentEventConsumer`; any service consuming from topics produced by `OutboxEventValueSerializer` |
| [BP-067](#bp-067) | pytest `--strict-markers` + new `e2e` marker not registered | `Failed: 'e2e' not found in markers configuration option` — collection error blocks ALL tests in the service | Any service pyproject.toml adding e2e tests when `--strict-markers` is set but `e2e` is missing from markers list |
| [BP-068](#bp-068) | `postgres:16-alpine` image missing pgvector extension | `ERROR: could not open extension control file ".../vector.control": No such file or directory` when bootstrapping nlp_db/intelligence_db | Test infrastructure for S6 (nlp-pipeline), S7 (knowledge-graph); any service using `VECTOR(N)` columns |
| [BP-072](#bp-072) | Scheduler dedupe key drift — `range_end=now` changes every tick | 120K+ task rows accumulate; MinIO OOM from 2 objects per task; ON CONFLICT DO NOTHING never fires | S2 `ScheduleDueTasksUseCase._build_incremental_task`; any scheduler that embeds `utc_now()` in a dedup key |
| [BP-073](#bp-073) | `has_active_task(variant=None)` bypass for FUNDAMENTALS | Fundamentals tasks created every tick regardless of active status — `dataset_variant IS NULL` never matches `'annual'` | S2 `ScheduleDueTasksUseCase._build_tasks_for_policy`; any has_active guard using nullable dimension columns |
| [BP-074](#bp-074) | Watermark key collision — scheduler omits `variant` | Scheduler creates watermark with `variant=NULL`; worker creates separate watermark with `variant='annual'` — `is_due` checks stale row | S2 `ScheduleDueTasksUseCase._build_tasks_for_policy` vs `ExecuteTaskUseCase.execute` watermark calls |
| [BP-075](#bp-075) | Backfill flag match too broad — provider+symbol only | Two OHLCV backfill policies with same provider+symbol but different timeframes both get `backfill_enabled=False` when budget only allows tasks for one — budget-limited policy skips its backfill permanently | S2 `ScheduleDueTasksUseCase.execute` post-enqueue flag flip; any scheduler with multi-dimensional policy dedup |
| [BP-076](#bp-076) | asyncpg rejects PostgreSQL `::type` cast syntax in `text()` params | `asyncpg.exceptions._base.UnknownPostgresError` or `UndefinedParameter` — SQLAlchemy `text()` does not transform `:name::type` to `$N`; asyncpg receives the raw cast notation and fails | Any service with raw SQL in `text()` using PostgreSQL cast syntax (e.g., `:payload::jsonb`, `:id::uuid`) |
| [BP-077](#bp-077) | `ON CONFLICT DO NOTHING` missing `index_where=` for partial index | `ProgrammingError: there is no unique or exclusion constraint matching the ON CONFLICT specification` — partial unique index not matched because `index_where` was omitted | Any service using `on_conflict_do_nothing(index_elements=[...])` on a table with a partial unique index |
| [BP-078](#bp-078) | Cross-service E2E `ImportError` when service package not installed | `ImportError: No module named 'portfolio'` in cross-service test even when the skip marker fires — import inside test function runs before `pytest.skip()` | `tests/e2e/` cross-service test files importing ORM models from individual service packages |
| [BP-079](#bp-079) | Expired worker lease stalls source permanently | Worker crashes after claiming a task; lease never expires in DB; scheduler's `has_active_task()` guard permanently blocks new tasks for that source — source silently stops ingesting | S4 `content-ingestion` scheduler tick; any scheduler-worker pattern with lease-based task ownership |
| [BP-090](#bp-090) | Ephemeral event in `relations` table — wrong decay behaviour | Geopolitical/regulatory/macro events put in `relations` use continuous confidence decay from inception; but these events are binary (active/inactive) then residually decaying. `confidence` reads as near-zero before active_from or very low during residual period | S7 knowledge graph: any new relation type representing temporal events |
| [BP-091](#bp-091) | AGE Cypher injection via f-string entity_id | `entity_id` f-stringed into Cypher query allows graph traversal manipulation; UUID validation alone is insufficient since AGE executes arbitrary Cypher string | S7 Cypher endpoints: `CypherPathUseCase`, `CypherNeighborhoodUseCase`; all AGE query builders |
| [BP-092](#bp-092) | GLOBAL temporal event → entity_event_exposures explosion | Creating `entity_event_exposures` rows for every company affected by a GLOBAL event (pandemic, rate cycle) creates millions of rows; one GLOBAL event can affect 50K companies | S7 `TemporalEventConsumer`: entity exposure linking; any code that creates exposures for GLOBAL-scope events |
| [BP-093](#bp-093) | EODHD non-existent fields (`Officers`/`Institutions`/`Revenue_Segment`) | `payload.get("General", {}).get("Officers", {})` always returns `{}`; these fields don't exist in the EODHD API | S7 `FundamentalsConsumer`, any EODHD payload extraction; use Insider Transactions API for officers |
| [BP-099](#bp-099) | DDL alignment test misses `ALTER TABLE ADD COLUMN` migrations | `TestXxxDDLAlignment` reports `ORM columns missing from DDL` for columns added via incremental `ALTER TABLE` migrations — `_extract_ddl_columns` only parses `CREATE TABLE` | Any service with incremental Alembic migrations; update `_extract_ddl_columns` to scan `ALTER TABLE … ADD COLUMN` patterns |
| [BP-100](#bp-100) | `app.state.dispatcher` missing in API lifespan → readyz 503 | Health endpoint accesses `app.state.dispatcher._get_producer()` but the dispatcher is a SEPARATE process — `app.state.dispatcher` is never set in the API lifespan → `AttributeError: 'State' object has no attribute 'dispatcher'` → 503 | Alert S10 `api/health.py:readyz`; any service where health check references a process-level object not created in the API lifespan |
| [BP-101](#bp-101) | SQLAlchemy 2.0.0 FK INSERT ordering fails without `relationship()` | `IntegrityError: insert or update on table … violates foreign key constraint … is not present in parent table` even though parent `session.add()` was called first — SQLAlchemy 2.0.0 UoW may not detect FK ordering from column-level `ForeignKey` alone without `relationship()` declarations | content-store `DocumentRepository.create()`: add explicit `await self._session.flush()` after `session.add()` to guarantee parent row is in DB before FK-referencing children |
| [BP-102](#bp-102) | S5 ProcessArticleUseCase hashes bronze envelope instead of original content | `doc.content_hash != article.content_hash` — `check_stage_a()` was called with `raw_bytes` (the JSON bronze envelope), not `article.content_hash` (sha256 of original article bytes) → inconsistent dedup across S4→S5 boundary | content-store `process_article.py`: pass `article.content_hash` (str) to `check_stage_a()` instead of `raw_bytes`; `check_stage_a()` must accept `bytes | str` |
| [BP-103](#bp-103) | Integration test constructor stale after production interface refactor | `TypeError: __init__() got an unexpected keyword argument 'session'` or `'silver_bucket'` — test was written for old API; production code refactored to port ABC (`silver_storage: SilverStoragePort`) | content-store integration tests; any test that constructs use-case objects directly must be updated when use-case constructor changes |
| [BP-104](#bp-104) | E2E DLQ count inflated by concurrent Docker services | `assert N == 5` fails because live Docker containers (e.g., alert-dispatcher) write to the same `dead_letter_queue` table during test execution | Alert E2E tests sharing DB with live Docker: add explicit `TRUNCATE dead_letter_queue CASCADE` before inserting test data in each DLQ-sensitive test |
| [BP-103b](#bp-103b) | ValkeyClient wrapper type annotation drift — `aioredis.Redis` vs `ValkeyClient` | mypy: `Argument "valkey" has incompatible type "ValkeyClient"; expected "Redis"` in `app.py`; or hook-only `attr-defined` when new ValkeyClient methods are unstaged | Any service constructor that accepts a Valkey client: always type as `ValkeyClient` from `messaging.valkey.client`; stage `libs/messaging` changes in same commit as callers |
| [BP-105](#bp-105) | `confluent-kafka[schemaregistry]` extras not declared — dispatcher fails with `No module named 'authlib'` | Outbox dispatcher fails to publish ANY message: `ModuleNotFoundError: No module named 'authlib'` (also `cachetools`, `attrs`) — `confluent_kafka.schema_registry.__init__.py` unconditionally imports the async client at module load | `libs/messaging/pyproject.toml`: use `confluent-kafka[schemaregistry]>=2.4,<3`; locally: `pip install "authlib>=1.3" "cachetools>=5.0" "attrs>=21.2"` |
| [BP-106](#bp-106) | `infra/kafka/schemas/` not copied into Docker images — consumer falls back to JSON | Avro deserialization silently falls back to `json.loads(raw.decode())` → `UnicodeDecodeError` on binary Avro bytes; `_SCHEMA_DIR` resolves to `/app/infra/kafka/schemas` which doesn't exist | All consumer/dispatcher Dockerfiles: add `COPY infra/kafka/schemas /app/infra/kafka/schemas` to runtime stage |
| [BP-107](#bp-107) | S4 raw_content dedup uses URL-hash not content-hash | `submit_content.py` generates unique `manual://<ULID>` URL each time → same raw_content always returns `"accepted"` from S4 | Use URL-based submissions to test S4 URL-dedup; test S5 content-hash dedup by submitting twice and waiting for S5 to store exactly 1 document |
| [BP-108](#bp-108) | nlp_db outbox_events has different schema — injection tests fail with `column "id" does not exist` | `nlp_db.outbox_events` uses `event_id, payload_avro` columns (Avro-encoded); application outbox tables use `id, aggregate_id, payload (jsonb)` | For cross-service injection: produce directly to Kafka via `confluent_kafka.Producer` + `AvroSerializer`, not via nlp outbox table |
| [BP-109](#bp-109) | S2 ingestion_tasks.result_ref stores CANONICAL path, not bronze path | `result_ref_bucket=market-canonical`, `result_ref_key=market-ingestion/canonical/...` — tests expecting bronze object via `result_ref_key` read canonical NDJSON instead | To get bronze key, construct manually: `market-ingestion/raw/{provider}/{dataset_type}/{symbol}/{task_id}` |
| [BP-110](#bp-110) | S2 outbox_events uses `status='published'` not `'delivered'`, has no `aggregate_id` column | S2 outbox schema: `(id, correlation_id, topic, key BYTEA, payload BYTEA, headers JSON, event_type, status, attempt, ...)` — different from application outbox tables with `aggregate_id` and `payload JSONB` | S2 outbox queries must use `event_type='market.dataset.fetched'` and `status='published'`; cannot JOIN to ingestion_tasks via `aggregate_id`; payload is Avro BYTEA (not parseable as JSON) |
| [BP-111](#bp-111) | EODHD demo key returns 0 OHLCV bars for AAPL — canonical NDJSON is empty | `result_ref_key` exists and canonical object is created, but it contains 0 lines; S3 ohlcv_consumer.materialized logs `bar_count=0` | Tests asserting `len(lines) > 0` or `bar_count > 0` must use `pytest.skip()` when empty, not fail; instrument creation (not bar count) is the reliable S2→S3 pipeline indicator |
| [BP-112](#bp-112) | `claim_batch` never reclaims RUNNING tasks with expired leases — worker crash leaves tasks stuck permanently | Tasks remain in `running` state with `locked_until < NOW()` forever; no worker ever re-claims them because `claim_batch` only selects `PENDING`/`RETRY` | Fixed by adding `OR (status='running' AND locked_until < now)` to the CTE WHERE clause in `SqlaTaskRepository.claim_batch` |
| [BP-113](#bp-113) | `TypeError` from None-valued OHLCV field not caught in `ExecuteTaskUseCase._canonicalize` — task stuck in running | EODHD intraday response may include `None` for `volume`; `int(None)` raises `TypeError` which is not in `except (ProviderDataError, ValueError, KeyError)`; `_persist_fail` never called; task stays RUNNING forever | Add `TypeError` to the exception tuple in `execute_task.py:110` |
| [BP-119](#bp-119) | Avro schema defined as inline Python dict drifts from canonical `.avsc` file | Schema changes applied to `.avsc` are not reflected in the serializer (or vice versa); Avro contract tests may pass while the actual schema diverges silently | Always load schemas via `fastavro.schema.load_schema(path_to_avsc)` — never define Avro schemas as inline Python dicts |
| [BP-120](#bp-120) | Post-commit hook failures silently suppressed — cache invalidation skipped with no retry path | Valkey/Redis outage during quote updates leaves stale cache; Kafka offset committed as if success; no mechanism to replay failed invalidation | S3 market-data UoW:131-137, S1 portfolio watchlist:229-236 — post-commit hooks suppress exceptions; see M-002/M-003 in QA-S1S2S3-2026-04-07 |
| [BP-121](#bp-121) | ML / Ollama | BGE-large BERT context window overflow crashes Ollama GGML runner with `GGML_ASSERT(i01 >= 0 && i01 < ne01) failed` | Any service using OllamaEmbeddingAdapter with document-length texts |
| [BP-122](#bp-122) | Kafka / Avro deserialization | S6 Confluent-Avro wire format not detected — consumer crashes on binary `bytes` instead of JSON dict | `article_consumer.py`, any consumer expecting JSON from Schema Registry topics |
| [BP-123](#bp-123) | ML / GLiNER | `model.predict_entities(list_of_texts)` returns `[]` — batch API unsupported; must iterate texts individually | `infra/gliner/server.py`, any GLiNER batch endpoint |
| [BP-124](#bp-124) | Kafka consumer / embedding | Entity exists but `embedding IS NULL` permanently — consumer early-return skips enrichment on replay | S7 `instrument_consumer.py`, any consumer with two-phase entity+enrichment writes |
| [BP-125](#bp-125) | pgvector / ANN | ANN similarity scores can be negative — pgvector cosine distance is `[0, 2]`, not `[0, 1]`; use `max(0.0, 1.0 - d)` floor | Any ANN query converting distance to similarity |
| [BP-126](#bp-126) | Alembic / DDL | `NotNullViolation` on NOT NULL column — ORM `server_default` not inherited by Alembic migration | Every Alembic migration with a NOT NULL column with server_default |
| [BP-128](#bp-128) | AGE extension / PostgreSQL session | AGE functions fail on new connections — `LOAD 'age'` and `SET search_path` must be re-executed per session | `AgeSyncWorker`, `CypherPathUseCase`, all AGE Cypher code paths |
| [BP-129](#bp-129) | Watermark sync / DDL | Incremental watermark sync fails when source table lacks `updated_at` — partitioned tables often have only `created_at` and domain-specific timestamp columns | `AgeSyncWorker` Worker 13F on `relations` table |
| [BP-130](#bp-130) | Kafka / Protocol adapter | `AttributeError: 'cimpl.Producer' has no attribute 'produce_bytes'` — Protocol interface defined but no concrete adapter wraps `confluent_kafka.Producer` | `enriched_consumer_main.py`, `graph_write.py`, any EODHD worker wired with a direct producer |
| [BP-131](#bp-131) | PostgreSQL / unique index | NULL values in multi-column unique index allow semantic duplicates — `ON CONFLICT` never fires when nullable column is NULL | `temporal_events.uidx_temporal_events_natural_key`, any table with nullable columns in a unique constraint |
| [BP-157](#bp-157) | Test infrastructure / Auth | Root E2E conftest generates HS256 JWT; live stack loads RS256 public key from S9 and correctly rejects it — `InvalidTokenError` on all E2E test requests | `tests/e2e/conftest.py:_make_e2e_system_jwt()`; use `PORTFOLIO_E2E_INTERNAL_JWT` env var with RS256 token from live api-gateway |
| [BP-158](#bp-158) | Test infrastructure / Auth | S6/S7/S10/S4/S2 E2E client fixtures + service-level E2E conftests missing `X-Internal-JWT` header after PLAN-0025 — all non-health endpoints 401 | `tests/e2e/conftest.py` s6_client/s7_client/s10_client; `services/{kg,market-data,content-ingestion,market-ingestion}/tests/e2e/conftest.py` |

---

## BP-119 — Avro Schema Inline Drift

**Date discovered**: 2026-04-07
**Service affected**: S10 Alert (`alert/infrastructure/messaging/email_sent_event.py`)

### Symptom

The serializer uses a hardcoded inline Python dict `_EMAIL_SENT_SCHEMA = {"type": "record", "name": "AlertEmailSentV1", ...}` instead of loading from `infra/kafka/schemas/alert.email.sent.v1.avsc`. When the canonical `.avsc` file is updated (e.g., adding a field), the inline dict is not updated, causing serialization to fail at runtime or produce invalid bytes silently.

### Root cause

The inline dict was written during initial implementation to avoid the `Path` calculation required to resolve the `.avsc` file path. The `.avsc` file and the inline dict are separate sources of truth that will diverge over time.

### Fix

Replace inline dicts with `fastavro.schema.load_schema(<path>)`:

```python
from pathlib import Path
import fastavro.schema

_SCHEMA_PATH = Path(__file__).parents[N] / "infra" / "kafka" / "schemas" / "<schema>.avsc"
_PARSED_SCHEMA: Any = None

def _get_parsed_schema() -> Any:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(_SCHEMA_PATH)
    return _PARSED_SCHEMA
```

The `parents[N]` depth depends on the file's location relative to the repo root. Use `load_schema` (not `parse_schema`) — it resolves `$ref` includes automatically.

### Prevention / AVRO-FILE-ONLY Rule

**All Avro schemas MUST be stored in `infra/kafka/schemas/*.avsc`.** No service may define an Avro schema as an inline Python dict. Any serializer/deserializer that currently uses an inline dict must be migrated to `fastavro.schema.load_schema`. Enforce in code review by grepping for `parse_schema({"type": "record"` or `SCHEMA = {"type": "record"` patterns.

**First seen**: PLAN-0016 Wave D-2 QA review (2026-04-07).

---

## BP-001 — OutboxKafkaValue not serialized to bytes

**Date discovered**: 2026-03-09
**Service affected**: `portfolio` (found during `make run-dispatcher`)
**Prompts updated**: `0003-exec-market-ingestion-migration-wave-02.md` T-MI-21 steps 7–8; `0003-exec-market-ingestion-migration-wave-03.md` T-MI-22 step 2

### Symptom

The outbox dispatcher starts and picks up pending records, but every delivery
attempt fails with:

```
error="a bytes-like object is required, not 'OutboxKafkaValue'"
```

Log lines show `outbox_record_dispatch_failed` for every record, cycling until
`max_attempts` is exceeded and records are dead-lettered.

### Root causes (two independent bugs, both required to fix)

#### Bug A — Wrong serializer class used (`KafkaEventValueSerializer` vs `OutboxEventValueSerializer`)

`KafkaEventValueSerializer.__call__` passes the raw `value` argument directly to
the per-type `AvroSerializer`:

```python
# KafkaEventValueSerializer — WRONG for outbox use
return serializer(value, ctx)   # value is OutboxKafkaValue — Avro rejects it
```

`AvroSerializer` expects a plain `dict` matching the Avro schema, not the
`OutboxKafkaValue` wrapper dataclass. This causes the bytes error.

`OutboxEventValueSerializer` (a subclass in `libs/messaging/src/messaging/kafka/producer.py`)
overrides `__call__` to extract `.payload` first:

```python
# OutboxEventValueSerializer — CORRECT for outbox use
return serializer(value.payload, ctx)   # plain dict — Avro accepts it
```

**Fix**: Always use `OutboxEventValueSerializer`, never `KafkaEventValueSerializer`,
when building a value serializer for an outbox dispatcher.

#### Bug B — `value_serializer=` not wired into `build_serializing_producer()`

```python
# WRONG — no value_serializer, producer silently accepts any Python object
return build_serializing_producer(producer_config)

# CORRECT — value_serializer wired in
value_serializer = OutboxEventValueSerializer(self._serializers)
return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

`SerializingProducer` accepts the call without a serializer and only fails at
delivery time — making this a silent misconfiguration that only surfaces on
first dispatch attempt.

### Correct implementation pattern

Every `BaseOutboxDispatcher` subclass must implement `_build_producer()` with
this exact three-step sequence:

```python
def _build_producer(self) -> Any:
    # Step 1 — build per-event-type AvroSerializer dict
    registry_client = build_schema_registry_client(registry_config)
    self._serializers = build_outbox_event_serializers(registry_client)

    # Step 2 — wrap in OutboxEventValueSerializer (NOT KafkaEventValueSerializer)
    value_serializer = OutboxEventValueSerializer(self._serializers)

    # Step 3 — pass value_serializer= explicitly (NOT optional)
    producer_config = KafkaProducerConfig(bootstrap_servers=...)
    return build_serializing_producer(producer_config, value_serializer=value_serializer)
```

### Test to add (prevents regression)

```python
def test_outbox_value_serializer_extracts_payload():
    """OutboxKafkaValue.payload must be passed to AvroSerializer, not the wrapper."""
    mock_avro = MagicMock(return_value=b"avro-bytes")
    ser = OutboxEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    result = ser(value, ctx=None)
    # The serializer must have been called with the plain dict, not the wrapper
    mock_avro.assert_called_once_with({"foo": 1}, None)
    assert result == b"avro-bytes"

def test_raw_avro_serializer_rejects_wrapper():
    """Confirm that passing OutboxKafkaValue directly to AvroSerializer fails —
    this documents why OutboxEventValueSerializer is required."""
    mock_avro = MagicMock(side_effect=TypeError("bytes-like object required"))
    ser = KafkaEventValueSerializer({"my.event": mock_avro})
    value = OutboxKafkaValue(event_type="my.event", payload={"foo": 1})
    with pytest.raises(TypeError):
        ser(value, ctx=None)
```

### Files changed in fix

| File | Change |
|------|--------|
| `libs/messaging/src/messaging/kafka/producer.py` | Added `OutboxEventValueSerializer.__call__` override that extracts `.payload` |
| `services/portfolio/src/portfolio/messaging/dispatcher.py` | Imported `OutboxEventValueSerializer`; wired `value_serializer=` into `build_serializing_producer()` |

---

## BP-002 — Env file loaded in wrong place (Makefile / Docker Compose)

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services are susceptible)
**Prompts updated**: `0002-exec-portfolio-migration-wave-*.md`, `0003-exec-market-ingestion-migration-wave-*.md`

### Symptom

Three distinct but related failure modes, all caused by environment variables not
reaching the service process:

- **Local `make run`**: service starts but uses wrong defaults (wrong DB URL, missing
  API keys). Pydantic-settings silently uses field defaults when env vars are absent.
- **`make test-integration`**: tests fail with `connection refused` or `authentication
  failed` because infra env vars (DB URL, Kafka bootstrap servers) were never exported.
- **Docker Compose (`make test-e2e`)**: service starts with `DATABASE_URL=...` (no
  prefix) so pydantic-settings (env_prefix="SERVICE_") silently ignores the var and
  uses the wrong default host.

### Root causes (three independent bugs, all must be fixed together)

#### Bug A — Makefile `.env-check` verifies file existence but never sources it

```makefile
# WRONG — checks file exists, but variables are NEVER exported
.env-check:
    @test -f configs/dev.local.env || (echo "Missing configs/dev.local.env"; exit 1)

run: .env-check
    $(VENV)/bin/uvicorn service.app:create_app --factory --reload --port 8000
```

The `set -a && . ./configs/dev.local.env && set +a` idiom is missing from every
`run*`, `test-integration`, and `test-e2e` target. The `.env-check` guard is
useless without actual sourcing.

#### Bug B — `docker-compose.yml` uses inline `environment:` with wrong variable names

```yaml
# WRONG — vars without SERVICE_ prefix; pydantic-settings silently ignores them
services:
  my-service:
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
      KAFKA_BOOTSTRAP_SERVERS: kafka:29092
```

Services use `Settings(env_prefix="MY_SERVICE_")`, so `DATABASE_URL` is never
read — `MY_SERVICE_DATABASE_URL` is required. The inline block also duplicates
what `configs/docker.env` already defines, creating two sources of truth that
inevitably drift.

#### Bug C — Postgres credentials mismatch between compose and service config

```yaml
# WRONG (old docker-compose.yml)
postgres:
  environment:
    POSTGRES_USER: worldview
    POSTGRES_PASSWORD: worldview
```

All service `docker.env` files connect as `postgres:postgres`. The container
creates a `worldview` superuser but no `postgres` user → all service connections
fail with `authentication failed for user "postgres"`.

Also: `infra/postgres/init/init-databases.sh` created `market_ingestion_db` but
`market-ingestion/docker.env` and `config.py` default to `ingestion_db` → service
fails to connect on first start.

### Correct implementation pattern

#### Makefile — source env for every target that talks to infra

```makefile
# CORRECT
run: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/uvicorn my_service.app:create_app --factory --reload --port 8000

run-worker: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/python -m my_service.worker.main

# Unit tests — no sourcing needed (all infra is mocked)
test:
    $(VENV)/bin/pytest tests/ -m unit -v

# Integration/e2e — DO source (hit real infra)
test-integration: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/pytest tests/ -m integration -v

test-e2e: .env-check
    @docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test up --build --wait; \
    COMPOSE_EXIT=$$?; \
    if [ $$COMPOSE_EXIT -ne 0 ]; then \
        docker compose -f ../../infra/compose/docker-compose.test.yml \
            --profile my-service-test down -v; \
        exit $$COMPOSE_EXIT; \
    fi; \
    set -a && . ./configs/dev.local.env && set +a; \
    $(VENV)/bin/pytest tests/e2e/ -v; \
    EXIT=$$?; \
    docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test down -v; \
    exit $$EXIT
```

#### `docker-compose.yml` — use `env_file:` pointing to the prefixed docker.env

```yaml
# CORRECT — env_file replaces ALL inline environment: blocks
services:
  my-service:
    env_file:
      - ../../services/my-service/configs/docker.env
    # NO inline environment: block
```

`configs/docker.env` must use the correct `SERVICE_` prefix:

```env
# configs/docker.env  (Docker-internal hostnames)
MY_SERVICE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092
MY_SERVICE_STORAGE_ENDPOINT_HOST=minio
```

#### `docker-compose.yml` — postgres must match service credentials

```yaml
# CORRECT
postgres:
  environment:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
```

#### `infra/postgres/init/init-databases.sh` — DB names must match service config

Always verify that each database name in the init script exactly matches the
database name used in the corresponding service's `docker.env` and `config.py`.

### Env loading responsibility table

| Context | Mechanism | File |
|---------|-----------|------|
| Local dev (`make run`) | `set -a && . ./configs/dev.local.env && set +a` | `configs/dev.local.env` |
| Docker Compose | `env_file:` in compose YAML | `configs/docker.env` |
| Unit tests | None — infra is fully mocked | N/A |
| Integration tests | Same as local dev (Makefile sources it) | `configs/dev.local.env` |
| CI/CD | Secret injection into process environment | CI secret store |
| Settings class | Reads **only** the process environment (no file knowledge) | `config.py` |

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Makefile` | Added `set -a && . ./configs/dev.local.env && set +a` to `run`, `run-dispatcher`, `test-integration`, `test-all`; restructured `test-e2e` to use `docker-compose.test.yml` |
| `services/market-ingestion/Makefile` | Same pattern as portfolio |
| `services/portfolio/configs/docker.env` | Created (was missing — only `.example` existed); contains `PORTFOLIO_`-prefixed vars with Docker-internal hostnames |
| `infra/compose/docker-compose.yml` | Replaced ALL inline `environment:` blocks with `env_file:`; fixed postgres credentials (`postgres:postgres`); built postgres from Dockerfile (TimescaleDB) |
| `infra/postgres/init/init-databases.sh` | Fixed `market_ingestion_db` → `ingestion_db` |
| `infra/compose/docker-compose.test.yml` | New isolated test stack with `tmpfs`, `service_completed_successfully`, `--wait`-compatible healthchecks |
| `infra/postgres/init/init-test-databases.sh` | New file for test stack; creates only `portfolio_db` and `ingestion_db` |
| `infra/minio/init/init-test-buckets.sh` | New file for test stack; creates `market-ingestion`, `market-bronze`, `market-canonical` buckets |
| `services/portfolio/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8001` |
| `services/portfolio/tests/e2e/test_full_flow.py` | Rewritten to use `e2e_client` (real HTTP, not ASGI transport) |
| `services/market-ingestion/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8002` |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | New; 13 tests covering all API workflows |

---

---

## BP-003 — `RuntimeError: Event loop is closed` at session-scoped async fixture teardown

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (any service with e2e tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

All e2e tests pass but produce `ERROR at teardown` for the last test in the session:

```
RuntimeError: Event loop is closed
  ...
  at tests/e2e/conftest.py:NN in e2e_client
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
```

This cascades: tests that actually pass show `ERROR` status, and unrelated unit
tests that run after the e2e teardown can also error (e.g. `test_frozen_dataclass`,
`TestQuantity`) due to the corrupted asyncio state.

### Root cause

pytest-asyncio (mode=auto) creates a **new event loop per test function** by
default. A `scope="session"` async fixture's setup runs in the first test's loop
but its teardown (the `async with` exit) runs after that loop is already closed.
Any `await` inside teardown — including closing an `httpx.AsyncClient`'s
connection pool — raises `RuntimeError: Event loop is closed`.

```python
# WRONG — session fixture torn down on a closed per-function loop
@pytest.fixture(scope="session")
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac  # teardown: AsyncClient.__aexit__ → runs on closed loop → crash
```

### Correct implementation pattern

Set `asyncio_default_fixture_loop_scope = "session"` in `pyproject.toml`. This
tells pytest-asyncio to keep ONE event loop alive for the entire session, so
session-scoped async fixtures always have a live loop for both setup and teardown.

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"   # ← REQUIRED when using session-scoped async fixtures
```

This setting must be present in **every service** that has `scope="session"` async
fixtures. It is harmless for services that only use function-scoped fixtures.

### Test to add (prevents regression)

No specific regression test — the failure only manifests at teardown reporting
time. The fix is purely in `pyproject.toml`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |
| `services/market-ingestion/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |

---

## BP-004 — `fixture 'settings' not found` causes `ERROR at setup` instead of SKIP

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion` (any service with bare `settings` parameter in integration tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

pytest shows `ERROR at setup` (not `FAILED`, not `SKIPPED`) for integration tests:

```
ERROR at setup of test_integration_task_add_and_claim
  fixture 'settings' not found
  available fixtures: app, client, ...
```

Even tests whose first line is `pytest.skip("...")` show as `ERROR` rather than
`SKIPPED` — because fixture resolution happens **before** the test body runs.

### Root cause

Two independent problems, both must be fixed:

**Problem A**: The `settings` pytest fixture is never defined. A helper function
`_make_settings()` (plain function, no decorator) exists in the test file but is
invisible to pytest's fixture system.

**Problem B**: Tests that should always skip use `pytest.skip()` **inside the body**
with a required fixture parameter. Since pytest must resolve all fixture parameters
before entering the body, it errors before it can execute the skip.

```python
# WRONG — fixture resolution fails before skip() can execute
@pytest.mark.integration
async def test_integration_foo(settings):          # 'settings' fixture required
    pytest.skip("Requires live Kafka")             # never reached
    ...

# CORRECT — skip evaluated at collection time, no fixture needed
@pytest.mark.integration
@pytest.mark.skip(reason="Requires live Kafka")    # evaluated before fixture resolution
async def test_integration_foo() -> None:
    ...
```

### Correct implementation pattern

Every service that has integration tests requiring a `Settings()` instance must
have a `conftest.py` in the relevant test subfolder (e.g. `tests/infrastructure/`)
defining a `settings` fixture:

```python
# tests/infrastructure/conftest.py
from __future__ import annotations
import pytest
from my_service.config import Settings

@pytest.fixture(scope="session")
def settings() -> Settings:
    """Real Settings() from MYSERVICE_* env vars.
    Populated by `make test-integration` via:
        set -a && . ./configs/dev.local.env && set +a
    """
    return Settings()
```

For tests that always skip (infrastructure not yet available), use the decorator
form rather than calling `pytest.skip()` in the body:

```python
# CORRECT
@pytest.mark.skip(reason="Requires live Kafka + Schema Registry")
async def test_integration_end_to_end() -> None:
    ...

# Also CORRECT — conditional skip based on env var
import os
_NEEDS_KAFKA = pytest.mark.skipif(
    not os.getenv("MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS"),
    reason="Requires live Kafka (set MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS)",
)

@_NEEDS_KAFKA
async def test_kafka_consumer_roundtrip() -> None:
    ...
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/tests/infrastructure/conftest.py` | Created; defines `settings` fixture |
| `services/market-ingestion/tests/infrastructure/test_dispatcher.py` | Replaced `pytest.skip()` in body + `settings` param with `@pytest.mark.skip` decorator; removed unused parameter |

---

## BP-005 — Docker multi-stage build: `exec /app/.venv/bin/alembic: no such file or directory`

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services using `uv venv` in Dockerfile)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

The migrate container (or any container that runs a venv entry-point directly)
exits with code 255:

```
portfolio-migrate-1  | exec /app/.venv/bin/alembic: no such file or directory
portfolio-migrate-1 exited with code 255
service "portfolio-migrate" didn't complete successfully: exit 255
```

The binary file physically exists. The file system path is correct. The container
still cannot execute it.

### Root cause

The Dockerfile builds the venv in the **builder** stage at `/build/.venv`:

```dockerfile
# Builder stage — WORKDIR /build
RUN uv venv /build/.venv && \
    uv pip install ...
```

`uv` writes entry-point scripts (e.g. `alembic`, `uvicorn`) with a hardcoded
shebang referencing the build-time Python path:

```
#!/build/.venv/bin/python3.11
```

The runtime stage copies the venv to `/app/.venv`:

```dockerfile
COPY --from=builder /build/.venv /app/.venv
```

Now `/app/.venv/bin/alembic` exists and is executable, but its shebang still
points to `/build/.venv/bin/python3.11` — a path that does not exist in the
runtime image. The kernel resolves the shebang first, finds nothing, and returns
`ENOENT` (no such file or directory).

This is silent in the builder stage (the scripts execute fine there) and only
fails at runtime when the entry-point is actually invoked.

### Correct implementation pattern

**Build the venv at the path it will occupy in the runtime stage.** Since the
runtime stage uses `WORKDIR /app`, build at `/app/.venv` even inside the builder:

```dockerfile
# CORRECT — venv built at the runtime path; shebangs are already right
RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        ...

# Runtime stage — copy from the same path (no path change = no shebang corruption)
COPY --from=builder /app/.venv /app/.venv
```

The `--python /app/.venv` flag to `uv pip install` is required when the venv
path differs from `WORKDIR` — `uv` won't auto-detect the venv otherwise.

**`PATH` and `ENV` in the runtime stage are unaffected** — they still point to
`/app/.venv/bin`.

### Test to add (prevents regression)

Add a smoke test to `docker-compose.test.yml` that verifies the migrate container
exits 0. The `service_completed_successfully` condition on every API service
dependency already catches this — if migration exits non-zero, the API container
never starts, causing `--wait` to fail.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Dockerfile` | Changed `uv venv /build/.venv` → `uv venv /app/.venv`; added `--python /app/.venv` to `uv pip install`; updated `COPY` source path |
| `services/market-ingestion/Dockerfile` | Same as portfolio |

---

## BP-006 — Alembic env.py uses hardcoded localhost URL from alembic.ini

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `make test-e2e` → migration container connection refused)

### Symptom

Migration container (`market-ingestion-migrate`) exits 1 with:

```
asyncpg.exceptions.InvalidCatalogNameError: database "ingestion_db" does not exist
```
or
```
ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 5432)
```

The host API service is healthy but the migrate container uses `localhost:5432`
(the `sqlalchemy.url` from `alembic.ini`) instead of the Docker Compose service
name `postgres:5432`.

### Root cause

`alembic/env.py` reads the DB URL from `sqlalchemy.url` in `alembic.ini`, which
has `localhost` hardcoded. The `alembic/env.py` must override this with
`Settings().database_url`, which reads from the running process's environment
variables (populated by Docker Compose's `env_file:` for containers, or
`dev.local.env` for local runs).

### Correct implementation pattern

In `alembic/env.py`:

```python
import os
from <service>.config import Settings as _Settings

config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("ALEMBIC_URL") or _Settings().database_url,
)
```

The `ALEMBIC_URL` escape hatch allows overriding without changing Settings
(useful for special-purpose migration runs).

### Test to add (prevents regression)

```python
def test_alembic_env_reads_from_settings(monkeypatch):
    monkeypatch.setenv("<SERVICE>_DATABASE_URL", "postgresql+asyncpg://x:x@custom-host/db")
    from alembic.config import Config
    alembic_cfg = Config("alembic.ini")
    # env.py should have overridden sqlalchemy.url
    assert "custom-host" in alembic_cfg.get_main_option("sqlalchemy.url", "")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/env.py` | Override `sqlalchemy.url` from `Settings().database_url` instead of reading static `alembic.ini` |

---

## BP-007 — PostgreSQL unique index doesn't deduplicate NULL nullable columns

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during repeated `test_scheduler_tick_with_no_policies_completes` runs)

### Symptom

`sqlalchemy.exc.MultipleResultsFound: Multiple rows were found when one or none was required`

Occurring in `watermark_repository.get()` after running the test suite multiple
times against the same DB. Rows that should be unique (same natural key) are
being duplicated.

### Root cause

A multi-column `UNIQUE` constraint on `(provider, dataset_type, dataset_variant,
symbol, exchange, timeframe)` allows duplicate rows when any nullable column is
`NULL`, because in ANSI SQL `NULL != NULL` (and therefore the constraint is never
triggered). Two rows with `dataset_variant=NULL` for the same provider/dataset/
symbol are treated as *different* by the constraint.

PostgreSQL 15+ supports `NULLS NOT DISTINCT` on unique indexes to fix this.

### Correct implementation pattern

In the migration creating the unique constraint:

```python
op.execute(sa.text("""
    CREATE UNIQUE INDEX uq_<table>_natural_key
    ON <table> (col1, col2, nullable_col3, ...)
    NULLS NOT DISTINCT
"""))
```

And never use `op.create_index(..., unique=True)` for indexes with nullable
columns — it generates SQL without `NULLS NOT DISTINCT`.

As a defensive measure, use `.limit(1)` on `SELECT` queries that expect to
return at most one row but rely on a nullable multi-column key:

```python
stmt = select(Model).where(...).limit(1)
row = (await session.execute(stmt)).scalar_one_or_none()
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/versions/0003_fix_watermarks_nulls_not_distinct.py` | New migration: deduplicates existing rows, drops old index, creates new `NULLS NOT DISTINCT` index |
| `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/watermark_repository.py` | Added `.limit(1)` to `get()` query as defensive guard |

---

## BP-008 — Initial schema migration out of sync with final ORM model

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `make test-e2e` — migration 0002 references columns not in 0001)

### Symptom

```
asyncpg.exceptions.UndefinedColumnError: column "min_interval_sec" of relation "polling_policies" does not exist
```

Migration 0002 (seed data) references columns that the 0001 schema migration
does not create. The ORM model has the correct final schema; 0001 was written
at an earlier stage before the model was finalised.

### Root cause

The initial schema migration (`0001_initial_schema.py`) was written when the ORM
model was still evolving. The final ORM model has different column names and
additional columns. Since no intermediate "alter table" migration was created,
the 0001 migration drifted from the ORM model.

### Detection

Run `alembic check` or `alembic revision --autogenerate -m "check"` and verify
the generated migration is empty. If it's not empty, 0001 is out of sync.

### Correct implementation pattern

When the service hasn't been deployed to production yet and you have the freedom
to rewrite 0001:

1. Update `0001_initial_schema.py` to match the current ORM model exactly.
2. Verify by running `alembic upgrade head && alembic check` — the check should
   produce an empty migration.
3. Any seed migrations (0002, etc.) must reference only columns that 0001 creates.

For services already deployed, create an `000N_alter_<table>.py` migration
to bring the DB schema to match the ORM.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/alembic/versions/0001_initial_schema.py` | Rewrote `polling_policies` block to match `PollingPolicyModel` ORM; rewrote `provider_budgets` block to match `ProviderBudgetModel` ORM |
| `services/market-ingestion/alembic/versions/0002_seed_default_policies.py` | Fixed `sa.func.now()` in `bulk_insert` row dicts (must be Python datetime); fixed timestamp assignments |

---

## BP-009 — DispatcherProcess passes raw Kafka dict as DispatcherConfig

**Date discovered**: 2026-03-10
**Service affected**: `market-ingestion` (found during `test_dispatcher_starts_and_stops_cleanly`)

### Symptom

```
AttributeError: 'dict' object has no attribute 'worker_id'
```

The `DispatcherProcess.__init__` constructs a dict
`{"bootstrap.servers": ...}` and passes it as the `config=` argument to
`build_<service>_dispatcher()`. The factory expects a `DispatcherConfig`
dataclass, not a raw dict.

### Root cause

The original code confused the Kafka producer config dict (used inside the
dispatcher for `SerializingProducer`) with the `DispatcherConfig` dataclass
(tuning parameters for the poll loop). These are completely different objects.
The `build_*_dispatcher` factory already handles constructing the
`DispatcherConfig` from `Settings`; callers should not pass it at all unless
they need to override defaults.

### Correct implementation pattern

```python
# WRONG
kafka_config = {"bootstrap.servers": settings.kafka_bootstrap_servers}
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf, config=kafka_config)

# CORRECT — let the factory derive DispatcherConfig from settings
dispatcher = build_service_dispatcher(settings=settings, write_factory=wf)
```

The `build_*_dispatcher` factory creates `DispatcherConfig` from `settings`
attributes (e.g. `settings.dispatcher_poll_interval_seconds`). The Kafka
`bootstrap.servers` is consumed inside the dispatcher's `_build_producer()`
via `settings.kafka_bootstrap_servers`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/src/market_ingestion/messaging/dispatcher_main.py` | Removed `kafka_config` dict and `config=kafka_config` from `build_market_ingestion_dispatcher` call |

---

## BP-010 — Docker Compose `--wait` fails for long-running worker processes

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`, `portfolio`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`, `0004-exec-market-data-migration-wave-03.md`, `0004-exec-market-data-migration-wave-04.md`

### Symptom

- `docker compose ... up --wait` fails with:

```
container <service>-dispatcher-1 has no healthcheck configured
```

- Or background processes exit because they inherited API-only healthchecks
    (e.g., probing `/readyz` on processes that do not expose HTTP).

### Root cause

Compose `--wait` requires health status for started services. Long-running
workers/schedulers/dispatchers often run as non-HTTP commands and cannot reuse
the API container healthcheck. If no healthcheck is present (or API healthcheck
is inherited from Dockerfile), readiness and lifecycle behavior become unstable.

### Correct implementation pattern

For non-HTTP background services:

```yaml
worker:
    command: ["python", "-m", "service.worker.main"]
    healthcheck:
        test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
        interval: 15s
        timeout: 3s
        retries: 3
        start_period: 5s
```

And do **not** rely on Dockerfile API healthchecks for these process types.

### Test to add (prevents regression)

- In CI/local smoke script, run:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --wait
docker compose -f infra/compose/docker-compose.test.yml ps
```

- Assert worker/scheduler/dispatcher are `Up (healthy)` and not restarting.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added explicit healthchecks for `market-ingestion-scheduler`, `market-ingestion-worker`, `market-ingestion-dispatcher`, and `portfolio-dispatcher` |

---

## BP-011 — Runtime schema files missing from container image

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`

### Symptom

Dispatcher crashes only in containers with:

```
FileNotFoundError: Could not locate market.dataset.fetched.avsc from module path or cwd
```

### Root cause

Schema files under `infra/kafka/schemas/` were available in the repo for local
execution but not copied into the Docker runtime image. Module path resolution
worked on host but failed in container filesystem.

### Correct implementation pattern

Copy required non-code assets into image at build time:

```dockerfile
COPY infra/kafka/schemas /build/infra/kafka/schemas
...
COPY --from=builder /build/infra/kafka/schemas /app/infra/kafka/schemas
```

Also prefer robust schema path resolution that scans parents/cwd and fails with
clear error text.

### Test to add (prevents regression)

- Container smoke command in CI:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --build --wait
docker compose -f infra/compose/docker-compose.test.yml logs <dispatcher-service>
```

- Assert no `FileNotFoundError` and dispatcher remains running.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/Dockerfile` | Copied `infra/kafka/schemas` into runtime image |
| `services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/serialization.py` | Added resilient schema path resolver |

---

## BP-012 — Async SQLAlchemy polling triggers `MissingGreenlet`

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-04.md`

### Symptom

E2E polling test fails with:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
```

typically when reading ORM object attributes after rollback/expiration.

### Root cause

Polling loop selected full ORM rows, then session rollback expired attributes.
Later attribute access triggered lazy load outside the active greenlet context.

### Correct implementation pattern

In async polling tests, query scalar columns instead of ORM objects:

```python
status = (
        (await session.execute(select(Model.status).where(...).limit(1)))
        .scalars()
        .first()
)
await session.rollback()
```

Avoid storing ORM entities across loop iterations when rollback is used.

### Test to add (prevents regression)

- Add an E2E polling test variant that runs the loop for several iterations and
    confirms no `MissingGreenlet` is raised.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | Replaced ORM-row polling with scalar-column polling |

---

## BP-013 — E2E tests appear infinite due to unstable async assertions

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-04.md`

### Symptom

E2E run appears to hang for minutes. Tests are not truly infinite but use long
deadlines while waiting for conditions that are fragile (symbol-specific queue
state, dispatcher timing, scheduler noise).

### Root cause

- Assertions depended on one task/symbol becoming terminal within an arbitrary
    window while scheduler continuously enqueued unrelated tasks.
- Poll loops had broad deadlines and ambiguous success criteria.

### Correct implementation pattern

1. Use bounded polling windows with explicit deadlines.
2. Assert stable, service-level progress conditions (e.g., any task processed),
     not brittle symbol-specific timing.
3. Keep scheduler deterministic in test profiles (short tick; bounded budget).

```yaml
environment:
    MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS: "2.0"
    MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK: "0"
```

### Test to add (prevents regression)

- Add one dedicated async-progress smoke test with a strict upper bound
    (`<= 20-30s`) and fail-fast assertion message.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added deterministic scheduler test env vars |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | Reworked full-flow test to bounded, stable progress assertion |

---

## BP-014 — Import guard allowlist `fnmatch` pattern does not match direct children

**Date discovered**: 2026-03-26
**Service affected**: `intelligence-migrations` (found during CI Import Guards job)
**Prompts updated**: `.claude/skills/implement/SKILL.md` Step 4 — added import guards to validation gate

### Symptom

CI Import Guards job fails with 3 net-new violations that should be covered by the allowlist:
```
[IG-OBS-001] services/intelligence-migrations/scripts/populate_embeddings.py:30
    Forbidden call: `logging.getLogger()` (rule IG-OBS-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:129
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:130
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
```

### Root cause

Two independent issues:

1. **`fnmatch` does not support recursive `**` like `pathlib.Path.glob()`**. The allowlist used patterns like `services/*/tests/**/*.py`, but Python's `fnmatch.fnmatch()` treats `*` as "match any characters" (including `/`). The `**/` in the pattern requires at least one path separator after `tests/`, so files directly in `tests/` (like `tests/test_migration.py`) are NOT matched — only files in subdirectories (like `tests/unit/test_foo.py`) match.

2. **Service-level scripts not covered**. The allowlist had `scripts/**/*.py` for repo-root scripts, but `services/intelligence-migrations/scripts/populate_embeddings.py` is under `services/`, not the root `scripts/` directory.

3. **No pre-commit import guard check**. The pre-commit hook (`pre-commit-validate.sh`) ran ruff + mypy + unit tests but did NOT run import guards, so violations passed local validation and only failed in CI.

### Correct implementation pattern

When writing `fnmatch`-style allowlist patterns, always include **both** direct-child and recursive patterns:

```yaml
# Direct children — fnmatch does NOT support ** recursion
- rule_id: IG-COMMON-001
  path: "services/*/tests/*.py"
  reason: Test code may use uuid4() directly.

# Nested children — still needed for tests/unit/*.py, tests/integration/*.py
- rule_id: IG-COMMON-001
  path: "services/*/tests/**/*.py"
  reason: Test code may use uuid4() directly.
```

When adding new service directories (like `services/*/scripts/`), add corresponding allowlist entries if the files don't follow service-code conventions.

### Test to add (prevents regression)

Import guards now run as Step 3/4 in the pre-commit hook (`scripts/hooks/pre-commit-validate.sh`), so violations are caught before commit — not just in CI.

### Files changed in fix

| File | Change |
|------|--------|
| `scripts/import_guards/allowlist.yaml` | Added `services/*/tests/*.py` patterns alongside existing `**/*.py` patterns; added `services/*/scripts/*.py` entries |
| `services/intelligence-migrations/scripts/populate_embeddings.py` | Replaced `logging.getLogger()` with `structlog.get_logger()` and structlog-style kwargs |
| `scripts/hooks/pre-commit-validate.sh` | Added import guards as Step 3/4 (scoped to changed services) |
| `.claude/skills/implement/SKILL.md` | Added import guards to Step 4 validation gate |

---

## BP-015 — Python `hash()` for cross-process coordination

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

Advisory lock IDs differ between Python processes. Multiple replicas acquire the "same" lock simultaneously because `hash("s4:fetch:eodhd")` returns different values per process (randomized by PYTHONHASHSEED).

### Root cause

Python's `hash()` is randomized per process (PEP 456). Using it for PostgreSQL advisory lock IDs produces different lock IDs in different pods/containers.

### Correct implementation pattern

```python
import hashlib
def advisory_lock_id(key: str) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)
```

Use `hashlib.sha256` for deterministic cross-process IDs. The shared `messaging.pg.advisory_lock` module does this correctly.

### Test to add (prevents regression)

```python
def test_advisory_lock_id_deterministic():
    assert advisory_lock_id("key") == advisory_lock_id("key")
```

---

## BP-016 — Advisory lock spanning external I/O

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

DB connection pool exhaustion under load. Advisory lock held for 10–30 seconds while adapter fetches from external API.

### Root cause

The advisory lock was acquired before the HTTP fetch, keeping a DB connection checked out during the entire external I/O. With 3 sources × 30s fetch × multiple replicas, the pool depletes.

### Correct implementation pattern

```python
# Fetch OUTSIDE the lock
results = await adapter.fetch(source)

# Write INSIDE the lock (short, bounded duration)
async with pg_advisory_lock(session, key) as acquired:
    if acquired:
        await use_case.write(results)
```

### Test to add (prevents regression)

Verify that the session factory is called separately for the read (watermark) + fetch phase and the write phase.

---

## BP-017 — Outbox payload fields mismatch Avro schema

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`SerializationError` at dispatcher time, or fields silently dropped. The outbox payload used field names like `url`, `minio_key` while the Avro schema expected `source_url`, `minio_bronze_key`.

### Root cause

Outbox payload was built with domain field names instead of Avro schema field names. No compile-time or test-time validation of the payload structure.

### Correct implementation pattern

Build payloads using a dedicated helper that maps to Avro field names:

```python
def build_raw_article_payload(*, doc_id, source_type, source_url, minio_bronze_key, ...):
    return {"event_id": ..., "source_url": source_url, "minio_bronze_key": minio_bronze_key, ...}
```

Add a test that asserts payload keys match the Avro schema fields.

---

## BP-018 — Client constructor mismatch in wiring code

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`TypeError: __init__() got an unexpected keyword argument 'rate_limiter'` when constructing adapter clients. Or: `http_client` not passed because generic `adapter_cls(**kwargs)` was used.

### Root cause

Each client has a different constructor signature (EODHD/Finnhub need `api_key`, SEC EDGAR needs `user_agent`, NewsAPI needs `valkey`). Generic wiring code doesn't handle these differences.

### Correct implementation pattern

Use explicit per-source-type wiring with type-checked constructors:

```python
if source_type == "eodhd":
    client = EODHDClient(http_client=http_client, api_key=settings.eodhd_api_key)
elif source_type == "newsapi":
    client = NewsAPIClient(http_client=http_client, api_key=settings.newsapi_key, valkey=valkey)
```

### Test to add (prevents regression)

HTTP client tests using `httpx.MockTransport` that verify each client can be constructed and called.

---

## BP-019 — Migration DDL vs ORM column mismatch

**Date discovered**: 2026-03-28
**Services affected**: `content-store`, `content-ingestion` (found during multi-agent QA review)
**Prompts updated**: `PLAN-0001-B-R2` tasks T-R2-1-01, T-R2-1-02, T-R2-1-05

### Symptom

`UndefinedColumnError` or `ProgrammingError` at runtime when Alembic migration creates a table with different columns than the SQLAlchemy ORM model expects. Integration tests that use `Base.metadata.create_all()` bypass Alembic and won't catch this.

Example: `outbox_events` migration DDL had `event_id`, `partition_key`, `payload_avro BYTEA` columns, but the ORM model had `id`, `aggregate_type`, `payload JSONB`.

### Root cause

Migration DDL was written manually at an early stage of development, then the ORM model evolved. Since no automated check existed, the two diverged silently. Integration tests use `Base.metadata.create_all()` which generates DDL from the ORM — not from Alembic — so they always pass.

### Correct implementation pattern

1. Always generate initial DDL from ORM column inspection, or copy the exact column definitions from the ORM model.
2. Add DDL-vs-ORM alignment tests that parse migration SQL and compare column names against `Model.__table__.columns`:

```python
def test_ddl_matches_orm():
    migration_text = Path("alembic/versions/0001_*.py").read_text()
    orm_columns = {c.name for c in MyModel.__table__.columns}
    # Parse CREATE TABLE from migration and extract column names
    for col in orm_columns:
        assert col in migration_text, f"ORM column '{col}' missing from migration DDL"
```

3. Never use `gen_random_uuid()` defaults on UUID PKs — all IDs must be app-generated UUIDv7.

### Test to add (prevents regression)

DDL-vs-ORM alignment tests (see `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py` and `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py`).

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/alembic/versions/0001_create_content_store_schema.py` | Rewrote `outbox_events` and `dead_letter_queue` DDL to match ORM |
| `services/content-ingestion/alembic/versions/0001_initial_s4_schema.py` | Added `payload_json JSONB` to `dead_letter_queue` DDL |
| `services/content-store/tests/unit/infrastructure/test_ddl_alignment.py` | New — DDL alignment tests for S5 |
| `services/content-ingestion/tests/unit/infrastructure/test_ddl_alignment.py` | New — DDL alignment tests for S4 |

---

## BP-020 — DLQ `move_to_dead_letter` only updates status without copying payload

**Date discovered**: 2026-03-28
**Services affected**: `content-store` (found during multi-agent QA review)
**Prompts updated**: `PLAN-0001-B-R2` tasks T-R2-1-03, T-R2-1-04, T-R2-1-06

### Symptom

Dead-lettered events are invisible to the `/admin/dlq` API and cannot be requeued. The `move_to_dead_letter` method updates the outbox `status` column to `dead_letter` but does not INSERT a row into the `dead_letter_queue` table. Additionally, `requeue()` creates a new outbox event with `payload={}` (empty) instead of the original payload.

### Root cause

1. `move_to_dead_letter` was implemented as a simple status update (one SQL UPDATE) instead of the S4 pattern which also INSERTs a DLQ row with the original payload.
2. `DeadLetterQueueModel` was missing the `payload_json` column, so even if a DLQ row existed, there was no place to store the payload for requeue.
3. `requeue()` hardcoded `payload={}` instead of reading `entry.payload_json`.

### Correct implementation pattern

```python
async def move_to_dead_letter(self, record_id: UUID, error_detail: str = "") -> None:
    # 1. Fetch the outbox record
    record = await self._get_outbox_record(record_id)
    if not record:
        return
    # 2. INSERT a DLQ row with the original payload
    dlq = DeadLetterQueueModel(
        dlq_id=new_uuid7(),
        original_event_id=record.id,
        topic=record.topic,
        payload_json=record.payload,  # preserve original payload
        error_detail=error_detail,
    )
    self._session.add(dlq)
    # 3. Update outbox status
    record.status = OutboxStatus.DEAD_LETTER
```

For `requeue()`:
```python
async def requeue(self, dlq_id: UUID) -> None:
    entry = await self._get(dlq_id)
    # Use original payload, not empty dict
    await outbox_repo.append(..., payload=entry.payload_json or {})
```

### Test to add (prevents regression)

See `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` — tests verify DLQ row creation and non-empty payload on requeue.

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Fixed `move_to_dead_letter` to INSERT DLQ row |
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Fixed `requeue` to use `entry.payload_json` |
| `services/content-store/src/content_store/infrastructure/db/models.py` | Added `payload_json` column to `DeadLetterQueueModel` |
| `services/content-store/tests/unit/infrastructure/test_dlq_repo.py` | New — DLQ copy + requeue tests |

---

## BP-021 — SQLAlchemy ORM `metadata` column name collision

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` (found during mypy check of nlp_db ORM models)
**Prompts updated**: N/A

### Symptom

```
error: Cannot override class variable (previously declared on base class "DeclarativeBase") with instance variable  [misc]
error: Incompatible types in assignment (expression has type "Mapped[dict[str, Any] | None]", base class "DeclarativeBase" defined the type as "MetaData")  [assignment]
```

### Root cause

`DeclarativeBase` (SQLAlchemy 2.x) defines a class-level `metadata: MetaData` attribute. Any ORM model that names a column `metadata` will shadow it, causing a mypy type conflict and potentially incorrect ORM behavior.

### Correct implementation pattern

Rename the Python attribute, preserving the DB column name via an explicit column name argument:

```python
# WRONG
metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

# CORRECT — rename attribute, keep DB column as "metadata"
resolution_metadata: Mapped[dict[str, Any] | None] = mapped_column(
    "metadata", JSONB, nullable=True
)
```

Update all repositories that set this field to use the new attribute name.

### Test to add (prevents regression)

```python
def test_mention_resolution_model_has_no_metadata_attr_collision():
    from nlp_pipeline.infrastructure.nlp_db.models import MentionResolutionModel
    # Python attr is resolution_metadata, not metadata
    assert hasattr(MentionResolutionModel, "resolution_metadata")
    assert not hasattr(MentionResolutionModel.__table__.columns, "resolution_metadata")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` | Renamed `metadata` → `resolution_metadata` with explicit column name `"metadata"` |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/mention_resolution.py` | Updated `metadata=` to `resolution_metadata=` |

---

## BP-022 — NMS IoU boundary: strictly-greater vs greater-or-equal

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` Block 4 NER (test failures during Wave C-2)
**Prompts updated**: N/A

### Symptom

NMS unit test `test_keeps_higher_confidence_when_overlapping` passes when IoU < threshold but fails when IoU = threshold (0.5 exactly). Spans that should be suppressed are kept, or vice versa.

### Root cause

The PRD says "IoU > 0.5" — strictly greater than. If the implementation uses `>=`, spans with IoU = 0.5 are incorrectly suppressed. Test fixtures using exact boundary values (e.g., spans (0,10) and (0,5) → IoU = 0.5 exactly) will fail because 0.5 is NOT > 0.5.

### Correct implementation pattern

```python
NMS_IOU_THRESHOLD = 0.5

def _nms(mentions):
    ...
    if _iou(a.char_start, a.char_end, b.char_start, b.char_end) > NMS_IOU_THRESHOLD:
        # suppress b (strictly greater than threshold)
```

Test fixtures must use spans with IoU **strictly greater than** 0.5, e.g., (0,10) and (1,9) → IoU = 8/10 = 0.8.

### Test to add (prevents regression)

```python
def test_nms_boundary_iou_exactly_half_not_suppressed():
    # spans (0,10) and (0,5): intersection=5, union=10, IoU=0.5 — NOT suppressed
    m1 = EntityMention(..., char_start=0, char_end=10, confidence=0.9, ...)
    m2 = EntityMention(..., char_start=0, char_end=5, confidence=0.7, ...)
    result = _nms([m1, m2])
    assert len(result) == 2  # neither suppressed at boundary
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/tests/unit/application/blocks/test_ner.py` | Updated test fixtures to use spans with IoU > 0.5 (not exactly 0.5) |

---

## BP-023 — pre-commit ruff-format stash conflict loop

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` (pre-commit hook during Wave C-2 commit)
**Prompts updated**: N/A

### Symptom

`git commit` enters an infinite failure loop:
```
ruff-format...Failed — 1 file reformatted
Stashed changes conflicted with hook auto-fixes... Rolling back fixes
```

The same file is reformatted every attempt; the commit never succeeds.

### Root cause

Two conditions must both be true to trigger this:
1. A staged file has a **different version in the working tree** (`AM` or `MM` git status)
2. The pre-commit hook's ruff version formats the file differently than the local venv's ruff

The hook stashes the working tree, formats the staged content, then tries to restore the stash. The stash's working tree version conflicts with the formatted index version, causing rollback.

### Correct implementation pattern

Before committing, ensure ALL staged Python files have `A ` or `M ` status (no working tree delta):

```bash
# Find partially-staged Python files
git diff --name-only | grep "\.py$"

# For each file listed, check if it's also staged
git status --short <file>  # AM or MM = problem

# Fix: restore working tree from index (use hook's formatted version)
git checkout -- <file>

# OR: format file with system ruff (pre-commit hook version) and re-stage
uvx ruff format <file>
git add <file>
```

**Always use `uvx ruff format` (system/pre-commit ruff), not the service venv's ruff**, since the venv may be pinned to an older version.

### Test to add (prevents regression)

N/A — this is a workflow issue, not a code bug. Add to commit checklist: verify no `AM`/`MM` Python files before committing.

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` | Reformatted assert statement to match pre-commit hook's ruff version |

---

## BP-024 — DLQ requeue corrupts aggregate_id

**Date discovered**: 2026-03-27
**Service affected**: `content-store` (found during PLAN-0001-B-R4 QA review)
**Prompts updated**: `docs/plans/0001-b-r4-qa-review-fixes-plan.md` W1

### Symptom

Downstream consumers receive `content.article.stored.v1` events where `aggregate_id` is the outbox primary key UUID instead of the canonical document UUID. Lookups by document ID silently fail — no error, wrong entity referenced.

### Root cause

`DLQRepository.requeue()` created the new outbox event using `entry.original_event_id` (the outbox PK) as `aggregate_id` instead of the actual document UUID stored in `entry.aggregate_id`. Similarly, `event_type` was hardcoded instead of read from the DLQ row.

### Correct implementation pattern

```python
# WRONG — uses outbox PK as aggregate_id
self._session.add(OutboxEventModel(
    aggregate_id=entry.original_event_id,  # ← outbox PK, not doc UUID!
    event_type="content.article.stored.v1",  # ← hardcoded
    ...
))

# CORRECT — use stored metadata with fallback for pre-existing rows
self._session.add(OutboxEventModel(
    aggregate_id=entry.aggregate_id or entry.original_event_id,
    aggregate_type=entry.aggregate_type or "document",
    event_type=entry.event_type or entry.payload_json.get("event_type", "content.article.stored.v1"),
    ...
))
```

Also: `move_to_dead_letter` must store `aggregate_type`, `aggregate_id`, and `event_type` from the source outbox record into the DLQ row when creating it.

### Test to add (prevents regression)

```python
async def test_requeue_uses_stored_aggregate_id():
    entry = make_dlq_entry()
    entry.aggregate_id = UUID("doc-uuid-here")
    entry.original_event_id = UUID("outbox-pk-here")
    ...
    outbox_model = session.add.call_args.args[0]
    assert outbox_model.aggregate_id == entry.aggregate_id  # doc UUID, not outbox PK
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-store/src/content_store/infrastructure/db/repositories/dlq.py` | Use `entry.aggregate_id` with fallback |
| `services/content-store/src/content_store/infrastructure/db/repositories/outbox.py` | Store metadata fields in DLQ row |
| `services/content-store/alembic/versions/0001_create_content_store_schema.py` | Add `aggregate_type`, `aggregate_id`, `event_type` columns to `dead_letter_queue` |

---

## BP-025 — Blocking DNS resolution in async context

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

Under slow or failing DNS, the entire FastAPI service freezes. Requests time out across all endpoints because a single blocked `socket.getaddrinfo()` call holds the event loop.

### Root cause

`socket.getaddrinfo()` is a blocking synchronous call. When called directly inside a Pydantic `field_validator` (which runs synchronously during request validation in an async handler), it blocks the asyncio event loop for the duration of the DNS lookup.

### Correct implementation pattern

```python
# WRONG — blocks the event loop
@field_validator("url")
def validate_url(cls, v: str) -> str:
    addrs = socket.getaddrinfo(hostname, None)  # blocks!
    ...

# CORRECT — move DNS to async handler with timeout
async def check_url_ssrf_async(url: str) -> None:
    try:
        addr_infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        raise ValueError(f"DNS timeout for {hostname}")
```

The Pydantic validator should only check scheme (http/https) and reject literal private IPs. DNS resolution moves to the async route handler.

### Test to add (prevents regression)

```python
async def test_async_dns_timeout():
    with patch("socket.getaddrinfo", side_effect=lambda *a, **kw: time.sleep(10)):
        with pytest.raises(ValueError, match="Could not resolve"):
            await check_url_ssrf_async("http://slow.example.com/article")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Removed DNS from validator; added `check_url_ssrf_async` |
| `services/content-ingestion/src/content_ingestion/api/routes/internal.py` | Call `check_url_ssrf_async` in handler |

---

## BP-026 — SSRF missing IPv4-mapped IPv6 bypass

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

A URL like `http://[::ffff:127.0.0.1]/internal` passes SSRF validation even though it routes to localhost. Manual IP range checks for `127.0.0.0/8` don't cover the IPv4-mapped IPv6 form.

### Root cause

Manual `_PRIVATE_NETWORKS` lists check `127.0.0.0/8`, `10.0.0.0/8`, etc. These only apply to `IPv4Address` objects. An `IPv6Address` like `::ffff:127.0.0.1` is technically in the `::ffff:0:0/96` range and has `ipv4_mapped = IPv4Address('127.0.0.1')`, but won't match any IPv4 range check unless you first extract the mapped address.

### Correct implementation pattern

```python
# WRONG — misses IPv4-mapped IPv6
def _is_private_ip(addr):
    return any(addr in network for network in _PRIVATE_NETWORKS)

# CORRECT — use Python builtins + handle IPv4-mapped IPv6
def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped  # unwrap ::ffff:x.x.x.x → IPv4
    return addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast or addr.is_link_local
```

Python's built-in `is_private`, `is_reserved`, `is_loopback` properties cover all RFC-defined ranges including CGNAT (100.64.0.0/10), multicast, and future additions.

### Test to add (prevents regression)

```python
@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:10.0.0.1]/",
    "http://100.64.0.1/",  # CGNAT
    "http://224.0.0.1/",   # multicast
])
def test_rejects_private_ip_variants(url):
    with pytest.raises(ValueError):
        IngestRequest(url=url, ...)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Replaced manual network lists with `is_private` builtins + IPv4-mapped unwrap |

---

## BP-027 — DNS rebinding TOCTOU in SSRF validation

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

URL passes SSRF validation (DNS resolves to public IP), but by the time the HTTP client connects, DNS has been rebounded to a private IP. The request reaches an internal service despite validation passing.

### Root cause

DNS validation and HTTP connection are two separate operations with a time gap. An attacker controls a DNS server that returns a public IP on the first query (validation) and a private IP on the second query (connection). This is a classic TOCTOU (Time Of Check, Time Of Use) race.

### Correct implementation pattern

```python
class SSRFSafeTransport(httpx.AsyncBaseTransport):
    """Validates resolved IPs at connection time, not just at validation time."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        if hostname:
            addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                addr = ipaddress.ip_address(sockaddr[0])
                if _is_private_ip(addr):
                    raise httpx.ConnectError(f"SSRF blocked: {hostname} → {addr}")
        return await self._inner.handle_async_request(request)
```

Wire this transport when constructing `httpx.AsyncClient` in the app lifespan.

### Test to add (prevents regression)

```python
async def test_transport_blocks_dns_rebinding():
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://rebind.example.com/")
    with patch("socket.getaddrinfo", return_value=[(..., ..., ..., "", ("127.0.0.1", 0))]):
        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            await transport.handle_async_request(request)
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/infrastructure/http/ssrf_transport.py` | New — `SSRFSafeTransport` implementation |
| `services/content-ingestion/src/content_ingestion/app.py` | Wire `SSRFSafeTransport` into `httpx.AsyncClient` |

---

## Template for new entries

Copy this block when adding a new pattern:

```markdown
## BP-NNN — Short title

**Date discovered**: YYYY-MM-DD
**Service affected**: `<service-name>` (found during `<make target or test>`)
**Prompts updated**: `<prompt file>` task `<T-XX-NN>` step N

### Symptom

<exact error message or observable behaviour>

### Root cause

<explanation of why it fails>

### Correct implementation pattern

<code snippet showing the correct way>

### Test to add (prevents regression)

<pytest test that would have caught this>

### Files changed in fix

| File | Change |
|------|--------|
| `path/to/file.py` | What was changed |
```

---

## BP-028 — AsyncMock used for sync method generates unawaited coroutine warnings

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Tests pass but emit `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` for calls like `uow.collect_event(...)`. The call is sync in production but the test's `AsyncMock()` wraps every attribute as an async mock.

### Root cause

`mock_uow = AsyncMock()` makes ALL attributes `AsyncMock` instances by default. When production code calls a **sync** method (`collect_event`) without `await`, the `AsyncMock` runs but the resulting coroutine is never consumed — generating the warning.

### Fix

Explicitly override sync methods after creating the `AsyncMock`:
```python
mock_uow = AsyncMock()
mock_uow.collect_event = MagicMock()  # sync — must not be AsyncMock
```

### Prevention

After `mock_uow = AsyncMock()`, check the real UoW for sync methods and override them with `MagicMock()`.

---

## BP-029 — Content-hash dedup event_type key mismatch — dedup never fires

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Content-hash dedup never fires — identical canonical objects are re-downloaded and re-materialized on every tick.

### Root cause

`mark_processed()` stored `event_type=_TOPIC` (e.g., `"market.dataset.fetched"`) while `exists_by_content_hash()` queried with `event_type=_DATASET_TYPE` (e.g., `"ohlcv"`). The lookup always missed.

### Fix

Use the same value (`_DATASET_TYPE`) in both `mark_processed()` and `exists_by_content_hash()`.

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

## BP-032 — `upsert()` missing `.returning()` — transient entity ID

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (InstrumentRepository)

### Symptom

After upsert, caller's in-memory entity ID is a transient UUID that may not match the DB row (on conflict, the DB keeps the original row ID).

### Root cause

`pg_insert(...).on_conflict_do_update(...)` executed without `.returning(InstrumentModel)`. Repo returned `None`.

### Fix

Add `.returning(InstrumentModel)`, fetch `scalar_one()`, and return the mapped entity.

---

## BP-033 — Concurrent flag updates — read-modify-write race clears flags

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (InstrumentRepository.update_flags)

### Symptom

Under concurrent consumers, a consumer setting `has_quotes=True` overwrites another consumer's concurrent `has_ohlcv=True` update.

### Root cause

`UPDATE instruments SET has_ohlcv=:v, has_quotes=:v, has_fundamentals=:v WHERE id=:id` overwrites all columns from a pre-read snapshot.

### Fix

Use atomic OR-merge so only `True` values propagate — flags can never be cleared by concurrent writers:
```python
has_ohlcv=case((flags.has_ohlcv, True), else_=InstrumentModel.has_ohlcv),
```

---

## BP-034 — Content-hash dedup early return skips `mark_processed`

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

The same Kafka message is re-processed on replay even though the data was unchanged. The content-hash dedup path returns early without recording the event_id.

### Root cause

When `exists_by_content_hash(sha256, event_type)` returns `True`, the consumer returns early. But the `event_id` is never written to the `ingestion_events` table. On next replay the `is_duplicate()` check returns `False` (event_id not found) and the consumer re-processes.

### Fix

Call `await self.mark_processed(event_id)` before the early return so the event_id is always recorded:
```python
if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
    await self.mark_processed(event_id)   # ← ADD THIS
    return
```

---

## BP-035 — `is_duplicate()` check-then-insert race under concurrent consumers

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (all three consumers)

### Symptom

Under rebalance or concurrent consumer scenarios, the same message is processed twice even though `ON CONFLICT DO NOTHING` exists on the dedup table.

### Root cause

The `is_duplicate()` SELECT and the `create()` INSERT happen in separate transactions. Two consumers can both pass the `is_duplicate()` check before either has committed the insert. The `ON CONFLICT DO NOTHING` prevents a duplicate row but does not prevent duplicate processing.

### Fix

Use a database-level lock or move the dedup INSERT to be the first operation inside the processing transaction. If the INSERT is rejected by the unique constraint, treat the event as a duplicate and skip processing.

---

## BP-036 — Token bucket `try_consume()` non-atomic with DB persist

**Date discovered**: 2026-03-27
**Service affected**: `market-ingestion` (ProviderBudget)

### Symptom

Under multi-worker load, the budget allows more requests than the configured limit — tokens are over-consumed.

### Root cause

`try_consume()` checks and decrements `self.tokens` in-memory before the DB write. Two workers loading the same budget row both see `tokens >= n`, both decrement in-memory, and both write back — one decrement is lost.

### Fix

Load the budget row with `SELECT ... FOR UPDATE` within the consuming transaction so only one worker can check-and-decrement at a time.

---

## BP-037 — `UnitOfWork.__aexit__` rollback failure masks original exception

**Date discovered**: 2026-03-27
**Service affected**: All services with async UnitOfWork

### Symptom

After a use-case failure, the log shows a rollback error instead of the original business exception — root cause is invisible.

### Root cause

`__aexit__` calls `await self.rollback()` inside a bare `try` block. If rollback itself raises (DB connection lost), the new exception replaces the original via Python's implicit exception chaining.

### Fix

Use explicit exception chaining and structured logging:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
    except Exception as cleanup_err:
        logger.error("uow_cleanup_failed", error=str(cleanup_err), original=str(exc_val))
    finally:
        await self._session.close()
```

---

## BP-038 — `assert` used for production error handling

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv_consumer, quotes_consumer, fundamentals_consumer)

### Symptom

With `python -O`, the assertion is stripped and the guard becomes a no-op. Under normal execution, `AssertionError` is raised with no context message.

### Root cause

```python
assert self._current_uow is not None  # Stripped by python -O
```

### Fix

Replace with explicit guard:
```python
if self._current_uow is None:
    raise RuntimeError("mark_processed called outside processing context")
```

---

## BP-039 — `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (OutboxRepository)

### Symptom

Outbox events for a newly-added event type are published to a Kafka topic literally named after the event type string (e.g., `portfolio.holding.changed`), not the canonical topic name.

### Root cause

`claim_batch()` resolves topic as `EVENT_TOPIC_MAP.get(row.event_type, row.event_type)`. If the event type is missing from the map, the fallback is the event_type string itself — a spurious topic is created silently.

### Fix

Fail explicitly on missing entries:
```python
topic = EVENT_TOPIC_MAP.get(row.event_type)
if topic is None:
    raise ValueError(f"Unknown event_type for outbox routing: {row.event_type!r}")
```

---

## BP-040 — Idempotency `INSERT` missing `ON CONFLICT DO NOTHING`

**Date discovered**: 2026-03-27
**Service affected**: `portfolio` (IdempotencyRepository), `market-data` (IngestionEventRepository)

### Symptom

On Kafka message replay, the consumer crashes with `IntegrityError: duplicate key value violates unique constraint` instead of silently skipping the duplicate.

### Root cause

The idempotency record INSERT uses a plain `INSERT INTO` without `ON CONFLICT DO NOTHING`. The table has a unique constraint on `event_id`, so a replay raises instead of being ignored.

### Fix

```python
stmt = (
    insert(IdempotencyModel)
    .values(event_id=event_id)
    .on_conflict_do_nothing(constraint="pk_idempotency")
)
```

---

## BP-041 — ruff TCH003→TC003 noqa rename breaks pre-commit hook

**Affects**: All SQLAlchemy ORM models using `Mapped[datetime]` (or other stdlib types only used in annotations)

### Symptom

Pre-commit hook fails with:

```
ruff.....................................................................Failed
services/.../models.py:9:22: TCH003 Move standard library import `datetime.datetime` into a type-checking block
Found 2 errors (1 fixed, 1 remaining).
```

After the hook auto-fixes the import (moves it to `TYPE_CHECKING`), SQLAlchemy raises at runtime:

```
sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotation: "Mapped[datetime]"
```

### Root cause

- The pre-commit hook pins ruff at `v0.4.0`, which uses rule code `TCH003`.
- Newer local ruff (≥v0.6.0) renames it to `TC003` and auto-converts `# noqa: TCH003` → `# noqa: TC003` in staged files.
- The hook's ruff v0.4.0 doesn't recognize `# noqa: TC003` as suppressing `TCH003` → auto-fixes the import → breaks SQLAlchemy → circular failure.

### Fix

Add the models path glob to `ruff.toml`'s `[lint.per-file-ignores]` to suppress the rule globally (no noqa comment needed):

```toml
# SQLAlchemy calls get_type_hints() at runtime — datetime must be importable
"services/*/src/*/infrastructure/db/models/*.py" = ["TCH003"]
"services/*/src/*/infrastructure/*/models.py" = ["TCH003"]   # non-standard subdirs (e.g. nlp_db/)
```

Do NOT use `# noqa: TCH003` or `# noqa: TC003` — they are unstable across ruff versions. The `per-file-ignores` approach is version-agnostic.

---

## BP-042 — FailureInfo[None] missing value/key/headers fields

**Affects**: `BaseKafkaConsumer[None]` implementations — `dead_letter()` and `process_message_from_failure()`

### Symptom

```
AttributeError: 'FailureInfo' object has no attribute 'value'
mypy: "FailureInfo[None]" has no attribute "value"
```

### Root cause

`FailureInfo[TFailure]` stores the original message in typed form. When `TFailure = None`, the consumer never parses the raw Kafka message into a domain object, so `FailureInfo[None]` has **no** `value`, `key`, or `headers` fields — only:

- `event_id: str`
- `topic: str`
- `partition: int`
- `offset: int`
- `attempt: int`
- `last_error: str`
- `record: Any` (the raw Kafka ConsumerRecord)

### Fix

In `dead_letter()`: use `failure.event_id` for identification, not `failure.value`.
In `process_message_from_failure()`: the original payload is not recoverable — log a warning and return without reprocessing.

```python
def dead_letter(self, failure: FailureInfo[None]) -> None:
    # failure.value does NOT exist — use event_id for the DLQ entry
    asyncio.create_task(self._write_dlq(event_id=failure.event_id, ...))

async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
    # Original payload is not recoverable for TFailure=None consumers
    logger.warning("cannot_reprocess_failure", event_id=failure.event_id)
```

## BP-043 — Pydantic V2 `Field(strip_whitespace=True)` deprecated

**Affects**: API request schemas using `Field(strip_whitespace=True)` — `TenantCreateRequest`, `PortfolioCreateRequest`, etc.

### Symptom

```
PydanticDeprecatedSince20: Using extra keyword arguments on `Field` is deprecated and will be removed.
Use `json_schema_extra` instead. (Extra keys: 'strip_whitespace')
```

### Root cause

Pydantic V2 removed non-standard kwargs from `Field()`. `strip_whitespace` was a Pydantic V1 feature. In V2, string constraints (including `strip_whitespace`, `min_length`, `max_length`) must be applied via `StringConstraints` in an `Annotated` type.

### Fix

```python
from typing import Annotated
from pydantic import StringConstraints

TrimmedStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

class TenantCreateRequest(BaseModel):
    name: TrimmedStr
```

Or drop `strip_whitespace` and rely on `min_length`/`max_length` in `Field(...)` only (the length constraints are the primary security fix):

```python
name: str = Field(min_length=1, max_length=255)
```

## BP-044 — f-string dynamic SQL for nullable filters triggers ruff S608

**Category**: SQL / Linting
**Services affected**: Any async service with optional filter params in repository queries
**First seen**: knowledge-graph S7 Wave D-4 (relation repository list_for_entity / list_filtered)

### Symptom

Repository method builds a dynamic WHERE clause using f-strings or string concatenation to handle optional filter parameters:

```python
# WRONG — triggers S608 (f-string in SQL) and is hard to audit
mode_filter = "AND r.semantic_mode = :semantic_mode" if semantic_mode else ""
query = text(f"SELECT ... FROM relations r WHERE ... {mode_filter}")
```

This approach:
1. Fires `S608: Possible SQL injection via string-based query construction` (even though it's not actually injectable here, ruff can't tell)
2. Requires `# noqa: S608` on every call site
3. Is structurally harder to audit for actual injection risks

### Root Cause

Using f-strings or `%` formatting in `text()` queries makes the SQL dynamic, even when the dynamic part is a safe literal (a clause name, not user data).

### Fix

Use PostgreSQL's `IS NULL OR column = :param` pattern to keep the SQL fully static while supporting optional filters:

```python
# CORRECT — fully static SQL, no f-strings, no S608
query = text("""
    SELECT ...
    FROM relations r
    WHERE (:semantic_mode IS NULL OR r.semantic_mode = :semantic_mode)
      AND (:min_confidence IS NULL OR r.confidence >= :min_confidence)
    ...
""")
result = await session.execute(query, {
    "semantic_mode": semantic_mode,          # None → clause passes for all rows
    "min_confidence": min_confidence,        # None → clause passes for all rows
})
```

### Why this works

PostgreSQL evaluates `:param IS NULL` first. When the parameter is `None` (bound as SQL NULL), the entire `IS NULL OR ...` disjunction short-circuits to `TRUE`, effectively removing the filter. When non-null, the actual column comparison is evaluated.

### Benefits

- Zero dynamic SQL → no S608, no `# noqa` suppressions
- Single static query → easier to read, audit, and plan/cache
- Works for all nullable parameters: strings, UUIDs, floats, datetimes

### Caution

- For very large tables with many optional filters, this can prevent index use on some filters even when non-null. Profile with `EXPLAIN ANALYZE` if performance is critical.
- Not applicable when the number of filters is dynamic (e.g., variable-length IN clauses) — those still need query building.

---

## BP-045 — Non-atomic consumer dedup: `is_duplicate` + `process_message` + `mark_processed` in separate transactions

**Category**: Idempotency / Concurrency
**Services affected**: portfolio `InstrumentEventConsumer` (fixed 2026-03-28), any `BaseKafkaConsumer` subclass using 3-method dedup pattern
**First seen**: PLAN-0001-E QA-003

### Symptom

Two concurrent consumer instances process the same event. Both call `is_duplicate(event_id)` → both get `False`. Both proceed through `process_message()`. Both call `mark_processed(event_id)`. The event is processed twice.

### Root cause

The classic 3-method dedup pattern opens **three separate DB transactions**:

```python
# WRONG — 3 separate transactions, race window between each
async def is_duplicate(self, event_id):
    async with await self.get_unit_of_work() as uow:
        return await uow.idempotency.exists(uid)  # Transaction 1

async def process_message(self, ...):
    async with await self.get_unit_of_work() as uow:
        await uow.instruments.upsert(instrument)  # Transaction 2

async def mark_processed(self, event_id):
    async with await self.get_unit_of_work() as uow:
        await uow.idempotency.record(uid)  # Transaction 3
```

Between Transaction 1 returning `False` and Transaction 3 completing, another consumer instance can also pass the `is_duplicate` check.

### Fix

Apply BP-035: atomic `INSERT … ON CONFLICT DO NOTHING RETURNING` inside the **same transaction** as the business logic. `is_duplicate()` always returns `False`; `mark_processed()` is a no-op.

```python
# CORRECT — BP-035 pattern, single transaction
async def is_duplicate(self, event_id: str) -> bool:
    return False  # dedup handled atomically in process_message

async def mark_processed(self, event_id: str) -> None:
    pass  # dedup record inserted atomically in process_message

async def process_message(self, key, value, headers):
    async with await self.get_unit_of_work() as uow:
        # Atomic dedup: both INSERT and business logic in one transaction
        is_new = await uow.idempotency.create_if_not_exists(event_uid)
        if not is_new:
            return  # duplicate — skip
        await uow.instruments.upsert(instrument)
```

The `create_if_not_exists` implementation:

```python
async def create_if_not_exists(self, event_id: UUID) -> bool:
    stmt = (
        insert(IdempotencyModel)
        .values(event_id=event_id, processed_at=datetime.now(tz=UTC))
        .on_conflict_do_nothing()
        .returning(IdempotencyModel.event_id)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none() is not None
```

### See also

BP-035 (Watermark dedup), BP-040 (idempotency INSERT missing ON CONFLICT)

---

## BP-046 — Cache invalidation before `uow.commit()` creates stale-read-into-cache race

**Category**: Cache consistency / M-005 violation
**Services affected**: market-data `QuotesConsumer` (fixed 2026-03-28), any consumer that invalidates Valkey inside `process_message()`
**First seen**: PLAN-0001-E QA-004

### Symptom

After a cache invalidation a client reads the data, gets the DB's current (old) value, and caches it. Then the transaction commits the new value. The cache now holds the OLD value until TTL expiry. Stale data is served from cache.

### Root cause

```python
# WRONG — cache invalidation before commit
async def process_message(self, key, value, headers):
    await uow.quotes.upsert(quote)           # DB write (not yet committed)
    await self._quote_cache.invalidate(id)   # Cache invalidated NOW
    # ... base class calls uow.commit() later
```

After invalidation but before commit:
1. Client reads `GET /quotes/{id}` → cache miss → hits DB → gets **old value** (write not committed)
2. Client's response is cached in Valkey
3. `uow.commit()` persists the new value
4. Valkey now serves the **stale cached old value** until TTL

### Fix

Use `uow.schedule_post_commit(coro)` — a post-commit hook that drains after `write_session.commit()`:

```python
# CORRECT — cache invalidation after commit (M-005)
async def process_message(self, key, value, headers):
    await uow.quotes.upsert(quote)
    # Schedule cache invalidation to run AFTER the transaction commits
    if self._quote_cache is not None:
        uow.schedule_post_commit(self._quote_cache.invalidate(instrument.id))
```

The `schedule_post_commit` implementation in `SqlAlchemyUnitOfWork.commit()`:

```python
async def commit(self) -> None:
    await self._write_session.commit()           # DB write durable
    # ... outbox notifier ...
    hooks = self._post_commit_hooks[:]
    self._post_commit_hooks.clear()
    for hook in hooks:
        await hook                               # Cache invalidated after durability
```

### Test pattern

Test must verify the hook is **scheduled** (not yet awaited), then manually drain:

```python
captured_hooks = []
mock_uow.schedule_post_commit = MagicMock(side_effect=captured_hooks.append)
await consumer.process_message(...)
mock_cache.invalidate.assert_not_awaited()   # Not yet
await captured_hooks[0]                       # Simulate commit drain
mock_cache.invalidate.assert_awaited_once_with(instrument_id)
```

---

## BP-047 — `readyz` health endpoint leaks DB credentials via raw exception string

**Category**: Security / Information disclosure
**Services affected**: All FastAPI services with `/readyz` endpoint
**First seen**: PLAN-0001-E QA-010

### Symptom

`GET /readyz` returns `HTTP 503` with body:
```json
{"db": "error: password authentication failed for user 'postgres'@db:5432/portfolio_db"}
```
Or worse, if the connection string contains a password:
```json
{"db": "error: (asyncpg.InvalidPasswordError) password authentication failed for user 'postgres' at postgresql+asyncpg://postgres:s3cr3t@db:5432/..."}
```

### Root cause

```python
# WRONG — raw exception message in HTTP response body
except Exception as exc:
    checks["db"] = f"error: {exc}"  # leaks DSN, password, host info
```

### Fix

Return opaque string in HTTP body; log full details internally:

```python
# CORRECT — opaque error in response, full details in logs only
except Exception as exc:
    log.error("readyz_db_check_failed",
              error_type=type(exc).__name__, error=str(exc))
    checks["db"] = "error"   # client sees only "error", not the exception
```

Also: `log` must be the service-level logger, not a locally-undefined name. If `log` is defined inside a lifespan function, it won't be accessible in a route handler defined in `create_app()`. Use `get_logger("service.app")` directly inside the handler.

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

## BP-049 — `get_or_create` reads back via read session after INSERT on write session (read-your-own-write failure)

**Category**: DB session management / Read/write splitting
**Services affected**: market-ingestion `BudgetRepository`, `WatermarkRepository` (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-007, QA-008

### Symptom

`get_or_create()` inserts a row on the write session, then calls `self.get()` which uses the read session `self._r` — a potentially separate replica connection. The replica may not see the uncommitted or just-committed write (replication lag or different connection), so `get()` returns `None`. The caller then falls back to a transient domain object with a new auto-generated ID, breaking idempotency: subsequent `UPDATE WHERE id = new_id` matches 0 rows silently.

### Root cause

```python
# WRONG — reads back from the wrong session after INSERT
async def get_or_create(self, key) -> DomainObject:
    stmt = insert(Model).values(...).on_conflict_do_nothing()
    await self._w.execute(stmt)
    row = await self.get(key)  # self.get() uses self._r (read session) ← WRONG
    if row:
        return row
    return DomainObject(id=new_uuid7(), ...)  # fresh ID = broken idempotency
```

### Fix

Read back from the write session after INSERT to guarantee read-your-own-write:

```python
# CORRECT — read back from write session
async def get_or_create(self, key) -> DomainObject:
    stmt = insert(Model).values(...).on_conflict_do_nothing()
    await self._w.execute(stmt)
    select_stmt = select(Model).where(Model.key == key)
    row = (await self._w.execute(select_stmt)).scalar_one_or_none()
    if row:
        return _to_domain(row)
    return DomainObject(id=new_uuid7(), ...)  # only reached on genuine insert failure
```

---

## BP-050 — `asyncio.Event.set()` called from librdkafka delivery callback without `call_soon_threadsafe`

**Category**: Thread safety / async
**Services affected**: market-ingestion `OutboxDispatcher` (fixed 2026-03-28), any service using confluent-kafka delivery callbacks with asyncio synchronization primitives
**First seen**: PLAN-0001-E QA-028

### Symptom

Intermittent deadlocks, missed delivery signals, or rare `RuntimeError: no running event loop` in high-throughput scenarios. Under normal load the issue is latent and only manifests under contention.

### Root cause

```python
# WRONG — asyncio.Event mutated from a non-asyncio thread
def _cb(err, _msg):
    nonlocal delivery_error
    if err:
        delivery_error = RuntimeError(str(err))
    delivery_event.set()   # ← called from librdkafka C thread, not asyncio thread

loop = asyncio.get_event_loop()  # captured AFTER _cb definition — too late
producer.produce(..., callback=_cb)
await asyncio.wait_for(asyncio.shield(asyncio.get_event_loop().run_until_complete(...)), ...)
```

librdkafka delivery callbacks run on the librdkafka internal thread pool, which is not the asyncio event loop thread. Calling `asyncio.Event.set()` from a non-asyncio thread is not thread-safe.

### Fix

Capture `loop` **before** defining the callback, then use `loop.call_soon_threadsafe`:

```python
# CORRECT — thread-safe event signaling from delivery callback
loop = asyncio.get_event_loop()    # captured before _cb is defined

def _cb(err: Any, _msg: Any) -> None:
    nonlocal delivery_error
    if err is not None:
        delivery_error = RuntimeError(str(err))
    loop.call_soon_threadsafe(delivery_event.set)   # ← thread-safe

producer.produce(..., callback=_cb)
```

---

## BP-051 — Avro record name contains dots or version suffix — invalid Java identifier

**Category**: Avro schema / Schema Registry
**Services affected**: market-data Avro schemas (fixed 2026-03-28); any service that uses dots in Avro `"name"` field
**First seen**: PLAN-0001-E QA-015

### Symptom

Schema Registry registration fails:
```
SchemaRegistryException: Invalid schema: name "instrument.created.v1" is not a valid Avro name
```
Or: two services register schemas for the same logical event type under different subjects because one uses `"name": "instrument.created"` and another uses `"name": "InstrumentCreated"` — they are different subjects.

### Root cause

Avro record names must be valid Java identifiers: start with a letter or `_`, contain only letters, digits, and `_`. Dots are **namespace separators** in Avro fullnames (format: `namespace.Name`), not valid within the `"name"` field itself.

```json
// WRONG — dots in "name" field, version suffix
{ "type": "record", "name": "instrument.created.v1", "namespace": "com.worldview" }

// WRONG — dots in "name", no namespace
{ "type": "record", "name": "instrument.created" }
```

### Fix

Use PascalCase for the `"name"` field; version and path belong in the `"namespace"`:

```json
// CORRECT
{ "type": "record", "name": "InstrumentCreated", "namespace": "com.worldview.market_data.events" }
```

---

## BP-052 — Inconsistent Avro namespace creates divergent Schema Registry subjects

**Category**: Avro schema / Schema Registry
**Services affected**: portfolio watchlist Avro schemas (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-014

### Symptom

Two schemas for the same service use different namespaces (`"portfolio.events"` vs `"com.worldview.portfolio.events"`). The Schema Registry registers them under different subjects. One service registers `portfolio.events.WatchlistCreated-value`; the consumer expects `com.worldview.portfolio.events.WatchlistCreated-value`. Deserialization fails at runtime.

### Root cause

No enforced namespace convention. Different developers use different namespace styles.

```json
// WRONG — short namespace
{ "type": "record", "name": "WatchlistCreated", "namespace": "portfolio.events" }

// WRONG — inconsistent with other schemas in same service
{ "type": "record", "name": "WatchlistCreated", "namespace": "events" }
```

### Fix

Enforce **canonical namespace** across all schemas: `com.worldview.<service_name>.events`

```json
// CORRECT — canonical namespace
{ "type": "record", "name": "WatchlistCreated", "namespace": "com.worldview.portfolio.events" }
```

All schemas in a service **must** use the same namespace. Add a CI check to enforce this.

---

## BP-053 — `schema_version: ClassVar[int] = 0` footgun — subclasses emit version-0 events silently

**Category**: Event schema versioning
**Services affected**: market-data domain events (fixed 2026-03-28)
**First seen**: PLAN-0001-E QA-026

### Symptom

A consumer parses an event with `schema_version=0` and either crashes (unexpected version) or silently uses the wrong schema. Debugging is hard because the producer code appears correct — the subclass simply forgot to override `SCHEMA_VERSION`.

### Root cause

```python
# WRONG — base class default is 0 ("unset")
class DomainEvent:
    SCHEMA_VERSION: ClassVar[int] = 0

class QuoteUpdated(DomainEvent):
    # forgot to override SCHEMA_VERSION
    pass  # emits schema_version=0 silently
```

Version 0 is meaningless as a valid schema version. A default of 0 is indistinguishable from "forgot to set this".

### Fix

Set base class default to `1` (the minimum valid production version):

```python
# CORRECT — default 1 means "unversioned but valid"
class DomainEvent:
    SCHEMA_VERSION: ClassVar[int] = 1
```

Subclasses that intentionally use a higher version override it explicitly. Version 0 should never appear in production events and can be used as a signal for misconfiguration.


---

## BP-056: Infrastructure Lib Imported in Domain Layer via Multiple Inheritance

**Severity**: MAJOR — architecture violation (R12)
**Service**: market-data (S3); generalizes to any service

### Pattern

```python
# WRONG — domain/errors.py pulls in messaging lib
from messaging.kafka.consumer.errors import FatalError

class ParseError(MarketDataError, FatalError):  # R12 violation
    ...
```

Using multiple inheritance to "conveniently" combine a domain error with an infrastructure error type pulls the infrastructure library into the domain layer. This breaks hexagonal architecture boundaries and creates a hidden coupling that is hard to detect through normal code review.

### Why it happens

The intent is that Kafka consumer routing treats `ParseError` as `FatalError` so the message is dead-lettered. Multiple inheritance feels like a neat shortcut. But it violates R12: domain layer must have zero infrastructure imports.

### Fix

Keep `ParseError` as a pure domain exception. Consumer infrastructure code maps it:

```python
# CORRECT — infrastructure/messaging/consumers/foo_consumer.py
except ParseError as exc:
    raise FatalError(str(exc)) from exc
```

Or, if the consumer already raises a messaging-layer error directly (e.g. `MalformedDataError`), no mapping is needed at all.

### Regression Guard

Add a unit test that walks the MRO and asserts no `messaging` module appears:

```python
def test_parse_error_is_pure_domain() -> None:
    mro_names = [c.__module__ for c in ParseError.__mro__]
    assert not any("messaging" in m for m in mro_names)
```

---

## BP-057 — Database session held across external I/O

**Severity**: HIGH — pool exhaustion under load (R24)
**Service**: Any service with background processes (workers, schedulers, dispatchers)
**Related**: [BP-016](#bp-016) (advisory lock spanning external I/O)

### Symptom

- `TimeoutError` on `pool.acquire()` — all connections busy despite low query volume
- Connection pool exhaustion under moderate load
- Long-running "idle in transaction" connections visible in `pg_stat_activity`
- Intermittent `sqlalchemy.exc.TimeoutError: QueuePool limit of N overflow M reached`

### Cause

A database session (and its underlying connection) is opened before an external I/O call
(HTTP request, MinIO upload, Kafka publish) and held idle throughout. The connection sits
in the pool's "checked out" state doing nothing while the I/O completes, preventing other
coroutines from using it.

```python
# WRONG — connection held idle during HTTP call
async with session_factory() as session:
    data = await repo.get(id)              # uses connection
    result = await http_client.post(...)   # connection held idle for seconds!
    await repo.save(result)                # uses connection again
    await session.commit()
```

This is especially harmful in workers with semaphore-bounded concurrency — 4 concurrent
tasks each holding a connection during I/O can exhaust a `pool_size=5` pool.

### Fix

Split into read → release → I/O → acquire → write phases:

```python
# CORRECT — release connection before I/O
async with read_factory() as ro:
    data = await repo.get(id)              # read phase

result = await http_client.post(...)       # I/O phase (no session held)

async with write_factory() as rw:
    await repo.save(result)                # write phase
    await rw.commit()
```

### Detection

Grep for session context managers that span external I/O calls:

```bash
# Look for session_factory/uow usage that spans http_client, storage, or producer calls
grep -n "session_factory\|uow\|unit_of_work" services/*/src/**/*.py | \
  grep -v "test" | grep -v "__pycache__"
```

Then manually inspect each match for external I/O calls within the same context block.

### Prevention

- R24 enforces this rule project-wide (see RULES.md)
- STANDARDS.md §16 documents the correct session lifecycle per process type
- Code review checklist: "Does any session context span an external I/O call?"

---

## BP-058 — UoW `__aexit__` Auto-Commit Causes Double-Commit Side Effects

**Severity**: MEDIUM — silent in SQLAlchemy sessions, but double-fires post-commit hooks (e.g., outbox notifier, on_commit callbacks)
**Service**: portfolio (S1) — any service using the `UnitOfWork` context manager
**Resolved by**: PLAN-0001-E-R1 Wave 2 (Option B, QA-006)

### Symptom

- `on_commit` hook (e.g., outbox dispatcher wake signal) is called twice per request
- Post-commit side effects (cache invalidation, metrics increment) execute twice on clean exit
- No crash — SQLAlchemy's `AsyncSession.commit()` is idempotent for already-committed sessions

### Cause

`UnitOfWork.__aexit__` auto-commits on clean exit:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
        await self.commit()  # WRONG — fires even when use case already called commit()
```

Use cases that call `await uow.commit()` explicitly (e.g., before cache invalidation) get the
commit called a **second time** by `__aexit__`, triggering any side effects attached to `commit()`
a second time.

### Fix (Option B)

Remove auto-commit from `__aexit__`. All mutating use cases must call `await uow.commit()` explicitly:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is not None:
        await self.rollback()
    # no auto-commit — explicit commit() required in each use case
```

### Detection

```bash
# Find any UoW __aexit__ that calls self.commit() unconditionally
grep -n "await self.commit" services/*/src/**/*unit_of_work*.py
```

Add the regression guard test:
```python
async def test_aexit_does_not_auto_commit_on_clean_exit(mock_session_factory, mock_session):
    async with SqlAlchemyUnitOfWork(mock_session_factory):
        pass  # no explicit commit
    mock_session.commit.assert_not_called()
```

### Prevention

- Review checklist item: "Does `UnitOfWork.__aexit__` auto-commit? If so, verify all callers are aware of the side effect."
- Every mutating use case must end with `await uow.commit()` before returning
- New use case template must include the commit call

## BP-059 — Use Case Calls `async with self._uow:` on Already-Entered UoW

**Category**: Architecture | **Severity**: Runtime error / silent data loss risk
**Discovered**: 2026-03-29 — PLAN-0001-E-R1 Wave 3 (QA-013)

### Pattern

When a service's dependency injection framework already enters the UoW before yielding it
(e.g., `async with uow_factory() as uow: yield uow`), any use case that wraps its body
in `async with self._uow:` will trigger a nested context manager entry:

```python
# WRONG — double-enters the UoW when get_uow yields an already-entered instance
class GetInstrumentUseCase:
    async def execute(self, instrument_id: str):
        async with self._uow:             # ← second __aenter__ — undefined behaviour
            return await self._uow.instruments_read.find_by_id(instrument_id)
```

### Root Cause

Two different UoW entry conventions exist across services:
1. **market-data** (S3): `get_uow` dependency yields an *already-entered* UoW
   (`async with SqlAlchemyUnitOfWork(...) as uow: yield uow`)
2. **portfolio** (S1): `get_uow` dependency yields an *uninitialized* factory — use cases
   enter it themselves

If a use case written for S1's convention is used in S3 (or vice versa), the double-entry
will either re-open the session (wasting connections) or raise a runtime error.

### Fix

Check the service's `api/dependencies.py` to determine which convention it uses.
For S3-style (already-entered), use cases must NOT wrap in `async with self._uow:`:

```python
# CORRECT for market-data — call repo methods directly, no context manager
class GetInstrumentUseCase:
    async def execute(self, instrument_id: str):
        return await self._uow.instruments_read.find_by_id(instrument_id)
```

### Detection

```bash
# In a service that yields pre-entered UoW: grep for use cases wrapping in async with
grep -n "async with self._uow" services/market-data/src/**/use_cases/*.py
```

### Prevention

- Service `.claude-context.md` must document which UoW convention is in use
- Use case template for market-data omits the `async with self._uow:` wrapper

---

## BP-058

**Category**: Kafka / outbox — silent event loss

**Symptom**: Kafka topics receive no messages despite consumers calling `uow.collect_event()` and committing. No errors in logs.

**Root cause**: `SqlAlchemyUnitOfWork.commit()` calls `self._outbox_notifier(events)` only if the notifier is not `None`. If `app.py` wires the UoW factory without injecting an outbox notifier, all collected events are silently discarded after commit.

```python
# WRONG — in app.py
def uow_factory() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(write_factory, read_factory)
    # outbox_notifier defaults to None → collect_event() is a no-op

# CORRECT — inject the notifier
def uow_factory() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(write_factory, read_factory, outbox_notifier=dispatcher.notify)
```

**Affected areas**: S3 (market-data) `app.py`; any service wiring `SqlAlchemyUnitOfWork` without `outbox_notifier`.

**Fix**: Either inject `outbox_notifier` into `SqlAlchemyUnitOfWork`, or bypass the notifier entirely and write directly to `outbox_events` via `await uow.outbox_events.create(...)` within the same DB transaction (preferred — see BP-060).

---

## BP-059

**Category**: Kafka / outbox — wrong topic routing

**Symptom**: Portfolio (S1) receives no instrument sync events. market-data consumers process data but no instrument events appear on `market.instrument.created` or `market.instrument.updated`.

**Root cause**: `EVENT_TOPIC_MAP` in `dispatcher.py` routed both event types to a shared legacy topic instead of their dedicated topics:

```python
# WRONG (pre QA-016 fix)
EVENT_TOPIC_MAP = {
    "market.instrument.created": "market.events.v1",  # ← WRONG
    "market.instrument.updated": "market.events.v1",  # ← WRONG
}

# CORRECT
EVENT_TOPIC_MAP = {
    "market.instrument.created": "market.instrument.created",
    "market.instrument.updated": "market.instrument.updated",
}
```

**Affected areas**: S3 (market-data) `infrastructure/messaging/outbox/dispatcher.py`; any service with a centralized `EVENT_TOPIC_MAP`.

**Regression guard**: `test_no_event_routes_to_market_events_v1` in `test_outbox_dispatcher.py` asserts no event type uses the legacy topic.

---

## BP-060

**Category**: Kafka / outbox — non-atomic event emission

**Symptom**: Events sometimes not dispatched (if `outbox_notifier` is missing or crashes after commit). Double-dispatch risk if `commit()` is called twice. Race between DB write and event emission.

**Root cause**: `uow.collect_event()` stores events in memory; they are emitted after `commit()` via the optional `outbox_notifier`. If the notifier is not wired, events are lost. Even if wired, there's a window between DB commit and notification.

**Fix**: Write directly to `outbox_events` within the same DB transaction as domain writes. The dispatcher polls and publishes atomically:

```python
# PREFERRED — atomic outbox write in consumer (no outbox_notifier needed)
event = InstrumentCreated(instrument_id=..., symbol=..., exchange=...)
await uow.outbox_events.create(
    event_type=event.event_type,
    topic=EVENT_TOPIC_MAP[event.event_type],
    payload=event_to_outbox_payload(event),
)
# event is committed atomically with the domain write in the same transaction
```

**Affected areas**: S3 consumers; any consumer emitting domain events that other services depend on.

---

## BP-061

**Category**: Domain events — missing `InstrumentUpdated` on flag change

**Symptom**: Portfolio (S1) `InstrumentRef` cache never shows `has_ohlcv=True` / `has_quotes=True` / `has_fundamentals=True` even after data has been materialized.

**Root cause**: Consumers correctly call `uow.instruments.update_flags()` when a new data type is materialized for an existing instrument, but never emit `InstrumentUpdated`. S1 only learns of flag changes via events; without the event, it never refreshes its cache.

**Affected areas**: S3 consumers (`ohlcv_consumer`, `quotes_consumer`, `fundamentals_consumer`); any consumer that updates an entity's capability flags.

**Fix**: Always emit an `InstrumentUpdated` (or equivalent) event atomically with the flag update, listing the changed fields in `fields_updated`.

---

## BP-062

**Category**: Cross-service contract — field name mismatch for stable ID

**Symptom**: Portfolio `InstrumentRef.id` is always a new `uuid7()` for each Kafka replay. `InstrumentRef.entity_id` is always `None`. Stable ID guarantee (M-017) is violated.

**Root cause**: Market-data emits events with `instrument_id` as the stable identifier. Portfolio consumer reads `value.get("entity_id")` for the stable ID. The field was never populated, so M-017 (stable ID via `entity_id`) was silently broken.

**Fix**: The producer must populate `entity_id = instrument_id` in the event payload. Use `event_to_outbox_payload()` which sets `entity_id = instrument_id` before the outbox write.

**Affected areas**: S3→S1 instrument sync; any cross-service event containing a stable entity identifier under a different name than the consumer expects.

---

## BP-063

**Category**: Kafka serialization — consumer format mismatch

**Symptom**: `json.JSONDecodeError` on Kafka message deserialization. Or garbled data (first bytes are binary, not `{`).

**Root cause**: Producer uses `OutboxEventValueSerializer` (Confluent Avro: magic byte `0x00` + 4-byte schema ID + Avro binary). Consumer does `json.loads(raw)` expecting plain JSON.

**Fix**: Use `deserialize_confluent_avro(schema_path, raw)` with a fallback to JSON:

```python
def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
    if schema_path:
        try:
            return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
        except Exception:
            pass
    return cast("dict[str, Any]", json.loads(raw))
```

**Affected areas**: S1 portfolio `InstrumentEventConsumer`; any consumer receiving from topics produced by `OutboxEventValueSerializer`.

## BP-064

**Category**: FastAPI — status code 204 with non-Response return type

**Symptom**: FastAPI raises a validation error or returns malformed response when using `@router.delete(..., status_code=204)` with a function that returns `None` or a dict in FastAPI ≤0.111.

**Root cause**: FastAPI 0.111 requires a `Response` return type annotation (or `response_class=Response`) to correctly handle status 204 without a body. Returning `None` from an endpoint with `status_code=204` triggers internal validation.

**Fix**: Use `status_code=200` and return a dict, OR explicitly annotate the return type as `Response`:

```python
# Option A (simplest):
@router.delete("/alerts/{alert_id}/ack")
async def ack(alert_id: UUID) -> dict[str, str]:
    ...
    return {"status": "acknowledged"}

# Option B (proper 204 no-content):
from fastapi import Response
@router.delete("/alerts/{alert_id}/ack", status_code=204)
async def ack(alert_id: UUID) -> Response:
    ...
    return Response(status_code=204)
```

**Affected areas**: Any FastAPI ≤0.111 DELETE/POST endpoint that returns 204.

## BP-065

**Category**: pre-commit hooks — stash/unstash conflict during commit

**Symptom**: Pre-commit hook succeeds in auto-fixing files but then fails with "Stashed changes conflicted with hook auto-fixes... Rolling back fixes...". The commit never succeeds despite ruff reporting no errors after the fix.

**Root cause**: pre-commit stashes unstaged changes before running hooks. If the hooks modify staged files AND there are untracked directories (e.g., `tests/e2e/`), the stash restore conflicts with the hook's in-place edits.

**Fix**: Run `uvx ruff format` + `uvx ruff check --fix` on all staged files BEFORE `git add` and BEFORE `git commit`. The staged index must be identical to the working tree for the files being committed:

```bash
uvx ruff format services/<service>/
uvx ruff check --fix services/<service>/
git add -u services/<service>/
git commit -m "..."
```

**Affected areas**: Any commit that includes new Python files alongside untracked directories in the repo (e.g., e2e test scaffolds, scratch dirs).

---

## BP-066

**Category**: SQLAlchemy ORM — `Mapped[datetime]` unresolvable with `from __future__ import annotations`

**Symptom**: `sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotation: "Mapped[datetime]"` when running tests that import ORM models.

**Root cause**: `from __future__ import annotations` makes ALL annotations strings (PEP 563 lazy evaluation). SQLAlchemy 2.x uses `get_type_hints()` at class-definition time to resolve `Mapped[X]` annotations. If `datetime` is imported only under `TYPE_CHECKING`, it is not in the module namespace at runtime and cannot be resolved.

**Fix**: Move `from datetime import datetime` (and any other types used in `Mapped[...]` columns) to a **runtime import** — outside the `TYPE_CHECKING` block:

```python
# WRONG — causes ArgumentError
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from datetime import datetime

# CORRECT — datetime available at runtime for SQLAlchemy
from datetime import datetime
from typing import TYPE_CHECKING, Any
```

**Affected areas**: All SQLAlchemy ORM model files using `Mapped[datetime]`, `Mapped[date]`, `Mapped[Decimal]`, or any other stdlib type that is only imported under `TYPE_CHECKING`.

---

## BP-067

**Category**: pytest configuration — `--strict-markers` + missing marker registration

**Date discovered**: 2026-03-30
**Service affected**: `alert` (discovered during QA-S4S5S6S7S10-001)

### Symptom

```
ERRORS
ERROR services/alert/tests/e2e/test_api_workflows.py - Failed: 'e2e' not found in `markers` configuration option
```

All tests in the service fail to collect, not just the e2e tests.

### Root cause

The service's `pyproject.toml` uses `addopts = "--strict-markers"` which turns any unregistered marker into a hard error at collection time. When new e2e test files are added with `pytestmark = [pytest.mark.e2e, ...]` but `e2e` is not listed in `[tool.pytest.ini_options] markers`, every test in the service's `testpaths` fails to collect.

### Fix

Add the `e2e` marker to the markers list in `pyproject.toml` before committing new e2e test files:

```toml
[tool.pytest.ini_options]
markers = [
    "unit: ...",
    "integration: ...",
    "contract: ...",
    "e2e: end-to-end tests against a real database",  # ← ADD THIS
]
```

### Affected areas

Any service using `--strict-markers` (currently: alert, content-ingestion) when e2e tests are first added. Check `addopts` in `pyproject.toml` before adding new marker types to tests.

---

## BP-068

**Category**: Docker Compose infrastructure — missing pgvector extension in postgres image

**Date discovered**: 2026-03-30
**Service affected**: S6 (nlp-pipeline), S7 (knowledge-graph) test infrastructure

### Symptom

```
ERROR:  could not open extension control file
"/usr/share/postgresql/16/extension/vector.control": No such file or directory
```

When `init-test-databases.sh` runs `CREATE EXTENSION IF NOT EXISTS vector` in the docker-entrypoint-initdb.d script, the `postgres:16-alpine` image does not include pgvector. The database creation succeeds but pgvector is missing.

### Root cause

`postgres:16-alpine` is a minimal PostgreSQL image with no third-party extensions. The `nlp_db` and `intelligence_db` databases require pgvector for `VECTOR(1024)` column types and HNSW indexes used by S6 and S7.

### Fix

Replace `postgres:16-alpine` with `pgvector/pgvector:pg16` in `docker-compose.test.yml`. This is an official image that is functionally identical to `postgres:16` but with pgvector pre-installed:

```yaml
# WRONG — no pgvector support
postgres:
  image: postgres:16-alpine

# CORRECT — pgvector pre-installed
postgres:
  image: pgvector/pgvector:pg16
```

The init script can then call `CREATE EXTENSION IF NOT EXISTS vector` without error.

### Affected areas

All test profiles using the shared `postgres` service in `docker-compose.test.yml` when S6 or S7 databases are being initialized. The `pgvector/pgvector:pg16` image is a drop-in replacement and works for all other services too.

## BP-069 — asyncpg AmbiguousParameterError when all optional filter params are None

**Category**: Database / asyncpg
**Services affected**: knowledge-graph (S7), any service using raw `text()` SQL with optional nullable parameters
**First seen**: knowledge-graph S7 `list_filtered` relation repository

### Symptom

`asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $1` at runtime when all optional filter parameters are None. The query uses the pattern `(:param IS NULL OR col = :param)` with asyncpg named params.

### Root Cause

PostgreSQL's prepared statement protocol requires each parameter to have a known type before execution. When all values are `None`, the parameter only appears in an `IS NULL` check, which doesn't constrain the type. PostgreSQL can't infer `uuid`, `text`, `float` etc. from `$1 IS NULL` alone.

### Fix

Build WHERE clauses conditionally — skip clauses entirely when the filter value is `None`:

```python
where_clauses = ["1=1"]
params: dict[str, object] = {"limit": limit, "offset": offset}
if subject_id is not None:
    where_clauses.append("r.subject_id = :subject_id")
    params["subject_id"] = str(subject_id)
where_sql = " AND ".join(where_clauses)
await session.execute(text(f"SELECT * FROM r WHERE {where_sql} LIMIT :limit"), params)  # noqa: S608
```

This avoids the type-inference problem entirely. Add `# noqa: S608` to suppress the false-positive SQL injection warning (these are static strings, not user input).

### Prevention

Avoid the `(:param IS NULL OR col = :param)` pattern with asyncpg. Always use conditional WHERE construction when parameters may be None.

## BP-070 — SQLAlchemy `func.cast()` and `func.Integer` do not exist

**Category**: SQLAlchemy / ORM
**Services affected**: nlp-pipeline (S6), any service using SQLAlchemy aggregate functions
**First seen**: nlp-pipeline S6 `signals_query.py` get_entity_detail

### Symptom

`AttributeError: Neither 'Function' object nor 'Comparator' object has an attribute '_isnull'` at runtime when a repository method uses `func.cast(expr, func.Integer)`.

### Root Cause

`func.cast` is not a standard SQLAlchemy function — it generates a SQL function call `CAST()` but the second argument `func.Integer` doesn't work because `func.Integer` creates a SQL function named "Integer" rather than a type. SQLAlchemy's `func.sum()` then tries to infer the type of the expression and fails.

### Fix

Use the top-level `cast()` and `Integer` from `sqlalchemy`:

```python
# WRONG
from sqlalchemy import func
func.sum(func.cast(expr, func.Integer))

# CORRECT
from sqlalchemy import Integer, cast, func
func.sum(cast(expr, Integer))
```

### Prevention

Never use `func.cast()` or `func.Integer`. Import `cast`, `Integer` (and other types) directly from `sqlalchemy`.

## BP-071 — FK constraint blocks manual/webhook submissions when source_id is NOT NULL

**Category**: Schema / Use Case
**Services affected**: content-ingestion (S4)
**First seen**: content-ingestion submit_content use case e2e testing

### Symptom

`sqlalchemy.dialects.postgresql.asyncpg.IntegrityError: ForeignKeyViolationError: insert or update on table "article_fetch_log" violates foreign key constraint` when the internal submit endpoint is called. The `SubmitContentUseCase` passed `doc_id` (the article UUID) as `source_id` into `article_fetch_log`, but `source_id` is a FK to `sources.id`.

### Root Cause

The `article_fetch_log.source_id` column was designed for scheduled polling sources. Manual/webhook submissions via the internal endpoint have no associated source, but the schema required a non-null source FK.

### Fix

1. Migrate `article_fetch_log.source_id` from `NOT NULL` to nullable.
2. Pass `source_id=None` in `SubmitContentUseCase.execute()`.
3. Update `FetchLogPort.create()` signature to `source_id: UUID | None`.

### Prevention

When designing tables that track both scheduled and manual events, make FK columns nullable from the start if the FK may not apply to all producers.

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

## BP-076 — asyncpg rejects PostgreSQL `::type` cast syntax in `text()` params

**Date discovered**: 2026-03-31
**Service affected**: `alert`, `nlp-pipeline`, `knowledge-graph`, `content-store` (E2E test seeds)

### Symptom

Raw SQL executed via SQLAlchemy `text()` with bound parameters fails at runtime or in tests with:

```
asyncpg.exceptions._base.UnknownPostgresError
```

or silently produces wrong results when parameters contain PostgreSQL cast notation like `:payload::jsonb` or `:id::uuid`.

### Root Cause

SQLAlchemy's `text()` constructs intentionally skip the `:name::type` pattern during parameter binding because `::` is the PostgreSQL cast operator. SQLAlchemy avoids mangling it. As a result, asyncpg receives the literal `:name::type` string instead of a positional `$N` placeholder, causing a syntax error or undefined-parameter error at the PostgreSQL driver level.

```python
# WRONG — asyncpg receives ":payload::jsonb" literally
await session.execute(
    text("INSERT INTO dlq (payload) VALUES (:payload::jsonb)"),
    {"payload": json.dumps(data)},
)

# CORRECT — use SQL standard CAST syntax
await session.execute(
    text("INSERT INTO dlq (payload) VALUES (CAST(:payload AS JSONB))"),
    {"payload": json.dumps(data)},
)
```

The same applies to `::uuid`, `::text`, `::integer`, and all other PostgreSQL cast suffixes.

### Fix

Replace all `:name::type` patterns in SQLAlchemy `text()` statements with `CAST(:name AS TYPE)`.

### Prevention

- Grep new SQL literals for `::` followed by a type name: `grep -rn '::\w\+' services/*/src/`
- Add a pre-commit check or test that rejects `text("...::\w")` patterns in source files
- Document this constraint in service `.claude-context.md` files for services with heavy raw SQL

---

## BP-077 — `ON CONFLICT DO NOTHING` missing `index_where=` for partial unique index

**Date discovered**: 2026-03-31
**Service affected**: `content-ingestion` (`IngestionTaskRepository.create_if_not_exists`)

### Symptom

A repository `upsert` or `insert_ignore` using SQLAlchemy's `on_conflict_do_nothing` fails at runtime with:

```
sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.InvalidColumnReferenceError)
there is no unique or exclusion constraint matching the ON CONFLICT specification
```

The failure only manifests when `window_start` (or another nullable column) is NOT NULL, because the partial index `WHERE window_start IS NOT NULL` only covers those rows.

### Root Cause

PostgreSQL `ON CONFLICT (col1, col2)` must reference a unique constraint or index **exactly**, including any `WHERE` clause for partial indexes. If the unique index is defined as:

```sql
CREATE UNIQUE INDEX ix_cit_source_window
    ON ingestion_tasks (source_id, window_start)
    WHERE window_start IS NOT NULL;
```

Then the SQLAlchemy dialect must match the predicate:

```python
# WRONG — no index_where, PostgreSQL cannot match the partial index
stmt.on_conflict_do_nothing(index_elements=["source_id", "window_start"])

# CORRECT
from sqlalchemy import text
stmt.on_conflict_do_nothing(
    index_elements=["source_id", "window_start"],
    index_where=text("window_start IS NOT NULL"),
)
```

### Fix

Add `index_where=text("<predicate>")` matching the partial index `WHERE` clause verbatim.

### Prevention

- Whenever a table has partial unique indexes, the corresponding repository `ON CONFLICT` clause must include `index_where=`
- Add `index_where` to the migration review checklist when `CREATE UNIQUE INDEX ... WHERE` appears

---

## BP-078 — Cross-service E2E `ImportError` when service package not installed

**Date discovered**: 2026-03-31
**Service affected**: `tests/e2e/test_security_isolation.py`, `tests/e2e/test_market_data_pipeline.py`

### Symptom

Cross-service E2E tests collect and fail with:

```
ImportError: No module named 'portfolio'
```

or

```
ImportError: No module named 'market_ingestion'
```

even though the test is decorated with a skip marker like:

```python
@pytest.mark.skipif(not _S1_UP, reason="S1 not reachable")
async def test_cross_tenant_holdings_isolation(...):
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    ...
```

The skip marker fires correctly when the service is unreachable, but the import still executes because Python processes the function body before `pytest.skip()` can run within the test function.

### Root Cause

`pytest.mark.skipif` evaluated at collection time prevents the test from being *scheduled*, but when `skipif` evaluates to `False` (service IS reachable) the test body runs, and a service that is reachable over HTTP may still not have its Python package installed in the test runner environment. The import fails with `ImportError` before any assertion.

Additionally, even when `skipif` is `True`, pytest collects the test function and evaluates skip markers; however, imports inside the function body can still surface during collection in some configurations.

### Fix

Wrap all service-package imports inside the test body with a `try/except ImportError` guard:

```python
async def test_cross_tenant_holdings_isolation(...):
    try:
        from portfolio.infrastructure.db.models.instrument import InstrumentModel
    except ImportError:
        pytest.skip("portfolio package not installed in cross-service test environment")
    ...
```

### Prevention

- All cross-service tests that import from another service's package MUST use `try/except ImportError: pytest.skip(...)` guards
- Never use bare top-level service-package imports in `tests/e2e/` files — only inside test functions with the guard
- Add this pattern to the review checklist for any new cross-service E2E test file

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

## BP-080 — pytest-asyncio 0.24 loop scope mismatch: `session` loop + function-scoped async fixtures

**Affected areas**: Any service using pytest-asyncio 0.24 with async fixtures

**Symptom**

Test teardown raises:

```
RuntimeError: Event loop is closed
```

after all tests pass, causing the overall test run to fail with a non-zero exit code.

**Root Cause**

`asyncio_default_fixture_loop_scope = "session"` with pytest-asyncio 0.24 creates a single event loop shared across the test session. When async generator fixtures have function scope (the default), their teardown (`yield`-after cleanup) executes after the test function completes but may run after the session loop has been torn down, causing `RuntimeError: Event loop is closed`.

This is especially common after changing a fixture from `session`-scoped to `function`-scoped (e.g., to fix a different isolation bug) without updating the pyproject.toml loop scope settings.

**Fix**

Set both loop scope settings to `"function"` in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_default_fixture_loop_scope = "function"
asyncio_default_test_loop_scope = "function"
```

Each test function then gets its own event loop, and fixture teardown always runs within an active loop.

**Prevention**

- `asyncio_default_fixture_loop_scope` and `asyncio_default_test_loop_scope` must always match the narrowest scope of any async fixture in the test suite
- Prefer `"function"` scope for both settings unless there is a strong measured performance reason to use `"session"`
- When adding or changing fixture scopes, verify both pyproject.toml settings remain consistent

---

## BP-081 — httpx `AsyncClient` double-open: `RuntimeError: Cannot open a client instance more than once`

**Affected areas**: Integration/E2E tests using `httpx.AsyncClient` fixtures

**Symptom**

Test fails immediately with:

```
RuntimeError: Cannot open a client instance more than once
```

**Root Cause**

An `AsyncClient` instance that was already opened (e.g., by a pytest fixture using `async with AsyncClient(...) as client:`) is used again as a context manager inside a test:

```python
# Fixture already opens the client:
@pytest.fixture
async def integration_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# Test tries to open it again — WRONG:
async def test_something(integration_client):
    async with integration_client as client:  # ← raises RuntimeError
        resp = await client.get("/endpoint")
```

**Fix**

Use the pre-opened client directly without wrapping it in `async with`:

```python
async def test_something(integration_client):
    resp = await integration_client.get("/endpoint")  # ← correct
```

**Prevention**

- Never use `async with <fixture_client> as client:` in tests — the fixture already manages the lifecycle
- Code review checklist: flag any `async with` usage on a variable that was received as a fixture parameter

---

## BP-082 — SQLAlchemy ORM enum column: `ValueError` when seed data uses wrong case

**Affected areas**: Tests that insert rows into tables with `Enum`-typed columns via raw SQL or dict-based inserts

**Symptom**

Test fails with:

```
ValueError: 'breakout_signal' is not a valid AlertType
```

when loading ORM rows after seeding the database.

**Root Cause**

SQLAlchemy `Enum` column types backed by Python `StrEnum` (or `enum.Enum`) coerce the stored string back into the enum member on load. If the stored value does not exactly match a member value (including case), the coercion raises `ValueError`. Test seeds using lowercase (`"signal"`) or arbitrary strings (`"breakout_signal"`) that are not valid enum member values cause this error when any code path loads those rows through the ORM.

**Fix**

Always use the exact enum member value (uppercase for `StrEnum` with uppercase values):

```python
# Wrong:
alert_type="signal"
alert_type="breakout_signal"

# Correct:
alert_type="SIGNAL"
alert_type="GRAPH_CHANGE"
```

**Prevention**

- Test seed functions must use enum member values, not arbitrary strings
- When adding a new enum value, search all test seeds for usages of that column and update them
- Consider defining seed constants from the actual enum class: `AlertType.SIGNAL.value`

---

## BP-083 — DLQ pagination: `total` field returns page count instead of DB total

**Affected areas**: Any paginated list API endpoint where `total` should reflect the full DB count

**Symptom**

API response returns `total = len(page)` (e.g., `2`) when the actual DB count is larger (e.g., `5`), causing pagination-aware clients or tests to undercount available records.

**Root Cause**

A common mistake when implementing paginated list endpoints:

```python
entries = await repo.list_failed(limit=limit, offset=offset)
return DLQListResponse(entries=entries, total=len(entries))  # ← wrong
```

`len(entries)` is the count of items in the current page, not the total across all pages.

**Fix**

Add a separate `count_failed()` query to the repository and use it for the `total` field:

```python
entries = await use_case.list_failed(limit=limit, offset=offset)
total = await use_case.count_failed()
return DLQListResponse(entries=[...], total=total)
```

Requires adding `count_failed()` to the port ABC, concrete repository, and use case.

**Prevention**

- All paginated endpoints MUST derive `total` from a `COUNT(*)` query, not `len(page)`
- Review checklist: when reviewing any paginated list endpoint, verify `total` comes from a separate count query
- Port ABCs for repositories should include `count_*()` methods alongside `list_*()` methods from the start

---

## BP-084 — `.gitignore` `src/` rule blocks new service source files from being tracked

**Category**: git — untracked files silently ignored

**Symptom**: `git add services/<service>/src/<new_file>.py` appears to succeed but `git diff --cached --name-only` returns empty. `git status` shows the file as untracked. New `*_main.py` entry points or other new source files under `services/*/src/` cannot be staged normally.

**Root cause**: `.gitignore` contains a bare `src/` rule (line 66 in this repo — added as a "Local attached source folder" marker). This rule matches **any directory named `src/` anywhere in the repo tree**, which includes every `services/*/src/` directory. New (untracked) files in those directories are silently ignored by git.

**Fix**: Use `git add -f` (force) to stage ignored files:

```bash
git add -f services/<service>/src/<new_file>.py
```

Or, if adding many new files in a service:

```bash
git add -f services/<service>/src/
```

**Prevention**

- When adding new source files under any `services/*/src/` path and `git status` does not show them as staged, check with `git check-ignore -v <path>` before assuming staging failed.
- The `src/` entry in `.gitignore` is intentional (for local IDE source-attachment workflows) — do not remove it. Always use `git add -f` for new files in service `src/` directories.

---

## BP-085 — Config field reuse: `otlp_endpoint` used as ML model URL

**Context**: Process topology refactoring (PLAN-0011) — standalone `*_consumer_main.py` entry points

**Symptom**: Embedding client silently connects to OpenTelemetry collector instead of Ollama. All vector embeddings fail or return nonsense. Error message resembles Jaeger/Tempo connection refused rather than Ollama.

**Root cause**: `settings.otlp_endpoint` was copy-pasted as the Ollama `base_url` fallback: `base_url=settings.otlp_endpoint or "http://ollama:11434"`. When OTLP is configured (e.g., `http://tempo:4317`), this URL is sent to the Ollama adapter instead of the OTel exporter endpoint.

**Fix**: Add a dedicated `ollama_base_url: str = "http://ollama:11434"` field to `Settings` (and optionally `embedding_model_id: str = "nomic-embed-text"`), then use `settings.ollama_base_url` in the entry point.

**Prevention**: Never reuse config fields for unrelated purposes. When writing a new entry point, check that every settings field used actually corresponds to the purpose implied by its name.

---

## BP-086 — Hardcoded Kafka consumer group IDs in standalone entry points

**Context**: Process topology refactoring — standalone `*_consumer_main.py` entry points

**Symptom**: Consumer group cannot be overridden via environment variable. Blue/green deployments collide on the same group ID. Non-default `kafka_consumer_group` in `.env` is silently ignored for some consumers but respected for others in the same service.

**Root cause**: Consumer group IDs hardcoded as string literals (`group_id="kg-fundamentals-group"`) instead of derived from `settings.kafka_consumer_group` with a suffix.

**Fix**: Replace hardcoded strings with `f"{settings.kafka_consumer_group}-{suffix}"` (e.g., `f"{settings.kafka_consumer_group}-fundamentals"`).

**Prevention**: When writing a new `*_consumer_main.py`, always derive `group_id` from `settings.kafka_consumer_group`. Search the same service's other consumer mains for the correct pattern before writing a new one.

---

## BP-087 — In-process WebSocket `ConnectionManager` dead in standalone consumer process

**Context**: Process topology refactoring — standalone `*_consumer_main.py` entry points

**Symptom**: WebSocket push notifications to browser clients never fire. `AlertFanoutUseCase.broadcast()` executes without error but no clients receive the message. Log shows events processed successfully.

**Root cause**: `ConnectionManager` maintains an in-memory set of WebSocket connections. When consumers run as separate OS processes, the consumer process has its own empty `ConnectionManager` instance with zero connections (all connections are registered in the API process).

**Fix**: Implement a cross-process pub/sub bridge (e.g., Valkey pub/sub). The consumer process publishes to a Valkey channel; the API process subscribes and broadcasts to WebSocket clients.

**Prevention**: Any in-process mutable state (connection registries, caches, queues) that was shared between the consumer and API in a monolithic deployment will break after process separation. Audit all stateful objects passed to use cases in standalone consumer entry points.

---

## BP-088 — `asyncio.Event` patch causes infinite recursion in entrypoint tests

**Context**: Unit testing standalone consumer `main()` functions that create an `asyncio.Event` for shutdown signalling.

**Symptom**: `RecursionError: maximum recursion depth exceeded` inside `unittest.mock`. The stack shows repeated calls to the side_effect function from inside itself.

**Root cause**: The `side_effect` helper calls `asyncio.Event()` to create a pre-set event, but `asyncio.Event` has already been patched by `patch("asyncio.Event", side_effect=helper)`. The helper therefore calls itself recursively.

**Fix**: Capture the real `asyncio.Event` class at module level BEFORE any test patches it:
```python
_REAL_ASYNCIO_EVENT = asyncio.Event  # module-level, before any patches

def _preset_event(*_args, **_kwargs):
    e = _REAL_ASYNCIO_EVENT()  # real class, not the patch
    e.set()
    return e
```

**Prevention**: Any `side_effect` function that instantiates a class being patched must hold a reference to the original class captured before the patch context is entered.

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

## BP-089 — Tautology assertions in entry-point tests: `assert X == f"{X}"`

**Services affected**: knowledge-graph, (any service with standalone consumer entry point tests)
**Detected**: PLAN-0013 QA pass (2026-04-01)

### Symptom

A test that is supposed to verify a constructor argument (e.g., `group_id`) passes
unconditionally because the assertion compares a variable to the identical expression
used to define it:

```python
expected_group = f"{settings.kafka_consumer_group}-fundamentals"
assert expected_group == f"{settings.kafka_consumer_group}-fundamentals"  # always True
```

The test passes even if the production code never constructs a `ConsumerConfig` at all.

### Root Cause

When the mock class is captured (`as mock_consumer_cls`) but the assertion is written
with the literal formula instead of inspecting `mock_consumer_cls.call_args`, the test
becomes a no-op.

### Fix

Capture the mock class with `as mock_cls` and assert on `call_args`:

```python
) as mock_cls,
...

call_kwargs = mock_cls.call_args
assert call_kwargs is not None
config_arg = call_kwargs.kwargs.get("config") or (
    call_kwargs.args[0] if call_kwargs.args else None
)
assert config_arg is not None
assert config_arg.group_id == f"{settings.kafka_consumer_group}-fundamentals"
```

### Prevention

In entrypoint tests, every constructor-argument assertion must reference
`mock_cls.call_args`, not restate the expected value formula.
Review checklist item: "Does the assertion inspect production behaviour, or does
it merely compare two identical expressions?"

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

## BP-091 — AGE Cypher injection via f-string entity_id

**Services affected**: knowledge-graph (S7) — `CypherPathUseCase`, `CypherNeighborhoodUseCase`
**Detected**: PRD-0018 security analysis (2026-04-04)

### Symptom

A Cypher query built with an f-string allows an attacker to manipulate graph traversal,
bypass confidence filters, or trigger unexpected query patterns. Even though `entity_id`
is validated as a UUID, the AGE `cypher()` function executes the full string as Cypher —
UUID validation does not prevent injection in other query parameters.

### Root Cause

```python
# WRONG — Cypher injection vector:
query = f"""
SELECT * FROM ag_catalog.cypher('worldview_graph', $$
  MATCH path = shortestPath((s:Entity {{entity_id: '{entity_id}'}})-[r*1..{max_hops}]->(...))
$$) AS (path ag_catalog.agtype)
"""
```

The `max_hops` parameter is an integer but still f-stringed; if the validation is bypassed,
arbitrary Cypher can be injected via other parameters.

### Fix

Use AGE parameterized Cypher with the `params` argument to `ag_catalog.cypher()`:

```python
query = text("""
SELECT * FROM ag_catalog.cypher('worldview_graph', $$
  MATCH path = shortestPath(
    (s:Entity {entity_id: $source})-[r*1..5]->(t:Entity {entity_id: $target})
  )
  WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_conf)
  RETURN path
$$, :params) AS (path ag_catalog.agtype)
""")
result = await session.execute(query, {
    "params": json.dumps({"source": str(source_id), "target": str(target_id), "min_conf": min_confidence})
})
```

Note: `max_hops` must be hardcoded in the Cypher template (not parameterized) since Cypher
variable-length patterns `[r*1..N]` do not accept runtime parameters for `N`. The route layer
enforces `max_hops ≤ 5` before the use case is called.

### Prevention

All AGE Cypher queries must use `ag_catalog.cypher(..., :params)` with a JSON params dict.
Never f-string any variable into a Cypher query string, even validated UUIDs.
REVIEW_CHECKLIST item: "AGE Cypher queries — parameterized, not f-stringed."

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

## BP-093 — EODHD API: Assumed fields don't exist (`General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment`)

**Symptom**: Implementation fetches `payload.get("General", {}).get("Officers", {})` but always gets `{}` even for large-cap companies with many executives. Similarly, `Holders.Institutions` and `Financials.Revenue_Segment` always return empty/absent.

**Root Cause**: These three sections (`General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment`) **do not exist** in the EODHD Fundamentals API response. They were assumed based on EODHD documentation that describes different response formats from different API tiers/endpoints.

**Affected Areas**: S7 `FundamentalsConsumer`, any code reading EODHD fundamentals payload from MinIO, PRD/plan sections referencing these fields.

**Correct Data Sources**:
| Intended Signal | Correct EODHD Source |
|-----------------|---------------------|
| Company officers / executives | `GET /insider-transactions?code={ticker}.US` — `ownerName` + `ownerTitle` |
| Institutional ownership | `SharesStats.PercentInstitutions` (aggregate %, from fundamentals payload) |
| Insider ownership | `SharesStats.PercentInsiders` (aggregate %, from fundamentals payload) |
| Geographic revenue breakdown | Not available — derive from `headquartered_in` + macro context |

**Fields That DO Exist** in EODHD fundamentals payload:
- `General.FullTimeEmployees` (int)
- `Highlights.RevenueTTM` (int, USD)
- `SharesStats.PercentInsiders` (float)
- `SharesStats.PercentInstitutions` (float)
- `General.Description` (str)
- All of: `Highlights` (MarketCap, EBITDA, PERatio, ROE, ROA), `Valuation` (TrailingPE, ForwardPE, EV/EBITDA)

**Prevention**: Before implementing any EODHD data extraction, verify the field exists in `docs/references/eodhd-endpoints-reference.md` against the Outputs section with actual JSON examples.


## BP-096 — FastAPI Route Parameters Must Not Be Under TYPE_CHECKING

**Pattern**: FastAPI route function parameters that appear in type annotations (e.g., `request: Request`) must be importable at runtime. Placing the import inside `if TYPE_CHECKING:` causes `PydanticUndefinedAnnotation` at application startup when FastAPI/Pydantic resolves the route's dependency graph.

**Symptom**:
```
pydantic.errors.PydanticUndefinedAnnotation: name 'Request' is not defined
```

**Cause**: `from __future__ import annotations` makes all annotations strings (lazy), but FastAPI's `get_dependant()` still evaluates them at route registration time via `get_type_hints()`. If `Request` (or any other route-parameter type) is only available under `TYPE_CHECKING`, this lookup fails.

**Fix**: Always import types used in route function signatures at module level (not under `TYPE_CHECKING`):
```python
# WRONG
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fastapi import Request

@router.get("/readyz")
async def readyz(request: Request) -> Response: ...

# CORRECT
from fastapi import APIRouter, Request  # ← runtime import

@router.get("/readyz")
async def readyz(request: Request) -> Response: ...
```

**Types that CAN be under TYPE_CHECKING**: return type annotations that FastAPI doesn't inspect at registration (only if the return type is a concrete Pydantic model or `dict`), and service-specific types used only in the function body (not the signature).

**Applies to**: All FastAPI services (S1–S10) when using `from __future__ import annotations`.

---

## BP-097 — Read Engine Connection Leak in Dual-Session Factory

**Pattern**: `_build_factories()` creates a separate `read_engine` when `database_url_read` differs from `database_url`, but only returns `write_engine` in the tuple. The `read_engine` is bound to `read_factory` via SQLAlchemy's internal reference, but is never explicitly disposed on shutdown.

**Symptom**: Graceful shutdown (e.g. Kubernetes SIGTERM) leaves read-replica TCP connections open until OS timeout. No data loss, but violates graceful shutdown contract and causes connection exhaustion under repeated rolling restarts.

**Cause**: Pattern `return write_engine, write_factory, read_factory` — only `write_engine` is tracked, so only `write_engine.dispose()` is called at shutdown.

**Fix**: Return both engines (or a named tuple) from `_build_factories()`:
```python
# WRONG — read_engine leaked on shutdown
return write_engine, write_factory, read_factory

# CORRECT — both engines tracked
return write_engine, read_engine_or_none, write_factory, read_factory
# OR store read_engine in app.state.read_engine for disposal in lifespan shutdown
app.state.read_engine = read_engine if read_url != write_url else None
```

**Only manifests when**: `database_url_read` is explicitly set to a different URL than `database_url`. All services default to empty (fallback), so this is a latent bug.

**Applies to**: All services implementing R23 dual-session (S1, S4, S5, S6, S7, S10, S8).

---

## BP-098 — Config Re-Export Shim Breaks AST Architecture Tests

**Pattern**: A service's `config.py` uses a thin re-export shim (`Settings = OtherSettingsClass`) instead of defining the `Settings` class directly. AST-based architecture tests that visit `ClassDef` nodes (like R23 and config-pattern tests) cannot detect fields defined in the aliased class.

**Symptom**: Architecture tests fail for the service with violations like "Settings missing a write database URL field" even though the service IS compliant — the actual class is in a different file.

**Fix Options**:
1. **Preferred**: Define the `Settings` class directly in `config.py` (standard pattern for all services)
2. **Workaround**: Add the service to the test's `_BASELINE` dict with explanation
3. **Test improvement**: Enhance AST visitor to follow `Settings = X` assignments and scan `X`'s source file

**Applies to**: Any service using `infrastructure/config/settings.py` as the canonical settings location (non-standard — avoid this pattern).

---

## BP-099 — DDL Alignment Test Misses ALTER TABLE ADD COLUMN Migrations

**Category**: DB / Testing
**Affected areas**: Any service whose `test_ddl_alignment.py` uses `_extract_ddl_columns()` with only `CREATE TABLE` parsing

**Symptom**: DDL alignment test reports `ORM columns missing from DDL: {'column_name'}` after adding a column via an `ALTER TABLE` migration — even though the migration is correct and the ORM is updated.

**Root cause**: The `_extract_ddl_columns` helper only parses `CREATE TABLE` blocks. When a column is added via a later `ALTER TABLE {table} ADD COLUMN` migration, it never appears in the CREATE TABLE DDL and the test falsely flags it as missing.

**Fix**: Extend `_extract_ddl_columns` to also scan for `ALTER TABLE {table_name} ADD COLUMN [IF NOT EXISTS] <col_name>` patterns using `re.finditer`:
```python
alter_pattern = rf"ALTER\s+TABLE\s+{table_name}\s+ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)"
for m in re.finditer(alter_pattern, migration_text, re.IGNORECASE):
    columns.add(m.group(1))
```

**First seen**: PLAN-0016 Wave A-2 — adding `context_valkey_key` + `summary_valkey_key` to `messages` table in rag-chat (migration 0002).

**Applies to**: Any service with incremental Alembic migrations that add columns to existing tables.

---

## BP-100 — PRD References Non-Existent External API Field

**Category**: Process / PRD quality
**Affected areas**: Any PRD/plan that references EODHD, SnapTrade, Polymarket, DeepInfra, or other external provider fields without verification

**Symptom**: Implementation hits `KeyError`, `AttributeError`, or silent `None` at runtime because the referenced field never existed in the external provider's response. Alternatively, the field name is wrong (e.g., different nesting level, camelCase vs snake_case).

**Root cause**: The PRD author (human or agent) assumed a field exists in an external API response without verifying against actual API documentation or a live response. The assumption propagates into domain entities, DB columns, and consumers before anyone tests against the real API.

**Real examples**:
- PRD-0018 referenced `General.Officers`, `Holders.Institutions`, `Financials.Revenue_Segment` from EODHD — none exist. Replaced with Insider Transactions API endpoint.

**Prevention**:
1. `/prd` Phase 2.7 External API Reality Check — every external field must be marked `Verified: YES` with a source before the PRD is written
2. If field cannot be verified in the session, it MUST be raised as a BLOCKING open question
3. `/revise-prd` Phase 4 explicitly checks this before planning

**Fix pattern**: Remove the non-existent field from the domain entity, DB column, and Avro schema. Identify the correct field or alternative API endpoint and update the PRD.

---

## BP-101 — PRD Describes Stale Architecture Baseline

**Category**: Process / PRD quality
**Affected areas**: Any PRD written before an architectural change lands; any plan derived from a PRD >14 days old

**Symptom**: Implementation produces conflicting code — duplicated logic, wrong index types, migration that tries to create an already-existing column, or tests that assert the old behavior.

**Root cause**: The PRD was written based on the architecture state at a point in time. Since then, the codebase evolved (e.g., index type changed, table restructured, new pattern adopted) but the PRD was not updated to reflect the new baseline. The plan inherits the stale assumption and generates tasks that conflict with reality.

**Real examples**:
- PRD-0017 specified IVFFlat indexes for `entity_embedding_state`; the codebase had already migrated to HNSW partial indexes. PRD had to be revised before planning.

**Prevention**:
1. `/revise-prd` Phase 3 Codebase Alignment Check — reads actual source code and diffs PRD claims against current state
2. `/plan` Phase 0.5 PRD Pre-Flight Gate — flags PRDs created >14 days ago for mandatory `/revise-prd` before decomposing waves
3. After any architectural change (index, schema, pattern), run `/revise-prd --all-draft` to check all pending PRDs

**Fix pattern**: Run `/revise-prd` on the affected PRD, resolve each stale assumption with the user, and update the PRD in-place before generating or proceeding with the plan.

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

## BP-103 — ValkeyClient Wrapper Type Annotation Drift

**Category**: Type system / libs/messaging
**Affected areas**: Any service that accepts a Valkey/Redis client as a constructor argument

**Symptom**: mypy reports `Argument "valkey" has incompatible type "ValkeyClient"; expected "Redis"` in `app.py` when wiring components. No runtime error (ValkeyClient passes all required methods to the underlying redis.asyncio.Redis).

**Root cause**: New components are sometimes written with `import redis.asyncio as aioredis` + `aioredis.Redis` as the type hint, copying patterns from older code or redis.asyncio documentation. The project's shared `ValkeyClient` (from `libs/messaging`) wraps `redis.asyncio.Redis` but is not a subclass, so mypy rejects the assignment.

**Secondary risk**: Unstaged additions to `ValkeyClient` (e.g. `pipeline()`, `setex()`) look correct locally but the pre-commit hook stashes unstaged files — callers fail with `attr-defined` in the hook run even though the method is visible in the working tree.

**Fix**:
1. All `valkey` parameters must be typed as `ValkeyClient` (not `aioredis.Redis`):
   ```python
   # In TYPE_CHECKING block
   from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
   # In __init__ signature
   def __init__(self, valkey: ValkeyClient, ...) -> None:
   ```
2. If `ValkeyClient` is missing a needed method, add it to `libs/messaging/src/messaging/valkey/client.py` and stage the change in the **same commit** as the callers.
3. Never use `setex(key, ttl, b"1")` — `ValkeyClient.setex` expects `str`, not `bytes`.

**Prevention**: Code review checklist: reject any `aioredis.Redis` or `redis.asyncio.Redis` parameter type annotation in service code.

**First seen**: PLAN-0016 Wave B-1 fix — S1Client, LLMProviderChain, HydeExpander all had `aioredis.Redis` instead of `ValkeyClient`.

---

## BP-105 — DLQ `original_event_id` Set to New UUID Instead of Kafka Event ID

**Category**: Data correctness / infrastructure
**Affected areas**: Any `dead_letter()` override in `BaseKafkaConsumer` subclasses

**Symptom**: DLQ entries have an `original_event_id` that bears no relation to the original Kafka message. Operators cannot correlate a DLQ entry with the Kafka topic, the `processed_events` table, or Avro envelope to diagnose root cause.

**Root cause**: `dead_letter()` override copies `dlq_id=common.ids.new_uuid7()` to both columns — `dlq_id` (correct, new PK) and `original_event_id` (wrong, should be `UUID(failure.event_id)`). The two fields have similar construction and are trivially confused.

**Fix**: `original_event_id=UUID(failure.event_id)` where `failure.event_id` is the string event_id extracted from the Kafka envelope. Add a `try/except ValueError` fallback to generate a new UUID if `failure.event_id` is not a valid UUID string (defensive, should not happen in practice).

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S5 `article_consumer.py:205`.

---

## BP-106 — `asyncio.shield()` Around Stop-Event Wait Leaks Background Tasks

**Category**: Resource leak / asyncio
**Affected areas**: Background scheduler loops, any `asyncio.wait_for` around an `asyncio.Event.wait()`

**Symptom**: `asyncio.shield(self._stop_event.wait())` creates a detached background task that is never cancelled when `wait_for` raises `TimeoutError`. The coroutine lingers until the event fires, which may be long after the enclosing function has returned.

**Root cause**: `asyncio.shield()` is intended to protect a coroutine from cancellation when the *parent* is cancelled. It does not protect against `TimeoutError` — `wait_for` will still raise, but the shielded inner coroutine continues executing independently. This creates an uncollected task and `ResourceWarning: coroutine was never awaited`.

**Fix**: Remove `asyncio.shield()` — use `await asyncio.wait_for(self._stop_event.wait(), timeout=...)` directly. The `wait_for` timeout cancels the inner coroutine on timeout by default, which is the correct behaviour for a tick-loop sleep.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4 `scheduler_main.py:63`.

---

## BP-107 — `asyncio.timeout` Wraps Semaphore Acquisition, Not Just Execution

**Category**: Correctness / asyncio
**Affected areas**: Worker processes using `asyncio.Semaphore` with `asyncio.timeout`

**Symptom**: Tasks time out while waiting for a concurrency slot (semaphore), before they even begin executing. Timeout budget is consumed by queue wait time, not actual work.

**Root cause**: Placing `asyncio.timeout(T)` outside `async with self._semaphore:` starts the timeout clock when the task *arrives at the semaphore*, not when it *acquires* the semaphore. If `worker_concurrency` tasks are all busy, the `(concurrency + 1)`th task times out after `T` seconds of waiting even though it never ran.

**Fix**: Swap the nesting — acquire the semaphore first, then apply the timeout around the actual execution:
```python
async with self._semaphore:
    try:
        async with asyncio.timeout(self._task_timeout):
            await self._execute_task(task)
    except TimeoutError:
        ...
```

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4 `worker.py:_execute_with_semaphore`.

---

## BP-108 — Read Engine Not Disposed in Process Entrypoints (Dual-URL Split)

**Category**: Resource leak / infrastructure
**Affected areas**: All standalone process entrypoints that call `_build_factories()` (dispatcher_main, consumer_main, worker)

**Symptom**: When `DATABASE_URL_READ` is set to a distinct endpoint, the read engine connection pool is never closed on shutdown. Under load, this exhausts PostgreSQL connection slots over time.

**Root cause**: Entrypoints copy `_engine.dispose()` but forget the conditional `_read_engine.dispose()`. The `app.py` lifespan correctly checks `if read_engine is not engine: await read_engine.dispose()`, but this pattern is not replicated in standalone process entrypoints.

**Fix**: Add after `await _engine.dispose()` in every process entrypoint:
```python
if _read_engine is not _engine:
    await _read_engine.dispose()
```
Also update test mocks: `return_value=(mock_engine, mock_engine, ...)` rather than `(mock_engine, MagicMock(), ...)` so the condition is False and `MagicMock().dispose()` is never awaited.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4/S5 dispatcher_main + S5 article_consumer_main.

---

## BP-109 — Non-Atomic `ZADD` + `EXPIRE` in Valkey LSH Index Leaves Immortal Keys

**Category**: Data correctness / Valkey
**Affected areas**: Any code that writes to Redis/Valkey sorted sets and then sets a TTL as two separate commands

**Symptom**: If the process crashes or the Valkey connection drops between `ZADD` and `EXPIRE`, the sorted-set key exists with **no TTL**. These keys grow unbounded and are never evicted, consuming Valkey memory indefinitely.

**Root cause**: `await redis.zadd(key, ...)` followed by `await redis.expire(key, ttl)` is not atomic. Any failure between the two leaves the key without a TTL.

**Fix**: Use a Redis pipeline to batch both commands in a single round-trip:
```python
async with redis.pipeline(transaction=False) as pipe:
    pipe.zadd(key, {member: score})
    pipe.expire(key, ttl)
    await pipe.execute()
```
Note: `transaction=False` (MULTI/EXEC not used) is sufficient here — the key is process-local per band; the atomicity concern is crash-between-commands, not concurrent writers.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S5 `lsh_client.py:index()`.

---

## BP-110 — Settings Re-Export Shim Not Staged Causes Mypy Pre-Commit Failures

**Category**: Tooling / Pre-commit hooks
**Affected areas**: Any service that splits config into `config.py` (canonical) + `infrastructure/config/settings.py` (re-export shim)

**Symptom**: `mypy` passes when run directly (`mypy services/<service>/src --config-file mypy.ini`) but fails in the pre-commit hook with errors like `"RagChatSettings" has no attribute "database_url"` or `Argument 1 has incompatible type "RagChatSettings"; expected "Settings"`.

**Root cause**: The pre-commit hook stashes ALL unstaged working-tree changes before running `mypy`. If `infrastructure/config/settings.py` (the shim that re-exports `Settings as RagChatSettings`) has unstaged working-tree changes — because it was refactored in a prior wave but not committed — the hook stashes it back to the committed version (which was the full class, not the shim). Mypy then sees two different types: `Settings` (from `rag_chat.config`) and `RagChatSettings` (from the committed full class), and treats them as incompatible.

**Fix**: Before committing any wave that touches the settings type, stage `infrastructure/config/settings.py` explicitly, even if the wave didn't formally change it:
```bash
git add services/<service>/src/<service>/infrastructure/config/settings.py
```
Also ensure all files in the module that reference `RagChatSettings` use the same canonical import path (`from rag_chat.infrastructure.config.settings import RagChatSettings`) so mypy resolves both sides to the same type.

**Prevention**: When introducing a `config.py` → `infrastructure/config/settings.py` shim in a wave, commit the shim in the same wave — do not leave it as an unstaged working-tree change.

**First seen**: PLAN-0016 Wave B-2 (2026-04-07), rag-chat S8.

---

## BP-111 — `aiosmtplib.SMTPConnectError` Constructor Changed in v3

**Category**: Dependency API change · **Severity**: Test failure (TypeError)
**Affected areas**: Any test constructing `aiosmtplib.SMTPException` subclasses directly

**Symptom**: `TypeError: SMTPException.__init__() takes 2 positional arguments but 3 were given` when constructing `aiosmtplib.SMTPConnectError(code, message)` in tests.

**Root cause**: `aiosmtplib` v3 changed the `SMTPException` base class constructor from `(code: int, message: str)` to `(message: str)` only. The error code is no longer a positional argument.

**Fix**: Use the single-argument form:
```python
# v2 (wrong in v3)
aiosmtplib.SMTPConnectError(421, "Service unavailable")

# v3 (correct)
aiosmtplib.SMTPConnectError("Service unavailable")
```

**Prevention**: Pin `aiosmtplib>=3.0,<4` in `pyproject.toml` and use single-argument form consistently in tests.

**First seen**: PLAN-0016 Wave C-2 (2026-04-07), alert S10.

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

## BP-114 — EODHD Demo Key Rate-Limits Silent `[]` for EOD OHLCV Under Concurrent Load

**Date discovered**: 2026-04-07
**Category**: External API / demo key behavior · **Severity**: MEDIUM (test data gap)
**Affected areas**: S2 market-ingestion worker, E2E tests asserting bar counts

**Symptom**: EODHD `/api/eod/AAPL.US?api_token=demo&period=d` returns HTTP 200 with body `[]` (empty JSON array, 2 bytes). Task succeeds, canonical NDJSON is 0 bytes. Tests that assert `bar_count > 0` skip.

**Root cause**: The EODHD demo API key has a low concurrent request rate limit. When the worker processes 30 tasks simultaneously (concurrency=4), the first 4-6 requests succeed with real data; subsequent requests for the same session receive empty `[]`. The EOD endpoint (daily/weekly/monthly) is more affected than real-time quotes, which use a separate endpoint.

**Evidence**: Worker logs show `row_count=1` for the first few quotes tasks and `row_count=0` for all subsequent EOD OHLCV tasks. Bronze objects contain `b'[]'`.

**Distinguishing from BP-112/BP-113**: This is NOT a bug in the codebase — the task correctly succeeds with 0 rows. It is a demo-key operational limitation.

**Mitigation options**:
1. Use a real (paid) EODHD API key for E2E tests — provides full data
2. Set `WORKER_CONCURRENCY=1` in test docker.env to serialize requests
3. Add a per-provider rate limiter in the worker (token bucket, 1 req/s for demo key)
4. In test assertions, skip on `row_count=0` rather than failing (already done in E2E tests)

**Prevention**: Document that E2E tests requiring EODHD OHLCV bar data need a real API key. The demo key is only reliable for quotes and fundamentals under low concurrency.

**First seen**: E2E investigation (2026-04-07), S2 market-ingestion full pipeline test.

---

## BP-120 — Post-Commit Hook Failures Silently Suppressed (Cache Invalidation Lost)

**Date discovered**: 2026-04-07
**Category**: Distributed Systems / Cache Consistency · **Severity**: MAJOR
**Affected areas**: S3 market-data `UnitOfWork.commit()`, S1 portfolio watchlist use case

**Symptom**: After a successful DB write and Kafka offset commit, the Valkey cache contains stale data with no mechanism to detect or repair it. Logs show `post_commit_hook_failed` warning but execution continues normally.

**Root cause**: Post-commit hooks (cache invalidation coroutines) are executed in a `try/except Exception: logger.warning(...)` block inside `commit()`. If Valkey is unavailable during hook execution, the exception is suppressed, the Kafka offset is already committed, and the stale cache entry persists until the next TTL expiry or explicit write.

**Evidence**:
- `services/market-data/src/market_data/infrastructure/db/uow.py:131-137`
- `services/portfolio/src/portfolio/application/use_cases/watchlist.py:229-236`

**Distinguishing from BP-003/004**: This is not a test setup issue — it occurs in production when Valkey is down or slow.

**Mitigation options**:
1. **Option A** (strict): Re-raise hook exception → consumer retries the Kafka message → stale cache gap is bounded by retry backoff
2. **Option B** (async repair): Persist hook failure to a dead-letter table → background job replays failed invalidations
3. **Option C** (accept): Current behaviour — stale cache for up to TTL (5s for quotes, varies for watchlists). Only acceptable if downstream callers can tolerate stale reads.

**Prevention**: When writing new post-commit hooks, explicitly document the consistency model. If the hook is critical (cache invalidation for a real-time feed), use Option A. If it's best-effort, document it and monitor `post_commit_hook_failed` counter.

**First seen**: QA pass QA-S1S2S3-2026-04-07 (finding M-002/M-003).

---

## BP-121 — BGE-large BERT Context Overflow Crashes Ollama GGML Runner

**Symptom**: Ollama returns `500 Internal Server Error` with `{"error":"do embedding request: Post ... EOF"}`. Docker logs show `GGML_ASSERT(i01 >= 0 && i01 < ne01) failed` and `llama runner terminated: signal: aborted`. Subsequent embedding requests continue returning 500 until the model is manually reloaded.

**Root cause**: BGE-large (`bert.context_length: 512`, `position_embd.weight shape: [1024, 512]`) has a hard 512-token BERT context window. Financial text with numbers, tickers, and dollar amounts tokenizes at ~3 chars/token (denser than typical English at ~4-5 chars/token). An article of 339 words in financial English can exceed 512 tokens after adding the instruction prefix (e.g., `"Represent this financial document passage for retrieval: "`). When the token index reaches position 512, the GGML matrix index check `i01 < ne01` fires, killing the runner subprocess.

**Fix**: In `OllamaEmbeddingAdapter.embed()` (`libs/ml-clients/src/ml_clients/adapters/ollama_embedding.py`), truncate the combined `(prefix + text)` string to `_MAX_CHARS = 1500` before sending. This keeps the tokenized length under 500 tokens (leaving margin for CLS/SEP special tokens).

**Affected areas**: Any service using `OllamaEmbeddingAdapter` with section-level or document-level texts; particularly NLP-pipeline S6 `run_embeddings_block` which embeds full section texts (not chunks).

**Prevention**: Always truncate input to BERT-based models at the adapter level. Do not rely on the model to truncate — BERT position embeddings are statically sized and do NOT truncate gracefully (they crash). Use `_MAX_CHARS = context_length * min_chars_per_token` as the safe limit.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

## BP-122 — Confluent Avro Wire Format Not Detected in S6 Consumer

**Symptom**: `article_consumer.py` raises `json.JSONDecodeError: Expecting value: line 1 column 1` or `AttributeError` when trying to read fields from the Kafka message. The message bytes start with `\x00` (magic byte) followed by 4 bytes schema ID — this is Confluent Schema Registry wire format, not JSON.

**Root cause**: The content-store dispatcher (S5) publishes `content.article.stored.v1` using Confluent Avro serialization (5-byte header: magic `0x00` + 4-byte schema ID + Avro binary payload). The original S6 consumer called `json.loads(raw)` directly, which fails on binary Avro payloads.

**Fix**: Override `deserialize_value()` in `ArticleProcessingConsumer` to detect the `\x00` magic byte and call `deserialize_confluent_avro(schema_path, raw)` from `messaging.kafka.serialization_utils`. Override `get_schema_path()` to return the `.avsc` file path for the topic.

**Affected areas**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`. Any consumer reading from topics published by Schema Registry-aware producers.

**Prevention**: When connecting a consumer to a topic produced with Confluent Schema Registry: (1) check if the first byte is `\x00`, (2) strip the 5-byte header, (3) use `fastavro.schemaless_reader` with the loaded schema. Never assume Kafka messages on SR topics are plain JSON.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

## BP-123 — GLiNER `predict_entities(list)` Returns Empty List — Batch API Unsupported

**Symptom**: GLiNER server returns `{"results": []}` (empty) for every batch request despite receiving valid texts. Consumer logs `ner_http_batch_completed, total_entities: 0`.

**Root cause**: `GLiNER.predict_entities(texts, labels)` where `texts` is a list returns `[]` — the GLiNER library batch API is broken (the implementation only works when `texts` is a single string). Passing a list silently returns nothing.

**Fix**: In `infra/gliner/server.py`, change `_run_batch()` to iterate texts individually: `[model.predict_entities(text, ...) for text in req.texts]`. Do NOT call `model.predict_entities(req.texts, ...)` — the batch overload does not work.

**Affected areas**: `infra/gliner/server.py` — the GLiNER HTTP server used by NLP pipeline S6.

**Prevention**: When using GLiNER: always pass a single string to `predict_entities`, wrap iteration at the call site. Do not assume the batch overload works — verify with a quick unit test.

**First seen**: 2026-04-08 E2E NLP pipeline investigation.

---

## BP-124 — Kafka Consumer Idempotency Check Skips Embedding on Entity Replay

**Symptom**: Entity exists in `canonical_entities` table but `entity_embedding_state.embedding` is permanently NULL for that entity. Embedding refresh worker never generates an embedding for it.

**Root cause**: `InstrumentEntityConsumer.process_message()` checks `if entity exists → early return`. If the pod crashes after the DB commit (entity created) but before offset commit, the message is replayed. On replay, the early return at `entity_repo.get()` is triggered, and `_def_worker.refresh_for_entity()` is never called. The definition embedding row is left permanently absent.

**Fix**: Change the idempotency check to be embedding-aware. If the entity exists but the definition embedding row is absent (or `embedding IS NULL`), still call `refresh_for_entity`. Alternatively, fold `refresh_for_entity` into the same DB transaction scope as entity creation.

**Affected areas**: Any Kafka consumer in S7 that creates an entity and then calls a worker with a separate DB session (two-phase write). Specifically `instrument_consumer.py`.

**Prevention**: When splitting consumer work into "create entity" + "trigger enrichment" phases, ensure the idempotency guard covers both phases. A "entity present but embedding absent" state must still trigger enrichment.

**First seen**: PLAN-0017 QA pass 2026-04-08.

---

## BP-125 — pgvector Cosine Distance Formula Off-By-Two

**Symptom**: ANN similarity scores can be negative; final_score returns < 0 to API caller despite `min_score=0.0` filter.

**Root cause**: pgvector `<=>` cosine distance range is `[0, 2]` (not `[0, 1]`). Using `similarity = 1.0 - distance` produces negative values when distance > 1.0. For L2-normalized embeddings cosine distance is always in `[0, 1]`, making the formula safe in practice — but without an explicit floor clamp, any unnormalized embedding produces negative scores.

**Fix**: Use `ann_similarity = max(0.0, 1.0 - ann.distance)` as a safety floor. If the team wants the mathematically correct formula for the full `[0, 2]` range: `ann_similarity = 1.0 - ann.distance / 2.0`.

**Affected areas**: Any service performing pgvector ANN search and converting distance to similarity: `entity_embedding_ann.py`, `relation_summary.py`, any future ANN use case.

**Prevention**: Always add `max(0.0, ...)` floor when converting pgvector distances to similarity scores.

**First seen**: PLAN-0017 QA pass 2026-04-08.

---

## BP-126 — Alembic Migration NOT NULL Column Missing server_default

**Symptom**: `psycopg.errors.NotNullViolation: null value in column "X"` when inserting from seed scripts, tools, or future workers that omit the column.

**Root cause**: SQLAlchemy ORM models can declare `server_default=text("now()")` on a column, but Alembic migrations do NOT inherit `server_default` from the ORM model. If the migration `sa.Column(...)` definition omits `server_default`, the DDL column has no server-side default even though the ORM model appears to.

**Fix**: Always explicitly set `server_default=sa.text("now()")` (or the appropriate literal) in the Alembic `op.create_table(...)` column definition when the ORM model has a `server_default`.

**Affected areas**: Every Alembic migration that adds a NOT NULL column with a `server_default` in the ORM model.

**Prevention**: In code review, always cross-check: if ORM model has `server_default`, migration must too. If ORM model has `nullable=False`, either migration has `server_default` or all code paths explicitly provide the column.

**First seen**: PLAN-0017 migration 004 QA pass 2026-04-08.

---

## BP-127 — pre-commit ruff-format Version Mismatch Causes Phantom Reformat Loop

**Symptom**: `git commit` fails with `ruff-format: 1 file reformatted, N files left unchanged` even after running `uvx ruff format` on all staged files. The hook passes when run via `pre-commit run ruff-format` standalone but fails on commit. Re-staging after formatting doesn't help if the wrong ruff version is used.

**Root cause**: The pre-commit config pins `ruff-pre-commit` to a specific version (e.g., `v0.4.0`) in `.pre-commit-config.yaml`. Running `uvx ruff format` uses a newer version of ruff from the default uvx cache. When the two versions produce different formatting for the same file, `uvx ruff format` marks the file as clean but the hook's pinned version reformats it again on commit.

**Fix**:
1. Identify the pinned ruff binary: `find ~/.cache/pre-commit -name "ruff" -path "*ruff-pre-commit*"`.
2. Use the pinned binary to format before staging: `~/.cache/pre-commit/repo*/py_env-python3.14/bin/ruff format <file>`.
3. Verify staged content is clean: `git show ":$file" | <pinned-ruff> format --stdin-filename "$file" -` should produce no diff.

**Prevention**: Always format using the same version as the pre-commit hook. Either pin `uvx ruff` to match (`uvx ruff@0.4.0 format`), or add a Makefile target that uses the pre-commit-managed binary.

**Affected areas**: Any Python file in any service/lib when the pre-commit ruff version differs from the local/uvx ruff version.

**First seen**: nlp-pipeline Issues 1–3 commit, 2026-04-08.

## BP-128 — AGE Extension Functions Fail on New Connections Due to Missing Session Setup

**Symptom**: `ERROR: function create_graph does not exist` or `ERROR: type "agtype" does not exist` when calling Apache AGE functions (e.g., `create_graph`, `cypher`, `create_vlabel`) inside a migration or worker. Works in one session but fails in a fresh connection.

**Root cause**: Apache AGE requires two session-level commands before any AGE function can be used:
```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```
These are **not persistent** — they must be re-executed at the start of every database connection. If not configured via `shared_preload_libraries = 'age'` in `postgresql.conf`, every session (Alembic migration, async SQLAlchemy connection, direct psql) must call them explicitly. Workers with connection pooling will silently fail on connections that were created before the session setup.

**Fix**:
1. Preferred: add `'age'` to `shared_preload_libraries` in `postgresql.conf` (Docker image config). This makes AGE available to every connection automatically.
2. Fallback: add session setup in every code path that issues AGE commands:
   ```python
   await session.execute(text("LOAD 'age'"))
   await session.execute(text("SET search_path = ag_catalog, public"))
   ```
3. For Alembic migrations: include `LOAD 'age'` and `SET search_path` in the migration script itself (before any `create_graph()` call).

**Prevention**: Add `_setup_age_session()` helper to `AgeSyncWorker` and call it at the start of every `run()`. Add connection event listener in the session factory that auto-issues these commands for AGE-enabled sessions.

**Affected areas**: `intelligence-migrations` migration 0004, `AgeSyncWorker` (Worker 13F), `CypherPathUseCase`, `CypherNeighborhoodUseCase`.

**First seen**: PRD-0018 audit, 2026-04-08.

## BP-129 — Watermark-Based Incremental Sync Fails When Target Table Lacks `updated_at`

**Symptom**: An incremental sync worker (watermark pattern: `WHERE updated_at > :watermark`) silently syncs zero rows or crashes with `column does not exist` for tables that only have `created_at` or `latest_evidence_at` but not `updated_at`.

**Root cause**: The `relations` table (and similar append-heavy tables) often track `created_at` and `latest_evidence_at` but not a generic `updated_at`. When a watermark-based sync worker queries `WHERE updated_at > :watermark`, it either: (a) fails with a column error, or (b) silently misses rows whose confidence was recomputed (which updates `confidence_last_computed_at` but not `updated_at`).

**Fix**: Before implementing a watermark sync worker, verify every source table has an `updated_at` column that is updated on ALL mutation paths (initial insert + subsequent updates). If missing, add it via a non-destructive migration:
```sql
ALTER TABLE relations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX idx_relations_updated_at ON relations (updated_at DESC);
```
Also add an `ON UPDATE` trigger or ensure all application-layer update paths explicitly set `updated_at = utc_now()`.

**Prevention**: PRD §6.4 DB table definitions should always include `updated_at` for any table used as a sync source. Plan migrations should verify the column exists before implementing the worker.

**Affected areas**: `AgeSyncWorker` (Worker 13F) — `relations` table required migration 0004 to add `updated_at`.

**First seen**: PRD-0018 audit, 2026-04-08.

## BP-130 — `DirectKafkaProducerProtocol.produce_bytes` Has No Concrete Adapter — AttributeError in Production

**Symptom**: `AttributeError: 'cimpl.Producer' object has no attribute 'produce_bytes'` in S7 hot-path graph write (every enriched article that materialises relations/claims). The `EnrichedArticleConsumer` processes the article, reaches step 5 of `materialize_entities()`, and crashes. Articles end up in the DLQ. `entity.dirtied.v1` is never produced.

**Root cause**: `DirectKafkaProducerProtocol` in `graph_write.py` defines a `produce_bytes(topic, key, value)` method as the interface. However `confluent_kafka.Producer` has no such method — only `produce(topic, value, key, ...)`. The `enriched_consumer_main.py` passes a raw `confluent_kafka.Producer` with `# type: ignore[arg-type]`, masking the duck-type mismatch. At runtime, `direct_producer.produce_bytes(...)` raises `AttributeError`.

**Fix**: Create a `ConfluentDirectProducer` adapter class that wraps `confluent_kafka.Producer` and implements `produce_bytes`:
```python
class ConfluentDirectProducer:
    def __init__(self, producer: Producer) -> None:
        self._producer = producer

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None:
        """Enqueue to librdkafka buffer — non-blocking, no flush."""
        self._producer.produce(topic, value=value, key=key)
```
Do NOT call `flush()` — `produce()` alone enqueues to the internal librdkafka buffer and is sub-millisecond. `flush()` is synchronous-blocking and would block the asyncio event loop. Delivery is handled by librdkafka's background thread.

In `enriched_consumer_main.py`:
```python
raw_producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
direct_producer = ConfluentDirectProducer(raw_producer)  # remove # type: ignore
```

**Prevention**:
- Never use `# type: ignore[arg-type]` to pass a dependency that doesn't satisfy the Protocol — this suppresses the type mismatch that would have caught the bug.
- When defining a Protocol for an external library type, immediately create the adapter in the same commit.
- Add a protocol conformance test: `isinstance(direct_producer, DirectKafkaProducerProtocol)` or mypy structural check.

**Affected areas**: `enriched_consumer_main.py`, `graph_write.py` step 5, any EODHD worker wired with a direct producer, `provisional_enrichment.py`.

**First seen**: PRD-0018 investigation, 2026-04-09.

## BP-131 — NULL Values in Multi-Column Unique Index Allow Semantic Duplicates

**Symptom**: Two rows exist in a table that should have been deduplicated by an `ON CONFLICT` upsert. One or more of the unique index columns is NULL. The upsert succeeds without conflict and creates a duplicate row.

**Root cause**: PostgreSQL standard behavior — `NULL ≠ NULL` in unique indexes. Two rows where the nullable column is NULL and all other columns are identical do NOT conflict with each other. The `ON CONFLICT (col_a, col_b, nullable_col, col_c) DO UPDATE` clause never fires for these rows.

**Examples in this codebase**:
- `temporal_events.uidx_temporal_events_natural_key` on `(event_type, region, title, date_trunc('day', active_from))` — LOCAL events have `region=NULL`; two LOCAL events with the same type/title/date create two rows
- BP-007 is a related pattern

**Fix options** (pick one):
1. **PostgreSQL 15+**: `CREATE UNIQUE INDEX ... ON table (...) NULLS NOT DISTINCT` — treats NULL as a distinct value in the uniqueness check. Requires dropping and recreating the index.
2. **Partial index** (all PG versions): `CREATE UNIQUE INDEX ... ON table (col_a, col_b, col_c) WHERE nullable_col IS NULL` plus the original index for non-NULL values. Requires two `INSERT` branches (one per NULL/non-NULL case).
3. **Sentinel value**: Replace NULL with a sentinel string (e.g., `__NULL__`). Ugly but universally compatible.
4. **Accept it**: If a compensating dedup mechanism (Valkey event-id dedup, application-level guard) covers the most common re-delivery paths, accepting rare semantic duplicates may be the pragmatic choice.

**Prevention**: When designing tables with nullable columns in unique constraints, explicitly decide which option to use and document it in the migration DDL comment. Verify the PostgreSQL version supports NULLS NOT DISTINCT if that option is chosen (PG ≥ 15).

**Affected areas**: `temporal_events.uidx_temporal_events_natural_key` (LOCAL events with NULL region), any table with nullable columns in a multi-column unique constraint.

**First seen**: PRD-0018 investigation, 2026-04-09.

## BP-132 — Hardcoded StrEnum Count Test Breaks When Shared Lib Enum Is Extended

**Symptom**: A downstream service unit test fails with `AssertionError` after adding a new member to `ContentSourceType` (or any other shared-lib StrEnum). The test in the downstream service hardcodes the expected set of values as an exact frozenset.

**Root cause**: Tests like `assert {v.value for v in SourceType} == {"eodhd", "sec_edgar", ...}` are membership-exact: they fail if any new value is added. When `libs/contracts.ContentSourceType` is extended with a new member (e.g., `POLYMARKET`), the test in `content-store`, `nlp-pipeline`, or any service that re-exports `ContentSourceType` as `SourceType` will fail.

**Example (PLAN-0019)**: `services/content-store/tests/unit/domain/test_enums.py::test_all_five_sources` hardcoded 5 values. Adding `POLYMARKET` in Wave A-1 caused an extra `"polymarket"` value that was not in the expected set.

**Fix**: Update the expected set to include the new value, and rename the test to avoid encoding the count in the test name (e.g., `test_all_five_sources` → `test_all_sources`).

**Prevention**: When adding a member to any StrEnum in `libs/contracts`, `libs/messaging`, or any shared library, search for `{v.value for v in SourceType}` / `== expected` patterns in ALL service test directories and update every hardcoded expected set in one atomic PR. Prefer additive assertions (`assert "polymarket" in {v.value for v in SourceType}`) over equality assertions for extensible enums.

**Affected areas**: `services/content-store/tests/unit/domain/test_enums.py`, any service that aliases or re-exports `ContentSourceType`.

**First seen**: PLAN-0019 QA pass, 2026-04-09.

## BP-133 — New Consumer Entry Point Missing From docker-compose.test.yml

**Symptom**: Architecture test `COMPOSE-MAIN-MISSING` fails with `<service>: <consumer_main.py> has no matching container in docker-compose.test.yml`. All unit tests pass but the architecture gate fails.

**Root cause**: When a new `*_consumer_main.py` (or `*_worker_main.py`) entry point is added to a service, a matching container must be registered in `infra/compose/docker-compose.test.yml`. The architecture test `test_every_entry_point_has_compose_container` scans all `*_main.py` files in `infrastructure/messaging/consumers/` and verifies a matching container command exists.

**Example (PLAN-0019)**: `prediction_market_consumer_main.py` was added to market-data in Wave B-1 but the `market-data-prediction-market-consumer` container was not added to `docker-compose.test.yml`.

**Fix**: Add a container entry following the pattern of sibling consumers (e.g., `market-data-ohlcv-consumer`). The container must appear under the same profiles and depend on `market-data-migrate`, `schema-registry-init`, `kafka-init`.

**Prevention**: Include the `docker-compose.test.yml` entry as an explicit task in every plan wave that adds a `*_main.py` entry point. The `/implement` skill should verify no `COMPOSE-MAIN-MISSING` violations remain before committing.

**Affected areas**: `infra/compose/docker-compose.test.yml`, any service adding a new consumer or worker process entry point.

**First seen**: PLAN-0019 QA pass, 2026-04-09.


## BP-134 — Live/Network Tests Missing `pytest.mark.live` Causes Fixture Scope Mismatch

**Symptom**: Running `pytest tests/ -m "not integration and not e2e"` still collects tests from `tests/live/` that fail with `ScopeMismatch: You tried to access the function scoped fixture _function_scoped_runner with a module scoped request object`. 55 errors in market-ingestion, 11 in market-data.

**Root cause**: Tests in `tests/live/` use `pytestmark = [pytest.mark.skipif(...)]` for network gating but are not decorated with `@pytest.mark.live`. Without a `live` marker, the `-m "not live"` filter does not exclude them. The fixture uses `scope="module"` on an asyncio fixture that pytest-asyncio resolves at function scope, causing a scope mismatch error.

**Fix**: Add `pytest.mark.live` to `pytestmark` in all `tests/live/*.py` files:
```python
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _is_network_available(), reason="No network connectivity"),
]
```
Then register `live` as a custom marker in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["live: requires live network access to external APIs"]
```

**Prevention**: Include `@pytest.mark.live` as a required marker in the `/test-feature` skill and REVIEW_CHECKLIST when writing tests in `tests/live/`.

**Affected**: `services/market-ingestion/tests/live/`, `services/market-data/tests/live/`.

**First seen**: Pre-Hetzner deployment QA pass, 2026-04-09.

## BP-135 — Consumer `process_message` Calls `uow.commit()` — Double-Commit Per Message

**Symptom**: Each Kafka message is committed twice: once inside `process_message` and once by the `BaseKafkaConsumer` base class after the method returns. Downstream effects include double-write errors for idempotency constraints, and test assertions like `uow.commit.assert_called_once()` failing unexpectedly.

**Root cause**: `process_message` calls `await uow.commit()` directly. The `BaseKafkaConsumer` already calls `commit()` after `process_message` returns (if no exception), so the transaction is committed twice.

**Fix**: Remove `await uow.commit()` from `process_message`. The base class owns the single commit. If the use case needs to commit mid-method (e.g., for outbox dispatch), use a different pattern or document why explicitly.

**In unit tests**: Assert `uow.commit.assert_not_called()` inside `process_message` tests — the base class mock is the correct location for commit assertions in integration/e2e tests.

**First seen**: QA pass PLAN-0019, 2026-04-09 (M-04). Fixed in `PredictionMarketConsumer.process_message`.

## BP-136 — Shared Session Poisoned After Exception — Missing Rollback in Per-Item Loop

**Symptom**: A use case iterates over a list and writes each item atomically (fetch_log + outbox + commit). If item N fails, the exception handler increments `failed` but does NOT rollback. The shared SQLAlchemy session is now in an aborted transaction state. All subsequent items in the loop fail immediately with `sqlalchemy.exc.InvalidRequestError: Can't reconnect until invalid transaction is rolled back`.

**Root cause**: Missing `await session.rollback()` (or equivalent) in the `except` block of the per-item loop.

**Fix**: Call `await self._rollback_fn()` in the `except` block before continuing to the next iteration. Pass `rollback_fn=session.rollback` from the worker when constructing the use case.

**Prevention**: Any use case that shares a session across multiple loop iterations MUST have a `rollback_fn` parameter. Review checklist: "Does the exception handler rollback before continuing the loop?"

**First seen**: QA pass PLAN-0019, 2026-04-09 (M-02). Fixed in `FetchAndWritePredictionMarketsUseCase.execute`.

## BP-137 — Helm values.yaml Key Mismatch Causes Silent Misconfiguration

**Symptom**: A service is deployed via Helm but starts without a required env var (e.g., `DEEPINFRA_API_KEY` is empty). Kubernetes shows the pod as `Running`/`Ready` because `/health` does not validate all config. The misconfiguration surfaces only at runtime when the first request exercises the missing config path.

**Root cause**: The key name in `infra/helm/values/<service>.yaml` under `env:` does not match what the Deployment template injects, or the key was renamed in the values file but the template variable reference was not updated. `helm install` succeeds silently; the env var is simply absent.

**Fix**: After any change to `infra/helm/values/*.yaml` or the Deployment template:
1. Run `helm template <svc> infra/helm/worldview-service -f infra/helm/values/<svc>.yaml` and inspect the rendered `env:` block
2. Run `kubectl -n worldview exec <pod> -- env | grep <KEY>` after deploy to verify presence
3. Run `./scripts/ci-local.sh --job validate-helm` to catch render failures in CI

**Prevention**:
- `validate-helm` is now part of `ci-local.sh --job all` and runs on every push
- For each new env var added to a values file, manually verify the Deployment template propagates it
- `helm test` hooks with env-var assertions are the most reliable guard (deferred)

**First seen**: Investigation 2026-04-10 — identified as deployment risk for PLAN-0024 Wave A-2.

## BP-138 — Kafka Consumer Crashes on Non-Numeric Float Field

**Symptom**: Consumer dead-letters an event with `TypeError: float() argument must be a string or a number, not 'NoneType'` or `ValueError: could not convert string to float`. The event never reaches the use case; the crash is silent (just logged) and the partition continues processing with offset committed.

**Root cause**: `float(value.get("field", 0.0))` raises `TypeError` when the field is `None` (JSON null) and `ValueError` when it is a non-numeric string. Both arise from Avro union types that include `null` or from schema mismatches between producers.

**Fix**: Guard with try/except:
```python
raw = value.get("market_impact_score", 0.0)
try:
    score = max(0.0, min(1.0, float(raw or 0.0)))
except (ValueError, TypeError):
    score = 0.0
```

**Prevention**: Any consumer extracting a float from a Kafka event dict must use the guarded pattern above. Add a unit test for `None` and non-numeric string values.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-003/F-055/F-157 merged finding).

---

## BP-139 — Unguarded JSON.parse in WebSocket onmessage Crashes React Tree

**Symptom**: Component tree crashes with `SyntaxError: Unexpected token` when the WebSocket server sends a non-JSON frame (keepalive bytes, proxy error, partial flush). Error boundary catches it but the WS connection remains open and state stops updating.

**Root cause**: `JSON.parse(event.data)` called without try/catch inside `ws.onmessage`.

**Fix**:
```typescript
ws.onmessage = (event: MessageEvent) => {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(event.data as string) as Record<string, unknown>;
  } catch {
    return; // skip malformed frame
  }
  ...
};
```

**Prevention**: Every React hook that wraps a WebSocket `onmessage` must wrap `JSON.parse` in try/catch. Add a unit test that passes a non-JSON string as `event.data`.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-014/F-152 merged finding).

---

## BP-140 — Settings Fields Defined But Never Read (Dead Config)

**Symptom**: Operators set an env var expecting to tune behavior (e.g., `ALERT_ALERT_SEVERITY_CRITICAL_THRESHOLD=0.9`), but the service ignores it because the Settings field is defined but never passed to the domain object that uses it. Behavior is silently hardcoded.

**Root cause**: Settings field added in `config.py`, but the consumer/service entry-point that constructs the domain object (e.g., `SeverityThresholds`) passes `None` or uses the default, never reading `settings.<field>`.

**Fix**: In the entry-point (`*_main.py` or `app.py`), explicitly pass all threshold/config fields when constructing domain objects:
```python
SeverityThresholds(
    critical=settings.alert_severity_critical_threshold,
    high=settings.alert_severity_high_threshold,
    medium=settings.alert_severity_medium_threshold,
)
```

**Prevention**: When adding a `Settings` field that controls domain behavior, grep for all constructors of the affected domain object and verify each reads from `settings`. Add the mock value to `_mock_settings()` in entrypoint tests.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-202 Architecture finding).

---

## BP-141 — Repository-Level session.rollback() Poisons Shared Session Context

**Symptom**: After a `DuplicateAlertError` (or any IntegrityError caught in a repo `save()` method), subsequent writes in the same request fail silently or raise `InvalidRequestError: Can't operate on rolled-back transaction`.

**Root cause**: A repo method calls `await self._session.rollback()` inside an `except IntegrityError` block. This rolls back the shared session that was created by the outer `async with session_factory() as session:` context manager. The context manager's own rollback-on-exit path then has nothing to do, but any code that continues after catching `DuplicateAlertError` operates on a dead session.

**Fix**: Remove `await self._session.rollback()` from repo-level exception handlers. Let the exception propagate; the `async with session_factory()` context manager handles rollback via `__aexit__`. The use case catches `DuplicateAlertError` and returns early without committing, so the session exits cleanly.

**Prevention**: Repository `save()` methods must NEVER call `session.rollback()` directly. Only the use-case-level `async with session_factory()` context manager owns the rollback.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-150 Distributed Systems finding).

---

## BP-142 — E2E Test Assumes Endpoint Convention Without Verifying Actual Path

**Category**: Test Correctness
**Severity**: CRITICAL (silent test failure in deployment validation)

**Pattern**: An E2E or smoke test hardcodes an endpoint path based on common convention (e.g., `/health`, `/status`, `/ping`) without checking what paths the service actually exposes. The test fails with HTTP 404 whenever the service uses a different convention (e.g., `/healthz`, `/api/v1/health`), producing false negatives that look identical to a real outage.

**Symptom**: Deployment readiness tests report service failure with `HTTP 404` even though the service is perfectly healthy and running on the expected port.

**Root cause**: The worldview scaffold generates `/healthz` (Kubernetes liveness probe convention) but the test was written using the generic HTTP health endpoint convention `/health`. No cross-reference with OpenAPI or `.claude-context.md` was done when writing the test.

**Fix**: Always derive test endpoint paths from the canonical source:
1. Check `services/<service>/.claude-context.md` for documented endpoints.
2. Or verify against the service's OpenAPI spec: `GET /openapi.json → .paths | keys[]`.
3. For worldview specifically: all services expose `/healthz` (not `/health`) and `/metrics` for Prometheus.

**Prevention**:
- When writing E2E/smoke tests against services, validate the endpoint path against the service's OpenAPI spec or `.claude-context.md` first.
- Add a comment in the test citing where the path convention is documented: `# /healthz per PRD-0024 §6.4 and scaffold convention`.

**First seen**: `tests/e2e/test_deployment_readiness.py`, commit `964f06a`, found and fixed 2026-04-11.


## BP-143 — Starlette Middleware Order: InternalJWT Outermost Sees user=None

**Category**: Architecture / Middleware
**Severity**: HIGH (silent security failure — internal JWT never issued)

**Pattern**: When registering `InternalJWTIssuerMiddleware` via `add_middleware()` AFTER `OIDCAuthMiddleware`, Starlette makes it the OUTERMOST middleware (runs first for requests). At that point `request.state.user` is not yet set by OIDCAuth, so the JWT issuance is silently skipped. All downstream service calls arrive without `X-Internal-JWT`.

**Symptom**: Backend services log `X-Internal-JWT header missing` 401 errors. No error in S9 — the middleware silently no-ops because `user is None`.

**Root cause**: Starlette's `add_middleware()` prepends middleware to the chain. Last added = outermost = first to receive requests. `InternalJWTIssuerMiddleware.dispatch()` reads `request.state.user` which is set by `OIDCAuthMiddleware` — but if InternalJWT runs before OIDCAuth, user is always None.

**Fix**: Register `InternalJWTIssuerMiddleware` BEFORE `OIDCAuthMiddleware` in `create_app()`:
```python
app.add_middleware(InternalJWTIssuerMiddleware)  # innermost of this pair — runs after OIDCAuth
app.add_middleware(OIDCAuthMiddleware)           # outermost of this pair — runs first
```

**Prevention**:
- Comment the intended request-processing order next to `add_middleware()` calls.
- Write integration test `test_proxy_request_includes_internal_jwt` that asserts `X-Internal-JWT` in downstream headers — this test fails immediately if order is wrong.
- Remember: in Starlette, "last `add_middleware()` call = outermost = first to receive requests".

**First seen**: `services/api-gateway/src/api_gateway/app.py`, PLAN-0025 Wave B, fixed 2026-04-12.


## BP-144 — Middleware Reads `app.state` at Construction Time — Feature Permanently Disabled

**Category**: Middleware / FastAPI
**Severity**: HIGH (silent feature failure — rate limiting / feature silently off)

**Pattern**: A FastAPI middleware captures a dependency (e.g., Valkey client, config flag) at `__init__` time by reading `app.state.<attr>`. Because `add_middleware()` is called before the lifespan populates `app.state`, the value is always `None`. The `dispatch()` method then checks `self.attr` (always `None`) and fast-paths through, disabling the feature for the entire process lifetime.

**Symptom**: Rate limiting, feature flags, or other middleware-controlled behavior never activates. No error is logged. Metrics counters remain at zero.

**Root cause**: FastAPI lifespan populates `app.state` after all middleware is registered. `self.attr = app.state.attr_name` in `__init__` captures `None`.

**Fix**: Read the dependency from `request.app.state` inside `dispatch()`:
```python
async def dispatch(self, request: Request, call_next):
    client = getattr(request.app.state, "valkey", None)
    if client is None:
        return await call_next(request)  # graceful degradation
    ...
```

**Prevention** (HR-028): Grep for `self\.<attr>\s*=.*app\.state` in middleware `__init__` methods. Any capture at construction time is suspect unless the value is a constant.

**First seen**: `services/api-gateway/src/api_gateway/middleware/rate_limit.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.


## BP-145 — JWT Decode Without `issuer=` — Issuer Spoofing Auth Bypass

**Category**: Security / Authentication
**Severity**: CRITICAL (auth bypass)

**Pattern**: `jwt.decode(token, public_key, algorithms=["RS256"])` is called without `issuer=expected_issuer`. The library validates the signature but does NOT check the `"iss"` claim. A token signed by any provider — or an attacker's own key pair — is accepted.

**Symptom**: Tokens from unexpected issuers are accepted silently. No error is raised. The `payload["sub"]` is trusted and used to identify the user.

**Fix**: Always pass `issuer=oidc_config.issuer` (and `audience` if applicable):
```python
payload = jwt.decode(
    token, public_key, algorithms=["RS256"],
    issuer=settings.oidc_issuer,
    audience=settings.oidc_client_id,
)
```

**Prevention** (HR-026): Grep `jwt\.decode\(` and verify every call includes `issuer=`. Add a test asserting that a token from a different issuer is rejected with 401.

**First seen**: `services/api-gateway/src/api_gateway/middleware/oidc_auth.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.


## BP-146 — PKCE / One-Time Token: Non-Atomic GET + DEL Enables State Replay

**Category**: Security / Race Condition
**Severity**: CRITICAL (PKCE replay vulnerability)

**Pattern**: A one-time-use secret (PKCE code verifier, nonce, CSRF token) is retrieved from Valkey using `GET key` then `DEL key` — two separate commands. Under concurrent load, two requests both execute `GET` before either executes `DEL`. Both receive the value, breaking the one-time-use guarantee.

**Root cause**: `GET` + `DEL` is not atomic. Valkey pipelines help throughput but do not make two commands atomic.

**Fix**: Use the atomic `GETDEL` command (Redis 6.2+, Valkey 7+):
```python
async def retrieve_and_delete(self, key: str) -> str | None:
    return await self._client.getdel(key)  # atomic GET-then-DELETE
```

**Prevention** (HR-027): Any "retrieve once and delete" operation on a security token MUST use `GETDEL` or a Lua script. Never use `GET` + `DEL` on the same key for one-time-use tokens.

**First seen**: `libs/messaging/src/messaging/valkey/client.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12 (added `ValkeyClient.getdel()`).


## BP-147 — Outbox Dispatcher Missing Serializer Registration → KeyError Dead-Letter

**Category**: Kafka / Outbox
**Severity**: HIGH (silent event loss)

**Pattern**: A Kafka outbox dispatcher maps event type strings to Avro serializers via `_SERIALIZERS: dict[str, Callable]`. When a new Kafka event type is introduced (e.g., by a new PRD), the serializer dict is not updated. The dispatcher raises `KeyError` and the message is moved to the dead-letter queue.

**Symptom**: New events never appear at the consumer. DLQ count increases. No startup error — failure occurs only when the first message of the new type is dispatched.

**Fix**: Add the missing serializer registration:
```python
_SERIALIZERS = {
    "content.article.raw.v1": article_ser,
    "market.prediction.snapshot": prediction_ser,  # ← was missing
}
```

**Prevention**: When adding a new Kafka event type, checklist: (1) Avro schema, (2) topic constant, (3) outbox serializer registration, (4) DLQ test. Write a startup validation test that asserts every known event type has a registered serializer.

**First seen**: `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox_dispatcher.py`, PLAN-0025 QA Phase 2, fixed 2026-04-12.


## BP-148 — Avro Schema Field With Empty String Default — Schema Registry Rejection

**Category**: Kafka / Avro Schema
**Severity**: HIGH (producer initialization failure)

**Pattern**: An Avro schema field is given `"default": ""` (empty string) on a non-string type (timestamp, enum, long). Schema Registry validates that the default value matches the declared type. An empty string is rejected for non-string fields.

**Symptom**: On service startup or schema registration, Schema Registry returns `422 Unprocessable Entity: default value is not compatible with schema`. All producers fail to initialize.

**Root cause**: Copy-paste of `"default": ""` from a string field onto a differently-typed field. The Avro Python library may not validate defaults locally, but Schema Registry enforces strict type correctness.

**Fix**: Remove the default (making the field required) or use a type-valid default:
```json
{ "name": "occurred_at", "type": "string" }
```

**Prevention**: Run schema compatibility check (`scripts/gen-contracts.sh --validate`) after every Avro schema change. Register all schemas against Schema Registry in CI before producer tests run.

**First seen**: `infra/kafka/schemas/market.prediction.v1.avsc`, PLAN-0025 QA Phase 2, fixed 2026-04-12.

---

## BP-149 — Non-Deterministic Entity PKs Break Kafka Re-Delivery Idempotency

**Pattern**: Consumer generates entity primary keys with `new_uuid7()` during processing. ON CONFLICT DO NOTHING guards are keyed on these PKs. On Kafka re-delivery, the same message produces *new* PKs — the conflict is never detected, and duplicate rows accumulate silently.

**Root cause**: `new_uuid7()` is not a function of the input — it yields a different UUID on each call. ON CONFLICT on a PK only protects against exact-same-PK retries, not logical-duplicate retries.

**Affected code**: `section_document()` in S6, `run_ner_block()` in S6 — every new Section, Chunk, and EntityMention gets a fresh `new_uuid7()` on each pipeline run for the same article.

**Symptom**: After a crash-and-restart that hits the re-delivery window (DB commit succeeded, Kafka offset not yet committed), duplicate section/chunk/mention rows appear in nlp_db with the same `doc_id` but different PKs.

**Fix**: Add an explicit idempotency pre-check before the main write transaction. Use an existing "pipeline completed" sentinel — the `routing_decisions.doc_id` row — to detect already-processed articles and skip the pipeline entirely.

```python
# At the start of _run_pipeline:
async with self._nlp_sf() as check_session:
    check_routing_repo = RoutingDecisionRepository(check_session)
    if await check_routing_repo.get_by_doc(doc_id) is not None:
        logger.info("article_consumer.skip_already_processed", doc_id=str(doc_id))
        return
```

**Prevention**:
- Prefer deterministic IDs derived from input (e.g., `uuid5(namespace, f"{doc_id}:{index}")`) when idempotency via ON CONFLICT is required.
- If IDs must be random (UUIDv7 monotonic), add a separate idempotency gate before the write session (see fix above).
- In tests: mock `session.execute` result so `scalar_one_or_none()` returns `None` — otherwise the idempotency guard fires on the first call and skips the pipeline being tested.

**First seen**: S6 `ArticleProcessingConsumer._run_pipeline`, investigation 2026-04-13, fixed 2026-04-13.

---

## BP-150 — Kafka Default Retention (7 Days) Causes Silent Backlog Loss on Extended Downtime

**Pattern**: Pipeline consumer services are taken down for maintenance or a failure lasting >7 days. The Kafka default `log.retention.hours=168` (7 days) expires messages that accumulated during the downtime. On restart with `auto.offset.reset=earliest`, the consumer starts from the oldest *remaining* message — silently skipping everything from the downtime window.

**Root cause**: Kafka topics created without explicit `retention.ms` configuration inherit the broker default (7 days). For high-value pipeline topics that carry non-reproducible articles and market data, this is insufficient for real maintenance windows.

**Affected topics**: `content.article.stored.v1`, `market.dataset.fetched`, `nlp.article.enriched.v1` (and by extension all downstream topics in those pipelines).

**Symptom**: After >7 days of downtime, the NLP pipeline / knowledge graph silently processes fewer articles than were published during the outage. No error is raised; the consumer simply has no messages to process.

**Fix**: Set `retention.ms=2592000000` (30 days) on all primary pipeline topics in `infra/kafka/init/create-topics.sh`.

**Prevention**:
- Every new primary pipeline topic should have an explicit retention config in `create-topics.sh`.
- Alert when consumer lag on `content.article.stored.v1` exceeds 3 days (half the old retention).
- Dead-letter topics can use a shorter retention (14 days) — dead-lettered messages are for investigation, not replay.

**First seen**: `infra/kafka/init/create-topics.sh`, investigation 2026-04-13, fixed 2026-04-13.

---

## BP-157 — Root E2E conftest HS256 JWT rejected by live RS256-keyed middleware

**Date discovered**: 2026-04-13
**Service affected**: All services in root `tests/e2e/` suite

### Symptom

Root E2E `conftest.py` `_make_e2e_system_jwt()` generates an HS256-signed JWT (`jwt.encode(..., algorithm="HS256")`). The live test stack loads the RS256 public key from `S9/internal/jwks` during service startup. `InternalJWTMiddleware` has `public_key != None` and calls `jwt.decode(token, public_key, algorithms=["RS256"])`. An HS256 token fails this check with `InvalidTokenError`, and all E2E test requests receive 401.

### Root cause

The conftest fallback (`public_key is None → skip sig verification`) was designed for the case where S9 is not running. When the full live stack is up, all services successfully load the RS256 key and enforce strict RS256 verification. The HS256 test token is not a valid RS256 token.

### Fix

Set `PORTFOLIO_E2E_INTERNAL_JWT` to a real RS256-signed token from the live api-gateway private key before running root E2E tests:

```bash
export PORTFOLIO_E2E_INTERNAL_JWT=$(python3 -c "
import jwt, time, subprocess
pem = subprocess.check_output(
    ['docker', 'compose', '-f', 'infra/compose/docker-compose.test.yml',
     'exec', '-T', 'api-gateway', 'bash', '-c', 'echo \"\$API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY\"'],
).decode().strip()
print(jwt.encode({'sub':'e2e','iss':'worldview-gateway','aud':['worldview-service'],
    'iat':int(time.time()),'exp':int(time.time())+7200,'tenant_id':'e2e','user_id':'e2e','role':'system'},
    pem, algorithm='RS256'))
")
```

**Prevention**: Either update `_make_e2e_system_jwt()` to try RS256 with the api-gateway key, or use HS256 only when public_key is None (already the design). The real fix is ensuring the conftest reads the gateway private key when the stack is live.

**First seen**: `tests/e2e/conftest.py:56-75`, 2026-04-13.

---

## BP-158 — E2E client fixtures missing X-Internal-JWT after PLAN-0025

**Date discovered**: 2026-04-13
**Service affected**: S2, S4, S6, S7, S10 E2E tests; KG/market-data/content-ingestion/market-ingestion service-level E2E conftests

### Symptom

After PLAN-0025 added `InternalJWTMiddleware` to all services (commit f21da3e), the root E2E conftest and service-level E2E conftests for S6/S7/S10/S4/S2 were not updated to include `X-Internal-JWT` in their `AsyncClient` default headers. All API calls to non-health endpoints return `{"detail":"Missing X-Internal-JWT header"}` (HTTP 401).

BP-134 documented the same issue for some services; this is the remaining set.

### Affected fixtures

- `tests/e2e/conftest.py`: `s6_client` (line 229), `s7_client` (line 233), `s10_client` (line 234), `s4_internal_client` (if present)
- `services/knowledge-graph/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/market-data/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/content-ingestion/tests/e2e/conftest.py`: `e2e_client` fixture
- `services/market-ingestion/tests/e2e/conftest.py`: `e2e_client` (if applicable)
- `services/alert/tests/integration/conftest.py`: `integration_client` fixture

### Fix

Add `X-Internal-JWT` to each fixture's `AsyncClient`:

```python
_INTERNAL_JWT = os.getenv("PORTFOLIO_E2E_INTERNAL_JWT", "") or _make_e2e_system_jwt()

@pytest.fixture
async def s6_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        base_url=_S6_BASE_URL,
        headers={"X-Internal-JWT": _INTERNAL_JWT},
        timeout=30.0,
    ) as ac:
        yield ac
```

For service-level conftests, add the same pattern to `e2e_client`.

**Prevention**: When adding `InternalJWTMiddleware` to a service, update ALL test conftest files in that service (unit, integration, e2e) and the root `tests/e2e/conftest.py` client fixture for that service.

**First seen**: Multiple service e2e conftests, 2026-04-13.

---

## BP-159 — BaseHTTPMiddleware Dual-Instance: startup() on Wrong Instance

**Category**: FastAPI / Starlette middleware wiring
**Severity**: CRITICAL (silent security bypass when the stored instance holds security keys)
**First seen**: `InternalJWTMiddleware`, portfolio service, 2026-04-14

### Symptom

`InternalJWTMiddleware.startup()` is called in the FastAPI lifespan on the explicitly-created instance:
```python
jwt_middleware = InternalJWTMiddleware(app, jwks_url=jwks_url)
app.state._jwt_middleware = jwt_middleware
await jwt_middleware.startup()  # sets jwt_middleware._public_key
```

But `app.add_middleware(InternalJWTMiddleware, jwks_url=jwks_url)` creates a **second instance** when `app.build_middleware_stack()` runs. That second instance is the one that actually handles requests — and its `_public_key` is always `None`.

Any code in `dispatch()` that reads `self._public_key` sees `None` regardless of whether startup() succeeded. In this case, the fallback was an unverified JWT decode (auth bypass). The test suite never catches this because tests construct the middleware manually, bypassing `add_middleware`.

### Root Cause

Starlette's middleware stack construction calls `cls(app=self.router, **kwargs)` for each registered middleware (not for the `app.add_middleware()` call itself). The explicitly-instantiated `jwt_middleware` and the stack instance are different Python objects.

### Fix

Store shared state on `app.state` instead of `self.*` in the middleware. Use `request.app.state` in `dispatch()` to read it (works because `request.app` is the FastAPI instance regardless of which middleware instance serves the request):

```python
async def startup(self) -> None:
    key = await self._fetch_public_key()
    self._public_key = key  # keep for background refresh
    if hasattr(self.app, "state"):
        self.app.state._internal_jwt_public_key = key  # share across instances

async def dispatch(self, request: Request, call_next: Callable) -> Response:
    public_key = getattr(request.app.state, "_internal_jwt_public_key", None)
    if public_key is None:
        return Response('{"detail":"Service not ready"}', status_code=503)
    ...
```

In tests, pre-populate `app.state._internal_jwt_public_key = test_key` before the middleware stack is built.

### Prevention

Never read security-critical state from `self.*` in a `BaseHTTPMiddleware` that is added via `app.add_middleware()`. Always route through `app.state` (readable via `request.app.state` in dispatch).

> **Confirmed 2026-04-18**: api-gateway lifespan correctly calls `startup()` via ASGI lifespan, NOT on a throw-away instance. Test gap remains (F-MAJOR-009).

---

## BP-160 — jsdom localStorage.clear() Not a Function in Vitest + Node.js

**Category**: Frontend / Testing
**Affected areas**: Any Vitest test that calls `localStorage.clear()` in `beforeEach`
**First seen**: PLAN-0028 Wave F-2 (2026-04-18)

### Symptom

```
TypeError: localStorage.clear is not a function
```

Also preceded by:
```
Warning: '--localstorage-file' was provided without a valid path
```

### Root Cause

Node.js 22+ has experimental `localStorage` support via `--experimental-webstorage`. When Vitest
runs under Node.js ≥22, Node intercepts `--localstorage-file` CLI arguments and installs its own
`localStorage` global — a non-standard object that does not implement the full `Storage` interface
(notably missing `.clear()`). This replaces jsdom's proper `Storage` object before tests run.

### Fix

Use `vi.stubGlobal` to install a fully-mocked localStorage in `beforeEach`:

```ts
const localStorageMock = {
  getItem: vi.fn<(key: string) => string | null>(() => null),
  setItem: vi.fn<(key: string, value: string) => void>(),
  removeItem: vi.fn<(key: string) => void>(),
  clear: vi.fn<() => void>(),
  length: 0 as number,
  key: vi.fn<(index: number) => string | null>(() => null),
};

beforeEach(() => {
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
  localStorageMock.getItem.mockReturnValue(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});
```

### Why vi.fn() generic syntax matters

Vitest v1+ changed the `vi.fn()` generic signature from `vi.fn<[Args], Return>()` (v0 style)
to `vi.fn<FunctionSignature>()`. Using the old 2-arg form causes TS2558. Use single-arg form.

### Prevention

Never call `localStorage.clear()` directly in test setup. Always stub localStorage explicitly.
Do NOT type the mock object as `Storage` — this strips Vitest's `Mock<...>` methods like
`mockReturnValue`. Keep the inferred type and cast with `as unknown as Storage` only where needed.

---

## BP-161 — Query-String Identity Injection

**Category**: Security
**Severity**: CRITICAL
**First seen**: 2026-04-18 QA audit (F-CRIT-002)

### Symptom

FastAPI unannotated `UUID` parameter silently maps to query string, allowing unauthenticated callers to pass arbitrary tenant/user IDs via `?tenant_id=<uuid>`.

### Root Cause

FastAPI treats non-path, non-body, unannotated scalar parameters as query parameters by default. An endpoint signature like `def handler(tenant_id: UUID)` where `tenant_id` is not in the path template and has no `Header()`, `Path()`, or `Depends()` annotation will accept `?tenant_id=<any-uuid>` from any caller — enabling tenant impersonation.

### Affected

Any FastAPI endpoint with `tenant_id: UUID` or `user_id: UUID` parameters that lack `Header()`, `Path()`, or `Depends()` annotations.

### Fix

Always annotate identity parameters. Use `request.state.tenant_id` from `InternalJWTMiddleware`, not headers or query params:

```python
# WRONG — silently becomes a query parameter
async def handler(tenant_id: UUID):
    ...

# RIGHT — read from middleware-validated JWT
async def handler(request: Request):
    tenant_id = request.state.tenant_id
    ...
```

### Prevention

Architecture test that greps for unannotated `tenant_id`/`user_id` function parameters in API routers. All identity values MUST come from `request.state` (populated by `InternalJWTMiddleware` from the verified `X-Internal-JWT`).

---

## BP-162 — S9 Composed Endpoints Missing `headers` Kwarg (JWT Never Forwarded)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | S9 api-gateway composed endpoints (`clients.py`) |
| **Root cause** | Composed functions (`get_top_movers`, `get_company_overview`, `get_market_heatmap`, `_screener_for_sector`) lacked a `headers` keyword parameter. The `X-Internal-JWT` from `_auth_headers(request)` was extracted correctly by the route handler but had nowhere to go — the composed function's httpx call hardcoded `headers={"Content-Type": "application/json"}` with no JWT. |
| **Symptom** | All composed S9→S3 endpoints return 401 "Missing X-Internal-JWT header" while simple proxy-through routes (e.g. portfolios → S1) work fine. |
| **Why hard to find** | Simple proxy routes worked; only composed endpoints failed. The middleware correctly added the JWT to the request scope. The `except Exception: pass` in InternalJWTIssuerMiddleware was a red herring. |
| **Fix** | Add `*, headers: dict[str, str] | None = None` to all composed functions in `clients.py`; pass `headers=_auth_headers(request)` from proxy routes. |

### Prevention

Every composed endpoint function in `clients.py` MUST accept `*, headers: dict[str, str] | None = None` and forward it to all downstream httpx calls. Unit tests MUST assert `"X-Internal-JWT" in call_kwargs["headers"]` for every downstream call.

---

## BP-163 — Frontend Gateway Response Shape Mismatch (API Returns Different Field Names)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | Frontend `lib/gateway.ts`, all pages using S1/S3 data |
| **Root cause** | S1 Portfolio service returns `{items: [{id, owner_id, ...}]}` paginated envelopes with `id` field. Frontend types expect `Portfolio[]` (bare array) with `portfolio_id` field. Same pattern for watchlists (`id` vs `watchlist_id`), holdings (bare array vs wrapped object), search (`symbol` vs `ticker`), prediction markets (`items` vs `markets`). |
| **Symptom** | Portfolio page crashes with error boundary. Dashboard portfolio widget shows "No portfolio" even though data exists. Search returns wrong field names. |
| **Fix** | Add response transformation layer in `gateway.ts` — unwrap envelopes, map field names. |

### Prevention

When adding a new S9 proxy route, always test the ACTUAL API response shape with `curl` and compare to the frontend TypeScript type. Never assume backend field names match frontend types — S1/S3 use ORM-generated names (`id`, `user_id`) while frontend uses domain names (`portfolio_id`, `owner_id`).

---

## BP-164 — Docker Compose Missing `depends_on` Causes JWKS Startup Race

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Affected areas** | S8 rag-chat (and potentially any service with InternalJWTMiddleware) |
| **Root cause** | S8's `depends_on` lists `rag-chat-migrate`, `valkey`, `ollama` but NOT `api-gateway`. S8 starts before S9, JWKS fetch fails (3 retries × 3s = 9s window), then ALL authenticated requests return 503 permanently. |
| **Fix** | Add `api-gateway: condition: service_healthy` to S8's `depends_on` in `docker-compose.yml`. |

### Prevention

Every backend service that uses `InternalJWTMiddleware` MUST declare `depends_on: api-gateway: condition: service_healthy` in docker-compose.yml. The InternalJWTMiddleware should also support on-demand JWKS retry when `_public_key is None` at request time (not just at startup).

---

## BP-165 — Open Redirect via Unvalidated `redirect_to` Query Parameter

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | CRITICAL |
| **Affected areas** | Frontend auth flow: `app/login/page.tsx`, `app/callback/page.tsx` |
| **Root cause** | `searchParams.get("redirect_to")` stored in sessionStorage and passed directly to `router.replace()`. Next.js `router.replace()` follows absolute URLs. An attacker crafting `/login?redirect_to=https://evil.com` redirects an authenticated user to an external phishing site. |
| **Symptom** | After successful OIDC login, user is redirected to attacker-controlled domain. |
| **Fix** | Added `sanitizeRedirect()` to `lib/utils.ts`; validates the value starts with `/` and not `//` before use. Applied at both reading sites. |

### Prevention

ANY URL, path, or redirect target that originates from a URL query parameter, sessionStorage, localStorage, or an external API MUST be validated before use in navigation. Use `sanitizeRedirect()` from `lib/utils.ts` for post-auth navigation. Never pass raw query param values to `router.push()`, `router.replace()`, `window.location.href`, or any `href` attribute.

---

## BP-166 — `javascript:` URL XSS via API-Supplied `href` Values

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | MAJOR |
| **Affected areas** | Any component that renders `<a href={apiValue}>` from external content (news articles, prediction markets, RAG citations) |
| **Root cause** | URLs from external APIs (news feeds, prediction markets) are placed directly in `href` attributes without scheme validation. A malicious or compromised content pipeline can return `javascript:alert(1)` as a URL, which executes when the user clicks the link. `rel="noopener noreferrer"` does NOT prevent `javascript:` execution. |
| **Symptom** | Clicking a "news article" or "prediction market" link executes JavaScript in the user's browser — stored XSS. |
| **Fix** | Added `safeExternalUrl()` to `lib/utils.ts`; allowlists only `http:` and `https:` protocols. Returns `"#"` for all other values. Applied to `ArticleCard.tsx`, `WatchlistNews.tsx`, `TopBets.tsx`, `chat/page.tsx`. |

### Prevention

ALL `<a href>` attributes populated from API data MUST use `safeExternalUrl()` from `lib/utils.ts`. Never place raw API string values in `href`. This applies to news article URLs, prediction market URLs, RAG citation URLs, and any other external link rendered in the frontend.

---

## BP-167 — Floating Docker Image Tags Create Non-Reproducible Builds

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | MAJOR |
| **Affected areas** | `infra/compose/docker-compose.yml`, `infra/compose/docker-compose.test.yml` |
| **Root cause** | `minio/mc:latest`, `timescale/timescaledb:latest-pg16`, `provectuslabs/kafka-ui:latest` used in compose files. Floating tags are updated by image publishers and can change behaviour silently between runs. Test and production compose used divergent TimescaleDB versions. |
| **Fix** | Pinned all three images to specific version tags (`2.17.2-pg16`, `RELEASE.2024-01-16T16-07-38Z`, `v0.7.2`). |

### Prevention

NEVER use `:latest` tags in any Docker Compose file (dev, test, or production). Always use an explicit version tag. The test compose file MUST use the same database image versions as the production compose file to prevent "passes in test, breaks in prod" failures.

---

## BP-168 — Cross-Database Dual-Commit: intel_db Persists Before nlp_db Commits

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | CRITICAL |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/consumers/article_consumer.py`, `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` |
| **Root cause** | The S6 `ArticleEnrichedConsumer` processes two separate databases (`nlp_db` and `intelligence_db`). The `entity_resolution` block opens and commits the `intelligence_db` session internally (inside its own scope), BEFORE the outer consumer commits `nlp_db`. If the `nlp_db` commit subsequently fails (connection error, constraint violation), the `intelligence_db` writes are already durably persisted with no rollback mechanism. This creates ghost entity-resolution records that reference article NLP rows that were never committed. |
| **Symptom** | Entity mention rows in `intelligence_db.entity_mentions` pointing to articles that do not exist in `nlp_db.document_chunks`. Knowledge graph builds on phantom data. Deduplication misses on re-delivery since `nlp_db` shows the article as unprocessed but `intelligence_db` already has its entity mentions. |
| **Fix (PLAN-0031 Wave B-3)** | Restructure `article_consumer.py` to open both sessions at the outermost level. Pass both sessions into all blocks. Commit `nlp_db` FIRST (since it is the source-of-truth for article existence), then commit `intelligence_db`. Remove the internal `session.commit()` from `entity_resolution.py` — it must be driven by the consumer, not the block. |

### Prevention

When a consumer writes to two separate databases in a single logical transaction, ALWAYS commit the source-of-truth database FIRST and the derived/downstream database SECOND. Never allow a sub-block to commit its own session; all commits must be controlled at the consumer level. If atomicity is required, use the outbox pattern (write to one DB + outbox, consume outbox to drive the other DB).

---

## BP-169 — Kafka Produce Before DB Commit (Pre-Commit Event Leakage)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | HIGH |
| **Affected areas** | `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py:375`, `services/knowledge-graph/src/knowledge_graph/infrastructure/consumers/enriched_consumer.py:232` |
| **Root cause** | `materialize_graph()` calls `direct_producer.produce_bytes()` for `entity.dirtied.v1` events at line 375, which is INSIDE the function and occurs BEFORE the consumer's `session.commit()` at `enriched_consumer.py:232`. If the DB commit fails after the produce, downstream consumers (S7 confidence recomputation workers) receive events for graph state that was never committed. The compacted `entity.dirtied.v1` topic then contains the latest entry for those entity IDs, suppressing future valid dirtying events via log compaction. |
| **Symptom** | S7 confidence recomputation workers trigger on ghost entities. Entities that were "dirtied" by a failed graph write never get reprocessed because the compacted topic already holds an entry for their ID with a later offset. |
| **Fix (PLAN-0031 Wave C-1)** | **FIXED 2026-04-21.** Refactored `materialize_graph()` to return `frozenset[uuid.UUID]` of entity IDs that need dirtying. Moved the `entity.dirtied.v1` produce loop to AFTER `session.commit()` in `enriched_consumer.py`. If the commit fails, no events are produced. If the produce fails after commit, the next re-delivery will produce a duplicate dirty event (idempotent — the worker re-runs confidence computation). 5 regression tests added. |

### Prevention

NEVER produce Kafka events inside a block/function that is called before the DB transaction commits. Either: (a) use the outbox pattern (write event to DB outbox within the same transaction, dispatch after commit), or (b) return the event payloads to the caller and produce them AFTER a successful `session.commit()`. This applies to all direct producers, not just compacted topics.

---

## BP-170 — UNRESOLVED Entity Mentions Permanently Orphaned (No Re-Resolution Pathway)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | HIGH |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py`, `services/knowledge-graph/` (missing worker) |
| **Root cause** | Block 9 entity resolution classifies mentions as PROVISIONAL (0.45–0.72), AUTO_RESOLVED (≥0.72), or UNRESOLVED (<0.45). PROVISIONAL mentions are queued in `provisional_entity_queue` for Worker 13E to create new entities. UNRESOLVED mentions (<0.45) are stored in `nlp_db.entity_mentions` with `resolved_entity_id=NULL` — but there is NO periodic worker or event-driven consumer that re-examines these rows as the entity catalog grows. If a new entity is later added to the knowledge graph (via market instrument consumer or ProvisionalEnrichmentWorker for a different article), all prior UNRESOLVED mentions for that surface form remain permanently orphaned. |
| **Symptom** | Entity signal counts, narrative embeddings (which draw from claims against resolved entities), and routing scores under-count entities mentioned before they were added to the catalog. Knowledge graph has no record of early mentions of entities that now exist. |
| **Fix** | Two options: (A) Periodic re-resolution worker — runs every N hours, queries `nlp_db.entity_mentions WHERE resolved_entity_id IS NULL AND resolution_confidence < 0.45` and re-runs the cascade; (B) Event-driven — S6 consumes `entity.canonical.created.v1`, triggers a targeted re-resolution scan for UNRESOLVED mentions matching the new entity's mention_class. Option B is more surgical and lower overhead. |

### Prevention

When classifying mentions as UNRESOLVED, always store enough metadata (`mention_class`, `resolution_confidence`) to enable future re-resolution as the entity catalog expands. Design pipelines with the assumption that "unresolvable today" means "retry later", not "discard". Consider storing `resolution_outcome` in the DB (currently only in-memory) to enable efficient querying.

---

## BP-171 — Provisional Entity Queue Dedup Loses Mention Linkage for Subsequent Articles

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-20 |
| **Severity** | MEDIUM |
| **Affected areas** | `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:249–255`, `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence.py` |
| **Root cause** | The `provisional_entity_queue` table has a UNIQUE constraint on `(normalized_surface, mention_class)`. When Article B mentions the same surface form as Article A before Worker 13E resolves the queue row, the INSERT fires `ON CONFLICT DO NOTHING` — Article B's `mention_id` is silently dropped. Article B's `relation_evidence_raw` rows are written with `entity_provisional=true` but the wrong (or missing) `provisional_queue_id`. When Worker 13E resolves the queue row and calls `UPDATE relation_evidence_raw WHERE provisional_queue_id = :queue_id`, Article B's evidence rows are NOT unblocked. The EntityCreatedConsumer's fallback query also cannot match because the entity didn't exist at insertion time. |
| **Symptom** | Relations from any article that mentions the same provisional entity surface after the first article, but before the entity is created, remain stuck with `entity_provisional=true, processed=false` permanently. Worker 13A (confidence recomputation) excludes these rows. Knowledge graph confidence values are under-computed for entities that appeared in multiple articles during their provisional window. |
| **Fix** | Replace the UNIQUE+NOTHING pattern with a proper tracking table: a `provisional_entity_queue_mentions` join table that stores all `(queue_id, mention_id, doc_id)` pairs. The EntityCreatedConsumer unblocks all evidence linked to any mention in the queue. Alternatively, change the INSERT to return the existing queue_id on conflict (`ON CONFLICT DO UPDATE SET updated_at=now() RETURNING queue_id`) and pass that returned queue_id into the evidence row. |

### Prevention

When using `ON CONFLICT DO NOTHING` for deduplication in a queue pattern, verify that the deduplication does NOT cause downstream data loss. If multiple producers need to reference the same queue row, the queue table must store N-to-1 relationships (e.g., a join table), not just the first producer's reference. Audit every `ON CONFLICT DO NOTHING` insert that is also referenced by a foreign key in another table.

---

## BP-172 — Integration Tests Using X-Tenant-ID/X-Owner-ID Headers After Auth Middleware Migration

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 |
| **Severity** | HIGH (silent test false-positives and 24 integration test failures) |
| **Affected areas** | `services/portfolio/tests/integration/` (5 test files) |
| **Root cause** | PLAN-0025 migrated all portfolio API routes to read `tenant_id` and `user_id` from `request.state` (set by `InternalJWTMiddleware` from `X-Internal-JWT` header). The old `X-Tenant-ID` and `X-Owner-ID` headers are completely ignored. Integration tests were not fully updated: they still called `make_tenant()/make_user()` to create dynamic identities under freshly-created UUIDs, then passed `X-Tenant-ID`/`X-Owner-ID` headers — which routes silently ignore. The JWT in the test client carries fixed `INTEGRATION_TENANT_ID`/`INTEGRATION_USER_ID`. Result: route uses `INTEGRATION_TENANT_ID` to look up the dynamically-created user → `uow.users.get(U_dynamic, INTEGRATION_TENANT_ID)` returns `None` → `UserInactiveError` → 409. |
| **Symptom** | Four failure modes: (A) 409 USER_INACTIVE on portfolio/watchlist/transaction creation; (B) `user_id` assertion mismatch (`INTEGRATION_USER_ID` ≠ dynamically-created user); (C) WATCHLIST_ALREADY_EXISTS collision across tests (all watchlists created for same `INTEGRATION_USER_ID`, duplicate name triggers 409 on second test); (D) 404 on `GET /users/{id}` (user created under `T_dynamic`, JWT lookup uses `INTEGRATION_TENANT_ID`). |
| **Fix** | Replace `make_tenant()/make_user()` API calls with DB-seeding helpers (`seed_tenant()`, `seed_user()`). Use `INTEGRATION_TENANT_ID`/`INTEGRATION_USER_ID` directly in all requests. For isolation tests (cross-user, cross-tenant), seed additional identities in DB and use `make_jwt_headers(tenant_id, user_id)` for per-request JWT injection. Use unique watchlist names (uuid4 suffix) to prevent cross-test name collisions in shared session-scoped DB. |

### Prevention

- After any auth middleware migration that changes how routes extract identity (header → JWT state), run a full integration test suite immediately to detect orphaned header patterns.
- Watchlist/collection endpoints with name uniqueness constraints MUST use unique names per test (e.g., `f"WL-{uuid4().hex[:8]}"`) when sharing a session-scoped DB.
- When a JWT carries a fixed test identity, ALL test data (tenants, users) that routes validate against MUST be seeded under that same identity. Never mix dynamic tenant/user creation with fixed-JWT test clients.
- Add to integration test review checklist: "Do any tests pass `X-Tenant-ID` or `X-Owner-ID` headers? If so, are routes guaranteed to read these headers (not JWT state)?"

---

## BP-173 — `create_metrics()` Isolated CollectorRegistry Makes All Shared-Lib Metrics Invisible

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | CRITICAL — all HTTP, Kafka, and outbox metrics for 10 services emit zero data |
| **Affected areas** | `libs/observability/src/observability/metrics.py:52`; all services calling `create_metrics()` (S1–S10 except S4/S5 which use their own module-level counters) |
| **Root cause** | `create_metrics()` defaults to `registry or CollectorRegistry()`, which creates a brand-new isolated registry every time it is called without an explicit registry argument. All returned `Counter`/`Histogram` objects are registered in this isolated registry. When Prometheus scrapes `/metrics`, the FastAPI app calls `prometheus_client.generate_latest()`, which reads from the global `REGISTRY` singleton. The custom metrics are in a different object (`reg`) that `generate_latest()` never sees. Result: 60 metric families across 10 services are permanently invisible. |
| **Symptom** | `GET /metrics` returns only Python process metrics (`python_gc_*`, `process_*`). Service-level counters (`s1_requests_total`, `s3_kafka_messages_consumed_total`, etc.) appear as 0 series in Prometheus and are absent from all Grafana panels. |
| **Fix** | Change `libs/observability/metrics.py:52` from `reg = registry or CollectorRegistry()` to `reg = registry if registry is not None else REGISTRY` (where `REGISTRY` is imported from `prometheus_client`). Tests that pass an isolated registry to avoid duplicate-registration errors continue to work unchanged. Services that pass `None` (the production default) will now correctly register in the global registry. Added `_global_registry_cache: dict[str, ServiceMetrics]` to make `create_metrics()` idempotent for the global REGISTRY — returns the cached instance when the same `service_name` is called again, avoiding `ValueError: Duplicated timeseries` in test suites that instantiate consumers multiple times. |

### Prevention

When writing shared-library metrics helpers that accept an optional `registry` parameter, always check `is not None` (not truthiness) to distinguish "no registry provided" from "explicit registry". `CollectorRegistry()` is falsy in Python 3.12+ because it defines no `__bool__`; relying on `or` to fall back causes the same bug. Only use an isolated registry in tests. The global `REGISTRY` must be the default for all production code.

**Grep pattern** (find the bug in any shared metrics helper):
```bash
grep -rn "registry or CollectorRegistry\(\)" libs/ services/ --include="*.py"
```

---

## BP-174 — Dead Metric Definitions (Metric Defined but Never Incremented)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | HIGH — dashboards and alerts built on these metrics produce no-data panels and phantom alert state |
| **Affected areas** | `services/content-store/src/content_store/infrastructure/metrics/prometheus.py` (8 of 9 metrics), `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics/prometheus.py` (all metrics), `services/rag-chat/src/rag_chat/infrastructure/metrics/prometheus.py` (all metrics) |
| **Root cause** | Metrics modules were created as copy-paste stubs during scaffolding. The counters/gauges/histograms are defined at module level and exported, but no use-case, consumer, or worker code in the service ever calls `.inc()`, `.set()`, or `.observe()` on them. The metric name appears correct in the module, but the metric is a dead symbol — never referenced outside the module. |
| **Symptom** | Prometheus returns the metric with value `0` at startup and it never changes. Dashboards built on these metrics appear to show a healthy flat line at 0, which looks like "no traffic" rather than "metric is broken". Alert rules fire `for: 5m` without matching real conditions. |
| **Fix** | For each dead metric, either: (a) find the correct use-case or consumer code that performs the action the metric is supposed to measure, and add a `metric.inc()` / `metric.observe()` call there; or (b) if the metric was added speculatively and no such code exists, remove the metric definition entirely. Never leave a metric defined but unincremented — it creates false confidence. |

### Prevention

When adding a Prometheus metric to a service, the metric definition and its first call site MUST be in the same commit. A metric with no call site is dead code. During code review, grep for each new metric name across the entire service to confirm at least one `.inc()`/`.set()`/`.observe()` call exists.

**Grep pattern** (find metrics defined but never called):
```bash
# For each metric name found in the metrics module, check for usage:
grep -rn "s5_articles_processed_total\|s5_processing_duration" services/content-store/src/ --include="*.py"
# Should return at least 2 lines: the definition AND a call site.
```

---

## BP-175 — Prometheus Scrape Target Uses Host-Mapped Port Instead of Container Port

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | HIGH — two services' metrics are permanently missing from all dashboards |
| **Affected areas** | `infra/prometheus/prometheus.yml` — `portfolio:8001` (correct: `portfolio:8000`) and `content-ingestion:8004` (correct: `content-ingestion:8000`) |
| **Root cause** | The Prometheus scrape config uses the host-side port mapping from `docker-compose.yml` (e.g., `8001:8000` → uses `8001`) instead of the container-internal port (`8000`). Within a Docker network, containers communicate on the container-internal port. The host-mapped port is only accessible from the Docker host, not from other containers. Prometheus (running as a container) cannot reach `portfolio:8001` because that port is only bound on the host interface. |
| **Symptom** | Prometheus shows `portfolio` and `content-ingestion` scrape targets as `DOWN` with `connection refused`. All panels for these services show no-data. Grafana "Service Overview" dashboard appears healthy for 8 services but blank for the other 2. |
| **Fix** | In `infra/prometheus/prometheus.yml`, change: `targets: ["portfolio:8001"]` → `targets: ["portfolio:8000"]` and `targets: ["content-ingestion:8004"]` → `targets: ["content-ingestion:8000"]`. The container-internal port is always the right-hand side of the `host:container` port mapping in docker-compose. When adding a new service, verify the `/metrics` path and the INTERNAL port from the service's `Dockerfile` `CMD` or `uvicorn` invocation. |

### Prevention

When adding a service to `prometheus.yml`, ALWAYS use the container-internal port (right side of `host_port:container_port` in docker-compose). Never use the host-mapped port. A simple way to verify: `docker compose exec prometheus wget -qO- http://<service_name>:<container_port>/metrics` — if this returns text, the port is correct.

---

## BP-176 — Alertmanager Receiver With No Notification Channels (Silent Alert Black Hole)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (observability audit) |
| **Severity** | CRITICAL — all Prometheus alerts fire and are permanently discarded; no human is ever notified |
| **Affected areas** | `infra/alertmanager/alertmanager.yml` |
| **Root cause** | The Alertmanager configuration defines a `default` receiver with no `email_configs`, `slack_configs`, `webhook_configs`, `pagerduty_configs`, or any other notification integration. Prometheus correctly evaluates alert rules, transitions them to `FIRING`, and sends them to Alertmanager — but Alertmanager silently matches them to the empty default receiver and discards them. No log message is emitted by Alertmanager for discarded notifications. |
| **Symptom** | Alertmanager UI shows alerts in `FIRING` state. No email, Slack message, or page is ever sent. On-call engineers have no awareness that alerts are firing. The Grafana "Active Alerts" panel may show counts, but operators never receive actionable notifications. |
| **Fix** | Add at minimum one notification channel to `infra/alertmanager/alertmanager.yml`. For local development, wire to MailHog (already running in the `dev` profile): add `email_configs` with `to: "oncall@worldview.local"`, `from: "alertmanager@worldview.local"`, `smarthost: "mailhog:1025"`, `require_tls: false`. For production, add Slack webhook or PagerDuty integration. Verify by triggering a test alert via `amtool alert add` and confirming delivery. |

### Prevention

An Alertmanager receiver with no integration config is not a valid production configuration. It is equivalent to disabling alerting entirely. Any CI or deployment check must verify that at least one receiver has at least one notification config entry. Add the following to the deployment checklist: "Alertmanager has at least one receiver with a working notification channel (email/Slack/PagerDuty). Verify with `amtool config routes show`."

---

## BP-177 — `app = create_app()` at Module Level With uvicorn `--factory` (Double Prometheus Registration)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (platform cold-start validation) |
| **Severity** | HIGH — service crashes at startup; no traffic served |
| **Affected areas** | FastAPI app factories used with uvicorn `--factory` |
| **Root cause** | A module-level `app = create_app()` call executes when the module is imported by uvicorn, registering Prometheus metrics into the global `CollectorRegistry`. uvicorn then calls `create_app()` a second time (as the factory function), which tries to register the same metrics again. If the `observability.metrics._global_registry_cache` is absent (old image) or the service name is identical, the second registration raises `ValueError: Duplicated timeseries in CollectorRegistry`. |
| **Symptom** | Service exits immediately on startup with `ValueError: Duplicated timeseries in CollectorRegistry: {'<svc>_requests_total', ...}`. Found in `alert/app.py:159`. |
| **Fix** | Remove the module-level `app = create_app()` call. uvicorn `--factory` handles the single instantiation. If module-level access is needed for testing, use `pytest` fixtures that call `create_app()` directly. |

### Prevention

Never add `app = create_app()` at module level in a FastAPI service that uses uvicorn `--factory`. Add to the service scaffold template and `.claude/review/checklists/REVIEW_CHECKLIST.md`: "FastAPI app.py: no module-level `app = create_app()` if CMD uses `--factory`."

---

## BP-178 — asyncpg Rejects Parameter Binding Inside `interval '...'` String Literals

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (platform cold-start validation) |
| **Severity** | HIGH — worker fails to start; all retry/recovery logic disabled |
| **Affected areas** | Any SQLAlchemy `text()` query with parameterized interval durations (asyncpg driver) |
| **Root cause** | asyncpg does not support parameters inside PostgreSQL `interval '...'` string literals. `interval ':minutes minutes'` becomes `interval '$1 minutes'` in the wire protocol, which asyncpg rejects with `IndeterminateDatatypeError: could not determine data type of parameter $1`. The pattern looks valid in psycopg2 or psql but fails with asyncpg's prepared-statement protocol. |
| **Symptom** | `sqlalchemy.exc.ProgrammingError: IndeterminateDatatypeError: could not determine data type of parameter $1` on queries containing `interval ':param ...'`. |
| **Fix** | Replace `interval ':minutes minutes'` with `make_interval(mins => :minutes)` and `interval ':days days'` with `make_interval(days => :days)`. PostgreSQL's `make_interval()` function accepts named integer parameters that asyncpg binds correctly. Affected file: `nlp-pipeline/infrastructure/nlp_db/repositories/entity_mention.py`. |

### Prevention

Any raw SQL with a parameterized duration must use `make_interval()`. Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "asyncpg: no `interval ':param ...'` literals — use `make_interval(mins => :param)` instead."

---

## BP-179 — pydantic-settings Parses Empty Env Var as `SecretStr("")` Not `None`

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (rag-chat local bring-up) |
| **Severity** | HIGH — service crashes at startup; all traffic fails |
| **Affected areas** | Any service with `Optional[SecretStr]` settings checked with `is not None` |
| **Root cause** | pydantic-settings parses `KEY=` (env var set to empty string) as `SecretStr("")` not `None`. An `is not None` guard evaluates True for `SecretStr("")`, so empty-string values are not treated as "absent". If downstream code passes the empty string to a URL parser (e.g., `create_async_engine("")`), it crashes with a parse error. |
| **Symptom** | `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from string ''` at startup. Only happens when the env var is present but empty (`KEY=`), not when it's absent. |
| **Fix** | Replace `if value is not None` guards on `SecretStr` settings with `if value` or `if value and value.get_secret_value()`. For URL-like settings, use: `url = settings.db_url_read.get_secret_value() if settings.db_url_read is not None else None` + `if not url or ...` (truthy check handles both `None` and `""`). |

### Prevention

Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "Settings: `Optional[SecretStr]` guarded by `is not None` is broken for empty-string env vars. Use `if value` or `if not url` instead."

---

## BP-180 — asyncpg `AmbiguousParameterError` for Nullable Params in `IS NULL` Checks

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (news/top endpoint 500 in nlp-pipeline) |
| **Severity** | HIGH — endpoint returns 500 for all calls when any optional filter param is None |
| **Affected areas** | SQLAlchemy `text()` queries with nullable filter parameters using `IS NULL` checks (asyncpg driver) |
| **Root cause** | asyncpg requires type information for all parameters before executing a prepared statement. When a nullable parameter appears ONLY in `:param IS NULL` (with no adjacent typed comparison that asyncpg can infer from), asyncpg raises `AmbiguousParameterError`. This happens even when the same param also appears in `= :param` alongside a typed column, if the type inference is inside a CTE subquery. |
| **Symptom** | `asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $N` for queries with patterns like `:param IS NULL OR column >= :param`. |
| **Fix** | Wrap the parameter in an explicit `CAST`: `CAST(:param AS TEXT) IS NULL OR column = CAST(:param AS TEXT)` and `CAST(:param AS DOUBLE PRECISION) IS NULL OR column >= CAST(:param AS DOUBLE PRECISION)`. This gives asyncpg unambiguous type info. |

### Prevention

In all `text()` SQL with optional filter params, always use `CAST(:param AS <type>) IS NULL` rather than bare `:param IS NULL`. Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "asyncpg text() SQL: nullable params in `IS NULL` checks need explicit CAST for type resolution."

---

## BP-181 — Missing Shared Library in Service Dockerfile (ml-clients Not Installed)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (rag-chat local bring-up, `ModuleNotFoundError: No module named 'ml_clients'`) |
| **Severity** | HIGH — service crashes at startup |
| **Affected areas** | Any service whose Dockerfile omits a lib it imports |
| **Root cause** | `libs/ml-clients` was added as an import in `rag_chat/infrastructure/llm/provider_chain.py` but was never added to `services/rag-chat/Dockerfile`. The build stage only copies `libs/common`, `libs/messaging`, `libs/observability`. The `PYTHONPATH` also lacks `ml-clients/src`. |
| **Symptom** | `ModuleNotFoundError: No module named 'ml_clients'` at import time during lifespan startup. |
| **Fix** | Add `COPY libs/ml-clients /build/libs/ml-clients` and `-e /build/libs/ml-clients` to the build stage; add `/app/libs/ml-clients/src` to `PYTHONPATH` in the runtime stage. |

### Prevention

When adding a new lib import to a service, check the service Dockerfile immediately and add the lib. Add to service scaffold checklist: "New lib dependency → update Dockerfile COPY + install + PYTHONPATH."

---

## BP-182 — `CanonicalOHLCVBar.from_dict` Crashes on `volume: null` from EODHD

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (`canonicalize_fatal error="int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"` for AAPL) |
| **Severity** | HIGH — every null-volume bar crashes canonicalize; task is marked FAILED; bronze write succeeds but canonical + downstream are lost |
| **Affected areas** | `libs/contracts/src/contracts/canonical/ohlcv.py:CanonicalOHLCVBar.from_dict`; any provider adapter (EODHD, Yahoo, Polygon) that returns `volume: null` |
| **Root cause** | `CanonicalOHLCVBar.from_dict()` used `int(d["volume"])` unconditionally. EODHD returns `"volume": null` for bars with no recorded trades (e.g. ETFs on foreign exchanges, data gaps, pre-market stubs). `int(None)` raises `TypeError`, which is caught by `ExecuteTaskUseCase._canonicalize()` (BP-113) and re-raised as `ProviderDataError`, failing the task. |
| **Symptom** | `canonicalize_fatal error="int() argument must be a string, a bytes-like object or a real number, not 'NoneType'" provider=eodhd symbol=<TICKER>` in logs. Bronze object written successfully; canonical never written; task moves to FAILED. |
| **Fix** | `libs/contracts/src/contracts/canonical/ohlcv.py` — extract `raw_volume = d.get("volume")` and compute `volume = int(raw_volume) if raw_volume is not None else 0`. The bar is preserved with `volume=0`; downstream consumers should filter zero-volume bars if needed rather than losing the entire bar. |

### Prevention

- Any `int()` or `float()` call on a provider-supplied field must use `int(v) if v is not None else <default>`. Price fields (`open`/`high`/`low`/`close`) default is not obvious (bad data → fail is correct); volume/size fields default to 0.
- When adding new provider fields to a canonical model `from_dict`, explicitly handle `None` for every numeric field.
- The regression test `test_serialize_ohlcv_null_volume_coerces_to_zero` in `test_canonical.py` and `test_null_volume_ohlcv_succeeds_bp182` in `test_execute_task.py` guard this path.
- See also: BP-138 (same `float(None)` pattern in Kafka consumer field extraction).

---

## BP-183 — Docker build fails: `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` when root `package.json` has `pnpm.overrides`

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (`make dev-rebuild` fails; worldview-web image fails at `pnpm install --frozen-lockfile`) |
| **Severity** | HIGH — blocks all Docker-based dev and CI builds for the frontend |
| **Affected areas** | `apps/worldview-web/Dockerfile`; triggered any time `pnpm.overrides` is added/changed in the root `package.json` without updating the Dockerfile |
| **Root cause** | pnpm v9 records `overrides` from the workspace root `package.json` (`pnpm.overrides`) into `pnpm-lock.yaml`. If the Dockerfile copies `pnpm-workspace.yaml` and `pnpm-lock.yaml` but **not** the root `package.json`, pnpm inside Docker finds overrides in the lockfile but no corresponding config → `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH`. Introduced by commit `43249e3` (PLAN-0032 CVE remediation) which added `pnpm.overrides` for `vite`/`@eslint/plugin-kit` without updating the Dockerfile. |
| **Symptom** | `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH  Cannot proceed with the frozen installation. The current "overrides" configuration doesn't match the value found in the lockfile` in Docker build output at the `pnpm install --frozen-lockfile` step. |
| **Fix** | `apps/worldview-web/Dockerfile` Stage 1 (`deps`): add root `package.json` to the COPY: `COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./` |

### Prevention

- The root `package.json` is not just a workspace marker — it carries `pnpm.overrides`, `pnpm.onlyBuiltDependencies`, and other workspace-level settings that affect lockfile resolution.
- Whenever `pnpm.overrides` or other `pnpm.*` fields are added/changed in the root `package.json`, verify that all Dockerfiles which run `pnpm install` also `COPY package.json` at the workspace root.
- The Dockerfile comment should document that the root `package.json` is required, not just `pnpm-workspace.yaml`.

---

## BP-184 — Scheduler Creates Tasks for Unregistered Providers

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (investigate skill: S2 ProviderRegistry only registers EODHD; Alpha Vantage/Polygon/Yahoo stubs not wired) |
| **Severity** | HIGH — any `polling_policy` row with a non-EODHD provider causes task creation every tick; tasks burn all retries and move to FAILED; creates permanently-failed task noise in DB |
| **Affected areas** | `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`; `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py:_build_registry()`; any service whose scheduler creates tasks without validating provider registration |
| **Root cause** | `ScheduleDueTasksUseCase._build_tasks_for_policy()` creates `IngestionTask` rows for any enabled `PollingPolicy` regardless of whether its `provider` has a registered adapter in `ProviderRegistry`. The worker then calls `registry.get(task.provider)`, receives `ProviderUnavailable("No adapter registered for provider …")`, and marks the task RETRY → eventually FAILED. |
| **Symptom** | Flood of `task_retryable_error error="No adapter registered for provider 'alpha_vantage'"` in worker logs. `ingestion_tasks` table accumulates FAILED rows for non-EODHD providers every scheduler tick. |
| **Fix** | In `ScheduleDueTasksUseCase._build_tasks_for_policy()`, check `str(policy.provider) in registered_providers` before creating a task. Pass the list of registered provider values into the use case at construction time (inject from `ProviderRegistry.all_providers()`). Log a WARNING and skip if the provider is not registered. |

### Prevention

- At service startup, assert that all enabled `PollingPolicy.provider` values are present in `ProviderRegistry.all_providers()`. Emit a CRITICAL log if any are missing.
- When adding a new `Provider` enum value, either register a stub that logs a warning or add a migration that prevents enabling policies for that provider until an adapter exists.
- See also: BP-031 (backfill flag flipped before budget check — same theme of scheduler optimistically creating work that cannot be executed).

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
