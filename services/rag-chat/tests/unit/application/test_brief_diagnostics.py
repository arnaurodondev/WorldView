"""Unit tests for brief diagnostics helpers (PLAN-0099 Wave A).

Covers:
  * ``compute_context_availability_score`` — weighted score in [0.0, 1.0].
  * ``timed_upstream_call`` — captures latency, classifies timeout / error /
    empty / ok outcomes.
  * ``record_cache_outcome`` — emits the Prometheus counter for the labelled
    cache + outcome.

All Prometheus assertions read the metric counter / histogram sample value
directly so the tests are self-contained (no Prometheus scrape).
"""

from __future__ import annotations

import asyncio

import pytest
from rag_chat.application.metrics import prometheus as _m
from rag_chat.application.use_cases.brief_diagnostics import (
    compute_context_availability_score,
    record_cache_outcome,
    timed_upstream_call,
)

pytestmark = pytest.mark.unit


# ── compute_context_availability_score ───────────────────────────────────────


def test_score_all_present_equals_one() -> None:
    """All five components present → score is exactly 1.0."""
    score = compute_context_availability_score(
        has_portfolio=True,
        news_count=8,
        events_count=6,
        alerts_count=5,
        sections_populated=4,
    )
    assert score == 1.0


def test_score_all_empty_equals_zero() -> None:
    """All five components empty → score is exactly 0.0."""
    score = compute_context_availability_score(
        has_portfolio=False,
        news_count=0,
        events_count=0,
        alerts_count=0,
        sections_populated=0,
    )
    assert score == 0.0


def test_score_half_components_returns_roughly_half() -> None:
    """Portfolio (weight 2) + news (weight 1) = 3 / 6 = 0.5."""
    score = compute_context_availability_score(
        has_portfolio=True,
        news_count=3,
        events_count=0,
        alerts_count=0,
        sections_populated=0,
    )
    assert score == 0.5


def test_score_only_news_low_weight() -> None:
    """News alone = 1 / 6 ≈ 0.1667 — confirms portfolio carries 2x weight."""
    score = compute_context_availability_score(
        has_portfolio=False,
        news_count=5,
        events_count=0,
        alerts_count=0,
        sections_populated=0,
    )
    assert score == pytest.approx(1.0 / 6.0, abs=1e-3)


def test_score_only_portfolio_double_weight() -> None:
    """Portfolio alone = 2 / 6 ≈ 0.3333."""
    score = compute_context_availability_score(
        has_portfolio=True,
        news_count=0,
        events_count=0,
        alerts_count=0,
        sections_populated=0,
    )
    assert score == pytest.approx(2.0 / 6.0, abs=1e-3)


# ── timed_upstream_call ──────────────────────────────────────────────────────


async def test_timed_upstream_call_ok_path() -> None:
    """Successful call records an ``ok`` outcome counter increment."""
    before = _m.brief_upstream_status.labels(source="test_ok", outcome="ok")._value.get()
    async with timed_upstream_call("test_ok"):
        await asyncio.sleep(0.001)
    after = _m.brief_upstream_status.labels(source="test_ok", outcome="ok")._value.get()
    assert after == before + 1


async def test_timed_upstream_call_empty_path() -> None:
    """``mark_empty`` switches the outcome label to ``empty``."""
    before = _m.brief_upstream_status.labels(source="test_empty", outcome="empty")._value.get()
    async with timed_upstream_call("test_empty") as outcome:
        outcome.mark_empty()
    after = _m.brief_upstream_status.labels(source="test_empty", outcome="empty")._value.get()
    assert after == before + 1


async def test_timed_upstream_call_timeout_classifies_correctly() -> None:
    """``TimeoutError`` raised inside the block → outcome=timeout + re-raise."""
    before = _m.brief_upstream_status.labels(source="test_to", outcome="timeout")._value.get()
    with pytest.raises(TimeoutError):
        async with timed_upstream_call("test_to"):
            raise TimeoutError("upstream slow")
    after = _m.brief_upstream_status.labels(source="test_to", outcome="timeout")._value.get()
    assert after == before + 1


async def test_timed_upstream_call_generic_error_classifies_as_error() -> None:
    """Generic exception → outcome=error + re-raise (preserves caller catch)."""
    before = _m.brief_upstream_status.labels(source="test_err", outcome="error")._value.get()
    with pytest.raises(RuntimeError):
        async with timed_upstream_call("test_err"):
            raise RuntimeError("boom")
    after = _m.brief_upstream_status.labels(source="test_err", outcome="error")._value.get()
    assert after == before + 1


# ── record_cache_outcome ─────────────────────────────────────────────────────


def test_record_cache_outcome_hit_increments_counter() -> None:
    """``record_cache_outcome("morning", "hit")`` increments the labelled metric."""
    before = _m.brief_cache_outcome.labels(cache_name="morning", outcome="hit")._value.get()
    record_cache_outcome("morning", "hit")
    after = _m.brief_cache_outcome.labels(cache_name="morning", outcome="hit")._value.get()
    assert after == before + 1


def test_record_cache_outcome_miss_increments_counter() -> None:
    """``record_cache_outcome("morning", "miss")`` increments the labelled metric."""
    before = _m.brief_cache_outcome.labels(cache_name="morning", outcome="miss")._value.get()
    record_cache_outcome("morning", "miss")
    after = _m.brief_cache_outcome.labels(cache_name="morning", outcome="miss")._value.get()
    assert after == before + 1
