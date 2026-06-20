"""Unit tests for W3 holdings response enrichment.

Covers FR-4 (brokerage_last_synced_at) and FR-7 (brokerage_sync_error_count)
for the HoldingsResponse envelope returned by GetHoldingsUseCase.

Test matrix:
  - BROKERAGE portfolio: last_synced_at non-null, error_count = 3
  - BROKERAGE portfolio: new connection (last_synced_at = None)
  - BROKERAGE portfolio: no connection row at all (never connected)
  - MANUAL portfolio: both fields are None/0
  - ROOT portfolio: both fields are None/0
  - Holdings list preserved after envelope wrapping
  - Error count scoped to connection (not bleeding across connections)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from portfolio.application.use_cases.create_portfolio import CreatePortfolioCommand, CreatePortfolioUseCase
from portfolio.application.use_cases.read_models import GetHoldingsUseCase, HoldingsResponse
from portfolio.application.use_cases.tenant import CreateTenantCommand, CreateTenantUseCase
from portfolio.application.use_cases.user import CreateUserCommand, CreateUserUseCase
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.entities.holding import Holding
from portfolio.domain.enums import ConnectionStatus, PortfolioKind, SyncErrorType

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit

# Fixed UTC timestamp for a completed sync -- represents a real timestamp that
# the frontend will format as "Last synced: 5 minutes ago" etc.
_SYNCED_AT = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)
_TOS_AT = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


def _make_connection(
    uow: FakeUnitOfWork,
    *,
    portfolio_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    last_synced_at: datetime | None = None,
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
) -> BrokerageConnection:
    """Seed a BrokerageConnection with sensible defaults into the fake UoW."""
    conn = BrokerageConnection(
        id=new_uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        portfolio_id=portfolio_id,
        snaptrade_user_id="snap-user-001",
        snaptrade_user_secret="secret-token",
        snaptrade_tos_accepted_at=_TOS_AT,
        status=status,
        last_synced_at=last_synced_at,
    )
    uow._brokerage_connections._store[conn.id] = conn
    return conn


def _seed_sync_error(uow: FakeUnitOfWork, connection_id: UUID) -> BrokerageTransactionSyncError:
    """Append one sync error for the given connection into the fake UoW."""
    err = BrokerageTransactionSyncError(
        id=new_uuid7(),
        connection_id=connection_id,
        snaptrade_transaction_id="tx-err-001",
        error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
        error_detail="Instrument not found",
        raw_transaction={"raw": "data"},
        created_at=utc_now(),
    )
    uow._brokerage_sync_errors._store.append(err)
    return err


async def _make_portfolio(
    uow: FakeUnitOfWork,
    *,
    kind: PortfolioKind = PortfolioKind.MANUAL,
) -> tuple[UUID, UUID, UUID]:
    """Create a minimal tenant + user + portfolio, returning (portfolio_id, owner_id, tenant_id)."""
    tenant_uc = CreateTenantUseCase()
    tenant = await tenant_uc.execute(CreateTenantCommand(name="TestCo"), uow)

    user_uc = CreateUserUseCase()
    user = await user_uc.execute(CreateUserCommand(tenant_id=tenant.id, email="test@testco.com"), uow)

    portfolio_uc = CreatePortfolioUseCase()
    result = await portfolio_uc.execute(
        CreatePortfolioCommand(tenant_id=tenant.id, owner_id=user.id, name="Test Portfolio"),
        uow,
    )
    portfolio = result.portfolio

    # CreatePortfolioUseCase always creates MANUAL portfolios. For non-MANUAL
    # kinds we mutate the stored entity directly -- this is test-only and avoids
    # needing a full BrokerageConnectionUseCase flow.
    if kind != PortfolioKind.MANUAL:
        from dataclasses import replace

        updated = replace(portfolio, kind=kind)
        uow._portfolios._store[portfolio.id] = updated

    return portfolio.id, user.id, tenant.id


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_brokerage_portfolio_with_synced_connection_and_errors(uow: FakeUnitOfWork) -> None:
    """BROKERAGE portfolio: last_synced_at non-null and error_count == 3.

    WHY: This is the primary user-facing scenario -- the portfolio has been
    synced at least once (so we can show "Last synced: X minutes ago") and
    has accumulated sync errors (so we should show the red error badge).
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.BROKERAGE)

    # Seed a connection that has completed one sync.
    conn = _make_connection(
        uow,
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        user_id=owner_id,
        last_synced_at=_SYNCED_AT,
    )

    # Seed 3 sync errors for this connection.
    for _ in range(3):
        _seed_sync_error(uow, conn.id)

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    # Verify the envelope type is correct (not a bare list).
    assert isinstance(response, HoldingsResponse)
    # FR-4: last_synced_at is present and correct.
    assert response.brokerage_last_synced_at == _SYNCED_AT
    # FR-7: error count reflects the number of seeded errors.
    assert response.brokerage_sync_error_count == 3
    # Holdings list is empty (no holding rows seeded) -- not the point of this test.
    assert response.holdings == []


@pytest.mark.asyncio
async def test_brokerage_portfolio_new_connection_never_synced(uow: FakeUnitOfWork) -> None:
    """BROKERAGE portfolio: connection exists but last_synced_at is None.

    WHY: A user just connected their brokerage -- the first sync hasn't run
    yet. The frontend should show "Never synced" (LastSyncedBadge handles
    null as "Never synced" copy). We must not raise or return a wrong value.
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.BROKERAGE)

    _make_connection(
        uow,
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        user_id=owner_id,
        last_synced_at=None,  # never synced
    )

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    assert isinstance(response, HoldingsResponse)
    # FR-4: None (never synced) -- not an error, just no timestamp yet.
    assert response.brokerage_last_synced_at is None
    # No errors seeded.
    assert response.brokerage_sync_error_count == 0


@pytest.mark.asyncio
async def test_brokerage_portfolio_no_connection_row(uow: FakeUnitOfWork) -> None:
    """BROKERAGE portfolio: no connection row in brokerage_connections at all.

    WHY: Edge case -- a portfolio has kind=BROKERAGE but the connection was
    deleted or never created (data inconsistency). We should degrade gracefully
    with None/0 rather than raising a 500. The frontend handles None as
    "Never synced" which is the least surprising UX.
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.BROKERAGE)
    # Intentionally do NOT seed a BrokerageConnection.

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    assert isinstance(response, HoldingsResponse)
    assert response.brokerage_last_synced_at is None
    assert response.brokerage_sync_error_count == 0


@pytest.mark.asyncio
async def test_manual_portfolio_returns_zero_brokerage_metadata(uow: FakeUnitOfWork) -> None:
    """MANUAL portfolio: brokerage fields are None and 0.

    WHY: MANUAL portfolios have no brokerage connection -- surfacing brokerage
    fields at all would be confusing. The use case must short-circuit the
    brokerage lookup and return the zero-value defaults without issuing any
    DB queries for brokerage_connections / brokerage_sync_errors.
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.MANUAL)

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    assert isinstance(response, HoldingsResponse)
    # For a MANUAL portfolio neither field should have a value.
    assert response.brokerage_last_synced_at is None
    assert response.brokerage_sync_error_count == 0


@pytest.mark.asyncio
async def test_root_portfolio_returns_zero_brokerage_metadata(uow: FakeUnitOfWork) -> None:
    """ROOT portfolio: brokerage fields are None and 0.

    WHY: ROOT portfolios are synthetic aggregates -- they have no direct
    brokerage connection of their own (the sub-portfolios they aggregate may
    be BROKERAGE, but the ROOT itself is not). The frontend never shows the
    LastSyncedBadge or SyncErrorBadge for ROOT portfolios.
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.ROOT)

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    assert isinstance(response, HoldingsResponse)
    assert response.brokerage_last_synced_at is None
    assert response.brokerage_sync_error_count == 0


@pytest.mark.asyncio
async def test_holdings_response_preserves_holdings_list(uow: FakeUnitOfWork) -> None:
    """HoldingsResponse.holdings contains the correct items for a MANUAL portfolio.

    WHY: Wrapping the return type in HoldingsResponse must not lose or corrupt
    the holdings list that was previously returned directly. This ensures the
    existing holdings display is unaffected by the W3 envelope change.
    """
    portfolio_id, owner_id, tenant_id = await _make_portfolio(uow, kind=PortfolioKind.MANUAL)

    # Seed one holding directly into the fake repo.
    instrument_id = new_uuid7()
    holding = Holding(
        id=new_uuid7(),
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        instrument_id=instrument_id,
        quantity=Decimal("10"),
        average_cost=Decimal("150.00"),
        currency="USD",
    )
    uow._holdings._store[(portfolio_id, instrument_id)] = holding

    uc = GetHoldingsUseCase()
    response = await uc.execute(portfolio_id, owner_id, tenant_id, uow)

    assert isinstance(response, HoldingsResponse)
    # One non-zero-quantity holding should be present.
    assert len(response.holdings) == 1
    assert response.holdings[0].holding.instrument_id == instrument_id
    assert response.holdings[0].holding.quantity == Decimal("10")
    # Brokerage fields are zero for MANUAL.
    assert response.brokerage_last_synced_at is None
    assert response.brokerage_sync_error_count == 0


@pytest.mark.asyncio
async def test_brokerage_error_count_is_scoped_to_connection(uow: FakeUnitOfWork) -> None:
    """Error count does not bleed across connections for different portfolios.

    WHY: If two BROKERAGE portfolios both have connections in the fake store,
    the error count for portfolio A must not include errors from portfolio B's
    connection. This verifies the scoping correctness of count_for_connection().
    """
    # First portfolio + connection + 2 errors.
    pid_a, owner_a, tenant_a = await _make_portfolio(uow, kind=PortfolioKind.BROKERAGE)
    conn_a = _make_connection(
        uow,
        portfolio_id=pid_a,
        tenant_id=tenant_a,
        user_id=owner_a,
        last_synced_at=_SYNCED_AT,
    )
    _seed_sync_error(uow, conn_a.id)
    _seed_sync_error(uow, conn_a.id)

    # Create a SECOND, separate brokerage connection not tied to portfolio A.
    # (We create it with a different fake connection_id -- no portfolio lookup.)
    conn_b = BrokerageConnection(
        id=new_uuid7(),
        tenant_id=tenant_a,
        user_id=owner_a,
        portfolio_id=new_uuid7(),  # different portfolio
        snaptrade_user_id="snap-user-002",
        snaptrade_user_secret="secret-b",
        snaptrade_tos_accepted_at=_TOS_AT,
        status=ConnectionStatus.ACTIVE,
        last_synced_at=_SYNCED_AT,
    )
    uow._brokerage_connections._store[conn_b.id] = conn_b
    # Add 5 errors for connection B.
    for _ in range(5):
        _seed_sync_error(uow, conn_b.id)

    uc = GetHoldingsUseCase()
    response = await uc.execute(pid_a, owner_a, tenant_a, uow)

    # Portfolio A's connection only has 2 errors -- not 7.
    assert response.brokerage_sync_error_count == 2
