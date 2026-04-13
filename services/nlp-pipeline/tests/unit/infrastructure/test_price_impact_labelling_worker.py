"""Unit tests for PriceImpactLabellingWorker (T-B-1-02)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.http.market_data_client import OHLCVBar
from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
    PriceImpactLabellingWorker,
)

if TYPE_CHECKING:
    from nlp_pipeline.domain.models import ArticlePriceImpact

pytestmark = pytest.mark.unit

_DOC_ID = uuid.uuid4()
_ENTITY_ID_1 = uuid.uuid4()
_ENTITY_ID_2 = uuid.uuid4()
_PUBLISHED_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_OHLCV_DATE = date(2026, 4, 1)


def _make_bar(open_: str = "100.00", close: str = "105.00") -> OHLCVBar:
    return OHLCVBar(
        symbol="AAPL",
        date=_OHLCV_DATE,
        open=Decimal(open_),
        close=Decimal(close),
        high=Decimal("106.00"),
        low=Decimal("99.00"),
        volume=1_000_000,
    )


def _make_session_factory(repo_mock: AsyncMock) -> MagicMock:
    """Return a mock async_sessionmaker that yields a context-manager session."""
    session = AsyncMock()
    session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = ctx
    return factory, session


def _make_worker(
    repo_mock: AsyncMock,
    market_client_mock: AsyncMock,
    normalisation_cap_pct: float = 5.0,
) -> tuple[PriceImpactLabellingWorker, MagicMock]:
    factory, _session = _make_session_factory(repo_mock)

    with patch(
        "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
        return_value=repo_mock,
    ):
        worker = PriceImpactLabellingWorker(
            nlp_session_factory=factory,
            market_data_client=market_client_mock,
            normalisation_cap_pct=normalisation_cap_pct,
            cycle_seconds=1,
            min_age_hours=25,
            batch_size=10,
        )
    return worker, factory


class TestLabellingWorkerBasic:
    @pytest.mark.asyncio
    async def test_labelling_worker_returns_zero_when_no_articles(self) -> None:
        """run_once() returns 0 when no unlabelled articles exist."""
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(return_value=[])
        client = AsyncMock()

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            count = await worker.run_once()

        assert count == 0
        client.get_ohlcv.assert_not_called()

    @pytest.mark.asyncio
    async def test_labelling_worker_creates_zero_impact_on_missing_ohlcv(self) -> None:
        """get_ohlcv() returning None → upsert called with impact_score=0.0."""
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID_1, "AAPL", _PUBLISHED_AT)])
        repo.upsert = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=None)

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            count = await worker.run_once()

        assert count == 1
        repo.upsert.assert_awaited_once()
        label: ArticlePriceImpact = repo.upsert.call_args[0][0]
        assert label.impact_score == Decimal("0.0")
        assert label.article_id == _DOC_ID

    @pytest.mark.asyncio
    async def test_labelling_worker_computes_impact_from_ohlcv(self) -> None:
        """Valid OHLCV bar → ArticlePriceImpact.compute() with correct impact_score."""
        # open=100, close=105 → delta=5%, cap=5% → score=min(1.0, 5/5)=1.0
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID_1, "AAPL", _PUBLISHED_AT)])
        repo.upsert = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=_make_bar("100.00", "105.00"))

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, normalisation_cap_pct=5.0, cycle_seconds=1)
            count = await worker.run_once()

        assert count == 1
        label: ArticlePriceImpact = repo.upsert.call_args[0][0]
        assert label.impact_score == Decimal("1.0")  # 5% / 5% cap = 1.0


class TestLabellingWorkerMaxImpact:
    @pytest.mark.asyncio
    async def test_labelling_worker_uses_max_impact_across_entities(self) -> None:
        """Doc with 2 entities (scores 0.3, 0.7) → upserts row with impact_score=0.7."""
        # entity1: open=100, close=101.5 → delta=1.5%, cap=5% → score=0.3
        # entity2: open=100, close=103.5 → delta=3.5%, cap=5% → score=0.7
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(
            return_value=[
                (_DOC_ID, _ENTITY_ID_1, "AAPL", _PUBLISHED_AT),
                (_DOC_ID, _ENTITY_ID_2, "MSFT", _PUBLISHED_AT),
            ]
        )
        repo.upsert = AsyncMock()

        bar1 = _make_bar("100.00", "101.50")  # 1.5% → score 0.30
        bar2 = _make_bar("100.00", "103.50")  # 3.5% → score 0.70

        call_count = 0

        async def side_effect(symbol: str, bar_date: date) -> OHLCVBar:
            nonlocal call_count
            call_count += 1
            return bar1 if symbol == "AAPL" else bar2

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(side_effect=side_effect)

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, normalisation_cap_pct=5.0, cycle_seconds=1)
            count = await worker.run_once()

        assert count == 1
        repo.upsert.assert_awaited_once()
        label: ArticlePriceImpact = repo.upsert.call_args[0][0]
        # The entity with score 0.70 (MSFT) should win
        assert abs(float(label.impact_score) - 0.70) < 0.001
        assert label.entity_id == _ENTITY_ID_2

    @pytest.mark.asyncio
    async def test_labelling_worker_skips_article_on_unexpected_error(self) -> None:
        """If computing a label raises unexpectedly, the article is skipped; cycle continues."""
        doc2 = uuid.uuid4()
        entity2 = uuid.uuid4()

        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(
            return_value=[
                (_DOC_ID, _ENTITY_ID_1, "BAD", _PUBLISHED_AT),  # will cause error
                (doc2, entity2, "GOOD", _PUBLISHED_AT),
            ]
        )
        repo.upsert = AsyncMock()

        call_count = 0

        async def side_effect(symbol: str, bar_date: date) -> OHLCVBar | None:
            nonlocal call_count
            call_count += 1
            if symbol == "BAD":
                raise RuntimeError("unexpected")
            return _make_bar()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(side_effect=side_effect)

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            count = await worker.run_once()

        # Only the good article was labelled
        assert count == 1
        label: ArticlePriceImpact = repo.upsert.call_args[0][0]
        assert label.article_id == doc2

    @pytest.mark.asyncio
    async def test_labelling_worker_idempotent(self) -> None:
        """Running run_once() twice calls upsert() with same article_id both times."""
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID_1, "AAPL", _PUBLISHED_AT)])
        repo.upsert = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=_make_bar())

        factory = MagicMock()
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            await worker.run_once()
            await worker.run_once()

        assert repo.upsert.await_count == 2
        first_call_article = repo.upsert.call_args_list[0][0][0].article_id
        second_call_article = repo.upsert.call_args_list[1][0][0].article_id
        assert first_call_article == second_call_article == _DOC_ID


class TestLabellingWorkerRunForever:
    @pytest.mark.asyncio
    async def test_labelling_worker_run_forever_stops_on_event(self) -> None:
        """stop.set() causes run_forever() to exit cleanly."""
        repo = AsyncMock()
        repo.get_unlabelled_article_details = AsyncMock(return_value=[])

        client = AsyncMock()

        factory = MagicMock()
        session = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = ctx

        with patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticlePriceImpactRepository",
            return_value=repo,
        ):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=9999)
            stop = asyncio.Event()
            stop.set()  # signal immediately

            # Should return without blocking
            await asyncio.wait_for(worker.run_forever(stop), timeout=2.0)
