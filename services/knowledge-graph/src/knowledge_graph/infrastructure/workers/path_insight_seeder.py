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

PLAN-0112 W1 (T-1-02, 2026-06-12): the demo-era default of 2 over-qualified
hubs once the KG grew, so the seeder enqueued far more anchors than the slow
discovery engine could drain.  Default raised 2 → 5 (still env-overridable
via ``PATH_INSIGHT_HUB_MIN_RELATIONS``).  This is advisory belt-and-suspenders;
W2's fast engine is the real volume fix.

PLAN-0112 W1 (T-1-01 / BP-690, 2026-06-12): the seeder previously skipped only
anchors with a *fresh* ``path_insights`` row.  An anchor whose discovery job
times out forever (``failed`` at ``retry_count >= max_retries``) never produces
a ``path_insights`` row, so it was re-enqueued every night — flooding Postgres
with statement-timeout cancellations.  A ``NOT EXISTS`` guard now excludes any
anchor with a terminally-``failed`` job, and each skip increments
``path_jobs_requeued_skipped_total`` (T-1-03, FR-1 proof).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.infrastructure.metrics.prometheus import (
    path_jobs_requeued_skipped_total,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Minimum outgoing relation count to qualify as a hub entity.
# D-R3-005 (2026-05-09): lowered from 10 → 2 default; env-overridable.
# PLAN-0112 T-1-02 (2026-06-12): raised 2 → 5 (production value); env-overridable.
_HUB_MIN_RELATIONS = int(os.environ.get("PATH_INSIGHT_HUB_MIN_RELATIONS", "5"))

# Maximum outgoing relation count for a hub to REMAIN eligible (data-coverage
# fix 2026-07-16).  On the live graph ~11 mega-hubs (subject-degree >60, e.g.
# NVIDIA/Apple/Oracle) explode the untyped 2-3 hop AGE VLE past the 25 s
# statement timeout, so their discovery jobs always fail (BP-690) and produce no
# ``path_insights`` — while starving the queue.  Capping the upper degree keeps
# the 254 tractable moderate hubs (degree 5-60) flowing.  ``0`` disables the cap
# (restores the historical unbounded behaviour).  Env: PATH_INSIGHT_HUB_MAX_RELATIONS.
_HUB_MAX_RELATIONS = int(os.environ.get("PATH_INSIGHT_HUB_MAX_RELATIONS", "60"))

# Skip seeding a job if the hub already has fresh insights younger than this.
_FRESHNESS_HOURS = 23

# PLAN-0112 T-1-01 (BP-690): an anchor with a ``failed`` job at this many (or
# more) retries is terminally failed — the discovery engine has given up on it,
# so re-enqueuing only floods Postgres.  Mirrors the worker's max-retry ceiling.
_MAX_RETRIES = 3


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
            #
            # BP-SA1-002: path_insight_jobs.entity_id has a FK constraint to
            # canonical_entities.  relations.subject_entity_id may reference
            # entities that were never promoted to canonical_entities (provisional
            # enrichment, deleted entities, etc.), causing IntegrityError on INSERT.
            # Filter to only canonical entities to prevent FK violations.
            #
            # BP-690 (PLAN-0112 T-1-01): also exclude anchors with a terminally
            # ``failed`` discovery job (``retry_count >= :max_retries``).  Such
            # jobs never complete (the slow engine always times out), produce no
            # ``path_insights`` row, and so slipped past the freshness guard and
            # were re-enqueued nightly forever, flooding Postgres.  Two queries
            # are issued (qualifying hubs, then terminally-failed-excluded hubs)
            # so we can emit the skip count for the FR-1 metric/log.
            qualifying_result = await session.execute(
                text("""
SELECT r.subject_entity_id AS entity_id
FROM relations r
WHERE EXISTS (
    SELECT 1 FROM canonical_entities ce
    WHERE ce.entity_id = r.subject_entity_id
)
GROUP BY r.subject_entity_id
HAVING COUNT(*) > :min_relations
   AND (:max_relations = 0 OR COUNT(*) <= :max_relations)
"""),
                {"min_relations": _HUB_MIN_RELATIONS, "max_relations": _HUB_MAX_RELATIONS},
            )
            qualifying_ids = {UUID(str(row[0])) for row in qualifying_result.fetchall()}

            hub_result = await session.execute(
                text("""
SELECT r.subject_entity_id AS entity_id
FROM relations r
WHERE EXISTS (
    SELECT 1 FROM canonical_entities ce
    WHERE ce.entity_id = r.subject_entity_id
)
AND NOT EXISTS (
    SELECT 1 FROM path_insight_jobs j
    WHERE j.entity_id = r.subject_entity_id
      AND j.status = 'failed'
      AND j.retry_count >= :max_retries
)
GROUP BY r.subject_entity_id
HAVING COUNT(*) > :min_relations
   AND (:max_relations = 0 OR COUNT(*) <= :max_relations)
"""),
                {
                    "min_relations": _HUB_MIN_RELATIONS,
                    "max_relations": _HUB_MAX_RELATIONS,
                    "max_retries": _MAX_RETRIES,
                },
            )
            hub_rows = hub_result.fetchall()

        hub_ids = [UUID(str(row[0])) for row in hub_rows]

        # BP-690: count anchors that qualified by relation-count but were skipped
        # because they are terminally failed.  Emitted as a metric + structlog so
        # the "flood is gone" guarantee (FR-1, NFR-3) is observable.
        skipped_terminally_failed = len(qualifying_ids - set(hub_ids))
        if skipped_terminally_failed:
            path_jobs_requeued_skipped_total.inc(skipped_terminally_failed)
            logger.info(  # type: ignore[no-any-return]
                "path_insight_seeder_skipped_terminally_failed",
                skipped=skipped_terminally_failed,
            )

        if not hub_rows:
            logger.info("path_insight_seeder_no_hubs_found")  # type: ignore[no-any-return]
            return 0

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
