"""PathInsightSeeder — inserts pending path_insight_jobs for hub entities (T-E1-04).

A "hub entity" is any canonical entity with more than ``_HUB_MIN_RELATIONS``
outgoing relations.  The seeder is idempotent: jobs that are already pending
or running are skipped via the ``uq_path_insight_jobs_active`` partial unique
index (ON CONFLICT DO NOTHING).

Jobs for hubs that already have recent insights (computed_at < 23 hours ago)
are also skipped to avoid redundant work.

Run nightly at 02:30 UTC by the APScheduler cron job in
``KnowledgeGraphScheduler``.

D-R3-005 (PLAN-0087, 2026-05-09): the default threshold was 10, which was
sized for a fully populated production KG (hundreds of relations per top-50
entity).  The pre-demo KG has ~3 relations per subject and 8 distinct
subjects, so the seeder found 0 hubs and ``/paths`` stayed permanently empty.
Lowered default to 2; production should override via the
``PATH_INSIGHT_HUB_MIN_RELATIONS`` env var once depth grows.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Minimum outgoing relation count to qualify as a hub entity.
# D-R3-005 (2026-05-09): lowered from 10 → 2 default; env-overridable.
_HUB_MIN_RELATIONS = int(os.environ.get("PATH_INSIGHT_HUB_MIN_RELATIONS", "2"))

# Skip seeding a job if the hub already has fresh insights younger than this.
_FRESHNESS_HOURS = 23


class PathInsightSeeder:
    """Seeds path insight jobs for hub entities.

    Args:
    ----
        session_factory: Write session factory for intelligence_db.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
    ) -> None:
        self._sf = session_factory

    async def seed_hub_entities(self) -> int:
        """Insert pending jobs for hub entities not already queued or recently completed.

        Returns the number of new jobs inserted.

        Idempotent: uses ON CONFLICT DO NOTHING against the
        ``uq_path_insight_jobs_active`` partial unique index.
        """
        async with self._sf() as session:
            # Step 1: find hub entity IDs (> _HUB_MIN_RELATIONS outgoing relations)
            # that do NOT already have an active pending/running job AND do NOT
            # have fresh insights computed within the last _FRESHNESS_HOURS hours.
            hub_result = await session.execute(
                text("""
SELECT r.subject_entity_id AS entity_id
FROM relations r
GROUP BY r.subject_entity_id
HAVING COUNT(*) > :min_relations
"""),
                {"min_relations": _HUB_MIN_RELATIONS},
            )
            hub_rows = hub_result.fetchall()

        if not hub_rows:
            logger.info("path_insight_seeder_no_hubs_found")  # type: ignore[no-any-return]
            return 0

        hub_ids = [UUID(str(row[0])) for row in hub_rows]
        inserted = 0

        # Step 2: insert jobs idempotently — one batch session.
        async with self._sf() as session:
            for entity_id in hub_ids:
                # Check for recently-completed insights (skip if fresh).
                fresh_result = await session.execute(
                    text("""
SELECT 1 FROM path_insights
WHERE anchor_entity_id = CAST(:entity_id AS UUID)
  AND computed_at > NOW() - make_interval(hours => :freshness_hours)
LIMIT 1
"""),
                    {
                        "entity_id": str(entity_id),
                        "freshness_hours": _FRESHNESS_HOURS,
                    },
                )
                if fresh_result.fetchone() is not None:
                    # Hub already has fresh insights — skip.
                    continue

                # Insert pending job (idempotent via partial unique index).
                insert_result = await session.execute(
                    text("""
INSERT INTO path_insight_jobs (entity_id, status)
VALUES (CAST(:entity_id AS UUID), 'pending')
ON CONFLICT DO NOTHING
RETURNING job_id
"""),
                    {"entity_id": str(entity_id)},
                )
                if insert_result.fetchone() is not None:
                    inserted += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "path_insight_seeder_complete",
            hubs_scanned=len(hub_ids),
            jobs_inserted=inserted,
        )
        return inserted
