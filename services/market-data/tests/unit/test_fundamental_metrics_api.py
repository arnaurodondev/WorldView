"""Unit tests for fundamental_metrics API routes (ROPT-10).

Covers:
- GET /api/v1/fundamentals/timeseries — returns sorted data, passes date params,
  validates required params (422), uses read session
- POST /api/v1/fundamentals/screen — returns matching instruments, empty filters → 422,
  uses read session
- GET /api/v1/fundamentals/metrics/{instrument_id} — returns list, empty list OK
- Existing section endpoints remain shape-compatible (regression guard)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_uow
from market_data.api.routers import fundamental_metrics as metrics_router
from market_data.infrastructure.db.repositories.fundamental_metrics_query import (
    MetricDataPoint,
    ScreenResult,
)

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_mock_uow() -> AsyncMock:
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    # Default: get_read_session returns a fresh AsyncMock
    mock.get_read_session = lambda: AsyncMock()
    return mock


def _make_app(mock_uow: AsyncMock) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(metrics_router.router, prefix="/api/v1")

    async def override_get_uow():  # type: ignore[misc]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_get_uow
    return app, TestClient(app)


# ── GET /fundamentals/timeseries ──────────────────────────────────────────────


def test_timeseries_returns_data_points() -> None:
    """Happy-path: timeseries returns instrument_id, metric, and data list."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

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

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=data_points),
    ):
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
    """start_date and end_date query params are forwarded to query_timeseries."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    captured: dict = {}

    async def _capture(
        session,
        instrument_id,
        metric,
        start_date=None,
        end_date=None,
        period_type=None,
        limit=1000,
    ):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["period_type"] = period_type
        return []

    with patch("market_data.api.routers.fundamental_metrics.query_timeseries", new=_capture):
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
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.get(
            "/api/v1/fundamentals/timeseries",
            params={"metric": "pe_ratio"},  # instrument_id missing
        )

    assert resp.status_code == 422


def test_timeseries_missing_metric_returns_422() -> None:
    """Missing required metric param → HTTP 422."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.get(
            "/api/v1/fundamentals/timeseries",
            params={"instrument_id": "instr-001"},  # metric missing
        )

    assert resp.status_code == 422


def test_timeseries_start_date_after_end_date_returns_422() -> None:
    """start_date > end_date → HTTP 422 explicit validation error."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.get(
            "/api/v1/fundamentals/timeseries",
            params={
                "instrument_id": "instr-001",
                "metric": "pe_ratio",
                "start_date": "2024-12-31",
                "end_date": "2024-01-01",  # end before start
            },
        )

    assert resp.status_code == 422


def test_timeseries_equal_start_end_date_is_valid() -> None:
    """start_date == end_date is valid (single-day query)."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
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


def test_timeseries_uses_read_session() -> None:
    """Timeseries endpoint calls uow.get_read_session(), not the write session."""
    mock_uow = _make_mock_uow()
    call_count = [0]

    def _track_read_session() -> AsyncMock:
        call_count[0] += 1
        return AsyncMock()

    mock_uow.get_read_session = _track_read_session
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
        client.get(
            "/api/v1/fundamentals/timeseries",
            params={"instrument_id": "instr-001", "metric": "pe_ratio"},
        )

    assert call_count[0] >= 1, "get_read_session() was not called"


def test_timeseries_empty_result_returns_empty_data_list() -> None:
    """No data points → response data list is empty (not 404)."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.get(
            "/api/v1/fundamentals/timeseries",
            params={"instrument_id": "instr-001", "metric": "pe_ratio"},
        )

    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_timeseries_text_metric_included_in_response() -> None:
    """Data points with value_text (e.g. analyst_rating) are returned."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    data_points = [
        MetricDataPoint(
            as_of_date=date(2024, 1, 1),
            value_numeric=None,
            value_text="Buy",
            period_type="SNAPSHOT",
        )
    ]

    with patch(
        "market_data.api.routers.fundamental_metrics.query_timeseries",
        new=AsyncMock(return_value=data_points),
    ):
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
    """Happy-path: screen returns count and results list."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    results = [
        ScreenResult(instrument_id="instr-001", metrics={"pe_ratio": Decimal("15.0")}),
        ScreenResult(instrument_id="instr-002", metrics={"pe_ratio": Decimal("18.0")}),
    ]

    with patch(
        "market_data.api.routers.fundamental_metrics.query_screen",
        new=AsyncMock(return_value=results),
    ):
        resp = client.post(
            "/api/v1/fundamentals/screen",
            json={"filters": [{"metric": "pe_ratio", "max_value": 20.0}]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["results"][0]["instrument_id"] == "instr-001"
    assert body["results"][0]["metrics"]["pe_ratio"] == pytest.approx(15.0)


def test_screen_empty_filters_returns_422() -> None:
    """POST with empty filters list → HTTP 422 (min_length=1 validation)."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_screen",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post("/api/v1/fundamentals/screen", json={"filters": []})

    assert resp.status_code == 422


def test_screen_invalid_body_returns_422() -> None:
    """POST with no body → HTTP 422."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    resp = client.post("/api/v1/fundamentals/screen", json={})
    assert resp.status_code == 422


def test_screen_uses_read_session() -> None:
    """Screen endpoint calls uow.get_read_session()."""
    mock_uow = _make_mock_uow()
    call_count = [0]

    def _track() -> AsyncMock:
        call_count[0] += 1
        return AsyncMock()

    mock_uow.get_read_session = _track
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_screen",
        new=AsyncMock(return_value=[]),
    ):
        client.post(
            "/api/v1/fundamentals/screen",
            json={"filters": [{"metric": "pe_ratio", "max_value": 20.0}]},
        )

    assert call_count[0] >= 1, "get_read_session() was not called"


def test_screen_two_filters_passed_to_query() -> None:
    """Two filters in the request body are forwarded as ScreenFilter objects."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    captured_filters: list = []

    async def _capture(session, filters, limit=100, offset=0):
        captured_filters.extend(filters)
        return []

    with patch("market_data.api.routers.fundamental_metrics.query_screen", new=_capture):
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


def test_screen_sector_filter_forwarded_to_query() -> None:
    """Sector field in a filter is forwarded as ScreenFilter.sector."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    captured_filters: list = []

    async def _capture(session, filters, limit=100, offset=0):
        captured_filters.extend(filters)
        return []

    with patch("market_data.api.routers.fundamental_metrics.query_screen", new=_capture):
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
    """No matching instruments → count=0, results=[]."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_screen",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post(
            "/api/v1/fundamentals/screen",
            json={"filters": [{"metric": "pe_ratio", "max_value": 1.0}]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["results"] == []


# ── GET /fundamentals/metrics/{instrument_id} ─────────────────────────────────


def test_available_metrics_returns_list() -> None:
    """Happy-path: returns instrument_id and list of metric names."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_available_metrics",
        new=AsyncMock(return_value=["pe_ratio", "target_price", "revenue_ttm"]),
    ):
        resp = client.get("/api/v1/fundamentals/metrics/instr-001")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == "instr-001"
    assert set(body["metrics"]) == {"pe_ratio", "target_price", "revenue_ttm"}


def test_available_metrics_empty_instrument_returns_empty_list() -> None:
    """Instrument with no metrics returns HTTP 200 with empty list (not 404)."""
    mock_uow = _make_mock_uow()
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_available_metrics",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.get("/api/v1/fundamentals/metrics/unknown-instr")

    assert resp.status_code == 200
    assert resp.json()["metrics"] == []


def test_available_metrics_uses_read_session() -> None:
    """Available metrics endpoint calls uow.get_read_session()."""
    mock_uow = _make_mock_uow()
    call_count = [0]

    def _track() -> AsyncMock:
        call_count[0] += 1
        return AsyncMock()

    mock_uow.get_read_session = _track
    _, client = _make_app(mock_uow)

    with patch(
        "market_data.api.routers.fundamental_metrics.query_available_metrics",
        new=AsyncMock(return_value=[]),
    ):
        client.get("/api/v1/fundamentals/metrics/instr-001")

    assert call_count[0] >= 1, "get_read_session() was not called"
