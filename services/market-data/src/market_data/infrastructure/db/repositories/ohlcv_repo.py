"""PostgreSQL adapter for OHLCVRepository.

Key implementation detail: ``bulk_upsert_with_priority`` uses
``INSERT ... ON CONFLICT DO UPDATE SET ... WHERE EXCLUDED.provider_priority
>= ohlcv_bars.provider_priority`` so that lower-priority data never
overwrites a higher-priority stored record.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import OHLCVRepository
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgOHLCVRepository(OHLCVRepository):
    """SQLAlchemy-backed implementation of OHLCVRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── mapping ────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_domain(row: OHLCVBarModel) -> OHLCVBar:
        return OHLCVBar(
            instrument_id=row.instrument_id,
            timeframe=Timeframe(row.timeframe),
            bar_date=row.bar_date,
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            volume=int(row.volume) if row.volume is not None else 0,
            adjusted_close=Decimal(str(row.adjusted_close)) if row.adjusted_close is not None else None,
            source=row.source or "",
            provider_priority=ProviderPriority(provider="unknown", priority=int(row.provider_priority)),
            is_derived=bool(row.is_derived),
            is_partial=bool(row.is_partial),
        )

    # ── commands ───────────────────────────────────────────────────────────────

    async def bulk_upsert_with_priority(self, bars: list[OHLCVBar]) -> None:
        """Bulk-upsert OHLCV bars with provider-priority conflict resolution.

        ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE SET ...
        WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority

        This guards against lower-priority sources overwriting higher-priority
        stored records (e.g., Yahoo overwriting Polygon data).
        """
        if not bars:
            return

        values = [
            {
                "instrument_id": bar.instrument_id,
                "timeframe": str(bar.timeframe),
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume if bar.volume is not None else 0,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "provider_priority": bar.provider_priority.priority,
                "is_partial": bar.is_partial,
            }
            for bar in bars
        ]

        stmt = (
            insert(OHLCVBarModel)
            .values(values)
            .on_conflict_do_update(
                index_elements=["instrument_id", "timeframe", "bar_date"],
                set_={
                    "open": insert(OHLCVBarModel).excluded.open,
                    "high": insert(OHLCVBarModel).excluded.high,
                    "low": insert(OHLCVBarModel).excluded.low,
                    "close": insert(OHLCVBarModel).excluded.close,
                    "volume": insert(OHLCVBarModel).excluded.volume,
                    "adjusted_close": insert(OHLCVBarModel).excluded.adjusted_close,
                    "source": insert(OHLCVBarModel).excluded.source,
                    "provider_priority": insert(OHLCVBarModel).excluded.provider_priority,
                    "is_partial": insert(OHLCVBarModel).excluded.is_partial,
                },
                where=(insert(OHLCVBarModel).excluded.provider_priority >= OHLCVBarModel.provider_priority),
            )
        )
        await self._session.execute(stmt)

    # ── queries ────────────────────────────────────────────────────────────────

    async def find_by_instrument_timeframe_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.bar_date >= start_dt,
                OHLCVBarModel.bar_date <= end_dt,
            )
            .order_by(OHLCVBarModel.bar_date.asc())
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_available_timeframes(self, instrument_id: str) -> list[Timeframe]:
        tf_result: Any = await self._session.execute(
            select(distinct(OHLCVBarModel.timeframe)).where(OHLCVBarModel.instrument_id == instrument_id)
        )
        return [Timeframe(tf) for tf in tf_result.scalars().all()]

    async def get_date_range(self, instrument_id: str, timeframe: Timeframe) -> tuple[date, date] | None:
        range_result = await self._session.execute(
            select(
                func.min(OHLCVBarModel.bar_date),
                func.max(OHLCVBarModel.bar_date),
            ).where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
            )
        )
        min_date: datetime | None
        max_date: datetime | None
        min_date, max_date = range_result.one()
        if min_date is None or max_date is None:
            return None
        return (min_date.date(), max_date.date())

    async def bulk_upsert_derived(self, bars: list[OHLCVBar]) -> None:
        """Upsert locally-derived bars unconditionally (no priority guard).

        Derived bars are always the authoritative source for their timeframe —
        no external provider will ever supply competing 1w/1M data via the
        normal ingestion path after PLAN-0036.  The ON CONFLICT clause always
        overwrites so that a fresh derivation pass replaces stale aggregates.
        """
        if not bars:
            return

        values = [
            {
                "instrument_id": bar.instrument_id,
                "timeframe": str(bar.timeframe),
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume if bar.volume is not None else 0,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "provider_priority": bar.provider_priority.priority,
                "is_derived": True,
                "is_partial": bar.is_partial,
            }
            for bar in bars
        ]

        stmt = (
            insert(OHLCVBarModel)
            .values(values)
            .on_conflict_do_update(
                index_elements=["instrument_id", "timeframe", "bar_date"],
                set_={
                    "open": insert(OHLCVBarModel).excluded.open,
                    "high": insert(OHLCVBarModel).excluded.high,
                    "low": insert(OHLCVBarModel).excluded.low,
                    "close": insert(OHLCVBarModel).excluded.close,
                    "volume": insert(OHLCVBarModel).excluded.volume,
                    "adjusted_close": insert(OHLCVBarModel).excluded.adjusted_close,
                    "source": insert(OHLCVBarModel).excluded.source,
                    "provider_priority": insert(OHLCVBarModel).excluded.provider_priority,
                    "is_derived": insert(OHLCVBarModel).excluded.is_derived,
                    "is_partial": insert(OHLCVBarModel).excluded.is_partial,
                },
            )
        )
        await self._session.execute(stmt)

    async def find_by_instrument_timeframe_datetime_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[OHLCVBar]:
        """Return bars within ``[start_dt, end_dt]`` (inclusive), ordered ascending."""
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.bar_date >= start_dt,
                OHLCVBarModel.bar_date <= end_dt,
            )
            .order_by(OHLCVBarModel.bar_date.asc())
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def find_derived(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        *,
        limit: int = 200,
    ) -> list[OHLCVBar]:
        """Return derived bars sorted by bar_date descending, capped at ``limit``."""
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.is_derived.is_(True),
            )
            .order_by(OHLCVBarModel.bar_date.desc())
            .limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars().all()]
