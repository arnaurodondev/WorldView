"""Backfill BGE chunk embeddings for LIGHT-tier documents (PLAN-0111 B-3).

WHY this script exists
----------------------
Before PLAN-0111, the suppression gate only generated CHUNK embeddings for
MEDIUM/DEEP docs (FULL_PIPELINE). LIGHT docs (SECTION_EMBEDDINGS_ONLY) got
section embeddings but no chunk embeddings. Chat retrieval queries
CHUNK-granularity vectors, so ~21% of the corpus (the LIGHT tier — ~3.7k docs /
~6.8k chunks) was invisible to semantic ANN retrieval, reachable only via the
BM25/tsvector leg.

B-1 fixed the gate so future LIGHT docs get chunk embeddings. This one-shot
script backfills the *historical* LIGHT chunks that were ingested under the old
gate and therefore have NO row in ``chunk_embeddings``.

Why a dedicated script (not the embedding_retry_worker)
-------------------------------------------------------
The ``EmbeddingRetryWorker`` only drains rows that already exist in
``embedding_pending``. These historical LIGHT chunks were never *attempted*
(the gate skipped them outright), so they were never enqueued — the retry
worker would never see them. This script selects the missing chunks directly
from ``chunks`` (LEFT JOIN ``chunk_embeddings`` IS NULL, filtered to the LIGHT
tier via ``routing_decisions``), embeds their inline ``chunk_text`` with the
same BGE-large adapter the pipeline uses, and writes 1024-d vectors into the
same ``chunk_embeddings`` table / HNSW index that MEDIUM/DEEP use — so they are
searchable together.

Idempotency / safety
--------------------
- Selection always re-checks ``chunk_embeddings IS NULL``, so re-running only
  picks up what is still missing.
- The INSERT uses ``ON CONFLICT (chunk_id, model_id) DO NOTHING`` so a partial
  prior run never errors on re-run.
- Chunks whose embed call fails are simply left for the next run (logged, not
  fatal). No data is mutated except inserting embedding rows.

Run as::

    python -m nlp_pipeline.workers.backfill_light_chunk_embeddings [--limit N] [--dry-run]

Environment: the standard ``NLP_PIPELINE_*`` settings (DB URL + embedding
provider/key/model) — identical to the article consumer, so the embedding model
and vector space match exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nlp_pipeline.bootstrap.embedding import build_embedding_client
from nlp_pipeline.config import Settings
from observability import get_logger  # type: ignore[import-untyped]

_log = get_logger(__name__)  # type: ignore[no-any-return]

# Embed in modest batches: one DeepInfra round-trip per batch keeps memory flat
# and lets us checkpoint progress (each batch is committed independently, so a
# crash mid-run loses at most one batch and the rest is already durable).
_BATCH_SIZE = 64


def _select_missing_sql(*, exclude_ids: set[str] | None = None) -> sa.TextClause:
    """SQL selecting LIGHT chunks that still lack a chunk embedding.

    LIGHT tier = ``COALESCE(final_routing_tier, routing_tier) = 'light'`` on the
    doc's routing_decisions row (final tier wins when novelty corrected it).

    We pull ``chunk_text`` inline — every historical LIGHT chunk has it populated
    (verified live: 6797/6797). We order by chunk_id for stable pagination and
    cap each fetch at :batch_size so the embed call stays bounded.

    ``exclude_ids`` lets the caller drop chunk_ids that permanently failed to
    embed, so they never re-appear at the top of the (offset-free) query.
    """
    # Two fully-static SQL literals (no f-string interpolation of any kind → no
    # SQL-injection surface, no ruff S608). The only difference is the optional
    # exclude predicate, whose VALUES are passed as a bound, casted uuid[] param.
    base_select = """
        SELECT c.chunk_id, c.chunk_text
        FROM chunks c
        JOIN routing_decisions rd ON rd.doc_id = c.doc_id
        WHERE COALESCE(rd.final_routing_tier, rd.routing_tier) = 'light'
          AND c.chunk_text IS NOT NULL
          AND length(c.chunk_text) > 0
          AND NOT EXISTS (
              SELECT 1 FROM chunk_embeddings ce WHERE ce.chunk_id = c.chunk_id
          )
        """
    order_limit = """
        ORDER BY c.chunk_id
        LIMIT :batch_size
        """
    if exclude_ids:
        stmt = sa.text(base_select + "AND c.chunk_id <> ALL(CAST(:exclude_ids AS uuid[]))" + order_limit)
        return stmt.bindparams(sa.bindparam("exclude_ids", value=[str(x) for x in exclude_ids]))
    return sa.text(base_select + order_limit)


async def _embed_rows_resilient(
    client: Any,
    rows: Sequence[Any],
    model_id: str,
    prefix: str,
    skipped: set[str],
) -> list[Any]:
    """Embed a batch, degrading to per-item on a batch-level provider error.

    WHY: a single chunk the provider 400s on (e.g. a pathological text the BGE
    tokenizer rejects) must not abort the whole 6.8k-row backfill. We try the
    fast batch path first; on failure we fall back to embedding each row alone so
    only the genuine offender is dropped (added to ``skipped`` so it is excluded
    from future SELECTs). Returns a list aligned 1:1 with ``rows`` (None where an
    item was skipped).
    """
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

    inputs = [EmbeddingInput(text=str(r.chunk_text), model_id=model_id, instruction_prefix=prefix) for r in rows]  # type: ignore[attr-defined]
    try:
        return list(await client.embed(inputs))  # type: ignore[attr-defined]
    except Exception as batch_exc:
        _log.warning("backfill_light_chunk_embeddings_batch_failed_degrading", error=str(batch_exc), batch=len(rows))

    outputs: list[object] = []
    for r in rows:
        one = EmbeddingInput(text=str(r.chunk_text), model_id=model_id, instruction_prefix=prefix)  # type: ignore[attr-defined]
        try:
            res = list(await client.embed([one]))  # type: ignore[attr-defined]
            outputs.append(res[0] if res else None)
        except Exception as item_exc:
            # Permanent skip: record so this poison row is excluded next loop.
            skipped.add(str(r.chunk_id))  # type: ignore[attr-defined]
            outputs.append(None)
            _log.warning(
                "backfill_light_chunk_embeddings_item_skipped",
                chunk_id=str(r.chunk_id),  # type: ignore[attr-defined]
                error=str(item_exc),
            )
    return outputs


async def _count_missing(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        row = await conn.execute(
            sa.text(
                """
                SELECT count(*)
                FROM chunks c
                JOIN routing_decisions rd ON rd.doc_id = c.doc_id
                WHERE COALESCE(rd.final_routing_tier, rd.routing_tier) = 'light'
                  AND c.chunk_text IS NOT NULL
                  AND length(c.chunk_text) > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM chunk_embeddings ce WHERE ce.chunk_id = c.chunk_id
                  )
                """
            )
        )
        return int(row.scalar_one())


async def _backfill(settings: Settings, *, limit: int | None, dry_run: bool) -> int:
    """Embed missing LIGHT chunks until none remain (or ``limit`` reached).

    Returns the number of embeddings written.
    """

    # Same model_id the article consumer writes for API-provider embeddings, so
    # backfilled rows are indistinguishable from freshly-ingested LIGHT chunks
    # and share the HNSW index (which is model-agnostic — it filters only on
    # embedding_status='ready').
    model_id = settings.embedding_api_model_id
    prefix = settings.embedding_instruction_prefix

    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    client = build_embedding_client(settings)

    total_missing = await _count_missing(engine)
    _log.info(
        "backfill_light_chunk_embeddings_start",
        total_missing=total_missing,
        model_id=model_id,
        batch_size=_BATCH_SIZE,
        limit=limit,
        dry_run=dry_run,
    )

    written = 0
    # chunk_ids that permanently fail to embed (e.g. a text the provider 400s on).
    # We hold them in memory and exclude them from the SELECT so a poison row never
    # re-blocks the run at the same offset (the SELECT is offset-free — it always
    # re-queries "still missing", so without this set a failing row loops forever).
    skipped: set[str] = set()
    try:
        while True:
            if limit is not None and written >= limit:
                break

            async with engine.connect() as conn:
                rows = (
                    await conn.execute(_select_missing_sql(exclude_ids=skipped).bindparams(batch_size=_BATCH_SIZE))
                ).all()

            if not rows:
                break  # nothing left to embed

            if dry_run:
                # Dry run: report what we would do without spending tokens.
                _log.info("backfill_light_chunk_embeddings_dry_run_batch", batch=len(rows))
                # Avoid an infinite loop on dry-run (we never insert): stop after
                # reporting the first batch.
                break

            outputs = await _embed_rows_resilient(client, rows, model_id, prefix, skipped)

            # Map embeddings back to their chunk_id positionally (embed preserves
            # input order). Defensive: only write rows whose vector came back.
            to_insert: list[dict[str, object]] = []
            for r, out in zip(rows, outputs, strict=False):
                vec = getattr(out, "embedding", None)
                if not vec:
                    continue
                to_insert.append(
                    {
                        "chunk_id": r.chunk_id,
                        # pgvector over asyncpg has no native list binder in a raw
                        # text() INSERT, so we serialise to the pgvector literal
                        # "[f1,f2,...]" and CAST(... AS vector) in SQL below.
                        "embedding": "[" + ",".join(repr(float(x)) for x in vec) + "]",
                        "model_id": model_id,
                    }
                )

            if to_insert:
                async with engine.begin() as conn:
                    # ON CONFLICT keeps the run idempotent: a re-run (or a racing
                    # live ingest of the same chunk) never errors on the unique
                    # (chunk_id, model_id) constraint.
                    await conn.execute(
                        sa.text(
                            """
                            INSERT INTO chunk_embeddings (chunk_id, embedding, model_id)
                            VALUES (:chunk_id, CAST(:embedding AS vector), :model_id)
                            ON CONFLICT (chunk_id, model_id) DO NOTHING
                            """
                        ),
                        to_insert,
                    )
                written += len(to_insert)

            _log.info(
                "backfill_light_chunk_embeddings_progress",
                written=written,
                last_batch=len(to_insert),
            )

            if len(rows) < _BATCH_SIZE:
                break  # drained the final partial batch
    finally:
        await engine.dispose()

    _log.info("backfill_light_chunk_embeddings_done", written=written)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill BGE chunk embeddings for LIGHT-tier docs.")
    parser.add_argument("--limit", type=int, default=None, help="Max embeddings to write (default: all).")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without embedding/inserting.")
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    written = asyncio.run(_backfill(settings, limit=args.limit, dry_run=args.dry_run))
    _log.info("backfill_light_chunk_embeddings_exit", written=written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
