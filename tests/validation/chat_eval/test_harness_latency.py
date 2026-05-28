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

from tests.validation.chat_eval.harness import (
    _compute_tps_streaming,
    _compute_ttft_and_tps,
    _events_to_result,
)

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


class TestBP613AnswerAssemblyFallback:
    """BP-613 — ``_events_to_result`` must fall back to streamed tokens.

    Background: in the Q8 isolated run the SSE stream emitted a full
    answer through ``token`` events but the trailing ``final_answer``
    event arrived with an empty payload. The previous logic
    (``final_answer if final_answer is not None else join(token_buf)``)
    surfaced ``answer_text=""`` — grading then verdicted USELESS even
    though the orchestrator clearly produced a coherent answer.

    The fix prefers the longer of the two when ``final_answer`` is
    missing, empty, or shorter than the token concatenation. These tests
    pin all three branches.

    Note: ``ask()`` already mints a fresh ``uuid4()`` per call
    (PLAN-0095 W3 T-W3-03 at harness.py L316), so the per-test
    thread_id isolation recommended in the audit is already in place
    and no further test-level state needs scrubbing.
    """

    def test_empty_final_answer_falls_back_to_streamed_tokens(self) -> None:
        """The Q8 reproduction case: token stream populated, final_answer empty."""
        events = [
            {"event": "token", "data": {"text": "OpenAI is connected to Microsoft "}},
            {"event": "token", "data": {"text": "via a strategic partnership."}},
            {"event": "final_answer", "data": {"text": ""}},
        ]
        result = _events_to_result(
            question="how is openai connected to microsoft?",
            status_code=200,
            events=events,
            latency_s=1.0,
        )
        assert result.answer_text == "OpenAI is connected to Microsoft via a strategic partnership."

    def test_missing_final_answer_uses_streamed_tokens(self) -> None:
        """No final_answer event at all → use joined tokens."""
        events = [
            {"event": "token", "data": {"text": "Hello "}},
            {"event": "token", "data": {"text": "world."}},
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        assert result.answer_text == "Hello world."

    def test_shorter_final_answer_loses_to_longer_token_stream(self) -> None:
        """If the provider re-emits a truncated final_answer, prefer tokens."""
        events = [
            {"event": "token", "data": {"text": "A complete answer with multiple sentences."}},
            {"event": "final_answer", "data": {"text": "A complete"}},  # truncated
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        assert result.answer_text == "A complete answer with multiple sentences."

    def test_full_final_answer_still_wins_when_present(self) -> None:
        """Regression: when final_answer is the canonical full text, use it."""
        events = [
            {"event": "token", "data": {"text": "A "}},
            {"event": "token", "data": {"text": "partial."}},
            {"event": "final_answer", "data": {"text": "A partial. Plus a synthesis paragraph."}},
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        assert result.answer_text == "A partial. Plus a synthesis paragraph."


class TestTPSStreamingSynthesisPhase:
    """PLAN-0101 W3 — ``tps_streaming`` uses the backend ``llm_synthesis_streaming``
    phase wall-clock instead of ``(e2e - ttft)``.

    These tests pin three failure modes (no data, zero wall-clock, healthy case)
    plus the end-to-end happy-path through ``_events_to_result`` (the done-event
    extraction path).
    """

    def test_healthy_synthesis_phase_yields_expected_tps(self) -> None:
        """60 tokens / 2000ms → 30 tok/s — the textbook calculation."""
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 2000.0},
            output_tokens=60,
        )
        assert tps == pytest.approx(30.0, abs=1e-6)

    def test_missing_phase_timings_yields_nan(self) -> None:
        """No ``phase_timings_ms`` dict (older backend, error path) → NaN."""
        import math

        tps = _compute_tps_streaming(phase_timings_ms={}, output_tokens=60)
        assert math.isnan(tps)

    def test_missing_synthesis_key_yields_nan(self) -> None:
        """Phase dict present but ``llm_synthesis_streaming`` absent (refusal
        path) → NaN. Other phase entries are ignored.
        """
        import math

        tps = _compute_tps_streaming(
            phase_timings_ms={"check_cache": 50.0, "entity_resolution": 200.0},
            output_tokens=60,
        )
        assert math.isnan(tps)

    def test_zero_synthesis_wall_clock_yields_nan(self) -> None:
        """Defensive divide-by-zero guard: synthesis_ms == 0 → NaN, not inf."""
        import math

        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 0.0},
            output_tokens=60,
        )
        assert math.isnan(tps)

    def test_zero_output_tokens_yields_nan(self) -> None:
        """Zero numerator must yield NaN (no data), not 0.0 — symmetric with
        the legacy ``tps`` policy.
        """
        import math

        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 2000.0},
            output_tokens=0,
        )
        assert math.isnan(tps)

    def test_events_to_result_extracts_phase_timings_from_done(self) -> None:
        """End-to-end: ``done`` event with ``phase_timings_ms`` lands on the
        ``ChatRunResult`` and ``tps_streaming`` is computed.

        60 tokens (via the metadata usage envelope) ÷ 2000 ms synthesis →
        30.0 tok/s.
        """
        events = [
            {"event": "token", "data": {"text": "Hello world."}},
            {
                "event": "metadata",
                "data": {"usage": {"output_tokens": 60}},
            },
            {
                "event": "done",
                "data": {"phase_timings_ms": {"llm_synthesis_streaming": 2000.0}},
            },
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=10.0,
        )
        assert result.phase_timings_ms == {"llm_synthesis_streaming": 2000.0}
        assert result.tps_streaming == pytest.approx(30.0, abs=1e-6)

    def test_events_to_result_done_without_phase_timings_yields_nan_streaming(self) -> None:
        """``done`` event without ``phase_timings_ms`` (older backend) → NaN."""
        import math

        events = [
            {"event": "token", "data": {"text": "Hello world."}},
            {"event": "metadata", "data": {"usage": {"output_tokens": 60}}},
            {"event": "done", "data": {}},
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=10.0,
        )
        assert result.phase_timings_ms == {}
        assert math.isnan(result.tps_streaming)


class TestAggregateTPSStreamingGate:
    """PLAN-0101 W3 — aggregate-gate threshold check.

    Imports the pure helper from ``test_aggregate_score`` so we exercise the
    real gate logic without a live rag-chat fixture.
    """

    def test_p50_below_threshold_fails_gate(self) -> None:
        """A run whose median ``tps_streaming`` is 15 tok/s must FAIL the
        20 tok/s gate.
        """
        from tests.validation.chat_eval.test_aggregate_score import _tps_streaming_gate_failures

        # Synthetic 5-question run: median = 15.0 tok/s.
        values = [10.0, 12.0, 15.0, 18.0, 22.0]
        failures = _tps_streaming_gate_failures(values)
        assert len(failures) == 1
        assert "TPS streaming p50" in failures[0]
        assert "15.00" in failures[0]

    def test_p50_above_threshold_passes_gate(self) -> None:
        """A run whose median ``tps_streaming`` is 25 tok/s must PASS."""
        from tests.validation.chat_eval.test_aggregate_score import _tps_streaming_gate_failures

        # Synthetic 5-question run: median = 25.0 tok/s.
        values = [20.0, 22.0, 25.0, 30.0, 35.0]
        failures = _tps_streaming_gate_failures(values)
        assert failures == []

    def test_all_nan_values_skip_the_gate(self) -> None:
        """When every sample is NaN (no backend phase_timings_ms anywhere),
        the gate is informational-only — no failure raised.
        """
        from tests.validation.chat_eval.test_aggregate_score import _tps_streaming_gate_failures

        nan = float("nan")
        failures = _tps_streaming_gate_failures([nan, nan, nan])
        assert failures == []
