"""HTTP adapter for the Market Data service (S3) OHLCV API (PRD-0020 §6.5).

Calls ``GET /api/v1/market-data/ohlcv/{symbol}?start={date}&end={date}`` and
returns a typed ``OHLCVBar`` dataclass (or ``None`` on 404 / any HTTP error).

No exceptions are propagated to the caller — all errors are swallowed and
logged as warnings so a single bad symbol never aborts the labelling cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import date

    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class OHLCVBar:
    """Typed OHLCV bar returned by the Market Data service."""

    symbol: str
    date: date
    open: Decimal
    close: Decimal
    high: Decimal
    low: Decimal
    volume: int | None


class MarketDataClient:
    """Async HTTP client for the internal Market Data (S3) OHLCV API.

    Usage::

        async with httpx.AsyncClient(timeout=10.0) as http:
            client = MarketDataClient(http, "http://market-data:8003")
            bar = await client.get_ohlcv("AAPL", date(2026, 4, 1))
    """

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def get_ohlcv(self, symbol: str, bar_date: date) -> OHLCVBar | None:
        """Return the daily OHLCV bar for *symbol* on *bar_date*, or ``None``.

        Returns ``None`` on:
          - HTTP 404 (symbol/date not found — normal for non-listed instruments)
          - Any ``httpx.RequestError`` (timeout, connection refused, …)
          - Non-200/404 HTTP status code
          - Unexpected response format (parsing error)

        Callers should treat ``None`` as "no data" and create a zero-impact label.
        """
        url = f"{self._base_url}/api/v1/market-data/ohlcv/{symbol}"
        params = {"start": bar_date.isoformat(), "end": bar_date.isoformat()}

        try:
            response = await self._client.get(url, params=params)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_request_error",
                symbol=symbol,
                date=bar_date.isoformat(),
                error=str(exc),
            )
            return None

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_unexpected_status",
                symbol=symbol,
                date=bar_date.isoformat(),
                status_code=response.status_code,
            )
            return None

        try:
            data = response.json()
            items = data.get("items", [])
            if not items:
                return None
            bar = items[0]
            price_open = Decimal(str(bar["open"]))
            price_close = Decimal(str(bar["close"]))
            if price_open <= Decimal("0") or price_close <= Decimal("0"):
                logger.warning(  # type: ignore[no-any-return]
                    "market_data_client_invalid_prices",
                    symbol=symbol,
                    date=bar_date.isoformat(),
                    open=str(price_open),
                    close=str(price_close),
                )
                return None
            return OHLCVBar(
                symbol=symbol,
                date=bar_date,
                open=price_open,
                close=price_close,
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                volume=bar.get("volume"),
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_parse_error",
                symbol=symbol,
                date=bar_date.isoformat(),
                error=str(exc),
            )
            return None
