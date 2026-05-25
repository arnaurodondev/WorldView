"""Unit tests for EmbeddingRefreshWorker (Worker 13F) — batch embed path."""

from __future__ import annotations

import asyncio
from datetime import UTC
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
    return [{"summary_id": ids[i % 3], "summary_text": f"Summary text {i + 1}."} for i in range(count)]


def _make_embedding_output(n: int) -> list:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

    return [EmbeddingOutput(embedding=[0.2] * 10, model_id="nomic-embed-text", dimension=10) for _ in range(n)]


@pytest.mark.unit()
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

    # ──────────────────────────────────────────────────────────────────────
    # Wave A-2 / DEF-022 — model_id + embedded_at tracking
    # ──────────────────────────────────────────────────────────────────────

    def test_update_embedding_writes_model_id(self) -> None:
        """update_embedding receives the configured summary_embedding_model_id."""
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        rows = _make_rows(2)
        sf, rel_repo, summary_repo = _make_session_factory()
        rel_repo.fetch_stale_summary_embeddings = AsyncMock(return_value=rows)

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=_make_embedding_output(2))

        with (
            patch(_REL_REPO, return_value=rel_repo),
            patch(_SUMMARY_REPO, return_value=summary_repo),
        ):
            worker = EmbeddingRefreshWorker(
                sf,
                llm,
                summary_embedding_model_id="BAAI/bge-large-en-v1.5",
            )
            asyncio.run(worker.run())

        # Every call must include the configured model_id (kw-only).
        assert summary_repo.update_embedding.await_count == 2
        for call in summary_repo.update_embedding.await_args_list:
            assert call.kwargs.get("model_id") == "BAAI/bge-large-en-v1.5"

    def test_update_embedding_writes_embedded_at(self) -> None:
        """embedded_at kwarg is timezone-aware UTC and within 1s of utc_now()."""
        from datetime import datetime

        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        rows = _make_rows(1)
        sf, rel_repo, summary_repo = _make_session_factory()
        rel_repo.fetch_stale_summary_embeddings = AsyncMock(return_value=rows)

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=_make_embedding_output(1))

        before = datetime.now(tz=UTC)
        with (
            patch(_REL_REPO, return_value=rel_repo),
            patch(_SUMMARY_REPO, return_value=summary_repo),
        ):
            worker = EmbeddingRefreshWorker(sf, llm)
            asyncio.run(worker.run())
        after = datetime.now(tz=UTC)

        assert summary_repo.update_embedding.await_count == 1
        embedded_at = summary_repo.update_embedding.await_args.kwargs["embedded_at"]
        assert isinstance(embedded_at, datetime)
        assert embedded_at.tzinfo is not None, "embedded_at must be tz-aware"
        # Sandwich check: within the [before, after] window (which is ≤1s wide
        # in practice for a single-row run).
        assert before <= embedded_at <= after

    def test_summary_embedding_model_id_falls_back_to_embedding_model_id(self) -> None:
        """When summary_embedding_model_id is None, the worker reuses embedding_model_id."""
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        rows = _make_rows(1)
        sf, rel_repo, summary_repo = _make_session_factory()
        rel_repo.fetch_stale_summary_embeddings = AsyncMock(return_value=rows)

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=_make_embedding_output(1))

        with (
            patch(_REL_REPO, return_value=rel_repo),
            patch(_SUMMARY_REPO, return_value=summary_repo),
        ):
            worker = EmbeddingRefreshWorker(sf, llm, embedding_model_id="custom-model-id")
            asyncio.run(worker.run())

        assert summary_repo.update_embedding.await_args.kwargs["model_id"] == "custom-model-id"


@pytest.mark.unit()
class TestSettingsDefaults:
    """Wave A-2 / DEF-022 — Settings field defaults."""

    def test_settings_default_model_id(self) -> None:
        """Default value of summary_embedding_model_id is the canonical 1024-dim slug."""
        import os
        from unittest.mock import patch as _patch

        from knowledge_graph.config import Settings

        # Clear the env var so we observe the in-code default, and provide the
        # required DATABASE_URL / storage creds so Settings instantiation
        # doesn't fail on unrelated required fields.
        env = {
            "KNOWLEDGE_GRAPH_DATABASE_URL": "postgresql+asyncpg://x:y@localhost/db",
            "KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY": "k",
            "KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY": "s",
        }
        with _patch.dict(os.environ, env, clear=True):
            settings = Settings()

        assert settings.summary_embedding_model_id == "BAAI/bge-large-en-v1.5"
