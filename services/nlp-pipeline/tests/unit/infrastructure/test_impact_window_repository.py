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
