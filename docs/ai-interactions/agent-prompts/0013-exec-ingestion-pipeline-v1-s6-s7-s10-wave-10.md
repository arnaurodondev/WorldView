# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 10

**Wave:** 10 of 13
**Service:** S7 Knowledge Graph
**Focus:** S7 API Surface + Health/Observability + Integration Tests
**Tasks:** T-S7-017, T-S7-018, T-S7-019
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/knowledge-graph.md`

---

## Assigned agent profile(s)

- **backend-engineer** — T-S7-017 (API), T-S7-018 (health/metrics/DLQ)
- **rag-knowledge-graph-engineer** — T-S7-019 (integration tests: graph upsert, contradiction, confidence formula)

T-S7-017 and T-S7-018 can be done in parallel; T-S7-019 validates the complete S7 surface.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/knowledge-graph.md`
4. All Wave 06–09 outputs (all S7 code)
5. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S7-017, T-S7-018, T-S7-019
6. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

Complete S7 as a fully deployable service:
- **T-S7-017**: REST API — 3 endpoints (entity graph, relations list, graph stats); `summary_authority()` computed at query time
- **T-S7-018**: `/healthz`, `/readyz` (intelligence_db + Kafka), 6 Prometheus metrics, `/admin/dlq`
- **T-S7-019**: Integration tests — graph upsert idempotency, contradiction round-trip, confidence formula, Valkey dedup, ALEMBIC_ENABLED=false, partition existence, S6→S7 pipeline continuity

After Wave 10, S7 is complete and S10 (Wave 11) may begin.

---

## Task scope for this wave

### Parallel (T-S7-017 and T-S7-018); then T-S7-019

**T-S7-017: API Surface**
- `services/knowledge-graph/src/knowledge_graph/api/routes/graph.py`

**T-S7-018: Health/Ready + Prometheus + DLQ**
- `services/knowledge-graph/src/knowledge_graph/api/routes/health.py` (finalize)
- `services/knowledge-graph/src/knowledge_graph/api/routes/admin.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics.py`

**T-S7-019: Integration Tests**
- `services/knowledge-graph/tests/integration/conftest.py`
- `services/knowledge-graph/tests/integration/test_graph.py`
- `services/knowledge-graph/docker-compose.test.yml`

---

## Why this chunk

Waves 06–09 implemented all S7 processing logic. Wave 10 adds the service shell and validates correctness end-to-end. T-S7-019 depends on all S7 code being available (cannot test entity graph endpoint until API is implemented, cannot test S6→S7 pipeline until consumer and blocks are in place). Wave 10 is the S7 completion milestone (M4+M5) and the gate before S10 begins.

---

## Implementation instructions

### T-S7-017: API Surface

#### CRITICAL: summary_authority() computed at query time — NOT cached

```python
# services/knowledge-graph/src/knowledge_graph/api/routes/graph.py
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from sqlalchemy import text

router = APIRouter(prefix="/api/v1")

@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(
    entity_id: str,
    min_confidence: float = Query(0.3, ge=0.0, le=1.0),
    limit: int = Query(50, le=200),
):
    """
    Entity's relations with confidence >= min_confidence.
    summary_authority() is computed at query time — NOT a cached column.
    """
    async with IntelligenceSession() as session:
        result = await session.execute(
            text("""
                SELECT
                    r.id AS relation_id,
                    r.confidence,
                    r.semantic_mode,
                    rtr.relation_type_str,
                    subj.canonical_name AS subject_name,
                    obj.canonical_name AS object_name,
                    rs.summary_text,
                    -- summary_authority() computed at query time:
                    CASE
                        WHEN rs.is_current AND rs.embedding IS NOT NULL THEN 'high'
                        WHEN rs.is_current THEN 'medium'
                        ELSE 'low'
                    END AS summary_authority
                FROM relations r
                JOIN relation_type_registry rtr ON r.relation_type_id = rtr.id
                JOIN canonical_entities subj ON r.subject_entity_id = subj.id
                JOIN canonical_entities obj ON r.object_entity_id = obj.id
                LEFT JOIN relation_summaries rs ON rs.relation_id = r.id AND rs.is_current = true
                WHERE r.subject_entity_id = :entity_id
                  AND r.confidence >= :min_conf
                ORDER BY r.confidence DESC
                LIMIT :limit
            """),
            {
                "entity_id": entity_id,
                "min_conf": min_confidence,
                "limit": limit,
            }
        )
        relations = [dict(row._mapping) for row in result]

    if not relations and await _entity_exists(entity_id) is False:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    return {"entity_id": entity_id, "relations": relations, "count": len(relations)}


@router.get("/relations")
async def list_relations(
    subject_entity_id: Optional[str] = Query(None),
    relation_type: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """Paginated list of relations with optional filters."""
    async with IntelligenceSession() as session:
        filters = ["r.confidence >= :min_conf"]
        params = {"min_conf": min_confidence, "limit": limit, "offset": offset}

        if subject_entity_id:
            filters.append("r.subject_entity_id = :subject_entity_id")
            params["subject_entity_id"] = subject_entity_id
        if relation_type:
            filters.append("rtr.relation_type_str = :relation_type")
            params["relation_type"] = relation_type

        where_clause = " AND ".join(filters)
        result = await session.execute(
            text(f"""
                SELECT r.id, r.subject_entity_id, r.object_entity_id,
                       r.confidence, r.semantic_mode,
                       rtr.relation_type_str
                FROM relations r
                JOIN relation_type_registry rtr ON r.relation_type_id = rtr.id
                WHERE {where_clause}
                ORDER BY r.confidence DESC
                LIMIT :limit OFFSET :offset
            """),
            params
        )
        relations = [dict(row._mapping) for row in result]

    return {"relations": relations, "count": len(relations), "offset": offset}


@router.get("/graph/stats")
async def get_graph_stats():
    """Aggregate graph statistics."""
    async with IntelligenceSession() as session:
        result = await session.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM relations) AS total_relations,
                    (SELECT COUNT(*) FROM relation_evidence_raw) AS total_evidence,
                    (SELECT COUNT(*) FROM relation_contradiction_links) AS total_contradictions,
                    (SELECT AVG(confidence) FROM relations) AS avg_confidence
            """)
        )
        row = result.fetchone()

        type_breakdown = await session.execute(
            text("""
                SELECT rtr.relation_type_str, COUNT(*) AS count
                FROM relations r
                JOIN relation_type_registry rtr ON r.relation_type_id = rtr.id
                GROUP BY rtr.relation_type_str
                ORDER BY count DESC
                LIMIT 20
            """)
        )
        by_type = [{"relation_type": r.relation_type_str, "count": r.count} for r in type_breakdown]

    return {
        "total_relations": row.total_relations,
        "total_evidence": row.total_evidence,
        "total_contradictions": row.total_contradictions,
        "avg_confidence": float(row.avg_confidence or 0.0),
        "relations_by_type": by_type,
    }


async def _entity_exists(entity_id: str) -> bool:
    async with IntelligenceSession() as session:
        result = await session.execute(
            text("SELECT 1 FROM canonical_entities WHERE id = :id"),
            {"id": entity_id}
        )
        return result.fetchone() is not None
```

### T-S7-018: Health/Ready + Prometheus + DLQ

```python
# services/knowledge-graph/src/knowledge_graph/infrastructure/metrics.py
from prometheus_client import Counter, Gauge

s7_relations_upserted_total = Counter(
    "s7_relations_upserted_total",
    "Relations upserted in intelligence_db",
)
s7_evidence_appended_total = Counter(
    "s7_evidence_appended_total",
    "Evidence rows inserted",
)
s7_contradictions_detected_total = Counter(
    "s7_contradictions_detected_total",
    "Contradictions detected (hot path + batch)",
)
s7_confidence_recomputed_total = Counter(
    "s7_confidence_recomputed_total",
    "Relations whose confidence was recomputed",
)
s7_summaries_generated_total = Counter(
    "s7_summaries_generated_total",
    "Relation summaries generated by LLM",
)
s7_embeddings_refreshed_total = Counter(
    "s7_embeddings_refreshed_total",
    "Embeddings refreshed",
    ["worker"],  # entity_profile, relation_summary, relation_evidence
)
```

```python
# services/knowledge-graph/src/knowledge_graph/api/routes/health.py
from fastapi import APIRouter, Response
from sqlalchemy import text
from knowledge_graph.infrastructure.intelligence_db.session import IntelligenceSession
from knowledge_graph.main import _scheduler

router = APIRouter()

@router.get("/healthz")
async def liveness():
    """Liveness — never checks dependencies."""
    return {"status": "ok"}

@router.get("/readyz")
async def readiness(response: Response):
    """
    Readiness — checks intelligence_db and Kafka assignment.
    """
    failing = []

    # 1. intelligence_db
    try:
        async with IntelligenceSession() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        failing.append("intelligence_db")

    # 2. Kafka consumer assignment
    from knowledge_graph.application.consumers.nlp_enriched_consumer import _consumer_instance
    if _consumer_instance is None or not _consumer_instance.assignment():
        failing.append("kafka_assignment")

    if failing:
        response.status_code = 503
        return {"status": "not_ready", "failing": failing}
    return {"status": "ready"}
```

```python
# services/knowledge-graph/src/knowledge_graph/api/routes/admin.py
from fastapi import APIRouter, Header, HTTPException
from knowledge_graph.config import settings

router = APIRouter()

@router.get("/admin/dlq")
async def get_dlq(x_admin_token: str = Header(...)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Query intelligence_db DLQ table
    async with IntelligenceSession() as session:
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT id, topic, partition, offset, error, created_at FROM s7_dlq ORDER BY created_at DESC LIMIT 100")
        )
        return {"entries": [dict(row._mapping) for row in result]}

@router.delete("/admin/dlq/{dlq_id}")
async def delete_dlq_entry(dlq_id: str, x_admin_token: str = Header(...)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with IntelligenceSession() as session:
        from sqlalchemy import text
        await session.execute(text("DELETE FROM s7_dlq WHERE id = :id"), {"id": dlq_id})
        await session.commit()
    return {"deleted": dlq_id}
```

### T-S7-019: Integration Tests

```yaml
# services/knowledge-graph/docker-compose.test.yml
version: "3.9"
services:
  intelligence_db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: intelligence_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5434:5432"

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    environment:
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_NODE_ID: 1
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
    ports:
      - "9092:9092"

  valkey:
    image: valkey/valkey:7.2
    ports:
      - "6380:6379"

  intelligence_migrations:
    image: worldview/intelligence-migrations:latest
    depends_on:
      - intelligence_db
    environment:
      DATABASE_URL: postgresql://test:test@intelligence_db:5432/intelligence_test
```

```python
# services/knowledge-graph/tests/integration/test_graph.py
import pytest
import asyncio
import json
from uuid import uuid4

@pytest.mark.integration
async def test_graph_upsert_idempotency(intelligence_db_session, s7_consumer, kafka_producer):
    """Same triple upserted twice → one relation row; evidence appended both times."""
    subject_id = str(uuid4())
    object_id = str(uuid4())

    msg = json.dumps({
        "article_id": str(uuid4()),
        "relations": [{"subject_entity_id": subject_id, "object_entity_id": object_id,
                       "relation_type": "CEO_OF", "polarity": "positive",
                       "confidence": 0.9, "evidence_text": "John is CEO of Acme Corp."}],
        "claims": [],
    }).encode()

    # Produce same message twice
    await kafka_producer.send("nlp.article.enriched.v1", value=msg)
    await kafka_producer.send("nlp.article.enriched.v1", value=msg)
    await asyncio.sleep(5)

    # Assert: only 1 relation row (ON CONFLICT DO UPDATE)
    result = await intelligence_db_session.execute(
        text("SELECT COUNT(*) FROM relations WHERE subject_entity_id = :s AND object_entity_id = :o"),
        {"s": subject_id, "o": object_id}
    )
    assert result.scalar() == 1  # Idempotent upsert

    # Assert: 2 evidence rows (evidence is appended, not upserted)
    result = await intelligence_db_session.execute(
        text("SELECT COUNT(*) FROM relation_evidence_raw WHERE relation_id IN (SELECT id FROM relations WHERE subject_entity_id = :s)"),
        {"s": subject_id}
    )
    assert result.scalar() == 2


@pytest.mark.integration
async def test_contradiction_round_trip(intelligence_db_session, s7_consumer, kafka_producer, kafka_consumer):
    """Write two opposing claims → relation_contradiction_links created → intelligence.contradiction.v1 emitted."""
    subject_id = str(uuid4())

    # Claim 1: positive revenue guidance
    msg1 = json.dumps({
        "article_id": str(uuid4()),
        "relations": [],
        "claims": [{"subject_entity_id": subject_id, "claimer_entity_id": subject_id,
                    "claim_type": "revenue_guidance", "polarity": "positive", "confidence": 0.9}],
    }).encode()

    # Claim 2: negative revenue guidance (contradicts claim 1)
    msg2 = json.dumps({
        "article_id": str(uuid4()),
        "relations": [],
        "claims": [{"subject_entity_id": subject_id, "claimer_entity_id": subject_id,
                    "claim_type": "revenue_guidance", "polarity": "negative", "confidence": 0.85}],
    }).encode()

    await kafka_producer.send("nlp.article.enriched.v1", value=msg1)
    await kafka_producer.send("nlp.article.enriched.v1", value=msg2)
    await asyncio.sleep(10)  # Allow hot-path and outbox dispatch

    # Assert: contradiction link created
    result = await intelligence_db_session.execute(
        text("SELECT COUNT(*) FROM relation_contradiction_links WHERE subject_entity_id = :s"),
        {"s": subject_id}  # Note: will need to join on claims table
    )
    assert result.scalar() >= 1

    # Assert: intelligence.contradiction.v1 in Kafka
    msg = await wait_for_kafka_message("intelligence.contradiction.v1", subject_id, timeout=15)
    assert msg is not None


@pytest.mark.integration
async def test_confidence_formula_bounded(intelligence_db_session, s7_consumer, kafka_producer):
    """Multi-source evidence (3 different sources) → confidence in [0.0, 1.0]; corroboration ≤ 0.20."""
    subject_id = str(uuid4())
    object_id = str(uuid4())

    # 3 different sources
    for source in ["reuters", "bloomberg", "sec_edgar"]:
        msg = json.dumps({
            "article_id": str(uuid4()),
            "relations": [{"subject_entity_id": subject_id, "object_entity_id": object_id,
                           "relation_type": "CEO_OF", "polarity": "positive",
                           "confidence": 0.9, "evidence_text": f"Evidence from {source}",
                           "source_type": "news", "source_name": source}],
            "claims": [],
        }).encode()
        await kafka_producer.send("nlp.article.enriched.v1", value=msg)

    await asyncio.sleep(30)  # Wait for confidence recomputation (15min worker won't run; trigger manually)

    # Manually trigger confidence recomputation
    from knowledge_graph.application.workers.confidence_recomputation import ConfidenceRecomputationWorker
    worker = ConfidenceRecomputationWorker(...)
    await worker.run()

    result = await intelligence_db_session.execute(
        text("SELECT confidence FROM relations WHERE subject_entity_id = :s"),
        {"s": subject_id}
    )
    confidence = result.scalar()
    assert 0.0 <= confidence <= 1.0, f"Confidence out of bounds: {confidence}"


@pytest.mark.integration
async def test_entity_dirtied_valkey_dedup(valkey_client, entity_profile_worker):
    """entity.dirtied.v1 twice in 30min → embedding refresh runs only once."""
    entity_id = str(uuid4())

    call_count = 0
    original_refresh = entity_profile_worker._refresh_entity

    async def counting_refresh(eid):
        nonlocal call_count
        call_count += 1
        await original_refresh(eid)

    entity_profile_worker._refresh_entity = counting_refresh

    # Process same entity twice (Valkey lock should prevent second)
    await entity_profile_worker._refresh_entity(entity_id)
    await entity_profile_worker._refresh_entity(entity_id)

    assert call_count == 1, f"Expected 1 refresh, got {call_count} (Valkey dedup not working)"


@pytest.mark.integration
async def test_alembic_enabled_false_raises():
    """Starting S7 with ALEMBIC_ENABLED=true must raise RuntimeError."""
    import os
    os.environ["ALEMBIC_ENABLED"] = "true"
    try:
        import importlib
        import knowledge_graph.infrastructure.intelligence_db.session as mod
        importlib.reload(mod)
        assert False, "Expected RuntimeError not raised"
    except RuntimeError as e:
        assert "ALEMBIC_ENABLED" in str(e) or "must not run Alembic" in str(e)
    finally:
        os.environ.pop("ALEMBIC_ENABLED", None)


@pytest.mark.integration
async def test_partitions_exist_before_tests(intelligence_db_session):
    """Verify monthly partitions for current+next month exist (created by intelligence-migrations)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    tables = ["relation_evidence_raw", "claims"]
    for table in tables:
        partition_name = f"{table}_{now.year}_{now.month:02d}"
        result = await intelligence_db_session.execute(
            text("SELECT 1 FROM pg_tables WHERE tablename = :name"),
            {"name": partition_name}
        )
        assert result.fetchone(), f"Partition {partition_name} not found — intelligence-migrations may not have run"


@pytest.mark.integration
async def test_s6_s7_pipeline_continuity(kafka_producer, kafka_consumer):
    """Publish nlp.article.enriched.v1 → S7 processes → graph.state.changed.v1 emitted."""
    article_id = str(uuid4())
    msg = json.dumps({
        "article_id": article_id,
        "relations": [{"subject_entity_id": str(uuid4()), "object_entity_id": str(uuid4()),
                       "relation_type": "CEO_OF", "polarity": "positive",
                       "confidence": 0.9, "evidence_text": "Pipeline test evidence"}],
        "claims": [],
    }).encode()

    await kafka_producer.send("nlp.article.enriched.v1", value=msg)
    graph_changed = await wait_for_kafka_message("graph.state.changed.v1", None, timeout=30)
    assert graph_changed is not None
```

---

## Constraints

- T-S7-017: `summary_authority()` MUST be computed at query time in SQL — do NOT add a `summary_authority` column to any table
- T-S7-017: entity graph endpoint returns 404 for unknown entity_id; 200 with empty relations for known entity with no relations
- T-S7-018: `/healthz` always 200 (liveness); `/readyz` checks exactly intelligence_db + Kafka
- T-S7-018: 6 metrics exactly as specified; `s7_embeddings_refreshed_total` has label `worker`
- T-S7-019: all tests marked `@pytest.mark.integration`; intelligence-migrations init container must run before tests
- T-S7-019: confidence formula test must manually trigger worker run (not wait 15 minutes)
- T-S7-019: ALEMBIC_ENABLED=false test must clean up env var in finally block
- **`common.ids.new_uuid7()` mandatory** — all entity, section, chunk, relation, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for canonical entity references across S6, S7; use `DocumentId` for document references; use `MinIOKey` for MinIO key strings.
- **`EntityId` for cross-service entity references**: S7 graph writes use `common.types.EntityId` for `subject_entity_id`, `object_entity_id`, and `entity_id` columns.

---

## Scope & token budget

**Write paths:**
```
services/knowledge-graph/src/knowledge_graph/api/routes/graph.py
services/knowledge-graph/src/knowledge_graph/api/routes/health.py (finalize)
services/knowledge-graph/src/knowledge_graph/api/routes/admin.py
services/knowledge-graph/src/knowledge_graph/infrastructure/metrics.py (finalize all 6 metrics)
services/knowledge-graph/tests/integration/conftest.py
services/knowledge-graph/tests/integration/test_graph.py
services/knowledge-graph/docker-compose.test.yml
```

**Stop condition:** All tasks implemented; unit + integration tests pass; ruff+mypy pass; S7 complete.

---

## Required tests

```bash
# Unit
cd services/knowledge-graph && pytest tests/unit/ -v

# Integration
cd services/knowledge-graph && make test-integration

# Lint + types
ruff check services/knowledge-graph/src/
mypy services/knowledge-graph/src/
```

**Pass criteria:** All 7 integration tests pass; S7 is complete and emitting `graph.state.changed.v1`.

---

## Incremental quality gates (mandatory)

1. **T-S7-017:**
   ```bash
   pytest tests/unit/api/test_graph.py -v
   ruff check src/knowledge_graph/api/routes/graph.py
   mypy src/knowledge_graph/api/routes/graph.py
   ```

2. **T-S7-018:**
   ```bash
   pytest tests/unit/api/test_health.py -v
   ruff check src/knowledge_graph/api/routes/health.py src/knowledge_graph/infrastructure/metrics.py
   mypy src/knowledge_graph/infrastructure/metrics.py
   ```

3. **T-S7-019:**
   ```bash
   make test-integration
   ```

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/knowledge-graph.md` | API reference | Add 3-endpoint table (method, path, params, response shape) |
| `docs/services/knowledge-graph.md` | Metrics | Add 6-metric table (name, type, labels, description) |
| `docs/services/knowledge-graph.md` | summary_authority | Document computed-at-query-time pattern; note it is NOT a cached column |

---

## Required handoff evidence

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/integration/test_graph.py::test_graph_upsert_idempotency -m integration` | T-S7-019 | 0 | Pass |
| `pytest tests/integration/test_graph.py::test_contradiction_round_trip -m integration` | T-S7-019 | 0 | Pass |
| `pytest tests/integration/test_graph.py::test_alembic_enabled_false_raises -m integration` | T-S7-019 critical | 0 | Pass |
| `pytest tests/integration/test_graph.py::test_s6_s7_pipeline_continuity -m integration` | T-S7-019 | 0 | Pass |
| `pytest tests/unit/ -v` | All S7 unit | 0 | All pass |
| `ruff check src/` | Full S7 | 0 | No violations |
| `mypy src/` | Full S7 | 0 | No errors |

### Commit message
```
feat(s7): add REST API, health probes, Prometheus metrics, and integration tests

Complete S7 with 3 API endpoints (summary_authority computed at query time),
/healthz+/readyz (intelligence_db+Kafka), 6 Prometheus metrics, /admin/dlq,
and 7 integration tests (idempotency, contradiction round-trip, confidence
formula, Valkey dedup, ALEMBIC guard, partition existence, S6→S7 continuity).
```

---

## Definition of done

- [ ] API: `summary_authority` computed at query time in SQL (no cached column)
- [ ] API: entity graph 404 for unknown entity; stats endpoint returns all 4 aggregates
- [ ] Health: /healthz always 200; /readyz checks intelligence_db + Kafka
- [ ] Metrics: all 6 metrics defined; s7_embeddings_refreshed_total has `worker` label
- [ ] Admin: /admin/dlq 401 without X-Admin-Token
- [ ] Integration: all 7 tests pass; intelligence-migrations ran before test suite
- [ ] ruff exits 0; mypy exits 0
- [ ] `docs/services/knowledge-graph.md` final — all sections complete
- [ ] S7 is complete — Wave 11 (S10) may begin
