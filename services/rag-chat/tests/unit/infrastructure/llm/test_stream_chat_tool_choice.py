"""Tests for stream_chat tools=[]/tool_choice="none" wiring (Fix #2).

When the orchestrator passes ``tools=[]`` on the synthesis turn, both the
DeepInfra and OpenRouter adapters must add ``tool_choice="none"`` to the
HTTP payload so the provider unambiguously forbids tool calls in the
response.  ``tools=None`` (the legacy default) leaves both keys absent.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest
from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter
from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

pytestmark = pytest.mark.unit


def _sse_with_content(text: str) -> bytes:
    frame = {"choices": [{"delta": {"content": text}}]}
    return f"data: {_json.dumps(frame)}\n\ndata: [DONE]\n\n".encode()


def _capture_handler(captured: list[dict]):
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(_json.loads(request.content))
        return httpx.Response(200, content=_sse_with_content("ok"))

    return _handler


# ─── DeepInfra ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deepinfra_stream_chat_empty_tools_sets_tool_choice_none() -> None:
    """tools=[] → payload carries tools=[] AND tool_choice="none"."""
    captured: list[dict] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(captured)))
    adapter = DeepInfraCompletionAdapter(api_key="x", model="primary/model", http_client=client)

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}], tools=[])]
    assert chunks == ["ok"]
    assert len(captured) == 1
    assert captured[0].get("tools") == []
    assert captured[0].get("tool_choice") == "none"
    await client.aclose()


@pytest.mark.asyncio
async def test_deepinfra_stream_chat_no_tools_param_omits_keys() -> None:
    """Legacy call without tools= → payload has neither tools nor tool_choice."""
    captured: list[dict] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(captured)))
    adapter = DeepInfraCompletionAdapter(api_key="x", model="primary/model", http_client=client)

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
    assert chunks == ["ok"]
    assert "tools" not in captured[0]
    assert "tool_choice" not in captured[0]
    await client.aclose()


# ─── OpenRouter ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openrouter_stream_chat_empty_tools_sets_tool_choice_none() -> None:
    """OpenRouter mirrors DeepInfra: tools=[] → tool_choice="none"."""
    captured: list[dict] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(captured)))
    adapter = OpenRouterCompletionAdapter(api_key="x", model="or/model", http_client=client)

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}], tools=[])]
    assert chunks == ["ok"]
    assert captured[0].get("tools") == []
    assert captured[0].get("tool_choice") == "none"
    await client.aclose()


@pytest.mark.asyncio
async def test_openrouter_stream_chat_no_tools_param_omits_keys() -> None:
    captured: list[dict] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(captured)))
    adapter = OpenRouterCompletionAdapter(api_key="x", model="or/model", http_client=client)

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
    assert chunks == ["ok"]
    assert "tools" not in captured[0]
    assert "tool_choice" not in captured[0]
    await client.aclose()
