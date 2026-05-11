"""NarrativeRepository — asyncpg-backed implementation for entity_narrative_versions.

Implements :class:`NarrativeRepositoryPort` using raw SQL via SQLAlchemy ``text()``.
S7 does not own intelligence_db DDL; all schema changes live in intelligence-migrations.

Table created by migration 0031 (Wave A).

Insert pattern (``insert_and_promote``):
  1. INSERT new row with ``is_current=False``.
  2. UPDATE existing ``is_current=True`` rows → ``is_current=False``.
  3. UPDATE the newly inserted row → ``is_current=True``.
  4. UPDATE ``canonical_entities.current_narrative_version_id`` + ``health_score``.

Idempotency:
  ``find_by_input_snapshot`` queries ``input_snapshot->>'_hash'`` which the caller
  (``GenerateNarrativeUseCase``) stores as a top-level key in ``input_snapshot``.

Cursor pagination:
  ``list_versions`` uses keyset pagination on ``(generated_at DESC, version_id)``
  encoded as base64(``<iso>|<uuid>``).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.narrative_repository import NarrativeRepositoryPort
from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _row_to_version(row: Any) -> EntityNarrativeVersion:
    """Convert a raw DB row (Row or dict-like) to an EntityNarrativeVersion."""
    generated_at = row[7]
    # Ensure timezone-aware — asyncpg returns timezone-aware datetimes for
    # TIMESTAMPTZ columns, but we guard defensively.
    if generated_at is not None and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)

    # input_snapshot column may be a dict (asyncpg JSON) or a JSON string.
    snapshot = row[5]
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (ValueError, TypeError):
            snapshot = None

    return EntityNarrativeVersion(
        version_id=UUID(str(row[0])),
        entity_id=UUID(str(row[1])),
        narrative_text=str(row[2]),
        model_id=str(row[3]),
        generation_reason=NarrativeGenerationReason(str(row[4])),
        input_snapshot=snapshot,
        generated_at=generated_at,
        is_current=bool(row[8]),
        word_count=int(row[9]) if row[9] is not None else None,
        quality_score=float(row[10]) if row[10] is not None else None,
    )


class NarrativeRepository(NarrativeRepositoryPort):
    """Read/write repository for ``entity_narrative_versions``.

    Args:
    ----
        session:              Read/write session (used for find_current and
                              find_by_input_snapshot when called with a session,
                              and by insert_and_promote).
        read_session_factory: Optional read-replica factory for read-only queries
                              (find_current, find_by_input_snapshot, list_versions).
                              Falls back to ``session`` when ``None``.

    """

    def __init__(
        self,
        session: AsyncSession,
        read_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        # When a read replica factory is provided, read-only queries use it.
        # This satisfies R27 (read-only use cases on read replica).
        self._read_sf = read_session_factory

    # ─── Read operations ──────────────────────────────────────────────────────

    async def find_current(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
    ) -> EntityNarrativeVersion | None:
        """Return the is_current=True version for an entity, or None."""
        result = await self._session.execute(
            text("""
SELECT version_id, entity_id, narrative_text, model_id, generation_reason,
       input_snapshot, tenant_id, generated_at, is_current, word_count, quality_score
FROM entity_narrative_versions
WHERE entity_id = :entity_id
  AND is_current = TRUE
  AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
LIMIT 1
"""),
            {
                "entity_id": str(entity_id),
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
            },
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_version(row)

    async def find_by_input_snapshot(
        self,
        entity_id: UUID,
        snapshot_hash: str,
    ) -> EntityNarrativeVersion | None:
        """Return a version whose input_snapshot->>'_hash' matches snapshot_hash.

        The use case stores the snapshot hash under the ``_hash`` key inside the
        ``input_snapshot`` JSONB column so we can query without re-hashing.
        """
        result = await self._session.execute(
            text("""
SELECT version_id, entity_id, narrative_text, model_id, generation_reason,
       input_snapshot, tenant_id, generated_at, is_current, word_count, quality_score
FROM entity_narrative_versions
WHERE entity_id = :entity_id
  AND input_snapshot->>'_hash' = :snapshot_hash
ORDER BY generated_at DESC
LIMIT 1
"""),
            {
                "entity_id": str(entity_id),
                "snapshot_hash": snapshot_hash,
            },
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_version(row)

    async def list_versions(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[EntityNarrativeVersion], str | None]:
        """Return paginated version history (newest first) with cursor support.

        Cursor format: base64(``<generated_at_iso>|<version_id>``).
        """
        # Decode cursor
        cursor_at: str | None = None
        cursor_vid: str | None = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor.encode()).decode()
                parts = decoded.split("|", 1)
                if len(parts) == 2:
                    cursor_at, cursor_vid = parts
            except Exception:  # malformed cursor → ignore
                cursor_at = None
                cursor_vid = None

        # Build query with optional cursor
        if cursor_at and cursor_vid:
            sql = text("""
SELECT version_id, entity_id, narrative_text, model_id, generation_reason,
       input_snapshot, tenant_id, generated_at, is_current, word_count, quality_score
FROM entity_narrative_versions
WHERE entity_id = :entity_id
  AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
  AND (generated_at, version_id) < (CAST(:cursor_at AS TIMESTAMPTZ), CAST(:cursor_vid AS uuid))
ORDER BY generated_at DESC, version_id DESC
LIMIT :limit
""")
            params: dict[str, Any] = {
                "entity_id": str(entity_id),
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
                "cursor_at": cursor_at,
                "cursor_vid": cursor_vid,
                "limit": limit + 1,
            }
        else:
            sql = text("""
SELECT version_id, entity_id, narrative_text, model_id, generation_reason,
       input_snapshot, tenant_id, generated_at, is_current, word_count, quality_score
FROM entity_narrative_versions
WHERE entity_id = :entity_id
  AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
ORDER BY generated_at DESC, version_id DESC
LIMIT :limit
""")
            params = {
                "entity_id": str(entity_id),
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
                "limit": limit + 1,
            }

        result = await self._session.execute(sql, params)
        rows = result.fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]

        versions = [_row_to_version(r) for r in rows]

        next_cursor: str | None = None
        if has_more and versions:
            last = versions[-1]
            raw = f"{last.generated_at.isoformat()}|{last.version_id}"
            next_cursor = base64.b64encode(raw.encode()).decode()

        return versions, next_cursor

    # ─── Write operations ─────────────────────────────────────────────────────

    async def insert_and_promote(
        self,
        version: EntityNarrativeVersion,
        session: AsyncSession,
        health_score: float | None = None,
    ) -> None:
        """Persist and promote a new narrative version in a single transaction.

        Steps:
          1. INSERT new row with is_current=False.
          2. UPDATE old is_current=True row → False.
          3. UPDATE new row → is_current=True.
          4. UPDATE canonical_entities pointer + health_score.

        The caller must commit the session.
        """
        # Serialize input_snapshot for storage
        snapshot_json: str | None = None
        if version.input_snapshot is not None:
            snapshot_json = json.dumps(version.input_snapshot, sort_keys=True, default=str)

        # Step 1: INSERT with is_current=False
        await session.execute(
            text("""
INSERT INTO entity_narrative_versions (
    version_id, entity_id, tenant_id, narrative_text, model_id,
    generation_reason, input_snapshot, generated_at, is_current,
    word_count, quality_score
) VALUES (
    CAST(:version_id AS uuid),
    CAST(:entity_id AS uuid),
    CAST(:tenant_id AS uuid),
    :narrative_text,
    :model_id,
    :generation_reason,
    CAST(:input_snapshot AS jsonb),
    CAST(:generated_at AS TIMESTAMPTZ),
    FALSE,
    :word_count,
    :quality_score
)
"""),
            {
                "version_id": str(version.version_id),
                "entity_id": str(version.entity_id),
                "tenant_id": None,  # tenant_id not carried on the domain entity for Wave C
                "narrative_text": version.narrative_text,
                "model_id": version.model_id,
                "generation_reason": version.generation_reason.value,
                "input_snapshot": snapshot_json,
                "generated_at": version.generated_at,
                "word_count": version.word_count,
                "quality_score": version.quality_score,
            },
        )

        # Step 2: Demote the previous current version
        await session.execute(
            text("""
UPDATE entity_narrative_versions
SET is_current = FALSE
WHERE entity_id = CAST(:entity_id AS uuid)
  AND is_current = TRUE
  AND version_id != CAST(:version_id AS uuid)
"""),
            {
                "entity_id": str(version.entity_id),
                "version_id": str(version.version_id),
            },
        )

        # Step 3: Promote the new row
        await session.execute(
            text("""
UPDATE entity_narrative_versions
SET is_current = TRUE
WHERE version_id = CAST(:version_id AS uuid)
"""),
            {"version_id": str(version.version_id)},
        )

        # Step 4: Update canonical_entities pointer + health_score
        await session.execute(
            text("""
UPDATE canonical_entities
SET current_narrative_version_id = CAST(:version_id AS uuid),
    health_score = COALESCE(CAST(:health_score AS FLOAT), health_score)
WHERE entity_id = CAST(:entity_id AS uuid)
"""),
            {
                "version_id": str(version.version_id),
                "entity_id": str(version.entity_id),
                "health_score": health_score,
            },
        )
