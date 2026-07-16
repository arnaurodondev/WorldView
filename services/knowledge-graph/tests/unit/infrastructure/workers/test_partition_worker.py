"""Unit tests for partition workers 13G-H (T-D-3-11).

Covers the DEFAULT-partition hardening (residual review 2026-07-16): per-
partition transaction isolation, non-fatal DEFAULT-conflict handling, and
DEFAULT-aware retention pruning.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_session(*, execute_side_effect: object = None, execute_return: object = None) -> MagicMock:
    """Build an async-context-manager session mock for a sessionmaker call."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    if execute_side_effect is not None:
        session.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        session.execute = AsyncMock(return_value=execute_return)
    return session


def _exists_row() -> MagicMock:
    row = MagicMock()
    row.fetchone.return_value = ("something",)
    return row


def _missing_row() -> MagicMock:
    row = MagicMock()
    row.fetchone.return_value = None
    return row


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
        session.execute = AsyncMock(side_effect=[_missing_row(), MagicMock()])

        result = asyncio.run(_create_monthly_partition(session, "relation_evidence", 2026, 5))
        assert result is True
        assert session.execute.call_count == 2

    def test_partition_skipped_when_exists(self) -> None:
        """If partition already exists, no CREATE should be issued."""
        from knowledge_graph.infrastructure.workers.partitions import _create_monthly_partition

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_exists_row())

        result = asyncio.run(_create_monthly_partition(session, "relation_evidence", 2026, 5))
        assert result is False
        session.execute.assert_awaited_once()  # Only the check query


class TestIsDefaultConflict:
    def test_matches_postgres_default_conflict(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _is_default_conflict

        exc = Exception(
            "updated partition constraint for default partition "
            '"relation_evidence_default" would be violated by some row',
        )
        assert _is_default_conflict(exc) is True

    def test_matches_via_cause_chain(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _is_default_conflict

        root = Exception("would be violated by some row")
        wrapper = Exception("(sqlalchemy) statement failed")
        wrapper.__cause__ = root
        assert _is_default_conflict(wrapper) is True

    def test_ignores_unrelated_error(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _is_default_conflict

        assert _is_default_conflict(Exception("connection refused")) is False


class TestMonthlyPartitionWorkerIdempotency:
    def test_run_does_not_raise_when_all_exist(self) -> None:
        """Worker.run() completes without error even if partitions exist."""
        from knowledge_graph.infrastructure.workers.partitions import MonthlyPartitionWorker

        # Every sessionmaker call yields a fresh session whose queries report
        # "exists" (no creates) and whose prune finds nothing to delete.
        def make() -> MagicMock:
            return _make_session(execute_return=_exists_row())

        sf = MagicMock(side_effect=lambda: make())

        worker = MonthlyPartitionWorker(sf)
        asyncio.run(worker.run())  # must not raise

    def test_default_conflict_is_non_fatal(self) -> None:
        """A DEFAULT-conflict on one create must not wedge the cycle."""
        from knowledge_graph.infrastructure.workers.partitions import MonthlyPartitionWorker

        # First create attempt raises a DEFAULT conflict; subsequent sessions
        # report "exists". run() must swallow the conflict and still complete.
        calls = {"n": 0}

        def make() -> MagicMock:
            calls["n"] += 1
            if calls["n"] == 1:
                exc = Exception("default partition would be violated by some row")
                return _make_session(execute_side_effect=[_missing_row(), exc])
            return _make_session(execute_return=_exists_row())

        sf = MagicMock(side_effect=lambda: make())
        worker = MonthlyPartitionWorker(sf)
        asyncio.run(worker.run())  # must not raise despite the conflict
        # 3 offsets x 3 tables = 9 create sessions + 1 prune session = 10 calls.
        assert calls["n"] == 10

    def test_one_bad_partition_does_not_block_others(self) -> None:
        """A non-DEFAULT error on one create is isolated; others still run."""
        from knowledge_graph.infrastructure.workers.partitions import MonthlyPartitionWorker

        calls = {"n": 0}

        def make() -> MagicMock:
            calls["n"] += 1
            if calls["n"] == 2:
                exc = Exception("deadlock detected")
                return _make_session(execute_side_effect=[_missing_row(), exc])
            return _make_session(execute_return=_exists_row())

        sf = MagicMock(side_effect=lambda: make())
        worker = MonthlyPartitionWorker(sf)
        asyncio.run(worker.run())  # isolated failure must not propagate
        assert calls["n"] == 10  # every partition + prune still attempted


class TestPruneDefaultPartitionRows:
    def test_noop_when_no_default_partition(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _prune_default_partition_rows

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_missing_row())  # default absent

        deleted = asyncio.run(_prune_default_partition_rows(session, "events", 2024, 7))
        assert deleted == 0
        session.execute.assert_awaited_once()  # only the existence probe

    def test_deletes_old_rows_when_default_present(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _prune_default_partition_rows

        exists = _exists_row()
        key_col = MagicMock()
        key_col.fetchone.return_value = ("evidence_date",)
        delete_result = MagicMock()
        delete_result.rowcount = 5

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[exists, key_col, delete_result])

        deleted = asyncio.run(
            _prune_default_partition_rows(session, "relation_evidence", 2024, 7),
        )
        assert deleted == 5
        assert session.execute.call_count == 3
        # The DELETE must target the resolved key column and cutoff date.
        delete_sql = str(session.execute.call_args_list[2].args[0])
        assert "DELETE FROM relation_evidence_default" in delete_sql
        assert "evidence_date <" in delete_sql

    def test_rejects_non_identifier_key_col(self) -> None:
        from knowledge_graph.infrastructure.workers.partitions import _prune_default_partition_rows

        exists = _exists_row()
        bad_key = MagicMock()
        bad_key.fetchone.return_value = ("evidence_date; DROP TABLE x",)

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[exists, bad_key])

        deleted = asyncio.run(
            _prune_default_partition_rows(session, "relation_evidence", 2024, 7),
        )
        assert deleted == 0
        assert session.execute.call_count == 2  # no DELETE issued
