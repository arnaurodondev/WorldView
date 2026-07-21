"""Unit tests for PriceImpactLabellingWorker — multi-window redesign (PRD-0026 Wave 4)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.domain.enums import WindowType
from nlp_pipeline.infrastructure.http.market_data_client import OHLCVBar
from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
    PriceImpactLabellingWorker,
)

if TYPE_CHECKING:
    from nlp_pipeline.domain.models import ArticleImpactWindow

pytestmark = pytest.mark.unit

_DOC_ID = uuid.uuid4()
_ENTITY_ID = uuid.uuid4()

# Article published 200h ago — all 4 windows (t0/t1/t2/t5) are due
_PUBLISHED_AT_OLD = datetime.now(UTC) - timedelta(hours=200)
# Article published 30h ago — only day_t0 is due
_PUBLISHED_AT_30H = datetime.now(UTC) - timedelta(hours=30)
# Article published 50h ago — day_t0 + day_t1 are due
_PUBLISHED_AT_50H = datetime.now(UTC) - timedelta(hours=50)
# Article published 10h ago — no windows due yet
_PUBLISHED_AT_10H = datetime.now(UTC) - timedelta(hours=10)

_PATCH_PATH = "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.ArticleImpactWindowRepository"


def _make_bar(
    symbol: str = "AAPL",
    open_: str = "100.00",
    close: str = "105.00",
    high: str = "106.00",
    low: str = "99.00",
    bar_date: date | None = None,
) -> OHLCVBar:
    return OHLCVBar(
        symbol=symbol,
        date=bar_date or date(2026, 4, 1),
        open=Decimal(open_),
        close=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        volume=1_000_000,
    )


def _make_session_factory(repo_mock: AsyncMock) -> tuple[MagicMock, AsyncMock]:
    """Return a (factory, session) pair where factory yields repo_mock on enter."""
    session = AsyncMock()
    session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = ctx
    return factory, session


@contextmanager
def _make_worker(
    repo_mock: AsyncMock,
    market_client_mock: AsyncMock,
    *,
    cycle_seconds: int = 1,
    min_age_hours: int = 25,
    batch_size: int = 10,
) -> Generator[tuple[PriceImpactLabellingWorker, MagicMock], None, None]:
    """Context manager that yields (worker, factory) with ArticleImpactWindowRepository patched.

    The patch must stay active for the duration of run_once() / run_forever() calls because
    the worker creates a new repository instance from the session factory on every cycle.
    Exiting this context restores the original class.
    """
    factory, _session = _make_session_factory(repo_mock)

    with patch(_PATCH_PATH, return_value=repo_mock):
        worker = PriceImpactLabellingWorker(
            nlp_session_factory=factory,
            market_data_client=market_client_mock,
            cycle_seconds=cycle_seconds,
            min_age_hours=min_age_hours,
            batch_size=batch_size,
        )
        yield worker, factory


class TestBasicBehavior:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_articles(self) -> None:
        """run_once() returns 0 when get_articles_needing_windows() returns empty list."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[])
        client = AsyncMock()

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        assert count == 0
        client.get_ohlcv.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_zero_when_article_too_young(self) -> None:
        """Article < 25h old → get_articles_needing_windows returns nothing yet."""
        # In practice get_articles_needing_windows filters by min_age_hours;
        # this test verifies the worker handles an empty batch gracefully.
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[])
        client = AsyncMock()

        with _make_worker(repo, client, min_age_hours=25) as (worker, _):
            count = await worker.run_once()

        assert count == 0


class TestWindowComputation:
    @pytest.mark.asyncio
    async def test_computes_all_four_windows_for_old_article(self) -> None:
        """Article published 200h ago → day_t0 + day_t1 + day_t2 + day_t5 all created."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        bar = _make_bar()
        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=bar)  # All bar lookups succeed

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        # 4 windows expected: day_t0, day_t1, day_t2, day_t5
        assert count == 4
        repo.upsert_batch.assert_awaited_once()
        windows: list[ArticleImpactWindow] = repo.upsert_batch.call_args[0][0]
        window_types = {w.window_type for w in windows}
        assert WindowType.DAY_T0 in window_types
        assert WindowType.DAY_T1 in window_types
        assert WindowType.DAY_T2 in window_types
        assert WindowType.DAY_T5 in window_types

    @pytest.mark.asyncio
    async def test_only_day_t0_for_article_30h_old(self) -> None:
        """Article published 30h ago → only day_t0 is due (day_t1 needs >= 49h)."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_30H)])
        repo.upsert_batch = AsyncMock()

        bar = _make_bar()
        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=bar)

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        assert count == 1
        windows: list[ArticleImpactWindow] = repo.upsert_batch.call_args[0][0]
        assert len(windows) == 1
        assert windows[0].window_type == WindowType.DAY_T0

    @pytest.mark.asyncio
    async def test_day_t0_and_day_t1_for_article_50h_old(self) -> None:
        """Article published 50h ago → day_t0 + day_t1 (day_t2 needs >= 73h)."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_50H)])
        repo.upsert_batch = AsyncMock()

        bar = _make_bar()
        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=bar)

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        assert count == 2
        windows: list[ArticleImpactWindow] = repo.upsert_batch.call_args[0][0]
        window_types = {w.window_type for w in windows}
        assert WindowType.DAY_T0 in window_types
        assert WindowType.DAY_T1 in window_types
        assert WindowType.DAY_T2 not in window_types
        assert WindowType.DAY_T5 not in window_types

    @pytest.mark.asyncio
    async def test_cumulative_window_uses_t0_close_as_price_start(self) -> None:
        """day_t2 and day_t5 use close price from day_t0 bar as price_start (cumulative)."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        # t0 bar: open=100, close=103 (3% gain)
        t0_bar = _make_bar(open_="100.00", close="103.00")
        # Other bars: use different values so we can distinguish
        t1_bar = _make_bar(open_="103.50", close="104.00")
        t2_bar = _make_bar(open_="104.00", close="108.00")
        t5_bar = _make_bar(open_="108.00", close="112.00")

        call_n = 0

        async def _get_ohlcv(symbol: str, bar_date: date) -> OHLCVBar:
            nonlocal call_n
            call_n += 1
            bars = [t0_bar, t1_bar, t2_bar, t5_bar]
            return bars[(call_n - 1) % len(bars)]

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(side_effect=_get_ohlcv)

        with _make_worker(repo, client) as (worker, _):
            await worker.run_once()

        windows: list[ArticleImpactWindow] = repo.upsert_batch.call_args[0][0]
        by_type = {w.window_type: w for w in windows}

        # day_t2 must have price_start == close_t0 (103.00), NOT t2_bar.open (104.00)
        assert WindowType.DAY_T2 in by_type
        assert by_type[WindowType.DAY_T2].price_start == Decimal("103.00")

        # day_t5 must also have price_start == close_t0 (103.00)
        assert WindowType.DAY_T5 in by_type
        assert by_type[WindowType.DAY_T5].price_start == Decimal("103.00")

    @pytest.mark.asyncio
    async def test_skips_all_windows_when_t0_bar_unavailable(self) -> None:
        """day_t0 bar returns None → ALL windows skipped (no baseline for cumulative)."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=None)  # All bars missing

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        assert count == 0
        repo.upsert_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_windows_for_candidates_logs_error(self) -> None:
        """FAIL-LOUD: candidates present but every get_ohlcv returns None must ERROR-log.

        Regression for the globally-empty ``article_impact_windows`` table: the worker
        stayed healthy for weeks writing nothing (systemic market-data 401/404) while
        silently returning 0. When rows were selected but zero windows were produced the
        worker MUST emit ``price_impact_labelling_zero_windows_for_candidates`` at ERROR
        so ops alerting can catch a persistently non-productive worker.
        """
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=None)  # systemic failure → no bars

        with (
            _make_worker(repo, client) as (worker, _),
            patch("nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.logger") as mock_logger,
        ):
            count = await worker.run_once()

        assert count == 0
        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args[0][0] == "price_impact_labelling_zero_windows_for_candidates"
        assert mock_logger.error.call_args.kwargs["candidates"] == 1

    @pytest.mark.asyncio
    async def test_day_t1_skipped_when_bar_missing(self) -> None:
        """day_t1 bar returns None → day_t1 window not created, others proceed."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        base_bar = _make_bar()
        call_n = 0

        async def _get_ohlcv(symbol: str, bar_date: date) -> OHLCVBar | None:
            nonlocal call_n
            call_n += 1
            # Second call is day_t1 — simulate non-trading day (404)
            return None if call_n == 2 else base_bar

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(side_effect=_get_ohlcv)

        with _make_worker(repo, client) as (worker, _):
            count = await worker.run_once()

        windows: list[ArticleImpactWindow] = repo.upsert_batch.call_args[0][0]
        window_types = {w.window_type for w in windows}
        assert WindowType.DAY_T1 not in window_types
        assert WindowType.DAY_T0 in window_types
        assert count >= 1


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_upsert_batch_called_with_on_conflict_do_nothing(self) -> None:
        """upsert_batch() is called once per run_once() — repository handles ON CONFLICT."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=_make_bar())

        with _make_worker(repo, client) as (worker, _):
            # First run
            await worker.run_once()
            # Second run (same data) — idempotency handled at DB level via ON CONFLICT
            repo.get_articles_needing_windows = AsyncMock(
                return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)]
            )
            await worker.run_once()

        # upsert_batch called once per run_once (both runs)
        assert repo.upsert_batch.await_count == 2


class TestR24Compliance:
    @pytest.mark.asyncio
    async def test_db_session_closed_before_http_calls(self) -> None:
        """R24: DB session must be released BEFORE any get_ohlcv HTTP call."""
        open_times: list[str] = []  # track "session_open" / "session_close" / "http_call"

        # Build a session factory that records when it's opened/closed
        session = AsyncMock()
        session.commit = AsyncMock()

        async def _enter(*args: object) -> AsyncMock:
            open_times.append("session_open")
            return session

        async def _exit(*args: object) -> bool:
            open_times.append("session_close")
            return False

        ctx = AsyncMock()
        ctx.__aenter__ = _enter
        ctx.__aexit__ = _exit
        factory = MagicMock(return_value=ctx)

        # Mark HTTP calls
        async def _get_ohlcv(symbol: str, bar_date: date) -> OHLCVBar:
            open_times.append("http_call")
            return _make_bar()

        client = AsyncMock()
        client.get_ohlcv = AsyncMock(side_effect=_get_ohlcv)

        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_30H)])
        repo.upsert_batch = AsyncMock()

        with patch(_PATCH_PATH, return_value=repo):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            await worker.run_once()

        # Phase 1 session must close before the first HTTP call
        first_close_idx = next(i for i, v in enumerate(open_times) if v == "session_close")
        first_http_idx = next(i for i, v in enumerate(open_times) if v == "http_call")
        assert first_close_idx < first_http_idx, f"Session not closed before HTTP call: {open_times}"


class TestRunForever:
    @pytest.mark.asyncio
    async def test_run_forever_stops_on_event(self) -> None:
        """stop.set() causes run_forever() to exit cleanly."""
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[])

        client = AsyncMock()
        factory, _ = _make_session_factory(repo)

        with patch(_PATCH_PATH, return_value=repo):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=9999)
            stop = asyncio.Event()
            stop.set()  # signal immediately

            await asyncio.wait_for(worker.run_forever(stop), timeout=5.0)

    @pytest.mark.asyncio
    async def test_run_forever_continues_after_error(self) -> None:
        """An exception in run_once() is caught; run_forever() keeps running until stop."""
        repo = AsyncMock()
        call_count = 0

        async def _get_windows(*args: object, **kwargs: object) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            return []

        repo.get_articles_needing_windows = AsyncMock(side_effect=_get_windows)
        client = AsyncMock()
        factory, _ = _make_session_factory(repo)

        with patch(_PATCH_PATH, return_value=repo):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            stop = asyncio.Event()

            async def _stop_after_two_cycles() -> None:
                while call_count < 2:
                    await asyncio.sleep(0.01)
                stop.set()

            await asyncio.gather(
                worker.run_forever(stop),
                _stop_after_two_cycles(),
            )

        assert call_count >= 2, "Worker should have run at least 2 cycles"


# ── F-Q2-02: document_source_metadata.impact_score writer ────────────────────
#
# These tests verify that run_once() now ALSO writes a headline impact_score to
# document_source_metadata in the same atomic commit as the article_impact_windows
# rows (PLAN-0050 QA iter-2 finding F-Q2-02).


class TestDsmImpactScoreWriter:
    @pytest.mark.asyncio
    async def test_run_once_updates_dsm_impact_score_after_upsert_batch(self) -> None:
        """F-Q2-02: After writing to article_impact_windows, run_once() issues an UPDATE
        to document_source_metadata.impact_score in the same DB session/transaction.

        The impact_score value is max(abs(impact_score)) across all windows for the article.
        """
        repo = AsyncMock()
        repo.get_articles_needing_windows = AsyncMock(return_value=[(_DOC_ID, _ENTITY_ID, "AAPL", _PUBLISHED_AT_OLD)])
        repo.upsert_batch = AsyncMock()

        bar = _make_bar(open_="100.00", close="103.00")  # 3% gain → impact_score > 0
        client = AsyncMock()
        client.get_ohlcv = AsyncMock(return_value=bar)

        # Capture session.execute calls to verify the DSM UPDATE is issued
        session = AsyncMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock(return_value=None)

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock()
        factory.return_value = ctx

        # We need two separate session factory calls: Phase 1 (read) + Phase 3 (write).
        # _make_session_factory gives only one session; patch both via a counter.
        call_count = 0
        read_session = AsyncMock()
        read_session.commit = AsyncMock()

        async def _multi_session_enter(*args: object) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Phase 1 (read session) — no execute calls needed here because
                # ArticleImpactWindowRepository is patched below
                return read_session
            # Phase 3 (write session)
            return session

        async def _multi_session_exit(*args: object) -> bool:
            return False

        ctx.__aenter__ = _multi_session_enter
        ctx.__aexit__ = _multi_session_exit
        factory.return_value = ctx

        with patch(_PATCH_PATH, return_value=repo):
            worker = PriceImpactLabellingWorker(factory, client, cycle_seconds=1)
            count = await worker.run_once()

        # Windows were produced (at least day_t0 for an article 200h old)
        assert count >= 1
        # Phase 3 session.execute must have been called for the DSM UPDATE
        # (once per unique article_id in the batch = once for _DOC_ID)
        assert session.execute.await_count >= 1, (
            "F-Q2-02: session.execute was never called — document_source_metadata.impact_score "
            "is not being updated. run_once() must call _update_dsm_impact_scores() in Phase 3."
        )

    @pytest.mark.asyncio
    async def test_update_dsm_impact_scores_uses_max_abs_impact(self) -> None:
        """F-Q2-02: _update_dsm_impact_scores() picks max(abs(impact_score)) per article.

        Given two windows for the same article with impact_score 0.30 and 0.55,
        the UPDATE to document_source_metadata must use 0.55.
        """
        from decimal import Decimal
        from unittest.mock import AsyncMock
        from uuid import uuid4

        from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
            _update_dsm_impact_scores,
        )

        article_id = uuid4()

        # Build two minimal ArticleImpactWindow mocks (avoid constructing full domain objects)
        w1 = MagicMock()
        w1.article_id = article_id
        w1.impact_score = Decimal("0.30")

        w2 = MagicMock()
        w2.article_id = article_id
        w2.impact_score = Decimal("0.55")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)

        await _update_dsm_impact_scores(session, [w1, w2])

        # One UPDATE call (one unique article_id)
        assert session.execute.await_count == 1

        # The impact_score passed to the UPDATE must be 0.55 (the maximum)
        _sql, params = session.execute.call_args.args
        assert params["impact_score"] == Decimal(
            "0.55"
        ), f"Expected impact_score=0.55 (max of 0.30 and 0.55) but got {params['impact_score']}"
        assert params["doc_id"] == article_id

    @pytest.mark.asyncio
    async def test_update_dsm_impact_scores_groups_by_article(self) -> None:
        """F-Q2-02: _update_dsm_impact_scores() issues one UPDATE per unique article_id.

        Two articles in the batch must produce two separate UPDATE statements.
        """
        from decimal import Decimal
        from uuid import uuid4

        from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
            _update_dsm_impact_scores,
        )

        article_1 = uuid4()
        article_2 = uuid4()

        w1 = MagicMock()
        w1.article_id = article_1
        w1.impact_score = Decimal("0.40")

        w2 = MagicMock()
        w2.article_id = article_2
        w2.impact_score = Decimal("0.70")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)

        await _update_dsm_impact_scores(session, [w1, w2])

        # Two UPDATE calls — one per article
        assert session.execute.await_count == 2

        # Extract doc_ids from both calls
        doc_ids_written = {call.args[1]["doc_id"] for call in session.execute.call_args_list}
        assert article_1 in doc_ids_written
        assert article_2 in doc_ids_written

    @pytest.mark.asyncio
    async def test_update_dsm_impact_scores_noop_on_empty_list(self) -> None:
        """F-Q2-02: _update_dsm_impact_scores() is a no-op when windows list is empty."""
        from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
            _update_dsm_impact_scores,
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)

        await _update_dsm_impact_scores(session, [])

        session.execute.assert_not_awaited()
