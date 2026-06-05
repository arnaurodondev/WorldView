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

# PLAN-0104 W46 / BP-NEW: HTTP statuses that indicate a transient condition on
# the *model* (rate-limit / upstream gateway) — worth retrying on the configured
# fallback model on the SAME provider before propagating to the chain.  4xx auth
# / validation errors and 500s on the wire are NOT in this set because they
# would just recur on the fallback model.
_FALLBACK_RETRIABLE_HTTP_STATUS: frozenset[int] = frozenset({429, 502, 503, 504})


def _is_retriable_chat_failure(exc: BaseException) -> bool:
    """Return True when an in-adapter model fallback could plausibly recover.

    Conservative on purpose: only timeouts, connect/read errors, and the
    retriable HTTP status codes above qualify.  Anything else (KeyError,
    ValueError, NotImplementedError, 4xx auth) bypasses the fallback and
    propagates so the orchestrator surfaces the real misconfiguration
    instead of doubling the upstream cost.
    """
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, httpx.ConnectError | httpx.ReadError | httpx.RemoteProtocolError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _FALLBACK_RETRIABLE_HTTP_STATUS
    return False


class DeepInfraCompletionAdapter:
    """Stream token chunks from DeepInfra (OpenAI-compat API).

    Args:
        api_key:     DeepInfra API key.
        model:       Model ID override (default: deepseek-ai/DeepSeek-R1-Distill-Llama-70B).
                     Configurable via RAG_CHAT_COMPLETION_MODEL env var.
        http_client: Optional pre-built httpx.AsyncClient for testing.
        timeout:     Generic request timeout in seconds (default 30); used for
                     stream() and the per-request httpx client floor.
        chat_with_tools_timeout: Per-call timeout for chat_with_tools (default
                     90). FIX-LIVE-X: with the Qwen3-235B completion model and
                     a multi-tool context (screen_universe + N fundamentals
                     results in the same message stack), the second-turn
                     `chat_with_tools` call regularly exceeds 30s — it timed
                     out *before* hitting the HTTP layer (asyncio.TimeoutError
                     with empty str()), which surfaced as the cryptic
                     ``provider_chat_with_tools_failed`` log + empty
                     ``llm_first_turn_failed`` error in Q6.  Default raised to
                     90s; configurable via RAG_CHAT_DEEPINFRA_TOOLCALL_TIMEOUT.
        thinking:   Whether to enable Qwen3 "thinking" mode on streaming calls.
    """

    name = "deepinfra"

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        chat_with_tools_timeout: float | None = None,
        thinking: bool = True,
        stream_chat_fallback_model: str | None = "deepseek-ai/DeepSeek-V4-Flash",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self.model_id: str = model  # expose for orchestrator model tracking
        # PLAN-0104 W43 / BP-NEW: alternate model used for second-turn synthesis
        # when the primary returns a zero-chunk SSE.  Root cause: Q5
        # ``ru_googl_pe_vs_history`` — DeepInfra returned HTTP 200 OK + a
        # ``data: [DONE]`` frame with no ``content`` deltas after a ~56s
        # multi-tool synthesis call against ``deepseek-ai/DeepSeek-V4-Flash-Thinking``.
        # The provider chain only has DeepInfra wired in this deployment
        # (no OpenRouter / Ollama keys for the live stack), so W40's
        # cross-provider failover never triggered.  By retrying the SAME
        # provider with a smaller, non-reasoning model we recover useful
        # answers without requiring extra API keys.  Set to ``None`` to
        # disable (legacy behaviour).
        self._stream_chat_fallback_model = stream_chat_fallback_model
        self._timeout = timeout
        # FIX-LIVE-X (2026-05-25): split timeout so the heavier chat-with-tools
        # second turn isn't bound by the 30s stream() default.  If the caller
        # didn't override, fall back to max(timeout, 90s).
        self._chat_with_tools_timeout = (
            chat_with_tools_timeout if chat_with_tools_timeout is not None else max(timeout, 90.0)
        )
        self._thinking = thinking
        # WHY use the larger of the two as the httpx floor: a low httpx
        # timeout would clip chat_with_tools BEFORE asyncio.wait_for could
        # honour the per-call budget.  We always size the client to the
        # widest budget the adapter knows about.
        _client_timeout = max(self._timeout, self._chat_with_tools_timeout)
        self._client = http_client or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(_client_timeout),
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
                # PLAN-0093 QA-7 security: do not log the raw arguments string —
                # it may carry user-entered text from the LLM-generated tool args
                # (e.g. `search_documents.query`). Log only length + tool name.
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
    ) -> LLMToolResponse:
        """Non-streaming structured call — returns text OR tool_calls.

        BP-025: entire HTTP call wrapped in asyncio.wait_for to honour self._timeout.
        WHY stream=False: tool_call deltas in streaming mode require reassembling
        JSON arguments across multiple chunks; non-streaming is simpler and the
        latency difference is negligible for tool-use turns (typically <2 s).

        PLAN-0104 W46 / BP-NEW (first-turn rate-limit recovery):
        Round 7 v2 hit DeepInfra 429s on the Qwen3-235B primary model that
        survived the in-chain retry budget (2 attempts x ~3s).  The chain then
        raised ``RuntimeError`` and the orchestrator emitted
        ``llm_first_turn_failed`` even though a smaller, far less rate-limited
        model on the SAME key (Llama-3.1-8B at 8x lower cost) would have
        succeeded.  When ``self._stream_chat_fallback_model`` is configured and
        the primary call fails with a retriable error (429 / 5xx / timeout),
        we retry once on the fallback model before propagating.  Non-retriable
        errors (4xx auth/validation) propagate immediately — they would just
        recur on the fallback.
        """

        async def _do_request(model: str) -> LLMToolResponse:
            payload: dict[str, object] = {
                "model": model,
                "messages": messages,
                "stream": False,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if tools:
                # OpenAI format: list of {"type": "function", "function": {...}}
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
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

        async def _call(model: str) -> LLMToolResponse:
            # FIX-LIVE-X (2026-05-25): wrap TimeoutError so the failure surfaces
            # with a non-empty error message in provider_chat_with_tools_failed
            # logs (str(TimeoutError()) is "" by default — which is why the Q6
            # failure was a black box until this fix).
            try:
                return await asyncio.wait_for(_do_request(model), timeout=self._chat_with_tools_timeout)
            except TimeoutError as exc:
                raise TimeoutError(
                    f"deepinfra chat_with_tools timed out after {self._chat_with_tools_timeout}s "
                    f"(model={model}, n_messages={len(messages)}, "
                    f"n_tools={len(tools) if tools else 0})"
                ) from exc

        try:
            return await _call(self._model)
        except Exception as exc:
            fallback_model = self._stream_chat_fallback_model
            if not fallback_model or fallback_model == self._model or not _is_retriable_chat_failure(exc):
                raise
            log.warning(  # type: ignore[no-any-return]
                "deepinfra_chat_with_tools_model_fallback",
                primary_model=self._model,
                fallback_model=fallback_model,
                n_messages=len(messages),
                n_tools=len(tools) if tools else 0,
                reason=type(exc).__name__,
                error=str(exc) or repr(exc),
            )
            return await _call(fallback_model)

    async def _stream_chat_one_model(
        self,
        messages: list[dict],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        """Run a single stream_chat call against a specific model.

        Extracted so ``stream_chat`` can transparently retry against a
        secondary model (PLAN-0104 W43) without duplicating the SSE-parsing
        loop.
        """
        payload: dict[str, object] = {
            "model": model,
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

        PLAN-0104 W43 / BP-NEW (zero-chunk same-provider model failover):
        Some long multi-tool second-turn calls against the primary completion
        model (Qwen3-235B at the time of writing) return HTTP 200 with an
        empty SSE — zero ``data: {...}`` content frames before ``[DONE]``.
        Cross-provider failover (W40) cannot help here because most deployments
        only have DeepInfra wired in the live stack.  When ``self._stream_chat_fallback_model``
        is set, we transparently retry the request once against that alternate
        model on the SAME provider before raising.  The W40 chain-level
        zero-chunk guard + W36 degraded-synthesis fallback remain in place as
        outer safety nets — this layer just gives them a far better shot at
        recovering a real LLM answer.

        We materialise the primary stream into a buffer because the OpenAI SSE
        API does not allow rewinding: if we yielded tokens piecemeal we could
        only detect "zero chunks" once iteration finished, at which point the
        caller would already have committed to an empty stream.  Latency is
        unaffected on the happy path — we yield the buffered tokens as soon
        as the primary stream completes (one extra event-loop tick).
        """
        primary_chunks: list[str] = []
        # PLAN-0104 W46: track whether the primary failed mid-setup (e.g. 429
        # on raise_for_status) vs completed empty (zero-chunk).  Both paths
        # now feed the same in-adapter fallback so the orchestrator never sees
        # a raw 429 from the synthesis turn when a cheaper model is configured.
        _primary_exc: BaseException | None = None
        try:
            async for chunk in self._stream_chat_one_model(
                messages,
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                primary_chunks.append(chunk)
        except Exception as exc:
            _primary_exc = exc

        if primary_chunks:
            # Got at least one token from the primary — emit and finish.
            # We DON'T fall back mid-stream because partial tokens cannot be
            # rewound on the wire (would emit duplicates to the client).
            for chunk in primary_chunks:
                yield chunk
            return

        fallback_model = self._stream_chat_fallback_model
        if not fallback_model or fallback_model == self._model:
            # No fallback configured; propagate any captured exception so the
            # provider chain sees the real failure mode (W40 zero-chunk guard
            # + W36 degraded-synthesis still catch this downstream).
            if _primary_exc is not None:
                raise _primary_exc
            return

        # If the primary raised something non-retriable (4xx auth, KeyError,
        # NotImplementedError, ...), the fallback model would not help.
        # Propagate so the chain can fall over to the next provider instead.
        if _primary_exc is not None and not _is_retriable_chat_failure(_primary_exc):
            raise _primary_exc

        log.warning(  # type: ignore[no-any-return]
            "deepinfra_stream_chat_model_fallback",
            primary_model=self._model,
            fallback_model=fallback_model,
            n_messages=len(messages),
            reason=(type(_primary_exc).__name__ if _primary_exc is not None else "zero_chunk_primary"),
            error=(str(_primary_exc) or repr(_primary_exc)) if _primary_exc is not None else "",
        )
        async for chunk in self._stream_chat_one_model(
            messages,
            model=fallback_model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    async def aclose(self) -> None:
        await self._client.aclose()
