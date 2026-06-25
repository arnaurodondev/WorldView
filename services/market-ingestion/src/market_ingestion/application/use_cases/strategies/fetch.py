"""Provider fetch dispatch — maps DatasetType to the correct adapter call.

All logic here is I/O only (awaits adapter calls). No storage or DB writes.

PLAN-0107 A-3
-------------
Three dispatch branches (EOD OHLCV, FUNDAMENTALS, EARNINGS_CALENDAR) optionally
funnel through :class:`MarketDataCache` when one is injected by the worker
composition root. Wrapping happens at this layer (not inside the adapter) so
the cache key is built from the *intent* (dataset/symbol/period) and therefore
survives a provider swap (EODHD → Polygon).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, cast

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import (
    CacheDatasetType,
    DatasetType,
    Provider,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from market_ingestion.application.ports.adapters import ProviderAdapter, ProviderFetchResult
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.cache.market_data_cache import MarketDataCache

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


# ---------------------------------------------------------------------------
# ProviderFetchResult <-> JSON envelope (for MarketDataCache payload).
#
# ``ProviderFetchResult`` is a frozen dataclass containing ``bytes`` and
# ``datetime`` fields that ``json.dumps`` cannot serialise natively. We
# round-trip via a small envelope: bytes → base64, datetime → ISO-8601,
# enums → their ``.value``. The schema is internal to this module; if
# ``ProviderFetchResult`` ever grows new fields, update both helpers and
# bump the ``_ENVELOPE_VERSION`` so stale cache entries are rejected.
# ---------------------------------------------------------------------------

_ENVELOPE_VERSION = 1


def _encode_fetch_result(result: ProviderFetchResult) -> dict[str, Any]:
    """Convert a ``ProviderFetchResult`` into a JSON-serialisable envelope."""
    return {
        "_v": _ENVELOPE_VERSION,
        "provider": result.provider.value,
        "dataset_type": result.dataset_type.value,
        "symbol": result.symbol,
        "raw_data_b64": base64.b64encode(result.raw_data).decode("ascii"),
        "content_type": result.content_type,
        "fetched_at": result.fetched_at.isoformat(),
        "duration_ms": result.duration_ms,
        "range_start": result.range_start.isoformat() if result.range_start is not None else None,
        "range_end": result.range_end.isoformat() if result.range_end is not None else None,
        "provider_metadata": result.provider_metadata,
        "bars_returned": result.bars_returned,
    }


def _decode_fetch_result(envelope: dict[str, Any]) -> ProviderFetchResult:
    """Reverse :func:`_encode_fetch_result`. Returns a fresh frozen dataclass."""
    # Imports here (not at module top) to keep the runtime import graph cheap
    # and to avoid a circular import via ``application.ports.adapters``.
    from datetime import datetime

    from market_ingestion.application.ports.adapters import ProviderFetchResult

    if envelope.get("_v") != _ENVELOPE_VERSION:
        # Caller treats this as a deserialisation error → cache miss → refetch.
        raise ValueError(f"unsupported cache envelope version: {envelope.get('_v')!r}")

    range_start_raw = envelope.get("range_start")
    range_end_raw = envelope.get("range_end")
    return ProviderFetchResult(
        provider=Provider(envelope["provider"]),
        dataset_type=DatasetType(envelope["dataset_type"]),
        symbol=envelope["symbol"],
        raw_data=base64.b64decode(envelope["raw_data_b64"].encode("ascii")),
        content_type=envelope["content_type"],
        fetched_at=datetime.fromisoformat(envelope["fetched_at"]),
        duration_ms=int(envelope["duration_ms"]),
        range_start=datetime.fromisoformat(range_start_raw) if range_start_raw else None,
        range_end=datetime.fromisoformat(range_end_raw) if range_end_raw else None,
        provider_metadata=envelope.get("provider_metadata"),
        bars_returned=int(envelope.get("bars_returned", 0)),
    )


async def _cached(
    cache: MarketDataCache,
    *,
    dataset_type: CacheDatasetType,
    symbol: str,
    period_key: str,
    provider_label: str,
    fetcher: Callable[[], Awaitable[ProviderFetchResult]],
) -> ProviderFetchResult:
    """Route a ``ProviderFetchResult``-producing fetch through ``MarketDataCache``.

    Encodes the envelope on miss-fill, decodes on hit. A decode failure is
    treated as a cache miss by the underlying class (logged + dropped).
    """

    async def _encoded_fetcher() -> dict[str, Any]:
        return _encode_fetch_result(await fetcher())

    raw = await cache.get_or_fetch(
        dataset_type=dataset_type,
        symbol=symbol,
        period_key=period_key,
        fetcher=_encoded_fetcher,
        provider_label=provider_label,
    )
    return _decode_fetch_result(raw)


async def fetch_for_task(
    adapter: ProviderAdapter,
    task: IngestionTask,
    *,
    cache: MarketDataCache | None = None,
) -> ProviderFetchResult:
    """Dispatch a fetch call to the correct adapter method based on DatasetType.

    Intraday OHLCV (1m/5m/15m/30m/1h/4h) uses ``fetch_intraday``; EOD OHLCV uses
    ``fetch_ohlcv``. All other dataset types have their own dedicated adapter method.
    FUNDAMENTALS is the default (final else branch).

    When ``cache`` is provided, three branches are wrapped in a read-through
    cache (PLAN-0107 A-3): EOD OHLCV, FUNDAMENTALS, EARNINGS_CALENDAR. Intraday
    OHLCV and every other branch bypass the cache (TTLs too short or no
    natural period key).
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
        # EOD OHLCV -- cacheable. ``period_key`` encodes timeframe + range so
        # different windows do not collide.
        timeframe = task.timeframe or "1d"
        start_iso = task.range_start.isoformat() if task.range_start is not None else ""
        end_iso = task.range_end.isoformat() if task.range_end is not None else ""

        async def _fetch_ohlcv() -> ProviderFetchResult:
            return await adapter.fetch_ohlcv(
                symbol=task.symbol,
                timeframe=timeframe,
                start=task.range_start,
                end=task.range_end,
                exchange=task.exchange,
            )

        if cache is not None:
            return await _cached(
                cache,
                dataset_type=CacheDatasetType.OHLCV_EOD,
                symbol=task.symbol,
                period_key=f"{timeframe}:{start_iso}:{end_iso}",
                provider_label=adapter.provider.value,
                fetcher=_fetch_ohlcv,
            )
        return await _fetch_ohlcv()

    if task.dataset_type == DatasetType.QUOTES:
        return await adapter.fetch_quotes(
            symbol=task.symbol,
            exchange=task.exchange,
        )

    if task.dataset_type == DatasetType.EARNINGS_CALENDAR:
        from datetime import timedelta

        today = utc_now().date()
        from_date = (today - timedelta(days=14)).isoformat()
        to_date = (today + timedelta(days=14)).isoformat()
        ext_adapter = cast("Any", adapter)

        async def _fetch_earnings() -> ProviderFetchResult:
            return cast(
                "ProviderFetchResult",
                await ext_adapter.fetch_earnings_calendar(
                    from_date=from_date,
                    to_date=to_date,
                ),
            )

        if cache is not None:
            return await _cached(
                cache,
                dataset_type=CacheDatasetType.EARNINGS_CALENDAR,
                symbol=task.symbol,
                period_key=f"{from_date}:{to_date}",
                provider_label=adapter.provider.value,
                fetcher=_fetch_earnings,
            )
        return await _fetch_earnings()

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

    # FUNDAMENTALS (default) -- cacheable. ``period_key`` is ``"latest"``: the
    # adapter call has no range argument and we want the same cache hit
    # regardless of variant (annual vs quarterly) because variant rides in
    # the response envelope.
    variant = task.variant or "annual"

    async def _fetch_fundamentals() -> ProviderFetchResult:
        return await adapter.fetch_fundamentals(
            symbol=task.symbol,
            variant=variant,
            exchange=task.exchange,
        )

    if cache is not None:
        return await _cached(
            cache,
            dataset_type=CacheDatasetType.FUNDAMENTALS_SNAPSHOT,
            symbol=task.symbol,
            period_key="latest",
            provider_label=adapter.provider.value,
            fetcher=_fetch_fundamentals,
        )
    return await _fetch_fundamentals()
