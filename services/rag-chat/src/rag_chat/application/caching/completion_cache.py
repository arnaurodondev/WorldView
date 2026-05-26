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
    # PLAN-0093 ITER-8 FIX-LL — bumped v2 → v3 to evict ITER-7-era refusal /
    # empty-tool-call answers. With FIX-JJ (classifier timeout → fail-open) and
    # FIX-PP (news.py date_to alias) the previously-cached "I cannot find
    # evidence" / "0 edges returned" responses for Q1/Q3/Q5/Q7 are stale: those
    # queries now proceed to real tool calls. Canonical rule: bump this prefix
    # on EVERY prompt / validator / tool-schema / security-path change that
    # affects answer quality, so stale poisoned entries cannot be served.
    # History: v1 → v2 = FIX-LIVE-A (Phase 5c F-LIVE-008 numeric grounding).
    # See docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md.
    return f"rag:v3:completion:{digest}"


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
