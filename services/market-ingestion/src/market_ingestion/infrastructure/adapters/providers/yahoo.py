"""YahooFinanceProviderAdapter — OHLCV daily/weekly/monthly via yfinance."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import yfinance as yf  # type: ignore[import-untyped]

from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.base import BaseProviderAdapter

# Yahoo Finance interval mapping — only daily/weekly/monthly supported for free tier.
# Keys are the internal timeframe strings used across the application; values are
# the interval codes expected by the yfinance Ticker.history() API.
_YF_INTERVAL_MAP: dict[str, str] = {
    "1d": "1d",  # daily bars
    "1w": "1wk",  # weekly bars
    "1mo": "1mo",  # monthly bars (long form)
    "1M": "1mo",  # monthly bars (short form alias)
}
# Use a frozenset for O(1) membership checks in the hot path.
_SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset(_YF_INTERVAL_MAP.keys())


class YahooFinanceProviderAdapter(BaseProviderAdapter):
    """Yahoo Finance adapter using yfinance library.

    Supports OHLCV daily/weekly/monthly data at zero credit cost.
    yfinance is a synchronous library — all calls run in an executor to avoid
    blocking the async event loop.
    """

    @property
    def provider(self) -> Provider:
        return Provider.YAHOO_FINANCE

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch OHLCV bars for *symbol* at the given *timeframe*.

        Supported timeframes: "1d" (daily), "1w" / "1mo" / "1M" (weekly, monthly).
        Raises ProviderUnavailable for intraday timeframes not supported by yfinance
        free tier.

        Args:
            symbol:    Ticker symbol (e.g. "AAPL", "MSFT").
            timeframe: Timeframe code — must be one of "1d", "1w", "1mo", "1M".
            start:     Inclusive range start (UTC); None means earliest available.
            end:       Exclusive range end (UTC); None means latest available.
            exchange:  Optional exchange suffix (e.g. "L" for London Stock Exchange).
                       When provided the ticker sent to Yahoo is "SYMBOL.EXCHANGE".

        Returns:
            ProviderFetchResult with raw_data containing a JSON-encoded list of bar
            dicts, each with keys: timestamp, open, high, low, close, volume.

        Raises:
            ProviderUnavailable: For unsupported timeframes, network errors, or any
                                 exception raised by yfinance during the fetch.
        """
        if timeframe not in _SUPPORTED_TIMEFRAMES:
            raise ProviderUnavailable(
                f"Yahoo Finance adapter only supports daily/weekly/monthly timeframes; got {timeframe!r}"
            )

        interval = _YF_INTERVAL_MAP[timeframe]
        # Yahoo Finance uses "SYMBOL.EXCHANGE" format for non-US symbols.
        # For US symbols (no exchange) just pass the bare ticker symbol.
        ticker_sym = f"{symbol}.{exchange}" if exchange else symbol

        t0 = time.monotonic()
        try:
            # yfinance is synchronous — run in executor to avoid blocking event loop.
            # The lambda captures the current values of all local variables so they
            # are not affected by any subsequent re-binding in an unlikely code path.
            # Wrapped with wait_for to enforce a 30s ceiling on the blocking call.
            loop = asyncio.get_running_loop()
            raw_records: list[dict[str, Any]] = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _download_ohlcv(ticker_sym, interval, start, end),
                ),
                timeout=30.0,
            )
        except ProviderUnavailable:
            # Re-raise our own domain errors unchanged so callers can catch them.
            raise
        except TimeoutError as exc:
            self._record_error(reason="timeout", endpoint="ohlcv")
            raise ProviderUnavailable(f"Yahoo Finance fetch timed out for {symbol!r}") from exc
        except Exception as exc:
            self._record_error(reason="fetch_failed", endpoint="ohlcv")
            raise ProviderUnavailable(f"Yahoo Finance fetch failed for {symbol!r}: {type(exc).__name__}") from exc

        duration_ms = int((time.monotonic() - t0) * 1000)
        # Serialise the list of bar dicts to JSON bytes for storage/downstream use.
        raw_bytes = json.dumps(raw_records).encode()
        bars_returned = len(raw_records)

        self._record_api_call(
            dataset_type=DatasetType.OHLCV.value,
            symbol=symbol,
            exchange=exchange or "",
            timeframe=timeframe,
            bars_returned=bars_returned,
            latency_ms=duration_ms,
            credit_cost=0,  # Yahoo Finance free tier — no credit cost
        )

        return ProviderFetchResult(
            provider=Provider.YAHOO_FINANCE,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            raw_data=raw_bytes,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            range_start=start,
            range_end=end,
            bars_returned=bars_returned,
        )

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Yahoo Finance adapter: use EODHD for quotes/fundamentals")

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Yahoo Finance adapter: use EODHD for quotes/fundamentals")


def _download_ohlcv(
    ticker: str,
    interval: str,
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    """Download OHLCV bars from Yahoo Finance (synchronous — runs in executor).

    This is a module-level function (not a method) so that it can be patched
    easily in unit tests via ``unittest.mock.patch``.

    Args:
        ticker:   Full ticker string, possibly "SYMBOL.EXCHANGE".
        interval: yfinance interval code (e.g. "1d", "1wk", "1mo").
        start:    Inclusive range start (UTC); None means earliest available.
        end:      Exclusive range end (UTC); None means latest available.

    Returns:
        A list of bar dicts, each with keys:
        - timestamp: ISO 8601 string (from the DataFrame index)
        - open:      float
        - high:      float
        - low:       float
        - close:     float (auto-adjusted)
        - volume:    int
    """
    kwargs: dict[str, Any] = {
        "interval": interval,
        # auto_adjust=True applies corporate action adjustments (splits, dividends)
        # to OHLCV prices so the series is consistent over long histories.
        "auto_adjust": True,
        # progress=False suppresses the tqdm progress bar that yfinance prints to
        # stdout when downloading multi-symbol batches.
        "progress": False,
    }
    if start:
        kwargs["start"] = start.strftime("%Y-%m-%d")
    if end:
        kwargs["end"] = end.strftime("%Y-%m-%d")

    ticker_obj = yf.Ticker(ticker)
    hist = ticker_obj.history(**kwargs)

    # Empty DataFrame means no data available for the requested range/symbol.
    if hist.empty:
        return []

    records: list[dict[str, Any]] = []
    for ts, row in hist.iterrows():
        records.append(
            {
                # Convert pandas Timestamp to ISO 8601 string for JSON serialisation.
                "timestamp": ts.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                # Volume is an integer count; cast explicitly to avoid float64 in JSON.
                "volume": int(row["Volume"]),
            }
        )
    return records
