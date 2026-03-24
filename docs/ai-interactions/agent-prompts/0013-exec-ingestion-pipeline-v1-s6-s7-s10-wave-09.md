# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 09

**Wave:** 09 of 13
**Service:** S7 Knowledge Graph
**Focus:** S7 Workers 13E–H + Outbox Dispatcher + Block 14 Design Memo
**Tasks:** T-S7-010, T-S7-011, T-S7-012, T-S7-013, T-S7-015, T-S7-016
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/knowledge-graph.md`

---

## Assigned agent profile(s)

- **backend-engineer** — T-S7-012 (monthly partition), T-S7-013 (yearly partition), T-S7-015 (outbox dispatcher)
- **rag-knowledge-graph-engineer** — T-S7-010 (relation summary embedding), T-S7-011 (evidence embedding), T-S7-016 (Block 14 design memo)

All tasks can run in parallel; T-S7-016 is documentation-only (no code).

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/knowledge-graph.md`
4. `docs/libs/ml-clients.md`
5. Wave 06 output: repos; Wave 07: scheduler, co-topology; Wave 08: Workers 13A–D
6. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S7-010 through T-S7-016
7. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
8. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Complete the remaining S7 async workers, outbox dispatcher, and the Block 14 design memo:
- **T-S7-010** (Block 13E): Relation summary embedding refresh — 2h interval; current summaries without embeddings
- **T-S7-011** (Block 13F): Relation evidence embedding refresh — 3h interval; recent evidence without embeddings
- **T-S7-012** (Block 13G): Monthly partition worker — 1st of month + startup; idempotent IF NOT EXISTS
- **T-S7-013** (Block 13H): Yearly partition worker — 1st of year + startup; idempotent
- **T-S7-015**: Outbox dispatcher — poll intelligence_db outbox; publish 3 Kafka topics; entity.dirtied.v1 direct (not via outbox)
- **T-S7-016**: Block 14 design memo — 4 shadow migration phases; no code

After Wave 09, all 8 workers are registered in `KnowledgeGraphScheduler.register_workers()` — update `main.py` to pass all 8 workers at startup.

---

## Task scope for this wave

### Parallel group (all 6 tasks independent)

**T-S7-010: Block 13E — Relation Summary Embedding**
- `services/knowledge-graph/src/knowledge_graph/application/workers/relation_summary_embedding.py`

**T-S7-011: Block 13F — Relation Evidence Embedding**
- `services/knowledge-graph/src/knowledge_graph/application/workers/relation_evidence_embedding.py`

**T-S7-012: Block 13G — Monthly Partition Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/monthly_partition.py`

**T-S7-013: Block 13H — Yearly Partition Worker**
- `services/knowledge-graph/src/knowledge_graph/application/workers/yearly_partition.py`

**T-S7-015: Outbox Dispatcher**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/dispatcher.py`

**T-S7-016: Block 14 Design Memo** (documentation only)
- `services/knowledge-graph/docs/block14-shadow-migration-design.md`

---

## Why this chunk

Workers 13E–H are the lower-priority refresh workers (longer intervals, no real-time impact). They are independent of each other and of Workers 13A–D from Wave 08. The outbox dispatcher (T-S7-015) depends on intelligence_db outbox (Wave 06) and the main loop (Wave 07) but not on any specific worker. T-S7-016 is a design memo with no code dependencies. All 6 tasks can be done in parallel.

After this wave, `main.py` must be updated to fully register all 8 workers.

---

## Implementation instructions

### T-S7-010: Block 13E — Relation Summary Embedding Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/relation_summary_embedding.py
import structlog
from sqlalchemy import text
from knowledge_graph.infrastructure.metrics import s7_embeddings_refreshed_total

logger = structlog.get_logger(__name__)

class RelationSummaryEmbeddingWorker:
    def __init__(self, embedding_client, session) -> None:
        self.embedding_client = embedding_client
        self.session = session

    async def run(self) -> None:
        """2h: embed current summaries missing embeddings."""
        # Query: is_current=true AND (embedding IS NULL)
        # HNSW partial index predicate: WHERE expires_at IS NULL OR expires_at > now()
        result = await self.session.execute(
            text("""
                SELECT id, summary_text
                FROM relation_summaries
                WHERE is_current = true AND embedding IS NULL
                LIMIT 100
                FOR UPDATE SKIP LOCKED
            """)
        )
        summaries = [dict(row._mapping) for row in result]
        if not summaries:
            return

        texts = [s["summary_text"] for s in summaries]
        embeddings = await self.embedding_client.embed(texts)

        for summary, embedding in zip(summaries, embeddings):
            await self.session.execute(
                text("""
                    UPDATE relation_summaries
                    SET embedding = :embedding::vector
                    WHERE id = :id
                """),
                {"embedding": str(embedding), "id": str(summary["id"])}
            )
        await self.session.commit()
        s7_embeddings_refreshed_total.labels(worker="relation_summary").inc(len(summaries))
        logger.info("relation_summary_embeddings_refreshed", count=len(summaries))
```

### T-S7-011: Block 13F — Relation Evidence Embedding Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/relation_evidence_embedding.py
import structlog
from sqlalchemy import text
from knowledge_graph.infrastructure.metrics import s7_embeddings_refreshed_total

logger = structlog.get_logger(__name__)

EMBEDDING_BATCH_SIZE = 32

class RelationEvidenceEmbeddingWorker:
    def __init__(self, embedding_client, session) -> None:
        self.embedding_client = embedding_client
        self.session = session

    async def run(self) -> None:
        """3h: embed recent evidence rows without embeddings."""
        result = await self.session.execute(
            text("""
                SELECT id, evidence_text
                FROM relation_evidence_raw
                WHERE embedding IS NULL
                ORDER BY evidence_date DESC
                LIMIT 200
                FOR UPDATE SKIP LOCKED
            """)
        )
        rows = [dict(row._mapping) for row in result]
        if not rows:
            return

        # Process in batches of EMBEDDING_BATCH_SIZE
        for i in range(0, len(rows), EMBEDDING_BATCH_SIZE):
            batch = rows[i:i + EMBEDDING_BATCH_SIZE]
            texts = [r["evidence_text"][:2048] for r in batch]  # First 2048 chars
            try:
                embeddings = await self.embedding_client.embed(texts)
                for row, embedding in zip(batch, embeddings):
                    await self.session.execute(
                        text("UPDATE relation_evidence_raw SET embedding = :emb::vector WHERE id = :id"),
                        {"emb": str(embedding), "id": str(row["id"])}
                    )
                await self.session.commit()
                s7_embeddings_refreshed_total.labels(worker="relation_evidence").inc(len(batch))
            except Exception as e:
                logger.error("evidence_embedding_batch_failed", error=str(e), batch_start=i)

        logger.info("evidence_embeddings_refreshed", total=len(rows))
```

### T-S7-012: Block 13G — Monthly Partition Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/monthly_partition.py
import structlog
from datetime import datetime, timezone
from calendar import monthrange
from sqlalchemy import text

logger = structlog.get_logger(__name__)

class MonthlyPartitionWorker:
    def __init__(self, session) -> None:
        self.session = session

    async def run(self) -> None:
        """
        Create next month's partitions for 3 tables.
        Idempotent: IF NOT EXISTS pattern.
        Runs on 1st of month and at startup.
        """
        now = datetime.now(timezone.utc)
        # Compute next month
        if now.month == 12:
            next_year, next_month = now.year + 1, 1
        else:
            next_year, next_month = now.year, now.month + 1

        await self._create_monthly_partition("relation_evidence_raw", now.year, now.month, "evidence_date")
        await self._create_monthly_partition("relation_evidence_raw", next_year, next_month, "evidence_date")

        # intelligence_db.events (monthly)
        await self._create_monthly_partition("events", now.year, now.month, "event_date")
        await self._create_monthly_partition("events", next_year, next_month, "event_date")

        # intelligence_db.claims (monthly)
        await self._create_monthly_partition("claims", now.year, now.month, "created_at")
        await self._create_monthly_partition("claims", next_year, next_month, "created_at")

        logger.info("monthly_partitions_created", year=next_year, month=next_month)

    async def _create_monthly_partition(
        self,
        parent_table: str,
        year: int,
        month: int,
        partition_column: str,
    ) -> None:
        """Create IF NOT EXISTS — idempotent."""
        partition_name = f"{parent_table}_{year}_{month:02d}"
        start = f"{year}-{month:02d}-01"
        # Compute end: first day of following month
        days = monthrange(year, month)[1]
        end_dt = datetime(year, month, days) + __import__("datetime").timedelta(days=1)
        end = end_dt.strftime("%Y-%m-%d")

        sql = f"""
            CREATE TABLE IF NOT EXISTS {partition_name}
            PARTITION OF {parent_table}
            FOR VALUES FROM ('{start}') TO ('{end}')
        """
        try:
            await self.session.execute(text(sql))
            await self.session.commit()
            logger.debug("partition_created_or_exists", partition=partition_name)
        except Exception as e:
            logger.error("partition_creation_failed", partition=partition_name, error=str(e))
```

### T-S7-013: Block 13H — Yearly Partition Worker

```python
# services/knowledge-graph/src/knowledge_graph/application/workers/yearly_partition.py
import structlog
from datetime import datetime, timezone
from sqlalchemy import text

logger = structlog.get_logger(__name__)

class YearlyPartitionWorker:
    def __init__(self, session) -> None:
        self.session = session

    async def run(self) -> None:
        """
        Create next year's partitions for yearly-partitioned tables.
        Idempotent: IF NOT EXISTS pattern.
        Runs on 1st of January and at startup.
        """
        now = datetime.now(timezone.utc)
        for year in [now.year, now.year + 1]:
            await self._create_yearly_partition("relation_evidence_yearly_archive", year)
        logger.info("yearly_partitions_created", current_year=now.year)

    async def _create_yearly_partition(self, parent_table: str, year: int) -> None:
        partition_name = f"{parent_table}_{year}"
        start = f"{year}-01-01"
        end = f"{year + 1}-01-01"

        sql = f"""
            CREATE TABLE IF NOT EXISTS {partition_name}
            PARTITION OF {parent_table}
            FOR VALUES FROM ('{start}') TO ('{end}')
        """
        try:
            await self.session.execute(text(sql))
            await self.session.commit()
            logger.debug("yearly_partition_created_or_exists", partition=partition_name)
        except Exception as e:
            logger.error("yearly_partition_creation_failed", partition=partition_name, error=str(e))
```

### T-S7-015: Outbox Dispatcher

```python
# services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/dispatcher.py
import asyncio
import json
import structlog
from knowledge_graph.config import settings
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox_repository import OutboxRepository

logger = structlog.get_logger(__name__)

TOPIC_MAP = {
    "graph.state.changed": "graph.state.changed.v1",
    "intelligence.contradiction": "intelligence.contradiction.v1",
    "relation.type.proposed": "relation.type.proposed.v1",
    # entity.dirtied is produced DIRECTLY — NOT via outbox (compacted topic)
}

class OutboxDispatcher:
    def __init__(
        self,
        outbox_repo: OutboxRepository,
        kafka_producer,
        avro_serializer,
    ) -> None:
        self.outbox_repo = outbox_repo
        self.kafka_producer = kafka_producer
        self.avro_serializer = avro_serializer
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._dispatch_batch()
            except Exception as e:
                logger.error("s7_outbox_dispatch_error", error=str(e))
            await asyncio.sleep(0.1)

    async def stop(self) -> None:
        self._running = False

    async def _dispatch_batch(self, limit: int = 100) -> None:
        events = await self.outbox_repo.poll_pending(limit)
        if not events:
            return

        dispatched_ids = []
        for event in events:
            try:
                await self._dispatch_event(event)
                dispatched_ids.append(event["id"])
            except Exception as e:
                logger.error("s7_event_dispatch_failed", event_id=event["id"], error=str(e))

        if dispatched_ids:
            await self.outbox_repo.mark_dispatched(dispatched_ids)

    async def _dispatch_event(self, event: dict) -> None:
        event_type = event["event_type"]
        payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])

        if event_type == "entity.dirtied":
            # entity.dirtied.v1 is produced DIRECTLY in Block 12a — should never reach outbox
            logger.warning("entity_dirtied_in_outbox",
                          message="entity.dirtied events should be produced directly, not via outbox")
            return

        topic = TOPIC_MAP.get(event_type)
        if not topic:
            logger.warning("unknown_event_type_in_outbox", event_type=event_type)
            return

        # Determine key
        key = None
        if event_type == "intelligence.contradiction":
            key = payload.get("subject_entity_id", "").encode()
        elif event_type == "graph.state.changed":
            key = payload.get("relation_id", "").encode()

        avro_bytes = self.avro_serializer.serialize(topic, payload)
        await self.kafka_producer.send(topic, key=key, value=avro_bytes)
        logger.debug("s7_event_dispatched", event_type=event_type, topic=topic)
```

**Also update `main.py` to complete worker registration (all 8 workers now available):**

```python
# Update services/knowledge-graph/src/knowledge_graph/main.py lifespan
# Replace the _scheduler.start() stub with full worker registration:
from knowledge_graph.application.workers.confidence_recomputation import ConfidenceRecomputationWorker
from knowledge_graph.application.workers.contradiction_batch import ContradictionBatchWorker
from knowledge_graph.application.workers.summary_generation import SummaryGenerationWorker
from knowledge_graph.application.workers.entity_profile_embedding import EntityProfileEmbeddingWorker
from knowledge_graph.application.workers.relation_summary_embedding import RelationSummaryEmbeddingWorker
from knowledge_graph.application.workers.relation_evidence_embedding import RelationEvidenceEmbeddingWorker
from knowledge_graph.application.workers.monthly_partition import MonthlyPartitionWorker
from knowledge_graph.application.workers.yearly_partition import YearlyPartitionWorker

# Wire all 8 workers (dependencies injected via session factory)
_scheduler.register_workers(
    confidence_worker=ConfidenceRecomputationWorker(...),
    contradiction_batch_worker=ContradictionBatchWorker(...),
    summary_worker=SummaryGenerationWorker(...),
    entity_profile_worker=EntityProfileEmbeddingWorker(...),
    relation_summary_embedding_worker=RelationSummaryEmbeddingWorker(...),
    evidence_embedding_worker=RelationEvidenceEmbeddingWorker(...),
    monthly_partition_worker=monthly,  # already created for startup run
    yearly_partition_worker=yearly,    # already created for startup run
)
_scheduler.start()
```

### T-S7-016: Block 14 Design Memo (documentation only — no code)

Create `services/knowledge-graph/docs/block14-shadow-migration-design.md` with content exactly as specified in Section 6 of the planning response (`0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`):

- 4 phases: shadow column add, dual write, backfill, cutover+cleanup
- Config settings: `BLOCK14_SHADOW_MIGRATION_ENABLED=false`, etc.
- Design decisions: why shadow columns over blue-green
- Explicitly marked DEFERRED — no implementation code in this document or any code file

---

## Constraints

- T-S7-010: HNSW partial index predicate for summaries: `WHERE expires_at IS NULL OR expires_at > now()` — this must match the intelligence-migrations index definition exactly; add a code comment
- T-S7-011: batch size ≤ 32; process 200 rows max per run
- T-S7-012 + T-S7-013: use `IF NOT EXISTS` — running twice MUST NOT error
- T-S7-012 + T-S7-013: use raw SQL via `sqlalchemy.text()` — no ORM DDL helpers
- T-S7-015: `entity.dirtied` events MUST NOT be routed through outbox; log warning if they appear
- T-S7-015: `intelligence.contradiction.v1` keyed by `subject_entity_id`; `graph.state.changed.v1` keyed by `relation_id`
- T-S7-016: DESIGN MEMO ONLY — no code written, no implementation tasks created
- After this wave: update `main.py` to register all 8 workers — the scheduler scaffold from Wave 07 has stub workers; replace with real implementations
- structlog only; UTC datetimes only
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.
- **`EntityId` for cross-service entity references**: S7 graph writes use `common.types.EntityId` for `subject_entity_id`, `object_entity_id`, and `entity_id` columns.

---

## Scope & token budget

**Write paths:**
```
services/knowledge-graph/src/knowledge_graph/application/workers/relation_summary_embedding.py
services/knowledge-graph/src/knowledge_graph/application/workers/relation_evidence_embedding.py
services/knowledge-graph/src/knowledge_graph/application/workers/monthly_partition.py
services/knowledge-graph/src/knowledge_graph/application/workers/yearly_partition.py
services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/__init__.py
services/knowledge-graph/src/knowledge_graph/infrastructure/outbox/dispatcher.py
services/knowledge-graph/src/knowledge_graph/main.py  (update: full worker registration)
services/knowledge-graph/docs/block14-shadow-migration-design.md
services/knowledge-graph/tests/unit/workers/test_relation_summary_embedding.py
services/knowledge-graph/tests/unit/workers/test_relation_evidence_embedding.py
services/knowledge-graph/tests/unit/workers/test_monthly_partition.py
services/knowledge-graph/tests/unit/workers/test_yearly_partition.py
services/knowledge-graph/tests/unit/infrastructure/test_outbox_dispatcher.py
```

**Max exploration:** Wave 06–08 outputs. Do not read S6/S10.

**Stop condition:** All 6 tasks implemented, unit tests pass, ruff+mypy pass, main.py has all 8 workers registered.

---

## Required tests

```bash
cd services/knowledge-graph && pytest tests/unit/ -v
ruff check services/knowledge-graph/src/
mypy services/knowledge-graph/src/
```

**Pass criteria:**
- `test_relation_summary_embedding_only_current`: only `is_current=true` summaries embedded
- `test_relation_evidence_embedding_batch_size_32`: batch size never exceeds 32
- `test_monthly_partition_idempotent`: run twice → second run does not error
- `test_monthly_partition_creates_current_and_next`: current month + next month partitions created
- `test_yearly_partition_idempotent`: run twice → no error
- `test_outbox_dispatcher_entity_dirtied_not_routed`: entity.dirtied event in outbox → warning logged, not published
- `test_outbox_dispatcher_contradiction_keyed_by_subject`: intelligence.contradiction.v1 key = subject_entity_id
- `test_scheduler_has_8_jobs_after_full_registration`: all 8 workers registered in main.py lifespan

---

## Incremental quality gates (mandatory)

1. **T-S7-010 + T-S7-011:**
   ```bash
   pytest tests/unit/workers/test_relation_summary_embedding.py tests/unit/workers/test_relation_evidence_embedding.py -v
   ruff check src/knowledge_graph/application/workers/relation_summary_embedding.py src/knowledge_graph/application/workers/relation_evidence_embedding.py
   mypy src/knowledge_graph/application/workers/relation_summary_embedding.py
   ```

2. **T-S7-012 + T-S7-013:**
   ```bash
   pytest tests/unit/workers/test_monthly_partition.py tests/unit/workers/test_yearly_partition.py -v
   ruff check src/knowledge_graph/application/workers/monthly_partition.py src/knowledge_graph/application/workers/yearly_partition.py
   mypy src/knowledge_graph/application/workers/monthly_partition.py
   ```

3. **T-S7-015:**
   ```bash
   pytest tests/unit/infrastructure/test_outbox_dispatcher.py -v
   ruff check src/knowledge_graph/infrastructure/outbox/dispatcher.py
   mypy src/knowledge_graph/infrastructure/outbox/dispatcher.py
   ```

4. **main.py update:**
   ```bash
   pytest tests/unit/test_scheduler.py::test_scheduler_has_8_jobs_after_full_registration -v
   ruff check src/knowledge_graph/main.py
   mypy src/knowledge_graph/main.py
   ```

No deferred fixes.

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/knowledge-graph.md` | Worker schedule | Update worker table to include all 8 workers with intervals |
| `docs/services/knowledge-graph.md` | Outbox routing | Add outbox topic routing table (event_type → Kafka topic → key) |
| `docs/services/knowledge-graph.md` | Block 14 | Add reference to `docs/block14-shadow-migration-design.md`; mark DEFERRED |
| `services/knowledge-graph/docs/block14-shadow-migration-design.md` | New file | Full 4-phase design memo (see planning response Section 6) |

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/unit/workers/test_monthly_partition.py::test_monthly_partition_idempotent` | T-S7-012 | 0 | Pass |
| `pytest tests/unit/infrastructure/test_outbox_dispatcher.py::test_outbox_dispatcher_entity_dirtied_not_routed` | T-S7-015 critical | 0 | Pass |
| `pytest tests/unit/ -v` | All wave 09 | 0 | All pass |
| `ruff check src/` | Full wave 09 | 0 | No violations |
| `mypy src/` | Full wave 09 | 0 | No errors |
| `ls services/knowledge-graph/docs/block14-shadow-migration-design.md` | T-S7-016 | 0 | File exists |

### Commit message
```
feat(s7): add workers 13E-H, outbox dispatcher, Block 14 design memo

Add relation summary/evidence embedding workers (2h/3h intervals), idempotent
monthly/yearly partition workers (IF NOT EXISTS, runs at startup), outbox
dispatcher (3 topics, entity.dirtied.v1 excluded with warning), full 8-worker
registration in main.py, and Block 14 shadow migration 4-phase design memo
(DEFERRED — no implementation).
```

---

## Definition of done

- [ ] Worker 13E: only `is_current=true` summaries embedded; HNSW predicate comment present
- [ ] Worker 13F: batch size ≤ 32; 200-row max per run
- [ ] Worker 13G: IF NOT EXISTS; creates current+next month; runs at startup
- [ ] Worker 13H: IF NOT EXISTS; creates current+next year; runs at startup
- [ ] Outbox: 3 topics routed correctly; entity.dirtied.v1 logs warning if seen in outbox
- [ ] Outbox: contradiction keyed by subject_entity_id; graph.state.changed keyed by relation_id
- [ ] main.py: all 8 workers registered at startup
- [ ] Block 14: design memo created with 4 phases and config settings; explicitly marked DEFERRED
- [ ] All unit tests pass
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/knowledge-graph.md` updated: all 8 workers in schedule table, outbox routing table, Block 14 reference
