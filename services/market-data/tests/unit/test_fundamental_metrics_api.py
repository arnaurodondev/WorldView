"""Unit tests for fundamental_metrics API routes (ROPT-10).

Covers:
- GET /api/v1/fundamentals/timeseries — returns sorted data, passes date params,
  validates required params (422), uses use case
- POST /api/v1/fundamentals/screen — returns matching instruments, empty filters → 422
- GET /api/v1/fundamentals/metrics/{instrument_id} — returns list, empty list OK
- Architecture guard: no infrastructure imports in router (QA-013)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_available_metrics_uc,
    get_screen_instruments_uc,
    get_timeseries_uc,
)
from market_data.api.routers import fundamental_metrics as metrics_router
from market_data.application.ports.repositories import MetricDataPoint, ScreenResult

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(
    mock_timeseries_uc: MagicMock | None = None,
    mock_screen_uc: MagicMock | None = None,
    mock_metrics_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(metrics_router.router, prefix="/api/v1")

    if mock_timeseries_uc is not None:
        app.dependency_overrides[get_timeseries_uc] = lambda: mock_timeseries_uc
    if mock_screen_uc is not None:
        app.dependency_overrides[get_screen_instruments_uc] = lambda: mock_screen_uc
    if mock_metrics_uc is not None:
        app.dependency_overrides[get_available_metrics_uc] = lambda: mock_metrics_uc

    return app, TestClient(app)


def _make_timeseries_uc(data_points: list[MetricDataPoint] | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=data_points or [])
    return uc


def _make_screen_uc(results: list[ScreenResult] | None = None, total: int | None = None) -> MagicMock:
    uc = MagicMock()
    result_list = results or []
    total_count = total if total is not None else len(result_list)
    uc.execute = AsyncMock(return_value=(result_list, total_count))
    return uc


def _make_metrics_uc(metrics: list[str] | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=metrics or [])
    return uc


# ── GET /fundamentals/timeseries ──────────────────────────────────────────────


def test_timeseries_returns_data_points() -> None:
    """Happy-path: timeseries returns instrument_id, metric, and data list."""
    data_points = [
        MetricDataPoint(
            as_of_date=date(2024, 1, 1),
            value_numeric=Decimal("100"),
            value_text=None,
            period_type="ANNUAL",
        ),
        MetricDataPoint(
            as_of_date=date(2024, 6, 30),
            value_numeric=Decimal("120"),
            value_text=None,
            period_type="QUARTERLY",
        ),
    ]
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc(data_points))

    resp = client.get(
        "/api/v1/fundamentals/timeseries",
        params={"instrument_id": "instr-001", "metric": "pe_ratio"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == "instr-001"
    assert body["metric"] == "pe_ratio"
    assert len(body["data"]) == 2
    assert body["data"][0]["value_numeric"] == pytest.approx(100.0)
    assert body["data"][1]["value_numeric"] == pytest.approx(120.0)


def test_timeseries_date_params_forwarded() -> None:
    """start_date and end_date query params are forwarded to the use case."""
    captured: dict = {}

    mock_uc = MagicMock()

    async def _capture(instrument_id, metric, *, start_date=None, end_date=None, period_type=None, limit=1000):  # type: ignore[misc]
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["period_type"] = period_type
        return []

    mock_uc.execute = AsyncMock(side_effect=_capture)
    _, client = _make_app(mock_timeseries_uc=mock_uc)

    client.get(
        "/api/v1/fundamentals/timeseries",
        params={
            "instrument_id": "instr-001",
            "metric": "pe_ratio",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "period_type": "ANNUAL",
        },
    )
    assert captured["start_date"] == date(2024, 1, 1)
    assert captured["end_date"] == date(2024, 12, 31)
    assert captured["period_type"] == "ANNUAL"


def test_timeseries_missing_instrument_id_returns_422() -> None:
    """Missing required instrument_id param → HTTP 422."""
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc())
    resp = client.get("/api/v1/fundamentals/timeseries", params={"metric": "pe_ratio"})
    assert resp.status_code == 422


def test_timeseries_missing_metric_returns_422() -> None:
    """Missing required metric param → HTTP 422."""
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc())
    resp = client.get("/api/v1/fundamentals/timeseries", params={"instrument_id": "instr-001"})
    assert resp.status_code == 422


def test_timeseries_start_date_after_end_date_returns_422() -> None:
    """start_date > end_date → HTTP 422 explicit validation error."""
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc())
    resp = client.get(
        "/api/v1/fundamentals/timeseries",
        params={
            "instrument_id": "instr-001",
            "metric": "pe_ratio",
            "start_date": "2024-12-31",
            "end_date": "2024-01-01",
        },
    )
    assert resp.status_code == 422


def test_timeseries_equal_start_end_date_is_valid() -> None:
    """start_date == end_date is valid (single-day query)."""
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc())
    resp = client.get(
        "/api/v1/fundamentals/timeseries",
        params={
            "instrument_id": "instr-001",
            "metric": "pe_ratio",
            "start_date": "2024-06-15",
            "end_date": "2024-06-15",
        },
    )
    assert resp.status_code == 200


def test_timeseries_empty_result_returns_empty_data_list() -> None:
    """No data points → response data list is empty (not 404)."""
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc([]))
    resp = client.get(
        "/api/v1/fundamentals/timeseries",
        params={"instrument_id": "instr-001", "metric": "pe_ratio"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_timeseries_text_metric_included_in_response() -> None:
    """Data points with value_text (e.g. analyst_rating) are returned."""
    data_points = [
        MetricDataPoint(
            as_of_date=date(2024, 1, 1),
            value_numeric=None,
            value_text="Buy",
            period_type="SNAPSHOT",
        )
    ]
    _, client = _make_app(mock_timeseries_uc=_make_timeseries_uc(data_points))
    resp = client.get(
        "/api/v1/fundamentals/timeseries",
        params={"instrument_id": "instr-001", "metric": "analyst_rating"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["value_text"] == "Buy"
    assert body["data"][0]["value_numeric"] is None


# ── POST /fundamentals/screen ─────────────────────────────────────────────────


def test_screen_returns_matching_instruments() -> None:
    """Happy-path: screen returns count, total, and results list."""
    results = [
        ScreenResult(instrument_id="instr-001", metrics={"pe_ratio": Decimal("15.0")}),
        ScreenResult(instrument_id="instr-002", metrics={"pe_ratio": Decimal("18.0")}),
    ]
    _, client = _make_app(mock_screen_uc=_make_screen_uc(results, total=42))
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio", "max_value": 20.0}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["total"] == 42
    assert body["results"][0]["instrument_id"] == "instr-001"
    assert body["results"][0]["metrics"]["pe_ratio"] == pytest.approx(15.0)


def test_screen_empty_filters_returns_200() -> None:
    """POST with empty filters list → HTTP 200 (min_length changed to 0 to enable no-filter path).

    WHY: ScreenRequest.filters now defaults to [] and min_length=0 so empty filters
    activates the optimised 'no filter' path (returns all instruments up to limit).
    The old min_length=1 forced callers to send a fallback filter; this was removed.
    """
    _, client = _make_app(mock_screen_uc=_make_screen_uc())
    resp = client.post("/api/v1/fundamentals/screen", json={"filters": []})
    assert resp.status_code == 200


def test_screen_no_body_uses_default_empty_filters() -> None:
    """POST with no body → HTTP 200 (filters defaults to empty list)."""
    _, client = _make_app(mock_screen_uc=_make_screen_uc())
    resp = client.post("/api/v1/fundamentals/screen", json={})
    assert resp.status_code == 200


def test_screen_two_filters_passed_to_use_case() -> None:
    """Two filters in the request body are forwarded as ScreenFilter objects."""
    captured_filters: list = []

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured_filters.extend(filters)
        return ([], 0)

    mock_uc = MagicMock()
    mock_uc.execute = AsyncMock(side_effect=_capture)
    _, client = _make_app(mock_screen_uc=mock_uc)

    client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [
                {"metric": "pe_ratio", "max_value": 20.0},
                {"metric": "roe_ttm", "min_value": 0.15},
            ]
        },
    )
    assert len(captured_filters) == 2
    assert captured_filters[0].metric == "pe_ratio"
    assert captured_filters[0].max_value == pytest.approx(20.0)
    assert captured_filters[1].metric == "roe_ttm"
    assert captured_filters[1].min_value == pytest.approx(0.15)


def test_screen_sector_filter_forwarded() -> None:
    """Sector field in a filter is forwarded as ScreenFilter.sector."""
    captured_filters: list = []

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured_filters.extend(filters)
        return ([], 0)

    mock_uc = MagicMock()
    mock_uc.execute = AsyncMock(side_effect=_capture)
    _, client = _make_app(mock_screen_uc=mock_uc)

    client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [
                {"metric": "pe_ratio", "max_value": 20.0, "sector": "Technology"},
                {"metric": "roe_ttm", "min_value": 0.15},
            ]
        },
    )
    assert len(captured_filters) == 2
    assert captured_filters[0].sector == "Technology"
    assert captured_filters[1].sector is None


def test_screen_no_results_returns_empty() -> None:
    """No matching instruments → count=0, total=0, results=[]."""
    _, client = _make_app(mock_screen_uc=_make_screen_uc([]))
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio", "max_value": 1.0}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["total"] == 0
    assert body["results"] == []


# ── GET /fundamentals/metrics/{instrument_id} ─────────────────────────────────


def test_available_metrics_returns_list() -> None:
    """Happy-path: returns instrument_id and list of metric names."""
    _, client = _make_app(mock_metrics_uc=_make_metrics_uc(["pe_ratio", "target_price", "revenue_ttm"]))
    resp = client.get("/api/v1/fundamentals/metrics/instr-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == "instr-001"
    assert set(body["metrics"]) == {"pe_ratio", "target_price", "revenue_ttm"}


def test_available_metrics_empty_instrument_returns_empty_list() -> None:
    """Instrument with no metrics returns HTTP 200 with empty list (not 404)."""
    _, client = _make_app(mock_metrics_uc=_make_metrics_uc([]))
    resp = client.get("/api/v1/fundamentals/metrics/unknown-instr")
    assert resp.status_code == 200
    assert resp.json()["metrics"] == []


def test_no_infra_import_in_fundamental_metrics_router() -> None:
    """The fundamental_metrics router must not import from infrastructure (QA-013)."""
    import ast
    import importlib
    from pathlib import Path

    spec = importlib.util.find_spec("market_data.api.routers.fundamental_metrics")  # type: ignore[attr-defined]
    assert spec is not None
    source = Path(spec.origin).read_text()  # type: ignore[arg-type]
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert (
                "infrastructure" not in node.module
            ), f"fundamental_metrics router imports from infrastructure: {node.module}"
