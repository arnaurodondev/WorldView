"""Backfill definition-view embeddings for entities missing them.

SA-3 remediation script (2026-05-10).

Context
-------
61 financial_instrument entities (and 0 of other types) are missing definition
embeddings. Root cause: these entities were provisioned with
``entity_embedding_state`` rows but the DefinitionRefreshWorker (60-min interval)
has not yet fired since container startup. Additionally, 6 of the 61 have
short descriptions (< 120 chars) seeded from a recent batch insert, while 55
have no description at all (provisioned after the last worker cycle).

Strategy:
  Phase 1 — reset ``next_refresh_at = now()`` for all missing-embedding rows so
             the next worker cycle picks them up immediately.
  Phase 2 — immediately invoke DefinitionRefreshWorker.run() to process all due
             rows right now (no waiting for the 60-min tick).

For financial_instrument entities with no description (55/61): DefinitionRefreshWorker
calls _resolve_non_company_text which generates a description via EntityDescriptionClient
(Gemini/DeepInfra) or falls back to the deterministic template
"<canonical_name> is a financial_instrument." — this fallback always succeeds, so
every entity WILL get an embedding even if the LLM description call fails.

Usage
-----
    # Dry-run: see what would be reset
    python scripts/ops/backfill_definition_embeddings.py --dry-run

    # Execute backfill (marks rows + runs worker once)
    python scripts/ops/backfill_definition_embeddings.py

    # Mark only — don't run worker (let scheduler pick up)
    python scripts/ops/backfill_definition_embeddings.py --mark-only

Environment
-----------
    DATABASE_URL:              optional async DSN override
    DEEPINFRA_API_KEY:         DeepInfra key for embedding calls (required for prod)
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


async def _mark_due(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Set next_refresh_at = now() for all definition rows with no embedding.

    Returns the number of rows updated.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
UPDATE entity_embedding_state
SET    next_refresh_at = now()
WHERE  view_type = 'definition'
  AND  embedding IS NULL
  AND  (next_refresh_at IS NULL OR next_refresh_at > now())
"""),
        )
        await session.commit()
        # SQLAlchemy returns rowcount on UPDATE via result.rowcount
        return result.rowcount


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

        # Count what's missing before we do anything
        async with session_factory() as session:
            result = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'definition' AND embedding IS NULL
"""),
            )
            missing_count = result.scalar() or 0

            result2 = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'definition' AND embedding IS NULL
  AND (next_refresh_at IS NULL OR next_refresh_at > now())
"""),
            )
            future_count = result2.scalar() or 0

            result3 = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'definition' AND embedding IS NULL AND next_refresh_at <= now()
"""),
            )
            overdue_count = result3.scalar() or 0

        print(f"Definition embeddings missing:    {missing_count}")
        print(f"  Already overdue (due now):       {overdue_count}")
        print(f"  Scheduled for future (will mark): {future_count}")

        if dry_run:
            print("[dry-run] Would mark future rows as due now and invoke DefinitionRefreshWorker.")
            return

        # Phase 1: mark all missing-embedding rows as due now
        updated = await _mark_due(session_factory)
        print(f"Marked {updated} rows as due (next_refresh_at = now()).")

        if mark_only:
            print("--mark-only set: skipping worker invocation. Scheduler will pick up on next 60-min tick.")
            return

        # Phase 2: run DefinitionRefreshWorker immediately
        if not api_key:
            print("WARNING: DEEPINFRA_API_KEY not set — embedding calls will use Ollama fallback or fail.")
            print("         Set DEEPINFRA_API_KEY for production-quality embeddings.")

        from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        # Build the embedding adapter — DeepInfra when key present, Ollama fallback otherwise
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

        worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client=None,  # NullDescriptionAdapter → deterministic fallback template
            embedding_model_id=embed_model,
            batch_limit=0,  # process all due rows
            read_session_factory=session_factory,
        )

        print(f"Running DefinitionRefreshWorker (model={embed_model})...")
        await worker.run()
        print("DefinitionRefreshWorker complete.")

        # Verify final state
        async with session_factory() as session:
            result = await session.execute(
                text("""
SELECT count(*) FROM entity_embedding_state
WHERE view_type = 'definition' AND embedding IS NULL
"""),
            )
            remaining = result.scalar() or 0
        print(f"Remaining missing definition embeddings: {remaining}")
        if remaining == 0:
            print("SUCCESS: all definition embeddings populated.")
        else:
            print(f"WARNING: {remaining} still missing — likely transient embed failures. Re-run to retry.")

    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Preview only — no DB changes")
    p.add_argument(
        "--mark-only",
        action="store_true",
        help="Only reset next_refresh_at; skip running the worker (scheduler will pick up)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run, mark_only=args.mark_only))
