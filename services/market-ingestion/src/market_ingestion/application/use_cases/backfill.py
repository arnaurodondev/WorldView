"""BackfillUseCase — create chunked OHLCV backfill tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.value_objects import DateRange, Timeframe
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.domain.enums import Provider

logger = get_logger(__name__)

_MAX_CHUNKS: int = 100


@dataclass
class BackfillResult:
    """Result of a backfill operation."""

    tasks_created: int = 0
    tasks_skipped: int = 0
    chunks: int = 0


class BackfillUseCase:
    """Create chunked OHLCV backfill tasks for a historical date range.

    The date range is split into *chunk_days*-day windows.  Raises
    ``ValueError`` if the range would produce more than 100 chunks.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        provider: Provider,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str,
        chunk_days: int = 30,
        exchange: str | None = None,
    ) -> BackfillResult:
        """Create one task per date-range chunk.

        Args:
            provider: Data provider.
            symbol: Instrument symbol.
            start_date: Inclusive start of the backfill range (UTC-aware).
            end_date: Exclusive end of the backfill range (UTC-aware).
            timeframe: Bar timeframe (e.g. ``"1d"``).
            chunk_days: Size of each chunk in days.
            exchange: Optional exchange code.

        Returns:
            ``BackfillResult`` with chunk count and task creation counts.

        Raises:
            ValueError: If the range would require more than 100 chunks.
        """
        chunks = self._split_chunks(start_date, end_date, chunk_days)

        if len(chunks) > _MAX_CHUNKS:
            raise ValueError(
                f"Backfill range requires {len(chunks)} chunks which exceeds the "
                f"maximum of {_MAX_CHUNKS}. Reduce the date range or increase chunk_days."
            )

        tf = Timeframe(timeframe)
        tasks: list[IngestionTask] = []
        for chunk_start, chunk_end in chunks:
            date_range = DateRange(start=chunk_start, end=chunk_end)
            task = IngestionTask.create_ohlcv_task(
                provider=provider,
                symbol=symbol,
                timeframe=tf,
                date_range=date_range,
                exchange=exchange,
            )
            tasks.append(task)

        async with self._uow:
            inserted = await self._uow.tasks.add_many(tasks)
            await self._uow.commit()

        skipped = len(tasks) - inserted
        logger.info(
            "backfill_enqueued",
            provider=str(provider),
            symbol=symbol,
            chunks=len(chunks),
            created=inserted,
            skipped=skipped,
        )
        return BackfillResult(
            tasks_created=inserted,
            tasks_skipped=skipped,
            chunks=len(chunks),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _split_chunks(
        start: datetime,
        end: datetime,
        chunk_days: int,
    ) -> list[tuple[datetime, datetime]]:
        """Split [start, end) into non-overlapping chunks of *chunk_days* days."""
        chunks: list[tuple[datetime, datetime]] = []
        current = start
        delta = timedelta(days=chunk_days)
        while current < end:
            chunk_end = min(current + delta, end)
            chunks.append((current, chunk_end))
            current = chunk_end
        return chunks
