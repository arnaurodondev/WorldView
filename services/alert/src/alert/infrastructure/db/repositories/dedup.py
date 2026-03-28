"""Dedup repository — thin wrapper querying ``alerts.dedup_key``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alert.infrastructure.db.models import AlertModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DedupRepository:
    """Check dedup_key existence against the ``alerts`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, dedup_key: str) -> bool:
        """Return ``True`` if an alert with this dedup_key is already stored."""
        stmt = select(AlertModel.alert_id).where(AlertModel.dedup_key == dedup_key).limit(1)
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return result is not None
