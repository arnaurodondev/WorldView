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

from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
    EntityEmbeddingStateRepository,
    get_view_types_for_entity_type,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Page size for the gap-detection query.  At ~250 canonicals there's a single
# round-trip; at 10K canonicals we paginate into 20 chunks so we don't load the
# whole catalogue into memory at once.
_PAGE_SIZE = 500


# Single round-trip query that returns ONLY canonicals with fewer view rows
# than expected.  PLAN-0057 QA M-2 fix: replaces the previous NxM pattern
# (per-canonical SELECT COUNT(*)) with one GROUP BY so startup time grows
# O(canonicals) instead of O(canonicals x round-trip-latency).  The HAVING
# clause embeds the same per-type expected count as
# ``get_view_types_for_entity_type``: 3 rows for ``financial_instrument``,
# 2 rows for everything else.
_GAP_QUERY = """
SELECT ce.entity_id, ce.entity_type
FROM canonical_entities ce
LEFT JOIN entity_embedding_state ees ON ees.entity_id = ce.entity_id
GROUP BY ce.entity_id, ce.entity_type
HAVING COUNT(ees.view_type) < CASE
    WHEN ce.entity_type = 'financial_instrument' THEN 3
    ELSE 2
END
ORDER BY ce.entity_id
"""


async def repair_missing_embedding_state(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Ensure every canonical has the correct number of ``entity_embedding_state`` rows.

    Args:
        session_factory: write-capable async sessionmaker for ``intelligence_db``.

    Returns:
        Dict with ``checked`` (canonicals with gaps detected) and ``inserted``
        (rows added).  Canonicals already at the expected row count are
        invisible to this counter — the GROUP BY query filters them out
        before the loop.

    Notes:
        ``entity_id`` is UUIDv4 (``gen_random_uuid()``) so it's not
        time-ordered; the lexicographic sort gives a *stable* cursor for
        keyset pagination but newly-inserted canonicals during the scan
        may be missed in this pass.  That's acceptable because the
        ``InstrumentDiscoveredConsumer`` and ``CanonicalEntityRepository``
        live-write paths also call ``ensure_rows_exist``; this repair is
        a safety-net for seeds and migrations, not a continuous worker.

    """
    checked = 0
    inserted = 0
    page_offset = 0  # Used only for the "page < _PAGE_SIZE → done" exit.

    while True:
        async with session_factory() as session:
            # We re-run the gap query each page because INSERTs from earlier
            # pages mean the gap set shrinks over time — re-querying is
            # cheaper than tracking a cursor manually since most pages will
            # be near-empty after the first run.
            result = await session.execute(text(_GAP_QUERY + " LIMIT :limit OFFSET :offset"), {
                "limit": _PAGE_SIZE,
                "offset": page_offset,
            })
            rows = result.fetchall()
            if not rows:
                break

            repo = EntityEmbeddingStateRepository(session)
            for row in rows:
                entity_id = row[0]
                entity_type = row[1]
                expected = len(get_view_types_for_entity_type(entity_type))

                await repo.ensure_rows_exist(entity_id, entity_type)
                # ensure_rows_exist uses ON CONFLICT DO NOTHING so we can't
                # know exactly how many INSERTs landed without a RETURNING
                # clause; count the worst case (every view row missing).
                # This over-reports when only some view rows were missing
                # — acceptable because the metric purpose is "did we do
                # work this startup" not "exact rows added".
                inserted += expected
                checked += 1

            await session.commit()

        if len(rows) < _PAGE_SIZE:
            break
        page_offset += _PAGE_SIZE

    logger.info(
        "kg_embedding_state_repair_complete",
        canonicals_checked=checked,
        rows_inserted=inserted,
    )
    return {"checked": checked, "inserted": inserted}
