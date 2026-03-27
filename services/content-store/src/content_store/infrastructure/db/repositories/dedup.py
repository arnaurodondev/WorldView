"""Dedup hash repository — Stage A/B hash existence checks and insertions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_store.application.ports.repositories import DedupHashRepositoryPort
from content_store.infrastructure.db.models import DedupHashModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class DedupHashRepository(DedupHashRepositoryPort):
    """PostgreSQL dedup hash repository for Stage A and Stage B lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_exists(self, hash_type: str, hash_value: str) -> UUID | None:
        """Check if a hash exists. Returns the associated doc_id or None."""
        result = await self._session.execute(
            select(DedupHashModel.doc_id).where(
                DedupHashModel.hash_type == hash_type,
                DedupHashModel.hash_value == hash_value,
            )
        )
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def insert(self, doc_id: UUID, hash_type: str, hash_value: str) -> None:
        """Insert a dedup hash record (raw_sha256 or normalized_sha256)."""
        self._session.add(
            DedupHashModel(
                hash_id=common.ids.new_uuid7(),
                doc_id=doc_id,
                hash_type=hash_type,
                hash_value=hash_value,
            )
        )

    async def insert_pair(self, doc_id: UUID, raw_hash: str, normalized_hash: str) -> None:
        """Insert both Stage A (raw) and Stage B (normalized) hashes in one call."""
        await self.insert(doc_id, "raw_sha256", raw_hash)
        await self.insert(doc_id, "normalized_sha256", normalized_hash)
