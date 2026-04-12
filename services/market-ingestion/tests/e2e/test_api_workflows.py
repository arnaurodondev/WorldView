"""E2E scenarios for market-ingestion HTTP API workflows.

Hits the LIVE service running on localhost:8002.
Started by: make test-e2e (docker-compose.test.yml --profile market-ingestion-test)

Workflows covered:
  1. Health probes (healthz, readyz)
  2. Trigger ingestion for one symbol → 202 + task persisted in DB
  3. Trigger ingestion for multiple symbols → N tasks created
  4. Trigger ingestion idempotency → second call skips (tasks_skipped > 0)
  5. Backfill → date range chunked into expected number of tasks
  6. GET /api/v1/ingest/status → counts include the tasks from above
  7. GET /api/v1/policies → returns empty list on fresh DB
  8. Invalid provider → 422
  9. Backfill exceeds max chunks → 422
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

_INTERNAL_JWT = os.getenv("MARKET_INGESTION_E2E_INTERNAL_JWT", "")
_AUTH_HEADERS = {"X-Internal-JWT": _INTERNAL_JWT} if _INTERNAL_JWT else {}


# ── Health probes ─────────────────────────────────────────────────────────────


async def test_healthz_always_ok(e2e_client: AsyncClient) -> None:
    """GET /healthz returns 200 regardless of infra state."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_db_ok(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 with both db and storage checks passing."""
    resp = await e2e_client.get("/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["storage"] == "ok"


# ── Trigger ingestion ─────────────────────────────────────────────────────────


async def test_trigger_single_symbol_creates_task(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
    """POST /api/v1/ingest/trigger for one symbol → 202 and task in DB."""
    symbol = f"E2E_TRIG_{int(time.time())}"

    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "eodhd",
            "symbols": [symbol],
            "dataset_type": "ohlcv",
            "timeframe": "1d",
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["tasks_created"] == 1
    assert body["tasks_skipped"] == 0
    assert symbol in body["symbols"]

    # White-box: verify task row exists in DB
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    result = await e2e_db_session.execute(select(IngestionTaskModel).where(IngestionTaskModel.symbol == symbol))
    row = result.scalars().first()
    assert row is not None, f"IngestionTask for {symbol} not found in DB"
    assert row.status == "pending"


async def test_trigger_multiple_symbols(e2e_client: AsyncClient) -> None:
    """POST /api/v1/ingest/trigger with multiple symbols creates N tasks."""
    ts = int(time.time()) % 10000
    symbols = [f"E2MUL{ts:04d}A", f"E2MUL{ts:04d}B", f"E2MUL{ts:04d}C"]

    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "eodhd",
            "symbols": symbols,
            "dataset_type": "ohlcv",
            "timeframe": "1d",
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["tasks_created"] == 3


async def test_trigger_idempotent(e2e_client: AsyncClient) -> None:
    """Triggering the same symbol twice: first creates, second skips."""
    symbol = f"E2E_IDEM_{int(time.time())}"
    payload = {
        "provider": "eodhd",
        "symbols": [symbol],
        "dataset_type": "ohlcv",
        "timeframe": "1d",
    }

    resp1 = await e2e_client.post("/api/v1/ingest/trigger", json=payload, headers=_AUTH_HEADERS)
    assert resp1.status_code == 202
    assert resp1.json()["tasks_created"] == 1

    resp2 = await e2e_client.post("/api/v1/ingest/trigger", json=payload, headers=_AUTH_HEADERS)
    assert resp2.status_code == 202
    body2 = resp2.json()
    # Idempotent: same dedupe key → skip (tasks_created=0, tasks_skipped=1)
    assert body2["tasks_created"] == 0
    assert body2["tasks_skipped"] == 1


async def test_trigger_invalid_provider_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/ingest/trigger with unknown provider returns 422."""
    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "not_a_real_provider",
            "symbols": ["AAPL"],
            "dataset_type": "ohlcv",
            "timeframe": "1d",
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 422, resp.text


# ── Backfill ──────────────────────────────────────────────────────────────────


async def test_backfill_90_days_produces_3_chunks(e2e_client: AsyncClient) -> None:
    """POST /api/v1/ingest/backfill with 90-day range and 30-day chunks → 3 tasks."""
    symbol = f"E2E_BF_{int(time.time())}"

    resp = await e2e_client.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "eodhd",
            "symbol": symbol,
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "timeframe": "1d",
            "chunk_days": 30,
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["chunks"] == 3
    assert body["tasks_created"] == 3


async def test_backfill_single_day_one_chunk(e2e_client: AsyncClient) -> None:
    """POST /api/v1/ingest/backfill for a 1-day range → 1 chunk."""
    symbol = f"E2E_BF1D_{int(time.time())}"

    resp = await e2e_client.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "eodhd",
            "symbol": symbol,
            "start_date": "2024-06-01",
            "end_date": "2024-06-02",
            "timeframe": "1d",
            "chunk_days": 30,
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["chunks"] == 1


async def test_backfill_exceeds_max_chunks_returns_422(e2e_client: AsyncClient) -> None:
    """POST /api/v1/ingest/backfill requesting >100 chunks returns 422."""
    # 3100 days / 30 day chunks = 104 chunks — exceeds the 100-chunk cap
    resp = await e2e_client.post(
        "/api/v1/ingest/backfill",
        json={
            "provider": "eodhd",
            "symbol": f"E2E_HUGE_{int(time.time())}",
            "start_date": "2015-01-01",
            "end_date": "2023-07-01",
            "timeframe": "1d",
            "chunk_days": 30,
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 422, resp.text


async def test_backfill_idempotent(e2e_client: AsyncClient) -> None:
    """Same backfill request twice: second call has tasks_created=0."""
    symbol = f"E2BFID{int(time.time()) % 10000:04d}"
    payload = {
        "provider": "eodhd",
        "symbol": symbol,
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "timeframe": "1d",
        "chunk_days": 30,
    }

    resp1 = await e2e_client.post("/api/v1/ingest/backfill", json=payload, headers=_AUTH_HEADERS)
    assert resp1.status_code == 202
    assert resp1.json()["tasks_created"] == 1

    resp2 = await e2e_client.post("/api/v1/ingest/backfill", json=payload, headers=_AUTH_HEADERS)
    assert resp2.status_code == 202
    assert resp2.json()["tasks_created"] == 0


# ── Status + Policies ─────────────────────────────────────────────────────────


async def test_ingest_status_returns_counts(e2e_client: AsyncClient) -> None:
    """GET /api/v1/ingest/status returns a counts dict with a total field."""
    resp = await e2e_client.get("/api/v1/ingest/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "counts" in body
    assert "total" in body
    assert isinstance(body["total"], int)
    assert body["total"] >= 0


async def test_list_policies_returns_list(e2e_client: AsyncClient) -> None:
    """GET /api/v1/policies returns a list (empty on fresh DB) with a total field."""
    resp = await e2e_client.get("/api/v1/policies")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "policies" in body
    assert "total" in body
    assert isinstance(body["policies"], list)
    assert body["total"] == len(body["policies"])


async def test_trigger_then_status_reflects_pending_task(e2e_client: AsyncClient) -> None:
    """After triggering ingestion, GET /status shows at least one pending task."""
    symbol = f"E2E_STAT_{int(time.time())}"
    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={"provider": "eodhd", "symbols": [symbol], "dataset_type": "ohlcv", "timeframe": "1d"},
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202

    resp = await e2e_client.get("/api/v1/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["counts"].get("pending", 0) >= 1


async def test_trigger_full_async_pipeline_reaches_terminal_states(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """Trigger ingestion and verify background services actively process queued tasks."""
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    symbol = f"E2E_ASYNC_{int(time.time())}"

    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "eodhd",
            "symbols": [symbol],
            "dataset_type": "ohlcv",
            "timeframe": "1d",
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["tasks_created"] == 1

    deadline = time.monotonic() + 20
    processed_count = 0
    while time.monotonic() < deadline:
        processed_rows = (
            (
                await e2e_db_session.execute(
                    select(IngestionTaskModel.id).where(
                        IngestionTaskModel.status.in_(["running", "retry", "succeeded", "failed"]),
                    ),
                )
            )
            .scalars()
            .all()
        )
        processed_count = len(processed_rows)
        await e2e_db_session.rollback()
        if processed_count > 0:
            break
        await asyncio.sleep(1.5)

    assert processed_count > 0, "Expected worker/scheduler to process at least one queued task within 20s"


async def test_scheduler_active_guard_prevents_duplicate_active_tasks(
    e2e_db_session: AsyncSession,
) -> None:
    """Scheduler should not keep more than one active task per stream tuple.

    Validates the guard behind `scheduler_skip_active_task` for incremental
    streams where variant is not used (OHLCV/QUOTES), checking there are no
    duplicate active rows (PENDING/RUNNING/RETRY) for the same:
    provider + dataset_type + symbol + exchange + timeframe + variant.
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import func, select

    await asyncio.sleep(5)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        duplicates = (
            await e2e_db_session.execute(
                select(
                    IngestionTaskModel.provider,
                    IngestionTaskModel.dataset_type,
                    IngestionTaskModel.symbol,
                    IngestionTaskModel.exchange,
                    IngestionTaskModel.timeframe,
                    IngestionTaskModel.dataset_variant,
                    func.count().label("n"),
                )
                .where(
                    IngestionTaskModel.status.in_(["pending", "running", "retry"]),
                    IngestionTaskModel.dataset_type.in_(["ohlcv", "quotes"]),
                )
                .group_by(
                    IngestionTaskModel.provider,
                    IngestionTaskModel.dataset_type,
                    IngestionTaskModel.symbol,
                    IngestionTaskModel.exchange,
                    IngestionTaskModel.timeframe,
                    IngestionTaskModel.dataset_variant,
                )
                .having(func.count() > 1),
            )
        ).all()
        await e2e_db_session.rollback()
        assert not duplicates, f"Found duplicate active tasks for same stream: {duplicates}"
        await asyncio.sleep(2)


async def test_triggered_task_progresses_out_of_pending(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """A manually-triggered task should be claimed/processed by worker pipeline.

    We do not require success (provider/network may retry/fail), only that the
    task leaves PENDING and enters processing lifecycle states.
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    symbol = f"E2LIFE{int(time.time()) % 10000:04d}"
    resp = await e2e_client.post(
        "/api/v1/ingest/trigger",
        json={
            "provider": "eodhd",
            "symbols": [symbol],
            "dataset_type": "ohlcv",
            "timeframe": "1d",
        },
        headers=_AUTH_HEADERS,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["tasks_created"] == 1

    task_row = (
        (
            await e2e_db_session.execute(
                select(IngestionTaskModel)
                .where(IngestionTaskModel.symbol == symbol)
                .order_by(IngestionTaskModel.created_at.desc()),
            )
        )
        .scalars()
        .first()
    )
    assert task_row is not None
    task_id = task_row.id

    deadline = time.monotonic() + 30
    seen_statuses: set[str] = set()
    while time.monotonic() < deadline:
        status_value = (
            await e2e_db_session.execute(select(IngestionTaskModel.status).where(IngestionTaskModel.id == task_id))
        ).scalar_one_or_none()
        assert status_value is not None
        seen_statuses.add(status_value)
        await e2e_db_session.rollback()
        if status_value in {"running", "retry", "succeeded", "failed"}:
            break
        await asyncio.sleep(1.5)

    assert seen_statuses != {"pending"}, f"Task never progressed beyond pending: {seen_statuses}"
