"""Unit tests for the general-news historical backfill (pure logic)."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import pytest
from content_ingestion.scripts.backfill_general_news import (
    RunBudget,
    articles_to_fetch_results,
    backward_windows,
    remaining_windows,
)

import common.ids

pytestmark = pytest.mark.unit


class TestBackwardWindows:
    def test_single_window_when_range_fits(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 7), window_days=7)
        assert windows == [(date(2026, 1, 1), date(2026, 1, 7))]

    def test_newest_first_contiguous_no_gaps_no_overlap(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 20), window_days=7)
        # Newest window first, last clamped to the floor date.
        assert windows[0] == (date(2026, 1, 14), date(2026, 1, 20))
        assert windows[-1] == (date(2026, 1, 1), date(2026, 1, 6))
        # Contiguous: each window starts exactly one day after the next's end.
        for newer, older in pairwise(windows):
            assert older[1] == newer[0] - timedelta(days=1)

    def test_full_range_is_covered_exactly_once(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 20), window_days=7)
        covered = {date.fromordinal(o) for w in windows for o in range(w[0].toordinal(), w[1].toordinal() + 1)}
        expected = {date.fromordinal(o) for o in range(date(2026, 1, 1).toordinal(), date(2026, 1, 20).toordinal() + 1)}
        assert covered == expected

    def test_empty_when_from_after_to(self) -> None:
        assert backward_windows(date(2026, 2, 1), date(2026, 1, 1), window_days=7) == []

    def test_rejects_zero_window(self) -> None:
        with pytest.raises(ValueError, match="window_days"):
            backward_windows(date(2026, 1, 1), date(2026, 1, 7), window_days=0)


class TestRemainingWindows:
    def test_no_cursor_returns_all(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 20), window_days=7)
        assert remaining_windows(windows, None) == windows

    def test_cursor_drops_completed_newer_windows(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 20), window_days=7)
        # We finished the newest window (start 2026-01-14) → resume older-only.
        todo = remaining_windows(windows, cursor=date(2026, 1, 14))
        assert (date(2026, 1, 14), date(2026, 1, 20)) not in todo
        assert todo == [w for w in windows if w[1] < date(2026, 1, 14)]

    def test_cursor_at_floor_leaves_nothing(self) -> None:
        windows = backward_windows(date(2026, 1, 1), date(2026, 1, 20), window_days=7)
        assert remaining_windows(windows, cursor=date(2026, 1, 1)) == []


class TestRunBudget:
    def _budget(self, **kw: int) -> RunBudget:
        defaults = {
            "max_credits": 1000,
            "daily_cap": 100_000,
            "daily_headroom": 10_000,
            "credits_per_request": 5,
            "page_size": 1000,
            "max_pages_per_window": 30,
        }
        defaults.update(kw)
        return RunBudget(**defaults)  # type: ignore[arg-type]

    def test_estimate_is_worst_case_full_paging(self) -> None:
        assert self._budget().estimate_window_credits() == 30 * 5

    def test_run_budget_exhausted_boundary(self) -> None:
        b = self._budget(max_credits=100)
        b.spent = 60
        assert b.run_budget_exhausted(50) is True  # 60 + 50 > 100
        assert b.run_budget_exhausted(40) is False  # 60 + 40 == 100 (allowed)

    def test_daily_budget_exhausted_respects_headroom(self) -> None:
        b = self._budget(daily_cap=100_000, daily_headroom=10_000)
        # Effective ceiling = 90_000.
        assert b.daily_budget_exhausted(daily_used=89_000, next_estimate=2_000) is True
        assert b.daily_budget_exhausted(daily_used=80_000, next_estimate=2_000) is False

    def test_record_articles_accumulates_by_page(self) -> None:
        b = self._budget()
        # 2001 articles → 3 pages (ceil(2001/1000)) → 15 credits.
        assert b.record_articles(2001) == 15
        assert b.spent == 15
        # An empty window still cost one request.
        assert b.record_articles(0) == 5
        assert b.spent == 20


class TestArticlesToFetchResults:
    def test_maps_and_marks_backfill(self) -> None:
        sid = common.ids.new_uuid7()
        results = articles_to_fetch_results(
            [{"link": "https://x/1", "title": "T1", "date": "2023-07-05T10:00:00"}],
            sid,
        )
        assert len(results) == 1
        r = results[0]
        assert r.source_id == sid
        assert r.is_backfill is True
        assert r.title == "T1"
        assert r.published_at is not None

    def test_dedups_within_batch_and_skips_linkless(self) -> None:
        sid = common.ids.new_uuid7()
        results = articles_to_fetch_results(
            [
                {"link": "https://x/1"},
                {"link": "https://x/1"},  # duplicate
                {"title": "no link"},  # skipped
                {"link": ""},  # skipped
            ],
            sid,
        )
        assert len(results) == 1
