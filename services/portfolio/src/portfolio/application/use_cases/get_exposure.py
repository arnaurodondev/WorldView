"""Compute current portfolio exposure (invested / cash / leverage).

PLAN-0046 Wave 5 / T-46-5-02.

Frontend uses this for the "Exposure Breakdown" panel on the portfolio
page. Unlike ``ComputePortfolioValueUseCase`` (which writes a snapshot
for a given date), this use case is purely read-only and operates on
*current* prices.

Inputs:

* ``portfolio_id`` — may be a ROOT portfolio; we fan out to
  non-root sub-portfolios via the same pattern as ``GetHoldingsUseCase``
  so the exposure number aggregates the user's whole book.
* A ``CurrentPriceClient`` port supplies current prices via batch
  lookup. The production implementation hits S3
  ``POST /api/v1/quotes/batch`` (R9 — REST only).

Outputs (all ``Decimal`` so the API can serialise as a string):

* ``invested = sum(quantity * current_price)`` (uses ``average_cost`` as a
  graceful fallback when the price client returns no quote for an
  instrument — keeps the headline non-zero rather than dropping the
  whole position).
* ``cash = 0`` (v1 — broker cash is not tracked yet).
* ``gross_exposure_pct = invested / (invested + cash)`` — for v1 this
  is always 1.0 when ``invested > 0`` and 0.0 otherwise. We still
  compute it explicitly so the field shape is forward-compatible
  with v2 cash support.
* ``net_exposure_pct`` — same as gross for v1 (no shorts modelled).
* ``leverage = invested / total_cost`` — a simple "how much of my
  cost basis is currently working for me" metric. Returns ``1.0``
  when ``total_cost == 0`` to avoid division-by-zero (an empty
  portfolio is by definition unleveraged).

Empty portfolios return all zeros (NOT NaN). The frontend depends on
this — see ``ExposureBreakdown.tsx`` empty-state behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from portfolio.domain.enums import PortfolioKind
from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork


class CurrentPriceClient(Protocol):
    """Port: fetch current (latest) prices for a batch of instruments.

    Production impl calls S3 ``POST /api/v1/quotes/batch`` and returns a
    ``{instrument_id: price}`` dict. Missing instruments are simply
    absent from the result — never present with a zero/NaN value, so
    callers can use ``dict.get`` and a fallback.
    """

    async def get_current_prices(
        self,
        instrument_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        """Return current prices keyed by instrument_id; missing keys are omitted."""
        ...


@dataclass(frozen=True)
class ExposureResult:
    """Output DTO. All numbers are ``Decimal`` for API serialisation parity.

    ``prices_stale`` (F-016): True when the price client returned no quotes
    for one or more instruments and we fell back to ``average_cost``. The
    caller (and ultimately the frontend) uses this to render a "stale"
    badge so the user knows ``invested`` reflects cost-basis-as-of-acquisition,
    not live market value.

    ``prices_as_of`` is left as None for v1 — the upstream ``CurrentPriceClient``
    port doesn't yet surface a per-quote timestamp. The field is reserved
    so the frontend can rely on a stable shape when v2 wires it up.

    ``buying_power`` (2026-06-10 frontend-enhancement sprint, gap #5):
    v1 semantics are ``buying_power == cash`` — margin is NOT modelled, so
    available buying power is exactly the uninvested cash balance. The field
    exists so the frontend stops inferring it client-side; when margin
    support lands, only this computation changes (``cash + margin_available``)
    and the wire contract stays stable.
    """

    invested: Decimal
    cash: Decimal
    gross_exposure_pct: Decimal
    net_exposure_pct: Decimal
    leverage: Decimal
    prices_stale: bool = False
    prices_as_of: datetime | None = None
    # v1: always equals ``cash`` (no margin modelling). Defaulted so existing
    # constructor call sites stay valid — forward-compatible add (R11).
    buying_power: Decimal = Decimal(0)


@dataclass(frozen=True)
class GetExposureQuery:
    portfolio_id: UUID
    owner_id: UUID
    tenant_id: UUID


class GetExposureUseCase:
    """Compute the current exposure breakdown for a portfolio."""

    def __init__(self, price_client: CurrentPriceClient) -> None:
        self._price_client = price_client

    async def execute(
        self,
        query: GetExposureQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> ExposureResult:
        portfolio = await uow.portfolios.get(query.portfolio_id, query.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {query.portfolio_id} not found")
        if portfolio.owner_id != query.owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's exposure")

        # ROOT fan-out: same pattern as GetHoldingsUseCase (read_models.py).
        # ROOT aggregates all non-root active portfolios for the same owner.
        if portfolio.kind == PortfolioKind.ROOT:
            sub_ids = await uow.portfolios.list_non_root_active_ids_by_owner(
                query.owner_id,
                query.tenant_id,
            )
            enriched = await uow.holdings.list_by_portfolio_ids_aggregated_enriched(sub_ids)
            holdings = [eh.holding for eh in enriched]
        else:
            holdings = await uow.holdings.list_by_portfolio(query.portfolio_id)

        # F-203 (QA iter-2): treat "all-zero quantity" the same as the no-holdings
        # branch. The earlier code only checked ``not holdings``, so a portfolio
        # with 17 zero-quantity rows (the F-201 incident state) still walked the
        # quote-fetch loop, marked itself ``prices_stale=True`` because no quote
        # came back for the orphan rows, and rendered a yellow "Prices stale"
        # badge over a $0 exposure card — semantically nonsensical (no positions
        # to be stale). ``sum(quantity) == 0`` covers both cases cleanly.
        total_quantity = sum((h.quantity for h in holdings), start=Decimal(0))
        if not holdings or total_quantity == 0:
            zero = Decimal(0)
            # An empty (or zero-quantity) portfolio is *trivially* not stale —
            # there are no prices to be missing. Returning False here keeps the
            # UI from rendering a "stale" badge over a blank exposure card.
            return ExposureResult(
                invested=zero,
                cash=zero,
                gross_exposure_pct=zero,
                net_exposure_pct=zero,
                leverage=zero,
                prices_stale=False,
                prices_as_of=None,
                # v1: buying_power == cash (no margin) — see dataclass docstring.
                buying_power=zero,
            )

        # Fetch current prices for ALL distinct instruments in a single
        # round-trip (avoid N+1). The port returns a dict; missing keys
        # mean the price client had no quote for that instrument.
        instrument_ids = [h.instrument_id for h in holdings]
        prices = await self._price_client.get_current_prices(instrument_ids)

        invested = Decimal(0)
        total_cost = Decimal(0)
        # F-016: detect price staleness. If ANY holding falls back to
        # ``average_cost`` because the price client returned no quote,
        # we mark the entire response as stale so the frontend can show
        # a yellow "Prices stale" badge. Intentional all-or-nothing flag
        # (vs per-holding) because the gross headline aggregates over
        # the whole book — a single missing quote is enough to make the
        # number partially synthetic.
        stale = False
        for h in holdings:
            total_cost += h.quantity * h.average_cost
            # WHY fall back to average_cost on missing price: the alternative
            # is to drop the position from the exposure number, which would
            # under-report the true "gross at-risk capital" — exactly the
            # opposite of what a portfolio manager wants from an exposure
            # readout. Cost basis is a conservative proxy when no live
            # quote is available.
            quote = prices.get(h.instrument_id)
            if quote is None:
                stale = True
                price = h.average_cost
            else:
                price = quote
            invested += h.quantity * price

        cash = Decimal(0)  # v1 — broker cash not tracked.
        denom = invested + cash
        gross_exposure_pct = (invested / denom) if denom > 0 else Decimal(0)
        # No short positions in v1, so net == gross. Kept as a separate
        # field so the API contract stays stable when shorts are added.
        net_exposure_pct = gross_exposure_pct
        # leverage = invested / total_cost; 1.0 when no cost basis (empty
        # but in this branch we already returned all zeros for empty —
        # so total_cost > 0 by construction here, but defensive guard is cheap).
        leverage = (invested / total_cost) if total_cost > 0 else Decimal(0)

        return ExposureResult(
            invested=invested,
            cash=cash,
            gross_exposure_pct=gross_exposure_pct,
            net_exposure_pct=net_exposure_pct,
            leverage=leverage,
            prices_stale=stale,
            # v1 leaves prices_as_of=None — the port doesn't yet surface
            # a per-quote timestamp. See dataclass docstring.
            prices_as_of=None,
            # v1: buying_power == cash (no margin) — see dataclass docstring.
            buying_power=cash,
        )
