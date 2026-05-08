"""Unit tests for PromptBuilder (T-F-2-02)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from rag_chat.application.pipeline.prompt_builder import PromptBuilder
from rag_chat.domain.entities.conversation import Message
from rag_chat.domain.enums import MessageRole

pytestmark = pytest.mark.unit


def _no_contradictions() -> MagicMock:
    block = MagicMock()
    block.has_contradictions = False
    block.text = ""
    return block


def _with_contradictions(text: str = "Conflict found") -> MagicMock:
    block = MagicMock()
    block.has_contradictions = True
    block.text = text
    return block


def _message(role: MessageRole, content: str) -> Message:
    from datetime import UTC, datetime

    return Message(
        message_id=uuid4(),
        thread_id=uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder()


@pytest.mark.unit
def test_prompt_builder_includes_system_prompt(builder: PromptBuilder) -> None:
    """Output contains the safety instruction."""
    prompt = builder.build(
        context_block="[1] Some evidence.",
        conversation_history=[],
        rephrased_query="What is Apple's revenue?",
        sub_questions=(),
        contradiction_block=_no_contradictions(),
    )
    assert "financial intelligence analyst" in prompt
    assert "Safety:" in prompt


@pytest.mark.unit
def test_prompt_builder_includes_contradiction_block(builder: PromptBuilder) -> None:
    """Contradictions present -> conflict block included in output."""
    prompt = builder.build(
        context_block="[1] Some evidence.",
        conversation_history=[],
        rephrased_query="What is Apple's revenue?",
        sub_questions=(),
        contradiction_block=_with_contradictions("Revenue conflict."),
    )
    assert "Revenue conflict." in prompt


@pytest.mark.unit
def test_prompt_builder_no_contradiction_block_when_empty(builder: PromptBuilder) -> None:
    """No contradictions -> conflict section absent."""
    prompt = builder.build(
        context_block="[1] Some evidence.",
        conversation_history=[],
        rephrased_query="What is Apple's revenue?",
        sub_questions=(),
        contradiction_block=_no_contradictions(),
    )
    assert "Conflicts:" not in prompt


@pytest.mark.unit
def test_prompt_builder_includes_conversation_history(builder: PromptBuilder) -> None:
    """Last 5 turns included in the prompt."""
    history = [_message(MessageRole.user, f"Question {i}") for i in range(8)] + [
        _message(MessageRole.assistant, f"Answer {i}") for i in range(3)
    ]
    prompt = builder.build(
        context_block="",
        conversation_history=history,
        rephrased_query="Follow up",
        sub_questions=(),
        contradiction_block=_no_contradictions(),
    )
    assert "Conversation History:" in prompt
    # Should contain recent messages — content is XML-wrapped
    assert "<msg>" in prompt
    assert "Question 7" in prompt or "Answer 2" in prompt


@pytest.mark.unit
def test_prompt_builder_includes_sub_questions(builder: PromptBuilder) -> None:
    """Sub-questions appear in the query section."""
    prompt = builder.build(
        context_block="",
        conversation_history=[],
        rephrased_query="Compare AAPL vs TSLA",
        sub_questions=("What are AAPL margins?", "What are TSLA margins?"),
        contradiction_block=_no_contradictions(),
    )
    assert "What are AAPL margins?" in prompt
    assert "Sub-questions:" in prompt
