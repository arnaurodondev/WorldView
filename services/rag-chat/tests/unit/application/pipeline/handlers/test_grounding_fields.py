"""Value-substantiation (2026-06-26) — fundamentals handlers populate grounding_fields.

The 4 value-bearing fundamentals handlers must lift the LATEST period's raw,
UNSCALED numbers (+ snapshot scalars) onto ``RetrievedItem.grounding_fields`` so
the chat-quality eval can substantiate numeric claims against returned values
(design: docs/audits/2026-06-26-substantiation-eval-design.md). Invariants under
test for every handler:

  * ``grounding_fields`` carries the LATEST period's revenue/eps/... as raw
    numeric strings (e.g. "81600000000", "1.87") — NOT the markdown "$81.6B".
  * a metric that is MISSING (None) on the latest period is ABSENT from the bag
    (never a phantom number).
  * ``query_fundamentals`` honours the per-metric COVERAGE flag: only ``ok``
    metrics are emitted; ``missing``/``partial`` are skipped.
  * ``compare_entities`` packs every compared entity into one item, suffixing the
    2nd+ entity's keys (``revenue_2``) so the judge can disambiguate.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: Any) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _gf_dict(result: Any) -> dict[str, str]:
    """Materialise the ordered grounding_fields tuple as a flat dict for asserts."""
    return dict(result.grounding_fields)


# ── _handle_get_fundamentals_history ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_emits_latest_period_raw_numbers() -> None:
    """Latest period's flow metrics (+ snapshot scalars) land as raw strings."""
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        # ASC by date — the LAST element is the latest period the eval should see.
        "periods": [
            {
                "period": "Q1 FY2026",
                "period_type": "QUARTERLY",
                "revenue": 90_000_000_000.0,
                "eps": 1.50,
                "net_income": 20_000_000_000.0,
                "pe_ratio": None,
                "market_cap": None,
            },
            {
                "period": "Q2 FY2026",
                "period_type": "QUARTERLY",
                "revenue": 95_000_000_000.0,
                "gross_profit": 42_000_000_000.0,
                "net_income": 23_000_000_000.0,
                "eps": 2.01,
                "ebitda": 30_000_000_000.0,
                "pe_ratio": None,  # MISSING on the period — must be absent...
                "market_cap": None,
            },
        ],
        "current_snapshot": {
            "pe_ratio": 30.4,  # ...but present on the snapshot → emitted.
            "market_cap_usd": 3_000_000_000_000,
            "as_of": "2026-06-01",
            "source": "highlights",
        },
    }
    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=2)

    assert result is not None
    gf = _gf_dict(result)
    assert gf["ticker"] == "AAPL"
    # Latest period (Q2), raw + unscaled — NOT "$95.0B".
    assert gf["revenue"] == "95000000000"
    assert gf["eps"] == "2.01"
    assert gf["net_income"] == "23000000000"
    assert gf["gross_profit"] == "42000000000"
    assert gf["ebitda"] == "30000000000"
    # pe_ratio/market_cap were None on the latest period but the snapshot
    # supplies them → emitted from the snapshot scalars.
    assert gf["pe_ratio"] == "30.4"
    assert gf["market_cap"] == "3000000000000"
    # No "$" / "B" formatting leaked into a value.
    assert all("$" not in v and "B" not in v for v in gf.values() if v != "AAPL")


@pytest.mark.asyncio
async def test_history_missing_metric_absent_from_bag() -> None:
    """A metric that is None on the latest period (and snapshot) is omitted."""
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        "periods": [
            {
                "period": "Q2 FY2026",
                "period_type": "QUARTERLY",
                "revenue": 95_000_000_000.0,
                "eps": 2.01,
                "net_income": 23_000_000_000.0,
                "gross_profit": None,  # missing → must NOT appear
                "pe_ratio": None,
                "market_cap": None,
            }
        ],
        "current_snapshot": None,
    }
    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)

    assert result is not None
    gf = _gf_dict(result)
    assert "revenue" in gf
    assert "gross_profit" not in gf  # phantom-number guard
    assert "pe_ratio" not in gf
    assert "market_cap" not in gf


# ── _handle_get_fundamentals_history_batch ────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_emits_per_ticker_latest_period_numbers() -> None:
    """Each batch item gets its OWN ticker's latest-period raw numbers."""
    s3 = AsyncMock()
    s3.get_fundamentals_history_batch.return_value = {
        "NVDA": {
            "status": "ok",
            "periods": [
                {"period": "Q4", "revenue": 35_000_000_000, "eps": 4.0, "gross_profit": 25_000_000_000},
                {"period": "Q1", "revenue": 44_100_000_000, "eps": 5.16, "gross_profit": 33_400_000_000},
            ],
        },
        "AMD": {
            "status": "error",
            "reason": "not_found",
        },
    }
    handler = _make_handler(s3)
    results = await handler._handle_get_fundamentals_history_batch(tickers=["NVDA", "AMD"], periods=2)

    by_ticker = {dict(r.grounding_fields).get("ticker"): r for r in results}
    nvda = _gf_dict(by_ticker["NVDA"])
    # Latest period is the LAST element (Q1).
    assert nvda["revenue"] == "44100000000"
    assert nvda["eps"] == "5.16"
    assert nvda["gross_profit"] == "33400000000"
    # The errored ticker carries no numeric grounding (data unavailable).
    amd = next(r for r in results if "AMD" in r.text)
    assert amd.grounding_fields == ()


# ── _handle_query_fundamentals ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_fundamentals_honours_coverage_flag() -> None:
    """Only ``ok``-coverage metrics are emitted; ``missing``/``partial`` skipped."""
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [
                {
                    "period_end": "2025-12-31",
                    "period_label": "Q1 FY2026",
                    "revenue": 80_000_000_000.0,
                    "eps": 1.50,
                    "net_income": 18_000_000_000.0,
                },
                {
                    "period_end": "2026-03-31",
                    "period_label": "Q2 FY2026",
                    "revenue": 81_600_000_000.0,
                    "eps": 1.87,
                    # net_income IS present on the row but coverage says partial,
                    # so it must still be skipped (coverage gates, not row value).
                    "net_income": 20_000_000_000.0,
                },
            ],
            "snapshot": None,
            "coverage": {
                "revenue": "ok",
                "eps": "ok",
                "net_income": "partial",  # must be SKIPPED despite a value
            },
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="aapl",
        metrics=["revenue", "eps", "net_income"],
        periods=2,
    )
    assert result is not None
    gf = _gf_dict(result)
    assert gf["ticker"] == "AAPL"
    # Latest period (Q2) values for the ``ok`` metrics.
    assert gf["revenue"] == "81600000000"
    assert gf["eps"] == "1.87"
    # net_income is partial-coverage → NOT emitted even though a value exists.
    assert "net_income" not in gf


# ── _handle_compare_entities ──────────────────────────────────────────────────


_NVDA_ID = UUID("018f0000-0000-7000-8000-00000000bb01")
_AMD_ID = UUID("018f0000-0000-7000-8000-00000000bb02")


@pytest.mark.asyncio
async def test_compare_entities_suffixes_second_entity() -> None:
    """compare_entities packs both tickers; 2nd entity's keys are ``_2`` suffixed."""
    s3 = AsyncMock()
    s3.find_instrument_by_ticker.side_effect = lambda ticker: {
        "NVDA": _NVDA_ID,
        "AMD": _AMD_ID,
    }.get(ticker)
    s3.get_quote.side_effect = lambda iid: {
        _NVDA_ID: {"price": 425.10},
        _AMD_ID: {"price": 150.0},
    }[iid]
    s3.get_fundamentals_history_batch.return_value = {
        "NVDA": {
            "status": "ok",
            "periods": [
                {
                    "period": "Q1 2026",
                    "revenue": 44_100_000_000,
                    "eps": 5.16,
                    "gross_profit": 33_400_000_000,
                    "pe_ratio": 65.0,
                    "market_cap": 4_500_000_000_000,
                }
            ],
        },
        "AMD": {
            "status": "ok",
            "periods": [
                {
                    "period": "Q1 2026",
                    "revenue": 7_440_000_000,
                    "eps": 0.78,
                    "gross_profit": 3_900_000_000,
                    "pe_ratio": 40.0,
                    "market_cap": 820_000_000_000,
                }
            ],
        },
    }
    handler = _make_handler(s3)
    results = await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])

    assert len(results) == 1
    gf = _gf_dict(results[0])
    # First entity → bare keys.
    assert gf["ticker"] == "NVDA"
    assert gf["revenue"] == "44100000000"
    assert gf["eps"] == "5.16"
    assert gf["price"] == "425.1"
    # Second entity → ``_2`` suffixed keys (matches the judge's _\d+$ stripping).
    assert gf["ticker_2"] == "AMD"
    assert gf["revenue_2"] == "7440000000"
    assert gf["eps_2"] == "0.78"
    assert gf["price_2"] == "150"
