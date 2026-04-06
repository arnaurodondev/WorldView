"""Ollama LLM streaming adapter - emergency fallback (T-F-3-01).

Last-resort provider using the local Ollama instance.
Model: deepseek-r1:32b (or configured completion model).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

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

    async def aclose(self) -> None:
        await self._client.aclose()
