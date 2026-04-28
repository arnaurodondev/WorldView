"""Read model use cases for holdings and transactions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.enums import PortfolioKind
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities import Holding, Transaction

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class EnrichedTransaction:
    """Transaction joined with instrument metadata (F-205, QA iter-2).

    Same DTO pattern as ``EnrichedHolding``: keeps the domain entity pure
    while letting the API layer surface ticker/name without a frontend
    workaround. ``ticker`` and ``name`` are nullable for transactions whose
    ``instrument_id`` is missing from the local instruments cache (e.g. a
    pre-existing row whose instrument hasn't synced yet).
    """

    transaction: Transaction
    ticker: str | None
    name: str | None


@dataclass
class EnrichedHolding:
    """Holding with instrument metadata joined from the instruments table.

    WHY a separate DTO (not modifying domain Holding entity): the instruments
    JOIN is an infrastructure concern — the Holding domain entity must not carry
    optional ticker/name fields that only exist when the instrument ref is present.
    This DTO is purely application-layer transport.
    """

    holding: Holding
    ticker: str | None
    name: str | None
    entity_id: UUID | None


class GetHoldingsUseCase:
    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
        *,
        include_closed: bool = False,
    ) -> list[EnrichedHolding]:
        """Return enriched holdings for a portfolio.

        F-303 (QA iter-3 2026-04-28): zero-quantity rows are noise in the
        default UI — they're either fully-sold positions retained for tax
        reporting OR orphans left behind when the F-201 repair script
        zeroed quantities and a sparse broker resync didn't repopulate
        every row. Either way, mixing them with active positions in the
        Holdings table makes a Demo portfolio with 5 active positions
        look like 17 (12 noise rows of "0 shares / $0 / 0%").

        Default behaviour: hide ``quantity == 0`` rows. Pro users can
        opt-in via ``include_closed=True`` (mapped from a ``?include_closed``
        query param at the API layer) when they want to see the historic
        position list — e.g. for tax / audit reporting.

        The filter is applied AFTER aggregation for the ROOT case so a
        position that's net-zero across sub-portfolios (rebalanced flat)
        is also hidden by default — that matches user expectation more
        than "show every leg".
        """
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's holdings")

        # PLAN-0046 Wave 3 / T-46-3-03: ROOT portfolios aggregate the user's
        # other portfolios. Replace the WHERE portfolio_id = X predicate with
        # WHERE portfolio_id IN (sub-portfolios), then collapse by instrument_id
        # with quantity sum + qty-weighted average cost.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(owner_id, tenant_id)
            holdings = await uow.holdings.list_by_portfolio_ids_aggregated_enriched(sub_ids)
        else:
            holdings = await uow.holdings.list_by_portfolio_enriched(portfolio_id)

        # F-303: filter zero-quantity unless the caller opted in.
        # ``Decimal(0)`` == 0 works for both Decimal and int/float quantities
        # because Python's numeric-comparison rules treat them as equal.
        if not include_closed:
            holdings = [eh for eh in holdings if eh.holding.quantity != Decimal(0)]

        return holdings


class ListTransactionsUseCase:
    async def execute(
        self,
        portfolio_id: UUID,
        owner_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EnrichedTransaction], int]:
        """List transactions for a portfolio with instrument enrichment.

        F-205 (QA iter-2): the response now carries ``ticker``/``name`` per
        row. Previously ``TransactionListItem`` left them empty and the
        frontend had to maintain a ``tickerByInstrumentId`` workaround keyed
        on holdings — which broke the moment the user filtered transactions
        before holdings loaded. Mobile/3rd-party clients had no escape at
        all. Now we resolve the instruments at the application layer and
        the API surfaces the enriched fields directly.

        Implementation note: we do NOT add a new ``list_by_instrument_ids``
        method to the InstrumentRepository — instead we read the small
        local instruments cache via the existing ``list_all`` and build an
        in-memory ``{id: ticker/name}`` map. That cache is bounded by the
        tenants' actual instrument footprint (typically <500 rows) so the
        cost is negligible vs. wiring a new port method.
        """
        portfolio = await uow.portfolios.get(portfolio_id, tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found")
        if portfolio.owner_id != owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's transactions")

        # PLAN-0046 Wave 3 / T-46-3-03: ROOT portfolios show the union of
        # transactions across the user's sub-portfolios, sorted newest-first.
        # No aggregation — every original transaction row is preserved.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(owner_id, tenant_id)
            transactions, total = await uow.transactions.list_by_portfolio_ids(
                sub_ids,
                tenant_id,
                limit=limit,
                offset=offset,
            )
        else:
            transactions, total = await uow.transactions.list_by_portfolio(
                portfolio_id,
                tenant_id,
                limit=limit,
                offset=offset,
            )

        # F-205 enrichment — build a single instrument_id → (ticker, name) lookup
        # for every distinct instrument referenced in the page. ``list_all`` is
        # already bounded by the tenant footprint (no separate query per row).
        instrument_ids_in_page = {tx.instrument_id for tx in transactions}
        if instrument_ids_in_page:
            all_instruments, _ = await uow.instruments.list_all(limit=10_000, offset=0)
            lookup: dict[UUID, tuple[str | None, str | None]] = {
                inst.id: (inst.symbol, inst.name) for inst in all_instruments if inst.id in instrument_ids_in_page
            }
        else:
            lookup = {}

        enriched: list[EnrichedTransaction] = []
        for tx in transactions:
            ticker, name = lookup.get(tx.instrument_id, (None, None))
            enriched.append(EnrichedTransaction(transaction=tx, ticker=ticker, name=name))

        return enriched, total
