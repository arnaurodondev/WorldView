#!/usr/bin/env python3
"""PLAN-0109 W2 — trigger one ConfidenceWorker cycle (evidence pass + staleness sweep).

Run inside the knowledge-graph container to backfill/recompute on demand instead
of waiting for the 15-minute schedule:

    docker exec worldview-knowledge-graph-scheduler-1 \
        python /app/trigger_confidence_worker.py
"""

from __future__ import annotations

import asyncio
import os

from knowledge_graph.config import Settings
from knowledge_graph.infrastructure.workers.confidence import ConfidenceWorker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_async_engine(os.environ["KNOWLEDGE_GRAPH_DATABASE_URL"])
    sf = async_sessionmaker(engine, expire_on_commit=False)
    worker = ConfidenceWorker(sf, settings)
    # Run several cycles to drain the backlog (each sweep pass is capped per partition).
    for i in range(6):
        await worker.run()
        print(f"cycle {i + 1} done")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
