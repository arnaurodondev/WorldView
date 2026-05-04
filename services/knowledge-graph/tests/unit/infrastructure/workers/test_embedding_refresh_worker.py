"""Unit tests for EmbeddingRefreshWorker (Worker 13F) — batch embed path."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_SUMMARY_ID_1 = UUID("00000000-0000-0000-0000-000000000011")
_SUMMARY_ID_2 = UUID("00000000-0000-0000-0000-000000000012")
_SUMMARY_ID_3 = UUID("00000000-0000-0000-0000-000000000013")

_REL_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository"
_SUMMARY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary.RelationSummaryRepository"


def _make_session_factory() -> tuple:
    """Return (session_factory, rel_repo_mock, summary_repo_mock)."""
    session = AsyncMock()
    session.commit = AsyncMock()

    def _make_cm() -> AsyncMock:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    sf = MagicMock(side_effect=lambda: _make_cm())

    rel_repo = AsyncMock()
    rel_repo.fetch_stale_summary_embeddings = AsyncMock(return_value=[])
    summary_repo = AsyncMock()
    summary_repo.update_embedding = AsyncMock()

    return sf, rel_repo, summary_repo


def _make_rows(count: int) -> list:
    ids = [_SUMMARY_ID_1, _SUMMARY_ID_2, _SUMMARY_ID_3]
    return [{"summary_id": ids[i % 3], "summary_text": f"Summary text {i+1}."} for i in range(count)]


def _make_embedding_output(n: int) -> list:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

    return [EmbeddingOutput(embedding=[0.2] * 10, model_id="nomic-embed-text", dimension=10) for _ in range(n)]


@pytest.mark.unit
class TestEmbeddingRefreshWorker:
    def test_embed_called_once_for_batch(self) -> None:
        """3 stale summaries → embed() called once with 3 inputs, not 3 separate calls."""
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        rows = _make_rows(3)
        sf, rel_repo, summary_repo = _make_session_factory()
        rel_repo.fetch_stale_summary_embeddings = AsyncMock(return_value=rows)

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=_make_embedding_output(3))

        with (
            patch(_REL_REPO, return_value=rel_repo),
            patch(_SUMMARY_REPO, return_value=summary_repo),
        ):
            worker = EmbeddingRefreshWorker(sf, llm)
            asyncio.run(worker.run())

        # embed() must be called once with 3 inputs.
        llm.embed.assert_awaited_once()
        inputs = llm.embed.call_args.args[0]
        assert len(inputs) == 3, f"Expected 3 embed inputs, got {len(inputs)}"

        # update_embedding called 3 times (one per summary).
        assert summary_repo.update_embedding.await_count == 3

    def test_empty_batch_no_embed(self) -> None:
        """No stale summaries → embed() never called."""
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        sf, rel_repo, summary_repo = _make_session_factory()
        # Default: fetch_stale_summary_embeddings returns [] already.

        llm = AsyncMock()
        llm.embed = AsyncMock()

        with (
            patch(_REL_REPO, return_value=rel_repo),
            patch(_SUMMARY_REPO, return_value=summary_repo),
        ):
            worker = EmbeddingRefreshWorker(sf, llm)
            asyncio.run(worker.run())

        llm.embed.assert_not_awaited()
        summary_repo.update_embedding.assert_not_awaited()
