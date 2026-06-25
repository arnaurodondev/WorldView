"""Regression tests — trade_side persistence + hydration in the SQL transaction repo.

2026-06-10 frontend-enhancement sprint: PLAN-0108 added ``trade_side`` to the
entity, the model and migration 0021, but ``SqlAlchemyTransactionRepository``
was never updated:

* ``save()`` silently dropped the field → TRADE rows persisted with NULL.
* ``_to_entity()`` never hydrated it → the ``Transaction.__post_init__``
  invariant ("trade_side required for TRADE") raised ``ValueError`` for ANY
  TRADE row, 500-ing realized-pnl / deep transaction pages / TWR.

These tests pin the fix: hydration maps the column, infers BUY/SELL from
direction for legacy NULL rows, and the write path persists the value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType
from portfolio.infrastructure.db.repositories.transaction import SqlAlchemyTransactionRepository

pytestmark = pytest.mark.unit


def _row(
    *,
    transaction_type: str,
    direction: str,
    trade_side: str | None,
) -> SimpleNamespace:
    """Minimal stand-in for a TransactionModel row — only the attributes
    ``_to_entity`` reads. SimpleNamespace keeps the test free of a DB session."""
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        portfolio_id=uuid4(),
        instrument_id=uuid4(),
        transaction_type=transaction_type,
        direction=direction,
        quantity=Decimal(10),
        price=Decimal(100),
        fees=Decimal(0),
        amount=None,
        currency="USD",
        executed_at=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
        external_ref=None,
        description=None,
        trade_side=trade_side,
        created_at=datetime(2026, 6, 9, 6, 30, tzinfo=UTC),
    )


def _repo() -> SqlAlchemyTransactionRepository:
    return SqlAlchemyTransactionRepository(session=MagicMock())


class TestToEntityTradeSide:
    def test_trade_row_with_stored_side_hydrates(self) -> None:
        entity = _repo()._to_entity(_row(transaction_type="TRADE", direction="INFLOW", trade_side="BUY"))  # type: ignore[arg-type]
        assert entity.trade_side == TradeSide.BUY

    def test_legacy_trade_row_null_side_infers_buy_from_inflow(self) -> None:
        """The pre-fix 500: NULL trade_side on a TRADE row raised ValueError.
        Now the side is inferred from direction (INFLOW → BUY)."""
        entity = _repo()._to_entity(_row(transaction_type="TRADE", direction="INFLOW", trade_side=None))  # type: ignore[arg-type]
        assert entity.trade_side == TradeSide.BUY

    def test_legacy_trade_row_null_side_infers_sell_from_outflow(self) -> None:
        entity = _repo()._to_entity(_row(transaction_type="TRADE", direction="OUTFLOW", trade_side=None))  # type: ignore[arg-type]
        assert entity.trade_side == TradeSide.SELL

    def test_non_trade_row_keeps_trade_side_none(self) -> None:
        """The entity invariant FORBIDS trade_side on non-TRADE types — the
        repo must not infer one even if a junk value is stored."""
        entity = _repo()._to_entity(_row(transaction_type="BUY", direction="INFLOW", trade_side=None))  # type: ignore[arg-type]
        assert entity.trade_side is None


class TestSavePersistsTradeSide:
    @pytest.mark.asyncio
    async def test_save_writes_trade_side_column(self) -> None:
        """The pre-fix silent drop: save() omitted trade_side from the INSERT."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)  # force the insert branch
        repo = SqlAlchemyTransactionRepository(session=session)

        tx = Transaction(
            tenant_id=uuid4(),
            portfolio_id=uuid4(),
            instrument_id=uuid4(),
            transaction_type=TransactionType.TRADE,
            direction=TransactionDirection.INFLOW,
            quantity=Decimal(1),
            price=Decimal(175),
            currency="USD",
            executed_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
            trade_side=TradeSide.BUY,
        )
        await repo.save(tx)

        session.add.assert_called_once()
        row = session.add.call_args[0][0]
        assert row.trade_side == "BUY"

    @pytest.mark.asyncio
    async def test_save_keeps_null_for_non_trade(self) -> None:
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        repo = SqlAlchemyTransactionRepository(session=session)

        tx = Transaction(
            tenant_id=uuid4(),
            portfolio_id=uuid4(),
            instrument_id=uuid4(),
            transaction_type=TransactionType.BUY,
            direction=TransactionDirection.INFLOW,
            quantity=Decimal(1),
            price=Decimal(100),
            currency="USD",
            executed_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
        )
        await repo.save(tx)

        row = session.add.call_args[0][0]
        assert row.trade_side is None
