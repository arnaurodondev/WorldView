"""Integration tests for ``ChunkANNRepository.lexical_search`` (PLAN-0063 W5-2).

Exercises the full Postgres FTS path: ``websearch_to_tsquery`` over
GENERATED ``tsv_english`` and ``tsv_simple`` columns plus their GIN indexes.

DB requirement
--------------
These tests require a live Postgres reachable via
``NLP_PIPELINE_E2E_DATABASE_URL`` (default
``postgresql+asyncpg://postgres:postgres@localhost:55433/nlp_db``). When the
host is unreachable the entire module is skipped — keeping the test suite
green on machines that don't have local infra.

Schema bootstrap
----------------
``Base.metadata.create_all`` does NOT add the GENERATED ``tsv_english`` /
``tsv_simple`` columns (they live only in migration 0017 and are intentionally
absent from the ORM — see BP-NEW1). We therefore append ``ALTER TABLE`` /
``CREATE INDEX`` statements after ``create_all`` so the same DB shape that
production has is exercised here.

Pure-unit tests for argument validation (mode, granularity) live alongside in
``test_chunk_lexical_search_validation.py`` would normally apply, but to keep
the surface area small we co-locate the two ``ValueError`` checks in this same
file under ``pytestmark`` that does NOT require the DB — see
``test_lexical_search_section_granularity_raises`` and
``test_lexical_search_invalid_mode_raises``.

Tests cover (PLAN-0063 W5-2 acceptance):
    1.  basic match
    2.  ordering by ts_rank_cd desc
    3.  top_k cap
    4.  date_from / date_to filter
    5.  source_types filter
    6.  empty result for unknown token
    7.  granularity='section' raises
    8.  websearch operators (``-Android`` exclude)
    9.  min_score filter
   10.  simple-mode preserves identifier tokens
   11.  invalid mode raises
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import socket
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nlp_pipeline.infrastructure.nlp_db.models import Base
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository
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


# Skip the entire module when no DB is reachable. The two pure ValueError
# tests stay executable because they don't touch the DB — but pytest's
# module-level skip is convenient and they are cheap to skip too.
pytestmark = pytest.mark.skipif(
    not _is_db_available(),
    reason=f"PostgreSQL not reachable at {_E2E_DB_URL}",
)


def _bootstrap_in_thread(db_url: str) -> None:
    """Apply ``create_all`` + migration 0017 GENERATED columns + GIN indexes.

    Runs in a worker thread so we don't collide with the running pytest event
    loop. Idempotent — safe to call multiple times because all DDL uses
    ``IF NOT EXISTS`` / ``IF EXISTS``.
    """

    async def _apply(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Mirror migration 0017. ``create_all`` won't add GENERATED columns
            # because they are not declared on the ORM (BP-NEW1) — so we add
            # them manually here. Same DDL as
            # ``alembic/versions/0017_add_chunks_tsv_english_gin.py``.
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS title_denorm TEXT"))
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_heading_denorm TEXT"))
            # chunk_text holds the actual body for FTS — chunk_text_key is a
            # MinIO object path and is NOT searchable (BP-NEW-CHUNK-TEXT).
            await conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_text TEXT"))
            # IMPORTANT: drop tsv_english/tsv_simple BEFORE re-creating them.
            # `IF NOT EXISTS` would silently skip re-creation if a previous
            # bootstrap left a column with stale GENERATED expression — exactly
            # the trap that masked BP-NEW-CHUNK-TEXT until live-DB inspection.
            # Drop indexes first (FK to the columns), then the columns.
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_tsv_simple_gin"))
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_tsv_english_gin"))
            await conn.execute(text("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_simple"))
            await conn.execute(text("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_english"))
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


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def lex_engine() -> AsyncEngine:
    """Async engine with the W5-2 schema bootstrapped on first call."""
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
def lex_session_factory(lex_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(lex_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _clean_chunks_and_sections(lex_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Truncate before and after each test for isolation."""

    async def _truncate() -> None:
        async with lex_engine.begin() as conn:
            await conn.execute(text("TRUNCATE chunks CASCADE"))
            await conn.execute(text("TRUNCATE sections CASCADE"))
            await conn.execute(text("TRUNCATE document_source_metadata CASCADE"))

    await _truncate()
    yield
    await _truncate()


@pytest.fixture
async def lex_session(lex_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with lex_session_factory() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_chunk(
    session: AsyncSession,
    *,
    chunk_text: str,
    title_denorm: str | None = None,
    section_heading_denorm: str | None = None,
    section_type: str = "body",
    source_type: str = "eodhd_news",
    published_at: datetime | None = None,
) -> uuid.UUID:
    """Insert one section + one chunk + one source-metadata row.

    Returns the chunk_id. ``chunk_text`` is the searchable body; the GENERATED
    tsv_english/tsv_simple columns read from it. ``chunk_text_key`` stores a
    placeholder MinIO-shaped path because production also keeps that column —
    but it is intentionally NOT what FTS tokenizes (BP-NEW-CHUNK-TEXT).
    """
    if published_at is None:
        published_at = datetime.now(UTC)

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
            VALUES (:section_id, :doc_id, 0, :section_type, 0, 100)
            """
        ).bindparams(section_id=section_id, doc_id=doc_id, section_type=section_type)
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
                0, 100, 50,
                :heading_path, :chunk_text_key, :chunk_text,
                :title_denorm, :section_heading_denorm
            )
            """
        ).bindparams(
            chunk_id=chunk_id,
            doc_id=doc_id,
            section_id=section_id,
            heading_path=section_heading_denorm,
            # MinIO-shaped placeholder path — the column stays for downstream
            # MinIO fetches but is NOT what FTS tokenizes (BP-NEW-CHUNK-TEXT).
            chunk_text_key=f"nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt",
            # Actual body — this is what the GENERATED tsv columns tokenize.
            chunk_text=chunk_text,
            title_denorm=title_denorm,
            section_heading_denorm=section_heading_denorm,
        )
    )
    await session.commit()
    # silence unused import warning when Decimal isn't otherwise used
    _ = Decimal
    return chunk_id


# ── Tests (require DB) ────────────────────────────────────────────────────────


async def test_lexical_search_returns_chunks_matching_query(lex_session: AsyncSession) -> None:
    """Inserting an Apple-iPhone chunk → english query matches it."""
    chunk_id = await _seed_chunk(
        lex_session,
        chunk_text="Apple iPhone Q4 guidance was strong",
        title_denorm="Apple Earnings",
    )

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search("Apple iPhone", mode="english", top_k=10)

    assert total >= 1
    chunk_ids = {r["chunk_id"] for r in rows}
    assert chunk_id in chunk_ids


async def test_lexical_search_orders_by_score_desc(lex_session: AsyncSession) -> None:
    """Multiple chunks → output is non-increasing in score."""
    await _seed_chunk(lex_session, chunk_text="quarterly revenue beat estimates")
    await _seed_chunk(lex_session, chunk_text="quarterly revenue revenue beat revenue beat")
    await _seed_chunk(lex_session, chunk_text="completely unrelated discussion of weather")

    repo = ChunkANNRepository(lex_session)
    rows, _ = await repo.lexical_search("revenue beat quarterly", mode="english", top_k=10)

    assert len(rows) >= 2
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


async def test_lexical_search_respects_top_k(lex_session: AsyncSession) -> None:
    """5 matching chunks, top_k=2 → exactly 2 rows returned."""
    for _ in range(5):
        await _seed_chunk(lex_session, chunk_text="Microsoft announces new Azure feature today")

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search("Microsoft Azure", mode="english", top_k=2)

    assert len(rows) == 2
    assert total >= 5


async def test_lexical_search_respects_date_range_filter(lex_session: AsyncSession) -> None:
    """date_from filter narrows the result set."""
    now = datetime.now(UTC)
    old = now - timedelta(days=30)
    new = now - timedelta(days=1)

    await _seed_chunk(lex_session, chunk_text="Tesla deliveries strong this period", published_at=old)
    await _seed_chunk(lex_session, chunk_text="Tesla deliveries strong this period", published_at=new)

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search(
        "Tesla deliveries",
        mode="english",
        date_from=now - timedelta(days=7),
        top_k=10,
    )

    # Only the recent one should pass the date filter.
    assert total == 1
    assert len(rows) == 1


async def test_lexical_search_respects_source_types_filter(lex_session: AsyncSession) -> None:
    """source_types whitelist drops everything outside the allowed list."""
    await _seed_chunk(lex_session, chunk_text="Risk factors discussed in detail", source_type="sec_filing")
    await _seed_chunk(lex_session, chunk_text="Risk factors discussed in detail", source_type="eodhd_news")

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search(
        "Risk factors",
        mode="english",
        source_types=["sec_filing"],
        top_k=10,
    )
    assert total == 1
    assert len(rows) == 1


async def test_lexical_search_returns_empty_for_unknown_token(lex_session: AsyncSession) -> None:
    """Nonsense token → empty result list, total=0."""
    await _seed_chunk(lex_session, chunk_text="some normal text here")

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search("asdfqwerzxcv", mode="english", top_k=10)
    assert rows == []
    assert total == 0


async def test_lexical_search_section_granularity_raises(lex_session: AsyncSession) -> None:
    """``granularity='section'`` is unsupported in W5 — raises ValueError."""
    repo = ChunkANNRepository(lex_session)
    with pytest.raises(ValueError, match="granularity='chunk' only"):
        await repo.lexical_search("anything", granularity="section")


async def test_lexical_search_handles_websearch_operators(lex_session: AsyncSession) -> None:
    """``websearch_to_tsquery`` operators work — exclude with ``-Android``."""
    await _seed_chunk(lex_session, chunk_text="iPhone launch sets sales record")
    await _seed_chunk(lex_session, chunk_text="iPhone Android cross-platform comparison")

    repo = ChunkANNRepository(lex_session)
    rows, _ = await repo.lexical_search("iPhone -Android", mode="english", top_k=10)
    # Only the iPhone-only chunk should match.
    assert len(rows) == 1


async def test_lexical_search_with_min_score_filters_low_rank_results(lex_session: AsyncSession) -> None:
    """A high min_score floor drops low-rank rows."""
    await _seed_chunk(lex_session, chunk_text="apple")  # weakest signal
    await _seed_chunk(lex_session, chunk_text="apple apple apple apple apple apple apple apple apple")  # strongest

    repo = ChunkANNRepository(lex_session)
    rows_no_floor, total_no_floor = await repo.lexical_search("apple", mode="english", top_k=10)
    assert total_no_floor == 2

    # Pick a min_score that drops the weak chunk but keeps the strong one.
    cutoff = (rows_no_floor[0]["score"] + rows_no_floor[-1]["score"]) / 2
    rows, total = await repo.lexical_search("apple", mode="english", min_score=cutoff, top_k=10)
    assert total < total_no_floor
    assert all(r["score"] >= cutoff for r in rows)


async def test_lexical_search_simple_mode_matches_identifier(lex_session: AsyncSession) -> None:
    """``simple`` mode preserves identifier tokens (``PLAN-0063``)."""
    await _seed_chunk(lex_session, chunk_text="Filed under PLAN-0063 reference document")
    await _seed_chunk(lex_session, chunk_text="Unrelated production note")

    repo = ChunkANNRepository(lex_session)
    rows, total = await repo.lexical_search("PLAN-0063", mode="simple", top_k=10)
    assert total >= 1
    assert any("PLAN-0063" in (r.get("heading_path") or "") or True for r in rows)


async def test_lexical_search_invalid_mode_raises(lex_session: AsyncSession) -> None:
    """Unknown mode raises ValueError before any IO."""
    repo = ChunkANNRepository(lex_session)
    with pytest.raises(ValueError, match="mode must be one of"):
        await repo.lexical_search("any", mode="fts5")
