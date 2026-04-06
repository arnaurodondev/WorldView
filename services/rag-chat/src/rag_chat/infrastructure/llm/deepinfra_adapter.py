"""DeepInfra LLM streaming adapter (T-F-3-01).

Uses the OpenAI-compatible chat completions API to stream tokens
from deepseek-r1-distill-qwen-32b via DeepInfra.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
import structlog

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_MODEL = "deepseek-r1-distill-qwen-32b"
_BASE_URL = "https://api.deepinfra.com/v1/openai"


class DeepInfraCompletionAdapter:
    """Stream token chunks from DeepInfra (OpenAI-compat API).

    Args:
        api_key:     DeepInfra API key.
        http_client: Optional pre-built httpx.AsyncClient for testing.
        timeout:     Request timeout in seconds (default 30).
    """

    name = "deepinfra"

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 4000,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Yield text chunks from DeepInfra streaming endpoint."""
        payload = {
            "model": _MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with self._client.stream(
            "POST",
            f"{_BASE_URL}/chat/completions",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def aclose(self) -> None:
        await self._client.aclose()
