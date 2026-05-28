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

import asyncio
import json
import math
import statistics
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from api_gateway.clients import ServiceClients


router = APIRouter(prefix="/v1")
logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── F-006: bare-envelope error helper ────────────────────────────────────────


class _BareEnvelopeError(Exception):
    """Internal exception that the route handler converts to a bare-envelope
    JSONResponse — bypassing FastAPI's ``HTTPException`` which always wraps
    ``detail=dict`` in ``{"detail": {...}}``.

    The portfolio domain's other endpoints (value-history, exposure) emit
    ``{"error_code", "message", "details"}`` directly via S1's exception
    handlers. Keeping the risk-metrics shape identical lets the frontend
    switch on ``error_code`` everywhere instead of special-casing the
    risk-metrics route.
    """

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "error_code": self.error_code,
                "message": self.message,
                "details": self.details,
            },
        )


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

# F-007: value_history error_reason values that represent a TRUE upstream
# failure (not an empty-but-healthy portfolio). When the portfolio leg
# reports one of these, data_quality.status flips to "degraded_upstream"
# instead of the legacy silent "insufficient_data" downgrade.
_UPSTREAM_VH_FAILURE: frozenset[str] = frozenset({"5xx", "4xx", "timeout", "exception"})


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


def _calmar(returns: list[float], drawdown_max: float | None) -> float | None:
    """Calmar = annualised_return / abs(drawdown_max).

    Returns None if drawdown_max is None, zero, or insufficient returns.
    Calmar measures return per unit of maximum drawdown risk — a portfolio
    with 20% annualised return and 10% max drawdown has Calmar = 2.0.
    """
    if len(returns) < _MIN_RETURNS:
        return None
    # WHY abs(...) < epsilon (not == 0.0): IEEE-754 equality catches both
    # +0.0 and -0.0, but a sub-normal float like -1e-300 would slip past
    # the equality check and produce an absurd calmar (e.g. 10^298). The
    # epsilon guard rejects any drawdown so small it's economically meaningless
    # — drawdowns below 1bp (1e-4) aren't real either, so 1e-12 is conservative.
    if drawdown_max is None or abs(drawdown_max) < 1e-12:
        return None
    mean_ret = statistics.fmean(returns)
    return (mean_ret * _TRADING_DAYS_PER_YEAR) / abs(drawdown_max)


def _win_rate(returns: list[float]) -> float | None:
    """Fraction of positive daily returns.

    Returns None if len(returns) < _MIN_RETURNS. A win rate of 0.58 means
    58% of trading days had positive portfolio returns — a useful proxy for
    the consistency of the strategy independent of magnitude.
    """
    if len(returns) < _MIN_RETURNS:
        return None
    return sum(1 for r in returns if r > 0) / len(returns)


def _alpha(portfolio_returns: list[float], spy_returns: list[float]) -> float | None:
    """Alpha = annualised_portfolio_return - annualised_spy_return.

    Uses the same aligned series as beta so the comparison is apples-to-apples
    (only dates where both portfolio and SPY have returns are included).
    Returns None if either series is too short or lengths diverge.
    """
    if len(portfolio_returns) < _MIN_RETURNS or len(spy_returns) < _MIN_RETURNS:
        return None
    # WHY defensive length-mismatch guard: the route always passes series
    # derived from _align_by_date() so lengths are guaranteed equal at the
    # callsite. If a future caller invokes _alpha() with unaligned series
    # this guard prevents a silently-wrong fmean comparison rather than
    # returning a meaningless number.
    if len(portfolio_returns) != len(spy_returns):
        return None
    p_ann = statistics.fmean(portfolio_returns) * _TRADING_DAYS_PER_YEAR
    s_ann = statistics.fmean(spy_returns) * _TRADING_DAYS_PER_YEAR
    return p_ann - s_ann


def _period_return(values: list[float]) -> float | None:
    """Total return over the window: ``(final - initial) / initial``.

    Returns ``None`` when fewer than 2 data points are available or the
    initial value is non-positive (the ratio is undefined / would explode).
    Sign convention: positive = gain, negative = loss. The frontend renders
    the value as a percentage.
    """
    if len(values) < 2:
        return None
    initial = values[0]
    if initial <= 0:
        return None
    return (values[-1] - initial) / initial


def _cagr(values: list[float], lookback_days: int) -> float | None:
    """Compound Annual Growth Rate: ``(V_T / V_0) ** (365.25 / lookback_days) - 1``.

    Uses ``365.25`` (calendar days, accounting for leap years) because the
    lookback window is expressed in calendar days, not trading days — the
    ``_TRADING_DAYS_PER_YEAR`` (252) constant is only correct when the
    exponent base is also in trading days.

    Returns ``None`` when fewer than 2 points are available, the initial
    value is non-positive, or ``lookback_days <= 0`` (the exponent is
    undefined). Also returns ``None`` if the final value is non-positive —
    the math would yield a complex number for the fractional root.
    """
    if len(values) < 2 or lookback_days <= 0:
        return None
    initial = values[0]
    final = values[-1]
    if initial <= 0 or final <= 0:
        return None
    # WHY explicit float(): ``a ** b`` widens to Any under mypy's stub for
    # int/float exponentiation; the cast pins the return type so the helper
    # stays ``float | None`` without a ``# type: ignore``.
    return float((final / initial) ** (365.25 / lookback_days) - 1)


def _var_95(returns: list[float]) -> float | None:
    """Historical Value-at-Risk at 95% confidence.

    Returns the empirical 5th-percentile of the daily-return series — i.e.
    the loss threshold such that on 95% of days the portfolio does no worse
    than this. Sign convention matches the rest of this file: negative for
    losses (e.g. ``-0.023`` means "5% of days lose at least 2.3%"). The
    frontend takes responsibility for formatting (sign flip / abs).

    Returns ``None`` if the series has fewer than ``_MIN_RETURNS`` (10)
    points — the percentile estimate would be too noisy to publish.

    Implementation note: ``statistics.quantiles(returns, n=20)`` partitions
    the series into 20 equal-frequency buckets; index ``[0]`` is the 5th
    percentile. This matches numpy's ``percentile(r, 5, method='inclusive')``
    closely enough for our purposes and avoids the numpy dependency.
    """
    if len(returns) < _MIN_RETURNS:
        return None
    # statistics.quantiles with n=20 returns 19 cut points at the 5%, 10%, ..., 95%
    # marks. Index 0 is the 5th-percentile cut.
    cuts = statistics.quantiles(returns, n=20, method="inclusive")
    return cuts[0]


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


# F-007: track per-leg degradation reason so the route can distinguish a true
# "insufficient_data" (portfolio genuinely has few snapshots) from a 5xx /
# timeout / exception on the upstream call. Without this the frontend's
# empty-state caption is misleading — every failure mode reads the same way.
@dataclass
class _LegResult:
    """Outcome of a single downstream fetch leg.

    error_reason values:
        None        — fetch succeeded; ``series`` carries the rows
        "5xx"       — upstream returned a 5xx HTTP status
        "4xx"       — upstream returned a non-404 4xx HTTP status
        "timeout"   — request timed out (httpx.TimeoutException)
        "exception" — any other transport / parse exception
        "no_data"   — fetch succeeded but result is empty (no SPY id, no points)
    """

    series: list[tuple[date, float]] = field(default_factory=list)
    error_reason: str | None = None


async def _fetch_value_history(
    clients: ServiceClients,
    portfolio_id: str,
    *,
    from_date: date,
    to_date: date,
    headers: dict[str, str],
) -> _LegResult:
    """Pull (date, total_value) pairs from S1 over the requested range.

    Returns a ``_LegResult`` whose ``error_reason`` distinguishes between a
    genuine empty series (``"no_data"``) and an upstream failure (``"5xx"`` /
    ``"4xx"`` / ``"timeout"`` / ``"exception"``). The 404 path still raises
    ``_BareEnvelopeError`` (caller converts to JSONResponse) so the API hands
    the frontend a clean "not found" envelope rather than confusing empty
    metrics. Any other failure becomes a non-None ``error_reason`` so the
    route can surface ``data_quality.degradation`` honestly.
    """
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/value-history",
        params={"from": from_date.isoformat(), "to": to_date.isoformat(), "granularity": "1d"},
        headers=headers,
    )
    if resp.status_code == 404:
        # Bubble 404 up so the API hands the frontend a clean "not found"
        # rather than confusingly-empty metrics.
        # F-006 (QA iter-2 carry-over): match the rest of the portfolio domain's
        # error envelope ({error_code, message, details}) — FastAPI's
        # ``HTTPException(detail=dict)`` wraps the body in ``{"detail": {...}}``,
        # so the previous fix did not actually fix the wrapping. We raise a
        # ``_BareEnvelopeError`` here and convert it in the route handler via
        # a JSONResponse so the body is the bare envelope, matching the S1
        # value-history / exposure error shape.
        raise _BareEnvelopeError(
            status_code=404,
            error_code="PORTFOLIO_NOT_FOUND",
            message="Portfolio not found",
            details={},
        )
    if resp.status_code != 200:
        logger.warning(
            "risk_metrics_value_history_unexpected_status",
            portfolio_id=portfolio_id,
            status=resp.status_code,
        )
        # F-007: classify the failure so the route can surface
        # data_quality.degradation.value_history rather than silently
        # collapsing every upstream failure into "insufficient_data".
        reason = "5xx" if resp.status_code >= 500 else "4xx"
        return _LegResult(series=[], error_reason=reason)
    try:
        body = resp.json()
    except Exception:
        return _LegResult(series=[], error_reason="exception")
    points = body.get("points") or []
    out: list[tuple[date, float]] = []
    for p in points:
        try:
            d = date.fromisoformat(str(p["date"]))
            v = float(p["value"])
        except Exception:  # noqa: S112 — malformed-row skip is intentional and not actionable
            continue
        out.append((d, v))
    # F-007: empty result on a 200 is "no_data" (portfolio truly has no
    # snapshots); a non-empty list is the success path.
    return _LegResult(series=out, error_reason=None if out else "no_data")


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
) -> _LegResult:
    """Pull SPY (date, close) pairs from S3 over the requested range.

    Returns a ``_LegResult`` distinguishing benchmark failure modes (5xx /
    timeout / no_data) so the route can render
    ``data_quality.degradation.benchmark`` honestly. SPY failures NEVER block
    the portfolio leg — they degrade beta/alpha to None and the caller
    transitions ``data_quality.status`` to ``"benchmark_unavailable"`` (or
    ``"degraded_upstream"`` when both legs error).
    """
    spy_id = await _resolve_spy_instrument_id(clients, headers)
    if spy_id is None:
        return _LegResult(series=[], error_reason="no_data")
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
        return _LegResult(series=[], error_reason="exception")
    if resp.status_code != 200:
        reason = "5xx" if resp.status_code >= 500 else "4xx"
        return _LegResult(series=[], error_reason=reason)
    try:
        body = resp.json()
    except Exception:
        return _LegResult(series=[], error_reason="exception")
    items = body.get("items") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return _LegResult(series=[], error_reason="no_data")
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
    return _LegResult(series=out, error_reason=None if out else "no_data")


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
    try:
        _uuid.UUID(portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid portfolio_id — must be a UUID") from exc

    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=lookback_days)
    clients = _clients(request)

    # 1+2. Portfolio value history (uses the user's JWT — value-history is
    #      tenant-scoped and 404s if not owned by the caller) and SPY OHLCV
    #      (public reference data, system JWT) in parallel.
    #
    # WHY asyncio.gather: the two fetches have NO data dependency — the
    # portfolio series is keyed by portfolio_id and the SPY series is
    # benchmark reference data. Running sequentially makes tail-latency
    # S1_RTT + S3_RTT + S3_search_RTT; running in parallel collapses it to
    # max(S1_RTT, S3_RTT + S3_search_RTT). F-005 (QA Wave G).
    #
    # The portfolio leg may raise ``_BareEnvelopeError`` on 404 (clean
    # "not found" envelope). ``return_exceptions=True`` keeps that
    # exception object instead of unwinding gather; we re-raise after
    # destructuring so the 404 still becomes a JSONResponse. SPY exceptions
    # ALWAYS degrade to an empty series (per existing contract).
    user_headers = _user_headers(request)
    sys_headers = _system_headers(request)
    portfolio_result, spy_result = await asyncio.gather(
        _fetch_value_history(
            clients,
            portfolio_id,
            from_date=start,
            to_date=today,
            headers=user_headers,
        ),
        _fetch_spy_ohlcv(
            clients,
            from_date=start,
            to_date=today,
            headers=sys_headers,
        ),
        return_exceptions=True,
    )

    # Portfolio leg: re-raise the 404 envelope; otherwise unpack or degrade.
    if isinstance(portfolio_result, _BareEnvelopeError):
        return portfolio_result.to_response()
    if isinstance(portfolio_result, BaseException):
        # Any other exception → degrade to empty + "exception" reason.
        logger.warning("risk_metrics_value_history_exception", exc_info=portfolio_result)
        portfolio_leg = _LegResult(series=[], error_reason="exception")
    else:
        portfolio_leg = portfolio_result

    # SPY leg: exceptions ALWAYS degrade (matches existing contract).
    if isinstance(spy_result, BaseException):
        logger.warning("risk_metrics_spy_exception", exc_info=spy_result)
        spy_leg = _LegResult(series=[], error_reason="exception")
    else:
        spy_leg = spy_result

    portfolio_series = portfolio_leg.series
    spy_series = spy_leg.series
    value_history_error_reason = portfolio_leg.error_reason
    spy_error_reason = spy_leg.error_reason

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

    # 4. Beta and Alpha — both need aligned-by-date returns from portfolio + SPY.
    beta_vs_spy: float | None
    alpha: float | None
    # WHY track aligned returns outside the if-block: _alpha needs the same
    # aligned series as _beta. Capturing them here avoids a second alignment call.
    _aligned_p_returns: list[float] = []
    _aligned_s_returns: list[float] = []
    if insufficient or not spy_series:
        beta_vs_spy = None
        alpha = None
    else:
        # Align values, THEN compute returns (so r_t for both series
        # corresponds to the same calendar date pair).
        p_aligned, s_aligned = _align_by_date(portfolio_series, spy_series)
        if len(p_aligned) < _MIN_RETURNS + 1:
            beta_vs_spy = None
            alpha = None
        else:
            _aligned_p_returns = _daily_returns(p_aligned)
            _aligned_s_returns = _daily_returns(s_aligned)
            beta_vs_spy = _beta(_aligned_p_returns, _aligned_s_returns)
            alpha = _alpha(_aligned_p_returns, _aligned_s_returns)

    # 5. Calmar and Win Rate — derived from portfolio returns alone.
    # WHY no explicit insufficient guard here: both _calmar and _win_rate
    # check len(returns) < _MIN_RETURNS internally and return None — and
    # drawdown_max is already None when insufficient (set in step 3 above).
    calmar = _calmar(portfolio_returns, drawdown_max)
    win_rate = _win_rate(portfolio_returns)

    # 5b. ARCH-F002: period_return, cagr, var_95 — derived from the raw
    # portfolio_values / portfolio_returns series. period_return and cagr
    # use the full value series (they care about endpoints, not returns)
    # so they degrade independently — a 2-point series gives a valid
    # period_return even though every return-based metric is null.
    # var_95 follows the same _MIN_RETURNS gate as Sharpe/Sortino since
    # it's a percentile of the return distribution.
    period_return: float | None = _period_return(portfolio_values)
    cagr: float | None = _cagr(portfolio_values, lookback_days)
    var_95: float | None = _var_95(portfolio_returns)

    # F-014 / F-015: surface ``as_of``, ``lookback_window``, and a
    # ``data_quality`` block so the frontend knows *why* a metric is
    # null and can render an honest empty-state hint instead of just "—".
    #
    # status discrimination:
    #   ok                    → enough returns and SPY data to compute everything
    #   insufficient_data     → fewer than _MIN_RETURNS daily returns
    #   benchmark_unavailable → enough returns BUT SPY OHLCV missing → β=null
    #   data_anomaly_detected → series contains a contaminated zero (F-209/F-302:
    #                           signals a holdings wipe, not a real catastrophic
    #                           loss; metrics are suppressed)
    #
    # F-209 / F-302: detect ANY contaminated-zero pattern, not just trailing
    # zeros. The original F-209 fix only checked ``values[-1] == 0 AND
    # values[-2] > 0``, which missed the more common case of an *intermediate*
    # zero (e.g. the F-201 wipe wrote a $0 snapshot for a single day, then a
    # broker resync repopulated subsequent days). The math still computes
    # drawdown_max = -100% / sharpe = -3.8 over that contaminated history
    # while ``data_quality.status`` reads ``benchmark_unavailable`` — totally
    # misleading caption.
    #
    # New rule: if ``min(values) == 0`` AND ``max(values) > 0`` the series has
    # at least one contaminated point sandwiched by real ones. Suppress every
    # metric and report ``data_anomaly_detected`` with the indices of the
    # contaminated points so an operator can see at a glance which dates need
    # to be rewritten by the snapshot-recompute backfill.
    anomaly_zero_indices: list[int] = (
        [i for i, v in enumerate(portfolio_values) if v == 0.0] if portfolio_values else []
    )
    has_contaminated_zero = len(portfolio_values) >= 2 and len(anomaly_zero_indices) > 0 and max(portfolio_values) > 0.0
    anomaly_details: dict[str, Any] = {}

    # F-007: classify "real upstream degradation" (5xx / timeout / exception
    # on the value-history leg) separately from a portfolio that genuinely
    # has too few snapshots. The legacy "insufficient_data" status conflated
    # the two and produced a misleading empty-state caption.
    value_history_degraded_upstream = value_history_error_reason in _UPSTREAM_VH_FAILURE

    if has_contaminated_zero:
        data_quality_status = "data_anomaly_detected"
        anomaly_details = {
            "zero_indices": anomaly_zero_indices,
            "total_points": len(portfolio_values),
        }
        # Null every metric — the underlying numbers are mathematically
        # correct but operationally misleading. The frontend uses the
        # status flag to render a caption explaining the suppression.
        drawdown_max = None
        drawdown_current = None
        volatility = None
        sharpe = None
        sortino = None
        beta_vs_spy = None
        calmar = None
        win_rate = None
        alpha = None
        # ARCH-F002: same suppression discipline for the three new metrics —
        # the underlying series is contaminated so any value would be misleading.
        period_return = None
        cagr = None
        var_95 = None
    elif value_history_degraded_upstream:
        # F-007: portfolio leg upstream-failed (5xx/4xx/timeout/exception).
        # Distinct from "insufficient_data" — the frontend can show a
        # transient-error caption instead of "not enough history".
        data_quality_status = "degraded_upstream"
    elif insufficient or len(portfolio_returns) < _MIN_RETURNS:
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
        # Wave G additions — computed from already-fetched data (no extra
        # downstream calls). See docs/designs/0089/04-portfolio-detail.md §3.6.
        "calmar": calmar,  # annualised_return / abs(drawdown_max); None when no drawdown
        "win_rate": win_rate,  # fraction of positive daily returns [0, 1]
        "alpha": alpha,  # portfolio_annualised_return - spy_annualised_return
        # ARCH-F002 additions — AnalyticsRiskSidebar tiles (VAR 95 / CAGR /
        # RETURN). Same nulling discipline as the siblings above.
        "period_return": period_return,  # (final - initial) / initial; None when < 2 points
        "cagr": cagr,  # (final/initial) ** (365.25 / lookback_days) - 1
        "var_95": var_95,  # 5th-percentile daily return (negative for losses)
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
            # F-302: when the anomaly path fires, surface the contaminated
            # indices so an operator can see at a glance which dates need
            # rewriting via the snapshot-recompute backfill (F-305 path).
            **({"details": anomaly_details} if anomaly_details else {}),
            # F-007: per-leg degradation map — additive, forward-compatible.
            # Frontend can read this to render a precise empty-state caption
            # ("upstream error" vs "no history yet" vs "benchmark down"). Old
            # clients that don't read the field continue to work.
            "degradation": {
                "value_history": value_history_error_reason,
                "benchmark": spy_error_reason,
            },
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
