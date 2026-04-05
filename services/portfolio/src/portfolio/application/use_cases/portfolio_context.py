"""Portfolio context use case — returns holdings and watchlist for S8 PORTFOLIO-intent queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from portfolio.domain.errors import UserNotFoundError

if TYPE_CHECKING:
    from decimal import Decimal
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class HoldingContext:
    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None
    quantity: Decimal
    current_weight: float  # always 0.0 — no price data in S1


@dataclass(frozen=True)
class WatchlistContext:
    ticker: str | None  # always None — WatchlistMember tracks entity_id, not instrument
    entity_id: UUID | None
    canonical_name: str | None  # always None


@dataclass(frozen=True)
class PortfolioContextDTO:
    user_id: UUID
    tenant_id: UUID
    holdings: list[HoldingContext] = field(default_factory=list)
    watchlist: list[WatchlistContext] = field(default_factory=list)
    total_positions: int = 0


class PortfolioContextUseCase:
    """Read-only use case: fetch holdings + watchlist for a user, for S8 context injection."""

    async def execute(self, user_id: UUID, tenant_id: UUID, uow: UnitOfWork) -> PortfolioContextDTO:
        user = await uow.users.get(user_id, tenant_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found in tenant {tenant_id}")

        # --- Holdings ---
        holdings: list[HoldingContext] = []
        portfolios, _ = await uow.portfolios.list_by_owner(user_id, tenant_id)
        for portfolio in portfolios:
            raw_holdings = await uow.holdings.list_by_portfolio(portfolio.id)
            for h in raw_holdings:
                instrument = await uow.instruments.get(h.instrument_id)
                holdings.append(
                    HoldingContext(
                        ticker=instrument.symbol if instrument else None,
                        entity_id=instrument.entity_id if instrument else None,
                        canonical_name=instrument.name if instrument else None,
                        quantity=h.quantity,
                        current_weight=0.0,
                    )
                )

        # --- Watchlist (deduplicated by entity_id) ---
        seen_entity_ids: set[UUID] = set()
        watchlist: list[WatchlistContext] = []
        all_watchlists = await uow.watchlists.list_by_user(user_id, tenant_id)
        for wl in all_watchlists:
            if not wl.is_active():
                continue
            members = await uow.watchlist_members.list_by_watchlist(wl.id)
            for m in members:
                if m.entity_id in seen_entity_ids:
                    continue
                seen_entity_ids.add(m.entity_id)
                watchlist.append(
                    WatchlistContext(
                        ticker=None,
                        entity_id=m.entity_id,
                        canonical_name=None,
                    )
                )

        return PortfolioContextDTO(
            user_id=user_id,
            tenant_id=tenant_id,
            holdings=holdings,
            watchlist=watchlist,
            total_positions=len(holdings),
        )
