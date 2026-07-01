"""Unit tests for PLAN-0086 Wave C-1: tenant_id isolation in S6 NLP Pipeline.

Covers:
  T-C-1-02 — Section/Chunk domain model tenant_id field + consumer stamping
  T-C-1-03 — ChunkANNRepository SQL tenant_id WHERE clause (public-only vs tenant)
  T-C-1-05 — ChunkSearchRequest API schema accepts tenant_id; route passes it through
"""

from __future__ import annotations

import dataclasses
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.domain.models import Chunk, Section
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository

pytestmark = pytest.mark.unit

# ── T-C-1-02: Domain model fields ─────────────────────────────────────────────


class TestSectionDomainModelTenantId:
    """Section frozen dataclass must carry tenant_id field (PLAN-0086 C-1)."""

    def test_section_default_tenant_id_is_none(self) -> None:
        """New Section instances have tenant_id=None by default (public content)."""
        section = Section(
            section_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_index=0,
            char_start=0,
            char_end=100,
            text="Sample body text.",
            section_type="body",
            token_count=50,
        )
        assert section.tenant_id is None

    def test_section_tenant_id_can_be_set(self) -> None:
        """Section accepts a non-None tenant_id for private content."""
        tenant = uuid.uuid4()
        section = Section(
            section_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_index=0,
            char_start=0,
            char_end=100,
            text="Sample body text.",
            section_type="body",
            token_count=50,
            tenant_id=tenant,
        )
        assert section.tenant_id == tenant

    def test_section_dataclasses_replace_stamps_tenant_id(self) -> None:
        """dataclasses.replace() must propagate tenant_id onto a new instance.

        This mirrors the consumer stamping pattern in article_consumer.py:
            sections = [dataclasses.replace(s, tenant_id=tenant_id) for s in sections]
        """
        original = Section(
            section_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_index=0,
            char_start=0,
            char_end=100,
            text="Sample body text.",
            section_type="body",
            token_count=50,
        )
        assert original.tenant_id is None

        tenant = uuid.uuid4()
        stamped = dataclasses.replace(original, tenant_id=tenant)

        assert stamped.tenant_id == tenant
        # Original must be unchanged (frozen dataclass)
        assert original.tenant_id is None


class TestChunkDomainModelTenantId:
    """Chunk frozen dataclass must carry tenant_id field (PLAN-0086 C-1)."""

    def test_chunk_default_tenant_id_is_none(self) -> None:
        """New Chunk instances have tenant_id=None by default (public content)."""
        chunk = Chunk(
            chunk_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_id=uuid.uuid4(),
            chunk_index=0,
            char_start=0,
            char_end=80,
            token_count=40,
            text="sample text",
        )
        assert chunk.tenant_id is None

    def test_chunk_tenant_id_can_be_set(self) -> None:
        """Chunk accepts a non-None tenant_id for private content."""
        tenant = uuid.uuid4()
        chunk = Chunk(
            chunk_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_id=uuid.uuid4(),
            chunk_index=0,
            char_start=0,
            char_end=80,
            token_count=40,
            text="sample text",
            tenant_id=tenant,
        )
        assert chunk.tenant_id == tenant

    def test_chunk_dataclasses_replace_stamps_tenant_id(self) -> None:
        """dataclasses.replace() must propagate tenant_id onto chunks.

        Mirrors the consumer pattern:
            chunks = [dataclasses.replace(chunk, ..., tenant_id=tenant_id) for chunk in chunks]
        """
        original = Chunk(
            chunk_id=uuid.uuid4(),
            doc_id=uuid.uuid4(),
            section_id=uuid.uuid4(),
            chunk_index=0,
            char_start=0,
            char_end=80,
            token_count=40,
            text="sample text",
        )
        assert original.tenant_id is None

        tenant = uuid.uuid4()
        stamped = dataclasses.replace(original, tenant_id=tenant)

        assert stamped.tenant_id == tenant
        assert original.tenant_id is None


# ── T-C-1-03: ChunkANNRepository SQL WHERE clause ─────────────────────────────


class TestChunkANNRepositoryTenantFilter:
    """ChunkANNRepository must include the tenant_id security boundary in SQL.

    These tests do NOT hit the DB — they verify that:
      1. tenant_id=None  → the SQL includes "c.tenant_id IS NULL" (public-only)
      2. tenant_id=<str> → the SQL includes the OR clause for the specific tenant

    The security invariant: passing tenant_id=None MUST NOT return tenant-private
    chunks. Only rows where tenant_id IS NULL (public content) are returned.
    """

    def _make_session(self) -> AsyncMock:
        session = AsyncMock()
        # BUG-3: the ANN path now issues an extra ``set_config('hnsw.ef_search')``
        # statement before the main query, so the mock must supply three results:
        # [ef_search set_config, main ANN query, COUNT].
        ef_result = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        # scalar_one() for the COUNT query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[ef_result, result_mock, count_result])
        return session

    @staticmethod
    def _find_sql(session: AsyncMock, needle: str) -> str:
        """Return the first executed SQL string containing *needle*.

        The ANN path issues multiple statements (set_config + main query +
        COUNT); the tenant predicate lives on the main query, so we scan all
        calls rather than assuming a fixed index.
        """
        for call in session.execute.call_args_list:
            sql_text = str(call[0][0])
            if needle in sql_text:
                return sql_text
        raise AssertionError(f"no executed SQL contained {needle!r}")

    @pytest.mark.asyncio
    async def test_ann_search_null_tenant_adds_public_only_filter(self) -> None:
        """tenant_id=None must produce 'c.tenant_id IS NULL' in the SQL.

        CRITICAL: this is the data-leak prevention boundary — public searches
        must NEVER return tenant-private chunks.
        """
        session = self._make_session()
        repo = ChunkANNRepository(session)

        dummy_embedding = [0.1] * 1024
        await repo.ann_search(
            embedding=dummy_embedding,
            granularity="chunk",
            top_k=5,
            min_score=0.0,
            date_from=None,
            date_to=None,
            source_types=None,
            tenant_id=None,  # explicit public-only
        )

        # Locate the main ANN query (scan past the set_config statement).
        sql_text = self._find_sql(session, "chunk_embeddings")

        # The WHERE clause MUST contain the public-only filter
        assert "c.tenant_id IS NULL" in sql_text
        # BUG-3: public rows also include the PUBLIC_TENANT_ID sentinel (BP-575).
        assert "c.tenant_id = '00000000-0000-0000-0000-000000000000'::uuid" in sql_text

        # It must NOT contain the OR clause that opens up private chunks
        assert "c.tenant_id = CAST(:tenant_id_str AS UUID)" not in sql_text

    @pytest.mark.asyncio
    async def test_ann_search_with_tenant_id_adds_or_filter(self) -> None:
        """tenant_id=<str> must produce the OR clause (public + tenant chunks)."""
        session = self._make_session()
        repo = ChunkANNRepository(session)

        tenant_id = str(uuid.uuid4())
        dummy_embedding = [0.1] * 1024
        await repo.ann_search(
            embedding=dummy_embedding,
            granularity="chunk",
            top_k=5,
            min_score=0.0,
            date_from=None,
            date_to=None,
            source_types=None,
            tenant_id=tenant_id,
        )

        sql_text = self._find_sql(session, "chunk_embeddings")

        # The OR clause allows both public and tenant-private chunks
        assert "c.tenant_id IS NULL" in sql_text
        assert "CAST(:tenant_id_str AS UUID)" in sql_text

    @pytest.mark.asyncio
    async def test_lexical_search_null_tenant_adds_public_only_filter(self) -> None:
        """lexical_search with tenant_id=None must include public-only clause."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[result_mock, count_result])

        repo = ChunkANNRepository(session)
        await repo.lexical_search(
            "apple revenue",
            tenant_id=None,
        )

        call_args = session.execute.call_args_list[0]
        # lexical_search uses a parameterised text() call; the SQL is in the statement
        sql_statement = call_args[0][0]
        sql_text = str(sql_statement)

        assert "c.tenant_id IS NULL" in sql_text
        assert "tenant_id_str" not in sql_text
        # BUG-3: public rows also include the PUBLIC_TENANT_ID sentinel.
        assert "c.tenant_id = '00000000-0000-0000-0000-000000000000'::uuid" in sql_text

    @pytest.mark.asyncio
    async def test_lexical_search_with_tenant_id_adds_or_filter(self) -> None:
        """lexical_search with tenant_id=<str> must include the OR filter."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[result_mock, count_result])

        repo = ChunkANNRepository(session)
        tenant_id = str(uuid.uuid4())
        await repo.lexical_search(
            "apple revenue",
            tenant_id=tenant_id,
        )

        call_args = session.execute.call_args_list[0]
        sql_statement = call_args[0][0]
        sql_text = str(sql_statement)

        assert "c.tenant_id IS NULL" in sql_text
        assert "tenant_id_str" in sql_text


# ── BUG-3: ANN degeneracy fix (feat/fix-s6-search-quality) ────────────────────


class TestChunkANNRepositoryBug3:
    """Regression tests for the ANN degeneracy fix (BUG-3).

    Two compounding root causes made ANN chunk search return ~0 rows:
      1. Public content is stamped with the nil-UUID PUBLIC_TENANT_ID sentinel
         (BP-575), but the search predicate only matched SQL NULL — hiding ~86%
         of the public corpus (so source_types=['sec_edgar'] returned 0).
      2. pgvector post-filters the HNSW candidate set; the default ef_search=40
         starved any selective filter. We raise ef_search per query.
    """

    def _make_session(self) -> AsyncMock:
        session = AsyncMock()
        ef_result = MagicMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[ef_result, result_mock, count_result])
        return session

    @pytest.mark.asyncio
    async def test_ann_issues_ef_search_set_config(self) -> None:
        """The ANN path must widen the HNSW candidate pool via set_config."""
        session = self._make_session()
        repo = ChunkANNRepository(session, ef_search=200)
        await repo.ann_search(embedding=[0.1] * 1024, granularity="chunk", top_k=5, tenant_id=None)

        # The FIRST statement raises hnsw.ef_search for the transaction.
        first_sql = str(session.execute.call_args_list[0][0][0])
        assert "set_config" in first_sql
        assert "hnsw.ef_search" in first_sql
        # The bound value is the configured ef_search.
        params = session.execute.call_args_list[0][0][1]
        assert params["ef"] == "200"

    @pytest.mark.asyncio
    async def test_ann_ef_search_disabled_when_zero(self) -> None:
        """ef_search<=0 must skip the set_config statement (no-op override)."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[result_mock, count_result])

        repo = ChunkANNRepository(session, ef_search=0)
        await repo.ann_search(embedding=[0.1] * 1024, granularity="chunk", top_k=5, tenant_id=None)

        # No set_config statement — first call is the main ANN query.
        assert "set_config" not in str(session.execute.call_args_list[0][0][0])

    @pytest.mark.asyncio
    async def test_ann_chunk_query_selects_source_type(self) -> None:
        """The chunk ANN SELECT must project dsm.source_type (was always null)."""
        session = self._make_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(embedding=[0.1] * 1024, granularity="chunk", top_k=5, tenant_id=None)

        main_sql = TestChunkANNRepositoryTenantFilter._find_sql(session, "chunk_embeddings")
        assert "dsm.source_type" in main_sql


# ── BUG-3 finish: filter-first exact KNN for selective filters ────────────────


class TestChunkANNRepositoryExactWhenFiltered:
    """Regression tests for the filter-first exact-KNN path (feat/fix-bug3-ann-recall).

    Root cause it fixes: raising ``hnsw.ef_search`` cannot surface a ~2%-density
    source (sec_edgar) under a HARD ``source_type`` post-filter — the HNSW
    candidate set is dominated by the 98%-news corpus, so the post-filter drops
    the rare bucket to ~0. When a selective filter is present we FILTER FIRST and
    run an EXACT ``ORDER BY embedding <=> query`` over the small filtered subset
    via a ``MATERIALIZED`` CTE (no HNSW dependence), guaranteeing the true nearest
    filtered rows.
    """

    @staticmethod
    def _make_chunk_row(source_type: str = "sec_edgar", score: float = 0.42) -> MagicMock:
        row = MagicMock()
        row.chunk_id = uuid.uuid4()
        row.doc_id = uuid.uuid4()
        row.section_id = uuid.uuid4()
        row.heading_path = "Item 1A. Risk Factors"
        row.chunk_text_key = "chunks/abc.txt"
        row.document_title = "10-K FY2025"
        row.section_type = "body"
        row.source_type = source_type
        row.score = score
        return row

    def _make_exact_session(self, filtered_count: int, rows: list[MagicMock]) -> AsyncMock:
        """Session whose execute() sequence matches the exact path: [COUNT, exact_query]."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = filtered_count
        rows_result = MagicMock()
        rows_result.all.return_value = rows
        session.execute = AsyncMock(side_effect=[count_result, rows_result])
        return session

    @pytest.mark.asyncio
    async def test_selective_source_filter_uses_exact_materialized_cte(self) -> None:
        """source_types present → filter-first exact CTE, NOT the HNSW post-filter."""
        row = self._make_chunk_row()
        session = self._make_exact_session(filtered_count=1433, rows=[row])
        repo = ChunkANNRepository(session, ef_search=200)

        results, total = await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["sec_edgar"],
            tenant_id=None,
        )

        # Exactly two statements: filtered COUNT, then the exact CTE query.
        assert session.execute.call_count == 2
        exact_sql = str(session.execute.call_args_list[1][0][0])
        # The exact path fences the filtered subset with a MATERIALIZED CTE so the
        # outer ORDER BY distance cannot use the HNSW index.
        assert "MATERIALIZED" in exact_sql
        assert "1 - distance" in exact_sql
        # It must NOT raise hnsw.ef_search — the exact path does not use HNSW.
        assert not any("hnsw.ef_search" in str(c[0][0]) for c in session.execute.call_args_list)
        # The source filter must be present in the filtered subset.
        assert "dsm.source_type = ANY(:source_types)" in exact_sql
        # It returns the filtered source rows, ordered by distance; total = filtered count.
        assert len(results) == 1
        assert results[0]["source_type"] == "sec_edgar"
        assert total == 1433

    @pytest.mark.asyncio
    async def test_exact_path_preserves_public_only_tenant_predicate(self) -> None:
        """Security invariant: exact path with tenant_id=None stays public-only."""
        session = self._make_exact_session(filtered_count=10, rows=[self._make_chunk_row()])
        repo = ChunkANNRepository(session)

        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["sec_edgar"],
            tenant_id=None,
        )

        exact_sql = str(session.execute.call_args_list[1][0][0])
        assert "c.tenant_id IS NULL" in exact_sql
        assert "c.tenant_id = '00000000-0000-0000-0000-000000000000'::uuid" in exact_sql
        # No private-tenant OR leg when unauthenticated.
        assert "CAST(:tenant_id_str AS UUID)" not in exact_sql

    @pytest.mark.asyncio
    async def test_exact_path_authenticated_tenant_adds_or_leg(self) -> None:
        """Authenticated caller: exact path includes public + own-tenant rows."""
        session = self._make_exact_session(filtered_count=10, rows=[self._make_chunk_row()])
        repo = ChunkANNRepository(session)

        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["sec_edgar"],
            tenant_id=str(uuid.uuid4()),
        )

        exact_sql = str(session.execute.call_args_list[1][0][0])
        assert "c.tenant_id IS NULL" in exact_sql
        assert "CAST(:tenant_id_str AS UUID)" in exact_sql

    @pytest.mark.asyncio
    async def test_empty_filtered_set_short_circuits_without_query(self) -> None:
        """filtered COUNT=0 → return early; no exact query, no HNSW fallback."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[count_result])
        repo = ChunkANNRepository(session)

        results, total = await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["nonexistent_source"],
            tenant_id=None,
        )

        assert results == []
        assert total == 0
        assert session.execute.call_count == 1  # only the COUNT

    @pytest.mark.asyncio
    async def test_non_selective_filter_falls_back_to_hnsw(self) -> None:
        """filtered count > exact_max_rows → HNSW ANN path (set_config issued)."""
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5_000  # exceeds the tiny bound below
        ef_result = MagicMock()
        rows_result = MagicMock()
        rows_result.all.return_value = []
        total_result = MagicMock()
        total_result.scalar_one.return_value = 66_800
        # Exact path: [COUNT] → over bound → HNSW path: [set_config, main, COUNT].
        session.execute = AsyncMock(side_effect=[count_result, ef_result, rows_result, total_result])
        repo = ChunkANNRepository(session, ef_search=200, exact_max_rows=1000)

        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["eodhd_news"],
            tenant_id=None,
        )

        all_sql = [str(c[0][0]) for c in session.execute.call_args_list]
        # The HNSW fallback fired: an ef_search set_config is present.
        assert any("hnsw.ef_search" in s for s in all_sql)
        # And no MATERIALIZED exact query ran.
        assert not any("MATERIALIZED" in s for s in all_sql)

    @pytest.mark.asyncio
    async def test_flag_disabled_keeps_hnsw_even_when_filtered(self) -> None:
        """exact_when_filtered=False → HNSW path even with a selective filter."""
        session = AsyncMock()
        ef_result = MagicMock()
        rows_result = MagicMock()
        rows_result.all.return_value = []
        total_result = MagicMock()
        total_result.scalar_one.return_value = 66_800
        session.execute = AsyncMock(side_effect=[ef_result, rows_result, total_result])
        repo = ChunkANNRepository(session, ef_search=200, exact_when_filtered=False)

        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=["sec_edgar"],
            tenant_id=None,
        )

        all_sql = [str(c[0][0]) for c in session.execute.call_args_list]
        assert any("hnsw.ef_search" in s for s in all_sql)
        assert not any("MATERIALIZED" in s for s in all_sql)

    @pytest.mark.asyncio
    async def test_unfiltered_query_keeps_hnsw_fast_path(self) -> None:
        """No filter → unchanged HNSW ANN fast path (98% case), no exact CTE."""
        session = AsyncMock()
        ef_result = MagicMock()
        rows_result = MagicMock()
        rows_result.all.return_value = []
        total_result = MagicMock()
        total_result.scalar_one.return_value = 66_800
        session.execute = AsyncMock(side_effect=[ef_result, rows_result, total_result])
        repo = ChunkANNRepository(session, ef_search=200)

        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            top_k=5,
            source_types=None,
            tenant_id=None,
        )

        all_sql = [str(c[0][0]) for c in session.execute.call_args_list]
        assert any("hnsw.ef_search" in s for s in all_sql)
        assert not any("MATERIALIZED" in s for s in all_sql)

    @pytest.mark.asyncio
    async def test_section_selective_filter_uses_exact_path(self) -> None:
        """Section ANN also filter-first exact-scans a selective source filter."""
        section_row = MagicMock()
        section_row.chunk_id = uuid.uuid4()
        section_row.doc_id = uuid.uuid4()
        section_row.section_id = section_row.chunk_id
        section_row.heading_path = "Risk Factors"
        section_row.section_type = "body"
        section_row.document_title = "10-K"
        section_row.score = 0.5
        session = self._make_exact_session(filtered_count=200, rows=[section_row])
        repo = ChunkANNRepository(session)

        results, total = await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="section",
            top_k=5,
            source_types=["sec_edgar"],
            tenant_id=None,
        )

        exact_sql = str(session.execute.call_args_list[1][0][0])
        assert "MATERIALIZED" in exact_sql
        assert "section_embeddings" in exact_sql
        assert "s.tenant_id IS NULL" in exact_sql
        assert not any("hnsw.ef_search" in str(c[0][0]) for c in session.execute.call_args_list)
        assert len(results) == 1
        assert results[0]["granularity"] == "section"
        assert total == 200


# ── T-C-1-05: API schema accepts tenant_id ────────────────────────────────────


class TestChunkSearchRequestSchemaTenantId:
    """nlp-pipeline ChunkSearchRequest Pydantic schema must accept tenant_id."""

    def test_schema_defaults_tenant_id_to_none(self) -> None:
        """Callers that do not set tenant_id get None (public-only default)."""
        from nlp_pipeline.api.schemas import ChunkSearchRequest

        req = ChunkSearchRequest(query_text="apple earnings")
        assert req.tenant_id is None

    def test_schema_accepts_tenant_id_string(self) -> None:
        """tenant_id can be set as a raw UUID string."""
        from nlp_pipeline.api.schemas import ChunkSearchRequest

        tenant = str(uuid.uuid4())
        req = ChunkSearchRequest(query_text="apple earnings", tenant_id=tenant)
        assert req.tenant_id == tenant

    def test_schema_accepts_null_tenant_id(self) -> None:
        """Explicitly passing tenant_id=None is identical to the default."""
        from nlp_pipeline.api.schemas import ChunkSearchRequest

        req = ChunkSearchRequest(query_text="apple earnings", tenant_id=None)
        assert req.tenant_id is None
