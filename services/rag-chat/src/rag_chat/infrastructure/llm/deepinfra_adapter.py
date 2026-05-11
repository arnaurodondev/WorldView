"""DeepInfra LLM adapter — streaming + structured function-calling (T-F-3-01, W11-1).

Uses the OpenAI-compatible chat completions API to either:
- Stream token chunks from a model (existing stream() method, unchanged)
- Run a non-streaming structured call with optional tool definitions (new chat_with_tools)
- Stream the final answer turn after tools have been executed (new stream_chat)
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

    # ------------------------------------------------------------------
    # Structured chat with optional function calling (W11-1)
    # ------------------------------------------------------------------

    def _parse_tool_calls(self, raw_calls: list[dict]) -> list[ToolUseBlock]:
        """Map OpenAI-format tool_calls list to canonical ToolUseBlock objects.

        WHY defensive parsing: LLMs occasionally emit syntactically invalid JSON
        in the arguments field (e.g. unquoted strings, trailing commas).  We log
        the malformed payload and fall back to an empty dict so the orchestrator
        can report the failure gracefully instead of raising an unhandled exception.
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
        """Non-streaming structured call — returns text OR tool_calls.

        BP-025: entire HTTP call wrapped in asyncio.wait_for to honour self._timeout.
        WHY stream=False: tool_call deltas in streaming mode require reassembling
        JSON arguments across multiple chunks; non-streaming is simpler and the
        latency difference is negligible for tool-use turns (typically <2 s).
        """
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            # OpenAI format: list of {"type": "function", "function": {...}}
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
        """Stream the final answer turn from an OpenAI-format messages list.

        WHY a separate method from stream(): stream() takes a raw prompt string
        and wraps it in a single-message list internally.  stream_chat() accepts
        a full conversation history (including injected tool results) so the model
        sees the complete context when producing its final answer.
        """
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
