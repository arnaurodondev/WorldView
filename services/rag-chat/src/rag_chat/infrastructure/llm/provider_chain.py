"""LLM provider fallback chain with Valkey-backed negative caching (T-F-3-01, W11-1).

Provider order: DeepInfra -> OpenRouter -> Ollama (emergency)
Negative cache: 60 seconds per failed provider (rag:v1:neg:{provider_name})

PLAN-0033 T-E-1-02: post-stream cost logging via LlmUsageLogProtocol.
Token counts are approximated from prompt/output text (word-count heuristic —
DeepInfra stream yields text chunks without token-count metadata).

W11-1 additions:
- chat_with_tools(): non-streaming structured call; skips Ollama (NotImplementedError)
- stream_chat(): streaming from a messages list; skips Ollama
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tools.types import LLMToolResponse  # type: ignore[import-untyped]

import structlog
from ml_clients.cost import estimate_cost, estimate_tokens_from_text  # type: ignore[import-untyped]

from rag_chat.domain.errors import ProviderUnavailableError
from rag_chat.infrastructure.metrics.prometheus import (
    rag_first_token,
    rag_provider_fallback,
    rag_provider_unavail,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_NEG_CACHE_TTL = 60  # seconds
_NEG_KEY_PREFIX = "rag:v1:neg:"


class LLMProvider(Protocol):
    """Protocol for LLM streaming providers."""

    name: str

    def stream(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]: ...


class LLMProviderChain:
    """3-tier LLM provider with automatic fallback and negative caching.

    On success: yields token chunks and returns.
    On failure: negative-caches the provider for 60 s, tries next.
    When all fail: raises ProviderUnavailableError.

    Args:
    ----
        providers:     Ordered list of provider adapters (primary first).
        valkey:        Async Redis/Valkey client for negative cache storage.
        usage_logger:  Optional LlmUsageLogProtocol; if set, cost is logged
                       fire-and-forget after each successful or failed stream.

    """

    def __init__(
        self,
        providers: list[LLMProvider],
        valkey: ValkeyClient,  # type: ignore[name-defined]
        usage_logger: LlmUsageLogProtocol | None = None,
    ) -> None:
        self._providers = providers
        self._valkey = valkey
        self._last_provider_name: str = ""
        self._usage_logger = usage_logger  # PLAN-0033 T-E-1-02

    @property
    def last_provider_name(self) -> str:
        """Name of the provider that successfully served the last request."""
        return self._last_provider_name

    async def stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 4000,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Stream tokens from the first available provider.

        After a successful stream, fires a fire-and-forget cost log via
        ``usage_logger`` (PLAN-0033 T-E-1-02).  Token counts are estimated
        from the prompt text and accumulated output using word-count heuristic.

        Raises
        ------
            ProviderUnavailableError: All providers failed or are negative-cached.

        """
        for provider in self._providers:
            neg_key = f"{_NEG_KEY_PREFIX}{provider.name}"
            if await self._valkey.exists(neg_key):
                log.debug(  # type: ignore[no-any-return]
                    "provider_neg_cached_skip",
                    provider=provider.name,
                )
                continue

            t0 = time.monotonic()
            _first_token_recorded = False
            output_chunks: list[str] = []

            try:
                self._last_provider_name = provider.name
                async for chunk in provider.stream(prompt, max_tokens=max_tokens, temperature=temperature):
                    if not _first_token_recorded:
                        rag_first_token.labels(provider=provider.name).observe(time.monotonic() - t0)
                        _first_token_recorded = True
                    output_chunks.append(chunk)
                    yield chunk

                # ── Success: fire-and-forget cost log ────────────────────────
                if self._usage_logger is not None:
                    active_model = getattr(provider, "model_id", provider.name)
                    tokens_in = estimate_tokens_from_text(prompt)
                    tokens_out = estimate_tokens_from_text("".join(output_chunks))
                    cost = estimate_cost(provider.name, active_model, tokens_in, tokens_out)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    asyncio.create_task(  # noqa: RUF006 — fire-and-forget observer
                        self._usage_logger.log(
                            model_id=active_model,
                            provider=provider.name,
                            capability="chat_completion",
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            latency_ms=latency_ms,
                            estimated_cost_usd=cost,
                            success=True,
                        ),
                    )
                return  # success

            except Exception as exc:
                log.warning(  # type: ignore[no-any-return]
                    "provider_failed",
                    provider=provider.name,
                    error=str(exc),
                )
                rag_provider_unavail.labels(provider=provider.name).inc()
                await self._valkey.setex(neg_key, _NEG_CACHE_TTL, "1")
                # Record fallback if there's a subsequent provider in the chain.
                _provider_idx = self._providers.index(provider)
                if _provider_idx + 1 < len(self._providers):
                    _next = self._providers[_provider_idx + 1]
                    rag_provider_fallback.labels(
                        from_provider=provider.name,
                        to_provider=_next.name,
                    ).inc()

        # All providers exhausted — log failure then raise
        if self._usage_logger is not None:
            tokens_in = estimate_tokens_from_text(prompt)
            asyncio.create_task(  # noqa: RUF006 — fire-and-forget observer
                self._usage_logger.log(
                    model_id="unknown",
                    provider="unknown",
                    capability="chat_completion",
                    tokens_in=tokens_in,
                    tokens_out=0,
                    latency_ms=0,
                    estimated_cost_usd=0.0,
                    success=False,
                    error_code="model_error",
                ),
            )

        raise ProviderUnavailableError("All LLM providers unavailable or negative-cached")

    # ------------------------------------------------------------------
    # Structured chat with optional function calling (W11-1)
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> LLMToolResponse:
        """Non-streaming structured call — tries providers in order.

        WHY skip NotImplementedError: OllamaCompletionAdapter does not support
        function calling and raises NotImplementedError explicitly.  We catch it
        here so the chain gracefully skips Ollama and uses DeepInfra/OpenRouter.

        All other exceptions are logged and cause the provider to be skipped,
        consistent with the stream() fallback behaviour.

        Raises:
            RuntimeError: if every provider is either unavailable or unsupported.
        """
        for provider in self._providers:
            try:
                resp = await provider.chat_with_tools(messages, tools, **kwargs)  # type: ignore[union-attr,attr-defined]
                # Log token usage if the provider returned it
                if self._usage_logger is not None and resp.usage:
                    active_model = getattr(provider, "model_id", provider.name)
                    asyncio.create_task(  # noqa: RUF006 — fire-and-forget observer
                        self._usage_logger.log(
                            model_id=active_model,
                            provider=provider.name,
                            capability="chat_with_tools",
                            tokens_in=resp.usage.get("prompt_tokens", 0),
                            tokens_out=resp.usage.get("completion_tokens", 0),
                            latency_ms=0,
                            estimated_cost_usd=0.0,
                            success=True,
                        ),
                    )
                return resp  # type: ignore[no-any-return]
            except NotImplementedError:
                # Skip providers that don't support function calling (e.g. Ollama)
                continue
            except Exception as exc:
                # FIX-LIVE-X (2026-05-25): include the exception class name so
                # silent failures like asyncio.TimeoutError (which has empty
                # str()) are still actionable from logs.  Previously a
                # tool-call turn timeout surfaced as `error=""` and the
                # operator had no way to tell apart a timeout from a 4xx.
                log.warning(  # type: ignore[no-any-return]
                    "provider_chat_with_tools_failed",
                    provider=provider.name,
                    error=str(exc) or repr(exc),
                    error_type=type(exc).__name__,
                )
                continue
        raise RuntimeError("All LLM providers failed or unsupported for chat_with_tools")

    def stream_chat(
        self,
        messages: list[dict],
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """Delegate stream_chat to the first provider that supports it.

        WHY skip NotImplementedError: same pattern as chat_with_tools — Ollama
        raises NotImplementedError to signal it can't handle message-list streaming.

        Returns the async generator from the first supporting provider so the caller
        can iterate it directly.  We don't wrap in a fallback generator because
        streaming mid-response is not resumable; the caller must retry from scratch.

        Raises:
            RuntimeError: if no provider supports stream_chat.
        """
        for provider in self._providers:
            # Check if the provider has stream_chat and it won't raise NotImplementedError
            if not hasattr(provider, "stream_chat"):
                continue
            # Return the generator from the first capable provider
            # Ollama will raise NotImplementedError synchronously, so we filter
            # by checking the name (simple heuristic consistent with provider.name)
            if getattr(provider, "name", "") == "ollama":
                continue
            return provider.stream_chat(messages, **kwargs)  # type: ignore[union-attr,return-value,no-any-return]
        raise RuntimeError("No LLM provider supports stream_chat")
