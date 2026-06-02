"""PLAN-0104 W32 — unified query_fundamentals handler tests.

Covers:
  * happy path: snapshot + period table rendered with coverage line
  * missing inputs degrade to None (R9 safe degradation)
  * upstream timeout → None, no fabricated row
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: Any) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


@pytest.mark.asyncio
async def test_query_fundamentals_renders_coverage_and_snapshot() -> None:
    """Happy path: coverage line, period table, snapshot block all present."""
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [
                {
                    "period_end": "2026-03-31",
                    "period_label": "Q2 FY2026",
                    "period_type": "QUARTERLY",
                    "gross_margin": 0.44,
                }
            ],
            "snapshot": {
                "forward_pe": 27.8,
                "peg_ratio": 2.15,
                "as_of": "2026-06-01",
                "source": "highlights",
            },
            "coverage": {"gross_margin": "ok", "forward_pe": "ok", "peg_ratio": "ok"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="AAPL",
        metrics=["gross_margin", "forward_pe", "peg_ratio"],
        periods=1,
    )
    assert result is not None
    text = result.text
    assert "AAPL fundamentals query" in text
    assert "Coverage:" in text
    assert "gross_margin=ok" in text
    assert "forward_pe=ok" in text
    # Margin rendered as percentage.
    assert "44.00%" in text
    # Snapshot block.
    assert "Snapshot" in text
    assert "27.80x" in text  # forward_pe
    assert "2.15" in text  # peg_ratio


@pytest.mark.asyncio
async def test_query_fundamentals_returns_none_on_missing_inputs() -> None:
    """Empty ticker or metric list → None (no fabricated row)."""
    s3 = AsyncMock()
    handler = _make_handler(s3)
    assert await handler._handle_query_fundamentals(ticker="", metrics=["revenue"]) is None
    assert await handler._handle_query_fundamentals(ticker="AAPL", metrics=[]) is None
    assert await handler._handle_query_fundamentals(ticker="AAPL", metrics=None) is None
    # Upstream MUST NOT have been called for any of these.
    s3.query_fundamentals.assert_not_called()


@pytest.mark.asyncio
async def test_query_fundamentals_returns_none_on_upstream_timeout() -> None:
    """asyncio.TimeoutError → None, no partial row."""
    s3 = AsyncMock()

    async def _raises(**_: Any) -> dict:
        raise TimeoutError

    s3.query_fundamentals = _raises
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="AAPL",
        metrics=["forward_pe"],
        periods=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_fundamentals_envelope_aligned_with_numeric_grounding() -> None:
    """PLAN-0104 W35 / BP-NEW: RetrievedItem envelope matches numeric_grounding.

    The W28-3 ``_TOOL_PREFIX_TICKER_RE`` matcher in
    ``rag_chat.application.services.numeric_grounding`` extracts the
    ticker from ``tool:<lowercase_name>:<UPPERCASE_TICKER>`` item ids.
    The handler MUST emit:

      * ``item_id == "tool:fundamentals:<TICKER>"`` (upper-cased
        ticker, no ``_query`` suffix — same shape as
        ``_handle_get_fundamentals_history``).
      * ``citation_meta.entity_name == <TICKER>`` (upper-cased), so
        the validator's third-tier entity-tag fallback also returns
        the same ticker.
      * The snapshot block exposing ratios like ``pe_ratio: 37.73x``
        verbatim, so the validator's text-scan path picks them up.
    """
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [],
            # Lower-case ticker on input to verify the handler upper-cases it.
            "snapshot": {
                "pe_ratio": 37.73,
                "forward_pe": 27.80,
                "as_of": "2026-06-01",
                "source": "highlights",
            },
            "coverage": {"pe_ratio": "ok", "forward_pe": "ok"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="aapl",  # LOWER-case input — must be normalised to AAPL.
        metrics=["pe_ratio", "forward_pe"],
        periods=0,
    )
    assert result is not None
    # Envelope shape: aligns with the W28-3 prefix matcher.
    assert result.item_id == "tool:fundamentals:AAPL"
    assert result.citation_meta.entity_name == "AAPL"
    # Snapshot ratios rendered with the "Nx" suffix the classifier
    # picks up as RATIO via the "ratio" / "pe" context keywords.
    assert "pe_ratio: 37.73x" in result.text
    assert "forward_pe: 27.80x" in result.text


@pytest.mark.asyncio
async def test_query_fundamentals_renders_not_available_for_none_snapshot_fields() -> None:
    """PLAN-0104 W39: snapshot rendering must label EVERY requested metric
    explicitly — populated as ``<metric>: <value>``, missing as
    ``<metric>: not available``.  Pre-W39 None fields were silently
    dropped, which let the LLM (Q1 AAPL artifact) interpret an absent
    line as "no data returned" and refuse despite a populated pe_ratio
    living one section above.
    """
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [],
            "snapshot": {
                "pe_ratio": 37.73,
                "forward_pe": None,  # explicitly None — must render as "not available"
                "peg_ratio": None,
                "as_of": "2026-06-02",
                "source": "highlights",
            },
            "coverage": {"pe_ratio": "ok", "forward_pe": "missing", "peg_ratio": "missing"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="AAPL",
        metrics=["pe_ratio", "forward_pe", "peg_ratio"],
        periods=0,
    )
    assert result is not None
    text = result.text
    # Populated metric uses the verbatim labelled form.
    assert "pe_ratio: 37.73x" in text
    # Missing metrics MUST appear as explicit "not available" rather than
    # being silently skipped.
    assert "forward_pe: not available" in text
    assert "peg_ratio: not available" in text


@pytest.mark.asyncio
async def test_query_fundamentals_per_period_block_uses_not_available_label() -> None:
    """PLAN-0104 W39: the per-period explicit listing must call out None cells
    as ``<metric>: not available`` so the grounding-rewrite pass cannot
    mis-classify a populated cell as missing on adjacent rows.
    """
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [
                {
                    "period_end": "2025-12-31",
                    "period_label": "Q4 2025",
                    "period_type": "QUARTERLY",
                    "gross_margin": 0.18,
                },
                {
                    "period_end": "2026-03-31",
                    "period_label": "Q1 2026",
                    "period_type": "QUARTERLY",
                    "gross_margin": None,
                },
            ],
            "snapshot": None,
            "coverage": {"gross_margin": "partial"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="TSLA",
        metrics=["gross_margin"],
        periods=2,
    )
    assert result is not None
    text = result.text
    # Per-period explicit-label block present.
    assert "Per-period metric listing" in text
    # Populated cell is rendered verbatim, missing cell is explicit.
    assert "gross_margin: 18.00%" in text
    assert "gross_margin: not available" in text


@pytest.mark.asyncio
async def test_query_fundamentals_flags_missing_metric_in_coverage_line() -> None:
    """Missing-coverage metric is surfaced in the rendered text."""
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [],
            "snapshot": {"forward_pe": 27.8, "as_of": "2026-06-01", "source": "highlights"},
            "coverage": {"forward_pe": "ok", "consensus_eps_next_year": "missing"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="NVDA",
        metrics=["forward_pe", "consensus_eps_next_year"],
        periods=0,
    )
    assert result is not None
    assert "consensus_eps_next_year=missing" in result.text
    assert "forward_pe=ok" in result.text
