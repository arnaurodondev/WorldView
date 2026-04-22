"""Valkey-backed per-source circuit breaker for RAG retrieval (T-D-1-01).

State machine:
    CLOSED    (healthy)  -> OPEN after ``failure_threshold`` failures in ``failure_window_seconds``
    OPEN      (tripped)  -> HALF_OPEN after ``cool_down_seconds`` (Valkey TTL expiry)
    HALF_OPEN (probe)    -> CLOSED on success; back to OPEN on failure

Valkey keys (per source):
    rag:cb:{source}:failures  — ZSET of failure timestamps (TTL = failure_window)
    rag:cb:{source}:state     — "open" with TTL = cool_down_seconds
                                CLOSED = key absent; HALF_OPEN = implicit (key expired,
                                failures ZSET still present with count >= threshold)

All Valkey calls are best-effort: if Valkey is unavailable the breaker
stays CLOSED (fail-open) so requests are never blocked by a cache outage.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class SourceCircuitBreaker:
    """Per-source circuit breaker backed by Valkey sorted sets.

    Args:
        valkey: A :class:`~messaging.valkey.client.ValkeyClient` instance.
        source_name: Logical retrieval source name (e.g. ``"chunk"``, ``"graph"``).
        failure_threshold: Failures within the window required to trip OPEN.
        failure_window_seconds: Rolling window for counting failures.
        cool_down_seconds: How long the breaker stays OPEN before allowing a probe.
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        source_name: str,
        *,
        failure_threshold: int = 3,
        failure_window_seconds: int = 120,
        cool_down_seconds: int = 3600,
    ) -> None:
        self._valkey = valkey
        self._source = source_name
        self._threshold = failure_threshold
        self._window = failure_window_seconds
        self._cooldown = cool_down_seconds

        self._failures_key = f"rag:cb:{source_name}:failures"
        self._state_key = f"rag:cb:{source_name}:state"

    async def is_open(self) -> bool:
        """Return ``True`` if the source should be skipped.

        - ``state`` key present with value ``"open"`` -> True (skip source).
        - ``state`` key absent -> False (CLOSED or HALF_OPEN; allow probe).
        - Valkey unreachable -> False (fail-open, never block on cache outage).
        """
        try:
            state = await self._valkey.get(self._state_key)
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="is_open")
            return False
        return state == "open"

    async def record_success(self) -> None:
        """Reset failure state — transition HALF_OPEN/CLOSED -> CLOSED.

        Clears both the state key and the failures ZSET so the breaker
        starts fresh.  Best-effort — Valkey errors are swallowed.
        """
        try:
            async with self._valkey.pipeline(transaction=False) as pipe:
                pipe.delete(self._state_key)
                pipe.delete(self._failures_key)
                await pipe.execute()
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="record_success")

    async def record_failure(self) -> None:
        """Add a failure timestamp; trip to OPEN if threshold is reached.

        Best-effort — Valkey errors are swallowed.
        """
        try:
            now = time.time()
            cutoff = now - self._window

            async with self._valkey.pipeline(transaction=False) as pipe:
                pipe.zadd(self._failures_key, {str(now): now})
                pipe.zremrangebyscore(self._failures_key, 0, cutoff)
                pipe.zcard(self._failures_key)
                pipe.expire(self._failures_key, self._window)
                results = await pipe.execute()

            failure_count: int = results[2]

            if failure_count >= self._threshold:
                # Trip breaker: set "open" with TTL = cool_down.  When the
                # TTL expires the key vanishes — is_open() returns False and
                # one probe request is allowed through (implicit HALF_OPEN).
                await self._valkey.set(self._state_key, "open", ttl=self._cooldown)
                log.warning(
                    "cb_tripped_open",
                    source=self._source,
                    failure_count=failure_count,
                    cool_down_seconds=self._cooldown,
                )
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="record_failure")
