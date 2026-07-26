"""Valkey-backed EntailmentCachePort adapter.

Wraps ``messaging.valkey.client.ValkeyClient.get_json``/``set_json`` (the same
helper ``rag_chat``'s ``ValkeyChunkCacheAdapter`` and ``CompletionCache`` use)
behind the tiny ``EntailmentCachePort`` protocol. All operations are
best-effort: a Valkey outage logs a warning and returns/no-ops rather than
propagating, matching the fail-open philosophy of the entailment blocks this
cache serves (``application/blocks/claim_entailment.py`` and
``relation_entailment.py``) — a cache blip must only cost an extra LLM call,
never break extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_VALKEY_UNAVAILABLE_MSG = "entailment_cache.valkey_unavailable"


class ValkeyEntailmentCacheAdapter:
    """Redis/Valkey JSON-backed cache for entailment verifier verdicts."""

    def __init__(self, client: ValkeyClient) -> None:
        self._client = client

    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached verdict dict, or ``None`` on a miss or Valkey error."""
        try:
            value = await self._client.get_json(key)
        except Exception as exc:
            logger.warning(_VALKEY_UNAVAILABLE_MSG, operation="get_json", error=str(exc))
            return None
        return value if isinstance(value, dict) else None

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """Persist *value* under *key* for *ttl* seconds. Best-effort (never raises)."""
        try:
            await self._client.set_json(key, value, ttl=ttl)
        except Exception as exc:
            logger.warning(_VALKEY_UNAVAILABLE_MSG, operation="set_json", error=str(exc))
