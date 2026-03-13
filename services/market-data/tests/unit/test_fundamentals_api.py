"""Unit tests for Fundamentals API (MD-025)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_uow
from market_data.api.routers import fundamentals as fundamentals_router
from market_data.domain.entities import FundamentalsRecord
from market_data.domain.enums import FundamentalsSection, PeriodType

pytestmark = pytest.mark.unit


def _make_record(section: FundamentalsSection = FundamentalsSection.INCOME_STATEMENT) -> FundamentalsRecord:
    return FundamentalsRecord(
        id="rec-001",
        security_id="instr-001",
        section=section,
        period_end=datetime(2023, 12, 31, tzinfo=UTC),
        period_type=PeriodType.ANNUAL,
        data={"revenue": 394_328_000_000.0},
        source="macrotrends",
        ingested_at=datetime(2024, 1, 10, tzinfo=UTC),
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(mock_uow: AsyncMock, patched_records: list[FundamentalsRecord]) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(fundamentals_router.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    return app, TestClient(app)


def _patched_query(records: list[FundamentalsRecord]):  # type: ignore[misc]
    """Return a patch context for query_fundamentals (patched at the router module level)."""

    async def _mock_query(uow: object, security_id: str, section: FundamentalsSection) -> list[FundamentalsRecord]:
        return [r for r in records if r.section == section]

    return patch(
        "market_data.api.routers.fundamentals.query_fundamentals",
        new=_mock_query,
    )


def test_get_fundamentals_all_sections_found() -> None:
    """GET /api/v1/fundamentals/{security_id} returns all matching records."""
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, records)

    with _patched_query(records):
        resp = client.get("/api/v1/fundamentals/instr-001")

    assert resp.status_code == 200
    data = resp.json()
    assert data["security_id"] == "instr-001"
    assert len(data["records"]) == 1


def test_get_fundamentals_not_found() -> None:
    """GET /api/v1/fundamentals/{security_id} returns 404 when no records exist."""
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, [])

    with _patched_query([]):
        resp = client.get("/api/v1/fundamentals/unknown-id")

    assert resp.status_code == 404


def test_get_income_statement() -> None:
    """GET /api/v1/fundamentals/{id}/income-statement returns income statements."""
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, records)

    with _patched_query(records):
        resp = client.get("/api/v1/fundamentals/instr-001/income-statement")

    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "income_statement"


def test_get_balance_sheet() -> None:
    """GET /api/v1/fundamentals/{id}/balance-sheet returns balance sheet records."""
    records = [_make_record(FundamentalsSection.BALANCE_SHEET)]
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, records)

    with _patched_query(records):
        resp = client.get("/api/v1/fundamentals/instr-001/balance-sheet")

    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "balance_sheet"


def test_get_earnings() -> None:
    """GET /api/v1/fundamentals/{id}/earnings returns earnings history."""
    records = [_make_record(FundamentalsSection.EARNINGS_HISTORY)]
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, records)

    with _patched_query(records):
        resp = client.get("/api/v1/fundamentals/instr-001/earnings")

    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "earnings_history"


def test_fundamentals_record_data_is_dict() -> None:
    """Fundamentals record response exposes data as a dict."""
    records = [_make_record()]
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    _, client = _make_app(mock_uow, records)

    with _patched_query(records):
        resp = client.get("/api/v1/fundamentals/instr-001/income-statement")

    assert resp.status_code == 200
    assert isinstance(resp.json()["records"][0]["data"], dict)
