"""Provider fetch dispatch — maps DatasetType to the correct adapter call.

All logic here is I/O only (awaits adapter calls). No storage or DB writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import DatasetType

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import ProviderAdapter, ProviderFetchResult
    from market_ingestion.domain.entities.ingestion_task import IngestionTask

# ISO-3166 alpha-3 → alpha-2 mapping used by EODHD /economic-events.
# WHY: seed symbols use alpha-3 (e.g. "EVENTS.USA") for consistency with other datasets;
# EODHD requires alpha-2 (e.g. "US"). Map at call time rather than at seed time.
_ISO3_TO_ISO2: dict[str, str] = {
    "USA": "US",
    "GBR": "GB",
    "EUR": "EU",
    "JPN": "JP",
    "CHN": "CN",
    "CAN": "CA",
    "AUS": "AU",
    "DEU": "DE",
    "FRA": "FR",
    "ITA": "IT",
}


async def fetch_for_task(adapter: ProviderAdapter, task: IngestionTask) -> ProviderFetchResult:
    """Dispatch a fetch call to the correct adapter method based on DatasetType.

    Intraday OHLCV (1m/5m/15m/30m/1h/4h) uses ``fetch_intraday``; EOD OHLCV uses
    ``fetch_ohlcv``. All other dataset types have their own dedicated adapter method.
    FUNDAMENTALS is the default (final else branch).
    """
    if task.dataset_type == DatasetType.OHLCV:
        # EXT-01: intraday vs EOD dispatch based on timeframe.
        # Intraday timeframes include 15m, 30m, 4h in addition to 1m, 5m, 1h —
        # extended to match PLAN-0040 A-2 / PRD-0032 intraday set.
        if task.timeframe in {"1m", "5m", "15m", "30m", "1h", "4h"}:
            ext_adapter = cast("Any", adapter)
            return cast(
                "ProviderFetchResult",
                await ext_adapter.fetch_intraday(
                    symbol=task.symbol,
                    interval=task.timeframe,
                    exchange=task.exchange,
                ),
            )
        return await adapter.fetch_ohlcv(
            symbol=task.symbol,
            timeframe=task.timeframe or "1d",
            start=task.range_start,
            end=task.range_end,
            exchange=task.exchange,
        )

    if task.dataset_type == DatasetType.QUOTES:
        return await adapter.fetch_quotes(
            symbol=task.symbol,
            exchange=task.exchange,
        )

    if task.dataset_type == DatasetType.EARNINGS_CALENDAR:
        from datetime import timedelta

        today = utc_now().date()
        ext_adapter = cast("Any", adapter)
        return cast(
            "ProviderFetchResult",
            await ext_adapter.fetch_earnings_calendar(
                from_date=(today - timedelta(days=14)).isoformat(),
                to_date=(today + timedelta(days=14)).isoformat(),
            ),
        )

    if task.dataset_type == DatasetType.ECONOMIC_EVENTS:
        from datetime import timedelta

        today = utc_now().date()
        # symbol encodes country: "EVENTS.USA" → "USA"
        _raw_country = task.symbol.split(".")[-1] if "." in task.symbol else "USA"
        country = _ISO3_TO_ISO2.get(_raw_country, _raw_country)
        ext_adapter = cast("Any", adapter)
        return cast(
            "ProviderFetchResult",
            await ext_adapter.fetch_economic_events(
                from_date=(today - timedelta(days=14)).isoformat(),
                to_date=(today + timedelta(days=14)).isoformat(),
                country=country,
            ),
        )

    if task.dataset_type == DatasetType.MACRO_INDICATOR:
        ext_adapter = cast("Any", adapter)
        return cast("ProviderFetchResult", await ext_adapter.fetch_macro_indicator(symbol=task.symbol))

    if task.dataset_type == DatasetType.NEWS_SENTIMENT:
        from datetime import timedelta

        today = utc_now().date()
        ext_adapter = cast("Any", adapter)
        return cast(
            "ProviderFetchResult",
            await ext_adapter.fetch_news_sentiment(
                symbol=task.symbol,
                from_date=(today - timedelta(days=7)).isoformat(),
                to_date=today.isoformat(),
            ),
        )

    if task.dataset_type == DatasetType.INSIDER_TRANSACTIONS:
        ext_adapter = cast("Any", adapter)
        return cast("ProviderFetchResult", await ext_adapter.fetch_insider_transactions(ticker=task.symbol))

    if task.dataset_type == DatasetType.YIELD_CURVE:
        ext_adapter = cast("Any", adapter)
        return cast("ProviderFetchResult", await ext_adapter.fetch_yield_curve(series_symbol=task.symbol))

    if task.dataset_type == DatasetType.MARKET_CAP:
        ext_adapter = cast("Any", adapter)
        return cast("ProviderFetchResult", await ext_adapter.fetch_historical_market_cap(ticker=task.symbol))

    # FUNDAMENTALS (default)
    return await adapter.fetch_fundamentals(
        symbol=task.symbol,
        variant=task.variant or "annual",
        exchange=task.exchange,
    )
