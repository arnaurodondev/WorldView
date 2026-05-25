"""Unit tests for POST /internal/v1/price/batch — REQ-004 partial-result schema.

The batch endpoint supports two response shapes via the `include_missing`
query parameter (audit task TASK-W0-07):

  * `include_missing=false` (default): legacy `list[PriceSnapshotResponse]`,
    instruments with no data silently omitted. Backwards-compatible with the
    S9 api-gateway batch caller.
  * `include_missing=true`: dict keyed by instrument_id with explicit nulls
    so callers can detect which instruments are missing.

These tests run against a FastAPI TestClient with the cache + read-UoW deps
overridden — no DB required. The resolver internals are bypassed by
monkey-patching the module-level `_resolve_and_cache` helper.

Run with:
    cd services/market-data && \
        ../../.venv312/bin/python -m pytest \
        tests/unit/api/routers/test_price_batch_partial.py -v -m unit
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# The route module — we monkey-patch its `_resolve_and_cache` helper to avoid
# touching the database / cache layers in unit tests.
from market_data.api.dependencies import get_read_uow
from market_data.api.routers import price_snapshot as price_snapshot_router
from market_data.api.schemas.price_snapshot import PriceSnapshotResponse

pytestmark = pytest.mark.unit


# ── Test fixtures ─────────────────────────────────────────────────────────────

# Three valid UUIDs we'll use as instrument_ids.  These are UUIDv4 strings —
# the route validator accepts any RFC-4122 UUID, not just UUIDv7.
_IID_1 = "0190f3a0-dead-beef-cafe-000000000001"
_IID_2 = "0190f3a0-dead-beef-cafe-000000000002"
_IID_3 = "0190f3a0-dead-beef-cafe-000000000003"


def _make_response(instrument_id: str, symbol: str = "AAPL") -> PriceSnapshotResponse:
    """Build a PriceSnapshotResponse for an instrument — used in test stubs."""
    return PriceSnapshotResponse(
        instrument_id=instrument_id,
        symbol=symbol,
        exchange="NASDAQ",
        price="150.00",
        price_change="1.50",
        price_change_pct="1.00",
        timestamp=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
        fetched_at=datetime(2024, 3, 15, 15, 0, 0, tzinfo=UTC),
        source="fresh_quote",
        freshness_status="live",
        stale_reason=None,
        refresh_available=True,
        refresh_cooldown_remaining_sec=0,
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc, no-untyped-def]
    """No-op lifespan so the test app doesn't try to connect to Valkey/DB."""
    yield


def _make_app(
    resolve_results: dict[str, PriceSnapshotResponse | None],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FastAPI, TestClient]:
    """Build a FastAPI test app with the price_snapshot router mounted.

    `resolve_results` is a mapping from instrument_id to the value
    `_resolve_and_cache` should return for that instrument. Any instrument_id
    not in the dict resolves to `None` (simulating "no data available").
    """
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(price_snapshot_router.router, prefix="/internal/v1")

    # The cache is read off `request.app.state.price_snapshot_cache` — a stub
    # is fine because the route never actually calls it (we patch _resolve_and_cache).
    app.state.price_snapshot_cache = MagicMock()

    # Override the read-UoW dep so we don't need a real DB session.
    app.dependency_overrides[get_read_uow] = lambda: MagicMock()

    # Monkey-patch the resolver helper at the module level — the route calls
    # this function directly (not via a class), so monkeypatch.setattr is the
    # cleanest way to inject test results.
    async def _fake_resolve(
        instrument_id: str,
        uow: Any,  # — unused in stub
        cache: Any,  # — unused in stub
    ) -> PriceSnapshotResponse | None:
        return resolve_results.get(instrument_id)

    monkeypatch.setattr(price_snapshot_router, "_resolve_and_cache", _fake_resolve)
    return app, TestClient(app)


# ── Test 1: all instruments resolve (list shape — default) ────────────────────


def test_batch_all_present_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (no include_missing) — all instruments resolve → list of all 3."""
    resolves = {
        _IID_1: _make_response(_IID_1, "AAPL"),
        _IID_2: _make_response(_IID_2, "MSFT"),
        _IID_3: _make_response(_IID_3, "GOOG"),
    }
    _, client = _make_app(resolves, monkeypatch)

    resp = client.post(
        "/internal/v1/price/batch",
        json={"instrument_ids": [_IID_1, _IID_2, _IID_3]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Default shape is a JSON list, not a dict
    assert isinstance(body, list)
    assert len(body) == 3
    assert {item["instrument_id"] for item in body} == {_IID_1, _IID_2, _IID_3}


# ── Test 2: some missing instruments (list shape — silently omits) ────────────


def test_batch_partial_list_shape_omits_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy list shape — instruments with no data are silently omitted.

    This is the documented behaviour BUG-008 calls out: the caller cannot tell
    which instruments were missing.  Verified here so any regression to the
    new dict shape is loud.
    """
    resolves = {
        _IID_1: _make_response(_IID_1, "AAPL"),
        # _IID_2 missing — resolver returns None
        _IID_3: _make_response(_IID_3, "GOOG"),
    }
    _, client = _make_app(resolves, monkeypatch)

    resp = client.post(
        "/internal/v1/price/batch",
        json={"instrument_ids": [_IID_1, _IID_2, _IID_3]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Only 2 of 3 — _IID_2 silently dropped (legacy behaviour preserved)
    assert len(body) == 2
    returned_ids = {item["instrument_id"] for item in body}
    assert returned_ids == {_IID_1, _IID_3}


# ── Test 3: include_missing=true — all instruments resolve (dict shape) ───────


def test_batch_include_missing_all_present_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """include_missing=true — all instruments resolve → dict with non-null values."""
    resolves = {
        _IID_1: _make_response(_IID_1, "AAPL"),
        _IID_2: _make_response(_IID_2, "MSFT"),
        _IID_3: _make_response(_IID_3, "GOOG"),
    }
    _, client = _make_app(resolves, monkeypatch)

    resp = client.post(
        "/internal/v1/price/batch?include_missing=true",
        json={"instrument_ids": [_IID_1, _IID_2, _IID_3]},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Dict shape — top level is a JSON object keyed by instrument_id
    assert isinstance(body, dict)
    assert set(body.keys()) == {_IID_1, _IID_2, _IID_3}
    # All three values are non-null PriceSnapshotResponse objects
    for iid in (_IID_1, _IID_2, _IID_3):
        assert body[iid] is not None
        assert body[iid]["instrument_id"] == iid


# ── Test 4: include_missing=true — some missing (dict shape with explicit nulls) ──


def test_batch_include_missing_some_missing_returns_nulls(monkeypatch: pytest.MonkeyPatch) -> None:
    """include_missing=true — missing instruments appear as explicit null values.

    This is the REQ-004 / BUG-008 fix: the caller can now detect which
    instruments had no available price data.
    """
    resolves = {
        _IID_1: _make_response(_IID_1, "AAPL"),
        # _IID_2 missing
        _IID_3: _make_response(_IID_3, "GOOG"),
    }
    _, client = _make_app(resolves, monkeypatch)

    resp = client.post(
        "/internal/v1/price/batch?include_missing=true",
        json={"instrument_ids": [_IID_1, _IID_2, _IID_3]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    # All requested keys present — none silently dropped
    assert set(body.keys()) == {_IID_1, _IID_2, _IID_3}
    # The missing instrument has an explicit null value
    assert body[_IID_2] is None
    # The present instruments have non-null PriceSnapshotResponse payloads
    assert body[_IID_1] is not None
    assert body[_IID_1]["symbol"] == "AAPL"
    assert body[_IID_3] is not None
    assert body[_IID_3]["symbol"] == "GOOG"


# ── Test 5: include_missing=true — deterministic key order matches input ──────


def test_batch_include_missing_preserves_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Input order of instrument_ids is preserved in the response dict's key order.

    Python 3.7+ dicts are insertion-ordered, and the route iterates
    body.instrument_ids in order — so the JSON object's key iteration order
    is deterministic.  This makes the response forward-compatible for
    clients that rely on positional pairing (uncommon but documented).
    """
    resolves = {
        _IID_1: _make_response(_IID_1, "AAPL"),
        _IID_2: _make_response(_IID_2, "MSFT"),
        _IID_3: _make_response(_IID_3, "GOOG"),
    }
    _, client = _make_app(resolves, monkeypatch)

    # Send the IDs in reverse order — verify the response object's key order
    # mirrors the request order, not the dict-population order of the test fixture.
    resp = client.post(
        "/internal/v1/price/batch?include_missing=true",
        json={"instrument_ids": [_IID_3, _IID_2, _IID_1]},
    )
    assert resp.status_code == 200
    # FastAPI / Pydantic serialise dicts preserving insertion order — and we
    # populate the response dict by iterating body.instrument_ids in order.
    # We compare list(body) (key iteration order) against the input.
    body = resp.json()
    assert list(body.keys()) == [_IID_3, _IID_2, _IID_1]
