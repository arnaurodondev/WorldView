"""Unit tests for DeepInfraCompletionAdapter chat_with_tools / stream_chat (W11-1).

All tests mock httpx.AsyncClient so no real network calls are made.
WHY test _parse_tool_calls separately: it's the most complex parsing logic
and handles the malformed-JSON edge case that the orchestrator must survive.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.application.ports.llm_provider import LlmChatProvider
from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter
from tools.types import LLMToolResponse, ToolUseBlock  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Get the current price for a ticker",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    }
]


def _make_adapter(mock_client: AsyncMock) -> DeepInfraCompletionAdapter:
    """Create an adapter with a pre-configured mock httpx.AsyncClient."""
    return DeepInfraCompletionAdapter(
        api_key="test-key",
        model="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        http_client=mock_client,
        timeout=5.0,
    )


def _mock_response(body: dict) -> MagicMock:
    """Build a mock httpx response that returns body as JSON and has raise_for_status as a no-op.

    WHY MagicMock not AsyncMock: httpx.Response.json() is a synchronous method.
    Using AsyncMock would make it return a coroutine instead of the dict, causing
    'coroutine object is not subscriptable' errors when the adapter does body["choices"].
    """
    resp = MagicMock()
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _tool_calls_body(tool_id: str, name: str, args: dict) -> dict:
    """Build an OpenAI-format response body with a tool call."""
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
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
    }


def _stop_body(text: str) -> dict:
    """Build an OpenAI-format response body with a text answer."""
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
# chat_with_tools — payload construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepinfra_chat_with_tools_sends_tools_in_payload() -> None:
    """When tools are passed, the adapter includes them in the POST body."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(_stop_body("AAPL is $190")))
    adapter = _make_adapter(mock_client)

    messages = [{"role": "user", "content": "What is AAPL price?"}]
    await adapter.chat_with_tools(messages, _SAMPLE_TOOLS)

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert "tools" in payload
    assert payload["tool_choice"] == "auto"
    assert payload["stream"] is False


@pytest.mark.asyncio
async def test_deepinfra_chat_with_no_tools_omits_tools_from_payload() -> None:
    """When tools=None, the payload must NOT contain 'tools' or 'tool_choice'."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(_stop_body("Hello")))
    adapter = _make_adapter(mock_client)

    await adapter.chat_with_tools([{"role": "user", "content": "Hello"}], tools=None)

    payload = mock_client.post.call_args.kwargs["json"]
    assert "tools" not in payload
    assert "tool_choice" not in payload


# ---------------------------------------------------------------------------
# chat_with_tools — response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepinfra_chat_with_tools_returns_tool_calls() -> None:
    """When the model requests a tool, LLMToolResponse.has_tool_calls is True."""
    mock_client = AsyncMock()
    body = _tool_calls_body("call_xyz", "get_price", {"ticker": "AAPL"})
    mock_client.post = AsyncMock(return_value=_mock_response(body))
    adapter = _make_adapter(mock_client)

    resp = await adapter.chat_with_tools(
        [{"role": "user", "content": "What is AAPL?"}],
        _SAMPLE_TOOLS,
    )

    assert isinstance(resp, LLMToolResponse)
    assert resp.has_tool_calls is True
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert isinstance(tc, ToolUseBlock)
    assert tc.id == "call_xyz"
    assert tc.name == "get_price"
    assert tc.input == {"ticker": "AAPL"}


@pytest.mark.asyncio
async def test_deepinfra_chat_with_tools_returns_text_on_stop() -> None:
    """When the model answers directly, LLMToolResponse.text is set and no tool calls."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(_stop_body("AAPL is $190.")))
    adapter = _make_adapter(mock_client)

    resp = await adapter.chat_with_tools(
        [{"role": "user", "content": "What is AAPL?"}],
        _SAMPLE_TOOLS,
    )

    assert isinstance(resp, LLMToolResponse)
    assert resp.has_tool_calls is False
    assert resp.text == "AAPL is $190."
    assert resp.finish_reason == "stop"


# ---------------------------------------------------------------------------
# _parse_tool_calls — edge cases
# ---------------------------------------------------------------------------


def test_deepinfra_parse_tool_calls_handles_bad_json_arguments() -> None:
    """Malformed JSON in arguments → input={} with a warning log, no exception raised."""
    mock_client = AsyncMock()
    adapter = _make_adapter(mock_client)

    raw = [
        {
            "id": "call_bad",
            "function": {
                "name": "get_price",
                "arguments": "{ticker: AAPL}",  # invalid JSON (unquoted keys)
            },
        }
    ]
    result = adapter._parse_tool_calls(raw)

    assert len(result) == 1
    assert result[0].id == "call_bad"
    assert result[0].name == "get_price"
    assert result[0].input == {}  # fallback on malformed JSON


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_deepinfra_adapter_is_instance_of_llm_chat_provider() -> None:
    """DeepInfraCompletionAdapter satisfies the LlmChatProvider runtime protocol check."""
    mock_client = AsyncMock()
    adapter = _make_adapter(mock_client)

    # isinstance check works because LlmChatProvider is @runtime_checkable
    assert isinstance(adapter, LlmChatProvider)
