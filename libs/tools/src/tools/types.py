"""Canonical LLM tool-use types for the worldview platform (PLAN-0067 Wave W11-1).

WHY a separate types module:
- ToolUseBlock/ToolCallBatch/LLMToolResponse are shared between the port layer
  (llm_provider.py) and the adapters (deepinfra, openrouter).  Centralising them
  here avoids any circular imports — ports import from libs/tools, adapters import
  from libs/tools, never from each other.
- The existing ToolUseBlock in tool_executor.py uses tool_use_id (Anthropic-style).
  This module uses 'id' (OpenAI-compat style) to match the DeepInfra/OpenRouter
  JSON field name.  The executor field will be harmonised in a later wave.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolUseBlock:
    """Single tool call emitted by the LLM.

    WHY id not tool_use_id: OpenAI-compatible endpoints (DeepInfra, OpenRouter)
    return {"id": "call_abc123", "function": {...}}.  Using 'id' keeps the field
    name identical to the wire format, avoiding a rename at parse time.
    """

    id: str  # LLM-assigned call ID (e.g. "call_abc123")
    name: str  # tool name — must match a key in the ToolRegistry
    input: dict  # parsed JSON arguments from the LLM


@dataclass
class ToolCallBatch:
    """Yielded from the LLM stream when the model emits function calls instead of text.

    WHY SEPARATE from ToolUseBlock:
    Streaming responses interleave text-delta tokens and tool_call deltas.
    When finish_reason=="tool_calls" arrives, the orchestrator needs a clean
    typed signal to stop accumulating text and start dispatching tool calls.
    A dedicated batch type makes that branching explicit and testable.
    """

    tool_calls: list[ToolUseBlock] = field(default_factory=list)
    finish_reason: str = "tool_calls"

    @property
    def has_tool_calls(self) -> bool:
        """True when at least one tool call is present in this batch."""
        return bool(self.tool_calls)


@dataclass
class LLMToolResponse:
    """Non-streaming response from chat_with_tools() — either text or tool calls.

    Exactly one of `text` or `tool_calls` will be populated depending on
    finish_reason:
    - "stop"        → text is set, tool_calls is empty
    - "tool_calls"  → tool_calls is non-empty, text is None
    - "length"      → text may be partial, tool_calls is empty

    WHY usage: token counts let the caller fire a cost-log without an extra
    round-trip; adapters populate this from the response body's usage field.
    """

    text: str | None  # set when finish_reason=="stop"
    tool_calls: list[ToolUseBlock]  # non-empty when finish_reason=="tool_calls"
    finish_reason: str  # "stop" | "tool_calls" | "length"
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": M, ...}

    @property
    def has_tool_calls(self) -> bool:
        """True when the LLM wants to call at least one tool."""
        return bool(self.tool_calls)
