"""OpenRouter LLM adapter — streaming + structured function-calling (T-F-3-01, W11-1).

Fallback provider using the OpenRouter OpenAI-compatible API.
Model: deepseek/deepseek-r1-distill-qwen-32b
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from observability.metrics import MLMetrics  # type: ignore[import-untyped]
    from rag_chat.application.ports.cost_recorder import CostRecorder
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
        metrics: MLMetrics | None = None,
        cost_recorder: CostRecorder | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self.model_id: str = model  # match DeepInfra adapter so cost code uses real model
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        # Optional MLMetrics — see DeepInfra adapter / observability.metrics for
        # the schema (ml_api_requests_total, ml_api_latency_seconds, ...).
        self._metrics = metrics
        # PLAN-0107 Agent-B: optional CostRecorder. See DeepInfra adapter for
        # the same contract — None disables, set wires cost capture.
        self._cost_recorder = cost_recorder

    async def _record_cost(
        self,
        *,
        thread_id: UUID | None,
        usage: dict | None,
        call_site: str,
    ) -> None:
        """Forward usage tokens to the injected CostRecorder. See DeepInfra adapter."""
        if self._cost_recorder is None:
            return
        if not usage:
            log.debug(  # type: ignore[no-any-return]
                "cost_recorder_no_usage",
                call_site=call_site,
                model_id=self._model,
                provider="openrouter",
            )
            tokens_in = 0
            tokens_out = 0
        else:
            tokens_in = int(usage.get("prompt_tokens", 0) or 0)
            tokens_out = int(usage.get("completion_tokens", 0) or 0)
        try:
            await self._cost_recorder.record(
                thread_id=thread_id,
                model_id=self._model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                call_site=call_site,
            )
        except Exception as exc:  # pragma: no cover — defensive
            log.debug(  # type: ignore[no-any-return]
                "cost_record_failed",
                call_site=call_site,
                model_id=self._model,
                error=str(exc),
            )

    def _record_ml_call(self, operation: str, status: str, latency_s: float) -> None:
        """Best-effort Prometheus update; no-op when metrics is None."""
        if self._metrics is None:
            return
        try:
            self._metrics.ml_api_requests_total.labels(model_id=self._model, operation=operation, status=status).inc()
            self._metrics.ml_api_latency_seconds.labels(model_id=self._model, operation=operation).observe(latency_s)
        except Exception:  # pragma: no cover — defensive
            log.debug("ml_metrics_record_failed", operation=operation, status=status)  # type: ignore[no-any-return]

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
                # PLAN-0093 QA-7 security: same redaction as DeepInfraCompletionAdapter —
                # raw arguments may contain user-entered text; log only length + tool name.
                _raw = fn.get("arguments", "") or ""
                log.warning(  # type: ignore[no-any-return]
                    "tool_call_bad_json",
                    name=fn.get("name", "unknown"),
                    raw_length=len(_raw),
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
        thread_id: UUID | None = None,
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

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(_do_request(), timeout=self._timeout)
        except Exception:
            self._record_ml_call("chat_with_tools", "error", time.perf_counter() - start)
            raise
        self._record_ml_call("chat_with_tools", "success", time.perf_counter() - start)
        # PLAN-0107 Agent-B: capture cost after successful call.
        await self._record_cost(
            thread_id=thread_id,
            usage=result.usage,
            call_site="tool_loop_iter",
        )
        return result

    async def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        thread_id: UUID | None = None,
        tools: list[dict] | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream the final answer turn from an OpenAI-format messages list.

        RC-1 (2026-06-18): ``model`` overrides ``self._model`` for THIS call
        only (combined grounding-repair rewrite A/B). ``None`` preserves the
        prior behaviour.
        """
        payload: dict[str, object] = {
            "model": model or self._model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # PLAN-0107 Agent-B: opt into per-stream usage frame (OpenRouter mirrors
        # OpenAI / DeepInfra contract for ``stream_options.include_usage``).
        if self._cost_recorder is not None:
            payload["stream_options"] = {"include_usage": True}
        # PLAN-0107 follow-up Fix #2: mirror the deepinfra contract — when the
        # caller passes an explicit empty tools list (synthesis turn), set
        # tool_choice="none" so the provider unambiguously forbids tool calls
        # in the response. tools=[] alone is ambiguous on some backends.
        if tools is not None:
            payload["tools"] = tools
            if not tools:
                payload["tool_choice"] = "none"
        # PLAN-0107 follow-up (eval framework v2 2026-06-06): forward an optional
        # ``seed`` to OpenRouter's OpenAI-compatible endpoint. Omit when None so
        # provider schema validators don't reject ``"seed": null``.
        if seed is not None:
            payload["seed"] = seed
        usage_capture: dict = {}
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
                    # PLAN-0107 Agent-B: capture usage from any chunk that has it.
                    if chunk.get("usage"):
                        usage_capture.update(chunk["usage"])
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        # PLAN-0107 Agent-B: record cost AFTER all chunks have been yielded so
        # a recorder hiccup never blocks token delivery.
        await self._record_cost(
            thread_id=thread_id,
            usage=usage_capture or None,
            call_site="synthesis",
        )

    async def aclose(self) -> None:
        await self._client.aclose()
