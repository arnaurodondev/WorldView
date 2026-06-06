"""Unit tests for the /internal/v1/instruments/top-by-market-cap endpoint.

PLAN-0100 T-W5-01.

We stub the use-case function (``query_top_by_market_cap``) directly so we
do not need a live database. The router opens an ``async with read_factory()``
context to get a session; we install a fake factory on ``app.state`` that
returns a no-op async context manager whose session value is irrelevant
because the stubbed use case ignores it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import require_internal_jwt
from market_data.api.routers import internal_instruments

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


class _DummySession:
    """Sentinel session — the stubbed use case ignores its content."""


def _install_read_factory(app: FastAPI) -> None:
    """Wire a fake ``read_session_factory`` onto ``app.state``.

    The factory is the callable; ``factory()`` returns an async context
    manager that yields the dummy session. Mirrors the production shape
    (an ``async_sessionmaker``) just enough for the router's
    ``async with read_factory() as session:`` line to work.
    """

    @asynccontextmanager
    async def _open() -> Any:  # type: ignore[misc]
        yield _DummySession()

    def _factory() -> Any:
        return _open()

    app.state.read_session_factory = _factory


def _make_app(
    *,
    use_case_return: tuple[int, list[dict[str, Any]]] | None = None,
    bypass_jwt: bool = True,
) -> tuple[FastAPI, TestClient, AsyncMock]:
    """Build a minimal FastAPI app mounted exactly like prod.

    Returns the app, a TestClient, and the AsyncMock stand-in for
    ``query_top_by_market_cap`` so individual tests can assert call args.
    """
    app = FastAPI(lifespan=_null_lifespan)
    # /internal/v1 prefix mirrors app.py wire-up.
    app.include_router(internal_instruments.router, prefix="/internal/v1")
    _install_read_factory(app)

    if bypass_jwt:
        app.dependency_overrides[require_internal_jwt] = lambda: None

    # Stub the use case at module-import location (the router did
    # ``from … import query_top_by_market_cap`` — must patch the binding the
    # router sees, not the source module).
    stub = AsyncMock(return_value=use_case_return or (0, []))
    internal_instruments.query_top_by_market_cap = stub  # type: ignore[assignment]

    return app, TestClient(app), stub


def test_happy_path_returns_top_n_sorted_desc() -> None:
    """Top-N is returned in the order the use case provided (router does not re-sort)."""
    rows = [
        {
            "id": "id-aapl",
            "symbol": "AAPL",
            "exchange": "US",
            "market_cap_usd": 3_500_000_000_000.0,
            "currency_code": "USD",
        },
        {
            "id": "id-msft",
            "symbol": "MSFT",
            "exchange": "US",
            "market_cap_usd": 3_100_000_000_000.0,
            "currency_code": "USD",
        },
        {
            "id": "id-nvda",
            "symbol": "NVDA",
            "exchange": "US",
            "market_cap_usd": 2_800_000_000_000.0,
            "currency_code": "USD",
        },
    ]
    _, client, stub = _make_app(use_case_return=(3, rows))

    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=3")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["limit"] == 3
    assert body["offset"] == 0
    assert [r["symbol"] for r in body["results"]] == ["AAPL", "MSFT", "NVDA"]
    assert body["results"][0]["market_cap_usd"] == 3_500_000_000_000.0
    stub.assert_awaited_once()


def test_n_equals_one_returns_single_row() -> None:
    """Edge case: n=1 returns exactly one row."""
    rows = [{"id": "id-aapl", "symbol": "AAPL", "exchange": "US", "market_cap_usd": 1.0, "currency_code": "USD"}]
    _, client, _ = _make_app(use_case_return=(1, rows))
    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["limit"] == 1


def test_n_above_max_returns_422() -> None:
    """FastAPI clamps via Query(le=5000); requests above the cap are rejected."""
    _, client, _ = _make_app(use_case_return=(0, []))
    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=5001")
    # Query(le=5000) → FastAPI emits 422 (validation error) rather than
    # silently clamping. This is the contract the worker depends on: a hard
    # error on bad input rather than a silently smaller response.
    assert resp.status_code == 422


def test_offset_past_end_returns_empty_results() -> None:
    """Offset beyond the dataset returns an empty results list with total preserved."""
    _, client, stub = _make_app(use_case_return=(42, []))
    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=100&offset=10000")
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 42
    assert body["offset"] == 10000
    # Confirm the offset was actually forwarded.
    _, kwargs = stub.call_args
    assert kwargs["offset"] == 10000


def test_null_market_cap_passes_through_as_none() -> None:
    """Rows without market_cap (NULL) keep ``market_cap_usd=None`` in the response."""
    rows = [
        {"id": "id-newco", "symbol": "NEWCO", "exchange": "US", "market_cap_usd": None, "currency_code": "USD"},
    ]
    _, client, _ = _make_app(use_case_return=(1, rows))
    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=10")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["market_cap_usd"] is None


def test_missing_jwt_returns_401() -> None:
    """Without ``X-Internal-JWT`` the route-level dep raises 401."""
    _, client, _ = _make_app(bypass_jwt=False)
    resp = client.get("/internal/v1/instruments/top-by-market-cap?n=10")
    assert resp.status_code == 401


def test_default_n_is_500() -> None:
    """Caller-omitted ``n`` defaults to 500 (matches worker default top_n)."""
    _, client, stub = _make_app(use_case_return=(0, []))
    resp = client.get("/internal/v1/instruments/top-by-market-cap")
    assert resp.status_code == 200
    _, kwargs = stub.call_args
    assert kwargs["n"] == 500
    assert kwargs["offset"] == 0
