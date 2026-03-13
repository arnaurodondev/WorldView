"""Tests for Watermark entity — monotonic advancement, SHA dedup, backfill state machine."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from market_ingestion.domain.entities.watermark import Watermark
from market_ingestion.domain.enums import BackfillStatus
from market_ingestion.domain.errors import InvalidStateTransition, WatermarkViolation

UTC = UTC


def _watermark(**kwargs: object) -> Watermark:
    return Watermark(
        provider="eodhd",
        dataset_type="ohlcv",
        symbol="AAPL",
        **kwargs,  # type: ignore[arg-type]
    )


# ── Natural key ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_natural_key_is_6_tuple() -> None:
    wm = _watermark(variant="annual", exchange="NASDAQ", timeframe="1d")
    key = wm.natural_key
    assert len(key) == 6
    assert key == ("eodhd", "ohlcv", "annual", "AAPL", "NASDAQ", "1d")


@pytest.mark.unit
def test_natural_key_with_none_fields() -> None:
    wm = _watermark()
    key = wm.natural_key
    assert key == ("eodhd", "ohlcv", None, "AAPL", None, None)


# ── Monotonic bar_ts advancement ─────────────────────────────────────────────


@pytest.mark.unit
def test_advance_bar_ts_from_none() -> None:
    wm = _watermark()
    ts = datetime(2024, 6, 1, tzinfo=UTC)
    wm.advance_bar_ts(ts)
    assert wm.current_bar_ts == ts


@pytest.mark.unit
def test_advance_bar_ts_strictly_forward() -> None:
    wm = _watermark()
    t1 = datetime(2024, 1, 1, tzinfo=UTC)
    t2 = datetime(2024, 6, 1, tzinfo=UTC)
    wm.advance_bar_ts(t1)
    wm.advance_bar_ts(t2)
    assert wm.current_bar_ts == t2


@pytest.mark.unit
def test_advance_bar_ts_same_value_raises() -> None:
    wm = _watermark()
    ts = datetime(2024, 6, 1, tzinfo=UTC)
    wm.advance_bar_ts(ts)
    with pytest.raises(WatermarkViolation):
        wm.advance_bar_ts(ts)


@pytest.mark.unit
def test_advance_bar_ts_regression_raises() -> None:
    wm = _watermark()
    t1 = datetime(2024, 6, 1, tzinfo=UTC)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    wm.advance_bar_ts(t1)
    with pytest.raises(WatermarkViolation, match="not strictly after"):
        wm.advance_bar_ts(t0)


@pytest.mark.unit
def test_advance_bar_ts_updates_updated_at() -> None:
    wm = _watermark()
    before = wm.updated_at
    wm.advance_bar_ts(datetime(2024, 6, 1, tzinfo=UTC))
    assert wm.updated_at >= before


# ── SHA-256 dedup ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_has_changed_returns_true_when_different_hash() -> None:
    wm = _watermark()
    wm.content_hash = "abc123"
    assert wm.has_changed("def456") is True


@pytest.mark.unit
def test_has_changed_returns_false_when_same_hash() -> None:
    wm = _watermark()
    wm.content_hash = "abc123"
    assert wm.has_changed("abc123") is False


@pytest.mark.unit
def test_has_changed_returns_true_when_hash_is_none() -> None:
    wm = _watermark()
    assert wm.has_changed("anyhash") is True


# ── Backfill state machine ────────────────────────────────────────────────────


@pytest.mark.unit
def test_backfill_initial_status_is_pending() -> None:
    wm = _watermark()
    assert wm.backfill_status == BackfillStatus.PENDING


@pytest.mark.unit
def test_start_backfill_transitions_to_in_progress() -> None:
    wm = _watermark()
    wm.start_backfill()
    assert wm.backfill_status == BackfillStatus.IN_PROGRESS


@pytest.mark.unit
def test_complete_backfill_transitions_to_completed() -> None:
    wm = _watermark()
    wm.start_backfill()
    wm.complete_backfill()
    assert wm.backfill_status == BackfillStatus.COMPLETED


@pytest.mark.unit
def test_start_backfill_from_in_progress_raises() -> None:
    wm = _watermark()
    wm.start_backfill()
    with pytest.raises(InvalidStateTransition, match="PENDING"):
        wm.start_backfill()


@pytest.mark.unit
def test_complete_backfill_from_pending_raises() -> None:
    wm = _watermark()
    with pytest.raises(InvalidStateTransition, match="IN_PROGRESS"):
        wm.complete_backfill()


@pytest.mark.unit
def test_watermark_id_is_ulid_string() -> None:
    wm = _watermark()
    assert isinstance(wm.id, str)
    assert len(wm.id) == 26
