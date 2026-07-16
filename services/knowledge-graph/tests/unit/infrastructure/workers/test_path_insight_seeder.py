"""Unit tests for PathInsightSeeder (T-E1-04)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def _make_seeder(
    hub_ids: list | None = None,
    fresh_ids: set | None = None,
    already_queued_ids: set | None = None,
    terminally_failed_ids: set | None = None,
) -> object:
    """Build a PathInsightSeeder backed by mocked session executions.

    Args:
    ----
        hub_ids: Entity IDs that qualify as hubs by relation count.  These are
            returned by BOTH hub queries unless the entity is terminally failed
            (in which case only the *qualifying* query returns it — the second,
            NOT-EXISTS-guarded query excludes it, mirroring T-1-01).
        fresh_ids: Entity IDs that already have fresh insights (skip).
        already_queued_ids: Entity IDs that already have pending/running jobs (ON CONFLICT).
        terminally_failed_ids: Entity IDs with a terminally-``failed`` job
            (retry_count >= max) — excluded from enqueue by the NOT EXISTS guard
            (BP-690, T-1-01).
    """
    from knowledge_graph.infrastructure.workers.path_insight_seeder import PathInsightSeeder

    hub_ids = hub_ids or []
    fresh_ids = fresh_ids or set()
    already_queued_ids = already_queued_ids or set()
    terminally_failed_ids = terminally_failed_ids or set()

    # The NOT-EXISTS-guarded hub query excludes terminally-failed anchors.
    enqueueable_hub_ids = [eid for eid in hub_ids if eid not in terminally_failed_ids]

    call_count = [0]

    async def _execute(sql: object, params: dict | None = None, **kwargs: object) -> MagicMock:
        result = MagicMock()
        sql_str = str(sql).lower()
        call_count[0] += 1

        if "group by" in sql_str and "having count" in sql_str:
            # Two hub queries are issued: the first (qualifying, no NOT EXISTS)
            # returns every relation-qualified hub; the second (NOT EXISTS guard
            # on terminally-failed jobs) drops terminally-failed anchors.
            if "not exists" in sql_str and "path_insight_jobs" in sql_str:
                result.fetchall.return_value = [(str(eid),) for eid in enqueueable_hub_ids]
            else:
                result.fetchall.return_value = [(str(eid),) for eid in hub_ids]
        elif "computed_at" in sql_str or "freshness" in sql_str or "path_insights" in sql_str:
            # Freshness check
            entity_id = params.get("entity_id", "") if params else ""
            from uuid import UUID

            try:
                eid = UUID(str(entity_id))
            except (ValueError, AttributeError):
                eid = None
            result.fetchone.return_value = (1,) if eid in (fresh_ids or set()) else None
        elif "on conflict" in sql_str and "path_insight_jobs" in sql_str:
            # Insert pending job
            entity_id = params.get("entity_id", "") if params else ""
            from uuid import UUID

            try:
                eid = UUID(str(entity_id))
            except (ValueError, AttributeError):
                eid = None
            if eid in (already_queued_ids or set()):
                result.fetchone.return_value = None  # conflict
            else:
                result.fetchone.return_value = (str(uuid4()),)  # inserted
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []

        return result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)

    return PathInsightSeeder(factory)


class TestPathInsightSeeder:
    def test_seeder_picks_hub_entities_by_count(self) -> None:
        """Seeder inserts jobs for hub entities returned by the relations query."""
        hub_id = uuid4()
        seeder = _make_seeder(hub_ids=[hub_id])
        count = asyncio.run(seeder.seed_hub_entities())
        # Hub should get a job inserted
        assert count == 1

    def test_seeder_no_hubs_inserts_nothing(self) -> None:
        """When no hubs exist, seeder inserts 0 jobs."""
        seeder = _make_seeder(hub_ids=[])
        count = asyncio.run(seeder.seed_hub_entities())
        assert count == 0

    def test_seeder_idempotent_rerun_no_duplicate_jobs(self) -> None:
        """Seeder skips hubs that already have active pending/running jobs."""
        hub_id = uuid4()
        # Hub already has a pending/running job (ON CONFLICT fires → returns None)
        seeder = _make_seeder(hub_ids=[hub_id], already_queued_ids={hub_id})
        count = asyncio.run(seeder.seed_hub_entities())
        # No new rows — conflict skipped insertion
        assert count == 0

    def test_seeder_skips_freshly_completed_hubs(self) -> None:
        """Seeder skips hubs that already have fresh insights within 23h."""
        hub_id = uuid4()
        # Hub has fresh insights
        seeder = _make_seeder(hub_ids=[hub_id], fresh_ids={hub_id})
        count = asyncio.run(seeder.seed_hub_entities())
        assert count == 0

    def test_seeder_multiple_hubs(self) -> None:
        """Seeder inserts one job per qualifying hub."""
        hub_ids = [uuid4(), uuid4(), uuid4()]
        seeder = _make_seeder(hub_ids=hub_ids)
        count = asyncio.run(seeder.seed_hub_entities())
        assert count == 3

    def test_seeder_mixed_fresh_and_stale_hubs(self) -> None:
        """Seeder only inserts jobs for stale hubs, skipping fresh ones."""
        fresh_id = uuid4()
        stale_id = uuid4()
        seeder = _make_seeder(hub_ids=[fresh_id, stale_id], fresh_ids={fresh_id})
        count = asyncio.run(seeder.seed_hub_entities())
        # Only stale_id gets a job
        assert count == 1

    # ── PLAN-0112 W1 (T-1-01 / BP-690) — skip terminally-failed anchors ────────

    def test_seeder_skips_terminally_failed(self) -> None:
        """An anchor with a failed job at retry_count >= max is NOT enqueued (BP-690)."""
        failed_id = uuid4()
        seeder = _make_seeder(hub_ids=[failed_id], terminally_failed_ids={failed_id})
        count = asyncio.run(seeder.seed_hub_entities())
        # Terminally-failed anchor excluded by the NOT EXISTS guard → no job.
        assert count == 0

    def test_seeder_still_enqueues_fresh_failure(self) -> None:
        """An anchor with a failed job at retry_count < max IS still enqueued.

        Such a job is NOT terminally failed (the worker will retry it), so the
        NOT EXISTS guard (status='failed' AND retry_count >= max) does not match
        it — the seeder still enqueues.  Modelled here by leaving the anchor out
        of ``terminally_failed_ids``.
        """
        retrying_id = uuid4()
        seeder = _make_seeder(hub_ids=[retrying_id], terminally_failed_ids=set())
        count = asyncio.run(seeder.seed_hub_entities())
        assert count == 1

    def test_seeder_still_skips_fresh_insights(self) -> None:
        """The existing freshness guard remains intact after the NOT EXISTS change."""
        fresh_id = uuid4()
        seeder = _make_seeder(hub_ids=[fresh_id], fresh_ids={fresh_id})
        count = asyncio.run(seeder.seed_hub_entities())
        assert count == 0

    def test_seeder_metric_increments_on_skip(self) -> None:
        """``path_jobs_requeued_skipped_total`` counts skipped terminally-failed anchors (T-1-03)."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            path_jobs_requeued_skipped_total,
        )

        failed_id = uuid4()
        stale_id = uuid4()

        before = path_jobs_requeued_skipped_total._value.get()
        seeder = _make_seeder(
            hub_ids=[failed_id, stale_id],
            terminally_failed_ids={failed_id},
        )
        count = asyncio.run(seeder.seed_hub_entities())
        after = path_jobs_requeued_skipped_total._value.get()

        # Only the non-failed hub got a job; the failed one is counted as skipped.
        assert count == 1
        assert after - before == 1

    def test_hub_min_relations_default_is_5(self) -> None:
        """T-1-02: the demo-era default of 2 was raised to a production value of 5."""
        from knowledge_graph.infrastructure.workers import path_insight_seeder

        assert path_insight_seeder._HUB_MIN_RELATIONS == 5

    def test_hub_max_relations_default_is_60(self) -> None:
        """Data-coverage fix 2026-07-16: an UPPER degree cap excludes the ~11
        mega-hubs (subject-degree >60) whose untyped 2-3 hop AGE VLE blows the
        25 s statement timeout — those jobs always failed and produced no
        path_insights.  ``0`` disables the cap."""
        from knowledge_graph.infrastructure.workers import path_insight_seeder

        assert path_insight_seeder._HUB_MAX_RELATIONS == 60
