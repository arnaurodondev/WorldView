"""Unit tests for S6NewsClient (PLAN-0113 T-2-04 — NEW client).

Covers the news-rollup-7d count read and the trending-entities count + momentum
reads, including the best-effort failure contract and the absent-entity
semantics (count → 0, momentum → None).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from alert.config import Settings
from alert.infrastructure.clients.s6_client import S6NewsClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        s6_nlp_base_url="http://s6:8006",
    )


def _resp(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_get_news_count_7d_parses() -> None:
    iid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"instrument_id": str(iid), "news_count_7d": 12}))
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_news_count_7d(iid) == 12


@pytest.mark.asyncio
async def test_get_news_count_7d_failure_returns_none() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_news_count_7d(uuid4()) is None


@pytest.mark.asyncio
async def test_get_trending_count_finds_entity() -> None:
    eid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_resp(
            {
                "window_hours": 24,
                "entities": [
                    {"entity_id": str(uuid4()), "count": 3, "delta_pct": 10.0},
                    {"entity_id": str(eid), "count": 9, "delta_pct": 80.0},
                ],
            }
        )
    )
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_trending_count(eid, 24) == 9


@pytest.mark.asyncio
async def test_get_trending_count_absent_entity_returns_zero() -> None:
    """Not in the trending feed → 0 articles (a real observation, re-arms count rules)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"entities": []}))
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_trending_count(uuid4(), 24) == 0


@pytest.mark.asyncio
async def test_get_trending_momentum_parses() -> None:
    eid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_resp({"entities": [{"entity_id": str(eid), "count": 7, "delta_pct": 120.0}]})
    )
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_trending_momentum(eid, 72) == (120.0, 7)


@pytest.mark.asyncio
async def test_get_trending_momentum_absent_returns_none() -> None:
    """Momentum skips (None) for a non-trending entity — no delta to compare."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"entities": []}))
    client = S6NewsClient(_settings(), client=mock_client)
    assert await client.get_trending_momentum(uuid4(), 24) is None


@pytest.mark.asyncio
async def test_window_snapped_to_allowed_set() -> None:
    """A non-allowed window_hours is snapped server-friendly to 24 in the query."""
    eid = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"entities": []}))
    client = S6NewsClient(_settings(), client=mock_client)
    await client.get_trending_count(eid, 999)
    _, kwargs = mock_client.get.call_args
    assert kwargs["params"]["window_hours"] == 24
