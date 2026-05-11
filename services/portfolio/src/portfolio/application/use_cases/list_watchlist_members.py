"""List watchlist members — paginated, owner-scoped (PLAN-0046 / T-46-2-02).

A read-only use case dedicated to ``GET /v1/watchlists/{id}/members``.
Lives in its own module rather than ``watchlist.py`` so the read path stays
clearly separated from the mutation use cases (the latter all carry outbox
write side-effects, this one does not).

Authorisation: the caller's ``owner_id`` must match the watchlist's
``user_id`` (same rule as ``GetWatchlistUseCase``). A mismatch raises
``WatchlistNotFoundError`` so the API responds with 404 — we don't leak the
existence of someone else's watchlist via 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.errors import (
    AuthorizationError,
    WatchlistNotFoundError,
)

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities.watchlist_member import WatchlistMember

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class ListWatchlistMembersQuery:
    """Query parameters for paginated member listing."""

    watchlist_id: UUID
    owner_id: UUID
    tenant_id: UUID
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class ListWatchlistMembersResult:
    """Page of members with the total row count for the watchlist."""

    members: list[WatchlistMember]
    total: int


class ListWatchlistMembersUseCase:
    """Return a page of members belonging to a watchlist owned by ``owner_id``."""

    async def execute(
        self,
        query: ListWatchlistMembersQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> ListWatchlistMembersResult:
        # ── Step 1: load the watchlist scoped to the caller's tenant ──
        # WHY tenant-scoped: ``WatchlistRepository.get`` already filters by
        # ``tenant_id``; this is the multi-tenancy guarantee R8 requires.
        watchlist = await uow.watchlists.get(query.watchlist_id, query.tenant_id)
        if watchlist is None:
            # Convert "no row in this tenant" to a 404 at the API layer.
            raise WatchlistNotFoundError(f"Watchlist {query.watchlist_id} not found")

        # ── Step 2: enforce ownership ──
        # WHY raise the same error class as not-found: matches existing
        # behaviour of ``_fetch_watchlist_for_owner`` in ``watchlist.py``,
        # except we can't reuse that helper directly because it raises
        # ``AuthorizationError`` (which the API layer maps to 403). For this
        # endpoint the spec requires a 404 to avoid leaking ownership
        # information across users; the API maps ``WatchlistNotFoundError``
        # → 404. Concretely: if a user requests another user's watchlist
        # they should not learn it exists.
        if watchlist.user_id != query.owner_id:
            # Defensive log line — useful for tracing forged requests.
            logger.info(
                "watchlist_members_authz_denied",
                watchlist_id=str(query.watchlist_id),
                requested_by=str(query.owner_id),
            )
            raise WatchlistNotFoundError(f"Watchlist {query.watchlist_id} not found")

        # ── Step 3: paginated fetch ──
        members, total = await uow.watchlist_members.list_by_watchlist_paginated(
            query.watchlist_id,
            limit=query.limit,
            offset=query.offset,
        )
        return ListWatchlistMembersResult(members=members, total=total)


# Re-export for convenience (mirror ``watchlist.py`` style).
__all__ = [
    "AuthorizationError",
    "ListWatchlistMembersQuery",
    "ListWatchlistMembersResult",
    "ListWatchlistMembersUseCase",
]
