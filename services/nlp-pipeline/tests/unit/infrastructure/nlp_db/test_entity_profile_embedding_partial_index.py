"""Unit tests for the partial-HNSW-index match in the entity-profile ANN repo (S6).

Same postgres-OOM root cause as the S7 entity_embedding_ann repo (2026-07-22):
``entity_embedding_state`` has PARTIAL HNSW indexes keyed on a LITERAL view_type
predicate (intelligence-migrations 0001). Binding ``view_type`` as a parameter
is opaque to the planner, so the partial index is skipped and the query falls
back to a Parallel Seq Scan + Sort → work_mem spike per backend → OOM.

Fix: allow-list ``view_type`` and inline it as a SQL literal so the partial HNSW
index is used. These tests assert the SQL shape and the injection gate; they do
not hit the DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
    EntityProfileEmbeddingRepository,
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
    repo = EntityProfileEmbeddingRepository(session)

    await repo.ann_search(query_embedding=[0.1] * 1024, view_type="definition")

    call = session.execute.await_args
    sql = str(call.args[0])
    params = call.args[1]
    assert "WHERE view_type = 'definition'" in sql
    assert "view_type = :view_type" not in sql
    assert "view_type" not in params
    assert "ORDER BY distance ASC" in sql


@pytest.mark.asyncio
async def test_unknown_view_type_is_rejected() -> None:
    """A view_type without a partial index (or a malicious value) must be refused."""
    repo = EntityProfileEmbeddingRepository(_session())

    with pytest.raises(ValueError, match="Unknown view_type"):
        await repo.ann_search(query_embedding=[0.1] * 1024, view_type="x'; DROP TABLE--")


@pytest.mark.asyncio
async def test_all_indexed_view_types_accepted() -> None:
    """Every view_type with a partial HNSW index must be inlined correctly."""
    for vt in ("definition", "narrative", "fundamentals_ohlcv"):
        session = _session()
        repo = EntityProfileEmbeddingRepository(session)
        await repo.ann_search(query_embedding=[0.1] * 1024, view_type=vt)
        sql = str(session.execute.await_args.args[0])
        assert f"WHERE view_type = '{vt}'" in sql
