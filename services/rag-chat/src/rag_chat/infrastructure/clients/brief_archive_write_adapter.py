"""BriefArchiveWriteAdapter — session-factory-backed WRITE adapter for use cases.

D-R4-004 (PLAN-0087, 2026-05-09): GenerateBriefingUseCase used to wire to
``NullBriefArchive`` because there was no write-side adapter that fitted the
"factory + per-call session" pattern; ``BriefArchiveRepository`` requires
caller-managed sessions which the existing wiring path could not supply.
This adapter mirrors the read-side ``BriefArchiveReadAdapter`` shape so the
use case can be wired with a single ``write_factory`` reference at boot time.

Each ``save`` opens its own session, runs the INSERT via the production
``BriefArchiveRepository``, commits, and closes — the use case layer no
longer needs to know about sessions for the brief-archive write path.

R8 (outbox) is NOT applicable here — brief archival is a single-table
write of a fully-derived row; no Kafka emission, no dual-write surface.

R26: this adapter calls ``session.commit()`` itself because there is no
encompassing UoW context (the call is fire-and-forget from the use case's
``asyncio.shield`` block).  The repository it delegates to does not commit;
this adapter owns the transaction boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from rag_chat.application.ports.brief_archive import UserBriefRecord

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefArchiveWriteAdapter:
    """BriefArchivePort-compatible WRITE adapter backed by a write session factory.

    Implements ``save`` (the write path used by GenerateBriefingUseCase).
    Read methods delegate to no-op semantics — production reads come through
    ``BriefArchiveReadAdapter`` (a different adapter).  The use case currently
    only invokes ``save`` from this adapter; if it ever needs reads, route
    them through the read adapter instead.
    """

    def __init__(self, write_factory: Callable[[], AsyncSession]) -> None:
        # WHY store factory (not a single session): the use case writes from
        # ``asyncio.shield`` blocks that may overlap. Each call must open its
        # own session for proper isolation.
        self._write_factory = write_factory

    async def save(self, brief: UserBriefRecord) -> None:
        """Persist a freshly generated brief.

        Errors are caught and logged — never raised — because the use case
        wraps this call in ``asyncio.shield`` and treats archival as a
        background concern.  A failed save must not propagate back to the
        caller of GenerateBriefingUseCase (the user gets their brief; the
        archive miss is just a missed history row).
        """
        from rag_chat.infrastructure.db.repositories.brief_archive_repository import BriefArchiveRepository

        try:
            async with self._write_factory() as session:
                repo = BriefArchiveRepository(session)
                await repo.save(brief)
                await session.commit()
            log.debug(  # type: ignore[no-any-return]
                "brief_archive_write_adapter_save_ok",
                brief_id=str(brief.id),
                user_id=str(brief.user_id),
                brief_type=brief.brief_type,
            )
        except Exception:  # — fire-and-forget; never propagate
            log.warning(  # type: ignore[no-any-return]
                "brief_archive_write_adapter_save_failed",
                brief_id=str(brief.id),
                user_id=str(brief.user_id),
                exc_info=True,
            )

    async def get_latest(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        limit: int = 2,
    ) -> list[UserBriefRecord]:
        # No-op: read path goes through BriefArchiveReadAdapter.
        log.warning(
            "brief_archive_write_adapter_get_latest_called",
            reason="read path should use BriefArchiveReadAdapter",
        )
        return []

    async def get_history(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        page: int,
        page_size: int,
    ) -> tuple[list[UserBriefRecord], int]:
        log.warning(
            "brief_archive_write_adapter_get_history_called",
            reason="read path should use BriefArchiveReadAdapter",
        )
        return [], 0

    async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None:
        # Read path goes through BriefArchiveReadAdapter; this no-op exists
        # only to satisfy the BriefArchivePort Protocol's full member set.
        log.warning(
            "brief_archive_write_adapter_get_by_id_called",
            reason="read path should use BriefArchiveReadAdapter",
        )
        return None

    async def get_latest_entity_brief(
        self,
        entity_id: UUID,
        limit: int = 1,
    ) -> list[UserBriefRecord]:
        """Read the latest entity-scoped brief for the freshness/idempotency check.

        WHY implemented here (not a no-op like the other reads): the entity-brief
        producers (on-demand route + pre-gen worker) wire this WRITE adapter, not
        the read adapter. They MUST be able to ask "is there already a fresh
        entity brief for this instrument?" before paying for an LLM call. Reusing
        the write factory's session keeps the producer path single-adapter; the
        query itself is read-only (no commit).

        Returns [] on any error (R9 safe degradation) so a transient DB blip
        degrades to "no fresh brief → regenerate" rather than crashing the
        producer.
        """
        from rag_chat.infrastructure.db.repositories.brief_archive_repository import BriefArchiveRepository

        try:
            async with self._write_factory() as session:
                repo = BriefArchiveRepository(session)
                return await repo.get_latest_entity_brief(entity_id=entity_id, limit=limit)
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "brief_archive_write_adapter_get_latest_entity_brief_failed",
                entity_id=str(entity_id),
                error=str(exc),
            )
            return []
