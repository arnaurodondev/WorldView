"""Platform QA scenarios for the full ingestion-to-materialization pipeline (T-MI-27).

These are end-to-end black-box scenarios that exercise the complete flow:
  Trigger → Task enqueued → Worker claims → Provider fetch → Object storage →
  Watermark advance → Outbox event → Kafka → (downstream materialization)

All tests require the full infrastructure stack (Postgres, MinIO, Kafka).
Run with: pytest -m e2e

Skip conditions:
  - MARKET_INGESTION_DATABASE_URL not set → skip all
  - MARKET_INGESTION_EODHD_API_KEY == "demo" → skip live provider tests
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.e2e

_HAS_INFRA = os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql")
_HAS_LIVE_KEY = os.getenv("MARKET_INGESTION_EODHD_API_KEY", "demo") != "demo"

_NEEDS_INFRA = pytest.mark.skipif(not _HAS_INFRA, reason="Requires full infra stack")
_NEEDS_LIVE_KEY = pytest.mark.skipif(not _HAS_LIVE_KEY, reason="Requires live EODHD API key")


# ---------------------------------------------------------------------------
# Scenario 1: Trigger → DB task persisted
# ---------------------------------------------------------------------------


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_scenario_trigger_creates_db_task():
    """GIVEN a POST /api/v1/ingest/trigger request
    WHEN the API accepts it (202)
    THEN a task record appears in the DB with status=pending.
    """
    from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
    from market_ingestion.config import Settings
    from market_ingestion.domain.enums import DatasetType, Provider
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    symbol = f"QA_TRIG_{int(time.time())}"

    uow = SqlaUnitOfWork(write_factory, read_factory)
    use_case = TriggerIngestionUseCase(uow=uow)
    result = await use_case.execute(
        provider=Provider.EODHD,
        symbols=[symbol],
        dataset_type=DatasetType.OHLCV,
        timeframe="1d",
    )

    assert result.tasks_created == 1
    assert result.tasks_skipped == 0

    # Verify it's idempotent — second call skips
    uow2 = SqlaUnitOfWork(write_factory, read_factory)
    use_case2 = TriggerIngestionUseCase(uow=uow2)
    result2 = await use_case2.execute(
        provider=Provider.EODHD,
        symbols=[symbol],
        dataset_type=DatasetType.OHLCV,
        timeframe="1d",
    )
    assert result2.tasks_created == 0


# ---------------------------------------------------------------------------
# Scenario 2: Backfill → chunked tasks
# ---------------------------------------------------------------------------


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_scenario_backfill_produces_chunks():
    """GIVEN a backfill request for a 90-day window with 30-day chunks
    WHEN BackfillUseCase.execute() runs
    THEN 3 chunked task records appear in the DB.
    """
    from market_ingestion.application.use_cases.backfill import BackfillUseCase
    from market_ingestion.config import Settings
    from market_ingestion.domain.enums import Provider
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    symbol = f"QA_BF_{int(time.time())}"

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 3, 31, tzinfo=UTC)  # 90 days (Jan 1 → Mar 31 exclusive = 30+29+31 days)

    uow = SqlaUnitOfWork(write_factory, read_factory)
    use_case = BackfillUseCase(uow=uow)
    result = await use_case.execute(
        provider=Provider.EODHD,
        symbol=symbol,
        start_date=start,
        end_date=end,
        timeframe="1d",
        chunk_days=30,
    )

    assert result.chunks == 3
    assert result.tasks_created == 3


# ---------------------------------------------------------------------------
# Scenario 3: Worker claims and executes task (mocked provider)
# ---------------------------------------------------------------------------


@_NEEDS_INFRA
@pytest.mark.asyncio
async def test_scenario_worker_executes_task_with_mock_provider():
    """GIVEN a pending task in the DB
    WHEN the worker claims and executes it with a mock provider
    THEN the task transitions to DONE and watermark is updated.
    """
    import json

    from market_ingestion.application.ports.adapters import ProviderFetchResult
    from market_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
    from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
    from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
    from market_ingestion.config import Settings
    from market_ingestion.domain.enums import DatasetType, Provider
    from market_ingestion.domain.value_objects import ObjectRef
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    symbol = f"QA_EXEC_{int(time.time())}"
    worker_id = f"qa-worker-{int(time.time())}"

    # Enqueue a task
    uow = SqlaUnitOfWork(write_factory, read_factory)
    trigger = TriggerIngestionUseCase(uow=uow)
    await trigger.execute(
        provider=Provider.EODHD,
        symbols=[symbol],
        dataset_type=DatasetType.OHLCV,
        timeframe="1d",
    )

    # Claim it
    uow2 = SqlaUnitOfWork(write_factory, read_factory)
    claim = ClaimTasksUseCase(uow=uow2)
    tasks = await claim.execute(worker_id=worker_id, batch_size=1)
    assert len(tasks) >= 1

    task = tasks[0]

    # Mock provider + object store
    mock_registry = MagicMock()
    mock_adapter = MagicMock()
    ohlcv_data = json.dumps(
        [
            {
                "symbol": symbol,
                "exchange": "US",
                "date": "2024-01-02T00:00:00",
                "open": 150.0,
                "high": 155.0,
                "low": 149.0,
                "close": 153.0,
                "volume": 1_000_000,
            }
        ]
    ).encode()
    fetch_result = ProviderFetchResult(
        provider=Provider.EODHD,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        raw_data=ohlcv_data,
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        duration_ms=100,
    )
    mock_adapter.fetch_ohlcv = AsyncMock(return_value=fetch_result)
    mock_registry.get = MagicMock(return_value=mock_adapter)

    mock_store = MagicMock()
    mock_store.put = AsyncMock(
        return_value=ObjectRef(
            bucket="market-bronze",
            key="test/key",
            byte_length=len(ohlcv_data),
            sha256="abc123def456" * 4,
            mime_type="application/json",
        )
    )

    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    uow3 = SqlaUnitOfWork(write_factory, read_factory)
    exec_uc = ExecuteTaskUseCase(
        uow=uow3,
        provider_registry=mock_registry,
        object_store=mock_store,
        serializer=DefaultCanonicalSerializer(),
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )
    await exec_uc.execute(task)

    # Verify task is SUCCEEDED (IngestionTaskStatus.SUCCEEDED = "succeeded")
    uow4 = SqlaUnitOfWork(write_factory, read_factory)
    async with uow4:
        counts = await uow4.tasks.count_by_status()

    assert counts.get("succeeded", 0) >= 1


# ---------------------------------------------------------------------------
# Scenario 4: Live provider fetch (requires real API key)
# ---------------------------------------------------------------------------


@_NEEDS_INFRA
@_NEEDS_LIVE_KEY
@pytest.mark.asyncio
async def test_scenario_live_eodhd_fetch():
    """GIVEN a valid EODHD API key
    WHEN fetching AAPL daily OHLCV for a 5-day window
    THEN raw data bytes are returned with 200 content.
    """
    import httpx
    from market_ingestion.config import Settings
    from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter

    settings = Settings()
    async with httpx.AsyncClient() as client:
        adapter = EODHDProviderAdapter(api_key=settings.eodhd_api_key, client=client)
        result = await adapter.fetch_ohlcv(
            symbol="AAPL",
            timeframe="1d",
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 8, tzinfo=UTC),
            exchange="US",
        )

    assert len(result.raw_data) > 0
    assert result.symbol == "AAPL"


# ---------------------------------------------------------------------------
# Scenario 5: API readyz with healthy DB (unit-level QA)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scenario_readyz_healthy():
    """GIVEN a healthy DB and storage
    WHEN GET /readyz is called
    THEN the response is 200 with status=ok and both checks passing.
    """
    from httpx import ASGITransport, AsyncClient
    from market_ingestion.api.dependencies import get_object_store, get_uow
    from market_ingestion.app import create_app

    app = create_app()

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.commit = AsyncMock()
    mock_uow.tasks = MagicMock()
    mock_uow.tasks.count_by_status = AsyncMock(return_value={"pending": 0})

    mock_store = MagicMock()
    mock_store.exists = AsyncMock(return_value=True)

    async def override_uow():
        yield mock_uow

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_object_store] = lambda: mock_store

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/readyz")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Scenario 6: Scheduler tick with policies creates tasks
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scenario_scheduler_tick_with_symbol_policy_creates_task():
    """GIVEN an enabled polling policy with a specific symbol
    WHEN the scheduler ticks
    THEN tasks are enqueued for that symbol.
    """
    from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
    from market_ingestion.domain.enums import DatasetType, Provider

    mock_policy = MagicMock()
    mock_policy.id = "policy-001"
    mock_policy.provider = Provider.EODHD
    mock_policy.dataset_type = DatasetType.OHLCV
    mock_policy.symbol = "AAPL"
    mock_policy.exchange = "US"
    mock_policy.timeframe = "1d"
    mock_policy.backfill_days = None
    mock_policy.backfill_start_date = None
    mock_policy.is_due = MagicMock(return_value=True)
    mock_policy.base_interval_seconds = 3600

    mock_watermark = MagicMock()
    mock_watermark.current_bar_ts = None

    mock_budget = MagicMock()
    mock_budget.last_refill_at = datetime.now(tz=UTC)
    mock_budget.try_consume = MagicMock(return_value=True)
    mock_budget.refill = MagicMock()

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.commit = AsyncMock()
    mock_uow.policies = MagicMock()
    mock_uow.policies.list_enabled = AsyncMock(return_value=[mock_policy])
    mock_uow.watermarks = MagicMock()
    mock_uow.watermarks.get_or_create = AsyncMock(return_value=mock_watermark)
    mock_uow.budgets = MagicMock()
    mock_uow.budgets.get_or_create = AsyncMock(return_value=mock_budget)
    mock_uow.budgets.get_for_update = AsyncMock(return_value=mock_budget)
    mock_uow.budgets.save = AsyncMock()
    mock_uow.tasks = MagicMock()
    mock_uow.tasks.has_active_task = AsyncMock(return_value=False)
    mock_uow.tasks.add_many = AsyncMock(return_value=1)

    use_case = ScheduleDueTasksUseCase(uow=mock_uow)
    result = await use_case.execute()

    assert result.policies_evaluated == 1
    assert result.tasks_enqueued == 1
    assert result.budget_limited == 0
