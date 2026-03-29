"""Unit tests for Securities API (MD-025)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_list_securities_uc, get_security_uc
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


def _make_app(
    mock_get_uc: MagicMock | None = None,
    mock_list_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(securities_router.router, prefix="/api/v1")
    if mock_get_uc is not None:
        app.dependency_overrides[get_security_uc] = lambda: mock_get_uc
    if mock_list_uc is not None:
        app.dependency_overrides[get_list_securities_uc] = lambda: mock_list_uc
    return app, TestClient(app)


def _make_get_uc(result: Security | None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def _make_list_uc(result: tuple[list[Security], int]) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def test_get_security_by_figi() -> None:
    """GET /api/v1/securities/{id} finds security by FIGI."""
    security = _make_security(figi="BBG000B9XRY4")
    _, client = _make_app(mock_get_uc=_make_get_uc(security))
    resp = client.get("/api/v1/securities/BBG000B9XRY4")
    assert resp.status_code == 200
    assert resp.json()["figi"] == "BBG000B9XRY4"
    assert resp.json()["name"] == "Apple Inc."


def test_get_security_not_found() -> None:
    """GET /api/v1/securities/{id} returns 404 when not found."""
    _, client = _make_app(mock_get_uc=_make_get_uc(None))
    resp = client.get("/api/v1/securities/NOTEXIST")
    assert resp.status_code == 404


def test_list_securities_by_figi() -> None:
    """GET /api/v1/securities?figi=... returns matching security."""
    security = _make_security()
    _, client = _make_app(mock_list_uc=_make_list_uc(([security], 1)))
    resp = client.get("/api/v1/securities?figi=BBG000B9XRY4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["figi"] == "BBG000B9XRY4"


def test_list_securities_by_isin() -> None:
    """GET /api/v1/securities?isin=... returns matching security."""
    security = _make_security()
    _, client = _make_app(mock_list_uc=_make_list_uc(([security], 1)))
    resp = client.get("/api/v1/securities?isin=US0378331005")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["isin"] == "US0378331005"


def test_list_securities_no_filter_returns_all() -> None:
    """GET /api/v1/securities without filters returns paginated list from DB."""
    sec1 = _make_security("sec-001", figi="FIGI1")
    sec2 = _make_security("sec-002", figi="FIGI2")
    _, client = _make_app(mock_list_uc=_make_list_uc(([sec1, sec2], 2)))
    resp = client.get("/api/v1/securities")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    assert len(resp.json()["items"]) == 2


def test_list_securities_no_filter_empty_db() -> None:
    """GET /api/v1/securities without filters returns empty list when DB is empty."""
    _, client = _make_app(mock_list_uc=_make_list_uc(([], 0)))
    resp = client.get("/api/v1/securities")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
