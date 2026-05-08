"""Tests for canonical LLM tool-use types (W11-1 T-W11-1-01).

WHY these tests: the ToolCallBatch and LLMToolResponse dataclasses have
computed properties (has_tool_calls) that branch on emptiness.  Verifying
both True and False paths ensures the orchestrator's conditional logic works
correctly without needing an actual LLM call.
"""

from __future__ import annotations

import pytest
from tools.types import LLMToolResponse, ToolCallBatch, ToolUseBlock  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ToolCallBatch.has_tool_calls
# ---------------------------------------------------------------------------


def test_tool_call_batch_has_tool_calls_true() -> None:
    """ToolCallBatch.has_tool_calls returns True when tool_calls is non-empty."""
    block = ToolUseBlock(id="call_1", name="get_price", input={"ticker": "AAPL"})
    batch = ToolCallBatch(tool_calls=[block])

    assert batch.has_tool_calls is True


def test_tool_call_batch_has_tool_calls_false_when_empty() -> None:
    """ToolCallBatch.has_tool_calls returns False when tool_calls list is empty."""
    batch = ToolCallBatch(tool_calls=[])

    assert batch.has_tool_calls is False


# ---------------------------------------------------------------------------
# LLMToolResponse.has_tool_calls
# ---------------------------------------------------------------------------


def test_llm_tool_response_stop_no_tool_calls() -> None:
    """LLMToolResponse with finish_reason==stop has no tool calls."""
    resp = LLMToolResponse(
        text="The price of AAPL is $190.",
        tool_calls=[],
        finish_reason="stop",
    )

    assert resp.has_tool_calls is False
    assert resp.text == "The price of AAPL is $190."
    assert resp.usage is None  # default


def test_llm_tool_response_has_tool_calls_when_tool_calls_present() -> None:
    """LLMToolResponse.has_tool_calls is True when the model requested a tool call."""
    block = ToolUseBlock(id="call_abc", name="query_entity_news", input={"entity_id": "ent_1"})
    resp = LLMToolResponse(
        text=None,
        tool_calls=[block],
        finish_reason="tool_calls",
        usage={"prompt_tokens": 120, "completion_tokens": 30},
    )

    assert resp.has_tool_calls is True
    assert resp.text is None
    assert resp.usage == {"prompt_tokens": 120, "completion_tokens": 30}


def test_llm_tool_response_finish_reason_length() -> None:
    """LLMToolResponse with finish_reason==length has no tool calls (truncated text)."""
    resp = LLMToolResponse(
        text="The analysis is",
        tool_calls=[],
        finish_reason="length",
    )

    assert resp.has_tool_calls is False
    assert resp.finish_reason == "length"
