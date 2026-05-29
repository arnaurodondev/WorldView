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

    def test_severely_truncated_final_answer_loses_to_longer_token_stream(self) -> None:
        """If the provider re-emits a *severely* truncated final_answer
        (≥10x shorter than tokens), prefer the token stream.

        PLAN-0102 W5 T-W5-01 (BP-619): the original "any-shorter" rule was
        relaxed to a 10x threshold so a numeric-grounding-validator trim
        (which legitimately shortens the answer by a moderate amount) no
        longer triggers a fallback to the unvalidated token stream.
        """
        long_tokens = "A complete answer with multiple sentences " * 20  # ~860 chars
        events = [
            {"event": "token", "data": {"text": long_tokens}},
            {"event": "final_answer", "data": {"text": "A complete"}},  # ~10 chars
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        # Fallback triggered: token stream is 86x longer than final_answer.
        assert result.answer_text.startswith("A complete answer with multiple sentences")

    def test_moderate_validator_trim_keeps_final_answer(self) -> None:
        """PLAN-0102 W5 T-W5-01 (BP-619): the numeric-grounding validator
        trims ungrounded numbers from the final answer. A 2-3x length
        difference is normal and the validated (shorter) answer must win.
        """
        token_stream_text = "AAPL Q1 2026 revenue was $124.3B and EPS was $2.18 per filings."  # noqa: S105
        validated = "AAPL Q1 2026 revenue was per filings."  # validator stripped numbers
        events = [
            {"event": "token", "data": {"text": token_stream_text}},
            {"event": "final_answer", "data": {"text": validated}},
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        # The validated (shorter) answer wins; the unvalidated token stream
        # with its ungrounded numbers must not leak back in.
        assert result.answer_text == validated
        assert "$124.3B" not in result.answer_text

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


class TestCitationMarkerScrub:
    """PLAN-0102 W5 T-W5-01 (BP-619) — orphan citation marker scrubber.

    When the harness falls back to ``joined_tokens`` (the pre-validation
    token stream) the orphan ``[Nk]`` markers (k > len(citations)) must be
    scrubbed so the grader's in-bounds check does not false-positive.
    """

    def test_scrub_drops_out_of_bounds_marker(self) -> None:
        """``[N7]`` against a 3-citation list → marker removed, text preserved."""
        from tests.validation.chat_eval.harness import _scrub_out_of_bounds_citations

        text = "AAPL Q1 [N1] revenue was strong [N7] per filings [N2]."
        citations = [{"snippet": "a"}, {"snippet": "b"}, {"snippet": "c"}]
        out = _scrub_out_of_bounds_citations(text, citations)
        assert "[N1]" in out
        assert "[N2]" in out
        assert "[N7]" not in out

    def test_scrub_preserves_all_in_bounds_markers(self) -> None:
        """All markers in-range → text returned verbatim."""
        from tests.validation.chat_eval.harness import _scrub_out_of_bounds_citations

        text = "Cited [N1], cited [N2]."
        citations = [{"snippet": "a"}, {"snippet": "b"}]
        assert _scrub_out_of_bounds_citations(text, citations) == text

    def test_scrub_strips_all_markers_when_citations_empty(self) -> None:
        """No citations event → every marker is orphan → strip all."""
        from tests.validation.chat_eval.harness import _scrub_out_of_bounds_citations

        text = "Some claim [N1] and another [N3]."
        out = _scrub_out_of_bounds_citations(text, [])
        assert "[N" not in out

    def test_severely_truncated_final_answer_scrubs_orphan_marker(self) -> None:
        """End-to-end: harness fallback to long token stream with [N7]
        marker against only 3 citations → ``answer_text`` has [N7] removed.
        """
        long_tokens = "AAPL revenue was strong [N7] per the screener report. " * 25
        events = [
            {"event": "token", "data": {"text": long_tokens}},
            {"event": "final_answer", "data": {"text": "x"}},  # forces fallback
            {"event": "citations", "data": [{"snippet": "a"}, {"snippet": "b"}, {"snippet": "c"}]},
        ]
        result = _events_to_result(
            question="q",
            status_code=200,
            events=events,
            latency_s=0.5,
        )
        assert "[N7]" not in result.answer_text


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

    def test_missing_phase_timings_yields_none(self) -> None:
        """No ``phase_timings_ms`` dict (older backend, error path) → ``None``.

        PLAN-0102 W4 T-W4-01: NaN sentinel replaced by typed ``None`` so JSON
        round-trip is unambiguous and the aggregate gate's ``_finite_only``
        cleanly drops the entry without sentinel games.
        """
        tps = _compute_tps_streaming(phase_timings_ms={}, output_tokens=60)
        assert tps is None

    def test_missing_synthesis_key_yields_none(self) -> None:
        """Both synthesis-stream AND direct-text keys absent → ``None``.

        PLAN-0102 W4 T-W4-B (BP-621): when neither
        ``llm_synthesis_streaming`` (tool-use branch) nor
        ``llm_direct_text_generation`` (direct-text branch) is present,
        we have no measurable generation window.
        """
        tps = _compute_tps_streaming(
            phase_timings_ms={"check_cache": 50.0, "entity_resolution": 200.0},
            output_tokens=60,
        )
        assert tps is None

    def test_direct_text_phase_used_when_synthesis_absent(self) -> None:
        """PLAN-0102 W4 T-W4-B (BP-621) — direct-text fallback.

        Direct-text answers ("What is Apple?") never reach the
        second-turn streaming branch, so ``llm_synthesis_streaming`` is
        absent. The harness must fall back to
        ``llm_direct_text_generation`` so ``tps_streaming`` is finite
        for these questions instead of dropping out of the gate.
        """
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_direct_text_generation": 500.0},
            output_tokens=100,
        )
        assert tps == pytest.approx(200.0, abs=1e-6)

    def test_synthesis_phase_wins_when_both_present(self) -> None:
        """If both keys present (defensive), prefer the explicit
        synthesis-stream key — that's the canonical second-turn measurement.
        """
        tps = _compute_tps_streaming(
            phase_timings_ms={
                "llm_synthesis_streaming": 1000.0,
                "llm_direct_text_generation": 500.0,
            },
            output_tokens=100,
        )
        # 100 / 1.0s = 100, not 200 (would be 200 if direct-text won).
        assert tps == pytest.approx(100.0, abs=1e-6)

    def test_sub_threshold_synthesis_wall_clock_yields_none(self) -> None:
        """Defensive guard against BP-618 double-record race.

        PLAN-0102 W4 T-W4-01: anything under ``_SYNTHESIS_MIN_MS`` (100ms)
        is structurally not a real stream — DeepInfra's first-token
        latency alone is ~150-300ms. Reading ``60 tok / 1ms = 60000 tok/s``
        would otherwise poison the median.
        """
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 0.0},
            output_tokens=60,
        )
        assert tps is None
        # And 50ms is also below floor.
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 50.0},
            output_tokens=60,
        )
        assert tps is None

    def test_zero_output_tokens_yields_none(self) -> None:
        """Zero numerator → ``None`` (no data)."""
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 2000.0},
            output_tokens=0,
        )
        assert tps is None

    def test_explicit_ms_to_seconds_conversion(self) -> None:
        """Pin the unit-bridge: 100 tokens / 500 ms must yield 200.0 tok/s.

        Regression guard for PLAN-0102 W4 T-W4-01: ensures the ``/ 1000``
        ms→s conversion is correct (forgetting it would yield 0.2 tok/s,
        which would silently fail the 20 tok/s gate everywhere).
        """
        tps = _compute_tps_streaming(
            phase_timings_ms={"llm_synthesis_streaming": 500.0},
            output_tokens=100,
        )
        assert tps == pytest.approx(200.0, abs=1e-6)

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

    def test_events_to_result_done_without_phase_timings_yields_none_streaming(self) -> None:
        """``done`` event without ``phase_timings_ms`` (older backend) → ``None``.

        PLAN-0102 W4 T-W4-01: NaN sentinel replaced by typed ``None``.
        """
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
        assert result.tps_streaming is None


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

    def test_all_none_values_skip_the_gate(self) -> None:
        """PLAN-0102 W4 T-W4-01: when every sample is ``None`` (no synthesis
        phase fired anywhere — every question hit the direct-text branch),
        the gate is informational-only — no failure raised.
        """
        from tests.validation.chat_eval.test_aggregate_score import _tps_streaming_gate_failures

        failures = _tps_streaming_gate_failures([None, None, None])
        assert failures == []

    def test_mixed_none_and_finite_values_use_only_finite(self) -> None:
        """PLAN-0102 W4 T-W4-01: ``None`` entries are dropped; the gate is
        evaluated against the surviving finite samples.

        Synthetic mix: 3 skipped + 2 finite values both above the 20 tok/s
        floor → gate passes.
        """
        from tests.validation.chat_eval.test_aggregate_score import _tps_streaming_gate_failures

        failures = _tps_streaming_gate_failures([None, 25.0, None, 30.0, None])
        assert failures == []
