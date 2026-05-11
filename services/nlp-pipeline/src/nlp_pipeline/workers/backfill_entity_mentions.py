"""Backfill chunks.entity_mentions for historical chunks (PLAN-0078 Wave B).

One-shot script that queries the existing chunk_entity_mentions join table and
entity_mentions resolution table to build the denormalised JSONB payload for
every chunk that still has entity_mentions = '[]'.

Run as:
    python -m nlp_pipeline.workers.backfill_entity_mentions

Environment:
    NLP_PIPELINE_NLP_DB_URL — asyncpg connection string for nlp_db.
    NLP_PIPELINE_GLINER_MENTION_FLOOR — minimum confidence score (default 0.6).

The script processes chunks in batches of BATCH_SIZE to avoid OOM on large
datasets.  It is safe to re-run — chunks with non-empty entity_mentions are
skipped.  Progress is logged to structlog.
"""

from __future__ import annotations

import asyncio
import json
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nlp_pipeline.config import Settings
from observability import get_logger  # type: ignore[import-untyped]

_log = get_logger(__name__)  # type: ignore[no-any-return]

BATCH_SIZE = 500


async def _backfill(engine: AsyncEngine, mention_floor: float) -> None:
    """Main backfill loop."""
    async with engine.begin() as conn:
        # Total chunks needing backfill (entity_mentions is still empty array)
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM chunks WHERE entity_mentions = '[]'::jsonb"))
        total = int(result.scalar_one())
        _log.info("backfill_entity_mentions_start", total_chunks=total, mention_floor=mention_floor)

    offset = 0
    updated = 0

    while True:
        async with engine.begin() as conn:
            # Fetch a batch of chunk_ids still needing backfill
            rows = (
                await conn.execute(
                    sa.text(
                        """
                        SELECT chunk_id
                        FROM chunks
                        WHERE entity_mentions = '[]'::jsonb
                        ORDER BY chunk_id
                        LIMIT :batch_size OFFSET :offset
                        """
                    ).bindparams(batch_size=BATCH_SIZE, offset=offset)
                )
            ).fetchall()

            if not rows:
                break

            chunk_ids = [str(r.chunk_id) for r in rows]

            # Fetch resolved entity mentions for these chunks via the join table.
            # Filters on mention_floor (confidence >= floor).
            mention_rows = (
                await conn.execute(
                    sa.text(
                        """
                        SELECT
                            cem.chunk_id,
                            em.resolved_entity_id,
                            em.mention_class AS entity_type,
                            em.char_start,
                            em.char_end,
                            em.confidence AS gliner_score,
                            em.mention_text AS raw_text
                        FROM chunk_entity_mentions cem
                        JOIN entity_mentions em ON em.mention_id = cem.mention_id
                        WHERE cem.chunk_id = ANY(CAST(:chunk_ids AS UUID[]))
                          AND em.confidence >= :floor
                        """
                    ).bindparams(chunk_ids=chunk_ids, floor=mention_floor)
                )
            ).fetchall()

            # Group by chunk_id
            mention_map: dict[str, list[dict]] = {cid: [] for cid in chunk_ids}
            for row in mention_rows:
                cid = str(row.chunk_id)
                mention_map[cid].append(
                    {
                        "entity_id": str(row.resolved_entity_id) if row.resolved_entity_id else None,
                        "entity_type": row.entity_type,
                        "char_start": row.char_start,
                        "char_end": row.char_end,
                        "gliner_score": float(row.gliner_score),
                        "raw_text": row.raw_text,
                    }
                )

            # Bulk UPDATE — only chunks that have at least one mention get a
            # non-empty array; all others stay at '[]' (no-op since they were
            # already '[]').  We update ALL fetched chunks to mark them as
            # processed (avoids re-fetching in subsequent batches).
            if chunk_ids:
                for cid in chunk_ids:
                    payload = json.dumps(mention_map[cid])
                    await conn.execute(
                        sa.text(
                            "UPDATE chunks"
                            " SET entity_mentions = CAST(:payload AS JSONB)"
                            " WHERE chunk_id = CAST(:chunk_id AS UUID)"
                        ).bindparams(payload=payload, chunk_id=cid)
                    )

        updated += len(chunk_ids)
        _log.info(
            "backfill_entity_mentions_progress",
            updated=updated,
            total=total,
        )
        offset += BATCH_SIZE

    _log.info("backfill_entity_mentions_complete", updated=updated)


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_async_engine(settings.database_url.get_secret_value(), echo=False, pool_size=2, max_overflow=0)
    try:
        await _backfill(engine, settings.gliner_mention_floor)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
