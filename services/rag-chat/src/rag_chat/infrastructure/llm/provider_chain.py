"""LLM provider fallback chain with Valkey-backed negative caching (T-F-3-01).

Provider order: DeepInfra -> OpenRouter -> Ollama (emergency)
Negative cache: 60 seconds per failed provider (rag:v1:neg:{provider_name})
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import structlog

from rag_chat.domain.errors import ProviderUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
        providers: Ordered list of provider adapters (primary first).
        valkey:    Async Redis/Valkey client for negative cache storage.
    """

    def __init__(
        self,
        providers: list[LLMProvider],
        valkey: ValkeyClient,  # type: ignore[name-defined]
    ) -> None:
        self._providers = providers
        self._valkey = valkey
        self._last_provider_name: str = ""

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

        Raises:
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

            try:
                self._last_provider_name = provider.name
                async for chunk in provider.stream(prompt, max_tokens=max_tokens, temperature=temperature):
                    yield chunk
                return  # success

            except Exception as exc:
                log.warning(  # type: ignore[no-any-return]
                    "provider_failed",
                    provider=provider.name,
                    error=str(exc),
                )
                await self._valkey.setex(neg_key, _NEG_CACHE_TTL, "1")

        raise ProviderUnavailableError("All LLM providers unavailable or negative-cached")
