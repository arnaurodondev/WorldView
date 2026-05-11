"""Unit tests for OpenRouterCompletionAdapter chat_with_tools (W11-1).

These tests verify the identical contract as the DeepInfra adapter —
OpenRouter is a fallback provider so the orchestrator treats them uniformly.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter
from tools.types import LLMToolResponse, ToolUseBlock  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(mock_client: AsyncMock) -> OpenRouterCompletionAdapter:
    return OpenRouterCompletionAdapter(
        api_key="or-key",
        model="deepseek/deepseek-r1-distill-qwen-32b",
        http_client=mock_client,
        timeout=5.0,
    )


def _mock_response(body: dict) -> MagicMock:
    """Build a mock httpx response. Use MagicMock (not AsyncMock) because
    httpx.Response.json() is synchronous — AsyncMock would return a coroutine."""
    resp = MagicMock()
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _tool_calls_body(tool_id: str, name: str, args: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 55, "completion_tokens": 25},
    }


def _stop_body(text: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 40, "completion_tokens": 10},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_completion_adapter_chat_with_tools_identical_contract() -> None:
    """OpenRouter adapter returns LLMToolResponse with tool calls — same contract as DeepInfra."""
    mock_client = AsyncMock()
    body = _tool_calls_body("call_or_1", "query_entity_news", {"entity_id": "ent_42"})
    mock_client.post = AsyncMock(return_value=_mock_response(body))
    adapter = _make_adapter(mock_client)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "query_entity_news",
                "description": "Fetch news for an entity",
                "parameters": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
        }
    ]
    resp = await adapter.chat_with_tools(
        [{"role": "user", "content": "What news for entity 42?"}],
        tools,
    )

    assert isinstance(resp, LLMToolResponse)
    assert resp.has_tool_calls is True
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc: ToolUseBlock = resp.tool_calls[0]
    assert tc.id == "call_or_1"
    assert tc.name == "query_entity_news"
    assert tc.input == {"entity_id": "ent_42"}


@pytest.mark.asyncio
async def test_openrouter_chat_with_tools_text_response() -> None:
    """OpenRouter adapter returns plain text when model answers directly (finish_reason==stop)."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(_stop_body("Markets are volatile.")))
    adapter = _make_adapter(mock_client)

    resp = await adapter.chat_with_tools([{"role": "user", "content": "How are markets?"}])

    assert resp.has_tool_calls is False
    assert resp.text == "Markets are volatile."
    assert resp.finish_reason == "stop"
