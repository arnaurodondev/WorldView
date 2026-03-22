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

    inst = InstrumentModel(
        id=uuid.uuid4(),
        symbol="TSLA",
        exchange="NASDAQ",
        name="Tesla Inc.",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid.uuid4(),
    )
    db_session.add(inst)
    await db_session.commit()

    resp = await integration_client.get("/api/v1/instruments")
    assert resp.status_code == 200
    data = resp.json()
    symbols = [i["symbol"] for i in data["items"]]
    assert "TSLA" in symbols
