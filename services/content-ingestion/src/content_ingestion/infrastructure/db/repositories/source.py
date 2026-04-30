"""Repository for sources table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import select

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import SourceModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[SourceModel]:
        result = await self._session.execute(select(SourceModel))
        return list(result.scalars().all())

    async def list_enabled(self) -> list[SourceModel]:
        """Return all sources where ``enabled=True``."""
        result = await self._session.execute(select(SourceModel).where(SourceModel.enabled.is_(True)))
        return list(result.scalars().all())

    async def get_by_id(self, source_id: UUID) -> SourceModel | None:
        result = await self._session.execute(select(SourceModel).where(SourceModel.id == source_id))
        return cast("SourceModel | None", result.scalar_one_or_none())

    async def create(
        self,
        name: str,
        source_type: str,
        config: dict,
        enabled: bool = True,
    ) -> tuple[SourceModel, bool]:
        """Idempotent INSERT (PLAN-0055 B-1).

        Returns ``(source, was_created)``. When a row with the same
        ``(source_type, config_hash)`` already exists (UNIQUE ``uq_sources_dedup``),
        we return the existing row with ``was_created=False`` instead of raising.
        Operators who delete + recreate a source with identical config keep the
        original UUID and watermark history.

        Why ON CONFLICT DO UPDATE rather than DO NOTHING: ``DO NOTHING`` does not
        return rows on conflict, so we'd need a follow-up SELECT — splitting the
        operation into two statements (BP-007 violation). ``DO UPDATE SET enabled=...``
        is a no-op when enabled is unchanged, but always populates RETURNING so the
        whole flow stays in a single round-trip.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        new_id = common.ids.new_uuid7()
        stmt = (
            pg_insert(SourceModel)
            .values(
                id=new_id,
                name=name,
                source_type=source_type,
                config=config,
                enabled=enabled,
            )
            .on_conflict_do_update(
                constraint="uq_sources_dedup",
                set_={"enabled": enabled},
            )
            .returning(SourceModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one()
        await self._session.flush()
        was_created = row.id == new_id
        return row, was_created

    _MUTABLE_FIELDS: frozenset[str] = frozenset({"name", "enabled", "config"})

    async def update(self, source_id: UUID, **kwargs: Any) -> SourceModel:
        row = await self.get_by_id(source_id)
        if row is None:
            raise ValueError(f"Source {source_id} not found")
        for key, value in kwargs.items():
            if key not in self._MUTABLE_FIELDS:
                msg = f"Field '{key}' is not mutable"
                raise ValueError(msg)
            setattr(row, key, value)
        await self._session.flush()
        return row
