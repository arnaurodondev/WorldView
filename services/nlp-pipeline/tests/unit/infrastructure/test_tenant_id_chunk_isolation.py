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
        result_mock = MagicMock()
        result_mock.all.return_value = []
        # scalar_one() for the COUNT query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[result_mock, count_result])
        return session

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

        # Extract the SQL text from the first execute call
        call_args = session.execute.call_args_list[0]
        sql_statement = call_args[0][0]
        sql_text = str(sql_statement)

        # The WHERE clause MUST contain the public-only filter
        assert "c.tenant_id IS NULL" in sql_text

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

        call_args = session.execute.call_args_list[0]
        sql_statement = call_args[0][0]
        sql_text = str(sql_statement)

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


# ── R40 (PLAN-0098 follow-up to Phase-D §2.3): PUBLIC_TENANT_ID sentinel ──────


# Canonical sentinel literal — must match `common.ids.PUBLIC_TENANT_ID`
# (all-zero UUID, see BP-575). Hardcoded here so the test pins the literal
# that ships in production SQL, independent of any later constant rename.
_PUBLIC_TENANT_LITERAL = "'00000000-0000-0000-0000-000000000000'::uuid"


def _make_dual_execute_session() -> AsyncMock:
    """Build a session mock that yields (rows-result, count-result) in order.

    Both `_search_chunks` and `_search_sections` issue exactly two execute
    calls: the SELECT and a follow-up COUNT(*). lexical_search also issues two
    (SELECT + COUNT) but both reuse the same `text(...)` shape. Factored as a
    helper so each R40 test below stays a 4-liner and the assertion logic is
    DRY across the three SQL surfaces.
    """
    session = AsyncMock()
    rows_result = MagicMock()
    rows_result.all.return_value = []
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    session.execute = AsyncMock(side_effect=[rows_result, count_result])
    return session


def _assert_three_or_legs(sql_text: str, column_alias: str, bind_name: str = "tenant_id_str") -> None:
    """Assert all three R40 OR-legs are present in a single boolean grouping.

    column_alias = "c" for chunks-side, "s" for sections-side.
    Pins (1) NULL-leg, (2) bound-tenant leg, (3) PUBLIC_TENANT_ID literal leg.
    """
    assert f"{column_alias}.tenant_id IS NULL" in sql_text, f"missing NULL-tenant OR-leg on {column_alias}"
    assert (
        f"{column_alias}.tenant_id = CAST(:{bind_name} AS UUID)" in sql_text
    ), f"missing real-tenant OR-leg on {column_alias}"
    assert (
        f"{column_alias}.tenant_id = {_PUBLIC_TENANT_LITERAL}" in sql_text
    ), f"missing PUBLIC_TENANT_ID OR-leg on {column_alias} (R40 / Phase-D §2.3)"


class TestChunkANNRepositoryPublicTenantSentinel:
    """R40 (Phase-D §2.3 P1 follow-up): all three SQL surfaces in
    `chunk_search.py` must admit the PUBLIC_TENANT_ID sentinel row class
    when a real tenant_id is supplied. Without the third OR-leg, every
    PLAN-0096 W4 fallback row (BP-575) would be invisible to authenticated
    tenants — exactly the inverse-visibility bug R40 codifies.
    """

    @pytest.mark.asyncio
    async def test_ann_search_chunks_admits_public_tenant_sentinel(self) -> None:
        """`_search_chunks` SQL must include the sentinel OR-leg on `c`."""
        session = _make_dual_execute_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="chunk",
            tenant_id=str(uuid.uuid4()),
        )
        sql_text = str(session.execute.call_args_list[0][0][0])
        _assert_three_or_legs(sql_text, column_alias="c")

    @pytest.mark.asyncio
    async def test_ann_search_sections_admits_public_tenant_sentinel(self) -> None:
        """`_search_sections` SQL (SELECT and COUNT) must include the sentinel."""
        session = _make_dual_execute_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(
            embedding=[0.1] * 1024,
            granularity="section",
            tenant_id=str(uuid.uuid4()),
        )
        # SELECT statement
        select_sql = str(session.execute.call_args_list[0][0][0])
        _assert_three_or_legs(select_sql, column_alias="s")
        # COUNT statement — independent string, must also carry the sentinel
        # so totals stay consistent with the SELECT visibility set.
        count_sql = str(session.execute.call_args_list[1][0][0])
        _assert_three_or_legs(count_sql, column_alias="s")

    @pytest.mark.asyncio
    async def test_lexical_search_admits_public_tenant_sentinel(self) -> None:
        """`lexical_search` SQL must include the sentinel OR-leg on `c`."""
        session = _make_dual_execute_session()
        repo = ChunkANNRepository(session)
        await repo.lexical_search(
            "apple revenue",
            tenant_id=str(uuid.uuid4()),
        )
        # Both SELECT and COUNT share the same `tenant_filter_sql` fragment;
        # asserting on the SELECT statement is sufficient because the COUNT
        # interpolates the same f-string variable in `chunk_search.py`.
        sql_text = str(session.execute.call_args_list[0][0][0])
        _assert_three_or_legs(sql_text, column_alias="c")

    @pytest.mark.asyncio
    async def test_null_tenant_does_not_widen_to_public_sentinel(self) -> None:
        """Defence-in-depth: anonymous (tenant_id=None) callers MUST NOT have
        the PUBLIC_TENANT_ID literal injected into their WHERE clause. The
        else-branch must stay `c.tenant_id IS NULL` only — widening it would
        change semantics for the public/anonymous surface (out of scope here).
        """
        session = _make_dual_execute_session()
        repo = ChunkANNRepository(session)
        await repo.ann_search(embedding=[0.1] * 1024, granularity="chunk", tenant_id=None)
        sql_text = str(session.execute.call_args_list[0][0][0])
        # The hardcoded sentinel literal must NOT appear in the public-only branch
        assert _PUBLIC_TENANT_LITERAL not in sql_text


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
