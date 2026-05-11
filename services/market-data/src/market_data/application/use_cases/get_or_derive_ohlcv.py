"""GetOrDeriveOHLCVBarsUseCase — serve weekly/monthly bars from derived storage.

For the ``1w`` and ``1M`` timeframes, this use case:
  1. Tries to fetch pre-computed derived bars from the repository.
  2. If fewer than ``limit`` derived bars exist, triggers ``DeriveOHLCVUseCase``
     to recompute them from the stored daily bars.
  3. Re-fetches and returns up to ``limit`` bars sorted descending by date.

For all other timeframes (including ``1d``) the request is passed through
directly to the OHLCV repository without any derivation (PLAN-0036 W2-5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_data.application.use_cases.derive_ohlcv import _DERIVABLE, DeriveOHLCVUseCase
from market_data.domain.enums import Timeframe
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.domain.entities import OHLCVBar

logger = get_logger(__name__)


class GetOrDeriveOHLCVBarsUseCase:
    """Return OHLCV bars for a symbol/exchange/timeframe, deriving on cache miss.

    For non-derivable timeframes (``1d``, intraday) the call is a simple pass-
    through to the underlying read repository so there is no performance impact
    on the common daily-bar path.

    For weekly (``1w``) and monthly (``1M``) bars:
    * A cache-hit path avoids derivation when enough derived bars already exist.
    * A cache-miss path runs ``DeriveOHLCVUseCase`` then re-fetches.

    Usage::

        async with uow_factory() as uow:
            uc = GetOrDeriveOHLCVBarsUseCase(uow)
            bars = await uc.execute(symbol="AAPL", exchange="US", timeframe="1w")
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        *,
        limit: int = 200,
    ) -> list[OHLCVBar]:
        """Return up to ``limit`` bars for the given symbol/exchange/timeframe.

        Parameters
        ----------
        symbol:
            Instrument ticker symbol.
        exchange:
            Exchange code.
        timeframe:
            OHLCV bar timeframe string (e.g. ``"1d"``, ``"1w"``, ``"1M"``).
        limit:
            Maximum number of bars to return.

        Returns
        -------
        list[OHLCVBar]
            Bars sorted descending by ``bar_date`` (most recent first).
        """
        # ── 1. Parse timeframe ────────────────────────────────────────────────
        try:
            tf = Timeframe(timeframe)
        except ValueError as exc:
            raise ValueError(f"Unknown timeframe: {timeframe!r}") from exc

        log = logger.bind(symbol=symbol, exchange=exchange, timeframe=tf, limit=limit)

        # ── 2. Pass-through for non-derivable timeframes ──────────────────────
        # Daily and intraday bars are never derived — fetch directly.
        if tf not in _DERIVABLE:
            log.debug("get_or_derive.passthrough")
            return await self._fetch_direct(symbol, exchange, tf, limit=limit)

        # ── 3. Try cache (derived bars already stored) ────────────────────────
        instrument = await self._uow.instruments_read.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            log.warning("get_or_derive.instrument_not_found")
            return []

        derived = await self._uow.ohlcv_read.find_derived(instrument.id, tf, limit=limit)

        if len(derived) >= limit:
            # Enough derived bars in store — return without re-deriving.
            log.debug("get_or_derive.cache_hit", count=len(derived))
            return derived

        # ── 4. Cache miss — derive and re-fetch ───────────────────────────────
        log.info("get_or_derive.cache_miss", existing=len(derived))

        derive_uc = DeriveOHLCVUseCase(self._uow)
        derived_count = await derive_uc.execute(
            symbol=symbol,
            exchange=exchange,
            source_timeframe="1d",
            target_timeframe=timeframe,
        )

        log.info("get_or_derive.derived", count=derived_count)

        # Re-fetch after derivation — the UoW was committed inside DeriveOHLCVUseCase.
        return await self._uow.ohlcv_read.find_derived(instrument.id, tf, limit=limit)

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _fetch_direct(
        self,
        symbol: str,
        exchange: str,
        tf: Timeframe,
        *,
        limit: int,
    ) -> list[OHLCVBar]:
        """Fetch bars directly from the read repository for non-derivable timeframes."""
        instrument = await self._uow.instruments_read.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            return []

        date_range = await self._uow.ohlcv_read.get_date_range(instrument.id, tf)
        if date_range is None:
            return []

        start_date, end_date = date_range
        # Fetch the full range then truncate — find_by_instrument_timeframe_range
        # returns ascending order; we reverse to give most-recent-first output.
        bars = await self._uow.ohlcv_read.find_by_instrument_timeframe_range(
            instrument.id,
            tf,
            start_date,
            end_date,
        )
        # Sort descending (most recent first) and apply the limit.
        bars_desc = sorted(bars, key=lambda b: b.bar_date, reverse=True)
        return bars_desc[:limit]
