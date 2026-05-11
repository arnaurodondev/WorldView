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
) -> object:
    """Build a PathInsightSeeder backed by mocked session executions.

    Args:
    ----
        hub_ids: Entity IDs returned by the hub query.
        fresh_ids: Entity IDs that already have fresh insights (skip).
        already_queued_ids: Entity IDs that already have pending/running jobs (ON CONFLICT).
    """
    from knowledge_graph.infrastructure.workers.path_insight_seeder import PathInsightSeeder

    hub_ids = hub_ids or []
    fresh_ids = fresh_ids or set()
    already_queued_ids = already_queued_ids or set()

    call_count = [0]

    async def _execute(sql: object, params: dict | None = None, **kwargs: object) -> MagicMock:
        result = MagicMock()
        sql_str = str(sql).lower()
        call_count[0] += 1

        if "group by" in sql_str and "having count" in sql_str:
            # Hub query
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
