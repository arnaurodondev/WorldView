"""Unit tests for ArticlePriceImpactRepository (T-A-2-02)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.ports.repositories import PriceImpactRepositoryPort
from nlp_pipeline.domain.models import ArticlePriceImpact
from nlp_pipeline.infrastructure.nlp_db.repositories.price_impact import (
    ArticlePriceImpactRepository,
)

pytestmark = pytest.mark.unit

_PUBLISHED_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_OHLCV_DATE = date(2026, 4, 1)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_impact(article_id: uuid.UUID | None = None) -> ArticlePriceImpact:
    return ArticlePriceImpact.compute(
        article_id=article_id or uuid.uuid4(),
        entity_id=uuid.uuid4(),
        symbol="AAPL",
        published_at=_PUBLISHED_AT,
        price_open=Decimal("100"),
        price_close=Decimal("103"),
    )


class TestUpsertIdempotent:
    @pytest.mark.asyncio
    async def test_upsert_calls_execute(self) -> None:
        """upsert() must call session.execute() with an INSERT statement."""
        session = _make_session()
        repo = ArticlePriceImpactRepository(session)

        await repo.upsert(_make_impact())

        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_same_article_id_twice_no_error(self) -> None:
        """Second upsert with same article_id must not raise (ON CONFLICT DO NOTHING)."""
        article_id = uuid.uuid4()
        session = _make_session()
        repo = ArticlePriceImpactRepository(session)

        await repo.upsert(_make_impact(article_id=article_id))
        await repo.upsert(_make_impact(article_id=article_id))

        assert session.execute.await_count == 2


class TestGetByArticleId:
    @pytest.mark.asyncio
    async def test_get_by_article_id_returns_none(self) -> None:
        """Unknown article_id → None returned without error."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticlePriceImpactRepository(session)

        result = await repo.get_by_article_id(uuid.uuid4())

        assert result is None
        session.execute.assert_awaited_once()


class TestGetMaxImpactNoRows:
    @pytest.mark.asyncio
    async def test_get_max_impact_no_rows(self) -> None:
        """No rows for doc_id → Decimal('0.0') returned."""
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None

        session = _make_session()
        session.execute = AsyncMock(return_value=fake_result)
        repo = ArticlePriceImpactRepository(session)

        result = await repo.get_max_impact_for_doc(uuid.uuid4())

        assert result == Decimal("0.0")


class TestPortIsAbstract:
    def test_price_impact_repo_port_is_abstract(self) -> None:
        """PriceImpactRepositoryPort cannot be instantiated directly."""
        with pytest.raises(TypeError):
            PriceImpactRepositoryPort()  # type: ignore[abstract]
