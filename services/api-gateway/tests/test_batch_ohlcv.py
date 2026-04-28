"""PLAN-0049 T-A-1-05 — POST /v1/ohlcv/batch tests.

Verify:
1. Auth required (no JWT → 401, downstream untouched).
2. Happy path returns one entry per requested instrument, in request order.
3. Per-symbol failures populate ``error`` instead of failing the whole batch.
4. Hard cap of 50 symbols (51+ → 422 ValidationError).
5. Empty payload → 422.
6. Cache-Control: max-age=300 header set.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105


def _make_jwt() -> str:
    return jwt.encode(
        {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _resp(status: int, body: dict) -> MagicMock:
    import json

    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.content = json.dumps(body).encode()
    r.json = MagicMock(return_value=body)
    return r


@pytest.mark.asyncio
async def test_batch_ohlcv_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            json={"requests": [{"instrument_id": "AAPL", "timeframe": "1d"}]},
        )
    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_batch_ohlcv_happy_path_returns_results_in_order(authed_app, authed_mock_clients) -> None:
    # Each call returns a different bar list keyed by URL path so we can verify ordering.
    async def _fake_get(path: str, **kwargs):
        if "AAPL" in path:
            return _resp(200, {"bars": [{"o": 100}]})
        if "MSFT" in path:
            return _resp(200, {"bars": [{"o": 200}]})
        return _resp(200, {"bars": []})

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_fake_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={
                "requests": [
                    {"instrument_id": "AAPL", "timeframe": "1d"},
                    {"instrument_id": "MSFT", "timeframe": "1d"},
                ]
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2
    assert body["results"][0]["instrument_id"] == "AAPL"
    assert body["results"][0]["bars"] == [{"o": 100}]
    assert body["results"][1]["instrument_id"] == "MSFT"
    assert body["results"][1]["bars"] == [{"o": 200}]


@pytest.mark.asyncio
async def test_batch_ohlcv_partial_failure_marks_error(authed_app, authed_mock_clients) -> None:
    async def _fake_get(path: str, **kwargs):
        if "BAD" in path:
            return _resp(404, {"detail": "not found"})
        return _resp(200, {"bars": [{"o": 1}]})

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_fake_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={
                "requests": [
                    {"instrument_id": "GOOD", "timeframe": "1d"},
                    {"instrument_id": "BAD", "timeframe": "1d"},
                ]
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["results"][0]["bars"] == [{"o": 1}]
    assert "error" not in body["results"][0]
    assert body["results"][1]["bars"] == []
    assert "404" in body["results"][1]["error"]


@pytest.mark.asyncio
async def test_batch_ohlcv_rejects_more_than_50_symbols(authed_app) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"requests": [{"instrument_id": f"S{i}", "timeframe": "1d"} for i in range(51)]},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_ohlcv_rejects_empty_payload(authed_app) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"requests": []},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_ohlcv_sets_cache_control_header(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_resp(200, {"bars": []}),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/ohlcv/batch",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
            json={"requests": [{"instrument_id": "AAPL", "timeframe": "1d"}]},
        )
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "max-age=300" in cc
    assert "private" in cc, "shared CDN must not be allowed to mix users' responses"
