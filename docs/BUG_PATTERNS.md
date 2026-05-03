# Bug Patterns Index

> **Purpose**: Living knowledge base of bugs encountered during development. Load only the category file you need — loading all patterns at once overflows context.
>
> **Before implementing**: scan the categories and quick-lookup table below. Open the relevant category file for full detail.
> **When you hit a runtime error**: scan the Symptom column below before debugging from scratch.
> **After fixing a new bug**: add an entry to the appropriate category file and update this index.

---

## Categories

| Category | File | Patterns | Description |
|----------|------|----------|-------------|
| [Kafka & Messaging](bug-patterns/kafka-messaging.md) | `bug-patterns/kafka-messaging.md` | 35 | Kafka, Avro, outbox, DLQ, Schema Registry |
| [Database & ORM](bug-patterns/database-orm.md) | `bug-patterns/database-orm.md` | 42 | SQLAlchemy, asyncpg, Alembic, PostgreSQL, pgvector |
| [Async & Concurrency](bug-patterns/async-concurrency.md) | `bug-patterns/async-concurrency.md` | 14 | asyncio, event loops, concurrency, React concurrent mode |
| [Auth & Security](bug-patterns/auth-security.md) | `bug-patterns/auth-security.md` | 28 | JWT/OIDC, SSRF, XSS, tenant isolation, CSP, middleware |
| [Testing](bug-patterns/testing.md) | `bug-patterns/testing.md` | 26 | pytest, AsyncMock, fixtures, Vitest, pre-commit, CI |
| [Frontend](bug-patterns/frontend.md) | `bug-patterns/frontend.md` | 29 | React, Next.js, WebSocket/SSE, TypeScript, CSS |
| [Config & Docker](bug-patterns/config-docker.md) | `bug-patterns/config-docker.md` | 28 | pydantic-settings, Docker, Compose, env vars, images |
| [ML & LLM](bug-patterns/ml-llm.md) | `bug-patterns/ml-llm.md` | 21 | Ollama, GLiNER, DeepInfra, embeddings, LLM prompt patterns |
| [Observability](bug-patterns/observability.md) | `bug-patterns/observability.md` | 9 | Prometheus, Grafana, Alertmanager, structlog, OTel |
| [Workers & Schedulers](bug-patterns/worker-scheduler.md) | `bug-patterns/worker-scheduler.md` | 36 | task scheduling, lease patterns, backfill, watermarks, rate limiting |
| [API & Contracts](bug-patterns/api-contracts.md) | `bug-patterns/api-contracts.md` | 21 | FastAPI, Pydantic, API contract drift, PRD assumptions, gateways |

---

## Quick Lookup Table

| BP | Title | Category | File |
|----|-------|----------|------|
| BP-001 | OutboxKafkaValue not serialized to bytes | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-001) |
| BP-002 | Env file loaded in wrong place (Makefile / Docker Compose) | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-002) |
| BP-003 | `RuntimeError: Event loop is closed` at session-scoped async fixture teardown | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-003) |
| BP-004 | `fixture 'settings' not found` causes `ERROR at setup` instead of SKIP | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-004) |
| BP-005 | Docker multi-stage build: `exec /app/.venv/bin/alembic: no such file or director... | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-005) |
| BP-006 | Alembic env.py uses hardcoded localhost URL from alembic.ini | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-006) |
| BP-007 | PostgreSQL unique index doesn't deduplicate NULL nullable columns | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-007) |
| BP-008 | Initial schema migration out of sync with final ORM model | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-008) |
| BP-009 | DispatcherProcess passes raw Kafka dict as DispatcherConfig | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-009) |
| BP-010 | Docker Compose `--wait` fails for long-running worker processes | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-010) |
| BP-011 | Runtime schema files missing from container image | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-011) |
| BP-012 | Async SQLAlchemy polling triggers `MissingGreenlet` | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-012) |
| BP-013 | E2E tests appear infinite due to unstable async assertions | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-013) |
| BP-014 | Import guard allowlist `fnmatch` pattern does not match direct children | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-014) |
| BP-015 | Python `hash()` for cross-process coordination | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-015) |
| BP-016 | Advisory lock spanning external I/O | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-016) |
| BP-017 | Outbox payload fields mismatch Avro schema | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-017) |
| BP-018 | Client constructor mismatch in wiring code | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-018) |
| BP-019 | Migration DDL vs ORM column mismatch | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-019) |
| BP-020 | DLQ `move_to_dead_letter` only updates status without copying payload | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-020) |
| BP-021 | SQLAlchemy ORM `metadata` column name collision | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-021) |
| BP-022 | NMS IoU boundary: strictly-greater vs greater-or-equal | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-022) |
| BP-023 | pre-commit ruff-format stash conflict loop | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-023) |
| BP-024 | DLQ requeue corrupts aggregate_id | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-024) |
| BP-025 | Blocking DNS resolution in async context | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-025) |
| BP-026 | SSRF missing IPv4-mapped IPv6 bypass | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-026) |
| BP-027 | DNS rebinding TOCTOU in SSRF validation | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-027) |
| BP-028 | AsyncMock used for sync method generates unawaited coroutine warnings | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-028) |
| BP-029 | Content-hash dedup event_type key mismatch — dedup never fires | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-029) |
| BP-030 | Token-bucket `last_refill_at` not wired — tokens never replenished | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-030) |
| BP-031 | Backfill flag flipped before budget/cap filtering | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-031) |
| BP-032 | `upsert()` missing `.returning()` — transient entity ID | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-032) |
| BP-033 | Concurrent flag updates — read-modify-write race clears flags | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-033) |
| BP-034 | Content-hash dedup early return skips `mark_processed` | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-034) |
| BP-035 | `is_duplicate()` check-then-insert race under concurrent consumers | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-035) |
| BP-036 | Token bucket `try_consume()` non-atomic with DB persist | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-036) |
| BP-037 | `UnitOfWork.__aexit__` rollback failure masks original exception | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-037) |
| BP-038 | `assert` used for production error handling | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-038) |
| BP-039 | `EVENT_TOPIC_MAP.get(event_type, event_type)` silently routes to wrong topic | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-039) |
| BP-040 | Idempotency `INSERT` missing `ON CONFLICT DO NOTHING` | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-040) |
| BP-041 | ruff TCH003→TC003 noqa rename breaks pre-commit hook | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-041) |
| BP-042 | FailureInfo[None] missing value/key/headers fields | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-042) |
| BP-043 | Pydantic V2 `Field(strip_whitespace=True)` deprecated | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-043) |
| BP-044 | f-string dynamic SQL for nullable filters triggers ruff S608 | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-044) |
| BP-045 | Non-atomic consumer dedup: `is_duplicate` + `process_message` + `mark_processed`... | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-045) |
| BP-046 | Cache invalidation before `uow.commit()` creates stale-read-into-cache race | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-046) |
| BP-047 | `readyz` health endpoint leaks DB credentials via raw exception string | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-047) |
| BP-048 | D-008 skip-if-exists guard applied to first storage step only; subsequent steps ... | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-048) |
| BP-049 | `get_or_create` reads back via read session after INSERT on write session (read-... | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-049) |
| BP-050 | `asyncio.Event.set()` called from librdkafka delivery callback without `call_soo... | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-050) |
| BP-051 | Avro record name contains dots or version suffix — invalid Java identifier | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-051) |
| BP-052 | Inconsistent Avro namespace creates divergent Schema Registry subjects | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-052) |
| BP-053 | `schema_version: ClassVar[int] = 0` footgun — subclasses emit version-0 events s... | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-053) |
| BP-056 | (no title) | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-056) |
| BP-057 | Database session held across external I/O | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-057) |
| BP-058 | UoW `__aexit__` Auto-Commit Causes Double-Commit Side Effects | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-058) |
| BP-058 | Kafka topics receive no messages despite consumers calling `uow.collect_event()` | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-058) |
| BP-059 | Use Case Calls `async with self._uow:` on Already-Entered UoW | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-059) |
| BP-059 | Portfolio (S1) receives no instrument sync events. market-data consumers process | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-059) |
| BP-060 | Events sometimes not dispatched (if `outbox_notifier` is missing or crashes afte | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-060) |
| BP-061 | Portfolio (S1) `InstrumentRef` cache never shows `has_ohlcv=True` / `has_quotes= | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-061) |
| BP-062 | Portfolio `InstrumentRef.id` is always a new `uuid7()` for each Kafka replay. `I | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-062) |
| BP-063 | `json.JSONDecodeError` on Kafka message deserialization. Or garbled data (first  | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-063) |
| BP-064 | FastAPI raises a validation error or returns malformed response when using `@rou | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-064) |
| BP-065 | Pre-commit hook succeeds in auto-fixing files but then fails with "Stashed chang | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-065) |
| BP-066 | `sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotat | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-066) |
| BP-067 | pytest configuration — `--strict-markers` + missing marker registration | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-067) |
| BP-068 | Docker Compose infrastructure — missing pgvector extension in postgres image | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-068) |
| BP-069 | asyncpg AmbiguousParameterError when all optional filter params are None | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-069) |
| BP-070 | SQLAlchemy `func.cast()` and `func.Integer` do not exist | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-070) |
| BP-071 | FK constraint blocks manual/webhook submissions when source_id is NOT NULL | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-071) |
| BP-072 | Scheduler dedupe key drift: `range_end=now` changes every tick | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-072) |
| BP-073 | `has_active_task(variant=None)` bypass for FUNDAMENTALS tasks | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-073) |
| BP-074 | Watermark key collision: scheduler omits `variant` parameter | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-074) |
| BP-075 | Backfill flag match too broad: provider+symbol only | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-075) |
| BP-076 | asyncpg rejects PostgreSQL `::type` cast syntax in `text()` params | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-076) |
| BP-077 | `ON CONFLICT DO NOTHING` missing `index_where=` for partial unique index | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-077) |
| BP-078 | Cross-service E2E `ImportError` when service package not installed | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-078) |
| BP-079 | asyncpg `AmbiguousParameterError` when using `IS NULL` on a bound parameter in `... | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-079) |
| BP-079 | Expired worker lease stalls source permanently | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-079) |
| BP-080 | pytest-asyncio 0.24 loop scope mismatch: `session` loop + function-scoped async ... | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-080) |
| BP-081 | httpx `AsyncClient` double-open: `RuntimeError: Cannot open a client instance mo... | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-081) |
| BP-082 | SQLAlchemy ORM enum column: `ValueError` when seed data uses wrong case | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-082) |
| BP-083 | DLQ pagination: `total` field returns page count instead of DB total | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-083) |
| BP-084 | `.gitignore` `src/` rule blocks new service source files from being tracked | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-084) |
| BP-085 | Config field reuse: `otlp_endpoint` used as ML model URL | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-085) |
| BP-086 | Hardcoded Kafka consumer group IDs in standalone entry points | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-086) |
| BP-087 | In-process WebSocket `ConnectionManager` dead in standalone consumer process | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-087) |
| BP-088 | `asyncio.Event` patch causes infinite recursion in entrypoint tests | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-088) |
| BP-089 | Tautology assertions in entry-point tests: `assert X == f"{X}"` | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-089) |
| BP-090 | Ephemeral event in `relations` table — wrong decay behaviour | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-090) |
| BP-091 | AGE Cypher injection via f-string entity_id | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-091) |
| BP-092 | GLOBAL temporal event → entity_event_exposures explosion | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-092) |
| BP-093 | EODHD API: Assumed fields don't exist (`General.Officers`, `Holders.Institutions... | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-093) |
| BP-096 | FastAPI Route Parameters Must Not Be Under TYPE_CHECKING | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-096) |
| BP-097 | Read Engine Connection Leak in Dual-Session Factory | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-097) |
| BP-098 | Config Re-Export Shim Breaks AST Architecture Tests | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-098) |
| BP-099 | DDL Alignment Test Misses ALTER TABLE ADD COLUMN Migrations | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-099) |
| BP-100 | PRD References Non-Existent External API Field | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-100) |
| BP-101 | PRD Describes Stale Architecture Baseline | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-101) |
| BP-102 | intelligence-migrations Numbering Conflict | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-102) |
| BP-103 | ValkeyClient Wrapper Type Annotation Drift | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-103) |
| BP-105 | DLQ `original_event_id` Set to New UUID Instead of Kafka Event ID | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-105) |
| BP-106 | `asyncio.shield()` Around Stop-Event Wait Leaks Background Tasks | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-106) |
| BP-107 | `asyncio.timeout` Wraps Semaphore Acquisition, Not Just Execution | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-107) |
| BP-108 | Read Engine Not Disposed in Process Entrypoints (Dual-URL Split) | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-108) |
| BP-109 | Non-Atomic `ZADD` + `EXPIRE` in Valkey LSH Index Leaves Immortal Keys | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-109) |
| BP-110 | Settings Re-Export Shim Not Staged Causes Mypy Pre-Commit Failures | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-110) |
| BP-111 | `aiosmtplib.SMTPConnectError` Constructor Changed in v3 | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-111) |
| BP-112 | `claim_batch` Never Reclaims RUNNING Tasks with Expired Leases | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-112) |
| BP-113 | `TypeError` from None-Valued OHLCV Field Bypasses `_persist_fail` in ExecuteTask... | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-113) |
| BP-114 | EODHD Demo Key Rate-Limits Silent `[]` for EOD OHLCV Under Concurrent Load | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-114) |
| BP-119 | Avro Schema Inline Drift | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-119) |
| BP-120 | Post-Commit Hook Failures Silently Suppressed (Cache Invalidation Lost) | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-120) |
| BP-121 | BGE-large BERT Context Overflow Crashes Ollama GGML Runner | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-121) |
| BP-122 | Confluent Avro Wire Format Not Detected in S6 Consumer | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-122) |
| BP-123 | GLiNER `predict_entities(list)` Returns Empty List — Batch API Unsupported | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-123) |
| BP-124 | Kafka Consumer Idempotency Check Skips Embedding on Entity Replay | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-124) |
| BP-125 | pgvector Cosine Distance Formula Off-By-Two | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-125) |
| BP-126 | Alembic Migration NOT NULL Column Missing server_default | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-126) |
| BP-127 | pre-commit ruff-format Version Mismatch Causes Phantom Reformat Loop | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-127) |
| BP-128 | AGE Extension Functions Fail on New Connections Due to Missing Session Setup | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-128) |
| BP-129 | Watermark-Based Incremental Sync Fails When Target Table Lacks `updated_at` | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-129) |
| BP-130 | `DirectKafkaProducerProtocol.produce_bytes` Has No Concrete Adapter — AttributeE... | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-130) |
| BP-131 | NULL Values in Multi-Column Unique Index Allow Semantic Duplicates | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-131) |
| BP-132 | Hardcoded StrEnum Count Test Breaks When Shared Lib Enum Is Extended | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-132) |
| BP-133 | New Consumer Entry Point Missing From docker-compose.test.yml | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-133) |
| BP-134 | Live/Network Tests Missing `pytest.mark.live` Causes Fixture Scope Mismatch | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-134) |
| BP-135 | Consumer `process_message` Calls `uow.commit()` — Double-Commit Per Message | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-135) |
| BP-136 | Shared Session Poisoned After Exception — Missing Rollback in Per-Item Loop | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-136) |
| BP-137 | Helm values.yaml Key Mismatch Causes Silent Misconfiguration | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-137) |
| BP-138 | Kafka Consumer Crashes on Non-Numeric Float Field | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-138) |
| BP-139 | Unguarded JSON.parse in WebSocket onmessage Crashes React Tree | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-139) |
| BP-140 | Settings Fields Defined But Never Read (Dead Config) | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-140) |
| BP-141 | Repository-Level session.rollback() Poisons Shared Session Context | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-141) |
| BP-142 | E2E Test Assumes Endpoint Convention Without Verifying Actual Path | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-142) |
| BP-143 | Starlette Middleware Order: InternalJWT Outermost Sees user=None | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-143) |
| BP-144 | Middleware Reads `app.state` at Construction Time — Feature Permanently Disabled | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-144) |
| BP-145 | JWT Decode Without `issuer=` — Issuer Spoofing Auth Bypass | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-145) |
| BP-146 | PKCE / One-Time Token: Non-Atomic GET + DEL Enables State Replay | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-146) |
| BP-147 | Outbox Dispatcher Missing Serializer Registration → KeyError Dead-Letter | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-147) |
| BP-148 | Avro Schema Field With Empty String Default — Schema Registry Rejection | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-148) |
| BP-149 | Non-Deterministic Entity PKs Break Kafka Re-Delivery Idempotency | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-149) |
| BP-150 | Kafka Default Retention (7 Days) Causes Silent Backlog Loss on Extended Downtime | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-150) |
| BP-157 | Root E2E conftest HS256 JWT rejected by live RS256-keyed middleware | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-157) |
| BP-158 | E2E client fixtures missing X-Internal-JWT after PLAN-0025 | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-158) |
| BP-159 | BaseHTTPMiddleware Dual-Instance: startup() on Wrong Instance | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-159) |
| BP-160 | jsdom localStorage.clear() Not a Function in Vitest + Node.js | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-160) |
| BP-161 | Query-String Identity Injection | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-161) |
| BP-162 | S9 Composed Endpoints Missing `headers` Kwarg (JWT Never Forwarded) | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-162) |
| BP-163 | Frontend Gateway Response Shape Mismatch (API Returns Different Field Names) | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-163) |
| BP-164 | Docker Compose Missing `depends_on` Causes JWKS Startup Race | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-164) |
| BP-165 | Open Redirect via Unvalidated `redirect_to` Query Parameter | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-165) |
| BP-166 | `javascript:` URL XSS via API-Supplied `href` Values | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-166) |
| BP-167 | Floating Docker Image Tags Create Non-Reproducible Builds | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-167) |
| BP-168 | Cross-Database Dual-Commit: intel_db Persists Before nlp_db Commits | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-168) |
| BP-169 | Kafka Produce Before DB Commit (Pre-Commit Event Leakage) | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-169) |
| BP-170 | UNRESOLVED Entity Mentions Permanently Orphaned (No Re-Resolution Pathway) | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-170) |
| BP-171 | Provisional Entity Queue Dedup Loses Mention Linkage for Subsequent Articles | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-171) |
| BP-172 | Integration Tests Using X-Tenant-ID/X-Owner-ID Headers After Auth Middleware Mig... | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-172) |
| BP-173 | `create_metrics()` Isolated CollectorRegistry Makes All Shared-Lib Metrics Invis... | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-173) |
| BP-174 | Dead Metric Definitions (Metric Defined but Never Incremented) | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-174) |
| BP-175 | Prometheus Scrape Target Uses Host-Mapped Port Instead of Container Port | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-175) |
| BP-176 | Alertmanager Receiver With No Notification Channels (Silent Alert Black Hole) | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-176) |
| BP-177 | `app = create_app()` at Module Level With uvicorn `--factory` (Double Prometheus... | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-177) |
| BP-178 | asyncpg Rejects Parameter Binding Inside `interval '...'` String Literals | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-178) |
| BP-179 | pydantic-settings Parses Empty Env Var as `SecretStr("")` Not `None` | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-179) |
| BP-180 | asyncpg `AmbiguousParameterError` for Nullable Params in `IS NULL` Checks | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-180) |
| BP-181 | Missing Shared Library in Service Dockerfile (ml-clients Not Installed) | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-181) |
| BP-182 | `CanonicalOHLCVBar.from_dict` Crashes on `volume: null` from EODHD | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-182) |
| BP-182 | `market_hours_only` DB Flag Never Enforced by Scheduler | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-182) |
| BP-182 | Playwright `networkidle` Times Out on Pages with `AlertStreamProvider` | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-182) |
| BP-183 | Docker build fails: `ERR_PNPM_LOCKFILE_CONFIG_MISMATCH` when root `package.json`... | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-183) |
| BP-183 | Budget System Ignores EODHD Per-Endpoint Credit Costs | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-183) |
| BP-183 | JTI Replay Destroys Cross-Service RAG Retrieval | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-183) |
| BP-184 | Scheduler Creates Tasks for Unregistered Providers | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-184) |
| BP-184 | Cold-Start Thundering Herd: All Policies Due Simultaneously | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-184) |
| BP-184 | Morning Brief Route Calls Wrong Use Case Method | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-184) |
| BP-185 | Content-Ingestion TokenBucket Rate Limiters Not Shared Across Worker Processes | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-185) |
| BP-186 | Content-Ingestion Missing Startup Validators for Optional API Keys | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-186) |
| BP-187 | `skip_verification` Has No Production Safety Guard | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-187) |
| BP-188 | JWKS Startup Failure Creates Zombie Pods | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-188) |
| BP-189 | Null Volume Coercion in CanonicalOHLCVBar | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-189) |
| BP-190 | Missing tenant_id Filter in NLP Pipeline News Queries | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-190) |
| BP-191 | No Entity Ownership Check in Entity Articles Endpoint | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-191) |
| BP-198 | Setting `_internal_jwt_public_key` in Shared Test Fixture Breaks `skip_verificat... | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-198) |
| BP-200 | ValkeyClient.set() ex=/nx= Kwargs Not Forwarded | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-200) |
| BP-201 | WS JWT sub=oidc_sub Instead of UUID user_id | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-201) |
| BP-202 | New Shared Lib Not Added to All Consuming Service Dockerfiles | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-202) |
| BP-215 | Consumer `_parse_symbol()` Format Inversion | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-215) |
| BP-216 | ISO3 Country Codes Passed to Alpha-2 Entity Lookups | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-216) |
| BP-217 | Standalone Consumer Entry Point Not Added to docker-compose | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-217) |
| BP-218 | Dead Watermark `last_success_at` Column Never Written | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-218) |
| BP-219 | Per-Replica In-Process Monthly Quota Counter (Market Ingestion) | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-219) |
| BP-220 | `_fallback_provider()` Returns `None` for Intraday — Silent Failover Gap | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-220) |
| BP-221 | Intraday Dispatch Set Missing Timeframes (`15m`, `30m`, `4h`) | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-221) |
| BP-222 | Worker Registry Divergence: `_build_registry()` Bypasses Shared Builder | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-222) |
| BP-223 | API Keys as `str` Instead of `SecretStr` in pydantic-settings | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-223) |
| BP-224 | Hardcoded `Path(__file__).parents[N]` Schema Path Fails in Docker | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-224) |
| BP-225 | `contextlib.suppress` on DB Insert Leaves SQLAlchemy Session Aborted | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-225) |
| BP-226 | `str(None)` Produces Colliding Alias Text `"None"` | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-226) |
| BP-227 | Polymarket Adapter Crashes on Zero/One-Outcome Markets | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-227) |
| BP-228 | Content-Ingestion Sources Table Never Seeded for Finnhub/NewsAPI | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-228) |
| BP-229 | Market-Ingestion Scheduler Missing Dispatch for EARNINGS_CALENDAR and NEWS_SENTI... | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-229) |
| BP-230 | Alert `add_middleware()` Missing `jti_replay_check_enabled` (Dual-Instantiation) | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-230) |
| BP-231 | qwen3:0.6b CPU Inference Latency Exceeds Default Ollama Timeout | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-231) |
| BP-232 | Content-Ingestion Article Titles Null in Documents Table | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-232) |
| BP-233 | asyncpg Vector ANN Parameter Must Be str, Not list[float] | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-233) |
| BP-233 | Polymarket Gamma API Format Change Silently Drops All Markets | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-233) |
| BP-234 | asyncpg DATE Parameter Requires Python date Object, Not ISO String | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-234) |
| BP-234 | Market Ingestion Scheduler Silently Drops ECONOMIC_EVENTS / MACRO_INDICATOR / IN... | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-234) |
| BP-235 | httpx Default 5s Read Timeout Shadows asyncio.wait_for Deadline | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-235) |
| BP-235 | prediction_market_snapshots ON CONFLICT ON CONSTRAINT Fails — Index vs. Constrai... | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-235) |
| BP-236 | Valkey 24h Briefing Cache Masks Article Score Updates | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-236) |
| BP-236 | entity_embedding_state.ensure_rows_exist() Inserts NULL next_refresh_at — Rows N... | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-236) |
| BP-237 | pgvector CAST in UPSERT Requires String Format, Not Python list[float] | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-237) |
| BP-238 | Ollama Model Reference Without Registry Verification Causes Silent 100% Fallback | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-238) |
| BP-239 | S3 Fundamentals Router Missing Section Endpoints Despite Enum + Use Case Support | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-239) |
| BP-240 | Alert S1Client Sends Wrong Auth Header After PRD-0025 Migration | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-240) |
| BP-241 | Alert Dedup Keys Block Replay After Config Fix | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-241) |
| BP-242 | Missing Error State in News Tab (Silent Empty on Fetch Failure) | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-242) |
| BP-243 | Alpaca Crypto Symbols Sent to Stock Endpoint (HTTP 400) | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-243) |
| BP-243 | Decimal Fraction vs. Percentage Mismatch in S3→Frontend Data Pipeline | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-243) |
| BP-244 | Alpaca Class Share Symbols Rejected (BRK-B → BRK.B) | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-244) |
| BP-244 | Stale Closure Over React State in useEffect ResizeObserver | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-244) |
| BP-245 | Docker Compose Per-Role Images Not Rebuilt by Base Service Build | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-245) |
| BP-246 | SQLAlchemy Session Poisoning Leaves Content-Ingestion Tasks Stuck in CLAIMED | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-246) |
| BP-247 | Batch OHLCV Fetch Uses First Task's Date Range for All Symbols | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-247) |
| BP-248 | WebSocket Path Mismatch: /v1/ vs /api/v1/ in Direct S10 Connection | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-248) |
| BP-249 | BaseHTTPMiddleware Bypasses WebSocket ASGI Scopes | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-249) |
| BP-250 | Python StrEnum Lowercase vs TypeScript Uppercase AlertSeverity Mismatch | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-250) |
| BP-251 | S9 Passthrough Returns Upstream Contract Instead of Frontend Contract | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-251) |
| BP-251 | SnapTrade "User Already Registered" (409) Returns 503 After DB Wipe | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-251) |
| BP-252 | LLM Wraps Output in Markdown Code Fence Despite Prompt Saying "Return Markdown" | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-252) |
| BP-252 | S10 AlertSeverity StrEnum Returns Lowercase; Frontend Expects Uppercase | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-252) |
| BP-253 | Price Change Always Zero: Resolver _build() Missing prev_close Parameter | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-253) |
| BP-254 | Derivation Consumer Hardcodes Source Timeframe | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-254) |
| BP-255 | SnapTrade v4 Callback Returns `connection_id`; Frontend/Backend Expect `authoriz... | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-255) |
| BP-256 | `AliasChoices` First-Match Wins: Empty Env Var Shadows Non-Empty Prefixed Var | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-256) |
| BP-257 | `docker compose restart` Does Not Swap Image; Use `up -d --no-deps` | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-257) |
| BP-258 | Service-to-Service Calls Bypass S9 Gateway: No RS256 Internal JWT Available | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-258) |
| BP-259 | Shared `ingestion_events` Dedup Table: Same Event ID Used by Multiple Consumers | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-259) |
| BP-260 | `is_due(watermark.current_bar_ts)` Blocks Re-Polling When Task Range Extends int... | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-260) |
| BP-261 | GitOps Env Drift: Local `docker.env` Changes Not Propagated to worldview-gitops | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-261) |
| BP-263 | SnapTrade Adapter Dropped `amount` and `fee`, Causing $0 Dividends | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-263) |
| BP-264 | Holdings Drift from Cumulative Activity Replay | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-264) |
| BP-265 | Gateway Hard-Coded Empty Collections Mask Missing Endpoints | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-265) |
| BP-266 | S3 Prediction Market List Returns `volume_24h=None` (Volume Never Displayed) | Workers & Schedulers | [bug-patterns/worker-scheduler.md](bug-patterns/worker-scheduler.md#bp-266) |
| BP-267 | Screener-Based `getTopMovers()` Hardcodes `price: 0` | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-267) |
| BP-268 | asyncio.create_task() Without done_callback Silently Swallows Consumer Crashes | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-268) |
| BP-269 | structlog OTel Context Not Injected — trace_id Missing from Logs | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-269) |
| BP-270 | Prometheus Regex s[1-9] Excludes Service S10 | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-270) |
| BP-271 | histogram_quantile Without sum by (label, le) Returns Incorrect Percentiles | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-271) |
| BP-272 | ML Adapter latency_ms=0 / tokens_in=0 Corrupts Cost Analytics | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-272) |
| BP-273 | `op.drop_constraint()` Fails on Bare UNIQUE INDEX | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-273) |
| BP-274 | Multi-Process Service: Scheduler State Not in API `app.state` | API & Contracts | [bug-patterns/api-contracts.md](bug-patterns/api-contracts.md#bp-274) |
| BP-275 | Kafka `MemberIdRequiredException` On First JoinGroup (Cosmetic) | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-275) |
| BP-276 | Wire field naming MUST be pinned by an end-to-end contract test | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-276) |
| BP-291 | `h-full` Loading Skeleton in `min-h-*` Parent Produces Black Overlay | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-291) |
| BP-292 | Prompt/Lookup Mismatch: LLM Outputs Reference Values Absent from Post-Parse Look... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-292) |
| BP-293 | Producer-Side `resolved_only` Lookup Destroys End-to-End Output Without Error Si... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-293) |
| BP-294 | Schema-Defined Audit Table Never Written: Hardcoded `usage_logger=None` / Missin... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-294) |
| BP-295 | Next.js 15 Page File Cannot Export Arbitrary Symbols (PageProps `never` Constrai... | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-295) |
| BP-296 | CSS Comment Containing `*/` Substring Breaks PostCSS | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-296) |
| BP-297 | Docker `--build` ≠ `--no-cache`: Stale Frontend Bundle in Live Container | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-297) |
| BP-298 | `e.isTrusted` Guard Breaks `fireEvent`-Based Hotkey Tests | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-298) |
| BP-299 | HotkeyContext Scope Push/Pop Non-Atomic in React 18 Concurrent Mode | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-299) |
| BP-300 | `isMountedRef` Not Reset on Effect Re-Run → WebSocket Permanently Dead After Tok... | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-300) |
| BP-301 | Test IDs Not Updated After UUID Pattern Constraint Added to FastAPI Path Paramet... | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-301) |
| BP-302 | `next.config.ts` `env:` Default Masks `NEXT_PUBLIC_*` Absence Check | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-302) |
| BP-303 | Production OHLCV Auth Blackhole: Workers Rely on `dev-login`, Blocked in Prod | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-303) |
| BP-304 | Spreadsheet Formula Injection (CWE-1236) in Client-Side TSV/CSV Serialisers | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-304) |
| BP-305 | Document-Level `copy` Listener Hijacks Native Selection Inside Component | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-305) |
| BP-306 | `useEffect` Dependency on Derived-Array Identity → Spurious or Infinite Fires | Async & Concurrency | [bug-patterns/async-concurrency.md](bug-patterns/async-concurrency.md#bp-306) |
| BP-307 | Compound Sign Operators Double-Negate in Numeric Parser | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-307) |
| BP-308 | Backend/Frontend Field-Name Drift in Nested Payloads (Citation `source` vs `sour... | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-308) |
| BP-309 | Classification Without Consequence: Positive Outcome Branch Writes Nothing | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-309) |
| BP-310 | Unbounded Retry Loop: Periodic Worker Without a Failure Terminal State | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-310) |
| BP-311 | DeepInfra Model Availability Mismatch: Config Defaults Referencing Unavailable M... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-311) |
| BP-312 | Worker Instantiated but Not Registered in Scheduler | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-312) |
| BP-313 | JSON-Only Kafka Consumer Hides Schema-Evolution Bugs (PLAN-0062) | Kafka & Messaging | [bug-patterns/kafka-messaging.md](bug-patterns/kafka-messaging.md#bp-313) |
| BP-318 | AsyncMock Session Returns AsyncMock: scalar_one_or_none() Yields Coroutine | Testing | [bug-patterns/testing.md](bug-patterns/testing.md#bp-318) |
| BP-319 | Stale Docker Image Blocks Alembic Upgrade After New Migration Added | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-319) |
| BP-320 | Docker Compose v5 `up -d` Leaves Services in `Created` State | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-320) |
| BP-321 | Grafana Alloy Service Filter Omits New Container: Logs Silently Dropped | Observability | [bug-patterns/observability.md](bug-patterns/observability.md#bp-321) |
| BP-322 | `json.dumps(..., default=str)` Stringifies Pydantic Models: Cache Round-Trip Bre... | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-322) |
| BP-323 | CSP `style-src` Missing Nonce Silently Blocks All Stylesheets (Safari + Next.js ... | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-323) |
| BP-324 | LLM Adapter Optimistic Assumption: Plan Adds Application-Layer Feature, Adapter ... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-324) |
| BP-324 | `NODE_ENV=production` Used as HTTPS Guard Causes `upgrade-insecure-requests` to ... | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-324) |
| BP-325 | `'strict-dynamic'` in CSP `script-src` Blocks All Scripts on Next.js Prerendered... | Auth & Security | [bug-patterns/auth-security.md](bug-patterns/auth-security.md#bp-325) |
| BP-326 | Lazy Imports in Kafka Consumer Hot-Path Hide `ModuleNotFoundError` from Container Health Checks | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-326) |
| BP-327 | EmbeddingClientProtocol Interface Mismatch: `embed(str)` vs `embed(list[EmbeddingInput])` | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-327) |
| BP-328 | `relation_type_registry` Embeddings Never Seeded — ANN Canonicalization Permanently Disabled | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-328) |
| BP-329 | Extraction Prompt `predicate` Unconstrained — Freeform Relation Types Bypass Canonicalization | ML & LLM | [bug-patterns/ml-llm.md](bug-patterns/ml-llm.md#bp-329) |
| BP-330 | Screener `entity_id` Slug Never Matched a Real Entity Page — Fall Back to `instrument_id` UUID | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-330) |
| BP-331 | Screener Revenue Column Always Blank: `revenue_usd` Nested Under `metrics`, Not Top-Level | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-331) |
| BP-332 | TanStack Controlled Sort Race: `getNextSortingOrder()` Captures Stale State Outside Updater When `useDeferredValue` Deferred Pass Is Pending | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-332) |
| BP-333 | Embedding Model Name Mismatch (HuggingFace ID vs Ollama Tag) Silently Disables ANN Seeder | Config & Docker | [bug-patterns/config-docker.md](bug-patterns/config-docker.md#bp-331) |
| BP-334 | Provisional Enrichment Alias Duplicate on Recovery Sweep — bare INSERT in `EntityAliasRepository.insert()` hits existing alias after stale-processing reset | Database & ORM | [bug-patterns/database-orm.md](bug-patterns/database-orm.md#bp-334) |
| BP-335 | `z.number()` Without `.optional()` Silently Blocks RHF Submit for Empty Optional Fields | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-335) |
| BP-336 | `user.tab()` Inside Radix Dialog Focus Trap Does Not Reliably Fire Blur on NumberInput in jsdom | Frontend | [bug-patterns/frontend.md](bug-patterns/frontend.md#bp-336) |

---

## How to Use

1. **Before implementing**: scan the table above for categories matching your task. Open the category file for the relevant BPs.
2. **When you hit a runtime error**: search this table for the error message or symptom.
3. **After fixing a new bug**: append the entry to the appropriate category file, then add a row to the Quick Lookup Table above.

## Adding New Patterns

```
# 1. Open the appropriate category file
# 2. Add a new ## BP-NNN section at the end
# 3. Add a row to the Quick Lookup Table in this index
# 4. Assign the next available BP number
```

> **Legacy note**: The original monolithic BUG_PATTERNS.md (8,775 lines) was restructured into this indexed format on 2026-05-03 to reduce LLM context load. All content is preserved in category files.
