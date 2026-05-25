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
    rag_chat_with_tools_failed,
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

    async def _record_provider_failure(
        self,
        provider: LLMProvider,
        exc: BaseException,
        *,
        call_site: str,
    ) -> None:
        """Record a provider failure: log + unavail metric + neg-cache + fallback metric.

        PLAN-0093 QA-7 P1-2: this helper is shared by stream(), chat_with_tools() and
        stream_chat() so a DeepInfra outage is visible in `rag_provider_fallback_total`
        regardless of which entry point the caller used. The `call_site` label is used
        only in the structured log to disambiguate which path failed — it is NOT a
        metric label, so cardinality stays bounded by provider name.
        """
        log.warning(  # type: ignore[no-any-return]
            "provider_failed",
            from_provider=provider.name,
            to_provider=self._next_provider_name(provider),
            error=str(exc),
            call_site=call_site,
        )
        rag_provider_unavail.labels(provider=provider.name).inc()
        await self._valkey.setex(f"{_NEG_KEY_PREFIX}{provider.name}", _NEG_CACHE_TTL, "1")
        # Record fallback if there's a subsequent provider in the chain.
        _idx = self._providers.index(provider)
        if _idx + 1 < len(self._providers):
            rag_provider_fallback.labels(
                from_provider=provider.name,
                to_provider=self._providers[_idx + 1].name,
            ).inc()

    def _next_provider_name(self, provider: LLMProvider) -> str:
        """Return the next provider's name in the chain, or "none" if last."""
        _idx = self._providers.index(provider)
        if _idx + 1 < len(self._providers):
            return self._providers[_idx + 1].name
        return "none"

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
                await self._record_provider_failure(provider, exc, call_site="stream")

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
                # PLAN-0093 QA-7 P1-5: increment per-provider failure counter so
                # tool-use outages are dashable, not just logged.
                rag_chat_with_tools_failed.labels(provider=provider.name).inc()
                log.warning(  # type: ignore[no-any-return]
                    "provider_chat_with_tools_failed",
                    provider=provider.name,
                    error=str(exc),
                )
                # PLAN-0093 QA-7 P1-2: also record symmetric fallback (neg-cache +
                # rag_provider_fallback) so a DeepInfra outage in the tool-use loop
                # surfaces on the same dashboard as a streaming outage.
                await self._record_provider_failure(provider, exc, call_site="chat_with_tools")
                continue
        raise RuntimeError("All LLM providers failed or unsupported for chat_with_tools")

    async def stream_chat(
        self,
        messages: list[dict],
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """Stream final-answer chunks from the first provider that supports it.

        WHY async generator (vs the previous sync-return-generator): so we can
        observe per-provider failures and record `rag_provider_fallback` +
        neg-cache symmetric with stream(). PLAN-0093 QA-7 P1-2.

        WHY skip NotImplementedError: Ollama raises NotImplementedError to signal
        it can't handle message-list streaming; we filter by name as before.

        Note: streaming mid-response is not resumable; if a provider's generator
        raises mid-iteration, we record the failure and move to the next provider
        but the caller will see two chunk-streams stitched. Callers that need a
        single contiguous stream should re-issue the call instead.

        Raises:
            RuntimeError: if no provider supports stream_chat.
        """
        any_attempted = False
        for provider in self._providers:
            if not hasattr(provider, "stream_chat"):
                continue
            if getattr(provider, "name", "") == "ollama":
                continue
            neg_key = f"{_NEG_KEY_PREFIX}{provider.name}"
            if await self._valkey.exists(neg_key):
                log.debug(  # type: ignore[no-any-return]
                    "provider_neg_cached_skip",
                    provider=provider.name,
                    call_site="stream_chat",
                )
                continue
            any_attempted = True
            try:
                async for chunk in provider.stream_chat(messages, **kwargs):  # type: ignore[union-attr]
                    yield chunk
                return
            except NotImplementedError:
                # Defensive: an adapter may raise this even though name != "ollama".
                continue
            except Exception as exc:
                # PLAN-0093 QA-7 P1-2: symmetric fallback recording for stream_chat.
                await self._record_provider_failure(provider, exc, call_site="stream_chat")
                continue
        if not any_attempted:
            raise RuntimeError("No LLM provider supports stream_chat")
        raise RuntimeError("All LLM providers failed for stream_chat")
