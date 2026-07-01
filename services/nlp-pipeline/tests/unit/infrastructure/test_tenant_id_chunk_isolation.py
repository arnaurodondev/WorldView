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
