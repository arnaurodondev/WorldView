"""BP-651 regression — deterministic date-window anchoring on the singular
``_handle_get_fundamentals_history`` path.

Background:
    ``get_fundamentals_history`` has NO upstream date filter — market-data's
    ``/api/v1/fundamentals/history`` returns the LATEST N periods only. So a
    question anchored to a PAST calendar year ("Tesla's quarterly revenue for
    each quarter of 2024") received the newest quarters (2025/2026), which the
    LLM then relabeled / misreported as the requested year (eval
    ``da_tsla_revenue_2024_full_year`` / ``da_msft``). The v1.15 synthesis
    prompt rule did not hold on gpt-oss.

    Fix: when the caller passes an explicit ``[from_date, to_date]`` window the
    handler over-fetches enough periods to reach the window and then filters the
    returned rows to it DETERMINISTICALLY, so wrong-year rows can never leak. An
    empty window → no-data (None) so the LLM refuses instead of relabeling.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _row(period: str, period_end: str, revenue: float) -> dict[str, Any]:
    """A minimal, non-phantom fundamentals row (one populated flow metric)."""
    return {
        "period": period,
        "period_end_date": period_end,
        "period_type": "QUARTERLY",
        "revenue": revenue,
        "gross_profit": None,
        "net_income": None,
        "eps": None,
        "ebitda": None,
        "pe_ratio": 30.0,
        "market_cap": 1_000_000_000_000,
    }


# The market-data "latest N" stream: newest first, spanning 2024 → 2026. This is
# exactly the shape that produced the bug — the newest rows are 2025/2026.
_MIXED_ROWS = [
    _row("Q1 2026", "2026-03-31", 28_095_000_000.0),
    _row("Q4 2025", "2025-12-31", 24_901_000_000.0),
    _row("Q3 2025", "2025-09-30", 22_387_000_000.0),
    _row("Q2 2025", "2025-06-30", 21_000_000_000.0),
    _row("Q1 2025", "2025-03-31", 20_000_000_000.0),
    _row("Q4 2024", "2024-12-31", 25_707_000_000.0),
    _row("Q3 2024", "2024-09-30", 25_182_000_000.0),
    _row("Q2 2024", "2024-06-30", 25_500_000_000.0),
    _row("Q1 2024", "2024-03-31", 21_301_000_000.0),
]


@pytest.mark.asyncio
async def test_window_keeps_only_2024_rows_and_excludes_2025_2026() -> None:
    """A 2024 window renders ONLY 2024 period_end rows; 2025/2026 cannot leak."""
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = list(_MIXED_ROWS)

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(
        ticker="TSLA",
        periods=4,
        from_date="2024-01-01",
        to_date="2024-12-31",
    )

    assert result is not None
    # All four 2024 quarters present...
    for q in ("Q1 2024", "Q2 2024", "Q3 2024", "Q4 2024"):
        assert q in result.text, f"missing in-window quarter {q}"
    # ...and NONE of the wrong-year quarters (the relabeling bug).
    for q in ("Q1 2026", "Q4 2025", "Q3 2025", "Q2 2025", "Q1 2025"):
        assert q not in result.text, f"out-of-window quarter {q} leaked into 2024 answer"


@pytest.mark.asyncio
async def test_window_widens_the_upstream_fetch() -> None:
    """With a historical window, the handler over-fetches past the caller's ``periods``.

    Otherwise ``periods=4`` would only ever reach the latest 4 quarters and the
    2024 window would be unreachable.
    """
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = list(_MIXED_ROWS)

    handler = _make_handler(s3)
    await handler._handle_get_fundamentals_history(
        ticker="TSLA",
        periods=4,
        from_date="2024-01-01",
        to_date="2024-12-31",
    )

    # The legacy accessor is the one that actually returns data in this test
    # (AsyncMock's snapshot accessor yields a non-dict → fall-through).
    called_periods = s3.get_fundamentals_history.call_args.kwargs["periods"]
    assert 4 < called_periods <= 20, f"fetch was not widened to reach the window: {called_periods}"


@pytest.mark.asyncio
async def test_window_with_no_matching_rows_returns_coverage_gap_sentinel() -> None:
    """D-b (2026-07-08): an empty window returns a clean COVERAGE-GAP sentinel.

    Prior behaviour returned ``None``, which the orchestrator rendered as
    status=empty/error and the model OVER-REFUSED with a resolver-style failure
    (da_apple_revenue_fy2024q4_precision). The sentinel degrades gracefully — it
    tells synthesis the exact window has no data — while STILL carrying no period
    numbers, so the anti-relabeling guarantee holds: no wrong-year figure can
    leak into the answer.
    """
    s3 = AsyncMock()
    # Only 2025/2026 rows available — nothing in the requested 2021 window.
    s3.get_fundamentals_history.return_value = [
        _row("Q1 2026", "2026-03-31", 28_000_000_000.0),
        _row("Q4 2025", "2025-12-31", 24_000_000_000.0),
    ]

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(
        ticker="TSLA",
        periods=4,
        from_date="2021-01-01",
        to_date="2021-12-31",
    )

    # A sentinel item, NOT None — and NOT a resolver-style hard error.
    assert result is not None
    assert result.item_id == "tool:fundamentals:TSLA:not_covered"
    assert "not covered" in result.text.lower() or "no fundamentals" in result.text.lower()
    # Anti-relabeling: no out-of-window figure may appear in the sentinel text.
    assert "28" not in result.text and "24" not in result.text
    assert "2026" not in result.text and "2025" not in result.text
    # The coverage marker rides the grounding bag but is NOT allow-listed, so it
    # never leaks into a grounding sample (mirrors query_fundamentals D7).
    assert ("coverage", "not_covered") in result.grounding_fields


@pytest.mark.asyncio
async def test_row_with_unparseable_period_end_dropped_under_active_window() -> None:
    """Rows we cannot date-verify must NOT leak into a year-anchored answer."""
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = [
        _row("Q3 2024", "2024-09-30", 25_182_000_000.0),
        # No parseable period_end → cannot prove it belongs to 2024.
        {**_row("Unknown", "—", 99_999_000_000.0), "period_end_date": None, "period_end": None, "date": None},
    ]

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(
        ticker="TSLA",
        periods=8,
        from_date="2024-01-01",
        to_date="2024-12-31",
    )

    assert result is not None
    assert "25.182B" in result.text  # the verifiable 2024 row survives
    assert "99.999B" not in result.text  # the unverifiable row is dropped


@pytest.mark.asyncio
async def test_no_window_preserves_legacy_latest_n_behaviour() -> None:
    """Without a window the handler is unchanged — all (latest) rows render."""
    s3 = AsyncMock()
    latest = [
        _row("Q1 2026", "2026-03-31", 28_095_000_000.0),
        _row("Q4 2025", "2025-12-31", 24_901_000_000.0),
    ]
    s3.get_fundamentals_history.return_value = list(latest)

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="TSLA", periods=2)

    assert result is not None
    assert "Q1 2026" in result.text and "Q4 2025" in result.text
    # No widening applied when no window is given.
    assert s3.get_fundamentals_history.call_args.kwargs["periods"] == 2


@pytest.mark.asyncio
async def test_partial_window_ignored_falls_back_to_latest_n() -> None:
    """A lone bound (only from_date) is ignored — legacy behaviour, no filtering."""
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = list(_MIXED_ROWS)

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(
        ticker="TSLA",
        periods=2,
        from_date="2024-01-01",  # no to_date
    )

    assert result is not None
    # Not filtered to 2024 — the latest rows still render (window was inactive).
    assert "Q1 2026" in result.text
    assert s3.get_fundamentals_history.call_args.kwargs["periods"] == 2


# ── module-level helper units ────────────────────────────────────────────────


def test_parse_iso_date_tolerates_datetime_prefix_and_bad_input() -> None:
    from datetime import date

    from rag_chat.application.pipeline.handlers.market import _parse_iso_date

    assert _parse_iso_date("2024-12-31") == date(2024, 12, 31)
    assert _parse_iso_date("2024-12-31T00:00:00Z") == date(2024, 12, 31)
    assert _parse_iso_date("—") is None
    assert _parse_iso_date("") is None
    assert _parse_iso_date(None) is None
    assert _parse_iso_date(20241231) is None


def test_periods_to_cover_window_widens_for_old_windows_and_caps_at_20() -> None:
    from datetime import date

    from rag_chat.application.pipeline.handlers.market import (
        _WINDOW_MAX_PERIODS,
        _periods_to_cover_window,
    )

    # A window a few years back needs meaningfully more than the caller's min.
    assert _periods_to_cover_window(date(2024, 1, 1), "quarterly", 4) > 4
    # Never exceed the hard cap even for very old windows.
    assert _periods_to_cover_window(date(1990, 1, 1), "quarterly", 4) == _WINDOW_MAX_PERIODS
    # Never go below the caller's requested minimum.
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    assert _periods_to_cover_window(today, "quarterly", 8) == 8
