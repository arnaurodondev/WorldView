"""Circuit breaker port interface.

The circuit breaker coordinates failure detection across all worker replicas
via a shared Valkey store, preventing retry storms when EODHD is degraded.

State machine:
    CLOSED    → normal operation; all calls pass through.
    OPEN      → provider is degraded; all calls are blocked.
    HALF_OPEN → cooldown elapsed; one probe call is allowed through.

Transitions:
    CLOSED  + N consecutive failures → OPEN
    OPEN    + open_until timestamp passed → HALF_OPEN
    HALF_OPEN + record_success → CLOSED
    HALF_OPEN + record_failure → OPEN (reset timer)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum


class CircuitState(IntEnum):
    """Possible states of the circuit breaker."""

    CLOSED = 0  # normal operation — all calls allowed
    OPEN = 1  # provider is degraded — all calls blocked
    HALF_OPEN = 2  # cooldown elapsed — one probe call allowed


class CircuitBreakerPort(ABC):
    """Port interface for the circuit breaker.

    Implementations coordinate state across replicas via a shared backing
    store (e.g. Valkey). Each method targets a specific provider *endpoint*
    slug so multiple EODHD API paths can be tracked independently.
    """

    @abstractmethod
    async def get_state(self, endpoint: str) -> CircuitState:
        """Return the current circuit state for *endpoint*.

        If the circuit is OPEN but the cooldown period has elapsed, the
        implementation transitions to HALF_OPEN and returns that state.
        """

    @abstractmethod
    async def record_success(self, endpoint: str) -> None:
        """Record a successful request for *endpoint*.

        A success in HALF_OPEN or CLOSED state resets the failure counter
        and sets the circuit back to CLOSED.
        """

    @abstractmethod
    async def record_failure(self, endpoint: str) -> None:
        """Record a failed request for *endpoint*.

        When the consecutive failure count reaches the threshold the circuit
        transitions to OPEN. Failures in OPEN or HALF_OPEN simply reset the
        cooldown timer without incrementing the counter further.
        """

    @abstractmethod
    async def is_open(self, endpoint: str) -> bool:
        """Return True if calls to *endpoint* should be blocked.

        Semantics by state:
            CLOSED    → False  (all calls allowed)
            HALF_OPEN → False  (probe call allowed)
            OPEN      → True   (all calls blocked)
        """
