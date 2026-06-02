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
                    tool_items=[],
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
                    tool_items=[],
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
                    tool_items=[],
                    messages=[],
                    budget=_make_budget(),
                )
            )

        # Because the rewrite was LONGER than the original, the defeatist
        # guard does not fire and the second validate pass accepts it.
        assert passed is True
        assert text == long_rewrite
