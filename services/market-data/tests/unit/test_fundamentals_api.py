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

# PLAN-0059 W0 fix F-010 added a UUID pattern constraint to the instrument_id
# path parameter so non-UUID paths return 422 (preventing asyncpg DataError on
# the screener route collision). Tests must use valid UUID strings as IDs.
INSTR_UUID = "00000000-0000-0000-0000-000000000001"
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000099"


def _make_record(section: FundamentalsSection = FundamentalsSection.INCOME_STATEMENT) -> FundamentalsRecord:
    return FundamentalsRecord(
        id="rec-001",
        security_id=INSTR_UUID,
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

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["security_id"] == INSTR_UUID
    assert len(data["records"]) == 1


def test_get_fundamentals_not_found() -> None:
    """GET /api/v1/fundamentals/{security_id} returns 404 when no records exist."""
    mock_uc = _make_section_uc(all_records=[])
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{UNKNOWN_UUID}")
    assert resp.status_code == 404


def test_get_income_statement() -> None:
    """GET /api/v1/fundamentals/{id}/income-statement returns income statements."""
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.INCOME_STATEMENT: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/income-statement")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "income_statement"


def test_get_balance_sheet() -> None:
    """GET /api/v1/fundamentals/{id}/balance-sheet returns balance sheet records."""
    records = [_make_record(FundamentalsSection.BALANCE_SHEET)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.BALANCE_SHEET: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/balance-sheet")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "balance_sheet"


def test_get_earnings() -> None:
    """GET /api/v1/fundamentals/{id}/earnings returns earnings history."""
    records = [_make_record(FundamentalsSection.EARNINGS_HISTORY)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.EARNINGS_HISTORY: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/earnings")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "earnings_history"


def test_fundamentals_record_data_is_dict() -> None:
    """Fundamentals record response exposes data as a dict."""
    records = [_make_record()]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.INCOME_STATEMENT: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/income-statement")
    assert resp.status_code == 200
    assert isinstance(resp.json()["records"][0]["data"], dict)


# ── PLAN-0041 Wave A-1: new section endpoints ─────────────────────────────────


def test_get_technicals_snapshot() -> None:
    """GET /api/v1/fundamentals/{id}/technicals-snapshot returns technicals."""
    records = [_make_record(FundamentalsSection.TECHNICALS_SNAPSHOT)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.TECHNICALS_SNAPSHOT: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/technicals-snapshot")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "technicals_snapshot"


def test_get_share_statistics() -> None:
    """GET /api/v1/fundamentals/{id}/share-statistics returns share statistics."""
    records = [_make_record(FundamentalsSection.SHARE_STATISTICS)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.SHARE_STATISTICS: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/share-statistics")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "share_statistics"


def test_get_splits_dividends() -> None:
    """GET /api/v1/fundamentals/{id}/splits-dividends returns splits/dividend history."""
    records = [_make_record(FundamentalsSection.SPLITS_DIVIDENDS)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.SPLITS_DIVIDENDS: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/splits-dividends")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "splits_dividends"


def test_get_earnings_trend() -> None:
    """GET /api/v1/fundamentals/{id}/earnings-trend returns forward earnings estimates."""
    records = [_make_record(FundamentalsSection.EARNINGS_TREND)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.EARNINGS_TREND: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/earnings-trend")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "earnings_trend"


def test_get_earnings_annual_trend() -> None:
    """GET /api/v1/fundamentals/{id}/earnings-annual-trend returns annual earnings projections."""
    records = [_make_record(FundamentalsSection.EARNINGS_ANNUAL_TREND)]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.EARNINGS_ANNUAL_TREND: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/earnings-annual-trend")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["section"] == "earnings_annual_trend"


def test_section_endpoint_returns_empty_list_when_no_data() -> None:
    """Section endpoints return 200 with empty records list when no data exists."""
    # WHY: Unlike the all-sections endpoint (which returns 404 on empty), individual
    # section endpoints return empty lists — the instrument may simply lack that data.
    mock_uc = _make_section_uc(records_by_section={})
    _, client = _make_app(mock_uc)

    for path in [
        "technicals-snapshot",
        "share-statistics",
        "splits-dividends",
        "earnings-trend",
        "earnings-annual-trend",
    ]:
        resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/{path}")
        assert resp.status_code == 200, f"Expected 200 for /{path}, got {resp.status_code}"
        assert resp.json()["records"] == [], f"Expected empty records for /{path}"


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


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0095 W2 T-W2-01: POST /v1/fundamentals/batch tests.
# These exercise the per-ticker fan-out logic with mocked use cases so we
# verify status routing (ok/error), partial-failure isolation, and the cap.
# ─────────────────────────────────────────────────────────────────────────────


def _make_history_uc(per_instrument: dict[str, list[dict]] | None = None) -> MagicMock:
    """Mock GetFundamentalsHistoryUseCase.execute(instrument_id=, periods=)."""
    mapping = per_instrument or {}
    uc = MagicMock()

    async def _execute(*, instrument_id, periods):  # type: ignore[no-untyped-def]
        # Lookup by the instrument UUID string so the route can vary its inputs.
        return {"periods": mapping.get(str(instrument_id), [])}

    uc.execute = AsyncMock(side_effect=_execute)
    return uc


def _make_lookup_uc(symbol_to_instr_id: dict[str, str]) -> MagicMock:
    """Mock InstrumentLookupUseCase.execute(symbol=) → result.instrument.id.

    Symbols not present raise InstrumentNotFoundError to mirror real behaviour.
    """
    from market_data.domain.errors import InstrumentNotFoundError

    uc = MagicMock()

    async def _execute(*, id=None, isin=None, symbol=None):  # type: ignore[no-untyped-def]  # noqa: A002
        if symbol is None or symbol not in symbol_to_instr_id:
            raise InstrumentNotFoundError(f"Instrument not found: symbol={symbol!r}")
        instr = MagicMock()
        instr.id = symbol_to_instr_id[symbol]
        instr.symbol = symbol
        result = MagicMock()
        result.instrument = instr
        return result

    uc.execute = AsyncMock(side_effect=_execute)
    return uc


def _make_batch_app(history_uc: MagicMock, lookup_uc: MagicMock) -> tuple[FastAPI, TestClient]:
    from market_data.api.dependencies import get_fundamentals_history_uc, get_lookup_instrument_uc

    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(fundamentals_router.router, prefix="/v1")
    app.dependency_overrides[get_fundamentals_history_uc] = lambda: history_uc
    app.dependency_overrides[get_lookup_instrument_uc] = lambda: lookup_uc
    return app, TestClient(app)


def test_fundamentals_batch_returns_per_ticker_status() -> None:
    """Mixed input — 2 known tickers + 1 unknown — yields ok/error per ticker.

    Asserts the wave-acceptance behaviour from PLAN-0095 W2 T-W2-01: an unknown
    ticker is reported as ``status="error"`` but does NOT fail the whole batch.
    """
    aapl_id = "00000000-0000-0000-0000-00000000aaaa"
    nvda_id = "00000000-0000-0000-0000-00000000bbbb"
    history_uc = _make_history_uc(
        {
            aapl_id: [{"period": "Q4 2024", "period_end_date": "2024-12-31", "revenue": 1.0}],
            nvda_id: [{"period": "Q4 2024", "period_end_date": "2024-12-31", "revenue": 2.0}],
        }
    )
    lookup_uc = _make_lookup_uc({"AAPL": aapl_id, "NVDA": nvda_id})
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post(
        "/v1/fundamentals/batch",
        json={"tickers": ["AAPL", "BADTICKER", "NVDA"], "periods": 4},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"]["AAPL"]["status"] == "ok"
    assert body["results"]["AAPL"]["periods"][0]["revenue"] == 1.0
    assert body["results"]["NVDA"]["status"] == "ok"
    assert body["results"]["BADTICKER"]["status"] == "error"
    # PLAN-0097 T-W3-04: typed reason codes, NOT raw str(exc).
    # Unknown ticker → InstrumentNotFoundError → "invalid_ticker" code.
    assert body["results"]["BADTICKER"]["reason"] == "invalid_ticker"


def test_fundamentals_batch_rejects_oversized_list() -> None:
    """26 tickers > 25 cap → HTTP 422 (no per-ticker fan-out attempted)."""
    history_uc = _make_history_uc()
    lookup_uc = _make_lookup_uc({})
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post(
        "/v1/fundamentals/batch",
        json={"tickers": [f"T{i}" for i in range(26)], "periods": 4},
    )
    assert resp.status_code == 422


def test_fundamentals_batch_all_empty() -> None:
    """All known tickers but no fundamentals rows → status="ok" with empty periods.

    Distinguishes the "data not ingested yet" case from the "ticker unknown"
    case so the rag-chat handler can render a different message.
    """
    aapl_id = "00000000-0000-0000-0000-00000000aaaa"
    history_uc = _make_history_uc({aapl_id: []})  # no periods recorded
    lookup_uc = _make_lookup_uc({"AAPL": aapl_id})
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post("/v1/fundamentals/batch", json={"tickers": ["AAPL"], "periods": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"]["AAPL"]["status"] == "ok"
    assert body["results"]["AAPL"]["periods"] == []


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0097 T-W3-02: parallel ticker resolution.
# T-W3-04: sanitised typed reason codes — str(exc) never leaks to body.
# ─────────────────────────────────────────────────────────────────────────────


def test_fundamentals_batch_resolves_tickers_in_parallel() -> None:
    """The N ticker→instrument_id lookups must run concurrently, not serially.

    PLAN-0097 T-W3-02. Strategy: make ``lookup_uc.execute`` sleep 100 ms per
    call; with N=5 sequential calls total wall-clock would be ≥500 ms, while
    a parallel ``asyncio.gather`` finishes in ~100 ms. We assert <300 ms to
    give CI generous headroom but still catch a regression to serial.
    """
    import asyncio
    import time

    from market_data.domain.errors import InstrumentNotFoundError

    tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META"]
    ids = {t: f"00000000-0000-0000-0000-0000{i:08d}" for i, t in enumerate(tickers)}

    lookup_uc = MagicMock()

    async def _slow_lookup(*, id=None, isin=None, symbol=None):  # type: ignore[no-untyped-def]  # noqa: A002
        # 100 ms per call. Serial total = ~500 ms; parallel = ~100 ms.
        await asyncio.sleep(0.1)
        if symbol not in ids:
            raise InstrumentNotFoundError(f"Instrument not found: {symbol}")
        instr = MagicMock()
        instr.id = ids[symbol]
        instr.symbol = symbol
        result = MagicMock()
        result.instrument = instr
        return result

    lookup_uc.execute = AsyncMock(side_effect=_slow_lookup)

    history_uc = _make_history_uc({iid: [] for iid in ids.values()})
    _, client = _make_batch_app(history_uc, lookup_uc)

    start = time.perf_counter()
    resp = client.post(
        "/v1/fundamentals/batch",
        json={"tickers": tickers, "periods": 4},
    )
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    # Serial bound = 5 x 0.1s = 0.5s. Parallel ideal ~0.1s. 0.3s threshold
    # gives ~3x headroom over the parallel ideal so flakiness on a busy CI
    # runner doesn't trigger a false positive while still failing if anyone
    # regresses to the serial pattern.
    assert elapsed < 0.3, f"batch endpoint serialised lookups: took {elapsed:.3f}s, expected <0.3s parallel"


def test_fundamentals_batch_reason_uses_typed_codes_not_raw_exception_text() -> None:
    """``reason`` in the JSON body must be one of the four sanitised codes.

    PLAN-0097 T-W3-04. Verifies that:
      * InstrumentNotFoundError → ``invalid_ticker`` (not "Instrument not found: BAD")
      * The original exception string never appears anywhere in the response body.

    The full exception detail is allowed (and expected) in structlog server-side
    logs, but the JSON body must be free of it for the security/info-leak reason
    documented in the route handler.
    """
    from market_data.domain.errors import InstrumentNotFoundError

    sentinel = "DO_NOT_LEAK_THIS_STRING_TO_RESPONSE"

    lookup_uc = MagicMock()

    async def _execute(*, id=None, isin=None, symbol=None):  # type: ignore[no-untyped-def]  # noqa: A002
        raise InstrumentNotFoundError(f"Instrument not found: {symbol} ({sentinel})")

    lookup_uc.execute = AsyncMock(side_effect=_execute)
    history_uc = _make_history_uc()
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post("/v1/fundamentals/batch", json={"tickers": ["BAD"], "periods": 4})
    assert resp.status_code == 200

    body = resp.json()
    assert body["results"]["BAD"]["status"] == "error"
    assert body["results"]["BAD"]["reason"] == "invalid_ticker"

    # Defence-in-depth: scan the full serialised body text for the sentinel —
    # if any future contributor adds str(exc) into another field, this catches it.
    assert sentinel not in resp.text, "raw exception text leaked into response body"


def test_fundamentals_batch_classifies_timeout_as_upstream_timeout() -> None:
    """asyncio/built-in TimeoutError → ``upstream_timeout`` reason code."""

    aapl_id = "00000000-0000-0000-0000-00000000aaaa"

    lookup_uc = _make_lookup_uc({"AAPL": aapl_id})
    history_uc = MagicMock()

    async def _timeout(*, instrument_id, periods):  # type: ignore[no-untyped-def]
        raise TimeoutError("simulated DB slow query")

    history_uc.execute = AsyncMock(side_effect=_timeout)
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post("/v1/fundamentals/batch", json={"tickers": ["AAPL"], "periods": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"]["AAPL"]["status"] == "error"
    assert body["results"]["AAPL"]["reason"] == "upstream_timeout"
    assert "simulated DB slow query" not in resp.text
