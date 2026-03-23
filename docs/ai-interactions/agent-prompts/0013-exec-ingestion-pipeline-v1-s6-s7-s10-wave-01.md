# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 01

**Wave:** 01 of 13
**Service:** S6 NLP Pipeline
**Focus:** S6 Foundation — Config, Domain Models, nlp_db Infrastructure, intelligence_db Adapter
**Tasks:** T-S6-001, T-S6-002, T-S6-003 (parallel)
**Date:** 2026-03-22

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0013-ingestion-pipeline-v1-s6-s7-s10-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- PRD: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
- Service doc: `docs/services/nlp-pipeline.md`

---

## Assigned agent profile(s)

- **backend-engineer** — infrastructure, repositories, config
- **machine-learning-lead** — domain models (EntityClass enum, NLP-specific types)

Both agents work in parallel on their respective task groups.

---

## Mandatory pre-read

Before writing any code, read:
1. `docs/agents/AGENTS.md` — agent protocols and conventions
2. `docs/CLAUDE.md` (or `CLAUDE.md` at repo root) — project-wide conventions
3. `docs/services/nlp-pipeline.md` — target service architecture
4. `docs/libs/ml-clients.md` — protocol definitions for NERClient, EmbeddingClient, ExtractionClient
5. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — full task details for T-S6-001, T-S6-002, T-S6-003
6. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

Establish the complete foundation for S6 NLP Pipeline: all configuration settings, domain models and enums, the nlp_db async SQLAlchemy session + repository layer, and the intelligence_db dual-connection adapter with ALEMBIC_ENABLED=false enforcement.

These three tasks are fully parallel — no cross-dependencies between them within this wave.

---

## Task scope for this wave

### Parallel group (all 3 tasks run simultaneously)

**T-S6-001: Config + Domain Models**
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `services/nlp-pipeline/src/nlp_pipeline/domain/__init__.py`
- `services/nlp-pipeline/src/nlp_pipeline/domain/enums.py`
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py`

**T-S6-002: nlp_db Infrastructure**
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/session.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/section_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/outbox_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/dlq_repository.py`

**T-S6-003: intelligence_db Adapter**
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/session.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/entity_alias_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/entity_profile_embedding_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/canonical_entity_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/relation_evidence_repository.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/claims_repository.py`

---

## Why this chunk

Wave 01 contains the three pure-foundation tasks with no intra-wave dependencies:
- T-S6-001 (config + domain) has no dependencies beyond Prompt 0015 foundations being in place
- T-S6-002 (nlp_db repos) depends only on nlp_db schema existing (Prompt 0015) and config (T-S6-001 can be co-developed)
- T-S6-003 (intelligence_db adapter) depends only on intelligence_db schema existing (Prompt 0015)

All subsequent S6 waves (02–05) import from these three modules. Getting them right and type-checked in Wave 01 prevents cascading type errors in later waves.

---

## Implementation instructions

### T-S6-001: Config + Domain Models

#### Step 1: Create config.py

```python
# services/nlp-pipeline/src/nlp_pipeline/config.py
from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    # Database
    NLP_DB_URL: str
    INTELLIGENCE_DB_URL: str
    INTELLIGENCE_DB_READONLY_URL: str

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_GROUP_ID: str = "nlp-pipeline-group"
    KAFKA_INPUT_TOPIC: str = "content.article.stored.v1"

    # Ollama / ML
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    GLINER_BATCH_SIZE: int = 32
    GLINER_THRESHOLD: float = 0.35
    MAX_OLLAMA_QUEUE_DEPTH: int = 20
    RESUME_OLLAMA_QUEUE_DEPTH: int = 5

    # Signal / resolution thresholds
    SIGNAL_CONFIDENCE_MIN: float = 0.80
    AUTO_RESOLVE_THRESHOLD: float = 0.85
    PROVISIONAL_THRESHOLD: float = 0.60

    # Embedding chunking
    EMBEDDING_CHUNK_SIZE: int = 512
    EMBEDDING_CHUNK_OVERLAP: int = 64

    # MinHash / LSH
    MINHASH_NUM_PERM: int = 128
    LSH_THRESHOLD: float = 0.80
    VALKEY_CONTENT_STORE_DB: int = 1
    VALKEY_URL: str = "redis://localhost:6379"

    # intelligence_db safety
    ALEMBIC_ENABLED: bool = False  # MUST remain false — DDL owned by intelligence-migrations

    # Admin
    ADMIN_TOKEN: str

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
```

#### Step 2: Create domain/enums.py

```python
# services/nlp-pipeline/src/nlp_pipeline/domain/enums.py
from enum import Enum

class EntityClass(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    FINANCIAL_INSTRUMENT = "FINANCIAL_INSTRUMENT"
    PRODUCT = "PRODUCT"
    EVENT = "EVENT"
    REGULATION = "REGULATION"
    CONCEPT = "CONCEPT"
    METRIC = "METRIC"
    OTHER = "OTHER"

class RoutingTier(str, Enum):
    DEEP = "deep"
    MEDIUM = "medium"
    LIGHT = "light"
    SUPPRESS = "suppress"

class SuppressAction(str, Enum):
    HALT = "halt"
    SECTION_EMBEDDINGS_ONLY = "section_embeddings_only"
    CONTINUE = "continue"

class ResolutionMethod(str, Enum):
    EXACT_ALIAS = "exact_alias"
    TICKER_ISIN = "ticker_isin"
    FUZZY_TRIGRAM = "fuzzy_trigram"
    ANN_HNSW = "ann_hnsw"
    UNRESOLVED = "unresolved"
```

#### Step 3: Create domain/models.py

All models as dataclasses with `__slots__=False` for SQLAlchemy compatibility. Use `uuid.uuid4` for IDs but accept UUIDv7 from callers (the domain layer does not generate IDs — infrastructure does).

```python
# services/nlp-pipeline/src/nlp_pipeline/domain/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID
from nlp_pipeline.domain.enums import EntityClass, RoutingTier, ResolutionMethod

@dataclass
class Section:
    id: UUID
    article_id: UUID
    section_index: int
    section_type: str  # 'paragraph', 'item_{n}', 'speaker_turn', 'synthetic'
    text: str
    start_char: int
    end_char: int
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Chunk:
    id: UUID
    section_id: UUID
    chunk_index: int
    text: str
    token_count: int
    embedding: Optional[list[float]] = None

@dataclass
class EntityMention:
    id: UUID
    section_id: UUID
    text: str
    entity_class: EntityClass
    start_char: int
    end_char: int
    score: float
    resolved_entity_id: Optional[UUID] = None
    resolution_method: ResolutionMethod = ResolutionMethod.UNRESOLVED
    resolution_confidence: float = 0.0

@dataclass
class RoutingDecision:
    id: UUID
    article_id: UUID
    tier: RoutingTier
    score: float
    signal_breakdown: dict  # {signal_name: weighted_value}
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class NLPDocument:
    article_id: UUID
    raw_content: str
    source_type: str  # 'news', 'sec_edgar', 'transcript', 'other'
    document_type: str  # 'article', 'earnings', '8K', etc.
    published_at: datetime
    sections: list[Section] = field(default_factory=list)
    entity_mentions: list[EntityMention] = field(default_factory=list)
    routing_decision: Optional[RoutingDecision] = None

@dataclass
class SignalEvent:
    entity_id: UUID
    article_id: UUID
    signal_type: str
    confidence: float
    payload: dict

@dataclass
class EmbeddingPendingEntry:
    id: UUID
    ref_type: str  # 'chunk' or 'section'
    ref_id: UUID
    retry_count: int = 0
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```

### T-S6-002: nlp_db Infrastructure

#### Step 1: session.py

```python
# services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from nlp_pipeline.config import settings

async_engine = create_async_engine(
    settings.NLP_DB_URL,
    pool_size=10,
    max_overflow=20,
    echo=False,
)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

#### Step 2: Each repository

Each repository takes `AsyncSession` as constructor argument. Use `sqlalchemy.text()` for all raw SQL. Use `sqlalchemy` Core or ORM selects — do NOT use raw f-strings with user data.

**SectionRepository:**
```python
async def insert_batch(self, sections: list[Section]) -> None:
    await self.session.execute(
        text("INSERT INTO sections (id, article_id, section_index, section_type, text, start_char, end_char) VALUES (:id, :article_id, :section_index, :section_type, :text, :start_char, :end_char)"),
        [asdict(s) for s in sections]
    )
    await self.session.commit()

async def get_by_article_id(self, article_id: UUID) -> list[Section]:
    result = await self.session.execute(
        text("SELECT * FROM sections WHERE article_id = :article_id ORDER BY section_index"),
        {"article_id": article_id}
    )
    return [Section(**row._mapping) for row in result]
```

**OutboxRepository (critical pattern):**
```python
async def poll_pending(self, limit: int = 100) -> list[dict]:
    result = await self.session.execute(
        text("""
            SELECT id, event_type, payload, created_at
            FROM outbox_events
            WHERE dispatched_at IS NULL
            ORDER BY created_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"limit": limit}
    )
    return [dict(row._mapping) for row in result]

async def mark_dispatched(self, ids: list[UUID]) -> None:
    await self.session.execute(
        text("UPDATE outbox_events SET dispatched_at = NOW() WHERE id = ANY(:ids)"),
        {"ids": ids}
    )
    await self.session.commit()
```

**DLQRepository:**
```python
async def insert(self, topic: str, partition: int, offset: int, payload: bytes, error: str) -> None:
    await self.session.execute(
        text("INSERT INTO dlq_events (id, topic, partition, offset, payload, error, created_at) VALUES (gen_random_uuid(), :topic, :partition, :offset, :payload, :error, NOW())"),
        {"topic": topic, "partition": partition, "offset": offset, "payload": payload, "error": error}
    )
    await self.session.commit()
```

### T-S6-003: intelligence_db Adapter

#### Step 1: session.py with ALEMBIC_ENABLED guard

```python
# services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from nlp_pipeline.config import settings

# SAFETY: S6 must NEVER run Alembic against intelligence_db
if settings.ALEMBIC_ENABLED:
    raise RuntimeError(
        "S6 NLP Pipeline must not run Alembic against intelligence_db. "
        "DDL is owned by intelligence-migrations. Set ALEMBIC_ENABLED=false."
    )

# Read-only engine (uses a read replica or same DB with read-only role)
_readonly_engine = create_async_engine(
    settings.INTELLIGENCE_DB_READONLY_URL,
    pool_size=5,
    max_overflow=10,
)

# Write engine (limited write access: canonical_entities, claims, relation_evidence_raw)
_write_engine = create_async_engine(
    settings.INTELLIGENCE_DB_URL,
    pool_size=5,
    max_overflow=10,
)

ReadOnlySession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _readonly_engine, expire_on_commit=False
)
WriteSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _write_engine, expire_on_commit=False
)
```

#### Step 2: EntityAliasRepository (read-only)

```python
class EntityAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session  # must be ReadOnlySession

    async def find_by_text(self, text: str) -> Optional[UUID]:
        result = await self.session.execute(
            sqlalchemy.text("SELECT entity_id FROM entity_aliases WHERE alias = :text LIMIT 1"),
            {"text": text}
        )
        row = result.fetchone()
        return row.entity_id if row else None

    async def find_by_ticker(self, ticker: str) -> Optional[UUID]:
        result = await self.session.execute(
            sqlalchemy.text("SELECT entity_id FROM entity_aliases WHERE alias = :ticker AND alias_type = 'TICKER' LIMIT 1"),
            {"ticker": ticker}
        )
        row = result.fetchone()
        return row.entity_id if row else None

    async def find_by_isin(self, isin: str) -> Optional[UUID]:
        result = await self.session.execute(
            sqlalchemy.text("SELECT entity_id FROM entity_aliases WHERE alias = :isin AND alias_type = 'ISIN' LIMIT 1"),
            {"isin": isin}
        )
        row = result.fetchone()
        return row.entity_id if row else None
```

#### Step 3: EntityProfileEmbeddingRepository (read for ANN search)

```python
async def find_nearest(self, embedding: list[float], limit: int = 5) -> list[tuple[UUID, float]]:
    # Uses HNSW index on entity_profile_embeddings
    result = await self.session.execute(
        sqlalchemy.text("""
            SELECT entity_id, embedding <=> :embedding::vector AS distance
            FROM entity_profile_embeddings
            WHERE expires_at IS NULL OR expires_at > NOW()
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """),
        {"embedding": str(embedding), "limit": limit}
    )
    return [(row.entity_id, row.distance) for row in result]
```

---

## Constraints

- Do NOT implement anything outside T-S6-001, T-S6-002, T-S6-003
- Do NOT create any Alembic migration files for intelligence_db — only for nlp_db if needed
- ALEMBIC_ENABLED=false guard must raise RuntimeError at module import time (not at request time)
- Domain layer (domain/) must have ZERO imports from infrastructure/
- All datetime values must be UTC-only; use `datetime.utcnow()` or `datetime.now(timezone.utc)`
- Use UUIDv7 for new IDs in infrastructure layer (not domain); if no UUIDv7 lib, use `uuid.uuid4()` and document
- structlog only for logging — do NOT use Python stdlib `logging` directly
- EntityClass enum must have exactly 10 values — count them
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.

---

## Scope & token budget

**Write paths (exhaustive list):**
```
services/nlp-pipeline/src/nlp_pipeline/config.py
services/nlp-pipeline/src/nlp_pipeline/domain/__init__.py
services/nlp-pipeline/src/nlp_pipeline/domain/enums.py
services/nlp-pipeline/src/nlp_pipeline/domain/models.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/session.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/section_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/outbox_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/dlq_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/session.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/__init__.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/entity_alias_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/entity_profile_embedding_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/canonical_entity_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/relation_evidence_repository.py
services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/claims_repository.py
services/nlp-pipeline/tests/unit/domain/test_models.py
services/nlp-pipeline/tests/unit/domain/test_enums.py
services/nlp-pipeline/tests/unit/infrastructure/test_nlp_db.py
services/nlp-pipeline/tests/unit/infrastructure/test_intelligence_db.py
```

**Max exploration:** Read existing `services/nlp-pipeline/` structure, existing `libs/ml-clients/` protocols. Do not read S7 or S10 code.

**Stop condition:** All files in write paths above exist, unit tests pass, ruff + mypy pass.

---

## Required tests

```bash
# Unit tests
cd services/nlp-pipeline && pytest tests/unit/domain/ tests/unit/infrastructure/ -v

# Lint
ruff check services/nlp-pipeline/src/

# Type check
mypy services/nlp-pipeline/src/
```

**Pass criteria:**
- `EntityClass` enum has exactly 10 members
- `ALEMBIC_ENABLED=true` in test env → `RuntimeError` raised at intelligence_db session import
- All repo methods have correct return type annotations
- No `Any` types without explicit `# type: ignore` with explanation
- ruff exits 0
- mypy exits 0

---

## Incremental quality gates (mandatory)

After EACH task is complete (do not wait for all three):

1. **T-S6-001 complete:**
   ```bash
   pytest services/nlp-pipeline/tests/unit/domain/ -v
   ruff check services/nlp-pipeline/src/nlp_pipeline/domain/ services/nlp-pipeline/src/nlp_pipeline/config.py
   mypy services/nlp-pipeline/src/nlp_pipeline/domain/ services/nlp-pipeline/src/nlp_pipeline/config.py
   ```

2. **T-S6-002 complete:**
   ```bash
   pytest services/nlp-pipeline/tests/unit/infrastructure/test_nlp_db.py -v
   ruff check services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/
   mypy services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/
   ```

3. **T-S6-003 complete:**
   ```bash
   pytest services/nlp-pipeline/tests/unit/infrastructure/test_intelligence_db.py -v
   ruff check services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/
   mypy services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/
   ```

**No deferred fixes rule:** If ruff or mypy fail on any task, fix before moving to the next task. Do not accumulate lint debt.

---

## Documentation requirements

| File | Update condition | Action |
|------|-----------------|--------|
| `docs/services/nlp-pipeline.md` | Domain models section | Add table of domain models with field descriptions |
| `docs/libs/ml-clients.md` | N/A — no ml-clients surface changes in Wave 01 | No update needed |
| `docs/services/nlp-pipeline.md` | Config section | Add table of all Settings fields with types and defaults |

**All 8 documentation quality criteria applied to updates:**
1. Accuracy: domain model table must match actual dataclass fields
2. Diagrams: N/A (no multi-component flows in this wave)
3. Realistic examples: N/A (no request/response shapes in this wave)
4. Abstract methods: N/A (no abstract base classes in this wave)
5. Common pitfalls: Add note in nlp-pipeline.md: "Do not set ALEMBIC_ENABLED=true — intelligence_db DDL is owned by intelligence-migrations"
6. Lib docs: N/A
7. Service docs: nlp-pipeline.md updated
8. No orphan docs: N/A

---

## Required handoff evidence

### Changed files
Exact list of files created or modified (all from write paths above).

### Test results
```
pytest tests/unit/domain/ tests/unit/infrastructure/ — PASS (N tests)
ruff check src/ — exit code 0
mypy src/ — exit code 0
```

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/domain/` | T-S6-001 | 0 | All tests pass |
| `pytest tests/unit/infrastructure/test_nlp_db.py` | T-S6-002 | 0 | All tests pass |
| `pytest tests/unit/infrastructure/test_intelligence_db.py` | T-S6-003 ALEMBIC_ENABLED guard | 0 | RuntimeError on ALEMBIC_ENABLED=true |
| `ruff check src/` | All wave 01 code | 0 | No violations |
| `mypy src/` | All wave 01 code | 0 | No errors |

### Commit message
```
feat(s6): add domain models, nlp_db repos, intelligence_db adapter foundation

Establish config, EntityClass/RoutingTier enums, 9 domain models, 7 nlp_db
repositories (AsyncSession, outbox, DLQ), and intelligence_db dual-connection
adapter with ALEMBIC_ENABLED=false runtime guard.
```

---

## Definition of done

- [ ] EntityClass enum has exactly 10 values
- [ ] RoutingTier enum has exactly 4 values (DEEP, MEDIUM, LIGHT, SUPPRESS)
- [ ] ALEMBIC_ENABLED=true raises RuntimeError at intelligence_db session import time
- [ ] All 7 nlp_db repositories implemented with type annotations
- [ ] All 5 intelligence_db repositories implemented with type annotations
- [ ] Domain layer imports nothing from infrastructure/
- [ ] Unit tests pass
- [ ] ruff exits 0
- [ ] mypy exits 0
- [ ] docs/services/nlp-pipeline.md updated with domain model table and config table
- [ ] Documentation quality gate: criterion 1 (accuracy) and criterion 5 (common pitfalls) satisfied
