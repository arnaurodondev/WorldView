"""Unit tests for /internal/v1/calendar/earnings (PLAN-0102 W3 T-W3-02).

We stub the SQLAlchemy query layer via a fake session because the real
query joins ``earnings_calendar`` x ``instruments`` which would require
a live DB.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import require_internal_jwt
from market_data.api.routers import internal_earnings_calendar

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    """Minimal AsyncSession stand-in — only ``execute`` is exercised."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)


def _install_factory(app: FastAPI, rows: list[tuple[Any, ...]]) -> None:
    @asynccontextmanager
    async def _open() -> Any:  # type: ignore[misc]
        yield _FakeSession(rows)

    def _factory() -> Any:
        return _open()

    app.state.read_session_factory = _factory
    app.state.valkey = None


def _make_app(
    *,
    rows: list[tuple[Any, ...]] | None = None,
    bypass_jwt: bool = True,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(internal_earnings_calendar.router, prefix="/internal/v1")
    _install_factory(app, rows or [])
    if bypass_jwt:
        app.dependency_overrides[require_internal_jwt] = lambda: None
    return app, TestClient(app)


def test_happy_path_returns_events_sorted() -> None:
    """A handful of rows surface as events ordered by the query."""
    rows = [
        # (symbol, report_date, before_after, eps_estimate)
        ("NVDA", date(2026, 5, 30), "AfterMarket", 0.83),
        ("CRM", date(2026, 5, 31), "AfterMarket", 1.55),
    ]
    _, client = _make_app(rows=rows)
    resp = client.get("/internal/v1/calendar/earnings?from=2026-05-29&to=2026-06-05")
    assert resp.status_code == 200
    body = resp.json()
    assert body["from"] == "2026-05-29"
    assert body["to"] == "2026-06-05"
    assert len(body["events"]) == 2
    e0 = body["events"][0]
    assert e0["symbol"] == "NVDA"
    assert e0["report_date"] == "2026-05-30"
    assert e0["when"] == "AMC"
    assert e0["consensus_eps"] == 0.83
    assert e0["entity_id"] is None  # not modelled on instruments
    assert e0["period"] is None
    assert e0["consensus_rev_usd"] is None


def test_empty_range_returns_empty_events() -> None:
    """When the query yields nothing, ``events`` is [] (not omitted, not 500)."""
    _, client = _make_app(rows=[])
    resp = client.get("/internal/v1/calendar/earnings?from=2026-05-29&to=2026-05-30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []


def test_to_before_from_returns_422() -> None:
    """Bad date ordering must be rejected up-front."""
    _, client = _make_app(rows=[])
    resp = client.get("/internal/v1/calendar/earnings?from=2026-06-05&to=2026-05-29")
    assert resp.status_code == 422


def test_range_too_large_returns_422() -> None:
    """Range cap protects the DB from runaway queries."""
    _, client = _make_app(rows=[])
    resp = client.get("/internal/v1/calendar/earnings?from=2026-01-01&to=2026-12-31")
    assert resp.status_code == 422


def test_when_tag_mapping() -> None:
    """EODHD ``BeforeMarket`` → ``BMO``, ``DuringMarket`` → ``DMH``, unknown passes through."""
    assert internal_earnings_calendar._when_tag("BeforeMarket") == "BMO"
    assert internal_earnings_calendar._when_tag("AfterMarket") == "AMC"
    assert internal_earnings_calendar._when_tag("DuringMarket") == "DMH"
    assert internal_earnings_calendar._when_tag(None) is None
    # Unknown values pass through verbatim so we never silently drop info.
    assert internal_earnings_calendar._when_tag("WEIRD") == "WEIRD"


def test_null_eps_estimate_surfaces_as_none() -> None:
    """NULL EPS estimate (typical for forward earnings) is preserved as null."""
    rows = [("NVDA", date(2026, 5, 30), None, None)]
    _, client = _make_app(rows=rows)
    resp = client.get("/internal/v1/calendar/earnings?from=2026-05-29&to=2026-06-05")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"][0]["consensus_eps"] is None
    assert body["events"][0]["when"] is None


def test_missing_jwt_returns_401() -> None:
    """Auth gate fires without X-Internal-JWT."""
    _, client = _make_app(rows=[], bypass_jwt=False)
    resp = client.get("/internal/v1/calendar/earnings?from=2026-05-29&to=2026-06-05")
    assert resp.status_code == 401


def test_db_exception_returns_empty_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-open contract — a DB error must still return a 200 with empty events."""

    class _BadSession:
        async def execute(self, _stmt: Any) -> Any:
            raise RuntimeError("simulated DB failure")

    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(internal_earnings_calendar.router, prefix="/internal/v1")

    @asynccontextmanager
    async def _open() -> Any:  # type: ignore[misc]
        yield _BadSession()

    def _factory() -> Any:
        return _open()

    app.state.read_session_factory = _factory
    app.state.valkey = None
    app.dependency_overrides[require_internal_jwt] = lambda: None

    client = TestClient(app)
    resp = client.get("/internal/v1/calendar/earnings?from=2026-05-29&to=2026-06-05")
    assert resp.status_code == 200
    assert resp.json()["events"] == []
