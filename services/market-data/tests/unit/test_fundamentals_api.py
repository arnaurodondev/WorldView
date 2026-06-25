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

    async def _execute(
        instrument_id: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        # Backend-gaps wave 3: the statement endpoints forward an optional
        # period_type — when supplied, mimic the repo filter so tests can
        # assert annual/quarterly selection.
        records = rbs.get(section, [])
        if period_type is not None:
            records = [r for r in records if r.period_type == period_type]
        return records

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


def _make_record_with_period(
    section: FundamentalsSection,
    period_type: PeriodType,
    rec_id: str,
) -> FundamentalsRecord:
    """Variant of _make_record with an explicit period_type for filter tests."""
    return FundamentalsRecord(
        id=rec_id,
        security_id=INSTR_UUID,
        section=section,
        period_end=datetime(2023, 12, 31, tzinfo=UTC),
        period_type=period_type,
        data={"revenue": 1.0},
        source="eodhd",
        ingested_at=datetime(2024, 1, 10, tzinfo=UTC),
    )


def test_statement_endpoints_accept_period_type_annual() -> None:
    """Backend-gaps wave 3: ?period_type=annual reaches the use case.

    Regression: the statement endpoints had no periodicity selector, and the
    repo's BP-546 default pinned balance_sheet/cash_flow to QUARTERLY — the
    ANNUAL rows were unreachable through the section API.
    """
    mixed = [
        _make_record_with_period(FundamentalsSection.BALANCE_SHEET, PeriodType.ANNUAL, "rec-a"),
        _make_record_with_period(FundamentalsSection.BALANCE_SHEET, PeriodType.QUARTERLY, "rec-q"),
    ]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.BALANCE_SHEET: mixed})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/balance-sheet?period_type=annual")
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert [r["period_type"] for r in records] == ["ANNUAL"]
    # The router must translate the lowercase query value to the enum member.
    mock_uc.execute.assert_awaited_once_with(INSTR_UUID, FundamentalsSection.BALANCE_SHEET, PeriodType.ANNUAL)


def test_statement_endpoints_period_type_uppercase_and_quarterly() -> None:
    """Uppercase QUARTERLY is accepted and mapped to the enum."""
    mixed = [
        _make_record_with_period(FundamentalsSection.CASH_FLOW, PeriodType.ANNUAL, "rec-a"),
        _make_record_with_period(FundamentalsSection.CASH_FLOW, PeriodType.QUARTERLY, "rec-q"),
    ]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.CASH_FLOW: mixed})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/cash-flow?period_type=QUARTERLY")
    assert resp.status_code == 200
    assert [r["period_type"] for r in resp.json()["records"]] == ["QUARTERLY"]


def test_statement_endpoints_period_type_omitted_passes_none() -> None:
    """No param → period_type=None (back-compat: repo default behaviour)."""
    records = [_make_record_with_period(FundamentalsSection.INCOME_STATEMENT, PeriodType.ANNUAL, "rec-a")]
    mock_uc = _make_section_uc(records_by_section={FundamentalsSection.INCOME_STATEMENT: records})
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/income-statement")
    assert resp.status_code == 200
    mock_uc.execute.assert_awaited_once_with(INSTR_UUID, FundamentalsSection.INCOME_STATEMENT, None)


def test_statement_endpoints_reject_bogus_period_type() -> None:
    """Values outside quarterly|annual are rejected with 422 at the boundary."""
    mock_uc = _make_section_uc()
    _, client = _make_app(mock_uc)

    resp = client.get(f"/api/v1/fundamentals/{INSTR_UUID}/balance-sheet?period_type=monthly")
    assert resp.status_code == 422


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

    PLAN-0097 T-W3-02. PLAN-0098 W4 T-W4-01 de-flake (code-review §5.3 P2):
    the primary assertion is now a *call-order barrier* — every lookup MUST
    have entered before any returned (and the observed peak in-flight count
    MUST equal ``len(tickers)``). The original wall-clock < 0.3s assertion
    is retained as a *backup* (it would still catch a serial regression on a
    fast runner) but is no longer the load-bearing gate — on a busy CI the
    event loop can introduce >100 ms of jitter that would false-positive an
    otherwise-correct parallel implementation.
    """
    import asyncio
    import time

    from market_data.domain.errors import InstrumentNotFoundError

    tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META"]
    ids = {t: f"00000000-0000-0000-0000-0000{i:08d}" for i, t in enumerate(tickers)}

    # Concurrency probe: every lookup increments ``in_flight`` on entry and
    # decrements on exit. ``peak_in_flight`` records the maximum observed.
    # A serial implementation tops out at 1; a parallel one tops out at N.
    in_flight = 0
    peak_in_flight = 0
    # All N lookups must START before any RETURNS. We enforce this with a
    # barrier event that the test only sets after observing N concurrent
    # entries. If a serial implementation drives this, the first lookup will
    # await the barrier forever and the test will time out (caught by the
    # outer ``asyncio.wait_for`` below) rather than flakily pass.
    all_entered = asyncio.Event()

    lookup_uc = MagicMock()

    async def _slow_lookup(*, id=None, isin=None, symbol=None):  # type: ignore[no-untyped-def]  # noqa: A002
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        if peak_in_flight >= len(tickers):
            # All lookups are concurrently in flight — release everyone.
            all_entered.set()
        try:
            # Wait for the all-entered barrier OR a generous deadline (so a
            # serial regression hangs on the first lookup and the outer
            # timeout fires deterministically). 2s ≫ any plausible parallel
            # turnaround; only a serial implementation would block here.
            await asyncio.wait_for(all_entered.wait(), timeout=2.0)
            if symbol not in ids:
                raise InstrumentNotFoundError(f"Instrument not found: {symbol}")
            instr = MagicMock()
            instr.id = ids[symbol]
            instr.symbol = symbol
            result = MagicMock()
            result.instrument = instr
            return result
        finally:
            in_flight -= 1

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
    # PRIMARY assertion: every lookup entered before any returned.
    assert peak_in_flight == len(tickers), (
        f"batch endpoint did not run lookups concurrently: peak_in_flight=" f"{peak_in_flight}, expected {len(tickers)}"
    )
    # BACKUP assertion: with the barrier resolving as soon as all N enter,
    # a correct parallel implementation finishes in well under 1s on any
    # plausible runner. Kept as a regression alarm for cases where a future
    # change accidentally introduces sequential post-resolve work.
    assert elapsed < 1.0, f"batch endpoint took {elapsed:.3f}s (>1.0s suggests serial regression)"


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


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0098 W4 T-W4-02: defensive UUID parse around resolution.instrument.id.
# Code-review §10.1 P2 — a malformed lookup payload (e.g. ``instrument`` None
# or ``id`` not a UUID string) MUST fail ONE ticker, not 500 the whole batch.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0099 W1 T-W1-01: regression tests for batch row-mix on partial-failure
# tickers (BP-592). Root cause: `next(fetch_iter)` over `fetch_results` only
# advanced when `task is not None`, but `fetch_results` only contained pending
# non-None outcomes. Any asymmetry between iterator-consumption and the
# `continue` branches silently desynced the row→ticker map — observed in the
# chat-eval Q4 artifact where NVDA Q3 FY2025 carried AMD's $10.3B value.
# Audit: `docs/audits/2026-05-27-plan-0098-batch-rowmix-and-latency.md` §A.
# Fix: bind each fetch outcome to its originating ticker via a dict BEFORE the
# result-assembly loop — the loop then indexes by ticker, never by position.
# ─────────────────────────────────────────────────────────────────────────────


def test_fundamentals_batch_mixed_resolution_outcomes() -> None:
    """3 tickers — valid / invalid resolution / valid — each gets its OWN data.

    Catches the BP-592 row-mix shape directly: the middle ticker fails
    resolution (so no fetch task is appended for it), and the assembly loop
    must NOT shift the third ticker's outcome onto the slot that was skipped.
    Pre-fix this would have surfaced as the third ticker receiving the first
    ticker's data (or vice-versa) because the iterator and the loop indices
    drift the moment a `task is None` branch fires its `continue`.
    """
    # Two valid tickers with deliberately DIFFERENT period payloads so a
    # cross-ticker bleed would be detectable by the response data itself
    # (not just by status codes).
    aapl_id = "00000000-0000-0000-0000-00000000aaaa"
    nvda_id = "00000000-0000-0000-0000-00000000bbbb"
    aapl_periods = [{"period": "Q4 2024", "period_end_date": "2024-12-31", "revenue": 111.0}]
    nvda_periods = [{"period": "Q4 2024", "period_end_date": "2024-12-31", "revenue": 222.0}]
    history_uc = _make_history_uc({aapl_id: aapl_periods, nvda_id: nvda_periods})
    # The middle ticker "BADTICKER" is not registered → InstrumentNotFoundError
    # → resolution failure → `task is None` for it → the assembly loop's
    # `continue` MUST NOT advance the per-ticker outcome cursor for NVDA.
    lookup_uc = _make_lookup_uc({"AAPL": aapl_id, "NVDA": nvda_id})
    _, client = _make_batch_app(history_uc, lookup_uc)

    # Order matters: putting BADTICKER between two valid tickers maximises the
    # exposure of the iterator-positional desync (the old code would have
    # consumed AAPL's outcome on BADTICKER's slot and then over-read for NVDA).
    resp = client.post(
        "/v1/fundamentals/batch",
        json={"tickers": ["AAPL", "BADTICKER", "NVDA"], "periods": 4},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Each ticker's slot must carry its OWN data — not the neighbour's.
    # The response model (`FundamentalsHistoryPeriod`) fills missing optional
    # fields with None, so we compare on the LOAD-BEARING `revenue` field
    # rather than the full dict equality (which would fail on the schema-added
    # None placeholders, not on a real row-mix bug).
    assert body["results"]["AAPL"]["status"] == "ok"
    assert body["results"]["AAPL"]["periods"][0]["revenue"] == 111.0
    assert body["results"]["BADTICKER"]["status"] == "error"
    assert body["results"]["BADTICKER"]["reason"] == "invalid_ticker"
    assert body["results"]["NVDA"]["status"] == "ok"
    assert body["results"]["NVDA"]["periods"][0]["revenue"] == 222.0

    # Load-bearing regression assertion: NVDA's revenue MUST NOT equal AAPL's
    # revenue. Pre-fix, the iterator-shift could have caused exactly that
    # (mirroring the chat-eval Q4 symptom where NVDA Q3 FY2025 carried AMD's
    # $10.3B value — BP-592).
    assert body["results"]["NVDA"]["periods"][0]["revenue"] != body["results"]["AAPL"]["periods"][0]["revenue"], (
        "row-mix regression: ticker[2] received ticker[0]'s data — "
        "iterator-positional desync (BP-592) has resurfaced"
    )


def test_fundamentals_batch_first_ticker_fetch_timeout_does_not_bleed_into_second() -> None:
    """2 tickers, both valid resolve; the FIRST raises asyncio.TimeoutError.

    Catches the second iterator-misalignment shape: when a fetch task succeeds
    for ticker[0] but raises for ticker[1] (or vice versa), the per-ticker
    outcome MUST land on the right ticker. The old `next(fetch_iter)` pattern
    paired with `return_exceptions=True` would not desync HERE (gather
    preserves input order, and both tickers contribute to `pending`), but
    a brittle iterator-positional pattern is one refactor away from doing so.
    This test pins the contract: ticker[1]'s OK outcome must NOT carry
    ticker[0]'s TimeoutError reason, and vice versa.
    """
    aapl_id = "00000000-0000-0000-0000-00000000aaaa"
    nvda_id = "00000000-0000-0000-0000-00000000bbbb"
    nvda_periods = [{"period": "Q4 2024", "period_end_date": "2024-12-31", "revenue": 333.0}]

    # Custom history-uc mock that raises TimeoutError ONLY for AAPL's id but
    # returns the nvda_periods payload for NVDA's id. The per-ticker outcome
    # MUST be routed by ticker, not by iterator position.
    lookup_uc = _make_lookup_uc({"AAPL": aapl_id, "NVDA": nvda_id})

    history_uc = MagicMock()

    async def _execute(*, instrument_id, periods):  # type: ignore[no-untyped-def]
        # Mirror the live use-case contract: raise on the first ticker, return
        # data on the second. The order matters — pre-fix, an iterator pattern
        # would still happen to work here because `asyncio.gather` preserves
        # input order, but this test acts as a structural guard for any future
        # change that breaks that invariant.
        if str(instrument_id) == aapl_id:
            raise TimeoutError("simulated DB timeout for AAPL")
        return {"periods": nvda_periods}

    history_uc.execute = AsyncMock(side_effect=_execute)
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post(
        "/v1/fundamentals/batch",
        json={"tickers": ["AAPL", "NVDA"], "periods": 4},
    )
    assert resp.status_code == 200
    body = resp.json()

    # AAPL gets its own typed reason — NOT NVDA's data.
    assert body["results"]["AAPL"]["status"] == "error"
    assert body["results"]["AAPL"]["reason"] == "upstream_timeout"
    # Load-bearing: NVDA MUST get its own data, not the AAPL TimeoutError slot.
    # Compare on `revenue` (schema fills other optional fields with None — see
    # `test_fundamentals_batch_mixed_resolution_outcomes` for the rationale).
    assert body["results"]["NVDA"]["status"] == "ok"
    assert body["results"]["NVDA"]["periods"][0]["revenue"] == 333.0


def test_fundamentals_batch_invalid_lookup_payload_fails_one_ticker_only() -> None:
    """A malformed lookup result is degraded to a per-ticker ``invalid_lookup``.

    Two tickers requested: one resolves normally (returns a valid UUID-shaped
    instrument), the other returns a lookup result with ``instrument.id =
    None`` — which would raise ``TypeError`` inside the previous
    ``UUID(resolution.instrument.id)`` line. The expected post-fix behaviour
    is that:

      * the GOOD ticker comes back ``status=ok``;
      * the BAD ticker comes back ``status=error`` with ``reason=invalid_lookup``;
      * the overall HTTP status is 200 (no batch-level 500).
    """
    tickers = ["AAPL", "MSFT"]
    good_id = "00000000-0000-0000-0000-000000000010"

    lookup_uc = MagicMock()

    async def _execute(*, id=None, isin=None, symbol=None):  # type: ignore[no-untyped-def]  # noqa: A002
        instr = MagicMock()
        # AAPL → valid UUID-shaped instrument; MSFT → contract drift (id=None)
        instr.id = good_id if symbol == "AAPL" else None
        instr.symbol = symbol
        result = MagicMock()
        result.instrument = instr
        return result

    lookup_uc.execute = AsyncMock(side_effect=_execute)
    history_uc = _make_history_uc({good_id: []})
    _, client = _make_batch_app(history_uc, lookup_uc)

    resp = client.post("/v1/fundamentals/batch", json={"tickers": tickers, "periods": 4})
    assert resp.status_code == 200, (
        f"batch endpoint 500ed on a malformed lookup payload — defensive guard regression " f"(body={resp.text!r})"
    )
    body = resp.json()
    assert body["results"]["AAPL"]["status"] == "ok"
    assert body["results"]["MSFT"]["status"] == "error"
    assert body["results"]["MSFT"]["reason"] == "invalid_lookup"
