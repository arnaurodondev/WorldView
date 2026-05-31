"""Unit tests for /internal/v1/market/tape (PLAN-0102 W3 T-W3-01).

We stub the per-symbol resolver because the real one walks SQLAlchemy
models that require a live DB. The cache + JWT layers are tested with
the resolver stubbed out so failures here surface as routing bugs not
DB-layer bugs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import require_internal_jwt
from market_data.api.routers import internal_market_tape

pytestmark = pytest.mark.unit


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


class _DummySession:
    """Sentinel — the stubbed _resolve_one ignores this."""


def _install_read_factory(app: FastAPI) -> None:
    @asynccontextmanager
    async def _open() -> Any:  # type: ignore[misc]
        yield _DummySession()

    def _factory() -> Any:
        return _open()

    app.state.read_session_factory = _factory
    # No Valkey on app.state — the router treats getattr(...) is None as
    # "no cache wired" and skips the cache code path. This isolates the
    # tests from cache state.
    app.state.valkey = None


def _make_app(*, bypass_jwt: bool = True) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(internal_market_tape.router, prefix="/internal/v1")
    _install_read_factory(app)
    if bypass_jwt:
        app.dependency_overrides[require_internal_jwt] = lambda: None
    return app, TestClient(app)


# ── _classify_session unit tests ────────────────────────────────────────────


def test_classify_session_premkt() -> None:
    from datetime import UTC, datetime

    assert internal_market_tape._classify_session(datetime(2026, 5, 29, 7, 0, tzinfo=UTC)) == "pre-mkt"


def test_classify_session_open() -> None:
    from datetime import UTC, datetime

    assert internal_market_tape._classify_session(datetime(2026, 5, 29, 15, 0, tzinfo=UTC)) == "open"


def test_classify_session_after_hours() -> None:
    from datetime import UTC, datetime

    assert internal_market_tape._classify_session(datetime(2026, 5, 29, 22, 0, tzinfo=UTC)) == "after-hours"


def test_classify_session_closed() -> None:
    from datetime import UTC, datetime

    assert internal_market_tape._classify_session(datetime(2026, 5, 29, 1, 0, tzinfo=UTC)) == "closed"


# ── Endpoint tests (stubbing _resolve_one to isolate routing) ───────────────


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, results: dict[str, dict]) -> AsyncMock:
    """Stub _resolve_one so the test controls per-symbol output.

    ``results`` maps symbol → kwargs for TapeTickerResponse. Any symbol not
    in the map gets the documented ``session="unavailable"`` shape so we
    exercise the graceful-degradation path.
    """

    async def _stub(_session: Any, symbol: str, _now: Any, session_label: str) -> Any:
        data = results.get(symbol.upper(), {})
        return internal_market_tape.TapeTickerResponse(
            symbol=symbol.upper(),
            last_close=data.get("last_close"),
            premkt_price=data.get("premkt_price"),
            premkt_pct=data.get("premkt_pct"),
            session=data.get("session", session_label) if data else "unavailable",
        )

    stub = AsyncMock(side_effect=_stub)
    monkeypatch.setattr(internal_market_tape, "_resolve_one", stub)
    return stub


def test_happy_path_three_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPY/QQQ/VIX all resolve → response carries 3 tickers in input order."""
    _patch_resolver(
        monkeypatch,
        {
            "SPY": {"last_close": 542.13, "premkt_price": 543.20, "premkt_pct": 0.20},
            "QQQ": {"last_close": 469.55, "premkt_price": 470.50, "premkt_pct": 0.20},
            "VIX": {"last_close": 14.2, "premkt_price": 14.3, "premkt_pct": 0.70},
        },
    )
    _, client = _make_app()

    resp = client.get("/internal/v1/market/tape?symbols=SPY,QQQ,VIX")
    assert resp.status_code == 200
    body = resp.json()
    assert "as_of" in body
    assert [t["symbol"] for t in body["tickers"]] == ["SPY", "QQQ", "VIX"]
    assert body["tickers"][0]["premkt_pct"] == 0.20


def test_unknown_symbol_returns_unavailable_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A symbol the resolver does not know about must surface as session=unavailable, not 500."""
    _patch_resolver(monkeypatch, {})  # no symbols known
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=ZZZNOTREAL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tickers"][0]["session"] == "unavailable"
    assert body["tickers"][0]["premkt_price"] is None
    assert body["tickers"][0]["premkt_pct"] is None


def test_mixed_known_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Partial responses — known tickers resolve, unknown ones tagged unavailable."""
    _patch_resolver(
        monkeypatch,
        {"SPY": {"last_close": 540.0, "premkt_price": 541.0, "premkt_pct": 0.185}},
    )
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=SPY,FAKETICKER")
    assert resp.status_code == 200
    tickers = resp.json()["tickers"]
    assert tickers[0]["symbol"] == "SPY"
    assert tickers[0]["premkt_pct"] == 0.185
    assert tickers[1]["symbol"] == "FAKETICKER"
    assert tickers[1]["session"] == "unavailable"


def test_dedup_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated symbols are collapsed (dedup preserves first-seen order)."""
    stub = _patch_resolver(monkeypatch, {"SPY": {"last_close": 540.0, "premkt_price": 541.0, "premkt_pct": 0.185}})
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=SPY,SPY,SPY")
    assert resp.status_code == 200
    # The router de-dups before fanning out — stub should have been awaited once.
    assert stub.await_count == 1
    assert len(resp.json()["tickers"]) == 1


def test_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Symbols are uppercased — `spy` and `SPY` collapse."""
    stub = _patch_resolver(monkeypatch, {"SPY": {"last_close": 540.0, "premkt_price": 541.0, "premkt_pct": 0.185}})
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=spy,SPY")
    assert resp.status_code == 200
    assert stub.await_count == 1


def test_too_many_symbols_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 20-symbol cap is enforced (protects DB from misconfigured callers)."""
    _patch_resolver(monkeypatch, {})
    _, client = _make_app()
    symbols = ",".join(f"T{i}" for i in range(21))
    resp = client.get(f"/internal/v1/market/tape?symbols={symbols}")
    assert resp.status_code == 422


def test_empty_symbols_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty symbols param (e.g. trailing comma only) is rejected."""
    _patch_resolver(monkeypatch, {})
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=,,,")
    assert resp.status_code == 422


def test_missing_jwt_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without X-Internal-JWT the route-level dep raises 401."""
    _patch_resolver(monkeypatch, {})
    _, client = _make_app(bypass_jwt=False)
    resp = client.get("/internal/v1/market/tape?symbols=SPY")
    assert resp.status_code == 401


# ── Two-tier fallback (PLAN-0103 W7 / BP-628) ───────────────────────────────


def test_prior_close_fallback_when_no_intraday(monkeypatch: pytest.MonkeyPatch) -> None:
    """No intraday data but a recent daily bar → session="prior_close".

    Regression for FQA-02: the live brief was showing "Not available" for
    SPY/QQQ/VIX whenever the request landed outside the 12 h intraday
    window even though OHLCV daily bars were present. The resolver now
    falls back to ``last_close`` and labels the row ``prior_close`` so the
    brief renderer can show "SPY 521.40 (prior close)" rather than dropping
    the Tape section.
    """
    _patch_resolver(
        monkeypatch,
        {
            "SPY": {
                "last_close": 521.40,
                "premkt_price": 521.40,
                "premkt_pct": 0.55,
                "session": "prior_close",
            },
        },
    )
    _, client = _make_app()
    resp = client.get("/internal/v1/market/tape?symbols=SPY")
    assert resp.status_code == 200
    body = resp.json()
    row = body["tickers"][0]
    assert row["symbol"] == "SPY"
    assert row["session"] == "prior_close"
    assert row["last_close"] == 521.40
    # When session=prior_close, premkt_price MUST be a real number so the
    # brief never renders "Not available" for symbols with OHLCV data.
    assert row["premkt_price"] is not None
    assert row["session"] != "unavailable"


def test_resolve_one_uses_prior_close_when_intraday_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct unit test on ``_resolve_one``: two daily bars + no intraday → prior_close.

    Builds an in-memory fake session that returns:
      * a known instrument_id for symbol="SPY"
      * two daily bars (latest 521.40, prior 518.55) → day-over-day = +0.55%
      * empty intraday + empty quote

    The function must return ``session="prior_close"``, ``last_close=521.40``,
    ``premkt_price=521.40``, ``premkt_pct ≈ 0.55``.
    """
    from datetime import UTC, datetime
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock

    # Fake instrument_id resolution: scalar_one_or_none()
    instrument_result = MagicMock()
    instrument_result.scalar_one_or_none = MagicMock(return_value="instr-1")

    # Fake daily-bars query: .all() returns two rows, each a tuple-like (close,)
    daily_row_1 = MagicMock()
    daily_row_1.__getitem__ = lambda self, i: (Decimal("521.40"),)[i]
    daily_row_2 = MagicMock()
    daily_row_2.__getitem__ = lambda self, i: (Decimal("518.55"),)[i]
    daily_result = MagicMock()
    daily_result.all = MagicMock(return_value=[daily_row_1, daily_row_2])

    # Fake intraday query: .first() returns None (no intraday bar).
    intraday_result = MagicMock()
    intraday_result.first = MagicMock(return_value=None)

    # Fake quote query: .first() returns None (no quote row).
    quote_result = MagicMock()
    quote_result.first = MagicMock(return_value=None)

    call_results = [instrument_result, daily_result, intraday_result, quote_result]

    session = MagicMock()
    session.execute = AsyncMock(side_effect=call_results)

    import asyncio

    out = asyncio.run(
        internal_market_tape._resolve_one(
            session,
            "SPY",
            datetime(2026, 5, 30, 6, 0, tzinfo=UTC),
            "pre-mkt",
        )
    )

    assert out.session == "prior_close"
    assert out.last_close == 521.40
    assert out.premkt_price == 521.40
    assert out.premkt_pct is not None
    # (521.40 - 518.55) / 518.55 * 100 ≈ 0.5496…
    assert abs(out.premkt_pct - 0.5496) < 0.01


def test_resolve_one_unavailable_when_no_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    """No intraday AND no daily bars → session="unavailable" (true gap).

    This is the only case where the brief should drop the row.
    """
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock

    instrument_result = MagicMock()
    instrument_result.scalar_one_or_none = MagicMock(return_value="instr-1")
    # Empty daily-bars list.
    daily_result = MagicMock()
    daily_result.all = MagicMock(return_value=[])
    intraday_result = MagicMock()
    intraday_result.first = MagicMock(return_value=None)
    quote_result = MagicMock()
    quote_result.first = MagicMock(return_value=None)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[instrument_result, daily_result, intraday_result, quote_result])

    import asyncio

    out = asyncio.run(
        internal_market_tape._resolve_one(
            session,
            "ZZZ",
            datetime(2026, 5, 30, 6, 0, tzinfo=UTC),
            "pre-mkt",
        )
    )
    assert out.session == "unavailable"
    assert out.last_close is None
    assert out.premkt_price is None
