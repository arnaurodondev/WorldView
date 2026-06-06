"""Startup retry decorator for worker bootstrap calls (PLAN-0093 Wave A-3).

When a worker process starts before its dependencies (Postgres, Valkey, Kafka,
DeepInfra, Ollama, …) are fully reachable, transient lookup / connection errors
should NOT crash the container.  Instead we want to retry a small number of
times with exponential backoff, log each attempt at WARNING, and only escalate
to CRITICAL + re-raise once the budget is exhausted (so docker-compose's
restart-policy can take over from a known-bad state).

Usage::

    from common.retry import retry_on_startup

    @retry_on_startup()
    async def _bootstrap() -> None:
        await session.execute(text("SELECT 1"))

    await _bootstrap()

Audit refs: F-NPL-002, F-REF-009, F-KG-102, F-REF-006.
Regression guard: BP-403 (no dangling background tasks on exhaustion — exit
clean and re-raise so the parent restart loop is authoritative).  HR-031
(silent failure — every retry logs, exhaustion logs CRITICAL).
"""

from __future__ import annotations

import asyncio
import functools
import socket
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

# F = the async callable being wrapped.  We preserve its full signature on the
# wrapper so callers keep type-hints + IDE help (cast via TypeVar trick below).
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Default set of exception types we treat as "transient startup blip".  These
# cover the three most common DNS / TCP race conditions we have seen in
# practice when a service comes up before Postgres / Valkey / Kafka / DeepInfra:
#   - socket.gaierror      → DNS not yet resolvable (compose network race)
#   - ConnectionRefusedError → port not yet listening
#   - OSError              → asyncpg sometimes wraps gaierror as OSError;
#                            httpx + aiohttp also surface OSError on TCP RST
#   - asyncio.TimeoutError → upstream slow on first hit (cold ML model, etc.)
_DEFAULT_RETRY_ON: tuple[type[BaseException], ...] = (
    socket.gaierror,
    ConnectionRefusedError,
    OSError,
    asyncio.TimeoutError,
)


def retry_on_startup(
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 5.0,
    retry_on: tuple[type[BaseException], ...] = _DEFAULT_RETRY_ON,
) -> Callable[[F], F]:
    """Wrap an async function so transient startup errors retry with backoff.

    Args:
        max_attempts: Total attempts (including the first).  After this many
            consecutive failures we log CRITICAL and re-raise the last error.
        backoff_seconds: Initial sleep between attempts.  Doubles each retry,
            so default 5s gives 5 → 10 → 20.
        retry_on: Tuple of exception types that count as transient.  Anything
            outside this tuple propagates immediately (we don't want to swallow
            a misconfiguration as a "transient blip").

    Returns:
        A decorator that preserves the wrapped function's signature.
    """

    def decorator(func: F) -> F:
        # structlog logger named after the wrapped function so each worker's
        # retry events show up under its own logger in the JSON log stream.
        # We use structlog directly (not libs/observability's helper) because
        # libs/common must stay dependency-light — every service already
        # configures structlog at startup via observability.configure_logging.
        log = structlog.get_logger(f"common.retry.{func.__module__}.{func.__name__}")

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Track the last exception so we can re-raise after exhaustion.
            last_exc: BaseException | None = None
            current_backoff = backoff_seconds

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last_exc = exc
                    remaining = max_attempts - attempt
                    if remaining <= 0:
                        # Out of budget — escalate and let the caller exit.
                        # BP-403: we never spawned a background task, so there
                        # is nothing to clean up here; raising is sufficient.
                        log.critical(
                            "startup_retry_exhausted",
                            function=func.__qualname__,
                            attempts=attempt,
                            error=str(exc),
                            error_type=type(exc).__name__,
                        )
                        raise
                    # Still have budget — log + sleep + try again.
                    log.warning(
                        "startup_retry",
                        function=func.__qualname__,
                        attempt=attempt,
                        remaining=remaining,
                        backoff_seconds=current_backoff,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    await asyncio.sleep(current_backoff)
                    current_backoff *= 2.0
                # Note: any exception NOT in retry_on falls through this
                # try/except untouched and propagates to the caller — this is
                # intentional (HR-031: don't mask misconfiguration as transient).

            # Unreachable in practice (the loop either returns or raises).
            # Kept as defensive belt-and-braces so mypy is happy and so a
            # future refactor that changes loop control can't silently return
            # None where the caller expects a value.
            assert last_exc is not None  # pragma: no cover
            raise last_exc  # pragma: no cover

        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["retry_on_startup"]
