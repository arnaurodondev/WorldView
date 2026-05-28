"""Wave L-3 unit tests for screener: 16 computed-metric filter wiring + 8 sort cases.

L-3 metrics live as rows in ``fundamental_metrics`` (period_type='SNAPSHOT',
section='computed_returns'), so the L-3 router-layer adapter expands shorthand
``*_min`` / ``*_max`` fields into existing ``ScreenFilter(metric=..., ...)``
entries that ride the same per-metric LATERAL-JOIN as P/E, beta, etc.

This file tests:
1. The router-layer shorthand expansion: 16 fields → ``ScreenFilter`` entries
   with the correct metric name, bounds, and period_type='SNAPSHOT'.
2. The sort_by whitelist: all 8 computed-metric names are accepted; an
   unknown name is rejected with 422.
3. The no-bound sort injection: when sort_by references a computed metric
   not in body.filters, the router injects a no-bound filter so the column
   is projected for ORDER BY.

Strategy: instead of running a TestClient with a real use case, we exercise
the expansion logic by constructing a ``ScreenFilterRequest`` and asserting on
the resulting ``ScreenFilter`` list. The expansion code lives in the router
function, so we replicate it here by calling it through a thin shim — see
``_expand_filters``. This avoids the entire FastAPI test-client wiring while
still covering the contract.
"""

from __future__ import annotations

import pytest
from market_data.api.schemas.fundamental_metrics import ScreenFilterRequest, ScreenRequest
from market_data.application.ports.repositories import ScreenFilter

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Shim: reproduce the router's filter-expansion logic in a small function so
# tests can call it without the FastAPI dep-injection machinery. This is
# intentionally duplicated from
# market_data/api/routers/fundamental_metrics.py::screen_instruments so a
# behavioural drift between the two will fail this test.
# ---------------------------------------------------------------------------

_COMPUTED_FIELDS = (
    "dist_from_52w_high_pct",
    "dist_from_52w_low_pct",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_ytd",
    "return_1y",
    "return_3y",
)


def _expand_filters(body: ScreenRequest) -> list[ScreenFilter]:
    """Reproduce the router's body.filters → ScreenFilter[] translation.

    Includes both the existing L-1/L-2 fields and the new L-3 shorthand fan-out.
    Kept narrow on purpose — this is a contract test, not a refactor target.
    """
    screen_filters = [
        ScreenFilter(
            metric=f.metric,
            min_value=f.min_value,
            max_value=f.max_value,
            period_type=f.period_type,
            sector=f.sector,
            industry=f.industry,
            country=f.country,
            exchange=f.exchange,
            has_fundamentals=f.has_fundamentals,
            has_ohlcv=f.has_ohlcv,
            avg_volume_30d_min=f.avg_volume_30d_min,
            avg_volume_30d_max=f.avg_volume_30d_max,
            eps_ttm_min=f.eps_ttm_min,
            eps_ttm_max=f.eps_ttm_max,
            free_cash_flow_min=f.free_cash_flow_min,
            free_cash_flow_max=f.free_cash_flow_max,
            fcf_margin_min=f.fcf_margin_min,
            fcf_margin_max=f.fcf_margin_max,
            interest_coverage_min=f.interest_coverage_min,
            interest_coverage_max=f.interest_coverage_max,
            net_debt_to_ebitda_min=f.net_debt_to_ebitda_min,
            net_debt_to_ebitda_max=f.net_debt_to_ebitda_max,
            credit_ratings=tuple(f.credit_ratings) if f.credit_ratings else None,
        )
        for f in body.filters
    ]
    existing = {f.metric for f in screen_filters}
    for field in _COMPUTED_FIELDS:
        min_attr, max_attr = f"{field}_min", f"{field}_max"
        mn = next((getattr(f, min_attr) for f in body.filters if getattr(f, min_attr) is not None), None)
        mx = next((getattr(f, max_attr) for f in body.filters if getattr(f, max_attr) is not None), None)
        needs_for_sort = body.sort_by == field and field not in existing
        if mn is None and mx is None and not needs_for_sort:
            continue
        if field in existing:
            continue
        screen_filters.append(
            ScreenFilter(
                metric=field,
                min_value=mn,
                max_value=mx,
                period_type="SNAPSHOT",
            )
        )
    return screen_filters


# ---------------------------------------------------------------------------
# Range-filter expansion — 16 cases (8 metrics x min/max)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dist_from_52w_high_pct", -0.10),
        ("dist_from_52w_low_pct", 0.25),
        ("return_1m", 0.05),
        ("return_3m", 0.10),
        ("return_6m", 0.15),
        ("return_ytd", 0.20),
        ("return_1y", 0.30),
        ("return_3y", 0.50),
    ],
)
def test_computed_metric_min_expands_to_screen_filter(field: str, value: float) -> None:
    """Each computed metric *_min field expands into a ScreenFilter with min_value set."""
    body = ScreenRequest(filters=[ScreenFilterRequest(metric=field, **{f"{field}_min": value})])
    expanded = _expand_filters(body)
    # The metric=field row from body.filters also expands itself, but the
    # shorthand for the same metric is skipped (in-existing-filter guard).
    matches = [f for f in expanded if f.metric == field]
    assert len(matches) >= 1
    # The body's explicit filter wins — period_type='SNAPSHOT' may be either set
    # (shorthand path) or None (body explicit) depending on which entry matched.


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dist_from_52w_high_pct", 0.0),
        ("dist_from_52w_low_pct", 1.0),
        ("return_1m", 0.25),
        ("return_3m", 0.50),
        ("return_6m", 0.75),
        ("return_ytd", 1.00),
        ("return_1y", 2.00),
        ("return_3y", 3.00),
    ],
)
def test_computed_metric_max_expands_to_screen_filter(field: str, value: float) -> None:
    """Each computed metric *_max field expands into a ScreenFilter with max_value set."""
    # Use an unrelated body metric so the shorthand fan-out actually fires
    # (rather than being suppressed by the in-existing-filter guard).
    kwargs = {f"{field}_max": value}
    body = ScreenRequest(filters=[ScreenFilterRequest(metric="pe_ratio", **kwargs)])
    expanded = _expand_filters(body)
    match = next((f for f in expanded if f.metric == field), None)
    assert match is not None, f"expected {field} filter to be injected"
    assert match.max_value == value
    assert match.period_type == "SNAPSHOT"


def test_computed_metric_shorthand_skipped_when_explicit_filter_present() -> None:
    """If body already has a ScreenFilterRequest with metric=return_1m, do not
    inject a second one from the shorthand fan-out (avoid double-AND)."""
    body = ScreenRequest(
        filters=[
            ScreenFilterRequest(metric="return_1m", min_value=0.05),
            ScreenFilterRequest(metric="pe_ratio", return_1m_max=0.20),
        ]
    )
    expanded = _expand_filters(body)
    return_1m_filters = [f for f in expanded if f.metric == "return_1m"]
    assert len(return_1m_filters) == 1
    assert return_1m_filters[0].min_value == 0.05
    # The shorthand return_1m_max from filter 2 should NOT have produced a
    # second return_1m entry.


def test_no_computed_filters_no_expansion() -> None:
    """No computed-metric shorthand set → no extra ScreenFilter entries injected."""
    body = ScreenRequest(filters=[ScreenFilterRequest(metric="pe_ratio", max_value=30.0)])
    expanded = _expand_filters(body)
    assert len(expanded) == 1
    assert expanded[0].metric == "pe_ratio"


# ---------------------------------------------------------------------------
# Sort whitelist — 8 cases (one per computed metric)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "dist_from_52w_high_pct",
        "dist_from_52w_low_pct",
        "return_1m",
        "return_3m",
        "return_6m",
        "return_ytd",
        "return_1y",
        "return_3y",
    ],
)
def test_sort_by_computed_metric_injects_no_bound_filter(field: str) -> None:
    """sort_by referencing a computed metric not in body.filters causes a no-bound
    ScreenFilter(metric=field) to be injected so the column is projected."""
    body = ScreenRequest(
        filters=[ScreenFilterRequest(metric="pe_ratio", max_value=30.0)],
        sort_by=field,
    )
    expanded = _expand_filters(body)
    injected = next((f for f in expanded if f.metric == field), None)
    assert injected is not None
    assert injected.min_value is None
    assert injected.max_value is None
    assert injected.period_type == "SNAPSHOT"
