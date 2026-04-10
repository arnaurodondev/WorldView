"""PriceImpactLabellingWorker — retroactively labels articles with price-impact scores.

Periodically claims batches of unlabelled articles from ``nlp_db``, fetches
the OHLCV bar for the article's publication date from the Market Data service,
computes an ``ArticlePriceImpact`` label, and upserts it via the repository.

Key design invariants (PRD-0020 §6.5):
  - DB session is released **before** HTTP calls to MarketDataClient (R24).
  - ``upsert()`` uses ``ON CONFLICT DO NOTHING`` — fully idempotent (R9).
  - Per-article errors are caught and logged; the cycle continues.
  - One label row per article (the entity with the highest ``impact_score`` wins).
"""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from typing import TYPE_CHECKING

from nlp_pipeline.domain.models import ArticlePriceImpact
from nlp_pipeline.infrastructure.nlp_db.repositories.price_impact import ArticlePriceImpactRepository
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.infrastructure.http.market_data_client import MarketDataClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


class PriceImpactLabellingWorker:
    """Background worker that retroactively labels articles with price-impact scores."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        market_data_client: MarketDataClient,
        normalisation_cap_pct: float = 5.0,
        cycle_seconds: int = 14400,
        min_age_hours: int = 25,
        batch_size: int = 100,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._market_data_client = market_data_client
        self._normalisation_cap_pct = Decimal(str(normalisation_cap_pct))
        self._cycle_seconds = cycle_seconds
        self._min_age_hours = min_age_hours
        self._batch_size = batch_size

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_once(self) -> int:
        """Run one labelling cycle.

        Returns the number of ``article_price_impacts`` rows upserted.
        """
        # ── 1. Read phase: fetch unlabelled article details, then close session (R24) ──
        async with self._nlp_sf() as session:
            repo = ArticlePriceImpactRepository(session)
            rows = await repo.get_unlabelled_article_details(
                min_age_hours=self._min_age_hours,
                batch_size=self._batch_size,
            )

        if not rows:
            return 0

        # Group rows by doc_id so we can process all entities per article together
        from collections import defaultdict

        groups: dict[object, list] = defaultdict(list)  # type: ignore[type-arg]
        for row_doc_id, entity_id, symbol, published_at in rows:
            groups[row_doc_id].append((entity_id, symbol, published_at))

        # ── 2. HTTP phase: fetch OHLCV bars (no open DB sessions) ─────────────
        labels = []
        for doc_id, entity_rows in groups.items():
            label = await self._label_article(doc_id, entity_rows)
            if label is not None:
                labels.append(label)
            await asyncio.sleep(0.1)  # throttle between articles (PRD §9)

        if not labels:
            return 0

        # ── 3. Write phase: upsert all labels in a fresh session ──────────────
        async with self._nlp_sf() as session:
            repo = ArticlePriceImpactRepository(session)
            for label in labels:
                await repo.upsert(label)
            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "price_impact_labelling_cycle_done",
            articles_labelled=len(labels),
        )
        return len(labels)

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Run labelling cycles until *stop* is set."""
        while not stop.is_set():
            try:
                count = await self.run_once()
                if count:
                    logger.info(  # type: ignore[no-any-return]
                        "price_impact_labelling_batch_done",
                        count=count,
                    )
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "price_impact_labelling_poll_error",
                    error=str(exc),
                    exc_info=True,
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._cycle_seconds)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _label_article(
        self,
        doc_id: object,
        entity_rows: list[tuple[object, str, object]],
    ) -> ArticlePriceImpact | None:
        """Compute the max-impact label for *doc_id* across all its entities.

        Returns an ``ArticlePriceImpact`` (possibly with ``impact_score=0.0`` if
        no OHLCV data is available) or ``None`` on unexpected error.
        """
        best: ArticlePriceImpact | None = None

        for entity_id, symbol, published_at in entity_rows:
            try:
                candidate = await self._label_entity(
                    doc_id=doc_id,  # type: ignore[arg-type]
                    entity_id=entity_id,  # type: ignore[arg-type]
                    symbol=symbol,
                    published_at=published_at,  # type: ignore[arg-type]
                )
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "price_impact_labelling_entity_error",
                    doc_id=str(doc_id),
                    entity_id=str(entity_id),
                    symbol=symbol,
                    error=str(exc),
                )
                continue

            if best is None or candidate.impact_score > best.impact_score:
                best = candidate

        return best

    async def _label_entity(
        self,
        doc_id: object,
        entity_id: object,
        symbol: str,
        published_at: object,
    ) -> ArticlePriceImpact:
        """Return an ``ArticlePriceImpact`` for a single entity mention."""
        bar_date = published_at.date()  # type: ignore[attr-defined]
        bar = await self._market_data_client.get_ohlcv(symbol, bar_date)

        if bar is None:
            return ArticlePriceImpact.zero(
                article_id=doc_id,  # type: ignore[arg-type]
                entity_id=entity_id,  # type: ignore[arg-type]
                symbol=symbol,
                published_at=published_at,  # type: ignore[arg-type]
                ohlcv_date=bar_date,
            )

        return ArticlePriceImpact.compute(
            article_id=doc_id,  # type: ignore[arg-type]
            entity_id=entity_id,  # type: ignore[arg-type]
            symbol=symbol,
            published_at=published_at,  # type: ignore[arg-type]
            price_open=bar.open,
            price_close=bar.close,
            normalisation_cap_pct=self._normalisation_cap_pct,
        )
