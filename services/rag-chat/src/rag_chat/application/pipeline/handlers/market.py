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
import time
from datetime import UTC, date
from typing import TYPE_CHECKING, Any

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
        interval: str = "week",
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
            buffer_seconds = max(implied_seconds * 2, 86400)  # >= 1 day
            buffer_seconds = min(buffer_seconds, 365 * 86400)  # cap at 1y
            _to = _dt.now(tz=UTC).date()
            _from = _to - _td(seconds=buffer_seconds)
        elif lookback_days is not None and lookback_days > 0:
            _to = _dt.now(tz=UTC).date()
            _from = _to - _td(days=int(lookback_days))
        else:
            # Default: most recent 20 bars at requested interval.
            n = 20
            interval_seconds = _INTERVAL_SECONDS_MAP.get(interval, 86400)
            buffer_seconds = max(n * interval_seconds * 2, 86400)
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
            # /ohlcv/bars returns ascending; take the trailing N.
            bars = sorted(
                bars,
                key=lambda b: b.get("ts") or b.get("bar_date") or "",
            )[-n:]

        # ── Step 4: format ──────────────────────────────────────────────
        table = self._format_price_table(ticker, str(_from), str(_to), interval, bars)
        # Distinguish "single most-recent bar" responses in the citation
        # so the LLM/UI can present them as "last known price" rather
        # than full history. Only n==1 paths get the latest_1m suffix.
        item_id = (
            f"tool:price_history:{ticker}:latest_1m" if n == 1 and interval == "1m" else f"tool:price_history:{ticker}"
        )
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
        )

    async def _handle_get_fundamentals_history(
        self,
        ticker: str,
        periods: int = 8,
        period_type: str = "quarterly",
    ) -> RetrievedItem | None:
        """Fetch fundamentals and format as a markdown table RetrievedItem.

        F-LIVE-P (2026-05-26): ``period_type`` ("quarterly" default, or
        "annual") selects the periodicity sent to market-data. Anything
        outside the allowlist falls back to "quarterly" with a structured
        warning — the LLM occasionally invents values like "ttm" or
        "trailing", and the safer behaviour is to honour the user-visible
        default rather than 500 on an unknown enum.
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

        if not non_phantom:
            # All rows were phantoms — surface no-data so the LLM knows to
            # refuse rather than fabricate. ``item_count=0`` is conveyed by
            # returning None (the orchestrator increments item_count only for
            # non-None returns).
            log.warning(
                "tool_no_data",
                tool="get_fundamentals_history",
                ticker=ticker,
                reason="all_rows_phantom",
            )
            return None

        table = self._format_fundamentals_table(
            ticker,
            non_phantom,
            current_snapshot=current_snapshot,
        )
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
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
        out: list[RetrievedItem] = []
        for ticker in ticker_list:
            entry = results.get(ticker) or {}
            status = entry.get("status")
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
            log.warning("tool_no_data", tool="query_fundamentals", ticker=ticker)
            return None

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
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{upper_ticker}",
            item_type=ItemType.financial,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
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
        for item in results:
            # M-3: BaseException is the correct check — asyncio.gather(return_exceptions=True)
            # can return KeyboardInterrupt, SystemExit, etc. which are BaseException but not Exception.
            if isinstance(item, BaseException) or item.get("error"):  # type: ignore[union-attr]
                ticker_label = item.get("ticker", "?") if not isinstance(item, BaseException) else "?"  # type: ignore[union-attr]
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
            for key, candidates in metric_specs:
                val = next((c for c in candidates if c is not None), None)
                if val is None:
                    continue
                # FIX-LIVE-DD: pre-format cap-style metrics so the LLM does not
                # have to read 13-digit integers and hallucinate trillion/
                # billion labels (the original screener fix, now reused here).
                if key in ("market_cap", "revenue", "gross_profit"):
                    formatted = _format_market_cap_value(val)
                    if formatted is not None:
                        lines.append(f"  {key.replace('_', ' ').title()}: {formatted} (raw: {val})")
                        continue
                lines.append(f"  {key.replace('_', ' ').title()}: {val}")
            lines.append("")

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

        payload: dict[str, Any] = {"filters": filter_list, "limit": clamped_limit}

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
        if not instruments:
            text = "No instruments matched the screening criteria."
        else:
            lines = [f"## Screener Results ({len(instruments)} instruments)\n"]
            for inst in instruments[:50]:
                ticker = inst.get("ticker") or inst.get("symbol") or "?"
                name = inst.get("name") or ""
                mc = inst.get("market_cap")
                pe = inst.get("pe_ratio")
                row = f"  {ticker}"
                if name:
                    row += f" — {name}"
                if mc is not None and mc != "":
                    # FIX-LIVE-DD: render BOTH raw and formatted. The raw
                    # integer is kept for the numeric-grounding validator
                    # (tolerance-matches `$5.23T` ↔ ``5230000000000``);
                    # the ``MCap`` (formatted) label is what the LLM
                    # actually copies into its answer.
                    formatted = _format_market_cap_value(mc)
                    if formatted is not None:
                        row += f" | MCap: {formatted} (raw: {mc})"
                    else:
                        # Legacy/string path: upstream already gave a
                        # display-ready label like ``"3T"`` — keep it.
                        row += f" | MCap: {mc}"
                if pe:
                    row += f" | P/E: {pe}"
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
        if not movers:
            text = f"No {safe_mover_type} data available for period {period}."
        else:
            lines = [f"## Market Movers — {safe_mover_type.replace('_', ' ').title()} ({period})\n"]
            for m in movers[:limit_clamped]:
                ticker = m.get("ticker") or m.get("symbol") or "?"
                change_pct = m.get("change_percent") or m.get("change_pct") or m.get("changePercent")
                price = m.get("price") or m.get("close")
                row = f"  {ticker}"
                if change_pct is not None:
                    row += f" {change_pct:+.2f}%" if isinstance(change_pct, float) else f" {change_pct}"
                if price:
                    row += f" @ {price}"
                lines.append(row)
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
                citation_meta=CitationMeta(
                    title=f"Market movers: {safe_mover_type} ({period})",
                    url=None,
                    source_name="market_data",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

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
        """Format OHLCV bars as a markdown table with a header line."""
        header = f"{ticker} price history ({interval}, {from_date} → {to_date})\n"
        header += "| Date       | Close  | Volume |\n|------------|--------|--------|\n"
        rows = []
        for b in bars:
            close = b.get("close", 0) or 0
            volume = b.get("volume", 0) or 0
            rows.append(f"| {b.get('date', '?')} | ${float(close):.2f} | {int(volume):,} |")
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
        header = f"{ticker} quarterly fundamentals (Periodicity: QUARTERLY)\n"
        header += "| Period | Periodicity | Revenue | Net Income | EPS | P/E |\n"
        header += "|--------|-------------|---------|------------|-----|-----|\n"
        rows = []
        for p in periods:
            rev_val = p.get("revenue") or p.get("totalRevenue")
            rev = f"${float(rev_val) / 1e9:.1f}B" if rev_val else "—"
            ni_val = p.get("net_income") or p.get("netIncome")
            ni = f"${float(ni_val) / 1e9:.1f}B" if ni_val else "—"
            eps_val = p.get("eps") or p.get("epsActual")
            eps = f"${float(eps_val):.2f}" if eps_val else "—"
            pe_val = p.get("pe_ratio") or p.get("pe")
            pe = f"{float(pe_val):.1f}x" if pe_val else "—"
            period_label = p.get("period") or p.get("date") or "?"
            # Explicit per-row periodicity tag. Fall back to QUARTERLY because
            # this formatter is only ever called from the quarterly-history
            # path; an ANNUAL row leaking here would be a contract violation
            # that we want the LLM to see, but until BP-577 audit confirms a
            # provenance for any non-QUARTERLY rows, QUARTERLY is the safer
            # default than leaving the cell blank.
            periodicity = p.get("period_type") or "QUARTERLY"
            rows.append(f"| {period_label} | {periodicity} | {rev} | {ni} | {eps} | {pe} |")
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
