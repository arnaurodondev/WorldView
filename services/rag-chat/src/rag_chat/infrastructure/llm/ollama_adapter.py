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
    from rag_chat.application.ports.cost_recorder import CostRecorder
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
        cost_recorder: CostRecorder | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.model_id: str = model  # match DeepInfra/OpenRouter — cost code reads model_id
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        # Optional MLMetrics — Ollama doesn't currently surface chat_with_tools
        # (it raises NotImplementedError), so the metric is wired but won't
        # tick unless stream-level instrumentation is added in future.  Stored
        # eagerly so a later patch can flip the switch without re-touching app.py.
        self._metrics = metrics
        # PLAN-0107 Agent-B: optional CostRecorder. Ollama is local + free so
        # MODEL_PRICING returns Decimal(0) — but recording still bumps the
        # llm_usage_log row + threads.estimated_cost_usd (no-op delta) so the
        # full per-call audit trail remains uniform across providers.
        self._cost_recorder = cost_recorder

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
        # Ollama returns prompt_eval_count + eval_count on the final chunk
        # where done=true. We capture them and emit a cost.record() AFTER the
        # stream completes — Ollama is the local fallback so cost is $0 in the
        # pricing matrix, but we still want call_site visibility (helps spot
        # whether the chain is falling through to the local model unexpectedly).
        usage_tokens_in = 0
        usage_tokens_out = 0
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
                        # Capture usage off the final frame for the cost emit below.
                        usage_tokens_in = int(chunk.get("prompt_eval_count", 0) or 0)
                        usage_tokens_out = int(chunk.get("eval_count", 0) or 0)
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        # Emit cost AFTER the response body closes; this only runs when the
        # generator was consumed to completion (caller break-out skips it,
        # which is fine — record() is an observability hint, not load-bearing).
        await self._record_cost(tokens_in=usage_tokens_in, tokens_out=usage_tokens_out)

    async def _record_cost(self, *, tokens_in: int, tokens_out: int) -> None:
        """Best-effort cost emit; defence-in-depth no-op on errors."""
        if self._cost_recorder is None:
            return
        try:
            await self._cost_recorder.record(
                # Ollama callers are background workers (intent fallback, judge
                # fallback) — thread_id=None matches the semantics. If we ever
                # invoke Ollama from a user chat path, plumb thread_id through.
                thread_id=None,
                model_id=self._model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                call_site="ollama_stream",
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("cost_record_failed", call_site="ollama_stream", error=str(exc))  # type: ignore[no-any-return]

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
