"""TriggerIngestionUseCase — immediately enqueue tasks for given symbols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType, FundamentalsVariant, Provider
from market_ingestion.domain.value_objects import DateRange, Timeframe
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass
class TriggerResult:
    """Result of a trigger operation."""

    tasks_created: int = 0
    tasks_skipped: int = 0


class TriggerIngestionUseCase:
    """Manually trigger immediate ingestion tasks for a set of symbols.

    Creates one ``IngestionTask`` per symbol.  Idempotent: duplicate
    ``dedupe_key`` values are silently ignored (ON CONFLICT DO NOTHING).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        provider: Provider,
        dataset_type: DatasetType,
        symbols: list[str],
        timeframe: str | None = None,
        exchange: str | None = None,
        variant: str | None = None,
    ) -> TriggerResult:
        """Enqueue one task per symbol.

        Args:
            provider: Data provider enum value.
            dataset_type: OHLCV, QUOTES, or FUNDAMENTALS.
            symbols: List of instrument symbols to trigger.
            timeframe: Required for OHLCV (e.g. ``"1d"``).
            exchange: Optional exchange code.
            variant: Required for FUNDAMENTALS (e.g. ``"annual"``).

        Returns:
            ``TriggerResult`` with counts of created vs skipped tasks.
        """
        # Truncate to UTC day boundaries so repeated triggers on the same day
        # produce the same dedupe_key (idempotent within a trading day).
        from datetime import timedelta

        now = utc_now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_start = today
        range_end = today + timedelta(days=1)
        date_range = DateRange(start=range_start, end=range_end)

        tasks: list[IngestionTask] = []
        for symbol in symbols:
            task = self._build_task(
                provider=provider,
                dataset_type=dataset_type,
                symbol=symbol,
                timeframe=timeframe,
                exchange=exchange,
                variant=variant,
                date_range=date_range,
            )
            tasks.append(task)

        async with self._uow:
            inserted = await self._uow.tasks.add_many(tasks)
            await self._uow.commit()

        skipped = len(tasks) - inserted
        logger.info(
            "trigger_complete",
            provider=str(provider),
            dataset_type=str(dataset_type),
            created=inserted,
            skipped=skipped,
        )
        return TriggerResult(tasks_created=inserted, tasks_skipped=skipped)

    # ------------------------------------------------------------------

    def _build_task(
        self,
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str,
        timeframe: str | None,
        exchange: str | None,
        variant: str | None,
        date_range: DateRange,
    ) -> IngestionTask:
        if dataset_type == DatasetType.OHLCV:
            tf = Timeframe(timeframe or "1d")
            return IngestionTask.create_ohlcv_task(
                provider=provider,
                symbol=symbol,
                timeframe=tf,
                date_range=date_range,
                exchange=exchange,
            )
        if dataset_type == DatasetType.QUOTES:
            return IngestionTask.create_quote_task(
                provider=provider,
                symbol=symbol,
                date_range=date_range,
                exchange=exchange,
            )
        # FUNDAMENTALS
        fv = FundamentalsVariant(variant or "annual")
        return IngestionTask.create_fundamentals_task(
            provider=provider,
            symbol=symbol,
            variant=fv,
            date_range=date_range,
            exchange=exchange,
        )
