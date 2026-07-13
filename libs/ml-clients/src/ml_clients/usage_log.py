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
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID


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
        cost_source: str | None = None,
        user_id: UUID | None = None,
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
            cost_source:         Provenance of ``estimated_cost_usd`` (PLAN-0117
                                 FR-2): "provider" (verbatim from the provider's
                                 ``usage.estimated_cost``), "pricematrix"
                                 (computed via ``pricing.compute_cost``), or
                                 "local" ($0 Ollama/GLiNER). ``None`` means a
                                 legacy caller that has not been migrated yet.
            user_id:             Authenticated end-user UUID when a genuine user
                                 triggered the call (PLAN-0117 FR-3); ``None``
                                 for system/background pipeline calls.
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
        provider_cost_usd:  Verbatim ``usage.estimated_cost`` returned by the
                            provider (DeepInfra reports this), as a
                            :class:`decimal.Decimal`; ``None`` when the provider
                            did not report a cost (PLAN-0117 FR-1).
        cost_source:        Provenance of the persisted cost: "provider" |
                            "pricematrix" | "local" (PLAN-0117 FR-2). Defaults to
                            "pricematrix" — the historical behaviour when no
                            provider cost is available.

    Invariants (documented; asserted by callers, not enforced on this frozen VO):
      * ``cost_source == "provider"`` ⇒ ``provider_cost_usd is not None``.
      * ``cost_source == "local"``    ⇒ ``estimated_cost_usd == 0``.

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
    # PLAN-0117 FR-1/FR-2 — appended with defaults so every existing positional
    # or keyword construction that stops at ``error_code`` keeps compiling
    # unchanged (verified: no production code constructs LlmCallUsage today).
    provider_cost_usd: Decimal | None = None
    cost_source: str = "pricematrix"
