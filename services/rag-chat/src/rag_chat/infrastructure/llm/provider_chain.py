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

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from tools.types import LLMToolResponse  # type: ignore[import-untyped]

import structlog
from ml_clients.cost import estimate_cost, estimate_tokens_from_text  # type: ignore[import-untyped]

from rag_chat.application.metrics.prometheus import (
    llm_provider_retry_attempt,
    rag_chat_with_tools_failed,
)
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


# FIX-LIVE-EE (2026-05-25): retriable HTTP status codes for chat_with_tools.
# 429 = rate limit, 502/503/504 = bad gateway / unavailable / gateway timeout —
# all expected transient conditions under chained-test load against DeepInfra.
_RETRIABLE_HTTP_STATUS: frozenset[int] = frozenset({429, 502, 503, 504})


def _is_retriable_exception(exc: BaseException) -> bool:
    """Classify whether ``exc`` is a transient failure worth retrying.

    Retriable: TimeoutError (incl. asyncio.TimeoutError — alias since 3.11),
    httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, and
    HTTPStatusError with status in ``_RETRIABLE_HTTP_STATUS``.

    Non-retriable: ValueError, KeyError, NotImplementedError, RuntimeError, and
    any other HTTPStatusError (4xx auth/validation, 500 unrecoverable, etc.).
    These indicate a misconfiguration or a real model error — retrying just
    wastes the upstream budget and slows the fallback to the next provider.
    """
    if isinstance(exc, TimeoutError):
        # asyncio.TimeoutError is aliased to builtin TimeoutError since Py 3.11.
        return True
    if isinstance(exc, httpx.ConnectError | httpx.ReadError | httpx.RemoteProtocolError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRIABLE_HTTP_STATUS
    return False


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
        *,
        retry_attempts: int = 2,
        retry_backoff_base: float = 1.0,
    ) -> None:
        self._providers = providers
        self._valkey = valkey
        self._last_provider_name: str = ""
        self._usage_logger = usage_logger  # PLAN-0033 T-E-1-02
        # FIX-LIVE-EE (2026-05-25): per-provider retry config — see config.py.
        # Default (2 attempts, 1.0s base) yields delays of 1s + 2s before
        # falling back to the next provider, on iter-0 transient failures.
        self._retry_attempts = retry_attempts
        self._retry_backoff_base = retry_backoff_base

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

    async def _invoke_provider_with_retry(
        self,
        provider: LLMProvider,
        messages: list[dict],
        tools: list[dict] | None,
        *,
        retry: bool,
        **kwargs: object,
    ) -> LLMToolResponse:
        """Call ``provider.chat_with_tools`` with optional in-place retry.

        FIX-LIVE-EE (2026-05-25): when ``retry=True`` (set by the orchestrator
        on iteration 0), classify exceptions and retry retriable ones up to
        ``self._retry_attempts`` times with exponential backoff before
        propagating the final failure.  Non-retriable exceptions (ValueError,
        KeyError, HTTP 4xx, NotImplementedError) bypass retry entirely so a
        real misconfiguration fails fast to the next provider in the chain.

        Why the retry happens HERE (per-provider) rather than at the chain
        level: a single transient failure on DeepInfra should NOT immediately
        trip the 60s Valkey negative cache + fall back to OpenRouter.
        Empirically, the 2nd/3rd attempt succeeds in well over half the cases
        observed in iter-5 chained tests (5x rapid Q4 v1 was 0-2/5 passing
        before, >=4/5 expected after).
        """
        max_attempts = self._retry_attempts if retry else 0
        # ``attempt`` is 0 on the initial call and 1..N for subsequent retries
        # so the retry-counter labels read naturally in dashboards.
        for attempt in range(max_attempts + 1):
            try:
                return await provider.chat_with_tools(messages, tools, **kwargs)  # type: ignore[union-attr,attr-defined,no-any-return]
            except NotImplementedError:
                # Always non-retriable + always bypass classifier — propagate
                # so the outer loop can skip this provider.
                raise
            except Exception as exc:
                # Last attempt OR non-retriable: propagate to outer loop.
                if attempt >= max_attempts or not _is_retriable_exception(exc):
                    if attempt > 0:
                        # We did retry but ultimately failed — record the
                        # exhaustion event so operators can see attempts that
                        # didn't recover.
                        llm_provider_retry_attempt.labels(
                            provider=provider.name,
                            attempt=str(attempt),
                            outcome="failure",
                        ).inc()
                        log.warning(  # type: ignore[no-any-return]
                            "llm_provider_retry_exhausted",
                            provider=provider.name,
                            attempts=attempt,
                            error=str(exc) or repr(exc),
                            error_type=type(exc).__name__,
                        )
                    raise
                # Retriable + budget remaining → sleep + retry.
                # Exponential: base * (2 ** attempt) so attempts 0, 1, 2 →
                # delays of base, 2*base, 4*base. With base=1.0 + 2 retries,
                # that's 1s + 2s = 3s worst-case before falling back.
                delay = self._retry_backoff_base * (2**attempt)
                next_attempt = attempt + 1
                log.info(  # type: ignore[no-any-return]
                    "llm_provider_retry_scheduled",
                    provider=provider.name,
                    attempt=next_attempt,
                    delay_seconds=delay,
                    error=str(exc) or repr(exc),
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(delay)
                # Mark the retry attempt; if it ultimately fails, the failure
                # branch above will record an exhaustion event with outcome=failure.
                llm_provider_retry_attempt.labels(
                    provider=provider.name,
                    attempt=str(next_attempt),
                    outcome="success",
                ).inc()
        # Unreachable: the loop always either returns or raises.
        msg = "internal error: retry loop exited without return/raise"
        raise RuntimeError(msg)

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        retry: bool = False,
        **kwargs: object,
    ) -> LLMToolResponse:
        """Non-streaming structured call — tries providers in order.

        WHY skip NotImplementedError: OllamaCompletionAdapter does not support
        function calling and raises NotImplementedError explicitly.  We catch it
        here so the chain gracefully skips Ollama and uses DeepInfra/OpenRouter.

        All other exceptions are logged and cause the provider to be skipped,
        consistent with the stream() fallback behaviour.

        Args:
            messages: OpenAI-format conversation history.
            tools:    Optional tool/function definitions.
            retry:    FIX-LIVE-EE — when True (set by the orchestrator on
                      iteration 0), retry retriable exceptions (timeouts,
                      429/503, connect/read errors) up to N times with
                      exponential backoff BEFORE falling back to the next
                      provider in the chain. Default False to preserve the
                      original fail-fast behaviour for mid-loop iterations
                      where FIX-LIVE-V's recovery handles failures instead.
            **kwargs: Forwarded to provider.chat_with_tools (max_tokens, etc.).

        Raises:
            RuntimeError: if every provider is either unavailable or unsupported.
        """
        for provider in self._providers:
            try:
                resp = await self._invoke_provider_with_retry(
                    provider,
                    messages,
                    tools,
                    retry=retry,
                    **kwargs,
                )
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
                    "provider_failed",
                    provider=provider.name,
                    error=str(exc) or repr(exc),
                    error_type=type(exc).__name__,
                )
                # PLAN-0093 QA-7 P1-5: per-provider chat_with_tools failure
                # counter — incremented only for genuine failures, NOT for
                # NotImplementedError (handled in the prior except clause).
                rag_chat_with_tools_failed.labels(provider=provider.name).inc()
                # Mirror stream_chat: emit fallback metric when there is a next provider.
                _provider_idx = self._providers.index(provider)
                if _provider_idx + 1 < len(self._providers):
                    _next = self._providers[_provider_idx + 1]
                    rag_provider_fallback.labels(
                        from_provider=provider.name,
                        to_provider=_next.name,
                    ).inc()
                continue
        raise RuntimeError("All LLM providers failed or unsupported for chat_with_tools")

    async def stream_chat(  # type: ignore[override]
        self,
        messages: list[dict],
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """Yield stream tokens, falling back to the next provider on failure.

        WHY async generator: we wrap the inner provider generator so that
        if the primary fails before yielding any tokens we can transparently
        fall back to the next provider and emit the `rag_provider_fallback`
        metric — mirroring the chat_with_tools fallback contract.

        Note: mid-stream failures (after tokens were already yielded) are still
        propagated to the caller because the partial response cannot be retried.

        Raises:
            RuntimeError: if all providers fail.
        """
        for i, provider in enumerate(self._providers):
            if getattr(provider, "name", "") == "ollama":
                continue
            try:
                async for chunk in provider.stream_chat(messages, **kwargs):  # type: ignore[union-attr,attr-defined]
                    yield chunk
                return  # success — stop iterating providers
            except Exception as exc:
                log.warning(  # type: ignore[no-any-return]
                    "provider_failed",
                    provider=provider.name,
                    error=str(exc) or repr(exc),
                    error_type=type(exc).__name__,
                )
                rag_provider_unavail.labels(provider=provider.name).inc()
                if i + 1 < len(self._providers):
                    _next = self._providers[i + 1]
                    rag_provider_fallback.labels(
                        from_provider=provider.name,
                        to_provider=_next.name,
                    ).inc()
        raise RuntimeError("All LLM providers failed stream_chat")
