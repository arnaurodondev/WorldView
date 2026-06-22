"""ChainedDescriptionAdapter — try multiple EntityDescriptionClients in order.

Implements the provider-chain pattern for entity description generation:
  1. Primary   : DeepInfraDescriptionAdapter (Qwen3 via DeepInfra GPU)
  2. Fallback 1: GeminiDescriptionAdapter    (gemini-3.1-flash-lite)
  3. Fallback 2: None → caller's _fallback_description() stub

Each adapter in the chain is called in sequence.  The first non-None result
is returned immediately; subsequent adapters are skipped.  If all adapters
return None (e.g. all cost caps exceeded or all APIs unavailable), None is
returned and the caller (DefinitionRefreshWorker._resolve_non_company_text)
falls back to the deterministic ``"{name} is a {entity_type}."`` template.

Chain-level timeout guard (BP-RC8):
    If an individual adapter hangs longer than ``per_adapter_timeout_s``
    (default: 65 s — slightly above DeepInfraDescriptionAdapter's own 60 s
    client timeout), ``asyncio.wait_for`` raises ``asyncio.TimeoutError``.
    The chained adapter catches this, logs a warning, and moves on to the
    next provider so a single hung provider cannot block the entire chain.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ml_clients.description_client import EntityDescriptionClient

logger = structlog.get_logger()

# Default per-adapter timeout — 5 s above DeepInfra's own 60 s client timeout
# so the chain still advances if the httpx pool itself hangs (e.g. DNS failure
# that does not raise immediately).
_DEFAULT_TIMEOUT_S = 65.0


class ChainedDescriptionAdapter:
    """Calls a sequence of EntityDescriptionClients and returns the first success.

    Args:
    ----
        adapters:              Ordered list of ``EntityDescriptionClient`` instances.
                               Tried left-to-right; first non-None result wins.
        per_adapter_timeout_s: Per-adapter wall-clock timeout in seconds (default: 65).
                               Prevents one hung provider from blocking the chain.

    Usage (scheduler.py):
    ----------------------
        chained = ChainedDescriptionAdapter([
            DeepInfraDescriptionAdapter(...),  # primary
            GeminiDescriptionAdapter(...),     # fallback
        ])

    The adapter exposes ``aclose()`` so that
    ``KnowledgeGraphScheduler.stop()`` can close all underlying HTTP clients
    via its ``_aux_aclose`` registry (F-X15).

    """

    def __init__(
        self,
        adapters: list[EntityDescriptionClient],
        per_adapter_timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._adapters = adapters
        self._timeout = per_adapter_timeout_s

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
        news_context: list[str] | None = None,
    ) -> str | None:
        """Try each adapter in order; return first non-None result or None.

        A per-adapter ``asyncio.wait_for`` guard prevents one provider from
        blocking the chain beyond ``per_adapter_timeout_s`` seconds.

        ``news_context`` (optional) is forwarded verbatim to every wrapped
        adapter so the news-grounding block / no-news guard reaches whichever
        provider ultimately serves the request.
        """
        for idx, adapter in enumerate(self._adapters):
            adapter_name = type(adapter).__name__
            try:
                result = await asyncio.wait_for(
                    adapter.generate_description(
                        entity_id=entity_id,
                        canonical_name=canonical_name,
                        entity_type=entity_type,
                        context_hints=context_hints,
                        news_context=news_context,
                    ),
                    timeout=self._timeout,
                )
            except TimeoutError:
                logger.warning(
                    "chained_description_adapter_timeout",
                    adapter=adapter_name,
                    position=idx,
                    timeout_s=self._timeout,
                    entity_id=entity_id,
                )
                continue
            except Exception as exc:
                logger.warning(
                    "chained_description_adapter_error",
                    adapter=adapter_name,
                    position=idx,
                    entity_id=entity_id,
                    error=str(exc),
                )
                continue

            if result is not None:
                logger.debug(
                    "chained_description_adapter_success",
                    adapter=adapter_name,
                    position=idx,
                    entity_id=entity_id,
                )
                return result

            # Adapter returned None (cost cap exceeded, API unavailable, etc.)
            logger.debug(
                "chained_description_adapter_returned_none",
                adapter=adapter_name,
                position=idx,
                entity_id=entity_id,
            )

        # All adapters exhausted — caller applies the deterministic fallback stub.
        logger.info(
            "chained_description_all_adapters_exhausted",
            entity_id=entity_id,
            adapter_count=len(self._adapters),
        )
        return None

    async def aclose(self) -> None:
        """Close all adapters that expose ``aclose()`` (F-X15 resource cleanup)."""
        for adapter in self._adapters:
            if hasattr(adapter, "aclose"):
                try:
                    await adapter.aclose()
                except Exception as exc:
                    logger.warning(
                        "chained_description_aclose_failed",
                        adapter=type(adapter).__name__,
                        error=str(exc),
                    )
