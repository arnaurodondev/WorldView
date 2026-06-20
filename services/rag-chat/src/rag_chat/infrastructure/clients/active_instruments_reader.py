"""ActiveInstrumentsReader — Valkey ``ZRANGEBYSCORE`` adapter (AI-brief-flag fix, 2026-06-19).

Reads the ``active_instruments`` sorted-set populated by the on-demand
instrument-brief route (``GET /api/v1/briefings/instrument/{entity_id}``). Each
member is an entity_id (the route param) with a Unix-timestamp score recording
the last time a brief was requested for it. The worker queries
``ZRANGEBYSCORE active_instruments <now - window_days*86400> +inf`` to fetch the
entity_ids viewed within the configured window.

WHY a thin adapter:
    The Valkey call is one line, but the worker layer must not contain
    infrastructure-specific code (R25). Wrapping the call behind
    :class:`IActiveInstrumentsPort` keeps the worker testable with in-memory
    fakes and confines the byte-decode error handling here. Mirrors
    :class:`ActiveUsersReader` (the morning-brief equivalent) one-to-one.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from rag_chat.application.ports.active_instruments import IActiveInstrumentsPort

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# The Valkey sorted-set key the instrument-brief route writes to. Kept as a
# module constant so the route writer and this reader cannot drift.
ACTIVE_INSTRUMENTS_KEY = "active_instruments"


class ActiveInstrumentsReader(IActiveInstrumentsPort):
    """Read instruments viewed in the last ``window_days`` days from Valkey.

    Construction args:
        valkey_client: a duck-typed Valkey client exposing
            ``async def zrangebyscore(key, min, max) -> list[bytes | str]``.
            In production this is :class:`messaging.valkey.client.ValkeyClient`;
            in tests it is a plain ``AsyncMock``.
        window_days: how far back to look. Stored as-is — the ``min_score`` is
            recomputed on each call so a long-running scheduler does not drift
            relative to the wall-clock cutoff.
    """

    def __init__(self, valkey_client: Any, window_days: int) -> None:
        self._valkey = valkey_client
        self._window_days = window_days

    async def list_active(self) -> list[str]:
        """Return entity_ids whose brief was requested within ``window_days``.

        Resilience: an empty set returns an empty list cleanly; a Valkey error
        is logged and degrades to an empty list (the pre-gen pass simply does no
        work this interval rather than crashing the scheduler).
        """
        now = int(time.time())
        min_score = now - self._window_days * 86400

        try:
            raw_members: list[Any] = await self._valkey.zrangebyscore(
                ACTIVE_INSTRUMENTS_KEY,
                min_score,
                "+inf",
            )
        except Exception as exc:
            _log.warning(  # type: ignore[no-any-return]
                "active_instruments_read_failed",
                error=str(exc),
                window_days=self._window_days,
            )
            return []

        instruments: list[str] = []
        for raw in raw_members:
            member = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            if member:
                instruments.append(member)
        return instruments


__all__ = ["ActiveInstrumentsReader", "ACTIVE_INSTRUMENTS_KEY"]
