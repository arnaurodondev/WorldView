"""Foundational primitives for downstream HTTP clients.

Hosts the building blocks shared by every composition module in this package:

- ``ServiceClients`` — dataclass holding one ``httpx.AsyncClient`` per
  downstream service (S1, S2, S3, S4, S5, S6, S7, S8, S10).
- ``DownstreamError`` — typed exception raised when a downstream returns 4xx/5xx.
- ``_checked_get`` / ``_checked_post`` — retry/error-translation helpers that
  every composition function uses for individual downstream calls.

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly: same status codes retried, same backoff delays,
same exception shape.

Why retry lives here (not in ``libs/common``):
    Other services (S1-S10) use Kafka/outbox-based retry mechanics; only
    api-gateway issues *outgoing HTTP retries* against sibling services.
    Extracting to ``libs/common/retry.py`` would benefit no other service
    today, so the helpers stay co-located with their only caller (audit
    decision recorded in TASK-W4-06 notes).
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    import httpx

# Module-level logger — structlog only (CLAUDE.md Rule 10).
# T-A-1-03: replaces silent `except Exception: pass` patterns with WARNING logs.
logger = structlog.get_logger()  # type: ignore[no-any-return]

# T-A-2-01: Retry configuration for transient downstream failures.
# Only HTTP 500 (Internal Server Error) and 503 (Service Unavailable) are
# retried — these indicate the downstream is temporarily unhealthy. 4xx errors
# are deterministic (bad input, auth, not-found) and must NOT be retried.
# 502 (Bad Gateway) is excluded because it usually means a dead container, and
# retrying immediately would just hit the same dead upstream.
_RETRY_STATUSES = frozenset({500, 503})

# Exponential-ish backoff delays (in seconds) between retry attempts.
# Three retries: 100 ms → 500 ms → 1.5 s.  Chosen to be within a 5-second
# httpx read-timeout budget (2 x 2 x 1.5 = 6s worst-case; acceptable given
# overall asyncio.wait_for budgets on composition endpoints are 15-20s).
_RETRY_DELAYS = (0.1, 0.5, 1.5)


class DownstreamError(Exception):
    """Raised when a downstream service returns an error."""

    def __init__(self, service: str, status: int, detail: str) -> None:
        self.service = service
        self.status = status
        self.detail = detail
        super().__init__(f"{service} returned {status}: {detail}")


@dataclass(frozen=True)
class ServiceClients:
    """Container for all downstream service HTTP clients."""

    portfolio: httpx.AsyncClient
    market_data: httpx.AsyncClient
    market_ingestion: httpx.AsyncClient
    content_ingestion: httpx.AsyncClient
    content_store: httpx.AsyncClient
    nlp_pipeline: httpx.AsyncClient
    knowledge_graph: httpx.AsyncClient
    rag_chat: httpx.AsyncClient
    alert: httpx.AsyncClient


async def _checked_get(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """GET with error translation and automatic retry on transient failures.

    ``headers`` are merged into the request so callers can forward
    ``X-Internal-JWT`` or other auth headers to downstream services.

    T-A-2-01: retries on HTTP 500/503 up to 3 times with exponential backoff
    [0.1, 0.5, 1.5]s. 4xx errors are deterministic (bad input, auth, not-found)
    and raise immediately without retrying. A WARNING is logged per retry so
    transient failures are visible in observability dashboards without alarming
    on-call for a single blip.
    """
    last_exc: DownstreamError | None = None
    # itertools.chain([0.0], _RETRY_DELAYS) gives [0.0, 0.1, 0.5, 1.5] —
    # the first element (0.0) represents the initial attempt (no sleep before it).
    for attempt, delay in enumerate(itertools.chain([0.0], _RETRY_DELAYS)):
        if delay:
            # Sleep between retry attempts. We await here (not time.sleep) because
            # this is an async function — blocking sleep would stall the event loop.
            await asyncio.sleep(delay)
        resp = await client.get(path, headers=headers, **kwargs)
        if resp.status_code < 400:
            # Success — return immediately (no retry needed).
            return cast("dict[str, Any]", resp.json())
        # F-005: truncate error detail to avoid leaking internal service details to frontend
        exc = DownstreamError(service_name, resp.status_code, resp.text[:200])
        # Only retry on transient server errors; raise immediately for all others.
        # attempt >= len(_RETRY_DELAYS) means we've exhausted all retries.
        if resp.status_code not in _RETRY_STATUSES or attempt >= len(_RETRY_DELAYS):
            raise exc
        last_exc = exc
        logger.warning(
            "downstream_retry",
            service=service_name,
            path=path,
            status=resp.status_code,
            attempt=attempt + 1,
        )
    # Unreachable: the loop always raises before completing all iterations, but
    # mypy needs a concrete raise here since last_exc is Optional.
    raise last_exc  # type: ignore[misc]


async def _checked_post(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    allow_retry: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST with error translation.

    ``headers`` are merged into the request so callers can forward
    ``X-Internal-JWT`` or other auth headers to downstream services.

    # WHY allow_retry=False: POST requests may not be idempotent (create-on-retry
    # → duplicate records). Only retry if the caller guarantees idempotency.
    # See CLAUDE.md BP-025 (idempotency rule) — never retry mutations without
    # explicit opt-in. GET is always safe to retry; POST is not by default.

    T-A-2-01: when ``allow_retry=True`` the same [0.1, 0.5, 1.5]s backoff
    strategy as ``_checked_get`` is applied. Only use this for POST endpoints
    that are idempotent (e.g. upsert-style operations with a caller-supplied key).
    """
    if not allow_retry:
        # Fast path: single attempt, no retry (default behaviour, always safe).
        resp = await client.post(path, headers=headers, **kwargs)
        if resp.status_code >= 400:
            # F-005: truncate error detail to avoid leaking internal service details to frontend
            raise DownstreamError(service_name, resp.status_code, resp.text[:200])
        return cast("dict[str, Any]", resp.json())

    # Retry path — only reached when the caller opts in (allow_retry=True).
    last_exc: DownstreamError | None = None
    for attempt, delay in enumerate(itertools.chain([0.0], _RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        resp = await client.post(path, headers=headers, **kwargs)
        if resp.status_code < 400:
            return cast("dict[str, Any]", resp.json())
        exc = DownstreamError(service_name, resp.status_code, resp.text[:200])
        if resp.status_code not in _RETRY_STATUSES or attempt >= len(_RETRY_DELAYS):
            raise exc
        last_exc = exc
        logger.warning(
            "downstream_retry",
            service=service_name,
            path=path,
            status=resp.status_code,
            attempt=attempt + 1,
        )
    raise last_exc  # type: ignore[misc]


__all__ = [
    "DownstreamError",
    "ServiceClients",
    "_RETRY_DELAYS",
    "_RETRY_STATUSES",
    "_checked_get",
    "_checked_post",
    "logger",
]
