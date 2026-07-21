"""PriceImpactLabellingWorker — multi-window price-impact labeller (PRD-0026).

Periodically claims batches of (article, entity) pairs from nlp_db that are
missing at least one of their expected daily-proxy windows, fetches OHLCV bars
from the Market Data service, and upserts ArticleImpactWindow rows via the
repository.

Key design invariants (PRD-0026 §6.7 Flow A):
  - R24: DB session closed BEFORE any HTTP / asyncio.sleep call.
  - R9: upsert_batch() uses ON CONFLICT DO NOTHING — fully idempotent.
  - Per-article errors are caught and logged; the cycle continues.
  - Windows NOT yet due (article too young) are silently skipped.

Windows and minimum article age (published_at + N hours before bar is closed):
  day_t0   >= 25 h  — publication-day bar (open -> close), cap 5%
  day_t1   >= 49 h  — following-day bar (open -> close), cap 5%
  day_t2   >= 73 h  — 2-day cumulative (close_t0 -> close_t2), cap 7.5%
  day_t5   >= 145 h — 5-day cumulative (close_t0 -> close_t5), cap 10%
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from nlp_pipeline.domain.enums import DataQuality, WindowType
from nlp_pipeline.domain.models import ArticleImpactWindow
from nlp_pipeline.infrastructure.nlp_db.repositories.impact_window import ArticleImpactWindowRepository
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nlp_pipeline.infrastructure.http.market_data_client import MarketDataClient, OHLCVBar

logger = get_logger(__name__)  # type: ignore[no-any-return]

# --- Window age thresholds (hours after published_at before the bar is closed) ---
_MIN_AGE_DAY_T0_H = 25
_MIN_AGE_DAY_T1_H = 49
_MIN_AGE_DAY_T2_H = 73
_MIN_AGE_DAY_T5_H = 145


class PriceImpactLabellingWorker:
    """Background worker that retroactively labels articles with multi-window price-impact scores."""

    def __init__(
        self,
        nlp_session_factory: async_sessionmaker[AsyncSession],
        market_data_client: MarketDataClient,
        cap_day_t0_pct: float = 5.0,
        cap_day_t1_pct: float = 5.0,
        cap_day_t2_pct: float = 7.5,
        cap_day_t5_pct: float = 10.0,
        cycle_seconds: int = 14400,
        min_age_hours: int = 25,
        batch_size: int = 100,
    ) -> None:
        self._nlp_sf = nlp_session_factory
        self._market_data_client = market_data_client
        self._cap_t0 = Decimal(str(cap_day_t0_pct))
        self._cap_t1 = Decimal(str(cap_day_t1_pct))
        self._cap_t2 = Decimal(str(cap_day_t2_pct))
        self._cap_t5 = Decimal(str(cap_day_t5_pct))
        self._cycle_seconds = cycle_seconds
        self._min_age_hours = min_age_hours
        self._batch_size = batch_size

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_once(self) -> int:
        """Run one labelling cycle.

        Returns the total number of ArticleImpactWindow rows upserted.
        """
        # ── Phase 1 — Read: fetch (article, entity) pairs needing windows ─────
        async with self._nlp_sf() as session:
            repo = ArticleImpactWindowRepository(session)
            rows = await repo.get_articles_needing_windows(
                min_age_hours=self._min_age_hours,
                batch_size=self._batch_size,
            )
        # Session is closed here — DB released BEFORE any HTTP calls (R24).

        if not rows:
            return 0

        # ── Phase 2 — HTTP: compute windows (no open DB sessions) ─────────────
        all_windows: list[ArticleImpactWindow] = []
        now = datetime.now(tz=UTC)

        for article_id, entity_id, symbol, published_at in rows:
            try:
                windows = await self._compute_windows(
                    article_id=article_id,
                    entity_id=entity_id,
                    symbol=symbol,
                    published_at=published_at,
                    now=now,
                )
                all_windows.extend(windows)
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "price_impact_labelling_entity_error",
                    article_id=str(article_id),
                    entity_id=str(entity_id),
                    symbol=symbol,
                    error=str(exc),
                )
            await asyncio.sleep(0.1)  # throttle between entities (PRD §9)

        if not all_windows:
            # FAIL-LOUD (2026-07-21): candidates existed this cycle but produced
            # ZERO windows — every ``get_ohlcv`` returned None. This is the exact
            # signature of the globally-empty ``article_impact_windows`` table:
            # the worker was healthy for weeks writing nothing while silently
            # returning 0. The usual cause is a systemic market-data dependency
            # failure — a missing ``NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN`` so every
            # OHLCV call 401s (dev-login is blocked in production), or an
            # unresolvable ``symbol`` (mention_text) 404ing. Log at ERROR so ops
            # alerting can catch a persistently non-productive worker instead of
            # the previous silent ``return 0``.
            logger.error(  # type: ignore[no-any-return]
                "price_impact_labelling_zero_windows_for_candidates",
                candidates=len(rows),
                hint="all get_ohlcv calls returned None — check market-data auth (401) / symbol resolution (404)",
            )
            return 0

        # ── Phase 3 — Write: upsert windows AND update impact_score headline ──
        #
        # F-Q2-02 (PLAN-0050 QA iter-2): document_source_metadata.impact_score
        # was never populated — PriceImpactLabellingWorker only wrote to
        # article_impact_windows, leaving the convenience column permanently NULL.
        # The GET /v1/news/top endpoint reads document_source_metadata.impact_score
        # directly (avoids a JOIN to article_impact_windows on every request), so
        # NULL there meant the News-tab impact pills never rendered.
        #
        # Derivation rationale: we take max(abs(impact_score)) across ALL windows
        # and ALL entities for a given article, then normalise to [0, 1].
        # WHY max(abs(...)): impact_score in article_impact_windows is already
        # normalised to [0, 1] by ArticleImpactWindow.compute() (cap applied).
        # The article-level headline score should reflect the strongest price-
        # movement signal regardless of direction, so we use the maximum absolute
        # value across all window/entity pairs.  No further normalisation is needed
        # because each individual impact_score is already in [0, 1].
        #
        # WHY same transaction: if the windows write commits but the DSM update
        # fails, the next cycle would see no missing windows for those articles and
        # never retry — leaving impact_score NULL forever.  Committing both writes
        # atomically prevents that divergence.
        async with self._nlp_sf() as session:
            repo = ArticleImpactWindowRepository(session)
            await repo.upsert_batch(all_windows)

            # Derive per-article headline impact_score and write to DSM
            await _update_dsm_impact_scores(session, all_windows)

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "price_impact_labelling_cycle_done",
            windows_written=len(all_windows),
            articles_processed=len(rows),
        )
        return len(all_windows)

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

    async def _compute_windows(
        self,
        article_id: UUID,
        entity_id: UUID,
        symbol: str,
        published_at: datetime,
        now: datetime,
    ) -> list[ArticleImpactWindow]:
        """Compute all due windows for a single (article_id, entity_id) pair.

        Returns an empty list if the day_t0 bar is unavailable (can't compute
        cumulative windows without the t0 baseline).
        """
        age_hours = (now - published_at).total_seconds() / 3600
        pub_date = published_at.date()

        # day_t0 must always be fetched first — it is the baseline for cumulative windows.
        if age_hours < _MIN_AGE_DAY_T0_H:
            return []  # Article too young for any window

        t0_bar_date = pub_date
        t0_bar: OHLCVBar | None = await self._market_data_client.get_ohlcv(symbol, t0_bar_date)
        if t0_bar is None:
            # 404 or network error — skip all windows; cannot form cumulative baseline.
            return []

        windows: list[ArticleImpactWindow] = []

        # --- day_t0 -------------------------------------------------------
        t0_start = datetime(pub_date.year, pub_date.month, pub_date.day, tzinfo=UTC)
        t0_end = t0_start + timedelta(days=1)
        with contextlib.suppress(ValueError):  # price_start == 0 can't happen (market_data_client guards it)
            w_t0 = ArticleImpactWindow.compute(
                article_id=article_id,
                entity_id=entity_id,
                symbol=symbol,
                published_at=published_at,
                window_type=WindowType.DAY_T0,
                window_start=t0_start,
                window_end=t0_end,
                price_start=t0_bar.open,
                price_end=t0_bar.close,
                cap_pct=self._cap_t0,
                high_pct=self.__high_pct(t0_bar),
                low_pct=self.__low_pct(t0_bar),
                data_quality=DataQuality.DAILY_PROXY,
            )
            windows.append(w_t0)

        close_t0 = t0_bar.close  # Baseline for cumulative windows

        # --- day_t1 -------------------------------------------------------
        if age_hours >= _MIN_AGE_DAY_T1_H:
            t1_bar_date = pub_date + timedelta(days=1)
            t1_bar: OHLCVBar | None = await self._market_data_client.get_ohlcv(symbol, t1_bar_date)
            if t1_bar is not None:
                t1_start = datetime(t1_bar_date.year, t1_bar_date.month, t1_bar_date.day, tzinfo=UTC)
                t1_end = t1_start + timedelta(days=1)
                with contextlib.suppress(ValueError):
                    windows.append(
                        ArticleImpactWindow.compute(
                            article_id=article_id,
                            entity_id=entity_id,
                            symbol=symbol,
                            published_at=published_at,
                            window_type=WindowType.DAY_T1,
                            window_start=t1_start,
                            window_end=t1_end,
                            price_start=t1_bar.open,
                            price_end=t1_bar.close,
                            cap_pct=self._cap_t1,
                            high_pct=self.__high_pct(t1_bar),
                            low_pct=self.__low_pct(t1_bar),
                            data_quality=DataQuality.DAILY_PROXY,
                        )
                    )

        # --- day_t2 (cumulative from close_t0) ----------------------------
        if age_hours >= _MIN_AGE_DAY_T2_H:
            t2_bar_date = pub_date + timedelta(days=2)
            t2_bar: OHLCVBar | None = await self._market_data_client.get_ohlcv(symbol, t2_bar_date)
            if t2_bar is not None and close_t0 > Decimal("0"):
                # Cumulative: starts from close of t0 bar
                t2_start = t0_end  # = pub_date + 1 day at 00:00 (conceptually t0 close)
                t2_end = datetime(t2_bar_date.year, t2_bar_date.month, t2_bar_date.day, tzinfo=UTC) + timedelta(days=1)
                with contextlib.suppress(ValueError):
                    windows.append(
                        ArticleImpactWindow.compute(
                            article_id=article_id,
                            entity_id=entity_id,
                            symbol=symbol,
                            published_at=published_at,
                            window_type=WindowType.DAY_T2,
                            window_start=t2_start,
                            window_end=t2_end,
                            price_start=close_t0,
                            price_end=t2_bar.close,
                            cap_pct=self._cap_t2,
                            data_quality=DataQuality.DAILY_PROXY,
                        )
                    )

        # --- day_t5 (cumulative from close_t0) ----------------------------
        if age_hours >= _MIN_AGE_DAY_T5_H:
            t5_bar_date = pub_date + timedelta(days=5)
            t5_bar: OHLCVBar | None = await self._market_data_client.get_ohlcv(symbol, t5_bar_date)
            if t5_bar is not None and close_t0 > Decimal("0"):
                t5_start = t0_end  # same as t2: cumulative baseline is t0 close
                t5_end = datetime(t5_bar_date.year, t5_bar_date.month, t5_bar_date.day, tzinfo=UTC) + timedelta(days=1)
                with contextlib.suppress(ValueError):
                    windows.append(
                        ArticleImpactWindow.compute(
                            article_id=article_id,
                            entity_id=entity_id,
                            symbol=symbol,
                            published_at=published_at,
                            window_type=WindowType.DAY_T5,
                            window_start=t5_start,
                            window_end=t5_end,
                            price_start=close_t0,
                            price_end=t5_bar.close,
                            cap_pct=self._cap_t5,
                            data_quality=DataQuality.DAILY_PROXY,
                        )
                    )

        return windows

    @staticmethod
    def __high_pct(bar: OHLCVBar) -> Decimal | None:
        """Compute intraday high as % above bar open, or None if invalid."""
        if bar.open <= Decimal("0"):
            return None
        return (bar.high - bar.open) / bar.open * Decimal("100")

    @staticmethod
    def __low_pct(bar: OHLCVBar) -> Decimal | None:
        """Compute intraday low as % below bar open (negative = below open), or None if invalid."""
        if bar.open <= Decimal("0"):
            return None
        return (bar.low - bar.open) / bar.open * Decimal("100")


# ── Module-level helper: write headline impact_score to document_source_metadata ──


# F-Q2-02 (PLAN-0050 QA iter-2): raw SQL UPDATE for the DSM convenience column.
#
# WHY text() not ORM: document_source_metadata is owned by nlp_pipeline's ORM
# model (DocumentSourceMetadataModel) but the PriceImpactLabellingWorker lives
# in the infrastructure.workers package, which should not import the full ORM
# model hierarchy just to issue a single UPDATE.  Using text() keeps the coupling
# minimal and matches the existing pattern in ArticleImpactWindowRepository's
# get_articles_needing_windows() (also raw SQL).
#
# The UPDATE is per-article (WHERE doc_id = :doc_id) and is issued once per
# unique article_id in the current batch.  Calling this inside the same
# async_sessionmaker context as upsert_batch() ensures both writes are committed
# atomically (same session → same transaction).
_DSM_UPDATE_SQL = text("""
    UPDATE document_source_metadata
    SET impact_score = :impact_score
    WHERE doc_id = :doc_id
""")


async def _update_dsm_impact_scores(
    session: AsyncSession,
    windows: list[ArticleImpactWindow],
) -> None:
    """Write a headline impact_score to document_source_metadata for each article.

    Derivation: max(impact_score) across all computed windows and all entities
    for a given article.

    WHY max(impact_score):
      - impact_score in article_impact_windows is already normalised to [0, 1]
        by ArticleImpactWindow.compute() (the normalisation_cap_pct is applied
        at compute-time, so values are capped and scaled).
      - The "headline" article-level signal should reflect the *strongest*
        price-movement event associated with the article, regardless of which
        entity or window triggered it.
      - We do NOT average because a single highly-impactful entity dominates
        the narrative; averaging would dilute it against unrelated mentions.
      - abs() is redundant here because impact_score is always >= 0 after
        ArticleImpactWindow.compute() clamps delta_pct / cap_pct to [0, 1].
        We call abs() defensively in case future callers produce negative values.

    Called in Phase 3 of run_once() — inside the same session as upsert_batch()
    so both writes are committed atomically.
    """
    if not windows:
        return

    # Group windows by article_id and find max impact_score per article
    per_article: dict[UUID, Decimal] = {}
    for w in windows:
        current_max = per_article.get(w.article_id, Decimal("0"))
        per_article[w.article_id] = max(current_max, abs(w.impact_score))

    for doc_id, score in per_article.items():
        await session.execute(
            _DSM_UPDATE_SQL,
            {
                "doc_id": doc_id,
                "impact_score": score,
            },
        )
