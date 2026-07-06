"""Unit tests for the partial-index accelerated ANN path (S6 chunk-search latency fix).

Context — why this path exists:
  ``source_type`` lives on ``document_source_metadata``, so a source-filtered ANN
  query historically bypassed the pgvector HNSW index and fell back to a
  filter-first EXACT KNN (a MATERIALIZED CTE that exact-sorts the whole bucket).
  That is O(bucket-size): the R1 filings backfill grew ``sec_edgar`` to ~30.5k
  rows, so the exact sort took ~19 s — past rag-chat's 10 s client timeout, so
  ``get_filings`` returned 0 items. Migration 0024 denormalizes ``source_type``
  onto ``chunk_embeddings`` / ``section_embeddings`` and adds a PARTIAL HNSW index
  per indexed bucket; for a single indexed source_type (no entity filter) the
  repository now emits a LITERAL ``source_type='<src>'`` predicate so the planner
  uses that index.

These tests do NOT hit the DB — they assert the SQL SHAPE (which decides whether
Postgres can use the partial index) and the routing/injection-gate logic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository


def _make_session() -> AsyncMock:
    """Session mock for the accel path: [set_config(ef), main query, COUNT]."""
    session = AsyncMock()
    ef_result = MagicMock()
    main_result = MagicMock()
    main_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    session.execute = AsyncMock(side_effect=[ef_result, main_result, count_result])
    return session


def _all_sql(session: AsyncMock) -> list[str]:
    return [str(call[0][0]) for call in session.execute.call_args_list]


def _find_sql(session: AsyncMock, needle: str) -> str:
    for sql in _all_sql(session):
        if needle in sql:
            return sql
    raise AssertionError(f"no executed SQL contained {needle!r}")


# ── _accel_source_type routing ────────────────────────────────────────────────


class TestAccelSourceTypeRouting:
    """The accel path fires ONLY for a single allow-listed source_type + no entity filter."""

    def _repo(self) -> ChunkANNRepository:
        return ChunkANNRepository(AsyncMock())  # default allow-list = {"sec_edgar"}

    def test_single_indexed_source_no_entity_filter_is_eligible(self) -> None:
        assert self._repo()._accel_source_type(["sec_edgar"], None, None) == "sec_edgar"

    def test_multi_source_falls_back(self) -> None:
        # A single ORDER BY cannot combine two per-source HNSW partials → exact path.
        assert self._repo()._accel_source_type(["sec_edgar", "eodhd"], None, None) is None

    def test_non_indexed_source_falls_back(self) -> None:
        assert self._repo()._accel_source_type(["eodhd_ticker_news"], None, None) is None

    def test_empty_source_falls_back(self) -> None:
        assert self._repo()._accel_source_type([], None, None) is None

    def test_entity_id_filter_falls_back(self) -> None:
        assert self._repo()._accel_source_type(["sec_edgar"], [uuid4()], None) is None

    def test_entity_type_filter_falls_back(self) -> None:
        assert self._repo()._accel_source_type(["sec_edgar"], None, ["organization"]) is None

    def test_unsafe_identifier_is_rejected_even_if_allow_listed(self) -> None:
        # Injection gate: an allow-listed value that is not [a-z0-9_]+ is refused,
        # so a malformed config value can never be inlined as a SQL literal.
        repo = ChunkANNRepository(AsyncMock(), indexed_source_types=frozenset({"sec';DROP--"}))
        assert repo._accel_source_type(["sec';DROP--"], None, None) is None

    def test_custom_allow_list_enables_other_source(self) -> None:
        repo = ChunkANNRepository(AsyncMock(), indexed_source_types=frozenset({"earnings_transcript"}))
        assert repo._accel_source_type(["earnings_transcript"], None, None) == "earnings_transcript"


# ── Accelerated SQL shape ─────────────────────────────────────────────────────


class TestAccelChunkSql:
    @pytest.mark.asyncio
    async def test_uses_literal_source_type_predicate_and_index_order_by(self) -> None:
        """The accel query must filter ce.source_type by LITERAL and ORDER BY distance.

        A literal predicate on the vector table's own column is what lets Postgres
        match the partial HNSW index idx_chunk_emb_hnsw_sec_edgar.
        """
        session = _make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=25,
            min_score=0.0,
            source_types=["sec_edgar"],
            tenant_id=None,
        )
        sql = _find_sql(session, "FROM chunk_embeddings")
        # Literal predicate on the denormalized column (NOT a bind param, NOT dsm).
        assert "ce.source_type = 'sec_edgar'" in sql
        assert "dsm.source_type = ANY(:source_types)" not in sql
        assert "ce.embedding_status = 'ready'" in sql
        # Distance ORDER BY + LIMIT is what the HNSW index answers.
        assert "ORDER BY ce.embedding <=> cast(:vec AS vector)" in sql
        # Must NOT use the exact-KNN MATERIALIZED CTE fence (that is the slow path).
        assert "MATERIALIZED" not in sql

    @pytest.mark.asyncio
    async def test_accel_path_widens_ef_search(self) -> None:
        """The accel path sets hnsw.ef_search to the configured accel value (400)."""
        session = _make_session()
        repo = ChunkANNRepository(session, accel_ef_search=400)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=25,
            source_types=["sec_edgar"],
            tenant_id=None,
        )
        # set_config is the first executed statement; its params carry ef='400'.
        first_call = session.execute.call_args_list[0]
        assert "set_config('hnsw.ef_search'" in str(first_call[0][0])
        assert first_call[0][1] == {"ef": "400"}

    @pytest.mark.asyncio
    async def test_accel_path_keeps_tenant_boundary(self) -> None:
        """tenant_id=None on the accel path must still be public-only (no leak)."""
        session = _make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=25,
            source_types=["sec_edgar"],
            tenant_id=None,
        )
        sql = _find_sql(session, "FROM chunk_embeddings")
        assert "c.tenant_id IS NULL" in sql
        assert "c.tenant_id = '00000000-0000-0000-0000-000000000000'::uuid" in sql
        assert "c.tenant_id = CAST(:tenant_id_str AS UUID)" not in sql

    @pytest.mark.asyncio
    async def test_accel_path_applies_date_filter_as_post_filter(self) -> None:
        """A date filter co-occurring with the source filter stays supported."""
        session = _make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=25,
            date_from="2026-01-01T00:00:00Z",
            date_to="2026-06-30T00:00:00Z",
            source_types=["sec_edgar"],
            tenant_id=None,
        )
        sql = _find_sql(session, "FROM chunk_embeddings")
        assert "dsm.published_at >= :date_from" in sql
        assert "dsm.published_at <= :date_to" in sql
        # Index selection must be preserved despite the date post-filter.
        assert "ce.source_type = 'sec_edgar'" in sql

    @pytest.mark.asyncio
    async def test_non_indexed_source_still_uses_exact_cte(self) -> None:
        """A non-allow-listed source keeps the correct exact-KNN path (recall preserved)."""
        session = _make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=25,
            source_types=["eodhd_ticker_news"],
            tenant_id=None,
        )
        # The exact path issues the filtered COUNT first, then the MATERIALIZED CTE.
        joined = "\n".join(_all_sql(session))
        assert "MATERIALIZED" in joined
        assert "ce.source_type = 'eodhd_ticker_news'" not in joined


class TestAccelSectionSql:
    @pytest.mark.asyncio
    async def test_section_accel_uses_literal_predicate(self) -> None:
        session = _make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="section",
            top_k=25,
            source_types=["sec_edgar"],
            tenant_id=None,
        )
        sql = _find_sql(session, "FROM section_embeddings")
        assert "se.source_type = 'sec_edgar'" in sql
        assert "ORDER BY se.embedding <=> cast(:vec AS vector)" in sql
        assert "MATERIALIZED" not in sql
