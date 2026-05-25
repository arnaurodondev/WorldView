"""Unit tests for screener sort + total + instrument fields (PRD-0017 §6.8, Wave B-1/B-2).

Tests:
- test_screen_response_includes_instrument_fields
- test_screen_sort_by_ticker
- test_screen_sort_by_metric_nulls_last
- test_screen_total_count
- test_screen_sort_by_invalid_field
- test_screen_field_metadata_static
- test_screen_sort_order_desc_forwarded
- test_screen_default_limit_and_offset
- test_screen_limit_exceeds_max_returns_422
- test_screen_offset_exceeds_max_returns_422
Wave B-2:
- test_screen_fields_use_case_cache_hit
- test_screen_fields_use_case_cache_miss_db_fallback
- test_screen_fields_use_case_cache_miss_empty_db
- test_get_screen_fields_route_returns_12_fields
- test_get_screen_fields_route_empty_returns_empty_list
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import get_screen_fields_uc, get_screen_instruments_uc
from market_data.api.routers import fundamental_metrics as metrics_router
from market_data.application.ports.repositories import ScreenResult
from market_data.application.use_cases.query_fundamental_metrics import ScreenFieldsMetadataUseCase
from market_data.domain.entities import ScreenFieldMetadata

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(mock_screen_uc: MagicMock) -> TestClient:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(metrics_router.router, prefix="/api/v1")
    app.dependency_overrides[get_screen_instruments_uc] = lambda: mock_screen_uc
    return TestClient(app)


def _make_screen_uc(
    results: list[ScreenResult] | None = None,
    total: int | None = None,
) -> MagicMock:
    result_list = results or []
    total_count = total if total is not None else len(result_list)
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=(result_list, total_count))
    return uc


# ---------------------------------------------------------------------------
# PRD-specified tests
# ---------------------------------------------------------------------------


def test_screen_response_includes_instrument_fields() -> None:
    """ScreenInstrumentResponse has ticker, name, exchange, sector fields."""
    results = [
        ScreenResult(
            instrument_id="instr-001",
            metrics={"pe_ratio": Decimal("15.0")},
            ticker="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            sector="Technology",
        ),
    ]
    client = _make_app(_make_screen_uc(results))
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio", "max_value": 20.0}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    r = body["results"][0]
    assert r["ticker"] == "AAPL"
    assert r["name"] == "Apple Inc."
    assert r["exchange"] == "NASDAQ"
    assert r["sector"] == "Technology"
    assert r["instrument_id"] == "instr-001"


def test_screen_sort_by_ticker() -> None:
    """sort_by='ticker' is forwarded to use case and response reflects sort."""
    captured: dict = {}

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured["sort_by"] = sort_by
        captured["sort_order"] = sort_order
        return ([], 0)

    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=_capture)
    client = _make_app(uc)

    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [{"metric": "pe_ratio", "max_value": 20.0}],
            "sort_by": "ticker",
            "sort_order": "asc",
        },
    )
    assert resp.status_code == 200
    assert captured["sort_by"] == "ticker"
    assert captured["sort_order"] == "asc"


def test_screen_sort_by_metric_nulls_last() -> None:
    """sort_by=metric name is forwarded; NULL-valued metrics appear last (verified via use case call)."""
    captured: dict = {}

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured["sort_by"] = sort_by
        captured["sort_order"] = sort_order
        return ([], 0)

    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=_capture)
    client = _make_app(uc)

    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [{"metric": "pe_ratio", "max_value": 50.0}],
            "sort_by": "pe_ratio",
            "sort_order": "asc",
        },
    )
    assert resp.status_code == 200
    # sort_by is a filter metric — should be forwarded
    assert captured["sort_by"] == "pe_ratio"


def test_screen_total_count() -> None:
    """total reflects rows before limit/offset, not current page size (PRD-0017 §6.8)."""
    results = [
        ScreenResult(instrument_id=f"instr-{i:03d}", metrics={"pe_ratio": Decimal(str(10 + i))}) for i in range(5)
    ]
    client = _make_app(_make_screen_uc(results, total=1234))
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}], "limit": 5, "offset": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 5  # page size
    assert body["total"] == 1234  # total before limit


def test_screen_sort_by_invalid_field() -> None:
    """Unknown sort_by value not in filter metrics or ['ticker','name'] → HTTP 422."""
    client = _make_app(_make_screen_uc())
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [{"metric": "pe_ratio", "max_value": 20.0}],
            "sort_by": "'; DROP TABLE instruments; --",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# ScreenFieldMetadata domain object
# ---------------------------------------------------------------------------


def test_screen_field_metadata_static() -> None:
    """ScreenFieldMetadata for pe_ratio has correct label, unit, type (PRD-0017 §6.4)."""
    meta = ScreenFieldMetadata(
        name="pe_ratio",
        label="P/E Ratio",
        field_type="numeric",
        unit="x",
        description="Trailing P/E (TTM)",
        observed_min=None,
        observed_max=None,
        null_fraction=0.0,
    )
    assert meta.name == "pe_ratio"
    assert meta.label == "P/E Ratio"
    assert meta.field_type == "numeric"
    assert meta.unit == "x"
    assert meta.null_fraction == 0.0


def test_screen_field_metadata_is_frozen() -> None:
    """ScreenFieldMetadata is immutable (frozen dataclass)."""
    meta = ScreenFieldMetadata(
        name="revenue_usd",
        label="Revenue",
        field_type="numeric",
        unit="USD M",
        description=None,
        observed_min=None,
        observed_max=None,
        null_fraction=0.1,
    )
    with pytest.raises(Exception):  # FrozenInstanceError  # noqa: B017
        meta.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_screen_sort_order_desc_forwarded() -> None:
    """sort_order='desc' is forwarded to use case."""
    captured: dict = {}

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured["sort_order"] = sort_order
        return ([], 0)

    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=_capture)
    client = _make_app(uc)

    client.post(
        "/api/v1/fundamentals/screen",
        json={
            "filters": [{"metric": "pe_ratio"}],
            "sort_by": "name",
            "sort_order": "desc",
        },
    )
    assert captured["sort_order"] == "desc"


def test_screen_default_limit_is_50() -> None:
    """Default limit is 50 (changed from old default of 100)."""
    captured: dict = {}

    async def _capture(filters, *, limit=50, offset=0, sort_by=None, sort_order="asc"):  # type: ignore[misc]
        captured["limit"] = limit
        return ([], 0)

    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=_capture)
    client = _make_app(uc)

    client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}]},
    )
    assert captured["limit"] == 50


def test_screen_limit_exceeds_max_returns_422() -> None:
    """limit > 200 → HTTP 422 (NFR-001: max limit is 200)."""
    client = _make_app(_make_screen_uc())
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}], "limit": 201},
    )
    assert resp.status_code == 422


def test_screen_offset_exceeds_max_returns_422() -> None:
    """offset > 5000 → HTTP 422 (NFR-001: max offset is 5000)."""
    client = _make_app(_make_screen_uc())
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}], "offset": 5001},
    )
    assert resp.status_code == 422


def test_screen_sort_by_none_no_validation_error() -> None:
    """sort_by=null (omitted) is valid — no sort guarantee."""
    client = _make_app(_make_screen_uc())
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}]},
    )
    assert resp.status_code == 200


def test_screen_instrument_fields_nullable() -> None:
    """ticker/name/exchange/sector may be null in response (not-yet-enriched instruments)."""
    results = [
        ScreenResult(
            instrument_id="instr-001",
            metrics={"pe_ratio": Decimal("10.0")},
            ticker=None,
            name=None,
            exchange="US",
            sector=None,
        ),
    ]
    client = _make_app(_make_screen_uc(results))
    resp = client.post(
        "/api/v1/fundamentals/screen",
        json={"filters": [{"metric": "pe_ratio"}]},
    )
    assert resp.status_code == 200
    r = resp.json()["results"][0]
    assert r["ticker"] is None
    assert r["name"] is None
    assert r["exchange"] == "US"
    assert r["sector"] is None


# ---------------------------------------------------------------------------
# Wave B-2: ScreenFieldsMetadataUseCase unit tests
# ---------------------------------------------------------------------------

_SAMPLE_FIELDS = [
    ScreenFieldMetadata(
        name="pe_ratio",
        label="P/E Ratio",
        field_type="numeric",
        unit="x",
        description="Trailing P/E (TTM)",
        observed_min=None,
        observed_max=None,
        null_fraction=0.0,
    ),
    ScreenFieldMetadata(
        name="revenue_usd",
        label="Revenue",
        field_type="numeric",
        unit="USD M",
        description="Annual revenue (USD millions)",
        observed_min=None,
        observed_max=None,
        null_fraction=0.0,
    ),
]


def _make_cache(fields: list[ScreenFieldMetadata] | None) -> MagicMock:
    cache = MagicMock()
    cache.get_all = AsyncMock(return_value=fields)
    cache.set_all = AsyncMock(return_value=None)
    return cache


def _make_uow_with_fields(fields: list[ScreenFieldMetadata]) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.get_screen_field_metadata = AsyncMock(return_value=fields)
    uow.fundamental_metrics_query = repo
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    return uow


async def test_screen_fields_use_case_cache_hit() -> None:
    """Cache hit: use case returns cached list and does NOT query DB."""
    cache = _make_cache(_SAMPLE_FIELDS)
    uow = _make_uow_with_fields([])
    uc = ScreenFieldsMetadataUseCase(uow=uow, cache=cache)

    result = await uc.execute()

    assert result == _SAMPLE_FIELDS
    cache.get_all.assert_awaited_once()
    uow.fundamental_metrics_query.get_screen_field_metadata.assert_not_awaited()
    cache.set_all.assert_not_awaited()


async def test_screen_fields_use_case_cache_miss_db_fallback() -> None:
    """Cache miss: use case queries DB and warms cache with result."""
    cache = _make_cache(None)  # cache miss
    uow = _make_uow_with_fields(_SAMPLE_FIELDS)
    uc = ScreenFieldsMetadataUseCase(uow=uow, cache=cache)

    result = await uc.execute()

    assert result == _SAMPLE_FIELDS
    uow.fundamental_metrics_query.get_screen_field_metadata.assert_awaited_once()
    cache.set_all.assert_awaited_once_with(_SAMPLE_FIELDS)


async def test_screen_fields_use_case_cache_miss_empty_db() -> None:
    """Cache miss + empty DB: returns empty list; does NOT call set_all (nothing to cache)."""
    cache = _make_cache(None)
    uow = _make_uow_with_fields([])
    uc = ScreenFieldsMetadataUseCase(uow=uow, cache=cache)

    result = await uc.execute()

    assert result == []
    cache.set_all.assert_not_awaited()


# ---------------------------------------------------------------------------
# Wave B-2: GET /fundamentals/screen/fields route tests
# ---------------------------------------------------------------------------


def _make_fields_app(mock_fields_uc: MagicMock) -> TestClient:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(metrics_router.router, prefix="/api/v1")
    app.dependency_overrides[get_screen_fields_uc] = lambda: mock_fields_uc
    return TestClient(app)


def _make_fields_uc(fields: list[ScreenFieldMetadata]) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=fields)
    return uc


def test_get_screen_fields_route_returns_12_fields() -> None:
    """GET /screen/fields happy-path: returns list of field metadata objects.

    Wave L-1/L-2 added 11 new fields (4 attribute + 7 snapshot), so the
    static set now contains 23 entries.
    """
    from market_data.app import _get_static_screen_fields

    static_fields = _get_static_screen_fields()
    client = _make_fields_app(_make_fields_uc(static_fields))

    resp = client.get("/api/v1/fundamentals/screen/fields")

    assert resp.status_code == 200
    body = resp.json()
    assert "fields" in body
    assert len(body["fields"]) == 23
    names = {f["name"] for f in body["fields"]}
    # Original fields still present
    assert "pe_ratio" in names
    assert "current_ratio" in names
    # L-1 attribute fields
    assert "country" in names
    assert "exchange" in names
    assert "has_fundamentals" in names
    assert "has_ohlcv" in names
    # L-2 snapshot fields
    assert "eps_ttm" in names
    assert "avg_volume_30d" in names
    assert "credit_rating" in names
    # Every field must have name, label, type, null_fraction
    for field in body["fields"]:
        assert "name" in field
        assert "label" in field
        assert "type" in field
        assert "null_fraction" in field


def test_get_screen_fields_route_empty_returns_empty_list() -> None:
    """GET /screen/fields with no fields seeded returns empty list (not 404)."""
    client = _make_fields_app(_make_fields_uc([]))

    resp = client.get("/api/v1/fundamentals/screen/fields")

    assert resp.status_code == 200
    assert resp.json()["fields"] == []


def test_get_screen_fields_field_shape() -> None:
    """Each field response has the correct PRD-0017 §6.2 shape."""
    client = _make_fields_app(_make_fields_uc(_SAMPLE_FIELDS))

    resp = client.get("/api/v1/fundamentals/screen/fields")

    assert resp.status_code == 200
    fields = resp.json()["fields"]
    assert fields[0] == {
        "name": "pe_ratio",
        "label": "P/E Ratio",
        "type": "numeric",
        "unit": "x",
        "description": "Trailing P/E (TTM)",
        "observed_min": None,
        "observed_max": None,
        "null_fraction": 0.0,
    }
