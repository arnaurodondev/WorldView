"""Valkey-backed circuit breaker adapter.

Coordinates circuit breaker state across all market-ingestion worker replicas
via a shared Valkey store. Each EODHD endpoint tracked independently via the
``endpoint`` slug parameter.

Key schema (all keys prefixed ``cb:v1:eodhd:{endpoint}:``):

    ``cb:v1:eodhd:{endpoint}:state``
        String value: ``"closed"`` | ``"open"`` | ``"half_open"``

    ``cb:v1:eodhd:{endpoint}:failures``
        Integer: consecutive failure count since last reset.

    ``cb:v1:eodhd:{endpoint}:open_until``
        Integer: Unix timestamp (epoch seconds) at which the OPEN cooldown
        expires and the circuit transitions to HALF_OPEN.

Design notes:
    - All state mutations use non-transactional Valkey commands.  In the rare
      case of concurrent replica writes the last writer wins — this is
      acceptable because the circuit breaker is a best-effort coordination
      mechanism, not a hard lock.
    - TTLs are intentionally not set on ``state``/``failures`` keys so that
      stale-CLOSED circuits do not ghost; callers must reset them explicitly
      via record_success().
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from market_ingestion.application.ports.circuit_breaker import CircuitBreakerPort, CircuitState
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Valkey state string → enum mapping
# ---------------------------------------------------------------------------

_STATE_MAP: dict[str, CircuitState] = {
    "closed": CircuitState.CLOSED,
    "open": CircuitState.OPEN,
    "half_open": CircuitState.HALF_OPEN,
}

_STATE_STR: dict[CircuitState, str] = {v: k for k, v in _STATE_MAP.items()}


class ValkeyCircuitBreaker(CircuitBreakerPort):
    """Valkey-backed implementation of the circuit breaker port.

    Args:
        valkey: Shared :class:`~messaging.valkey.client.ValkeyClient` instance.
        failure_threshold: Consecutive failures required to open the circuit.
            Defaults to 5.
        open_duration_sec: Seconds the circuit remains OPEN before
            transitioning to HALF_OPEN for a probe.  Defaults to 60.
        success_threshold: Successful probes in HALF_OPEN required to close
            the circuit.  Defaults to 1 (first success closes immediately).
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        *,
        failure_threshold: int = 5,
        open_duration_sec: int = 60,
        success_threshold: int = 1,
    ) -> None:
        self._valkey = valkey
        self._failure_threshold = failure_threshold
        self._open_duration_sec = open_duration_sec
        self._success_threshold = success_threshold

    # ------------------------------------------------------------------
    # Key helpers — centralise the key schema in one place
    # ------------------------------------------------------------------

    def _key_state(self, endpoint: str) -> str:
        """Valkey key for the circuit state string."""
        return f"cb:v1:eodhd:{endpoint}:state"

    def _key_failures(self, endpoint: str) -> str:
        """Valkey key for the consecutive failure counter."""
        return f"cb:v1:eodhd:{endpoint}:failures"

    def _key_open_until(self, endpoint: str) -> str:
        """Valkey key for the cooldown expiry unix timestamp."""
        return f"cb:v1:eodhd:{endpoint}:open_until"

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------

    async def get_state(self, endpoint: str) -> CircuitState:
        """Return the effective circuit state for *endpoint*.

        If the stored state is OPEN but the ``open_until`` timestamp has
        passed, the circuit is transparently transitioned to HALF_OPEN
        (allowing a single probe request through) before returning.
        """
        raw = await self._valkey.get(self._key_state(endpoint))

        # No key → circuit has never been opened; treat as CLOSED.
        if raw is None:
            return CircuitState.CLOSED

        state = _STATE_MAP.get(raw, CircuitState.CLOSED)

        if state == CircuitState.OPEN:
            # Check whether the cooldown window has elapsed.
            open_until_raw = await self._valkey.get(self._key_open_until(endpoint))
            if open_until_raw is not None:
                open_until = int(open_until_raw)
                if time.time() >= open_until:
                    # Cooldown elapsed — transition to HALF_OPEN so one probe
                    # request is allowed through.  Write the new state back so
                    # that other replicas see the transition immediately.
                    await self._valkey.set(self._key_state(endpoint), "half_open")
                    logger.info(
                        "circuit_breaker_half_open",
                        endpoint=endpoint,
                        open_duration_sec=self._open_duration_sec,
                    )
                    return CircuitState.HALF_OPEN

        return state

    async def record_success(self, endpoint: str) -> None:
        """Record a successful provider call for *endpoint*.

        Resets the failure counter to zero and closes the circuit regardless
        of the current state (CLOSED, HALF_OPEN, or even a stale OPEN).
        """
        await self._valkey.set(self._key_state(endpoint), "closed")
        await self._valkey.set(self._key_failures(endpoint), "0")
        await self._valkey.delete(self._key_open_until(endpoint))

        logger.debug("circuit_breaker_success_recorded", endpoint=endpoint)

    async def record_failure(self, endpoint: str) -> None:
        """Record a failed provider call for *endpoint*.

        Behaviour differs by current state:

        - **CLOSED**: increment the failure counter.  If the count reaches
          ``failure_threshold``, open the circuit and log an event.
        - **OPEN / HALF_OPEN**: re-open the circuit (reset the cooldown timer)
          without touching the failure counter — the probe failed.
        """
        state = await self.get_state(endpoint)

        if state == CircuitState.CLOSED:
            # Atomically increment the consecutive failure count.
            failures = await self._valkey.incr(self._key_failures(endpoint))
            logger.debug(
                "circuit_breaker_failure_counted",
                endpoint=endpoint,
                failures=failures,
                threshold=self._failure_threshold,
            )

            if failures >= self._failure_threshold:
                # Threshold reached — open the circuit.
                await self._open_circuit(endpoint)
        else:
            # Already OPEN or HALF_OPEN: probe failed; reset the cooldown timer
            # so the provider gets another full cooldown period.
            await self._open_circuit(endpoint)

    async def is_open(self, endpoint: str) -> bool:
        """Return True if calls to *endpoint* should be blocked.

        Only the OPEN state blocks callers.  HALF_OPEN allows a single probe
        request through (the probe result is reported via record_success /
        record_failure).  CLOSED allows all calls.
        """
        state = await self.get_state(endpoint)
        return state == CircuitState.OPEN

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_circuit(self, endpoint: str) -> None:
        """Transition the circuit to OPEN and reset the cooldown timer."""
        open_until = int(time.time()) + self._open_duration_sec
        await self._valkey.set(self._key_state(endpoint), "open")
        await self._valkey.set(self._key_open_until(endpoint), str(open_until))

        logger.warning(
            "circuit_breaker_opened",
            endpoint=endpoint,
            open_until=open_until,
            open_duration_sec=self._open_duration_sec,
            failure_threshold=self._failure_threshold,
        )
