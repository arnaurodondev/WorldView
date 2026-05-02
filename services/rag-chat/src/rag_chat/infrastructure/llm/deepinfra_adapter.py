"""DeepInfra LLM streaming adapter (T-F-3-01).

Uses the OpenAI-compatible chat completions API to stream tokens
from deepseek-ai/DeepSeek-R1-Distill-Llama-70B via DeepInfra.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
import structlog

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
_BASE_URL = "https://api.deepinfra.com/v1/openai"


class DeepInfraCompletionAdapter:
    """Stream token chunks from DeepInfra (OpenAI-compat API).

    Args:
        api_key:     DeepInfra API key.
        model:       Model ID override (default: deepseek-ai/DeepSeek-R1-Distill-Llama-70B).
                     Configurable via RAG_CHAT_COMPLETION_MODEL env var.
        http_client: Optional pre-built httpx.AsyncClient for testing.
        timeout:     Request timeout in seconds (default 30).
    """

    name = "deepinfra"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        thinking: bool = True,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self.model_id: str = model  # expose for orchestrator model tracking
        self._timeout = timeout
        self._thinking = thinking
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
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Qwen3 thinking mode: model reasons internally before answering.
        # The <think>...</think> block is stripped by _ThinkBlockFilter in the
        # orchestrator before tokens reach the user. Only beneficial for
        # reasoning-heavy tasks (financial analysis, multi-hop queries).
        if self._thinking:
            payload["chat_template_kwargs"] = {"thinking": True}
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
