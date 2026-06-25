"""Integration tests for instrument API endpoint."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_list_instruments_empty(integration_client) -> None:
    """GET /api/v1/instruments returns empty list when no instruments exist."""
    resp = await integration_client.get("/api/v1/instruments")
    assert resp.status_code == 200
    # May be empty or contain previously seeded instruments (session-scoped DB)
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


async def test_list_instruments_after_seeding(integration_client, db_session) -> None:
    """GET /api/v1/instruments returns instruments after they are inserted."""
    import uuid

    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    from sqlalchemy.dialects.postgresql import insert

    # ON CONFLICT DO NOTHING on uq_instruments_symbol_exchange: the testcontainer
    # DB is session-scoped with no per-test cleanup, and sibling integration
    # tests (test_transaction_export, test_record_transaction_trade) also seed
    # TSLA/NASDAQ. A plain INSERT would raise UniqueViolationError on that shared
    # (symbol, exchange). We only need the row to exist for the list assertion.
    stmt = (
        insert(InstrumentModel)
        .values(
            id=uuid.uuid4(),
            symbol="TSLA",
            exchange="NASDAQ",
            name="Tesla Inc.",
            currency="USD",
            asset_class="equity",
            source_event_id=uuid.uuid4(),
        )
        .on_conflict_do_nothing(constraint="uq_instruments_symbol_exchange")
    )
    await db_session.execute(stmt)
    await db_session.commit()

    resp = await integration_client.get("/api/v1/instruments")
    assert resp.status_code == 200
    data = resp.json()
    symbols = [i["symbol"] for i in data["items"]]
    assert "TSLA" in symbols
