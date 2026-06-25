"""Unit tests for ManualHoldingsWorker.

PLAN-0114 W1 / T-W1-09 (worker unit tests).

Tests:
    1. run_once skips portfolios with zero transactions
    2. run_once processes MANUAL portfolios and calls ComputeManualHoldingsUseCase
    3. BROKERAGE and ROOT portfolios are skipped (not passed to use case)
    4. Cron expression is set to 22:00 UTC daily
    5. Worker is resilient to per-portfolio errors (logs and continues)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import PortfolioKind
from portfolio.workers.manual_holdings_worker import CRON_EXPRESSION, ManualHoldingsWorker

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")


def _make_portfolio(kind: PortfolioKind, pid: UUID | None = None) -> Portfolio:
    return Portfolio(
        id=pid or UUID("00000000-0000-0000-0000-000000000010"),
        name="Test",
        owner_id=OWNER_ID,
        tenant_id=TENANT_ID,
        kind=kind,
        currency="USD",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCronExpression:
    """The worker cron must fire at 22:00 UTC daily."""

    def test_cron_is_22_utc(self) -> None:
        # "0 22 * * *" — minute=0, hour=22, every day
        assert CRON_EXPRESSION == "0 22 * * *"
        assert ManualHoldingsWorker.CRON_EXPRESSION == "0 22 * * *"


class TestRunOnceFiltering:
    """run_once must skip non-MANUAL portfolios."""

    def test_skips_brokerage_portfolio(self) -> None:
        """A BROKERAGE portfolio must not result in ComputeManualHoldingsUseCase call."""
        brokerage = _make_portfolio(PortfolioKind.BROKERAGE)
        manual = _make_portfolio(PortfolioKind.MANUAL, pid=UUID("00000000-0000-0000-0000-000000000020"))

        session_factory = MagicMock()

        # Mock the UoW context manager
        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        mock_uow.portfolios.list_all_non_root_active = AsyncMock(return_value=[brokerage, manual])
        mock_uow.transactions.list_by_portfolio = AsyncMock(return_value=(["fake_tx"], 1))

        compute_result = MagicMock()
        compute_result.skipped = False
        compute_result.upserted = 1
        compute_result.deleted = 0

        with (
            patch(
                "portfolio.infrastructure.db.unit_of_work.SqlAlchemyUnitOfWork",
                return_value=mock_uow,
            ),
            patch.object(
                ManualHoldingsWorker,
                "_use_case",
                create=True,
            ),
        ):
            worker = ManualHoldingsWorker(session_factory=session_factory)
            worker._use_case = AsyncMock()
            worker._use_case.execute = AsyncMock(return_value=compute_result)

            asyncio.get_event_loop().run_until_complete(worker.run_once())

            # Use case was only called for the MANUAL portfolio
            assert worker._use_case.execute.call_count == 1
            call_args = worker._use_case.execute.call_args[0][0]
            assert call_args.portfolio_id == manual.id

    def test_skips_portfolio_with_no_transactions(self) -> None:
        """Portfolios with 0 transactions must be skipped to avoid empty upserts."""
        manual_empty = _make_portfolio(PortfolioKind.MANUAL)

        session_factory = MagicMock()

        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        mock_uow.portfolios.list_all_non_root_active = AsyncMock(return_value=[manual_empty])
        # Zero transactions
        mock_uow.transactions.list_by_portfolio = AsyncMock(return_value=([], 0))

        with patch(
            "portfolio.infrastructure.db.unit_of_work.SqlAlchemyUnitOfWork",
            return_value=mock_uow,
        ):
            worker = ManualHoldingsWorker(session_factory=session_factory)
            worker._use_case = AsyncMock()
            worker._use_case.execute = AsyncMock()

            asyncio.get_event_loop().run_until_complete(worker.run_once())

            # No use case call — portfolio has no transactions
            worker._use_case.execute.assert_not_called()


class TestRunOnceResilient:
    """run_once must continue processing after a per-portfolio error."""

    def test_continues_after_error(self) -> None:
        manual1 = _make_portfolio(PortfolioKind.MANUAL, pid=UUID("00000000-0000-0000-0000-000000000011"))
        manual2 = _make_portfolio(PortfolioKind.MANUAL, pid=UUID("00000000-0000-0000-0000-000000000012"))

        session_factory = MagicMock()

        call_count = 0

        async def fake_execute(cmd, uow):
            nonlocal call_count
            call_count += 1
            if cmd.portfolio_id == manual1.id:
                raise RuntimeError("simulated error")
            result = MagicMock()
            result.skipped = False
            result.upserted = 1
            result.deleted = 0
            return result

        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        mock_uow.portfolios.list_all_non_root_active = AsyncMock(return_value=[manual1, manual2])
        mock_uow.transactions.list_by_portfolio = AsyncMock(return_value=(["tx"], 1))

        with patch(
            "portfolio.infrastructure.db.unit_of_work.SqlAlchemyUnitOfWork",
            return_value=mock_uow,
        ):
            worker = ManualHoldingsWorker(session_factory=session_factory)
            worker._use_case = AsyncMock()
            worker._use_case.execute = fake_execute  # type: ignore[assignment]

            asyncio.get_event_loop().run_until_complete(worker.run_once())

            # Both portfolios were attempted; second succeeded
            assert call_count == 2
