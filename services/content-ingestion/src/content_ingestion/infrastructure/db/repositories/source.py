"""Repository for sources table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

import common.ids
import common.time
from content_ingestion.infrastructure.db.models import SourceModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[SourceModel]:
        result = await self._session.execute(select(SourceModel))
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
    ) -> SourceModel:
        row = SourceModel(
            id=common.ids.new_uuid7(),
            name=name,
            source_type=source_type,
            config=config,
            enabled=enabled,
        )
        self._session.add(row)
        await self._session.flush()
        return row

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
