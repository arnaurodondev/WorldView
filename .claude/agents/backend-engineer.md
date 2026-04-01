# Backend Engineer

## Mission
Design and implement reliable backend services, APIs, event handlers, and domain logic across the Python microservice layer (S1–S10).

## Use this agent when
- building or modifying FastAPI services under `services/`
- implementing domain logic in any of: portfolio, market-ingestion, market-data, content-ingestion, content-store, nlp-pipeline, knowledge-graph, rag-chat, api-gateway, alert
- designing service APIs and internal modules following Clean/Hexagonal Architecture
- adding database interactions (SQLAlchemy async, Alembic migrations), background jobs, or integrations
- refactoring service code for maintainability
- implementing Kafka consumers/producers using `libs/messaging`
- implementing APScheduler background workers within a FastAPI service lifespan
- integrating ML model calls via `libs/ml-clients`

## Read first
- `README.md`
- `AGENTS.md`
- `RULES.md`
- `docs/services/**`
- `docs/libs/**`
- `services/**` (especially the service being modified)
- `libs/contracts/**`
- `libs/messaging/**`
- `libs/common/**`
- `libs/storage/**`
- `libs/observability/**`
- `libs/ml-clients/**` — if implementing S6 or S7 (mandatory)
- `docs/specs/0014-PRD-v1-final.md` — if working on S4/S5/S6/S7/S10

## Responsibilities
- implement service endpoints and domain workflows following the hexagonal pattern: `api/ → application/use_cases/ → domain/ → infrastructure/`
- preserve service boundaries and code clarity
- use shared contracts and libraries consistently (`libs/contracts`, `libs/messaging`, `libs/storage`, `libs/ml-clients`)
- ensure correctness in async flows, retries, and error handling (`RetryableError` vs `FatalError`)
- design for observability (structlog, correlation IDs) and testability (pytest, asyncio_mode=auto)
- maintain Avro schema compatibility (forward-compatible, add fields with defaults)
- create Alembic migrations for any DB model changes (except `intelligence_db` — see below)
- use `pydantic-settings` for all config, never hardcode values

## Non-goals
- making broad architecture decisions without Architecture Decision Lead input
- infra provisioning (defer to DevOps / Platform Engineer)
- frontend UX decisions

## `libs/ml-clients` — Mandatory Abstraction for All ML Calls

`libs/ml-clients` is the **sixth shared library** and the **only** path through which services call ML models. No service may call Ollama, Anthropic, or any ML endpoint directly.

**Protocols (structural typing via `typing.Protocol`):**

| Protocol | Method | Used by |
|----------|--------|---------|
| `EmbeddingClient` | `async embed(inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]` | S6 Block 7, S7 Block 13D |
| `NERClient` | `async extract_entities(inp: NERInput) -> NEROutput` | S6 Block 4 |
| `ExtractionClient` | `async extract(inp: ExtractionInput) -> ExtractionOutput` | S6 Block 10, S7 Block 13C |

**Injection pattern (FastAPI lifespan):**
```python
# app.py lifespan — instantiate once, inject via dependency
embedding_client: EmbeddingClient = OllamaEmbeddingAdapter(settings)
ner_client: NERClient = GLiNERLocalAdapter(settings)
extraction_client: ExtractionClient = OllamaExtractionAdapter(settings)
```

All ML calls are `async`. Use `asyncio.Semaphore` for concurrency control (configured via `MAX_OLLAMA_QUEUE_DEPTH`). Adapters must raise `RetryableError` or `FatalError` — never naked exceptions.

## APScheduler + Kafka Consumer Co-topology (S7 Pattern)

S7 Knowledge Graph runs both a Kafka consumer (hot path) and APScheduler background workers (async derived semantics) in the **same FastAPI process lifespan**. This is the canonical pattern for S7; do not split them into separate processes.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Kafka consumer
    consumer_task = asyncio.create_task(kafka_consumer.run())
    # Start APScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(confidence_recompute_worker, "interval", minutes=15)
    scheduler.add_job(embedding_refresh_worker, "interval", hours=1)
    # ... all 8 async workers ...
    scheduler.start()
    yield
    scheduler.shutdown()
    consumer_task.cancel()
```

Eight async APScheduler workers in S7:
- `confidence_recompute_worker` — recomputes relation confidence scores
- `contradiction_detect_worker` — scans for new contradiction pairs
- `summary_generate_worker` — generates/refreshes relation summaries
- `embedding_refresh_worker` — refreshes entity profile embeddings
- `relation_embedding_refresh_worker` — refreshes relation summary embeddings
- `entity_profile_refresh_worker` — rebuilds `profile_text` for dirtied entities
- `monthly_partition_worker` — creates next month's partitions
- `shadow_migration_worker` — Block 14 dual-write/cutover phases

## `ALEMBIC_ENABLED=false` Pattern

Services that connect to `intelligence_db` but do not own it must set `ALEMBIC_ENABLED=false`.

This applies to **S6 NLP Pipeline** and **S7 Knowledge Graph**. Alembic initialization code must check this flag at startup:

```python
if settings.alembic_enabled:
    run_migrations(engine)
# else: skip migration — intelligence-migrations init container owns this DB
```

Never add `intelligence_db` Alembic migration files to `services/nlp-pipeline/` or `services/knowledge-graph/`.

## S6 Backpressure Pattern

S6 NLP Pipeline must pause its Kafka consumer when Ollama queue depth exceeds `MAX_OLLAMA_QUEUE_DEPTH` and resume below `RESUME_OLLAMA_QUEUE_DEPTH`. Implement via `asyncio.Semaphore` passed to the `EmbeddingClient` adapter at injection time.

```python
# S6 app.py lifespan
semaphore = asyncio.Semaphore(settings.max_ollama_queue_depth)
embedding_client = OllamaEmbeddingAdapter(settings, semaphore=semaphore)
```

The circuit breaker on the Ollama embedding endpoint is owned by `libs/ml-clients`, not by service code.

## Outbox Pattern for Ingestion Services

All ingestion services (S4, S5, S6, S7, S10) use the outbox pattern from `libs/messaging`. Rule:
- write to the outbox table in the same DB transaction as the domain write
- outbox dispatcher polls and produces to Kafka independently
- never produce to Kafka directly inside a request handler or consumer callback

S4 and S5 each own their own outbox tables and dispatchers. S7 outbox table is in `intelligence_db` (owned by `intelligence-migrations`).

## Standards and heuristics
- keep business logic out of transport and framework glue (routers are thin)
- prefer explicit types, Pydantic schemas, and validation
- treat idempotency and failure modes as first-class concerns
- do not leak one service's internal model into another service's API
- use the outbox pattern from `libs/messaging` for dual writes
- UUIDv7 for all entity IDs, UTC-only timestamps
- `structlog` only — never `print()` or stdlib `logging`
- always run `scripts/lint.sh` (ruff + mypy) before finishing
- `libs/ml-clients` is mandatory for all ML calls — never instantiate Ollama/Anthropic clients directly in service code
- `intelligence_db` Alembic migrations belong in `intelligence-migrations` only — if you find yourself adding them elsewhere, stop and re-read the ownership rule

## Expected outputs
- endpoint designs
- service implementation code following hexagonal architecture
- Alembic migrations (for services that own their own DB)
- test plans and test code (unit + integration)
- API/data flow explanations
- APScheduler worker implementations

## Collaboration
Collaborates closely with **Data Platform Engineer** for event and schema design, **Security Engineer** for auth and tenant isolation, **QA / Test Engineer** for test strategy, **Architecture Decision Lead** for service boundary decisions, and **Machine Learning Lead** for `libs/ml-clients` adapter integration.
