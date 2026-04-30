"""Startup repair task for ``entity_embedding_state`` (PLAN-0057 Wave E-5 / F-MAJOR-06).

Why this exists
---------------
Several historical canonicals (and any seeds added before E-5 shipped) ended up in
``canonical_entities`` without the matching ``entity_embedding_state`` rows.  Without
those rows the definition / narrative / fundamentals refresh workers never pick them
up and their embeddings stay ``NULL`` — silently degrading ANN search.

The audit (2026-04-29 §F-MAJOR-06) measured ~43 missing rows out of 206; A-3
adds 224 more canonicals so the gap can grow further if a seed migration races
with the consumer that normally calls ``ensure_rows_exist``.

What it does
------------
* Scans every ``canonical_entity`` and asks ``EntityEmbeddingStateRepository``
  to ``ensure_rows_exist`` for it.
* The repo uses ``INSERT ... ON CONFLICT DO NOTHING``, so re-runs are no-ops.
* Reports a count of canonicals checked + rows inserted via structlog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
    get_view_types_for_entity_type,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Entities are scanned in pages so a large catalogue doesn't materialise the
# entire table in one round-trip.  500 fits comfortably in memory and keeps the
# session small enough that other writers aren't blocked.
_PAGE_SIZE = 500


async def repair_missing_embedding_state(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Ensure every canonical has the correct number of ``entity_embedding_state`` rows.

    Args:
        session_factory: write-capable async sessionmaker for ``intelligence_db``.

    Returns:
        Dict with ``checked`` (canonicals scanned) and ``inserted`` (rows added).

    """
    checked = 0
    inserted = 0
    last_id: str | None = None

    while True:
        async with session_factory() as session:
            # Keyset pagination on entity_id keeps the scan stable even when new
            # canonicals are inserted concurrently (we'd just see them on the
            # next run thanks to ON CONFLICT DO NOTHING).
            params: dict[str, object] = {"limit": _PAGE_SIZE}
            cursor_clause = ""
            if last_id is not None:
                cursor_clause = "WHERE entity_id > :last_id"
                params["last_id"] = last_id

            result = await session.execute(
                text(
                    f"""
SELECT entity_id, entity_type
FROM canonical_entities
{cursor_clause}
ORDER BY entity_id
LIMIT :limit
"""
                ),
                params,
            )
            rows = result.fetchall()
            if not rows:
                break

            repo = EntityEmbeddingStateRepository(session)
            for row in rows:
                entity_id = row[0]
                entity_type = row[1]

                # Count current rows; if already correct, skip the insert calls.
                expected = len(get_view_types_for_entity_type(entity_type))
                current = await repo.count_for_entity(entity_id)
                if current >= expected:
                    checked += 1
                    last_id = str(entity_id)
                    continue

                await repo.ensure_rows_exist(entity_id, entity_type)
                # ensure_rows_exist may have inserted up to (expected - current) rows;
                # we conservatively count the gap.
                inserted += expected - current
                checked += 1
                last_id = str(entity_id)

            await session.commit()

        if len(rows) < _PAGE_SIZE:
            break

    logger.info(
        "kg_embedding_state_repair_complete",
        canonicals_checked=checked,
        rows_inserted=inserted,
    )
    return {"checked": checked, "inserted": inserted}
