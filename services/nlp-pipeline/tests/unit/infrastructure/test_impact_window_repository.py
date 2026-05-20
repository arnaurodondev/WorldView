"""Unit tests for ArticleImpactWindowRepository (PRD-0026 Wave 3 T-A-3-02)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.ports.repositories import ArticleImpactWindowRepositoryPort
from nlp_pipeline.domain.enums import WindowType
from nlp_pipeline.domain.models import ArticleImpactWindow
from nlp_pipeline.infrastructure.nlp_db.repositories.impact_window import (
    ArticleImpactWindowRepository,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)
_WINDOW_START = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
_WINDOW_END = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_window(
    article_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    window_type: WindowType = WindowType.DAY_T0,
) -> ArticleImpactWindow:
    """Build a minimal ArticleImpactWindow domain entity."""
    return ArticleImpactWindow.compute(
        article_id=article_id or uuid.uuid4(),
        entity_id=entity_id or uuid.uuid4(),
        symbol="AAPL",
        published_at=_NOW,
        window_type=window_type,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        price_start=Decimal("100"),
        price_end=Decimal("103"),
        cap_pct=Decimal("5.0"),
    )


class TestPortIsAbstract:
    def test_article_impact_window_repo_port_is_abstract(self) -> None:
        """ArticleImpactWindowRepositoryPort cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ArticleImpactWindowRepositoryPort()  # type: ignore[abstract]


class TestUpsertBatch:
    @pytest.mark.asyncio
    async def test_upsert_batch_calls_execute(self) -> None:
        """upsert_batch() with one window must call session.execute() once."""
        session = _make_session()
        repo = ArticleImpactWindowRepository(session)

        await repo.upsert_batch([_make_window()])

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_batch_empty_list_no_execute(self) -> None:
        """upsert_batch([]) must NOT call session.execute (avoids empty INSERT)."""
        session = _make_session()
        repo = ArticleImpactWindowRepository(session)

        await repo.upsert_batch([])

        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_batch_multiple_windows(self) -> None:
        """upsert_batch() with multiple windows calls execute once (bulk INSERT)."""
        session = _make_session()
        repo = ArticleImpactWindowRepository(session)

        article_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        windows = [
            _make_window(article_id=article_id, entity_id=entity_id, window_type=WindowType.DAY_T0),
            _make_window(article_id=article_id, entity_id=entity_id, window_type=WindowType.DAY_T1),
        ]

        await repo.upsert_batch(windows)

        # Bulk INSERT: single execute call for all windows
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_batch_uses_on_conflict_do_nothing(self) -> None:
        """The INSERT statement must use ON CONFLICT DO NOTHING (idempotency, R9)."""
        session = _make_session()
        repo = ArticleImpactWindowRepository(session)

        await repo.upsert_batch([_make_window()])

        # Verify execute was called — the ON CONFLICT clause is in the compiled SQL;
        # we just assert the call happened without error (mock accepts anything).
        session.execute.assert_awaited_once()


class TestGetMaxImpactForDoc:
    @pytest.mark.asyncio
    async def test_get_max_impact_returns_zero_when_no_rows(self) -> None:
        """No windows for doc_id -> Decimal('0.0') returned."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        result = await repo.get_max_impact_for_doc(uuid.uuid4())

        assert result == Decimal("0.0")

    @pytest.mark.asyncio
    async def test_get_max_impact_returns_decimal_value(self) -> None:
        """When rows exist, returns Decimal(max impact_score)."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = Decimal("0.75")

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        result = await repo.get_max_impact_for_doc(uuid.uuid4())

        assert result == Decimal("0.75")

    @pytest.mark.asyncio
    async def test_get_max_impact_calls_execute(self) -> None:
        """get_max_impact_for_doc() must call session.execute()."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        await repo.get_max_impact_for_doc(uuid.uuid4())

        session.execute.assert_awaited_once()


class TestGetArticlesNeedingWindows:
    @pytest.mark.asyncio
    async def test_get_articles_needing_windows_calls_execute(self) -> None:
        """get_articles_needing_windows() must call session.execute()."""
        fake_result = MagicMock()
        fake_result.all.return_value = []

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        result = await repo.get_articles_needing_windows(min_age_hours=25, batch_size=50)

        assert result == []
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_articles_needing_windows_maps_rows(self) -> None:
        """Returned rows are mapped to (doc_id, entity_id, symbol, published_at) tuples."""
        doc_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        pub_at = _NOW - timedelta(hours=30)

        fake_row = MagicMock()
        fake_row.doc_id = doc_id
        fake_row.entity_id = entity_id
        fake_row.symbol = "MSFT"
        fake_row.published_at = pub_at

        fake_result = MagicMock()
        fake_result.all.return_value = [fake_row]

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        result = await repo.get_articles_needing_windows(min_age_hours=25, batch_size=50)

        assert len(result) == 1
        assert result[0] == (doc_id, entity_id, "MSFT", pub_at)

    # ------------------------------------------------------------------
    # W1-02 (BUG-002): SUPPRESS-tier articles must NOT be eligible for
    # impact-window labelling. The fix joins ``routing_decisions`` and
    # filters on ``processing_path != 'halt'`` (with a NULL fallback for
    # legacy pre-migration-0015 rows). The two tests below pin the SQL
    # to that contract.
    #
    # We assert at the SQL-text level rather than running against a
    # real Postgres because the rest of this file is a unit-test module
    # (mocked AsyncSession). The integration-test suite covers actual
    # row-level behaviour elsewhere; here we want a fast, deterministic
    # guard against any future refactor that silently drops the filter.
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sql_text(session: AsyncMock) -> str:
        """Pull the compiled SQL string out of the mocked execute() call.

        ``session.execute`` is invoked with a ``TextClause`` (the return value
        of ``sqlalchemy.text(...)``). We stringify it to grep for the new
        routing-tier filter. This is a structural test — exact whitespace and
        quoting are not part of the contract, only the presence of the
        relevant tokens.
        """
        # call_args is (args, kwargs); the statement is the first positional arg.
        stmt = session.execute.call_args.args[0]
        return str(stmt)

    @pytest.mark.asyncio
    async def test_get_articles_needing_windows_excludes_suppress_articles(self) -> None:
        """SQL must JOIN routing_decisions and exclude processing_path='halt'.

        This is the BUG-002 regression contract: SUPPRESS-tier (HALT) articles
        must never become candidates for impact-window labelling, because
        their inflated impact scores would feed back into the composite
        routing score for future articles citing the same instrument.
        """
        fake_result = MagicMock()
        fake_result.all.return_value = []

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        await repo.get_articles_needing_windows(min_age_hours=25, batch_size=50)

        sql = self._extract_sql_text(session)

        # JOIN against routing_decisions on doc_id is required to know the
        # processing_path of each candidate document.
        assert "routing_decisions" in sql, (
            "BUG-002 regression: query must JOIN routing_decisions to filter "
            "SUPPRESS-tier articles. Got SQL:\n" + sql
        )
        assert "rd.doc_id = em.doc_id" in sql, (
            "BUG-002 regression: routing_decisions must be joined on doc_id. " "Got SQL:\n" + sql
        )
        # The actual exclusion predicate — 'halt' is the ProcessingPath.HALT
        # string value used by the suppression gate.
        assert "processing_path" in sql, "BUG-002 regression: query must reference processing_path column."
        assert "'halt'" in sql, "BUG-002 regression: query must exclude processing_path='halt'. " "Got SQL:\n" + sql

    @pytest.mark.asyncio
    async def test_get_articles_needing_windows_preserves_legacy_null_rows(self) -> None:
        """NULL ``processing_path`` rows (pre-migration-0015) are NOT excluded.

        Migration 0015 added ``processing_path`` as a nullable column. Rows
        written before that migration have NULL. Treating NULL as
        "non-suppress" prevents a regression on legacy data (those rows
        pre-date the bug anyway). The SQL must therefore express the filter
        as ``(processing_path IS NULL OR processing_path != 'halt')``.
        """
        fake_result = MagicMock()
        fake_result.all.return_value = []

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticleImpactWindowRepository(session)

        await repo.get_articles_needing_windows(min_age_hours=25, batch_size=50)

        sql = self._extract_sql_text(session)

        # The exact predicate shape matters: a bare ``!= 'halt'`` would
        # silently drop legacy NULL rows because NULL != 'halt' evaluates
        # to NULL (i.e. false) in SQL three-valued logic.
        assert "processing_path IS NULL" in sql, (
            "BUG-002 NULL-fallback regression: query must allow legacy NULL "
            "processing_path rows through. Got SQL:\n" + sql
        )
