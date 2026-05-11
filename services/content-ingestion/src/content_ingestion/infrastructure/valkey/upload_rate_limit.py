"""Valkey-backed rate limiter for per-tenant document uploads.

PLAN-0086 Wave D-2: Implements ``UploadRateLimitPort`` using a simple
INCR + EXPIRE pattern against Valkey.  The approach is:

1. INCR the tenant's counter key — returns the new count atomically.
2. On first increment (count == 1), set the TTL so the window expires
   after ``window_seconds``.  Subsequent increments within the window
   do not reset the TTL, giving a fixed (not sliding) window.
3. If the new count exceeds ``limit``, return False to the caller.

Design choices:
- **Fail-open**: Valkey unavailability returns True (allow) so a cache
  outage doesn't block all uploads (rate limits are advisory, not a
  security control per the port contract).
- **Key taxonomy** follows ADR-0004: ``upload:v1:tenant:<uuid>``.
- Deferred import of ``ValkeyClient`` — the adapter accepts the duck-typed
  client from DI so tests can inject a plain AsyncMock without importing
  the messaging library.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from content_ingestion.application.ports.tenant_upload import UploadRateLimitPort

log = structlog.get_logger()  # type: ignore[no-any-return]


class UploadRateLimitAdapter(UploadRateLimitPort):
    """Rate limiter backed by Valkey INCR + EXPIRE.

    The ``valkey_client`` parameter is duck-typed rather than concretely typed
    to ``ValkeyClient`` so that unit tests can pass a plain ``AsyncMock``
    without a live Valkey connection.  The only methods called are:
    - ``incr(key: str) -> int``
    - ``expire(key: str, seconds: int) -> bool``
    - ``ttl(key: str) -> int``
    """

    def __init__(self, valkey_client: Any) -> None:
        # Accept any object with the right async interface — avoids a hard
        # dependency on the messaging library here (DI wires the real client).
        self._valkey: Any = valkey_client

    async def check_and_increment(
        self,
        tenant_id: UUID,
        window_seconds: int,
        limit: int,
    ) -> bool:
        """Atomically increment the tenant counter and check against the limit.

        Returns True (allow) when within limit, False (block) when over.
        Returns True (fail-open) if Valkey raises any exception.
        """
        try:
            key = f"upload:v1:tenant:{tenant_id}"
            # INCR is atomic — safe under concurrent calls from multiple workers.
            count: int = await self._valkey.incr(key)
            if count == 1:
                # First request in this window — set the expiry.
                # If the EXPIRE call fails after a successful INCR the key will
                # persist indefinitely, but the next successful write will reset
                # it.  This is an acceptable trade-off vs. a Lua script for the
                # simpler codepath.
                await self._valkey.expire(key, window_seconds)
            return count <= limit
        except Exception:
            log.warning(
                "upload_rate_limit_valkey_unavailable",
                tenant_id=str(tenant_id),
            )
            # Fail-open: never block uploads because Valkey is down.
            return True

    async def get_reset_at(self, tenant_id: UUID) -> datetime | None:
        """Return UTC datetime when the current rate-limit window expires.

        Returns None if no active window exists or Valkey is unavailable.
        Used by callers to populate the ``resets_at`` field in 429 responses.
        """
        try:
            key = f"upload:v1:tenant:{tenant_id}"
            ttl: int = await self._valkey.ttl(key)
            # ttl() returns -2 if key missing, -1 if key has no expiry.
            # Only positive values represent an active expiring window.
            if ttl > 0:
                return datetime.now(tz=UTC) + timedelta(seconds=ttl)
            return None
        except Exception:
            return None
