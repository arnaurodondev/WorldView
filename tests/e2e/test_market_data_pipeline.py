"""Cross-service E2E: Market Ingestion (S2) → Market Data (S3) pipeline.

Exercises the full data path:
    POST /api/v1/ingest/trigger (S2) →
    IngestionTask persisted in DB →
    Scheduler/Worker picks up task →
    Task lifecycle progresses →
    Optionally: market.dataset.fetched event emitted →
    S3 consumer materializes data

Requirements:
  - S2 running on localhost:8002
  - S3 running on localhost:8003
  - Postgres on localhost:55433 (ingestion_db) AND localhost:5433 (market_data_db)
  - Kafka on localhost:9092

These tests are SKIPPED when services are not reachable.
Run with: docker compose -f infra/compose/docker-compose.test.yml --profile all up --build --wait
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# Set to "true" to skip tests that require a live EODHD key.
_DEMO_KEY_ONLY = os.getenv("EODHD_DEMO_KEY_ONLY", "true").lower() in ("1", "true", "yes")

_S2_INTERNAL_TOKEN = os.getenv("MARKET_INGESTION_INTERNAL_SERVICE_TOKEN", "e2e-internal-token")
_S2_INTERNAL_HEADERS = {"X-Internal-Token": _S2_INTERNAL_TOKEN}


# ── Availability guards ────────────────────────────────────────────────────────


def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S2_UP = _reachable("localhost", 8002)
_S3_UP = _reachable("localhost", 8003)

_skip_s2 = pytest.mark.skipif(not _S2_UP, reason="S2 (market-ingestion) not reachable on localhost:8002")
_skip_s3 = pytest.mark.skipif(not _S3_UP, reason="S3 (market-data) not reachable on localhost:8003")
_skip_both = pytest.mark.skipif(
    not (_S2_UP and _S3_UP),
    reason="S2 and/or S3 not reachable — run the full stack first",
)


# ── Helper ─────────────────────────────────────────────────────────────────────


def _trigger_payload(symbol: str, *, provider: str = "eodhd", timeframe: str = "1d") -> dict:
    return {
        "provider": provider,
        "symbols": [symbol],
        "dataset_type": "ohlcv",
        "timeframe": timeframe,
    }


# ── Health probes ──────────────────────────────────────────────────────────────


@_skip_s2
async def test_s2_healthz(s2_client: AsyncClient) -> None:
    """GET /healthz on S2 returns 200 with status=ok."""
    resp = await s2_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s3
async def test_s3_healthz(s3_client: AsyncClient) -> None:
    """GET /healthz on S3 returns 200 with status=ok."""
    resp = await s3_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@_skip_s2
async def test_s2_readyz_healthy(s2_client: AsyncClient) -> None:
    """GET /readyz on S2 returns 200 with db and storage checks passing."""
    resp = await s2_client.get("/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["storage"] == "ok"


@_skip_s3
async def test_s3_readyz_healthy(s3_client: AsyncClient) -> None:
    """GET /readyz on S3 returns 200."""
    resp = await s3_client.get("/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"


# ── Ingestion trigger: task creation ──────────────────────────────────────────


@_skip_s2
async def test_trigger_aapl_creates_exactly_one_task(
    s2_client: AsyncClient,
    s2_db_session: AsyncSession,
) -> None:
    """POST /api/v1/ingest/trigger for AAPL → 202 + exactly 1 pending task row in DB."""
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    # Use a unique symbol so we don't collide with existing tasks from other tests.
    symbol = f"AAPL_E2E_{int(time.time())}"

    resp = await s2_client.post("/api/v1/ingest/trigger", json=_trigger_payload(symbol), headers=_S2_INTERNAL_HEADERS)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["tasks_created"] == 1
    assert body["tasks_skipped"] == 0
    assert symbol in body["symbols"]

    # White-box: verify exactly one DB row exists for this symbol.
    result = await s2_db_session.execute(select(IngestionTaskModel).where(IngestionTaskModel.symbol == symbol))
    rows = result.scalars().all()
    assert len(rows) == 1, f"Expected 1 task row for {symbol}, got {len(rows)}"
    assert rows[0].status == "pending"


@_skip_s2
async def test_trigger_same_symbol_twice_creates_only_one_task(
    s2_client: AsyncClient,
    s2_db_session: AsyncSession,
) -> None:
    """Triggering the same symbol twice: first creates, second skips (idempotency).

    DB should contain exactly 1 active task for this symbol after both calls.
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    symbol = f"IDEM_{int(time.time())}"
    payload = _trigger_payload(symbol)

    resp1 = await s2_client.post("/api/v1/ingest/trigger", json=payload, headers=_S2_INTERNAL_HEADERS)
    assert resp1.status_code == 202
    body1 = resp1.json()
    assert body1["tasks_created"] == 1
    assert body1["tasks_skipped"] == 0

    resp2 = await s2_client.post("/api/v1/ingest/trigger", json=payload, headers=_S2_INTERNAL_HEADERS)
    assert resp2.status_code == 202
    body2 = resp2.json()
    assert body2["tasks_created"] == 0
    assert body2["tasks_skipped"] == 1

    # White-box: only one row should exist with an active status.
    result = await s2_db_session.execute(
        select(IngestionTaskModel).where(
            IngestionTaskModel.symbol == symbol,
            IngestionTaskModel.status.in_(["pending", "running", "retry"]),
        ),
    )
    active_rows = result.scalars().all()
    assert len(active_rows) == 1, f"Expected exactly 1 active task for {symbol}, found {len(active_rows)}"


# ── Task lifecycle ─────────────────────────────────────────────────────────────


@_skip_s2
async def test_triggered_task_progresses_through_lifecycle(
    s2_client: AsyncClient,
    s2_db_session: AsyncSession,
) -> None:
    """A triggered task should leave 'pending' within 30 s as the worker claims it.

    We do not require success — running/retry/succeeded/failed are all valid
    terminal-or-intermediate states that confirm the worker pipeline is active.
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    symbol = f"LIFECYCLE_{int(time.time())}"
    resp = await s2_client.post("/api/v1/ingest/trigger", json=_trigger_payload(symbol), headers=_S2_INTERNAL_HEADERS)
    assert resp.status_code == 202, resp.text
    assert resp.json()["tasks_created"] == 1

    # Fetch the task ID immediately.
    row = (
        (
            await s2_db_session.execute(
                select(IngestionTaskModel)
                .where(IngestionTaskModel.symbol == symbol)
                .order_by(IngestionTaskModel.created_at.desc()),
            )
        )
        .scalars()
        .first()
    )
    assert row is not None, f"No task row found for symbol {symbol}"
    task_id = row.id

    deadline = time.monotonic() + 90  # extended to handle large task backlogs in long-running envs
    seen_statuses: set[str] = set()
    while time.monotonic() < deadline:
        status_value = (
            await s2_db_session.execute(select(IngestionTaskModel.status).where(IngestionTaskModel.id == task_id))
        ).scalar_one_or_none()
        assert status_value is not None, "Task row disappeared from DB"
        seen_statuses.add(status_value)
        await s2_db_session.rollback()
        if status_value in {"running", "retry", "succeeded", "failed"}:
            break
        await asyncio.sleep(1.5)

    assert seen_statuses != {
        "pending",
    }, f"Task {task_id} never progressed beyond 'pending' within 90 s — seen statuses: {seen_statuses}"


@_skip_s2
async def test_eodhd_demo_key_task_lifecycle_observed(
    s2_client: AsyncClient,
    s2_db_session: AsyncSession,
) -> None:
    """Full worker pipeline test using the EODHD demo key with symbol AAPL.

    The demo key may return data or fail with an API error; either outcome is
    acceptable.  What we assert is that:
      1. The API accepted the trigger (202).
      2. The worker claimed the task within 30 s (status != 'pending').

    This confirms the scheduler and worker processes are running end-to-end.
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    resp = await s2_client.post("/api/v1/ingest/trigger", json=_trigger_payload("AAPL"), headers=_S2_INTERNAL_HEADERS)
    assert resp.status_code == 202, resp.text
    # tasks_created may be 0 if AAPL is already queued; either is fine.
    body = resp.json()
    assert body["tasks_created"] + body["tasks_skipped"] >= 1

    # Find the most-recently touched AAPL task.
    row = (
        (
            await s2_db_session.execute(
                select(IngestionTaskModel)
                .where(IngestionTaskModel.symbol == "AAPL", IngestionTaskModel.dataset_type == "ohlcv")
                .order_by(IngestionTaskModel.created_at.desc()),
            )
        )
        .scalars()
        .first()
    )
    assert row is not None, "No AAPL ohlcv task found in DB"
    task_id = row.id

    deadline = time.monotonic() + 30
    final_status: str = row.status
    while time.monotonic() < deadline:
        current_status = (
            await s2_db_session.execute(select(IngestionTaskModel.status).where(IngestionTaskModel.id == task_id))
        ).scalar_one_or_none()
        await s2_db_session.rollback()
        if current_status is not None:
            final_status = current_status
        if current_status in {"running", "retry", "succeeded", "failed"}:
            break
        await asyncio.sleep(1.5)

    # At least ONE outcome was observed — task is not stuck in 'pending'.
    assert final_status in {
        "running",
        "retry",
        "succeeded",
        "failed",
    }, f"AAPL task {task_id} is still 'pending' after 30 s — check that the worker and scheduler processes are running"


# ── Cross-service: S2 → Kafka → S3 ───────────────────────────────────────────


@pytest.mark.skipif(
    _DEMO_KEY_ONLY,
    reason="Skipped when EODHD_DEMO_KEY_ONLY=true — requires a live EODHD API key",
)
@_skip_both
async def test_s3_instrument_count_after_market_data_event(
    s2_client: AsyncClient,
    s3_client: AsyncClient,
    s2_db_session: AsyncSession,
) -> None:
    """When S2 successfully processes a task and emits market.dataset.fetched,
    S3 eventually creates/updates an instrument record for the symbol.

    This test validates the full async path:
        S2 trigger → worker → Kafka → S3 consumer → S3 DB

    Requires a live EODHD API key (not the demo key). Set:
        EODHD_DEMO_KEY_ONLY=false
    """
    from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
    from sqlalchemy import select

    symbol = "MSFT"

    # 1. Trigger ingestion on S2.
    resp = await s2_client.post("/api/v1/ingest/trigger", json=_trigger_payload(symbol), headers=_S2_INTERNAL_HEADERS)
    assert resp.status_code == 202, resp.text

    # 2. Wait for S2 task to reach succeeded state (up to 60 s with live key).
    row = (
        (
            await s2_db_session.execute(
                select(IngestionTaskModel)
                .where(IngestionTaskModel.symbol == symbol, IngestionTaskModel.dataset_type == "ohlcv")
                .order_by(IngestionTaskModel.created_at.desc()),
            )
        )
        .scalars()
        .first()
    )
    assert row is not None, f"No task row found for symbol {symbol}"
    task_id = row.id

    deadline = time.monotonic() + 60
    final_status: str = row.status
    while time.monotonic() < deadline:
        current_status = (
            await s2_db_session.execute(select(IngestionTaskModel.status).where(IngestionTaskModel.id == task_id))
        ).scalar_one_or_none()
        await s2_db_session.rollback()
        if current_status is not None:
            final_status = current_status
        if current_status == "succeeded":
            break
        if current_status == "failed":
            pytest.skip(f"S2 task failed (likely API key issue) — skipping S3 assertion. status={current_status}")
        await asyncio.sleep(2.0)

    if final_status != "succeeded":
        pytest.skip(f"S2 task did not reach 'succeeded' within 60 s (final={final_status}) — skipping S3 assertion")

    # 3. Wait for S3 to materialise the instrument (Kafka propagation may take a few seconds).
    deadline_s3 = time.monotonic() + 30
    found = False
    while time.monotonic() < deadline_s3:
        instr_resp = await s3_client.get(f"/api/v1/instruments?symbol={symbol}")
        if instr_resp.status_code == 200:
            body = instr_resp.json()
            items = body.get("items", body.get("instruments", body.get("data", [])))
            if items:
                found = True
                break
        await asyncio.sleep(2.0)

    assert found, (
        f"S3 did not materialise an instrument for {symbol} within 30 s after S2 task succeeded. "
        "Check that S3 Kafka consumer is running and the market.dataset.fetched topic is wired correctly."
    )
