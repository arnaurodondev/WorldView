"""ActiveUsersReader — Valkey ``ZRANGEBYSCORE`` adapter (PLAN-0094 W2, T-W2-02).

Reads the ``active_users`` sorted-set populated by S9's ``OIDCAuthMiddleware``
(W1).  Each member is a user_id (UUID string) with a Unix-timestamp score that
records the last successful authentication.  The worker queries
``ZRANGEBYSCORE active_users <now - window_days*86400> +inf`` to fetch user_ids
active within the configured window.

WHY a thin adapter:
    The Valkey call is one line — but the worker layer must not contain
    infrastructure-specific code (R25).  Wrapping the call in this adapter
    behind :class:`IActiveUsersPort` keeps the worker testable with in-memory
    fakes and confines the byte-decode / UUID-parse error-handling here.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from rag_chat.application.ports.active_users import IActiveUsersPort

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ────────────────────────────────────────────────────────────────
# Mirror api-gateway's constant (see services/api-gateway/src/api_gateway/middleware.py).
# Keeping this string here (rather than importing from api-gateway) preserves
# service-boundary isolation — rag-chat must not depend on api-gateway code.
_ACTIVE_USERS_KEY = "active_users"


class ActiveUsersReader(IActiveUsersPort):
    """Read users active in the last ``window_days`` days from Valkey.

    Construction args:
        valkey_client: A duck-typed Valkey client that exposes
            ``async def zrangebyscore(key, min, max) -> list[bytes | str]``.
            In production this is :class:`messaging.valkey.client.ValkeyClient`
            (which delegates to ``redis.asyncio.Redis``); in tests it's a
            plain ``AsyncMock``.
        window_days: How far back to look.  The constructor stores this as-is —
            the actual ``min_score`` is computed on each call so a long-running
            scheduler does not drift relative to the wall-clock cutoff.

    The reader is stateless beyond the constructor args, so it is safe to
    share across coroutines.
    """

    def __init__(self, valkey_client: Any, window_days: int) -> None:
        # WHY ``Any``: the worker layer accepts either ValkeyClient (production)
        # or a mock (tests).  Static typing is enforced at the port boundary
        # (:class:`IActiveUsersPort`) rather than on this attribute.
        self._valkey = valkey_client
        self._window_days = window_days

    async def list_active(self) -> list[UUID]:
        """Return user_ids that have authenticated within ``window_days``.

        Calls ``ZRANGEBYSCORE active_users <now - window*86400> +inf``.

        Resilience:
            * Malformed members (non-UUID) are logged at WARNING and skipped —
              one bad row never breaks the batch.  This protects against an
              upstream bug in S9 that might write a malformed user_id.
            * An empty set returns an empty list cleanly (no exception).
        """
        now = int(time.time())
        min_score = now - self._window_days * 86400

        # ``zrangebyscore`` returns ``list[bytes | str]`` depending on whether
        # ``decode_responses=True`` was set on the Redis client.  We handle both.
        raw_members: list[Any] = await self._valkey.zrangebyscore(
            _ACTIVE_USERS_KEY,
            min_score,
            "+inf",
        )

        users: list[UUID] = []
        for raw in raw_members:
            # Normalise bytes → str.  Mock returns strings; real redis-py returns
            # bytes unless ``decode_responses=True``.
            member = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            try:
                users.append(UUID(member))
            except (ValueError, AttributeError):
                # BP-549-style defensive logging: surface the bad row so we can
                # find and fix its source, but DO NOT raise — the rest of the
                # pre-generation run must continue.
                _log.warning(  # type: ignore[no-any-return]
                    "active_users_malformed_member_skipped",
                    member=member[:64],  # cap length for log hygiene
                    window_days=self._window_days,
                )

        return users


__all__ = ["ActiveUsersReader"]
