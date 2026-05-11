"""Unit tests for partition workers 13G-H (T-D-3-11)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


class TestAddMonths:
    def test_simple_increment(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _add_months

        assert _add_months(2026, 1, 1) == (2026, 2)

    def test_year_rollover(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _add_months

        assert _add_months(2026, 12, 1) == (2027, 1)

    def test_negative_delta(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _add_months

        assert _add_months(2026, 1, -1) == (2025, 12)

    def test_multi_year_rollover(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _add_months

        assert _add_months(2026, 1, 12) == (2027, 1)


class TestCreateMonthlyPartition:
    def test_partition_created_when_not_exists(self) -> None:
        """If partition doesn't exist, CREATE TABLE should be executed."""
        from knowledge_graph.infrastructure.workers.partitions import _create_monthly_partition

        session = AsyncMock()
        # First execute: pg_class check → no row (not exists)
        not_found = MagicMock()
        not_found.fetchone.return_value = None
        # Second execute: CREATE TABLE
        created = MagicMock()
        session.execute = AsyncMock(side_effect=[not_found, created])

        result = asyncio.run(_create_monthly_partition(session, "relation_evidence", 2026, 5))
        assert result is True
        assert session.execute.call_count == 2

    def test_partition_skipped_when_exists(self) -> None:
        """If partition already exists, no CREATE should be issued."""
        from knowledge_graph.infrastructure.workers.partitions import _create_monthly_partition

        session = AsyncMock()
        found = MagicMock()
        found.fetchone.return_value = ("relation_evidence_2026_05",)
        session.execute = AsyncMock(return_value=found)

        result = asyncio.run(_create_monthly_partition(session, "relation_evidence", 2026, 5))
        assert result is False
        session.execute.assert_awaited_once()  # Only the check query


class TestMonthlyPartitionWorkerIdempotency:
    def test_run_does_not_raise(self) -> None:
        """Worker.run() completes without error even if partitions exist."""
        from knowledge_graph.infrastructure.workers.partitions import MonthlyPartitionWorker

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        # All partition checks return "exists"
        found = MagicMock()
        found.fetchone.return_value = ("partition",)
        session.execute = AsyncMock(return_value=found)

        sf = MagicMock()
        sf.return_value = session

        worker = MonthlyPartitionWorker(sf)
        asyncio.run(worker.run())
        session.commit.assert_awaited()
