# Execution Prompt 0013 — Ingestion Pipeline v1: S6+S7+S10 Wave 13

**Wave:** 13 of 13 — FINAL WAVE
**Service:** S10 Alert Service
**Focus:** S10 API Surface + Health/Observability + Integration Tests + Full Pipeline PR
**Tasks:** T-S10-009, T-S10-010, T-S10-012
**Date:** 2026-03-22

---

## Context (read first)

- Planning response: `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md`
- Service doc: `docs/services/alert-service.md`
- S6 integration test results (Wave 05)
- S7 integration test results (Wave 10)

---

## Assigned agent profile(s)

- **backend-engineer** — T-S10-009 (API), T-S10-010 (health/metrics)
- **machine-learning-lead** — T-S10-012 (integration tests: full pipeline S4→S5→S6→S7→S10)

Both can work in parallel; T-S10-012 validates the complete surface.

---

## Mandatory pre-read

1. `docs/agents/AGENTS.md`
2. `docs/CLAUDE.md`
3. `docs/services/alert-service.md`
4. `docs/services/nlp-pipeline.md`
5. `docs/services/knowledge-graph.md`
6. All Wave 11–12 outputs (S10 complete codebase)
7. `docs/ai-interactions/agent-responses/0013-response-20260322-ingestion-pipeline-v1-s6-s7-s10.md` — task details T-S10-009, T-S10-010, T-S10-012
8. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)

---

## Objective

Complete S10 and validate the entire pipeline:
- **T-S10-009**: REST API — 3 endpoints (WS stream, GET pending, DELETE ack)
- **T-S10-010**: `/healthz`, `/readyz` (alert_db + Kafka + Valkey + S1 /health), 4 Prometheus metrics, `/admin/dlq`
- **T-S10-012**: Integration tests — 5 tests including full S7→S10 pipeline continuity; includes the full end-to-end PR description (M7 milestone)

This is the final wave. After Wave 13:
- S10 is complete and deployable
- Milestone M7 (full S4→S5→S6→S7→S10 pipeline validated) is achieved
- A comprehensive PR is created covering the entire prompt 0013 scope

---

## Task scope for this wave

### Parallel (T-S10-009 and T-S10-010); then T-S10-012

**T-S10-009: API Surface**
- `services/alert/src/alert_service/api/routes/alerts.py`
- (WebSocket already implemented in Wave 12 T-S10-006)

**T-S10-010: Health/Ready + Prometheus + DLQ**
- `services/alert/src/alert_service/api/routes/health.py`
- `services/alert/src/alert_service/api/routes/admin.py`
- `services/alert/src/alert_service/infrastructure/metrics.py`

**T-S10-012: Integration Tests**
- `services/alert/tests/integration/conftest.py`
- `services/alert/tests/integration/test_alert_pipeline.py`
- `services/alert/docker-compose.test.yml`

---

## Why this chunk

Waves 11–12 implemented all S10 processing logic. Wave 13 completes the service shell (API + health) and validates correctness end-to-end. T-S10-012 is the final integration test suite and includes the full pipeline test (S4→S5→S6→S7→S10), representing M7. The PR description generated in this wave covers the entirety of prompt 0013's scope.

---

## Implementation instructions

### T-S10-009: API Surface

```python
# services/alert/src/alert_service/api/routes/alerts.py
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from sqlalchemy import text

router = APIRouter(prefix="/api/v1")

@router.get("/alerts/pending")
async def get_pending_alerts(
    # user_id from authenticated request (JWT validation)
    user_id: str = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """
    List pending alerts for the authenticated user.
    Returns alerts not yet acknowledged.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT a.id, a.entity_id, a.alert_type, a.payload, a.created_at
                FROM pending_alerts pa
                JOIN alerts a ON pa.alert_id = a.id
                WHERE pa.user_id = :user_id
                ORDER BY a.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"user_id": user_id, "limit": limit, "offset": offset}
        )
        pending = [dict(row._mapping) for row in result]

    return {
        "user_id": user_id,
        "pending_alerts": pending,
        "count": len(pending),
        "offset": offset,
    }


@router.delete("/alerts/{alert_id}/ack", status_code=204)
async def acknowledge_alert(
    alert_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Acknowledge and remove a pending alert.
    Scoped to the authenticated user — cannot ack another user's alerts.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                DELETE FROM pending_alerts
                WHERE alert_id = :alert_id AND user_id = :user_id
                RETURNING id
            """),
            {"alert_id": alert_id, "user_id": user_id}
        )
        deleted = result.fetchone()

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found or does not belong to user"
        )
    # 204 No Content


async def get_current_user(authorization: str = Header(None)) -> str:
    """
    Stub: extract user_id from Authorization Bearer token.
    In production: validate JWT and return sub claim.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    # Stub: return token as user_id (replace with real JWT validation)
    return token
```

### T-S10-010: Health/Ready + Prometheus + DLQ

```python
# services/alert/src/alert_service/infrastructure/metrics.py
from prometheus_client import Counter, Gauge

s10_alerts_fanned_out_total = Counter(
    "s10_alerts_fanned_out_total",
    "Alerts fanned out to users",
    ["type"],  # SIGNAL_DETECTED, GRAPH_CHANGED, CONTRADICTION_DETECTED
)
s10_alerts_deduplicated_total = Counter(
    "s10_alerts_deduplicated_total",
    "Alerts suppressed by dedup window",
)
s10_alerts_pending_total = Gauge(
    "s10_alerts_pending_total",
    "Current count of unacknowledged pending alerts",
)
s10_websocket_pushes_total = Counter(
    "s10_websocket_pushes_total",
    "Successful WebSocket alert pushes",
)
```

```python
# services/alert/src/alert_service/api/routes/health.py
from fastapi import APIRouter, Response
from sqlalchemy import text
from alert_service.infrastructure.alert_db.session import AsyncSessionLocal
from alert_service.infrastructure.s1_client.client import S1Client
from alert_service.config import settings
import asyncio

router = APIRouter()

@router.get("/healthz")
async def liveness():
    """Liveness — never checks dependencies."""
    return {"status": "ok"}

@router.get("/readyz")
async def readiness(response: Response):
    """
    Readiness — checks 4 dependencies:
    1. alert_db (SELECT 1)
    2. Kafka consumer has partition assignment
    3. Valkey (PING)
    4. S1 /health (critical — S10 cannot function without S1)
    """
    failing = []

    # 1. alert_db
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        failing.append("alert_db")

    # 2. Kafka assignment
    from alert_service.application.consumers.intelligence_consumer import _consumer_instance
    if _consumer_instance is None or not _consumer_instance.assignment():
        failing.append("kafka_assignment")

    # 3. Valkey
    try:
        import redis.asyncio as redis_async
        async with asyncio.timeout(1.0):
            r = redis_async.from_url(settings.VALKEY_URL)
            await r.ping()
            await r.aclose()
    except Exception:
        failing.append("valkey")

    # 4. S1 health (deployment gate — S10 cannot start without S1)
    s1 = S1Client()
    try:
        if not await s1.health_check():
            failing.append("s1_health")
    except Exception:
        failing.append("s1_health")
    finally:
        await s1.close()

    if failing:
        response.status_code = 503
        return {"status": "not_ready", "failing": failing}
    return {"status": "ready"}
```

```python
# services/alert/src/alert_service/api/routes/admin.py
from fastapi import APIRouter, Header, HTTPException
from alert_service.config import settings
from alert_service.infrastructure.alert_db.session import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter()

@router.get("/admin/dlq")
async def get_dlq(x_admin_token: str = Header(...)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, event_type, payload, created_at FROM outbox_events WHERE dispatched_at IS NULL ORDER BY created_at DESC LIMIT 100")
        )
        return {"dlq_entries": [dict(row._mapping) for row in result]}
```

### T-S10-012: Integration Tests

```yaml
# services/alert/docker-compose.test.yml
version: "3.9"
services:
  alert_db:
    image: postgres:16
    environment:
      POSTGRES_DB: alert_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5435:5432"

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    environment:
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_NODE_ID: 1
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
    ports:
      - "9093:9092"

  valkey:
    image: valkey/valkey:7.2
    ports:
      - "6381:6379"

  mock_s1:
    image: python:3.12-slim
    command: python -m uvicorn mock_s1:app --host 0.0.0.0 --port 8000
    environment:
      PYTHONPATH: /app
    volumes:
      - ./tests/integration/mock_s1.py:/app/mock_s1.py
    ports:
      - "8001:8000"
```

```python
# services/alert/tests/integration/mock_s1.py
"""Minimal mock S1 service for integration tests."""
from fastapi import FastAPI
app = FastAPI()

ENTITY_USERS = {
    "AAPL": ["user-1", "user-2"],
    "MSFT": ["user-3"],
}

@app.get("/internal/v1/watchlists/by-entity/{entity_id}")
async def get_by_entity(entity_id: str):
    return {"user_ids": ENTITY_USERS.get(entity_id, [])}

@app.post("/internal/v1/watchlists/by-entities")
async def get_by_entities(body: dict):
    return {eid: ENTITY_USERS.get(eid, []) for eid in body.get("entity_ids", [])}

@app.get("/internal/v1/health")
async def health():
    return {"status": "ok"}
```

```python
# services/alert/tests/integration/test_alert_pipeline.py
import pytest
import asyncio
import json
from uuid import uuid4

@pytest.mark.integration
async def test_watchlist_cache_invalidation(valkey_client, kafka_producer, watchlist_cache):
    """Publish watchlist.item_deleted → Valkey key for entity deleted."""
    entity_id = "AAPL"

    # Pre-populate cache
    await valkey_client.set(f"s10:v1:watchlist:by_entity:{entity_id}", '["user-1"]', ex=300)
    assert await valkey_client.exists(f"s10:v1:watchlist:by_entity:{entity_id}")

    # Publish watchlist.item_deleted event
    msg = json.dumps({
        "event_type": "watchlist.item_deleted",
        "entity_ids_affected": [entity_id],
        "user_id": "user-1",
    }).encode()
    await kafka_producer.send("portfolio.watchlist.updated.v1", value=msg)
    await asyncio.sleep(3)

    # Cache key should be deleted
    assert not await valkey_client.exists(f"s10:v1:watchlist:by_entity:{entity_id}")


@pytest.mark.integration
async def test_alert_fanout_end_to_end(alert_db_session, kafka_producer, mock_s1):
    """Mock S1 returns 2 users for AAPL → publish nlp.signal.detected.v1 → 2 alerts in alert_db."""
    entity_id = "AAPL"

    msg = json.dumps({
        "entity_id": entity_id,
        "signal_type": "price_momentum",
        "confidence": 0.92,
        "article_id": str(uuid4()),
    }).encode()
    await kafka_producer.send("nlp.signal.detected.v1", value=msg)
    await asyncio.sleep(5)

    # Assert 2 alerts created (one per user from mock S1)
    result = await alert_db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE entity_id = :eid AND alert_type = 'SIGNAL_DETECTED'"),
        {"eid": entity_id}
    )
    count = result.scalar()
    assert count == 2, f"Expected 2 alerts for {entity_id}, got {count}"


@pytest.mark.integration
async def test_dedup_within_window(alert_db_session, kafka_producer):
    """Same signal twice within 300s → only 1 alert per user; second suppressed."""
    entity_id = "MSFT"
    msg = json.dumps({
        "entity_id": entity_id,
        "signal_type": "earnings_signal",
        "confidence": 0.88,
        "article_id": str(uuid4()),
    }).encode()

    # Publish same signal twice
    await kafka_producer.send("nlp.signal.detected.v1", value=msg)
    await asyncio.sleep(2)
    await kafka_producer.send("nlp.signal.detected.v1", value=msg)
    await asyncio.sleep(3)

    result = await alert_db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE entity_id = :eid"),
        {"eid": entity_id}
    )
    count = result.scalar()
    assert count == 1, f"Dedup failed — got {count} alerts instead of 1"


@pytest.mark.integration
async def test_websocket_push_to_online_user(alert_service_client):
    """Connect WS as user-1 → trigger alert → assert WS message received."""
    import websockets

    received = []
    async with websockets.connect(
        f"ws://localhost:{alert_service_client.port}/api/v1/alerts/stream?token=user-1"
    ) as ws:
        # Trigger an alert in background
        asyncio.create_task(trigger_alert("AAPL", "SIGNAL_DETECTED"))

        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            received.append(json.loads(msg))
        except asyncio.TimeoutError:
            pass

    assert len(received) == 1
    assert received[0]["alert_type"] == "SIGNAL_DETECTED"
    assert received[0]["entity_id"] == "AAPL"


@pytest.mark.integration
async def test_s7_s10_pipeline_continuity(kafka_producer, alert_db_session, kafka_consumer):
    """
    Publish graph.state.changed.v1 for AAPL → S10 processes → alert in alert_db.
    This validates the S7→S10 boundary.
    """
    entity_id = "AAPL"
    msg = json.dumps({
        "subject_entity_id": entity_id,
        "object_entity_id": str(uuid4()),
        "relation_type_str": "CEO_OF",
        "confidence": 0.87,
        "relation_id": str(uuid4()),
    }).encode()

    await kafka_producer.send("graph.state.changed.v1", value=msg)
    await asyncio.sleep(5)

    result = await alert_db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE entity_id = :eid AND alert_type = 'GRAPH_CHANGED'"),
        {"eid": entity_id}
    )
    count = result.scalar()
    assert count >= 1, f"Expected alert for GRAPH_CHANGED event on {entity_id}, got {count}"
```

---

## Constraints

- T-S10-009: `/alerts/{id}/ack` scoped to user — cannot ack another user's alert; return 404 (not 403) on wrong user (info leak prevention)
- T-S10-009: `/alerts/pending` paginated; authenticated user only
- T-S10-010: `/readyz` checks all 4 deps including S1 /health — 503 if ANY fail
- T-S10-010: `/healthz` always 200 — never check deps in liveness
- T-S10-010: `s10_alerts_pending_total` is a Gauge (not Counter) — update it periodically
- T-S10-012: 5 integration tests; mock S1 service provides deterministic user lists
- PR description: must cover ALL 48 tasks across 13 waves (not just Wave 13)
- **`common.ids.new_uuid7()` mandatory** — all alert, pending-alert, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `EntityId` (from `common.types`) for watchlist entity_id keys; use `DocumentId` for any document references.
- **`EntityId` for fan-out**: S10 watchlist lookups use `common.types.EntityId` for entity_id keys.

---

## Scope & token budget

**Write paths:**
```
services/alert/src/alert_service/api/routes/alerts.py
services/alert/src/alert_service/api/routes/health.py
services/alert/src/alert_service/api/routes/admin.py
services/alert/src/alert_service/infrastructure/metrics.py
services/alert/tests/integration/conftest.py
services/alert/tests/integration/test_alert_pipeline.py
services/alert/tests/integration/mock_s1.py
services/alert/docker-compose.test.yml
```

**Stop condition:** All 3 tasks implemented; integration tests pass; ruff+mypy pass; PR created.

---

## Required tests

```bash
# Unit
cd services/alert && pytest tests/unit/ -v

# Contract
cd services/alert && pytest tests/contract/ -v

# Integration
cd services/alert && make test-integration

# Full S6+S7+S10
ruff check services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/
mypy services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/
```

**Pass criteria:**
- All 5 S10 integration tests pass
- /readyz returns 503 when mock S1 is down
- /ack returns 404 for wrong user (not 403)
- M7: S7→S10 pipeline continuity test passes (`graph.state.changed.v1` → alert in alert_db)

---

## Incremental quality gates (mandatory)

1. **T-S10-009:**
   ```bash
   pytest tests/unit/api/test_alerts.py -v
   ruff check src/alert_service/api/routes/alerts.py
   mypy src/alert_service/api/routes/alerts.py
   ```

2. **T-S10-010:**
   ```bash
   pytest tests/unit/api/test_health.py -v
   ruff check src/alert_service/api/routes/health.py src/alert_service/infrastructure/metrics.py
   mypy src/alert_service/infrastructure/metrics.py
   ```

3. **T-S10-012:**
   ```bash
   make test-integration
   ```

---

## Documentation requirements

| File | Update | Action |
|------|--------|--------|
| `docs/services/alert-service.md` | API reference | Add 3-endpoint table (WS stream, GET pending, DELETE ack) with auth requirements |
| `docs/services/alert-service.md` | Metrics | Add 4-metric table (name, type, labels, description) |
| `docs/services/alert-service.md` | Readiness | Document 4 readiness checks; explain S1 as deployment gate |
| `docs/services/alert-service.md` | Common pitfalls | Add: (1) /ack returns 404 not 403 on wrong user; (2) pending gauge must be updated periodically; (3) WS single-replica constraint |

**All 8 documentation quality criteria applied to final docs/services/alert-service.md:**
1. Accuracy — every endpoint, param, config matches implementation
2. Diagrams — Mermaid fan-out sequence diagram (from Wave 12)
3. Realistic examples — complete curl examples for /alerts/pending and /ack
4. Abstract methods — ConnectionManager.push() documented (when called, must do, returns)
5. Common pitfalls — ≥3 (see above)
6. Lib docs — N/A (no ml-clients surface changes in S10)
7. Service docs — alert-service.md complete and accurate
8. No orphan docs — no unreferenced documents

---

## Required handoff evidence — FINAL WAVE

### Changed files (complete S10 list)
All files created in Waves 11–13.

### Test results
```
pytest tests/unit/ tests/contract/ -v — PASS
make test-integration — PASS (5 integration tests)
ruff check services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/ — exit 0
mypy services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/ — exit 0
```

### Validation ledger

| Command | Scope | Exit code | Result |
|---------|-------|-----------|--------|
| `pytest tests/integration/test_alert_pipeline.py::test_s7_s10_pipeline_continuity -m integration` | M7 milestone | 0 | Pass |
| `pytest tests/integration/test_alert_pipeline.py -m integration` | All S10 integration | 0 | 5 tests pass |
| `pytest tests/unit/ tests/contract/ -v` | All S10 unit+contract | 0 | All pass |
| `ruff check services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/` | Full S6+S7+S10 | 0 | No violations |
| `mypy services/nlp-pipeline/src/ services/knowledge-graph/src/ services/alert/src/` | Full S6+S7+S10 | 0 | No errors |

### Commit message (Wave 13)
```
feat(s10): add REST API, health probes, Prometheus metrics, and integration tests

Complete S10 Alert Service with GET /alerts/pending, DELETE /alerts/{id}/ack,
/healthz+/readyz (4 deps including S1 deployment gate), 4 Prometheus metrics,
/admin/dlq, and 5 integration tests (cache invalidation, fan-out end-to-end,
dedup, WebSocket push, S7→S10 continuity validating M7 milestone).
```

---

## Pull Request Description (FINAL WAVE — full scope)

```markdown
## feat: Ingestion Pipeline v1 — S6 NLP Pipeline + S7 Knowledge Graph + S10 Alert Service

Implements prompt 0013: 48 tasks across 13 waves delivering the intelligence
enrichment arm of the Worldview ingestion pipeline.

### Services delivered

**S6 NLP Pipeline** (`services/nlp-pipeline/`)
- 10-block processing chain: sectioning → GLiNER NER → routing (7-signal) → suppression → embeddings → novelty gate → entity resolution (4-step) → LLM extraction
- GLiNER NER with NMS (IoU>0.5) and OOM retry; zero mentions never suppresses
- asyncio.Semaphore backpressure (MAX_OLLAMA_QUEUE_DEPTH=20)
- intelligence_db adapter with ALEMBIC_ENABLED=false guard
- Outbox: nlp.article.enriched.v1, nlp.signal.detected.v1 (confidence≥0.80)
- 6 REST endpoints; /healthz + /readyz (4 deps); 7 Prometheus metrics; /admin/dlq

**S7 Knowledge Graph** (`services/knowledge-graph/`)
- Relation canonicalization (exact/soft-map/propose-no-fail)
- Graph materialization with advisory lock; partition_key excluded from INSERTs
- Contradiction detection (subject-based, 90-day window, opposite polarity)
- 8 APScheduler workers: confidence (15min), contradiction batch (30min), summary (60min), entity embedding (60min), relation summary embedding (2h), evidence embedding (3h), monthly partition, yearly partition
- Confidence formula: sum(w_i·s_i)/sum(temporal_weight) + corroboration(≤0.20) - contradiction_penalty(≤0.60); clamp to [0,1]
- entity.dirtied.v1 produced directly (compacted topic, no outbox)
- 3 REST endpoints; /healthz + /readyz; 6 Prometheus metrics

**S10 Alert Service** (`services/alert/`)
- 2 consumer groups: 3 intelligence topics + 1 watchlist topic
- Alert fan-out with single-transaction write (alerts + pending + outbox + dedup)
- SHA-256 dedup window (user_id + entity_id + alert_type + window_bucket)
- WebSocket push (post-commit, best-effort)
- Watchlist cache invalidation on item_deleted (TTL=300s)
- S1 deployment gate: /readyz checks S1 /health; 3 contract tests via pytest-httpserver
- alert.delivered.v1 via outbox

### Architectural invariants enforced
- S6/S7: ALEMBIC_ENABLED=false → RuntimeError at import time
- S6/S7: intelligence_db DDL owned by intelligence-migrations (never by services)
- S7: partition_key is STORED column — never in INSERT
- S7: confidence always in [0.0, 1.0] — clamp() mandatory
- S6: zero NER mentions never suppresses document
- S10: all 4 alert_db writes in ONE transaction

### Milestones achieved
- M1: S6 NER + routing operational
- M2: S6 embeddings + entity resolution operational
- M3: S6 emitting nlp.article.enriched.v1 + nlp.signal.detected.v1
- M4: S7 graph writes + contradiction detection operational
- M5: S7 confidence + summaries + embeddings updating on schedule
- M6: S10 alert fan-out flowing for watchlist-registered entities
- M7: Full S4→S5→S6→S7→S10 pipeline validated in integration tests

### Test coverage
- S6: 4 integration tests (full pipeline, zero NER, backpressure, idempotency)
- S7: 7 integration tests (upsert idempotency, contradiction round-trip, confidence formula, Valkey dedup, ALEMBIC guard, partition existence, S6→S7 continuity)
- S10: 5 integration tests (cache invalidation, fan-out, dedup, WebSocket push, S7→S10 continuity)
- S10: 3 contract tests for S1 endpoint shapes (pytest-httpserver)

### Deferred work
- Block 14 shadow migration: design memo created at `services/knowledge-graph/docs/block14-shadow-migration-design.md`; implementation deferred
- S10 multi-replica WebSocket: single-replica constraint documented; Valkey pub/sub enhancement deferred
- S1 endpoints: S1 team notified via `services/alert/docs/s1-contract-testing.md`

🤖 Generated with Claude Code (claude-sonnet-4-6)
```

---

## Definition of done — FINAL WAVE

- [ ] T-S10-009: /alerts/pending authenticated, paginated; /ack scoped to user (404 not 403 on wrong user)
- [ ] T-S10-010: /healthz always 200; /readyz checks all 4 deps including S1; 4 metrics defined; /admin/dlq auth enforced
- [ ] T-S10-012: 5 integration tests pass; mock S1 service in docker-compose; M7 test passes
- [ ] Full pipeline ruff exits 0; mypy exits 0 for all 3 services
- [ ] `docs/services/alert-service.md` complete — all 8 documentation quality criteria satisfied
- [ ] PR description created covering all 48 tasks and 7 milestones
- [ ] Wave 13 commit created
- [ ] PR submitted via `gh pr create`
- [ ] S10 is complete — prompt 0013 is done
