"""Unit tests for NarrativeRefreshWorker (Worker 13D-2) — batch embed path."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID_1 = UUID("00000000-0000-0000-0000-000000000001")
_ENTITY_ID_2 = UUID("00000000-0000-0000-0000-000000000002")
_ENTITY_ID_3 = UUID("00000000-0000-0000-0000-000000000003")
_ENTITY_ID_4 = UUID("00000000-0000-0000-0000-000000000004")
_ENTITY_ID_5 = UUID("00000000-0000-0000-0000-000000000005")

_EMB_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository"
)


def _make_due_row(entity_id: UUID, name: str = "TestEntity", entity_type: str = "person") -> dict:
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "entity_type": entity_type,
        "source_hash": None,
        "source_text": None,
        "ticker": None,
        "isin": None,
        "exchange": None,
    }


def _make_session_factory(due_rows: list) -> tuple:
    """Return (session_factory, emb_repo).

    The factory returns a fresh context-manager each call (Phase 1 read and
    Phase 3 write each open a separate session).  Both share the same underlying
    session mock so we can assert on it.

    The session execute() returns an empty result (no claims or contradictions),
    so _build_narrative_text produces a minimal 'Name (type)' string.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    # execute() is called by _build_narrative_text for claims + contradictions.
    # Return empty result objects so no lines are appended.
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=empty_result)

    def _make_cm() -> AsyncMock:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    sf = MagicMock(side_effect=lambda: _make_cm())

    emb_repo = AsyncMock()
    emb_repo.get_due_for_refresh = AsyncMock(return_value=due_rows)
    emb_repo.upsert = AsyncMock()

    return sf, emb_repo


def _make_embedding_output(n: int = 1) -> list:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

    return [EmbeddingOutput(embedding=[0.1] * 10, model_id="nomic-embed-text", dimension=10) for _ in range(n)]


@pytest.mark.unit()
class TestNarrativeRefreshWorker:
    def test_embed_called_once_for_batch_of_entities(self) -> None:
        """5 due entities → embed() must be called exactly once with 5 inputs."""
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        due_rows = [
            _make_due_row(eid, f"Entity{i}")
            for i, eid in enumerate(
                [
                    _ENTITY_ID_1,
                    _ENTITY_ID_2,
                    _ENTITY_ID_3,
                    _ENTITY_ID_4,
                    _ENTITY_ID_5,
                ],
            )
        ]

        sf, emb_repo = _make_session_factory(due_rows)

        llm = AsyncMock()
        # Return 5 outputs for 5 inputs.
        llm.embed = AsyncMock(return_value=_make_embedding_output(5))

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = NarrativeRefreshWorker(sf, llm, embedding_model_id="nomic-embed-text")
            asyncio.run(worker.run())

        # embed() called once (not 5 times).
        llm.embed.assert_awaited_once()
        # The single call must have received 5 inputs.
        call_args = llm.embed.call_args
        assert call_args is not None
        inputs = call_args.args[0]
        assert len(inputs) == 5, f"Expected 5 embed inputs, got {len(inputs)}"

        # Upsert called 5 times (one per entity).
        assert emb_repo.upsert.await_count == 5

    def test_empty_due_returns_without_embed(self) -> None:
        """No due entities → embed() is never called."""
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        sf, emb_repo = _make_session_factory(due_rows=[])

        llm = AsyncMock()
        llm.embed = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = NarrativeRefreshWorker(sf, llm)
            asyncio.run(worker.run())

        llm.embed.assert_not_awaited()
        emb_repo.upsert.assert_not_awaited()

    def test_embed_failure_still_upserts_with_none_embedding(self) -> None:
        """When embed returns [] (transient failure), upsert is still called with embedding=None."""
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        due_rows = [_make_due_row(_ENTITY_ID_1, "Apple Inc.", "financial_instrument")]
        sf, emb_repo = _make_session_factory(due_rows)

        llm = AsyncMock()
        # Simulate DeepInfra transient failure — embed returns empty list.
        llm.embed = AsyncMock(return_value=[])

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = NarrativeRefreshWorker(sf, llm)
            asyncio.run(worker.run())

        # Upsert must still be called (Phase 3 always writes the prepared entries).
        emb_repo.upsert.assert_awaited_once()

        # The embedding kwarg must be None.
        call_kwargs = emb_repo.upsert.call_args.kwargs
        assert call_kwargs.get("embedding") is None, "embedding should be None when embed returns empty list"

    def test_llm_narrative_used_when_available(self) -> None:
        """BP-542 regression: when entity_narrative_versions has rich text, worker must use it.

        The hourly NarrativeRefreshWorker previously overwrote LLM narratives with
        the claims-template stub because _build_narrative_text never checked
        entity_narrative_versions.  This test verifies the fix: if the first DB
        execute() (LLM narrative lookup) returns a row with >60 chars, that text
        is used as source_text — not the '{name} ({type})' stub.
        """

        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        llm_narrative = (
            "NVIDIA Corporation is a leading semiconductor company that designs graphics "
            "processing units for gaming and AI workloads. Its H100 GPU has become the "
            "de facto standard for large-scale AI training infrastructure globally."
        )

        due_rows = [_make_due_row(_ENTITY_ID_1, "NVIDIA Corporation", "financial_instrument")]
        sf, emb_repo = _make_session_factory(due_rows)

        # Override execute() on the session: first call (LLM narrative lookup) returns
        # a row with rich text; subsequent calls (claims, contradictions) return empty.
        session = AsyncMock()
        session.commit = AsyncMock()

        llm_row_result = MagicMock()
        llm_row_result.fetchone.return_value = (llm_narrative,)
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        empty_result.fetchone.return_value = None

        execute_results = [llm_row_result, empty_result, empty_result]
        execute_call_count = 0

        async def _side_effect(*args: object, **kwargs: object) -> object:
            nonlocal execute_call_count
            result = execute_results[min(execute_call_count, len(execute_results) - 1)]
            execute_call_count += 1
            return result

        session.execute = AsyncMock(side_effect=_side_effect)

        def _make_cm() -> AsyncMock:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        sf_llm = MagicMock(side_effect=lambda: _make_cm())

        emb_repo_llm = AsyncMock()
        emb_repo_llm.get_due_for_refresh = AsyncMock(return_value=due_rows)
        emb_repo_llm.upsert = AsyncMock()

        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=_make_embedding_output(1))

        with patch(_EMB_REPO, return_value=emb_repo_llm):
            worker = NarrativeRefreshWorker(sf_llm, llm_client)
            asyncio.run(worker.run())

        # Upsert must have been called with the LLM narrative as source_text.
        emb_repo_llm.upsert.assert_awaited_once()
        upsert_kwargs = emb_repo_llm.upsert.call_args.kwargs
        assert (
            upsert_kwargs.get("source_text") == llm_narrative
        ), "source_text must be the LLM narrative, not the claims-template stub"

    def test_llm_narrative_stub_falls_back_to_claims_template(self) -> None:
        """BP-542: when entity_narrative_versions has a stub (<= 60 chars), fall back to claims template."""
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        stub_narrative = "NVIDIA Corporation (financial_instrument)"  # <60 chars — stub

        due_rows = [_make_due_row(_ENTITY_ID_2, "NVIDIA Corporation", "financial_instrument")]

        session = AsyncMock()
        session.commit = AsyncMock()

        llm_stub_result = MagicMock()
        llm_stub_result.fetchone.return_value = (stub_narrative,)
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        empty_result.fetchone.return_value = None

        execute_results = [llm_stub_result, empty_result, empty_result]
        execute_call_count = 0

        async def _side_effect(*args: object, **kwargs: object) -> object:
            nonlocal execute_call_count
            result = execute_results[min(execute_call_count, len(execute_results) - 1)]
            execute_call_count += 1
            return result

        session.execute = AsyncMock(side_effect=_side_effect)

        def _make_cm() -> AsyncMock:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        sf_fallback = MagicMock(side_effect=lambda: _make_cm())

        emb_repo_fallback = AsyncMock()
        emb_repo_fallback.get_due_for_refresh = AsyncMock(return_value=due_rows)
        emb_repo_fallback.upsert = AsyncMock()

        llm_client = AsyncMock()
        llm_client.embed = AsyncMock(return_value=_make_embedding_output(1))

        with patch(_EMB_REPO, return_value=emb_repo_fallback):
            worker = NarrativeRefreshWorker(sf_fallback, llm_client)
            asyncio.run(worker.run())

        emb_repo_fallback.upsert.assert_awaited_once()
        upsert_kwargs = emb_repo_fallback.upsert.call_args.kwargs
        # Falls back to claims template: source_text starts with "NVIDIA Corporation (financial_instrument)"
        source_text = upsert_kwargs.get("source_text", "")
        assert source_text.startswith(
            "NVIDIA Corporation (financial_instrument)"
        ), f"Expected claims-template fallback, got: {source_text!r}"
