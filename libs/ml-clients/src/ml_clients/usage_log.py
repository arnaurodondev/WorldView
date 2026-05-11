"""LLM usage log protocol and call-usage value object (PLAN-0033 Wave 1).

Defines:
  - ``LlmUsageLogProtocol`` — structural interface that every service-side
    cost-log repository must satisfy (runtime-checkable, Protocol).
  - ``LlmCallUsage`` — immutable value object returned by cost-aware adapters.

Design invariants:
  - ``LlmUsageLogProtocol`` lives in *ml-clients* (shared lib) so that adapters
    (GeminiDescriptionAdapter, LLMProviderChain) can accept loggers without
    importing service infrastructure.
  - Implementations MUST be non-blocking (fire-and-forget); callers use
    ``asyncio.create_task()`` — exceptions MUST be swallowed and logged via
    structlog so that a cost-logging failure never disrupts the main path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class LlmUsageLogProtocol(Protocol):
    """Structural protocol for LLM cost-log repositories.

    Every service that owns a ``llm_usage_log`` table implements this interface.
    Because the protocol is ``@runtime_checkable``, you can guard at runtime:

        assert isinstance(repo, LlmUsageLogProtocol)

    Keyword-only ``**context`` allows each service to pass domain-specific
    extras (e.g. ``doc_id``, ``entity_id``, ``session_id``) without breaking
    the shared signature — the implementation extracts what it needs.

    **Invariant**: implementations MUST swallow all internal exceptions and
    emit a structlog warning instead.  A cost-logging failure must never
    propagate to the caller.
    """

    async def log(
        self,
        *,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
        error_code: str | None = None,
        **context: object,
    ) -> None:
        """Append one LLM usage record.

        Args:
        ----
            model_id:            Model string used (e.g. "qwen2.5:3b").
            provider:            Provider name: "deepinfra" | "openrouter"
                                 | "gemini" | "ollama".
            capability:          Call type: "embedding" | "extraction"
                                 | "chat_completion" | "description"
                                 | "classification".
            tokens_in:           Input token count (exact or estimated).
            tokens_out:          Output token count (exact or estimated).
            latency_ms:          Wall-clock duration of the API call, ms.
            estimated_cost_usd:  USD cost estimate (0.0 for Ollama).
            success:             True on 2xx, False on exception/timeout.
            error_code:          Short error tag when success=False.
                                 Values: "timeout" | "rate_limit" | "auth"
                                 | "model_error" | None.
            **context:           Service-specific extras (doc_id, entity_id,
                                 session_id, tenant_id, …).

        """
        ...  # pragma: no cover


@dataclass(frozen=True)
class LlmCallUsage:
    """Immutable summary of one LLM call returned by cost-aware adapters.

    This is a *value object* — frozen dataclass, equality by value.

    Attributes
    ----------
        model_id:           Model string used for the call.
        provider:           Provider name (deepinfra / openrouter / gemini / ollama).
        capability:         Functional role of the call (embedding / chat_completion …).
        tokens_in:          Input token count (exact if API returns it, otherwise
                            word-count estimate via ``estimate_tokens_from_text``).
        tokens_out:         Output token count (same caveat).
        estimated_cost_usd: USD cost computed by ``estimate_cost()``.
        latency_ms:         Wall-clock duration of the API call in milliseconds.
        success:            True on 2xx response, False on exception or timeout.
        error_code:         Short error classification when success=False, or None.

    """

    model_id: str
    provider: str
    capability: str
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    latency_ms: int
    success: bool
    error_code: str | None = None
