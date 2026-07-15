"""Unit tests for NodeDegreeRepository.refresh_from_age (PLAN-0112 T-3-02).

Live-QA fix: degrees are now computed by a FAST pure-SQL aggregation over the
raw AGE storage tables (``_ag_label_edge`` + ``entity``), NOT the slow Cypher
``-[r]-`` enumeration (which timed out at 50 s).  The aggregation SQL returns
per-vertex ``(entity_id, degree, degree_meaningful)`` directly, and a separate
stats query returns ``(total_edges, total_meaningful_edges)``.

These tests mock the AsyncSession to drive that SQL contract: they assert the
membership labels are excluded from the *meaningful* count via the AGE catalogue
(``ag_catalog.ag_label``) rather than by naming per-label child tables, that the
search_path is set (so the ``graphid`` operator resolves), and that the upserts
encode the right degree / meaningful / stats values.

Regression (fresh-graph fail-open noise): AGE materialises a label's child table
lazily on the first edge of that label, so a small graph has no
``worldview_graph."HEADQUARTERED_IN"`` table yet.  The membership exclusion must
therefore NOT reference any per-label child table (which would raise
``relation ... does not exist`` until the graph grows) — it filters on the
parent ``_ag_label_edge`` + ``ag_label`` catalogue instead.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
    NodeDegreeRepository,
)

pytestmark = pytest.mark.unit

_A = "01900000-0000-7000-8000-0000000000a1"
_B = "01900000-0000-7000-8000-0000000000b2"
_C = "01900000-0000-7000-8000-0000000000c3"


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None, one: tuple[Any, ...] | None = None) -> None:
        self._rows = rows or []
        self._one = one

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._one


def _make_session(
    *,
    degree_rows: list[tuple[str, int, int]],
    stat_row: tuple[int, int],
) -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Mock session: first SELECT -> degree aggregation, second SELECT -> stats.

    Returns (session, captured) where ``captured`` collects (sql, params) of
    every executed statement so the test can inspect the upserts + search_path.
    """
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(getattr(stmt, "text", stmt))
        captured.append((sql, params or {}))
        # Identify the two read queries by their distinctive SQL.
        if "GROUP BY vx.entity_id" in sql:
            return _FakeResult(rows=degree_rows)
        if "total_meaningful_edges" in sql:
            return _FakeResult(one=stat_row)
        return _FakeResult()

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session, captured


@pytest.mark.asyncio
async def test_uses_raw_table_sql_not_cypher() -> None:
    """The degree query must hit the raw AGE storage tables, never Cypher -[r]-."""
    session, captured = _make_session(degree_rows=[(_A, 2, 1)], stat_row=(2, 1))
    repo = NodeDegreeRepository(session)
    await repo.refresh_from_age()
    deg_sql = next(sql for sql, _ in captured if "GROUP BY vx.entity_id" in sql)
    assert "_ag_label_edge" in deg_sql, "must aggregate over the raw edge table"
    assert "cypher(" not in deg_sql.lower(), "must NOT use AGE Cypher (the slow -[r]- path)"
    assert "MATCH (a:entity)" not in deg_sql


@pytest.mark.asyncio
async def test_sets_ag_catalog_search_path() -> None:
    """search_path must include ag_catalog so the graphid operator resolves."""
    session, captured = _make_session(degree_rows=[(_A, 1, 1)], stat_row=(1, 1))
    repo = NodeDegreeRepository(session)
    await repo.refresh_from_age()
    assert any("search_path" in sql and "ag_catalog" in sql for sql, _ in captured)


@pytest.mark.asyncio
async def test_membership_labels_excluded_from_meaningful() -> None:
    """Every MEMBERSHIP_RELATIONS label appears (as a string literal) in the SQL."""
    session, captured = _make_session(degree_rows=[(_A, 3, 1)], stat_row=(3, 1))
    repo = NodeDegreeRepository(session)
    await repo.refresh_from_age()
    deg_sql = next(sql for sql, _ in captured if "GROUP BY vx.entity_id" in sql)
    for label in MEMBERSHIP_RELATIONS:
        # Excluded by matching the label NAME in ag_label (a string literal),
        # NOT by naming its child table.
        assert f"'{label}'" in deg_sql, f"membership label {label} must be excluded in the SQL"
    # Membership is resolved via the AGE catalogue, not per-label tables.
    assert "ag_catalog.ag_label" in deg_sql
    assert "e.tableoid" in deg_sql
    # is_meaningful flag drives the FILTERed count.
    assert "FILTER (WHERE ep.is_meaningful)" in deg_sql


@pytest.mark.asyncio
async def test_no_per_label_child_table_referenced() -> None:
    """Regression: the SQL must NEVER name a per-label child table.

    AGE creates ``worldview_graph."<LABEL>"`` only after the first edge of that
    label exists, so on a fresh/small graph a membership label such as
    ``HEADQUARTERED_IN`` has no table yet.  The old exclusion did
    ``SELECT id FROM worldview_graph."HEADQUARTERED_IN"`` and raised
    ``relation "worldview_graph.HEADQUARTERED_IN" does not exist`` every cycle.
    Both the degree query and the stats query must reference only the parent
    ``_ag_label_edge`` table + the catalogue — never a quoted per-label table.
    """
    session, captured = _make_session(degree_rows=[(_A, 3, 1)], stat_row=(3, 1))
    repo = NodeDegreeRepository(session)
    # Must not raise regardless of which label tables exist (the SQL never
    # depends on their existence).
    await repo.refresh_from_age()

    read_sqls = [sql for sql, _ in captured if "_ag_label_edge" in sql]
    assert read_sqls, "expected the degree + stats queries to hit _ag_label_edge"
    for sql in read_sqls:
        for label in MEMBERSHIP_RELATIONS:
            # A per-label child-table reference would look like  ."HEADQUARTERED_IN"
            assert f'"{label}"' not in sql, (
                f"per-label child table {label!r} must not be referenced "
                "(it may not be materialised yet on a fresh graph)"
            )


@pytest.mark.asyncio
async def test_degree_and_meaningful_upserted() -> None:
    """Per-vertex degree + meaningful are written to node_degree from the SQL rows."""
    session, captured = _make_session(
        degree_rows=[(_A, 5, 3), (_B, 2, 2), (_C, 1, 0)],
        stat_row=(8, 5),
    )
    repo = NodeDegreeRepository(session)
    stats = await repo.refresh_from_age()

    # max_degree derived from the per-vertex rows (no extra scan).
    assert stats.max_degree == 5
    assert stats.total_edges == 8
    assert stats.total_meaningful_edges == 5

    upsert = next(p for sql, p in captured if "INSERT INTO node_degree" in sql)
    rows = {upsert[f"eid_{i}"]: (upsert[f"deg_{i}"], upsert[f"mdeg_{i}"]) for i in range(3)}
    assert rows[_A] == (5, 3)
    assert rows[_B] == (2, 2)
    assert rows[_C] == (1, 0)


@pytest.mark.asyncio
async def test_non_uuid_vertices_skipped_in_upsert() -> None:
    """Seed/test vertices with non-UUID ids (e.g. 'e-test1') are not upserted."""
    session, captured = _make_session(
        degree_rows=[(_A, 2, 2), ("e-test1", 9, 9)],
        stat_row=(2, 2),
    )
    repo = NodeDegreeRepository(session)
    await repo.refresh_from_age()
    upsert = next(p for sql, p in captured if "INSERT INTO node_degree" in sql)
    eids = {v for k, v in upsert.items() if k.startswith("eid_")}
    assert _A in eids
    assert "e-test1" not in eids


@pytest.mark.asyncio
async def test_graph_stats_single_row_upsert() -> None:
    """graph_stats is upserted as the single id=1 row with the stat counts."""
    session, captured = _make_session(degree_rows=[(_A, 4, 2)], stat_row=(9979, 5260))
    repo = NodeDegreeRepository(session)
    await repo.refresh_from_age()
    stats_sql, stats_params = next((sql, p) for sql, p in captured if "INSERT INTO graph_stats" in sql)
    assert "ON CONFLICT (id)" in stats_sql
    assert stats_params["te"] == 9979
    assert stats_params["tme"] == 5260


@pytest.mark.asyncio
async def test_empty_graph_yields_zero_stats() -> None:
    """An empty AGE graph produces zeroed stats and no node_degree upsert."""
    session, captured = _make_session(degree_rows=[], stat_row=(0, 0))
    repo = NodeDegreeRepository(session)
    stats = await repo.refresh_from_age()
    assert stats.total_edges == 0
    assert stats.max_degree == 0
    assert not any("INSERT INTO node_degree" in sql for sql, _ in captured)


@pytest.mark.asyncio
async def test_get_degree_map_parses_rows() -> None:
    """get_degree_map returns {entity_id: (degree, meaningful)}."""
    session = MagicMock()

    async def _execute(stmt: Any, params: Any = None) -> Any:
        return _FakeResult(rows=[(_A, 5, 3), (_B, 2, 2)])

    session.execute = AsyncMock(side_effect=_execute)
    repo = NodeDegreeRepository(session)
    result = await repo.get_degree_map()
    assert result[UUID(_A)] == (5, 3)
    assert result[UUID(_B)] == (2, 2)
