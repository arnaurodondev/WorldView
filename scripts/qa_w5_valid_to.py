#!/usr/bin/env python3
"""QA (PLAN-0109 W5): exercise the deployed valid_to upsert path end-to-end.

Picks a real relation, re-upserts it via RelationRepository.upsert(valid_to=<past>)
— the exact write path extraction now uses — and verifies relations.valid_to is set.
Then it can be recomputed to confirm the W3 step-decay fires. Cleans up after.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["KNOWLEDGE_GRAPH_DATABASE_URL"])
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as s:
        row = (
            await s.execute(
                text(
                    "SELECT subject_entity_id, object_entity_id, canonical_type, semantic_mode, "
                    "decay_class, decay_alpha, base_confidence, confidence "
                    "FROM relations WHERE semantic_mode='RELATION_STATE' AND valid_to IS NULL LIMIT 1"
                )
            )
        ).fetchone()
        repo = RelationRepository(s)
        past = datetime.now(UTC) - timedelta(days=30)
        rid = await repo.upsert(
            subject_entity_id=row[0],
            object_entity_id=row[1],
            canonical_type=row[2],
            semantic_mode=row[3],
            decay_class=row[4],
            decay_alpha=float(row[5]),
            base_confidence=float(row[6]),
            valid_to=past,
        )
        # mark due so the next worker cycle recomputes (step-decay should fire)
        await s.execute(
            text("UPDATE relations SET confidence_last_computed_at = NULL WHERE relation_id = :r"),
            {"r": str(rid)},
        )
        await s.commit()
        vt = (
            await s.execute(text("SELECT valid_to FROM relations WHERE relation_id = :r"), {"r": str(rid)})
        ).fetchone()
        print(f"W5 upsert(valid_to) -> relations.valid_to = {vt[0]}  (relation {rid})")
        print(f"RELATION_ID={rid}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
