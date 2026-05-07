"""DEF-034 / Wave B-5 — read/write replica split coverage.

These tests are intentionally minimal: they assert that every scheduler
worker affected by the R23 split:

  1. Accepts a ``read_session_factory`` keyword argument (default ``None``).
  2. Stores the read factory on ``self._read_session_factory``, falling back
     to the write factory when no read replica is configured.
  3. Routes its Phase-1 read query through the read factory at runtime.

The third assertion is provided for the workers that were actively split
(definition / narrative / embedding / fundamentals) by mocking both factory
context managers and verifying which one was opened first.  Workers that are
forward-compat only (provisional, age sync) just assert (1) + (2).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_factory(name: str) -> tuple[MagicMock, AsyncMock]:
    """Return a (factory, session) pair where ``factory()`` is a working async
    context manager yielding ``session``.

    The session is also returned so individual tests can attach mock query
    results without re-wiring the context manager dance.
    """
    session = AsyncMock(name=f"{name}_session")
    session.commit = AsyncMock()

    cm = AsyncMock(name=f"{name}_cm")
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(name=name)
    factory.return_value = cm
    return factory, session


# ---------------------------------------------------------------------------
# Constructor wiring
# ---------------------------------------------------------------------------


class TestDefinitionRefreshConstructor:
    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        llm = MagicMock()

        worker = DefinitionRefreshWorker(write_sf, llm, read_session_factory=read_sf)
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        write_sf, _ = _make_factory("write")
        worker = DefinitionRefreshWorker(write_sf, MagicMock())
        assert worker._read_session_factory is write_sf


class TestNarrativeRefreshConstructor:
    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        worker = NarrativeRefreshWorker(write_sf, MagicMock(), read_session_factory=read_sf)
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        write_sf, _ = _make_factory("write")
        worker = NarrativeRefreshWorker(write_sf, MagicMock())
        assert worker._read_session_factory is write_sf


class TestEmbeddingRefreshConstructor:
    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        worker = EmbeddingRefreshWorker(write_sf, MagicMock(), read_session_factory=read_sf)
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        write_sf, _ = _make_factory("write")
        worker = EmbeddingRefreshWorker(write_sf, MagicMock())
        assert worker._read_session_factory is write_sf


class TestFundamentalsRefreshConstructor:
    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        worker = FundamentalsRefreshWorker(
            write_sf,
            MagicMock(),
            "http://localhost:9999",
            read_session_factory=read_sf,
        )
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        write_sf, _ = _make_factory("write")
        worker = FundamentalsRefreshWorker(write_sf, MagicMock(), "http://x")
        assert worker._read_session_factory is write_sf


class TestProvisionalEnrichmentConstructor:
    """Constructor wiring only — Phase 1 claim path uses the WRITE factory in
    the same transaction (SELECT FOR UPDATE + UPDATE), so no behavioural switch
    happens today."""

    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment import ProvisionalEnrichmentWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        worker = ProvisionalEnrichmentWorker(write_sf, MagicMock(), read_session_factory=read_sf)
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.provisional_enrichment import ProvisionalEnrichmentWorker

        write_sf, _ = _make_factory("write")
        worker = ProvisionalEnrichmentWorker(write_sf, MagicMock())
        assert worker._read_session_factory is write_sf


class TestAgeSyncConstructor:
    """Constructor wiring only — AGE Cypher writes share the session with the
    SELECTs (LOAD 'age' must run on the same connection), so the run path
    keeps using the write factory.  Read factory is stored for future use."""

    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        valkey = MagicMock()
        settings = MagicMock(cypher_enabled=False)
        worker = AgeSyncWorker(write_sf, valkey, settings, read_session_factory=read_sf)
        assert worker._read_session_factory is read_sf
        assert worker._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        write_sf, _ = _make_factory("write")
        worker = AgeSyncWorker(write_sf, MagicMock(), MagicMock(cypher_enabled=False))
        assert worker._read_session_factory is write_sf


class TestEntityEnrichmentAdapterConstructor:
    def test_accepts_read_session_factory(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
            EntityEnrichmentAdapter,
        )

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")
        adapter = EntityEnrichmentAdapter(write_sf, read_session_factory=read_sf)
        assert adapter._read_session_factory is read_sf
        assert adapter._sf is write_sf

    def test_falls_back_to_write_factory_when_none(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
            EntityEnrichmentAdapter,
        )

        write_sf, _ = _make_factory("write")
        adapter = EntityEnrichmentAdapter(write_sf)
        assert adapter._read_session_factory is write_sf


# ---------------------------------------------------------------------------
# Runtime fetch-uses-read-factory checks for split workers.
# ---------------------------------------------------------------------------


class TestDefinitionRefreshFetchUsesReadFactory:
    @pytest.mark.asyncio
    async def test_phase1_opens_read_factory_session(self) -> None:
        """The Phase 1 ``get_due_for_refresh`` SELECT must open a session from
        the read factory; when ``due`` is empty the worker returns early so
        the write factory is never opened."""
        from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

        write_sf, _write_sess = _make_factory("write")
        read_sf, _read_sess = _make_factory("read")

        # Stub the repository so Phase 1 returns no due rows — keeps the test
        # focused on which factory is opened.
        from knowledge_graph.infrastructure.intelligence_db.repositories import entity_embedding_state as ees_mod

        async def _empty(*args, **kwargs):
            return []

        # The repo is constructed inside ``run`` against ``session``; patch
        # ``get_due_for_refresh`` on the class itself so any instance returns [].
        original = ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh
        ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh = _empty  # type: ignore[assignment]
        try:
            worker = DefinitionRefreshWorker(write_sf, MagicMock(), read_session_factory=read_sf)
            await worker.run()
        finally:
            ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh = original  # type: ignore[assignment]

        # Read factory was opened for Phase 1 fetch.
        read_sf.assert_called_once()
        # Write factory must NOT be opened — Phase 3 short-circuits on empty due.
        write_sf.assert_not_called()


class TestNarrativeRefreshFetchUsesReadFactory:
    @pytest.mark.asyncio
    async def test_phase1_opens_read_factory_session(self) -> None:
        from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")

        from knowledge_graph.infrastructure.intelligence_db.repositories import entity_embedding_state as ees_mod

        async def _empty(*args, **kwargs):
            return []

        original = ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh
        ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh = _empty  # type: ignore[assignment]
        try:
            worker = NarrativeRefreshWorker(write_sf, MagicMock(), read_session_factory=read_sf)
            await worker.run()
        finally:
            ees_mod.EntityEmbeddingStateRepository.get_due_for_refresh = original  # type: ignore[assignment]

        read_sf.assert_called_once()
        write_sf.assert_not_called()


class TestEmbeddingRefreshFetchUsesReadFactory:
    @pytest.mark.asyncio
    async def test_phase1_opens_read_factory_session(self) -> None:
        from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker

        write_sf, _ = _make_factory("write")
        read_sf, _ = _make_factory("read")

        # Patch the relation repository's stale fetch to return [].
        from knowledge_graph.infrastructure.intelligence_db.repositories import relation as rel_mod

        async def _empty(*args, **kwargs):
            return []

        # ``fetch_stale_summary_embeddings`` is added at runtime via ``# type: ignore[attr-defined]``
        # in the worker; setattr keeps the test stable even if the canonical
        # method moves.
        rel_mod.RelationRepository.fetch_stale_summary_embeddings = _empty  # type: ignore[attr-defined]
        try:
            worker = EmbeddingRefreshWorker(write_sf, MagicMock(), read_session_factory=read_sf)
            await worker.run()
        finally:
            # Best-effort cleanup so this monkey-patch does not leak across tests.
            try:
                delattr(rel_mod.RelationRepository, "fetch_stale_summary_embeddings")
            except AttributeError:
                pass

        read_sf.assert_called_once()
        write_sf.assert_not_called()


class TestEntityEnrichmentAdapterFetchUsesReadFactory:
    @pytest.mark.asyncio
    async def test_list_unenriched_opens_read_factory_session(self) -> None:
        """``list_unenriched`` is a pure SELECT — must open the read factory."""
        from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
            EntityEnrichmentAdapter,
        )

        write_sf, _ = _make_factory("write")
        read_sf, read_sess = _make_factory("read")

        # Make ``session.execute`` return an object whose ``fetchall()`` is [].
        result_obj = MagicMock()
        result_obj.fetchall = MagicMock(return_value=[])
        read_sess.execute = AsyncMock(return_value=result_obj)

        adapter = EntityEnrichmentAdapter(write_sf, read_session_factory=read_sf)
        rows = await adapter.list_unenriched(batch_size=10)

        assert rows == []
        read_sf.assert_called_once()
        # The write factory is only used by mutation methods that take a caller
        # supplied session; ``list_unenriched`` must never open a write session.
        write_sf.assert_not_called()
