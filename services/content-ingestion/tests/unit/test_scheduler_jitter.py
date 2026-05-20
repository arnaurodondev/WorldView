"""Unit tests for scheduler startup jitter helper (BUG-008 / BP-491).

The scheduler computes a deterministic per-source startup offset based on
md5(source_name) so the 4 source adapters (EODHD, SEC EDGAR, Finnhub,
NewsAPI) don't all tick at the same wall-clock instant. These tests pin:

1. The 4 production source names produce **distinct** offsets that fall
   within ``[0, interval_seconds // 4)`` at a realistic 15-minute interval.
2. The helper is fully deterministic (same args → same result).
3. Edge cases for ``interval_seconds`` of 0 and 1 return 0.
"""

from __future__ import annotations

import pytest
from content_ingestion.infrastructure.scheduler.scheduler import _startup_offset_seconds

pytestmark = pytest.mark.unit


class TestStartupOffsetSeconds:
    @pytest.mark.parametrize("source_name", ["eodhd", "sec_edgar", "finnhub", "newsapi"])
    def test_offset_within_quarter_window(self, source_name: str) -> None:
        """Each production source's offset lies in ``[0, interval/4)``."""
        interval = 900  # 15 minutes — matches the production default
        offset = _startup_offset_seconds(source_name, interval)
        assert 0 <= offset < interval // 4

    def test_production_sources_offsets_are_distinct(self) -> None:
        """All 4 production sources land in different slots — no thundering herd."""
        interval = 900
        offsets = {
            name: _startup_offset_seconds(name, interval) for name in ("eodhd", "sec_edgar", "finnhub", "newsapi")
        }
        # All 4 values must be unique; if any two collide the staggering is broken
        assert len(set(offsets.values())) == 4, f"offsets collided: {offsets}"

    def test_deterministic_across_calls(self) -> None:
        """Calling the helper twice with the same args returns the same value."""
        first = _startup_offset_seconds("eodhd", 900)
        second = _startup_offset_seconds("eodhd", 900)
        assert first == second

    def test_zero_interval_returns_zero(self) -> None:
        """Defensive: a 0 interval can't be divided into slots → offset is 0."""
        assert _startup_offset_seconds("x", 0) == 0

    def test_one_second_interval_returns_zero(self) -> None:
        """span = max(1, 1//4) = 1 → the only valid slot is 0."""
        assert _startup_offset_seconds("x", 1) == 0

    def test_negative_interval_returns_zero(self) -> None:
        """Defensive guard against accidentally configured negative intervals."""
        assert _startup_offset_seconds("x", -10) == 0
