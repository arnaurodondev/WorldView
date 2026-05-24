"""LLM completion cache backed by Valkey (T-E-1-02).

Caches full completion responses keyed by a SHA-256 hash of the sanitised
message and thread_id. TTL is 24 hours.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

_TTL_SECONDS = 86_400  # 24 hours


def _cache_key(message: str, thread_id: UUID | None) -> str:
    raw = f"{message}:{thread_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    # PLAN-0093 Phase 5c F-LIVE-008 — bumped v1 → v2 to evict pre-fix poisoned
    # entries. INV-LIVE-C found Q4 v1 returning a fabricated "$34.6B" answer
    # because a pre-FIX-2 poisoned response (set at TTL 24h) was still being
    # served from cache; the new tool-use prompt + numeric-grounding validator
    # never executed. Canonical rule: bump this prefix on EVERY prompt /
    # validator / tool-schema change that affects answer quality, so stale
    # poisoned entries cannot ever be returned. See
    # docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md.
    return f"rag:v2:completion:{digest}"


class CompletionCache:
    """Cache LLM completion responses to avoid redundant inference.

    Args:
        valkey: A :class:`~messaging.valkey.client.ValkeyClient` instance.
    """

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    async def get(self, message: str, thread_id: UUID | None) -> dict | None:  # type: ignore[type-arg]
        """Return the cached response dict or *None* on a cache miss."""
        key = _cache_key(message, thread_id)
        data: str | None = await self._valkey.get(key)
        if data is None:
            return None
        return json.loads(data)  # type: ignore[no-any-return]

    async def set(self, message: str, thread_id: UUID | None, response: dict) -> None:  # type: ignore[type-arg]
        """Store *response* under *message* + *thread_id* for 24 hours."""
        key = _cache_key(message, thread_id)
        await self._valkey.set(key, json.dumps(response), ttl=_TTL_SECONDS)
