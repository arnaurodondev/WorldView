"""Unit tests for Securities API (MD-025)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_uow
from market_data.api.routers import securities as securities_router
from market_data.domain.entities import Security

pytestmark = pytest.mark.unit


def _make_security(
    security_id: str = "sec-001",
    figi: str = "BBG000B9XRY4",
    isin: str = "US0378331005",
) -> Security:
    return Security(
        id=security_id,
        figi=figi,
        isin=isin,
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        country="US",
        currency="USD",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(mock_uow: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(securities_router.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    return app, TestClient(app)


def _make_sec_repo(
    figi_result: Security | None = None,
    isin_result: Security | None = None,
    list_result: tuple[list[Security], int] | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.find_by_figi = AsyncMock(return_value=figi_result)
    repo.find_by_isin = AsyncMock(return_value=isin_result)
    repo.list = AsyncMock(return_value=list_result or ([], 0))
    return repo


def test_get_security_by_figi() -> None:
    """GET /api/v1/securities/{id} finds security by FIGI."""
    security = _make_security(figi="BBG000B9XRY4")
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo(figi_result=security)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities/BBG000B9XRY4")
    assert resp.status_code == 200
    assert resp.json()["figi"] == "BBG000B9XRY4"
    assert resp.json()["name"] == "Apple Inc."


def test_get_security_not_found() -> None:
    """GET /api/v1/securities/{id} returns 404 when not found."""
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo()

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities/NOTEXIST")
    assert resp.status_code == 404


def test_list_securities_by_figi() -> None:
    """GET /api/v1/securities?figi=... returns matching security."""
    security = _make_security()
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo(figi_result=security)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities?figi=BBG000B9XRY4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["figi"] == "BBG000B9XRY4"


def test_list_securities_by_isin() -> None:
    """GET /api/v1/securities?isin=... returns matching security."""
    security = _make_security()
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo(isin_result=security)

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities?isin=US0378331005")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["isin"] == "US0378331005"


def test_list_securities_no_filter_returns_all() -> None:
    """GET /api/v1/securities without filters returns paginated list from DB."""
    sec1 = _make_security("sec-001", figi="FIGI1")
    sec2 = _make_security("sec-002", figi="FIGI2")
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo(list_result=([sec1, sec2], 2))

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    assert len(resp.json()["items"]) == 2


def test_list_securities_no_filter_empty_db() -> None:
    """GET /api/v1/securities without filters returns empty list when DB is empty."""
    mock_uow = AsyncMock()
    mock_uow.securities_read = _make_sec_repo(list_result=([], 0))

    _, client = _make_app(mock_uow)
    resp = client.get("/api/v1/securities")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
