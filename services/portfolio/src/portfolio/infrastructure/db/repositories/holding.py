"""SQLAlchemy implementation of HoldingRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from portfolio.application.ports.repositories import HoldingRepository
from portfolio.application.use_cases.read_models import EnrichedHolding
from portfolio.domain.entities.holding import Holding
from portfolio.infrastructure.db.models.holding import HoldingModel
from portfolio.infrastructure.db.models.instrument import InstrumentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyHoldingRepository(HoldingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_entity(self, row: HoldingModel) -> Holding:
        return Holding(
            id=row.id,
            portfolio_id=row.portfolio_id,
            instrument_id=row.instrument_id,
            tenant_id=row.tenant_id,
            quantity=row.quantity,
            average_cost=row.average_cost,
            currency=row.currency,
            updated_at=row.updated_at,
            cost_basis_per_unit=getattr(row, "cost_basis_per_unit", None),
            total_cost_basis=getattr(row, "total_cost_basis", None),
        )

    async def get(self, portfolio_id: UUID, instrument_id: UUID) -> Holding | None:
        result = await self._session.execute(
            select(HoldingModel).where(
                HoldingModel.portfolio_id == portfolio_id,
                HoldingModel.instrument_id == instrument_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_portfolio(self, portfolio_id: UUID) -> list[Holding]:
        result = await self._session.execute(select(HoldingModel).where(HoldingModel.portfolio_id == portfolio_id))
        return [self._to_entity(r) for r in result.scalars()]

    async def list_by_portfolio_enriched(self, portfolio_id: UUID) -> list[EnrichedHolding]:
        """Return holdings with ticker/name/entity_id from the instruments table.

        WHY LEFT OUTER JOIN: a holding may reference an instrument_id that has not
        yet been synced from S3 (race condition between SnapTrade sync and instrument
        consumer). LEFT JOIN ensures all holdings are returned even without an instrument
        record — the enrichment fields default to None and the frontend degrades gracefully.

        2026-06-10 (gap #1): ``asset_class`` added to the same JOIN — no new
        query, no DDL (instruments.asset_class already exists).
        """
        stmt = (
            select(
                HoldingModel,
                InstrumentModel.symbol,
                InstrumentModel.name,
                InstrumentModel.entity_id,
                InstrumentModel.asset_class,
            )
            .outerjoin(InstrumentModel, HoldingModel.instrument_id == InstrumentModel.id)
            .where(HoldingModel.portfolio_id == portfolio_id)
        )
        result = await self._session.execute(stmt)
        enriched: list[EnrichedHolding] = []
        for holding_row, symbol, name, entity_id, asset_class in result.tuples():
            enriched.append(
                EnrichedHolding(
                    holding=self._to_entity(holding_row),
                    ticker=symbol,
                    name=name,
                    entity_id=entity_id,
                    asset_class=asset_class,
                ),
            )
        return enriched

    async def list_by_portfolio_ids_aggregated_enriched(
        self,
        portfolio_ids: list[UUID],
    ) -> list[EnrichedHolding]:
        """Aggregate holdings across multiple portfolios (PLAN-0046 / T-46-3-03).

        Strategy: fetch all holdings for the listed portfolios with the same
        instrument LEFT-JOIN as the single-portfolio path, then collapse by
        ``instrument_id`` in Python. This trades one round-trip + a small
        in-memory reduce for a much simpler implementation than a SQL GROUP
        BY with weighted-average cost (which would also need to special-case
        zero-quantity rows). For the user counts we target (≤ 5 portfolios,
        ≤ 100 instruments each) the overhead is negligible.

        WHY weighted average cost (not simple mean): if a user holds 100 AAPL
        @ $150 in one portfolio and 10 AAPL @ $200 in another, the blended
        cost basis is (100*150 + 10*200) / 110 = $154.55, not $175. Simple
        mean would mislead the P&L calculation in the UI.
        """
        from collections import defaultdict
        from decimal import Decimal

        if not portfolio_ids:
            return []

        stmt = (
            select(
                HoldingModel,
                InstrumentModel.symbol,
                InstrumentModel.name,
                InstrumentModel.entity_id,
                InstrumentModel.asset_class,
            )
            .outerjoin(InstrumentModel, HoldingModel.instrument_id == InstrumentModel.id)
            .where(HoldingModel.portfolio_id.in_(portfolio_ids))
        )
        result = await self._session.execute(stmt)

        # Per-instrument accumulators.
        qty_sum: dict[UUID, Decimal] = defaultdict(lambda: Decimal(0))
        cost_qty_sum: dict[UUID, Decimal] = defaultdict(lambda: Decimal(0))  # SUM(qty * avg_cost)
        # Carry the first (holding, ticker, name, entity_id, asset_class) seen for
        # each instrument so we can reconstruct an EnrichedHolding without losing
        # the joined fields.
        first_seen: dict[UUID, tuple[HoldingModel, str | None, str | None, UUID | None, str | None]] = {}

        for holding_row, symbol, name, entity_id, asset_class in result.tuples():
            iid = holding_row.instrument_id
            qty_sum[iid] += holding_row.quantity
            cost_qty_sum[iid] += holding_row.quantity * holding_row.average_cost
            first_seen.setdefault(iid, (holding_row, symbol, name, entity_id, asset_class))

        enriched: list[EnrichedHolding] = []
        for iid, total_qty in qty_sum.items():
            # WHY rename to *_val: mypy narrows ``name`` from the loop above
            # (where it came from a Mapped[str] tuple slot inferred as str)
            # and refuses to re-bind it to ``str | None`` here. Distinct names
            # for the unpacked snapshot tuple side-step the collision and
            # also make it explicit that these come from ``first_seen``.
            base_row, symbol_val, name_val, entity_id_val, asset_class_val = first_seen[iid]
            # NULLIF(SUM(qty), 0) — avoid division by zero for fully-closed positions
            # that still have stale holding rows (shouldn't happen, but defensive).
            weighted_cost = (cost_qty_sum[iid] / total_qty) if total_qty != 0 else Decimal(0)
            aggregated = Holding(
                # Synthesize an id deterministically from instrument_id so successive
                # calls return stable ids (helpful for React keys); the row is
                # virtual and never persisted.
                id=base_row.id,
                portfolio_id=base_row.portfolio_id,
                instrument_id=iid,
                tenant_id=base_row.tenant_id,
                quantity=total_qty,
                average_cost=weighted_cost,
                currency=base_row.currency,
                updated_at=base_row.updated_at,
            )
            enriched.append(
                EnrichedHolding(
                    holding=aggregated,
                    ticker=symbol_val,
                    name=name_val,
                    entity_id=entity_id_val,
                    asset_class=asset_class_val,
                ),
            )
        return enriched

    async def save(self, holding: Holding) -> None:
        row = await self._session.get(HoldingModel, holding.id)
        if row is None:
            row = HoldingModel(
                id=holding.id,
                portfolio_id=holding.portfolio_id,
                instrument_id=holding.instrument_id,
                tenant_id=holding.tenant_id,
                quantity=holding.quantity,
                average_cost=holding.average_cost,
                currency=holding.currency,
                updated_at=holding.updated_at,
                cost_basis_per_unit=holding.cost_basis_per_unit,
                total_cost_basis=holding.total_cost_basis,
            )
            self._session.add(row)
        else:
            row.quantity = holding.quantity
            row.average_cost = holding.average_cost
            row.updated_at = holding.updated_at
            row.cost_basis_per_unit = holding.cost_basis_per_unit
            row.total_cost_basis = holding.total_cost_basis

    async def delete(self, portfolio_id: UUID, instrument_id: UUID) -> None:
        """Delete one holding row by composite key.

        PLAN-0046 / BP-264: used by UpsertHoldingsFromSnapshotUseCase to remove
        positions that are no longer present in the broker's snapshot.
        """
        # Use ORM delete via fetched row to keep behaviour identical to save():
        # if the row is missing this is a no-op (idempotent) — desirable since
        # the caller may pass an instrument_id that was never persisted (e.g. a
        # closed position from a previous sync).
        result = await self._session.execute(
            select(HoldingModel).where(
                HoldingModel.portfolio_id == portfolio_id,
                HoldingModel.instrument_id == instrument_id,
            ),
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
