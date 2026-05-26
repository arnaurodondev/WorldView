"""IActiveUsersPort — application-layer interface for the "recently active users" lookup.

PLAN-0094 W2 (T-W2-02).

WHY an ABC (not Protocol):
    The plan explicitly mandates an ABC port for this port (§ Wave W2 architecture
    compliance R25).  The convention in rag-chat is mixed (some ports use
    typing.Protocol — e.g. ``brief_archive.py``), but for this port we follow the
    plan exactly.  The contract is a single async method, so the boilerplate of an
    ABC is negligible.

WHY a port at all:
    The :class:`~rag_chat.application.workers.morning_brief_pregeneration_worker.MorningBriefPregenerationWorker`
    needs the list of "users active in the last K days" to decide whose morning
    brief to pre-generate.  In production this is backed by a Valkey sorted-set
    (``active_users``) populated by S9's ``OIDCAuthMiddleware`` (W1).  In tests
    we substitute a deterministic in-memory implementation.  The port keeps the
    worker free of any Valkey-specific code (R25 — dependency rule).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


class IActiveUsersPort(ABC):
    """Abstract port for "list users seen in the last K days".

    Concrete implementations:
      * :class:`~rag_chat.infrastructure.clients.active_users_reader.ActiveUsersReader`
        — reads the Valkey ``active_users`` sorted-set populated by S9 (W1).
      * In-memory fakes for unit tests — return a fixed user list.

    The port is read-only: it never mutates the underlying source.  Writes to
    ``active_users`` happen in S9 (api-gateway middleware), not here.
    """

    @abstractmethod
    async def list_active(self) -> list[UUID]:
        """Return the user_ids that have authenticated in the configured window.

        Returns:
            A list of :class:`uuid.UUID`.  Order is unspecified — callers must
            not rely on it.  On an empty source the list is empty (never ``None``).

        Implementations MUST be resilient to malformed entries (e.g. a member
        that is not a valid UUID).  They should log a warning and skip the bad
        entry rather than raising — one bad row must not break the whole
        pre-generation pass.
        """
        ...


__all__ = ["IActiveUsersPort"]
