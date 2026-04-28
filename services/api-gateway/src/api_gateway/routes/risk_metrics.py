"""S9 portfolio risk metrics — pure composition, no DB access.

PLAN-0046 Wave 5 / T-46-5-03.

This is a *composition* endpoint, NOT a proxy. The frontend cannot
safely fan out to two backend services itself (CORS + auth complexity),
so S9 stitches together:

1. Portfolio value-history from S1 (``GET /api/v1/portfolios/{id}/value-history``)
2. SPY benchmark OHLCV from S3 (``GET /api/v1/ohlcv/...``) — used for beta

…and then computes drawdown, volatility, Sharpe, Sortino, beta vs SPY
on the resulting daily-return series.

R9 compliance: every cross-service call goes over REST. No DB access
in S9 at all.

Statistics — formal definitions used here::

    daily_return r_t  = (V_t - V_{t-1}) / V_{t-1}                (t >= 1)
    drawdown_max      = min over t of (V_t - max_so_far) / max_so_far
    drawdown_current  = (V_now - max_so_far_to_now) / max_so_far_to_now
    volatility_ann    = stdev(r) * sqrt(252)                     # 252 trading days
    sharpe            = (mean(r) * 252 - rf) / volatility_ann    # rf = 0.05 (constant)
    sortino           = (mean(r) * 252 - rf) / downside_dev_ann
                        where downside_dev_ann uses only r < 0, * sqrt(252)
    beta_vs_spy       = cov(r_p, r_spy) / var(r_spy)             # aligned by date

Insufficient-history guard: ANY metric that needs >= 10 daily returns
returns ``null`` when the input has fewer points. The frontend renders
``null`` as "—" rather than "NaN" so an empty equity curve doesn't
poison the KPI tiles.

Risk-free rate: ``0.05`` (5%) is hard-coded for v1 — matches the plan
spec. A future wave may pull this from FRED; for now a constant is
honest and reproducible.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from api_gateway.clients import ServiceClients


router = APIRouter(prefix="/v1")
logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Constants ────────────────────────────────────────────────────────────────

# Trading days per year — standard convention for annualisation. We
# use 252 (NYSE business days minus holidays) rather than 365 because
# the underlying returns are computed on a *trading-day* series.
_TRADING_DAYS_PER_YEAR = 252

# Risk-free rate (annual). PLAN-0046 v1 hard-codes 5% — the plan
# explicitly defers FRED-driven rates to a future wave.
_RISK_FREE_RATE = 0.05

# Minimum number of daily returns required for any metric. With <10
# the variance estimate is far too noisy to mean anything; we return
# ``null`` and let the UI show "Insufficient history".
_MIN_RETURNS = 10

# SPY ticker symbol — the canonical broad-market US benchmark used for
# beta computation. Resolved via S3 instrument-search at request time
# so we don't have to hard-code an instrument UUID (which differs per
# environment).
_SPY_SYMBOL = "SPY"


# ── Helpers (clients + auth headers — mirrors proxy.py) ──────────────────────


def _clients(request: Request) -> ServiceClients:
    """Shortcut to the typed ServiceClients on app.state."""
    return cast("ServiceClients", request.app.state.clients)


def _user_headers(request: Request) -> dict[str, str]:
    """Mint a fresh user-scoped JWT for a single downstream call.

    Replicates the convention in proxy.py — every parallel downstream
    request gets its own JTI so backend ``InternalJWTMiddleware``
    replay-detection doesn't fire.
    """
    user = getattr(request.state, "user", None)
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if user is not None and private_key is not None and kid is not None:
        token = issue_user_jwt(
            user_id=user.get("user_id", ""),
            tenant_id=user.get("tenant_id", ""),
            oidc_sub=user.get("sub", ""),
            private_key=private_key,
            kid=kid,
        )
        return {"X-Internal-JWT": token}
    # Test path — no RSA configured; fall through with whatever the
    # request already carries.
    internal_jwt = request.headers.get("X-Internal-JWT")
    return {"X-Internal-JWT": internal_jwt} if internal_jwt else {}


def _system_headers(request: Request) -> dict[str, str]:
    """Mint a system JWT for endpoints that don't carry a real user identity.

    SPY OHLCV and instrument-search are public reference data — we
    use a system JWT to satisfy the backend auth middleware without
    impersonating the requesting user.
    """
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        return {}
    token = issue_public_jwt(private_key, kid)
    return {"X-Internal-JWT": token}


# ── Pure stat functions (extracted so they're independently unit-testable) ──


def _daily_returns(values: list[float]) -> list[float]:
    """Return r_t = (V_t - V_{t-1}) / V_{t-1} for t >= 1.

    Skips any pair where the previous value is non-positive — a zero
    or negative portfolio value would produce ``inf``/``nan`` which
    contaminates every downstream metric.
    """
    out: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev <= 0:
            continue
        out.append((values[i] - prev) / prev)
    return out


def _drawdowns(values: list[float]) -> tuple[float, float]:
    """Return (drawdown_max, drawdown_current) as negative fractions.

    drawdown_max is the worst peak-to-trough decline ever seen in the
    series; drawdown_current is the current decline relative to the
    running peak. Both are <= 0; a portfolio at all-time-high has
    drawdown_current == 0.
    """
    if not values:
        return 0.0, 0.0

    max_so_far = values[0]
    dd_max = 0.0
    for v in values:
        if v > max_so_far:
            max_so_far = v
        # Guard against divide-by-zero from a zeroed-out portfolio.
        if max_so_far > 0:
            dd = (v - max_so_far) / max_so_far
            if dd < dd_max:
                dd_max = dd

    # drawdown_current uses the peak running by the LAST point — by
    # construction ``max_so_far`` already holds it because we iterated
    # the full series.
    dd_current = 0.0 if values[-1] <= 0 or max_so_far <= 0 else (values[-1] - max_so_far) / max_so_far
    return dd_max, dd_current


def _volatility_annualised(returns: list[float]) -> float:
    """Annualised standard deviation of daily returns (population stdev * √252)."""
    if len(returns) < 2:
        return 0.0
    return statistics.pstdev(returns) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _sharpe(returns: list[float]) -> float | None:
    """(mean(r) * 252 - rf) / volatility_ann.

    Returns ``None`` if the volatility is zero (a perfectly constant
    series) — the ratio is undefined and any synthetic value would be
    misleading.
    """
    vol = _volatility_annualised(returns)
    if vol == 0.0:
        return None
    mean_ret = statistics.fmean(returns)
    return (mean_ret * _TRADING_DAYS_PER_YEAR - _RISK_FREE_RATE) / vol


def _sortino(returns: list[float]) -> float | None:
    """Like Sharpe but using only the downside (negative) deviation.

    Returns ``None`` if no negative returns exist (no downside risk to
    measure) or downside volatility is zero.
    """
    downside = [r for r in returns if r < 0]
    if len(downside) < 2:
        return None
    downside_dev = statistics.pstdev(downside) * math.sqrt(_TRADING_DAYS_PER_YEAR)
    if downside_dev == 0.0:
        return None
    mean_ret = statistics.fmean(returns)
    return (mean_ret * _TRADING_DAYS_PER_YEAR - _RISK_FREE_RATE) / downside_dev


def _beta(portfolio_returns: list[float], spy_returns: list[float]) -> float | None:
    """β = cov(r_p, r_spy) / var(r_spy).

    Caller is responsible for aligning the two return series by date.
    Returns ``None`` if SPY's variance is zero (e.g. a flat series — no
    meaningful beta is definable) or if the lengths differ.

    WHY ``statistics.variance`` (sample, n-1) and ``statistics.covariance``
    (also sample, n-1): both estimators use the same Bessel correction,
    so the ratio is invariant — and crucially, β(x, x) == 1.0 exactly,
    which is the textbook self-beta. Mixing population variance with
    sample covariance introduces an n/(n-1) bias that we don't want.
    """
    if len(portfolio_returns) != len(spy_returns) or len(portfolio_returns) < 2:
        return None
    spy_var = statistics.variance(spy_returns)
    if spy_var == 0.0:
        return None
    cov = statistics.covariance(portfolio_returns, spy_returns)
    return cov / spy_var


def _align_by_date(
    series_a: list[tuple[date, float]],
    series_b: list[tuple[date, float]],
) -> tuple[list[float], list[float]]:
    """Inner-join two ``(date, value)`` series; return aligned value lists.

    Used to pair portfolio values with SPY closes — we only keep dates
    present in both series. Output is ordered by date ascending.
    """
    map_b = dict(series_b)
    a_aligned: list[float] = []
    b_aligned: list[float] = []
    for d, v in series_a:
        if d in map_b:
            a_aligned.append(v)
            b_aligned.append(map_b[d])
    return a_aligned, b_aligned


# ── Downstream fetchers ──────────────────────────────────────────────────────


async def _fetch_value_history(
    clients: ServiceClients,
    portfolio_id: str,
    *,
    from_date: date,
    to_date: date,
    headers: dict[str, str],
) -> list[tuple[date, float]]:
    """Pull (date, total_value) pairs from S1 over the requested range.

    Returns ``[]`` on any non-200 response so the caller can degrade
    gracefully — risk metrics for a portfolio with no snapshots are
    correctly nulled out by the insufficient-history guard.
    """
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/value-history",
        params={"from": from_date.isoformat(), "to": to_date.isoformat(), "granularity": "1d"},
        headers=headers,
    )
    if resp.status_code == 404:
        # Bubble 404 up so the API hands the frontend a clean "not found"
        # rather than confusingly-empty metrics.
        # F-006: match the rest of the portfolio domain's error envelope
        # ({error_code, message, details}) instead of FastAPI's default
        # {detail: "..."} shape — the frontend switches on ``error_code``
        # to decide how to render the failure.
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "PORTFOLIO_NOT_FOUND",
                "message": "Portfolio not found",
                "details": {},
            },
        )
    if resp.status_code != 200:
        logger.warning(
            "risk_metrics_value_history_unexpected_status",
            portfolio_id=portfolio_id,
            status=resp.status_code,
        )
        return []
    try:
        body = resp.json()
    except Exception:
        return []
    points = body.get("points") or []
    out: list[tuple[date, float]] = []
    for p in points:
        try:
            d = date.fromisoformat(str(p["date"]))
            v = float(p["value"])
        except Exception:  # noqa: S112 — malformed-row skip is intentional and not actionable
            continue
        out.append((d, v))
    return out


async def _resolve_spy_instrument_id(
    clients: ServiceClients,
    headers: dict[str, str],
) -> str | None:
    """Look up SPY's instrument UUID via S3 instrument search.

    WHY runtime resolution (not a config constant): instrument UUIDs
    differ per environment (dev/staging/prod each ingested SPY at a
    different time). Searching by ticker works portably.

    Returns ``None`` if S3 cannot resolve SPY — the caller treats this
    as "SPY data unavailable" and returns ``beta_vs_spy = null``
    rather than failing the whole request.
    """
    try:
        resp = await clients.market_data.get(
            "/api/v1/instruments",
            params={"query": _SPY_SYMBOL, "limit": 10},
            headers=headers,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    # The endpoint returns either {"items": [...]} or a bare list — be
    # tolerant of both shapes since S3 has shifted between the two.
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return None
    # Prefer an exact ticker match — search may return many partial hits.
    for it in items:
        if not isinstance(it, dict):
            continue
        ticker = it.get("ticker") or it.get("symbol")
        if isinstance(ticker, str) and ticker.upper() == _SPY_SYMBOL:
            iid = it.get("instrument_id") or it.get("id")
            if isinstance(iid, str) and iid:
                return iid
    return None


async def _fetch_spy_ohlcv(
    clients: ServiceClients,
    *,
    from_date: date,
    to_date: date,
    headers: dict[str, str],
) -> list[tuple[date, float]]:
    """Pull SPY (date, close) pairs from S3 over the requested range.

    Returns ``[]`` on any failure — same graceful-degradation rule as
    ``_fetch_value_history``.
    """
    spy_id = await _resolve_spy_instrument_id(clients, headers)
    if spy_id is None:
        return []
    try:
        resp = await clients.market_data.get(
            f"/api/v1/ohlcv/{spy_id}",
            params={
                "timeframe": "1d",
                "start": from_date.isoformat(),
                "end": to_date.isoformat(),
            },
            headers=headers,
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        body = resp.json()
    except Exception:
        return []
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return []
    out: list[tuple[date, float]] = []
    for bar in items:
        if not isinstance(bar, dict):
            continue
        try:
            d = date.fromisoformat(str(bar["bar_date"]))
            close = float(bar["close"])
        except Exception:  # noqa: S112 — malformed-bar skip is intentional and not actionable
            continue
        out.append((d, close))
    # OHLCV may be returned newest-first; sort ascending so alignment works.
    out.sort(key=lambda t: t[0])
    return out


# ── Route ────────────────────────────────────────────────────────────────────


@router.get("/portfolios/{portfolio_id}/risk-metrics")
async def get_risk_metrics(
    portfolio_id: str,
    request: Request,
    lookback_days: int = Query(default=90, ge=10, le=3650),
) -> Response:
    """Return drawdown, volatility, Sharpe, Sortino, beta vs SPY for a portfolio.

    PLAN-0046 Wave 5 / T-46-5-03. Pure S9 composition — no S1 endpoint
    is required beyond the existing value-history. Auth required.

    Each metric is independently nullable. ``null`` means either:

    * Insufficient history (N < 10 daily returns), OR
    * The metric is ill-defined (volatility 0, no downside returns,
      SPY data unavailable, etc.).

    The frontend renders every ``null`` as "—" — see RiskMetricsStrip.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=lookback_days)
    clients = _clients(request)

    # 1. Portfolio value history (uses the user's JWT — value-history is
    #    tenant-scoped and 404s if not owned by the caller).
    user_headers = _user_headers(request)
    portfolio_series = await _fetch_value_history(
        clients,
        portfolio_id,
        from_date=start,
        to_date=today,
        headers=user_headers,
    )

    # 2. SPY OHLCV — public reference data, system JWT is sufficient.
    sys_headers = _system_headers(request)
    spy_series = await _fetch_spy_ohlcv(
        clients,
        from_date=start,
        to_date=today,
        headers=sys_headers,
    )

    # 3. Compute metrics on the portfolio series alone (drawdown / vol /
    #    sharpe / sortino don't need SPY).
    portfolio_values = [v for _, v in portfolio_series]
    portfolio_returns = _daily_returns(portfolio_values)

    insufficient = len(portfolio_returns) < _MIN_RETURNS

    if insufficient or len(portfolio_values) == 0:
        drawdown_max: float | None = None
        drawdown_current: float | None = None
        volatility: float | None = None
        sharpe: float | None = None
        sortino: float | None = None
    else:
        dd_max, dd_curr = _drawdowns(portfolio_values)
        drawdown_max = dd_max
        drawdown_current = dd_curr
        volatility = _volatility_annualised(portfolio_returns)
        sharpe = _sharpe(portfolio_returns)
        sortino = _sortino(portfolio_returns)

    # 4. Beta — needs aligned-by-date returns from both series.
    beta_vs_spy: float | None
    if insufficient or not spy_series:
        beta_vs_spy = None
    else:
        # Align values, THEN compute returns (so r_t for both series
        # corresponds to the same calendar date pair).
        p_aligned, s_aligned = _align_by_date(portfolio_series, spy_series)
        if len(p_aligned) < _MIN_RETURNS + 1:
            beta_vs_spy = None
        else:
            p_returns = _daily_returns(p_aligned)
            s_returns = _daily_returns(s_aligned)
            beta_vs_spy = _beta(p_returns, s_returns)

    # F-014 / F-015: surface ``as_of``, ``lookback_window``, and a
    # ``data_quality`` block so the frontend knows *why* a metric is
    # null and can render an honest empty-state hint instead of just "—".
    #
    # status discrimination:
    #   ok                   → enough returns and SPY data to compute everything
    #   insufficient_data    → fewer than _MIN_RETURNS daily returns
    #   benchmark_unavailable → enough returns BUT SPY OHLCV missing → β=null
    if insufficient or len(portfolio_returns) < _MIN_RETURNS:
        data_quality_status = "insufficient_data"
    elif not spy_series:
        data_quality_status = "benchmark_unavailable"
    else:
        data_quality_status = "ok"

    payload: dict[str, Any] = {
        "portfolio_id": portfolio_id,
        "lookback_days": lookback_days,
        "drawdown_max": drawdown_max,
        "drawdown_current": drawdown_current,
        "volatility_annualized": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "beta_vs_spy": beta_vs_spy,
        "n_returns": len(portfolio_returns),
        # When the metric was computed (UTC ISO-8601). Lets the frontend
        # cache-bust intelligently if it ever wants to compare against a
        # later snapshot.
        "as_of": datetime.now(tz=UTC).isoformat(),
        "lookback_window": {
            "from": start.isoformat(),
            "to": today.isoformat(),
        },
        "data_quality": {
            "status": data_quality_status,
            "n_returns": len(portfolio_returns),
            "lookback_days": lookback_days,
        },
    }

    # WHY explicit Response: payload contains JSON ``null`` for missing
    # metrics. Returning a plain dict would also work but Response keeps
    # the content-type pinned and matches the rest of proxy.py.
    return Response(
        content=json.dumps(payload).encode(),
        status_code=200,
        media_type="application/json",
    )
