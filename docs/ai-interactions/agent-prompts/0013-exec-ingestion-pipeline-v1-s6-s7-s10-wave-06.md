# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 06

**Wave:** 06 of 13
**Service:** S7 Knowledge Graph
**Focus:** S7 Foundation — Config, Domain Models, intelligence_db Adapter
**Tasks:** T-S7-001, T-S7-002 (parallel)
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/knowledge-graph.md`

---

## Assigned agent profile(s)

- **backend-engineer** — T-S7-002 (intelligence_db adapter, 7 repositories)
- **rag-knowledge-graph-engineer** — T-S7-001 (domain models: graph-specific types, confidence components, semantic modes)

Both agents work in parallel.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/knowledge-graph.md`
4. `docs/libs/ml-clients.md`
5. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S7-001, T-S7-002
6. Wave 05 handoff evidence — confirm S6 is complete and emitting `nlp.article.enriched.v1`
7. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
8. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

**PREREQUISITE GATE:** Do not begin Wave 06 until Wave 05 integration test `test_full_pipeline` passes. S7 consumes `nlp.article.enriched.v1` — S7 is useless without S6 emitting it.

---

## Objective

Establish the S7 Knowledge Graph foundation:
- **T-S7-001**: All configuration settings and 8 domain models (Relation, RelationEvidence, RelationSummary, Contradiction, RelationType, SemanticMode enum, DecayClass, ConfidenceComponents)
- **T-S7-002**: intelligence_db AsyncSession with 7 repositories; ALEMBIC_ENABLED=false enforced with RuntimeError

Unlike S6 which had a separate `nlp_db` and only read from `intelligence_db`, S7 owns the intelligence_db write path for relations, evidence, and claims (read access). Both tasks enforce that S7 must NOT run Alembic against intelligence_db — DDL is owned by the `intelligence-migrations` init container.

---

## Task scope for this wave

### Parallel group (both tasks run simultaneously)

**T-S7-001: Config + Domain Models**
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/src/knowledge_graph/domain/__init__.py`
- `services/knowledge-graph/src/knowledge_graph/domain/enums.py`
- `services/knowledge-graph/src/knowledge_graph/domain/models.py`

**T-S7-002: intelligence_db Adapter**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence_raw_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/claims_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/contradiction_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_summary_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/outbox_repository.py`

---

## Why this chunk

Wave 06 mirrors what Wave 01 did for S6: establish the foundation before any processing blocks are written. T-S7-001 (domain models) and T-S7-002 (repositories) are independent — they can be developed in parallel. All subsequent S7 waves (07–10) import from these modules. Correct type annotations and the ALEMBIC_ENABLED=false guard here prevent cascading errors in later waves.

---

## Implementation instructions

### T-S7-001: Config + Domain Models

#### config.py

```python
# services/knowledge-graph/src/knowledge_graph/config.py
from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    # intelligence_db
    INTELLIGENCE_DB_URL: str
    INTELLIGENCE_DB_READONLY_URL: str

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_GROUP_ID: str = "knowledge-graph-group"
    KAFKA_INPUT_TOPIC: str = "nlp.article.enriched.v1"
    KAFKA_ENTITY_DIRTIED_TOPIC: str = "entity.dirtied.v1"  # compacted topic

    # Valkey
    VALKEY_URL: str = "redis://localhost:6379"

    # intelligence_db safety
    ALEMBIC_ENABLED: bool = False  # MUST remain false — DDL owned by intelligence-migrations

    # Canonicalization
    RELATION_CANONICALIZATION_THRESHOLD: float = 0.35  # cosine distance threshold

    # Worker intervals (minutes)
    CONFIDENCE_RECOMPUTE_INTERVAL_MINUTES: int = 15
    CONTRADICTION_BATCH_INTERVAL_MINUTES: int = 30
    SUMMARY_GENERATION_INTERVAL_MINUTES: int = 60
    ENTITY_EMBEDDING_INTERVAL_MINUTES: int = 60
    RELATION_SUMMARY_EMBEDDING_INTERVAL_MINUTES: int = 120
    EVIDENCE_EMBEDDING_INTERVAL_MINUTES: int = 180

    # Confidence formula
    CORROBORATION_MIN_TEMPORAL_WEIGHT: float = 0.1  # for corroboration_gain
    MAX_CORROBORATION_GAIN: float = 0.20
    MAX_CONTRADICTION_PENALTY: float = 0.60

    # Block 14 shadow migration (deferred)
    BLOCK14_SHADOW_MIGRATION_ENABLED: bool = False
    BLOCK14_SHADOW_MIGRATION_CURRENT_PHASE: int = 0
    BLOCK14_SHADOW_MIGRATION_BACKFILL_BATCH_SIZE: int = 1000

    # Admin
    ADMIN_TOKEN: str

    # Entity refresh Valkey dedup
    ENTITY_REFRESH_LOCK_TTL_SECONDS: int = 1800  # 30 minutes

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
```

#### domain/enums.py

```python
# services/knowledge-graph/src/knowledge_graph/domain/enums.py
from enum import Enum

class SemanticMode(str, Enum):
    RELATION_STATE = "RELATION_STATE"    # Persistent relationship (e.g., CEO_OF)
    TEMPORAL_CLAIM = "TEMPORAL_CLAIM"   # Time-bound assertion (e.g., revenue guidance)

class DecayClass(str, Enum):
    """Decay class determines temporal weight half-life."""
    STANDARD = "standard"       # Uses relation_type_registry.decay_alpha
    TEMPORAL = "temporal"       # Fixed: 0.02310 (30-day half-life)

class RelationType(str, Enum):
    """Well-known relation types. Registry is authoritative; this is a partial list."""
    CEO_OF = "CEO_OF"
    CFO_OF = "CFO_OF"
    BOARD_MEMBER_OF = "BOARD_MEMBER_OF"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    PARTNER_OF = "PARTNER_OF"
    ACQUIRED_BY = "ACQUIRED_BY"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPLIES_TO = "SUPPLIES_TO"
```

#### domain/models.py

```python
# services/knowledge-graph/src/knowledge_graph/domain/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID
from knowledge_graph.domain.enums import SemanticMode, DecayClass

@dataclass
class ConfidenceComponents:
    """Breakdown of the 4-step confidence formula for a relation."""
    support: float           # Step 1: normalized weighted support
    corroboration_gain: float  # Step 2: distinct source corroboration (capped at 0.20)
    contradiction_penalty: float  # Step 3: top-3 contradiction links (capped at 0.60)
    final: float             # Step 4: clamp(support + corroboration - penalty, 0.0, 1.0)

    def validate(self) -> None:
        assert 0.0 <= self.final <= 1.0, f"Confidence must be in [0,1], got {self.final}"
        assert self.corroboration_gain <= 0.20, f"Corroboration gain capped at 0.20, got {self.corroboration_gain}"
        assert self.contradiction_penalty <= 0.60, f"Contradiction penalty capped at 0.60, got {self.contradiction_penalty}"

@dataclass
class Relation:
    id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    relation_type_id: int
    confidence: float
    summary_stale: bool = True
    semantic_mode: SemanticMode = SemanticMode.RELATION_STATE
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class RelationEvidence:
    id: UUID
    relation_id: UUID
    source_type: str          # 'news', 'sec_edgar', 'transcript'
    source_name: str          # publication or filing name
    evidence_text: str        # supporting text snippet
    temporal_weight: float    # decay-adjusted weight
    source_weight: float      # source reliability factor
    evidence_date: datetime
    processed: bool = False   # set True after confidence recomputation
    # partition_key: STORED column — NEVER set manually

@dataclass
class RelationSummary:
    id: UUID
    relation_id: UUID
    summary_text: str
    is_current: bool
    evidence_hash: str       # SHA-256 of sorted evidence IDs; change detection
    embedding: Optional[list[float]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Contradiction:
    id: UUID
    subject_entity_id: UUID  # Contradiction is subject-based, NOT claimer-based
    claim_type: str
    claim_a_id: UUID
    claim_b_id: UUID
    strength: float
    detected_at: datetime = field(default_factory=datetime.utcnow)
    # NO temporal weights cached here — computed dynamically in Block 13A
```

### T-S7-002: intelligence_db Adapter

#### session.py with ALEMBIC_ENABLED=false guard

```python
# services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from knowledge_graph.config import settings

# SAFETY: S7 must NEVER run Alembic against intelligence_db
# DDL is owned by intelligence-migrations init container
if settings.ALEMBIC_ENABLED:
    raise RuntimeError(
        "S7 Knowledge Graph must not run Alembic against intelligence_db. "
        "Set ALEMBIC_ENABLED=false. DDL is owned by intelligence-migrations."
    )

_engine = create_async_engine(
    settings.INTELLIGENCE_DB_URL,
    pool_size=20,
    max_overflow=10,
    echo=False,
)

_readonly_engine = create_async_engine(
    settings.INTELLIGENCE_DB_READONLY_URL,
    pool_size=10,
    max_overflow=5,
)

IntelligenceSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

ReadOnlySession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _readonly_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

#### RelationRepository (critical patterns)

```python
# services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_repository.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from knowledge_graph.domain.models import Relation

class RelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, relation: Relation) -> Relation:
        """
        Upsert with advisory lock on triple hash.
        NEVER insert partition_key — it is a STORED column.
        """
        result = await self.session.execute(
            text("""
                INSERT INTO relations
                    (id, subject_entity_id, object_entity_id, relation_type_id,
                     confidence, summary_stale, semantic_mode, created_at, updated_at)
                VALUES
                    (:id, :subject_entity_id, :object_entity_id, :relation_type_id,
                     :confidence, :summary_stale, :semantic_mode, NOW(), NOW())
                ON CONFLICT (subject_entity_id, object_entity_id, relation_type_id)
                DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    summary_stale = true,
                    updated_at = NOW()
                RETURNING id, confidence, summary_stale
            """),
            {
                "id": str(relation.id),
                "subject_entity_id": str(relation.subject_entity_id),
                "object_entity_id": str(relation.object_entity_id),
                "relation_type_id": relation.relation_type_id,
                "confidence": relation.confidence,
                "summary_stale": relation.summary_stale,
                "semantic_mode": relation.semantic_mode.value,
            }
        )
        await self.session.commit()
        return relation

    async def get_stale_summaries(self, limit: int = 50) -> list[dict]:
        result = await self.session.execute(
            text("SELECT id, subject_entity_id, object_entity_id FROM relations WHERE summary_stale = true LIMIT :limit FOR UPDATE SKIP LOCKED"),
            {"limit": limit}
        )
        return [dict(row._mapping) for row in result]

    async def set_confidence(self, relation_id, confidence: float) -> None:
        assert 0.0 <= confidence <= 1.0, f"Confidence out of range: {confidence}"
        await self.session.execute(
            text("UPDATE relations SET confidence = :conf, updated_at = NOW() WHERE id = :id"),
            {"conf": confidence, "id": str(relation_id)}
        )

    async def mark_summary_fresh(self, relation_id) -> None:
        await self.session.execute(
            text("UPDATE relations SET summary_stale = false WHERE id = :id"),
            {"id": str(relation_id)}
        )
```

#### RelationEvidenceRawRepository

```python
class RelationEvidenceRawRepository:
    async def insert(self, evidence: RelationEvidence) -> None:
        """
        CRITICAL: partition_key is a STORED generated column — NEVER include it in INSERT.
        """
        await self.session.execute(
            text("""
                INSERT INTO relation_evidence_raw
                    (id, relation_id, source_type, source_name, evidence_text,
                     temporal_weight, source_weight, evidence_date, processed)
                VALUES
                    (:id, :relation_id, :source_type, :source_name, :evidence_text,
                     :temporal_weight, :source_weight, :evidence_date, false)
            """),
            {
                "id": str(evidence.id),
                "relation_id": str(evidence.relation_id),
                "source_type": evidence.source_type,
                "source_name": evidence.source_name,
                "evidence_text": evidence.evidence_text,
                "temporal_weight": evidence.temporal_weight,
                "source_weight": evidence.source_weight,
                "evidence_date": evidence.evidence_date,
            }
        )

    async def get_unprocessed_by_partition(self, partition_key: str, limit: int = 1000) -> list[dict]:
        result = await self.session.execute(
            text("""
                SELECT id, relation_id, temporal_weight, source_weight, source_type, source_name
                FROM relation_evidence_raw
                WHERE partition_key = :pk AND processed = false
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            """),
            {"pk": partition_key, "limit": limit}
        )
        return [dict(row._mapping) for row in result]
```

#### ClaimsRepository (S7 read-only; S6 writes claims via outbox dispatcher)

```python
class ClaimsRepository:
    async def get_by_subject(
        self,
        subject_entity_id: UUID,
        claim_type: str,
        since: datetime,
    ) -> list[dict]:
        """Used by contradiction detection hot path and batch worker."""
        result = await self.session.execute(
            text("""
                SELECT id, subject_entity_id, claim_type, polarity, confidence, created_at
                FROM claims
                WHERE subject_entity_id = :subject_id
                  AND claim_type = :claim_type
                  AND created_at >= :since
                ORDER BY created_at DESC
            """),
            {
                "subject_id": str(subject_entity_id),
                "claim_type": claim_type,
                "since": since,
            }
        )
        return [dict(row._mapping) for row in result]
```

---

## Constraints

- Do NOT implement any processing blocks in this wave (Blocks 11–14 are Waves 07–09)
- ALEMBIC_ENABLED=false guard MUST raise RuntimeError at module import time
- Domain layer MUST NOT import from infrastructure/
- `partition_key` is a STORED generated column — RelationEvidenceRawRepository.insert MUST NOT include it in any INSERT statement
- `summary_authority()` is computed at query time (Wave 10 API) — do NOT add a `summary_authority` column or field to the Relation model
- `ConfidenceComponents.validate()` must assert all invariants — called in tests
- SemanticMode enum: exactly 2 values (RELATION_STATE, TEMPORAL_CLAIM)
- All datetime values UTC-only; use `datetime.utcnow()` or `datetime.now(timezone.utc)`
- structlog only
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.
- **`EntityId` for cross-service entity references**: S7 graph writes use `common.types.EntityId` for `subject_entity_id`, `object_entity_id`, and `entity_id` columns.

---

## Scope & token budget

**Write paths:**
```
services/knowledge-graph/src/knowledge_graph/__init__.py
services/knowledge-graph/src/knowledge_graph/config.py
services/knowledge-graph/src/knowledge_graph/domain/__init__.py
services/knowledge-graph/src/knowledge_graph/domain/enums.py
services/knowledge-graph/src/knowledge_graph/domain/models.py
services/knowledge-graph/src/knowledge_graph/infrastructure/__init__.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/__init__.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/__init__.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_evidence_raw_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/claims_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/contradiction_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_summary_repository.py
services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/outbox_repository.py
services/knowledge-graph/tests/unit/domain/test_models.py
services/knowledge-graph/tests/unit/domain/test_enums.py
services/knowledge-graph/tests/unit/infrastructure/test_intelligence_db.py
```

**Max exploration:** Read `docs/services/knowledge-graph.md`, `docs/libs/ml-clients.md`. Do not read S6 code.

**Stop condition:** All files created, unit tests pass, ruff+mypy pass.

---

## Required tests

```bash
cd services/knowledge-graph && pytest tests/unit/ -v
ruff check services/knowledge-graph/src/
mypy services/knowledge-graph/src/
```

**Pass criteria:**
- `SemanticMode` has exactly 2 values
- `ALEMBIC_ENABLED=true` raises `RuntimeError` at session import time
- `ConfidenceComponents.validate()` raises on `final > 1.0` and on `corroboration_gain > 0.20`
- `RelationEvidenceRawRepository.insert()` SQL does NOT include `partition_key` in column list
- All 7 repos have type annotations on all methods

---

## Incremental quality gates (mandatory)

1. **T-S7-001:**
   ```bash
   pytest tests/unit/domain/ -v
   ruff check src/knowledge_graph/domain/ src/knowledge_graph/config.py
   mypy src/knowledge_graph/domain/ src/knowledge_graph/config.py
   ```

2. **T-S7-002:**
   ```bash
   pytest tests/unit/infrastructure/test_intelligence_db.py -v
   ruff check src/knowledge_graph/infrastructure/intelligence_db/
   mypy src/knowledge_graph/infrastructure/intelligence_db/
   ```

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/knowledge-graph.md` | Domain models | Add table: model, fields, description |
| `docs/services/knowledge-graph.md` | Config | Add Settings table with defaults |
| `docs/services/knowledge-graph.md` | ALEMBIC safety | Add note: S7 must NOT run Alembic; DDL owned by intelligence-migrations |
| `docs/services/knowledge-graph.md` | partition_key | Add pitfall: partition_key is STORED — never include in INSERT |

**Common pitfalls (add to knowledge-graph.md):**
1. Setting `ALEMBIC_ENABLED=true` will cause RuntimeError at startup — intelligence_db DDL is owned exclusively by intelligence-migrations
2. Including `partition_key` in an INSERT will cause PostgreSQL error — it is a STORED generated column
3. Contradiction detection is subject-based (`subject_entity_id`), not claimer-based — wrong field causes missed contradictions

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/domain/ -v` | T-S7-001 | 0 | All pass |
| `pytest tests/unit/infrastructure/test_intelligence_db.py -v` | T-S7-002 | 0 | All pass |
| `ALEMBIC_ENABLED=true python -c "from knowledge_graph.infrastructure.intelligence_db.session import IntelligenceSession"` | ALEMBIC guard | 1 | RuntimeError |
| `ruff check src/` | Full wave 06 | 0 | No violations |
| `mypy src/` | Full wave 06 | 0 | No errors |

### Commit message
```
feat(s7): add domain models, intelligence_db adapter, ALEMBIC_ENABLED=false guard

Establish S7 config, SemanticMode/DecayClass/RelationType enums, 5 domain
models with ConfidenceComponents validation, and 7 intelligence_db repositories
with ALEMBIC_ENABLED=false RuntimeError guard and partition_key exclusion.
```

---

## Definition of done

- [ ] SemanticMode enum has exactly 2 values (RELATION_STATE, TEMPORAL_CLAIM)
- [ ] ALEMBIC_ENABLED=true raises RuntimeError at module import
- [ ] RelationEvidenceRawRepository.insert: no `partition_key` in SQL column list
- [ ] ConfidenceComponents.validate() asserts all 3 invariants
- [ ] All 7 repositories implemented with type annotations
- [ ] Domain layer imports nothing from infrastructure/
- [ ] Unit tests pass
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/knowledge-graph.md` updated with domain models, config table, ALEMBIC safety note, partition_key pitfall

---

## Backfill requirements for this wave (added 2026-03-23)

### `RelationEvidence` model — add `is_backfill`

Add `is_backfill: bool = False` to the `RelationEvidence` dataclass:

```python
@dataclass
class RelationEvidence:
    id: UUID
    relation_id: UUID
    source_type: str
    source_name: str
    evidence_text: str
    temporal_weight: float
    source_weight: float
    evidence_date: datetime   # coalesce(published_at, extracted_at) — see §2.4 PRD
    is_backfill: bool = False # True when ingested during boot-time backfill run
    processed: bool = False
    # partition_key: STORED column — NEVER set manually
```

### `relation_evidence_raw` schema — `is_backfill` column

The `intelligence_db` migration (owned by `intelligence-migrations`) adds `is_backfill BOOLEAN NOT NULL DEFAULT false` to `relation_evidence_raw`.  The `RelationEvidenceRawRepository.insert()` SQL must include this column:

```sql
INSERT INTO relation_evidence_raw
    (id, relation_id, source_type, source_name, evidence_text,
     temporal_weight, source_weight, evidence_date, is_backfill, processed)
VALUES
    (:id, :relation_id, :source_type, :source_name, :evidence_text,
     :temporal_weight, :source_weight, :evidence_date, :is_backfill, false)
```

### `evidence_date` setting rule (non-negotiable)

When constructing `RelationEvidence` in Block 10 (S6 LLM extraction), set:

```python
evidence_date = published_at if published_at is not None else extracted_at
```

where `published_at` comes from the `nlp.article.enriched.v1` Kafka event payload
(propagated from `content.article.stored.v1` → S4 adapter).

**Never use `datetime.utcnow()` or `now()` as `evidence_date`** — doing so makes
2-year-old backfilled articles appear as fresh evidence and corrupts the decay formula.
