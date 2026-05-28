"""Unit tests for harness TTFT/TPS computation (PLAN-0100 W2 T-W2-02).

These tests pin the broadened TTFT semantics: the first user-visible event
defines TTFT — that includes content tokens (``token``/``delta``/``text``/
``final_answer``) AND tool-status frames (``tool_call``, ``status``).

Why this matters: on tool-using questions the first content token does not
arrive until after the tool loop + synthesis (often 60s+). Real users see
pills (``ToolCallIndicator``) render within 1-3s — that IS the first user-
visible feedback. If the harness ignores it, p95 is contaminated by the
synthesis tail and the metric stops correlating with perceived latency.

See ``docs/audits/2026-05-27-plan-0100-latency-structural.md`` §A.
"""

from __future__ import annotations

import pytest

from tests.validation.chat_eval.harness import _compute_ttft_and_tps

pytestmark = pytest.mark.unit


class TestTTFTBroadenedSemantics:
    """``_CONTENT_EVENT_KINDS`` extension verification."""

    def test_tool_call_event_defines_ttft_when_it_arrives_first(self) -> None:
        """Synthetic stream: metadata at 100ms, tool_call at 300ms, token at 5000ms.

        TTFT must pick the ``tool_call`` timestamp (0.3s), NOT the token
        timestamp (5.0s) — the pill rendering is what the user sees first.
        """
        timings = [
            ("status", 50_000),  # 0.050s — pre-tool aggregate badge
            ("metadata", 100_000),  # ignored — not user-visible
            ("tool_call", 300_000),  # 0.3s — first pill
            ("tool_result", 2_000_000),  # ignored
            ("token", 5_000_000),  # 5.0s — first content
        ]
        ttft_s, _tps, _tokens = _compute_ttft_and_tps(
            timings=timings,
            latency_s=6.0,
            answer_text="Hello world.",
            usage_output_tokens=None,
        )
        # PLAN-0100 W2: ``status`` is first in our set, so TTFT picks 0.050s.
        # (Both ``status`` and ``tool_call`` qualify; the FIRST wins.)
        assert ttft_s == pytest.approx(0.050, abs=1e-6)

    def test_status_event_defines_ttft_when_it_arrives_first(self) -> None:
        """Aggregate ``Loading <tools>…`` status at 200ms beats later content."""
        timings = [
            ("metadata", 80_000),  # not in content set — skipped
            ("status", 200_000),  # PLAN-0100: aggregate tool-status badge
            ("tool_call", 600_000),  # would also qualify, but later
            ("token", 4_500_000),
        ]
        ttft_s, _tps, _tokens = _compute_ttft_and_tps(
            timings=timings,
            latency_s=5.0,
            answer_text="x",
            usage_output_tokens=None,
        )
        assert ttft_s == pytest.approx(0.2, abs=1e-6)

    def test_metadata_only_stream_yields_nan_ttft(self) -> None:
        """If no event in _CONTENT_EVENT_KINDS arrived, TTFT is NaN."""
        timings = [
            ("metadata", 100_000),
            ("thinking", 200_000),
            ("tool_result", 1_000_000),  # not user-visible BY ITSELF
        ]
        ttft_s, _tps, _tokens = _compute_ttft_and_tps(
            timings=timings,
            latency_s=2.0,
            answer_text="",
            usage_output_tokens=None,
        )
        # NaN is unequal to itself — explicit isnan check.
        import math

        assert math.isnan(ttft_s)

    def test_pure_content_stream_still_works(self) -> None:
        """Regression: questions WITHOUT tools (pure direct-answer) still use
        the first token as TTFT — broadened semantics are additive."""
        timings = [
            ("metadata", 50_000),
            ("token", 800_000),  # 0.8s — first token
            ("token", 1_000_000),
        ]
        ttft_s, _tps, _tokens = _compute_ttft_and_tps(
            timings=timings,
            latency_s=2.0,
            answer_text="Answer body.",
            usage_output_tokens=None,
        )
        assert ttft_s == pytest.approx(0.8, abs=1e-6)
