"""Integration tests for AsyncpgDocumentSearchRepository + SearchDocumentsUseCase (PLAN-0064 W6 T-W6-3-02).

Tests the full FTS path against a real PostgreSQL instance:
  - chunks.tsv_english GIN index (ix_chunks_tsv_english_gin from alembic 0017)
  - entity_mentions table for facet aggregation
  - document_source_metadata table for source_type + published_at filters
  - AsyncpgDocumentSearchRepository for the SQL queries
  - SearchDocumentsUseCase for the orchestration (S5/S7 HTTP clients are mocked)

DB requirement
--------------
Requires a live Postgres reachable at:
  NLP_PIPELINE_E2E_DATABASE_URL  (default postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db)

When the host is unreachable the entire module is skipped — keeping the suite green
on machines that don't have local infra.

Schema bootstrap
----------------
Mirrors the approach in test_chunk_lexical_search.py — Base.metadata.create_all adds
the core ORM tables, then we append the GENERATED tsv_english column + GIN index via
ALTER TABLE (since GENERATED columns are not supported by the ORM declarative layer).

S5/S7 HTTP clients are mocked with AsyncMock so that the integration tests run without
spinning up S5 (content-store) and S7 (knowledge-graph).  The _S5BatchClient mock returns
a title-only document dict; the _S7BatchClient mock returns a name-only entity dict.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.api.schemas import SearchDocumentsRequest
from nlp_pipeline.application.use_cases.search_documents import (
    SearchDocumentsUseCase,
    _S5BatchClient,
    _S7BatchClient,
)
from nlp_pipeline.infrastructure.nlp_db.models import Base
from nlp_pipeline.infrastructure.nlp_db.repositories.document_search import AsyncpgDocumentSearchRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ── DB availability probe ─────────────────────────────────────────────────────

_E2E_DB_URL = os.getenv(
    "NLP_PIPELINE_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db",
)
_DB_AVAILABLE: bool | None = None
_TABLES_INITIALISED = False


def _is_db_available() -> bool:
    """TCP probe — caches result for the whole pytest session."""
    global _DB_AVAILABLE
    if _DB_AVAILABLE is not None:
        return _DB_AVAILABLE
    try:
        parsed = urllib.parse.urlparse(_E2E_DB_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        sock.close()
        _DB_AVAILABLE = True
    except OSError:
        _DB_AVAILABLE = False
    return _DB_AVAILABLE


# Skip the entire module when no DB is reachable.
pytestmark = pytest.mark.skipif(
    not _is_db_available(),
    reason=f"PostgreSQL not reachable at {_E2E_DB_URL}",
)


def _bootstrap_in_thread(db_url: str) -> None:
    """Apply create_all + GENERATED tsv_english column + GIN index.

    Identical to the approach in test_chunk_lexical_search.py — drops and
    recreates the GENERATED columns to avoid stale GENERATED expressions.
    The base ORM tables (sections, chunks, entity_mentions, etc.) are created
    via Base.metadata.create_all.  All DDL is idempotent (IF NOT EXISTS / IF EXISTS).
    """

    async def _apply(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            # Create core ORM tables (does NOT add GENERATED columns).
            await conn.run_sync(Base.metadata.create_all)

            # Add searchable text columns that production uses.
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS title_denorm TEXT"))
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_heading_denorm TEXT"))
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_text TEXT"))

            # Drop old GENERATED columns + indexes before recreating to avoid stale expression trap.
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_tsv_simple_gin"))
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_tsv_english_gin"))
            await conn.execute(text("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_simple"))
            await conn.execute(text("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_english"))

            # Re-create GENERATED tsv_english (mirrors alembic 0017).
            await conn.execute(
                text(
                    """
                    ALTER TABLE chunks
                    ADD COLUMN IF NOT EXISTS tsv_english tsvector
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(title_denorm, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(section_heading_denorm, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(chunk_text, '')), 'D')
                    ) STORED
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE chunks
                    ADD COLUMN IF NOT EXISTS tsv_simple tsvector
                    GENERATED ALWAYS AS (
                        to_tsvector('simple', coalesce(chunk_text, ''))
                    ) STORED
                    """
                )
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv_english_gin ON chunks USING GIN (tsv_english)")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv_simple_gin ON chunks USING GIN (tsv_simple)")
            )
        await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        engine = create_async_engine(db_url, echo=False)
        loop.run_until_complete(_apply(engine))
    finally:
        loop.close()


# ── Session-scoped engine + session factory ───────────────────────────────────


@pytest.fixture(scope="session")
def fts_engine() -> AsyncEngine:
    """Session-scoped async engine with the FTS schema bootstrapped."""
    engine = create_async_engine(_E2E_DB_URL, echo=False, future=True, poolclass=NullPool)
    global _TABLES_INITIALISED
    if not _TABLES_INITIALISED:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_bootstrap_in_thread, _E2E_DB_URL).result(timeout=30)
            _TABLES_INITIALISED = True
        except Exception as exc:
            pytest.skip(f"DB bootstrap failed: {exc}")
    return engine


@pytest.fixture(scope="session")
def fts_session_factory(fts_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(fts_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _clean_tables(fts_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate relevant tables before and after each test for isolation."""

    async def _truncate() -> None:
        async with fts_engine.begin() as conn:
            # CASCADE handles FK-dependent rows in entity_mentions, sections.
            await conn.execute(text("TRUNCATE entity_mentions CASCADE"))
            await conn.execute(text("TRUNCATE chunks CASCADE"))
            await conn.execute(text("TRUNCATE sections CASCADE"))
            await conn.execute(text("TRUNCATE document_source_metadata CASCADE"))

    await _truncate()
    yield
    await _truncate()


@pytest.fixture
async def fts_session(fts_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with fts_session_factory() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_doc(
    session: AsyncSession,
    *,
    chunk_text: str,
    title_denorm: str | None = None,
    section_heading_denorm: str | None = None,
    source_type: str = "news",
    published_at: datetime | None = None,
    doc_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert one document_source_metadata + section + chunk row.

    Returns (doc_id, section_id, chunk_id).

    WHY tsv_english is NOT explicitly inserted: it is a GENERATED ALWAYS AS column —
    Postgres computes it from title_denorm + section_heading_denorm + chunk_text on
    every INSERT/UPDATE.  We only need to supply the source columns.
    """
    if published_at is None:
        published_at = datetime.now(UTC)
    if doc_id is None:
        doc_id = uuid.uuid4()
    section_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO document_source_metadata (doc_id, source_type, published_at, created_at)
            VALUES (:doc_id, :source_type, :published_at, NOW())
            """
        ).bindparams(doc_id=doc_id, source_type=source_type, published_at=published_at)
    )
    await session.execute(
        text(
            """
            INSERT INTO sections (section_id, doc_id, section_index, section_type, char_start, char_end)
            VALUES (:section_id, :doc_id, 0, 'body', 0, 500)
            """
        ).bindparams(section_id=section_id, doc_id=doc_id)
    )
    await session.execute(
        text(
            """
            INSERT INTO chunks (
                chunk_id, doc_id, section_id, chunk_index,
                char_start, char_end, token_count,
                heading_path, chunk_text_key, chunk_text,
                title_denorm, section_heading_denorm
            ) VALUES (
                :chunk_id, :doc_id, :section_id, 0,
                0, 500, 100,
                :heading, :ctext_key, :chunk_text,
                :title_denorm, :section_heading_denorm
            )
            """
        ).bindparams(
            chunk_id=chunk_id,
            doc_id=doc_id,
            section_id=section_id,
            heading=section_heading_denorm,
            ctext_key=f"nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt",
            chunk_text=chunk_text,
            title_denorm=title_denorm,
            section_heading_denorm=section_heading_denorm,
        )
    )
    await session.commit()
    return doc_id, section_id, chunk_id


async def _seed_entity_mention(
    session: AsyncSession,
    *,
    doc_id: uuid.UUID,
    section_id: uuid.UUID,
    resolved_entity_id: uuid.UUID,
    mention_class: str = "organization",
) -> uuid.UUID:
    """Insert one entity_mention row referencing the given doc and entity."""
    mention_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO entity_mentions (
                mention_id, doc_id, section_id,
                mention_text, mention_class, confidence,
                char_start, char_end, resolved_entity_id,
                resolution_outcome, created_at
            ) VALUES (
                :mention_id, :doc_id, :section_id,
                'TestCorp', :mention_class, 0.9,
                0, 8, :resolved_entity_id,
                'resolved', NOW()
            )
            """
        ).bindparams(
            mention_id=mention_id,
            doc_id=doc_id,
            section_id=section_id,
            mention_class=mention_class,
            resolved_entity_id=resolved_entity_id,
        )
    )
    await session.commit()
    return mention_id


def _make_request(**kwargs) -> SearchDocumentsRequest:  # type: ignore[no-untyped-def]
    """Build a SearchDocumentsRequest with sensible defaults for testing."""
    defaults: dict = {
        "q": "apple",
        "entity_ids": [],
        "scope": "all",
        "source_type": "all",
        "date_from": None,
        "date_to": None,
        "date_preset": None,
        "page": 1,
        "page_size": 25,
    }
    defaults.update(kwargs)
    return SearchDocumentsRequest(**defaults)


def _make_use_case(session: AsyncSession) -> SearchDocumentsUseCase:
    """Build a SearchDocumentsUseCase with mocked S5/S7 HTTP clients.

    The mock clients always return empty dicts — the use case gracefully falls back
    to title=None and name=str(entity_id), which is correct for testing DB queries.
    """
    repo = AsyncpgDocumentSearchRepository(session)
    s5_mock = AsyncMock(spec=_S5BatchClient)
    s5_mock.batch_documents = AsyncMock(return_value={})
    s7_mock = AsyncMock(spec=_S7BatchClient)
    s7_mock.batch_get_entities = AsyncMock(return_value={})
    return SearchDocumentsUseCase(repo=repo, s5_client=s5_mock, s7_client=s7_mock)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_search_finds_seeded_article_by_keyword(fts_session: AsyncSession) -> None:
    """Seed 1 chunk containing "Apple announced record revenue", search "apple" → 1 hit.

    This is the fundamental smoke test: FTS tokenises the chunk_text via tsv_english
    and the websearch_to_tsquery('english', 'apple') matches 'Apple' (stemmed to 'appl').
    """
    doc_id, _, _ = await _seed_doc(
        fts_session,
        chunk_text="Apple announced record revenue this quarter.",
        title_denorm="Apple Earnings",
    )

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="apple"))

    assert output.total >= 1
    doc_ids = {h.doc_id for h in output.results}
    assert doc_id in doc_ids


@pytest.mark.integration
async def test_search_filters_by_source_type(fts_session: AsyncSession) -> None:
    """Seed 1 news + 1 sec_edgar chunk; query source_type=sec_edgar → 1 hit.

    The filtered CTE in the repository applies `CAST(:source_type AS text) IS NULL OR
    dsm.source_type = ...` which must correctly exclude the news chunk when filtering.
    """
    await _seed_doc(fts_session, chunk_text="Revenue beat expectations this quarter", source_type="news")
    edgar_doc_id, _, _ = await _seed_doc(
        fts_session,
        chunk_text="Revenue beat expectations this quarter",
        source_type="sec_edgar",
    )

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="revenue beat", source_type="sec_edgar"))

    assert output.total == 1
    assert output.results[0].doc_id == edgar_doc_id
    assert output.results[0].source_type == "sec_edgar"


@pytest.mark.integration
async def test_search_filters_by_entity_id(fts_session: AsyncSession) -> None:
    """Seed 2 docs; only one has a resolved_entity_id=APPLE_UUID → filter returns 1.

    The entity_ids filter uses an IN subquery over entity_mentions.  This test
    confirms the JOIN logic correctly narrows the result set.
    """
    apple_entity_id = uuid.uuid4()
    other_entity_id = uuid.uuid4()

    apple_doc, apple_section, _ = await _seed_doc(
        fts_session,
        chunk_text="Apple quarterly earnings beat analyst expectations by ten percent",
    )
    other_doc, other_section, _ = await _seed_doc(
        fts_session,
        chunk_text="Apple quarterly earnings beat analyst expectations by ten percent",
    )

    # Only apple_doc has the Apple entity mention.
    await _seed_entity_mention(
        fts_session,
        doc_id=apple_doc,
        section_id=apple_section,
        resolved_entity_id=apple_entity_id,
    )
    await _seed_entity_mention(
        fts_session,
        doc_id=other_doc,
        section_id=other_section,
        resolved_entity_id=other_entity_id,
    )

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="apple quarterly", entity_ids=[apple_entity_id]))

    assert output.total == 1
    assert output.results[0].doc_id == apple_doc


@pytest.mark.integration
async def test_search_filters_by_date_range(fts_session: AsyncSession) -> None:
    """Seed 3 docs at different dates; date_from/date_to filter returns only the match.

    Documents published before date_from or after date_to must be excluded.
    BP-180: CAST(:date_from AS timestamptz) IS NULL guard handles the None case.
    """
    now = datetime.now(UTC)
    old_date = now - timedelta(days=60)
    mid_date = now - timedelta(days=15)
    new_date = now - timedelta(days=2)

    common_text = "Revenue guidance updated for the coming fiscal year"
    await _seed_doc(fts_session, chunk_text=common_text, published_at=old_date)
    mid_doc, _, _ = await _seed_doc(fts_session, chunk_text=common_text, published_at=mid_date)
    await _seed_doc(fts_session, chunk_text=common_text, published_at=new_date)

    # Filter to only the 30-7 day window: old and new docs are excluded.
    date_from = now - timedelta(days=30)
    date_to = now - timedelta(days=7)

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="revenue guidance", date_from=date_from, date_to=date_to))

    assert output.total == 1
    assert output.results[0].doc_id == mid_doc


@pytest.mark.integration
async def test_search_pagination_no_overlap(fts_session: AsyncSession) -> None:
    """Seed 30 matching chunks; page=1 (25) + page=2 (5) — no doc_ids repeat.

    The LIMIT/OFFSET pagination in the repository must not produce duplicates
    across pages.  This test seeds 30 distinct docs with identical chunk text
    so all 30 rank equally and pagination is stable.
    """
    # Seed 30 docs — same text so all rank equally.
    for _ in range(30):
        await _seed_doc(fts_session, chunk_text="Tesla quarterly delivery data shows strong growth momentum")

    use_case = _make_use_case(fts_session)

    page1 = await use_case.execute(_make_request(q="Tesla quarterly", page=1, page_size=25))
    page2 = await use_case.execute(_make_request(q="Tesla quarterly", page=2, page_size=25))

    assert page1.total == 30
    assert len(page1.results) == 25
    assert len(page2.results) == 5

    # No doc_id should appear on both pages.
    page1_ids = {h.doc_id for h in page1.results}
    page2_ids = {h.doc_id for h in page2.results}
    assert page1_ids.isdisjoint(page2_ids), "Pagination returned overlapping doc_ids"


@pytest.mark.integration
async def test_search_facets_capped_at_25(fts_session: AsyncSession) -> None:
    """Seed 30 distinct entity_ids in entity_mentions → facets list len <= 25.

    The _FACETS_SQL query has a LIMIT 25 clause — this test confirms the cap is
    enforced and the response never returns more than 25 entity facets.
    """
    doc_id, section_id, _ = await _seed_doc(
        fts_session,
        chunk_text="Microsoft Azure cloud revenue surpassed analysts' quarterly forecast",
    )

    # Seed 30 distinct entity_ids for this doc.
    for _ in range(30):
        await _seed_entity_mention(
            fts_session,
            doc_id=doc_id,
            section_id=section_id,
            resolved_entity_id=uuid.uuid4(),
        )

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="Microsoft Azure"))

    assert output.total >= 1
    assert len(output.facets) <= 25, f"Expected ≤25 facets but got {len(output.facets)}"


@pytest.mark.integration
async def test_search_empty_result_for_nonexistent_term(fts_session: AsyncSession) -> None:
    """Search for a nonsense term returns total=0, empty results and facets.

    Verifies the empty-result fast-path in SearchDocumentsUseCase — when total=0,
    the S5/S7 batch calls are skipped and the output has empty lists.
    """
    await _seed_doc(fts_session, chunk_text="Apple reported strong revenue this quarter")

    use_case = _make_use_case(fts_session)
    output = await use_case.execute(_make_request(q="xyzzy42nonexistenttoken"))

    assert output.total == 0
    assert output.results == []
    assert output.facets == []


@pytest.mark.integration
async def test_search_special_chars_no_500(fts_session: AsyncSession) -> None:
    """Queries with special characters (C# .NET, &, |) do not raise an exception.

    websearch_to_tsquery handles most special characters gracefully — this test
    confirms that no exception escapes the repository for common special-char inputs.
    """
    await _seed_doc(fts_session, chunk_text="Microsoft announces C# language updates for dot net platform")

    use_case = _make_use_case(fts_session)

    # These patterns exercise websearch_to_tsquery's special-char handling.
    for q in ["C# .NET", "revenue & income | sales", "profit-loss estimate"]:
        output = await use_case.execute(_make_request(q=q))
        # We only require no exception — result count may be 0 (tokenisation varies).
        assert isinstance(output.total, int), f"Expected int total for q={q!r}"


@pytest.mark.integration
async def test_search_explain_uses_gin_index(fts_session: AsyncSession) -> None:
    """EXPLAIN output contains 'ix_chunks_tsv_english_gin' (GIN Bitmap Index Scan).

    The repository must use the GIN FTS index — a sequential scan would be
    unacceptably slow at scale.  We force the planner to use the index by
    running ``SET enable_seqscan = off`` for the session before EXPLAIN.

    WHY SET enable_seqscan = off: with a tiny test table the planner's cost model
    correctly prefers a Seq Scan (cheaper for < ~100 rows).  The goal of this test
    is to verify the GIN index EXISTS and is used when the planner would want it —
    not to check the planner's cost decision on a micro-table.  Disabling seq scan
    forces the planner to choose the GIN index, which is the production-relevant
    access path at scale.
    """
    await _seed_doc(fts_session, chunk_text="Apple quarterly results beat expectations")

    # Disable seq scan for this session so the planner is forced to use the GIN index.
    # This is a session-level setting that does not affect other connections.
    await fts_session.execute(text("SET enable_seqscan = off"))

    explain_sql = text(
        """
        EXPLAIN (FORMAT TEXT)
        SELECT c.doc_id
        FROM chunks c
        WHERE c.tsv_english @@ websearch_to_tsquery('english', :q)
        """
    )

    result = await fts_session.execute(explain_sql.bindparams(q="apple quarterly"))
    plan_lines = [row[0] for row in result.all()]

    # Re-enable seq scan so this setting does not leak to other uses of the session.
    await fts_session.execute(text("SET enable_seqscan = on"))

    plan_text = "\n".join(plan_lines)
    assert "ix_chunks_tsv_english_gin" in plan_text, f"Expected GIN index in query plan but got:\n{plan_text}"
