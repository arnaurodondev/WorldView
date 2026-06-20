"""Unit tests for S7GraphClient (PLAN-0113 T-3-01 — NEW pairwise-path client).

Covers the four W3 acceptance cases for ``confirm_connection``:
  - ``connected:true``  → True
  - ``connected:false`` → False
  - 503 / timeout       → fail-closed (False, no fire)
  - ``relation_type``   → matched / unmatched edge filtering
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from alert.config import Settings
from alert.infrastructure.clients.s7_client import S7GraphClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        s7_knowledge_graph_base_url="http://s7:8007",
        s7_internal_jwt="tok",  # — test token, not a real secret
    )


def _resp(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_confirm_connection_true() -> None:
    a, b = uuid4(), uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_resp({"connected": True, "shortest_hops": 1, "paths": []}),
    )
    client = S7GraphClient(_settings(), client=mock_client)
    assert await client.confirm_connection(a, b, 3) is True
    # JWT header forwarded (PRD-0025).
    assert mock_client.get.call_args.kwargs["headers"]["X-Internal-JWT"] == "tok"


@pytest.mark.asyncio
async def test_confirm_connection_false() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"connected": False, "paths": []}))
    client = S7GraphClient(_settings(), client=mock_client)
    assert await client.confirm_connection(uuid4(), uuid4(), 2) is False


@pytest.mark.asyncio
async def test_confirm_connection_503_fail_closed() -> None:
    """S7 returns 503 on AGE statement timeout → fail-closed (False)."""
    request = httpx.Request("GET", "http://s7:8007/api/v1/paths/between")
    response = httpx.Response(503, request=request)
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError("503", request=request, response=response),
    )
    client = S7GraphClient(_settings(), client=mock_client)
    assert await client.confirm_connection(uuid4(), uuid4(), 3) is False


@pytest.mark.asyncio
async def test_confirm_connection_timeout_fail_closed() -> None:
    """A transport timeout is also fail-closed (no fire)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    client = S7GraphClient(_settings(), client=mock_client)
    assert await client.confirm_connection(uuid4(), uuid4(), 3) is False


@pytest.mark.asyncio
async def test_confirm_connection_relation_type_matched() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_resp(
            {
                "connected": True,
                "paths": [
                    {"path_edges": [{"relation_type": "SUPPLIES"}, {"relation_type": "OWNS"}]},
                ],
            },
        ),
    )
    client = S7GraphClient(_settings(), client=mock_client)
    # Case-insensitive match.
    assert await client.confirm_connection(uuid4(), uuid4(), 3, relation_type="owns") is True


@pytest.mark.asyncio
async def test_confirm_connection_relation_type_unmatched() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        return_value=_resp(
            {
                "connected": True,
                "paths": [{"path_edges": [{"relation_type": "SUPPLIES"}]}],
            },
        ),
    )
    client = S7GraphClient(_settings(), client=mock_client)
    # connected=true but no COMPETES_WITH edge → no fire.
    assert await client.confirm_connection(uuid4(), uuid4(), 3, relation_type="COMPETES_WITH") is False


@pytest.mark.asyncio
async def test_confirm_connection_self_loop_short_circuits() -> None:
    """node_a == node_b never round-trips to S7 and is never 'connected'."""
    same = uuid4()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock()
    client = S7GraphClient(_settings(), client=mock_client)
    assert await client.confirm_connection(same, same, 3) is False
    mock_client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_connection_clamps_max_hops() -> None:
    """An out-of-range stored max_hops is clamped to S7's 1..3 contract."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=_resp({"connected": False, "paths": []}))
    client = S7GraphClient(_settings(), client=mock_client)
    await client.confirm_connection(uuid4(), uuid4(), 99)
    assert mock_client.get.call_args.kwargs["params"]["max_hops"] == 3
