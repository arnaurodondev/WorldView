"""Compute overnight P&L for all of a user's holdings (PLAN-0102 W2 T-W2-01).

This use case underpins ``GET /internal/v1/users/{user_id}/portfolio/pnl``.
It does NOT own price data — that lives in S3 (market-data). Instead it
joins live portfolio holdings (read from S1's own DB via the existing
``ReadOnlyUnitOfWork``) with two prices per instrument provided by an
injected ``RecentPricesClient`` port: the **current price** and the
**last close**. The dollar delta + percent delta is computed in Python so
the wire shape is deterministic and the LLM-facing serialisation cannot
silently drop a tail of holdings on a single-instrument upstream error.

Why pull both prices from a single S3 call:
    The existing ``/internal/v1/price/batch`` endpoint already returns
    ``price`` (current/last traded) AND ``price_change`` (delta vs previous
    close). We derive ``last_close = price - price_change`` from that
    single round-trip; one batch HTTP call covers the whole portfolio.

Why the port abstraction:
    Lets unit tests stub deterministic prices without standing up an httpx
    transport (R9 safe-degradation comes from the adapter not raising).
    Mirrors the ``CurrentPriceClient`` pattern in ``get_exposure.py``.

Returns shape (PLAN-0102 W2 §T-W2-01):
    PortfolioPnLDTO {
        user_id, as_of (UTC ISO-8601),
        holdings: [PnLHoldingItem],
        total_overnight_pnl_usd: Decimal,
        total_overnight_pnl_pct: float,  # weighted-average %
        generated_at: datetime,
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from portfolio.domain.errors import UserNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork


@dataclass(frozen=True)
class PnLPriceQuote:
    """Both prices needed for overnight P&L on a single instrument.

    ``current_price`` is the most-recent traded price (S3 ``price`` field on
    the snapshot envelope). ``last_close`` is the previous trading session's
    close, derived from ``price - price_change`` upstream — either value may
    be ``None`` when S3 has no data for the instrument (we degrade per-row
    rather than failing the whole brief).
    """

    current_price: Decimal | None
    last_close: Decimal | None


class RecentPricesClient(Protocol):
    """Port — fetch current price + last close per instrument."""

    async def get_recent_prices(
        self,
        instrument_ids: list[UUID],
    ) -> dict[UUID, PnLPriceQuote]:
        """Return ``{instrument_id: PnLPriceQuote}`` for the supplied ids.

        MUST return an empty dict on any transport error (R9 safe
        degradation). Missing instruments may simply be absent from the
        returned mapping; the use case treats them as zero-P&L rows.
        """
        ...


@dataclass(frozen=True)
class PnLHoldingItem:
    """One row of the response — per-holding overnight P&L."""

    symbol: str | None
    entity_id: UUID | None
    instrument_id: UUID
    qty: Decimal
    last_close_usd: Decimal | None
    current_price_usd: Decimal | None
    overnight_pnl_usd: Decimal
    overnight_pnl_pct: float  # percent vs last close, 0.0 when last close missing


@dataclass(frozen=True)
class PortfolioPnLDTO:
    """Top-level DTO returned by the use case (and serialised by the API)."""

    user_id: UUID
    as_of: datetime
    holdings: list[PnLHoldingItem] = field(default_factory=list)
    total_overnight_pnl_usd: Decimal = Decimal(0)
    total_overnight_pnl_pct: float = 0.0
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class GetPortfolioPnLUseCase:
    """Read-only orchestration: holdings (DB) x recent prices (S3)."""

    def __init__(self, price_client: RecentPricesClient) -> None:
        self._price_client = price_client

    async def execute(
        self,
        user_id: UUID,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> PortfolioPnLDTO:
        # ── 1. Resolve user (404 if missing — same shape as portfolio_context) ─
        user = await uow.users.get(user_id, tenant_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found in tenant {tenant_id}")

        # ── 2. Gather (instrument_id, ticker, entity_id, quantity) per holding ──
        # We aggregate across all portfolios owned by the user; this matches the
        # behaviour of portfolio_context (PORTFOLIO intent context shape).
        holdings_raw: list[tuple[UUID, str | None, UUID | None, Decimal]] = []
        portfolios, _ = await uow.portfolios.list_by_owner(user_id, tenant_id)
        for portfolio in portfolios:
            raw = await uow.holdings.list_by_portfolio(portfolio.id)
            for h in raw:
                instrument = await uow.instruments.get(h.instrument_id)
                holdings_raw.append(
                    (
                        h.instrument_id,
                        instrument.symbol if instrument else None,
                        instrument.entity_id if instrument else None,
                        h.quantity,
                    ),
                )

        # ── 3. Fetch S3 recent prices in ONE batch call ─────────────────────────
        # Use ``set`` to dedupe across portfolios so we don't pay twice for the
        # same ticker held in multiple sub-portfolios.
        unique_instrument_ids = list({iid for (iid, *_rest) in holdings_raw})
        prices: dict[UUID, PnLPriceQuote] = {}
        if unique_instrument_ids:
            prices = await self._price_client.get_recent_prices(unique_instrument_ids)

        # ── 4. Compute per-row P&L + accumulate totals ──────────────────────────
        items: list[PnLHoldingItem] = []
        total_pnl = Decimal(0)
        # For weighted-average percent we accumulate (sum of last_close * qty)
        # as the denominator — this equals the portfolio's overnight cost basis
        # so the percent is "portfolio value % change from yesterday's close".
        total_cost_basis = Decimal(0)
        for instrument_id, symbol, entity_id, qty in holdings_raw:
            quote = prices.get(instrument_id, PnLPriceQuote(current_price=None, last_close=None))
            current = quote.current_price
            last_close = quote.last_close
            if current is not None and last_close is not None:
                pnl_dollar = (current - last_close) * qty
                pct = float((current - last_close) / last_close) if last_close > 0 else 0.0
                total_cost_basis += last_close * qty
            else:
                pnl_dollar = Decimal(0)
                pct = 0.0
            items.append(
                PnLHoldingItem(
                    symbol=symbol,
                    entity_id=entity_id,
                    instrument_id=instrument_id,
                    qty=qty,
                    last_close_usd=last_close,
                    current_price_usd=current,
                    overnight_pnl_usd=pnl_dollar,
                    overnight_pnl_pct=pct,
                ),
            )
            total_pnl += pnl_dollar

        total_pct = float(total_pnl / total_cost_basis) if total_cost_basis > 0 else 0.0

        # ``as_of`` represents the freshness of the *prices* — close to now,
        # but the actual upstream timestamp is per-instrument so we report the
        # request-time clock for simplicity. Callers cache for 60 s.
        now = datetime.now(tz=UTC)
        return PortfolioPnLDTO(
            user_id=user_id,
            as_of=now,
            holdings=items,
            total_overnight_pnl_usd=total_pnl,
            total_overnight_pnl_pct=total_pct,
            generated_at=now,
        )
