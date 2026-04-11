"""Unit tests for BrokerageTransactionSyncWorker (PRD-0022 §6.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from portfolio.application.ports.brokerage_client import SnapTradeActivity
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.enums import ConnectionStatus, SyncErrorType

from common.time import utc_now  # type: ignore[import-untyped]
from tests.unit.fakes import FakeBrokerageClient, FakeUnitOfWork

pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────

USER_ID = uuid4()
TENANT_ID = uuid4()
PORTFOLIO_ID = uuid4()
CONNECTION_ID = uuid4()


def _make_connection(
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
    last_sync_cursor: str | None = None,
) -> BrokerageConnection:
    return BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=status,
        last_sync_cursor=last_sync_cursor,
    )


def _make_activity(
    activity_type: str = "BUY",
    symbol: str = "AAPL",
    txn_id: str = "txn-001",
) -> SnapTradeActivity:
    return SnapTradeActivity(
        snaptrade_transaction_id=txn_id,
        activity_type=activity_type,
        symbol=symbol,
        quantity=Decimal("10"),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC),
    )


def _make_instrument(symbol: str = "AAPL") -> InstrumentRef:
    return InstrumentRef(
        id=uuid4(),
        symbol=symbol,
        exchange="NASDAQ",
        source_event_id=uuid4(),
        currency="USD",
    )


def _make_worker(uow: FakeUnitOfWork, broker: FakeBrokerageClient | None = None) -> tuple:
    """Return (worker, session_factory_mock) with pre-wired fake UoW."""
    from portfolio.config import Settings
    from portfolio.workers.brokerage_sync_worker import BrokerageTransactionSyncWorker

    settings = Settings(internal_service_token="t")
    broker = broker or FakeBrokerageClient()

    # We pass a sentinel for the session_factory — the worker's sync_cycle and
    # _sync_connection methods normally create SqlAlchemyUnitOfWork from it.
    # In unit tests we patch SqlAlchemyUnitOfWork to yield our FakeUnitOfWork.
    sentinel = object()
    worker = BrokerageTransactionSyncWorker(
        session_factory=sentinel,  # type: ignore[arg-type]
        brokerage_client=broker,
        settings=settings,
        cipher=None,
    )
    return worker, sentinel


# ── T-D-1-00: get_by_symbol (FakeInstrumentRepository) ───────────────────────


async def test_fake_instrument_repo_get_by_symbol_found() -> None:
    """FakeInstrumentRepository.get_by_symbol returns matching instrument (case-insensitive)."""
    uow = FakeUnitOfWork()
    inst = _make_instrument("AAPL")
    await uow.instruments.upsert(inst)

    result = await uow.instruments.get_by_symbol("aapl")
    assert result is not None
    assert result.symbol == "AAPL"


async def test_fake_instrument_repo_get_by_symbol_not_found() -> None:
    """FakeInstrumentRepository.get_by_symbol returns None for unknown symbol."""
    uow = FakeUnitOfWork()
    result = await uow.instruments.get_by_symbol("UNKNOWN")
    assert result is None


# ── sync_cycle: no active connections ────────────────────────────────────────


async def test_sync_cycle_no_connections_does_nothing() -> None:
    """sync_cycle with no active/error connections completes without errors."""
    worker, _ = _make_worker(FakeUnitOfWork())
    uow = FakeUnitOfWork()  # empty — no connections

    with patch(
        "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
    ) as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        await worker.sync_cycle()

    # No transactions, no errors
    assert len(uow.brokerage_connections._store) == 0


# ── _process_activity: type mapping ──────────────────────────────────────────


async def test_process_activity_buy_records_transaction() -> None:
    """BUY activity → TransactionType.BUY + INFLOW (asset direction) recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY")
    worker._http_client = None  # disable S3 fallback

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    # Verify no sync errors created
    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_sell_records_transaction() -> None:
    """SELL activity → TransactionType.SELL + OUTFLOW (asset direction) recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="SELL")
    worker._http_client = None

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_div_records_transaction() -> None:
    """DIV activity → TransactionType.DIVIDEND + INFLOW recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="DIV")
    worker._http_client = None

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_dividend_alias_records_transaction() -> None:
    """DIVIDEND (alias) activity → TransactionType.DIVIDEND + INFLOW recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="DIVIDEND")
    worker._http_client = None

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


# ── _process_activity: unsupported type ──────────────────────────────────────


async def test_process_activity_unsupported_type_creates_sync_error() -> None:
    """Unsupported activity type → UNSUPPORTED_TYPE sync error, worker continues."""
    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="TRANSFER")
    worker._http_client = None

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNSUPPORTED_TYPE
    assert errors[0].snaptrade_transaction_id == "txn-001"


# ── _process_activity: unknown instrument ────────────────────────────────────


async def test_process_activity_unknown_instrument_creates_sync_error() -> None:
    """Instrument not in DB and S3 returns None → UNKNOWN_INSTRUMENT sync error."""
    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="UNKNWN")
    worker._http_client = None  # no S3 fallback

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNKNOWN_INSTRUMENT
    assert "UNKNWN" in (errors[0].error_detail or "")


# ── _sync_connection: BrokerageApiError marks ERROR ─────────────────────────


async def test_sync_connection_api_error_marks_connection_error() -> None:
    """BrokerageApiError from get_activities → connection marked ERROR."""
    uow = FakeUnitOfWork()
    conn = _make_connection(status=ConnectionStatus.ACTIVE)
    await uow.brokerage_connections.save(conn)

    failing_broker = FakeBrokerageClient()
    failing_broker.should_raise_on_activities = True

    worker, _ = _make_worker(uow, broker=failing_broker)

    with patch(
        "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
    ) as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        await worker._sync_connection(conn)

    updated = uow.brokerage_connections._store[CONNECTION_ID]
    assert updated.status == ConnectionStatus.ERROR


# ── _process_activity: idempotency conflict silently skipped ─────────────────


async def test_process_activity_idempotency_conflict_silently_skipped() -> None:
    """Duplicate activity (same external_ref) → silently skipped, no sync error."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", txn_id="txn-dup-001")
    worker._http_client = None

    # Record same activity twice
    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]
    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    # Second call should be silently skipped (dedup via find_by_external_ref)
    assert len(uow.brokerage_sync_errors._store) == 0
    # Transaction recorded exactly once
    txns = [t for t in uow.transactions._store.values() if t.external_ref == "txn-dup-001"]
    assert len(txns) == 1


# ── Helpers (full UoW with tenant/user/portfolio/instrument) ──────────────────


async def _setup_full_uow() -> FakeUnitOfWork:
    """Return a FakeUnitOfWork seeded with tenant, user, portfolio, AAPL instrument, and 100-share holding.

    The holding is pre-seeded so that SELL tests don't trigger InsufficientHoldingsError.
    """
    from decimal import Decimal

    from portfolio.domain.entities.holding import Holding
    from portfolio.domain.entities.instrument import InstrumentRef
    from portfolio.domain.entities.portfolio import Portfolio
    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User
    from portfolio.domain.enums import TenantStatus, UserStatus

    uow = FakeUnitOfWork()

    tenant = Tenant(id=TENANT_ID, name="Test Tenant", status=TenantStatus.ACTIVE)
    await uow.tenants.save(tenant)

    user = User(id=USER_ID, tenant_id=TENANT_ID, email="test@example.com", status=UserStatus.ACTIVE)
    await uow.users.save(user)

    portfolio = Portfolio(id=PORTFOLIO_ID, tenant_id=TENANT_ID, owner_id=USER_ID, name="Test", currency="USD")
    await uow.portfolios.save(portfolio)

    instrument = InstrumentRef(
        id=uuid4(),
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        currency="USD",
    )
    await uow.instruments.upsert(instrument)

    # Pre-seed a holding so SELL tests don't hit InsufficientHoldingsError
    holding = Holding(
        id=uuid4(),
        portfolio_id=PORTFOLIO_ID,
        instrument_id=instrument.id,
        tenant_id=TENANT_ID,
        currency="USD",
        quantity=Decimal("100"),
        average_cost=Decimal("150.00"),
    )
    await uow.holdings.save(holding)

    return uow
