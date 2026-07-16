"""PostgreSQL adapter for IngestionEventRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import IngestionEventRepository
from market_data.infrastructure.db.models.infrastructure import IngestionEventModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgIngestionEventRepository(IngestionEventRepository):
    """SQLAlchemy-backed implementation of IngestionEventRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, event_id: str) -> bool:
        result = await self._session.execute(select(exists().where(IngestionEventModel.event_id == event_id)))
        return bool(result.scalar())

    async def exists_by_content_hash(self, sha256: str, event_type: str) -> bool:
        result = await self._session.execute(
            select(
                exists().where(
                    and_(
                        IngestionEventModel.content_sha256 == sha256,
                        IngestionEventModel.event_type == event_type,
                    )
                )
            )
        )
        return bool(result.scalar())

    async def create(
        self,
        event_id: str,
        event_type: str | None = None,
        content_sha256: str | None = None,
    ) -> None:
        stmt = (
            insert(IngestionEventModel)
            .values(event_id=event_id, event_type=event_type, content_sha256=content_sha256)
            .on_conflict_do_nothing(constraint="uq_ingestion_events_event_id")
        )
        await self._session.execute(stmt)

    async def create_if_not_exists(
        self,
        event_id: str,
        event_type: str | None = None,
        content_sha256: str | None = None,
    ) -> bool:
        """Atomically insert the event; return True if new, False if duplicate."""
        stmt = (
            insert(IngestionEventModel)
            .values(event_id=event_id, event_type=event_type, content_sha256=content_sha256)
            .on_conflict_do_nothing(constraint="uq_ingestion_events_event_id")
            .returning(IngestionEventModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_many_if_not_exists(
        self,
        events: list[tuple[str, str | None, str | None]],
    ) -> set[str]:
        """Bulk-insert events; return the set of event_ids that were NEW.

        One multi-row ``INSERT … ON CONFLICT DO NOTHING … RETURNING event_id``
        so a batch consumer dedups the whole batch in a single round-trip.
        """
        if not events:
            return set()
        # De-duplicate within the batch first: a multi-row INSERT with the SAME
        # event_id twice raises "ON CONFLICT DO UPDATE command cannot affect row
        # a second time" on some paths, and DO NOTHING silently keeps only one —
        # collapse here so the RETURNING set is unambiguous.
        seen: dict[str, tuple[str, str | None, str | None]] = {}
        for event_id, event_type, sha in events:
            seen.setdefault(event_id, (event_id, event_type, sha))
        values = [{"event_id": eid, "event_type": et, "content_sha256": sha} for eid, et, sha in seen.values()]
        stmt = (
            insert(IngestionEventModel)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_ingestion_events_event_id")
            .returning(IngestionEventModel.event_id)
        )
        result = await self._session.execute(stmt)
        return {row[0] for row in result.fetchall()}
