"""Backfill narrative-view embeddings for entities with current narrative but no embedding.

SA-3 remediation script (2026-05-10).

Context
-------
60 entities have an is_current narrative version but no narrative embedding.
Root cause: the NarrativeRefreshWorker (60-min interval, first tick at 60min
after container start) has not yet fired for these rows since the last scheduler
restart. The ``entity_embedding_state`` rows exist with ``embedding IS NULL`` and
``next_refresh_at`` set to a future time (or already past due in some cases).

Additionally:
- 1103 narrative embeddings exist but only 1101 canonical entities (and 1161
  have current narrative versions). The 1103 > 1101 discrepancy is benign:
  2 entities have a narrative embedding but no current is_current narrative
  (likely deleted/superseded versions that still have their embedding rows).

Strategy:
  Phase 1 — reset ``next_refresh_at = now()`` for narrative rows with no embedding.
  Phase 2 — invoke NarrativeRefreshWorker.run() immediately.

Usage
-----
    # Dry-run
    python scripts/ops/backfill_narrative_embeddings.py --dry-run

    # Execute
    python scripts/ops/backfill_narrative_embeddings.py

    # Mark only (let scheduler pick up)
    python scripts/ops/backfill_narrative_embeddings.py --mark-only

Environment
-----------
    DATABASE_URL:                       optional async DSN override
    DEEPINFRA_API_KEY:                  DeepInfra key for embedding calls
    KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID: defaults to BAAI/bge-large-en-v1.5
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_DEFAULT_EMBED_MODEL = "BAAI/bge-large-en-v1.5"
_DEFAULT_DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai"


async def main(dry_run: bool, mark_only: bool) -> None:
    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    api_key = os.environ.get("DEEPINFRA_API_KEY", "")
    embed_model = os.environ.get("KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID", _DEFAULT_EMBED_MODEL)
    deepinfra_url = os.environ.get("DEEPINFRA_EXTRACTION_BASE_URL", _DEFAULT_DEEPINFRA_URL)

    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    try:
        from sqlalchemy import text

        # Count missing narrative embeddings (for entities that have current narratives)
        async with session_factory() as session:
            result = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state ees
JOIN canonical_entities ce ON ce.entity_id = ees.entity_id
WHERE ees.view_type = 'narrative'
  AND ees.embedding IS NULL
  AND EXISTS (
    SELECT 1 FROM entity_narrative_versions nv
    WHERE nv.entity_id = ees.entity_id AND nv.is_current = true
  )
"""),
            )
            missing_with_current_narr = result.scalar() or 0

            result2 = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'narrative' AND embedding IS NULL
"""),
            )
            total_missing_narr = result2.scalar() or 0

            result3 = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'narrative' AND embedding IS NULL
  AND (next_refresh_at IS NULL OR next_refresh_at > now())
"""),
            )
            future_count = result3.scalar() or 0

        print(f"Narrative embeddings missing (total):              {total_missing_narr}")
        print(f"  With current narrative version (actionable):     {missing_with_current_narr}")
        print(f"  Scheduled for future (will reset to now):        {future_count}")

        if dry_run:
            print("[dry-run] Would mark future rows as due now and invoke NarrativeRefreshWorker.")
            return

        # Phase 1: reset next_refresh_at for all narrative rows with no embedding
        async with session_factory() as session:
            result = await session.execute(
                text("""
UPDATE entity_embedding_state
SET    next_refresh_at = now()
WHERE  view_type = 'narrative'
  AND  embedding IS NULL
  AND  (next_refresh_at IS NULL OR next_refresh_at > now())
"""),
            )
            await session.commit()
            updated = result.rowcount
        print(f"Marked {updated} narrative rows as due (next_refresh_at = now()).")

        if mark_only:
            print("--mark-only set: skipping worker invocation. Scheduler will pick up on next 60-min tick.")
            return

        # Phase 2: run NarrativeRefreshWorker immediately
        if not api_key:
            print("WARNING: DEEPINFRA_API_KEY not set — embedding calls will use Ollama fallback or fail.")

        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        deepinfra_embed = None
        if api_key:
            from ml_clients.adapters.deepinfra_embedding import (
                DeepInfraEmbeddingAdapter,  # type: ignore[import-untyped]
            )

            deepinfra_embed = DeepInfraEmbeddingAdapter(
                api_key=api_key,
                model_id=embed_model,
                base_url=deepinfra_url,
            )

        llm_client = FallbackChainClient(deepinfra_embedding=deepinfra_embed)

        worker = NarrativeRefreshWorker(
            session_factory,
            llm_client,
            embedding_model_id=embed_model,
            batch_limit=0,  # process all due rows
            read_session_factory=session_factory,
        )

        print(f"Running NarrativeRefreshWorker (model={embed_model})...")
        await worker.run()
        print("NarrativeRefreshWorker complete.")

        # Verify
        async with session_factory() as session:
            result = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'narrative' AND embedding IS NULL
"""),
            )
            remaining = result.scalar() or 0
        print(f"Remaining missing narrative embeddings: {remaining}")
        if remaining == 0:
            print("SUCCESS: all narrative embeddings populated.")
        else:
            print(f"NOTE: {remaining} rows still missing — these are entities with no current narrative version.")
            print("      They will be populated after NarrativeGenerationWorker generates narratives.")

    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Preview only — no DB changes")
    p.add_argument(
        "--mark-only",
        action="store_true",
        help="Only reset next_refresh_at; skip running the worker",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run, mark_only=args.mark_only))
