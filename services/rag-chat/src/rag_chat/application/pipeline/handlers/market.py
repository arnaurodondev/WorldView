"""Market data tool handlers — price history, fundamentals, screener, movers, calendars.

Covers tools backed by S3Port and S3BriefPort:
  - get_price_history       (S3Port)
  - get_fundamentals_history (S3Port)
  - compare_entities        (S3Port — fundamentals highlights + quote)
  - screen_universe         (S3BriefPort)
  - get_market_movers       (S3BriefPort)
  - get_economic_calendar   (S3BriefPort)
  - get_earnings_calendar   (S3BriefPort)
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler, filter_kwargs_to_signature

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import S3BriefPort, S3Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
# WHY: OHLCV data for 252 trading days at ~50 chars/row ≈ 12,600 chars — well
# beyond most context windows. Cap at 4000 to stay within budget.
_TOOL_RESULT_MAX_CHARS = 4000

# Interval -> seconds-per-bar lookup. Used by _handle_get_price_history's
# last_n_bars/lookback_days computation to size the backward window. Values
# match the canonical intervals exposed by the market-data /ohlcv/bars
# endpoint; unknown intervals fall through to "day" (86400).
# Minimum backward-window span (seconds) for any computed last_n_bars /
# default price-history fetch. 86400 (1 day) is NOT enough: the newest bars
# are the last *trading* session, so a request made on a weekend or holiday
# (or before the first prints of the current session, e.g. Monday pre-market)
# anchored on now() with a 1-day window reaches back only to "yesterday",
# which may be Sunday/Saturday — yielding ZERO bars even though the symbol
# has plenty of Friday data. This is the AAPL "couldn't find a match" bug
# (investigation 2026-06-15): `last_n_bars=1, interval=1m` computed
# max(1*60*2, 86400) = 1 day, returning empty on Mon/weekend while a 3-day
# window returned 252 Friday bars. 4 calendar days clears a normal Fri→Mon
# weekend PLUS one adjacent market holiday so the last session is always in
# range. Daily/weekly intervals already imply much larger windows, so this
# floor only bites the intraday + tiny-N cases that were broken.
_MIN_LOOKBACK_SECONDS = 4 * 86400  # 4 calendar days — clears a weekend + holiday

_INTERVAL_SECONDS_MAP: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "hour": 3600,
    "1h": 3600,
    "4h": 14400,
    "day": 86400,
    "1d": 86400,
    "week": 604800,
    "1w": 604800,
    "month": 2_592_000,
    "1M": 2_592_000,
}


# FIX-LIVE-DD (2026-05-25): Q6 ("AI semiconductors above $50B") graded USELESS
# because the LLM fabricated market caps ($5.23T for NVDA, $742B for AMD,
# $842B for MU). The screener output rendered ``market_cap`` as a raw
# 13-digit integer (e.g. ``MCap: 5230000000000``). 8B-parameter models
# struggle to read scientific-magnitude integers and tend to substitute
# plausible-looking trillion/billion strings from pretraining. The
# numeric-grounding validator then flags those as unsupported, the rewrite
# prompt tells the LLM "you can't verify these", and the model collapses
# into a flat refusal.
#
# Fix: render market caps in BOTH raw and human-friendly form. The raw
# integer stays so the validator's tolerance-based matching (MARKET_CAP ±
# 0.5%) still works against `$5.23T` (= 5.23e12) extractions; the
# pre-formatted `$X.XXT` string gives the LLM a copy-paste-ready label so
# it doesn't need to convert digits in its head.
#
# Why $X.XXT/B/M cutoffs (not just T): the screener returns mid-caps too
# (e.g. ARM at $226B). A single trillion-only label would read as
# "$0.23T" — fine numerically but ugly. Use T for >= 1e12, B for >= 1e9,
# M for >= 1e6, otherwise plain dollars. Two decimals everywhere keeps
# the format predictable for the LLM.
def _format_market_cap_value(value: Any) -> str | None:
    """Render a numeric market cap as ``$X.XXT/B/M``.

    Returns ``None`` for non-numeric input so callers can decide whether to
    fall back to ``str(value)`` (preserving legacy pre-formatted strings
    like ``"3T"`` that some upstream APIs already return).
    """
    if value is None:
        return None
    # If upstream already gave us a string with a magnitude suffix
    # (legacy/test path: ``"3T"``, ``"$2.8T"``), trust it verbatim.
    if isinstance(value, str):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    abs_n = abs(num)
    sign = "-" if num < 0 else ""
    if abs_n >= 1e12:
        return f"{sign}${abs_n / 1e12:.2f}T"
    if abs_n >= 1e9:
        return f"{sign}${abs_n / 1e9:.2f}B"
    if abs_n >= 1e6:
        return f"{sign}${abs_n / 1e6:.2f}M"
    return f"{sign}${abs_n:,.0f}"


# ── Value-based substantiation (2026-06-26) ───────────────────────────────────
# Helpers that lift the RAW numeric values the fundamentals handlers already
# compute into a structured ``grounding_fields`` bag on RetrievedItem, so the
# chat-quality eval can substantiate numeric claims against returned values
# rather than re-parsing the markdown ``text`` blob (brittle: "$81.6B" loses
# precision). See docs/audits/2026-06-26-substantiation-eval-design.md.
#
# Values are emitted as RAW, UNSCALED numeric strings ("81600000000", "1.87",
# "0.586") so the judge's scale logic (B/M/K/T, %, $) stays authoritative and we
# never double-scale. A metric is emitted ONLY when its value is a finite number
# — a missing/None value is skipped so it never enters as a phantom number.

# Per-period flow/snapshot metrics we lift, mapped to the synonym keys a row may
# carry (first non-None wins). Order is stable so grounding_fields are
# deterministic. Margins are ratios on the row; we emit them verbatim (the judge
# compares a "%" claim against ratio*100 via its percent-valued set).
_GROUNDING_PERIOD_METRIC_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("revenue", ("revenue", "totalRevenue", "revenue_ttm")),
    ("net_income", ("net_income", "netIncome")),
    ("eps", ("eps", "epsActual")),
    ("gross_profit", ("gross_profit",)),
    ("pe_ratio", ("pe_ratio", "pe")),
    ("market_cap", ("market_cap", "market_capitalization", "market_cap_usd")),
    ("ebitda", ("ebitda",)),
    ("free_cash_flow", ("free_cash_flow", "fcf")),
    ("forward_pe", ("forward_pe",)),
    # Margins (2026-06-26 STEP A): emitted as RAW RATIOS ("0.586"), NOT pre-
    # scaled to a percent. The W1 percent-typed matcher (_PERCENT_VALUED_FIELDS)
    # cross-checks a "58.6 %" claim against BOTH the raw sample AND sample*100,
    # so the ratio form is the canonical one — pre-scaling here would double the
    # value. These are the per-period margin fractions ``query_fundamentals`` and
    # the history rows carry; a missing margin is skipped (never a phantom 0).
    ("gross_margin", ("gross_margin",)),
    ("operating_margin", ("operating_margin",)),
    ("net_margin", ("net_margin",)),
    # C1 (2026-07-06): the most-asked VALUATION metrics were absent from the
    # grounding allow-list, so a pe/ps/growth answer emitted only ``{ticker}`` —
    # the judge could never verify the number and defaulted to a blind PASS
    # ("presumed" mode). Add them here (per-period form, where a row carries
    # them) AND to the snapshot list below (the TTM/current form). ``price_to_
    # sales_ttm`` is inherently TTM (snapshot), but some upstream rows attach a
    # per-period P/S — we accept either. ``quarterly_revenue_growth_yoy`` is a
    # per-period derived growth figure. Multiple synonyms cover the market-data
    # normalised name plus common EODHD-cased variants; first non-None wins.
    ("price_to_sales_ttm", ("price_to_sales_ttm", "price_to_sales", "ps_ratio")),
    ("quarterly_revenue_growth_yoy", ("quarterly_revenue_growth_yoy", "revenue_growth_yoy")),
)

# Snapshot scalars we lift in addition to the latest period row. The snapshot
# uses slightly different keys (e.g. market_cap_usd) than per-period rows.
_GROUNDING_SNAPSHOT_METRIC_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pe_ratio", ("pe_ratio",)),
    ("forward_pe", ("forward_pe",)),
    ("market_cap", ("market_cap_usd", "market_cap")),
    ("ebitda", ("ebitda",)),
    ("free_cash_flow", ("free_cash_flow", "fcf")),
    # C1 (2026-07-06): valuation scalars that live ONLY on the highlights/TTM
    # snapshot for a snapshot-oriented query (e.g. "what's META's P/E and EPS?").
    # ``eps`` is added here (in addition to the per-period flow key above) so a
    # SINGLE-metric EPS query whose value is carried on the TTM snapshot — not a
    # per-period row — still emits the VALUE, matching the multi-metric batch
    # path (which already surfaces per-period eps). Without this an EPS-only
    # query fell through to ``{ticker}`` only.
    ("eps", ("eps", "eps_ttm", "diluted_eps_ttm", "earnings_share")),
    ("price_to_sales_ttm", ("price_to_sales_ttm", "price_to_sales", "ps_ratio")),
    ("quarterly_revenue_growth_yoy", ("quarterly_revenue_growth_yoy", "revenue_growth_yoy")),
)


def _coerce_grounding_number(value: Any) -> str | None:
    """Return ``value`` as a raw, unscaled numeric string, or None if not numeric.

    Rejects bools (``True`` is an int subclass) and non-finite floats so a phantom
    NaN never enters the bag. ``str(float(...))`` keeps full precision and avoids
    the markdown formatter's lossy "$81.6B" rendering.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    # Emit integers without a trailing ".0" so "81600000000" matches the judge's
    # bare-integer parse; keep float precision otherwise ("1.87", "0.586").
    if num.is_integer():
        return str(int(num))
    return repr(num)


def _fmt_raw_number(value: Any) -> str:
    """Render ``value`` as a full-precision, un-rounded numeric string for a cell.

    Cat-A FIX 3 (2026-06-28): the fundamentals table previously rounded revenue
    to ``$X.1f B``, so a 3-decimal-precision question could not be answered from
    the cell and the model padded digits. We render the raw value alongside the
    billions form so the LLM-visible cell carries full precision (revenue is an
    exact dollar figure like ``94930000000``; an EODHD decimal like ``94.93`` is
    kept verbatim). Integers shed the trailing ``.0``; non-numeric input is
    stringified unchanged so the cell never errors. Reuses ``_coerce_grounding_number``'s
    canonical formatting so the displayed raw matches what the matcher substantiates.
    """
    coerced = _coerce_grounding_number(value)
    return coerced if coerced is not None else str(value)


def _grounding_fields_from_row(
    row: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    *,
    ticker: str,
    metric_keys: tuple[tuple[str, tuple[str, ...]], ...] = _GROUNDING_PERIOD_METRIC_KEYS,
    allowed_canonicals: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Build the ``grounding_fields`` bag for one entity from its latest period.

    ``row`` is the latest-period metric dict (revenue/eps/...); ``snapshot`` is the
    current-snapshot scalar dict (pe_ratio/market_cap/...). The first non-None
    candidate per canonical metric wins, with the period row taking priority over
    the snapshot. ``ticker`` is always emitted first so the entity is anchored even
    when every numeric metric is missing.

    ``allowed_canonicals`` (when given) restricts BOTH the period and snapshot-only
    metric sets to those canonical names — used by query_fundamentals to honour the
    per-metric coverage flag so an uncovered metric never enters as a phantom number.
    """
    fields: list[tuple[str, str]] = [("ticker", ticker)]
    seen: set[str] = set()
    row = row or {}
    snapshot = snapshot or {}
    for canonical, synonyms in metric_keys:
        if canonical in seen:
            continue
        # RC-3 (2026-06-28): honour the coverage filter on the PERIOD metrics too,
        # not just the snapshot-only scalars below. The query_fundamentals caller
        # now passes the full default ``metric_keys`` and relies on
        # ``allowed_canonicals`` to drop uncovered metrics (previously it pre-filtered
        # ``metric_keys`` itself). Without this guard an uncovered period metric would
        # leak as a phantom number on every period.
        if allowed_canonicals is not None and canonical not in allowed_canonicals:
            continue
        raw: Any = None
        for syn in synonyms:
            if row.get(syn) is not None:
                raw = row.get(syn)
                break
        if raw is None:
            for syn in synonyms:
                if snapshot.get(syn) is not None:
                    raw = snapshot.get(syn)
                    break
        num = _coerce_grounding_number(raw)
        if num is not None:
            fields.append((canonical, num))
            seen.add(canonical)
    # Snapshot-only scalars (pe_ratio/forward_pe/market_cap/...) that the period
    # row did not provide — pull straight from the snapshot under its own keys.
    for canonical, synonyms in _GROUNDING_SNAPSHOT_METRIC_KEYS:
        if canonical in seen:
            continue
        if allowed_canonicals is not None and canonical not in allowed_canonicals:
            continue
        for syn in synonyms:
            num = _coerce_grounding_number(snapshot.get(syn))
            if num is not None:
                fields.append((canonical, num))
                seen.add(canonical)
                break
    return tuple(fields)


# Multi-period cap (FIX 2, 2026-06-26). A trend/batch answer quotes values across
# SEVERAL periods (e.g. "EPS grew 4.10 -> 5.20 -> 6.30 -> 7.31 over 4 quarters").
# Emitting only the LATEST period made every NON-latest figure false-``contradicted``
# against the single sampled row (the dominant remaining issue: da_msft 18,
# chain_top_mover 14). We therefore emit up to this many periods, newest first, with
# the matcher's ``_<idx>`` suffix convention so each period's distinct value survives
# without colliding (the judge + sse_emitter both strip ``_\d+$`` to the base metric).
#
# RC-3 (2026-06-28): raised 4 -> 8, then 8 -> 13 (RC-3 follow-up) in lockstep with
# the emission-side caps in sse_emitter.py (GROUNDING_MAX_ROWS 3->10,
# SAMPLE_MAX_BYTES 1024->4096, and GROUNDING_MAX_FIELDS_PER_ROW 8->14).
# A fundamentals-history answer ("Tesla revenue since 2023", "last N quarters")
# quotes one figure per quarter; emitting too few periods left the older quarters
# unsubstantiated → GROUNDING_FLOOR even though the figures were correct (RC-3 in
# docs/audits/2026-06-28-grounding-floor-rootcause.md). 13 = the headroom under the
# emission per-row field cap (GROUNDING_MAX_FIELDS_PER_ROW=14: ticker + up to 13
# period values survive into a single packed item) — covering a full ~3-year
# quarterly trend. Packing more than the field cap allows would be silently trimmed
# downstream, so 13 is the effective ceiling for a single-metric trend.
_GROUNDING_MAX_PERIODS = 13

# Screener multi-instrument cap (STEP B, 2026-06-26). A screen answer cites a few
# top tickers' P/E / cap; we lift the top N rows' values under suffixed keys so
# those citations substantiate. Kept small so the per-row field/byte caps in
# build_grounding_sample still hold (each row contributes up to 4 keys).
_SCREEN_GROUNDING_MAX_ROWS = 3

# Cat-C C1 (2026-06-28): price-series per-bar grounding band cap. A "plot NVDA
# last 90 days" answer cites N individual daily closes, but the grounding bag
# emitted only 3 aggregate scalars (high/low/last-close), so the judge could
# verify almost none of the series and floored it (GROUNDING_FLOOR,
# docs/audits/2026-06-28-cat-c-priceseries-judgenoise.md). We keep the summary
# stats AND emit a small DOWN-SAMPLED band of per-bar (close, date) pairs so a
# representative subset of the series — plus the endpoints — substantiates.
# Bounded so summary scalars (ticker/high/low/close = 4) + band (K bars x 2
# fields) stay under the emission per-row field cap (GROUNDING_MAX_FIELDS_PER_ROW
# =14 in sse_emitter): 5 bars x 2 = 10, + 4 = 14 exactly. The band is partial by
# design for a long series; the matcher tolerates unmatched bars and the
# down-sample (first, last, evenly-spaced interior) covers the endpoints.
_PRICE_BAR_GROUNDING_MAX_ROWS = 5

# ── PERIOD-ANCHOR (BP-651, 2026-07-08) ────────────────────────────────────────
# ``get_fundamentals_history`` has NO upstream date filter: market-data's
# ``/api/v1/fundamentals/history`` returns the LATEST N periods only (see
# s3_client.get_fundamentals_history_with_snapshot — it forwards ``periods`` /
# ``period_type`` and nothing else). So a question anchored to a PAST calendar
# year ("show TSLA revenue for each quarter of 2024") could ONLY ever receive
# the newest quarters (2025/2026). The LLM then reported those off-target rows
# as if they answered the 2024 question — the "relabeling" failure in
# ``da_tsla_revenue_2024_full_year`` / ``da_msft`` that survived the v1.15
# synthesis-prompt rule (a prompt rule alone does not hold on gpt-oss).
#
# The DETERMINISTIC fix (a prompt rule already failed once): when the caller
# passes an explicit ``[from_date, to_date]`` window we (a) OVER-FETCH enough
# periods to reach that window and (b) filter the returned rows to the window
# in code — so a 2025/2026 row can never leak into a 2024-anchored answer. If
# nothing falls in the window we surface no-data, and the LLM refuses honestly
# instead of fabricating.
_WINDOW_MAX_PERIODS = 20
# ~days per period; used only to size the over-fetch, generously (with margin +
# a hard cap), so the requested window is guaranteed reachable.
_DAYS_PER_QUARTER = 91
_DAYS_PER_YEAR = 365


def _parse_iso_date(value: object) -> date | None:
    """Parse an ISO date (or the date prefix of an ISO datetime) → ``date`` | None.

    Tolerant: accepts ``"2024-12-31"`` and ``"2024-12-31T00:00:00Z"`` alike, and
    returns ``None`` on anything unparseable so callers can treat a bad value as
    "no constraint" rather than raising into the tool executor.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, TypeError):
        return None


def _periods_to_cover_window(window_from: date, period_type: str, min_periods: int) -> int:
    """How many latest periods to fetch so that ``window_from`` is reachable.

    market-data returns only the newest N periods, so to include a historical
    window we must fetch back far enough to reach its START. We size the fetch
    from (today - window_from), add a 2-period margin, floor at the caller's
    requested ``periods``, and cap at ``_WINDOW_MAX_PERIODS`` to bound the
    upstream payload.
    """
    today = datetime.now(UTC).date()
    days = max((today - window_from).days, 0)
    span_per = _DAYS_PER_YEAR if period_type == "annual" else _DAYS_PER_QUARTER
    span = days // span_per + 2
    return max(min_periods, min(span, _WINDOW_MAX_PERIODS))


def _row_period_end(row: object) -> date | None:
    """Extract a row's period-end ISO date, tolerating model/dict and field aliases.

    The history use case tags rows with ``period_end_date``; ``query_fundamentals``
    uses ``period_end``; some adapters only carry ``date``. Mirror the tolerance
    used by ``_format_fundamentals_table``.
    """
    d = row.model_dump() if hasattr(row, "model_dump") else (row if isinstance(row, dict) else {})
    return _parse_iso_date(d.get("period_end_date") or d.get("period_end") or d.get("date"))


def _grounding_fields_from_rows(
    rows: list[dict[str, Any]],
    snapshot: dict[str, Any] | None,
    *,
    ticker: str,
    max_periods: int = _GROUNDING_MAX_PERIODS,
    allowed_canonicals: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Build a MULTI-PERIOD ``grounding_fields`` bag (FIX 2, 2026-06-26).

    ``rows`` is the period list in ASCENDING date order (oldest -> newest); we emit
    the newest ``max_periods`` rows so the most-quoted recent figures are covered.
    The newest period keeps the BARE metric keys (``revenue``, ``eps``, ...); each
    older period's metrics are suffixed (``revenue_2``, ``revenue_3``, ...) so the
    matcher associates a claim to the SET of period values for that metric and a
    non-latest figure is ``substantiated`` rather than false-``contradicted``. The
    snapshot scalars (pe_ratio/market_cap/...) are folded once onto the newest period
    only — they are TTM/current, not per-period, so they have one true value.

    The ``ticker`` is emitted exactly once (identifiers are non-numeric and must not
    be duplicated). Flag-safe: like the single-period helper this only fills the
    in-memory item; the CHAT_EVAL_GROUNDING_SAMPLES flag still gates the wire.

    ``allowed_canonicals`` (RC-3, 2026-06-28): when given, restrict the per-period
    metrics to those canonical names — threaded straight to ``_grounding_fields_from_row``
    so query_fundamentals can honour the per-metric coverage flag across EVERY period
    (an uncovered metric must never enter as a phantom number, on any period — not just
    the latest). When ``None`` (the history/batch callers) every metric is emitted as
    before.
    """
    if not rows:
        # C1 (2026-07-06): a SNAPSHOT-ORIENTED query (valuation metrics like
        # pe_ratio / forward_pe / ebitda / price_to_sales_ttm / eps-TTM) can come
        # back with an EMPTY ``metrics_by_period`` list but a populated snapshot —
        # those scalars are TTM/current, not per-period. Previously we returned
        # ``()`` (no ticker, no value), so the answer's valuation numbers were
        # unverifiable and the judge stayed in blind "presumed" mode. Emit the
        # snapshot scalars (ticker first) so their VALUES reach the grounding
        # sample. ``allowed_canonicals`` is honoured so an uncovered metric never
        # enters as a phantom number.
        if snapshot:
            return _grounding_fields_from_row(
                {},
                snapshot,
                ticker=ticker,
                allowed_canonicals=allowed_canonicals,
            )
        return ()
    # Newest period first, capped. ``rows`` is ASC so reversed() is newest -> oldest.
    newest_first = list(reversed(rows))[:max_periods]
    fields: list[tuple[str, str]] = [("ticker", ticker)]
    for idx, row in enumerate(newest_first):
        # Newest period folds in the snapshot scalars; older periods get the row only
        # (snapshot is current/TTM, so it has a single value, attached to the latest).
        row_snapshot = snapshot if idx == 0 else None
        per_row = _grounding_fields_from_row(
            row,
            row_snapshot,
            ticker=ticker,
            allowed_canonicals=allowed_canonicals,
        )
        for key, val in per_row:
            if key == "ticker":
                continue  # already emitted once; never duplicate the identifier
            # idx 0 -> bare key; idx 1 -> ``_2``; idx 2 -> ``_3`` ... (matcher strips _\d+$)
            suffixed = key if idx == 0 else f"{key}_{idx + 1}"
            fields.append((suffixed, val))
    return tuple(fields)


def _grounding_fields_from_bars(
    bars: list[dict[str, Any]],
    *,
    ticker: str,
) -> tuple[tuple[str, str], ...]:
    r"""Build the ``grounding_fields`` bag for a price-history (OHLCV) result.

    PLAN-0116 W5 / Item 3. Two benchmark questions cite price figures the matcher
    could not substantiate (``tc_price_history_msft_ytd_range`` — "MSFT's high and
    low so far this year"; ``tc_price_history_nvda_90d``): the handler returned a
    close-only markdown table with no structured numbers. We lift the WINDOW
    high/low (max bar high / min bar low across the returned bars) and the latest
    CLOSE so a "high was $X, low was $Y" claim substantiates and a fabricated
    high/low is contradicted (the rubric's ``fabricated_high_low`` forbidden fact).

    Cat-C C1 (2026-06-28): a SERIES answer ("plot NVDA last 90 days") cites N
    individual daily closes, which the 3 aggregate scalars could not substantiate
    — the judge floored it (docs/audits/2026-06-28-cat-c-priceseries-judgenoise.md).
    So in ADDITION to the summary stats we now emit (i) the first close + the window
    range, and (ii) a small DOWN-SAMPLED band of per-bar ``(close, date)`` pairs
    (first / last / evenly-spaced interior) so a representative subset of the series
    AND its endpoints substantiate. The band is partial by design for a long series
    (capped at ``_PRICE_BAR_GROUNDING_MAX_ROWS`` to stay under the emission field
    cap); the matcher tolerates the unmatched interior bars.

    Emitted RAW + unscaled (``_coerce_grounding_number``), ``ticker`` first. A bar
    may carry ``high``/``low``/``close``/``date`` (live ``/ohlcv/bars`` shape); a
    missing field is simply skipped so no phantom number enters. Suffixed keys
    (``close_2``, ``period_2`` …) ride the matcher's ``_\d+$``-strip convention and
    the ``get_price_history`` allow-list (ticker/period/open/high/low/close/volume).
    Flag-safe: this only fills the in-memory item; CHAT_EVAL_GROUNDING_SAMPLES still
    gates the wire.
    """
    if not bars:
        return ()
    fields: list[tuple[str, str]] = [("ticker", ticker)]
    # Window high = max of bar highs; window low = min of bar lows. Collect only
    # the numeric values so a None/garbled bar field never poisons the extremum.
    highs = [float(h) for b in bars if (h := _coerce_grounding_number(b.get("high"))) is not None]
    lows = [float(low) for b in bars if (low := _coerce_grounding_number(b.get("low"))) is not None]
    if highs:
        hi = _coerce_grounding_number(max(highs))
        if hi is not None:
            fields.append(("high", hi))
    if lows:
        lo = _coerce_grounding_number(min(lows))
        if lo is not None:
            fields.append(("low", lo))
    # Latest close (bars are sliced to the trailing window in ASC order, so the
    # last entry is the most-recent bar).
    last_close = _coerce_grounding_number(bars[-1].get("close"))
    if last_close is not None:
        fields.append(("close", last_close))

    # ── Cat-C C1: down-sampled per-bar band (close + date) ────────────────────
    # Pick up to _PRICE_BAR_GROUNDING_MAX_ROWS bars by evenly-spaced index so the
    # band always includes the FIRST and LAST bar (the trajectory endpoints) plus
    # interior samples. Emitted suffixed (_2, _3 …) so they ride alongside — and
    # never overwrite — the bare ``close`` summary scalar above. ``period`` carries
    # the bar's date (an allow-listed key) so a claim like "$215.20 on 2026-05-12"
    # can bind to a specific bar.
    n_band = min(_PRICE_BAR_GROUNDING_MAX_ROWS, len(bars))
    if n_band > 0:
        if n_band == 1:
            band_indices = [0]
        else:
            # Evenly spaced over [0, len-1] inclusive; round to int and dedupe so a
            # short series never emits the same bar twice.
            step = (len(bars) - 1) / (n_band - 1)
            band_indices = sorted({round(i * step) for i in range(n_band)})
        suffix = 2  # _2 onward; bare close/period are reserved for the summary
        for idx in band_indices:
            bar = bars[idx]
            bar_close = _coerce_grounding_number(bar.get("close"))
            if bar_close is None:
                continue
            fields.append((f"close_{suffix}", bar_close))
            bar_date = bar.get("date") or bar.get("bar_date") or bar.get("ts")
            if bar_date:
                fields.append((f"period_{suffix}", str(bar_date)))
            suffix += 1
    return tuple(fields)


# ── Chat-eval #4 (2026-06-12): screener metric rendering ─────────────────────
# Maps a screener FILTER metric name (the DB column the filter list uses, e.g.
# ``quarterly_revenue_growth_yoy``) to a display label + the response-row keys
# the screener may return for that metric (synonyms tolerated so a backend rename
# does not silently drop the column). The render order is: filtered metrics first
# (most relevant to the question), then this CORE set, de-duplicated.
_SCREEN_METRIC_RENDER: dict[str, tuple[str, tuple[str, ...]]] = {
    "market_capitalization": ("MCap", ("market_cap", "market_capitalization", "market_cap_usd")),
    "pe_ratio": ("P/E", ("pe_ratio", "pe", "trailing_pe")),
    "forward_pe": ("Fwd P/E", ("forward_pe",)),
    "quarterly_revenue_growth_yoy": ("Rev growth YoY", ("revenue_growth_yoy", "quarterly_revenue_growth_yoy")),
    "revenue_growth_yoy": ("Rev growth YoY", ("revenue_growth_yoy", "quarterly_revenue_growth_yoy")),
    "revenue": ("Revenue", ("revenue", "revenue_ttm")),
    "gross_margin": ("Gross margin", ("gross_margin",)),
    "operating_margin": ("Op margin", ("operating_margin",)),
    "roe": ("ROE", ("roe",)),
    "dividend_yield": ("Div yield", ("dividend_yield",)),
    "eps_ttm": ("EPS (TTM)", ("eps_ttm", "eps")),
}

# Always-rendered core columns (in addition to any filtered metric). These are
# the high-signal fundamentals an analyst expects in a screen result table.
_SCREEN_CORE_METRICS: tuple[str, ...] = ("market_capitalization", "pe_ratio", "quarterly_revenue_growth_yoy", "revenue")


def _screen_metric_columns(filter_metric_names: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Return ``[(label, row_keys), …]`` columns to render for a screener result.

    Filtered metrics come first (the columns the user actually keyed the screen
    on), then the core set — de-duplicated by display label so a metric that is
    both filtered AND core appears once. Unknown filter metric names are skipped
    (no render mapping) rather than guessed.
    """
    columns: list[tuple[str, tuple[str, ...]]] = []
    seen_labels: set[str] = set()
    for metric in (*filter_metric_names, *_SCREEN_CORE_METRICS):
        spec = _SCREEN_METRIC_RENDER.get(metric)
        if spec is None:
            continue
        label, row_keys = spec
        if label in seen_labels:
            continue
        seen_labels.add(label)
        columns.append((label, row_keys))
    return columns


# ── compare_entities period selection helpers (FQA-04 carry / PLAN-0103 W14) ──
# WHY at module level: pure helpers, no MarketHandler state required, easier
# to unit-test in isolation than instance methods.

# Core metrics that MUST all be non-None for a period to count as
# "fully populated" in the per-ticker pre-filter (PLAN-0103 W14). Chosen
# to mirror the cells the LLM most often complains about being NULL in the
# rendered comparison table: top-line, profitability, bottom-line.
_COMPARE_CORE_METRICS: tuple[str, ...] = ("revenue", "eps", "gross_profit")


def _period_is_fully_populated(period_row: Any) -> bool:
    """Return True when the period row has revenue + EPS + gross_profit non-None.

    Accepts either a pydantic ``FundamentalsHistoryPeriod`` (has
    ``model_dump``) or the dict shape the adapter forwards. Returns False
    on any unexpected shape so the caller can fall back gracefully — never
    raises.
    """
    if period_row is None:
        return False
    if hasattr(period_row, "model_dump"):
        row = period_row.model_dump()
    elif isinstance(period_row, dict):
        row = period_row
    else:
        return False
    return all(row.get(metric) is not None for metric in _COMPARE_CORE_METRICS)


def _select_latest_fully_populated_period(
    tickers: list[str],
    batch_results: dict[str, dict],
) -> str | None:
    """Pick the latest period present + fully-populated for ALL ``tickers``.

    Algorithm:
      1. For each ticker, build the set of period labels that are fully
         populated (revenue + EPS + gross_profit all non-None).
      2. Intersect those sets — these are the candidate common periods.
      3. Return the LATEST candidate (lexicographic max works for the
         ``YYYY-QN`` / ``YYYY-MM-DD`` shapes EODHD emits).
      4. Return ``None`` when no common fully-populated period exists,
         signalling the caller should fall back to per-ticker latest.

    Why intersection (not "any ticker fully populated"): the comparison
    table is read as a side-by-side grid; choosing different periods per
    ticker hides the asymmetry behind a unified-looking row. The whole
    fix is to make the comparison apples-to-apples.

    Why "latest" lex max: EODHD period labels are ISO-ordered (``2026-Q1``,
    ``2026-Q2``, ...; ``2026-03-31``, ``2026-06-30``, ...) so string max
    matches date max without parsing.
    """
    # Defensive: batch endpoint failure may surface here as a non-dict
    # (e.g. an unawaited coroutine from a partially-mocked test fixture).
    # In all such cases the safe answer is "no common period" so the caller
    # falls back to per-ticker latest.
    if not tickers or not isinstance(batch_results, dict) or not batch_results:
        return None

    populated_sets: list[set[str]] = []
    for ticker in tickers:
        entry = batch_results.get(ticker) or {}
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            return None  # one ticker missing → can't form a common period
        periods_data = entry.get("periods") or []
        populated: set[str] = set()
        for row in periods_data:
            label = (
                row.model_dump().get("period")
                if hasattr(row, "model_dump")
                else (row.get("period") if isinstance(row, dict) else None)
            )
            if label and _period_is_fully_populated(row):
                populated.add(label)
        if not populated:
            return None  # this ticker has no fully-populated period in window
        populated_sets.append(populated)

    common = set.intersection(*populated_sets) if populated_sets else set()
    if not common:
        return None
    return max(common)


def _pick_period_row(periods_data: list[Any], common_period: str | None) -> Any:
    """Return the row matching ``common_period`` if present, else the latest row.

    Accepts either pydantic-model rows or dicts. Caller is responsible for
    coercing the result to a dict (this helper preserves the input shape so
    the existing ``hasattr(chosen, "model_dump")`` path keeps working).
    """
    if common_period:
        for row in periods_data:
            label = (
                row.model_dump().get("period")
                if hasattr(row, "model_dump")
                else (row.get("period") if isinstance(row, dict) else None)
            )
            if label == common_period:
                return row
    return periods_data[-1]


# ── Polymarket canonical URL builder (chat prediction-market tool) ────────────
# Mirrors the FRONTEND helper apps/worldview-web/lib/prediction-markets.ts
# ``buildPolymarketUrl`` so the chat citation link is byte-identical to the link
# the dashboard/widget renders. The known frontend "wrong links" bug (memory
# 2026-06-28) was that the prediction-market UI ignored ``market_slug`` and sent
# every row to a generic search page; the canonical deep link is
# ``https://polymarket.com/event/<market_slug>``.

# MALFORMED_SLUG_TAIL — detects the ~4/525 stored slugs with a corrupted
# "numeric-tail" (e.g. ``...-143-229-513-574-212-254``) that 404 on /event/.
# Requires a chain of 3+ purely-numeric "-<digits>" segments so a legitimate
# slug ending in a single year/number (``...-by-2024``, ``...-game-7``) is NOT
# misclassified. Identical to the TS regex ``/-\d+(-\d+){2,}$/``.
_POLYMARKET_MALFORMED_SLUG_TAIL = re.compile(r"-\d+(-\d+){2,}$")


def _build_polymarket_url(slug: str | None, question: str) -> str:
    """Return the best Polymarket link for a market row.

    - Clean, non-empty slug → canonical deep link
      ``https://polymarket.com/event/<slug>``.
    - Null / empty / whitespace slug OR a malformed numeric-tail slug →
      the title-search fallback ``https://polymarket.com/markets?_q=<title>``
      (always resolves to a usable results list — a safe degraded experience).

    WHY ``/event/`` (not ``/market/``): ``/event/<slug>`` is the grouped page a
    human lands on from Polymarket's own UI and the one that resolves for the
    slugs we ingest from the Gamma API; ``/market/<slug>`` would 404.
    """
    clean_slug = (slug or "").strip()
    # quote() escapes spaces / '?' / '%' etc. in the title so the fallback query
    # string is always well-formed. An empty title still lands on the market list.
    search_url = f"https://polymarket.com/markets?_q={quote(question or '')}"
    if not clean_slug:
        return search_url
    if _POLYMARKET_MALFORMED_SLUG_TAIL.search(clean_slug):
        return search_url
    return f"https://polymarket.com/event/{clean_slug}"


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a tz-aware UTC datetime, or None.

    Tolerates a trailing ``Z`` (Python <3.11 fromisoformat rejects it) and
    naive timestamps (assumed UTC). Returns None on any non-string / unparseable
    input so a malformed upstream field never raises (R9-style safe degradation).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _format_probability(price: Any) -> str | None:
    """Render an implied-probability float (0.0-1.0) as a ``NN%`` string, or None."""
    num = _coerce_grounding_number(price)
    if num is None:
        return None
    try:
        pct = float(num) * 100.0
    except (TypeError, ValueError):
        return None
    return f"{pct:.0f}%"


class MarketHandler(ToolHandler):
    """Handles price, fundamentals, screener, movers, and calendar tools.

    All tools in this handler call either S3Port (market-data service) or
    S3BriefPort (brief/screener endpoint proxied through S9).
    """

    _HANDLED_TOOLS = frozenset(
        {
            "get_price_history",
            "get_fundamentals_history",
            # PLAN-0095 W2 T-W2-02: batch sibling of get_fundamentals_history.
            "get_fundamentals_history_batch",
            # PLAN-0104 W32: unified parameterised fundamentals query.
            "query_fundamentals",
            "compare_entities",
            "screen_universe",
            "get_market_movers",
            "get_economic_calendar",
            "get_earnings_calendar",
            # Chat prediction-market tool — Polymarket odds search (S3BriefPort).
            "get_prediction_markets",
        }
    )

    def __init__(
        self,
        s3: S3Port,
        s3_brief: S3BriefPort | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s3 = s3
        self._s3_brief = s3_brief
        self._timeout = timeout

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        # BP-622 systemic fix (PLAN-0103 W1): sanitise the LLM kwarg payload
        # against each handler's actual signature BEFORE dispatch.  Unknown
        # kwargs are logged + counted, not silently dropped or crashed.
        dispatch: dict[str, Any] = {
            "get_price_history": self._handle_get_price_history,
            "get_fundamentals_history": self._handle_get_fundamentals_history,
            # PLAN-0095 W2 T-W2-02: batched fundamentals fan-out tool.
            "get_fundamentals_history_batch": self._handle_get_fundamentals_history_batch,
            # PLAN-0104 W32: unified parameterised fundamentals query.
            "query_fundamentals": self._handle_query_fundamentals,
            "compare_entities": self._handle_compare_entities,
            "screen_universe": self._handle_screen_universe,
            "get_market_movers": self._handle_get_market_movers,
            "get_economic_calendar": self._handle_get_economic_calendar,
            "get_earnings_calendar": self._handle_get_earnings_calendar,
            "get_prediction_markets": self._handle_get_prediction_markets,
        }
        target = dispatch.get(tool_name)
        if target is None:
            # Unreachable if can_handle() is checked first; guard for safety.
            raise ValueError(f"MarketHandler cannot handle tool: {tool_name}")
        known, _unknown = filter_kwargs_to_signature(target, tool_name, args)
        return await target(**known)

    async def _handle_get_price_history(
        self,
        ticker: str,
        from_date: str | None = None,
        to_date: str | None = None,
        # Chat-eval #5 root cause A (2026-06-12): default to "day" (was "week").
        # The backend /ohlcv/bars endpoint does not support week/month
        # aggregation, and those values were removed from the tool enum.
        interval: str = "day",
        last_n_bars: int | None = None,
        lookback_days: int | None = None,
    ) -> RetrievedItem | None:
        """Fetch OHLCV bars and format as a markdown table RetrievedItem.

        Parameter resolution (B-3, 2026-06-10):
          1. If ``from_date`` AND ``to_date`` are both provided, use them
             verbatim (explicit-window mode, the original behavior).
          2. Else if ``last_n_bars`` is provided, request the most recent N
             bars of the given ``interval`` by computing a backward window
             of ``N x interval_seconds + buffer``, then slicing to the last
             N rows post-fetch.
          3. Else if ``lookback_days`` is provided, fetch
             ``today - lookback_days`` -> ``today`` at the given interval.
          4. Else default to ``last_n_bars=20`` (one screen of bars).

        Replaces the implicit 7-day 1m fallback shipped in 9a8bb6244:
        the LLM now expresses "what is X trading at?" explicitly as
        ``last_n_bars=1, interval="1m"`` — single retrieved bar, no
        guessing on the handler side. Quotes are intentionally disabled
        to cap third-party costs; the most-recent 1m bar fills the gap.
        """
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        # ── Step 1: resolve the date window from inputs ──────────────────
        explicit_window = bool(from_date and to_date)
        n: int | None = None

        if explicit_window:
            try:
                _from = date.fromisoformat(from_date)  # type: ignore[arg-type]
                _to = date.fromisoformat(to_date)  # type: ignore[arg-type]
            except ValueError:
                log.warning(
                    "tool_invalid_dates",
                    tool="get_price_history",
                    from_date=from_date,
                    to_date=to_date,
                )
                return None
        elif last_n_bars is not None and last_n_bars > 0:
            # Compute a backward window with enough headroom for weekends /
            # off-hours / non-trading days. Buffer = 2x the implied span,
            # bounded to a sane ceiling so 1m x 60 doesn't pull years.
            n = int(last_n_bars)
            interval_seconds = _INTERVAL_SECONDS_MAP.get(interval, 86400)
            implied_seconds = n * interval_seconds
            # Floor at _MIN_LOOKBACK_SECONDS (4d) so a weekend/holiday between
            # now() and the last trading session never produces an empty fetch
            # (the AAPL "couldn't find a match" bug). Was max(..., 86400).
            buffer_seconds = max(implied_seconds * 2, _MIN_LOOKBACK_SECONDS)
            buffer_seconds = min(buffer_seconds, 365 * 86400)  # cap at 1y
            _to = _dt.now(tz=UTC).date()
            _from = _to - _td(seconds=buffer_seconds)
        elif lookback_days is not None and lookback_days > 0:
            _to = _dt.now(tz=UTC).date()
            # Honour the caller's window but never look back less than the
            # weekend/holiday-clearing floor — a literal lookback_days=1 on a
            # Monday/weekend would otherwise miss Friday's session entirely.
            _lookback = max(int(lookback_days) * 86400, _MIN_LOOKBACK_SECONDS)
            _from = _to - _td(seconds=_lookback)
        else:
            # Default: most recent 20 bars at requested interval.
            n = 20
            interval_seconds = _INTERVAL_SECONDS_MAP.get(interval, 86400)
            # Same weekend/holiday-clearing floor as the explicit last_n_bars
            # branch (was 86400) so an interval="1m" default fetch on a
            # weekend still reaches the last trading session.
            buffer_seconds = max(n * interval_seconds * 2, _MIN_LOOKBACK_SECONDS)
            _to = _dt.now(tz=UTC).date()
            _from = _to - _td(seconds=buffer_seconds)

        # ── Step 2: fetch ────────────────────────────────────────────────
        # BP-025: wrap S3 call with timeout to prevent long tail latency.
        bars = await asyncio.wait_for(
            self._s3.get_ohlcv_range(
                ticker=ticker,
                from_date=_from,
                to_date=_to,
                interval=interval,
            ),
            timeout=self._timeout,
        )
        if not bars:
            log.warning(
                "tool_no_data",
                tool="get_price_history",
                ticker=ticker,
                interval=interval,
                last_n_bars=last_n_bars,
                lookback_days=lookback_days,
            )
            return None

        # ── Step 3: slice when last_n_bars mode ──────────────────────────
        if n is not None and len(bars) > n:
            # /ohlcv/bars returns ascending; take the trailing N (the most
            # recent bars of the last trading session). The live market-data
            # payload keys each bar as "date" (e.g. "2026-06-12 18:48"); older
            # callers used "ts"/"bar_date". Include all three so the sort is a
            # real chronological sort regardless of upstream shape — the
            # previous key (ts|bar_date) was always "" for the live "date"
            # payload, silently degrading to a no-op that only worked because
            # the upstream order is already ascending.
            bars = sorted(
                bars,
                key=lambda b: b.get("ts") or b.get("bar_date") or b.get("date") or "",
            )[-n:]

        # ── Step 4: format ──────────────────────────────────────────────
        table = self._format_price_table(ticker, str(_from), str(_to), interval, bars)
        # Distinguish "single most-recent bar" responses in the citation
        # so the LLM/UI can present them as "last known price" rather
        # than full history. Only n==1 paths get the latest_1m suffix.
        item_id = (
            f"tool:price_history:{ticker}:latest_1m" if n == 1 and interval == "1m" else f"tool:price_history:{ticker}"
        )
        # Value-substantiation (PLAN-0116 W5 / Item 3): lift the window high/low +
        # latest close so the eval can verify "high $X / low $Y" claims rather than
        # re-parse the close-only markdown table. Flag-gated at the SSE layer.
        grounding_fields = _grounding_fields_from_bars(bars, ticker=ticker.upper())
        return RetrievedItem.create(
            item_id=item_id,
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88 if explicit_window else 0.84,
            trust_weight=0.90,
            # BP-670: bind the requested symbol so the BP-605 grounding gate
            # and the entity-name validator see WHICH entity this price data
            # belongs to (the live BTC-USD refusal had entity_name=None and
            # the symbol appeared only inside the item_id).
            citation_meta=CitationMeta(
                title=f"{ticker.upper()} price history ({interval})",
                url=None,
                source_name="market_data",
                published_at=None,
                entity_name=ticker.upper(),
            ),
            grounding_fields=grounding_fields,
        )

    async def _handle_get_fundamentals_history(
        self,
        ticker: str,
        periods: int = 8,
        period_type: str = "quarterly",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> RetrievedItem | None:
        """Fetch fundamentals and format as a markdown table RetrievedItem.

        F-LIVE-P (2026-05-26): ``period_type`` ("quarterly" default, or
        "annual") selects the periodicity sent to market-data. Anything
        outside the allowlist falls back to "quarterly" with a structured
        warning — the LLM occasionally invents values like "ttm" or
        "trailing", and the safer behaviour is to honour the user-visible
        default rather than 500 on an unknown enum.

        PERIOD-ANCHOR (BP-651, 2026-07-08): ``from_date`` / ``to_date`` bound
        the answer to a HISTORICAL calendar window (e.g. all of 2024). Because
        market-data has no upstream date filter (it returns the LATEST N
        periods), we over-fetch enough periods to reach the window and then
        filter the returned rows to it DETERMINISTICALLY — so a year-anchored
        question can never be answered with the latest (wrong-year) quarters.
        Both bounds must be supplied together; a lone bound is ignored.
        """
        period_type_norm = (period_type or "quarterly").strip().lower()
        if period_type_norm not in {"quarterly", "annual"}:
            log.warning(
                "tool_invalid_param",
                tool="get_fundamentals_history",
                param="period_type",
                value=period_type,
                fallback="quarterly",
            )
            period_type_norm = "quarterly"

        # PERIOD-ANCHOR: resolve the optional historical window. A window is
        # only ACTIVE when both bounds parse and are correctly ordered; a
        # partial/invalid window degrades to the legacy "latest N" behaviour
        # (logged) rather than erroring. When active we widen the fetch so the
        # window's start is reachable in the latest-N stream market-data returns.
        window_from = _parse_iso_date(from_date)
        window_to = _parse_iso_date(to_date)
        window_active = window_from is not None and window_to is not None and window_from <= window_to
        if (from_date or to_date) and not window_active:
            log.warning(
                "tool_invalid_param",
                tool="get_fundamentals_history",
                param="date_window",
                from_date=from_date,
                to_date=to_date,
                fallback="latest_n",
            )
        fetch_periods = periods
        if window_active:
            assert window_from is not None  # narrowed by window_active; for mypy
            fetch_periods = _periods_to_cover_window(window_from, period_type_norm, periods)
        periods = fetch_periods

        # PLAN-0103 W25 / BP-640: prefer the snapshot-aware accessor when
        # the adapter implements it AND the response is well-formed. Test
        # doubles based on AsyncMock auto-spawn every attribute (so a plain
        # ``hasattr`` check passes even on legacy mocks); we therefore
        # ALSO require the returned value to be a dict with the new
        # ``periods``/``current_snapshot`` keys. Anything else falls back
        # to the legacy ``get_fundamentals_history`` list shape so existing
        # tests + adapters don't churn.
        current_snapshot: dict | None = None
        data: list | None = None
        snap_method = getattr(self._s3, "get_fundamentals_history_with_snapshot", None)
        if snap_method is not None:
            bundle = await asyncio.wait_for(
                snap_method(
                    ticker=ticker,
                    periods=periods,
                    period_type=period_type_norm,
                ),
                timeout=self._timeout,
            )
            if isinstance(bundle, dict) and "periods" in bundle:
                periods_field = bundle.get("periods", [])
                if isinstance(periods_field, list):
                    data = periods_field
                snap = bundle.get("current_snapshot")
                current_snapshot = snap if isinstance(snap, dict) else None
        if data is None:
            data = await asyncio.wait_for(
                self._s3.get_fundamentals_history(
                    ticker=ticker,
                    periods=periods,
                    period_type=period_type_norm,
                ),
                timeout=self._timeout,
            )
        if not data and current_snapshot is None:
            log.warning("tool_no_data", tool="get_fundamentals_history", ticker=ticker)
            return None
        # Narrow ``data`` to ``list`` for mypy + downstream iteration. Either
        # the snapshot-aware path populated it, or the legacy fallback did,
        # or we returned None above — the assertion is structural.
        if data is None:
            data = []

        # PLAN-0103 W24 / BP-639: phantom-row guard.
        #
        # If a row comes back with EVERY flow metric (revenue, eps, net_income,
        # ebitda) null/missing, treat it as if the upstream returned no data.
        # WHY: market-data's filter (PLAN-0103 W22) already drops EODHD's
        # future-dated placeholders before they reach us, but defence-in-depth
        # matters — any future schema drift that lets a phantom row through
        # would otherwise be quoted by the LLM as if it were real (audit
        # ``docs/audits/2026-06-01-chat-quality-aapl-pe-investigation.md``;
        # symmetric to the batch fix landed as BP-626 / PLAN-0103 W4).
        #
        # We intentionally use the FLOW metrics only — not pe_ratio/market_cap,
        # which are TTM snapshot fields injected into every row regardless of
        # whether the per-period row itself has data (see PLAN-0104 / BP-640
        # TODO in the market-data use case).
        flow_keys = ("revenue", "eps", "net_income", "ebitda")

        def _is_phantom_row(row: object) -> bool:
            d = row.model_dump() if hasattr(row, "model_dump") else (row if isinstance(row, dict) else {})
            return all(d.get(k) in (None, "", "None") for k in flow_keys)

        non_phantom = []
        for row in data:
            if _is_phantom_row(row):
                period_end = (row.get("period_end_date") if isinstance(row, dict) else None) or "?"
                log.info(
                    "tool_phantom_row_dropped",
                    tool="get_fundamentals_history",
                    symbol=ticker,
                    period_end=period_end,
                )
                continue
            non_phantom.append(row)

        # PERIOD-ANCHOR (BP-651): deterministic date-window filter. When the
        # caller anchored the question to a historical window, keep ONLY rows
        # whose period_end falls inside it. Rows with an unparseable period_end
        # are DROPPED under an active window (we cannot prove they belong, so we
        # must not let an unanchored row leak into a year-specific answer). If
        # the window matches nothing we fall through to the no-data branch below
        # → the LLM refuses honestly instead of relabeling the latest quarters.
        if window_active:
            assert window_from is not None and window_to is not None  # window_active guarantees
            in_window = []
            for row in non_phantom:
                pe = _row_period_end(row)
                if pe is not None and window_from <= pe <= window_to:
                    in_window.append(row)
            if not in_window:
                log.info(
                    "tool_no_data",
                    tool="get_fundamentals_history",
                    ticker=ticker,
                    reason="window_no_rows",
                    from_date=from_date,
                    to_date=to_date,
                )
            non_phantom = in_window

        if not non_phantom:
            # All rows were phantoms (or filtered out by the date window) —
            # surface no-data so the LLM knows to refuse rather than fabricate.
            # ``item_count=0`` is conveyed by returning None (the orchestrator
            # increments item_count only for non-None returns).
            log.warning(
                "tool_no_data",
                tool="get_fundamentals_history",
                ticker=ticker,
                reason="window_no_rows" if window_active else "all_rows_phantom",
            )
            return None

        table = self._format_fundamentals_table(
            ticker,
            non_phantom,
            current_snapshot=current_snapshot,
        )
        # Value-substantiation (2026-06-26): lift the raw numbers so the eval can
        # verify quoted figures. ``non_phantom`` is ASC by date. FIX 2 (multi-period):
        # a trend answer quotes several periods, so emit up to _GROUNDING_MAX_PERIODS
        # rows (newest first, suffixed) instead of only the latest — otherwise every
        # non-latest figure false-contradicts the single sampled row. Rows may be
        # pydantic models (model_dump) or plain dicts depending on the adapter path.
        row_dicts = [
            (r.model_dump() if hasattr(r, "model_dump") else (r if isinstance(r, dict) else {})) for r in non_phantom
        ]
        grounding_fields = _grounding_fields_from_rows(row_dicts, current_snapshot, ticker=ticker)
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
            grounding_fields=grounding_fields,
            # PLAN-0103 W26 / BP-644: bind the entity_name so the BP-605
            # entity-grounding guard (chat_orchestrator._check_entity_grounding)
            # can match this item to the question's ticker. Pre-W26 the
            # singular handler set no citation_meta, so a TSLA-only question
            # whose only retrieved item was this fundamentals tool result
            # would false-positive the BP-605 refusal.
            citation_meta=CitationMeta(
                title=f"Fundamentals: {ticker}",
                url=None,
                source_name="fundamentals",
                published_at=None,
                entity_name=ticker,
            ),
        )

    async def _handle_get_fundamentals_history_batch(
        self,
        tickers: list[str] | None = None,
        periods: int = 5,
    ) -> list[RetrievedItem]:
        """Fetch fundamentals for many tickers in one HTTP call (PLAN-0095 W2 T-W2-02).

        Calls ``S3Port.get_fundamentals_history_batch`` (backed by S9-proxied
        ``POST /api/v1/fundamentals/batch``). Per-ticker failures are surfaced
        in the rendered text as "— data unavailable: <reason>" rather than
        dropped silently, so the LLM can decide whether to retry the missing
        tickers individually or carry on with what it has.

        R9: returns [] on missing port, invalid input, or upstream timeout.
        R27: read-only — no UnitOfWork.
        """
        ticker_list = [t.strip().upper() for t in (tickers or []) if isinstance(t, str) and t.strip()]
        if not ticker_list:
            log.warning("tool_invalid_param", tool="get_fundamentals_history_batch", reason="empty_tickers")
            return []
        # Mirror the server-side cap (25) so we fail fast with a clear log
        # instead of letting the route return a 422 that becomes ``{}`` here.
        if len(ticker_list) > 25:
            log.warning(
                "tool_invalid_param",
                tool="get_fundamentals_history_batch",
                reason="too_many_tickers",
                count=len(ticker_list),
            )
            ticker_list = ticker_list[:25]

        t0 = time.monotonic()
        try:
            results = await asyncio.wait_for(
                self._s3.get_fundamentals_history_batch(tickers=ticker_list, periods=periods),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_fundamentals_history_batch", error=str(e))
            return []

        if not results:
            log.info("tool_no_data", tool="get_fundamentals_history_batch")
            return []

        # Render one RetrievedItem per ticker so the LLM can cite each ticker
        # independently in its answer. The id namespace ``tool:fundamentals_batch:<ticker>``
        # avoids colliding with singular ``tool:fundamentals:<ticker>`` items
        # if both tools run in the same turn (unlikely but defensible).
        # C6 (2026-07-06): build a CASE-INSENSITIVE view of the upstream results
        # so a ticker whose upstream key differs in case (e.g. the batch endpoint
        # echoes "nvda" while we requested "NVDA") is NOT silently dropped from
        # the output. A dropped ticker previously left the answer with no grounded
        # row for that entity, which let synthesis cross-attribute another
        # entity's figure to it (ru_nvda_amd_revenue_4q: NVDA's row vanished, its
        # value surfaced under AMD). Every requested ticker MUST yield an item.
        results_ci = {str(k).strip().upper(): v for k, v in results.items() if isinstance(v, dict)}

        out: list[RetrievedItem] = []
        for ticker in ticker_list:
            entry = results.get(ticker) or results_ci.get(ticker) or {}
            status = entry.get("status")
            grounding_fields: tuple[tuple[str, str], ...] = ()
            if status == "ok":
                periods_data = entry.get("periods") or []
                # PLAN-0103 W25 / BP-640: forward the per-ticker snapshot
                # block when the batch endpoint surfaced it. Pre-W25 entries
                # had no snapshot field so this defaults to None → table
                # renderer omits the section.
                snap = entry.get("current_snapshot")
                snap_dict = snap if isinstance(snap, dict) else None
                if not periods_data and snap_dict is None:
                    text = f"{ticker}: no quarterly fundamentals available"
                else:
                    text = self._format_fundamentals_table(ticker, periods_data, current_snapshot=snap_dict)
                    # Value-substantiation: lift the raw period numbers (periods are
                    # ASC). FIX 2 (multi-period): emit up to _GROUNDING_MAX_PERIODS
                    # rows (newest first, suffixed) so a batch trend answer's
                    # non-latest figures substantiate instead of false-contradicting.
                    period_dicts = [
                        (p.model_dump() if hasattr(p, "model_dump") else (p if isinstance(p, dict) else {}))
                        for p in periods_data
                    ]
                    grounding_fields = _grounding_fields_from_rows(period_dicts, snap_dict, ticker=ticker)
            else:
                reason = entry.get("reason") or "unknown"
                text = f"{ticker}: data unavailable — {reason}"

            out.append(
                RetrievedItem.create(
                    item_id=f"tool:fundamentals_batch:{ticker}",
                    item_type=ItemType.financial,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=0.88,
                    trust_weight=0.90,
                    grounding_fields=grounding_fields,
                    citation_meta=CitationMeta(
                        title=f"Fundamentals: {ticker}",
                        url=None,
                        source_name="fundamentals",
                        published_at=None,
                        entity_name=ticker,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_fundamentals_history_batch",
            latency_ms=round((time.monotonic() - t0) * 1000),
            ticker_count=len(ticker_list),
            ok_count=sum(1 for t in ticker_list if (results.get(t) or {}).get("status") == "ok"),
        )
        return out

    async def _handle_query_fundamentals(
        self,
        ticker: str,
        metrics: list[str] | None = None,
        periods: int = 8,
        period_type: str = "quarterly",
        include_snapshot: bool = True,
    ) -> RetrievedItem | None:
        """Fetch a parameterised metric projection (PLAN-0104 W32).

        Calls the unified ``POST /api/v1/fundamentals/query`` endpoint and
        formats the result as a compact markdown block that lists each
        metric's coverage flag, the per-period series (when periods > 0),
        and the snapshot scalars (when present). The coverage block lets
        the LLM see at a glance which metrics are reliable ("ok"), which
        need a caveat ("partial"), and which to refuse on ("missing")
        rather than fabricating from a half-empty series.

        R9: returns None on invalid input or upstream timeout (no fake row).
        R27: read-only.
        """
        if not ticker or not metrics:
            log.warning("tool_invalid_param", tool="query_fundamentals", reason="missing_ticker_or_metrics")
            return None

        period_type_norm = (period_type or "quarterly").strip().lower()
        if period_type_norm not in {"quarterly", "annual"}:
            log.warning(
                "tool_invalid_param",
                tool="query_fundamentals",
                param="period_type",
                value=period_type,
                fallback="quarterly",
            )
            period_type_norm = "quarterly"

        query_method = getattr(self._s3, "query_fundamentals", None)
        if query_method is None:
            log.warning("tool_handler_missing_method", tool="query_fundamentals")
            return None

        try:
            bundle = await asyncio.wait_for(
                query_method(
                    ticker=ticker,
                    metrics=metrics,
                    periods=periods,
                    period_type=period_type_norm,
                    include_snapshot=include_snapshot,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="query_fundamentals", error=str(e), ticker=ticker)
            return None

        if not isinstance(bundle, dict):
            log.warning("tool_no_data", tool="query_fundamentals", ticker=ticker)
            return None

        rows: list[dict[str, Any]] = bundle.get("metrics_by_period") or []  # type: ignore[assignment]
        snapshot: dict[str, Any] | None = bundle.get("snapshot")
        coverage: dict[str, str] = bundle.get("coverage") or {}

        if not rows and not snapshot:
            # D7 (2026-07-06): a valid bundle with NO rows and NO snapshot means the
            # requested metric(s) are genuinely uncovered (unsupported metric like
            # ``data_center_revenue``, or no fundamentals for this entity) — NOT a
            # transient failure. Returning ``None`` here made this indistinguishable
            # from the transport/timeout ``except`` path, so the model over-refused
            # ("I couldn't retrieve data") instead of reasoning around a coverage gap.
            # Emit an explicit COVERAGE-GAP sentinel item so synthesis states the
            # metric is not covered rather than treating it as a failure. The
            # ``coverage=not_covered`` grounding marker is NOT allow-listed, so it
            # never leaks into a grounding sample; it just labels the sentinel.
            log.info(
                "tool_coverage_gap",
                tool="query_fundamentals",
                ticker=ticker,
                metrics=metrics,
            )
            upper_ticker = ticker.upper()
            metric_list = ", ".join(metrics)
            return RetrievedItem.create(
                item_id=f"tool:fundamentals:{upper_ticker}:not_covered",
                item_type=ItemType.financial,
                text=(
                    f"Coverage gap: the requested metric(s) for {upper_ticker} "
                    f"({metric_list}) are not covered by the available fundamentals "
                    "data. This is a data-coverage limitation, not a temporary error "
                    "— state that the metric is not available rather than estimating it."
                ),
                score=0.50,
                trust_weight=0.90,
                grounding_fields=(("ticker", upper_ticker), ("coverage", "not_covered")),
                citation_meta=CitationMeta(
                    title=f"Fundamentals query: {upper_ticker} (not covered)",
                    url=None,
                    source_name="fundamentals",
                    published_at=None,
                    entity_name=upper_ticker,
                ),
            )

        # PLAN-0104 W35 / BP-NEW: align the envelope with
        # ``_handle_get_fundamentals_history`` so numeric_grounding can
        # entity-tag this row the same way.
        #
        # 1. ``item_id`` uses the ``tool:fundamentals:<TICKER>`` pattern
        #    (no ``_query`` suffix) — this matches the W28-3 prefix
        #    matcher AND keeps the two fundamentals tools in the same
        #    per-entity candidate pool. We force ``ticker.upper()``
        #    because the LLM occasionally lower-cases the symbol when
        #    quoting it back, and ``_TOOL_PREFIX_TICKER_RE`` requires
        #    ``[A-Z]{1,5}`` after the prefix.
        # 2. ``citation_meta.entity_name`` is also upper-cased so the
        #    fallback path in ``_entity_tag_for`` (step 3) returns a
        #    consistent lower-case ticker.
        # 3. The snapshot block already exposes ``pe_ratio: 37.73x`` /
        #    ``forward_pe: 27.80x`` / ``peg_ratio: 2.15`` etc. (see
        #    ``_format_query_fundamentals`` below); the validator's
        #    text-scan path picks those up via ``classify_number``.
        upper_ticker = ticker.upper()
        text = self._format_query_fundamentals(upper_ticker, metrics, rows, snapshot, coverage)
        # Value-substantiation (2026-06-26): lift the raw numbers so the eval can
        # verify quoted figures. CRITICAL: only emit a metric whose coverage is
        # "ok" — a "missing"/"partial" metric must NOT enter as a phantom number
        # (so the eval correctly leaves an asserted-but-uncovered metric as
        # unsupported). ``rows`` is ASC by date.
        #
        # RC-3 (2026-06-28): emit MULTI-PERIOD grounding (one entry per returned
        # period, newest first, suffixed) like the sibling history/batch handlers
        # — NOT only ``rows[-1]``. A "Tesla revenue since 2023 / last N quarters"
        # answer quotes one figure per quarter; the prior single-latest-row sample
        # left every non-latest quarter unsubstantiated → GROUNDING_FLOOR despite
        # correct figures (RC-3 in docs/audits/2026-06-28-grounding-floor-rootcause.md).
        # ``allowed_canonicals`` is threaded so the per-metric coverage flag is
        # honoured on EVERY period, not just the latest.
        ok_metrics = {m for m in metrics if coverage.get(m, "missing") == "ok"}
        row_dicts = [r for r in rows if isinstance(r, dict)]
        grounding_fields = _grounding_fields_from_rows(
            row_dicts,
            snapshot,
            ticker=upper_ticker,
            allowed_canonicals=ok_metrics,
        )
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{upper_ticker}",
            item_type=ItemType.financial,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
            grounding_fields=grounding_fields,
            citation_meta=CitationMeta(
                title=f"Fundamentals query: {upper_ticker}",
                url=None,
                source_name="fundamentals",
                published_at=None,
                entity_name=upper_ticker,
            ),
        )

    def _format_query_fundamentals(
        self,
        ticker: str,
        metrics: list[str],
        rows: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
        coverage: dict[str, str],
    ) -> str:
        """Render the unified query response as a compact markdown block.

        Layout::

            ## TICKER fundamentals query
            Coverage: metric=flag, metric=flag, ...
            [per-period table when rows]
            [snapshot section when snapshot]
        """
        out: list[str] = [f"## {ticker} fundamentals query"]
        if coverage:
            cov_str = ", ".join(f"{m}={coverage.get(m, 'missing')}" for m in metrics)
            out.append(f"Coverage: {cov_str}")
        if rows:
            # Build a markdown table whose columns are exactly the requested
            # metrics that have at least one non-null value AND are present
            # on the rows (so derived metrics are included automatically).
            # Per-period flow metrics may have no value if all periods were
            # null — we still keep the column so the LLM sees the gap rather
            # than silently dropping it.
            displayed = [m for m in metrics if any(m in r for r in rows)]
            if displayed:
                header = "| Period | Periodicity | " + " | ".join(displayed) + " |"
                divider = "|" + "|".join(["-" * 8] * (2 + len(displayed))) + "|"
                out.append("")
                out.append(header)
                out.append(divider)
                for idx, row in enumerate(rows):
                    # PLAN-0107 follow-up Bug 2 — defensive fallback for the
                    # "Period → Period" missing-number rendering. When both
                    # ``period_label`` and ``period_end`` are null (a
                    # market-data upstream gap; tracked separately by the
                    # BugFix B agent) we used to render the literal "?",
                    # which then encouraged the LLM to write "Period → Period"
                    # with no number. Emit a synthetic, ordinal-indexed label
                    # so the row is still identifiable in the table and the
                    # downstream prose has a concrete identifier to cite.
                    period = row.get("period_label") or row.get("period_end") or f"Period {idx}"
                    ptype = row.get("period_type") or "QUARTERLY"
                    cells = []
                    for m in displayed:
                        v = row.get(m)
                        if v is None:
                            # PLAN-0104 W39: previously rendered "—" which the
                            # LLM (8B-class) sometimes silently skipped or
                            # mis-aligned with adjacent columns.  Explicit
                            # "not available" matches the prompt's MISSING-
                            # METRIC RULE vocabulary so the LLM knows to
                            # refuse on this cell rather than fabricate.
                            cells.append("not available")
                        elif isinstance(v, float):
                            # Margins are fractions; render as percentage so
                            # the LLM does not quote "0.44" as a P/E ratio.
                            if m.endswith("_margin") or m == "fcf_yield":
                                cells.append(f"{v * 100:.2f}%")
                            elif abs(v) >= 1e9:
                                # Cap-style raw amount → defer to the same
                                # B/M formatter so the LLM does not have to
                                # parse 13-digit integers (FIX-LIVE-DD).
                                fmt = _format_market_cap_value(v)
                                cells.append(fmt if fmt is not None else f"{v}")
                            else:
                                cells.append(f"{v:.2f}")
                        else:
                            cells.append(str(v))
                    out.append(f"| {period} | {ptype} | " + " | ".join(cells) + " |")
                # PLAN-0104 W39: per-period explicit-label block emitted AFTER
                # the table.  WHY: Q1 AAPL benchmark (run_20260602T053049Z)
                # showed the LLM initially streamed the correct value but the
                # grounding-rewrite step then reframed the snapshot as
                # "no valid data".  An explicit "<metric>: <value>" listing
                # per row anchors the cell value to its label so the
                # grounding pass cannot mis-classify a populated cell as
                # missing.
                out.append("")
                out.append(f"### {ticker} — Per-period metric listing")
                for idx, row in enumerate(rows):
                    # PLAN-0107 follow-up Bug 2 — see matching fallback in the
                    # period table above. The Per-period metric listing is the
                    # explicit "<metric>: <value>" block the grounding-rewrite
                    # path keys on; emitting "Period {idx}" instead of "?" keeps
                    # each bullet uniquely addressable when upstream label is null.
                    period = row.get("period_label") or row.get("period_end") or f"Period {idx}"
                    out.append(f"- {period}:")
                    for m in displayed:
                        v = row.get(m)
                        if v is None:
                            out.append(f"    - {m}: not available")
                        elif isinstance(v, float):
                            if m.endswith("_margin") or m == "fcf_yield":
                                out.append(f"    - {m}: {v * 100:.2f}%")
                            elif abs(v) >= 1e9:
                                fmt = _format_market_cap_value(v)
                                out.append(f"    - {m}: {fmt if fmt is not None else v}")
                            else:
                                out.append(f"    - {m}: {v:.2f}")
                        else:
                            out.append(f"    - {m}: {v}")
        if snapshot:
            # Snapshot is opt-in — render only when present and there's at
            # least one non-meta field populated.
            #
            # PLAN-0104 W39: render EVERY requested snapshot metric (including
            # ones that came back None) as an explicit "<metric>: <value>" or
            # "<metric>: not available" line.  Pre-W39 we silently dropped
            # None fields, which let the LLM (Q1 AAPL artifact) interpret an
            # absent line as "no data returned" and refuse despite a populated
            # pe_ratio living one section above.  The explicit per-metric
            # label kills that ambiguity.
            as_of = snapshot.get("as_of") or "unknown"
            source = snapshot.get("source") or "highlights"
            snap_lines = [f"\n### {ticker} — Current Snapshot (as-of {as_of}, source: {source})"]
            any_populated = False
            for m in metrics:
                # Skip metadata fields that live in the snapshot dict but are
                # not user-facing metrics.
                if m in {"as_of", "source"}:
                    continue
                v = snapshot.get(m) if isinstance(snapshot, dict) else None
                if v is None:
                    snap_lines.append(f"- {m}: not available")
                    continue
                any_populated = True
                if isinstance(v, float):
                    if m.endswith("_margin") or m == "fcf_yield" or m == "dividend_yield":
                        snap_lines.append(f"- {m}: {v * 100:.2f}%")
                    elif abs(v) >= 1e9:
                        fmt = _format_market_cap_value(v)
                        snap_lines.append(f"- {m}: {fmt if fmt is not None else v} (raw: {v})")
                    elif m.endswith("_ratio") or m in {"forward_pe", "pe_ratio", "ev_ebitda", "price_to_book"}:
                        snap_lines.append(f"- {m}: {v:.2f}x")
                    else:
                        snap_lines.append(f"- {m}: {v:.2f}")
                else:
                    snap_lines.append(f"- {m}: {v}")
            # Always emit the snapshot block when ANY requested metric is
            # listed (populated OR explicitly "not available"), so the LLM
            # always sees the as-of date + per-metric labelling — never an
            # empty subsection that could be misread as "tool returned
            # nothing".
            if any_populated or len(snap_lines) > 1:
                out.extend(snap_lines)
        return "\n".join(out)

    async def _handle_compare_entities(
        self,
        entity_tickers: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Side-by-side fundamentals + price comparison for 2-4 entities (PLAN-0081 Wave A).

        Fetches fundamentals highlights and latest quote in parallel for each ticker.
        R9: returns [] on missing port, invalid input, or upstream errors.
        R27: read-only — no UnitOfWork.

        FQA-04 (BP-626, 2026-05-30): the previous implementation called
        ``get_fundamentals_highlights`` which returns an EODHD-shaped dict
        (``RevenueTTM``, ``EarningsShare``, ``MarketCapitalization``, ...).
        The handler then looked up keys ``revenue``/``eps``/``gross_profit``
        which are *not* present in that payload, so every fundamentals cell
        silently rendered as nothing — the LLM filled the visible gaps with
        ``—`` placeholders and (correctly) refused to fabricate numbers.
        Meanwhile ``get_fundamentals_history_batch`` returns a clean
        ``FundamentalsHistoryPeriod`` row with normalised ``revenue``/``eps``/
        ``gross_profit``/``pe_ratio``/``market_cap`` fields. We now source
        those metrics from the batch endpoint for the *whole ticker list in
        one HTTP call* and fall back to the legacy highlights path *only*
        for tickers the batch could not resolve. That gives the LLM the
        same numbers Q5 sees and aligns the two tool paths on a single
        source of truth.

        FQA-04 carry (PLAN-0103 W14, 2026-05-30): BP-626 unified the FIELD
        NAMES but not the PERIOD WINDOW. ``compare_entities`` previously
        fetched ``periods=1`` (latest quarter only). ``get_fundamentals_
        history_batch`` defaults to ``periods=5``. When ticker A has the
        latest quarter populated but ticker B's latest quarter is still
        pending (revenue/EPS NULL because the report dropped after the
        last EODHD sync), the latest-only window silently rendered B's
        cells as missing while ``get_fundamentals_history_batch(periods=5)``
        had perfectly good data 1-2 quarters back.

        Fix: widen the window to ``periods=4`` (one fiscal year, matches
        the Quote-tab Financials default) AND pick the latest period that
        has all three core metrics (revenue, EPS, gross_profit) populated
        for ALL tickers being compared — the "latest fully populated common
        period". This guarantees side-by-side comparability: every column
        shows the same fiscal quarter. Falls back to per-ticker latest when
        no common period is fully populated (preserves the old behaviour
        for true data-pipeline gaps rather than rendering an empty table).
        """
        if self._s3 is None:
            log.warning("tool_handler_missing_port", tool="compare_entities", port="s3")
            return []

        tickers = entity_tickers or []
        if len(tickers) < 2 or len(tickers) > 4:
            log.warning(
                "tool_invalid_param",
                tool="compare_entities",
                reason="entity_tickers must be 2-4 items",
                count=len(tickers),
            )
            return []

        t0 = time.monotonic()

        # ── Phase 1: 4-quarter fundamentals via the SAME endpoint that
        # get_fundamentals_history_batch uses (FQA-04 / BP-626).  One HTTP
        # call for all 2-4 tickers; per-ticker failures isolated upstream.
        # periods=4 (PLAN-0103 W14) widens the window so we can pick the
        # latest common FULLY-POPULATED period rather than blindly trusting
        # the freshest row — see method docstring for full rationale.
        batch_results: dict[str, dict] = {}
        try:
            batch_results = await asyncio.wait_for(
                self._s3.get_fundamentals_history_batch(tickers=tickers, periods=4),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("compare_entities_batch_failed", error=str(e))
            batch_results = {}

        # ── Phase 1b: select the latest period that has revenue + EPS +
        # gross_profit populated for ALL tickers being compared (PLAN-0103
        # W14). Returns None when no common fully-populated period exists,
        # in which case we fall back to per-ticker latest below.
        common_period = _select_latest_fully_populated_period(tickers, batch_results)

        async def _fetch_per_ticker(ticker: str) -> dict:
            """Fetch instrument_id + quote (+ highlights fallback if needed)."""
            instrument_id = await self._s3.find_instrument_by_ticker(ticker)
            if instrument_id is None:
                return {"ticker": ticker, "error": "not_found"}
            # Always pull quote — that is the freshest live price.  Highlights
            # are only used as a fallback when the batch endpoint returned
            # error/empty for this ticker (preserves the old behaviour for
            # tickers without quarterly history).
            entry = batch_results.get(ticker) or {}
            need_highlights = entry.get("status") != "ok" or not entry.get("periods")
            coros: list[Any] = [self._s3.get_quote(instrument_id)]
            if need_highlights:
                coros.append(self._s3.get_fundamentals_highlights(instrument_id))
            raw_results = list(await asyncio.gather(*coros, return_exceptions=True))
            quote_raw = raw_results[0]
            highlights_raw = raw_results[1] if need_highlights and len(raw_results) > 1 else {}
            return {
                "ticker": ticker,
                "quote": quote_raw if not isinstance(quote_raw, BaseException) else {},
                "highlights": highlights_raw if not isinstance(highlights_raw, BaseException) else {},
            }

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch_per_ticker(t) for t in tickers], return_exceptions=True),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="compare_entities", error=str(e))
            return []

        lines = [f"## Entity Comparison: {', '.join(tickers)}\n"]
        # Value-substantiation (2026-06-26): accumulate grounding_fields across all
        # compared entities into the single returned item. The first entity uses
        # bare metric names; the 2nd+ are suffixed ``_2``/``_3`` (matching the
        # judge's ``_\d+$`` field-name normalisation) so per-entity claims map to
        # the right number. ``entity_idx`` advances only for entities that render.
        compare_grounding: list[tuple[str, str]] = []
        entity_idx = 0
        for item in results:
            # M-3: BaseException is the correct check — asyncio.gather(return_exceptions=True)
            # can return KeyboardInterrupt, SystemExit, etc. which are BaseException but not Exception.
            if isinstance(item, BaseException) or item.get("error"):  # type: ignore[union-attr]
                ticker_label = item.get("ticker", "?") if not isinstance(item, BaseException) else "?"  # type: ignore[union-attr]
                # D8 (2026-07-06): ``find_instrument_by_ticker`` returned None for a
                # ticker that does not resolve to a US-listed instrument (Samsung /
                # Huawei / Xiaomi are not on our US universe). The old bare "data
                # unavailable" line read like a transient gap, so the model filled
                # it with a WRONG entity (iter3_apple_competitors_spanish →
                # hallucinated "Estée Lauder"). Emit an EXPLICIT not-covered /
                # not-US-listed signal so synthesis says so instead of fabricating.
                err = item.get("error") if not isinstance(item, BaseException) else None  # type: ignore[union-attr]
                if err == "not_found":
                    lines.append(
                        f"### {ticker_label} — not covered: ticker not found or not "
                        "US-listed (no fundamentals available)\n"
                    )
                else:
                    lines.append(f"### {ticker_label} — data unavailable\n")
                continue
            ticker = item["ticker"]  # type: ignore[index]
            quote = item.get("quote") or {}  # type: ignore[union-attr]
            highlights = item.get("highlights") or {}  # type: ignore[union-attr]

            # Pick the period row for this ticker. Preferred path: the
            # ``common_period`` selected in Phase 1b — guarantees every
            # column in the rendered table is the SAME fiscal quarter so
            # the LLM is comparing like-for-like (FQA-04 carry / PLAN-0103
            # W14). Fall back to the per-ticker latest only when no common
            # fully-populated period exists for the comparison set.
            #
            # ``periods`` is sorted ASC by date so the latest is the LAST
            # element. The batch endpoint guarantees ``revenue``/``eps``/
            # ``gross_profit``/``pe_ratio``/``market_cap`` are present
            # (nullable) on each row.
            batch_entry = batch_results.get(ticker) or {}
            latest_period: dict[str, Any] = {}
            period_label: str | None = None
            if batch_entry.get("status") == "ok":
                periods_data = batch_entry.get("periods") or []
                if periods_data:
                    chosen = _pick_period_row(periods_data, common_period)
                    # FundamentalsHistoryPeriod is a pydantic BaseModel post-
                    # http; the adapter passes it through as a dict.  Defensive
                    # against either shape so a future contract tweak does not
                    # silently re-introduce the original bug.
                    if hasattr(chosen, "model_dump"):
                        latest_period = chosen.model_dump()
                    elif isinstance(chosen, dict):
                        latest_period = chosen
                    period_label = latest_period.get("period")

            lines.append(f"### {ticker}")
            if period_label:
                lines.append(f"  Period: {period_label}")
            if quote:
                price = quote.get("price") or quote.get("close") or quote.get("last_price")
                if price:
                    lines.append(f"  Price: {price}")

            # Metric merge priority: batch (normalised) → highlights fallback
            # (EODHD-cased keys).  Each entry maps the rendered label to the
            # candidate value list — first non-None wins.
            metric_specs: list[tuple[str, list[Any]]] = [
                (
                    "market_cap",
                    [latest_period.get("market_cap"), highlights.get("MarketCapitalization")],
                ),
                (
                    "pe_ratio",
                    [latest_period.get("pe_ratio"), highlights.get("PERatio")],
                ),
                (
                    "revenue",
                    [latest_period.get("revenue"), highlights.get("RevenueTTM")],
                ),
                (
                    "gross_profit",
                    [latest_period.get("gross_profit"), highlights.get("GrossProfitTTM")],
                ),
                (
                    "eps",
                    [latest_period.get("eps"), highlights.get("DilutedEpsTTM"), highlights.get("EarningsShare")],
                ),
            ]
            # Per-entity grounding bag: ticker first, then each resolved metric as
            # a RAW number. Suffix non-first entities (``_2``/``_3``...) so the
            # judge can disambiguate which ticker a claim refers to.
            suffix = "" if entity_idx == 0 else f"_{entity_idx + 1}"
            entity_grounding: list[tuple[str, str]] = [(f"ticker{suffix}", ticker)]
            quote_price = _coerce_grounding_number(quote.get("price") or quote.get("close") or quote.get("last_price"))
            if quote_price is not None:
                entity_grounding.append((f"price{suffix}", quote_price))
            for key, candidates in metric_specs:
                val = next((c for c in candidates if c is not None), None)
                if val is None:
                    continue
                num = _coerce_grounding_number(val)
                if num is not None:
                    entity_grounding.append((f"{key}{suffix}", num))
                # FIX-LIVE-DD: pre-format cap-style metrics so the LLM does not
                # have to read 13-digit integers and hallucinate trillion/
                # billion labels (the original screener fix, now reused here).
                if key in ("market_cap", "revenue", "gross_profit"):
                    formatted = _format_market_cap_value(val)
                    if formatted is not None:
                        lines.append(f"  {key.replace('_', ' ').title()}: {formatted} (raw: {val})")
                        continue
                lines.append(f"  {key.replace('_', ' ').title()}: {val}")
            compare_grounding.extend(entity_grounding)
            entity_idx += 1
            lines.append("")

        # D8 (2026-07-06): when NO requested entity resolved to a US-listed
        # instrument (e.g. an all-non-US comparison set), make the coverage
        # boundary explicit so synthesis refuses rather than substituting an
        # unrelated company. Without this the single returned item was just a
        # header + "not covered" lines, which the model back-filled with a
        # fabricated entity.
        if entity_idx == 0:
            lines.append(
                "Note: none of the requested entities are covered by US-listed "
                "fundamentals data. Do not fabricate figures or substitute a "
                "different company — state that the requested comparison data is "
                "not available."
            )

        text = "\n".join(lines)
        log.info(
            "tool_executed",
            tool="compare_entities",
            latency_ms=round((time.monotonic() - t0) * 1000),
            ticker_count=len(tickers),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:compare:{'-'.join(tickers)}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                grounding_fields=tuple(compare_grounding),
                citation_meta=CitationMeta(
                    title=f"Comparison: {', '.join(tickers)}",
                    url=None,
                    source_name="fundamentals",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_screen_universe(
        self,
        market_cap_min: float | None = None,
        market_cap_max: float | None = None,
        pe_ratio_max: float | None = None,
        sector: str | None = None,
        industry: str | None = None,
        region: str | None = None,
        limit: int = 20,
        # PLAN-0103 W1 (BP-622): explicit metric-filter parameters so the
        # LLM can ask for fundamentals-grade screens (revenue growth, gross
        # margin, ROE, dividend yield, etc.) without the kwarg being silently
        # dropped by the dispatch gate.  Each maps to a ScreenFilterRequest
        # entry keyed off the matching market-data ``metric`` column —
        # the names mirror metric_extractor.py:171 so the LLM can ask using
        # the same vocabulary the screener API documents.
        revenue_growth_yoy_min: float | None = None,
        revenue_growth_yoy_max: float | None = None,
        gross_margin_min: float | None = None,
        gross_margin_max: float | None = None,
        roe_min: float | None = None,
        dividend_yield_min: float | None = None,
        dividend_yield_max: float | None = None,
    ) -> list[RetrievedItem]:
        """Quantitative screener via S9 POST /v1/fundamentals/screen (PLAN-0081 Wave A).

        Builds a filter dict from LLM-supplied params and forwards to S3BriefPort.
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="screen_universe", port="s3_brief")
            return []

        # FIX-LIVE-T (2026-05-25): The S3 ``POST /v1/fundamentals/screen`` endpoint
        # expects ``ScreenRequest`` with a ``filters: list[ScreenFilterRequest]``
        # body — top-level ``sector``/``industry``/``market_cap_min`` were silently
        # ignored as unknown pydantic fields, so the call effectively ran the
        # "no-filter" path and returned 50 unrelated tickers (Healthcare,
        # Industrials, …). FIX-LIVE-Q's allowlist hint could not help because the
        # LLM never saw the right tickers in the result. Build a proper filter
        # list here. WHY ``market_capitalization`` (and not ``market_cap_usd``):
        # the screener metric whitelist is keyed off the DB metric column, where
        # cap is stored as ``market_capitalization``; ``market_cap_usd`` is only a
        # display-side alias from the /screen/fields endpoint.
        filter_list: list[dict[str, Any]] = []

        # ``ScreenFilterRequest.sector``/``industry`` are *per-filter* fields
        # (not body-level) and only one filter can carry them — replicate them
        # on every entry so the WHERE clause AND-combines correctly.
        scope: dict[str, str] = {}
        if sector:
            scope["sector"] = sector
        # FIX-LIVE-M (2026-05-24): GICS industry filter — more selective than sector.
        if industry:
            scope["industry"] = industry

        if market_cap_min is not None or market_cap_max is not None:
            entry: dict[str, Any] = {"metric": "market_capitalization", **scope}
            if market_cap_min is not None:
                entry["min_value"] = market_cap_min
            if market_cap_max is not None:
                entry["max_value"] = market_cap_max
            filter_list.append(entry)

        if pe_ratio_max is not None:
            filter_list.append({"metric": "pe_ratio", "max_value": pe_ratio_max, **scope})

        # PLAN-0103 W1 (BP-622): fundamentals-grade metric filters. Each builds
        # a ScreenFilterRequest entry against the corresponding column name in
        # market_data.metric_extractor. The DB-side name (e.g.
        # ``quarterly_revenue_growth_yoy``) is hidden from the LLM behind the
        # friendlier ``revenue_growth_yoy_min/max`` parameter pair.
        metric_filter_specs: list[tuple[str, float | None, float | None]] = [
            ("quarterly_revenue_growth_yoy", revenue_growth_yoy_min, revenue_growth_yoy_max),
            ("gross_margin", gross_margin_min, gross_margin_max),
            ("roe", roe_min, None),
            ("dividend_yield", dividend_yield_min, dividend_yield_max),
        ]
        for metric_name, mn, mx in metric_filter_specs:
            if mn is None and mx is None:
                continue
            entry = {"metric": metric_name, **scope}
            if mn is not None:
                entry["min_value"] = mn
            if mx is not None:
                entry["max_value"] = mx
            filter_list.append(entry)

        # If the LLM only supplied sector/industry (no numeric thresholds) we
        # still need ONE filter entry so the sector/industry predicates bind —
        # screener body-level fields don't exist. Use a no-op cap floor of 0.
        if not filter_list and scope:
            filter_list.append({"metric": "market_capitalization", "min_value": 0, **scope})

        # WHY clamp limit: prevent the LLM from requesting huge result sets that
        # would overflow the context window budget. Hard upper bound is the
        # ScreenRequest ``le=200`` constraint.
        clamped_limit = max(1, min(int(limit), 100))

        # ``region`` is not a ScreenFilterRequest field, so it is dropped here
        # (no DB column for it). Track it in the log so we notice if the LLM
        # routinely supplies it and we need to add support upstream.
        if region:
            log.info("tool_arg_dropped", tool="screen_universe", arg="region", value=region)

        # Chat-eval #4 / #5 (2026-06-12): pass an explicit ``sort_by``/``sort_dir``
        # so the rendered top-N is the TRUE top-N. The screener used to return
        # rows in arbitrary order and truncate at ``limit`` — so "top 5 tech by
        # market cap" got whatever 5 rows came back first (CRM/IBM instead of
        # GOOGL/AVGO/META). We default the sort to the PRIMARY filter metric
        # descending (the column the question actually filtered on). A separate
        # market-data agent is adding backend ``sort_by`` support; until then the
        # field is forward-compatible (ignored if unsupported upstream).
        #
        # ``_PRIMARY_SORT_METRIC`` is the first filter's metric — that is the
        # metric the user keyed the screen on (market_capitalization, pe_ratio,
        # quarterly_revenue_growth_yoy, …). "max-only" filters (e.g. pe_ratio_max
        # for "cheapest") sort ascending; "min-only"/range filters sort
        # descending (largest/highest first), which matches "top N by X" intent.
        sort_by = filter_list[0]["metric"] if filter_list else "market_capitalization"
        _first = filter_list[0] if filter_list else {}
        sort_dir = "asc" if (_first.get("max_value") is not None and _first.get("min_value") is None) else "desc"

        payload: dict[str, Any] = {
            "filters": filter_list,
            "limit": clamped_limit,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.screen_instruments(payload),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="screen_universe", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="screen_universe")
            return []

        instruments = raw.get("instruments") or raw.get("results") or raw.get("data") or []
        # Value-substantiation (2026-06-26 STEP B): per-instrument grounding bag,
        # populated for the top few rows inside the render loop below.
        screen_grounding: list[tuple[str, str]] = []
        screen_grounding_rows = 0
        if not instruments:
            text = "No instruments matched the screening criteria."
        else:
            # Chat-eval #4 (2026-06-12): render the metric columns the user
            # FILTERED on (plus a small core set), not just ticker/name/MCap/PE.
            # Previously the formatter dropped ``revenue_growth_yoy`` / ``revenue``
            # / ``roe`` etc., so the LLM could not ground "YoY revenue growth",
            # re-fetched fundamentals, hand-computed ratios, and those LLM-derived
            # numbers failed NumericGroundingValidator (unsupported_count=39 on
            # ``ru_ai_semi_screener``). We surface the raw values directly so the
            # answer can cite them with no extra tool round-trip.
            #
            # ``_screen_metric_columns`` maps the DB metric names used in the
            # filter list to the response-row keys the screener returns. The
            # filtered metrics come first (most relevant to the question), then a
            # core set, de-duplicated and order-preserving.
            _filter_metric_names = [f["metric"] for f in filter_list]
            metric_cols = _screen_metric_columns(_filter_metric_names)

            lines = [f"## Screener Results ({len(instruments)} instruments, sorted by {sort_by} {sort_dir})\n"]
            for inst in instruments[:50]:
                ticker = inst.get("ticker") or inst.get("symbol") or "?"
                name = inst.get("name") or ""
                row = f"  {ticker}"
                # Value-substantiation (2026-06-26 STEP B): lift the TOP few rows'
                # ticker/pe_ratio/market_cap/revenue onto the single screener item
                # under suffixed keys, so an answer citing a screened ticker's P/E
                # or cap substantiates. Bounded to _SCREEN_GROUNDING_MAX_ROWS — the
                # per-row field/byte caps in build_grounding_sample bound it further.
                if screen_grounding_rows < _SCREEN_GROUNDING_MAX_ROWS and ticker != "?":
                    suffix = "" if screen_grounding_rows == 0 else f"_{screen_grounding_rows + 1}"
                    screen_grounding.append((f"ticker{suffix}", str(ticker)))
                    pe_num = _coerce_grounding_number(
                        next((inst.get(k) for k in ("pe_ratio", "pe", "trailing_pe") if inst.get(k) is not None), None)
                    )
                    if pe_num is not None:
                        screen_grounding.append((f"pe_ratio{suffix}", pe_num))
                    cap_num = _coerce_grounding_number(
                        next(
                            (
                                inst.get(k)
                                for k in ("market_cap", "market_capitalization", "market_cap_usd")
                                if inst.get(k) is not None
                            ),
                            None,
                        )
                    )
                    if cap_num is not None:
                        screen_grounding.append((f"market_cap{suffix}", cap_num))
                    rev_num = _coerce_grounding_number(
                        next((inst.get(k) for k in ("revenue", "revenue_ttm") if inst.get(k) is not None), None)
                    )
                    if rev_num is not None:
                        screen_grounding.append((f"revenue{suffix}", rev_num))
                    screen_grounding_rows += 1
                if name:
                    row += f" — {name}"
                for col_label, row_keys in metric_cols:
                    val = next((inst.get(k) for k in row_keys if inst.get(k) not in (None, "")), None)
                    if val is None:
                        continue
                    if col_label == "MCap":
                        # FIX-LIVE-DD: render BOTH raw and formatted. The raw
                        # integer is kept for the numeric-grounding validator
                        # (tolerance-matches `$5.23T` ↔ ``5230000000000``);
                        # the formatted label is what the LLM copies into its
                        # answer.
                        formatted = _format_market_cap_value(val)
                        row += f" | MCap: {formatted} (raw: {val})" if formatted is not None else f" | MCap: {val}"
                    else:
                        row += f" | {col_label}: {val}"
                lines.append(row)
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="screen_universe",
            latency_ms=round((time.monotonic() - t0) * 1000),
            result_count=len(instruments) if isinstance(instruments, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id="tool:screener:results",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.82,
                trust_weight=0.80,
                grounding_fields=tuple(screen_grounding),
                citation_meta=CitationMeta(
                    title="Screener results",
                    url=None,
                    source_name="screener",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_market_movers(
        self,
        mover_type: str = "gainers",
        limit: int = 10,
        period: str = "1D",
    ) -> list[RetrievedItem]:
        """Top gainers/losers via S9 GET /v1/market/top-movers (PLAN-0081 Wave A).

        C-2: period default changed to "1D" (uppercase) to match S9 contract.
        C-3: "most_active" removed — S9 only accepts "gainers" and "losers".
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_market_movers", port="s3_brief")
            return []

        # C-3: "most_active" is NOT a valid S9 mover_type — only "gainers" and "losers" are accepted.
        # WHY removed: sending "most_active" to S9 causes a 422 validation error downstream.
        valid_types = {"gainers", "losers"}
        safe_mover_type = mover_type if mover_type in valid_types else "gainers"
        limit_clamped = max(1, min(int(limit), 50))

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.get_top_movers(
                    mover_type=safe_mover_type,
                    limit=limit_clamped,
                    period=period,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_market_movers", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="get_market_movers")
            return []

        movers = raw.get("movers") or raw.get("data") or raw.get("results") or []
        # Value-substantiation (2026-06-26 STEP B): accumulate a per-mover
        # grounding bag so an answer citing "TICKER +X.XX%" / "@ price" can be
        # substantiated against the values the tool actually returned. ALL movers
        # share ONE RetrievedItem (the markdown table is a single block), so we
        # pack each mover under suffixed keys (``ticker``/``change_pct``/``price``,
        # then ``ticker_2``/...). The sse_emitter admits ``_\d+$`` keys whose base
        # is allow-listed; the W1 matcher strips the suffix back to the base metric.
        # change_pct is emitted as a RAW PERCENT NUMBER ("4.27", not "4.27%") — the
        # matcher's percentage typing handles the unit, and "change_pct" is in
        # _PERCENT_VALUED_FIELDS-equivalent percent kind via its name.
        mover_grounding: list[tuple[str, str]] = []
        if not movers:
            text = f"No {safe_mover_type} data available for period {period}."
        else:
            lines = [f"## Market Movers — {safe_mover_type.replace('_', ' ').title()} ({period})\n"]
            for idx, m in enumerate(movers[:limit_clamped]):
                ticker = m.get("ticker") or m.get("symbol") or "?"
                change_pct = m.get("change_percent") or m.get("change_pct") or m.get("changePercent")
                price = m.get("price") or m.get("close")
                row = f"  {ticker}"
                if change_pct is not None:
                    row += f" {change_pct:+.2f}%" if isinstance(change_pct, float) else f" {change_pct}"
                if price:
                    row += f" @ {price}"
                lines.append(row)
                # idx 0 → bare keys; idx N → ``_<N+1>`` suffix (matcher strips _\d+$).
                suffix = "" if idx == 0 else f"_{idx + 1}"
                if ticker and ticker != "?":
                    mover_grounding.append((f"ticker{suffix}", str(ticker)))
                cp_num = _coerce_grounding_number(change_pct)
                if cp_num is not None:
                    mover_grounding.append((f"change_pct{suffix}", cp_num))
                price_num = _coerce_grounding_number(price)
                if price_num is not None:
                    mover_grounding.append((f"price{suffix}", price_num))
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_market_movers",
            latency_ms=round((time.monotonic() - t0) * 1000),
            mover_type=safe_mover_type,
            count=len(movers) if isinstance(movers, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:movers:{safe_mover_type}:{period}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.85,
                trust_weight=0.82,
                grounding_fields=tuple(mover_grounding),
                citation_meta=CitationMeta(
                    title=f"Market movers: {safe_mover_type} ({period})",
                    url=None,
                    source_name="market_data",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_prediction_markets(
        self,
        query: str | None = None,
        category: str | None = None,
        status: str = "open",
        limit: int = 10,
    ) -> list[RetrievedItem]:
        """Search Polymarket prediction markets via S9 GET /v1/signals/prediction-markets.

        Returns ONE RetrievedItem per matching market so each carries its own
        clickable ``citation_meta.url`` (the canonical Polymarket event link
        derived from ``market_slug``). The text block renders the question,
        current outcome probabilities (implied odds), resolution date, 24h
        volume, and category so the LLM can answer "what are the odds of X".

        R9: returns [] on missing port, invalid input, or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_prediction_markets", port="s3_brief")
            return []

        # Normalise status against the values market-data's list endpoint
        # accepts (it 422s on anything else). Default/unknown → "open".
        status_norm = (status or "open").strip().lower()
        if status_norm not in {"open", "resolved", "cancelled", "all"}:
            log.warning(
                "tool_invalid_param",
                tool="get_prediction_markets",
                param="status",
                value=status,
                fallback="open",
            )
            status_norm = "open"
        # Clamp limit to the tool's advertised 1-50 band (server caps at 200).
        limit_clamped = max(1, min(int(limit), 50))
        query_norm = query.strip() if isinstance(query, str) and query.strip() else None
        category_norm = category.strip() if isinstance(category, str) and category.strip() else None

        t0 = time.monotonic()
        try:
            markets = await asyncio.wait_for(
                self._s3_brief.get_prediction_markets(
                    query=query_norm,
                    category=category_norm,
                    status=status_norm,
                    limit=limit_clamped,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_prediction_markets", error=str(e))
            return []

        if not markets:
            log.info("tool_no_data", tool="get_prediction_markets", query=query_norm, category=category_norm)
            return []

        out: list[RetrievedItem] = []
        for m in markets[:limit_clamped]:
            if not isinstance(m, dict):
                continue
            market_id = str(m.get("market_id") or "")
            question = str(m.get("question") or "").strip() or "(untitled market)"
            slug = m.get("market_slug")
            # Canonical Polymarket deep link from the slug (search fallback on
            # null/empty/malformed slug) — mirrors the frontend helper exactly.
            url = _build_polymarket_url(slug, question)

            # Render the outcome probabilities. Outcomes are [{name, token_id, price}]
            # where price is the implied probability 0.0-1.0. Most markets are
            # binary (Yes/No) but we render whatever outcomes are present.
            outcomes = m.get("outcomes") or []
            odds_parts: list[str] = []
            if isinstance(outcomes, list):
                for o in outcomes:
                    if not isinstance(o, dict):
                        continue
                    name = str(o.get("name") or "").strip()
                    pct = _format_probability(o.get("price"))
                    if name and pct is not None:
                        odds_parts.append(f"{name} {pct}")
            odds_line = ", ".join(odds_parts) if odds_parts else "no current odds"

            close_time = m.get("close_time")
            resolution = str(close_time) if close_time else "TBD"
            volume = m.get("volume_24h")
            volume_str = _format_market_cap_value(volume) or "n/a"
            cat = m.get("category") or "uncategorized"
            res_status = m.get("resolution_status") or status_norm

            lines = [
                f"## {question}",
                f"- Implied odds: {odds_line}",
                f"- Resolution date: {resolution}",
                f"- 24h volume: {volume_str}",
                f"- Category: {cat}  |  Status: {res_status}",
                f"- Source: Polymarket — {url}",
            ]
            text = "\n".join(lines)

            published_at = _parse_iso_datetime(m.get("updated_at"))
            # BUG-1 (2026-07-01): BP-604/605 requires every retrieval source to set
            # a non-null entity_id OR citation_meta.entity_name — a null here made
            # the entity-grounding guard refuse the whole answer
            # (entity_grounding_failed item_entity_names:[null,null]). Prediction
            # markets are NOT a single ticker; the market's subject IS the user's
            # topic (the market was ILIKE-matched to the query). Use the market's
            # category as a stable, human-readable subject label, falling back to a
            # generic label. (The entity-grounding guard ALSO exempts topic-matched
            # polymarket items — see _check_entity_grounding — so grounding no
            # longer depends on the flaky question-entity resolution.)
            entity_label = str(cat).strip().title() if isinstance(cat, str) and cat.strip() else "Prediction Market"
            out.append(
                RetrievedItem.create(
                    item_id=f"tool:prediction_market:{market_id or question[:32]}",
                    item_type=ItemType.financial,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=0.84,
                    # Prediction markets are a market-priced signal, not an
                    # authoritative filing — mid trust (eodhd_news tier).
                    trust_weight=0.70,
                    published_at=published_at,
                    citation_meta=CitationMeta(
                        title=question,
                        url=url,
                        source_name="polymarket",
                        published_at=published_at,
                        entity_name=entity_label,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_prediction_markets",
            latency_ms=round((time.monotonic() - t0) * 1000),
            query=query_norm,
            category=category_norm,
            count=len(out),
        )
        return out

    async def _handle_get_economic_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        region: str | None = None,
    ) -> list[RetrievedItem]:
        """Upcoming macro events (CPI, FOMC, GDP) via S9 GET /v1/fundamentals/economic-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_economic_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            events = await asyncio.wait_for(
                self._s3_brief.get_economic_calendar(
                    from_date=from_date,
                    to_date=to_date,
                    region=region,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_economic_calendar", error=str(e))
            return []

        if not events:
            log.info("tool_no_data", tool="get_economic_calendar")
            return []

        lines = ["## Economic Calendar\n"]
        for evt in events[:30]:
            date_str = evt.get("date") or evt.get("event_date") or ""
            name = evt.get("name") or evt.get("event") or evt.get("title") or "?"
            actual = evt.get("actual")
            forecast = evt.get("forecast") or evt.get("estimate")
            prev = evt.get("previous") or evt.get("prior")
            row = f"  {date_str}  {name}"
            if actual is not None:
                row += f" | Actual: {actual}"
            if forecast is not None:
                row += f" | Forecast: {forecast}"
            if prev is not None:
                row += f" | Prior: {prev}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_economic_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            event_count=len(events),
        )
        return [
            RetrievedItem.create(
                item_id="tool:economic_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Economic calendar",
                    url=None,
                    source_name="economic_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_earnings_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[RetrievedItem]:
        """Earnings release dates via S9 GET /v1/fundamentals/earnings-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_earnings_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            earnings = await asyncio.wait_for(
                self._s3_brief.get_earnings_calendar(
                    from_date=from_date,
                    to_date=to_date,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_earnings_calendar", error=str(e))
            return []

        if not earnings:
            log.info("tool_no_data", tool="get_earnings_calendar")
            return []

        lines = ["## Earnings Calendar\n"]
        for entry in earnings[:30]:
            date_str = entry.get("date") or entry.get("report_date") or ""
            ticker = entry.get("ticker") or entry.get("symbol") or "?"
            name = entry.get("name") or entry.get("company") or ""
            eps_est = entry.get("eps_estimate") or entry.get("eps_forecast")
            eps_act = entry.get("eps_actual")
            row = f"  {date_str}  {ticker}"
            if name:
                row += f" ({name})"
            if eps_est is not None:
                row += f" | EPS Est: {eps_est}"
            if eps_act is not None:
                row += f" | EPS Actual: {eps_act}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_earnings_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            entry_count=len(earnings),
        )
        return [
            RetrievedItem.create(
                item_id="tool:earnings_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Earnings calendar",
                    url=None,
                    source_name="earnings_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    def _format_price_table(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        interval: str,
        bars: list[dict[str, Any]],
    ) -> str:
        """Format OHLCV bars as a markdown table with a header line.

        Cat-B B2 (2026-06-28): the per-bar table now renders ``High`` and ``Low``
        columns (they were computed into ``grounding_fields`` but NEVER into the
        text the LLM sees, so the model truthfully but wrongly reported "high/low
        not available" for a YTD-range question — a split-brain between the eval
        wire and the LLM context, docs/audits/2026-06-28-cat-b-screener-missingness.md).
        We also prepend an explicit aggregated WINDOW SUMMARY line (period high /
        low / range / first / last close / N bars) so a "high and low so far this
        year" question has the aggregate to copy rather than asking the model to
        fold ~120 bars itself — an aggregation it is unreliable at.
        """
        # ── Window summary (the aggregate the model should copy, not compute) ──
        # Collect numeric extrema defensively: a None/garbled bar field must never
        # poison the max/min (mirrors _grounding_fields_from_bars' guard).
        highs = [float(h) for b in bars if (h := _coerce_grounding_number(b.get("high"))) is not None]
        lows = [float(low) for b in bars if (low := _coerce_grounding_number(b.get("low"))) is not None]
        summary = ""
        if highs or lows:
            parts: list[str] = []
            if highs:
                parts.append(f"high ${max(highs):.2f}")
            if lows:
                parts.append(f"low ${min(lows):.2f}")
            if highs and lows:
                parts.append(f"range ${max(highs) - min(lows):.2f}")
            # First / last close anchor the trajectory endpoints for a series
            # question (Cat-C C1: a "plot last 90 days" answer summarises rather
            # than enumerates every bar).
            first_close = _coerce_grounding_number(bars[0].get("close")) if bars else None
            last_close = _coerce_grounding_number(bars[-1].get("close")) if bars else None
            if first_close is not None:
                parts.append(f"first close ${float(first_close):.2f}")
            if last_close is not None:
                parts.append(f"last close ${float(last_close):.2f}")
            parts.append(f"{len(bars)} bars")
            summary = f"Window summary: {' — '.join(parts)}\n"

        header = summary + f"{ticker} price history ({interval}, {from_date} → {to_date})\n"
        header += "| Date       | High   | Low    | Close  | Volume |\n"
        header += "|------------|--------|--------|--------|--------|\n"
        rows = []
        for b in bars:
            close = b.get("close", 0) or 0
            volume = b.get("volume", 0) or 0
            # High/Low may be absent on a degenerate bar — render "—" rather than
            # a fabricated 0 so the LLM never quotes a phantom extremum.
            hi_raw = _coerce_grounding_number(b.get("high"))
            lo_raw = _coerce_grounding_number(b.get("low"))
            hi = f"${float(hi_raw):.2f}" if hi_raw is not None else "—"
            lo = f"${float(lo_raw):.2f}" if lo_raw is not None else "—"
            rows.append(f"| {b.get('date', '?')} | {hi} | {lo} | ${float(close):.2f} | {int(volume):,} |")
        return header + "\n".join(rows)

    def _format_fundamentals_table(
        self,
        ticker: str,
        periods: list[dict[str, Any]],
        current_snapshot: dict[str, Any] | None = None,
    ) -> str:
        """Format quarterly fundamentals as a markdown table.

        PLAN-0097 T-W1-02 (BP-577): every row carries an explicit
        ``Periodicity`` column so the LLM cannot quote a TTM/ANNUAL value as
        quarterly without seeing the mismatch in the table itself. The use
        case (``GetFundamentalsHistoryUseCase``) tags every output row with
        ``period_type="QUARTERLY"`` (income_statement filter + EARNINGS_HISTORY
        is quarterly-only). We default to ``QUARTERLY`` if the field is
        missing rather than ``UNKNOWN`` to stay forward-compatible with any
        future use-case version that drops the label; if the upstream ever
        starts returning ANNUAL/TTM rows here, the prompt grounding will
        surface the mismatch and the validator will catch quoted values that
        don't align with the user's quarter intent. The header row also
        states "Periodicity: QUARTERLY" so the LLM sees the contract before
        reading the cells.
        """
        # Cat-A FIX 3 (2026-06-28, period precision): the table now carries TWO
        # period-identity columns — the fiscal ``Period`` label AND the explicit
        # ``Period End`` ISO date — so a question that names a quarter by its
        # period-end date ("fiscal Q4 2024 ending Sep 28 2024") can be bound to
        # the matching row by date, not just by a fiscal label the model might
        # mis-anchor (the Apple two-Sep-28-Q4s trap, docs/audits/
        # 2026-06-28-cat-a-period-selection.md). Revenue/Net Income are rendered
        # UN-ROUNDED (full precision) alongside the human-readable $X.XXXB form,
        # because the prior ``$X.1f B`` rounding made 3-decimal-precision
        # questions impossible to answer from the cell, so the model padded
        # digits ("$102.500B") that were themselves unsubstantiated.
        header = f"{ticker} quarterly fundamentals (Periodicity: QUARTERLY)\n"
        header += "| Period | Period End | Periodicity | Revenue | Net Income | EPS | P/E |\n"
        header += "|--------|------------|-------------|---------|------------|-----|-----|\n"
        rows = []
        for p in periods:
            rev_val = p.get("revenue") or p.get("totalRevenue")
            # Render BOTH the rounded billions form (readability) and the raw,
            # un-rounded value (precision) so the LLM-visible cell can support a
            # 3-decimal answer without padding. e.g. "$94.930B (raw: 94930000000)".
            rev = f"${float(rev_val) / 1e9:.3f}B (raw: {_fmt_raw_number(rev_val)})" if rev_val else "—"
            ni_val = p.get("net_income") or p.get("netIncome")
            ni = f"${float(ni_val) / 1e9:.3f}B (raw: {_fmt_raw_number(ni_val)})" if ni_val else "—"
            eps_val = p.get("eps") or p.get("epsActual")
            eps = f"${float(eps_val):.2f}" if eps_val else "—"
            pe_val = p.get("pe_ratio") or p.get("pe")
            pe = f"{float(pe_val):.1f}x" if pe_val else "—"
            period_label = p.get("period") or p.get("date") or "?"
            # Explicit ISO period-end date (the unambiguous anchor). The history
            # use case tags every row with ``period_end_date``; ``query_fundamentals``
            # uses ``period_end``. Tolerate both, and fall back to "—" so the
            # column is always present (the LLM sees the date is unavailable
            # rather than the column silently vanishing).
            period_end = p.get("period_end_date") or p.get("period_end") or p.get("date") or "—"
            # Explicit per-row periodicity tag. Fall back to QUARTERLY because
            # this formatter is only ever called from the quarterly-history
            # path; an ANNUAL row leaking here would be a contract violation
            # that we want the LLM to see, but until BP-577 audit confirms a
            # provenance for any non-QUARTERLY rows, QUARTERLY is the safer
            # default than leaving the cell blank.
            periodicity = p.get("period_type") or "QUARTERLY"
            rows.append(f"| {period_label} | {period_end} | {periodicity} | {rev} | {ni} | {eps} | {pe} |")
        table = header + "\n".join(rows)

        # PLAN-0103 W25 / BP-640: snapshot block — emitted AFTER the period
        # table so the LLM cannot conflate the two. The block is rendered as
        # a small markdown subsection with explicit "as-of <date>" and
        # source="highlights" labels. Every field is opt-in: missing values
        # are omitted entirely rather than rendered as "—", because the
        # ratio-or-TTM prompt rule (tool_use.py v1.5) tells the LLM to
        # refuse rather than fabricate when a snapshot field is missing.
        if current_snapshot:
            snap_lines: list[str] = []
            import contextlib

            snap_pe = current_snapshot.get("pe_ratio")
            if snap_pe is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  P/E (TTM): {float(snap_pe):.2f}x")
            snap_ev = current_snapshot.get("ev_ebitda")
            if snap_ev is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  EV/EBITDA: {float(snap_ev):.2f}x")
            snap_mc = current_snapshot.get("market_cap_usd")
            if snap_mc is not None:
                snap_mc_fmt = _format_market_cap_value(snap_mc)
                if snap_mc_fmt is not None:
                    snap_lines.append(f"  Market Cap: {snap_mc_fmt} (raw: {snap_mc})")
            snap_pb = current_snapshot.get("price_to_book")
            if snap_pb is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  Price/Book: {float(snap_pb):.2f}x")
            snap_dy = current_snapshot.get("dividend_yield")
            if snap_dy is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  Dividend Yield: {float(snap_dy):.4f}")
            # PLAN-0104 W30 / BP-649: forward P/E + PEG ratio. Emitted only
            # when non-None — missing snapshot fields are NEVER rendered as
            # "—", because tool_use.py v1.5 instructs the LLM to refuse
            # rather than fabricate when a snapshot field is absent.
            snap_fpe = current_snapshot.get("forward_pe")
            if snap_fpe is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  Forward P/E: {float(snap_fpe):.2f}x")
            snap_peg = current_snapshot.get("peg_ratio")
            if snap_peg is not None:
                with contextlib.suppress(TypeError, ValueError):
                    snap_lines.append(f"  PEG Ratio: {float(snap_peg):.2f}")
            if snap_lines:
                as_of = current_snapshot.get("as_of") or "unknown"
                source = current_snapshot.get("source") or "highlights"
                snap_header = f"\n\n### {ticker} Current Snapshot (as-of {as_of}, source: {source})\n"
                table = table + snap_header + "\n".join(snap_lines)
        return table
