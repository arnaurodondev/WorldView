"""LLM fallback chain client (PRD §6.7 Block 13D).

Wraps primary (Ollama) and secondary (Gemini Flash Lite) ML clients with:
  - Retry with configurable backoff delays.
  - Automatic fallback from primary to secondary on exhaustion.
  - NULL result + caller-scheduled retry when both chains are exhausted.
  - All calls logged to ``llm_usage_log`` (including $0 Ollama calls).

Retry schedule:
  - Ollama:  max_retries_ollama attempts, delays = retry_delays_ollama (default 30/60/120 s).
  - Gemini:  max_retries_gemini attempts,  delays = retry_delays_gemini (default 30/60 s).

In unit tests, pass ``retry_delays_ollama=[]`` and ``retry_delays_gemini=[]``
to skip sleeping.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput, ExtractionInput, ExtractionOutput
    from ml_clients.protocols import EmbeddingClient, ExtractionClient

    from knowledge_graph.infrastructure.intelligence_db.repositories.llm_usage_log import LlmUsageLogRepository

logger = get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_OLLAMA_DELAYS = (30.0, 60.0, 120.0)
_DEFAULT_GEMINI_DELAYS = (30.0, 60.0)


class FallbackChainClient:
    """Primary-Ollama → secondary-Gemini fallback with logging.

    Args:
        ollama_embedding: Primary embedding client (Ollama).
        gemini_embedding: Secondary embedding client (Gemini Flash Lite).
        ollama_extraction: Primary extraction client (Ollama).
        gemini_extraction: Secondary extraction client (Gemini Flash Lite).
        usage_log_repo:  Repository for LLM cost logging; may be None (logging skipped).
        retry_delays_ollama: Seconds to wait between Ollama attempts.
        retry_delays_gemini: Seconds to wait between Gemini attempts.
    """

    def __init__(
        self,
        *,
        ollama_embedding: EmbeddingClient | None = None,
        gemini_embedding: EmbeddingClient | None = None,
        ollama_extraction: ExtractionClient | None = None,
        gemini_extraction: ExtractionClient | None = None,
        usage_log_repo: LlmUsageLogRepository | None = None,
        retry_delays_ollama: tuple[float, ...] = _DEFAULT_OLLAMA_DELAYS,
        retry_delays_gemini: tuple[float, ...] = _DEFAULT_GEMINI_DELAYS,
    ) -> None:
        self._ollama_emb = ollama_embedding
        self._gemini_emb = gemini_embedding
        self._ollama_ext = ollama_extraction
        self._gemini_ext = gemini_extraction
        self._log_repo = usage_log_repo
        self._delays_ollama = retry_delays_ollama
        self._delays_gemini = retry_delays_gemini

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed(
        self,
        inputs: list[EmbeddingInput],
        *,
        entity_id: UUID | None = None,
    ) -> list[EmbeddingOutput] | None:
        """Embed inputs via Ollama → Gemini fallback.

        Returns None if both chains are exhausted (caller should schedule retry).
        """
        result = await self._try_embedding(
            self._ollama_emb,
            inputs,
            provider="ollama",
            delays=self._delays_ollama,
            entity_id=entity_id,
            estimated_cost_usd=0.0,
        )
        if result is not None:
            return result

        result = await self._try_embedding(
            self._gemini_emb,
            inputs,
            provider="gemini",
            delays=self._delays_gemini,
            entity_id=entity_id,
            estimated_cost_usd=_gemini_embedding_cost(inputs),
        )
        if result is None:
            logger.warning("fallback_chain_exhausted", capability="embedding")  # type: ignore[no-any-return]
        return result

    async def extract(
        self,
        inp: ExtractionInput,
        *,
        entity_id: UUID | None = None,
    ) -> ExtractionOutput | None:
        """Extract via Ollama → Gemini fallback.

        Returns None if both chains are exhausted.
        """
        result = await self._try_extraction(
            self._ollama_ext,
            inp,
            provider="ollama",
            delays=self._delays_ollama,
            entity_id=entity_id,
            estimated_cost_usd=0.0,
        )
        if result is not None:
            return result

        result = await self._try_extraction(
            self._gemini_ext,
            inp,
            provider="gemini",
            delays=self._delays_gemini,
            entity_id=entity_id,
            estimated_cost_usd=_gemini_extraction_cost(inp),
        )
        if result is None:
            logger.warning("fallback_chain_exhausted", capability="extraction")  # type: ignore[no-any-return]
        return result

    # ------------------------------------------------------------------
    # Private retry loops
    # ------------------------------------------------------------------

    async def _try_embedding(
        self,
        client: EmbeddingClient | None,
        inputs: list[EmbeddingInput],
        provider: str,
        delays: tuple[float, ...],
        entity_id: UUID | None,
        estimated_cost_usd: float,
    ) -> list[EmbeddingOutput] | None:
        if client is None:
            return None

        max_attempts = len(delays) + 1
        for attempt in range(max_attempts):
            t0 = time.monotonic()
            try:
                result = await client.embed(inputs)
                latency_ms = int((time.monotonic() - t0) * 1000)
                await self._log(
                    model_id=getattr(client, "model_id", provider),
                    provider=provider,
                    capability="embedding",
                    tokens_in=sum(len(i.text.split()) for i in inputs),
                    tokens_out=0,
                    latency_ms=latency_ms,
                    entity_id=entity_id,
                    estimated_cost_usd=estimated_cost_usd,
                    success=True,
                )
                return result
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                await self._log(
                    model_id=getattr(client, "model_id", provider),
                    provider=provider,
                    capability="embedding",
                    tokens_in=sum(len(i.text.split()) for i in inputs),
                    tokens_out=0,
                    latency_ms=latency_ms,
                    entity_id=entity_id,
                    estimated_cost_usd=0.0,
                    success=False,
                )
                logger.warning(  # type: ignore[no-any-return]
                    "fallback_chain_attempt_failed",
                    provider=provider,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
        return None

    async def _try_extraction(
        self,
        client: ExtractionClient | None,
        inp: ExtractionInput,
        provider: str,
        delays: tuple[float, ...],
        entity_id: UUID | None,
        estimated_cost_usd: float,
    ) -> ExtractionOutput | None:
        if client is None:
            return None

        max_attempts = len(delays) + 1
        for attempt in range(max_attempts):
            t0 = time.monotonic()
            try:
                result = await client.extract(inp)
                latency_ms = int((time.monotonic() - t0) * 1000)
                await self._log(
                    model_id=getattr(client, "model_id", provider),
                    provider=provider,
                    capability="extraction",
                    tokens_in=len(inp.prompt.split()) + len(inp.context.split()),
                    tokens_out=len(str(result.result).split()),
                    latency_ms=latency_ms,
                    entity_id=entity_id,
                    estimated_cost_usd=estimated_cost_usd,
                    success=True,
                )
                return result
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                await self._log(
                    model_id=getattr(client, "model_id", provider),
                    provider=provider,
                    capability="extraction",
                    tokens_in=len(inp.prompt.split()) + len(inp.context.split()),
                    tokens_out=0,
                    latency_ms=latency_ms,
                    entity_id=entity_id,
                    estimated_cost_usd=0.0,
                    success=False,
                )
                logger.warning(  # type: ignore[no-any-return]
                    "fallback_chain_attempt_failed",
                    provider=provider,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])
        return None

    async def _log(self, **kwargs: Any) -> None:
        """Log to usage_log_repo if available; swallow errors to never block callers."""
        if self._log_repo is None:
            return
        try:
            await self._log_repo.insert(**kwargs)
        except Exception as exc:
            logger.warning("llm_usage_log_write_failed", error=str(exc))  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Simple cost estimators (approximate)
# ---------------------------------------------------------------------------


def _gemini_embedding_cost(inputs: list[EmbeddingInput]) -> float:
    total_chars = sum(len(i.text) for i in inputs)
    return round(total_chars / 1_000_000 * 0.00002, 8)


def _gemini_extraction_cost(inp: ExtractionInput) -> float:
    chars = len(inp.prompt) + len(inp.context)
    return round(chars / 1_000_000 * 0.075, 8)
