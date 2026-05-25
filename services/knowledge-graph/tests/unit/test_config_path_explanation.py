"""Unit tests for PathExplanationBatchWorker throughput defaults.

Pins the tuned values applied by FIX-LIVE-HH2 (INV-LIVE-HH-2 Option 4) so a
silent regression of the throughput-critical knobs is caught at CI time
instead of at the next production drain audit.

Tuning rationale (see docs/audits/2026-05-25-iter-5-results-and-closeout.md
section INV-LIVE-HH-2):
  * batch_size 200 -> 300
  * concurrency 5  -> 7
  * cycle_minutes 30 -> 20
Together: ~3.15x throughput (400 rows/hr -> 1266 rows/hr).
"""

from __future__ import annotations

import pytest
from knowledge_graph.config import Settings

pytestmark = pytest.mark.unit


def _make_settings() -> Settings:
    """Instantiate Settings using the env defaults seeded by tests/conftest.py."""
    return Settings()  # type: ignore[call-arg]


class TestPathExplanationDefaults:
    """Pin the FIX-LIVE-HH2 tuned defaults."""

    def test_batch_size_default_is_300(self) -> None:
        # 200 -> 300: 1.5x more rows per tick.
        assert _make_settings().path_explanation_batch_size == 300

    def test_concurrency_default_is_7(self) -> None:
        # 5 -> 7: 1.4x more parallel LLM calls per tick.
        assert _make_settings().path_explanation_concurrency == 7

    def test_cycle_minutes_default_is_20(self) -> None:
        # 30 -> 20: 1.5x more ticks per hour. New env knob:
        # KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES.
        assert _make_settings().path_explanation_cycle_minutes == 20

    def test_combined_throughput_multiplier(self) -> None:
        """Sanity-check the ~3.15x throughput claim baked into the commit message.

        baseline = 200 batch * 5 concurrency / 30 min = 33.3 rows/min effective
        tuned    = 300 batch * 7 concurrency / 20 min = 105 rows/min effective
        ratio    = 105 / 33.3 ≈ 3.15
        """
        s = _make_settings()
        baseline = (200 * 5) / 30.0
        tuned = (s.path_explanation_batch_size * s.path_explanation_concurrency) / s.path_explanation_cycle_minutes
        # Allow tiny float tolerance; 3.15x is the headline figure.
        assert tuned / baseline == pytest.approx(3.15, rel=0.02)
