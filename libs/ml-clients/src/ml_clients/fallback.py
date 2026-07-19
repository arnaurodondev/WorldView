"""Primary → fallback wrappers for ML adapters (LIB-004 / TASK-W4-02).

Adapter-layer fallback so services don't have to wire their own
try/except primary → fallback chains. Each wrapper composes a *primary*
adapter and a *fallback* adapter (any duck-typed pair that satisfies the
matching :mod:`ml_clients.protocols` Protocol). The wrapper invokes the
primary first and, on :class:`~ml_clients.errors.RetryableError`
(timeout, 5xx, 429 after exhausting per-adapter retries), transparently
falls back to the secondary.

Design notes
------------
* **Retryable → fall back; fatal → propagate.**  ``FatalError`` is raised
  for malformed requests (e.g. 4xx other than 429, auth errors) — the
  secondary adapter would fail the same way, so we surface the original
  error to the caller instead of doubling the latency budget.
* **RateLimitError IS a RetryableError.**  The class hierarchy
  (``Exception → ConsumerError → RetryableError → RateLimitedError →
  RateLimitError``) means a 429 from the primary will trigger fallback
  exactly the same as a 5xx or timeout. This matches the audit's
  W4-02 acceptance criteria.
* **No fallback retries here.**  Each adapter is already expected to
  apply its own internal retry policy (httpx + tenacity, etc.). When the
  primary's retries are exhausted we make a *single* call against the
  fallback — adding another retry layer here would amplify outage
  blast-radius and break Retry-After semantics.
* **Back-compatibility is preserved by NOT touching existing adapters.**
  Services that don't opt-in (don't construct one of these wrappers)
  keep their current behaviour exactly. Service-side fallback code can
  be replaced by ``FallbackEmbeddingClient(primary, fallback)`` etc. as
  a follow-up.
* **One wrapper class per Protocol shape.**  A single generic wrapper
  would type-erase the methods and lose static checking. Three small
  classes match the three protocols in :mod:`ml_clients.protocols` and
  cost virtually no extra code.

Example
-------
.. code-block:: python

    from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
    from ml_clients.fallback import FallbackEmbeddingClient

    primary = DeepInfraEmbeddingAdapter(api_key=..., ...)
    fallback = OllamaEmbeddingAdapter(base_url=..., semaphore=..., ...)
    client = FallbackEmbeddingClient(primary=primary, fallback=fallback)

    # Identical interface to EmbeddingClient — no service changes needed
    # beyond the wiring point.
    outputs = await client.embed(inputs)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ml_clients.errors import RetryableError

if TYPE_CHECKING:
    from ml_clients.dataclasses import (
        EmbeddingInput,
        EmbeddingOutput,
        ExtractionInput,
        ExtractionOutput,
        NERInput,
        NEROutput,
    )
    from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient

logger = structlog.get_logger(__name__)

__all__ = [
    "FallbackEmbeddingClient",
    "FallbackExtractionClient",
    "FallbackNERClient",
]


def _log_fallback(
    *,
    primary: object,
    fallback: object,
    operation: str,
    error: BaseException,
) -> None:
    """Centralised structured log emitted whenever a fallback fires.

    Keeps the log shape consistent across the three wrappers so
    operators can build a single Grafana panel / alert on
    ``ml_client_falling_back_to_secondary``.
    """
    logger.warning(
        "ml_client_falling_back_to_secondary",
        primary=type(primary).__name__,
        fallback=type(fallback).__name__,
        operation=operation,
        error=str(error),
        error_type=type(error).__name__,
    )


class FallbackEmbeddingClient:
    """Wraps a primary + fallback :class:`EmbeddingClient` pair.

    Conforms to the :class:`ml_clients.protocols.EmbeddingClient` Protocol —
    service code that previously held a single adapter can swap to this
    wrapper without any other changes.
    """

    def __init__(self, *, primary: EmbeddingClient, fallback: EmbeddingClient) -> None:
        # Keyword-only so accidental positional swaps (``primary``/``fallback``
        # are interchangeable types) are impossible at the call site.
        self._primary = primary
        self._fallback = fallback

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        """Embed via primary; on RetryableError, retry once via fallback.

        FatalError (genuine bad input: 400/404/413/422) propagates without invoking
        the fallback — bad input won't get better on a second backend.

        BP-729 author-awareness: ``ProviderBillingError`` (HTTP 402/401/403) is a
        ``RetryableError`` subclass, so a primary spend-cap / auth refusal now ALSO
        triggers fallback-to-secondary. For 402 (spend-cap) this is desirable — a
        free/local secondary (e.g. Ollama) keeps embeddings flowing while the cap is
        raised. The trade-off: a PERMANENT primary 401/403 (revoked key) is silently
        served from the fallback instead of surfacing. The embedding retry worker's
        billing-defer metric + persistent-abandon escalation (BP-729) covers the
        retry-queue path; if a primary key can be revoked long-term while a fallback
        masks it here, add primary-health alerting rather than relying on this wrapper
        to surface it.
        """
        try:
            return await self._primary.embed(inputs)
        except RetryableError as exc:
            _log_fallback(
                primary=self._primary,
                fallback=self._fallback,
                operation="embed",
                error=exc,
            )
            # If the fallback also fails (Retryable or Fatal) we let the
            # exception propagate untouched — the caller's Kafka retry /
            # DLQ layer is responsible for that case.
            return await self._fallback.embed(inputs)


class FallbackNERClient:
    """Wraps a primary + fallback :class:`NERClient` pair."""

    def __init__(self, *, primary: NERClient, fallback: NERClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def extract_entities(self, inp: NERInput) -> NEROutput:
        try:
            return await self._primary.extract_entities(inp)
        except RetryableError as exc:
            _log_fallback(
                primary=self._primary,
                fallback=self._fallback,
                operation="extract_entities",
                error=exc,
            )
            return await self._fallback.extract_entities(inp)

    async def batch_extract_entities(self, inputs: list[NERInput]) -> list[NEROutput]:
        try:
            return await self._primary.batch_extract_entities(inputs)
        except RetryableError as exc:
            _log_fallback(
                primary=self._primary,
                fallback=self._fallback,
                operation="batch_extract_entities",
                error=exc,
            )
            return await self._fallback.batch_extract_entities(inputs)


class FallbackExtractionClient:
    """Wraps a primary + fallback :class:`ExtractionClient` pair."""

    def __init__(self, *, primary: ExtractionClient, fallback: ExtractionClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        try:
            return await self._primary.extract(inp)
        except RetryableError as exc:
            _log_fallback(
                primary=self._primary,
                fallback=self._fallback,
                operation="extract",
                error=exc,
            )
            return await self._fallback.extract(inp)
