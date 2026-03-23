# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 04

**Wave:** 04 of 07
**Date issued:** 2026-03-22
**Services:** S4 Content Ingestion (integration tests) + S5 Content Store (foundation)
**Execution model:** T-S4-014 first (sequential gate), then T-S5-001 and T-S5-002 in parallel
**Prerequisite:** Wave 03 complete and merged

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`

---

## Assigned agent profile(s)

- `docs/agents/backend-engineer.md`
- `docs/agents/data-platform-engineer.md`

---

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/services/content-ingestion.md` — full, final state after Wave 03 updates
4. `docs/services/content-store.md` — S5 service specification
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
6. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`
7. Confirm Wave 03 outputs exist:
   - `services/content-ingestion/src/content_ingestion/main.py`
   - `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`
   - `services/content-ingestion/src/content_ingestion/api/admin.py`
   - `services/content-ingestion/src/content_ingestion/api/health.py`
8. `services/content-store/pyproject.toml` — verify `uuid6`, `pydantic-settings`, `structlog`, `datasketch`, `readability-lxml`, `bleach`, `aiokafka`, `fastavro`, `redis[asyncio]` are listed.
9. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

This wave has two distinct parts:

**Part 1 (T-S4-014):** Validate the complete S4 service against real infrastructure (Postgres, MinIO, Kafka) via docker-compose integration tests. This gate must pass before S5 build begins — it confirms the S4→S5 contract (Avro schema on `content.article.raw.v1`) is correct.

**Part 2 (T-S5-001 + T-S5-002, parallel):** Lay the S5 Content Store foundation: domain entities and database infrastructure. These have no S4 implementation dependencies and can be authored in parallel with T-S4-014 if resources allow, but T-S4-014 must pass before Wave 05 starts.

---

## Task scope for this wave

**Sequential gate:**

| Task ID | Description | Execution |
|---------|-------------|-----------|
| T-S4-014 | S4 integration tests (pytest.mark.integration, full round-trip, idempotency) | Must complete + pass first |

**Parallel after T-S4-014 passes (or concurrent if separate agents available):**

| Task ID | Description |
|---------|-------------|
| T-S5-001 | S5 Config + Domain entities (Article, CanonicalDocument, DeduplicationDecision, DeduplicationStage, CorroborationPolicy) |
| T-S5-002 | S5 DB infrastructure (content_store_db session, DocumentRepository, MinHashRepository, OutboxRepository) |

---

## Why this chunk

T-S4-014 serves as the integration gate for S4: it validates that the full pipeline (adapter→MinIO→Postgres→Kafka outbox→Kafka dispatch) works end-to-end with real infrastructure. Running integration tests before starting S5 ensures the Avro schema contract on `content.article.raw.v1` is stable — S5's Kafka consumer will consume that topic. T-S5-001 and T-S5-002 have zero dependencies on S4 implementation (they only depend on design contracts from the PRD), so they can begin as soon as Wave 03 is merged, maximizing parallel throughput.

---

## Implementation instructions

### T-S4-014 — S4 Integration Tests

1. **Create `services/content-ingestion/docker-compose.test.yml`**:
   ```yaml
   version: "3.9"
   services:
     postgres:
       image: postgres:16
       environment:
         POSTGRES_DB: content_ingestion_test
         POSTGRES_USER: test
         POSTGRES_PASSWORD: test
       ports: ["5433:5432"]
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U test"]
         interval: 5s
         timeout: 5s
         retries: 10

     kafka:
       image: bitnami/kafka:3.7
       environment:
         KAFKA_CFG_NODE_ID: 0
         KAFKA_CFG_PROCESS_ROLES: controller,broker
         KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
         KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
         KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
         KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
       ports: ["9093:9092"]
       healthcheck:
         test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
         interval: 10s
         timeout: 10s
         retries: 10

     minio:
       image: minio/minio:latest
       command: server /data --console-address :9001
       environment:
         MINIO_ROOT_USER: minioadmin
         MINIO_ROOT_PASSWORD: minioadmin
       ports: ["9002:9000", "9003:9001"]
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
         interval: 5s
         timeout: 5s
         retries: 10
   ```

2. **Create `services/content-ingestion/tests/integration/conftest.py`**:
   - `pytest.fixture(scope="session")` for DB session factory (using test Postgres URL).
   - `pytest.fixture(scope="session")` for MinIO client (test bucket: `worldview-bronze-test`; create bucket on setup).
   - `pytest.fixture(scope="session")` for Kafka producer + consumer (topic: `content.article.raw.v1`).
   - All fixtures skip if `pytest.mark.integration` not present.
   - Run Alembic migrations in session fixture before tests.

3. **Create `services/content-ingestion/tests/integration/test_eodhd_adapter_pipeline.py`** (`@pytest.mark.integration`):
   ```python
   async def test_fetch_and_write_full_round_trip(session_factory, minio_client, kafka_consumer):
       """Full pipeline: adapter fetch → MinIO write → DB write → outbox pending."""
       # Setup: mock EODHD HTTP with respx/pytest-httpx returning 2 articles
       # Act: call FetchAndWriteUseCase.execute(source)
       # Assert 1: MinIO object exists at content-ingestion/eodhd/{url_hash}/raw/v1.json
       # Assert 2: fetch_log row written to Postgres
       # Assert 3: outbox_events row with status='pending'
       # Assert 4: NO Kafka message yet (dispatcher not run)
   ```

4. **Create `services/content-ingestion/tests/integration/test_outbox_dispatcher.py`** (`@pytest.mark.integration`):
   ```python
   async def test_outbox_dispatcher_publishes_to_kafka(session_factory, kafka_consumer):
       """Dispatcher round-trip: seed outbox → run_once() → Kafka message → status=dispatched."""
       # Seed: insert 1 outbox_event with valid Avro payload
       # Act: run OutboxDispatcher.run_once()
       # Assert 1: Kafka message received on content.article.raw.v1
       # Assert 2: outbox_event status='dispatched'
       # Assert 3: dispatched_at is set
   ```

5. **Create `services/content-ingestion/tests/integration/test_admin_api.py`** (`@pytest.mark.integration`):
   ```python
   async def test_source_crud_and_trigger(async_client):
       """Admin API CRUD + ingest trigger against real DB."""
       # POST /api/v1/sources → 201
       # GET /api/v1/sources → contains new source
       # PUT /api/v1/sources/{id} → update enabled=False → 200
       # POST /api/v1/ingest/trigger → 200 + FetchSummary
   ```

6. **Create `services/content-ingestion/tests/integration/test_idempotency.py`** (`@pytest.mark.integration`):
   ```python
   async def test_duplicate_fetch_results_in_single_row(session_factory, minio_client):
       """Idempotency: same URL fetched twice → exactly 1 fetch_log row, 1 outbox_event."""
       # Act 1: FetchAndWriteUseCase.execute(source) with mock returning article_url_A
       # Act 2: FetchAndWriteUseCase.execute(source) with same mock response
       # Assert: SELECT COUNT(*) FROM fetch_logs WHERE url_hash=... == 1
       # Assert: SELECT COUNT(*) FROM outbox_events == 1
   ```

7. **Update `services/content-ingestion/Makefile`** (or `pyproject.toml` test scripts):
   ```makefile
   test-integration:
       docker-compose -f docker-compose.test.yml up -d
       sleep 10  # Wait for healthchecks (or use wait-for-it)
       pytest tests/integration/ -m integration -v
       docker-compose -f docker-compose.test.yml down -v
   ```
   Prefer `wait-for-it.sh` or `pytest-docker` over bare `sleep`.

8. **Run:** `cd services/content-ingestion && make test-integration` — ALL tests must pass.

9. **Also run unit tests** to confirm no regression: `make test`, `ruff check`, `mypy`.

---

### T-S5-001 — S5 Config + Domain Entities

1. **Verify `services/content-store/pyproject.toml`** — confirm `uuid6`, `pydantic-settings`, `structlog`, `datasketch`, `readability-lxml`, `bleach`, `aiokafka`, `fastavro`, `redis[asyncio]` (for Valkey) present. Add missing deps.

2. **Create `services/content-store/src/content_store/config.py`**:
   ```python
   class Settings(BaseSettings):
       CONTENT_STORE_DB_URL: str
       KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
       KAFKA_INPUT_TOPIC: str = "content.article.raw.v1"
       KAFKA_OUTPUT_TOPIC: str = "content.article.stored.v1"
       KAFKA_CONSUMER_GROUP: str = "content-store-group"
       MINIO_ENDPOINT: str = "localhost:9000"
       MINIO_ACCESS_KEY: str
       MINIO_SECRET_KEY: str
       MINIO_BUCKET_BRONZE: str = "worldview-bronze"
       MINIO_BUCKET_SILVER: str = "worldview-silver"
       VALKEY_URL: str = "redis://localhost:6379"
       ADMIN_TOKEN: str
       MINHASH_NUM_PERM: int = 128
       LSH_NUM_BANDS: int = 4
       LSH_ROWS_PER_BAND: int = 32
       JACCARD_HARD_THRESHOLD: float = 0.95
       JACCARD_SOFT_THRESHOLD: float = 0.80
       OUTBOX_BATCH_SIZE: int = 100
       OUTBOX_POLL_INTERVAL_SECONDS: int = 5
       MAX_RETRIES: int = 3
       OUTBOX_METRICS_POLL_SECONDS: int = 30
   ```

3. **Create `services/content-store/src/content_store/domain/entities.py`**:
   - `DeduplicationStage` enum: `EXACT_RAW = "exact_raw"`, `EXACT_NORMALIZED = "exact_normalized"`, `NEAR_DUPLICATE = "near_duplicate"`.
   - `DeduplicationDecision` dataclass (frozen=True): `stage: DeduplicationStage`, `is_duplicate: bool`, `similarity_score: float | None`, `existing_doc_id: UUID | None`, `decision: str`.
     - Valid `decision` values: `"EXACT_DUPLICATE"`, `"NORMALIZED_DUPLICATE"`, `"SAME_SOURCE_DUPLICATE"`, `"CORROBORATING"`, `"UNIQUE"`.
   - `CorroborationPolicy` dataclass: `jaccard_hard_threshold: float = 0.95`, `jaccard_soft_threshold: float = 0.80`, `source_type_aware: bool = True`.
     - Method `classify(jaccard: float, same_source_type: bool) -> str`: returns `"SAME_SOURCE_DUPLICATE"` if `jaccard >= hard_threshold AND same_source_type`; `"CORROBORATING"` if `jaccard >= soft_threshold` (regardless of source type for > hard; cross-source for < hard but ≥ soft); `"UNIQUE"` otherwise.
   - `Article` dataclass (frozen=True): `id: UUID`, `source_type: str`, `url: str`, `url_hash: str`, `minio_bronze_key: str`, `fetched_at: datetime`, `byte_size: int`. (Fields match Avro schema from S4.)
   - `CanonicalDocument` dataclass: `id: UUID` (UUIDv7), `source_article_id: UUID`, `url: str`, `url_hash: str`, `normalized_text_hash: str`, `raw_sha256: str`, `minio_silver_key: str`, `source_type: str`, `created_at: datetime`.

4. **Create `services/content-store/src/content_store/domain/exceptions.py`**:
   - `DeduplicationError(Exception)`, `StorageError(Exception)`, `ConsumerError(Exception)`.

5. **Write unit tests** at `services/content-store/tests/unit/test_s5_domain.py`:
   - `test_corroboration_policy_same_source_high_jaccard` — jaccard=0.96, same source → SAME_SOURCE_DUPLICATE.
   - `test_corroboration_policy_cross_source_mid_jaccard` — jaccard=0.85, different source → CORROBORATING.
   - `test_corroboration_policy_cross_source_high_jaccard` — jaccard=0.96, different source → CORROBORATING.
   - `test_corroboration_policy_low_jaccard` — jaccard=0.70 → UNIQUE.
   - `test_deduplication_decision_frozen` — assert modifying field raises `FrozenInstanceError`.
   - `test_article_fields_from_avro_payload` — construct `Article` from dict matching Avro fields.

6. **Run:** `cd services/content-store && make test`, `ruff check services/content-store/src/`, `mypy services/content-store/src/`.

---

### T-S5-002 — S5 DB Infrastructure

1. **Create `services/content-store/src/content_store/infrastructure/db/session.py`** (same pattern as S4).

2. **Create `services/content-store/src/content_store/infrastructure/db/models.py`**:
   - `Base = DeclarativeBase()`
   - `DocumentModel` → table `documents`:
     `id UUID PK`, `source_article_id UUID NOT NULL`, `url TEXT NOT NULL`, `url_hash TEXT NOT NULL`, `normalized_text_hash TEXT NOT NULL`, `raw_sha256 TEXT NOT NULL`, `minio_silver_key TEXT NOT NULL`, `source_type TEXT NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
     Constraints: `UNIQUE(url_hash)`, `UNIQUE(normalized_text_hash)`.
   - `DeduplicationHashModel` → table `dedup_hashes`:
     `id UUID PK`, `hash_value TEXT NOT NULL`, `hash_type TEXT NOT NULL` (values: `raw_sha256`, `normalized_sha256`), `doc_id UUID NOT NULL FK→documents.id`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
     Constraint: `UNIQUE(hash_value, hash_type)`.
   - `MinHashSignatureModel` → table `minhash_signatures`:
     `id UUID PK`, `doc_id UUID NOT NULL FK→documents.id UNIQUE`, `signature INTEGER[] NOT NULL`, `num_perm INT NOT NULL DEFAULT 128`, `created_at TIMESTAMPTZ NOT NULL`.
     CRITICAL: `signature` column type is `ARRAY(Integer())` — NEVER `LargeBinary`/`BYTEA`.
   - `MinHashEntityMentionModel` → table `minhash_entity_mentions`:
     `id UUID PK`, `doc_id UUID NOT NULL FK→documents.id`, `entity_id UUID NOT NULL`, `entity_type TEXT NOT NULL`, `created_at TIMESTAMPTZ NOT NULL`.
     CRITICAL: `entity_id` has NO Postgres FK constraint (cross-DB logical FK to `intelligence_db`).
   - `OutboxEventModel` → table `outbox_events` (same schema as S4 outbox — define independently).
   - `DLQEventModel` → table `dlq_events` (same schema as S4 DLQ).

3. **Implement repositories**:
   - `DocumentRepository(session)`:
     - `async def create(doc: CanonicalDocument) -> None`
     - `async def exists_by_raw_sha256(sha256: str) -> bool`
     - `async def exists_by_normalized_hash(hash: str) -> bool`
     - `async def get_by_id(id: UUID) -> CanonicalDocument | None`
   - `MinHashRepository(session)`:
     - `async def create_signature(doc_id: UUID, signature: list[int], num_perm: int = 128) -> None`
     - `async def get_signature(doc_id: UUID) -> list[int] | None`
   - `OutboxRepository(session)` (same interface as S4 — implements independently):
     - `async def append(...)`, `async def fetch_pending(...)`, `async def mark_dispatched(...)`, `async def mark_failed(...)`, `async def move_to_dlq(...)`, `async def count_pending() -> int`

4. **Create Alembic migration** `services/content-store/alembic/versions/0001_initial_s5_schema.py`:
   - CREATE TABLE documents (with `UNIQUE(url_hash)`, `UNIQUE(normalized_text_hash)`).
   - CREATE TABLE dedup_hashes (with `UNIQUE(hash_value, hash_type)`).
   - CREATE TABLE minhash_signatures (signature column type: `INTEGER[]`).
   - CREATE TABLE minhash_entity_mentions (NO FK constraint on `entity_id`).
   - CREATE TABLE outbox_events.
   - CREATE TABLE dlq_events.
   - Verify in raw SQL: `signature INTEGER[]` — not `BYTEA`.

5. **Write unit tests** at `services/content-store/tests/unit/test_s5_repositories.py`:
   - `test_document_repo_create` — assert INSERT called with correct fields.
   - `test_document_repo_exists_by_raw_sha256_true` — mock returns row.
   - `test_document_repo_exists_by_raw_sha256_false`.
   - `test_document_repo_exists_by_normalized_hash`.
   - `test_minhash_repo_create_signature_stores_integer_list` — assert column type is `list[int]` not bytes.
   - `test_minhash_repo_get_signature_returns_list_int`.
   - `test_outbox_repo_count_pending`.
   - `test_entity_mention_no_fk_constraint` — assert `MinHashEntityMentionModel` has no FK on `entity_id` field (inspect `__table__.foreign_keys`).

6. **Run:** `cd services/content-store && make test`, `ruff check services/content-store/src/`, `mypy services/content-store/src/`.

---

## Constraints

- T-S4-014 integration tests MUST use `@pytest.mark.integration` — never mix into the unit test suite.
- T-S4-014: all assertions must verify actual state (DB rows, MinIO objects, Kafka messages) — no mock assertions in integration tests.
- T-S5-001 and T-S5-002: do NOT implement any S5 application logic, adapters, or API yet — domain + DB only.
- S5 `minhash_signatures.signature` MUST be `INTEGER[]` — fail the migration if `BYTEA` appears anywhere.
- S5 `minhash_entity_mentions.entity_id` MUST have no Postgres FK constraint — fail the test `test_entity_mention_no_fk_constraint` if FK is detected.
- No `print()` — `structlog` only.
- All datetimes UTC.
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths:**

```
# S4 integration tests
services/content-ingestion/docker-compose.test.yml
services/content-ingestion/tests/integration/__init__.py
services/content-ingestion/tests/integration/conftest.py
services/content-ingestion/tests/integration/test_eodhd_adapter_pipeline.py
services/content-ingestion/tests/integration/test_outbox_dispatcher.py
services/content-ingestion/tests/integration/test_admin_api.py
services/content-ingestion/tests/integration/test_idempotency.py

# S5 foundation
services/content-store/src/content_store/__init__.py
services/content-store/src/content_store/config.py
services/content-store/src/content_store/domain/__init__.py
services/content-store/src/content_store/domain/entities.py
services/content-store/src/content_store/domain/exceptions.py
services/content-store/src/content_store/infrastructure/__init__.py
services/content-store/src/content_store/infrastructure/db/__init__.py
services/content-store/src/content_store/infrastructure/db/session.py
services/content-store/src/content_store/infrastructure/db/models.py
services/content-store/src/content_store/infrastructure/db/repositories/__init__.py
services/content-store/src/content_store/infrastructure/db/repositories/document.py
services/content-store/src/content_store/infrastructure/db/repositories/minhash.py
services/content-store/src/content_store/infrastructure/db/repositories/outbox.py
services/content-store/alembic/versions/0001_initial_s5_schema.py
services/content-store/tests/__init__.py
services/content-store/tests/unit/__init__.py
services/content-store/tests/unit/test_s5_domain.py
services/content-store/tests/unit/test_s5_repositories.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 15 files outside write paths (S4 source code to understand outbox Avro schema, S4 models for reference, S5 PRD section).

**Stop condition:** T-S4-014 integration tests pass; T-S5-001 + T-S5-002 unit tests pass; all lint/type checks clean.

---

## Required tests

```bash
# S4 integration tests (requires docker-compose)
cd services/content-ingestion && make test-integration

# S4 unit tests (regression check)
cd services/content-ingestion && make test

# S5 unit tests
cd services/content-store && make test

# Lint + types (both services)
ruff check services/content-ingestion/src/ services/content-store/src/
mypy services/content-ingestion/src/ services/content-store/src/
```

**Pass criteria:**
- `make test-integration` exits 0 — all 4 integration test files green.
- `make test` (S4) exits 0 — no regression.
- `make test` (S5) exits 0 — all S5 unit tests green.
- `ruff check` exits 0 for both service src dirs.
- `mypy` exits 0 for both service src dirs.

---

## Incremental quality gates (mandatory)

1. **T-S4-014**: write docker-compose → write test files → `make test-integration` → `ruff check` → `mypy` → all green → DONE.
2. **T-S5-001** (parallel with T-S4-014 if separate agent): write domain → `make test` → `ruff check` → `mypy` → DONE.
3. **T-S5-002** (after T-S5-001): write DB infra → `make test` → `ruff check` → `mypy` → DONE.

No deferred fixes. If integration tests fail, diagnose and fix before proceeding.

---

## Documentation requirements

| File | Update condition | Required update |
|------|-----------------|-----------------|
| `docs/services/content-ingestion.md` | Testing section | Add integration test coverage description (4 test files, what each validates) |
| `docs/services/content-store.md` | Domain entities section | Add entity tables: Article, CanonicalDocument, DeduplicationDecision, CorroborationPolicy |
| `docs/services/content-store.md` | Database schema section | Add table schemas with column types; PROMINENTLY NOTE `signature INTEGER[]` and no FK on `entity_id` |

**Documentation quality criteria:**

1. Accuracy — `Article` fields must match S4 Avro schema fields exactly; `signature INTEGER[]` noted. ✓
2. Diagrams — N/A for domain entities. N/A.
3. Realistic code examples — show `Article` construction from Avro-deserialized dict. ✓
4. Abstract methods — N/A in this wave.
5. Common pitfalls — add to S5 service doc: (a) `signature BYTEA` instead of `INTEGER[]` will silently corrupt MinHash comparisons; (b) `entity_id FK constraint` will cause cross-DB FK violations at runtime — never add it; (c) `DeduplicationDecision.is_duplicate=True` does NOT always mean the article is suppressed — `CORROBORATING` articles are written.
6. Lib docs — N/A.
7. Service docs — both `content-ingestion.md` and `content-store.md` updated. ✓
8. No orphan docs. N/A.

---

## Required handoff evidence

1. **Changed files list.**
2. **Integration test results:** paste `make test-integration` output — all green.
3. **Unit test results (both services):** `make test` outputs — all green.
4. **Ruff + Mypy:** both exit 0.
5. **Docs changed:** integration test section in S4 doc; domain + schema section in S5 doc.
6. **Validation ledger:**

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S4-014 | PASS (integration) | PASS | PASS | UPDATED |
| T-S5-001 | PASS | PASS | PASS | UPDATED |
| T-S5-002 | PASS | PASS | PASS | UPDATED |

7. **Commit message proposal:**

```
feat(s4,s5): add S4 integration tests + S5 foundation (domain + DB infra)

S4: full pipeline integration tests (adapter→MinIO→Postgres→Kafka outbox→dispatch) with
idempotency and round-trip validation via docker-compose.
S5: domain entities (Article, CanonicalDocument, CorroborationPolicy, DeduplicationDecision)
and async SQLAlchemy repositories; minhash_signatures.signature as INTEGER[].

Co-authored-by: <agent>
```

---

## Definition of done

- [ ] T-S4-014: 4 integration test files pass against real infra (Postgres+MinIO+Kafka); idempotency confirmed; round-trip Kafka dispatch confirmed; `ruff`/`mypy` clean.
- [ ] T-S5-001: all domain entities importable; `CorroborationPolicy.classify()` tested for all threshold combinations; `Article` fields match S4 Avro schema; `ruff`/`mypy` clean.
- [ ] T-S5-002: session factory + 3 repositories; Alembic migration with `INTEGER[]` for signature; no FK on `entity_id`; FK test assertion passes; `ruff`/`mypy` clean.
- [ ] `make test-integration` (S4) exits 0.
- [ ] `make test` (S4 + S5) exits 0.
- [ ] `ruff check` + `mypy` exit 0 for both services.
- [ ] Both service docs updated per requirements.
- [ ] Documentation quality gate: all 8 criteria ✓ or N/A justified.
- [ ] Commit message proposal provided.
