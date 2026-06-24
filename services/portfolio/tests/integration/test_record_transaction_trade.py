"""Integration tests for PLAN-0108: TRADE transaction type via POST /api/v1/transactions.

Verifies:
- TRADE + BUY → 201 with direction=INFLOW and trade_side=BUY
- Unknown transaction_type → 422 (Pydantic validation, not 500)
- TRADE without trade_side → 422

These tests require a live Postgres testcontainer (integration marker).
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.helpers import INTEGRATION_USER_ID

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_EXECUTED_AT = "2026-01-01T12:00:00Z"


async def test_post_transaction_trade_buy(integration_client, db_session) -> None:
    """POST TRADE + trade_side=BUY returns 201 with direction=INFLOW and trade_side=BUY."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "NVDA", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "TRADE",
            "trade_side": "BUY",
            "quantity": "10",
            "price": "800.00",
            "fees": "1.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["transaction_type"] == "TRADE"
    assert data["direction"] == "INFLOW"
    assert data["trade_side"] == "BUY"


async def test_post_transaction_invalid_type_returns_422(integration_client, db_session) -> None:
    """POST with an unknown transaction_type must return 422, not 500."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "TSLA", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "BOGUS_TYPE",
            "direction": "INFLOW",
            "quantity": "5",
            "price": "250.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 422


async def test_post_transaction_trade_missing_side_returns_422(integration_client, db_session) -> None:
    """POST TRADE without trade_side must return 422, not 500."""
    portfolio_id = await _create_portfolio(integration_client)
    instrument_id = await _seed_instrument(db_session, "AMD", "NASDAQ")

    resp = await integration_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_id,
            "instrument_id": str(instrument_id),
            "transaction_type": "TRADE",
            # trade_side intentionally omitted — schema validator must reject this
            "quantity": "5",
            "price": "150.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
    )
    assert resp.status_code == 422


# ── helpers ───────────────────────────────────────────────────────────────────


async def _create_portfolio(client) -> str:  # type: ignore[no-untyped-def]
    """Create a portfolio for INTEGRATION_USER_ID and return its id."""
    resp = await client.post(
        "/api/v1/portfolios",
        json={
            "name": f"Trade Test Portfolio {uuid.uuid4().hex[:8]}",
            "owner_user_id": INTEGRATION_USER_ID,
            "currency": "USD",
        },
    )
    assert resp.status_code == 201, f"create_portfolio failed: {resp.text}"
    return resp.json()["id"]


async def _seed_instrument(db_session, symbol: str, exchange: str) -> uuid.UUID:
    """Upsert an instrument into the test DB and return its ID."""
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    inst_id = uuid.uuid4()
    stmt = (
        insert(InstrumentModel)
        .values(
            id=inst_id,
            symbol=symbol,
            exchange=exchange,
            name=f"{symbol} Inc.",
            currency="USD",
            asset_class="equity",
            source_event_id=uuid.uuid4(),
        )
        .on_conflict_do_nothing(constraint="uq_instruments_symbol_exchange")
    )
    await db_session.execute(stmt)
    await db_session.commit()

    result = await db_session.execute(
        select(InstrumentModel.id).where(
            InstrumentModel.symbol == symbol,
            InstrumentModel.exchange == exchange,
        ),
    )
    return result.scalar_one()
