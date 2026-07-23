"""Unit tests for the partial-HNSW-index match in the entity-embedding ANN repo.

Context — postgres-OOM root cause (2026-07-22):
  ``entity_embedding_state`` has a PARTIAL HNSW index per view_type
  (``... WHERE view_type = 'definition' AND embedding IS NOT NULL`` etc., from
  intelligence-migrations 0001). Postgres only matches a partial index when its
  predicate is provably implied by the query WHERE clause, and that proof is
  made against CONSTANT LITERALS. The repository previously bound ``view_type``
  as a parameter (``view_type = :view_type``), which is opaque to the planner,
  so the partial index was skipped and the query fell back to a Parallel Seq
  Scan + Sort over the whole table — a work_mem spike per concurrent backend
  that, times ~30 direct backends, drove postgres past 6Gi → OOM.

  Fix: validate ``view_type`` against an allow-list and inline it as a SQL
  literal so the planner uses the partial HNSW index.

These tests do NOT hit the DB — they assert the SQL SHAPE (which is what decides
whether Postgres can use the partial index) and the injection allow-list gate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_ann import (
    SqlalchemyEntityEmbeddingANNRepository,
)

pytestmark = pytest.mark.unit


def _session() -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_view_type_inlined_as_literal_not_bind_param() -> None:
    """The WHERE clause must use a LITERAL view_type so the partial HNSW index matches."""
    session = _session()
    repo = SqlalchemyEntityEmbeddingANNRepository(session)

    await repo.find_nearest(query_embedding=[0.1] * 1024, view_type="fundamentals_ohlcv", limit=40)

    call = session.execute.await_args
    sql = str(call.args[0])
    params = call.args[1]

    # Literal predicate on the vector table's own column — this is what lets
    # Postgres prove the partial-index predicate and use the HNSW index.
    assert "ees.view_type = 'fundamentals_ohlcv'" in sql
    # It must NOT be a bind parameter (the planner-opaque form that caused OOM).
    assert "ees.view_type = :view_type" not in sql
    assert "view_type" not in params
    # Distance ORDER BY + LIMIT is what the HNSW index answers.
    assert "ORDER BY distance ASC" in sql


@pytest.mark.asyncio
async def test_unknown_view_type_is_rejected() -> None:
    """A view_type without a partial index (or a malicious value) must be refused."""
    repo = SqlalchemyEntityEmbeddingANNRepository(_session())

    with pytest.raises(ValueError, match="Unknown view_type"):
        await repo.find_nearest(query_embedding=[0.1] * 1024, view_type="definition'; DROP TABLE--")


@pytest.mark.asyncio
async def test_all_indexed_view_types_accepted() -> None:
    """Every view_type with a partial HNSW index must be inlined correctly."""
    for vt in ("definition", "narrative", "fundamentals_ohlcv"):
        session = _session()
        repo = SqlalchemyEntityEmbeddingANNRepository(session)
        await repo.find_nearest(query_embedding=[0.1] * 1024, view_type=vt)
        sql = str(session.execute.await_args.args[0])
        assert f"ees.view_type = '{vt}'" in sql


@pytest.mark.asyncio
async def test_optional_filters_still_use_bind_params() -> None:
    """exclude_entity_id / entity_types stay parameterized (only view_type is inlined)."""
    session = _session()
    repo = SqlalchemyEntityEmbeddingANNRepository(session)

    await repo.find_nearest(
        query_embedding=[0.1] * 1024,
        view_type="definition",
        exclude_entity_id=UUID("01234567-89ab-7def-8012-cccccccccccc"),
        entity_types=["organization"],
    )
    call = session.execute.await_args
    sql = str(call.args[0])
    params = call.args[1]
    assert "ees.entity_id != :exclude_entity_id" in sql
    assert "ce.entity_type = ANY(:entity_types)" in sql
    assert params["entity_types"] == ["organization"]
