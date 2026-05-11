"""One-shot SummaryWorker trigger for operator use.

Runs the Worker 13C SummaryWorker once — useful for forcing relation_summaries
population after the relation_evidence promotion script has run.

Usage (from repo root):
    # In the container:
    docker exec worldview-knowledge-graph-scheduler-1 \
        python scripts/ops/run_summary_worker_once.py

    # Or locally (with DATABASE_URL pointing at dev Postgres):
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db \
        python scripts/ops/run_summary_worker_once.py

Environment variables read:
    DATABASE_URL              — intelligence_db async URL
    DEEPINFRA_API_KEY         — DeepInfra API key (required for LLM calls)
    DEEPINFRA_EXTRACTION_BASE_URL
    DEEPINFRA_EXTRACTION_MODEL_ID
    SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE  — optional (default 0 = hash-based skip)
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_DEFAULT_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct"


async def _count(session_factory: async_sessionmaker[AsyncSession], sql: str) -> int:
    async with session_factory() as session:
        result = await session.execute(text(sql))
        val = result.scalar()
        return int(val) if val is not None else 0


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    api_key = os.environ.get("DEEPINFRA_API_KEY", "")
    base_url = os.environ.get("DEEPINFRA_EXTRACTION_BASE_URL", _DEFAULT_DEEPINFRA_BASE_URL)
    model_id = os.environ.get("DEEPINFRA_EXTRACTION_MODEL_ID", _DEFAULT_MODEL_ID)
    force_regen = int(os.environ.get("SUMMARY_WORKER_FORCE_REGEN_BATCH_SIZE", "0"))

    print(f"run_summary_worker_once: db={db_url.split('@')[-1]}  model={model_id}")

    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    try:
        # Pre-run counts
        stale_count = await _count(session_factory, "SELECT count(*) FROM relations WHERE summary_stale = true")
        evidence_count = await _count(session_factory, "SELECT count(*) FROM relation_evidence")
        summaries_before = await _count(session_factory, "SELECT count(*) FROM relation_summaries")
        print(
            f"Before: stale_relations={stale_count}  relation_evidence={evidence_count}  summaries={summaries_before}"
        )

        if evidence_count == 0:
            print("WARNING: relation_evidence is empty — run promote_relation_evidence.py first.")
            print("SummaryWorker will fall back to raw evidence (lower quality but functional).")

        if not api_key:
            print("WARNING: DEEPINFRA_API_KEY not set — SummaryWorker LLM calls will fail.")
            print("Set DEEPINFRA_API_KEY env var or the worker will skip all summaries.")

        # Build the LLM client (mirrors scheduler_main.py setup)
        from knowledge_graph.infrastructure.llm.fallback_chain import (
            FallbackChainClient,  # type: ignore[import-untyped]
        )
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter  # type: ignore[import-not-found]

        deepinfra_ext = (
            DeepSeekExtractionAdapter(
                api_key=api_key,
                model_id=model_id,
                base_url=base_url,
            )
            if api_key
            else None
        )

        llm_client = FallbackChainClient(deepinfra_extraction=deepinfra_ext)

        worker = SummaryWorker(
            session_factory=session_factory,
            llm_client=llm_client,
            force_regen_batch_size=force_regen,
            read_session_factory=session_factory,  # no read replica in ops context
        )

        print("Running SummaryWorker...")
        await worker.run()

        # Post-run counts
        summaries_after = await _count(session_factory, "SELECT count(*) FROM relation_summaries")
        stale_after = await _count(session_factory, "SELECT count(*) FROM relations WHERE summary_stale = true")
        print(f"After:  summaries={summaries_after}  stale_remaining={stale_after}")
        print(f"Summaries created this run: {summaries_after - summaries_before}")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
