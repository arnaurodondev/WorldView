"""PLAN-0104 W28-5 / BP-648 — rewrite-path guard regression tests.

These tests cover ``ChatOrchestratorUseCase._run_grounding_validation``
directly (no end-to-end streaming) because the surface under test is the
two new defensive branches added in W28-5:

  1. Skip the rewrite entirely when the unsupported set is dominated
     (>=80%) by single-digit REVENUE classifications — those are almost
     always validator mis-classifications of quarter labels (BP-647).

  2. Reject a rewrite that opens with "I cannot" / "I am unable" AND is
     materially shorter than the original answer — the LLM has
     produced a defeatist refusal rather than fixing numbers.

We patch the validator output directly so the tests are deterministic
and decoupled from the classifier's tolerance table.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Fakes ────────────────────────────────────────────────────────────────────


@dataclass
class _FakeUnsupported:
    """Mimics ``UnsupportedNumber`` for the small subset of fields used."""

    value: float
    field_kind: Any  # FieldKind enum
    tolerance_used: float = 0.05
    closest_tool_value: float | None = None
    snippet: str = "snippet"


@dataclass
class _FakeResult:
    passed: bool
    unsupported: tuple[_FakeUnsupported, ...] = ()


def _make_orchestrator() -> Any:
    """Build a use-case instance with no-op pipeline / factory dependencies."""
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    pipeline = MagicMock()
    factory = MagicMock()
    return ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)


def _make_pipeline_with_stream(rewrite_text: str) -> MagicMock:
    """Build a pipeline mock whose llm_chain.stream_chat yields ``rewrite_text``."""
    p = MagicMock()
    p.llm_chain = MagicMock()

    async def _stream(*_a: Any, **_kw: Any):
        yield rewrite_text

    p.llm_chain.stream_chat = _stream
    return p


def _make_budget() -> Any:
    b = MagicMock()
    b.max_tokens_final = 256
    return b


def _nonempty_pool() -> list[Any]:
    """A tool-item list with at least one structured numeric value.

    These tests patch ``NumericGroundingValidator`` to control the validate()
    verdicts, so the item content is irrelevant to the validator. But the
    2026-06-12 Theme-A empty-pool refusal gate runs the REAL flatten helper on
    ``tool_items`` BEFORE the validator — so the pool must be non-empty, else the
    gate refuses up front and the rewrite-guard branches under test never run.
    """
    from rag_chat.application.services.numeric_grounding import FieldKind

    item = MagicMock()
    item.text = "tool row"
    item.value = 181.5e9
    item.field_kind = FieldKind.REVENUE
    item.citation_meta = None
    item.item_id = "tool:fundamentals:AAPL"
    return [item]


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRewriteSkippedForSingleDigitRevenue:
    """W28-5 guard A — skip rewrite when >=80% unsupported is small REVENUE.

    PLAN-0104 W44 amendment: the banner is now SUPPRESSED in this branch
    because the small-revenue pattern is a validator FALSE POSITIVE (BP-648)
    — the original answer is actually fine. Appending the banner was
    misleading the judge into scoring grounding=0 (R6) and the user into
    distrusting an actually-correct answer. The test now pins the
    suppressed-banner behaviour; the rewrite is still skipped (the value
    of the guard is unchanged).
    """

    def test_eight_of_ten_single_digit_revenue_skips_rewrite_and_suppresses_banner(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        # 8 small-revenue + 2 EPS = 80% ratio → should hit the guard.
        unsupported = (
            *(_FakeUnsupported(value=float(v), field_kind=FieldKind.REVENUE) for v in (1, 2, 3, 2, 3, 4, 1, 2)),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
            _FakeUnsupported(value=5.11, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)

        orch = _make_orchestrator()
        original_response = "Q2 2026 revenue rose strongly with EPS at $7.14 [1]."
        pipeline = _make_pipeline_with_stream(rewrite_text="I cannot answer that.")

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.return_value = first

            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=original_response,
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                )
            )

        # Validator called exactly once — rewrite was skipped.
        assert v_inst.validate.call_count == 1
        # W44 — original returned UNCHANGED (passed=True flag, no banner).
        assert passed is True
        assert text == original_response
        assert "could not be verified" not in text


class TestDefeatistRewriteRejected:
    """W28-5 guard B — refusal-shorter-than-original rewrite is rejected."""

    def test_defeatist_short_rewrite_falls_back_to_original(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        # Mixed unsupported set — does NOT trip the small-revenue guard so
        # the rewrite branch runs.
        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=False, unsupported=unsupported)

        orch = _make_orchestrator()
        original_response = (
            "Apple Q3 revenue was $181.5B [1] and EPS came in at $7.14 [2]. "
            "Year-over-year growth accelerated meaningfully."
        )
        defeatist_rewrite = "I cannot answer that."  # Much shorter than original.
        pipeline = _make_pipeline_with_stream(rewrite_text=defeatist_rewrite)

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.side_effect = [first, second]

            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=original_response,
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                )
            )

        assert passed is False
        # The defeatist text must NOT be in the final answer.
        assert "I cannot answer that" not in text
        assert original_response in text
        assert "could not be verified" in text

    def test_long_rewrite_starting_with_i_cannot_still_processed(self) -> None:
        """A long rewrite that happens to start with 'I cannot' but is not shorter
        than the original passes through to the standard re-validation path.
        """
        from rag_chat.application.services.numeric_grounding import FieldKind

        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        # Second pass passes → returns rewrite directly.
        second = _FakeResult(passed=True, unsupported=())

        orch = _make_orchestrator()
        original_response = "Apple revenue."  # Deliberately very short.
        long_rewrite = (
            "I cannot verify every number but here is a careful breakdown: "
            "Apple reported revenue of $181.5B [1] with EPS of $7.14 [2], "
            "and the analyst consensus had pencilled in $180B with EPS $7.10."
        )
        pipeline = _make_pipeline_with_stream(rewrite_text=long_rewrite)

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.side_effect = [first, second]

            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=original_response,
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                )
            )

        # Because the rewrite was LONGER than the original, the defeatist
        # guard does not fire and the second validate pass accepts it.
        assert passed is True
        assert text == long_rewrite


# ── PLAN-0104 W50 — banner suppression on full citation coverage ─────────────


class TestW50FullCitationCoverageHelper:
    """W50 helper unit tests — ``_answer_has_full_citation_coverage``.

    The helper is intentionally conservative: True only when every numeric
    token is within ±200 chars of a ``[tool_name row N]`` / ``[tool_name]``
    citation. We pin the success and failure modes so the orchestrator's
    last-line banner suppression cannot drift silently.
    """

    def test_full_coverage_with_per_number_citations(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import (
            _answer_has_full_citation_coverage,
        )

        text = (
            "AAPL P/E is 37.73x [query_fundamentals row 0]. "
            "Revenue last quarter was $84.7B [get_fundamentals_history row 7]. "
            "EPS came in at $2.18 [query_fundamentals row 0]."
        )
        assert _answer_has_full_citation_coverage(text) is True

    def test_missing_citation_on_one_number_returns_false(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import (
            _answer_has_full_citation_coverage,
        )

        # Last sentence has a bare number with no citation anywhere within
        # the ±200 char window. Helper must return False.
        text = (
            "AAPL P/E is 37.73x [query_fundamentals row 0]. "
            + (" filler " * 60)
            + "Mystery growth was 42.5%."  # uncited and far from prior cite
        )
        assert _answer_has_full_citation_coverage(text) is False

    def test_no_numeric_tokens_returns_false(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import (
            _answer_has_full_citation_coverage,
        )

        # Conservative behaviour: text with no numbers does NOT trigger
        # banner suppression — the helper returns False so the legacy path
        # decides what to do.
        assert _answer_has_full_citation_coverage("Some prose with no numbers.") is False

    def test_empty_text_returns_false(self) -> None:
        from rag_chat.application.use_cases.chat_orchestrator import (
            _answer_has_full_citation_coverage,
        )

        assert _answer_has_full_citation_coverage("") is False


class TestW50BannerSuppressionOnFullCoverage:
    """W50 integration: ``_run_grounding_validation`` suppresses the
    banner when both passes fail but the rewrite body is fully cited.

    Round 8 Q5 GOOGL: every number had a ``[query_fundamentals row 0]`` or
    ``[get_fundamentals_history row 7]`` citation yet the validator's numeric
    matcher mis-classified unit-suffixed values, emitting the banner. With
    W50 the helper rescues this case.
    """

    def test_both_passes_fail_but_full_coverage_suppresses_banner(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=False, unsupported=unsupported)

        orch = _make_orchestrator()
        original_response = "Apple revenue."
        fully_cited_rewrite = (
            "Apple Q3 revenue was $181.5B [get_fundamentals_history row 7] "
            "and EPS came in at $7.14 [query_fundamentals row 0]. "
            "Operating margin held at 30.2% [query_fundamentals row 0]."
        )
        pipeline = _make_pipeline_with_stream(rewrite_text=fully_cited_rewrite)

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.side_effect = [first, second]

            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=original_response,
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                )
            )

        # W50: full citation coverage → no banner, treat as grounded.
        assert passed is True
        assert text == fully_cited_rewrite
        assert "could not be verified" not in text

    def test_both_passes_fail_without_coverage_appends_banner(self) -> None:
        """Negative path: when the rewrite body is NOT fully cited, the legacy
        banner-append behaviour is preserved (true fabrications still warned)."""
        from rag_chat.application.services.numeric_grounding import FieldKind

        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=False, unsupported=unsupported)

        orch = _make_orchestrator()
        original_response = "Apple revenue."
        # Rewrite mixes a cited number with an uncited one — no full coverage.
        partially_cited_rewrite = (
            "Apple Q3 revenue was $181.5B [get_fundamentals_history row 7]. "
            + (" filler " * 60)
            + "EPS came in at $7.14 and net income was $25B."  # uncited tail
        )
        pipeline = _make_pipeline_with_stream(rewrite_text=partially_cited_rewrite)

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.side_effect = [first, second]

            text, passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=original_response,
                    tool_items=_nonempty_pool(),
                    messages=[],
                    budget=_make_budget(),
                )
            )

        # Legacy path: banner appended because helper returned False.
        assert passed is False
        assert "could not be verified" in text
        assert partially_cited_rewrite in text


# ── PLAN-0107 follow-up Bug 1 — rewrite history filter ───────────────────────


class TestRewriteHistoryFiltersPriorAssistantDraft:
    """PLAN-0107 follow-up Bug 1 — the rewrite path must NOT show the LLM its
    prior failed prose draft. Showing the draft trained the LLM to emit
    visible self-correction preambles ("You're right - I need to correct
    this. Let me re-examine the data...") because the rewrite text is the
    user-visible answer.

    Fix: strip prose assistant turns from the history before the corrective
    user turn, and do NOT re-inject ``{role: assistant, content: response}``.
    Assistant turns carrying ``tool_calls`` (no prose) are preserved so the
    tool-call/tool-result pairing remains valid for providers that check it.
    """

    def _capture_rewrite_messages(self, rewrite_text: str) -> tuple[Any, list]:
        """Return (pipeline_mock, captured_messages_holder).

        ``captured_messages_holder[0]`` will be populated with the first
        positional arg passed to ``stream_chat`` once the rewrite runs.
        """
        captured: list = []
        p = MagicMock()
        p.llm_chain = MagicMock()

        async def _stream(messages, *_a: Any, **_kw: Any):
            captured.append(messages)
            yield rewrite_text

        p.llm_chain.stream_chat = _stream
        return p, captured

    def test_prior_prose_assistant_turn_is_filtered_from_rewrite_history(self) -> None:
        from rag_chat.application.services.numeric_grounding import FieldKind

        # Build a history containing: user, assistant tool_calls (no prose),
        # tool result, AND a leftover prose assistant draft. Only the prose
        # assistant turn must be filtered; the tool-calls assistant turn
        # must survive so the tool/result pairing is intact.
        prose_draft = "Apple Q3 revenue was $999B [hallucinated]."
        history = [
            {"role": "user", "content": "What is Apple's revenue?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "get_fundamentals_history"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "revenue: $94.9B"},
            # The prose assistant turn that must be stripped.
            {"role": "assistant", "content": prose_draft},
        ]

        unsupported = (
            _FakeUnsupported(value=181.5e9, field_kind=FieldKind.REVENUE, closest_tool_value=94.9e9),
            _FakeUnsupported(value=7.14, field_kind=FieldKind.EPS, closest_tool_value=1.20),
        )
        first = _FakeResult(passed=False, unsupported=unsupported)
        second = _FakeResult(passed=True, unsupported=())

        orch = _make_orchestrator()
        pipeline, captured = self._capture_rewrite_messages(
            rewrite_text="Apple Q3 revenue was $94.9B [get_fundamentals_history row 0]."
        )

        with patch(
            "rag_chat.application.services.numeric_grounding.NumericGroundingValidator",
        ) as v_cls:
            v_inst = v_cls.return_value
            v_inst.validate.side_effect = [first, second]

            _text, _passed = asyncio.run(
                orch._run_grounding_validation(
                    p=pipeline,
                    response=prose_draft,
                    tool_items=_nonempty_pool(),
                    messages=history,
                    budget=_make_budget(),
                )
            )

        assert captured, "stream_chat was not invoked"
        sent = captured[0]
        # 1. The prose assistant draft text must NOT appear anywhere in the
        #    sent message list — that is the whole point of the filter.
        for m in sent:
            assert m.get("content") != prose_draft, f"Prose assistant draft leaked into rewrite history: {m!r}"
        # 2. The tool-calls assistant turn must survive (preserves pairing).
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls") for m in sent
        ), "tool_calls assistant turn was incorrectly filtered out"
        # 3. The user-turn corrective payload must be present and must NOT
        #    contain self-correction preamble phrasing — the prompt explicitly
        #    forbids the rewrite from starting with "You're right" etc.
        last = sent[-1]
        assert last.get("role") == "user"
        assert "You're right" in last["content"] or "Let me re-examine" in last["content"], (
            "Corrective user turn should reference forbidden preamble phrases so the LLM " "knows not to use them"
        )
