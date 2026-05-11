"""SeedSourceWatermarksUseCase — initialize cursors at first deploy.

PLAN-0055 A-3: when ``settings.backfill_on_startup`` is True the lifespan spawns
this as a non-blocking task. For every enabled source whose adapter state has a
``NULL`` ``last_watermark``, we seed it to ``now - INITIAL_DAYS`` (clamped by
``YEARS * 365``). The regular scheduler tick then fetches backwards from that
cursor on its own — this use case never enqueues fetch tasks itself.

Idempotent: any source that already has a non-NULL watermark is skipped, so
re-running on container restarts is safe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import common.time  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.application.ports.unit_of_work import UnitOfWork
    from content_ingestion.config import Settings

logger = get_logger(__name__)


@dataclass(frozen=True)
class SeedWatermarkSummary:
    """Outcome of one seeding pass — emitted as structured log fields."""

    seeded: int = 0
    skipped: int = 0
    failed: int = 0


class SeedSourceWatermarksUseCase:
    """Seed NULL watermarks to ``now - INITIAL_DAYS`` for every enabled source.

    Best-effort: per-source failures are logged and the loop continues — never
    raises out so the lifespan can keep starting other components.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    async def execute(self) -> SeedWatermarkSummary:
        if not self._settings.backfill_on_startup:
            return SeedWatermarkSummary()

        # Clamp INITIAL_DAYS to the YEARS hard cap; same shape as S3 to keep ops mental
        # model consistent across services.
        max_days = self._settings.backfill_years * 365
        horizon_days = min(self._settings.backfill_initial_days, max_days)
        target_watermark = common.time.utc_now() - timedelta(days=horizon_days)

        # List enabled sources in a fresh UoW; per-source seeding gets its own
        # transaction (BP-007 — small txns, no cross-source poisoning).
        list_uow = self._uow_factory()
        async with list_uow:
            sources = await list_uow.sources.list_enabled()

        seeded = 0
        skipped = 0
        failed = 0
        for source in sources:
            try:
                if await self._seed_one(source.id, target_watermark):
                    seeded += 1
                else:
                    skipped += 1
            except Exception as exc:  # — best-effort, isolate per source
                failed += 1
                logger.warning(
                    "seed_watermark_failed",
                    source_id=str(source.id),
                    name=getattr(source, "name", None),
                    error=str(exc),
                )

        summary = SeedWatermarkSummary(seeded=seeded, skipped=skipped, failed=failed)
        logger.info(
            "startup_watermarks_seeded",
            seeded=summary.seeded,
            skipped=summary.skipped,
            failed=summary.failed,
            horizon_days=horizon_days,
        )
        return summary

    async def _seed_one(self, source_id, target_watermark: datetime) -> bool:  # type: ignore[no-untyped-def]
        """Return True iff we actually seeded a NULL watermark."""
        uow = self._uow_factory()
        async with uow:
            state = await uow.adapter_state.get(source_id)
            if state is not None and state.last_watermark is not None:
                # Idempotency: never overwrite an existing cursor (would lose progress).
                return False
            await uow.adapter_state.upsert(source_id, last_watermark=target_watermark)
            await uow.commit()
            return True
