"""Unit tests for Fundamentals API (MD-025)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_fundamentals_section_uc
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


def _make_section_uc(
    records_by_section: dict[FundamentalsSection, list[FundamentalsRecord]] | None = None,
    all_records: list[FundamentalsRecord] | None = None,
) -> MagicMock:
    """Build a mock GetFundamentalsSectionUseCase."""
    uc = MagicMock()
    rbs = records_by_section or {}

    async def _execute(instrument_id: str, section: FundamentalsSection) -> list[FundamentalsRecord]:
        return rbs.get(section, [])

    async def _execute_all(instrument_id: str) -> list[FundamentalsRecord]:
        return all_records or []

    uc.execute = AsyncMock(side_effect=_execute)
    uc.execute_all_sections = AsyncMock(side_effect=_execute_all)
    return uc


def _make_app(mock_uc: MagicMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(fundamentals_router.router, prefix="/api/v1")
    app.dependency_overrides[get_fundamentals_section_uc] = lambda: mock_uc
    return app, TestClient(app)


def test_get_fundamentals_all_sections_found() -> None:
    """GET /api/v1/fundamentals/{security_id} returns all matching records."""
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    mock_uc = _make_section_uc(all_records=records)
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/instr-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["security_id"] == "instr-001"
    assert len(data["records"]) == 1


def test_get_fundamentals_not_found() -> None:
    """GET /api/v1/fundamentals/{security_id} returns 404 when no records exist."""
    mock_uc = _make_section_uc(all_records=[])
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/unknown-id")
    assert resp.status_code == 404


def test_get_income_statement() -> None:
    """GET /api/v1/fundamentals/{id}/income-statement returns income statements."""
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.INCOME_STATEMENT: records})
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/instr-001/income-statement")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "income_statement"


def test_get_balance_sheet() -> None:
    """GET /api/v1/fundamentals/{id}/balance-sheet returns balance sheet records."""
    records = [_make_record(FundamentalsSection.BALANCE_SHEET)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.BALANCE_SHEET: records})
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/instr-001/balance-sheet")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "balance_sheet"


def test_get_earnings() -> None:
    """GET /api/v1/fundamentals/{id}/earnings returns earnings history."""
    records = [_make_record(FundamentalsSection.EARNINGS_HISTORY)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.EARNINGS_HISTORY: records})
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/instr-001/earnings")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "earnings_history"


def test_fundamentals_record_data_is_dict() -> None:
    """Fundamentals record response exposes data as a dict."""
    records = [_make_record()]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.INCOME_STATEMENT: records})
    _, client = _make_app(mock_uc)

    resp = client.get("/api/v1/fundamentals/instr-001/income-statement")
    assert resp.status_code == 200
    assert isinstance(resp.json()["records"][0]["data"], dict)


def test_no_infra_import_in_fundamentals_router() -> None:
    """The fundamentals router must not import from the infrastructure layer (QA-013)."""
    import ast
    import importlib
    from pathlib import Path

    spec = importlib.util.find_spec("market_data.api.routers.fundamentals")  # type: ignore[attr-defined]
    assert spec is not None
    source = Path(spec.origin).read_text()  # type: ignore[arg-type]
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    "infrastructure" not in node.module
                ), f"fundamentals router imports from infrastructure: {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "infrastructure" not in alias.name
