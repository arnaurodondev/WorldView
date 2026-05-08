"""OpenRouter LLM adapter — streaming + structured function-calling (T-F-3-01, W11-1).

Fallback provider using the OpenRouter OpenAI-compatible API.
Model: deepseek/deepseek-r1-distill-qwen-32b
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
import structlog
from tools.types import LLMToolResponse, ToolUseBlock  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_MODEL = "deepseek/deepseek-r1-distill-qwen-32b"
_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterCompletionAdapter:
    """Stream token chunks from OpenRouter (OpenAI-compat API).

    Args:
        api_key:     OpenRouter API key.
        model:       Model ID override (default: deepseek/deepseek-r1-distill-qwen-32b).
                     Configurable via RAG_CHAT_OPENROUTER_COMPLETION_MODEL env var.
        http_client: Optional pre-built httpx.AsyncClient for testing.
        timeout:     Request timeout in seconds (default 30).
    """

    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
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
        """Yield text chunks from OpenRouter streaming endpoint."""
        payload = {
            "model": self._model,
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

    # ------------------------------------------------------------------
    # Structured chat with optional function calling (W11-1)
    # ------------------------------------------------------------------

    def _parse_tool_calls(self, raw_calls: list[dict]) -> list[ToolUseBlock]:
        """Map OpenAI-format tool_calls list to canonical ToolUseBlock objects.

        Same defensive parsing as DeepInfraCompletionAdapter — malformed JSON
        arguments are logged and replaced with an empty dict.
        """
        result = []
        for call in raw_calls or []:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, ValueError):
                log.warning(  # type: ignore[no-any-return]
                    "tool_call_bad_json",
                    name=fn.get("name", ""),
                    raw=fn.get("arguments", "")[:100],
                )
                args = {}
            result.append(
                ToolUseBlock(
                    id=call.get("id", ""),
                    name=fn.get("name", ""),
                    input=args,
                )
            )
        return result

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        """Non-streaming structured call — identical contract to DeepInfra adapter.

        BP-025: entire HTTP call wrapped in asyncio.wait_for.
        """
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async def _do_request() -> LLMToolResponse:
            resp = await self._client.post(
                f"{_BASE_URL}/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            choice = body["choices"][0]
            message = choice["message"]
            finish_reason: str = choice.get("finish_reason", "stop")
            usage: dict | None = body.get("usage")

            raw_tool_calls: list[dict] = message.get("tool_calls") or []
            if raw_tool_calls:
                return LLMToolResponse(
                    text=None,
                    tool_calls=self._parse_tool_calls(raw_tool_calls),
                    finish_reason="tool_calls",
                    usage=usage,
                )
            return LLMToolResponse(
                text=message.get("content", ""),
                tool_calls=[],
                finish_reason=finish_reason,
                usage=usage,
            )

        return await asyncio.wait_for(_do_request(), timeout=self._timeout)

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Stream the final answer turn from an OpenAI-format messages list."""
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
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
