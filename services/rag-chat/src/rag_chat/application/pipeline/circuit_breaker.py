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

PLAN-0076 Wave B-2 / DEF-031 (BP-403): the ZADD → ZREMRANGEBYSCORE → ZCARD
sequence used by ``record_failure()`` is now executed inside a single Lua
script (atomic + isolated on the Redis server). The previous pipeline-with-
``transaction=False`` implementation was non-atomic — two concurrent failures
could both observe count below the threshold and one trip would be missed
even though both writers committed their ZADD.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog

from rag_chat.application.metrics.prometheus import rag_circuit_breaker_open

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Atomic record-failure: single Lua script eliminates TOCTOU race ──────────
# KEYS[1] = failures ZSET key
# ARGV[1] = now (unix seconds, used as ZADD score)
# ARGV[2] = window cutoff (oldest score to keep)
# ARGV[3] = window TTL seconds (refreshed on every failure)
# ARGV[4] = unique suffix — prevents sub-second failures from coalescing.
#           ZADD members must be unique within a ZSET; if two failures arrive
#           within the same clock tick (same float from time.time()), the second
#           ZADD overwrites the first entry instead of adding a new one.
#           Appending a random hex suffix makes every member unique while keeping
#           the score as the real timestamp for ZRANGEBYSCORE TTL pruning. (BP-426)
_RECORD_FAILURE_LUA = """
local key = KEYS[1]
local now = ARGV[1]
local cutoff = ARGV[2]
local ttl = tonumber(ARGV[3])
local member = now .. ":" .. ARGV[4]
redis.call('ZADD', key, now, member)
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ttl)
return count
"""


class SourceCircuitBreaker:
    """Per-source circuit breaker backed by Valkey sorted sets.

    Args:
        valkey: A :class:`~messaging.valkey.client.ValkeyClient` instance.
        source_name: Logical retrieval source name (e.g. ``"chunk"``, ``"graph"``).
        failure_threshold: Failures within the window required to trip OPEN.
        failure_window_seconds: Rolling window for counting failures.
        cool_down_seconds: How long the breaker stays OPEN before allowing a probe.
            PLAN-0084 A-2: default lowered from 3600 → 120s (F-X04 fix).
        probe_ttl_seconds: TTL for the SETNX probe key that prevents stampede
            on cooldown expiry (F-X01 fix).  Only one caller wins the probe slot;
            others see the breaker still OPEN until the probe TTL expires.
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        source_name: str,
        *,
        failure_threshold: int = 3,
        failure_window_seconds: int = 120,
        cool_down_seconds: int = 120,
        probe_ttl_seconds: int = 5,
    ) -> None:
        self._valkey = valkey
        self._source = source_name
        self._threshold = failure_threshold
        self._window = failure_window_seconds
        self._cooldown = cool_down_seconds
        self._probe_ttl = probe_ttl_seconds

        self._failures_key = f"rag:cb:{source_name}:failures"
        self._state_key = f"rag:cb:{source_name}:state"
        # F-X01 probe key: exactly one caller wins SETNX after cooldown expiry.
        self._probe_key = f"rag:cb:{source_name}:probe"

    async def is_open(self) -> bool:
        """Return ``True`` if the source should be skipped.

        State machine:
        - ``state`` key present ("open") → True; breaker is tripped.
        - ``state`` key absent AND probe SETNX wins → False; this caller is
          the probe.  Others that lose the SETNX still see True until the
          probe TTL expires, preventing stampede on cooldown expiry (F-X01).
        - Valkey unreachable → False (fail-open; never block on cache outage).
        """
        try:
            state = await self._valkey.get(self._state_key)
            if state == "open":
                return True
            # Cooldown expired (state key absent) — attempt to claim probe slot
            # via SETNX.  Only one concurrent caller wins; the rest return True
            # (backed off) until the probe TTL expires naturally.
            won = await self._valkey.set_nx(self._probe_key, "1", ex=self._probe_ttl)
            if won:
                log.info("circuit_breaker_probe_admitted", source=self._source)  # type: ignore[no-any-return]
                return False
            return True
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="is_open")
            return False

    async def reconcile_gauge(self) -> None:
        """Sync the Prometheus gauge with the actual Valkey CB state on startup.

        D-006: On service restart the Prometheus gauge is re-initialised to 0
        (healthy) even if the CB was ``open`` in Valkey before restart.  The
        state key persists across restarts (TTL = cool_down_seconds), so the
        gauge shows a false-healthy state until the first ``record_failure`` or
        ``record_success`` call.  Calling this method once during the lifespan
        startup corrects the gauge immediately.

        Best-effort — errors are swallowed and logged at WARNING.
        """
        try:
            state = await self._valkey.get(self._state_key)
            rag_circuit_breaker_open.labels(source=self._source).set(1 if state == "open" else 0)
            log.debug("cb_gauge_reconciled", source=self._source, state=state or "closed")  # type: ignore[no-any-return]
        except Exception:
            log.warning("cb_gauge_reconcile_failed", source=self._source)  # type: ignore[no-any-return]

    async def record_success(self) -> None:
        """Reset failure state — transition HALF_OPEN/CLOSED -> CLOSED.

        F-X05 fix (Option A): Only the state key and probe key are deleted.
        The failures ZSET is NOT deleted — it expires naturally via its TTL
        (set equal to the failure_window_seconds on each ``record_failure`` call).
        Deleting the ZSET here would race with a concurrent failure writer
        that already did ZADD but hasn't called ZCARD yet, causing the failure
        count to start from scratch instead of the correct value.

        # NOTE: The failures ZSET is intentionally NOT deleted on success. It expires
        # naturally via its TTL (failure_window_seconds). Old failures in the window can
        # cause the breaker to re-open quickly after recovery if new failures occur within
        # the same window. This is intentional — it avoids a concurrent-write race and
        # provides a "cooling off" period after recovery.

        Best-effort — Valkey errors are swallowed.
        """
        try:
            # D-004 fix: delete both keys atomically via a Lua script so a
            # mid-call crash cannot leave the probe key alive and cause a
            # false-positive circuit-open for up to probe_ttl_seconds.
            # ValkeyClient.delete() only accepts a single key; Lua gives us
            # a single atomic server-side DEL of both keys in one round-trip.
            await self._valkey.execute_lua_script(
                "redis.call('DEL', KEYS[1], KEYS[2]); return 1",
                keys=[self._state_key, self._probe_key],
                args=[],
            )
            rag_circuit_breaker_open.labels(source=self._source).set(0)
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="record_success")

    async def record_failure(self, error: Exception | None = None) -> None:
        """Add a failure timestamp; trip to OPEN if threshold is reached.

        S-003: 4xx client errors (``ProviderClientError`` with ``status_code < 500``)
        do NOT count toward the failure threshold.  A bad prompt or quota error is a
        caller fault, not an indication that the upstream service is unhealthy.
        Only 5xx / network failures should trip the circuit breaker.

        The ZADD → ZREMRANGEBYSCORE → ZCARD → EXPIRE sequence runs inside a
        single Lua script (BP-403) so two concurrent failures cannot both
        observe count below the threshold. Best-effort — Valkey errors are
        swallowed (fail-open).
        """
        # Lazy import to avoid circular dependency: domain.errors ← application.pipeline
        from rag_chat.domain.errors import ProviderClientError

        if isinstance(error, ProviderClientError) and error.status_code < 500:
            log.debug(
                "cb_skip_4xx_client_error",
                source=self._source,
                status_code=error.status_code,
            )
            return

        try:
            now = time.time()
            cutoff = now - self._window

            count_result = await self._valkey.execute_lua_script(
                _RECORD_FAILURE_LUA,
                keys=[self._failures_key],
                args=[str(now), str(cutoff), str(self._window), uuid.uuid4().hex[:8]],
            )
            failure_count = int(count_result)

            if failure_count >= self._threshold:
                # Trip breaker: set "open" with TTL = cool_down.  When the
                # TTL expires the key vanishes — is_open() returns False and
                # one probe request is allowed through (implicit HALF_OPEN).
                await self._valkey.set(self._state_key, "open", ttl=self._cooldown)
                # PLAN-0084 A-2 T-A-2-04: expose breaker state as a Prometheus gauge.
                rag_circuit_breaker_open.labels(source=self._source).set(1)
                log.warning(
                    "cb_tripped_open",
                    source=self._source,
                    failure_count=failure_count,
                    cool_down_seconds=self._cooldown,
                )
        except Exception:
            log.warning("cb_valkey_unavailable", source=self._source, op="record_failure")
