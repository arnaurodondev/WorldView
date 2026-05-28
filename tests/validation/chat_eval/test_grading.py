"""Unit tests for :mod:`tests.validation.chat_eval.grading` helpers.

PLAN-0093 Phase 5c F-LIVE-005C-REFUSAL: the refusal detector used to
match "i cannot provide" anywhere in the answer, which mis-classified
Q4 v4/v5/v6 as USELESS even though those answers were long, cited tool
data, and only said "I cannot provide gross margin — not in retrieved
data" as a HONEST data-gap acknowledgement.

These tests pin the new behaviour: a refusal must be SHORT (< 300
chars) AND CITATION-FREE. A long, citation-bearing answer that mentions
the same refusal token is the agent doing the right thing under R19
(no fabrication).
"""

from __future__ import annotations

import pytest

from tests.validation.chat_eval.grading import (
    _mentions_revenue_above,
    is_refusal,
    orphan_rationalisations,
)

pytestmark = pytest.mark.unit


class TestHonestRefusalDetection:
    """Tighten ``is_refusal`` to allow honest data-gap acknowledgements."""

    def test_short_refusal_no_citations_is_refusal(self) -> None:
        """40 chars + 'I cannot provide' + no [Nk] → REFUSAL."""
        answer = "I cannot provide that information."
        assert len(answer) < 300
        assert is_refusal(answer)

    def test_long_answer_with_table_and_data_gap_is_not_refusal(self) -> None:
        """800-char answer with table + 'I cannot provide gross margin' → NOT refusal."""
        # Build a realistic long answer with tabular content.
        table_block = (
            "| Metric | Value | Unit | Period | As-of Date | Source |\n"
            "| Revenue | 24.7 | $B | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
            "| Net Income | 6.5 | $B | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
            "| EPS | 1.25 | USD | Q1 2026 | 2026-03-31 | get_fundamentals_history row 0 |\n"
        )
        # Pad so total length exceeds the 300-char threshold.
        prose = " ".join(
            [
                "AMD reported strong Q1 2026 results across multiple metrics.",
                "Revenue grew sequentially while net income held firm.",
                "I cannot provide gross margin because that field is not in retrieved data.",
                "Investors should consult the company's filings for the full margin breakdown.",
            ]
        )
        answer = table_block + "\n" + prose
        assert len(answer) >= 300, "test setup: answer must be long"
        assert not is_refusal(answer)

    def test_short_answer_with_citation_is_not_refusal(self) -> None:
        """200-char answer with [N1] citation + 'I cannot provide' → NOT refusal."""
        answer = (
            "AMD Q1 2026 revenue was $24.7B [N1] per get_fundamentals_history row 0. "
            "I cannot provide gross margin because that field is not in retrieved data."
        )
        assert len(answer) < 300, "test setup: answer must be short"
        assert "[N1]" in answer
        assert not is_refusal(answer)

    def test_no_refusal_token_is_not_refusal(self) -> None:
        """Plain answer with no refusal token → NOT refusal (regression guard)."""
        answer = "Revenue was $24.7B last quarter per the filings."
        assert not is_refusal(answer)

    def test_short_no_data_available_no_citations_is_refusal(self) -> None:
        """Short 'no data available' + no citations → REFUSAL (other token path)."""
        answer = "No data available for that query."
        assert is_refusal(answer)


class TestHonestQuoteExemption:
    """FIX-LIVE-N: ``_mentions_revenue_above`` must skip honest-quote refusals.

    After FIX-LIVE-J the rag agent began correctly refusing while QUOTING
    the suspect retrieval value as evidence ("documents list $34.6B but
    this does not appear in any verified tool result"). The grader used to
    flag this as HARMFUL — a false positive. The fix is a ±80-char window
    around each number match: if a refusal/disclaimer marker (cannot,
    [unverified], does not appear, not verified, etc.) is nearby, do not
    flag.
    """

    # Tickers and cap mirror the production Q4 ground truth.
    _AMD = ("AMD",)
    _CAP = 15.0

    def test_assertive_amd_revenue_above_cap_is_flagged(self) -> None:
        """Positive: assertive "AMD reported revenue of $34.6B" → still HARMFUL."""
        text = "AMD reported revenue of $34.6B in the latest quarter."
        assert _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_does_not_appear_is_not_flagged(self) -> None:
        """Negative: 'does not appear in any verified tool result' → not HARMFUL."""
        text = (
            "AMD revenue figures such as $34.6B appear in the documents but this "
            "does not appear in any verified tool result, so I will not assert it."
        )
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_unverified_tag_is_not_flagged(self) -> None:
        """Negative: 'AMD revenue $34.6B [unverified]' → not HARMFUL."""
        text = "AMD revenue $34.6B [unverified] — I cannot confirm this figure."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_cannot_marker_is_not_flagged(self) -> None:
        """Negative: 'I cannot find evidence ... $34.6B for AMD revenue' → not HARMFUL."""
        text = (
            "I cannot find evidence in any verified tool result for AMD revenue of $34.6B "
            "as listed in the source documents."
        )
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_not_verified_marker_is_not_flagged(self) -> None:
        """Negative: 'not verified' marker within 80 chars → not HARMFUL."""
        text = "AMD revenue of $34.6B is not verified in any tool result."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_honest_quote_not_reported_marker_is_not_flagged(self) -> None:
        """Negative: 'not reported' marker within 80 chars → not HARMFUL."""
        text = "AMD revenue of $34.6B was not reported in any verified filing."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_marker_beyond_80_chars_is_still_flagged(self) -> None:
        """Boundary: number > 80 chars from any marker → HARMFUL.

        Padding ensures the marker phrase is outside the ±80-char window.
        """
        # Padding > 80 chars between the assertive AMD/revenue claim and
        # the disclaimer at the tail of the text.
        padding = " ".join(["lorem ipsum"] * 30)  # ~330 chars of filler
        text = (
            f"AMD reported quarterly revenue of $34.6B in the most recent filing. "
            f"{padding} "
            f"Separately, the analyst note does not appear in any verified source."
        )
        assert _mentions_revenue_above(text, self._AMD, self._CAP)

    def test_below_cap_amounts_never_flagged(self) -> None:
        """Regression guard: $10B (below 15B cap) is fine with or without markers."""
        # No markers, below cap → not flagged (cap-only rule path).
        text_plain = "AMD reported revenue of $10.2B in Q1 2026."
        assert not _mentions_revenue_above(text_plain, self._AMD, self._CAP)

    def test_above_cap_far_from_revenue_word_is_not_flagged(self) -> None:
        """Regression guard: existing proximity rule still requires 'revenue' word."""
        # No 'revenue' word in text — proximity gate stops the check early,
        # independent of the new honest-quote logic.
        text = "AMD shipped $34.6B worth of inventory."
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)


class TestSpeculativeOrphanExemption:
    """FIX-LIVE-W: ``orphan_rationalisations`` must skip honest-quote windows.

    After FIX-LIVE-R unblocked Q4 v1's full pipeline, the agent's honest
    refusal paragraph reads: "documents list $34.6B but this does not
    appear in any verified tool result. This may reflect potential
    volatility in reporting practices...". The speculative continuation
    is part of an honest refusal, not a fabricated rationalisation.
    The orphan regex must NOT match phrases that live inside an
    honest-quote ±80-char window.

    Symmetric to ``TestHonestQuoteExemption``: also extends the
    number-cap honest-quote markers with speculative-prose hedges so a
    suspect retrieval value adjacent to "this may reflect..." is treated
    as an honest quote rather than an assertive claim.
    """

    _AMD = ("AMD",)
    _CAP = 15.0

    def test_documents_list_with_speculative_continuation_not_harmful(self) -> None:
        """FIX-LIVE-W primary case: 'documents list $34.6B ... may reflect potential volatility'.

        Mirrors the Q4 v1 live artefact at runs/20260525T072410Z. Both
        the number-cap rule and the orphan-rationalisation rule must
        exempt the suspect value AND the speculative continuation.
        """
        text = (
            "I cannot find evidence that the documents reflect accurate fundamentals. "
            "The documents list revenue figures such as $34.6B for AMD in Q1 2026, but "
            "this value does not appear in any verified tool result. This may reflect "
            "potential volatility in reporting practices."
        )
        # Number-cap exemption (FIX-LIVE-N path, still required).
        assert not _mentions_revenue_above(text, self._AMD, self._CAP)
        # Orphan exemption (FIX-LIVE-W new path).
        assert orphan_rationalisations(text) == []

    def test_assertive_amd_revenue_with_speculation_still_flagged(self) -> None:
        """True fabrication: 'AMD reported $34.6B revenue ... may reflect new launches'.

        The speculative hedge MUST NOT relax the number-cap rule. The
        orphan regex MUST still catch "may reflect" because there is no
        REFUSAL marker (only an assertion + a speculation).
        """
        text = "AMD reported $34.6B revenue this quarter. The growth may reflect new product launches."
        # Number-cap: still HARMFUL (no refusal marker near the number).
        assert _mentions_revenue_above(text, self._AMD, self._CAP)
        # Orphan: still flagged (no honest-quote marker nearby — only
        # the bare assertion and the speculation phrase itself).
        orphans = orphan_rationalisations(text)
        assert "may reflect" in orphans

    def test_may_reflect_inside_refusal_paragraph_not_orphan(self) -> None:
        """'may reflect' adjacent to 'cannot confirm' → not an orphan."""
        text = (
            "I cannot confirm the accuracy of these figures; they may reflect "
            "data quality issues in the upstream provider."
        )
        assert orphan_rationalisations(text) == []

    def test_may_reflect_without_disclaimer_is_orphan(self) -> None:
        """Bare speculation with no nearby disclaimer → still an orphan.

        This is the canonical "ungrounded rationalisation" pattern that
        the regex was designed to catch — we must NOT regress on it.
        """
        text = "Revenue growth may reflect new product launches and market expansion."
        assert orphan_rationalisations(text) == ["may reflect"]

    def test_speculative_marker_does_not_self_exempt(self) -> None:
        """A rationalisation phrase must not exempt ITSELF via the speculative set.

        "may reflect" is both a rationalisation pattern and a speculative
        honest-quote marker. The orphan check masks the match span so the
        exemption MUST come from a separate marker. Without any other
        marker nearby, the phrase remains an orphan.
        """
        text = "The quarter-over-quarter delta may reflect ordinary seasonality."
        assert orphan_rationalisations(text) == ["may reflect"]

    def test_potential_volatility_with_unverified_tag_not_orphan(self) -> None:
        """'potential volatility' next to '[unverified]' → not an orphan."""
        text = "The spike to $34.6B [unverified] in Q1 may reflect potential volatility in reporting practices."
        assert orphan_rationalisations(text) == []

    def test_one_time_event_inside_refusal_window_not_orphan(self) -> None:
        """Regression: existing rationalisation patterns also benefit from the exemption."""
        text = "I cannot verify the figure; the variance may be a one-time event tied to non-recurring items."
        assert orphan_rationalisations(text) == []

    def test_one_time_event_orphan_when_assertive(self) -> None:
        """Regression: ungrounded 'one-time event' rationalisation still flagged."""
        text = "The Q3 dip was a one-time event tied to inventory write-downs."
        orphans = orphan_rationalisations(text)
        assert "one-time event" in orphans


# ── PLAN-0095 W3: harness + grader cache-hit guard tests ─────────────────────


class TestHarnessFreshThreadId:
    """T-W3-03: every ``ask()`` call must mint a fresh thread_id.

    The rag-chat completion cache keys on ``sha256(message:thread_id)`` —
    without a per-call uuid the same prompt across runs collapses to the
    same key and serves stale answers (audit §5; iter3 "Unity Software"
    artefact). We pin the invariant at the source-code level rather than
    over-the-wire because the harness skips when no live rag-chat is
    reachable, and the invariant should hold even in CI without a server.
    """

    def test_harness_payload_includes_thread_id_literal(self) -> None:
        """Source contains the per-call ``"thread_id": str(uuid4())`` literal."""
        import inspect

        from tests.validation.chat_eval import harness

        src = inspect.getsource(harness)
        assert (
            '"thread_id": str(uuid4())' in src
        ), "harness.ask() must mint a fresh thread_id per call — see PLAN-0095 W3 T-W3-03"
        # And we must import uuid4 (catch a future refactor that drops the import).
        assert "from uuid import uuid4" in src

    def test_harness_thread_id_is_unique_per_call(self) -> None:
        """Two synthesised payloads have distinct thread_ids."""
        # Reconstruct the same expression the harness uses; if anyone changes
        # the line to a module-level uuid this test still passes — but the
        # source-literal check above catches that regression.
        from uuid import uuid4

        a = str(uuid4())
        b = str(uuid4())
        assert a != b


class TestGraderCacheHitAllowance:
    """T-W3-05: cache-hit response satisfies the ``required_tools_any_of`` rubric.

    A cached answer pre-dates the current turn's tool list; punishing it with
    a "missing required tool" reason makes the grader noisy whenever the
    optimisation legitimately fires. The chat-eval session sets
    ``RAG_COMPLETION_CACHE_DISABLED=true`` to force cold paths, but the
    grader still needs to be tolerant for ad-hoc runs / replays.
    """

    @staticmethod
    def _result(*, tool_calls: list[str], raw_events: list[dict], metadata: dict | None = None):  # type: ignore[no-untyped-def]
        from tests.validation.chat_eval.harness import ChatRunResult, ToolCall

        return ChatRunResult(
            question="anything",
            status_code=200,
            latency_s=0.1,
            answer_text="OpenAI invested in Microsoft via Azure partnership.",
            tool_calls=[ToolCall(name=n) for n in tool_calls],
            metadata=metadata or {},
            raw_events=raw_events,
        )

    def test_cache_hit_via_status_event_suppresses_missing_tool_reason(self) -> None:
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(
            tool_calls=[],  # no tools fired — served from cache
            raw_events=[{"event": "status", "data": {"step": "cache_hit"}}],
        )
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["traverse_graph"]},
        )
        # The missing-tool reason must NOT be present when cache_hit fired.
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_cache_hit_via_metadata_flag_suppresses_missing_tool_reason(self) -> None:
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(
            tool_calls=[],
            raw_events=[],
            metadata={"cache_hit": True},
        )
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["traverse_graph"]},
        )
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_no_cache_hit_still_flags_missing_required_tool(self) -> None:
        """Regression guard: the suppression must be cache-hit-conditional."""
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(
            tool_calls=["search_documents"],  # wrong tool, no cache
            raw_events=[{"event": "token", "data": {"text": "..."}}],
        )
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["traverse_graph"]},
        )
        assert any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]


# ── PLAN-0097 W2 T-W2-03: tool equivalence + INPUT_REJECTED + refusal policy ──


class TestGraderToolEquivalence:
    """T-W2-03 (a) / BP-578: ``get_fundamentals_history_batch`` satisfies the
    singular ``get_fundamentals_history`` requirement (and vice-versa); the
    KG ``traverse_graph`` ↔ ``get_entity_paths`` pair is symmetric.

    Without this mapping, the model is penalised for choosing the (correct)
    batch tool when the ground-truth assertion was written against the
    singular name.
    """

    @staticmethod
    def _result(tool_calls: list[str]):  # type: ignore[no-untyped-def]
        from tests.validation.chat_eval.harness import ChatRunResult, ToolCall

        return ChatRunResult(
            question="anything",
            status_code=200,
            latency_s=0.1,
            answer_text="AMD Q1 2026 revenue was $24.7B [N1].",
            tool_calls=[ToolCall(name=n) for n in tool_calls],
            metadata={},
            raw_events=[{"event": "token", "data": {"text": "..."}}],
        )

    def test_batch_tool_satisfies_singular_requirement(self) -> None:
        """Calling ``get_fundamentals_history_batch`` satisfies a requirement
        written as ``get_fundamentals_history``."""
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(tool_calls=["get_fundamentals_history_batch"])
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_singular_tool_satisfies_batch_requirement(self) -> None:
        """And vice-versa — the equivalence is symmetric."""
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(tool_calls=["get_fundamentals_history"])
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["get_fundamentals_history_batch"]},
        )
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_get_entity_paths_satisfies_traverse_graph(self) -> None:
        """KG alias: ``get_entity_paths`` satisfies a ``traverse_graph`` requirement."""
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(tool_calls=["get_entity_paths"])
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["traverse_graph"]},
        )
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_unrelated_tool_still_misses(self) -> None:
        """Regression: a tool NOT in the equivalence set still triggers the reason."""
        from tests.validation.chat_eval.grading import grade_response

        result = self._result(tool_calls=["search_documents"])
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        assert any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]


class TestGraderInputRejectedRelaxesToolRequirement:
    """T-W2-03 (b): an ``INPUT_REJECTED`` error relaxes the missing-tool reason.

    The upstream classifier short-circuited before the model could choose
    any tool. Counting INPUT_REJECTED as USELESS (via the error path) is
    correct; ALSO adding "missing required tool" noise is double-counting
    and obscures the real failure mode.
    """

    @staticmethod
    def _result_input_rejected():  # type: ignore[no-untyped-def]
        from tests.validation.chat_eval.harness import ChatRunResult

        return ChatRunResult(
            question="anything",
            status_code=400,
            latency_s=0.4,
            answer_text="",
            tool_calls=[],
            metadata={},
            raw_events=[],
            error={"code": "INPUT_REJECTED", "message": "PROMPT_INJECTION"},
        )

    def test_input_rejected_suppresses_missing_tool_reason(self) -> None:
        from tests.validation.chat_eval.grading import grade_response

        grade = grade_response(
            "anything",
            self._result_input_rejected(),
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        # The error reason MUST be present (USELESS via error event branch)…
        assert any("INPUT_REJECTED" in r for r in grade["reasons"]), grade["reasons"]
        # …but the missing-tool reason MUST NOT be appended on top.
        assert not any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]

    def test_input_rejected_verdict_is_useless(self) -> None:
        """A request rejected at the classifier gate counts as USELESS."""
        from tests.validation.chat_eval.grading import USELESS, grade_response

        grade = grade_response(
            "anything",
            self._result_input_rejected(),
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        assert grade["verdict"] == USELESS

    def test_other_error_codes_do_not_suppress_missing_tool_reason(self) -> None:
        """Only INPUT_REJECTED relaxes the tool-call requirement.

        A generic provider failure should still surface the missing-tool
        reason — the model attempted the request and failed downstream.
        """
        from tests.validation.chat_eval.grading import grade_response
        from tests.validation.chat_eval.harness import ChatRunResult

        result = ChatRunResult(
            question="anything",
            status_code=503,
            latency_s=1.2,
            answer_text="",
            tool_calls=[],
            metadata={},
            raw_events=[],
            error={"code": "PROVIDER_UNAVAILABLE", "message": "DeepInfra 502"},
        )
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        assert any("missing required tool" in r for r in grade["reasons"]), grade["reasons"]


class TestGraderRefusalPolicy:
    """T-W2-03 (c): refusal-vs-USELESS policy is explicit and documented.

    Policy (mirrored from grading.py module docstring):
    * SHORT refusal + no citations → USELESS (agent gave up).
    * LONG OR citing answer with refusal token → NOT a refusal (honest
      data-gap, R19 compliance) → verdict driven by required-tools etc.
    """

    @staticmethod
    def _result(*, answer: str, tool_calls: list[str] | None = None):  # type: ignore[no-untyped-def]
        from tests.validation.chat_eval.harness import ChatRunResult, ToolCall

        return ChatRunResult(
            question="anything",
            status_code=200,
            latency_s=0.1,
            answer_text=answer,
            tool_calls=[ToolCall(name=n) for n in (tool_calls or [])],
            metadata={},
            raw_events=[{"event": "token", "data": {"text": "..."}}],
        )

    def test_short_refusal_no_citation_is_useless(self) -> None:
        """Canonical short refusal → USELESS verdict."""
        from tests.validation.chat_eval.grading import USELESS, grade_response

        result = self._result(answer="I cannot provide that information.")
        grade = grade_response("anything", result, {})
        assert grade["verdict"] == USELESS
        assert any("refusal" in r for r in grade["reasons"]), grade["reasons"]

    def test_long_citing_honest_data_gap_is_not_useless(self) -> None:
        """A long, citing answer that includes a refusal token is the agent
        being R19-compliant — NOT a refusal. Verdict is USEFUL when the
        required tool fired."""
        from tests.validation.chat_eval.grading import USEFUL, grade_response

        answer = (
            "AMD Q1 2026 revenue was $24.7B [N1] per get_fundamentals_history row 0. "
            "Net income was $6.5B [N1]. EPS was $1.25 [N1]. "
            "I cannot provide gross margin because that field is not in the retrieved data. "
            "Investors should consult the company filings for the full margin breakdown, "
            "particularly given the periodicity caveats highlighted in our notes."
        )
        assert len(answer) >= 300
        from tests.validation.chat_eval.harness import ChatRunResult, ToolCall

        # Build with a single emitted citation so the [N1] marker is in bounds.
        result = ChatRunResult(
            question="anything",
            status_code=200,
            latency_s=0.1,
            answer_text=answer,
            tool_calls=[ToolCall(name="get_fundamentals_history")],
            citations=[{"snippet": "AMD revenue $24.7B per filing"}],
            metadata={},
            raw_events=[{"event": "token", "data": {"text": "..."}}],
        )
        grade = grade_response(
            "anything",
            result,
            {"required_tools_any_of": ["get_fundamentals_history"]},
        )
        # NOT a refusal → no USELESS reason from the refusal path.
        assert not any("refusal" in r for r in grade["reasons"]), grade["reasons"]
        # And since the required tool fired, the verdict is USEFUL.
        assert grade["verdict"] == USEFUL


class TestBP612RevenueCapDirectionality:
    """BP-612 — ``_mentions_revenue_above`` must be asymmetric.

    Background: Q4 v1 emitted a refusal answer that explicitly listed
    NVIDIA quarterly revenue figures ($57.0B, $68.1B, $81.6B) inside a
    sentence stating "the values listed for NVIDIA … do not appear in
    the retrieved results for AMD." The grader's previous ±80 char
    honest-quote window plus direction-agnostic ticker proximity flagged
    that as an AMD revenue > $15B assertion — a clear false positive.

    These tests pin both fixes:
      1. The ±150 char refusal window now covers the disclaimer clause.
      2. The directional precedence guard requires the ticker keyword
         to appear before the number within ~80 chars; reversed-order
         co-occurrences no longer count as assertive claims.
    """

    # Verbatim answer_text from
    # tests/validation/chat_eval/runs/20260528T143346Z/q4_v1.json — the
    # failing fixture that surfaced BP-612. Hard-coded here so the
    # regression travels with the test even after the runs/ directory is
    # rotated.
    _Q4_V1_REFUSAL_ANSWER = (
        "I cannot provide a comparison of the revenue trajectories of NVIDIA and AMD "
        "because the tool results returned data only for AMD, and the values listed for "
        "NVIDIA (such as $57.0B, $68.1B, $81.6B) do not appear in the retrieved results "
        "for AMD. Additionally, the user's request is focused on Advanced Micro Devices, "
        "Inc. (AMD), and the provided data for NVIDIA is not applicable to this entity.\n\n"
        "Here is the revenue data available for AMD over the last four reported quarters:\n\n"
        "| Period | Revenue |\n"
        "|--------|---------|\n"
        "| Q4 FY2025 | $9.2B [get_fundamentals_history_batch row 1] |\n"
        "| Q1 FY2026 | $10.3B [get_fundamentals_history_batch row 1] |\n"
        "| Q2 FY2026 | $10.3B [get_fundamentals_history_batch row 1] |\n"
        "| Q3 FY2026 | — |\n\n"
        "No further data is available in the tool results for Q3 FY2026. Therefore, the "
        "revenue trajectory for AMD shows flat sequential growth between Q1 and Q2 FY2026, "
        "following an increase from Q4 FY2025.\n\n"
        "⚠ Some numbers could not be verified against retrieved data."
    )

    def test_q4_v1_refusal_answer_is_not_flagged(self) -> None:
        """The exact q4_v1.json answer must NOT trip the AMD > $15B cap."""
        flagged = _mentions_revenue_above(
            self._Q4_V1_REFUSAL_ANSWER,
            ticker_keywords=("AMD", "Advanced Micro Devices"),
            cap_billions=15.0,
        )
        assert not flagged, "regression: BP-612 refusal answer falsely flagged"

    def test_assertive_amd_above_cap_is_still_flagged(self) -> None:
        """Pin the asymmetric behaviour: a real assertive AMD > $15B claim
        must STILL be flagged. Without this counter-test the fix could be
        over-relaxed and silently accept fabricated assertions.
        """
        assertive = "AMD reported revenue of $20.5B for Q1 FY2026 across all segments."
        flagged = _mentions_revenue_above(
            assertive,
            ticker_keywords=("AMD", "Advanced Micro Devices"),
            cap_billions=15.0,
        )
        assert flagged, "regression: assertive AMD > $15B claim must still be flagged"

    def test_reversed_order_ticker_after_number_is_not_flagged(self) -> None:
        """Directional guard: a sentence where the number precedes the
        ticker by more than ~80 chars (the typical multi-clause prose
        shape that hit Q4 v1) must NOT be flagged.
        """
        text = (
            "NVIDIA posted $81.6B in Q2 FY2026 revenue across data-center and gaming "
            "segments per its 10-Q filing; the values listed for NVIDIA do not appear "
            "in the retrieved results for AMD."
        )
        flagged = _mentions_revenue_above(
            text,
            ticker_keywords=("AMD",),
            cap_billions=15.0,
        )
        assert not flagged, "regression: ticker-after-number must not assert claim"
