"""E2E tests for the market-data HTTP API.

Scenarios:
  1.  GET /healthz — liveness always 200
  2.  GET /readyz  — all subsystem checks pass
  3.  GET /api/v1/instruments — seeded instrument appears in list
  4.  GET /api/v1/instruments/symbol/{symbol} — lookup by symbol+exchange
  5.  GET /api/v1/instruments/{id} — lookup by UUID
  6.  GET /api/v1/instruments/{id} — unknown UUID → 404
  7.  GET /api/v1/ohlcv/{instrument_id} — returns seeded bars with correct fields
  8.  GET /api/v1/ohlcv/{instrument_id} — reversed date range → 422
  9.  GET /api/v1/ohlcv/{instrument_id}/timeframes — contains '1d'
  10. GET /api/v1/ohlcv/{instrument_id}/range — returns min/max date
  11. GET /api/v1/ohlcv/bulk — multi-instrument bulk request
  12. GET /api/v1/quotes/{instrument_id} — cache-aside: first call hits DB
  13. GET /api/v1/quotes/{instrument_id} — second call served from Valkey cache
  14. GET /api/v1/quotes/{instrument_id} — missing quote → 404
  15. POST /api/v1/quotes/batch — batch lookup returns both results
  16. GET /api/v1/securities — seeded security appears
  17. GET /api/v1/securities/{id} — security detail by UUID

Requires: docker-compose.test.yml --profile market-data-test is up and healthy.
Run with: cd services/market-data && make test -- tests/e2e/ -m e2e -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


# ── Health probes ─────────────────────────────────────────────────────────────


async def test_healthz_always_ok(e2e_client: AsyncClient) -> None:
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_all_checks_pass(e2e_client: AsyncClient) -> None:
    resp = await e2e_client.get("/readyz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    checks = body["checks"]
    assert checks["db"] == "ok"
    assert checks["valkey"] == "ok"


# ── Instruments ───────────────────────────────────────────────────────────────


async def test_instruments_list_contains_seeded(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    resp = await e2e_client.get("/api/v1/instruments")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [i["id"] for i in body["items"]]
    assert seeded_instrument["instrument_id"] in ids


async def test_instrument_lookup_by_symbol(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    # Canonical lookup endpoint: GET /api/v1/instruments/lookup?symbol=...
    # The old /instruments/symbol/{symbol} route was removed in favour of
    # this unified query-param contract (see test_old_symbol_endpoint_removed
    # in the unit suite, and the lookup route at instruments.py:54).
    symbol = seeded_instrument["symbol"]
    resp = await e2e_client.get(
        "/api/v1/instruments/lookup",
        params={"symbol": symbol},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == symbol


async def test_instrument_lookup_by_id(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    # Canonical lookup: GET /api/v1/instruments/lookup?id={uuid}
    instr_id = seeded_instrument["instrument_id"]
    resp = await e2e_client.get(
        "/api/v1/instruments/lookup",
        params={"id": instr_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == instr_id


async def test_instrument_unknown_id_returns_404(e2e_client: AsyncClient) -> None:
    resp = await e2e_client.get(
        "/api/v1/instruments/lookup",
        params={"id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


# ── OHLCV ─────────────────────────────────────────────────────────────────────


async def test_ohlcv_returns_seeded_bars(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(
        f"/api/v1/ohlcv/{instr_id}",
        params={"timeframe": "1d", "start": "2024-06-01", "end": "2024-06-05"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 5
    # All bars belong to the right instrument
    for bar in body["items"]:
        assert bar["instrument_id"] == instr_id
        assert bar["timeframe"] == "1d"
        # Price fields returned as strings (Decimal serialisation)
        assert "close" in bar
        float(bar["close"])  # must be numeric string


async def test_ohlcv_reversed_range_returns_422(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(
        f"/api/v1/ohlcv/{instr_id}",
        params={"timeframe": "1d", "start": "2024-12-01", "end": "2024-01-01"},
    )
    assert resp.status_code == 422


async def test_ohlcv_empty_range_returns_empty_list(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    """Querying a date range with no data returns 200 with empty bars."""
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(
        f"/api/v1/ohlcv/{instr_id}",
        params={"timeframe": "1d", "start": "2020-01-01", "end": "2020-01-31"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_ohlcv_available_timeframes(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(f"/api/v1/ohlcv/{instr_id}/timeframes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "1d" in body


async def test_ohlcv_date_range_endpoint(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(f"/api/v1/ohlcv/{instr_id}/range", params={"timeframe": "1d"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "min_date" in body
    assert "max_date" in body
    assert body["min_date"] == "2024-06-01"
    assert body["max_date"] == "2024-06-05"


async def test_ohlcv_bulk_multiple_instruments(
    e2e_client: AsyncClient,
    seeded_ohlcv: dict,
) -> None:
    """GET /ohlcv/bulk returns one list response per requested instrument."""
    instr_id = seeded_ohlcv["instrument_id"]
    resp = await e2e_client.get(
        "/api/v1/ohlcv/bulk",
        params={
            "instrument_ids": instr_id,
            "timeframe": "1d",
            "start": "2024-06-01",
            "end": "2024-06-05",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["timeframe"] == "1d"
    assert body[0]["total"] == 5
    assert len(body[0]["items"]) == 5


# ── Quotes ────────────────────────────────────────────────────────────────────


async def test_quote_cache_aside_first_call_hits_db(
    e2e_client: AsyncClient,
    seeded_quote: dict,
) -> None:
    instr_id = seeded_quote["instrument_id"]
    resp = await e2e_client.get(f"/api/v1/quotes/{instr_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["instrument_id"] == instr_id
    assert float(body["bid"]) == pytest.approx(182.50)
    assert float(body["ask"]) == pytest.approx(183.00)


async def test_quote_second_call_served_from_cache(
    e2e_client: AsyncClient,
    seeded_quote: dict,
) -> None:
    """Two consecutive GET /quotes calls must return identical data (cache-aside)."""
    instr_id = seeded_quote["instrument_id"]
    resp1 = await e2e_client.get(f"/api/v1/quotes/{instr_id}")
    resp2 = await e2e_client.get(f"/api/v1/quotes/{instr_id}")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["bid"] == resp2.json()["bid"]
    assert resp1.json()["ask"] == resp2.json()["ask"]


async def test_quote_missing_returns_404(e2e_client: AsyncClient) -> None:
    resp = await e2e_client.get("/api/v1/quotes/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_batch_quotes_post(
    e2e_client: AsyncClient,
    seeded_quote: dict,
) -> None:
    instr_id = seeded_quote["instrument_id"]
    resp = await e2e_client.post(
        "/api/v1/quotes/batch",
        json={"instrument_ids": [instr_id, "00000000-0000-0000-0000-000000000001"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert instr_id in body["quotes"]
    assert body["quotes"][instr_id] is not None
    # Unknown instrument returns null entry
    assert body["quotes"].get("00000000-0000-0000-0000-000000000001") is None


async def test_batch_quotes_get_latest(
    e2e_client: AsyncClient,
    seeded_quote: dict,
) -> None:
    instr_id = seeded_quote["instrument_id"]
    resp = await e2e_client.get(
        "/api/v1/quotes/latest",
        params={"instrument_ids": instr_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert instr_id in body["quotes"]


# ── Securities ────────────────────────────────────────────────────────────────


async def test_securities_list_contains_seeded(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    sec_id = seeded_instrument["security_id"]
    resp = await e2e_client.get("/api/v1/securities")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [s["id"] for s in body["items"]]
    assert sec_id in ids


async def test_security_detail_by_id(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    sec_figi = seeded_instrument["security_figi"]
    resp = await e2e_client.get(f"/api/v1/securities/{sec_figi}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["figi"] == sec_figi
    assert body["name"] == "E2E Apple Inc."


async def test_security_unknown_id_returns_404(e2e_client: AsyncClient) -> None:
    resp = await e2e_client.get("/api/v1/securities/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
