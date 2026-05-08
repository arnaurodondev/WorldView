"""Dedup hash repository — Stage A/B hash existence checks and insertions.

Uses ``INSERT ... ON CONFLICT DO NOTHING`` for idempotent inserts (BP-040).
Duplicate hash inserts (e.g. Kafka consumer re-delivery) are silently ignored
rather than raising ``UniqueViolationError``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import common.ids  # type: ignore[import-untyped]
from content_store.application.ports.repositories import DedupHashRepositoryPort
from content_store.infrastructure.db.models import DedupHashModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DedupHashRepository(DedupHashRepositoryPort):
    """PostgreSQL dedup hash repository for Stage A and Stage B lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_exists(self, hash_type: str, hash_value: str, tenant_id: UUID | None = None) -> UUID | None:
        """Check if a hash exists for the given scope. Returns the associated doc_id or None.

        ``tenant_id=None`` looks up in the global (public news) hash space.
        Pass a tenant UUID to scope the lookup to that tenant's private content.
        SQLAlchemy ``== None`` compiles to ``IS NULL``, which is correct here.
        """
        result = await self._session.execute(
            select(DedupHashModel.doc_id).where(
                DedupHashModel.hash_type == hash_type,
                DedupHashModel.hash_value == hash_value,
                DedupHashModel.tenant_id == tenant_id,  # IS NULL or = <uuid>
            )
        )
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def insert(self, doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID | None = None) -> None:
        """Insert a dedup hash record (raw_sha256 or normalized_sha256).

        ``tenant_id=None`` inserts into the global (public) hash space.
        Uses ``ON CONFLICT DO NOTHING`` on the relevant partial index so
        duplicate inserts (e.g. Kafka re-delivery) are silently ignored
        instead of raising ``UniqueViolationError`` (BP-040).

        Note: partial-index ON CONFLICT uses index name (index_where),
        not a named constraint.
        """
        # Choose the correct partial index target based on tenant scope.
        # PostgreSQL requires the ON CONFLICT target to match the partial index predicate.
        if tenant_id is None:
            stmt = (
                pg_insert(DedupHashModel)
                .values(
                    hash_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    hash_type=hash_type,
                    hash_value=hash_value,
                    tenant_id=None,
                )
                .on_conflict_do_nothing(
                    index_elements=["hash_type", "hash_value"],
                    index_where=DedupHashModel.tenant_id.is_(None),
                )
            )
        else:
            stmt = (
                pg_insert(DedupHashModel)
                .values(
                    hash_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    hash_type=hash_type,
                    hash_value=hash_value,
                    tenant_id=tenant_id,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "hash_type", "hash_value"],
                    index_where=DedupHashModel.tenant_id.isnot(None),
                )
            )
        await self._session.execute(stmt)

    async def insert_pair(
        self,
        doc_id: UUID,
        raw_hash: str,
        normalized_hash: str,
        tenant_id: UUID | None = None,
    ) -> None:
        """Insert both Stage A (raw) and Stage B (normalized) hashes in one call.

        Each insert is individually idempotent via ``ON CONFLICT DO NOTHING``.
        ``tenant_id`` is forwarded to both inserts so both hashes land in the
        correct scope (global or tenant-private).
        """
        await self.insert(doc_id, "raw_sha256", raw_hash, tenant_id=tenant_id)
        await self.insert(doc_id, "normalized_sha256", normalized_hash, tenant_id=tenant_id)
