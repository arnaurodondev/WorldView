"""Ollama LLM streaming adapter - emergency fallback (T-F-3-01, W11-1).

Last-resort provider using the local Ollama instance.
Model: deepseek-r1:32b (or configured completion model).

NOTE: Ollama does not support OpenAI-compatible function calling.
chat_with_tools() and stream_chat() raise NotImplementedError so that
LLMProviderChain skips this adapter and falls back to DeepInfra/OpenRouter
when tool-use is required.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tools.types import LLMToolResponse  # type: ignore[import-untyped]

    from observability.metrics import MLMetrics  # type: ignore[import-untyped]
import structlog

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class OllamaCompletionAdapter:
    """Stream token chunks from local Ollama (emergency fallback).

    Args:
        base_url:    Base URL for Ollama API (e.g. http://localhost:11434).
        model:       Model name (default: deepseek-r1:32b).
        http_client: Optional pre-built httpx.AsyncClient for testing.
        timeout:     Request timeout in seconds (default 60 - longer for local).
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str = "deepseek-r1:32b",
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        # Optional MLMetrics — Ollama doesn't currently surface chat_with_tools
        # (it raises NotImplementedError), so the metric is wired but won't
        # tick unless stream-level instrumentation is added in future.  Stored
        # eagerly so a later patch can flip the switch without re-touching app.py.
        self._metrics = metrics

    async def stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 4000,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Yield text chunks from Ollama /api/chat endpoint."""
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        async with self._client.stream(
            "POST",
            f"{self._base_url}/api/chat",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    # ------------------------------------------------------------------
    # Structured chat / function calling — NOT SUPPORTED (W11-1)
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        """Not implemented — Ollama does not support OpenAI function calling.

        WHY raise not return: LLMProviderChain catches NotImplementedError and
        skips this adapter, falling back to DeepInfra or OpenRouter which do
        support the function-calling API.
        """
        raise NotImplementedError(
            "Ollama function calling not supported — use DeepInfra or OpenRouter for tool-use path"
        )

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Not implemented — delegate to stream() after collapsing messages to a prompt.

        WHY raise: for the tool-use path the orchestrator always calls stream_chat()
        on the chain, not on Ollama directly.  Raising ensures the chain correctly
        skips Ollama and uses a capable provider.
        """
        raise NotImplementedError(
            "Ollama function calling not supported — use DeepInfra or OpenRouter for tool-use path"
        )

    async def aclose(self) -> None:
        await self._client.aclose()
