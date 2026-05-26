"""Unit tests for PathExplanationBatchWorker throughput defaults.

Pins the tuned values applied by FIX-LIVE-HH2 (INV-LIVE-HH-2 Option 4) and
PLAN-0095 W4 T-W4-01 so a silent regression of the throughput-critical knobs
is caught at CI time instead of at the next production drain audit.

Tuning history:
  * FIX-LIVE-HH2 (2026-05-25): batch 200->300, concurrency 5->7, cycle 30->20
    → ~3.15x throughput (400 rows/hr -> 1266 rows/hr).
  * PLAN-0095 W4 (2026-05-26): cycle 20->12 to drain iter-9 backlog faster
    → 5.25x cumulative (400 rows/hr -> 2100 rows/hr).

See docs/audits/2026-05-25-iter-5-results-and-closeout.md (INV-LIVE-HH-2)
and docs/plans/0095-iter-9-pipeline-quality-plan.md (W4 T-W4-01).
"""

from __future__ import annotations

import pytest
from knowledge_graph.config import Settings

pytestmark = pytest.mark.unit


def _make_settings() -> Settings:
    """Instantiate Settings using the env defaults seeded by tests/conftest.py."""
    return Settings()  # type: ignore[call-arg]


class TestPathExplanationDefaults:
    """Pin the FIX-LIVE-HH2 + PLAN-0095 W4 tuned defaults."""

    def test_batch_size_default_is_300(self) -> None:
        # 200 -> 300: 1.5x more rows per tick.
        assert _make_settings().path_explanation_batch_size == 300

    def test_concurrency_default_is_7(self) -> None:
        # 5 -> 7: 1.4x more parallel LLM calls per tick.
        assert _make_settings().path_explanation_concurrency == 7

    def test_cycle_minutes_default_is_12(self) -> None:
        # 30 -> 20 -> 12: 2.5x more ticks per hour vs the pre-HH2 baseline.
        # Env knob: KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES.
        assert _make_settings().path_explanation_cycle_minutes == 12

    def test_combined_throughput_multiplier(self) -> None:
        """Sanity-check the ~5.25x cumulative throughput claim.

        baseline = 200 batch * 5 concurrency / 30 min = 33.3 rows/min effective
        tuned    = 300 batch * 7 concurrency / 12 min = 175 rows/min effective
        ratio    = 175 / 33.3 ≈ 5.25
        """
        s = _make_settings()
        baseline = (200 * 5) / 30.0
        tuned = (s.path_explanation_batch_size * s.path_explanation_concurrency) / s.path_explanation_cycle_minutes
        # Allow tiny float tolerance; 5.25x is the headline figure.
        assert tuned / baseline == pytest.approx(5.25, rel=0.02)


class TestPathExplanationEnvOverride:
    """T-W4-01: ensure the pydantic-settings env-prefix override path is wired.

    The Settings class uses ``env_prefix="KNOWLEDGE_GRAPH_"``; therefore an
    env var named ``KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES`` should
    override the in-code default. If this regresses (e.g. someone renames the
    field, drops the env_prefix, or adds a Field(alias=...) that breaks the
    derived name), the deployed docker.env override silently stops working
    and the path-insight backlog quietly stops draining.
    """

    def test_cycle_minutes_env_override_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Set the override BEFORE constructing Settings (pydantic-settings
        # reads env at __init__ time, not lazily).
        monkeypatch.setenv("KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES", "7")
        assert _make_settings().path_explanation_cycle_minutes == 7

    def test_batch_size_env_override_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KNOWLEDGE_GRAPH_PATH_EXPLANATION_BATCH_SIZE", "450")
        assert _make_settings().path_explanation_batch_size == 450

    def test_concurrency_env_override_applies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KNOWLEDGE_GRAPH_PATH_EXPLANATION_CONCURRENCY", "10")
        assert _make_settings().path_explanation_concurrency == 10
