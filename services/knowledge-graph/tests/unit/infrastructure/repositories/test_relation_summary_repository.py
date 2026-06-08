"""Unit tests for RelationSummaryRepository.update_embedding (FQA-2).

Regression coverage for the pgvector binding bug that crashed the
``embedding_refresh`` KG worker every 5 minutes with
``DataError: expected str, got list``.

Root cause: ``update_embedding`` previously bound a Python ``list[float]``
directly to a ``vector`` column.  asyncpg (the driver behind the async
SQLAlchemy engine) cannot serialise a list into a ``vector`` — pgvector
requires the text literal ``[v1,v2,...]`` combined with a ``CAST(:p AS
vector)`` in SQL.  This is the same pattern used by ``entity_embedding_state``.

These tests mock the SQLAlchemy ``AsyncSession`` so they do not need a real
Postgres instance — they assert that the SQL ``execute`` call receives:
  - a ``CAST(... AS vector)`` clause in the rendered text, and
  - an ``embedding`` parameter that is a ``str`` formatted as ``[..]``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
    RelationSummaryRepository,
)

pytestmark = pytest.mark.unit


_SUMMARY_ID = UUID("01234567-89ab-7def-8012-cccccccccccc")
_EMBEDDED_AT = datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_update_embedding_formats_pgvector_text_literal() -> None:
    """The list[float] must be formatted as ``[v1,v2,v3]`` for pgvector."""
    session = MagicMock()
    session.execute = AsyncMock()
    repo = RelationSummaryRepository(session)

    await repo.update_embedding(
        _SUMMARY_ID,
        [0.1, 0.2, 0.3],
        model_id="BAAI/bge-large-en-v1.5",
        embedded_at=_EMBEDDED_AT,
    )

    session.execute.assert_awaited_once()
    call_args = session.execute.await_args
    # First positional arg is a SQLAlchemy ``TextClause`` — render its template.
    sql_text = str(call_args.args[0])
    params = call_args.args[1]

    # SQL must CAST the bound parameter as a vector.  Without the CAST,
    # asyncpg infers ``text`` and Postgres raises an implicit-cast error.
    assert "CAST(:embedding AS vector)" in sql_text

    # The bound value must be a STRING, never a Python list — the regression
    # was a list reaching asyncpg's vector codec.
    assert isinstance(params["embedding"], str)
    assert params["embedding"] == "[0.1,0.2,0.3]"
    assert params["summary_id"] == str(_SUMMARY_ID)
    assert params["model_id"] == "BAAI/bge-large-en-v1.5"
    assert params["embedded_at"] == _EMBEDDED_AT


@pytest.mark.asyncio
async def test_update_embedding_handles_large_vector() -> None:
    """A realistic 1024-dim BGE-large embedding should serialise cleanly."""
    session = MagicMock()
    session.execute = AsyncMock()
    repo = RelationSummaryRepository(session)

    big_vec = [float(i) / 1024.0 for i in range(1024)]
    await repo.update_embedding(
        _SUMMARY_ID,
        big_vec,
        model_id="BAAI/bge-large-en-v1.5",
        embedded_at=_EMBEDDED_AT,
    )

    params = session.execute.await_args.args[1]
    # Must start with ``[`` and end with ``]`` and contain 1023 commas.
    assert params["embedding"].startswith("[")
    assert params["embedding"].endswith("]")
    assert params["embedding"].count(",") == 1023
