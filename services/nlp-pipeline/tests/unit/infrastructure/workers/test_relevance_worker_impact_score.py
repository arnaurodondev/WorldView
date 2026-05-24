"""Unit tests for PLAN-0093 T-C-3-03 — impact_score writer in ArticleRelevanceScoringWorker.

Covers the new ``_write_impact_scores`` static method that populates
``document_source_metadata.impact_score`` from ``article_impact_windows``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.infrastructure.workers.article_relevance_scoring_worker import (
    ArticleRelevanceScoringWorker,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_write_impact_scores_no_op_on_empty_list() -> None:
    """Empty doc_ids list short-circuits without touching the session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    await ArticleRelevanceScoringWorker._write_impact_scores(session, [])
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_impact_scores_calls_update_with_correct_ids() -> None:
    """PLAN-0093 T-C-3-03: UPDATE binds doc_ids as the :doc_ids param."""
    session = AsyncMock()
    session.execute = AsyncMock()
    ids = [uuid.uuid4(), uuid.uuid4()]

    await ArticleRelevanceScoringWorker._write_impact_scores(session, ids)

    session.execute.assert_awaited_once()
    call = session.execute.await_args
    # Second positional arg is the bind-param dict
    params = call.args[1]
    assert params == {"doc_ids": [str(d) for d in ids]}


@pytest.mark.asyncio
async def test_write_impact_scores_uses_correlated_update() -> None:
    """PLAN-0093 T-C-3-03: SQL must JOIN through article_impact_windows GROUP BY.

    Asserts the statement structure: it MUST be a single UPDATE…FROM with
    a sub-select that aggregates MAX(impact_score) — anything else (e.g.
    one UPDATE per doc_id) would defeat the batch optimisation.
    """
    session = AsyncMock()
    session.execute = AsyncMock()
    await ArticleRelevanceScoringWorker._write_impact_scores(session, [uuid.uuid4()])

    stmt = session.execute.await_args.args[0]
    # SQLAlchemy `text()` clauses expose .text on the underlying _TextClause
    sql_text = str(stmt)
    assert "UPDATE document_source_metadata" in sql_text
    assert "MAX(impact_score)" in sql_text
    assert "article_impact_windows" in sql_text
    assert "ANY(:doc_ids)" in sql_text


@pytest.mark.asyncio
async def test_impact_score_stays_null_when_no_windows_row() -> None:
    """PLAN-0093 T-C-3-03 acceptance: don't write 0.0 when no impact_windows row.

    Because the UPDATE … FROM correlates on article_id, doc_ids that have no
    matching article_impact_windows row simply don't participate in the
    JOIN — their document_source_metadata.impact_score stays NULL. The test
    asserts the SQL shape that produces this behaviour (no COALESCE, no
    UNION ALL with 0.0 default).
    """
    session = AsyncMock()
    session.execute = AsyncMock()
    await ArticleRelevanceScoringWorker._write_impact_scores(session, [uuid.uuid4()])
    sql_text = str(session.execute.await_args.args[0])
    # If a COALESCE(..., 0) crept in, the test should fail loudly because we'd
    # be conflating "no windows yet" with "labelled zero impact".
    assert "COALESCE" not in sql_text.upper().replace("FOREIGN", "X")
