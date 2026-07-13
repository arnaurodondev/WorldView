"""Tests for LLMProviderChain.chat_with_tools and stream_chat (W11-1).

The chain must:
1. Skip Ollama (NotImplementedError) and use DeepInfra/OpenRouter
2. Return the first successful LLMToolResponse
3. Log usage via the usage_logger if provided
4. Raise RuntimeError if all capable providers fail
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain
from tools.types import LLMToolResponse, ToolUseBlock  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey(neg_cached: set[str] | None = None) -> AsyncMock:
    neg = neg_cached or set()
    valkey = AsyncMock()
    valkey.exists = AsyncMock(side_effect=lambda key: key.split(":")[-1] in neg)
    valkey.setex = AsyncMock()
    return valkey


def _make_capable_provider(
    name: str,
    resp: LLMToolResponse | None = None,
    *,
    fail: bool = False,
) -> MagicMock:
    """Create a provider that supports chat_with_tools."""
    provider = MagicMock()
    provider.name = name
    provider.model_id = name

    if fail:
        provider.chat_with_tools = AsyncMock(side_effect=RuntimeError(f"{name} down"))
    else:
        provider.chat_with_tools = AsyncMock(
            return_value=resp
            or LLMToolResponse(
                text="ok",
                tool_calls=[],
                finish_reason="stop",
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        )

    async def _stream_chat(messages: list, **kw):  # type: ignore[no-untyped-def]
        yield "chunk"

    provider.stream_chat = _stream_chat
    return provider


def _make_ollama_provider() -> MagicMock:
    """Create a provider that raises NotImplementedError for tool-use (like OllamaCompletionAdapter)."""
    provider = MagicMock()
    provider.name = "ollama"
    provider.chat_with_tools = AsyncMock(side_effect=NotImplementedError("Ollama function calling not supported"))
    provider.stream_chat = MagicMock(side_effect=NotImplementedError("Ollama function calling not supported"))
    return provider


# ---------------------------------------------------------------------------
# chat_with_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_provider_chain_skips_ollama_for_tool_calls() -> None:
    """Chain skips Ollama (NotImplementedError) and succeeds with OpenRouter."""
    ollama = _make_ollama_provider()
    openrouter = _make_capable_provider(
        "openrouter",
        LLMToolResponse(
            text=None,
            tool_calls=[ToolUseBlock(id="call_1", name="get_price", input={"ticker": "AAPL"})],
            finish_reason="tool_calls",
        ),
    )
    valkey = _make_valkey()

    # Put Ollama first to verify it is skipped
    chain = LLMProviderChain(providers=[ollama, openrouter], valkey=valkey)
    resp = await chain.chat_with_tools([{"role": "user", "content": "AAPL?"}])

    assert resp.has_tool_calls is True
    assert resp.tool_calls[0].name == "get_price"


@pytest.mark.asyncio
async def test_llm_provider_chain_chat_with_tools_uses_first_capable() -> None:
    """Primary provider is used when it supports tool calling."""
    deepinfra = _make_capable_provider(
        "deepinfra",
        LLMToolResponse(text="Answer", tool_calls=[], finish_reason="stop"),
    )
    openrouter = _make_capable_provider("openrouter")
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)
    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}])

    assert resp.text == "Answer"
    # OpenRouter must not have been called
    openrouter.chat_with_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_provider_chain_chat_with_tools_falls_back_on_error() -> None:
    """When primary raises a non-NotImplementedError, chain falls back to secondary."""
    deepinfra = _make_capable_provider("deepinfra", fail=True)
    openrouter = _make_capable_provider(
        "openrouter",
        LLMToolResponse(text="fallback", tool_calls=[], finish_reason="stop"),
    )
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)
    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}])

    assert resp.text == "fallback"


@pytest.mark.asyncio
async def test_llm_provider_chain_chat_with_tools_all_fail_raises() -> None:
    """If all providers fail or are unsupported, RuntimeError is raised."""
    ollama = _make_ollama_provider()
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[ollama], valkey=valkey)

    with pytest.raises(RuntimeError, match="chat_with_tools"):
        await chain.chat_with_tools([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_llm_provider_chain_chat_with_tools_logs_usage() -> None:
    """When usage is present and usage_logger is set, a log task is fired."""
    usage_logger = AsyncMock()
    usage_logger.log = AsyncMock()

    provider = _make_capable_provider(
        "deepinfra",
        LLMToolResponse(
            text="ok",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 8},
        ),
    )
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[provider], valkey=valkey, usage_logger=usage_logger)

    await chain.chat_with_tools([{"role": "user", "content": "hi"}])
    # Allow fire-and-forget task to execute
    await asyncio.sleep(0)

    usage_logger.log.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_provider_chain_chat_with_tools_aggregate_wrapper_is_zero() -> None:
    """PLAN-0117 W4 / OQ-3: the chat_with_tools wrapper row is a $0 aggregate.

    The provider adapter records the SAME round-trip as the ``tool_loop_iter``
    leaf (with the real provider cost). The provider-chain wrapper must stay at
    ``estimated_cost_usd=0.0`` (no double count) and stamp
    ``cost_source='aggregate'`` so the FR-7 silent-zero guard can exempt it.
    """
    usage_logger = AsyncMock()
    usage_logger.log = AsyncMock()

    provider = _make_capable_provider(
        "deepinfra",
        LLMToolResponse(
            text="ok",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 8},
        ),
    )
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[provider], valkey=valkey, usage_logger=usage_logger)

    await chain.chat_with_tools([{"role": "user", "content": "hi"}])
    await asyncio.sleep(0)

    kwargs = usage_logger.log.await_args.kwargs
    assert kwargs["capability"] == "chat_with_tools"
    assert kwargs["estimated_cost_usd"] == 0.0
    assert kwargs["cost_source"] == "aggregate"


# ---------------------------------------------------------------------------
# stream_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_provider_chain_stream_chat_skips_ollama() -> None:
    """stream_chat skips Ollama (name=="ollama") and delegates to OpenRouter.

    PLAN-0093 QA-7 P1-2: stream_chat is now an async generator function so it can
    record per-provider failures. We must iterate it to drive the body.
    """
    ollama = _make_ollama_provider()
    openrouter = _make_capable_provider("openrouter")
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[ollama, openrouter], valkey=valkey)
    chunks = [chunk async for chunk in chain.stream_chat([{"role": "user", "content": "hi"}])]

    # OpenRouter helper yields a single "chunk" sentinel — confirm we got it.
    assert chunks == ["chunk"]


@pytest.mark.asyncio
async def test_llm_provider_chain_stream_chat_raises_if_no_provider() -> None:
    """RuntimeError raised when only Ollama is in the chain (no supporting provider)."""
    ollama = _make_ollama_provider()
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[ollama], valkey=valkey)

    with pytest.raises(RuntimeError, match="stream_chat"):
        async for _ in chain.stream_chat([{"role": "user", "content": "hi"}]):
            pass
